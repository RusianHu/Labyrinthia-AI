"""
Labyrinthia AI - 游戏进程管理器
Progress manager for controlling game flow and quest progression
"""

import asyncio
import hashlib
import logging
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from config import config
from data_models import GameState, Quest, Character, Monster, GameMap
from llm_service import llm_service
from generation_contract import resolve_generation_contract


logger = logging.getLogger(__name__)


class ProgressEventType(Enum):
    """进度事件类型"""
    MAP_TRANSITION = "map_transition"      # 地图切换
    COMBAT_VICTORY = "combat_victory"      # 战斗胜利
    TREASURE_FOUND = "treasure_found"      # 发现宝藏
    STORY_EVENT = "story_event"           # 剧情事件
    EXPLORATION = "exploration"           # 探索进度
    OBJECTIVE_COMPLETE = "objective_complete"  # 目标完成
    CUSTOM_EVENT = "custom_event"         # 自定义事件


@dataclass
class ProgressRule:
    """进度规则配置"""
    event_type: ProgressEventType
    base_increment: float = 0.0           # 基础进度增量
    multiplier: float = 1.0               # 进度倍数
    max_increment: float = 100.0          # 最大单次增量
    condition_check: Optional[Callable] = None  # 条件检查函数
    custom_calculator: Optional[Callable] = None  # 自定义计算函数
    
    def calculate_progress(self, context: Any = None, current_progress: float = 0.0) -> float:
        """计算进度增量"""
        if self.custom_calculator:
            return self.custom_calculator(context, current_progress)
        
        increment = self.base_increment * self.multiplier
        return min(increment, self.max_increment)


