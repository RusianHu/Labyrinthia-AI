"""
Labyrinthia AI - 统一的 LLM 上下文日志管理器
Unified LLM Context Log Manager for centralized context management
"""

import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from enum import Enum
from contextvars import ContextVar, Token
from contextlib import contextmanager

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
        total_chars += len(str(self.metadata))
        return int(total_chars / 2.5)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "entry_type": self.entry_type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "token_estimate": self.token_estimate,
        }


@dataclass
class ContextSession:
    """单个会话的上下文容器"""
    context_entries: List[ContextEntry] = field(default_factory=list)
    entries_by_type: Dict[ContextEntryType, List[ContextEntry]] = field(
        default_factory=lambda: {entry_type: [] for entry_type in ContextEntryType}
    )
    total_entries_added: int = 0
    total_entries_cleaned: int = 0
    current_token_count: int = 0


class LLMContextManager:
    """
    统一的 LLM 上下文日志管理器（按 context_key 隔离）

    说明：
    - 默认 context_key 为 "global"，保持向后兼容。
    - 推荐在业务层使用 "{user_id}:{game_id}" 作为 context_key，避免跨用户串话。
    """

    def __init__(self):
        self.sessions: Dict[str, ContextSession] = {}
        self.max_context_tokens = getattr(config.llm, "max_history_tokens", 10240)
        self.min_context_entries = getattr(config.llm, "min_context_entries", 5)
        self.cleanup_threshold = getattr(config.llm, "context_cleanup_threshold", 0.8)
        self._lock = RLock()

        self._current_context_key: ContextVar[str] = ContextVar(
            "llm_context_key", default="global"
        )

        logger.info(
            "LLMContextManager initialized with max_tokens=%s, min_entries=%s, threshold=%s",
            self.max_context_tokens,
            self.min_context_entries,
            self.cleanup_threshold,
        )

    def _normalize_context_key(self, context_key: Optional[str]) -> str:
        if context_key is None:
            context_key = self._current_context_key.get()
        key = str(context_key or "global").strip()
        return key or "global"

    def set_current_context_key(self, context_key: Optional[str]) -> Token:
        """设置当前协程上下文键，并返回可用于恢复的Token。"""
        key = self._normalize_context_key(context_key)
        return self._current_context_key.set(key)

    def reset_current_context_key(self, token: Token):
        """恢复之前的上下文键。"""
        self._current_context_key.reset(token)

    def get_current_context_key(self) -> str:
        """获取当前协程上下文键。"""
        return self._normalize_context_key(None)

    @contextmanager
    def use_context_key(self, context_key: Optional[str]):
        """临时切换当前协程上下文键。"""
        token = self.set_current_context_key(context_key)
        try:
            yield
        finally:
            self.reset_current_context_key(token)

    def _get_or_create_session(self, context_key: Optional[str]) -> ContextSession:
        key = self._normalize_context_key(context_key)
        with self._lock:
            if key not in self.sessions:
                self.sessions[key] = ContextSession()
            return self.sessions[key]

    def add_entry(
        self,
        entry_type: ContextEntryType,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        context_key: Optional[str] = None,
    ) -> ContextEntry:
        """添加上下文条目"""
        session = self._get_or_create_session(context_key)
        entry = ContextEntry(entry_type=entry_type, content=content, metadata=metadata or {})

        with self._lock:
            session.context_entries.append(entry)
            session.entries_by_type[entry_type].append(entry)
            session.total_entries_added += 1
            session.current_token_count += entry.token_estimate

            if self._should_cleanup(session):
                self._cleanup_context(session)

        logger.debug(
            "Added context entry: type=%s tokens=%s context_key=%s",
            entry_type.value,
            entry.token_estimate,
            self._normalize_context_key(context_key),
        )
        return entry

    def add_movement(
        self,
        position: Tuple[int, int],
        events: List[str],
        context_key: Optional[str] = None,
    ) -> ContextEntry:
        """添加移动上下文"""
        content = f"移动到位置 ({position[0]}, {position[1]})"
        if events:
            content += f": {', '.join(events)}"

        return self.add_entry(
            ContextEntryType.MOVEMENT,
            content,
            {"position": position, "events": events},
            context_key=context_key,
        )

    def add_combat(
        self,
        is_attack: bool,
        attacker: str,
        target: str,
        damage: int,
        result: str,
        context_key: Optional[str] = None,
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
                "result": result,
            },
            context_key=context_key,
        )

    def add_event(
        self,
        event_type: str,
        description: str,
        data: Optional[Dict[str, Any]] = None,
        context_key: Optional[str] = None,
    ) -> ContextEntry:
        """添加事件上下文"""
        return self.add_entry(
            ContextEntryType.EVENT_TRIGGER,
            description,
            {"event_type": event_type, "data": data or {}},
            context_key=context_key,
        )

    def add_choice(
        self,
        choice_type: str,
        choice_text: str,
        result: str,
        context_key: Optional[str] = None,
    ) -> ContextEntry:
        """添加选择事件上下文"""
        content = f"选择: {choice_text} -> {result}"
        return self.add_entry(
            ContextEntryType.CHOICE_EVENT,
            content,
            {
                "choice_type": choice_type,
                "choice_text": choice_text,
                "result": result,
            },
            context_key=context_key,
        )

    def add_narrative(
        self,
        narrative: str,
        context_type: str = "general",
        context_key: Optional[str] = None,
    ) -> ContextEntry:
        """添加叙述文本"""
        return self.add_entry(
            ContextEntryType.NARRATIVE,
            narrative,
            {"context_type": context_type},
            context_key=context_key,
        )

    def get_recent_context(
        self,
        max_entries: Optional[int] = None,
        max_tokens: Optional[int] = None,
        entry_types: Optional[List[ContextEntryType]] = None,
        context_key: Optional[str] = None,
    ) -> List[ContextEntry]:
        """获取最近上下文"""
        session = self._get_or_create_session(context_key)

        with self._lock:
            if entry_types:
                entries = [e for e in session.context_entries if e.entry_type in entry_types]
            else:
                entries = session.context_entries.copy()

        entries.reverse()

        if max_entries:
            entries = entries[:max_entries]

        if max_tokens:
            selected: List[ContextEntry] = []
            token_count = 0
            for entry in entries:
                if token_count + entry.token_estimate <= max_tokens:
                    selected.append(entry)
                    token_count += entry.token_estimate
                else:
                    break
            entries = selected

        entries.reverse()
        return entries

    def build_context_string(
        self,
        max_entries: Optional[int] = None,
        max_tokens: Optional[int] = None,
        entry_types: Optional[List[ContextEntryType]] = None,
        include_metadata: bool = False,
        context_key: Optional[str] = None,
    ) -> str:
        """构建传给LLM的上下文文本"""
        entries = self.get_recent_context(
            max_entries=max_entries,
            max_tokens=max_tokens,
            entry_types=entry_types,
            context_key=context_key,
        )

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

    def _should_cleanup(self, session: ContextSession) -> bool:
        threshold_tokens = int(self.max_context_tokens * self.cleanup_threshold)
        return session.current_token_count > threshold_tokens

    def _cleanup_context(self, session: ContextSession):
        if len(session.context_entries) <= self.min_context_entries:
            return

        target_tokens = int(self.max_context_tokens * 0.6)
        while (
            session.current_token_count > target_tokens
            and len(session.context_entries) > self.min_context_entries
        ):
            removed_entry = session.context_entries.pop(0)
            if removed_entry in session.entries_by_type[removed_entry.entry_type]:
                session.entries_by_type[removed_entry.entry_type].remove(removed_entry)
            session.current_token_count -= removed_entry.token_estimate
            session.total_entries_cleaned += 1

    def get_statistics(self, context_key: Optional[str] = None) -> Dict[str, Any]:
        """获取统计信息（指定 context_key 时返回会话统计，否则返回全局概览）"""
        if context_key is not None:
            session = self._get_or_create_session(context_key)
            with self._lock:
                return {
                    "context_key": self._normalize_context_key(context_key),
                    "total_entries": len(session.context_entries),
                    "total_entries_added": session.total_entries_added,
                    "total_entries_cleaned": session.total_entries_cleaned,
                    "current_token_count": session.current_token_count,
                    "max_context_tokens": self.max_context_tokens,
                    "token_usage_percent": round(
                        (session.current_token_count / self.max_context_tokens) * 100, 2
                    ) if self.max_context_tokens > 0 else 0,
                    "entries_by_type": {
                        entry_type.value: len(entries)
                        for entry_type, entries in session.entries_by_type.items()
                    },
                }

        with self._lock:
            total_entries = 0
            total_tokens = 0
            for session in self.sessions.values():
                total_entries += len(session.context_entries)
                total_tokens += session.current_token_count

            return {
                "session_count": len(self.sessions),
                "total_entries": total_entries,
                "total_token_count": total_tokens,
                "max_context_tokens": self.max_context_tokens,
            }

    def clear_all(self, context_key: Optional[str] = None):
        """清空上下文（指定 context_key 时仅清理该会话）"""
        if context_key is not None:
            key = self._normalize_context_key(context_key)
            with self._lock:
                self.sessions[key] = ContextSession()
            logger.info("Context cleared for context_key=%s", key)
            return

        with self._lock:
            self.sessions.clear()
        logger.info("All context cleared")

    def serialize_recent_context(
        self,
        max_entries: Optional[int] = None,
        context_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """序列化最近上下文"""
        entries = self.get_recent_context(max_entries=max_entries, context_key=context_key)
        return [e.to_dict() for e in entries]

    def restore_context(
        self,
        entries: List[Dict[str, Any]],
        append: bool = False,
        max_entries: Optional[int] = None,
        context_key: Optional[str] = None,
    ) -> int:
        """恢复上下文"""
        try:
            key = self._normalize_context_key(context_key)
            if not append:
                self.clear_all(context_key=key)

            session = self._get_or_create_session(key)
            items = entries[-max_entries:] if (max_entries and len(entries) > max_entries) else entries

            restored = 0
            with self._lock:
                for d in items:
                    try:
                        et_str = d.get("entry_type", ContextEntryType.SYSTEM.value)
                        try:
                            et = ContextEntryType(et_str)
                        except Exception:
                            et = ContextEntryType.SYSTEM

                        ts = None
                        ts_str = d.get("timestamp")
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str)
                            except Exception:
                                ts = datetime.now()

                        token_est = d.get("token_estimate", 0)
                        if not isinstance(token_est, int):
                            token_est = 0

                        entry = ContextEntry(
                            entry_type=et,
                            content=str(d.get("content", "")),
                            timestamp=ts or datetime.now(),
                            metadata=d.get("metadata", {}),
                            token_estimate=token_est,
                        )

                        session.context_entries.append(entry)
                        session.entries_by_type[et].append(entry)
                        session.current_token_count += entry.token_estimate
                        session.total_entries_added += 1
                        restored += 1
                    except Exception as inner_ex:
                        logger.warning("Skip invalid context entry during restore: %s", inner_ex)

            logger.info("Restored %s LLM context entries (append=%s, context_key=%s)", restored, append, key)
            return restored
        except Exception as e:
            logger.warning("Failed to restore LLM context: %s", e)
            return 0


# 全局单例
llm_context_manager = LLMContextManager()
