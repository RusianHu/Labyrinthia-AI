"""
Labyrinthia AI - LLM服务封装
LLM service wrapper for the Labyrinthia AI game
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Any, Union
from concurrent.futures import ThreadPoolExecutor

from gemini_api import GeminiAPI
from openrouter_client import OpenRouterClient, ChatError
from openai_api_tool import OpenAIAPITool
from config import config, LLMProvider


class LLMUnavailableError(RuntimeError):
    """LLM服务不可用时抛出的异常。

    当 LLM 请求因超时、API错误、网络不可达或返回空响应而失败时，
    本异常会被抛出并沿调用栈向上传播，让上层（GameEngine / API层）
    统一返回 error_code='LLM_UNAVAILABLE' 给前端。
    """

    def __init__(self, message: str = "LLM服务不可用", *, cause: str = "unknown"):
        self.cause = cause
        super().__init__(message)
from data_models import Character, Monster, GameMap, Quest, GameState, Item
from encoding_utils import encoding_converter
from prompt_manager import prompt_manager
from async_task_manager import async_task_manager, async_performance_monitor, TaskType

from llm_context_manager import llm_context_manager


logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务封装类"""

    def __init__(self):
        self.provider = config.llm.provider

        # 初始化异步任务管理器（如果还未初始化）
        if not async_task_manager._initialized:
            async_task_manager.initialize()

        # 使用统一的线程池管理器
        self.executor = async_task_manager.llm_executor

        # 准备代理配置
        proxies = {}
        if config.llm.use_proxy and config.llm.proxy_url:
            proxies = {
                'http': config.llm.proxy_url,
                'https': config.llm.proxy_url
            }
            logger.info(f"Using proxy: {config.llm.proxy_url}")

        # 初始化对应的LLM客户端
        if self.provider == LLMProvider.GEMINI:
            self.client = GeminiAPI(
                api_key=config.llm.api_key,
                endpoint=config.llm.gemini_endpoint,
                api_version=config.llm.gemini_api_version,
                default_timeout=config.llm.timeout,
                proxies=proxies
            )
        elif self.provider == LLMProvider.OPENROUTER:
            self.client = OpenRouterClient(
                api_key=config.llm.api_key,
                base_url=config.llm.openrouter_base_url,
                default_model=config.llm.model_name,
                timeout=config.llm.timeout,
                proxies=proxies,
                referer="https://github.com/Labyrinthia-AI/Labyrinthia-AI", # 使用一个有效的URL作为Referer
                title=config.game.game_name
            )
        elif self.provider == LLMProvider.OPENAI:
            # 配置代理（OpenAI API工具类使用requests，需要设置环境变量或传递proxies）
            import os
            if config.llm.use_proxy and config.llm.proxy_url:
                # 设置环境变量以便requests使用代理
                os.environ['HTTP_PROXY'] = config.llm.proxy_url
                os.environ['HTTPS_PROXY'] = config.llm.proxy_url
                logger.info(f"Set proxy environment variables for OpenAI: {config.llm.proxy_url}")

            self.client = OpenAIAPITool(
                api_key=config.llm.api_key,
                base_url=config.llm.openai_base_url,
                default_model=config.llm.model_name,
                default_image_model=config.llm.openai.image_model,
                default_tts_model=config.llm.openai.tts_model,
                timeout=config.llm.timeout
            )
        elif self.provider == LLMProvider.LMSTUDIO:
            # LMStudio使用OpenAI兼容API
            if config.llm.use_proxy and config.llm.proxy_url:
                import os
                os.environ['HTTP_PROXY'] = config.llm.proxy_url
                os.environ['HTTPS_PROXY'] = config.llm.proxy_url
                logger.info(f"Set proxy environment variables for LMStudio: {config.llm.proxy_url}")

            self.client = OpenAIAPITool(
                api_key=config.llm.api_key,
                base_url=config.llm.lmstudio_base_url,
                default_model=config.llm.model_name,
                timeout=config.llm.timeout
            )
        else:
            raise NotImplementedError(f"LLM provider {self.provider} not implemented yet")

    # reasoning 模型可能输出的结构化标签列表
    _REASONING_TAGS = ('think', 'thinking', 'analysis', 'reasoning', 'reflection', 'step')

    # reasoning 模型常见的元数据行模式（如 "**生成的叙述文本：**"、"---"、"*字符数：128字*" 等）
    _METADATA_LINE_PATTERNS = [
        re.compile(r'^\*{1,2}生成的.*?[:：]\*{1,2}\s*$', re.MULTILINE),  # **生成的叙述文本：**
        re.compile(r'^---+\s*$', re.MULTILINE),                            # 分隔线
        re.compile(r'^\*字符数[:：].*?\*\s*$', re.MULTILINE),             # *字符数：128字*
        re.compile(r'^\*.*?(?:字数|字符|上限|下限).*?\*\s*$', re.MULTILINE),  # 通用字数统计行
        re.compile(r'^#{1,3}\s*(?:生成的)?(?:开场)?叙述.*$', re.MULTILINE),   # ## 生成的开场叙述 / ## 开场叙述：XXX
    ]

    # reasoning 模型在正文输出之后常附加的"创作思路说明"等尾部段落，
    # 一旦匹配到这些标题行，截断其后的所有内容。
    # 注意：关键词必须足够精确（使用多字组合短语），避免在正文叙事中
    # 误匹配到单字关键词如"设计"、"元素"、"角色"等常见词汇。
    _TAIL_SECTION_PATTERN = re.compile(
        r'(?:\n|\r\n?)#{1,3}\s*(?:'
        r'创作思路|创作说明|写作说明|设计思路|设计说明|'
        r'分析说明|补充说明|注释说明|思路说明|'
        r'字数统计|词数统计|字符统计|生成说明|元素说明|'
        r'备注说明|实现说明|对照说明|参考说明|技巧说明|'
        r'创作解释|写作思考|设计解释|生成方案'
        r').*$',
        re.DOTALL
    )

    @staticmethod
    def _strip_thinking_tags(text: str, aggressive: bool = False) -> str:
        """移除 reasoning 模型输出中的推理过程标签块，可选清理元数据垃圾。

        **分层清理策略**：
        - **基础层（所有渠道）**：清除 ``<think>``/``<Thinking>``/``<analysis>``
          等标签块。OpenAI 的 o1/o3 reasoning 模型也可能输出这类标签，因此
          此层对所有渠道无条件执行，不会误伤正常叙事文本。
        - **激进层（仅 LMStudio 等本地模型）**：清理元数据行（粗体标题、字数
          统计、分隔线、markdown 标题等）和截断"创作思路/说明"等尾部段落。
          这些规则针对本地 reasoning/蒸馏模型的特有杂质设计，对 OpenAI/Gemini
          等云端模型可能造成误伤（如误删正文中的 ``---`` 分隔线或含关键词的
          标题），因此仅在 ``aggressive=True`` 时执行。

        Args:
            text: 待清理的原始文本
            aggressive: 是否启用激进清理（元数据行 + 尾部截断），
                        仅建议对 LMStudio 等本地 reasoning 模型开启
        """
        if not text:
            return text
        cleaned = text
        # 基础层：清除 reasoning 标签块（对所有渠道安全）
        # 使用 DOTALL 使 . 匹配换行符，IGNORECASE 匹配大小写变体
        for tag in LLMService._REASONING_TAGS:
            cleaned = re.sub(
                rf'<{tag}>.*?</{tag}>', '', cleaned, flags=re.DOTALL | re.IGNORECASE
            )
        # 激进层：仅对本地 reasoning 模型执行，避免误伤 OpenAI 等强模型的正常输出
        if aggressive:
            # 清理前置思考块：部分蒸馏模型会在正文之前输出 "## 思考过程"
            # 等 markdown 标题引导的内联思考段落（<think> 标签被清理后的变体）。
            # 匹配该标题行及其后续非粗体行，直到遇到 ** 粗体开头的正式叙事。
            cleaned = re.sub(
                r'^#{1,3}\s*(?:思考过程|思考|分析过程|分析|推理过程|推理)\b.*?\n'
                r'(?:(?!\*\*).*\n)*',   # 匹配后续行直到遇到 ** 开头行
                '', cleaned, flags=re.MULTILINE
            )
            # 截断尾部的"创作思路说明"等段落（含后续所有内容）
            cleaned = LLMService._TAIL_SECTION_PATTERN.sub('', cleaned)
            # 清理元数据行
            for pattern in LLMService._METADATA_LINE_PATTERNS:
                cleaned = pattern.sub('', cleaned)
        return cleaned.strip()

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """
        健壮的JSON响应解析方法，处理各种编码和格式问题

        Args:
            text: 原始响应文本

        Returns:
            解析后的JSON字典，解析失败时返回空字典
        """
        if not text or not text.strip():
            logger.warning("Empty response text for JSON parsing")
            return {}

        # 清理文本
        cleaned_text = text.strip()

        # 移除 reasoning 模型的 <think> 标签块
        # 安全策略：统一只做基础标签清理，避免激进规则误删正文/JSON。
        cleaned_text = self._strip_thinking_tags(cleaned_text, aggressive=False)

        if not cleaned_text:
            logger.warning("Response text empty after stripping thinking tags")
            return {}

        # 移除BOM字符
        if cleaned_text.startswith('\ufeff'):
            cleaned_text = cleaned_text[1:]

        # 移除markdown代码块标记
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.startswith('```'):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]

        cleaned_text = cleaned_text.strip()

        # 尝试多种解析方法
        parse_attempts = [
            # 方法1：直接解析
            lambda: json.loads(cleaned_text),
            # 方法2：处理可能的列表响应
            lambda: self._handle_list_response(cleaned_text),
            # 方法3：使用编码转换器
            lambda: self._parse_with_encoding_converter(cleaned_text),
            # 方法4：修复常见JSON格式问题
            lambda: self._parse_with_json_fixes(cleaned_text),
            # 方法5：从混合文本中提取第一个完整 JSON 对象
            #（reasoning 模型可能在 JSON 前后夹杂 markdown/推理文本）
            lambda: self._extract_json_from_mixed_text(cleaned_text),
        ]

        for i, parse_func in enumerate(parse_attempts, 1):
            try:
                result = parse_func()
                if isinstance(result, dict):
                    logger.debug(f"JSON parsing succeeded with method {i}")
                    return result
                elif isinstance(result, list) and result:
                    # 如果是列表，尝试返回第一个字典元素
                    for item in result:
                        if isinstance(item, dict):
                            logger.debug(f"JSON parsing succeeded with method {i} (extracted from list)")
                            return item
                    logger.warning(f"JSON parsing method {i} returned list without dict elements")
                else:
                    logger.warning(f"JSON parsing method {i} returned unexpected type: {type(result)}")
            except Exception as e:
                logger.debug(f"JSON parsing method {i} failed: {e}")
                continue

        # 所有方法都失败
        logger.error(f"All JSON parsing methods failed for text: {cleaned_text[:200]}...")
        return {}

    def _handle_list_response(self, text: str) -> Dict[str, Any]:
        """处理LLM返回列表而非字典的情况"""
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            # 返回列表中的第一个字典
            for item in parsed:
                if isinstance(item, dict):
                    return item
        elif isinstance(parsed, dict):
            return parsed
        return {}

    def _parse_with_encoding_converter(self, text: str) -> Dict[str, Any]:
        """使用编码转换器解析"""
        if encoding_converter.enabled:
            # 验证编码
            if not encoding_converter.validate_encoding(text):
                logger.warning("Invalid encoding detected in response text")
                return {}

        return json.loads(text)

    def _parse_with_json_fixes(self, text: str) -> Dict[str, Any]:
        """修复常见的JSON格式问题后解析"""
        # 修复常见问题
        fixed_text = text

        # 修复单引号
        fixed_text = fixed_text.replace("'", '"')

        # 修复尾随逗号
        fixed_text = re.sub(r',(\s*[}\]])', r'\1', fixed_text)

        # 修复未转义的换行符
        fixed_text = fixed_text.replace('\n', '\\n').replace('\r', '\\r')

        return json.loads(fixed_text)

    def _extract_json_from_mixed_text(self, text: str) -> Dict[str, Any]:
        """从混合文本中提取第一个完整的 JSON 对象。

        reasoning/蒸馏模型可能在 JSON 前后夹杂 markdown 标题、推理说明等
        非 JSON 文本。本方法通过花括号匹配来定位并提取最外层 JSON 对象。
        """
        # 先尝试提取 ```json ... ``` 代码块中的 JSON
        code_block_match = re.search(
            r'```(?:json)?\s*(\{.*?\})\s*```', text, flags=re.DOTALL
        )
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1))
            except json.JSONDecodeError:
                pass

        # 手动定位最外层的 { ... } 对象
        start_idx = text.find('{')
        if start_idx == -1:
            return {}

        depth = 0
        in_string = False
        escape_next = False
        for i in range(start_idx, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start_idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # 尝试修复后解析
                        try:
                            fixed = re.sub(r',(\s*[}\]])', r'\1', candidate)
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    # 继续查找下一个可能的 JSON 对象
                    next_start = text.find('{', i + 1)
                    if next_start == -1:
                        return {}
                    start_idx = next_start
                    depth = 0
        return {}

    async def _async_generate(self, prompt: str, timeout: Optional[float] = None, **kwargs) -> str:
        """
        异步生成内容（带并发控制和超时）

        Args:
            prompt: 提示词
            timeout: 超时时间（秒），None表示使用配置的默认超时
            **kwargs: 其他参数

        Returns:
            生成的文本
        """
        # 使用信号量控制并发
        async with async_task_manager.llm_semaphore:
            loop = asyncio.get_event_loop()
            hard_dependency = bool(getattr(config.llm, "hard_dependency", True))

            current_context_key = llm_context_manager.get_current_context_key()

            def _sync_generate():
                try:
                    # 使用原始提示词
                    processed_prompt = prompt

                    # 注入统一上下文到提示词（可通过配置开关控制）
                    try:
                        if getattr(config.llm, "inject_context_to_prompt", True):
                            context_block = llm_context_manager.build_context_string(
                                max_entries=getattr(config.llm, "context_max_entries", 12),
                                max_tokens=getattr(config.llm, "max_history_tokens", 10240),
                                include_metadata=getattr(config.llm, "context_include_metadata", False),
                                context_key=current_context_key,
                            )
                            if context_block:
                                processed_prompt = f"{context_block}\n\n{processed_prompt}"
                    except Exception as _e:
                        logger.warning(f"Failed to inject LLM context: {_e}")

                    generation_config = {}

                    # 只有在启用生成参数时才添加temperature和top_p
                    if config.llm.use_generation_params:
                        generation_config.update({
                            "temperature": config.llm.temperature,
                            "top_p": config.llm.top_p,
                        })

                    # 如果设置了max_output_tokens，则添加到配置中
                    if config.llm.max_output_tokens:
                        generation_config["max_output_tokens"] = config.llm.max_output_tokens

                    # 合并用户提供的配置
                    generation_config.update(kwargs.get("generation_config", {}))

                    # 根据提供商调用不同的客户端
                    if self.provider == LLMProvider.GEMINI:
                        response = self.client.single_turn(
                            model=config.llm.model_name,
                            text=processed_prompt,
                            generation_config=generation_config
                        )

                        # 提取生成的文本
                        if response.get("candidates") and response["candidates"][0].get("content"):
                            parts = response["candidates"][0]["content"].get("parts", [])
                            if parts and parts[0].get("text"):
                                return parts[0]["text"]

                        # 检查是否因为其他原因（如MAX_TOKENS）导致没有文本内容
                        if response.get("candidates"):
                            candidate = response["candidates"][0]
                            finish_reason = candidate.get("finishReason", "")
                            if finish_reason in ["MAX_TOKENS", "STOP"]:
                                logger.warning(f"LLM response finished with reason: {finish_reason}")
                                # 尝试从content中获取任何可用文本
                                content = candidate.get("content", {})
                                if content.get("parts"):
                                    for part in content["parts"]:
                                        if part.get("text"):
                                            return part["text"]

                        logger.warning("LLM response format unexpected")
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了意外的空响应",
                                cause="empty_response",
                            )
                        return ""

                    elif self.provider == LLMProvider.OPENROUTER:
                        # OpenRouter API使用 `max_tokens` 而不是 `max_output_tokens`
                        if "max_output_tokens" in generation_config:
                            generation_config["max_tokens"] = generation_config.pop("max_output_tokens")

                        response_text = self.client.chat_once(
                            prompt=processed_prompt,
                            model=config.llm.model_name,
                            **generation_config
                        )
                        if isinstance(response_text, str) and response_text.strip():
                            return response_text
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了空文本响应",
                                cause="empty_response",
                            )
                        return ""

                    elif self.provider == LLMProvider.OPENAI or self.provider == LLMProvider.LMSTUDIO:
                        # OpenAI API使用 `max_tokens` 而不是 `max_output_tokens`
                        if "max_output_tokens" in generation_config:
                            generation_config["max_tokens"] = generation_config.pop("max_output_tokens")

                        # LMStudio: 注入 enable_thinking 参数（Qwen3/3.5 混合思考模型支持）
                        if self.provider == LLMProvider.LMSTUDIO:
                            _et = config.llm.lmstudio.enable_thinking
                            if _et is not None:
                                generation_config["chat_template_kwargs"] = {
                                    "enable_thinking": _et
                                }

                        response_text = self.client.single_chat(
                            message=processed_prompt,
                            model=config.llm.model_name,
                            **generation_config
                        )
                        # 清理 reasoning 模型可能嵌入的 <think> 标签
                        # 安全策略：统一只做基础标签清理，避免激进规则误删正文。
                        if isinstance(response_text, str):
                            response_text = self._strip_thinking_tags(response_text, aggressive=False)
                        if isinstance(response_text, str) and response_text.strip():
                            return response_text
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了空文本响应",
                                cause="empty_response",
                            )
                        return ""

                except ChatError as e:
                    logger.error(f"LLM generation error (OpenRouter): {e}")
                    if hard_dependency:
                        raise LLMUnavailableError(
                            f"LLM请求失败: {e}",
                            cause="chat_error",
                        ) from e
                    return ""
                except LLMUnavailableError:
                    raise
                except Exception as e:
                    logger.error(f"LLM generation error: {e}")
                    if hard_dependency:
                        raise LLMUnavailableError(
                            f"LLM请求异常: {e}",
                            cause="exception",
                        ) from e
                    return ""

            # 使用超时控制
            if timeout is None:
                timeout = config.llm.timeout

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self.executor, _sync_generate),
                    timeout=timeout
                )
                return result
            except asyncio.TimeoutError:
                logger.error(f"LLM request timed out after {timeout}s")
                if hard_dependency:
                    raise LLMUnavailableError(
                        f"LLM请求超时（{timeout}秒）",
                        cause="timeout",
                    )
                return ""

    async def _async_generate_json(self, prompt: str, schema: Optional[Dict] = None, timeout: Optional[float] = None, **kwargs) -> Dict[str, Any]:
        """
        异步生成JSON格式内容（带并发控制和超时）

        Args:
            prompt: 提示词
            schema: JSON schema
            timeout: 超时时间（秒），None表示使用配置的默认超时
            **kwargs: 其他参数

        Returns:
            生成的JSON字典
        """
        # 使用信号量控制并发
        async with async_task_manager.llm_semaphore:
            loop = asyncio.get_event_loop()
            hard_dependency = bool(getattr(config.llm, "hard_dependency", True))

            current_context_key = llm_context_manager.get_current_context_key()

            def _sync_generate_json():
                try:
                    # 使用原始提示词
                    processed_prompt = prompt


                    # 注入统一上下文到提示词（可通过配置开关控制）
                    try:
                        if getattr(config.llm, "inject_context_to_prompt", True):
                            context_block = llm_context_manager.build_context_string(
                                max_entries=getattr(config.llm, "context_max_entries", 12),
                                max_tokens=getattr(config.llm, "max_history_tokens", 10240),
                                include_metadata=getattr(config.llm, "context_include_metadata", False),
                                context_key=current_context_key,
                            )
                            if context_block:
                                processed_prompt = f"{context_block}\n\n{processed_prompt}"
                    except Exception as _e:
                        logger.warning(f"Failed to inject LLM context: {_e}")

                    generation_config = {}

                    # 只有在启用生成参数时才添加temperature和top_p
                    if config.llm.use_generation_params:
                        generation_config.update({
                            "temperature": config.llm.temperature,
                            "top_p": config.llm.top_p,
                        })

                    # 如果设置了max_output_tokens，则添加到配置中
                    if config.llm.max_output_tokens:
                        generation_config["max_output_tokens"] = config.llm.max_output_tokens

                    # 合并用户提供的配置
                    generation_config.update(kwargs.get("generation_config", {}))

                    # 根据提供商调用不同的客户端
                    if self.provider == LLMProvider.GEMINI:
                        response = self.client.single_turn_json(
                            model=config.llm.model_name,
                            text=processed_prompt,
                            schema=schema,
                            generation_config=generation_config
                        )

                        # 提取生成的JSON
                        if response.get("candidates") and response["candidates"][0].get("content"):
                            parts = response["candidates"][0]["content"].get("parts", [])
                            if parts and parts[0].get("text"):
                                # 使用健壮的JSON解析方法
                                parsed_json = self._parse_json_response(parts[0]["text"])
                                if parsed_json:
                                    return parsed_json

                        logger.warning("LLM JSON response format unexpected")
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了无效的JSON响应",
                                cause="invalid_json_response",
                            )
                        return {}

                    elif self.provider == LLMProvider.OPENROUTER:
                        # OpenRouter API使用 `max_tokens` 而不是 `max_output_tokens`
                        if "max_output_tokens" in generation_config:
                            generation_config["max_tokens"] = generation_config.pop("max_output_tokens")

                        response_json = self.client.chat_json_once(
                            prompt=processed_prompt,
                            model=config.llm.model_name,
                            schema=schema,
                            **generation_config
                        )
                        if isinstance(response_json, dict) and response_json:
                            return response_json
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了空JSON响应",
                                cause="empty_json_response",
                            )
                        return {}

                    elif self.provider == LLMProvider.OPENAI or self.provider == LLMProvider.LMSTUDIO:
                        # OpenAI API使用 `max_tokens` 而不是 `max_output_tokens`
                        if "max_output_tokens" in generation_config:
                            generation_config["max_tokens"] = generation_config.pop("max_output_tokens")

                        # 在提示词中明确要求JSON格式
                        json_prompt = f"{processed_prompt}\n\n请以JSON格式返回结果。"

                        # LMStudio: 注入 enable_thinking 参数（Qwen3/3.5 混合思考模型支持）
                        if self.provider == LLMProvider.LMSTUDIO:
                            _et = config.llm.lmstudio.enable_thinking
                            if _et is not None:
                                generation_config["chat_template_kwargs"] = {
                                    "enable_thinking": _et
                                }

                        # LMStudio 本地模型仅支持 response_format.type = json_schema | text，
                        # 不支持 json_object。因此：
                        #   - 有 schema 时，尝试 json_schema 模式（降级为纯提示词）
                        #   - 无 schema 时，直接走纯提示词模式，避免不必要的 400 错误
                        response_text = None
                        if self.provider == LLMProvider.LMSTUDIO:
                            if schema:
                                try:
                                    response_format = {
                                        "type": "json_schema",
                                        "json_schema": {
                                            "name": "response",
                                            "schema": schema
                                        }
                                    }
                                    response_text = self.client.single_chat(
                                        message=json_prompt,
                                        model=config.llm.model_name,
                                        response_format=response_format,
                                        **generation_config
                                    )
                                except Exception as rf_err:
                                    logger.warning(
                                        f"LMStudio json_schema 模式不受支持，降级为纯提示词模式: {rf_err}"
                                    )
                                    response_text = self.client.single_chat(
                                        message=json_prompt,
                                        model=config.llm.model_name,
                                        **generation_config
                                    )
                            else:
                                # 无 schema 时直接用纯提示词模式，跳过 response_format
                                response_text = self.client.single_chat(
                                    message=json_prompt,
                                    model=config.llm.model_name,
                                    **generation_config
                                )
                        else:
                            response_format = {"type": "json_object"}
                            if schema:
                                response_format["schema"] = schema
                            response_text = self.client.single_chat(
                                message=json_prompt,
                                model=config.llm.model_name,
                                response_format=response_format,
                                **generation_config
                            )

                        parsed_json = self._parse_json_response(response_text)
                        if isinstance(parsed_json, dict) and parsed_json:
                            return parsed_json
                        if hard_dependency:
                            raise LLMUnavailableError(
                                "LLM返回了空JSON响应",
                                cause="empty_json_response",
                            )
                        return {}

                except ChatError as e:
                    logger.error(f"LLM JSON generation error (OpenRouter): {e}")
                    if hard_dependency:
                        raise LLMUnavailableError(
                            f"LLM JSON请求失败: {e}",
                            cause="chat_error",
                        ) from e
                    return {}
                except LLMUnavailableError:
                    raise
                except Exception as e:
                    logger.error(f"LLM JSON generation error: {e}")
                    if hard_dependency:
                        raise LLMUnavailableError(
                            f"LLM JSON请求异常: {e}",
                            cause="exception",
                        ) from e
                    return {}

            # 使用超时控制
            if timeout is None:
                timeout = config.llm.timeout

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self.executor, _sync_generate_json),
                    timeout=timeout
                )
                return result
            except asyncio.TimeoutError:
                logger.error(f"LLM JSON request timed out after {timeout}s")
                if hard_dependency:
                    raise LLMUnavailableError(
                        f"LLM JSON请求超时（{timeout}秒）",
                        cause="timeout",
                    )
                return {}

    @async_performance_monitor
    async def generate_character(self, character_type: str = "npc", context: str = "") -> Optional[Character]:
        """生成角色"""
        prompt = f"""
        请生成一个DnD风格的{character_type}角色。

        上下文信息：{context}

        请返回JSON格式的角色数据，包含以下字段：
        - name: 角色名称
        - description: 角色描述
        - character_class: 职业（fighter, wizard, rogue, cleric, ranger, barbarian, bard, paladin, sorcerer, warlock）
        - abilities: 能力值对象（strength, dexterity, constitution, intelligence, wisdom, charisma，每个值10-18）
        - stats: 属性对象（hp, max_hp, mp, max_mp, ac, speed, level, experience）

        确保角色符合DnD设定，有趣且平衡。
        """

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "character_class": {"type": "string"},
                "abilities": {
                    "type": "object",
                    "properties": {
                        "strength": {"type": "integer", "minimum": 8, "maximum": 18},
                        "dexterity": {"type": "integer", "minimum": 8, "maximum": 18},
                        "constitution": {"type": "integer", "minimum": 8, "maximum": 18},
                        "intelligence": {"type": "integer", "minimum": 8, "maximum": 18},
                        "wisdom": {"type": "integer", "minimum": 8, "maximum": 18},
                        "charisma": {"type": "integer", "minimum": 8, "maximum": 18}
                    }
                },
                "stats": {
                    "type": "object",
                    "properties": {
                        "hp": {"type": "integer", "minimum": 1},
                        "max_hp": {"type": "integer", "minimum": 1},
                        "mp": {"type": "integer", "minimum": 0},
                        "max_mp": {"type": "integer", "minimum": 0},
                        "ac": {"type": "integer", "minimum": 8},
                        "speed": {"type": "integer", "minimum": 20},
                        "level": {"type": "integer", "minimum": 1, "maximum": 20},
                        "experience": {"type": "integer", "minimum": 0}
                    }
                }
            },
            "required": ["name", "description", "character_class", "abilities", "stats"]
        }

        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                # 创建Character对象
                character = Character()
                character.name = result.get("name", "")
                character.description = result.get("description", "")

                # 设置职业
                from data_models import CharacterClass
                try:
                    character.character_class = CharacterClass(result.get("character_class", "fighter"))
                except ValueError:
                    character.character_class = CharacterClass.FIGHTER

                # 设置能力值
                if abilities := result.get("abilities"):
                    for attr, value in abilities.items():
                        if hasattr(character.abilities, attr):
                            setattr(character.abilities, attr, value)

                # 设置属性
                if stats := result.get("stats"):
                    for attr, value in stats.items():
                        if hasattr(character.stats, attr):
                            setattr(character.stats, attr, value)

                return character
        except Exception as e:
            logger.error(f"Failed to generate character: {e}")

        return None

    @async_performance_monitor
    async def generate_monster(self, challenge_rating: float = 1.0, context: str = "") -> Optional[Monster]:
        """生成怪物"""
        # 使用PromptManager构建提示词
        prompt = prompt_manager.format_prompt(
            "monster_generation",
            player_level=int(challenge_rating * 2),  # 简单的等级转换
            difficulty="easy" if challenge_rating < 1.0 else "medium" if challenge_rating < 2.0 else "hard",
            context=context
        )

        # 使用generate_character生成基础角色，然后转换为Monster
        monster_context = f"挑战等级{challenge_rating}的怪物。{context}"
        character = await self.generate_character("monster", monster_context)
        if character:
            monster = Monster()
            # 正确复制Character的所有属性，保持对象类型
            monster.id = character.id
            monster.name = character.name
            monster.description = character.description
            monster.character_class = character.character_class
            monster.creature_type = character.creature_type
            monster.abilities = character.abilities  # 保持为Ability对象
            monster.stats = character.stats  # 保持为Stats对象
            monster.inventory = character.inventory
            monster.spells = character.spells
            monster.position = character.position

            monster.challenge_rating = challenge_rating
            monster.behavior = "aggressive"  # 默认行为

            # 根据挑战等级随机设置攻击范围，高等级怪物更可能有远程攻击
            import random
            if challenge_rating >= 2.0 and random.random() < 0.3:  # 30%概率远程攻击
                monster.attack_range = random.randint(2, 4)
            elif challenge_rating >= 1.0 and random.random() < 0.15:  # 15%概率远程攻击
                monster.attack_range = random.randint(2, 3)
            else:
                monster.attack_range = 1  # 默认近战

            return monster

        return None

    @async_performance_monitor
    async def generate_map_description(self, map_data: GameMap, context: str = "") -> str:
        """生成地图描述"""
        # 使用PromptManager构建提示词
        map_context = prompt_manager.build_map_context(map_data)
        map_context["context"] = context

        prompt = prompt_manager.format_prompt("map_description", **map_context)
        return await self._async_generate(prompt)

    @async_performance_monitor
    async def generate_quest(self, player_level: int = 1, context: str = "") -> Optional[Quest]:
        """生成任务"""
        # 使用PromptManager构建提示词
        prompt = prompt_manager.format_prompt(
            "quest_generation",
            player_level=player_level,
            context=context
        )

        # 获取对应的schema
        schema = prompt_manager.get_schema("quest_generation")

        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                quest = Quest()
                quest.title = result.get("title", "")
                quest.description = result.get("description", "")
                quest.objectives = result.get("objectives", [])
                quest.completed_objectives = [False] * len(quest.objectives)
                quest.experience_reward = result.get("experience_reward", 0)
                return quest
        except Exception as e:
            logger.error(f"Failed to generate quest: {e}")

        return None

    async def generate_narrative(self, game_state: GameState, action: str) -> str:
        """生成叙述文本"""
        prompt = f"""
        基于当前游戏状态，为玩家的行动生成叙述文本。

        玩家信息：
        - 名称：{game_state.player.name}
        - 等级：{game_state.player.stats.level}
        - 位置：{game_state.player.position}

        当前地图：{game_state.current_map.name}
        回合数：{game_state.turn_count}

        玩家行动：{action}

        请生成一段生动的叙述文本，描述行动的结果和环境变化。
        """

        return await self._async_generate(prompt)

    async def generate_opening_narrative(self, game_state: GameState) -> str:
        """生成开场叙述（结构化优先）。

        优先使用 JSON 模式仅提取 ``narrative`` 字段，减少 reasoning 模型
        将“思路说明/字数统计”等解释信息混入正文的概率；若 JSON 失败，
        自动回退到纯文本模式，保证链路可用性。
        """
        active_quest = next(
            (q for q in getattr(game_state, "quests", []) if getattr(q, "is_active", False)),
            None
        )
        if active_quest:
            quest_objectives = getattr(active_quest, "objectives", []) or []
            objective_preview = "；".join(str(x) for x in quest_objectives[:3]) if quest_objectives else "无"
            quest_info = (
                f"- 当前任务标题：{getattr(active_quest, 'title', '未知任务')}\n"
                f"- 当前任务描述：{getattr(active_quest, 'description', '无')}\n"
                f"- 当前任务目标摘要：{objective_preview}\n"
                f"- 当前任务进度：{float(getattr(active_quest, 'progress_percentage', 0.0) or 0.0):.1f}%"
            )
        else:
            quest_info = "- 当前任务：暂无活跃任务"

        prompt = f"""
        为一个DnD风格的冒险游戏生成开场叙述。

        玩家信息：
        - 名称：{game_state.player.name}
        - 职业：{game_state.player.character_class.value}
        - 等级：{game_state.player.stats.level}

        当前地图：{game_state.current_map.name}
        地图描述：{game_state.current_map.description}

        任务信息：
        {quest_info}

        请生成一段引人入胜的开场叙述（100-200字），描述玩家刚刚抵达当前场景/地图的情景，
        并将当前任务目标自然融入叙事动机中（不剧透后续细节）。

        仅在 narrative 字段中返回最终正文，不要在字段外输出任何解释。
        """

        schema = {
            "type": "object",
            "properties": {
                "narrative": {"type": "string"}
            },
            "required": ["narrative"]
        }

        try:
            result = await self._async_generate_json(prompt, schema=schema)
            narrative = (result or {}).get("narrative", "") if isinstance(result, dict) else ""
            if isinstance(narrative, str) and narrative.strip():
                return narrative.strip()
        except Exception as e:
            logger.warning(f"Opening narrative JSON mode failed, fallback to text mode: {e}")

        return await self._async_generate(prompt)

    async def generate_return_narrative(self, game_state: GameState) -> str:
        """生成重新进入游戏的叙述"""
        prompt = f"""
        为一个DnD风格的冒险游戏生成重新进入游戏的叙述。

        玩家信息：
        - 名称：{game_state.player.name}
        - 职业：{game_state.player.character_class.value}
        - 等级：{game_state.player.stats.level}
        - 当前位置：{game_state.player.position}

        当前地图：{game_state.current_map.name}
        回合数：{game_state.turn_count}

        请生成一段简短的叙述（50-100字），描述玩家重新回到游戏世界的情景，
        让玩家快速回忆起当前的状况和环境。
        """

        return await self._async_generate(prompt)

    async def generate_trap_narrative(self, game_state: GameState, trap_context: Dict[str, Any]) -> str:
        """生成陷阱触发的叙述文本"""
        try:
            # 使用PromptManager构建提示词
            player_context = prompt_manager.build_player_context(game_state.player)
            map_context = prompt_manager.build_map_context(game_state.current_map)

            # 合并所有上下文
            context = {
                **player_context,
                **map_context,
                "trap_name": trap_context.get("trap_name", "未知陷阱"),
                "trap_type": trap_context.get("trap_type", "damage"),
                "damage": trap_context.get("damage", 0),
                "damage_type": trap_context.get("damage_type", "physical"),
                "save_attempted": trap_context.get("save_attempted", False),
                "save_success": trap_context.get("save_success", False),
            }

            prompt = prompt_manager.format_prompt("trap_narrative", **context)
            
            narrative = await self._async_generate(prompt)
            
            return narrative.strip()

        except Exception as e:
            logger.error(f"Failed to generate trap narrative: {e}")
            # 返回一个更通用的默认描述
            return "你触发了一个隐藏的机关！"

    async def generate_text(self, prompt: str) -> str:
        """生成文本（通用方法）"""
        return await self._async_generate(prompt)

    async def generate_complex_content(self, prompt: str, context_data: Optional[Dict[str, Any]] = None,
                                     schema: Optional[Dict] = None, **kwargs) -> Union[str, Dict[str, Any]]:
        """
        生成复杂内容，专门处理包含大量上下文信息的请求

        Args:
            prompt: 基础提示词
            context_data: 上下文数据（地图、任务信息等）
            schema: JSON schema（如果需要JSON输出）
            **kwargs: 其他生成配置

        Returns:
            生成的内容（文本或JSON）
        """
        try:
            # 构建完整的提示词
            safe_prompt = prompt
            # 如果有上下文数据，添加到提示词中
            if context_data:
                import json
                context_json = json.dumps(context_data, ensure_ascii=False, indent=2)
                safe_prompt += f"\n\n上下文信息：\n{context_json}"

            # 根据是否需要JSON输出选择方法
            if schema:
                return await self._async_generate_json(safe_prompt, schema, **kwargs)
            else:
                return await self._async_generate(safe_prompt, **kwargs)

        except Exception as e:
            logger.error(f"Complex content generation failed: {e}")
            # 回退到基本方法
            if schema:
                return await self._async_generate_json(prompt, schema, **kwargs)
            else:
                return await self._async_generate(prompt, **kwargs)

    @staticmethod
    def _normalize_item_type(raw_type: Any) -> str:
        item_type = str(raw_type or "misc").strip().lower()
        if item_type not in {"weapon", "armor", "consumable", "misc"}:
            return "misc"
        return item_type

    @staticmethod
    def _normalize_item_rarity(raw_rarity: Any) -> str:
        rarity = str(raw_rarity or "common").strip().lower()
        if rarity not in {"common", "uncommon", "rare", "epic", "legendary"}:
            return "common"
        return rarity

    @staticmethod
    def _parse_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off"}:
            return False
        return default

    def _normalize_generated_item(self, result: Dict[str, Any], pickup_context: str) -> Item:
        item = Item()

        item_type = self._normalize_item_type(result.get("item_type"))
        rarity = self._normalize_item_rarity(result.get("rarity"))
        requested_slot = str(result.get("equip_slot", "") or "").strip()

        has_explicit_equippable = "is_equippable" in result
        is_equippable = self._parse_bool(result.get("is_equippable"), default=False)

        if not has_explicit_equippable:
            is_equippable = item_type in {"weapon", "armor"}

        if item_type == "consumable":
            is_equippable = False

        if is_equippable:
            if requested_slot in {"weapon", "armor", "accessory_1", "accessory_2"}:
                equip_slot = requested_slot
            elif item_type == "weapon":
                equip_slot = "weapon"
            elif item_type == "armor":
                equip_slot = "armor"
            else:
                equip_slot = "accessory_1"
        else:
            equip_slot = ""

        item.name = str(result.get("name") or "神秘物品")
        item.description = str(result.get("description") or "一个神秘的物品")
        item.item_type = item_type
        item.rarity = rarity
        item.value = int(result.get("value", 10) or 10)
        item.weight = float(result.get("weight", 1.0) or 1.0)

        usage_description = str(result.get("usage_description") or "").strip()
        if not usage_description:
            usage_description = "装备后自动生效" if is_equippable else "使用后触发效果"
        item.usage_description = usage_description

        hint_level = str(result.get("hint_level") or "vague").strip().lower()
        if hint_level not in {"none", "vague", "clear"}:
            hint_level = "vague"
        item.hint_level = hint_level
        item.trigger_hint = str(result.get("trigger_hint") or "").strip()
        item.risk_hint = str(result.get("risk_hint") or "").strip()

        expected_outcomes_raw = result.get("expected_outcomes", [])
        if isinstance(expected_outcomes_raw, list):
            item.expected_outcomes = [str(v).strip() for v in expected_outcomes_raw if str(v).strip()]
        elif expected_outcomes_raw:
            item.expected_outcomes = [str(expected_outcomes_raw).strip()]
        else:
            item.expected_outcomes = []

        item.requires_use_confirmation = self._parse_bool(result.get("requires_use_confirmation"), default=False)

        item.is_equippable = is_equippable
        item.equip_slot = equip_slot
        item.max_charges = int(result.get("max_charges", 0) or 0)
        item.charges = item.max_charges
        item.cooldown_turns = int(result.get("cooldown_turns", 0) or 0)
        item.current_cooldown = 0

        effect_payload = result.get("effect_payload", {})
        item.effect_payload = effect_payload if isinstance(effect_payload, dict) else {}

        properties = {}
        if isinstance(result.get("properties"), dict):
            properties.update(result["properties"])
        if result.get("damage") is not None:
            properties["damage"] = result.get("damage")
        if result.get("armor_class") is not None:
            properties["armor_class"] = result.get("armor_class")
        if result.get("healing") is not None:
            properties["healing"] = result.get("healing")
        if result.get("mana_restore") is not None:
            properties["mana_restore"] = result.get("mana_restore")
        if result.get("special_effect") is not None:
            properties["special_effect"] = result.get("special_effect")

        if item.is_equippable:
            properties["consumption_policy"] = "keep_on_use"
        elif item.item_type == "consumable":
            properties["consumption_policy"] = "consume_on_use"
        else:
            properties.setdefault("consumption_policy", "keep_on_use")

        policy = str(properties.get("consumption_policy", "") or "").strip().lower()
        if policy == "consume_on_use":
            item.consumption_hint = "通常会在成功使用后消耗"
        elif policy == "keep_on_use":
            item.consumption_hint = "通常不会被消耗，可重复使用"
        else:
            item.consumption_hint = "消耗方式由情境决定"

        if not item.trigger_hint:
            item.trigger_hint = "在当前场景中使用后触发效果"
        if not item.risk_hint:
            item.risk_hint = "风险未知，建议在安全位置尝试"
        if not item.expected_outcomes:
            if item.item_type == "consumable":
                item.expected_outcomes = ["可能恢复状态", "可能施加短时增益", "可能产生环境互动"]
            else:
                item.expected_outcomes = ["可能改变当前状态", "可能触发剧情或环境反馈"]

        item.properties = properties
        item.llm_generated = True
        item.generation_context = pickup_context

        return item

    def _normalize_item_usage_response(self, item: Item, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        response = dict(raw_response or {})
        response.setdefault("message", f"使用了{item.name}")

        events = response.get("events")
        if isinstance(events, list):
            response["events"] = [str(event) for event in events]
        elif events:
            response["events"] = [str(events)]
        else:
            response["events"] = []

        if not isinstance(response.get("effects"), dict):
            response["effects"] = {}

        policy = str((item.properties or {}).get("consumption_policy", "") or "").strip().lower()

        if item.is_equippable or item.item_type in {"weapon", "armor"}:
            response["item_consumed"] = False
            return response

        if "item_consumed" in response:
            response["item_consumed"] = self._parse_bool(response.get("item_consumed"), default=False)
        elif policy in {"consume_on_use", "keep_on_use"}:
            response["item_consumed"] = policy == "consume_on_use"
        else:
            response["item_consumed"] = item.item_type == "consumable"

        return response

    async def generate_item_on_pickup(self, game_state: GameState,
                                    pickup_context: str = "") -> Optional[Item]:
        """在拾取时生成物品"""
        player_context = prompt_manager.build_player_context(game_state.player)
        map_context = prompt_manager.build_map_context(game_state.current_map)

        context = {**player_context, **map_context, "pickup_context": pickup_context}

        prompt = prompt_manager.format_prompt("item_pickup_generation", **context)
        schema = prompt_manager.get_schema("item_pickup_generation")

        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                return self._normalize_generated_item(result, pickup_context)
        except Exception as e:
            logger.error(f"生成物品失败: {e}")

        return None

    async def process_item_usage(self, game_state: GameState, item: Item) -> Dict[str, Any]:
        """处理物品使用，返回效果数据"""
        # 使用PromptManager构建提示词
        player_context = prompt_manager.build_player_context(game_state.player)
        item_context = prompt_manager.build_item_context(item)

        # 构建地图状态信息
        map_info = {
            "name": game_state.current_map.name,
            "description": game_state.current_map.description,
            "depth": game_state.current_map.depth,
            "player_position": game_state.player.position,
            "nearby_terrain": self._get_nearby_terrain(game_state, game_state.player.position[0], game_state.player.position[1])
        }

        # 合并所有上下文
        context = {**player_context, **item_context, "map_info": map_info}

        prompt = prompt_manager.format_prompt("item_usage_effect", **context)

        # 定义物品使用效果的JSON schema（扩展版）
        schema = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "effect_scope": {"type": "string", "enum": ["active_use", "equip_passive", "trigger"]},
                "source": {"type": "string"},
                "events": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "item_consumed": {"type": "boolean"},
                "hint_level": {"type": "string", "enum": ["none", "vague", "clear"]},
                "trigger_hint": {"type": "string"},
                "risk_hint": {"type": "string"},
                "expected_outcomes": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "requires_use_confirmation": {"type": "boolean"},
                "consumption_hint": {"type": "string"},
                "effects": {
                    "type": "object",
                    "properties": {
                        "stat_changes": {
                            "type": "object",
                            "properties": {
                                "hp": {"type": "integer"},
                                "mp": {"type": "integer"},
                                "experience": {"type": "integer"},
                                "max_hp": {"type": "integer"},
                                "max_mp": {"type": "integer"},
                                "ac": {"type": "integer"},
                                "speed": {"type": "integer"}
                            }
                        },
                        "ability_changes": {
                            "type": "object",
                            "properties": {
                                "strength": {"type": "integer"},
                                "dexterity": {"type": "integer"},
                                "constitution": {"type": "integer"},
                                "intelligence": {"type": "integer"},
                                "wisdom": {"type": "integer"},
                                "charisma": {"type": "integer"}
                            }
                        },
                        "teleport": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["random", "specific", "stairs"]},
                                "x": {"type": "integer"},
                                "y": {"type": "integer"}
                            }
                        },
                        "map_changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "terrain": {"type": "string"},
                                    "add_items": {"type": "array", "items": {"type": "object"}}
                                }
                            }
                        },
                        "inventory_changes": {
                            "type": "object",
                            "properties": {
                                "add_items": {"type": "array", "items": {"type": "object"}},
                                "remove_items": {"type": "array", "items": {"type": "string"}}
                            }
                        },
                        "apply_status_effects": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "effect_type": {"type": "string"},
                                    "duration_turns": {"type": "integer"},
                                    "stacks": {"type": "integer"},
                                    "max_stacks": {"type": "integer"},
                                    "stack_policy": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "potency": {"type": "object"},
                                    "modifiers": {"type": "object"},
                                    "tick_effects": {"type": "object"},
                                    "triggers": {"type": "object"},
                                    "metadata": {"type": "object"}
                                },
                                "required": ["name", "effect_type", "duration_turns"]
                            }
                        },
                        "remove_status_effects": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "effect_type": {"type": "string"},
                                    "tag": {"type": "string"}
                                }
                            }
                        },
                        "special_effects": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "code": {"type": "string"}
                                        },
                                        "required": ["code"]
                                    }
                                ]
                            }
                        }
                    }
                }
            },
            "required": ["message", "events", "item_consumed", "effects"]
        }

        try:
            result = await self._async_generate_json(prompt, schema)
            normalized = self._normalize_item_usage_response(item, result or {})
            normalized.setdefault("effect_scope", "active_use")
            normalized.setdefault("source", f"item_use:{item.id}")
            normalized.setdefault("hint_level", item.hint_level or "vague")
            normalized.setdefault("trigger_hint", item.trigger_hint or "")
            normalized.setdefault("risk_hint", item.risk_hint or "")
            normalized.setdefault("expected_outcomes", item.expected_outcomes or [])
            normalized.setdefault("requires_use_confirmation", bool(item.requires_use_confirmation))
            normalized.setdefault("consumption_hint", item.consumption_hint or "")
            logger.info(f"物品使用LLM响应: {normalized}")
            return normalized
        except Exception as e:
            logger.error(f"处理物品使用失败: {e}")
            fallback = {
                "message": f"使用{item.name}时发生了意外",
                "effect_scope": "active_use",
                "source": f"item_use:{item.id}",
                "events": ["物品使用失败"],
                "item_consumed": False,
                "hint_level": item.hint_level or "vague",
                "trigger_hint": item.trigger_hint or "",
                "risk_hint": item.risk_hint or "",
                "expected_outcomes": item.expected_outcomes or [],
                "requires_use_confirmation": bool(item.requires_use_confirmation),
                "consumption_hint": item.consumption_hint or "",
                "effects": {}
            }
            return self._normalize_item_usage_response(item, fallback)

    def get_last_request_payload(self) -> Optional[Dict[str, Any]]:
        """获取最后一次发送给LLM的请求报文。

        注意：在并发请求的环境下，这个方法返回的报文可能不完全准确，
        因为它只保留了最后一次完成的请求的报文。
        在串行调用的场景下（例如测试脚本），这是可靠的。
        """
        import copy

        # OpenRouter客户端有last_request_payload属性
        if hasattr(self.client, 'last_request_payload'):
            return copy.deepcopy(self.client.last_request_payload)

        # OpenAI API工具类没有内置的请求跟踪，返回None
        # 如果需要，可以在OpenAIAPITool中添加类似的功能
        return None

    def get_last_response_payload(self) -> Optional[Dict[str, Any]]:
        """获取最后一次LLM的响应报文。

        注意：在并发请求的环境下，这个方法返回的报文可能不完全准确，
        因为它只保留了最后一次完成的请求的响应。
        在串行调用的场景下（例如测试脚本），这是可靠的。
        """
        import copy

        # OpenRouter客户端有last_response_payload属性
        if hasattr(self.client, 'last_response_payload'):
            return copy.deepcopy(self.client.last_response_payload)

        # OpenAI API工具类没有内置的响应跟踪，返回None
        # 如果需要，可以在OpenAIAPITool中添加类似的功能
        return None
    def _get_nearby_terrain(self, game_state: GameState, x: int, y: int, radius: int = 2) -> List[str]:
        """获取周围地形信息"""
        terrain_list = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = x + dx, y + dy
                if (0 <= nx < game_state.current_map.width and
                    0 <= ny < game_state.current_map.height):
                    tile = game_state.current_map.get_tile(nx, ny)
                    if tile:
                        terrain_list.append(f"({nx},{ny}):{tile.terrain.value}")
        return terrain_list

    def close(self):
        """关闭服务"""
        # 不再需要手动关闭executor，由async_task_manager统一管理
        logger.info("LLMService close() called - executor managed by AsyncTaskManager")


# 全局LLM服务实例
llm_service = LLMService()

__all__ = ["LLMService", "llm_service"]