@dataclass
class ProgressContext:
    """进度上下文信息"""
    event_type: ProgressEventType
    game_state: GameState
    context_data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProgressManager:
    """游戏进程管理器"""
    
    def __init__(self):
        self.progress_rules: Dict[ProgressEventType, ProgressRule] = {}
        self.event_handlers: Dict[ProgressEventType, List[Callable]] = {}
        self.progress_history: List[ProgressContext] = []
        
        # 初始化默认规则
        self._setup_default_rules()
    
    def _setup_default_rules(self):
        """设置默认进度规则"""
        # 地图切换规则 - 基于楼层变化量计算（修复：改为固定增量而非绝对深度）
        self.progress_rules[ProgressEventType.MAP_TRANSITION] = ProgressRule(
            event_type=ProgressEventType.MAP_TRANSITION,
            custom_calculator=self._calculate_map_transition_progress
        )

        # 【修复】战斗胜利规则 - 支持任务专属怪物的自定义进度值
        self.progress_rules[ProgressEventType.COMBAT_VICTORY] = ProgressRule(
            event_type=ProgressEventType.COMBAT_VICTORY,
            base_increment=3.0,  # 降低普通战斗进度（原5.0）
            multiplier=1.0,
            custom_calculator=self._calculate_combat_victory_progress
        )

        # 探索规则
        self.progress_rules[ProgressEventType.EXPLORATION] = ProgressRule(
            event_type=ProgressEventType.EXPLORATION,
            base_increment=1.5,  # 降低探索进度（原2.0）
            multiplier=1.0
        )

        # 【修复】剧情事件规则 - 支持任务专属事件的自定义进度值
        self.progress_rules[ProgressEventType.STORY_EVENT] = ProgressRule(
            event_type=ProgressEventType.STORY_EVENT,
            base_increment=8.0,  # 降低普通事件进度（原10.0）
            multiplier=1.0,
            custom_calculator=self._calculate_story_event_progress
        )

    def _calculate_map_transition_progress(self, context: Any, current_progress: float) -> float:
        """计算地图切换的进度增量

        【重要修复】改为基于楼层变化量而非绝对深度计算
        这样可以避免进度跳跃式增长，确保每次切换楼层都是固定增量
        """
        if not isinstance(context, dict):
            # 兼容旧的调用方式（直接传入depth整数）
            # 这种情况下使用固定增量
            return config.game.map_transition_progress

        # 新的调用方式：传入包含old_depth和new_depth的字典
        old_depth = context.get('old_depth', 0)
        new_depth = context.get('new_depth', 0)

        # 计算楼层变化量（绝对值，上楼或下楼都算）
        depth_change = abs(new_depth - old_depth)

        if depth_change == 0:
            # 没有楼层变化，不增加进度
            return 0.0

        # 使用配置的地图切换进度增量
        # 每次切换楼层固定增加配置的百分比
        increment = config.game.map_transition_progress * depth_change

        # 应用单次进度增量上限，避免进度跳跃过大
        max_single_increment = config.game.max_single_progress_increment
        increment = min(increment, max_single_increment)

        logger.info(f"Map transition progress: {old_depth} -> {new_depth}, increment: {increment:.1f}%")

        return increment

    def _calculate_combat_victory_progress(self, context: Any, current_progress: float) -> float:
        """计算战斗胜利的进度增量"""
        if not isinstance(context, dict):
            return 3.0  # 默认进度值（已降低）

        # 检查是否是任务专属怪物
        if 'progress_value' in context:
            progress_value = context['progress_value']
            logger.info(f"Quest monster defeated, using custom progress: {progress_value}%")
            return progress_value

        # 普通怪物使用默认进度值
        return 3.0

    def _calculate_story_event_progress(self, context: Any, current_progress: float) -> float:
        """计算剧情事件的进度增量"""
        if not isinstance(context, dict):
            return 8.0  # 默认进度值（已降低）

        # 检查是否是任务专属事件
        if 'progress_value' in context:
            progress_value = context['progress_value']
            logger.info(f"Quest event triggered, using custom progress: {progress_value}%")
            return progress_value

        # 普通事件使用默认进度值
        return 8.0
    
    def register_rule(self, rule: ProgressRule):
        """注册进度规则"""
        self.progress_rules[rule.event_type] = rule
        logger.info(f"Registered progress rule for {rule.event_type}")
    
    def register_event_handler(self, event_type: ProgressEventType, handler: Callable):
        """注册事件处理器"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.info(f"Registered event handler for {event_type}")
    
    async def process_event(self, progress_context: ProgressContext) -> Dict[str, Any]:
        """处理进度事件"""
        try:
            # 记录事件历史
            self.progress_history.append(progress_context)
            
            # 获取当前活跃任务
            active_quest = self._get_active_quest(progress_context.game_state)
            if not active_quest:
                return {"success": False, "message": "没有活跃任务"}
            
            self._ensure_progress_plan_defaults(active_quest, progress_context)
            self._ensure_completion_guard_defaults(active_quest)

            # 幂等：同一任务怪重复结算仅生效一次
            if self._is_duplicate_quest_monster_settlement(active_quest, progress_context.context_data):
                self._append_progress_ledger(
                    quest=active_quest,
                    event_type=progress_context.event_type,
                    increment=0.0,
                    old_progress=active_quest.progress_percentage,
                    new_progress=active_quest.progress_percentage,
                    context_data=progress_context.context_data,
                    note="duplicate_quest_monster_settlement_ignored",
                )
                return {
                    "success": True,
                    "progress_increment": 0.0,
                    "new_progress": active_quest.progress_percentage,
                    "quest_completed": active_quest.is_completed,
                    "message": "重复任务怪结算已忽略",
                }

            # 计算进度增量
            progress_increment = await self._calculate_progress_increment(
                progress_context, active_quest
            )
            
            # 更新任务进度
            result = await self._update_quest_progress(
                progress_context, active_quest, progress_increment
            )

            # 记录进度异常指标
            anomalies = self._detect_progress_anomalies(progress_context, active_quest, progress_increment)
            if not isinstance(progress_context.game_state.generation_metrics, dict):
                progress_context.game_state.generation_metrics = {}
            metrics = progress_context.game_state.generation_metrics.get("progress_metrics")
            if not isinstance(metrics, dict):
                metrics = {
                    "total_events": 0,
                    "anomaly_events": 0,
                    "anomaly_codes": {},
                    "final_objective_direct_completion": 0,
                    "final_objective_guard_blocked": 0,
                    "final_objective_guard_blocked_reasons": {},
                }
            metrics["total_events"] = int(metrics.get("total_events", 0) or 0) + 1
            if anomalies:
                metrics["anomaly_events"] = int(metrics.get("anomaly_events", 0) or 0) + 1
                anomaly_codes = metrics.get("anomaly_codes") if isinstance(metrics.get("anomaly_codes"), dict) else {}
                for code in anomalies:
                    key = str(code)
                    anomaly_codes[key] = int(anomaly_codes.get(key, 0) or 0) + 1
                metrics["anomaly_codes"] = anomaly_codes
            if bool(progress_context.metadata.get("final_objective_guard_passed", False)):
                metrics["final_objective_direct_completion"] = int(metrics.get("final_objective_direct_completion", 0) or 0) + 1
            if bool(progress_context.metadata.get("final_objective_hit", False)) and not bool(progress_context.metadata.get("final_objective_guard_passed", False)):
                metrics["final_objective_guard_blocked"] = int(metrics.get("final_objective_guard_blocked", 0) or 0) + 1
                guard_reasons = progress_context.metadata.get("final_objective_guard_reasons")
                reason_counter = (
                    metrics.get("final_objective_guard_blocked_reasons")
                    if isinstance(metrics.get("final_objective_guard_blocked_reasons"), dict)
                    else {}
                )
                if isinstance(guard_reasons, list):
                    for reason in guard_reasons:
                        key = str(reason)
                        reason_counter[key] = int(reason_counter.get(key, 0) or 0) + 1
                metrics["final_objective_guard_blocked_reasons"] = reason_counter
            progress_context.game_state.generation_metrics["progress_metrics"] = metrics
            result["progress_anomalies"] = anomalies

            # 执行事件处理器
            await self._execute_event_handlers(progress_context)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing progress event: {e}")
            return {"success": False, "message": f"处理进度事件失败: {e}"}
    
    def _get_active_quest(self, game_state: GameState) -> Optional[Quest]:
        """获取当前活跃任务"""
        for quest in game_state.quests:
            if quest.is_active and not quest.is_completed:
                return quest
        return None
    
    async def _calculate_progress_increment(self, context: ProgressContext, quest: Quest) -> float:
        """计算进度增量"""
        rule = self.progress_rules.get(context.event_type)
        if not rule:
            logger.warning(f"No rule found for event type: {context.event_type}")
            return 0.0
        
        # 检查条件
        if rule.condition_check and not rule.condition_check(context):
            return 0.0
        
        # 计算增量
        increment = rule.calculate_progress(
            context.context_data,
            quest.progress_percentage
        )

        old_progress = float(quest.progress_percentage or 0.0)
        guard = quest.completion_guard if isinstance(quest.completion_guard, dict) else {}
        max_single = float(guard.get("max_single_increment_except_final", 25.0) or 25.0)

        final_objective_hit = False
        final_objective_guard_passed = False
        guard_reasons: List[str] = []

        plan = quest.progress_plan if isinstance(getattr(quest, "progress_plan", None), dict) else {}
        completion_policy = str(plan.get("completion_policy", "aggregate") or "aggregate")

        if context.event_type == ProgressEventType.COMBAT_VICTORY and self._is_final_objective(quest, context.context_data):
            final_objective_hit = True
            guard_reasons = self._check_completion_guard(context.game_state, quest, old_progress)
            final_objective_guard_passed = len(guard_reasons) == 0
            if final_objective_guard_passed:
                allow_final_burst = completion_policy in {"single_target_100", "hybrid"}
                if allow_final_burst:
                    increment = max(0.0, 100.0 - old_progress)
                else:
                    final_objective_guard_passed = False
                    guard_reasons.append("completion_policy_disallow_final_burst")
                    increment = min(float(increment), max_single)
            else:
                increment = min(float(increment), max_single)

        if not final_objective_hit:
            increment = min(float(increment), max_single)

        increment = self._apply_budget_guard(context, quest, increment)

        context.metadata["final_objective_hit"] = final_objective_hit
        context.metadata["final_objective_guard_passed"] = final_objective_guard_passed
        context.metadata["final_objective_guard_reasons"] = guard_reasons
        context.metadata["max_single_increment_except_final"] = max_single
        context.metadata["completion_policy"] = completion_policy

        return max(0.0, float(increment))
    
    async def _update_quest_progress(self, context: ProgressContext, quest: Quest, increment: float) -> Dict[str, Any]:
        """更新任务进度"""
        old_progress = quest.progress_percentage
        new_progress = min(100.0, old_progress + increment)

        final_objective_hit = bool(context.metadata.get("final_objective_hit", False))
        final_objective_guard_passed = bool(context.metadata.get("final_objective_guard_passed", False))
        final_objective_guard_reasons = context.metadata.get("final_objective_guard_reasons", [])

        # 【新增】检查是否为调试清理（跳过LLM交互）
        is_debug_clear = (
            isinstance(context.context_data, dict) and
            context.context_data.get("debug_clear", False)
        )

        if is_debug_clear:
            # 调试清理模式：仅更新进度数值，不触发LLM交互
            logger.info(f"Debug clear mode: updating progress without LLM interaction ({old_progress:.1f}% -> {new_progress:.1f}%)")
            quest.progress_percentage = new_progress
            self._mark_quest_monster_defeated(quest, context.context_data)

            # 检查任务完成（但不触发LLM）
            if new_progress >= 100.0:
                await self._complete_quest(context.game_state, quest)

            self._append_progress_ledger(
                quest=quest,
                event_type=context.event_type,
                increment=increment,
                old_progress=old_progress,
                new_progress=new_progress,
                context_data=context.context_data,
                note="debug_mode",
            )

            return {
                "success": True,
                "progress_increment": increment,
                "new_progress": new_progress,
                "quest_completed": quest.is_completed,
                "message": f"任务进度更新: {old_progress:.1f}% -> {new_progress:.1f}% (调试模式)",
                "debug_mode": True
            }

        # 正常模式：构建LLM提示
        prompt = self._build_progress_update_prompt(context, quest, old_progress, new_progress)

        try:
            # 调用LLM更新任务内容
            result = await llm_service._async_generate_json(prompt)

            if result:
                # 更新任务数据
                quest.progress_percentage = new_progress
                self._mark_quest_monster_defeated(quest, context.context_data)
                quest.story_context = result.get("story_context", quest.story_context)
                quest.llm_notes = result.get("llm_notes", quest.llm_notes)

                # 检查任务完成
                if new_progress >= 100.0 or result.get("should_complete", False):
                    await self._complete_quest(context.game_state, quest)

                # 更新目标
                if result.get("new_objectives"):
                    quest.objectives = result["new_objectives"]
                    quest.completed_objectives = [False] * len(quest.objectives)

                note_parts = []
                if final_objective_hit and final_objective_guard_passed:
                    note_parts.append("final_objective_direct_completion")
                if final_objective_hit and not final_objective_guard_passed:
                    note_parts.append("final_objective_guard_blocked")
                    if isinstance(final_objective_guard_reasons, list) and final_objective_guard_reasons:
                        note_parts.append("reasons=" + ",".join([str(r) for r in final_objective_guard_reasons]))

                anomalies = self._detect_progress_anomalies(context, quest, increment)
                if anomalies:
                    note_parts.append("anomalies=" + ",".join(anomalies))

                self._append_progress_ledger(
                    quest=quest,
                    event_type=context.event_type,
                    increment=increment,
                    old_progress=old_progress,
                    new_progress=new_progress,
                    context_data=context.context_data,
                    note=";".join(note_parts),
                )

                return {
                    "success": True,
                    "progress_increment": increment,
                    "new_progress": new_progress,
                    "quest_completed": quest.is_completed,
                    "story_update": result.get("story_context", ""),
                    "guard_reasons": final_objective_guard_reasons if final_objective_hit else [],
                    "message": f"任务进度更新: {old_progress:.1f}% -> {new_progress:.1f}%"
                }

        except Exception as e:
            logger.error(f"Failed to update quest progress with LLM: {e}")
            # 降级处理：仅更新进度数值
            quest.progress_percentage = new_progress
            self._mark_quest_monster_defeated(quest, context.context_data)

            if new_progress >= 100.0:
                await self._complete_quest(context.game_state, quest)

        note_parts = []
        if final_objective_hit and final_objective_guard_passed:
            note_parts.append("final_objective_direct_completion")
        if final_objective_hit and not final_objective_guard_passed:
            note_parts.append("final_objective_guard_blocked")
            if isinstance(final_objective_guard_reasons, list) and final_objective_guard_reasons:
                note_parts.append("reasons=" + ",".join([str(r) for r in final_objective_guard_reasons]))

        anomalies = self._detect_progress_anomalies(context, quest, increment)
        if anomalies:
            note_parts.append("anomalies=" + ",".join(anomalies))

        self._append_progress_ledger(
            quest=quest,
            event_type=context.event_type,
            increment=increment,
            old_progress=old_progress,
            new_progress=new_progress,
            context_data=context.context_data,
            note=";".join(note_parts),
        )

        return {
            "success": True,
            "progress_increment": increment,
            "new_progress": new_progress,
            "quest_completed": quest.is_completed,
            "guard_reasons": final_objective_guard_reasons if final_objective_hit else [],
            "message": f"任务进度更新: {old_progress:.1f}% -> {new_progress:.1f}%"
        }
    
    def _ensure_progress_plan_defaults(self, quest: Quest, context: ProgressContext) -> None:
        contract = resolve_generation_contract().contract
        contract_progress = contract.get("progress", {}) if isinstance(contract.get("progress"), dict) else {}
        existing = quest.progress_plan if isinstance(getattr(quest, "progress_plan", None), dict) else {}

        completion_policy = existing.get("completion_policy")
        if completion_policy not in {"aggregate", "single_target_100", "hybrid"}:
            completion_policy = contract_progress.get("completion_policy", "aggregate")

        budget = existing.get("budget") if isinstance(existing.get("budget"), dict) else {}

        def _safe_float(value: Any, default_value: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default_value

        normalized_budget = {
            "events": max(0.0, _safe_float(budget.get("events", 0.0), 0.0)),
            "quest_monsters": max(0.0, _safe_float(budget.get("quest_monsters", 0.0), 0.0)),
            "map_transition": max(0.0, _safe_float(budget.get("map_transition", 0.0), 0.0)),
            "exploration_buffer": max(0.0, _safe_float(budget.get("exploration_buffer", 0.0), 0.0)),
        }

        if sum(normalized_budget.values()) <= 0.0:
            normalized_budget = {
                "events": 30.0,
                "quest_monsters": 40.0,
                "map_transition": 20.0,
                "exploration_buffer": 10.0,
            }

        quest.progress_plan = {
            "completion_policy": completion_policy,
            "budget": normalized_budget,
            "final_objective_id": str(existing.get("final_objective_id", "") or ""),
        }

        if not isinstance(getattr(quest, "progress_ledger", None), list):
            quest.progress_ledger = []
        if not isinstance(getattr(quest, "defeated_quest_monster_ids", None), list):
            quest.defeated_quest_monster_ids = []

    def _event_bucket_key(self, event_type: ProgressEventType) -> str:
        if event_type == ProgressEventType.COMBAT_VICTORY:
            return "quest_monsters"
        if event_type == ProgressEventType.STORY_EVENT:
            return "events"
        if event_type == ProgressEventType.MAP_TRANSITION:
            return "map_transition"
        return "exploration_buffer"

    def _apply_budget_guard(self, context: ProgressContext, quest: Quest, increment: float) -> float:
        plan = quest.progress_plan if isinstance(getattr(quest, "progress_plan", None), dict) else {}
        budget = plan.get("budget") if isinstance(plan.get("budget"), dict) else {}
        if not budget:
            return max(0.0, float(increment))

        ledger = quest.progress_ledger if isinstance(getattr(quest, "progress_ledger", None), list) else []
        consumed: Dict[str, float] = {
            "events": 0.0,
            "quest_monsters": 0.0,
            "map_transition": 0.0,
            "exploration_buffer": 0.0,
        }
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            bucket = str(entry.get("bucket", "") or "")
            if bucket in consumed:
                try:
                    consumed[bucket] += float(entry.get("increment", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue

        bucket = self._event_bucket_key(context.event_type)
        bucket_budget = float(budget.get(bucket, 0.0) or 0.0)
        bucket_left = max(0.0, bucket_budget - consumed.get(bucket, 0.0))
        applied = min(float(increment), bucket_left)

        context.metadata["budget_bucket"] = bucket
        context.metadata["budget_bucket_total"] = bucket_budget
        context.metadata["budget_bucket_consumed"] = consumed.get(bucket, 0.0)
        context.metadata["budget_bucket_left"] = bucket_left
        if applied < float(increment):
            context.metadata["budget_guard_limited"] = True
            context.metadata["budget_guard_reason"] = "bucket_budget_exhausted"
        return max(0.0, applied)

    def _detect_progress_anomalies(self, context: ProgressContext, quest: Quest, increment: float) -> List[str]:
        anomalies: List[str] = []
        if increment > 70.0 and not bool(context.metadata.get("final_objective_guard_passed", False)):
            anomalies.append("single_increment_spike")

        if isinstance(context.context_data, dict):
            quest_monster_id = context.context_data.get("quest_monster_id")
            if quest_monster_id and not isinstance(quest_monster_id, str):
                anomalies.append("invalid_quest_monster_id_type")
            elif isinstance(quest_monster_id, str):
                known_ids = {m.id for m in quest.special_monsters}
                if quest_monster_id and quest_monster_id not in known_ids:
                    anomalies.append("illegal_quest_monster_id")

        return anomalies

    def _ensure_completion_guard_defaults(self, quest: Quest) -> None:
        contract = resolve_generation_contract().contract
        progress_cfg = contract.get("progress", {}) if isinstance(contract.get("progress"), dict) else {}
        guard = quest.completion_guard if isinstance(getattr(quest, "completion_guard", None), dict) else {}

        quest.completion_guard = {
            "require_final_floor": bool(guard.get("require_final_floor", progress_cfg.get("require_final_floor", False))),
            "require_all_mandatory_events": bool(
                guard.get("require_all_mandatory_events", progress_cfg.get("require_all_mandatory_events", False))
            ),
            "min_progress_before_final_burst": float(
                guard.get("min_progress_before_final_burst", progress_cfg.get("min_progress_before_final_burst", 70.0)) or 70.0
            ),
            "max_single_increment_except_final": float(
                guard.get("max_single_increment_except_final", progress_cfg.get("max_single_increment_except_final", 25.0)) or 25.0
            ),
        }

    def _is_duplicate_quest_monster_settlement(self, quest: Quest, context_data: Any) -> bool:
        if not isinstance(context_data, dict):
            return False
        quest_monster_id = context_data.get("quest_monster_id")
        if not isinstance(quest_monster_id, str) or not quest_monster_id:
            return False
        return quest_monster_id in quest.defeated_quest_monster_ids

    def _mark_quest_monster_defeated(self, quest: Quest, context_data: Any) -> None:
        if not isinstance(context_data, dict):
            return
        quest_monster_id = context_data.get("quest_monster_id")
        if not isinstance(quest_monster_id, str) or not quest_monster_id:
            return
        if quest_monster_id not in quest.defeated_quest_monster_ids:
            quest.defeated_quest_monster_ids.append(quest_monster_id)

    def _append_progress_ledger(
        self,
        quest: Quest,
        event_type: ProgressEventType,
        increment: float,
        old_progress: float,
        new_progress: float,
        context_data: Any,
        note: str = "",
    ) -> None:
        bucket = self._event_bucket_key(event_type)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type.value,
            "bucket": bucket,
            "increment": float(increment),
            "old_progress": float(old_progress),
            "new_progress": float(new_progress),
            "context": context_data if isinstance(context_data, dict) else {},
            "note": note,
        }
        quest.progress_ledger.append(entry)
        if len(quest.progress_ledger) > 500:
            quest.progress_ledger = quest.progress_ledger[-500:]

    def _all_mandatory_events_triggered(self, game_state: GameState, quest: Quest) -> bool:
        mandatory_ids = [e.id for e in quest.special_events if getattr(e, "is_mandatory", False)]
        if not mandatory_ids:
            return True
        triggered = set()
        for tile in game_state.current_map.tiles.values():
            if tile.has_event and tile.event_triggered and isinstance(tile.event_data, dict):
                event_id = tile.event_data.get("quest_event_id")
                if isinstance(event_id, str) and event_id:
                    triggered.add(event_id)
        return all(event_id in triggered for event_id in mandatory_ids)

    def _is_final_objective(self, quest: Quest, context_data: Any) -> bool:
        if not isinstance(context_data, dict):
            return False
        quest_monster_id = context_data.get("quest_monster_id")
        if not isinstance(quest_monster_id, str) or not quest_monster_id:
            return False

        monster = next((m for m in quest.special_monsters if m.id == quest_monster_id), None)
        if not monster:
            return False

        if bool(getattr(monster, "is_final_objective", False)):
            return True

        plan = quest.progress_plan if isinstance(quest.progress_plan, dict) else {}
        final_objective_id = str(plan.get("final_objective_id", "") or "")
        return bool(final_objective_id and final_objective_id == quest_monster_id)

    def _check_completion_guard(self, game_state: GameState, quest: Quest, old_progress: float) -> List[str]:
        reasons: List[str] = []
        guard = quest.completion_guard if isinstance(quest.completion_guard, dict) else {}

        require_final_floor = bool(guard.get("require_final_floor", False))
        require_all_mandatory_events = bool(guard.get("require_all_mandatory_events", False))
        min_progress_before_final_burst = float(guard.get("min_progress_before_final_burst", 70.0) or 70.0)

        max_target_floor = max(quest.target_floors) if quest.target_floors else config.game.max_quest_floors
        if require_final_floor and game_state.current_map.depth < max_target_floor:
            reasons.append("require_final_floor_not_met")

        if require_all_mandatory_events and not self._all_mandatory_events_triggered(game_state, quest):
            reasons.append("require_all_mandatory_events_not_met")

        if old_progress < min_progress_before_final_burst:
            reasons.append("min_progress_before_final_burst_not_met")

        return reasons

    def _build_progress_update_prompt(self, context: ProgressContext, quest: Quest,
                                    old_progress: float, new_progress: float) -> str:
        """构建进度更新的LLM提示"""
        return f"""
        任务进度更新请求：

        当前任务信息：
        - 标题：{quest.title}
        - 描述：{quest.description}
        - 原进度：{old_progress:.1f}%
        - 新进度：{new_progress:.1f}%
        - 故事背景：{quest.story_context}
        - LLM笔记：{quest.llm_notes}

        触发事件：
        - 事件类型：{context.event_type.value}
        - 事件数据：{context.context_data}
        - 玩家等级：{context.game_state.player.stats.level}
        - 当前地图：{context.game_state.current_map.name}
        - 地图深度：{context.game_state.current_map.depth}

        进度控制说明：
        - 进度已从 {old_progress:.1f}% 更新到 {new_progress:.1f}%
        - 最大楼层数：{config.game.max_quest_floors}
        - 地图切换进度增量：{config.game.map_transition_progress}%
        - 战斗胜利进度：{config.game.combat_victory_weight}%
        - 剧情事件进度：{config.game.story_event_weight}%

        请根据新的进度更新任务内容，返回JSON格式：
        {{
            "story_context": "更新的故事背景，反映当前进度和事件",
            "llm_notes": "LLM的内部笔记，用于控制节奏和记录重要信息",
            "should_complete": 是否应该完成任务(true/false，当进度达到100%时),
            "new_objectives": ["如果需要，更新的目标列表"],
            "narrative_update": "给玩家的叙述更新，描述当前进展"
        }}

        注意：
        1. 进度百分比由系统控制，你只需要更新故事内容
        2. 当进度达到100%时，任务应该完成
        3. 根据事件类型调整叙述风格
        4. 保持故事的连贯性和沉浸感
        """
    
    async def _complete_quest(self, game_state: GameState, quest: Quest):
        """完成任务"""
        quest.is_completed = True
        quest.is_active = False
        quest.progress_percentage = 100.0

        # 给予经验奖励
        game_state.player.stats.experience += quest.experience_reward

        # 添加完成事件和特效标记
        completion_message = f"任务完成：{quest.title}！获得 {quest.experience_reward} 经验值！"
        game_state.pending_events.append(completion_message)

        # 添加任务完成特效标记
        quest_completion_effect = {
            "type": "quest_completion",
            "quest_title": quest.title,
            "experience_reward": quest.experience_reward,
            "message": completion_message,
            "timestamp": self._get_current_timestamp(),
            "completed_quest": quest.to_dict()  # 添加完整的任务数据
        }

        # 将特效信息添加到游戏状态中，供前端使用
        if not hasattr(game_state, 'pending_effects'):
            game_state.pending_effects = []
        game_state.pending_effects.append(quest_completion_effect)

        # 设置任务完成选择标志，让游戏引擎处理选择系统
        if not hasattr(game_state, 'pending_quest_completion'):
            game_state.pending_quest_completion = None
        game_state.pending_quest_completion = quest

        # 设置新任务生成标志，确保玩家始终有活跃任务
        if not hasattr(game_state, 'pending_new_quest_generation'):
            game_state.pending_new_quest_generation = False
        game_state.pending_new_quest_generation = True

        logger.info(f"Quest completed: {quest.title}")

    def _get_current_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    async def _execute_event_handlers(self, context: ProgressContext):
        """执行事件处理器"""
        handlers = self.event_handlers.get(context.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(context)
                else:
                    handler(context)
            except Exception as e:
                logger.error(f"Error executing event handler: {e}")
    
    def get_progress_summary(self, game_state: GameState) -> Dict[str, Any]:
        """获取进度摘要"""
        active_quest = self._get_active_quest(game_state)
        if not active_quest:
            return {"has_active_quest": False}
        
        return {
            "has_active_quest": True,
            "quest_title": active_quest.title,
            "progress_percentage": active_quest.progress_percentage,
            "story_context": active_quest.story_context,
            "objectives": active_quest.objectives,
            "completed_objectives": active_quest.completed_objectives,
            "is_near_completion": active_quest.progress_percentage >= 80.0
        }
    
    def clear_history(self, keep_recent: int = 100):
        """清理历史记录，保留最近的记录"""
        if len(self.progress_history) > keep_recent:
            self.progress_history = self.progress_history[-keep_recent:]


# 全局进程管理器实例
progress_manager = ProgressManager()


# 导出
__all__ = [
    "ProgressManager",
    "ProgressEventType", 
    "ProgressRule",
    "ProgressContext",
    "progress_manager"
]
