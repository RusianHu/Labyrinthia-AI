"""
gemini_api.py - Google Gemini API SDK 版本
基于 google-genai 1.20.0 实现
"""

import base64
import json
import os
from typing import List, Dict, Optional, Tuple, Union, Any

from google import genai
from google.genai import types


# =============================================================================
# 配置常量 - Configuration Constants
# =============================================================================

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
    """Google Gemini API SDK 客户端，基于 google-genai 1.20.0 实现"""

    def __init__(
        self,
        api_key: str,
        *,
        proxy: Optional[str] = None,
        api_version: str = "v1beta",
        # 兼容旧版参数
        endpoint: Optional[str] = None,
        default_timeout: Optional[int] = None,
        proxies: Optional[Dict[str, str]] = None,
        use_vertex_ai: bool = False,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        """
        初始化 Gemini API 客户端

        Args:
            api_key: Google API 密钥
            proxy: 代理服务器地址 (可选)
            api_version: API 版本 (默认 v1beta)
            endpoint: API端点（兼容性参数，已忽略）
            default_timeout: 默认超时时间（兼容性参数，已忽略）
            proxies: 代理配置字典（兼容性参数）
            use_vertex_ai: 是否使用 Vertex AI（兼容性参数，已忽略）
            project_id: Google Cloud 项目 ID（兼容性参数，已忽略）
            location: 区域位置（兼容性参数，已忽略）
        """
        self.api_key = api_key
        self.last_request_payload: Optional[dict] = None  # 兼容性属性

        # 处理代理配置（兼容旧版）
        if proxies:
            # 旧版使用 proxies 字典
            if "http" in proxies:
                os.environ['HTTP_PROXY'] = proxies["http"]
            if "https" in proxies:
                os.environ['HTTPS_PROXY'] = proxies["https"]
        elif proxy:
            # 新版使用 proxy 字符串
            os.environ['HTTPS_PROXY'] = proxy
            os.environ['HTTP_PROXY'] = proxy

        # 创建客户端
        http_options = types.HttpOptions(api_version=api_version) if api_version != "v1beta" else None
        self.client = genai.Client(api_key=api_key, http_options=http_options)

    # ---------------------------------------------------------------------
    # 内部辅助方法
    # ---------------------------------------------------------------------
    def _convert_generation_config(self, config: Optional[dict]) -> Optional[types.GenerateContentConfig]:
        """将字典格式的生成配置转换为 SDK 类型"""
        if not config:
            return None

        # 映射字段名称
        sdk_config = {}
        field_mapping = {
            'maxOutputTokens': 'max_output_tokens',
            'temperature': 'temperature',
            'topP': 'top_p',
            'topK': 'top_k',
            'candidateCount': 'candidate_count',
            'stopSequences': 'stop_sequences',
            'responseMimeType': 'response_mime_type',
            'responseSchema': 'response_schema',
            'responseModalities': 'response_modalities',
        }

        for old_key, new_key in field_mapping.items():
            if old_key in config:
                sdk_config[new_key] = config[old_key]

        return types.GenerateContentConfig(**sdk_config)

    def _convert_safety_settings(self, settings: Optional[list]) -> Optional[List[types.SafetySetting]]:
        """转换安全设置"""
        if not settings:
            return None

        result = []
        for setting in settings:
            result.append(types.SafetySetting(
                category=setting.get('category'),
                threshold=setting.get('threshold')
            ))
        return result

    def _sdk_response_to_dict(self, response) -> dict:
        """将 SDK 响应转换为字典格式，保持与 REST 版本兼容"""
        try:
            # 构建兼容的响应格式
            result = {
                "candidates": [],
                "usageMetadata": {}
            }

            # 处理简单的文本响应
            if hasattr(response, 'text') and response.text:
                result["candidates"].append({
                    "content": {
                        "parts": [{"text": response.text}],
                        "role": "model"
                    },
                    "finishReason": "STOP",
                    "index": 0
                })
            elif hasattr(response, 'candidates') and response.candidates:
                for i, candidate in enumerate(response.candidates):
                    candidate_dict = {
                        "content": {
                            "parts": [],
                            "role": "model"
                        },
                        "finishReason": str(getattr(candidate, 'finish_reason', 'STOP')),
                        "index": i
                    }

                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text:
                                    candidate_dict["content"]["parts"].append({"text": part.text})
                                elif hasattr(part, 'inline_data'):
                                    candidate_dict["content"]["parts"].append({
                                        "inline_data": {
                                            "mime_type": part.inline_data.mime_type,
                                            "data": part.inline_data.data
                                        }
                                    })

                    # 如果没有找到内容，但候选项存在，尝试从候选项直接获取文本
                    if not candidate_dict["content"]["parts"] and hasattr(candidate, 'text') and candidate.text:
                        candidate_dict["content"]["parts"].append({"text": candidate.text})

                    result["candidates"].append(candidate_dict)

            # 添加使用元数据
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                result["usageMetadata"] = {
                    "promptTokenCount": getattr(usage, 'prompt_token_count', 0),
                    "candidatesTokenCount": getattr(usage, 'response_token_count', 0),
                    "totalTokenCount": getattr(usage, 'total_token_count', 0)
                }

            return result
        except Exception as e:
            # 如果转换失败，返回基本格式
            text_content = str(response)
            if hasattr(response, 'text'):
                text_content = response.text
            return {
                "candidates": [{"content": {"parts": [{"text": text_content}], "role": "model"}}],
                "usageMetadata": {}
            }

    # ---------------------------------------------------------------------
    # 公共方法 - 保持与 REST 版本相同的接口
    # ---------------------------------------------------------------------
    def single_turn(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """单轮对话"""
        # 记录请求负载（兼容性）
        self.last_request_payload = {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generation_config": generation_config
        }

        # 处理编码转换（如果需要）
        processed_text = text
        try:
            # 导入编码转换器（延迟导入避免循环依赖）
            from encoding_utils import encoding_converter
            if encoding_converter.enabled:
                processed_text = encoding_converter.process_text(text)
        except ImportError:
            # 如果编码转换器不可用，使用原始文本
            pass
        except Exception as e:
            # 如果编码转换失败，使用原始文本
            print(f"Encoding conversion failed, using original text: {e}")

        config = self._convert_generation_config(generation_config)

        response = self.client.models.generate_content(
            model=model,
            contents=processed_text,
            config=config
        )

        return self._sdk_response_to_dict(response)

    def single_turn_json(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        schema: Optional[dict] = None,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """强制 JSON 输出的单轮对话"""
        # 记录请求负载（兼容性）
        gen_cfg = generation_config.copy() if generation_config else {}
        gen_cfg['response_mime_type'] = 'application/json'
        if schema:
            gen_cfg['response_schema'] = schema

        self.last_request_payload = {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generation_config": gen_cfg
        }

        # 处理编码转换（如果需要）
        processed_text = text
        try:
            # 导入编码转换器（延迟导入避免循环依赖）
            from encoding_utils import encoding_converter
            if encoding_converter.enabled:
                processed_text = encoding_converter.process_text(text)
        except ImportError:
            # 如果编码转换器不可用，使用原始文本
            pass
        except Exception as e:
            # 如果编码转换失败，使用原始文本
            print(f"Encoding conversion failed, using original text: {e}")

        config = self._convert_generation_config(gen_cfg)

        response = self.client.models.generate_content(
            model=model,
            contents=processed_text,
            config=config
        )

        return self._sdk_response_to_dict(response)

    # ---------------------------- ChatSession ----------------------------
    class ChatSession:
        """多轮对话会话，基于 SDK 的 Chat 实现"""

        def __init__(
            self,
            _parent: "GeminiAPI",
            model: str,
            system_prompt: str = "",
            generation_config: Optional[dict] = None,
        ):
            self._parent = _parent
            self.model = model
            self._gen_cfg = generation_config or {}
            self._system_prompt = system_prompt

            # 创建 SDK 聊天会话
            self._chat = _parent.client.chats.create(model=model)

            # 如果有系统提示，先发送一条系统消息
            if system_prompt:
                try:
                    # 发送系统提示作为第一条消息
                    self._chat.send_message(f"System: {system_prompt}")
                except:
                    # 如果失败，忽略错误
                    pass

        @property
        def history(self) -> List[dict]:
            """获取对话历史"""
            history = []

            # 添加系统提示（如果有）
            if self._system_prompt:
                history.append({
                    "role": "system",
                    "parts": [{"text": self._system_prompt}]
                })

            # 获取 SDK 聊天历史并转换格式
            if hasattr(self._chat, 'history'):
                for content in self._chat.history:
                    if hasattr(content, 'role') and hasattr(content, 'parts'):
                        parts = []
                        for part in content.parts:
                            if hasattr(part, 'text'):
                                parts.append({"text": part.text})
                        history.append({
                            "role": content.role,
                            "parts": parts
                        })

            return history

        def send(self, text: str, **gen_cfg) -> dict:
            """发送消息并返回响应"""
            try:
                # 合并生成配置
                merged_cfg = {**self._gen_cfg, **gen_cfg}
                config = self._parent._convert_generation_config(merged_cfg) if merged_cfg else None

                # 发送消息
                response = self._chat.send_message(text, config=config)

                # 转换响应格式
                return self._parent._sdk_response_to_dict(response)

            except Exception as e:
                # 错误处理
                return {
                    "candidates": [{
                        "content": {
                            "parts": [{"text": f"[Error: {str(e)}]"}],
                            "role": "model"
                        },
                        "finishReason": "ERROR"
                    }],
                    "usageMetadata": {}
                }

    def start_chat(
        self,
        model: str = DEFAULT_TEXT_MODEL,
        *,
        system_prompt: str = "",
        generation_config: Optional[dict] = None,
    ) -> "GeminiAPI.ChatSession":
        """创建多轮对话会话"""
        return self.ChatSession(
            self, model, system_prompt=system_prompt, generation_config=generation_config
        )

    # --------------------------- 多模态功能 ---------------------------
    def multimodal_input(
        self,
        *,
        model: str = DEFAULT_VISION_MODEL,
        text: str = "",
        image_path: Optional[str] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """文本 + 图像输入 → 文本输出"""
        contents = []

        # 添加文本部分
        if text:
            contents.append(text)

        # 添加图像部分
        if image_path:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            contents.append(image_part)

        config = self._convert_generation_config(generation_config)

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        return self._sdk_response_to_dict(response)

    def multimodal_in_out(
        self,
        *,
        prompt: str,
        model: str = DEFAULT_IMAGE_GEN_MODEL,
        reference_images: Optional[List[str]] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> Tuple[List[str], dict]:
        """提示词 + 参考图像 → 生成图像 + 原始响应

        Returns:
            images: base64 编码的图像字符串列表
            resp: 原始 API 响应
        """
        contents = [prompt]

        # 添加参考图像
        reference_images = reference_images or []
        for img_path in reference_images:
            with open(img_path, 'rb') as f:
                image_bytes = f.read()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            contents.append(image_part)

        # 配置多模态输出
        gen_cfg = generation_config.copy() if generation_config else {}
        gen_cfg['response_modalities'] = ['IMAGE', 'TEXT']

        config = self._convert_generation_config(gen_cfg)

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        # 提取生成的图像
        images = []
        resp_dict = self._sdk_response_to_dict(response)

        if resp_dict.get("candidates"):
            candidate = resp_dict["candidates"][0]
            if candidate.get("content", {}).get("parts"):
                for part in candidate["content"]["parts"]:
                    if "inline_data" in part:
                        inline_data = part["inline_data"]
                        if inline_data.get("mime_type", "").startswith("image/"):
                            images.append(inline_data["data"])

        return images, resp_dict

    def generate_image(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGEN_MODEL,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        person_generation: str = DEFAULT_PERSON_GENERATION,
    ) -> List[str]:
        """使用 Imagen 3 生成图像

        注意：Imagen 模型仅支持英文提示词
        """
        try:
            config = types.GenerateImagesConfig(
                number_of_images=sample_count,
                aspect_ratio=aspect_ratio,
                person_generation=person_generation,
                output_mime_type='image/png'
            )

            response = self.client.models.generate_images(
                model=model,
                prompt=prompt,
                config=config
            )

            # 提取 base64 图像数据
            images_base64 = []
            if hasattr(response, 'generated_images'):
                for generated_image in response.generated_images:
                    if hasattr(generated_image, 'image') and hasattr(generated_image.image, 'image_bytes'):
                        # 将图像字节转换为 base64
                        image_b64 = base64.b64encode(generated_image.image.image_bytes).decode()
                        images_base64.append(image_b64)

            return images_base64

        except Exception as e:
            # 如果 SDK 方法不可用，返回空列表
            print(f"Warning: generate_image failed: {e}")
            return []

    # ------------------------------ 其他功能 ---------------------------------
    def embed_text(
        self,
        text: str,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        task_type: str = DEFAULT_TASK_TYPE,
    ) -> List[float]:
        """获取文本的嵌入向量"""
        try:
            config = types.EmbedContentConfig(
                task_type=task_type
            )

            response = self.client.models.embed_content(
                model=model,
                contents=text,
                config=config
            )

            # 提取嵌入向量
            if hasattr(response, 'embeddings') and response.embeddings:
                embedding = response.embeddings[0]
                if hasattr(embedding, 'values'):
                    return embedding.values

            return []

        except Exception as e:
            print(f"Warning: embed_text failed: {e}")
            return []

    def generate_content_stream(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        """
        流式生成文本内容（兼容性方法）

        Args:
            prompt: 输入提示
            model: 模型名称
            system_instruction: 系统指令
            max_output_tokens: 最大输出令牌数
            temperature: 温度参数

        Yields:
            生成的文本块
        """
        config = types.GenerateContentConfig()

        if system_instruction:
            config.system_instruction = system_instruction
        if max_output_tokens:
            config.max_output_tokens = max_output_tokens
        if temperature is not None:
            config.temperature = temperature

        try:
            for chunk in self.client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=config
            ):
                if hasattr(chunk, 'text') and chunk.text:
                    yield chunk.text
        except Exception as e:
            print(f"Stream generation failed: {e}")
            yield f"[Stream error: {e}]"

    def count_tokens(
        self,
        text: str,
        *,
        model: str = DEFAULT_TEXT_MODEL,
    ) -> Any:
        """
        计算文本的令牌数（兼容性方法）

        Args:
            text: 输入文本
            model: 模型名称

        Returns:
            令牌计数结果
        """
        try:
            response = self.client.models.count_tokens(
                model=model,
                contents=text
            )
            return response
        except Exception as e:
            print(f"Token counting failed: {e}")
            return {"total_tokens": 0}

    def list_models(self) -> dict:
        """列出可用模型"""
        try:
            models = []
            for model in self.client.models.list():
                model_dict = {
                    "name": getattr(model, 'name', ''),
                    "displayName": getattr(model, 'display_name', ''),
                    "description": getattr(model, 'description', ''),
                    "supportedGenerationMethods": getattr(model, 'supported_generation_methods', [])
                }
                models.append(model_dict)

            return {"models": models}

        except Exception as e:
            print(f"Warning: list_models failed: {e}")
            return {"models": []}


# 兼容性别名 - 保持向后兼容
GeminiAPISDK = GeminiAPI