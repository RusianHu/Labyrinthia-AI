"""
Labyrinthia AI - 输入安全验证模块
Input Security Validation Module

提供全面的用户输入验证和清理功能，防止注入攻击、XSS、路径遍历等安全问题
"""

import re
import json
import html
import shlex
import logging
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """验证级别"""
    STRICT = "strict"      # 严格模式 - 只允许字母数字和基本符号
    NORMAL = "normal"      # 正常模式 - 允许常见字符
    RELAXED = "relaxed"    # 宽松模式 - 允许更多字符但仍过滤危险内容


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    sanitized_value: Any
    error_message: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class InputValidator:
    """输入验证器 - 提供全面的输入安全验证"""
    
    # 危险字符模式
    DANGEROUS_PATTERNS = {
        'sql_injection': [
            r"(\bUNION\b.*\bSELECT\b)",
            r"(\bDROP\b.*\bTABLE\b)",
            r"(\bINSERT\b.*\bINTO\b)",
            r"(\bDELETE\b.*\bFROM\b)",
            r"(\bUPDATE\b.*\bSET\b)",
            r"(--\s*$)",
            r"(;\s*DROP\b)",
            r"('\s*OR\s*'1'\s*=\s*'1)",
        ],
        'xss': [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"on\w+\s*=",
            r"<iframe[^>]*>",
            r"<object[^>]*>",
            r"<embed[^>]*>",
        ],
        'path_traversal': [
            r"\.\./",
            r"\.\.",
            r"~\/",
            r"\/etc\/",
            r"\/proc\/",
            r"\/sys\/",
            r"C:\\",
            r"\\\\",
        ],
        'command_injection': [
            r"[;&|`$]",
            r"\$\(",
            r"`.*`",
            r"\|\s*\w+",
        ],
        'null_bytes': [
            r"\x00",
            r"\\0",
            r"%00",
        ]
    }
    
    # 允许的字符集（根据验证级别）
    ALLOWED_CHARS = {
        ValidationLevel.STRICT: r'^[a-zA-Z0-9_\-\s]+$',
        ValidationLevel.NORMAL: r'^[a-zA-Z0-9_\-\s\u4e00-\u9fa5.,!?()（）。，！？]+$',
        ValidationLevel.RELAXED: r'^[a-zA-Z0-9_\-\s\u4e00-\u9fa5.,!?()（）。，！？:：;；\'\"]+$',
    }
    
    def __init__(self):
        """初始化验证器"""
        self.compiled_patterns = {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """预编译正则表达式模式以提高性能"""
        for category, patterns in self.DANGEROUS_PATTERNS.items():
            self.compiled_patterns[category] = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in patterns
            ]
    
    def validate_player_name(self, name: str) -> ValidationResult:
        """
        验证玩家名称
        
        规则：
        - 长度: 1-20字符
        - 允许: 中文、英文、数字、下划线、空格
        - 禁止: 特殊符号、脚本标签、路径字符
        """
        if not name or not isinstance(name, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="角色名称不能为空"
            )
        
        # 去除首尾空格
        name = name.strip()
        
        # 长度检查
        if len(name) < 1:
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="角色名称不能为空"
            )
        
        if len(name) > 20:
            return ValidationResult(
                is_valid=False,
                sanitized_value=name[:20],
                error_message="角色名称不能超过20个字符"
            )
        
        # 危险模式检查
        danger_check = self._check_dangerous_patterns(name)
        if not danger_check.is_valid:
            return danger_check
        
        # 字符集检查（正常模式）
        if not re.match(self.ALLOWED_CHARS[ValidationLevel.NORMAL], name):
            # 清理不允许的字符
            sanitized = re.sub(r'[^a-zA-Z0-9_\-\s\u4e00-\u9fa5]', '', name)
            return ValidationResult(
                is_valid=True,
                sanitized_value=sanitized,
                warnings=["角色名称包含不允许的字符，已自动清理"]
            )
        
        return ValidationResult(
            is_valid=True,
            sanitized_value=name
        )
    
    def validate_character_class(self, character_class: str) -> ValidationResult:
        """
        验证角色职业
        
        只允许预定义的职业名称
        """
        valid_classes = [
            "fighter", "warrior", "wizard", "rogue", "cleric",
            "ranger", "barbarian", "bard", "paladin", "sorcerer", "warlock"
        ]
        
        if not character_class or not isinstance(character_class, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="fighter",
                error_message="职业不能为空，使用默认职业：战士"
            )
        
        character_class = character_class.lower().strip()
        
        if character_class not in valid_classes:
            return ValidationResult(
                is_valid=False,
                sanitized_value="fighter",
                error_message=f"无效的职业：{character_class}，使用默认职业：战士"
            )
        
        return ValidationResult(
            is_valid=True,
            sanitized_value=character_class
        )
    
    def validate_game_id(self, game_id: str) -> ValidationResult:
        """
        验证游戏ID（UUID格式）
        """
        if not game_id or not isinstance(game_id, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="游戏ID不能为空"
            )
        
        # UUID格式检查
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, game_id.lower()):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="无效的游戏ID格式"
            )
        
        return ValidationResult(
            is_valid=True,
            sanitized_value=game_id
        )
    
    def validate_save_data(self, save_data: Dict[str, Any]) -> ValidationResult:
        """
        验证存档数据
        
        检查：
        - JSON结构完整性
        - 必需字段存在
        - 数据类型正确
        - 数据大小限制
        - 嵌套深度限制
        """
        warnings = []
        
        # 检查是否为字典
        if not isinstance(save_data, dict):
            return ValidationResult(
                is_valid=False,
                sanitized_value={},
                error_message="存档数据必须是JSON对象"
            )
        
        # 检查数据大小（限制为10MB）
        try:
            data_size = len(json.dumps(save_data))
            if data_size > 10 * 1024 * 1024:  # 10MB
                return ValidationResult(
                    is_valid=False,
                    sanitized_value={},
                    error_message="存档文件过大（超过10MB）"
                )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                sanitized_value={},
                error_message=f"无法序列化存档数据: {str(e)}"
            )
        
        # 检查必需字段
        required_fields = ["player", "current_map"]
        missing_fields = [field for field in required_fields if field not in save_data]
        
        if missing_fields:
            return ValidationResult(
                is_valid=False,
                sanitized_value=save_data,
                error_message=f"存档缺少必需字段: {', '.join(missing_fields)}"
            )
        
        # 检查嵌套深度（防止深度嵌套导致的性能问题）
        max_depth = self._get_dict_depth(save_data)
        if max_depth > 20:
            warnings.append(f"存档数据嵌套深度较深（{max_depth}层），可能影响性能")
        
        # 验证玩家数据
        if "player" in save_data and isinstance(save_data["player"], dict):
            if "name" in save_data["player"]:
                name_result = self.validate_player_name(save_data["player"]["name"])
                if not name_result.is_valid:
                    return ValidationResult(
                        is_valid=False,
                        sanitized_value=save_data,
                        error_message=f"存档中的角色名称无效: {name_result.error_message}"
                    )
        
        return ValidationResult(
            is_valid=True,
            sanitized_value=save_data,
            warnings=warnings
        )
    
    def _get_dict_depth(self, d: Any, current_depth: int = 0) -> int:
        """递归计算字典嵌套深度"""
        if not isinstance(d, dict):
            return current_depth
        
        if not d:
            return current_depth + 1
        
        return max(self._get_dict_depth(v, current_depth + 1) for v in d.values())
    
    def _check_dangerous_patterns(self, text: str) -> ValidationResult:
        """检查文本中的危险模式"""
        for category, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    logger.warning(f"Detected {category} pattern in input: {text[:50]}...")
                    return ValidationResult(
                        is_valid=False,
                        sanitized_value="",
                        error_message=f"输入包含不允许的内容（{category}）"
                    )

        return ValidationResult(is_valid=True, sanitized_value=text)

    def sanitize_html(self, text: str) -> str:
        """清理HTML特殊字符，防止XSS"""
        if not isinstance(text, str):
            return ""
        return html.escape(text)

    def sanitize_shell_arg(self, arg: str) -> str:
        """
        清理shell参数，防止命令注入

        使用shlex.quote进行安全转义
        """
        if not isinstance(arg, str):
            return ""
        return shlex.quote(arg)

    def validate_integer_range(
        self,
        value: Any,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        field_name: str = "值"
    ) -> ValidationResult:
        """
        验证整数范围

        Args:
            value: 要验证的值
            min_value: 最小值（可选）
            max_value: 最大值（可选）
            field_name: 字段名称（用于错误消息）
        """
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            return ValidationResult(
                is_valid=False,
                sanitized_value=0,
                error_message=f"{field_name}必须是整数"
            )

        if min_value is not None and int_value < min_value:
            return ValidationResult(
                is_valid=False,
                sanitized_value=min_value,
                error_message=f"{field_name}不能小于{min_value}"
            )

        if max_value is not None and int_value > max_value:
            return ValidationResult(
                is_valid=False,
                sanitized_value=max_value,
                error_message=f"{field_name}不能大于{max_value}"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=int_value
        )

    def validate_float_range(
        self,
        value: Any,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        field_name: str = "值"
    ) -> ValidationResult:
        """验证浮点数范围"""
        try:
            float_value = float(value)
        except (ValueError, TypeError):
            return ValidationResult(
                is_valid=False,
                sanitized_value=0.0,
                error_message=f"{field_name}必须是数字"
            )

        if min_value is not None and float_value < min_value:
            return ValidationResult(
                is_valid=False,
                sanitized_value=min_value,
                error_message=f"{field_name}不能小于{min_value}"
            )

        if max_value is not None and float_value > max_value:
            return ValidationResult(
                is_valid=False,
                sanitized_value=max_value,
                error_message=f"{field_name}不能大于{max_value}"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=float_value
        )

    def validate_string_length(
        self,
        text: str,
        min_length: int = 0,
        max_length: Optional[int] = None,
        field_name: str = "文本"
    ) -> ValidationResult:
        """验证字符串长度"""
        if not isinstance(text, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message=f"{field_name}必须是字符串"
            )

        text_length = len(text)

        if text_length < min_length:
            return ValidationResult(
                is_valid=False,
                sanitized_value=text,
                error_message=f"{field_name}长度不能少于{min_length}个字符"
            )

        if max_length is not None and text_length > max_length:
            return ValidationResult(
                is_valid=False,
                sanitized_value=text[:max_length],
                error_message=f"{field_name}长度不能超过{max_length}个字符"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=text
        )

    def validate_uuid(self, uuid_str: str, field_name: str = "UUID") -> ValidationResult:
        """
        验证UUID格式

        格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (32个十六进制字符，用连字符分隔)
        """
        if not uuid_str or not isinstance(uuid_str, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message=f"{field_name}不能为空"
            )

        # UUID格式验证
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

        if not re.match(uuid_pattern, uuid_str, re.IGNORECASE):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message=f"无效的{field_name}格式"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=uuid_str
        )

    def validate_choice_id(self, choice_id: str) -> ValidationResult:
        """
        验证事件选择ID

        格式: UUID格式 (例如: f9fac4a0-0eda-4c01-aaa0-837528b0d9c4)
        或旧格式: choice_0, choice_1, etc.
        """
        if not choice_id or not isinstance(choice_id, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="选择ID不能为空"
            )

        # 检查UUID格式或旧的choice_N格式
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        old_pattern = r'^choice_\d+$'

        if not (re.match(uuid_pattern, choice_id, re.IGNORECASE) or re.match(old_pattern, choice_id)):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="无效的选择ID格式"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=choice_id
        )

    def validate_direction(self, direction: str) -> ValidationResult:
        """
        验证移动方向

        只允许: north, south, east, west, northeast, northwest, southeast, southwest
        """
        valid_directions = [
            "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest",
            "n", "s", "e", "w", "ne", "nw", "se", "sw"
        ]

        if not direction or not isinstance(direction, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message="方向不能为空"
            )

        direction = direction.lower().strip()

        if direction not in valid_directions:
            return ValidationResult(
                is_valid=False,
                sanitized_value="",
                error_message=f"无效的移动方向: {direction}"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=direction
        )

    def validate_json_structure(
        self,
        data: Any,
        required_fields: Optional[List[str]] = None,
        max_size_mb: float = 10.0
    ) -> ValidationResult:
        """
        验证JSON数据结构

        Args:
            data: JSON数据
            required_fields: 必需字段列表
            max_size_mb: 最大大小（MB）
        """
        warnings = []

        # 检查是否可序列化
        try:
            json_str = json.dumps(data, ensure_ascii=False)
            data_size = len(json_str.encode('utf-8'))

            # 检查大小
            max_size_bytes = int(max_size_mb * 1024 * 1024)
            if data_size > max_size_bytes:
                return ValidationResult(
                    is_valid=False,
                    sanitized_value=data,
                    error_message=f"数据过大（{data_size / 1024 / 1024:.2f}MB，限制{max_size_mb}MB）"
                )

        except (TypeError, ValueError) as e:
            return ValidationResult(
                is_valid=False,
                sanitized_value=data,
                error_message=f"数据无法序列化为JSON: {str(e)}"
            )

        # 检查必需字段
        if required_fields and isinstance(data, dict):
            missing = [f for f in required_fields if f not in data]
            if missing:
                return ValidationResult(
                    is_valid=False,
                    sanitized_value=data,
                    error_message=f"缺少必需字段: {', '.join(missing)}"
                )

        return ValidationResult(
            is_valid=True,
            sanitized_value=data,
            warnings=warnings
        )

    def validate_file_upload(
        self,
        filename: str,
        content: bytes,
        allowed_extensions: Optional[List[str]] = None,
        max_size_mb: float = 10.0
    ) -> ValidationResult:
        """
        验证文件上传

        Args:
            filename: 文件名
            content: 文件内容
            allowed_extensions: 允许的扩展名列表
            max_size_mb: 最大文件大小（MB）
        """
        warnings = []

        # 检查文件名
        if not filename or not isinstance(filename, str):
            return ValidationResult(
                is_valid=False,
                sanitized_value=None,
                error_message="文件名无效"
            )

        # 检查路径遍历
        if ".." in filename or "/" in filename or "\\" in filename:
            return ValidationResult(
                is_valid=False,
                sanitized_value=None,
                error_message="文件名包含非法字符"
            )

        # 检查扩展名
        if allowed_extensions:
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in allowed_extensions:
                return ValidationResult(
                    is_valid=False,
                    sanitized_value=None,
                    error_message=f"不支持的文件类型: .{ext}（允许: {', '.join(allowed_extensions)}）"
                )

        # 检查文件大小
        file_size = len(content)
        max_size_bytes = int(max_size_mb * 1024 * 1024)

        if file_size > max_size_bytes:
            return ValidationResult(
                is_valid=False,
                sanitized_value=None,
                error_message=f"文件过大（{file_size / 1024 / 1024:.2f}MB，限制{max_size_mb}MB）"
            )

        return ValidationResult(
            is_valid=True,
            sanitized_value=content,
            warnings=warnings
        )


# 全局验证器实例
input_validator = InputValidator()


__all__ = [
    "InputValidator",
    "ValidationResult",
    "ValidationLevel",
    "input_validator"
]

