"""
OpenAI API 兼容工具类
支持单轮对话、多轮对话、多模态输入和输出
使用 REST 方法与 OpenAI 兼容的 API 进行交互
"""

import requests
import json
import base64
from typing import List, Dict, Optional, Union, Any
from pathlib import Path


class OpenAIAPITool:
    """OpenAI API 兼容工具类"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-3.5-turbo",
        default_image_model: str = "dall-e-3",
        default_tts_model: str = "tts-1",
        timeout: int = 60,
        proxies: Optional[Dict[str, str]] = None
    ):
        """
        初始化 OpenAI API 工具

        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            default_model: 默认的文本模型
            default_image_model: 默认的图片生成模型
            default_tts_model: 默认的 TTS 模型
            timeout: 请求超时时间（秒）
            proxies: 代理配置字典，格式为 {'http': 'http://...', 'https': 'http://...'}
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.default_model = default_model
        self.default_image_model = default_image_model
        self.default_tts_model = default_tts_model
        self.timeout = timeout
        self.proxies = proxies
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # 用于调试的请求/响应跟踪
        self.last_request_payload: Optional[Dict[str, Any]] = None
        self.last_response_payload: Optional[Dict[str, Any]] = None
    
    def _make_request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        method: str = "POST",
        return_json: bool = True
    ) -> Union[Dict[str, Any], bytes]:
        """
        发送 HTTP 请求

        Args:
            endpoint: API 端点
            data: 请求数据
            method: HTTP 方法
            return_json: 是否返回 JSON 数据（False 时返回原始字节）

        Returns:
            响应数据（JSON 或字节）
        """
        url = f"{self.base_url}/{endpoint}"

        # 保存请求数据用于调试
        self.last_request_payload = data.copy() if isinstance(data, dict) else data

        try:
            if method == "POST":
                response = requests.post(
                    url,
                    headers=self.headers,
                    json=data,
                    timeout=self.timeout,
                    proxies=self.proxies
                )
            else:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=data,
                    timeout=self.timeout,
                    proxies=self.proxies
                )

            response.raise_for_status()

            if return_json:
                response_data = response.json()
                # 保存响应数据用于调试
                self.last_response_payload = response_data
                return response_data
            else:
                return response.content

        except requests.exceptions.RequestException as e:
            # 添加更详细的错误信息
            error_msg = f"API 请求失败: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f"\n请求 URL: {url}"
                error_msg += f"\n状态码: {e.response.status_code}"
                try:
                    error_msg += f"\n响应内容: {e.response.text}"
                except:
                    pass
            raise Exception(error_msg)
    
    def single_chat(
        self,
        message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        单轮对话

        Args:
            message: 用户消息
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 响应格式配置（例如 {"type": "json_object"}）
            **kwargs: 其他参数

        Returns:
            AI 回复内容
        """
        model = model or self.default_model

        data = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "temperature": temperature,
            **kwargs
        }

        if max_tokens is not None:
            data["max_tokens"] = max_tokens

        if response_format is not None:
            data["response_format"] = response_format

        response = self._make_request("chat/completions", data)
        return response["choices"][0]["message"]["content"]
    
    def multi_turn_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        多轮对话
        
        Args:
            messages: 消息列表，格式为 [{"role": "user/assistant/system", "content": "..."}]
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数
            
        Returns:
            AI 回复内容
        """
        model = model or self.default_model
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs
        }
        
        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        
        response = self._make_request("chat/completions", data)
        return response["choices"][0]["message"]["content"]
    
    def _encode_image(self, image_path: str) -> str:
        """
        将图片编码为 base64
        
        Args:
            image_path: 图片路径
            
        Returns:
            base64 编码的图片
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def _create_image_content(
        self,
        image_source: str,
        detail: str = "auto"
    ) -> Dict[str, Any]:
        """
        创建图片内容对象
        
        Args:
            image_source: 图片源（URL 或本地路径）
            detail: 图片细节级别
            
        Returns:
            图片内容对象
        """
        if image_source.startswith(('http://', 'https://')):
            # URL 图片
            return {
                "type": "image_url",
                "image_url": {
                    "url": image_source,
                    "detail": detail
                }
            }
        else:
            # 本地图片
            base64_image = self._encode_image(image_source)
            # 获取图片扩展名
            ext = Path(image_source).suffix.lower().lstrip('.')
            mime_type = f"image/{ext}" if ext in ['png', 'jpeg', 'jpg', 'gif', 'webp'] else "image/jpeg"
            
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_image}",
                    "detail": detail
                }
            }
    
    def multimodal_input(
        self,
        text: str,
        images: Union[str, List[str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        detail: str = "auto",
        **kwargs
    ) -> str:
        """
        多模态输入（文本 + 图片）
        
        Args:
            text: 文本内容
            images: 图片路径或 URL（单个或列表）
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            detail: 图片细节级别（low/high/auto）
            **kwargs: 其他参数
            
        Returns:
            AI 回复内容
        """
        model = model or self.default_model
        
        # 处理图片列表
        if isinstance(images, str):
            images = [images]
        
        # 构建内容
        content = [{"type": "text", "text": text}]
        
        for image in images:
            content.append(self._create_image_content(image, detail))
        
        data = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            **kwargs
        }
        
        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        
        response = self._make_request("chat/completions", data)
        return response["choices"][0]["message"]["content"]
    
    def generate_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        response_format: str = "url",
        **kwargs
    ) -> List[str]:
        """
        生成图片

        Args:
            prompt: 图片描述
            model: 模型名称
            size: 图片尺寸
            quality: 图片质量（standard/hd）
            n: 生成图片数量
            response_format: 响应格式（url/b64_json）
            **kwargs: 其他参数

        Returns:
            图片 URL 或 base64 数据列表。
            注意：当 response_format 为 "b64_json" 时，返回的是带有 "data:image/png;base64," 前缀的 base64 字符串。
        """
        model = model or self.default_image_model

        data = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
            "response_format": response_format,
            **kwargs
        }

        response = self._make_request("images/generations", data)

        # 支持两种响应格式
        results = []
        for item in response["data"]:
            if "url" in item:
                results.append(item["url"])
            elif "b64_json" in item:
                results.append(f"data:image/png;base64,{item['b64_json']}")
            else:
                # 如果都没有，尝试获取任何可用的字段
                results.append(str(item))

        return results
    
    def multimodal_input_output(
        self,
        text: str,
        input_images: Optional[Union[str, List[str]]] = None,
        generate_image: bool = False,
        image_prompt: Optional[str] = None,
        model: Optional[str] = None,
        image_model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        image_size: str = "1024x1024",
        image_quality: str = "standard",
        **kwargs
    ) -> Dict[str, Any]:
        """
        多模态输入与输出（文本 + 图片输入，文本 + 图片输出）
        
        Args:
            text: 文本内容
            input_images: 输入图片路径或 URL（可选）
            generate_image: 是否生成图片
            image_prompt: 图片生成提示词（如果为 None，使用 text）
            model: 文本模型名称
            image_model: 图片模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            image_size: 图片尺寸
            image_quality: 图片质量
            **kwargs: 其他参数
            
        Returns:
            包含文本和图片 URL 的字典
        """
        result = {
            "text": None,
            "images": []
        }
        
        # 处理文本输入（可能包含图片）
        if input_images:
            result["text"] = self.multimodal_input(
                text=text,
                images=input_images,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
        else:
            result["text"] = self.single_chat(
                message=text,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
        
        # 生成图片
        if generate_image:
            prompt = image_prompt or text
            result["images"] = self.generate_image(
                prompt=prompt,
                model=image_model,
                size=image_size,
                quality=image_quality,
                **kwargs
            )
        
        return result

    def text_to_speech(
        self,
        text: str,
        output_path: str,
        model: Optional[str] = None,
        voice: str = "alloy",
        response_format: str = "mp3",
        speed: float = 1.0,
        **kwargs
    ) -> str:
        """
        文本转语音（TTS）

        Args:
            text: 要转换的文本
            output_path: 输出音频文件路径
            model: TTS 模型名称
            voice: 语音选项（alloy/echo/fable/onyx/nova/shimmer）
            response_format: 音频格式（mp3/opus/aac/flac/wav/pcm）
            speed: 语速（0.25 到 4.0）
            **kwargs: 其他参数

        Returns:
            输出文件路径
        """
        model = model or self.default_tts_model

        data = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
            **kwargs
        }

        # TTS API 返回音频字节流
        audio_content = self._make_request("audio/speech", data, return_json=False)

        # 保存音频文件
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "wb") as f:
            f.write(audio_content)

        return str(output_file)

    def text_to_speech_stream(
        self,
        text: str,
        model: Optional[str] = None,
        voice: str = "alloy",
        response_format: str = "mp3",
        speed: float = 1.0,
        **kwargs
    ) -> bytes:
        """
        文本转语音（TTS）- 返回音频字节流

        Args:
            text: 要转换的文本
            model: TTS 模型名称
            voice: 语音选项（alloy/echo/fable/onyx/nova/shimmer）
            response_format: 音频格式（mp3/opus/aac/flac/wav/pcm）
            speed: 语速（0.25 到 4.0）
            **kwargs: 其他参数

        Returns:
            音频字节流
        """
        model = model or self.default_tts_model

        data = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
            **kwargs
        }

        # TTS API 返回音频字节流
        return self._make_request("audio/speech", data, return_json=False)

