"""
Labyrinthia AI - 物品效果处理器
Item effect processor for handling LLM-generated item usage effects
"""

import logging
import random
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from data_models import GameState, Item, Character, MapTile, TerrainType
from config import config

logger = logging.getLogger(__name__)


@dataclass
class ItemEffectResult:
    """物品使用效果结果"""
    success: bool = True
    message: str = ""
    events: List[str] = None
    stat_changes: Dict[str, int] = None
    position_change: Optional[Tuple[int, int]] = None
    map_changes: List[Dict[str, Any]] = None
    item_consumed: bool = True
    
    def __post_init__(self):
        if self.events is None:
            self.events = []
        if self.stat_changes is None:
            self.stat_changes = {}
        if self.map_changes is None:
            self.map_changes = []


class ItemEffectProcessor:
    """物品效果处理器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def process_llm_response(self, llm_response: Dict[str, Any],
                           game_state: GameState, item: Item) -> ItemEffectResult:
        """处理LLM返回的物品使用效果"""
        try:
            self.logger.info(f"处理物品 {item.name} 的LLM响应: {llm_response}")
            result = ItemEffectResult()

            # 解析LLM返回的效果
            effects = llm_response.get("effects", {})
            result.message = llm_response.get("message", f"使用了{item.name}")
            result.events = llm_response.get("events", [])
            result.item_consumed = llm_response.get("item_consumed", True)

            self.logger.info(f"解析的效果数据: {effects}")
            
            # 处理属性变化
            if "stat_changes" in effects:
                result.stat_changes = effects["stat_changes"]
                self._apply_stat_changes(game_state.player, result.stat_changes)
            
            # 处理位置变化（传送效果）
            if "teleport" in effects and effects["teleport"]:
                teleport_data = effects["teleport"]
                if teleport_data.get("type"):  # 确保有传送类型
                    result.position_change = self._process_teleport(
                        game_state, teleport_data
                    )
            
            # 处理地图变化
            if "map_changes" in effects:
                result.map_changes = effects["map_changes"]
                self._apply_map_changes(game_state, result.map_changes)
            
            # 处理特殊效果
            if "special_effects" in effects:
                self._process_special_effects(
                    game_state, effects["special_effects"], result
                )
            
            return result
            
        except Exception as e:
            self.logger.error(f"处理物品效果时出错: {e}")
            return ItemEffectResult(
                success=False,
                message=f"使用{item.name}时发生错误",
                events=[f"物品使用失败: {str(e)}"]
            )
    
    def _apply_stat_changes(self, player: Character, stat_changes: Dict[str, int]):
        """应用属性变化"""
        for stat_name, change in stat_changes.items():
            if hasattr(player.stats, stat_name):
                current_value = getattr(player.stats, stat_name)
                new_value = current_value + change
                
                # 处理特殊限制
                if stat_name == "hp":
                    new_value = max(0, min(new_value, player.stats.max_hp))
                elif stat_name == "mp":
                    new_value = max(0, min(new_value, player.stats.max_mp))
                elif stat_name in ["max_hp", "max_mp"]:
                    new_value = max(1, new_value)
                elif stat_name == "experience":
                    new_value = max(0, new_value)
                
                setattr(player.stats, stat_name, new_value)
                self.logger.info(f"属性变化: {stat_name} {current_value} -> {new_value}")
    
    def _process_teleport(self, game_state: GameState, 
                         teleport_data: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """处理传送效果"""
        teleport_type = teleport_data.get("type", "random")
        
        if teleport_type == "random":
            # 随机传送到地图上的空地
            return self._find_random_empty_position(game_state)
        elif teleport_type == "specific":
            # 传送到指定位置
            x = teleport_data.get("x", game_state.player.position[0])
            y = teleport_data.get("y", game_state.player.position[1])
            if self._is_valid_position(game_state, x, y):
                return (x, y)
        elif teleport_type == "stairs":
            # 传送到楼梯位置
            return self._find_stairs_position(game_state)
        
        return None
    
    def _find_random_empty_position(self, game_state: GameState) -> Optional[Tuple[int, int]]:
        """寻找随机空位置"""
        empty_positions = []
        
        for y in range(game_state.current_map.height):
            for x in range(game_state.current_map.width):
                if self._is_valid_position(game_state, x, y):
                    empty_positions.append((x, y))
        
        if empty_positions:
            return random.choice(empty_positions)
        return None
    
    def _find_stairs_position(self, game_state: GameState) -> Optional[Tuple[int, int]]:
        """寻找楼梯位置"""
        for y in range(game_state.current_map.height):
            for x in range(game_state.current_map.width):
                tile = game_state.current_map.get_tile(x, y)
                if tile and tile.terrain in [TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN]:
                    return (x, y)
        return None
    
    def _is_valid_position(self, game_state: GameState, x: int, y: int) -> bool:
        """检查位置是否有效"""
        if (x < 0 or x >= game_state.current_map.width or
            y < 0 or y >= game_state.current_map.height):
            return False

        tile = game_state.current_map.get_tile(x, y)
        if not tile:
            return False

        return (tile.terrain not in [TerrainType.WALL, TerrainType.LAVA, TerrainType.PIT] and
                tile.character_id is None)
    
    def _apply_map_changes(self, game_state: GameState, map_changes: List[Dict[str, Any]]):
        """应用地图变化"""
        for change in map_changes:
            x = change.get("x")
            y = change.get("y")

            if (x is not None and y is not None and
                0 <= x < game_state.current_map.width and
                0 <= y < game_state.current_map.height):

                tile = game_state.current_map.get_tile(x, y)
                if not tile:
                    continue

                # 改变地形
                if "terrain" in change:
                    new_terrain = change["terrain"]
                    if hasattr(TerrainType, new_terrain.upper()):
                        tile.terrain = TerrainType(new_terrain.lower())

                # 添加物品
                if "add_items" in change:
                    # 这里可以添加物品到地图
                    pass
    
    def _process_special_effects(self, game_state: GameState, 
                               special_effects: List[str], result: ItemEffectResult):
        """处理特殊效果"""
        for effect in special_effects:
            if effect == "reveal_map":
                # 揭示整个地图
                self._reveal_entire_map(game_state)
                result.events.append("地图完全显现！")
            elif effect == "heal_full":
                # 完全治愈
                game_state.player.stats.hp = game_state.player.stats.max_hp
                game_state.player.stats.mp = game_state.player.stats.max_mp
                result.events.append("完全恢复了生命值和法力值！")
            elif effect == "level_up":
                # 升级
                game_state.player.stats.level += 1
                game_state.player.stats.max_hp += 10
                game_state.player.stats.max_mp += 5
                result.events.append("等级提升！")
    
    def _reveal_entire_map(self, game_state: GameState):
        """揭示整个地图"""
        for y in range(game_state.current_map.height):
            for x in range(game_state.current_map.width):
                tile = game_state.current_map.get_tile(x, y)
                if tile:
                    tile.is_explored = True
                    tile.is_visible = True


# 全局实例
item_effect_processor = ItemEffectProcessor()

__all__ = ["ItemEffectProcessor", "ItemEffectResult", "item_effect_processor"]
