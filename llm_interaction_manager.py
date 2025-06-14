"""
Labyrinthia AI - LLM交互管理器
统一管理游戏中的LLM交互逻辑，确保上下文的连贯性和相关性
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

from data_models import GameState, Monster, Item
from llm_service import llm_service
from prompt_manager import prompt_manager
from config import config


logger = logging.getLogger(__name__)


class InteractionType(Enum):
    """LLM交互类型"""
    MOVEMENT = "movement"
    COMBAT_ATTACK = "combat_attack"
    COMBAT_DEFENSE = "combat_defense"
    ITEM_USE = "item_use"
    EVENT_TRIGGER = "event_trigger"
    MAP_TRANSITION = "map_transition"
    QUEST_PROGRESS = "quest_progress"
    EXPLORATION = "exploration"


@dataclass
class InteractionContext:
    """交互上下文数据"""
    interaction_type: InteractionType
    primary_action: str
    events: List[str]
    combat_data: Optional[Dict[str, Any]] = None
    item_data: Optional[Dict[str, Any]] = None
    movement_data: Optional[Dict[str, Any]] = None
    quest_data: Optional[Dict[str, Any]] = None
    environmental_changes: List[str] = None
    
    def __post_init__(self):
        if self.environmental_changes is None:
            self.environmental_changes = []


class LLMInteractionManager:
    """LLM交互管理器"""
    
    def __init__(self):
        self.recent_contexts: List[InteractionContext] = []
        self.combat_history: List[Dict[str, Any]] = []
        self.movement_trail: List[Tuple[int, int]] = []
        self.session_events: List[str] = []
    
    def add_context(self, context: InteractionContext):
        """添加交互上下文"""
        self.recent_contexts.append(context)
        
        # 记录到会话事件中
        self.session_events.extend(context.events)
        
        # 根据类型更新特定历史
        if context.interaction_type in [InteractionType.COMBAT_ATTACK, InteractionType.COMBAT_DEFENSE]:
            if context.combat_data:
                self.combat_history.append(context.combat_data)
        
        if context.movement_data:
            position = context.movement_data.get('new_position')
            if position:
                self.movement_trail.append(position)
        
        # 保持历史记录不过长
        self._cleanup_history()
    
    def _cleanup_history(self):
        """清理历史记录 - 基于数量和token估算的智能清理"""
        # 基础数量限制
        if len(self.recent_contexts) > 15:
            self.recent_contexts = self.recent_contexts[-10:]

        if len(self.combat_history) > 10:
            self.combat_history = self.combat_history[-7:]

        if len(self.movement_trail) > 15:
            self.movement_trail = self.movement_trail[-10:]

        if len(self.session_events) > 30:
            self.session_events = self.session_events[-20:]

        # Token估算清理
        self._cleanup_by_token_estimate()

    def _cleanup_by_token_estimate(self):
        """基于token估算进行清理"""
        # 估算当前历史记录的token数量
        estimated_tokens = self._estimate_history_tokens()
        max_history_tokens = getattr(config.llm, 'max_history_tokens', 2000)

        if estimated_tokens > max_history_tokens:
            # 逐步减少历史记录直到token数量合理
            while estimated_tokens > max_history_tokens and len(self.session_events) > 5:
                # 优先减少会话事件
                self.session_events = self.session_events[2:]
                estimated_tokens = self._estimate_history_tokens()

            while estimated_tokens > max_history_tokens and len(self.recent_contexts) > 3:
                # 然后减少交互上下文
                self.recent_contexts = self.recent_contexts[1:]
                estimated_tokens = self._estimate_history_tokens()

    def _estimate_history_tokens(self) -> int:
        """估算历史记录的token数量"""
        total_chars = 0

        # 估算会话事件的字符数
        for event in self.session_events:
            total_chars += len(str(event))

        # 估算交互上下文的字符数
        for context in self.recent_contexts:
            total_chars += len(str(context.events))
            total_chars += len(context.primary_action)

        # 估算战斗历史的字符数
        for combat in self.combat_history:
            total_chars += len(str(combat))

        # 粗略估算：中文约2-3字符=1token，英文约4字符=1token
        # 使用保守估算：2.5字符=1token
        estimated_tokens = int(total_chars / 2.5)

        return estimated_tokens
    
    async def generate_contextual_narrative(self, game_state: GameState,
                                          context: InteractionContext) -> str:
        """生成具有上下文的叙述文本"""

        # 构建详细的上下文信息
        context_info = self._build_context_info(game_state, context)

        try:
            # 使用PromptManager构建提示词
            game_context = prompt_manager.build_game_context(game_state)
            narrative_context = {
                **game_context,
                "recent_events": '; '.join(context_info['recent_events']),
                "combat_summary": context_info['combat_summary'],
                "movement_pattern": context_info['movement_pattern'],
                "environmental_state": context_info['environmental_state'],
                "quest_status": context_info['quest_status'],
                "current_events": '; '.join(context.events),
                "primary_action": context.primary_action
            }

            prompt = prompt_manager.format_prompt("general_narrative", **narrative_context)
            narrative = await llm_service._async_generate(prompt)
            logger.info(f"生成叙述文本 - 类型: {context.interaction_type.value}, 长度: {len(narrative)}")
            return narrative
        except Exception as e:
            logger.error(f"生成叙述文本失败: {e}")
            return self._get_fallback_narrative(context)
    
    def _build_context_info(self, game_state: GameState, context: InteractionContext) -> Dict[str, Any]:
        """构建上下文信息"""
        info = {
            "recent_events": self.session_events[-5:] if self.session_events else [],
            "combat_summary": self._get_combat_summary(),
            "movement_pattern": self._get_movement_pattern(),
            "environmental_state": self._get_environmental_state(game_state),
            "quest_status": self._get_quest_status(game_state)
        }
        
        return info
    
    def _get_combat_summary(self) -> str:
        """获取战斗摘要"""
        if not self.combat_history:
            return "无战斗记录"
        
        recent_combat = self.combat_history[-3:]
        summary_parts = []
        
        for combat in recent_combat:
            if combat.get('type') == 'player_attack':
                summary_parts.append(f"玩家攻击{combat.get('target', '敌人')}造成{combat.get('damage', 0)}伤害")
            elif combat.get('type') == 'monster_attack':
                summary_parts.append(f"{combat.get('attacker', '敌人')}攻击玩家造成{combat.get('damage', 0)}伤害")
        
        return "; ".join(summary_parts) if summary_parts else "无明显战斗"
    
    def _get_movement_pattern(self) -> str:
        """获取移动模式"""
        if len(self.movement_trail) < 2:
            return "刚开始探索"
        
        recent_moves = self.movement_trail[-3:]
        return f"移动轨迹: {' -> '.join([f'({x},{y})' for x, y in recent_moves])}"
    
    def _get_environmental_state(self, game_state: GameState) -> str:
        """获取环境状态"""
        player_pos = game_state.player.position
        current_tile = game_state.current_map.get_tile(*player_pos)
        
        env_info = [f"当前位置: {player_pos}"]
        
        if current_tile:
            env_info.append(f"地形: {current_tile.terrain.value}")
            if current_tile.has_event:
                env_info.append(f"事件类型: {current_tile.event_type}")
        
        # 检查周围怪物
        nearby_monsters = []
        for monster in game_state.monsters:
            mx, my = monster.position
            px, py = player_pos
            distance = max(abs(mx - px), abs(my - py))
            if distance <= 3:
                nearby_monsters.append(f"{monster.name}(距离{distance})")
        
        if nearby_monsters:
            env_info.append(f"附近敌人: {', '.join(nearby_monsters)}")
        
        return "; ".join(env_info)
    
    def _get_quest_status(self, game_state: GameState) -> str:
        """获取任务状态"""
        if not game_state.quests:
            return "无活跃任务"
        
        active_quest = None
        for quest in game_state.quests:
            if quest.is_active:
                active_quest = quest
                break
        
        if not active_quest:
            return "无活跃任务"
        
        return f"当前任务: {active_quest.title} (进度: {active_quest.progress_percentage:.1f}%)"
    
    def _build_prompt(self, game_state: GameState, context: InteractionContext, 
                     context_info: Dict[str, Any]) -> str:
        """构建LLM提示"""
        
        base_info = f"""
        玩家信息：
        - 名称：{game_state.player.name}
        - 等级：{game_state.player.stats.level}
        - 生命值：{game_state.player.stats.hp}/{game_state.player.stats.max_hp}
        - 位置：{game_state.player.position}
        
        当前地图：{game_state.current_map.name}
        回合数：{game_state.turn_count}
        
        上下文信息：
        - 最近事件：{'; '.join(context_info['recent_events'])}
        - 战斗情况：{context_info['combat_summary']}
        - 移动情况：{context_info['movement_pattern']}
        - 环境状态：{context_info['environmental_state']}
        - 任务状态：{context_info['quest_status']}
        """
        
        # 根据交互类型定制提示
        if context.interaction_type == InteractionType.COMBAT_DEFENSE:
            return f"""{base_info}
            
        刚刚发生的事件：{'; '.join(context.events)}
        
        玩家刚刚遭受了攻击！请生成一段生动的叙述，描述：
        1. 攻击的具体过程和玩家的反应
        2. 战斗的紧张氛围和环境变化
        3. 玩家当前的状态和可能的下一步行动
        4. 结合之前的战斗历史，展现战斗的连续性
        
        叙述应该体现战斗的激烈程度和玩家面临的挑战。(100-150字)
        """
        
        elif context.interaction_type == InteractionType.COMBAT_ATTACK:
            return f"""{base_info}
            
        刚刚发生的事件：{'; '.join(context.events)}
        
        玩家刚刚发动了攻击！请生成一段生动的叙述，描述：
        1. 攻击的具体动作和效果
        2. 敌人的反应和战场变化
        3. 战斗的进展和氛围
        4. 结合战斗历史，展现战术的运用
        
        叙述应该体现玩家的战斗技巧和战斗的动态变化。(100-150字)
        """
        
        elif context.interaction_type == InteractionType.MOVEMENT:
            return f"""{base_info}
            
        刚刚发生的事件：{'; '.join(context.events)}
        
        玩家进行了移动。请生成叙述，描述：
        1. 移动过程中的环境观察
        2. 新位置的特点和发现
        3. 结合移动历史，展现探索的进展
        4. 如果触发了特殊事件，重点描述事件的影响
        
        叙述应该体现探索的乐趣和发现的惊喜。(80-120字)
        """
        
        else:
            return f"""{base_info}
            
        刚刚发生的事件：{'; '.join(context.events)}
        主要行动：{context.primary_action}
        
        请根据当前情况和上下文信息，生成一段连贯的叙述文本，
        描述行动的结果、环境的变化和玩家的感受。(80-120字)
        """
    
    def _get_fallback_narrative(self, context: InteractionContext) -> str:
        """获取备用叙述文本"""
        # 使用PromptManager的备用消息
        interaction_type_map = {
            InteractionType.COMBAT_DEFENSE: "combat_defense",
            InteractionType.COMBAT_ATTACK: "combat_attack",
            InteractionType.MOVEMENT: "movement",
            InteractionType.ITEM_USE: "item_use",
            InteractionType.EVENT_TRIGGER: "event_trigger"
        }

        interaction_key = interaction_type_map.get(context.interaction_type, "default")
        return prompt_manager.get_fallback_message(interaction_key)


# 全局LLM交互管理器实例
llm_interaction_manager = LLMInteractionManager()

__all__ = ["LLMInteractionManager", "InteractionType", "InteractionContext", "llm_interaction_manager"]
