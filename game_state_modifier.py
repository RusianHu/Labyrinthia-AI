"""
Labyrinthia AI - 游戏状态修改器
统一的游戏状态修改接口，用于处理所有LLM驱动的游戏状态变更
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from data_models import (
    GameState, Character, Monster, Item, MapTile, Quest,
    TerrainType, CharacterClass, Stats
)
from config import config
from entity_manager import entity_manager


logger = logging.getLogger(__name__)


class ModificationType(Enum):
    """状态修改类型"""
    PLAYER_STATS = "player_stats"
    PLAYER_ABILITIES = "player_abilities"  # 新增: 六维属性修改
    PLAYER_INVENTORY = "player_inventory"
    MAP_TILE = "map_tile"
    MONSTER = "monster"
    MONSTER_ABILITIES = "monster_abilities"  # 新增: 怪物六维属性修改
    QUEST = "quest"
    GAME_STATE = "game_state"


@dataclass
class ModificationRecord:
    """状态修改记录"""
    modification_type: ModificationType
    timestamp: datetime
    source: str  # 修改来源（如 "event_choice", "item_use", "combat"）
    target_id: str  # 目标ID（如玩家ID、怪物ID、瓦片坐标等）
    changes: Dict[str, Any]  # 具体的修改内容
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "modification_type": self.modification_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "target_id": self.target_id,
            "changes": self.changes,
            "success": self.success,
            "error_message": self.error_message
        }


@dataclass
class ModificationResult:
    """状态修改结果"""
    success: bool = True
    message: str = ""
    records: List[ModificationRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def add_record(self, record: ModificationRecord):
        """添加修改记录"""
        self.records.append(record)
        if not record.success:
            self.success = False
            self.errors.append(record.error_message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "records": [r.to_dict() for r in self.records],
            "errors": self.errors
        }


class GameStateModifier:
    """
    游戏状态修改器
    
    统一管理所有LLM驱动的游戏状态修改，提供：
    1. 统一的状态修改接口
    2. 验证机制
    3. 错误处理
    4. 日志记录
    5. 修改历史追踪
    """
    
    def __init__(self):
        self.modification_history: List[ModificationRecord] = []
        self.max_history_size = 100
        
    def apply_llm_updates(
        self,
        game_state: GameState,
        llm_response: Dict[str, Any],
        source: str = "llm"
    ) -> ModificationResult:
        """
        应用LLM返回的所有更新
        
        Args:
            game_state: 游戏状态
            llm_response: LLM返回的更新数据
            source: 修改来源标识
            
        Returns:
            ModificationResult: 修改结果
        """
        result = ModificationResult()
        
        try:
            # 应用玩家更新
            if "player_updates" in llm_response:
                player_result = self.apply_player_updates(
                    game_state,
                    llm_response["player_updates"],
                    source
                )
                result.records.extend(player_result.records)
                if not player_result.success:
                    result.success = False
                    result.errors.extend(player_result.errors)
            
            # 应用地图更新
            if "map_updates" in llm_response:
                map_result = self.apply_map_updates(
                    game_state,
                    llm_response["map_updates"],
                    source
                )
                result.records.extend(map_result.records)
                if not map_result.success:
                    result.success = False
                    result.errors.extend(map_result.errors)
            
            # 应用任务更新
            if "quest_updates" in llm_response:
                quest_result = self.apply_quest_updates(
                    game_state,
                    llm_response["quest_updates"],
                    source
                )
                result.records.extend(quest_result.records)
                if not quest_result.success:
                    result.success = False
                    result.errors.extend(quest_result.errors)
            
            # 添加事件到待显示列表
            if "events" in llm_response and isinstance(llm_response["events"], list):
                game_state.pending_events.extend(llm_response["events"])
            
            # 记录到历史
            self._add_to_history(result.records)
            
            logger.info(f"Applied LLM updates from {source}: {len(result.records)} modifications")
            
        except Exception as e:
            logger.error(f"Error applying LLM updates: {e}")
            result.success = False
            result.errors.append(f"应用LLM更新时发生错误: {str(e)}")
        
        return result
    
    def apply_player_updates(
        self,
        game_state: GameState,
        player_updates: Dict[str, Any],
        source: str = "unknown"
    ) -> ModificationResult:
        """
        应用玩家状态更新

        Args:
            game_state: 游戏状态
            player_updates: 玩家更新数据 (支持stats和abilities)
            source: 修改来源

        Returns:
            ModificationResult: 修改结果
        """
        result = ModificationResult()
        player = game_state.player

        try:
            # 应用六维属性更新 (新增)
            if "abilities" in player_updates:
                abilities_updates = player_updates["abilities"]
                changes = {}

                for ability_name, value in abilities_updates.items():
                    if hasattr(player.abilities, ability_name):
                        old_value = getattr(player.abilities, ability_name)

                        # 使用entity_manager设置属性值 (自动验证和重新计算衍生属性)
                        success = entity_manager.set_ability_score(player, ability_name, value)

                        if success:
                            new_value = getattr(player.abilities, ability_name)
                            changes[ability_name] = {
                                "old": old_value,
                                "new": new_value
                            }
                            logger.debug(f"Updated player ability {ability_name}: {old_value} -> {new_value}")

                if changes:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_ABILITIES,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes=changes
                    )
                    result.add_record(record)

            # 应用衍生属性更新
            if "stats" in player_updates:
                stats_updates = player_updates["stats"]
                changes = {}

                for stat_name, value in stats_updates.items():
                    if hasattr(player.stats, stat_name):
                        old_value = getattr(player.stats, stat_name)

                        # 验证并应用属性变化
                        validated_value = self._validate_stat_value(
                            stat_name, value, player.stats
                        )

                        setattr(player.stats, stat_name, validated_value)
                        changes[stat_name] = {
                            "old": old_value,
                            "new": validated_value
                        }

                        logger.debug(f"Updated player stat {stat_name}: {old_value} -> {validated_value}")

                if changes:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_STATS,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes=changes
                    )
                    result.add_record(record)
            
            # 应用物品添加
            if "add_items" in player_updates:
                for item_data in player_updates["add_items"]:
                    if isinstance(item_data, dict):
                        item = self._create_item_from_data(item_data)
                        player.inventory.append(item)
                        
                        record = ModificationRecord(
                            modification_type=ModificationType.PLAYER_INVENTORY,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=player.id,
                            changes={"action": "add", "item": item.to_dict()}
                        )
                        result.add_record(record)
                        
                        logger.info(f"Added item {item.name} to player inventory")
            
            # 应用物品移除
            if "remove_items" in player_updates:
                items_to_remove = player_updates["remove_items"]
                removed_items = []
                
                for item_name in items_to_remove:
                    # 查找并移除物品
                    for item in player.inventory[:]:
                        if item.name == item_name:
                            player.inventory.remove(item)
                            removed_items.append(item.to_dict())
                            logger.info(f"Removed item {item_name} from player inventory")
                            break
                
                if removed_items:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_INVENTORY,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes={"action": "remove", "items": removed_items}
                    )
                    result.add_record(record)
            
        except Exception as e:
            logger.error(f"Error applying player updates: {e}")
            error_record = ModificationRecord(
                modification_type=ModificationType.PLAYER_STATS,
                timestamp=datetime.now(),
                source=source,
                target_id=player.id,
                changes={},
                success=False,
                error_message=str(e)
            )
            result.add_record(error_record)
        
        return result

    def apply_map_updates(
        self,
        game_state: GameState,
        map_updates: Dict[str, Any],
        source: str = "unknown"
    ) -> ModificationResult:
        """应用地图更新"""
        result = ModificationResult()
        current_map = game_state.current_map

        try:
            tile_updates = map_updates.get("tiles", {})

            for tile_key, tile_data in tile_updates.items():
                try:
                    # 解析坐标
                    if "," in tile_key:
                        x, y = map(int, tile_key.split(","))
                    else:
                        logger.warning(f"Invalid tile key format: {tile_key}")
                        continue

                    # 验证坐标范围
                    if not self._validate_tile_position(current_map, x, y):
                        logger.warning(f"Invalid tile position: ({x}, {y})")
                        continue

                    # 获取或创建瓦片
                    tile = current_map.get_tile(x, y)
                    if not tile:
                        tile = MapTile(x=x, y=y)
                        current_map.set_tile(x, y, tile)

                    # 记录瓦片原本状态
                    had_event = tile.has_event
                    was_triggered = tile.event_triggered
                    changes = {}

                    # 更新瓦片属性
                    for attr_name, value in tile_data.items():
                        if attr_name == "terrain":
                            old_terrain = tile.terrain
                            new_terrain = self._parse_terrain_type(value)
                            if new_terrain:
                                tile.terrain = new_terrain
                                changes["terrain"] = {"old": old_terrain.value, "new": new_terrain.value}

                        elif attr_name == "items" and isinstance(value, list):
                            added_items = []
                            for item_data in value:
                                if isinstance(item_data, dict):
                                    item = self._create_item_from_data(item_data)
                                    tile.items.append(item)
                                    added_items.append(item.to_dict())
                            if added_items:
                                changes["items_added"] = added_items

                        elif attr_name == "monster" and isinstance(value, dict):
                            monster_result = self._handle_monster_update(game_state, x, y, value, source)
                            if monster_result.records:
                                result.records.extend(monster_result.records)

                        elif hasattr(tile, attr_name):
                            old_value = getattr(tile, attr_name)
                            setattr(tile, attr_name, value)
                            changes[attr_name] = {"old": old_value, "new": value}

                    # 保持事件触发状态
                    if had_event and was_triggered and "event_triggered" not in tile_data:
                        tile.event_triggered = True

                    if changes:
                        record = ModificationRecord(
                            modification_type=ModificationType.MAP_TILE,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=f"{x},{y}",
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated tile at ({x}, {y}): {list(changes.keys())}")

                except Exception as e:
                    logger.error(f"Error updating tile {tile_key}: {e}")
                    error_record = ModificationRecord(
                        modification_type=ModificationType.MAP_TILE,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=tile_key,
                        changes={},
                        success=False,
                        error_message=str(e)
                    )
                    result.add_record(error_record)

        except Exception as e:
            logger.error(f"Error applying map updates: {e}")
            result.success = False
            result.errors.append(f"应用地图更新时发生错误: {str(e)}")

        return result

    def apply_quest_updates(
        self,
        game_state: GameState,
        quest_updates: Dict[str, Any],
        source: str = "unknown"
    ) -> ModificationResult:
        """应用任务更新"""
        result = ModificationResult()

        try:
            # 记录本次更新中被显式设置为激活的任务ID（若有，则强制保持单活跃任务）
            last_set_active_id = None

            for quest in game_state.quests:
                quest_update = quest_updates.get(quest.id)
                if quest_update:
                    changes = {}

                    for attr_name, value in quest_update.items():
                        if hasattr(quest, attr_name):
                            old_value = getattr(quest, attr_name)
                            setattr(quest, attr_name, value)
                            changes[attr_name] = {"old": old_value, "new": value}

                            # 方案A强约束：若有任务被设置为 is_active=True，记录下来
                            if attr_name == "is_active" and bool(value) is True:
                                last_set_active_id = quest.id

                    if changes:
                        record = ModificationRecord(
                            modification_type=ModificationType.QUEST,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=quest.id,
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated quest {quest.title}: {list(changes.keys())}")

            # 方案A收尾：若本次更新显式激活了某个任务，则保证仅此任务处于激活，其他任务全部取消激活
            if last_set_active_id is not None:
                for quest in game_state.quests:
                    quest.is_active = (quest.id == last_set_active_id)
            else:
                # 若未显式设置，依然兜底：如果出现多个任务激活，仅保留第一个激活任务
                active_quests = [q for q in game_state.quests if getattr(q, "is_active", False)]
                if len(active_quests) > 1:
                    keeper_id = active_quests[0].id
                    for quest in game_state.quests:
                        quest.is_active = (quest.id == keeper_id)

        except Exception as e:
            logger.error(f"Error applying quest updates: {e}")
            result.success = False
            result.errors.append(f"应用任务更新时发生错误: {str(e)}")

        return result

    def _handle_monster_update(
        self,
        game_state: GameState,
        x: int,
        y: int,
        monster_data: Dict[str, Any],
        source: str
    ) -> ModificationResult:
        """处理怪物添加/更新/移除"""
        result = ModificationResult()

        try:
            action = monster_data.get("action", "add")
            tile = game_state.current_map.get_tile(x, y)

            if not tile:
                return result

            if action == "remove":
                if tile.character_id:
                    game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]
                    tile.character_id = None
                    record = ModificationRecord(
                        modification_type=ModificationType.MONSTER,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=f"{x},{y}",
                        changes={"action": "remove"}
                    )
                    result.add_record(record)
                    logger.info(f"Removed monster from tile ({x}, {y})")

            elif action == "update":
                if tile.character_id:
                    monster = next((m for m in game_state.monsters if m.id == tile.character_id), None)
                    if monster:
                        changes = {}
                        if "name" in monster_data:
                            changes["name"] = {"old": monster.name, "new": monster_data["name"]}
                            monster.name = monster_data["name"]
                        if "description" in monster_data:
                            monster.description = monster_data["description"]

                        # 支持六维属性更新 (新增)
                        if "abilities" in monster_data:
                            abilities_data = monster_data["abilities"]
                            for ability_name, value in abilities_data.items():
                                if hasattr(monster.abilities, ability_name):
                                    old_value = getattr(monster.abilities, ability_name)
                                    entity_manager.set_ability_score(monster, ability_name, value)
                                    new_value = getattr(monster.abilities, ability_name)
                                    changes[f"ability_{ability_name}"] = {"old": old_value, "new": new_value}

                        # 支持衍生属性更新
                        if "stats" in monster_data:
                            stats_data = monster_data["stats"]
                            if "hp" in stats_data:
                                monster.stats.hp = min(stats_data["hp"], monster.stats.max_hp)
                            if "max_hp" in stats_data:
                                monster.stats.max_hp = stats_data["max_hp"]
                                monster.stats.hp = min(monster.stats.hp, monster.stats.max_hp)

                        record = ModificationRecord(
                            modification_type=ModificationType.MONSTER,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=monster.id,
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated monster {monster.name} at ({x}, {y})")

            elif action == "add":
                if tile.character_id:
                    game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]

                monster = Monster()
                monster.name = monster_data.get("name", "神秘生物")
                monster.description = monster_data.get("description", "一个神秘的生物")
                monster.character_class = CharacterClass.FIGHTER
                monster.position = (x, y)
                monster.challenge_rating = monster_data.get("challenge_rating", 1.0)
                monster.behavior = monster_data.get("behavior", "aggressive")
                monster.is_boss = monster_data.get("is_boss", False)
                monster.quest_monster_id = monster_data.get("quest_monster_id")
                monster.attack_range = monster_data.get("attack_range", 1)

                if "stats" in monster_data:
                    stats_data = monster_data["stats"]
                    monster.stats.max_hp = stats_data.get("max_hp", 20)
                    monster.stats.hp = stats_data.get("hp", monster.stats.max_hp)
                    monster.stats.max_mp = stats_data.get("max_mp", 10)
                    monster.stats.mp = stats_data.get("mp", monster.stats.max_mp)
                    monster.stats.ac = stats_data.get("ac", 12)
                    monster.stats.level = stats_data.get("level", 1)

                game_state.monsters.append(monster)
                tile.character_id = monster.id

                record = ModificationRecord(
                    modification_type=ModificationType.MONSTER,
                    timestamp=datetime.now(),
                    source=source,
                    target_id=monster.id,
                    changes={"action": "add", "monster": monster.to_dict()}
                )
                result.add_record(record)
                logger.info(f"Added new monster {monster.name} at ({x}, {y})")

        except Exception as e:
            logger.error(f"Error handling monster update: {e}")
            error_record = ModificationRecord(
                modification_type=ModificationType.MONSTER,
                timestamp=datetime.now(),
                source=source,
                target_id=f"{x},{y}",
                changes={},
                success=False,
                error_message=str(e)
            )
            result.add_record(error_record)

        return result

    # ==================== 验证方法 ====================

    def _validate_stat_value(self, stat_name: str, value: Any, stats: Stats) -> Any:
        """验证并调整属性值"""
        try:
            # 确保值是数字
            if not isinstance(value, (int, float)):
                value = int(value)

            # 特殊属性的范围限制
            if stat_name == "hp":
                return max(0, min(value, stats.max_hp))
            elif stat_name == "mp":
                return max(0, min(value, stats.max_mp))
            elif stat_name in ["max_hp", "max_mp"]:
                return max(1, value)
            elif stat_name == "experience":
                return max(0, value)
            elif stat_name == "level":
                return max(1, min(value, 100))  # 最高等级100
            elif stat_name == "ac":
                return max(0, min(value, 50))  # 护甲等级上限50
            else:
                # 其他属性（力量、敏捷等）
                return max(1, min(value, 30))  # 属性范围1-30

        except Exception as e:
            logger.error(f"Error validating stat {stat_name}={value}: {e}")
            return getattr(stats, stat_name)  # 返回原值

    def _validate_tile_position(self, game_map: 'GameMap', x: int, y: int) -> bool:
        """验证瓦片位置是否有效"""
        return 0 <= x < game_map.width and 0 <= y < game_map.height

    def _parse_terrain_type(self, terrain_value: str) -> Optional[TerrainType]:
        """解析地形类型"""
        try:
            if hasattr(TerrainType, terrain_value.upper()):
                return TerrainType(terrain_value.lower())
            else:
                logger.warning(f"Unknown terrain type: {terrain_value}")
                return None
        except Exception as e:
            logger.error(f"Error parsing terrain type {terrain_value}: {e}")
            return None

    def _create_item_from_data(self, item_data: Dict[str, Any]) -> Item:
        """从数据字典创建物品对象"""
        item = Item(
            name=item_data.get("name", "神秘物品"),
            description=item_data.get("description", "一个神秘的物品"),
            item_type=item_data.get("item_type", "misc"),
            rarity=item_data.get("rarity", "common")
        )

        # 设置其他可选属性
        if "usage_description" in item_data:
            item.usage_description = item_data["usage_description"]
        if "properties" in item_data:
            item.properties = item_data["properties"]
        if "value" in item_data:
            item.value = item_data["value"]
        if "weight" in item_data:
            item.weight = item_data["weight"]
        if "effect_payload" in item_data:
            item.effect_payload = item_data.get("effect_payload", {}) or {}
        if "use_mode" in item_data:
            item.use_mode = item_data.get("use_mode", "active")
        if "is_equippable" in item_data:
            item.is_equippable = bool(item_data.get("is_equippable", False))
        if "equip_slot" in item_data:
            item.equip_slot = item_data.get("equip_slot", "")
        if "max_charges" in item_data:
            item.max_charges = int(item_data.get("max_charges", 0) or 0)
        if "charges" in item_data:
            item.charges = int(item_data.get("charges", item.max_charges) or 0)
        else:
            item.charges = item.max_charges
        if "cooldown_turns" in item_data:
            item.cooldown_turns = int(item_data.get("cooldown_turns", 0) or 0)
        if "current_cooldown" in item_data:
            item.current_cooldown = int(item_data.get("current_cooldown", 0) or 0)

        return item

    # ==================== 历史记录管理 ====================

    def _add_to_history(self, records: List[ModificationRecord]):
        """添加记录到历史"""
        self.modification_history.extend(records)

        # 限制历史记录大小
        if len(self.modification_history) > self.max_history_size:
            self.modification_history = self.modification_history[-self.max_history_size:]

    def get_modification_history(
        self,
        limit: int = 20,
        modification_type: Optional[ModificationType] = None,
        source: Optional[str] = None
    ) -> List[ModificationRecord]:
        """
        获取修改历史

        Args:
            limit: 返回记录数量限制
            modification_type: 筛选特定类型的修改
            source: 筛选特定来源的修改

        Returns:
            修改记录列表
        """
        filtered_history = self.modification_history

        if modification_type:
            filtered_history = [r for r in filtered_history if r.modification_type == modification_type]

        if source:
            filtered_history = [r for r in filtered_history if r.source == source]

        return filtered_history[-limit:]

    def clear_history(self):
        """清空修改历史"""
        self.modification_history.clear()
        logger.info("Modification history cleared")

    def get_statistics(self) -> Dict[str, Any]:
        """获取修改统计信息"""
        stats = {
            "total_modifications": len(self.modification_history),
            "successful_modifications": sum(1 for r in self.modification_history if r.success),
            "failed_modifications": sum(1 for r in self.modification_history if not r.success),
            "by_type": {},
            "by_source": {}
        }

        # 按类型统计
        for mod_type in ModificationType:
            count = sum(1 for r in self.modification_history if r.modification_type == mod_type)
            if count > 0:
                stats["by_type"][mod_type.value] = count

        # 按来源统计
        sources = set(r.source for r in self.modification_history)
        for source in sources:
            count = sum(1 for r in self.modification_history if r.source == source)
            stats["by_source"][source] = count

        return stats


# 全局实例
game_state_modifier = GameStateModifier()

__all__ = [
    "GameStateModifier",
    "ModificationResult",
    "ModificationRecord",
    "ModificationType",
    "game_state_modifier"
]

