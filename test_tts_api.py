from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

import asyncio

import main
import tts_gateway


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
    """mimo provider 走 TTSGateway → MimoTTSProvider → OpenAIAPITool 链路。

    重构后 mock 点变为 `tts_gateway.OpenAIAPITool`（而非旧版 `main.OpenAIAPITool`），
    其余断言（透传 model/voice/response_format/text）保持不变。
    """
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
    monkeypatch.setattr(tts_gateway, "OpenAIAPITool", FakeOpenAIAPITool)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "地牢入口已经打开。", "category": "narrative"},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-test-audio"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers.get("X-TTS-Voice") == "mimo_default"
    assert captured["init"]["api_key"] == "test-key"
    assert captured["call"]["model"] == "mimo-v2.5-tts"
    assert captured["call"]["voice"] == "mimo_default"
    assert captured["call"]["response_format"] == "wav"
    assert captured["call"]["text"] == "地牢入口已经打开。"


def test_tts_endpoint_uses_qwen_provider(monkeypatch):
    """qwen_gradio provider 走 TTSGateway → 注册的 fake provider 实例。

    通过临时覆盖 `TTSGateway._registry["qwen_gradio"]` 注入 fake provider，
    断言 `/api/tts/synthesize` 在 provider 切换后仍按统一契约返回 audio bytes，
    且响应头 `X-TTS-Voice` 反映 provider 解析后的真实音色。
    """
    captured = {}

    class FakeQwenProvider(tts_gateway.TTSProviderBase):
        name = "qwen_gradio"
        supports_prefetch = True
        required_config_fields = ("base_url",)
        fixed_response_format = "wav"

        def __init__(self):
            captured["init"] = True

        def synthesize(self, text, voice=None, response_format="wav", style_hint=None):
            captured["call"] = {
                "text": text,
                "voice": voice,
                "response_format": response_format,
                "style_hint": style_hint,
            }
            return b"RIFF-qwen-fake", "vivian"

    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "qwen_gradio")
    monkeypatch.setattr(main.config.tts, "base_url", "https://qwen-qwen3-tts-demo.ms.show")
    monkeypatch.setattr(main.config.tts, "default_voice", "vivian")
    monkeypatch.setattr(main.config.tts, "output_format", "mp3")
    monkeypatch.setattr(main.config.tts, "timeout", 120)
    monkeypatch.setattr(main.config.tts, "max_text_chars", 800)
    monkeypatch.setattr(main.config.tts, "model_name", "")
    monkeypatch.setattr(main.config.tts, "api_key", "")

    monkeypatch.setitem(tts_gateway.TTSGateway._registry, "qwen_gradio", FakeQwenProvider)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "迷雾中传来低沉吟唱。", "category": "narrative"},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-qwen-fake"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers.get("X-TTS-Provider") == "qwen_gradio"
    assert response.headers.get("X-TTS-Voice") == "vivian"
    assert captured["init"] is True
    assert captured["call"]["text"] == "迷雾中传来低沉吟唱。"
    assert captured["call"]["voice"] == "vivian"
    assert captured["call"]["response_format"] == "wav"


def test_tts_config_allows_qwen_blank_dedicated_env_vars(monkeypatch):
    """qwen_gradio 允许 API key / model / base_url 显式空串，不回填 mimo 默认值。"""
    import importlib
    import config as config_module

    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_PROVIDER", "qwen_gradio")
    monkeypatch.setenv("TTS_API_KEY", "")
    monkeypatch.setenv("TTS_BASE_URL", "")
    monkeypatch.setenv("TTS_MODEL_NAME", "")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "")

    importlib.reload(config_module)
    fresh_cfg = config_module.Config()

    assert fresh_cfg.tts.enabled is True
    assert fresh_cfg.tts.provider == "qwen_gradio"
    assert fresh_cfg.tts.api_key == ""
    assert fresh_cfg.tts.base_url == ""
    assert fresh_cfg.tts.model_name == ""
    assert fresh_cfg.tts.default_voice == ""


def test_tts_endpoint_unknown_provider(monkeypatch):
    """未知 provider 必须被 TTSGateway.is_known 在 _validate_tts_request_text 阶段拦截。"""
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "unknown_xyz_provider")
    monkeypatch.setattr(main.config.tts, "max_text_chars", 800)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "地牢入口已经打开。", "category": "narrative"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "TTS_PROVIDER_UNSUPPORTED"


