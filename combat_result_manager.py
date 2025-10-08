"""
Labyrinthia AI - 战斗结果管理器
统一管理战斗结果处理，包括怪物死亡、经验获取、掉落物品和LLM叙述生成
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from data_models import GameState, Monster, Character, Item
from llm_service import llm_service
from prompt_manager import prompt_manager
from config import config


logger = logging.getLogger(__name__)


class CombatResultType(Enum):
    """战斗结果类型"""
    MONSTER_DEFEATED = "monster_defeated"
    BOSS_DEFEATED = "boss_defeated"
    QUEST_MONSTER_DEFEATED = "quest_monster_defeated"
    PLAYER_VICTORY = "player_victory"
    PLAYER_DEFEAT = "player_defeat"


@dataclass
class CombatResult:
    """战斗结果数据"""
    result_type: CombatResultType
    defeated_monster: Optional[Monster] = None
    damage_dealt: int = 0
    experience_gained: int = 0
    level_up: bool = False
    loot_items: List[Item] = field(default_factory=list)
    quest_progress: float = 0.0
    is_quest_monster: bool = False
    is_boss: bool = False
    narrative: str = ""
    events: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "result_type": self.result_type.value,
            "defeated_monster": self.defeated_monster.to_dict() if self.defeated_monster else None,
            "damage_dealt": self.damage_dealt,
            "experience_gained": self.experience_gained,
            "level_up": self.level_up,
            "loot_items": [item.to_dict() for item in self.loot_items],
            "quest_progress": self.quest_progress,
            "is_quest_monster": self.is_quest_monster,
            "is_boss": self.is_boss,
            "narrative": self.narrative,
            "events": self.events
        }


class CombatResultManager:
    """战斗结果管理器"""
    
    def __init__(self):
        self.combat_history: List[CombatResult] = []
        self.total_monsters_defeated: int = 0
        self.total_bosses_defeated: int = 0
        
    async def process_monster_defeat(
        self, 
        game_state: GameState, 
        monster: Monster,
        damage_dealt: int
    ) -> CombatResult:
        """
        处理怪物被击败
        
        Args:
            game_state: 游戏状态
            monster: 被击败的怪物
            damage_dealt: 造成的伤害
            
        Returns:
            CombatResult: 战斗结果
        """
        logger.info(f"Processing monster defeat: {monster.name}")
        
        # 确定战斗结果类型
        result_type = self._determine_result_type(monster)
        
        # 创建战斗结果对象
        combat_result = CombatResult(
            result_type=result_type,
            defeated_monster=monster,
            damage_dealt=damage_dealt,
            is_boss=monster.is_boss,
            is_quest_monster=bool(monster.quest_monster_id)
        )
        
        # 计算经验值
        combat_result.experience_gained = self._calculate_experience(monster)
        
        # 应用经验值并检查升级
        old_level = game_state.player.stats.level
        game_state.player.stats.experience += combat_result.experience_gained
        combat_result.level_up = self._check_level_up(game_state.player)
        
        # 生成战利品
        combat_result.loot_items = await self._generate_loot(game_state, monster)
        
        # 检查任务进度
        if monster.quest_monster_id:
            combat_result.quest_progress = await self._update_quest_progress(
                game_state, monster
            )
        
        # 构建事件列表
        combat_result.events = self._build_combat_events(combat_result, old_level)
        
        # 生成LLM叙述
        combat_result.narrative = await self._generate_combat_narrative(
            game_state, combat_result
        )
        
        # 更新统计
        self.total_monsters_defeated += 1
        if monster.is_boss:
            self.total_bosses_defeated += 1
        
        # 记录到历史
        self.combat_history.append(combat_result)
        self._cleanup_history()
        
        logger.info(f"Combat result processed: {result_type.value}, exp: {combat_result.experience_gained}")
        
        return combat_result
    
    def _determine_result_type(self, monster: Monster) -> CombatResultType:
        """确定战斗结果类型"""
        if monster.is_boss:
            return CombatResultType.BOSS_DEFEATED
        elif monster.quest_monster_id:
            return CombatResultType.QUEST_MONSTER_DEFEATED
        else:
            return CombatResultType.MONSTER_DEFEATED
    
    def _calculate_experience(self, monster: Monster) -> int:
        """计算经验值"""
        base_exp = int(monster.challenge_rating * 100)
        
        # Boss额外奖励
        if monster.is_boss:
            base_exp = int(base_exp * 2.0)
        
        # 任务怪物额外奖励
        if monster.quest_monster_id:
            base_exp = int(base_exp * 1.5)
        
        return base_exp
    
    def _check_level_up(self, player: Character) -> bool:
        """检查并处理升级"""
        exp_needed = player.stats.level * 1000
        
        if player.stats.experience >= exp_needed:
            player.stats.level += 1
            player.stats.experience -= exp_needed
            
            # 提升属性
            player.stats.max_hp += 10
            player.stats.hp = player.stats.max_hp
            player.stats.max_mp += 5
            player.stats.mp = player.stats.max_mp
            player.stats.ac += 1
            
            logger.info(f"Player leveled up to {player.stats.level}")
            return True
        
        return False
    
    async def _generate_loot(self, game_state: GameState, monster: Monster) -> List[Item]:
        """生成战利品"""
        loot_items = []
        
        try:
            # 根据怪物类型决定掉落概率
            drop_chance = 0.3  # 基础30%掉落率
            
            if monster.is_boss:
                drop_chance = 1.0  # Boss必定掉落
            elif monster.quest_monster_id:
                drop_chance = 0.6  # 任务怪物60%掉落
            
            import random
            if random.random() < drop_chance:
                from content_generator import content_generator
                
                # 根据怪物挑战等级生成物品
                rarity = "common"
                if monster.is_boss:
                    rarity = "rare"
                elif monster.challenge_rating >= 3.0:
                    rarity = "uncommon"
                
                items = await content_generator.generate_loot_items(
                    game_state.player.stats.level,
                    rarity=rarity,
                    count=1
                )
                
                if items:
                    loot_items.extend(items)
                    # 将物品添加到玩家背包
                    game_state.player.inventory.extend(items)
                    logger.info(f"Generated loot: {[item.name for item in items]}")
        
        except Exception as e:
            logger.error(f"Failed to generate loot: {e}")
        
        return loot_items
    
    async def _update_quest_progress(self, game_state: GameState, monster: Monster) -> float:
        """更新任务进度"""
        try:
            # 查找活跃任务
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if not active_quest:
                return 0.0
            
            # 查找对应的任务怪物
            quest_monster = next(
                (qm for qm in active_quest.special_monsters if qm.id == monster.quest_monster_id),
                None
            )
            
            if quest_monster:
                progress_value = quest_monster.progress_value
                logger.info(f"Quest progress updated: +{progress_value}%")
                return progress_value
        
        except Exception as e:
            logger.error(f"Failed to update quest progress: {e}")
        
        return 0.0
    
    def _build_combat_events(self, combat_result: CombatResult, old_level: int) -> List[str]:
        """构建战斗事件列表"""
        events = []
        
        # 击败怪物
        monster_name = combat_result.defeated_monster.name if combat_result.defeated_monster else "怪物"
        events.append(f"{monster_name} 被击败了！")
        
        # 经验值
        events.append(f"获得了 {combat_result.experience_gained} 点经验")
        
        # 升级
        if combat_result.level_up:
            events.append(f"恭喜升级！等级提升至 {old_level + 1}")
        
        # 战利品
        if combat_result.loot_items:
            for item in combat_result.loot_items:
                events.append(f"获得了 {item.name}")
        
        # 任务进度
        if combat_result.quest_progress > 0:
            events.append(f"任务进度 +{combat_result.quest_progress}%")
        
        return events
    
    async def _generate_combat_narrative(
        self, 
        game_state: GameState, 
        combat_result: CombatResult
    ) -> str:
        """生成战斗叙述"""
        try:
            # 获取活跃任务信息
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            quest_info = ""
            if active_quest:
                quest_info = f"\n当前任务：{active_quest.title}\n任务进度：{active_quest.progress_percentage:.1f}%"
            
            # 构建提示
            prompt = prompt_manager.format_prompt(
                "combat_victory_narrative",
                player_name=game_state.player.name,
                player_level=game_state.player.stats.level,
                player_hp=game_state.player.stats.hp,
                player_max_hp=game_state.player.stats.max_hp,
                monster_name=combat_result.defeated_monster.name,
                monster_description=combat_result.defeated_monster.description,
                is_boss=combat_result.is_boss,
                is_quest_monster=combat_result.is_quest_monster,
                damage_dealt=combat_result.damage_dealt,
                experience_gained=combat_result.experience_gained,
                level_up=combat_result.level_up,
                loot_items=[item.name for item in combat_result.loot_items],
                quest_progress=combat_result.quest_progress,
                map_name=game_state.current_map.name,
                map_depth=game_state.current_map.depth,
                quest_info=quest_info
            )
            
            # 调用LLM生成叙述
            narrative = await llm_service._async_generate(prompt)
            
            # 调试日志
            if config.game.show_llm_debug:
                logger.info(f"Combat narrative prompt: {prompt}")
                logger.info(f"Combat narrative response: {narrative}")
            
            return narrative
        
        except Exception as e:
            logger.error(f"Failed to generate combat narrative: {e}")
            return self._get_fallback_narrative(combat_result)
    
    def _get_fallback_narrative(self, combat_result: CombatResult) -> str:
        """获取降级叙述"""
        monster_name = combat_result.defeated_monster.name if combat_result.defeated_monster else "怪物"
        
        if combat_result.is_boss:
            return f"经过激烈的战斗，你终于击败了强大的Boss {monster_name}！这是一场值得铭记的胜利。"
        elif combat_result.is_quest_monster:
            return f"你成功击败了任务目标 {monster_name}，离完成任务又近了一步。"
        else:
            return f"你击败了 {monster_name}，继续前进吧。"
    
    def _cleanup_history(self):
        """清理历史记录"""
        max_history = 20
        if len(self.combat_history) > max_history:
            self.combat_history = self.combat_history[-max_history:]
    
    def get_recent_combats(self, count: int = 5) -> List[CombatResult]:
        """获取最近的战斗记录"""
        return self.combat_history[-count:]
    
    def get_combat_statistics(self) -> Dict[str, Any]:
        """获取战斗统计"""
        return {
            "total_monsters_defeated": self.total_monsters_defeated,
            "total_bosses_defeated": self.total_bosses_defeated,
            "total_experience_gained": sum(c.experience_gained for c in self.combat_history),
            "recent_combats": len(self.combat_history)
        }


# 全局实例
combat_result_manager = CombatResultManager()

