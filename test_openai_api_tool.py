import copy
import base64

from config import config, LLMProvider
from llm_service import llm_service
from openai_api_tool import OpenAIAPITool


class _FakeOpenAIAPITool(OpenAIAPITool):
    def __init__(self, responses, base_url="https://api.xiaomimimo.com/v1"):
        super().__init__(api_key="test-key", base_url=base_url, default_model="mimo-v2.5-pro")
        self._responses = [copy.deepcopy(response) for response in responses]
        self.captured_payloads = []

    def _make_request(self, endpoint, data, method="POST", return_json=True):
        self.last_request_payload = copy.deepcopy(data)
        self.captured_payloads.append(copy.deepcopy(data))
        response = copy.deepcopy(self._responses.pop(0))
        self.last_response_payload = copy.deepcopy(response)
        return response


def test_mimo_uses_max_completion_tokens_for_chat_completions():
    client = _FakeOpenAIAPITool(
        responses=[
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        }
                    }
                ]
            }
        ]
    )

    assistant_message = client.single_chat_message("hello", max_tokens=321)

    assert assistant_message["content"] == "ok"
    assert client.last_request_payload["max_completion_tokens"] == 321
    assert "max_tokens" not in client.last_request_payload


def test_mimo_tts_chat_returns_audio_bytes_and_uses_assistant_text():
    audio_bytes = b"RIFF-test-audio"
    client = _FakeOpenAIAPITool(
        responses=[
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "audio": {
                                "data": base64.b64encode(audio_bytes).decode("ascii"),
                            },
                        }
                    }
                ]
            }
        ]
    )

    result = client.mimo_text_to_speech_chat(
        text="地牢入口已经打开。",
        model="mimo-v2.5-tts",
        voice="mimo_default",
        response_format="wav",
        style_hint="用GM旁白语气朗读。",
    )

    assert result == audio_bytes
    assert client.last_request_payload["model"] == "mimo-v2.5-tts"
    assert client.last_request_payload["audio"] == {
        "format": "wav",
        "voice": "mimo_default",
    }
    assert client.last_request_payload["messages"][0] == {
        "role": "user",
        "content": "用GM旁白语气朗读。",
    }
    assert client.last_request_payload["messages"][1] == {
        "role": "assistant",
        "content": "地牢入口已经打开。",
    }


def test_stateful_history_preserves_reasoning_content_and_tool_calls():
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "让我先查天气。",
                        "reasoning_content": "用户问河北天气，我应该调用天气工具。",
                        "tool_calls": [
                            {
                                "id": "call_weather_1",
                                "type": "function",
                                "function": {
                                    "name": "get_current_weather",
                                    "arguments": "{\"location\":\"Hebei\",\"unit\":\"celsius\"}"
                                }
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "河北当前天气晴，约 25 摄氏度。",
                        "reasoning_content": "我已经获得工具结果，可以直接回答用户。",
                        "tool_calls": None
                    }
                }
            ]
        }
    ]
    client = _FakeOpenAIAPITool(responses=responses)

    client.add_system("You are MiMo.")
    client.add_user("河北天气怎么样？")

    first_assistant = client.chat_message(
        thinking={"type": "enabled"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        },
                        "required": ["location"]
                    }
                }
            }
        ],
        tool_choice="auto"
    )

    assert first_assistant["reasoning_content"] == "用户问河北天气，我应该调用天气工具。"
    assert first_assistant["tool_calls"][0]["id"] == "call_weather_1"

    history_after_first_turn = client.get_history()
    assert history_after_first_turn[-1]["reasoning_content"] == "用户问河北天气，我应该调用天气工具。"
    assert history_after_first_turn[-1]["tool_calls"][0]["function"]["name"] == "get_current_weather"

    client.add_tool('{"location":"Hebei","temperature":25,"unit":"celsius"}', "call_weather_1", name="get_current_weather")
    second_assistant = client.chat_message(thinking={"type": "enabled"})

    second_request_messages = client.captured_payloads[1]["messages"]
    assert second_request_messages[-2]["role"] == "assistant"
    assert second_request_messages[-2]["reasoning_content"] == "用户问河北天气，我应该调用天气工具。"
    assert second_request_messages[-2]["tool_calls"][0]["id"] == "call_weather_1"
    assert second_request_messages[-1]["role"] == "tool"
    assert second_request_messages[-1]["tool_call_id"] == "call_weather_1"
    assert second_assistant["content"] == "河北当前天气晴，约 25 摄氏度。"


def test_llm_service_exposes_openai_client_debug_payloads(monkeypatch):
    fake_client = _FakeOpenAIAPITool(
        responses=[
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "完成",
                            "reasoning_content": "调试请求测试",
                            "tool_calls": None
                        }
                    }
                ]
            }
        ]
    )
    original_client = llm_service.client
    monkeypatch.setattr(llm_service, "client", fake_client)

    try:
        fake_client.single_chat_message("调试一下", thinking={"type": "enabled"})
        last_request = llm_service.get_last_request_payload()
        last_response = llm_service.get_last_response_payload()
    finally:
        monkeypatch.setattr(llm_service, "client", original_client)

    assert last_request is not None
    assert last_request["messages"][0]["content"] == "调试一下"
    assert last_request["thinking"]["type"] == "enabled"
    assert last_response is not None
    assert last_response["choices"][0]["message"]["reasoning_content"] == "调试请求测试"


def test_openai_compatible_thinking_defaults_to_disabled(monkeypatch):
    old_provider = llm_service.provider
    old_global_thinking = config.llm.thinking_enabled

    monkeypatch.setattr(llm_service, "provider", LLMProvider.OPENAI)
    monkeypatch.setattr(config.llm, "thinking_enabled", False)

    try:
        generation_config = llm_service._apply_openai_compatible_thinking_config({})
    finally:
        monkeypatch.setattr(llm_service, "provider", old_provider)
        monkeypatch.setattr(config.llm, "thinking_enabled", old_global_thinking)

    assert generation_config["thinking"]["type"] == "disabled"


def test_lmstudio_provider_override_takes_precedence(monkeypatch):
    old_provider = llm_service.provider
    old_global_thinking = config.llm.thinking_enabled
    old_lmstudio_thinking = config.llm.lmstudio.enable_thinking

    monkeypatch.setattr(llm_service, "provider", LLMProvider.LMSTUDIO)
    monkeypatch.setattr(config.llm, "thinking_enabled", False)
    monkeypatch.setattr(config.llm.lmstudio, "enable_thinking", True)

    try:
        generation_config = llm_service._apply_openai_compatible_thinking_config({})
    finally:
        monkeypatch.setattr(llm_service, "provider", old_provider)
        monkeypatch.setattr(config.llm, "thinking_enabled", old_global_thinking)
        monkeypatch.setattr(config.llm.lmstudio, "enable_thinking", old_lmstudio_thinking)

    assert generation_config["chat_template_kwargs"]["enable_thinking"] is True
