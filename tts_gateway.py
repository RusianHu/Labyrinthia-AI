"""统一 TTS 入口与 Provider 注册表

设计原则
--------
1. 单一入口：`TTSGateway` 是注册表 + 工厂；`main.py` 不再直连具体 SDK。
2. 模块化 Provider：每个 provider 实现 `TTSProviderBase.synthesize`，
   返回 `(audio_bytes, resolved_voice_id)` 两元组，对外契约统一。
3. 错误语义两层化：
   - provider 构造阶段 `ValueError` —— 配置缺失（由 `main.py` 翻译为 503）。
   - `synthesize` 阶段 `ValueError` / `RuntimeError` —— 参数无效或上游失败
     （由 `main.py` 翻译为 502）。
4. 不与 LLM Provider 耦合：TTS 的 `api_key` / `base_url` / `model_name`
   由独立环境变量驱动；`MimoTTSProvider` 仍复用 `config.llm.use_proxy`
   作为代理出口，但不读 LLM 的 `api_key`。
5. 阻塞调用（如 `gradio_client.predict`）由 provider 内部封装好，
   外部由 `main.py` 用 `await asyncio.to_thread(provider.synthesize, ...)`
   包装即可，不在 provider 层引入 asyncio 依赖。

关于 import 顺序
-----------------
- 本模块不在顶层 import `config.config`，provider 实例化时才惰性读取配置；
  这样 `config.py` 的启动校验可以安全地按需 import gateway。
- `qwen_tts_adapter.py` 在 import 末尾调用 `TTSGateway.register(...)` 完成
  qwen_gradio provider 注册；`main.py` 顶部应 import 该 adapter，确保注册
  在请求到达前完成。
"""

from __future__ import annotations

import logging
import inspect
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type

from openai_api_tool import OpenAIAPITool


logger = logging.getLogger(__name__)


def _get_config(runtime_config: Optional[Any] = None):
    """Lazy-load runtime config to avoid config.py validation import cycles."""
    if runtime_config is not None:
        return runtime_config

    from config import config

    return config


class TTSProviderBase(ABC):
    """所有 TTS provider 的统一基类。

    子类必须设置：
    - `name`: provider 标识符（与 `TTS_PROVIDER` 环境变量取值对齐）
    - `supports_prefetch`: 是否支持开场预合成缓存（默认 True）
    - `required_config_fields`: 在 `config.tts` 中必须显式提供的字段名元组
    """

    name: str = ""
    supports_prefetch: bool = True
    required_config_fields: Tuple[str, ...] = ()
    fixed_response_format: Optional[str] = None

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        response_format: str = "wav",
        style_hint: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """合成语音；返回 `(audio_bytes, resolved_voice_id)`。

        约定：
        - 若 `text` 为空，应抛 `ValueError`。
        - 若上游网络失败 / 返回空音频 / 协议错误，应抛 `RuntimeError`。
        - 若请求的 `voice` 不在 provider 支持列表中（且不是默认兜底情形），
          应抛 `ValueError`，由 gateway 调用方翻译为 502 `TTS_VOICE_UNKNOWN`。
        """
        raise NotImplementedError

    @classmethod
    def get_required_config_fields(cls) -> List[str]:
        return list(cls.required_config_fields)

    @classmethod
    def get_effective_response_format(cls, requested: Optional[str]) -> str:
        if cls.fixed_response_format:
            return cls.fixed_response_format
        return str(requested or "wav").strip().lower() or "wav"


