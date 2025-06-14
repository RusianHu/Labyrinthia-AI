"""
gemini_api_sdk.py
使用最新的 Google Gen AI SDK 重构的 Gemini API 工具类
"""

import base64
import time
import os
from typing import List, Dict, Optional, Tuple, Union, Any
from pathlib import Path

from google import genai
from google.genai import types


# =============================================================================
# 配置常量 - Configuration Constants
# =============================================================================

# API 端点配置 - API Endpoint Configuration (为了兼容性保留)
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


class GeminiAPI:
    """使用最新 Google Gen AI SDK 的 Gemini API 客户端，兼容原REST版本接口"""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        api_version: str = DEFAULT_API_VERSION,
        default_timeout: int = DEFAULT_TIMEOUT,
        proxies: Optional[Dict[str, str]] = None,
        use_vertex_ai: bool = False,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        """
        初始化 Gemini API 客户端

        Args:
            api_key: API 密钥
            endpoint: API端点（为兼容性保留，SDK中不使用）
            api_version: API版本（为兼容性保留，SDK中不使用）
            default_timeout: 默认超时时间
            proxies: 代理配置
            use_vertex_ai: 是否使用 Vertex AI（默认使用 Gemini Developer API）
            project_id: Google Cloud 项目 ID（仅在使用 Vertex AI 时需要）
            location: 区域位置（仅在使用 Vertex AI 时需要）
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/") if endpoint else DEFAULT_ENDPOINT
        self.api_version = api_version
        self.default_timeout = default_timeout
        self.proxies = proxies or {}
        self.use_vertex_ai = use_vertex_ai
        self.last_request_payload: Optional[dict] = None  # 兼容性属性

        # 设置代理环境变量（如果提供了代理配置）
        if self.proxies:
            if "http" in self.proxies:
                os.environ["HTTP_PROXY"] = self.proxies["http"]
            if "https" in self.proxies:
                os.environ["HTTPS_PROXY"] = self.proxies["https"]

        if use_vertex_ai:
            if not project_id:
                raise ValueError("使用 Vertex AI 时必须提供 project_id")
            # 使用 Vertex AI 客户端
            self.client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location or "us-central1"
            )
        else:
            # 使用 Gemini Developer API 客户端
            self.client = genai.Client(api_key=api_key)

    # ---------------------------------------------------------------------
    # 基础文本生成方法
    # ---------------------------------------------------------------------
    def single_turn(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """
        单轮对话生成

        Args:
            model: 模型名称
            text: 输入文本
            generation_config: 生成配置字典

        Returns:
            包含生成内容的响应字典
        """
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

        config = types.GenerateContentConfig()

        if generation_config:
            if generation_config.get('max_output_tokens'):
                config.max_output_tokens = generation_config['max_output_tokens']
            if generation_config.get('temperature') is not None:
                config.temperature = generation_config['temperature']
            if generation_config.get('top_p') is not None:
                config.top_p = generation_config['top_p']
            if generation_config.get('top_k') is not None:
                config.top_k = generation_config['top_k']
            if generation_config.get('stop_sequences'):
                config.stop_sequences = generation_config['stop_sequences']

        response = self.client.models.generate_content(
            model=model,
            contents=processed_text,
            config=config
        )

        # 获取响应文本 - SDK 响应有 text 属性，但可能为 None
        response_text = ""
        if hasattr(response, 'text') and response.text is not None:
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            # 如果 text 为 None，尝试从 candidates 中提取
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                if hasattr(candidate.content, 'parts') and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text is not None:
                            response_text += part.text

        # 返回与 REST 版本兼容的格式
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": response_text}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }

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
        流式生成文本内容
        
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
            
        for chunk in self.client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=config
        ):
            yield chunk.text

    # ---------------------------------------------------------------------
    # JSON 结构化输出
    # ---------------------------------------------------------------------
    def single_turn_json(
        self,
        *,
        model: str = DEFAULT_TEXT_MODEL,
        text: str,
        schema: Optional[dict] = None,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """
        强制 JSON 输出的单轮对话

        Args:
            model: 模型名称
            text: 输入文本
            schema: JSON 模式
            generation_config: 生成配置字典

        Returns:
            包含 JSON 内容的响应字典
        """
        # 构造生成配置
        gen_cfg = {"response_mime_type": "application/json"}
        if generation_config:
            gen_cfg.update(generation_config)
        if schema:
            gen_cfg["response_schema"] = schema

        # 记录请求负载（兼容性）
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

        config = types.GenerateContentConfig(
            response_mime_type="application/json"
        )

        if gen_cfg.get('max_output_tokens'):
            config.max_output_tokens = gen_cfg['max_output_tokens']
        if gen_cfg.get('temperature') is not None:
            config.temperature = gen_cfg['temperature']
        if gen_cfg.get('top_p') is not None:
            config.top_p = gen_cfg['top_p']
        if gen_cfg.get('top_k') is not None:
            config.top_k = gen_cfg['top_k']
        if schema:
            config.response_schema = schema

        response = self.client.models.generate_content(
            model=model,
            contents=processed_text,
            config=config
        )

        # 获取响应文本 - SDK 响应有 text 属性
        response_text = response.text if hasattr(response, 'text') else ""

        # 返回与 REST 版本兼容的格式
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": response_text}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }

    # ---------------------------------------------------------------------
    # 聊天会话
    # ---------------------------------------------------------------------
    def start_chat(
        self,
        model: str = DEFAULT_TEXT_MODEL,
        *,
        system_prompt: str = "",
        generation_config: Optional[dict] = None,
    ) -> "GeminiAPISDK.ChatSession":
        """
        创建聊天会话

        Args:
            model: 模型名称
            system_prompt: 系统提示
            generation_config: 生成配置字典

        Returns:
            聊天会话对象
        """
        return self.ChatSession(
            self.client,
            model=model,
            system_prompt=system_prompt,
            generation_config=generation_config,
        )

    # ---------------------------------------------------------------------
    # 多模态功能
    # ---------------------------------------------------------------------
    def multimodal_input(
        self,
        *,
        model: str = DEFAULT_VISION_MODEL,
        text: str = "",
        image_path: Optional[str] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> dict:
        """
        多模态输入：文本 + (可选) 图片 → 文本

        Args:
            model: 模型名称
            text: 输入文本
            image_path: 图片文件路径
            mime_type: MIME 类型
            generation_config: 生成配置字典

        Returns:
            包含生成内容的响应字典
        """
        # 构建内容部分
        contents = []

        if text:
            contents.append(text)

        if image_path:
            # 读取图片文件
            with open(image_path, 'rb') as f:
                image_bytes = f.read()

            # 自动检测 MIME 类型
            if not mime_type or mime_type == DEFAULT_MIME_TYPE:
                path = Path(image_path)
                ext = path.suffix.lower()
                mime_map = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp',
                }
                mime_type = mime_map.get(ext, 'image/jpeg')

            # 创建图片部分
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type
            )
            contents.append(image_part)

        config = types.GenerateContentConfig()
        if generation_config:
            if generation_config.get('max_output_tokens'):
                config.max_output_tokens = generation_config['max_output_tokens']
            if generation_config.get('temperature') is not None:
                config.temperature = generation_config['temperature']
            if generation_config.get('top_p') is not None:
                config.top_p = generation_config['top_p']
            if generation_config.get('top_k') is not None:
                config.top_k = generation_config['top_k']

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        # 获取响应文本 - SDK 响应有 text 属性
        response_text = response.text if hasattr(response, 'text') else ""

        # 返回与 REST 版本兼容的格式
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": response_text}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }

    # ---------------------------------------------------------------------
    # 图像生成
    # ---------------------------------------------------------------------
    def generate_image(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGEN_MODEL,
        sample_count: int = DEFAULT_SAMPLE_COUNT,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        person_generation: str = DEFAULT_PERSON_GENERATION,
    ) -> List[str]:
        """
        使用 Imagen 3 生成图像

        Args:
            prompt: 图像生成提示
            model: 模型名称
            sample_count: 生成图像数量
            aspect_ratio: 宽高比
            person_generation: 人物生成设置

        Returns:
            base64 编码的图像列表
        """
        config = types.GenerateImagesConfig(
            number_of_images=sample_count,
            include_rai_reason=True,
            output_mime_type="image/png",
        )

        try:
            response = self.client.models.generate_images(
                model=model,
                prompt=prompt,
                config=config
            )

            # 提取 base64 图像数据
            images_base64 = []
            for generated_image in response.generated_images:
                # 获取 Image 对象
                image = generated_image.image

                # 检查 image_bytes 属性（这是正确的方式）
                if hasattr(image, 'image_bytes') and image.image_bytes:
                    # 将字节数据转换为 base64
                    images_base64.append(base64.b64encode(image.image_bytes).decode())
                elif hasattr(image, 'data') and image.data:
                    # 如果已经是 base64 数据
                    images_base64.append(image.data)
                else:
                    print(f"警告: 无法从图像对象中提取数据，类型: {type(image)}")
                    print(f"可用属性: {[attr for attr in dir(image) if not attr.startswith('_')]}")

            return images_base64

        except Exception as e:
            # 如果 SDK 方法不可用，尝试使用回退方法
            print(f"SDK 图像生成失败，尝试使用回退方法: {e}")
            return self._generate_image_rest(prompt, model, sample_count, aspect_ratio, person_generation)

    def _generate_image_rest(
        self,
        prompt: str,
        model: str,
        sample_count: int,
        aspect_ratio: str,
        person_generation: str,
    ) -> List[str]:
        """使用 SDK 生成图像的回退方法（已弃用 REST 实现）"""
        # 现在完全使用 SDK 实现，不再使用 REST API
        try:
            # 使用标准的 SDK 图像生成配置
            config = types.GenerateImagesConfig(
                number_of_images=sample_count,
                include_rai_reason=True,
                output_mime_type="image/png",
            )

            response = self.client.models.generate_images(
                model=model,
                prompt=prompt,
                config=config
            )

            # 提取 base64 图像数据
            images_base64 = []
            for generated_image in response.generated_images:
                # 获取 Image 对象
                image = generated_image.image

                # 检查 image_bytes 属性（这是正确的方式）
                if hasattr(image, 'image_bytes') and image.image_bytes:
                    # 将字节数据转换为 base64
                    images_base64.append(base64.b64encode(image.image_bytes).decode())
                elif hasattr(image, 'data') and image.data:
                    # 如果已经是 base64 数据
                    images_base64.append(image.data)
                else:
                    print(f"警告: 无法从图像对象中提取数据，类型: {type(image)}")
                    print(f"可用属性: {[attr for attr in dir(image) if not attr.startswith('_')]}")

            return images_base64

        except Exception as e:
            print(f"SDK 图像生成失败: {e}")
            return []

    # ---------------------------------------------------------------------
    # 文本嵌入
    # ---------------------------------------------------------------------
    def embed_text(
        self,
        text: str,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        task_type: str = DEFAULT_TASK_TYPE,
    ) -> List[float]:
        """
        生成文本嵌入

        Args:
            text: 输入文本
            model: 嵌入模型名称
            task_type: 任务类型

        Returns:
            嵌入向量列表
        """
        response = self.client.models.embed_content(
            model=model,
            contents=text,
        )

        # 返回与 REST 版本兼容的格式
        if hasattr(response, 'embedding') and hasattr(response.embedding, 'values'):
            return response.embedding.values
        elif hasattr(response, 'embeddings') and len(response.embeddings) > 0:
            return response.embeddings[0].values
        else:
            # 如果结构不同，尝试直接返回
            return response

    def multimodal_in_out(
        self,
        *,
        prompt: str,
        model: str = DEFAULT_VISION_MODEL,  # 使用视觉模型而不是图像生成模型
        reference_images: Optional[List[str]] = None,
        mime_type: str = DEFAULT_MIME_TYPE,
        generation_config: Optional[dict] = None,
    ) -> Tuple[List[str], dict]:
        """
        多模态输入输出：提示 (+ 参考图片) → 生成图片 + 原始响应

        Args:
            prompt: 图像生成提示
            model: 模型名称
            reference_images: 参考图片路径列表
            mime_type: MIME 类型
            generation_config: 生成配置字典

        Returns:
            images: base64 编码的图片列表
            resp: 原始 JSON 响应
        """
        # 构建内容部分
        contents = [prompt]

        reference_images = reference_images or []
        for img_path in reference_images:
            with open(img_path, 'rb') as f:
                image_bytes = f.read()

            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type
            )
            contents.append(image_part)

        # 配置生成参数
        gen_cfg = generation_config or {}

        config = types.GenerateContentConfig()
        if gen_cfg.get('max_output_tokens'):
            config.max_output_tokens = gen_cfg['max_output_tokens']
        if gen_cfg.get('temperature') is not None:
            config.temperature = gen_cfg['temperature']
        if gen_cfg.get('top_p') is not None:
            config.top_p = gen_cfg['top_p']
        if gen_cfg.get('top_k') is not None:
            config.top_k = gen_cfg['top_k']

        try:
            # 注意：多模态输出（生成图像）需要使用专门的图像生成模型
            # 这里我们使用 generate_content 进行文本生成，如果需要图像生成，应该使用 generate_images
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            # 提取文本响应
            response_text = response.text if hasattr(response, 'text') else ""

            # 检查响应中是否包含图像（目前 SDK 可能不直接支持多模态输出）
            imgs: List[str] = []

            # 如果需要图像生成，建议使用单独的 generate_images 方法
            if "生成图像" in prompt or "generate image" in prompt.lower():
                try:
                    # 尝试使用图像生成
                    image_response = self.client.models.generate_images(
                        model=DEFAULT_IMAGEN_MODEL,
                        prompt=prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            include_rai_reason=True,
                            output_mime_type="image/png",
                        )
                    )

                    # 提取生成的图像
                    for generated_image in image_response.generated_images:
                        image = generated_image.image
                        if hasattr(image, 'image_bytes') and image.image_bytes:
                            imgs.append(base64.b64encode(image.image_bytes).decode())
                        elif hasattr(image, 'data') and image.data:
                            imgs.append(image.data)

                except Exception as img_e:
                    print(f"图像生成失败: {img_e}")

            resp = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": response_text}]
                        },
                        "finishReason": "STOP"
                    }
                ]
            }

            return imgs, resp

        except Exception as e:
            # 如果 SDK 调用失败，返回错误响应
            resp = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": f"[多模态处理失败: {e}]"}]
                        },
                        "finishReason": "STOP"
                    }
                ]
            }
            return [], resp

    def list_models(self) -> dict:
        """
        列出可用模型

        Returns:
            包含模型列表的字典
        """
        try:
            # 使用 SDK 方法列出所有可用模型
            models = self.client.models.list()
            model_list = []

            # 遍历模型并提取信息
            for model in models:
                model_info = {"name": model.name}

                # 添加额外的模型信息（如果可用）
                if hasattr(model, 'display_name') and model.display_name:
                    model_info["display_name"] = model.display_name
                if hasattr(model, 'description') and model.description:
                    model_info["description"] = model.description
                if hasattr(model, 'supported_generation_methods'):
                    model_info["supported_generation_methods"] = model.supported_generation_methods

                model_list.append(model_info)

            return {"models": model_list}

        except Exception as e:
            print(f"SDK 列出模型失败: {e}")
            # 如果 SDK 方法失败，返回默认模型列表
            return {
                "models": [
                    {"name": DEFAULT_TEXT_MODEL, "display_name": "Gemini 2.5 Flash Preview"},
                    {"name": DEFAULT_VISION_MODEL, "display_name": "Gemini 2.5 Flash Preview (Vision)"},
                    {"name": DEFAULT_IMAGE_GEN_MODEL, "display_name": "Gemini 2.0 Flash Image Generation"},
                    {"name": DEFAULT_IMAGEN_MODEL, "display_name": "Imagen 3.0 Generate"},
                    {"name": DEFAULT_EMBEDDING_MODEL, "display_name": "Text Embedding 004"},
                ]
            }

    # ---------------------------------------------------------------------
    # 工具函数
    # ---------------------------------------------------------------------
    def count_tokens(
        self,
        text: str,
        *,
        model: str = DEFAULT_TEXT_MODEL,
    ) -> Any:
        """
        计算文本的令牌数
        
        Args:
            text: 输入文本
            model: 模型名称
            
        Returns:
            令牌计数结果
        """
        response = self.client.models.count_tokens(
            model=model,
            contents=text
        )
        
        return response


    class ChatSession:
        """聊天会话类，与 REST 版本兼容"""

        def __init__(
            self,
            client: genai.Client,
            *,
            model: str = DEFAULT_TEXT_MODEL,
            system_prompt: str = "",
            generation_config: Optional[dict] = None,
        ):
            """
            初始化聊天会话

            Args:
                client: Gemini 客户端
                model: 模型名称
                system_prompt: 系统提示
                generation_config: 生成配置字典
            """
            self.client = client
            self.model = model
            self._history: List[dict] = []
            self._gen_cfg = generation_config or {}

            # 存储系统提示
            self._system_instruction = system_prompt

            # 创建聊天会话
            # 注意：新的 SDK 不再有 client.chats.create 方法
            # 我们使用手动管理历史记录的方式，这是推荐的做法
            self.chat = None

        @property
        def history(self) -> List[dict]:
            """获取聊天历史记录"""
            if self._system_instruction:
                # 为显示目的创建系统角色条目
                display_history = [{"role": "system", "parts": [{"text": self._system_instruction}]}]
                display_history.extend(self._history)
                return display_history
            return self._history

        def send(self, text: str, **gen_cfg) -> dict:
            """
            发送用户消息，返回模型候选 JSON

            Args:
                text: 用户消息
                **gen_cfg: 生成配置参数

            Returns:
                包含模型回复的响应字典
            """
            # 手动管理历史记录，使用生成内容 API
            merged_cfg = {**self._gen_cfg, **(gen_cfg.get("generation_config") or {})}

            config = types.GenerateContentConfig()
            if self._system_instruction:
                config.system_instruction = self._system_instruction
            if merged_cfg.get('max_output_tokens'):
                config.max_output_tokens = merged_cfg['max_output_tokens']
            if merged_cfg.get('temperature') is not None:
                config.temperature = merged_cfg['temperature']
            if merged_cfg.get('top_p') is not None:
                config.top_p = merged_cfg['top_p']
            if merged_cfg.get('top_k') is not None:
                config.top_k = merged_cfg['top_k']

            try:
                # 构建完整的对话内容，包括历史记录和当前消息
                contents = []

                # 添加历史记录
                for msg in self._history:
                    if msg["role"] == "user":
                        contents.append(types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=msg["parts"][0]["text"])]
                        ))
                    elif msg["role"] == "model":
                        contents.append(types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=msg["parts"][0]["text"])]
                        ))

                # 添加当前用户消息
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=text)]
                ))

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config
                )
                # 获取响应文本 - SDK 响应有 text 属性，但可能为 None
                response_text = ""
                if hasattr(response, 'text') and response.text is not None:
                    response_text = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    # 如果 text 为 None，尝试从 candidates 中提取
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'text') and part.text is not None:
                                    response_text += part.text
            except Exception as e:
                response_text = f"[生成内容失败: {e}]"

            # 将用户消息和助手回复都添加到历史记录
            self._history.append({"role": "user", "parts": [{"text": text}]})
            self._history.append({"role": "model", "parts": [{"text": response_text}]})

            # 返回与 REST 版本兼容的格式
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": response_text}]
                        },
                        "finishReason": "STOP"
                    }
                ]
            }


# 兼容性别名 - 保持向后兼容
GeminiAPISDK = GeminiAPI
