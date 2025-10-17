"""
Labyrinthia AI - 怪物生成管理器
统一管理所有怪物生成逻辑
"""

import logging
import random
from typing import List, Optional, Dict, Any, Tuple
import asyncio

from data_models import Monster, GameState, GameMap, Quest, TerrainType
from llm_service import llm_service
from config import config

logger = logging.getLogger(__name__)


class MonsterSpawnManager:
    """怪物生成管理器 - 统一管理所有怪物生成逻辑"""
    
    def __init__(self):
        """初始化怪物生成管理器"""
        self.spawn_history = []  # 生成历史记录
        
    async def generate_encounter_monsters(
        self, 
        player_level: int,
        encounter_difficulty: str = "medium",
        quest_context: Optional[Dict[str, Any]] = None
    ) -> List[Monster]:
        """
        生成遭遇怪物（普通怪物）
        
        Args:
            player_level: 玩家等级
            encounter_difficulty: 遭遇难度 (easy, medium, hard, deadly)
            quest_context: 任务上下文（可选，用于生成与任务相关的怪物）
        
        Returns:
            生成的怪物列表
        """
        # 根据难度确定怪物数量和挑战等级
        difficulty_config = {
            "easy": {"count": (1, 2), "cr_modifier": 0.5},
            "medium": {"count": (1, 3), "cr_modifier": 1.0},
            "normal": {"count": (1, 3), "cr_modifier": 1.0},  # 别名
            "hard": {"count": (2, 4), "cr_modifier": 1.5},
            "deadly": {"count": (3, 6), "cr_modifier": 2.0}
        }
        
        config_data = difficulty_config.get(encounter_difficulty, difficulty_config["medium"])
        monster_count = random.randint(*config_data["count"])
        base_cr = max(0.25, player_level * config_data["cr_modifier"])
        
        monsters = []
        
        # 构建上下文信息
        context_info = f"为等级{player_level}的玩家生成怪物，遭遇难度：{encounter_difficulty}。"
        
        # 如果有任务上下文，添加到提示中
        if quest_context:
            quest_name = quest_context.get("quest_name", "")
            quest_description = quest_context.get("quest_description", "")
            if quest_name:
                context_info += f"\n当前任务：{quest_name}"
            if quest_description:
                context_info += f"\n任务描述：{quest_description}"
        
        # 批量生成怪物
        tasks = []
        for i in range(monster_count):
            cr = base_cr + random.uniform(-0.5, 0.5)
            cr = max(0.25, cr)
            
            monster_context = f"{context_info}\n挑战等级：{cr:.1f}。怪物名称必须是中文。"
            tasks.append(llm_service.generate_monster(cr, monster_context))
        
        # 等待所有怪物生成完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Monster):
                monsters.append(result)
                logger.info(f"Generated encounter monster: {result.name} (CR: {result.challenge_rating})")
            elif isinstance(result, Exception):
                logger.error(f"Failed to generate monster: {result}")
        
        # 记录生成历史
        self._record_spawn(monsters, "encounter", encounter_difficulty)
        
        return monsters
    
    async def generate_quest_monsters(
        self, 
        game_state: GameState, 
        game_map: GameMap
    ) -> List[Monster]:
        """
        生成任务专属怪物
        
        Args:
            game_state: 游戏状态
            game_map: 当前地图
        
        Returns:
            生成的任务专属怪物列表
        """
        quest_monsters = []
        
        # 获取当前活跃任务
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if not active_quest:
            return quest_monsters

        # 【修复】处理 active_quest 可能是字典或对象的情况
        quest_title = active_quest.get('title') if isinstance(active_quest, dict) else active_quest.title
        quest_description = active_quest.get('description') if isinstance(active_quest, dict) else active_quest.description
        special_monsters = active_quest.get('special_monsters') if isinstance(active_quest, dict) else active_quest.special_monsters

        if not special_monsters:
            return quest_monsters

        current_depth = game_map.depth

        # 筛选适合当前楼层的专属怪物
        suitable_monsters = [
            monster_data for monster_data in special_monsters
            if not monster_data.location_hint or str(current_depth) in monster_data.location_hint
        ]

        for monster_data in suitable_monsters:
            try:
                # 使用LLM生成具体的怪物实例
                context = f"""
                根据任务专属怪物模板生成具体怪物：
                - 任务名称：{quest_title}
                - 任务描述：{quest_description}
                - 怪物名称：{monster_data.name}（必须保持中文名称）
                - 怪物描述：{monster_data.description}
                - 挑战等级：{monster_data.challenge_rating}
                - 是否为Boss：{monster_data.is_boss}
                - 生成条件：{monster_data.spawn_condition}
                - 位置提示：{monster_data.location_hint}
                - 当前楼层：{current_depth}
                
                **重要**：请生成一个符合这些要求的怪物，确保：
                1. 怪物名称必须是纯中文（如模板中指定的名称）
                2. 所有描述性文本都使用中文
                3. 能力与挑战等级相符
                4. 符合任务背景和剧情
                """
                
                monster = await llm_service.generate_monster(
                    monster_data.challenge_rating, context
                )
                
                if monster:
                    # 设置任务相关属性
                    monster.name = monster_data.name  # 确保名称匹配
                    monster.is_boss = monster_data.is_boss
                    monster.quest_monster_id = monster_data.id if hasattr(monster_data, 'id') else None
                    quest_monsters.append(monster)
                    
                    logger.info(f"Generated quest monster: {monster.name} (CR: {monster_data.challenge_rating}, Boss: {monster.is_boss})")
            
            except Exception as e:
                logger.error(f"Failed to generate quest monster {monster_data.name}: {e}")
        
        # 记录生成历史
        self._record_spawn(quest_monsters, "quest", quest_title if active_quest else "unknown")
        
        return quest_monsters
    
    async def generate_random_monster_nearby(
        self,
        game_state: GameState,
        player_position: Tuple[int, int],
        difficulty: Optional[str] = None
    ) -> Optional[Tuple[Monster, Tuple[int, int]]]:
        """
        在玩家附近生成随机怪物（调试功能）
        
        Args:
            game_state: 游戏状态
            player_position: 玩家位置
            difficulty: 难度（可选，默认根据当前任务和地图状态自动判断）
        
        Returns:
            (怪物, 生成位置) 或 None
        """
        # 如果没有指定难度，根据当前状态自动判断
        if not difficulty:
            difficulty = self._determine_difficulty(game_state)
        
        # 构建任务上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = {
                "quest_name": active_quest.title,
                "quest_description": active_quest.description,
                "quest_progress": active_quest.progress_percentage
            }
        
        # 生成怪物
        monsters = await self.generate_encounter_monsters(
            game_state.player.stats.level,
            difficulty,
            quest_context
        )
        
        if not monsters:
            logger.warning("Failed to generate random monster nearby")
            return None
        
        monster = monsters[0]
        
        # 在玩家附近找一个空位置
        spawn_pos = self._find_nearby_spawn_position(
            game_state.current_map,
            player_position,
            radius=3
        )
        
        if not spawn_pos:
            logger.warning("No available spawn position nearby")
            return None
        
        monster.position = spawn_pos
        
        logger.info(f"Generated random monster nearby: {monster.name} at {spawn_pos}")
        
        return (monster, spawn_pos)
    
    def _determine_difficulty(self, game_state: GameState) -> str:
        """
        根据游戏状态自动判断怪物难度
        
        Args:
            game_state: 游戏状态
        
        Returns:
            难度字符串
        """
        # 获取当前任务进度
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        
        if active_quest:
            progress = active_quest.progress_percentage
            
            # 根据任务进度调整难度
            if progress < 30:
                return "easy"
            elif progress < 60:
                return "medium"
            elif progress < 90:
                return "hard"
            else:
                return "deadly"
        
        # 如果没有活跃任务，根据地图深度判断
        depth = game_state.current_map.depth
        if depth <= 1:
            return "easy"
        elif depth <= 2:
            return "medium"
        else:
            return "hard"
    
    def _find_nearby_spawn_position(
        self,
        game_map: GameMap,
        center_position: Tuple[int, int],
        radius: int = 3
    ) -> Optional[Tuple[int, int]]:
        """
        在指定位置附近找一个可生成怪物的位置
        
        Args:
            game_map: 游戏地图
            center_position: 中心位置
            radius: 搜索半径
        
        Returns:
            可生成位置或None
        """
        nearby_positions = []
        cx, cy = center_position
        
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0:  # 跳过中心位置
                    continue
                
                new_x, new_y = cx + dx, cy + dy
                tile = game_map.get_tile(new_x, new_y)
                
                if tile and tile.terrain == TerrainType.FLOOR and not tile.character_id:
                    nearby_positions.append((new_x, new_y))
        
        if not nearby_positions:
            return None
        
        # 随机选择一个位置
        return random.choice(nearby_positions)
    
    def _record_spawn(self, monsters: List[Monster], spawn_type: str, context: str):
        """
        记录怪物生成历史
        
        Args:
            monsters: 生成的怪物列表
            spawn_type: 生成类型 (encounter, quest, debug)
            context: 上下文信息
        """
        from datetime import datetime
        
        for monster in monsters:
            self.spawn_history.append({
                "timestamp": datetime.now().isoformat(),
                "monster_name": monster.name,
                "monster_id": monster.id,
                "challenge_rating": monster.challenge_rating,
                "spawn_type": spawn_type,
                "context": context
            })
        
        # 限制历史记录数量
        if len(self.spawn_history) > 100:
            self.spawn_history = self.spawn_history[-100:]
    
    def get_spawn_statistics(self) -> Dict[str, Any]:
        """
        获取怪物生成统计信息
        
        Returns:
            统计信息字典
        """
        if not self.spawn_history:
            return {
                "total_spawned": 0,
                "by_type": {},
                "average_cr": 0
            }
        
        # 统计各类型数量
        by_type = {}
        total_cr = 0
        
        for record in self.spawn_history:
            spawn_type = record["spawn_type"]
            by_type[spawn_type] = by_type.get(spawn_type, 0) + 1
            total_cr += record["challenge_rating"]
        
        return {
            "total_spawned": len(self.spawn_history),
            "by_type": by_type,
            "average_cr": round(total_cr / len(self.spawn_history), 2)
        }


# 全局怪物生成管理器实例
monster_spawn_manager = MonsterSpawnManager()

__all__ = ["MonsterSpawnManager", "monster_spawn_manager"]

