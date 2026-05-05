"""
Labyrinthia AI - 游戏配置导入文件
Configuration file for the Labyrinthia AI game
"""

import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# 配置基础日志（在导入其他模块之前）
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 加载 .env 文件
_env_loaded = load_dotenv()


class LLMProvider(Enum):
    """LLM服务提供商枚举"""
    GEMINI = "gemini"
    OPENAI = "openai"
    LMSTUDIO = "lmstudio"
    OPENROUTER = "openrouter"


@dataclass
class _GeminiConfig:
    """Gemini Provider Specific Config"""
    api_key: str = ""  # 从环境变量加载
    model_name: str = "gemini-2.0-flash"
    endpoint: str = "https://generativelanguage.googleapis.com"
    api_version: str = "v1beta"

@dataclass
class _OpenRouterConfig:
    """OpenRouter Provider Specific Config"""
    api_key: str = ""  # 从环境变量加载
    model_name: str = "google/gemini-2.0-flash-001"
    base_url: str = "https://openrouter.ai/api/v1"

@dataclass
class _OpenAIConfig:
    """OpenAI Provider Specific Config"""
    # OpenAI兼容服务器配置（实际使用中转后的 Gemini 模型）
    api_key: str = ""  # 从环境变量加载
    model_name: str = "gemini-2.0-flash"
    base_url: str = "https://ai.yanshanlaosiji.top/v1"
    # 图片生成模型配置
    image_model: str = "imagen-4.0-ultra-generate-001"
    # TTS模型配置
    tts_model: str = "tts-1"

@dataclass
class _LMStudioConfig:
    """LMStudio Provider Specific Config（通过 OpenAI 兼容 API 驱动本地模型）"""
    api_key: str = "lm-studio"
    model_name: str = "local-model"
    base_url: str = "http://localhost:1234/v1"
    # Qwen3/3.5 混合思考模型支持 enable_thinking 参数控制是否输出思考过程。
    # True = 开启思考（模型先 <think>...</think> 再回复，默认行为）
    # False = 关闭思考（模型直接回复，不输出推理过程，输出更干净但推理能力可能下降）
    # None = 不传递此参数（由模型/服务端决定默认行为）
    enable_thinking: Optional[bool] = None


@dataclass
class TTSConfig:
    """Text-to-Speech配置类

    设计原则：
    - TTS 是与 LLM Provider 完全解耦的独立链路；
      `api_key` / `base_url` / `model_name` 必须由专属环境变量
      `TTS_API_KEY` / `TTS_BASE_URL` / `TTS_MODEL_NAME` 显式提供，
      不再回退到 `OPENAI_API_KEY` / `OPENAI_BASE_URL`。
    - 当 `enabled=True` 但关键字段缺失时，`Config._validate_critical_config`
      会发出明确警告；运行期 `/api/tts/synthesize` 端点也会以
      `TTS_NOT_CONFIGURED` 错误码拦截请求。
    """
    enabled: bool = False
    provider: str = "mimo_openai_compatible"
    api_key: str = ""
    base_url: str = ""
    model_name: str = "mimo-v2.5-tts"
    default_voice: str = "mimo_default"
    output_format: str = "wav"
    timeout: int = 120
    max_text_chars: int = 800
    opening_prefetch_enabled: bool = True
    opening_prefetch_max_concurrency: int = 2
    opening_cache_ttl_seconds: int = 600
    opening_cache_max_entries: int = 64
    opening_fetch_wait_seconds: float = 2.0

    # ---- 语音白名单分级（默认朗读） ----
    # 这些字段会作为前端 voice_whitelist_defaults 下发，前端的用户偏好（localStorage）会覆盖此处。
    # 设计目标：让 GM 语音聚焦于叙事/事件/任务/选项/里程碑，不要朗读 “攻击了 xxx / 移动到 xxx” 等模板消息。
    voice_whitelist_narrative: bool = True       # LLM 旁白（必读）
    voice_whitelist_event: bool = True           # 事件描述（必读）
    voice_whitelist_combat_narrative: bool = True  # 长战斗叙事（≥30字）
    voice_whitelist_choice: bool = True          # 事件选项汇总
    voice_whitelist_quest: bool = True           # 任务进展叙事
    voice_whitelist_milestone: bool = True       # 升级/楼梯/重大发现
    voice_whitelist_combat_summary: bool = False  # “X 攻击了 Y 造成 N 伤害”模板
    voice_whitelist_action: bool = False          # “攻击了 xxx / 移动到 xxx”
    voice_whitelist_status: bool = False          # “获得 5 点经验 / 恢复 N HP”
    voice_whitelist_system_state: bool = False    # “游戏已保存/已加载”
    voice_whitelist_error: bool = False           # 错误提示
    voice_whitelist_warning: bool = False         # 会话失效等
    voice_whitelist_debug: bool = False           # Emoji 前缀的调试输出