class MimoTTSProvider(TTSProviderBase):
    """MiMo-V2.5-TTS provider，使用 OpenAI 兼容 chat/completions 协议。

    依赖：
    - `config.tts.api_key` / `base_url` / `model_name` 必须显式提供
      （已与 `OPENAI_*` 解耦，不会回退）。
    - 复用 `config.llm.use_proxy` / `proxy_url` 作为可选代理。
    - 内部仍调用 `OpenAIAPITool.mimo_text_to_speech_chat`，不重复实现协议层。
    """

    name = "mimo_openai_compatible"
    supports_prefetch = True
    required_config_fields = ("api_key", "base_url", "model_name")

    def __init__(self, runtime_config: Optional[Any] = None) -> None:
        config = _get_config(runtime_config)
        api_key = str(config.tts.api_key or "").strip()
        base_url = str(config.tts.base_url or "").strip()
        model_name = str(config.tts.model_name or "").strip()

        missing: List[str] = []
        if not api_key:
            missing.append("api_key")
        if not base_url:
            missing.append("base_url")
        if not model_name:
            missing.append("model_name")
        if missing:
            raise ValueError(f"mimo TTS 配置缺失字段: {', '.join(missing)}")

        proxies: Optional[Dict[str, str]] = None
        if getattr(config.llm, "use_proxy", False) and getattr(config.llm, "proxy_url", ""):
            proxies = {
                "http": config.llm.proxy_url,
                "https": config.llm.proxy_url,
            }

        timeout_value = int(getattr(config.tts, "timeout", 120) or 120)

        self._client = OpenAIAPITool(
            api_key=api_key,
            base_url=base_url,
            default_tts_model=model_name,
            timeout=timeout_value,
            proxies=proxies,
        )
        self._model_name = model_name
        default_voice = str(config.tts.default_voice or "").strip()
        self._default_voice = default_voice or "mimo_default"

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        response_format: str = "wav",
        style_hint: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        if not text or not str(text).strip():
            raise ValueError("mimo TTS 文本不能为空")

        resolved_voice = (voice or self._default_voice or "mimo_default").strip() or "mimo_default"
        try:
            audio_bytes = self._client.mimo_text_to_speech_chat(
                text=text,
                model=self._model_name,
                voice=resolved_voice,
                response_format=response_format or "wav",
                style_hint=style_hint,
            )
        except Exception as exc:  # pragma: no cover - 由 gateway 上游统一翻译
            raise RuntimeError(f"mimo TTS 合成失败: {exc}") from exc

        if not isinstance(audio_bytes, (bytes, bytearray)) or len(audio_bytes) == 0:
            raise RuntimeError("mimo TTS 返回空音频")

        return bytes(audio_bytes), resolved_voice


class TTSGateway:
    """TTS provider 注册表与统一入口。

    使用方式：
        from tts_gateway import TTSGateway
        provider = TTSGateway.get_provider()           # 按 config.tts.provider 实例化
        bytes_, voice = provider.synthesize("...", voice=None)

    `peek(provider_name)` 仅返回 provider 类（不实例化），用于 `config.py`
    在启动期校验最小必填字段；避免在配置阶段触发上游网络请求。
    """

    _registry: Dict[str, Type[TTSProviderBase]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: Type[TTSProviderBase]) -> None:
        if not name:
            raise ValueError("TTSGateway.register: name 不能为空")
        if not issubclass(provider_cls, TTSProviderBase):
            raise TypeError(
                f"TTSGateway.register: {provider_cls!r} 必须继承自 TTSProviderBase"
            )
        cls._registry[name] = provider_cls
        logger.debug("[TTSGateway] 注册 provider: %s -> %s", name, provider_cls.__name__)

    @classmethod
    def is_known(cls, provider: Optional[str]) -> bool:
        return bool(provider) and str(provider).strip() in cls._registry

    @classmethod
    def peek(cls, provider: Optional[str]) -> Optional[Type[TTSProviderBase]]:
        """获取 provider 类（不实例化），用于 config 阶段校验必填字段。"""
        if not provider:
            return None
        return cls._registry.get(str(provider).strip())

    @classmethod
    def get_provider(
        cls,
        provider_name: Optional[str] = None,
        runtime_config: Optional[Any] = None,
    ) -> TTSProviderBase:
        """实例化当前生效的 provider。

        Args:
            provider_name: 显式指定 provider 名（用于测试）。默认读 `config.tts.provider`。

        Raises:
            ValueError: provider 未注册或配置缺失（由 provider __init__ 抛出）。
        """
        config = _get_config(runtime_config)
        name = (provider_name or str(config.tts.provider or "")).strip()
        provider_cls = cls._registry.get(name)
        if provider_cls is None:
            raise ValueError(
                f"未知 TTS provider: {name!r}; 已注册: {sorted(cls._registry.keys())}"
            )
        signature = inspect.signature(provider_cls)
        if "runtime_config" in signature.parameters:
            return provider_cls(runtime_config=runtime_config)
        return provider_cls()

    @classmethod
    def known_providers(cls) -> List[str]:
        return sorted(cls._registry.keys())


# ----- 默认注册 -----
TTSGateway.register(MimoTTSProvider.name, MimoTTSProvider)
