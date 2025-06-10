"""
gemini_api.py
"""

import base64
import json
from typing import List, Dict, Optional, Tuple

import requests


# =============================================================================
# 配置常量 - Configuration Constants
# =============================================================================

# API 端点配置 - API Endpoint Configuration
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com"
DEFAULT_API_VERSION = "v1beta"
DEFAULT_TIMEOUT = 60

# 默认模型名称 - Default Model Names
DEFAULT_TEXT_MODEL = "gemini-2.5-flash-preview-05-20"          # 文本生成和对话
DEFAULT_VISION_MODEL = "gemini-2.5-flash-preview-05-20"       # 多模态输入（视觉+文本）
DEFAULT_IMAGE_GEN_MODEL = "gemini-2.0-flash-preview-image-generation"  # 图像生成（多模态输出）
DEFAULT_IMAGEN_MODEL = "imagen-3.0-generate-002"               # Imagen 原生图像生成
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"                 # 文本嵌入

# 图像处理默认参数 - Image Processing Default Parameters
DEFAULT_MIME_TYPE = "image/png"
DEFAULT_SAMPLE_COUNT = 1
DEFAULT_ASPECT_RATIO = "1:1"
DEFAULT_PERSON_GENERATION = "allow_adult"

# 嵌入默认参数 - Embedding Default Parameters
DEFAULT_TASK_TYPE = "RETRIEVAL_DOCUMENT"

# 提示：
# 例如像这个 gemini-2.5-flash-preview-05-20 模型有一个内部的"思考"过程，会消耗大量的token，而 maxOutputTokens 限制包括了这些思考token。解决方案是要么不设置 maxOutputTokens 限制，要么设置一个非常大的值来容纳思考过程，避免出现问题。


