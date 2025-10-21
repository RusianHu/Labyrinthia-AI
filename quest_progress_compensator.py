"""
任务进度智能补偿系统
当玩家完成所有任务目标但进度未达到100%时，自动补足进度
"""

import logging
from typing import Dict, List, Any, Optional
from data_models import GameState, Quest, Monster
from progress_manager import progress_manager, ProgressEventType, ProgressContext
from config import config

logger = logging.getLogger(__name__)


class QuestProgressCompensator:
    """任务进度补偿器"""
    
    def __init__(self):
        self.compensation_history: List[Dict[str, Any]] = []
    
    async def check_and_compensate(self, game_state: GameState) -> Dict[str, Any]:
        """检查并补偿任务进度"""
        result = {
            "compensated": False,
            "compensation_amount": 0.0,
            "reason": "",
            "details": {}
        }
        
        # 获取活跃任务
        active_quest = self._get_active_quest(game_state)
        if not active_quest:
            return result
        
        # 检查是否需要补偿
        compensation_info = self._analyze_compensation_need(game_state, active_quest)
        
        if compensation_info["needs_compensation"]:
            # 执行补偿
            compensation_amount = compensation_info["compensation_amount"]
            reason = compensation_info["reason"]
            
            logger.info(f"Compensating quest progress: +{compensation_amount:.1f}% ({reason})")
            
            # 直接更新进度
            old_progress = active_quest.progress_percentage
            active_quest.progress_percentage = min(100.0, old_progress + compensation_amount)
            
            # 记录补偿
            compensation_record = {
                "quest_id": active_quest.id,
                "quest_title": active_quest.title,
                "old_progress": old_progress,
                "new_progress": active_quest.progress_percentage,
                "compensation_amount": compensation_amount,
                "reason": reason,
                "details": compensation_info["details"]
            }
            self.compensation_history.append(compensation_record)
            
            # 添加消息
            game_state.pending_events.append(
                f"✨ 探索完成！任务进度 +{compensation_amount:.1f}%"
            )
            
            # 检查是否完成任务
            if active_quest.progress_percentage >= 100.0:
                await self._complete_quest(game_state, active_quest)
            
            result["compensated"] = True
            result["compensation_amount"] = compensation_amount
            result["reason"] = reason
            result["details"] = compensation_info["details"]
        
        return result
    
    def _analyze_compensation_need(self, game_state: GameState, quest: Quest) -> Dict[str, Any]:
        """分析是否需要补偿"""
        info = {
            "needs_compensation": False,
            "compensation_amount": 0.0,
            "reason": "",
            "details": {}
        }
        
        current_progress = quest.progress_percentage
        current_depth = game_state.current_map.depth
        
        # 情况1：在最后一层且清空了所有敌人
        if current_depth >= max(quest.target_floors) if quest.target_floors else config.game.max_quest_floors:
            if len(game_state.monsters) == 0:
                # 检查是否所有任务怪物都已击败
                all_quest_monsters_defeated = self._check_all_quest_monsters_defeated(game_state, quest)
                
                if all_quest_monsters_defeated and current_progress < 100.0:
                    # 计算缺少的进度
                    deficit = 100.0 - current_progress
                    info["needs_compensation"] = True
                    info["compensation_amount"] = deficit
                    info["reason"] = "最后一层已清空，所有任务目标已完成"
                    info["details"]["all_monsters_defeated"] = True
                    info["details"]["current_depth"] = current_depth
                    info["details"]["progress_deficit"] = deficit
                    return info
        
        # 情况2：清空当前楼层的所有敌人（给予探索奖励）
        if len(game_state.monsters) == 0 and current_progress < 100.0:
            # 检查当前楼层是否有任务目标
            floor_has_objectives = self._check_floor_has_objectives(quest, current_depth)
            
            if floor_has_objectives:
                # 给予楼层清空奖励（5-10%）
                exploration_bonus = min(10.0, (100.0 - current_progress) * 0.1)
                info["needs_compensation"] = True
                info["compensation_amount"] = exploration_bonus
                info["reason"] = f"第{current_depth}层探索完成"
                info["details"]["floor_cleared"] = True
                info["details"]["current_depth"] = current_depth
                info["details"]["exploration_bonus"] = exploration_bonus
                return info
        
        # 情况3：所有必须完成的任务事件都已触发
        all_mandatory_events_triggered = self._check_all_mandatory_events_triggered(game_state, quest)
        if all_mandatory_events_triggered and current_progress < 95.0:
            # 给予事件完成奖励
            event_bonus = min(5.0, 95.0 - current_progress)
            info["needs_compensation"] = True
            info["compensation_amount"] = event_bonus
            info["reason"] = "所有必须事件已完成"
            info["details"]["all_events_triggered"] = True
            info["details"]["event_bonus"] = event_bonus
            return info
        
        return info
    
    def _check_all_quest_monsters_defeated(self, game_state: GameState, quest: Quest) -> bool:
        """检查所有任务怪物是否都已击败"""
        if not quest.special_monsters:
            return True
        
        # 获取当前存活的怪物ID
        alive_monster_quest_ids = set()
        for monster in game_state.monsters:
            if hasattr(monster, 'quest_monster_id') and monster.quest_monster_id:
                alive_monster_quest_ids.add(monster.quest_monster_id)
        
        # 检查是否所有任务怪物都不在存活列表中
        for quest_monster in quest.special_monsters:
            if quest_monster.id in alive_monster_quest_ids:
                return False
        
        return True
    
    def _get_attr(self, obj, attr_name, default=None):
        """统一获取对象属性（兼容字典和对象）"""
        if isinstance(obj, dict):
            return obj.get(attr_name, default)
        else:
            return getattr(obj, attr_name, default)

    def _check_floor_has_objectives(self, quest: Quest, floor: int) -> bool:
        """检查楼层是否有任务目标"""
        # 检查事件
        for event in quest.special_events:
            location_hint = self._get_attr(event, 'location_hint', '')
            if location_hint and str(floor) in location_hint:
                return True

        # 检查怪物
        for monster in quest.special_monsters:
            location_hint = self._get_attr(monster, 'location_hint', '')
            if location_hint and str(floor) in location_hint:
                return True

        return False
    
    def _check_all_mandatory_events_triggered(self, game_state: GameState, quest: Quest) -> bool:
        """检查所有必须事件是否都已触发"""
        # 兼容字典/对象：使用统一取值以避免类型不一致导致的异常
        mandatory_events = [e for e in quest.special_events if self._get_attr(e, 'is_mandatory', False)]
        if not mandatory_events:
            return False

        # 检查地图上的事件状态
        triggered_event_ids = set()
        for tile in game_state.current_map.tiles.values():
            if tile.has_event and tile.event_triggered:
                event_data = tile.event_data or {}
                quest_event_id = event_data.get('quest_event_id')
                if quest_event_id:
                    triggered_event_ids.add(quest_event_id)

        # 检查是否所有必须事件都已触发
        for event in mandatory_events:
            ev_id = self._get_attr(event, 'id')
            if ev_id not in triggered_event_ids:
                return False

        return True
    
    def _get_active_quest(self, game_state: GameState) -> Optional[Quest]:
        """获取当前活跃任务"""
        for quest in game_state.quests:
            if quest.is_active and not quest.is_completed:
                return quest
        return None
    
    async def _complete_quest(self, game_state: GameState, quest: Quest):
        """完成任务"""
        quest.is_completed = True
        quest.is_active = False
        quest.progress_percentage = 100.0

        # 给予经验奖励
        game_state.player.stats.experience += quest.experience_reward

        # 添加完成消息
        completion_message = f"🎉 任务完成：{quest.title}！获得 {quest.experience_reward} 经验值！"
        game_state.pending_events.append(completion_message)

        # 添加任务完成特效
        quest_completion_effect = {
            "type": "quest_completion",
            "quest_title": quest.title,
            "experience_reward": quest.experience_reward,
            "message": completion_message,
            "completed_quest": quest.to_dict()
        }
        game_state.pending_effects.append(quest_completion_effect)

        # 【修复】设置任务完成选择标志，让游戏引擎处理选择系统
        if not hasattr(game_state, 'pending_quest_completion'):
            game_state.pending_quest_completion = None
        game_state.pending_quest_completion = quest

        # 设置新任务生成标志，确保玩家始终有活跃任务
        if not hasattr(game_state, 'pending_new_quest_generation'):
            game_state.pending_new_quest_generation = False
        game_state.pending_new_quest_generation = True

        logger.info(f"Quest '{quest.title}' completed via compensation system")
    
    def get_compensation_summary(self) -> Dict[str, Any]:
        """获取补偿摘要"""
        if not self.compensation_history:
            return {
                "total_compensations": 0,
                "total_amount": 0.0,
                "history": []
            }
        
        total_amount = sum(record["compensation_amount"] for record in self.compensation_history)
        
        return {
            "total_compensations": len(self.compensation_history),
            "total_amount": total_amount,
            "history": self.compensation_history[-10:]  # 最近10条记录
        }
    
    def clear_history(self):
        """清空历史记录"""
        self.compensation_history.clear()


# 全局补偿器实例
quest_progress_compensator = QuestProgressCompensator()


# 导出
__all__ = [
    "QuestProgressCompensator",
    "quest_progress_compensator"
]

