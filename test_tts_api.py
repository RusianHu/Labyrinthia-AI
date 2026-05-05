from fastapi.testclient import TestClient

import main


def test_tts_endpoint_disabled(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", False)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "地牢入口已经打开。", "category": "narrative"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "TTS_DISABLED"


def test_tts_endpoint_rejects_long_text(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "max_text_chars", 4)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "这段文本太长了", "category": "narrative"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "TTS_TEXT_TOO_LONG"


def test_tts_endpoint_uses_default_voice_and_returns_audio(monkeypatch):
    captured = {}

    class FakeOpenAIAPITool:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def mimo_text_to_speech_chat(self, **kwargs):
            captured["call"] = kwargs
            return b"RIFF-test-audio"

    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    monkeypatch.setattr(main.config.tts, "api_key", "test-key")
    monkeypatch.setattr(main.config.tts, "base_url", "https://api.xiaomimimo.com/v1")
    monkeypatch.setattr(main.config.tts, "model_name", "mimo-v2.5-tts")
    monkeypatch.setattr(main.config.tts, "default_voice", "mimo_default")
    monkeypatch.setattr(main.config.tts, "output_format", "wav")
    monkeypatch.setattr(main.config.tts, "timeout", 120)
    monkeypatch.setattr(main.config.tts, "max_text_chars", 800)
    monkeypatch.setattr(main, "OpenAIAPITool", FakeOpenAIAPITool)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "地牢入口已经打开。", "category": "narrative"},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-test-audio"
    assert response.headers["content-type"].startswith("audio/wav")
    assert captured["init"]["api_key"] == "test-key"
    assert captured["call"]["model"] == "mimo-v2.5-tts"
    assert captured["call"]["voice"] == "mimo_default"
    assert captured["call"]["response_format"] == "wav"
    assert captured["call"]["text"] == "地牢入口已经打开。"


def test_tts_config_does_not_fall_back_to_openai(monkeypatch):
    """回归：TTS 配置必须独立于 OpenAI Provider，禁止任何隐式回退。

    场景：仅设置 OPENAI_API_KEY / OPENAI_BASE_URL，未设置 TTS_API_KEY / TTS_BASE_URL；
    期望：新构建的 Config 中 tts.api_key / tts.base_url 不会被 OpenAI 的值填充。

    实现说明：
    - `python-dotenv` 默认 `override=False`，已存在于环境中的变量（即使空串）
      不会被 .env 文件覆盖。所以这里用 `setenv(..., "")` 而不是 `delenv`，
      避免 reload 时 .env 中的真实 TTS_API_KEY 重新注入污染断言。
    """
    import importlib
    import config as config_module

    # 把所有可能影响判断的 TTS_* 变量显式设为空串，阻断 .env 重新注入
    for var in (
        "TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL_NAME", "TTS_DEFAULT_VOICE",
        "TTS_PROVIDER", "TTS_OUTPUT_FORMAT", "TTS_TIMEOUT", "TTS_MAX_TEXT_CHARS",
    ):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("TTS_ENABLED", "false")

    monkeypatch.setenv("OPENAI_API_KEY", "openai-only-key-should-not-leak")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example.com/v1")

    # 重新加载 config 模块以走全套 _load_from_env 流程
    importlib.reload(config_module)

    fresh_cfg = config_module.Config()

    assert fresh_cfg.tts.api_key == "", (
        "TTS api_key 不应再回退至 OPENAI_API_KEY，"
        f"实际值: {fresh_cfg.tts.api_key!r}"
    )
    assert fresh_cfg.tts.base_url == "", (
        "TTS base_url 不应再回退至 OPENAI_BASE_URL，"
        f"实际值: {fresh_cfg.tts.base_url!r}"
    )
    # OpenAI 自己的配置应正常加载，证明只是 TTS 解耦
    assert fresh_cfg.llm.openai.api_key == "openai-only-key-should-not-leak"
    assert fresh_cfg.llm.openai.base_url == "https://openai.example.com/v1"


def test_tts_config_picks_up_dedicated_env_vars(monkeypatch):
    """回归：TTS 配置在显式设置专属环境变量时正确加载，且与 OpenAI 配置互不影响。"""
    import importlib
    import config as config_module

    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example.com/v1")
    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_API_KEY", "tts-dedicated-key")
    monkeypatch.setenv("TTS_BASE_URL", "https://tts.example.com/v1/")
    monkeypatch.setenv("TTS_MODEL_NAME", "mimo-v2.5-tts")

    importlib.reload(config_module)
    fresh_cfg = config_module.Config()

    assert fresh_cfg.tts.enabled is True
    assert fresh_cfg.tts.api_key == "tts-dedicated-key"
    # base_url 末尾斜杠应被剥离
    assert fresh_cfg.tts.base_url == "https://tts.example.com/v1"
    assert fresh_cfg.tts.model_name == "mimo-v2.5-tts"
    # OpenAI 配置不受影响
    assert fresh_cfg.llm.openai.api_key == "openai-key"
    assert fresh_cfg.llm.openai.base_url == "https://openai.example.com/v1"
    # 关键：两条配置完全独立
    assert fresh_cfg.tts.api_key != fresh_cfg.llm.openai.api_key
    assert fresh_cfg.tts.base_url != fresh_cfg.llm.openai.base_url