def test_tts_endpoint_provider_known_but_unconfigured(monkeypatch):
    """provider 已注册但缺少必填字段（mimo 缺 api_key）→ 503 TTS_NOT_CONFIGURED。

    覆盖 `_get_tts_provider` 中 ValueError → HTTPException(503) 的翻译路径。
    """
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    monkeypatch.setattr(main.config.tts, "api_key", "")  # 故意留空
    monkeypatch.setattr(main.config.tts, "base_url", "https://api.xiaomimimo.com/v1")
    monkeypatch.setattr(main.config.tts, "model_name", "mimo-v2.5-tts")
    monkeypatch.setattr(main.config.tts, "max_text_chars", 800)

    client = TestClient(main.app)
    response = client.post(
        "/api/tts/synthesize",
        json={"text": "地牢入口已经打开。", "category": "narrative"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "TTS_NOT_CONFIGURED"


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


def test_tts_opening_prefetch_config_loads_dedicated_env_vars(monkeypatch):
    import importlib
    import config as config_module

    monkeypatch.setenv("TTS_OPENING_PREFETCH_ENABLED", "false")
    monkeypatch.setenv("TTS_OPENING_PREFETCH_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("TTS_OPENING_CACHE_TTL_SECONDS", "30")
    monkeypatch.setenv("TTS_OPENING_CACHE_MAX_ENTRIES", "8")
    monkeypatch.setenv("TTS_OPENING_FETCH_WAIT_SECONDS", "1.5")

    importlib.reload(config_module)
    fresh_cfg = config_module.Config()

    assert fresh_cfg.tts.opening_prefetch_enabled is False
    assert fresh_cfg.tts.opening_prefetch_max_concurrency == 5
    assert fresh_cfg.tts.opening_cache_ttl_seconds == 30
    assert fresh_cfg.tts.opening_cache_max_entries == 8
    assert fresh_cfg.tts.opening_fetch_wait_seconds == 1.5


def _make_completed_entry(audio: bytes, *, user_id: str, game_id: str, segment_id: str):
    loop = asyncio.new_event_loop()
    try:
        async def _result():
            return audio
        future = loop.create_task(_result())
        loop.run_until_complete(future)
        entry = main.OpeningTTSEntry(
            user_id=user_id,
            game_id=game_id,
            segment_id=segment_id,
            text="开场白",
            category="narrative",
            voice="mimo_default",
            created_at=__import__("time").time(),
            future=future,
        )
        return entry, loop
    except Exception:
        loop.close()
        raise


def _make_request_with_user(user_id: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/tts/opening/game-abc/opening_narrative",
        "headers": [(b"cookie", f"labyrinthia_user_id={user_id}".encode("ascii"))],
    })


def test_opening_tts_endpoint_returns_cached_audio(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    monkeypatch.setattr(main.config.tts, "output_format", "wav")
    monkeypatch.setattr(main.config.tts, "opening_cache_ttl_seconds", 600)

    main._opening_tts_cache.clear()

    fake_user_id = "11111111-1111-1111-1111-111111111111"
    entry, loop = _make_completed_entry(
        b"RIFF-cached-audio",
        user_id=fake_user_id,
        game_id="game-abc",
        segment_id="opening_narrative",
    )
    main._opening_tts_cache[(fake_user_id, "game-abc", "opening_narrative")] = entry

    try:
        client = TestClient(main.app)
        client.cookies.set("labyrinthia_user_id", fake_user_id)
        response = client.get("/api/tts/opening/game-abc/opening_narrative")

        assert response.status_code == 200
        assert response.content == b"RIFF-cached-audio"
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.headers.get("X-TTS-Cache") == "hit"
    finally:
        loop.close()
        main._opening_tts_cache.clear()


def test_opening_tts_endpoint_evicts_failed_pending_prefetch(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    monkeypatch.setattr(main.config.tts, "opening_cache_ttl_seconds", 600)
    monkeypatch.setattr(main.config.tts, "opening_fetch_wait_seconds", 0.5)

    main._opening_tts_cache.clear()
    fake_user_id = "11111111-1111-1111-1111-111111111111"
    key = (fake_user_id, "game-abc", "opening_narrative")

    async def _run():
        async def _fail():
            await asyncio.sleep(0)
            raise RuntimeError("prefetch failed")

        failed_task = asyncio.create_task(_fail())
        main._opening_tts_cache[key] = main.OpeningTTSEntry(
            user_id=fake_user_id,
            game_id="game-abc",
            segment_id="opening_narrative",
            text="开场白",
            category="narrative",
            voice="mimo_default",
            created_at=__import__("time").time(),
            future=failed_task,
        )

        try:
            await main.get_opening_tts_audio(
                "game-abc",
                "opening_narrative",
                _make_request_with_user(fake_user_id),
            )
        except HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail["error_code"] == "TTS_PREFETCH_FAILED"
        else:
            raise AssertionError("failed prefetch should raise HTTPException")

    try:
        asyncio.run(_run())
        assert key not in main._opening_tts_cache
    finally:
        main._opening_tts_cache.clear()


def test_opening_tts_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    main._opening_tts_cache.clear()

    fake_user_id = "11111111-1111-1111-1111-111111111111"
    client = TestClient(main.app)
    client.cookies.set("labyrinthia_user_id", fake_user_id)
    response = client.get("/api/tts/opening/game-xyz/opening_narrative")

    assert response.status_code == 404
    # 全局 404 处理器统一改写 body，行为对等于现有 /api/load 等端点
    body = response.json()
    assert body["success"] is False
    assert "API端点未找到" in body["message"]


def test_opening_tts_endpoint_blocks_other_user(monkeypatch):
    monkeypatch.setattr(main.config.tts, "enabled", True)
    monkeypatch.setattr(main.config.tts, "provider", "mimo_openai_compatible")
    monkeypatch.setattr(main.config.tts, "output_format", "wav")

    main._opening_tts_cache.clear()

    owner = "11111111-1111-1111-1111-111111111111"
    intruder = "22222222-2222-2222-2222-222222222222"
    entry, loop = _make_completed_entry(
        b"RIFF-secret",
        user_id=owner,
        game_id="game-abc",
        segment_id="opening_narrative",
    )
    main._opening_tts_cache[(owner, "game-abc", "opening_narrative")] = entry

    try:
        client = TestClient(main.app)
        client.cookies.set("labyrinthia_user_id", intruder)
        response = client.get("/api/tts/opening/game-abc/opening_narrative")

        assert response.status_code == 404
        body = response.json()
        # 入侵用户不应拿到 owner 的音频，无论 body 形态如何
        assert b"RIFF-secret" not in response.content
        assert body.get("success") is False
    finally:
        loop.close()
        main._opening_tts_cache.clear()
