"""
Labyrinthia AI - 统一的 LLM 上下文日志管理器
Unified LLM Context Log Manager for centralized context management
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from enum import Enum

from config import config

logger = logging.getLogger(__name__)


class ContextEntryType(Enum):
    """上下文条目类型"""
    MOVEMENT = "movement"
    COMBAT_ATTACK = "combat_attack"
    COMBAT_DEFENSE = "combat_defense"
    ITEM_USE = "item_use"
    EVENT_TRIGGER = "event_trigger"
    MAP_TRANSITION = "map_transition"
    QUEST_PROGRESS = "quest_progress"
    EXPLORATION = "exploration"
    CHOICE_EVENT = "choice_event"
    NARRATIVE = "narrative"
    SYSTEM = "system"


@dataclass
class ContextEntry:
    """上下文条目"""
    entry_type: ContextEntryType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0
    
    def __post_init__(self):
        """自动估算token数量"""
        if self.token_estimate == 0:
            self.token_estimate = self._estimate_tokens()
    
    def _estimate_tokens(self) -> int:
        """估算token数量（中文约2.5字符=1token）"""
        total_chars = len(self.content)
        # 添加metadata的字符数
        total_chars += len(str(self.metadata))
        return int(total_chars / 2.5)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "entry_type": self.entry_type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "token_estimate": self.token_estimate
        }


class LLMContextManager:
    """
    统一的 LLM 上下文日志管理器
    
    功能：
    1. 集中管理所有 LLM 交互的上下文
    2. 智能清理和长度控制
    3. 可配置的上下文策略
    4. 调试和监控支持
    """
    
    def __init__(self):
        # 主上下文存储
        self.context_entries: List[ContextEntry] = []

        # 分类存储（用于快速检索）
        self.entries_by_type: Dict[ContextEntryType, List[ContextEntry]] = {
            entry_type: [] for entry_type in ContextEntryType
        }

        # 配置参数（从config读取，带默认值）
        self.max_context_tokens = getattr(config.llm, 'max_history_tokens', 10240)
        self.min_context_entries = getattr(config.llm, 'min_context_entries', 5)
        self.cleanup_threshold = getattr(config.llm, 'context_cleanup_threshold', 0.8)

        # 统计信息
        self.total_entries_added = 0
        self.total_entries_cleaned = 0
        self.current_token_count = 0

        logger.info(f"LLMContextManager initialized with max_tokens={self.max_context_tokens}, "
                   f"min_entries={self.min_context_entries}, threshold={self.cleanup_threshold}")
    
    def add_entry(
        self,
        entry_type: ContextEntryType,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ContextEntry:
        """
        添加上下文条目
        
        Args:
            entry_type: 条目类型
            content: 内容文本
            metadata: 元数据
            
        Returns:
            创建的上下文条目
        """
        entry = ContextEntry(
            entry_type=entry_type,
            content=content,
            metadata=metadata or {},
        )
        
        # 添加到主列表
        self.context_entries.append(entry)
        
        # 添加到分类列表
        self.entries_by_type[entry_type].append(entry)
        
        # 更新统计
        self.total_entries_added += 1
        self.current_token_count += entry.token_estimate
        
        # 检查是否需要清理
        if self._should_cleanup():
            self._cleanup_context()
        
        logger.debug(f"Added context entry: {entry_type.value}, tokens={entry.token_estimate}")
        
        return entry
    
    def add_movement(self, position: Tuple[int, int], events: List[str]) -> ContextEntry:
        """添加移动上下文"""
        content = f"移动到位置 ({position[0]}, {position[1]})"
        if events:
            content += f": {', '.join(events)}"
        
        return self.add_entry(
            ContextEntryType.MOVEMENT,
            content,
            {"position": position, "events": events}
        )
    
    def add_combat(
        self,
        is_attack: bool,
        attacker: str,
        target: str,
        damage: int,
        result: str
    ) -> ContextEntry:
        """添加战斗上下文"""
        entry_type = ContextEntryType.COMBAT_ATTACK if is_attack else ContextEntryType.COMBAT_DEFENSE
        content = f"{attacker} 攻击 {target}，造成 {damage} 点伤害。{result}"
        
        return self.add_entry(
            entry_type,
            content,
            {
                "attacker": attacker,
                "target": target,
                "damage": damage,
                "result": result
            }
        )
    
    def add_event(self, event_type: str, description: str, data: Optional[Dict] = None) -> ContextEntry:
        """添加事件上下文"""
        return self.add_entry(
            ContextEntryType.EVENT_TRIGGER,
            description,
            {"event_type": event_type, "data": data or {}}
        )
    
    def add_choice(
        self,
        choice_type: str,
        choice_text: str,
        result: str
    ) -> ContextEntry:
        """添加选择事件上下文"""
        content = f"选择: {choice_text} -> {result}"
        
        return self.add_entry(
            ContextEntryType.CHOICE_EVENT,
            content,
            {"choice_type": choice_type, "choice_text": choice_text, "result": result}
        )
    
    def add_narrative(self, narrative: str, context_type: str = "general") -> ContextEntry:
        """添加叙述文本"""
        return self.add_entry(
            ContextEntryType.NARRATIVE,
            narrative,
            {"context_type": context_type}
        )
    
    def get_recent_context(
        self,
        max_entries: Optional[int] = None,
        max_tokens: Optional[int] = None,
        entry_types: Optional[List[ContextEntryType]] = None
    ) -> List[ContextEntry]:
        """
        获取最近的上下文
        
        Args:
            max_entries: 最大条目数
            max_tokens: 最大token数
            entry_types: 筛选的条目类型
            
        Returns:
            上下文条目列表
        """
        # 筛选类型
        if entry_types:
            entries = [e for e in self.context_entries if e.entry_type in entry_types]
        else:
            entries = self.context_entries.copy()
        
        # 按时间倒序
        entries.reverse()
        
        # 限制数量
        if max_entries:
            entries = entries[:max_entries]
        
        # 限制token数
        if max_tokens:
            selected = []
            token_count = 0
            for entry in entries:
                if token_count + entry.token_estimate <= max_tokens:
                    selected.append(entry)
                    token_count += entry.token_estimate
                else:
                    break
            entries = selected
        
        # 恢复时间顺序
        entries.reverse()
        
        return entries
    
    def build_context_string(
        self,
        max_entries: Optional[int] = None,
        max_tokens: Optional[int] = None,
        entry_types: Optional[List[ContextEntryType]] = None,
        include_metadata: bool = False
    ) -> str:
        """
        构建上下文字符串（用于传递给LLM）
        
        Args:
            max_entries: 最大条目数
            max_tokens: 最大token数
            entry_types: 筛选的条目类型
            include_metadata: 是否包含元数据
            
        Returns:
            格式化的上下文字符串
        """
        entries = self.get_recent_context(max_entries, max_tokens, entry_types)
        
        if not entries:
            return ""
        
        lines = ["=== 最近的游戏上下文 ==="]
        for entry in entries:
            timestamp_str = entry.timestamp.strftime("%H:%M:%S")
            line = f"[{timestamp_str}] [{entry.entry_type.value}] {entry.content}"
            
            if include_metadata and entry.metadata:
                line += f" (元数据: {entry.metadata})"
            
            lines.append(line)
        
        lines.append("=" * 30)
        
        return "\n".join(lines)
    
    def _should_cleanup(self) -> bool:
        """检查是否应该清理上下文"""
        threshold_tokens = int(self.max_context_tokens * self.cleanup_threshold)
        return self.current_token_count > threshold_tokens
    
    def _cleanup_context(self):
        """清理上下文（保留最近的重要条目）"""
        if len(self.context_entries) <= self.min_context_entries:
            return
        
        target_tokens = int(self.max_context_tokens * 0.6)  # 清理到60%
        
        # 从最旧的条目开始删除
        while self.current_token_count > target_tokens and len(self.context_entries) > self.min_context_entries:
            removed_entry = self.context_entries.pop(0)
            
            # 从分类列表中删除
            if removed_entry in self.entries_by_type[removed_entry.entry_type]:
                self.entries_by_type[removed_entry.entry_type].remove(removed_entry)
            
            # 更新统计
            self.current_token_count -= removed_entry.token_estimate
            self.total_entries_cleaned += 1
        
        logger.info(f"Context cleaned: removed {self.total_entries_cleaned} entries, "
                   f"current tokens={self.current_token_count}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_entries": len(self.context_entries),
            "total_entries_added": self.total_entries_added,
            "total_entries_cleaned": self.total_entries_cleaned,
            "current_token_count": self.current_token_count,
            "max_context_tokens": self.max_context_tokens,
            "token_usage_percent": round(self.current_token_count / self.max_context_tokens * 100, 2),
            "entries_by_type": {
                entry_type.value: len(entries)
                for entry_type, entries in self.entries_by_type.items()
            }
        }
    
    def clear_all(self):
        """清空所有上下文"""
        self.context_entries.clear()
        for entry_list in self.entries_by_type.values():
            entry_list.clear()
        self.current_token_count = 0
        logger.info("All context cleared")


# 全局单例
llm_context_manager = LLMContextManager()

