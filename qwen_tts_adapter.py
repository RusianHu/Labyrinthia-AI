"""Qwen Gradio TTS Provider —— 同进程纯 Python 适配器

来源
----
本文件从 qwen-tts-skill 的 `QwenTTSBackend` 类迁移而来，并适配为本项目的
`TTSProviderBase` 接口。

移植范围
--------
- ✅ 远端音色 / 语言枚举抓取（`refresh_catalog`）
- ✅ 通过 `gradio_client.Client.predict` 调用上游 `/tts_interface`
- ✅ 临时音频文件读取与清理
- ✅ 默认音色解析（vivian fallback）

裁掉范围
--------
- ❌ `QwenTTSService`（子进程模式启动 FastAPI 服务）
- ❌ `QwenTTSSkill`（CLI 入口 / context manager）
- ❌ `create_app` / `start_server`（OpenAI 风格 REST 暴露层）
- ❌ `get_missing_rest_dependencies`（依赖检查 helper）
- ❌ `tts()` / `skill_say` / `skill_voices` / `skill_languages` 等 skill 化函数

行为差异（与上游 backend 对比）
-----------------------------
- **严格音色校验**：上游 backend 在收到未知音色 ID 时静默 fallback 到默认音色；
  本 provider 在严格模式下抛 `ValueError`，与 mimo provider 的错误语义对齐，
  避免缓存错误音色的音频。
- **mimo_default 兼容**：当请求的 voice 为 `None` / `""` / `"mimo_default"` 时，
  自动映射为默认 `vivian`，避免切换 provider 时 `default_voice` 残留导致请求失败。
- **lazy 枚举**：`refresh_catalog` 在第一次 `synthesize` 时按需触发；后续按
  upstream URL 复用进程内缓存，避免每次请求重复抓取枚举。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tts_gateway import TTSGateway, TTSProviderBase


logger = logging.getLogger(__name__)


DEFAULT_QWEN_BASE_URL = "https://qwen-qwen3-tts-demo.ms.show"
DEFAULT_QWEN_API_NAME = "/tts_interface"
DEFAULT_QWEN_LANGUAGE_ID = "auto"
DEFAULT_QWEN_LANGUAGE_NAME = "Auto / 自动"
DEFAULT_QWEN_VOICE_ID = "vivian"
DEFAULT_QWEN_VOICE_NAME = "Vivian / 十三"

# 当 `default_voice` 来自 mimo provider 残留时（如切 provider 时未同步 .env），
# 把这些值视为「未指定」，回退到 qwen 的默认音色。
_MIMO_LEGACY_VOICE_ALIASES = frozenset({"", "mimo_default", "default", "auto"})


def _get_config(runtime_config: Optional[Any] = None):
    """Lazy-load runtime config to avoid config.py validation import cycles."""
    if runtime_config is not None:
        return runtime_config

    from config import config

    return config


def _normalize_option_id(label: object) -> str:
    """从 'Vivian / 十三' 这种枚举显示名抽出小写 id（'vivian'）。"""
    value = str(label or "").strip().lower()
    if not value:
        return ""
    return value.split("/")[0].strip()


class QwenGradioTTSProvider(TTSProviderBase):
    """通过 `gradio_client` 调用魔搭社区 Qwen3-TTS Demo 的同进程 provider。

    依赖：
    - `gradio_client>=2.0.0`（已加入 requirements.txt）
    - `config.tts.base_url`（可选；为空时使用 `DEFAULT_QWEN_BASE_URL`）
    - `config.tts.default_voice`（建议显式设为 `vivian`；任何 mimo 残留值都会被映射）

    备注：
    - 上游为公开 Gradio Space，单段 3-6s 排队 + 限流风险，建议作为开发体验位；
      `main.py` 不做自动 fallback，由 `TTS_PROVIDER` 显式切换。
    """

    name = "qwen_gradio"
    supports_prefetch = True
    required_config_fields = ()
    fixed_response_format = "wav"
    _catalog_lock = threading.RLock()
    _catalog_cache: Dict[str, Any] = {}

    def __init__(self, runtime_config: Optional[Any] = None) -> None:
        config = _get_config(runtime_config)
        base_url = str(config.tts.base_url or "").strip() or DEFAULT_QWEN_BASE_URL
        self._upstream_url = base_url
        self._api_name = DEFAULT_QWEN_API_NAME
        self._voices: Dict[str, str] = {}
        self._languages: Dict[str, str] = {}
        self._default_voice_id: str = DEFAULT_QWEN_VOICE_ID
        self._default_voice_name: str = DEFAULT_QWEN_VOICE_NAME
        self._default_language_id: str = DEFAULT_QWEN_LANGUAGE_ID
        self._default_language_name: str = DEFAULT_QWEN_LANGUAGE_NAME

    # ----- 内部：远端 client 与枚举抓取 -----
    def _create_client(self):
        try:
            from gradio_client import Client
        except ImportError as exc:
            raise RuntimeError("qwen_gradio 需要安装 gradio_client 依赖") from exc
        return Client(self._upstream_url)

    def _refresh_catalog(self, force: bool = False) -> None:
        if not force and self._voices and self._languages:
            return

        cache_key = self._upstream_url
        with self._catalog_lock:
            cached = self._catalog_cache.get(cache_key)
            if not force and cached:
                self._voices = dict(cached["voices"])
                self._languages = dict(cached["languages"])
                self._default_voice_id = cached["default_voice_id"]
                self._default_voice_name = cached["default_voice_name"]
                self._default_language_id = cached["default_language_id"]
                self._default_language_name = cached["default_language_name"]
                return

            voices: Dict[str, str] = {}
            languages: Dict[str, str] = {}
            client = self._create_client()
            try:
                for endpoint in client.endpoints.values():
                    for param in endpoint.parameters_info or []:
                        pname = param.get("parameter_name")
                        enum_values = param.get("type", {}).get("enum", []) or []
                        for display in enum_values:
                            opt_id = _normalize_option_id(display)
                            if not opt_id:
                                continue
                            if pname == "voice_display":
                                voices.setdefault(opt_id, str(display))
                            elif pname == "language_display":
                                languages.setdefault(opt_id, str(display))
            except Exception as exc:
                logger.error("[qwen_gradio] 拉取上游枚举失败: %s", exc, exc_info=True)
                raise RuntimeError(f"qwen 上游枚举抓取失败: {exc}") from exc
            finally:
                try:
                    client.close()
                except Exception:
                    pass

            if not voices:
                raise RuntimeError("qwen 上游未返回任何音色")

            self._voices = voices
            self._languages = languages

            # 选默认音色：优先 vivian，其次首个
            chosen_default: Optional[str] = None
            for vid, dname in self._voices.items():
                label = str(dname).lower()
                if "vivian" in vid.lower() or "vivian" in label or "十三" in str(dname):
                    chosen_default = vid
                    break
            if chosen_default is None:
                chosen_default = next(iter(self._voices.keys()))
            self._default_voice_id = chosen_default
            self._default_voice_name = self._voices[chosen_default]

            if DEFAULT_QWEN_LANGUAGE_ID in self._languages:
                self._default_language_id = DEFAULT_QWEN_LANGUAGE_ID
                self._default_language_name = self._languages[DEFAULT_QWEN_LANGUAGE_ID]
            elif self._languages:
                first_lang_id = next(iter(self._languages.keys()))
                self._default_language_id = first_lang_id
                self._default_language_name = self._languages[first_lang_id]

            self._catalog_cache[cache_key] = {
                "voices": dict(self._voices),
                "languages": dict(self._languages),
                "default_voice_id": self._default_voice_id,
                "default_voice_name": self._default_voice_name,
                "default_language_id": self._default_language_id,
                "default_language_name": self._default_language_name,
            }

        logger.info(
            "[qwen_gradio] 枚举就绪：%d 音色 / %d 语言，默认音色=%s",
            len(self._voices),
            len(self._languages),
            self._default_voice_id,
        )

    # ----- 内部：参数解析 -----
    def _resolve_voice(self, requested: Optional[str]) -> Tuple[str, str]:
        """返回 `(voice_id, voice_display_name)`。

        规则：
        - None / 空串 / 'mimo_default' / 'default' / 'auto' → 默认 vivian
        - 已知音色 id → 使用该音色
        - 其他 id → ValueError（严格模式，避免静默 fallback 导致缓存错误音频）
        """
        self._refresh_catalog(force=False)
        normalized = (requested or "").strip().lower()
        if normalized in _MIMO_LEGACY_VOICE_ALIASES:
            return self._default_voice_id, self._default_voice_name
        if normalized not in self._voices:
            raise ValueError(
                f"qwen TTS 未知音色: {requested!r}; 可用音色样本: "
                + ", ".join(list(self._voices.keys())[:8])
                + ("..." if len(self._voices) > 8 else "")
            )
        return normalized, self._voices[normalized]

    def _resolve_language(self, requested: Optional[str]) -> Tuple[str, str]:
        self._refresh_catalog(force=False)
        normalized = (requested or DEFAULT_QWEN_LANGUAGE_ID).strip().lower()
        if normalized in self._languages:
            return normalized, self._languages[normalized]
        return self._default_language_id, self._default_language_name

    def list_voices(self) -> List[Dict[str, str]]:
        """供调试 / 未来音色选择 UI 使用。"""
        self._refresh_catalog(force=False)
        return [{"id": vid, "name": name} for vid, name in self._voices.items()]

    def _extract_audio_path(self, value: Any) -> Optional[str]:
        if isinstance(value, (str, os.PathLike)):
            return str(value)
        if isinstance(value, dict):
            for key in ("path", "name", "file", "orig_name"):
                candidate = self._extract_audio_path(value.get(key))
                if candidate:
                    return candidate
            for item in value.values():
                candidate = self._extract_audio_path(item)
                if candidate:
                    return candidate
        if isinstance(value, (list, tuple)):
            for item in value:
                candidate = self._extract_audio_path(item)
                if candidate:
                    return candidate
        return None

    # ----- TTSProviderBase 接口 -----
    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        response_format: str = "wav",
        style_hint: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        if not text or not str(text).strip():
            raise ValueError("qwen TTS 文本不能为空")

        # 上游目前固定返回 wav，response_format != wav 时仅记录调试日志
        if response_format and response_format.lower() != self.fixed_response_format:
            logger.debug(
                "[qwen_gradio] 上游仅返回 wav，已忽略 response_format=%s", response_format,
            )
        # style_hint 在 qwen 上游无对应能力位
        del style_hint

        voice_id, voice_name = self._resolve_voice(voice)
        language_id, language_name = self._resolve_language(None)

        client = self._create_client()
        audio_path: Optional[str] = None
        try:
            predict_result = client.predict(
                api_name=self._api_name,
                text=str(text).strip(),
                voice_display=voice_name,
                language_display=language_name,
            )
            audio_path = self._extract_audio_path(predict_result)
        except Exception as exc:
            logger.error("[qwen_gradio] 上游 predict 失败: %s", exc, exc_info=True)
            raise RuntimeError(f"qwen 上游合成失败: {exc}") from exc
        finally:
            try:
                client.close()
            except Exception:
                pass

        if not audio_path or not os.path.exists(audio_path):
            raise RuntimeError("qwen 上游未返回有效音频文件")

        try:
            audio_bytes = Path(audio_path).read_bytes()
        except Exception as exc:
            logger.error("[qwen_gradio] 读取音频文件失败: %s", exc, exc_info=True)
            raise RuntimeError(f"qwen 音频文件读取失败: {exc}") from exc
        finally:
            try:
                os.remove(audio_path)
            except OSError:
                pass

        if not audio_bytes:
            raise RuntimeError("qwen 音频文件为空")

        logger.debug(
            "[qwen_gradio] synthesize ok: voice=%s language=%s bytes=%d",
            voice_id,
            language_id,
            len(audio_bytes),
        )
        return audio_bytes, voice_id


# 注册到 gateway（import 本模块即完成注册）
TTSGateway.register(QwenGradioTTSProvider.name, QwenGradioTTSProvider)
