"""
Labyrinthia AI - 游戏进程管理器
Progress manager for controlling game flow and quest progression
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from config import config
from data_models import GameState, Quest, Character, Monster, GameMap
from llm_service import llm_service


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
        # 地图切换规则 - 基于楼层深度计算
        self.progress_rules[ProgressEventType.MAP_TRANSITION] = ProgressRule(
            event_type=ProgressEventType.MAP_TRANSITION,
            custom_calculator=self._calculate_map_transition_progress
        )
        
        # 战斗胜利规则
        self.progress_rules[ProgressEventType.COMBAT_VICTORY] = ProgressRule(
            event_type=ProgressEventType.COMBAT_VICTORY,
            base_increment=5.0,
            multiplier=1.0
        )
        
        # 探索规则
        self.progress_rules[ProgressEventType.EXPLORATION] = ProgressRule(
            event_type=ProgressEventType.EXPLORATION,
            base_increment=2.0,
            multiplier=1.0
        )
        
        # 剧情事件规则
        self.progress_rules[ProgressEventType.STORY_EVENT] = ProgressRule(
            event_type=ProgressEventType.STORY_EVENT,
            base_increment=10.0,
            multiplier=1.0
        )
    
    def _calculate_map_transition_progress(self, context: Any, current_progress: float) -> float:
        """计算地图切换的进度增量"""
        if not isinstance(context, int):
            return 0.0
        
        current_depth = context
        # 使用配置的进度系数
        progress_per_floor = config.game.quest_progress_multiplier
        new_progress = current_depth * progress_per_floor
        
        # 返回增量而不是绝对值
        return max(0.0, new_progress - current_progress)
    
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
            
            # 计算进度增量
            progress_increment = await self._calculate_progress_increment(
                progress_context, active_quest
            )
            
            # 更新任务进度
            result = await self._update_quest_progress(
                progress_context, active_quest, progress_increment
            )
            
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
        
        return increment
    
    async def _update_quest_progress(self, context: ProgressContext, quest: Quest, increment: float) -> Dict[str, Any]:
        """更新任务进度"""
        old_progress = quest.progress_percentage
        new_progress = min(100.0, old_progress + increment)
        
        # 构建LLM提示
        prompt = self._build_progress_update_prompt(context, quest, old_progress, new_progress)
        
        try:
            # 调用LLM更新任务内容
            result = await llm_service._async_generate_json(prompt)
            
            if result:
                # 更新任务数据
                quest.progress_percentage = new_progress
                quest.story_context = result.get("story_context", quest.story_context)
                quest.llm_notes = result.get("llm_notes", quest.llm_notes)
                
                # 检查任务完成
                if new_progress >= 100.0 or result.get("should_complete", False):
                    await self._complete_quest(context.game_state, quest)
                
                # 更新目标
                if result.get("new_objectives"):
                    quest.objectives = result["new_objectives"]
                    quest.completed_objectives = [False] * len(quest.objectives)
                
                return {
                    "success": True,
                    "progress_increment": increment,
                    "new_progress": new_progress,
                    "quest_completed": quest.is_completed,
                    "story_update": result.get("story_context", ""),
                    "message": f"任务进度更新: {old_progress:.1f}% -> {new_progress:.1f}%"
                }
            
        except Exception as e:
            logger.error(f"Failed to update quest progress with LLM: {e}")
            # 降级处理：仅更新进度数值
            quest.progress_percentage = new_progress
            
            if new_progress >= 100.0:
                await self._complete_quest(context.game_state, quest)
        
        return {
            "success": True,
            "progress_increment": increment,
            "new_progress": new_progress,
            "quest_completed": quest.is_completed,
            "message": f"任务进度更新: {old_progress:.1f}% -> {new_progress:.1f}%"
        }
    
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
        - 进度系数：{config.game.quest_progress_multiplier}
        
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