@dataclass
class LLMConfig:
    """LLM配置类"""
    # ------------------- LLM Provider Master Configuration --------------------
    # 在此处选择要使用的LLM供应商
    # Load from `LLM_PROVIDER` environment variable first.
    provider: LLMProvider = LLMProvider.OPENAI

    # 各个供应商的详细配置 (可在此处修改默认值)
    gemini: _GeminiConfig = field(default_factory=_GeminiConfig)
    openrouter: _OpenRouterConfig = field(default_factory=_OpenRouterConfig)
    openai: _OpenAIConfig = field(default_factory=_OpenAIConfig)
    lmstudio: _LMStudioConfig = field(default_factory=_LMStudioConfig)
    # --------------------------------------------------------------------------

    # --- Active LLM Configuration (由上面选择的provider动态填充) ---
    # --- (DO NOT EDIT THESE FIELDS DIRECTLY) ---
    api_key: str = ""
    model_name: str = ""
    # 通用生成参数（从环境变量加载，见 _load_from_env）
    max_output_tokens: Optional[int] = None  # 不设置限制，避免思考过程被截断
    use_generation_params: bool = False  # 是否使用temperature和top_p参数，False时使用LLM默认值
    temperature: float = 0.8
    top_p: float = 0.9
    thinking_enabled: bool = False
    timeout: int = 120
    hard_dependency: bool = True  # LLM是否为硬依赖；true时失败将中止主链路
    # 历史记录管理参数
    max_history_tokens: int = 10240  # 历史记录最大token数量
    min_context_entries: int = 5  # 最小保留的上下文条目数
    context_cleanup_threshold: float = 0.8  # 上下文清理触发阈值
    # ---- LLM 上下文记录开关（可通过环境变量覆盖） ----
    record_combat_to_context: bool = True   # 是否记录战斗事件到上下文
    record_trap_to_context: bool = True     # 是否记录陷阱事件到上下文
    # ---- LLM 上下文注入控制（可通过环境变量覆盖） ----
    inject_context_to_prompt: bool = True      # 是否将最近游戏上下文注入到提示词
    context_max_entries: int = 12              # 注入的上下文最大条目数
    context_include_metadata: bool = False     # 是否在上下文块中包含元数据

    # ---- LLM 上下文持久化控制 ----
    save_context_entries: int = 20             # 存档中保存的上下文条目数上限

    # 动态填充的特定于提供商的URL
    gemini_endpoint: str = ""
    gemini_api_version: str = ""
    openrouter_base_url: str = ""
    openai_base_url: str = ""
    lmstudio_base_url: str = ""
    # --------------------------------------------------------------------------

    # -------------------------- Proxy Configuration ---------------------------
    use_proxy: bool = False
    proxy_url: str = "http://127.0.0.1:10808"
    proxy_username: str = ""
    proxy_password: str = ""
    # --------------------------------------------------------------------------

    # ------------------------ Encoding Configuration -------------------------
    # 编码转换配置 - 用于解决Ubuntu服务器上的字符编码问题
    use_encoding_conversion: bool = False            # 是否启用编码转换（Windows环境默认关闭）
    encoding_method: str = "utf8_strict"             # 编码方法： utf8_strict, json_escape
    force_utf8_encoding: bool = True                 # 强制UTF-8编码

    # 编码性能配置
    encoding_timeout: float = 30.0                   # 编码操作超时时间（秒）
    encoding_retry_count: int = 2                    # 编码失败重试次数
    encoding_fallback_enabled: bool = True          # 启用编码失败回退机制
    show_encoding_impact: bool = True                # 显示编码对大小的影响




@dataclass
class DebugConfig:
    """调试配置类"""
    # 基础调试设置
    enabled: bool = True                             # 启用调试模式
    show_llm_debug: bool = True                      # 显示LLM调试信息
    show_encoding_debug: bool = True                 # 显示编码调试信息
    show_performance_metrics: bool = True            # 显示性能指标

    # 编码调试设置
    log_encoding_operations: bool = True             # 记录编码操作
    show_size_comparisons: bool = True               # 显示大小对比
    log_encoding_failures: bool = True               # 记录编码失败

    # 性能调试设置
    measure_request_time: bool = True                # 测量请求时间
    measure_encoding_time: bool = True               # 测量编码时间
    log_slow_operations: bool = True                 # 记录慢操作
    slow_operation_threshold: float = 1.0            # 慢操作阈值（秒）

    # 日志设置
    log_level: str = "DEBUG"                         # 日志级别
    log_to_file: bool = True                         # 记录到文件
    log_file_max_size: int = 10485760               # 日志文件最大大小（10MB）
    log_file_backup_count: int = 5                   # 日志文件备份数量


