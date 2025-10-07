"""
Labyrinthia AI - 编码转换工具类
Encoding conversion utilities for cross-platform compatibility
"""

import json
import logging
import time
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

        # 错误处理配置
        self.retry_count = config.llm.encoding_retry_count
        self.timeout = config.llm.encoding_timeout
        self.fallback_enabled = config.llm.encoding_fallback_enabled

        # 性能配置（保留用于其他编码方法）
        self.show_size_impact = getattr(config.llm, 'show_encoding_impact', True)

        # 统计信息
        self.stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "fallback_operations": 0,
            "total_encoding_time": 0.0,
            "total_size_increase": 0
        }

        logger.info(f"EncodingConverter initialized: enabled={self.enabled}, method={self.method}, "
                   f"retry_count={self.retry_count}, timeout={self.timeout}s")
    
    def encode_request_payload(self, payload: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        编码请求载荷（带重试和错误处理）

        Args:
            payload: 原始请求载荷

        Returns:
            编码后的载荷（可能是字典或字符串）
        """
        if not self.enabled:
            return payload

        self.stats["total_operations"] += 1
        start_time = time.time()

        for attempt in range(self.retry_count + 1):
            try:
                # 检查操作超时
                if time.time() - start_time > self.timeout:
                    logger.warning(f"Encoding operation timeout after {self.timeout}s")
                    break

                if self.method == "utf8_strict":
                    result = self._encode_utf8_strict(payload)
                elif self.method == "json_escape":
                    result = self._encode_json_escape(payload)
                else:
                    logger.warning(f"Unknown encoding method: {self.method}, using original payload")
                    result = payload

                # 记录成功操作
                encoding_time = time.time() - start_time
                self.stats["successful_operations"] += 1
                self.stats["total_encoding_time"] += encoding_time

                if config.debug.show_encoding_debug:
                    logger.debug(f"Encoding successful on attempt {attempt + 1}, time: {encoding_time:.3f}s")

                return result

            except Exception as e:
                logger.warning(f"Encoding attempt {attempt + 1} failed: {e}")
                if attempt < self.retry_count:
                    time.sleep(0.1 * (attempt + 1))  # 递增延迟
                continue

        # 所有重试都失败了
        self.stats["failed_operations"] += 1

        if self.fallback_enabled:
            logger.info("All encoding attempts failed, using fallback (original payload)")
            self.stats["fallback_operations"] += 1
            return payload
        else:
            logger.error("Encoding failed and fallback is disabled")
            raise RuntimeError(f"Failed to encode payload after {self.retry_count + 1} attempts")
    
    def decode_response(self, response: Union[str, Dict[str, Any]], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        解码响应数据

        Args:
            response: 编码的响应数据
            headers: 响应头信息（用于确定编码方法）

        Returns:
            解码后的响应字典
        """
        if not self.enabled:
            return response if isinstance(response, dict) else {}

        try:
            # 检查响应头中的编码方法
            encoding_method = self.method
            if headers and 'X-Encoding-Method' in headers:
                encoding_method = headers['X-Encoding-Method']

            if encoding_method in ["utf8_strict", "json_escape"]:
                return response if isinstance(response, dict) else {}
            else:
                return response if isinstance(response, dict) else {}

        except Exception as e:
            logger.error(f"Failed to decode response: {e}")
            # 解码失败时尝试返回原始响应
            if isinstance(response, dict):
                return response
            elif isinstance(response, str):
                try:
                    # 尝试直接解析JSON
                    return json.loads(response)
                except:
                    return {}
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

        注意：编码功能主要用于解决客户端的字符编码问题，
        确保字符串内容的编码安全。

        Args:
            payload: 原始请求载荷

        Returns:
            (处理后的载荷, 额外的请求头)
        """
        extra_headers = {}

        if not self.enabled:
            return payload, extra_headers

        try:
            # 所有编码方法都保持JSON格式，只处理字符串内容
            processed_payload = self.encode_request_payload(payload)
            extra_headers['Content-Type'] = 'application/json; charset=utf-8'
            extra_headers['X-Encoding-Method'] = self.method

            # 记录编码信息用于调试
            if config.debug.show_encoding_debug:
                logger.debug(f"Applied encoding method: {self.method}")

            return processed_payload, extra_headers

        except Exception as e:
            logger.error(f"Failed to prepare request data: {e}")
            # 编码失败时回退到原始载荷
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
                # 未知方法，直接返回原文本
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
            "retry_count": self.retry_count,
            "timeout": self.timeout,
            "fallback_enabled": self.fallback_enabled,
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取编码操作统计信息"""
        total_ops = self.stats["total_operations"]
        success_rate = (self.stats["successful_operations"] / total_ops * 100) if total_ops > 0 else 0
        avg_encoding_time = (self.stats["total_encoding_time"] / self.stats["successful_operations"]) if self.stats["successful_operations"] > 0 else 0

        return {
            "total_operations": total_ops,
            "successful_operations": self.stats["successful_operations"],
            "failed_operations": self.stats["failed_operations"],
            "fallback_operations": self.stats["fallback_operations"],
            "success_rate_percent": round(success_rate, 2),
            "average_encoding_time_ms": round(avg_encoding_time * 1000, 2),
            "total_size_increase_bytes": self.stats["total_size_increase"],
        }

    def reset_stats(self):
        """重置统计信息"""
        self.stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "fallback_operations": 0,
            "total_encoding_time": 0.0,
            "total_size_increase": 0
        }
        logger.info("Encoding statistics reset")

    def log_performance_summary(self):
        """记录性能摘要"""
        if config.debug.show_performance_metrics:
            stats = self.get_stats()
            logger.info(f"Encoding Performance Summary: {stats}")

    def calculate_size_impact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算编码对数据大小的影响

        Args:
            payload: 原始载荷

        Returns:
            包含大小信息的字典
        """
        try:
            # 原始JSON大小
            original_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            original_size = len(original_json.encode('utf-8'))

            # 编码后大小
            encoded_payload = self.encode_request_payload(payload)
            if isinstance(encoded_payload, str):
                encoded_size = len(encoded_payload.encode('utf-8'))
            else:
                encoded_json = json.dumps(encoded_payload, ensure_ascii=False, separators=(',', ':'))
                encoded_size = len(encoded_json.encode('utf-8'))

            size_increase = encoded_size - original_size
            size_ratio = encoded_size / original_size if original_size > 0 else 1.0

            return {
                "original_size": original_size,
                "encoded_size": encoded_size,
                "size_increase": size_increase,
                "size_ratio": size_ratio,
                "increase_percentage": (size_ratio - 1.0) * 100,
                "method": self.method,
                "enabled": self.enabled
            }

        except Exception as e:
            logger.error(f"Failed to calculate size impact: {e}")
            return {
                "original_size": 0,
                "encoded_size": 0,
                "size_increase": 0,
                "size_ratio": 1.0,
                "increase_percentage": 0.0,
                "method": self.method,
                "enabled": self.enabled,
                "error": str(e)
            }


# 全局编码转换器实例
encoding_converter = EncodingConverter()

# 导出
__all__ = [
    "EncodingConverter",
    "encoding_converter"
]
