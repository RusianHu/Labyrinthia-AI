"""
Labyrinthia AI - 内容清理器
Content sanitizer for Gemini API compatibility issues
解决Gemini API在Ubuntu服务器上的特定字符和内容问题
"""

import re
import json
import logging
from typing import Dict, Any, Optional, Union, List
import unicodedata

from config import config

logger = logging.getLogger(__name__)


class ContentSanitizer:
    """
    内容清理器，专门解决Gemini API的已知问题：
    1. 控制字符（Tab、NULL等）导致的500错误
    2. Markdown代码围栏导致的超时问题
    3. 复杂JSON结构导致的解析问题
    """
    
    def __init__(self):
        self.enabled = config.llm.use_content_sanitization if hasattr(config.llm, 'use_content_sanitization') else True
        self.aggressive_mode = config.llm.aggressive_sanitization if hasattr(config.llm, 'aggressive_sanitization') else False
        
        # 控制字符映射表
        self.control_char_replacements = {
            '\t': '    ',  # Tab -> 4个空格
            '\r': '',      # 回车符删除
            '\n': '\n',    # 保留换行符
            '\0': '',      # NULL字符删除
            '\x0b': ' ',   # 垂直制表符 -> 空格
            '\x0c': ' ',   # 换页符 -> 空格
        }
        
        # Markdown代码围栏模式
        self.code_fence_patterns = [
            r'```[\s\S]*?```',           # 标准代码围栏
            r'~~~[\s\S]*?~~~',           # 波浪线代码围栏
            r'`[^`\n]*`',                # 行内代码
        ]
        
        # 复杂表格模式
        self.table_patterns = [
            r'\|[\s\S]*?\|',             # 简单表格行
            r'^\|.*\|$',                 # 完整表格行（多行模式）
        ]
        
        logger.info(f"ContentSanitizer initialized: enabled={self.enabled}, aggressive={self.aggressive_mode}")
    
    def sanitize_text(self, text: str) -> str:
        """
        清理文本内容，移除可能导致Gemini API问题的字符和结构
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        if not self.enabled or not text:
            return text
        
        try:
            # 1. 移除控制字符
            cleaned_text = self._remove_control_characters(text)
            
            # 2. 处理Markdown代码围栏
            cleaned_text = self._sanitize_code_fences(cleaned_text)
            
            # 3. 简化复杂表格
            cleaned_text = self._simplify_tables(cleaned_text)
            
            # 4. 规范化Unicode字符
            cleaned_text = self._normalize_unicode(cleaned_text)
            
            # 5. 验证最终结果
            cleaned_text = self._validate_final_content(cleaned_text)
            
            if len(cleaned_text) != len(text):
                logger.debug(f"Content sanitized: {len(text)} -> {len(cleaned_text)} chars")
            
            return cleaned_text
            
        except Exception as e:
            logger.error(f"Content sanitization failed: {e}")
            # 如果清理失败，返回基本清理版本
            return self._basic_sanitization(text)
    
    def sanitize_json_content(self, data: Union[Dict, List, str]) -> Union[Dict, List, str]:
        """
        清理JSON内容中的文本字段
        
        Args:
            data: JSON数据（字典、列表或字符串）
            
        Returns:
            清理后的JSON数据
        """
        if not self.enabled:
            return data
        
        try:
            if isinstance(data, dict):
                return {key: self.sanitize_json_content(value) for key, value in data.items()}
            elif isinstance(data, list):
                return [self.sanitize_json_content(item) for item in data]
            elif isinstance(data, str):
                return self.sanitize_text(data)
            else:
                return data
                
        except Exception as e:
            logger.error(f"JSON content sanitization failed: {e}")
            return data
    
    def _remove_control_characters(self, text: str) -> str:
        """移除控制字符"""
        # 使用映射表替换已知的问题字符
        for char, replacement in self.control_char_replacements.items():
            text = text.replace(char, replacement)

        # 移除其他控制字符（除了换行符）
        if self.aggressive_mode:
            # 激进模式：移除所有控制字符，但保留换行符
            text = ''.join(char for char in text if unicodedata.category(char)[0] != 'C' or char == '\n')
        else:
            # 保守模式：只移除已知的ASCII控制字符，保留中文和其他Unicode字符
            # 移除ASCII控制字符（0x00-0x1F，除了\n=0x0A），但保留所有非ASCII字符
            text = ''.join(char for char in text if (
                ord(char) >= 32 or  # 可打印ASCII字符
                char == '\n' or     # 保留换行符
                ord(char) >= 128    # 保留所有非ASCII字符（包括中文）
            ))

        return text
    
    def _sanitize_code_fences(self, text: str) -> str:
        """处理Markdown代码围栏"""
        if not self.aggressive_mode:
            # 保守模式：只替换代码围栏标记
            text = re.sub(r'```(\w*)', r'[代码块:\1]', text)
            text = re.sub(r'```', r'[/代码块]', text)
            text = re.sub(r'~~~(\w*)', r'[代码块:\1]', text)
            text = re.sub(r'~~~', r'[/代码块]', text)
        else:
            # 激进模式：完全移除代码块内容
            for pattern in self.code_fence_patterns:
                text = re.sub(pattern, '[代码块已移除]', text, flags=re.MULTILINE)
        
        return text
    
    def _simplify_tables(self, text: str) -> str:
        """简化复杂表格"""
        if self.aggressive_mode:
            # 激进模式：移除所有表格
            for pattern in self.table_patterns:
                text = re.sub(pattern, '[表格已简化]', text, flags=re.MULTILINE)
        else:
            # 保守模式：简化表格分隔符
            text = re.sub(r'\|', ' | ', text)  # 在管道符周围添加空格
            text = re.sub(r'\s+\|\s+', ' | ', text)  # 规范化管道符间距
        
        return text
    
    def _normalize_unicode(self, text: str) -> str:
        """规范化Unicode字符"""
        try:
            # 使用NFC规范化
            normalized = unicodedata.normalize('NFC', text)
            
            # 如果激进模式，移除非基本多文种平面字符
            if self.aggressive_mode:
                # 保留基本多文种平面字符（U+0000到U+FFFF）
                normalized = ''.join(char for char in normalized if ord(char) <= 0xFFFF)
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Unicode normalization failed: {e}")
            return text
    
    def _validate_final_content(self, text: str) -> str:
        """验证最终内容的安全性"""
        try:
            # 验证UTF-8编码
            text.encode('utf-8')
            
            # 检查长度限制
            max_length = 100000  # 100KB文本限制
            if len(text) > max_length:
                logger.warning(f"Content too long ({len(text)} chars), truncating to {max_length}")
                text = text[:max_length] + "...[内容已截断]"
            
            return text
            
        except UnicodeEncodeError as e:
            logger.error(f"Final content validation failed: {e}")
            return self._basic_sanitization(text)
    
    def _basic_sanitization(self, text: str) -> str:
        """基本清理，作为失败时的后备方案"""
        try:
            # 保留更多字符，包括中文字符和常用标点
            safe_chars = set(' \n.,!?;:()[]{}"\'-_=+*/\\|@#$%^&<>')
            safe_text = ''.join(char for char in text if (
                ord(char) < 128 or  # ASCII字符
                char.isalnum() or   # 字母数字（包括中文）
                char in safe_chars or  # 安全标点符号
                ord(char) >= 0x4e00 and ord(char) <= 0x9fff or  # 中文汉字
                ord(char) >= 0x3400 and ord(char) <= 0x4dbf or  # 中文扩展A
                ord(char) >= 0xff00 and ord(char) <= 0xffef     # 全角字符
            ))
            return safe_text
        except Exception:
            # 最后的后备方案 - 保留原文本但移除明显的控制字符
            try:
                return ''.join(char for char in text if ord(char) >= 32 or char == '\n')
            except Exception:
                return "内容清理失败，已使用安全文本"
    
    def create_safe_prompt(self, prompt: str, context_data: Optional[Dict[str, Any]] = None) -> str:
        """
        创建安全的提示词，专门用于复杂的LLM请求
        
        Args:
            prompt: 原始提示词
            context_data: 上下文数据（如地图、任务信息等）
            
        Returns:
            安全的提示词
        """
        try:
            # 清理主要提示词
            safe_prompt = self.sanitize_text(prompt)
            
            # 如果有上下文数据，进行安全序列化
            if context_data:
                # 清理上下文数据
                safe_context = self.sanitize_json_content(context_data)
                
                # 创建安全的JSON字符串
                context_json = self._create_safe_json_string(safe_context)
                
                # 将上下文添加到提示词中
                safe_prompt += f"\n\n上下文信息：\n{context_json}"
            
            return safe_prompt
            
        except Exception as e:
            logger.error(f"Safe prompt creation failed: {e}")
            return self.sanitize_text(prompt)
    
    def _create_safe_json_string(self, data: Any) -> str:
        """创建安全的JSON字符串"""
        try:
            # 使用安全的JSON序列化选项
            json_str = json.dumps(
                data,
                ensure_ascii=False,
                separators=(',', ':'),
                indent=None
            )
            
            # 进一步清理JSON字符串
            json_str = self.sanitize_text(json_str)
            
            return json_str
            
        except Exception as e:
            logger.error(f"Safe JSON creation failed: {e}")
            return str(data)
    
    def get_sanitization_stats(self) -> Dict[str, Any]:
        """获取清理器统计信息"""
        return {
            "enabled": self.enabled,
            "aggressive_mode": self.aggressive_mode,
            "control_char_count": len(self.control_char_replacements),
            "code_fence_patterns": len(self.code_fence_patterns),
            "table_patterns": len(self.table_patterns)
        }


# 全局内容清理器实例
content_sanitizer = ContentSanitizer()

# 导出
__all__ = [
    "ContentSanitizer",
    "content_sanitizer"
]