@dataclass
class GameConfig:
    """游戏配置类"""
    # 基础游戏设置
    game_name: str = "Labyrinthia AI"
    version: str = "1.0.0"
    debug_mode: bool = True
    show_llm_debug: bool = True  # 是否显示LLM调试信息

    # 地图设置
    default_map_size: tuple = (20, 20)
    max_map_size: tuple = (50, 50)
    min_map_size: tuple = (10, 10)
    map_generation_provider: str = "llm"  # llm | local
    map_generation_fallback_to_llm: bool = True
    local_map_monster_hints_enabled: bool = True
    map_generation_release_stage: str = "debug"  # debug | canary | stable
    map_generation_canary_percent: int = 0  # 0-100
    map_generation_canary_seed: str = "labyrinthia-map-canary"
    map_generation_force_legacy_chain: bool = False
    map_generation_disable_high_risk_patch: bool = True
    map_unreachable_rate_warn: float = 0.001
    map_unreachable_rate_block: float = 0.01
    map_stairs_violation_warn: float = 0.001
    map_stairs_violation_block: float = 0.01
    progress_anomaly_rate_warn: float = 0.02
    progress_anomaly_rate_block: float = 0.1
    final_objective_guard_block_warn: float = 0.1
    final_objective_guard_block_block: float = 0.3
    map_alert_blocking_enabled: bool = False

    # 角色设置
    max_player_level: int = 20
    starting_level: int = 1
    starting_hp: int = 100
    starting_mp: int = 50

    # 战斗设置
    max_combat_rounds: int = 50
    critical_hit_chance: float = 0.05
    combat_authority_mode: str = "local"          # local | hybrid | server
    combat_diff_threshold: int = 5                 # hybrid差异阈值（命中/伤害/死亡/经验）
    combat_release_stage: str = "debug"           # debug | canary | stable
    combat_canary_percent: int = 0                 # 0-100
    combat_auto_degrade_enabled: bool = True
    combat_degrade_latency_p95_ms: int = 500
    combat_degrade_error_rate: float = 0.05

    # 战斗叙述设置
    enable_combat_narrative: bool = True           # 启用战斗叙述生成
    boss_defeat_full_context: bool = True          # Boss击败使用完整上下文
    quest_monster_full_context: bool = True        # 任务怪物击败使用完整上下文
    normal_monster_full_context: bool = False      # 普通怪物击败使用简化上下文

    # 陷阱叙述设置
    trap_narrative_mode: str = "local"            # local | llm
    trap_narrative_fallback_to_local: bool = True  # llm失败时是否回退到本地叙述

    # DND判定系统设置
    use_new_roll_resolver: bool = True             # 使用新的统一判定引擎（支持豁免熟练、详细breakdown等）
    show_detailed_rolls: bool = True               # 显示详细的投掷过程（调试模式）

    # 内容生成设置
    enable_ai_generation: bool = True
    batch_generation_size: int = 5  # 批量生成内容的数量
    content_cache_size: int = 100   # 内容缓存大小

    # 存档设置（从环境变量加载，见 _load_from_env）
    max_save_slots: int = 10
    auto_save_interval: int = 300  # 秒
    game_session_timeout: int = 3600  # 游戏会话超时时间（秒），1小时无活动后自动关闭
    max_active_games_per_user: int = 5  # 每个用户最多同时活跃的游戏数量

    # 性能设置（从环境变量加载，见 _load_from_env）
    max_concurrent_llm_requests: int = 3
    request_retry_count: int = 3
    request_retry_delay: float = 1.0

    # 任务进度控制设置（已优化）
    max_quest_floors: int = 3                   # 开发阶段：任务最大楼层数
    # 注意：任务进度在UI中始终显示，不受调试模式控制

    # 【重要修复】进度增量配置 - 基于楼层变化而非绝对深度
    map_transition_progress: float = 18.0       # 地图切换进度增量（每次切换楼层增加18%）
    max_single_progress_increment: float = 25.0 # 单次进度增量上限（避免跳跃过大）

    # 进度管理器设置
    enable_smart_progression: bool = True       # 启用智能进度推进
    progress_history_limit: int = 100          # 进度历史记录限制
    auto_quest_completion: bool = True         # 自动任务完成

    # 事件进度权重配置（已优化降低）
    combat_victory_weight: float = 3.0         # 战斗胜利进度权重（原5.0）
    exploration_weight: float = 1.5            # 探索进度权重（原2.0）
    story_event_weight: float = 8.0            # 剧情事件进度权重（原10.0）
    treasure_found_weight: float = 2.0         # 发现宝藏进度权重（原3.0）

    # 进度触发阈值
    major_progress_threshold: float = 25.0     # 重大进度阈值（触发特殊事件）
    completion_threshold: float = 100.0        # 完成阈值
    near_completion_threshold: float = 80.0    # 接近完成阈值


@dataclass
class WebConfig:
    """Web服务配置类"""
    host: str = "127.0.0.1"
    port: int = 8001
    reload: bool = False

    # 静态文件配置
    static_dir: str = "static"
    templates_dir: str = "templates"

    # 安全配置（从环境变量加载，见 _load_from_env）
    secret_key: str = "labyrinthia-ai-secret-key-change-in-production"
    cors_origins: list = field(default_factory=lambda: ["*"])

    # 会话配置
    session_timeout: int = 3600  # 秒


