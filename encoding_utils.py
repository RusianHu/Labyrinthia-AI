"""
Labyrinthia AI - 编码转换工具类
Encoding conversion utilities for cross-platform compatibility
"""

import base64
import json
import logging
from typing import Dict, Any, Optional, Union
import codecs

from config import config

logger = logging.getLogger(__name__)


class EncodingConverter:
    """编码转换工具类，用于解决跨平台字符编码问题"""
    
    def __init__(self):
        self.enabled = config.llm.use_encoding_conversion
        self.method = config.llm.encoding_method
        self.force_utf8 = config.llm.force_utf8_encoding
        
        logger.info(f"EncodingConverter initialized: enabled={self.enabled}, method={self.method}")
    
    def encode_request_payload(self, payload: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        编码请求载荷
        
        Args:
            payload: 原始请求载荷
            
        Returns:
            编码后的载荷（可能是字典或字符串）
        """
        if not self.enabled:
            return payload
        
        try:
            if self.method == "base64":
                return self._encode_base64(payload)
            elif self.method == "utf8_strict":
                return self._encode_utf8_strict(payload)
            elif self.method == "json_escape":
                return self._encode_json_escape(payload)
            else:
                logger.warning(f"Unknown encoding method: {self.method}, using original payload")
                return payload
                
        except Exception as e:
            logger.error(f"Failed to encode payload: {e}")
            # 如果编码失败，返回原始载荷
            return payload
    
    def decode_response(self, response: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        解码响应数据
        
        Args:
            response: 编码的响应数据
            
        Returns:
            解码后的响应字典
        """
        if not self.enabled:
            return response if isinstance(response, dict) else {}
        
        try:
            if self.method == "base64" and isinstance(response, str):
                return self._decode_base64(response)
            elif self.method in ["utf8_strict", "json_escape"]:
                return response if isinstance(response, dict) else {}
            else:
                return response if isinstance(response, dict) else {}
                
        except Exception as e:
            logger.error(f"Failed to decode response: {e}")
            return response if isinstance(response, dict) else {}
    
    def _encode_base64(self, payload: Dict[str, Any]) -> str:
        """Base64编码方法"""
        # 将载荷转换为JSON字符串，确保UTF-8编码
        json_str = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        
        # 强制UTF-8编码
        if self.force_utf8:
            json_bytes = json_str.encode('utf-8')
        else:
            json_bytes = json_str.encode()
        
        # Base64编码
        encoded = base64.b64encode(json_bytes).decode('ascii')
        
        logger.debug(f"Base64 encoded payload length: {len(encoded)}")
        return encoded
    
    def _decode_base64(self, encoded_data: str) -> Dict[str, Any]:
        """Base64解码方法"""
        try:
            # Base64解码
            json_bytes = base64.b64decode(encoded_data.encode('ascii'))
            
            # UTF-8解码
            json_str = json_bytes.decode('utf-8')
            
            # JSON解析
            return json.loads(json_str)
            
        except Exception as e:
            logger.error(f"Base64 decode error: {e}")
            return {}
    
    def _encode_utf8_strict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """严格UTF-8编码方法"""
        # 递归处理所有字符串字段，确保UTF-8编码
        return self._process_strings_recursive(payload, self._ensure_utf8_string)
    
    def _encode_json_escape(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """JSON转义编码方法"""
        # 递归处理所有字符串字段，进行JSON转义
        return self._process_strings_recursive(payload, self._escape_json_string)
    
    def _process_strings_recursive(self, obj: Any, string_processor) -> Any:
        """递归处理对象中的所有字符串"""
        if isinstance(obj, dict):
            return {key: self._process_strings_recursive(value, string_processor) 
                   for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._process_strings_recursive(item, string_processor) 
                   for item in obj]
        elif isinstance(obj, str):
            return string_processor(obj)
        else:
            return obj
    
    def _ensure_utf8_string(self, text: str) -> str:
        """确保字符串是有效的UTF-8编码"""
        try:
            # 尝试编码为UTF-8然后解码，确保字符串有效
            return text.encode('utf-8').decode('utf-8')
        except UnicodeError:
            # 如果编码失败，使用错误处理策略
            return text.encode('utf-8', errors='replace').decode('utf-8')
    
    def _escape_json_string(self, text: str) -> str:
        """对字符串进行JSON转义"""
        # 使用json.dumps对字符串进行转义，然后去掉外层引号
        escaped = json.dumps(text, ensure_ascii=False)
        return escaped[1:-1]  # 去掉首尾的引号
    
    def prepare_request_data(self, payload: Dict[str, Any]) -> tuple[Union[Dict[str, Any], str], Dict[str, str]]:
        """
        准备请求数据，包括载荷和请求头

        Args:
            payload: 原始请求载荷

        Returns:
            (处理后的载荷, 额外的请求头)
        """
        # 对于API请求，我们不使用Base64编码，而是使用安全的UTF-8处理
        extra_headers = {}

        if self.enabled:
            # 所有启用的编码方法都使用UTF-8安全处理
            extra_headers['Content-Type'] = 'application/json; charset=utf-8'
            extra_headers['X-Encoding-Method'] = self.method

        return payload, extra_headers
    
    def create_safe_json_payload(self, payload: Dict[str, Any]) -> str:
        """
        创建安全的JSON载荷字符串，专门用于解决Ubuntu编码问题
        
        Args:
            payload: 原始载荷字典
            
        Returns:
            安全编码的JSON字符串
        """
        try:
            # 方法1：使用ensure_ascii=False + 手动UTF-8编码
            json_str = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            
            # 验证UTF-8编码
            json_str.encode('utf-8')
            
            logger.debug(f"Created safe JSON payload, length: {len(json_str)}")
            return json_str
            
        except UnicodeEncodeError as e:
            logger.warning(f"UTF-8 encoding failed, using ASCII fallback: {e}")
            # 方法2：回退到ASCII安全模式
            return json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
        except Exception as e:
            logger.error(f"JSON serialization failed: {e}")
            raise
    
    def validate_encoding(self, text: str) -> bool:
        """
        验证文本编码是否有效
        
        Args:
            text: 要验证的文本
            
        Returns:
            编码是否有效
        """
        try:
            # 尝试UTF-8编码和解码
            text.encode('utf-8').decode('utf-8')
            return True
        except UnicodeError:
            return False
    
    def process_text(self, text: str) -> str:
        """
        处理文本，确保编码安全

        Args:
            text: 要处理的文本

        Returns:
            处理后的文本
        """
        if not self.enabled:
            return text

        try:
            if self.method == "utf8_strict":
                return self._ensure_utf8_string(text)
            elif self.method == "json_escape":
                return self._escape_json_string(text)
            else:
                # 对于base64方法，直接返回原文本（base64主要用于载荷编码）
                return text
        except Exception as e:
            logger.error(f"Failed to process text: {e}")
            return text

    def get_encoding_info(self) -> Dict[str, Any]:
        """获取当前编码配置信息"""
        return {
            "enabled": self.enabled,
            "method": self.method,
            "force_utf8": self.force_utf8,
            "system_encoding": codecs.lookup('utf-8').name,
        }


# 全局编码转换器实例
encoding_converter = EncodingConverter()

# 导出
__all__ = [
    "EncodingConverter",
    "encoding_converter"
]
