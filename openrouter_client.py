"""
openrouter_client.py
--------------------

A lightweight Python client for OpenRouter's REST API without depending on the
`openai` SDK.  It supports:

1. One-shot chat completions (`chat_once`)
2. Stateful multi-turn conversations (`chat`)
3. Multi-modal inputs with image/PDF support (`chat_multimodal`)
4. Streaming responses (`stream_chat`)
5. Utility helpers (`list_models`, `get_generation`, `encode_image_base64`)
6. Automatic retry & simple cost accounting
7. Force-JSON output helpers (`chat_json_once`, `chat_json`)

Default model: ``google/gemini-2.5-flash-preview-05-20``

Example
-------
```python
from openrouter_client import OpenRouterClient

client = OpenRouterClient("<OPENROUTER_API_KEY>")

# 强制 JSON 输出
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"}
    },
    "required": ["title", "summary"]
}

obj = client.chat_json_once("用 JSON 格式返回新闻标题和摘要", schema=schema)
print(obj["title"], obj["summary"])
```
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

__all__ = ["OpenRouterClient", "ChatError"]


class ChatError(RuntimeError):
    """Raised when the OpenRouter API returns an error response."""


@dataclass
class OpenRouterClient:
    api_key: str
    referer: Optional[str] = None
    title: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "google/gemini-2.5-flash-preview-05-20"
    timeout: int = 60
    max_retries: int = 3
    backoff_factor: float = 0.5
    proxies: Optional[Dict[str, str]] = None
    _history: List[Dict[str, Any]] = field(default_factory=list, init=False)
    last_request_payload: Optional[Dict[str, Any]] = field(default=None, init=False)
    last_response_payload: Optional[Dict[str, Any]] = field(default=None, init=False)
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        retries = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST", "GET", "PATCH", "DELETE"]),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retries))
        self._session.headers.update(self._build_headers())
        if self.proxies:
            self._session.proxies.update(self.proxies)

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #

    def chat_once(self, prompt: str, model: Optional[str] = None, **params: Any) -> str:
        """Single-turn chat; returns assistant content."""
        messages = [{"role": "user", "content": prompt}]
        result = self._chat(messages, model=model, **params)
        return result["choices"][0]["message"]["content"]

    # Stateful chat
    def add_user(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_system(self, content: str) -> None:
        self._history.append({"role": "system", "content": content})

    def chat(self, model: Optional[str] = None, **params: Any) -> str:
        if not self._history:
            raise ValueError("No messages in history; call add_user/add_system first.")
        result = self._chat(self._history, model=model, **params)
        assistant_msg = result["choices"][0]["message"]
        self._history.append(assistant_msg)
        return assistant_msg["content"]

    # Multi‑modal
    def chat_multimodal(
        self,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        image_paths: Optional[List[str]] = None,
        model: Optional[str] = None,
        **params: Any,
    ) -> str:
        content = [{"type": "text", "text": prompt}]
        for url in image_urls or []:
            content.append({"type": "image_url", "image_url": {"url": url}})
        for path in image_paths or []:
            data_url = self.encode_image_base64(path)
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        messages = [{"role": "user", "content": content}]
        result = self._chat(messages, model=model, **params)
        return result["choices"][0]["message"]["content"]

    # Streaming
    def stream_chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        **params: Any,
    ) -> Generator[str, None, None]:
        messages = [{"role": "user", "content": prompt}]
        payload = self._build_payload(messages, model=model, stream=True, **params)
        response = self._post("/chat/completions", payload, stream=True)
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data_str = line[len("data: "):].strip()
                # Skip [DONE] marker
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    if data.get("choices"):
                        delta = data["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                except json.JSONDecodeError:
                    # Skip malformed JSON lines
                    continue

    # NEW: Force-JSON helper
    def chat_json_once(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """Single-turn chat that **guarantees** a JSON object reply.

        If parsing fails, `ChatError` is raised.
        Optionally pass a JSON schema (dict) which will be appended to the
        `response_format` field (supported by OpenAI-compatible APIs).
        """
        rf: Dict[str, Any] = {"type": "json_object"}
        if schema is not None:
            rf["schema"] = schema
        params.setdefault("response_format", rf)

        messages = [{"role": "user", "content": prompt}]
        result = self._chat(messages, model=model, **params)
        content = result["choices"][0]["message"]["content"]
        try:
            parsed_json = json.loads(content)
            if not isinstance(parsed_json, dict):
                raise ChatError(
                    f"Model did not return a JSON object (dict). Got {type(parsed_json).__name__} instead. "
                    f"Raw response: {content}"
                )
            return parsed_json
        except json.JSONDecodeError as exc:
            raise ChatError(
                "Model did not return valid JSON. Raw response: " + content
            ) from exc

    def chat_json(
        self,
        *,
        model: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """Stateful, multi-turn chat that **guarantees** a JSON object reply.

        Uses the internal message history. Call `add_user`/`add_system` first.
        If parsing fails, `ChatError` is raised.
        Optionally pass a JSON schema (dict) for structured output.
        """
        if not self._history:
            raise ValueError("No messages in history; call add_user/add_system first.")

        rf: Dict[str, Any] = {"type": "json_object"}
        if schema is not None:
            rf["schema"] = schema
        params.setdefault("response_format", rf)

        result = self._chat(self._history, model=model, **params)
        assistant_msg = result["choices"][0]["message"]
        content = assistant_msg["content"]

        self._history.append(assistant_msg)

        try:
            parsed_json = json.loads(content)
            if not isinstance(parsed_json, dict):
                raise ChatError(
                    f"Model did not return a JSON object (dict). Got {type(parsed_json).__name__} instead. "
                    f"Raw response: {content}"
                )
            return parsed_json
        except json.JSONDecodeError as exc:
            raise ChatError(
                "Model did not return valid JSON. Raw response: " + content
            ) from exc

    # Utilities
    def list_models(self) -> List[str]:
        resp = self._session.get(f"{self.base_url}/models", timeout=self.timeout)
        self._handle_error(resp)
        data = resp.json()
        # OpenRouter API returns models in a 'data' field
        if isinstance(data, dict) and 'data' in data:
            return [m["id"] for m in data["data"]]
        # Fallback for direct list response
        elif isinstance(data, list):
            return [m["id"] for m in data]
        else:
            raise ChatError(f"Unexpected API response format: {type(data)}")

    def get_generation(self, generation_id: str) -> Dict[str, Any]:
        resp = self._session.get(
            f"{self.base_url}/generations/{generation_id}", timeout=self.timeout
        )
        self._handle_error(resp)
        return resp.json()

    # Low‑level
    def _chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        stream: bool = False,
        **params: Any,
    ) -> Dict[str, Any]:
        payload = self._build_payload(messages, model=model, stream=stream, **params)
        resp = self._post("/chat/completions", payload, stream=False)
        response_data = resp.json()
        # 保存响应用于调试
        self.last_response_payload = response_data
        return response_data

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        stream: bool = False,
        **params: Any,
    ) -> Dict[str, Any]:
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": stream,
            **params,
        }
        self.last_request_payload = payload
        return payload

    def _post(self, path: str, payload: Dict[str, Any], *, stream: bool = False) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.post(url, json=payload, timeout=self.timeout, stream=stream)
        if not stream:
            self._handle_error(resp)
        return resp

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title
        return headers

    def _handle_error(self, resp: requests.Response) -> None:
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except json.JSONDecodeError:
                err = resp.text
            logging.error("OpenRouter API error %s: %s", resp.status_code, err)
            raise ChatError(f"{resp.status_code}: {err}")

    # Static helpers
    @staticmethod
    def encode_image_base64(path: str) -> str:
        mime = "image/jpeg" if path.lower().endswith(("jpg", "jpeg")) else "image/png"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"

    # Cost estimator
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, price_per_million: float) -> float:
        return price_per_million * (prompt_tokens + completion_tokens) / 1_000_000