@dataclass
class DataConfig:
    """数据存储配置类"""
    # 数据目录
    data_dir: str = "data"
    saves_dir: str = "saves"
    cache_dir: str = "cache"
    logs_dir: str = "logs"

    # 数据文件格式
    data_format: str = "json"  # json, yaml, pickle
    compression: bool = False

    # 备份设置
    enable_backup: bool = True
    backup_interval: int = 86400  # 秒（24小时）
    max_backups: int = 7


class Config:
    """主配置类"""

    def __init__(self):
        self.llm = LLMConfig()
        self.tts = TTSConfig()
        self.game = GameConfig()
        self.web = WebConfig()
        self.data = DataConfig()
        self.debug = DebugConfig()

        # 检查 .env 文件
        self._check_env_file()

        # 从环境变量加载配置
        self._load_from_env()

        # 创建必要的目录
        self._create_directories()

        # 验证关键配置
        self._validate_critical_config()

    def _load_from_env(self):
        """从环境变量加载配置"""
        # ------------------- Load LLM Configuration -------------------
        # 1. 从环境变量确定LLM Provider
        if provider_env := os.getenv("LLM_PROVIDER"):
            try:
                self.llm.provider = LLMProvider(provider_env.lower())
            except ValueError:
                pass  # 保留代码中设置的默认值

        # 2. 加载对应Provider的环境变量 (如果存在)
        # Gemini
        if gemini_api_key := os.getenv("GEMINI_API_KEY"):
            self.llm.gemini.api_key = gemini_api_key
        if gemini_model := os.getenv("GEMINI_MODEL_NAME"):
            self.llm.gemini.model_name = gemini_model
        # OpenRouter
        if openrouter_api_key := os.getenv("OPENROUTER_API_KEY"):
            self.llm.openrouter.api_key = openrouter_api_key
        if openrouter_model := os.getenv("OPENROUTER_MODEL_NAME"):
            self.llm.openrouter.model_name = openrouter_model
        # OpenAI
        if openai_api_key := os.getenv("OPENAI_API_KEY"):
            self.llm.openai.api_key = openai_api_key
        if openai_model := os.getenv("OPENAI_MODEL_NAME"):
            self.llm.openai.model_name = openai_model
        if openai_base_url := os.getenv("OPENAI_BASE_URL"):
            self.llm.openai.base_url = openai_base_url
        # LMStudio
        if lmstudio_base_url := os.getenv("LMSTUDIO_BASE_URL"):
            self.llm.lmstudio.base_url = lmstudio_base_url
        if lmstudio_model := os.getenv("LMSTUDIO_MODEL_NAME"):
            self.llm.lmstudio.model_name = lmstudio_model
        # enable_thinking: "true"→True, "false"→False, 未设置或其他→None
        _et = os.getenv("LMSTUDIO_ENABLE_THINKING", "").strip().lower()
        if _et == "true":
            self.llm.lmstudio.enable_thinking = True
        elif _et == "false":
            self.llm.lmstudio.enable_thinking = False
        # else: 保持 None（不传递此参数）

        # 3. 根据最终确定的provider，动态填充Active LLM Configuration
        provider_config_map = {
            LLMProvider.GEMINI: self.llm.gemini,
            LLMProvider.OPENROUTER: self.llm.openrouter,
            LLMProvider.OPENAI: self.llm.openai,
            LLMProvider.LMSTUDIO: self.llm.lmstudio,
        }

        active_provider_config = provider_config_map.get(self.llm.provider)

        if active_provider_config:
            self.llm.api_key = getattr(active_provider_config, 'api_key', '')
            self.llm.model_name = getattr(active_provider_config, 'model_name', '')

            # 填充特定于提供商的URL
            self.llm.gemini_endpoint = self.llm.gemini.endpoint
            self.llm.gemini_api_version = self.llm.gemini.api_version
            self.llm.openrouter_base_url = self.llm.openrouter.base_url
            self.llm.openai_base_url = self.llm.openai.base_url
            self.llm.lmstudio_base_url = self.llm.lmstudio.base_url

        if llm_hard_dependency := os.getenv("LLM_HARD_DEPENDENCY"):
            self.llm.hard_dependency = llm_hard_dependency.lower() in ("true", "1", "yes")

        # ------------------- Load TTS Configuration -------------------
        # 设计：TTS 配置完全独立于 LLM Provider，禁止回退至 OPENAI_API_KEY/BASE_URL。
        # 仅当 TTS_API_KEY / TTS_BASE_URL / TTS_MODEL_NAME 显式提供时，才会被采用；
        # 否则保留 TTSConfig dataclass 中的默认值（空串或安全占位），
        # 由 _validate_critical_config + /api/tts/synthesize 联合兜底校验。
        if tts_enabled := os.getenv("TTS_ENABLED"):
            self.tts.enabled = tts_enabled.lower() in ("true", "1", "yes")

        if tts_provider := os.getenv("TTS_PROVIDER"):
            provider = tts_provider.strip().lower()
            if provider:
                self.tts.provider = provider

        if tts_api_key := os.getenv("TTS_API_KEY"):
            self.tts.api_key = tts_api_key.strip()

        if tts_base_url := os.getenv("TTS_BASE_URL"):
            self.tts.base_url = tts_base_url.strip().rstrip("/")

        if tts_model := os.getenv("TTS_MODEL_NAME"):
            self.tts.model_name = tts_model.strip() or self.tts.model_name

        if tts_voice := os.getenv("TTS_DEFAULT_VOICE"):
            self.tts.default_voice = tts_voice.strip() or self.tts.default_voice

        if tts_format := os.getenv("TTS_OUTPUT_FORMAT"):
            output_format = tts_format.strip().lower()
            if output_format in ("wav", "mp3", "pcm16"):
                self.tts.output_format = output_format

        if tts_timeout := os.getenv("TTS_TIMEOUT"):
            try:
                self.tts.timeout = max(1, int(tts_timeout))
            except ValueError:
                pass

        if tts_max_chars := os.getenv("TTS_MAX_TEXT_CHARS"):
            try:
                self.tts.max_text_chars = max(1, int(tts_max_chars))
            except ValueError:
                pass

        if tts_opening_prefetch := os.getenv("TTS_OPENING_PREFETCH_ENABLED"):
            self.tts.opening_prefetch_enabled = tts_opening_prefetch.lower() in ("true", "1", "yes", "on")

        if tts_opening_concurrency := os.getenv("TTS_OPENING_PREFETCH_MAX_CONCURRENCY"):
            try:
                self.tts.opening_prefetch_max_concurrency = max(1, int(tts_opening_concurrency))
            except ValueError:
                pass

        if tts_opening_ttl := os.getenv("TTS_OPENING_CACHE_TTL_SECONDS"):
            try:
                self.tts.opening_cache_ttl_seconds = max(1, int(tts_opening_ttl))
            except ValueError:
                pass

        if tts_opening_max_entries := os.getenv("TTS_OPENING_CACHE_MAX_ENTRIES"):
            try:
                self.tts.opening_cache_max_entries = max(1, int(tts_opening_max_entries))
            except ValueError:
                pass

        if tts_opening_wait := os.getenv("TTS_OPENING_FETCH_WAIT_SECONDS"):
            try:
                self.tts.opening_fetch_wait_seconds = max(0.1, float(tts_opening_wait))
            except ValueError:
                pass

        # 语音白名单分级覆盖：TTS_VOICE_<CATEGORY>=true|false
        voice_whitelist_env = {
            "TTS_VOICE_NARRATIVE": "voice_whitelist_narrative",
            "TTS_VOICE_EVENT": "voice_whitelist_event",
            "TTS_VOICE_COMBAT_NARRATIVE": "voice_whitelist_combat_narrative",
            "TTS_VOICE_CHOICE": "voice_whitelist_choice",
            "TTS_VOICE_QUEST": "voice_whitelist_quest",
            "TTS_VOICE_MILESTONE": "voice_whitelist_milestone",
            "TTS_VOICE_COMBAT_SUMMARY": "voice_whitelist_combat_summary",
            "TTS_VOICE_ACTION": "voice_whitelist_action",
            "TTS_VOICE_STATUS": "voice_whitelist_status",
            "TTS_VOICE_SYSTEM_STATE": "voice_whitelist_system_state",
            "TTS_VOICE_ERROR": "voice_whitelist_error",
            "TTS_VOICE_WARNING": "voice_whitelist_warning",
            "TTS_VOICE_DEBUG": "voice_whitelist_debug",
        }
        for env_key, attr_name in voice_whitelist_env.items():
            raw_value = os.getenv(env_key)
            if raw_value is None:
                continue
            normalized = str(raw_value).strip().lower()
            if normalized in ("true", "1", "yes", "on"):
                setattr(self.tts, attr_name, True)
            elif normalized in ("false", "0", "no", "off"):
                setattr(self.tts, attr_name, False)

        # ------------------- Load Proxy Configuration -------------------
        if proxy_url := os.getenv("PROXY_URL"):
            self.llm.proxy_url = proxy_url

        if use_proxy := os.getenv("USE_PROXY"):
            self.llm.use_proxy = use_proxy.lower() in ("true", "1", "yes")

        if proxy_username := os.getenv("PROXY_USERNAME"):
            self.llm.proxy_username = proxy_username

        if proxy_password := os.getenv("PROXY_PASSWORD"):
            self.llm.proxy_password = proxy_password

        # Web配置
        if host := os.getenv("WEB_HOST"):
            self.web.host = host

        if port := os.getenv("WEB_PORT"):
            try:
                self.web.port = int(port)
            except ValueError:
                pass

        # 游戏配置
        if debug := os.getenv("DEBUG"):
            self.game.debug_mode = debug.lower() in ("true", "1", "yes")

        if show_llm_debug := os.getenv("SHOW_LLM_DEBUG"):
            self.game.show_llm_debug = show_llm_debug.lower() in ("true", "1", "yes")

        if map_provider := os.getenv("MAP_GENERATION_PROVIDER"):
            provider = map_provider.strip().lower()
            if provider in ("llm", "local"):
                self.game.map_generation_provider = provider

        if combat_authority_mode := os.getenv("COMBAT_AUTHORITY_MODE"):
            mode = combat_authority_mode.strip().lower()
            if mode in ("local", "hybrid", "server"):
                self.game.combat_authority_mode = mode

        if combat_diff_threshold := os.getenv("COMBAT_DIFF_THRESHOLD"):
            try:
                self.game.combat_diff_threshold = max(0, int(combat_diff_threshold))
            except ValueError:
                pass

        if release_stage := os.getenv("COMBAT_RELEASE_STAGE"):
            stage = release_stage.strip().lower()
            if stage in ("debug", "canary", "stable"):
                self.game.combat_release_stage = stage

        if canary_percent := os.getenv("COMBAT_CANARY_PERCENT"):
            try:
                self.game.combat_canary_percent = max(0, min(100, int(canary_percent)))
            except ValueError:
                pass

        if auto_degrade := os.getenv("COMBAT_AUTO_DEGRADE_ENABLED"):
            self.game.combat_auto_degrade_enabled = auto_degrade.lower() in ("true", "1", "yes")

        if degrade_latency := os.getenv("COMBAT_DEGRADE_LATENCY_P95_MS"):
            try:
                self.game.combat_degrade_latency_p95_ms = max(100, int(degrade_latency))
            except ValueError:
                pass

        if degrade_error_rate := os.getenv("COMBAT_DEGRADE_ERROR_RATE"):
            try:
                self.game.combat_degrade_error_rate = max(0.0, min(1.0, float(degrade_error_rate)))
            except ValueError:
                pass

        if map_fallback := os.getenv("MAP_GENERATION_FALLBACK_TO_LLM"):
            self.game.map_generation_fallback_to_llm = map_fallback.lower() in ("true", "1", "yes")

        if local_hints := os.getenv("LOCAL_MAP_MONSTER_HINTS_ENABLED"):
            self.game.local_map_monster_hints_enabled = local_hints.lower() in ("true", "1", "yes")

        if map_release_stage := os.getenv("MAP_GENERATION_RELEASE_STAGE"):
            stage = map_release_stage.strip().lower()
            if stage in ("debug", "canary", "stable"):
                self.game.map_generation_release_stage = stage

        if map_canary_percent := os.getenv("MAP_GENERATION_CANARY_PERCENT"):
            try:
                self.game.map_generation_canary_percent = max(0, min(100, int(map_canary_percent)))
            except ValueError:
                pass

        if map_canary_seed := os.getenv("MAP_GENERATION_CANARY_SEED"):
            self.game.map_generation_canary_seed = map_canary_seed.strip() or self.game.map_generation_canary_seed

        if map_force_legacy := os.getenv("MAP_GENERATION_FORCE_LEGACY_CHAIN"):
            self.game.map_generation_force_legacy_chain = map_force_legacy.lower() in ("true", "1", "yes")

        if disable_patch := os.getenv("MAP_GENERATION_DISABLE_HIGH_RISK_PATCH"):
            self.game.map_generation_disable_high_risk_patch = disable_patch.lower() in ("true", "1", "yes")

        if map_unreachable_warn := os.getenv("MAP_UNREACHABLE_RATE_WARN"):
            try:
                self.game.map_unreachable_rate_warn = max(0.0, min(1.0, float(map_unreachable_warn)))
            except ValueError:
                pass

        if map_unreachable_block := os.getenv("MAP_UNREACHABLE_RATE_BLOCK"):
            try:
                self.game.map_unreachable_rate_block = max(0.0, min(1.0, float(map_unreachable_block)))
            except ValueError:
                pass

        if map_stairs_warn := os.getenv("MAP_STAIRS_VIOLATION_WARN"):
            try:
                self.game.map_stairs_violation_warn = max(0.0, min(1.0, float(map_stairs_warn)))
            except ValueError:
                pass

        if map_stairs_block := os.getenv("MAP_STAIRS_VIOLATION_BLOCK"):
            try:
                self.game.map_stairs_violation_block = max(0.0, min(1.0, float(map_stairs_block)))
            except ValueError:
                pass

        if progress_anomaly_warn := os.getenv("PROGRESS_ANOMALY_RATE_WARN"):
            try:
                self.game.progress_anomaly_rate_warn = max(0.0, min(1.0, float(progress_anomaly_warn)))
            except ValueError:
                pass

        if progress_anomaly_block := os.getenv("PROGRESS_ANOMALY_RATE_BLOCK"):
            try:
                self.game.progress_anomaly_rate_block = max(0.0, min(1.0, float(progress_anomaly_block)))
            except ValueError:
                pass

        if final_guard_warn := os.getenv("FINAL_OBJECTIVE_GUARD_BLOCK_WARN"):
            try:
                self.game.final_objective_guard_block_warn = max(0.0, min(1.0, float(final_guard_warn)))
            except ValueError:
                pass

        if final_guard_block := os.getenv("FINAL_OBJECTIVE_GUARD_BLOCK_BLOCK"):
            try:
                self.game.final_objective_guard_block_block = max(0.0, min(1.0, float(final_guard_block)))
            except ValueError:
                pass

        if alert_blocking := os.getenv("MAP_ALERT_BLOCKING_ENABLED"):
            self.game.map_alert_blocking_enabled = alert_blocking.lower() in ("true", "1", "yes")

        if trap_narrative_mode := os.getenv("TRAP_NARRATIVE_MODE"):
            mode = trap_narrative_mode.strip().lower()
            if mode in ("local", "llm"):
                self.game.trap_narrative_mode = mode

        if trap_fallback := os.getenv("TRAP_NARRATIVE_FALLBACK_TO_LOCAL"):
            self.game.trap_narrative_fallback_to_local = trap_fallback.lower() in ("true", "1", "yes")

        # 调试配置
        if debug_enabled := os.getenv("DEBUG_ENABLED"):
            self.debug.enabled = debug_enabled.lower() in ("true", "1", "yes")

        if show_encoding_debug := os.getenv("SHOW_ENCODING_DEBUG"):
            self.debug.show_encoding_debug = show_encoding_debug.lower() in ("true", "1", "yes")

        if show_performance_metrics := os.getenv("SHOW_PERFORMANCE_METRICS"):
            self.debug.show_performance_metrics = show_performance_metrics.lower() in ("true", "1", "yes")

        # 编码配置
        if use_encoding := os.getenv("USE_ENCODING_CONVERSION"):
            self.llm.use_encoding_conversion = use_encoding.lower() in ("true", "1", "yes")

        if encoding_method := os.getenv("ENCODING_METHOD"):
            if encoding_method in ["utf8_strict", "json_escape"]:
                self.llm.encoding_method = encoding_method

        # ------------------- Load Security Configuration -------------------
        if secret_key := os.getenv("SECRET_KEY"):
            self.web.secret_key = secret_key

        # ------------------- Load LLM Advanced Configuration -------------------
        if llm_timeout := os.getenv("LLM_TIMEOUT"):
            try:
                self.llm.timeout = int(llm_timeout)
            except ValueError:
                pass

        if llm_max_output := os.getenv("LLM_MAX_OUTPUT_TOKENS"):
            if llm_max_output.strip().lower() in ("none", ""):
                self.llm.max_output_tokens = None
            else:
                try:
                    self.llm.max_output_tokens = int(llm_max_output)
                except ValueError:
                    pass

        if llm_thinking_enabled := os.getenv("LLM_THINKING_ENABLED"):
            self.llm.thinking_enabled = llm_thinking_enabled.lower() in ("true", "1", "yes")

        if llm_use_gen_params := os.getenv("LLM_USE_GENERATION_PARAMS"):
            self.llm.use_generation_params = llm_use_gen_params.lower() in ("true", "1", "yes")

        if llm_temperature := os.getenv("LLM_TEMPERATURE"):
            try:
                self.llm.temperature = float(llm_temperature)
            except ValueError:
                pass

        if llm_top_p := os.getenv("LLM_TOP_P"):
            try:
                self.llm.top_p = float(llm_top_p)
            except ValueError:
                pass

        # ------------------- Load LLM Context Management Configuration -------------------
        if max_history_tokens := os.getenv("LLM_MAX_HISTORY_TOKENS"):
            try:
                self.llm.max_history_tokens = int(max_history_tokens)
            except ValueError:
                pass

        if min_context_entries := os.getenv("LLM_MIN_CONTEXT_ENTRIES"):
            try:
                self.llm.min_context_entries = int(min_context_entries)
            except ValueError:
                pass

        if cleanup_threshold := os.getenv("LLM_CONTEXT_CLEANUP_THRESHOLD"):
            try:
                self.llm.context_cleanup_threshold = float(cleanup_threshold)
            except ValueError:
                pass

        #
        #
        if save_ctx_entries := os.getenv("LLM_SAVE_CONTEXT_ENTRIES"):
            try:
                self.llm.save_context_entries = int(save_ctx_entries)
            except ValueError:
                pass


        # LLM 上下文记录开关（环境变量覆盖）
        if record_combat := os.getenv("LLM_RECORD_COMBAT_TO_CONTEXT"):
            self.llm.record_combat_to_context = record_combat.lower() in ("true", "1", "yes")
        if record_trap := os.getenv("LLM_RECORD_TRAP_TO_CONTEXT"):
            self.llm.record_trap_to_context = record_trap.lower() in ("true", "1", "yes")

        # ------------------- Load Game Session Configuration -------------------
        if auto_save_interval := os.getenv("AUTO_SAVE_INTERVAL"):
            try:
                self.game.auto_save_interval = int(auto_save_interval)
            except ValueError:
                pass

        if game_session_timeout := os.getenv("GAME_SESSION_TIMEOUT"):
            try:
                self.game.game_session_timeout = int(game_session_timeout)
            except ValueError:
                pass

        if max_active_games := os.getenv("MAX_ACTIVE_GAMES_PER_USER"):
            try:
                self.game.max_active_games_per_user = int(max_active_games)
            except ValueError:
                pass

        # ------------------- Load Performance Configuration -------------------
        if max_concurrent_llm := os.getenv("MAX_CONCURRENT_LLM_REQUESTS"):
            try:
                self.game.max_concurrent_llm_requests = int(max_concurrent_llm)
            except ValueError:
                pass

        if retry_count := os.getenv("REQUEST_RETRY_COUNT"):
            try:
                self.game.request_retry_count = int(retry_count)
            except ValueError:
                pass

        if retry_delay := os.getenv("REQUEST_RETRY_DELAY"):
            try:
                self.game.request_retry_delay = float(retry_delay)
            except ValueError:
                pass

    def _check_env_file(self):
        """检查 .env 文件并提示用户"""
        env_path = Path(".env")
        env_example_path = Path(".env.example")

        if not _env_loaded:
            if not env_path.exists():
                logger.warning("⚠️  .env 文件不存在")
                if env_example_path.exists():
                    logger.info("💡 提示: 复制 .env.example 为 .env 并配置您的 API 密钥")
                    logger.info("   命令: copy .env.example .env  (Windows)")
                    logger.info("   命令: cp .env.example .env    (Linux/Mac)")
                else:
                    logger.info("💡 提示: 创建 .env 文件并配置您的 API 密钥")
                logger.info("   或者直接在 config.py 中修改默认配置")
            else:
                logger.debug("✓ .env 文件已加载")

    def _validate_critical_config(self):
        """验证关键配置"""
        # 检查 API Key
        if not self.llm.api_key:
            logger.warning("⚠️  LLM API Key 未设置")
            logger.info(f"💡 当前使用的 Provider: {self.llm.provider.value}")

            # 根据不同的 Provider 给出具体提示
            provider_key_map = {
                LLMProvider.GEMINI: "GEMINI_API_KEY",
                LLMProvider.OPENROUTER: "OPENROUTER_API_KEY",
                LLMProvider.OPENAI: "OPENAI_API_KEY",
                LLMProvider.LMSTUDIO: "LMSTUDIO_BASE_URL"
            }

            key_name = provider_key_map.get(self.llm.provider, "API_KEY")
            logger.info(f"   请在 .env 文件中设置: {key_name}=your_key_here")
        else:
            logger.debug(f"✓ API Key 已配置 (Provider: {self.llm.provider.value})")

        # ---- TTS 独立性校验 ----
        # TTS 已与 LLM Provider 解耦，启用时必须显式提供 TTS_API_KEY 与 TTS_BASE_URL。
        if self.tts.enabled:
            tts_missing = []
            if not (self.tts.api_key or "").strip():
                tts_missing.append("TTS_API_KEY")
            if not (self.tts.base_url or "").strip():
                tts_missing.append("TTS_BASE_URL")
            if not (self.tts.model_name or "").strip():
                tts_missing.append("TTS_MODEL_NAME")

            if tts_missing:
                logger.warning(
                    "⚠️  TTS 已启用但配置不完整，缺失变量: %s",
                    ", ".join(tts_missing),
                )
                logger.info(
                    "💡 TTS 现已与 OpenAI 配置解耦，请在 .env 中独立设置以上 TTS_* 变量；"
                    "缺失时 /api/tts/synthesize 将返回 TTS_NOT_CONFIGURED。"
                )
            else:
                logger.debug(
                    "✓ TTS 配置已就绪 (provider=%s, model=%s)",
                    self.tts.provider,
                    self.tts.model_name,
                )

    def _create_directories(self):
        """创建必要的目录"""
        directories = [
            self.data.data_dir,
            self.data.saves_dir,
            self.data.cache_dir,
            self.data.logs_dir,
            self.web.static_dir,
            self.web.templates_dir,
        ]

        for directory in directories:
            try:
                os.makedirs(directory, exist_ok=True)
                logger.debug(f"✓ 目录已就绪: {directory}")
            except PermissionError:
                logger.error(f"❌ 权限不足，无法创建目录: {directory}")
                logger.error("   请检查文件系统权限或使用管理员权限运行")
                raise
            except OSError as e:
                logger.error(f"❌ 创建目录失败: {directory}")
                logger.error(f"   错误信息: {e}")
                raise

    def update_config(self, section: str, **kwargs):
        """更新配置"""
        if hasattr(self, section):
            config_section = getattr(self, section)
            for key, value in kwargs.items():
                if hasattr(config_section, key):
                    setattr(config_section, key, value)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        tts_dict = dict(self.tts.__dict__)
        if tts_dict.get("api_key"):
            tts_dict["api_key"] = "***"

        return {
            "llm": self.llm.__dict__,
            "tts": tts_dict,
            "game": self.game.__dict__,
            "web": self.web.__dict__,
            "data": self.data.__dict__,
            "debug": self.debug.__dict__,
        }


# 全局配置实例
config = Config()

# 导出常用配置
__all__ = [
    "Config",
    "LLMConfig",
    "TTSConfig",
    "GameConfig",
    "WebConfig",
    "DataConfig",
    "DebugConfig",
    "LLMProvider",
    "config"
]