class GeminiAPI:
    """Minimal REST client for Google's Gemini API (v1beta)."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        api_version: str = DEFAULT_API_VERSION,
        default_timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.api_version = api_version
        self.default_timeout = default_timeout

    # ---------------------------------------------------------------------
    # Low‑level helpers
    # ---------------------------------------------------------------------
    def _url(self, path: str) -> str:
        """Return full URL with API key query parm attached."""
        return f"{self.endpoint}/{self.api_version}/{path}?key={self.api_key}"

    def _post(self, path: str, payload: dict, *, timeout: Optional[int] = None) -> dict:
        """HTTP POST with JSON payload and robust error handling."""
        url = self._url(path)
        t = timeout or self.default_timeout
        resp = requests.post(url, json=payload, timeout=t)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Gemini API error {resp.status_code} – {resp.text[:200]}"
            ) from exc
        return resp.json()

    # ---------------------------------------------------------------------
    # Core generateContent wrapper
    # ---------------------------------------------------------------------
    def _generate_content(
        self,
        model: str,
        contents: List[dict],
        *,
        system_instruction: Optional[dict] = None,
        generation_config: Optional[dict] = None,
        tools: Optional[list] = None,
        safety_settings: Optional[list] = None,
        stream: bool = False,
    ) -> dict:
        """Generic wrapper around `models/*:generateContent`."""
        payload: Dict = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if generation_config:
            payload["generation_config"] = generation_config
        if tools:
            payload["tools"] = tools
        if safety_settings:
            payload["safety_settings"] = safety_settings
        if stream:
            payload["stream"] = True

        path = f"models/{model}:generateContent"
        return self._post(path, payload)

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------
    def single_turn(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """One‑shot prompt."""
        contents = [{"role": "user", "parts": [{"text": text}]}]
        return self._generate_content(
            model, contents, generation_config=generation_config
        )
    
    # ---------------------- JSON-forced single-turn ----------------------
    def single_turn_json(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        schema: Optional[dict] = None,
        generation_config: Optional[dict] = None,
    ) -> dict:
        # ① 基础 contents
        contents = [{"role": "user", "parts": [{"text": text}]}]

        # ② 构造 / 合并 generation_config
        gen_cfg = {"response_mime_type": "application/json"} # 强制 JSON
        if generation_config:
            gen_cfg.update(generation_config)
        if schema:
            gen_cfg["response_schema"] = schema

        # ③ 调用底层生成
        return self._generate_content(
            model, contents, generation_config=gen_cfg
        )

    # ---------------------------- ChatSession ----------------------------
    class ChatSession:
        """Stateful multi‑turn chat helper returned by :meth:`start_chat`."""

        def __init__(
            self,
            _parent: "GeminiAPI",
            model: str,
            system_prompt: str = "",
            generation_config: Optional[dict] = None,
        ):
            self._parent = _parent
            self.model = model
            self._history: List[dict] = []
            self._gen_cfg = generation_config or {}
            # Store system prompt separately, don't add to history yet.
            self._system_instruction = {"parts": [{"text": system_prompt}]} if system_prompt else None

        @property
        def history(self) -> List[dict]:
            # For user visibility, we can prepend the system prompt to the history
            if self._system_instruction:
                # Create a "system" role entry for display purposes only
                display_history = [{"role": "system", "parts": self._system_instruction["parts"]}]
                display_history.extend(self._history)
                return display_history
            return self._history

        def send(self, text: str, **gen_cfg) -> dict:
            """Send user message; returns model candidate JSON."""
            self._history.append({"role": "user", "parts": [{"text": text}]})
            merged_cfg = {**self._gen_cfg, **(gen_cfg.get("generation_config") or {})}

            resp = self._parent._generate_content(
                self.model,
                self._history,
                system_instruction=self._system_instruction,
                generation_config=merged_cfg
            )

            # Safely extract and persist assistant reply into history
            if (resp.get("candidates") and
                resp["candidates"][0].get("content") and
                resp["candidates"][0]["content"].get("parts")):
                parts = resp["candidates"][0]["content"]["parts"]
                self._history.append({"role": "model", "parts": parts})
            else:
                # Handle cases where response doesn't contain expected parts
                # This can happen when generation is cut off due to safety filters,
                # token limits, or other API constraints
                finish_reason = resp.get("candidates", [{}])[0].get("finishReason", "UNKNOWN")
                error_parts = [{"text": f"[Response incomplete - finish reason: {finish_reason}]"}]
                self._history.append({"role": "model", "parts": error_parts})

            return resp

    def start_chat(
        self,
        model: str = DEFAULT_TEXT_MODEL,
        *,
        system_prompt: str = "",
        generation_config: Optional[dict] = None,
    ) -> "GeminiAPI.ChatSession":
        """Return a stateful :class:`ChatSession`."""
        return self.ChatSession(
            self, model, system_prompt=system_prompt, generation_config=generation_config
        )

    # --------------------------- Multimodality ---------------------------
    def multimodal_input(
        self,
        *,
        model: str = DEFAULT_VISION_MODEL,
        text: str = "",
        image_path: Optional[str] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """Text + (optional) image → text."""
        parts: List[dict] = []
        if text:
            parts.append({"text": text})
        if image_path:
            with open(image_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            parts.append({"inline_data": {"mime_type": mime_type, "data": data}})

        contents = [{"role": "user", "parts": parts}]
        return self._generate_content(
            model, contents, generation_config=generation_config
        )

    def multimodal_in_out(
        self,
        *,
        prompt: str,
        model: str = DEFAULT_IMAGE_GEN_MODEL,
        reference_images: Optional[List[str]] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> Tuple[List[str], dict]:
        """Prompt (+ reference images) → generated image(s) + raw response.

        Returns
        -------
        images : List[str]
            List of base64‑encoded image strings.
        resp : dict
            Raw JSON response from the API.
        """
        parts: List[dict] = [{"text": prompt}]
        reference_images = reference_images or []
        for img in reference_images:
            with open(img, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            parts.append({"inline_data": {"mime_type": mime_type, "data": b64}})

        # Add responseModalities to generation_config, crucial for image generation
        # Add responseModalities to generation_config, crucial for image generation
        gen_cfg = generation_config or {}
        gen_cfg["responseModalities"] = ["TEXT", "IMAGE"]

        contents = [{"role": "user", "parts": parts}]
        resp = self._generate_content(
            model, contents, generation_config=gen_cfg
        )

        imgs: List[str] = []
        # Safely extract images, handling cases like RECITATION where no content is returned.
        if resp.get("candidates"):
            candidate = resp["candidates"][0]
            if candidate.get("finishReason") == "STOP" and candidate.get("content", {}).get("parts"):
                for part in candidate["content"]["parts"]:
                    inline = part.get("inline_data")
                    if inline and inline.get("mime_type", "").startswith("image/"):
                        imgs.append(inline["data"])
        return imgs, resp

    def generate_image(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGEN_MODEL,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        person_generation: str = DEFAULT_PERSON_GENERATION,
    ) -> List[str]:
        """Generate images using Imagen 3.

        Note: Imagen models only support English prompts.
        """
        path = f"models/{model}:predict"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "numberOfImages": sample_count,
                "aspectRatio": aspect_ratio,
                "personGeneration": person_generation,
            },
        }
        resp = self._post(path, payload)

        # Extract base64 image data from the response
        images_base64 = []
        if "predictions" in resp:
            for prediction in resp["predictions"]:
                if "bytesBase64Encoded" in prediction:
                    images_base64.append(prediction["bytesBase64Encoded"])
        return images_base64

    # ------------------------------ Misc ---------------------------------
    def embed_text(
        self,
        text: str,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        task_type: str = DEFAULT_TASK_TYPE,
    ) -> List[float]:
        """Return embedding vector for *text*."""
        payload = {
            "content": {"parts": [{"text": text}]},
            "task_type": task_type,
        }
        path = f"models/{model}:embedContent"
        resp = self._post(path, payload)
        return resp["embedding"]["values"]

    def list_models(self) -> dict:
        """GET /models – list available models."""
        url = self._url("models")
        resp = requests.get(url, timeout=self.default_timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Gemini API error {resp.status_code} – {resp.text[:200]}"
            ) from exc
        return resp.json()