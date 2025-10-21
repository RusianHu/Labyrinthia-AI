"""
Labyrinthia AI - 数据管理器
Data manager for the Labyrinthia AI game
"""

import json
import os
import shutil
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pathlib import Path

from config import config
from data_models import (
    GameState, Character, Monster, GameMap, Quest, Item, Spell,
    MapTile, TerrainType, CharacterClass, CreatureType, DamageType
)


logger = logging.getLogger(__name__)


class DataManager:
    """数据管理器类"""
    
    def __init__(self):
        self.data_dir = Path(config.data.data_dir)
        self.saves_dir = Path(config.data.saves_dir)
        self.cache_dir = Path(config.data.cache_dir)
        
        # 确保目录存在
        self._ensure_directories()
    
    def _ensure_directories(self):
        """确保所有必要的目录存在"""
        for directory in [self.data_dir, self.saves_dir, self.cache_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _get_save_path(self, save_id: str) -> Path:
        """获取存档文件路径"""
        return self.saves_dir / f"{save_id}.json"
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"
    
    def save_game_state(self, game_state: GameState) -> bool:
        """保存游戏状态"""
        try:
            game_state.last_saved = datetime.now()
            save_path = self._get_save_path(game_state.id)
            
            # 转换为字典格式
            data = game_state.to_dict()
            
            # 写入文件
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Game state saved: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save game state: {e}")
            return False
    
    def load_game_state(self, save_id: str) -> Optional[GameState]:
        """加载游戏状态"""
        try:
            save_path = self._get_save_path(save_id)
            
            if not save_path.exists():
                logger.warning(f"Save file not found: {save_path}")
                return None
            
            with open(save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 从字典重建GameState对象
            game_state = self._dict_to_game_state(data)
            logger.info(f"Game state loaded: {save_path}")
            return game_state
            
        except Exception as e:
            logger.error(f"Failed to load game state: {e}")
            return None
    
    def _dict_to_game_state(self, data: Dict[str, Any]) -> GameState:
        """从字典重建GameState对象"""
        game_state = GameState()

        # 基础属性
        game_state.id = data.get("id", game_state.id)
        game_state.turn_count = data.get("turn_count", 0)
        game_state.game_time = data.get("game_time", 0)

        # 时间属性
        if created_at := data.get("created_at"):
            game_state.created_at = datetime.fromisoformat(created_at)
        if last_saved := data.get("last_saved"):
            game_state.last_saved = datetime.fromisoformat(last_saved)

        # 玩家角色
        if player_data := data.get("player"):
            game_state.player = self._dict_to_character(player_data)

        # 当前地图
        if map_data := data.get("current_map"):
            game_state.current_map = self._dict_to_game_map(map_data)

        # 怪物列表
        if monsters_data := data.get("monsters"):
            game_state.monsters = [self._dict_to_monster(monster_data) for monster_data in monsters_data]

        # 任务列表
        if quests_data := data.get("quests"):
            game_state.quests = [self._dict_to_quest(quest_data) for quest_data in quests_data]

        # 游戏状态属性
        game_state.last_narrative = data.get("last_narrative", "")
        game_state.is_game_over = data.get("is_game_over", False)
        game_state.game_over_reason = data.get("game_over_reason", "")

        # 待处理事件和特效
        game_state.pending_events = data.get("pending_events", [])
        game_state.pending_effects = data.get("pending_effects", [])

        # 地图切换状态
        game_state.pending_map_transition = data.get("pending_map_transition", None)

        # 事件选择上下文
        if choice_context_data := data.get("pending_choice_context"):
            game_state.pending_choice_context = self._dict_to_event_choice_context(choice_context_data)

        return game_state
    
    def _dict_to_character(self, data: Dict[str, Any]) -> Character:
        """从字典重建Character对象"""
        from data_models import Ability, Stats
        
        character = Character()
        character.id = data.get("id", character.id)
        character.name = data.get("name", "")
        character.description = data.get("description", "")
        character.position = tuple(data.get("position", (0, 0)))
        
        # 职业
        if character_class := data.get("character_class"):
            try:
                character.character_class = CharacterClass(character_class)
            except ValueError:
                pass
        
        # 生物类型
        if creature_type := data.get("creature_type"):
            try:
                character.creature_type = CreatureType(creature_type)
            except ValueError:
                pass
        
        # 能力值
        if abilities_data := data.get("abilities"):
            character.abilities = Ability(**abilities_data)
        
        # 属性
        if stats_data := data.get("stats"):
            character.stats = Stats(**stats_data)
        
        # 物品
        if inventory_data := data.get("inventory"):
            character.inventory = [self._dict_to_item(item_data) for item_data in inventory_data]
        
        # 法术
        if spells_data := data.get("spells"):
            character.spells = [self._dict_to_spell(spell_data) for spell_data in spells_data]
        
        return character
    
    def _dict_to_monster(self, data: Dict[str, Any]) -> Monster:
        """从字典重建Monster对象"""
        from data_models import Ability

        monster = Monster()

        # 复制Character的属性
        character_data = {k: v for k, v in data.items() if k not in ["challenge_rating", "behavior", "loot_table", "attack_range", "is_boss", "quest_monster_id"]}
        character = self._dict_to_character(character_data)

        for attr in ["id", "name", "description", "character_class", "creature_type",
                     "abilities", "stats", "inventory", "spells", "position"]:
            setattr(monster, attr, getattr(character, attr))

        # Monster特有属性
        monster.challenge_rating = data.get("challenge_rating", 1.0)
        monster.behavior = data.get("behavior", "aggressive")
        monster.loot_table = data.get("loot_table", [])
        monster.attack_range = data.get("attack_range", 1)

        # 任务相关属性
        monster.is_boss = data.get("is_boss", False)
        monster.quest_monster_id = data.get("quest_monster_id", None)

        # 兼容性处理：确保旧存档的怪物有abilities字段
        if not hasattr(monster.abilities, 'strength'):
            # 根据挑战等级生成合理的属性值
            cr = monster.challenge_rating
            base_stat = 10 + int(cr * 2)  # CR 1.0 = 12, CR 2.0 = 14
            monster.abilities = Ability(
                strength=base_stat,
                dexterity=base_stat,
                constitution=base_stat,
                intelligence=max(8, base_stat - 2),
                wisdom=max(8, base_stat - 2),
                charisma=max(8, base_stat - 4)
            )
            # 重新计算衍生属性
            monster.stats.calculate_derived_stats(monster.abilities)

        return monster
    
    def _dict_to_item(self, data: Dict[str, Any]) -> Item:
        """从字典重建Item对象"""
        item = Item()
        item.id = data.get("id", item.id)
        item.name = data.get("name", "")
        item.description = data.get("description", "")
        item.item_type = data.get("item_type", "misc")
        item.value = data.get("value", 0)
        item.weight = data.get("weight", 0.0)
        item.rarity = data.get("rarity", "common")
        item.properties = data.get("properties", {})
        # 新增字段
        item.usage_description = data.get("usage_description", "")
        item.llm_generated = data.get("llm_generated", False)
        item.generation_context = data.get("generation_context", "")
        return item
    
    def _dict_to_spell(self, data: Dict[str, Any]) -> Spell:
        """从字典重建Spell对象"""
        spell = Spell()
        spell.id = data.get("id", spell.id)
        spell.name = data.get("name", "")
        spell.description = data.get("description", "")
        spell.level = data.get("level", 1)
        spell.school = data.get("school", "evocation")
        spell.casting_time = data.get("casting_time", "1 action")
        spell.range = data.get("range", "60 feet")
        spell.components = data.get("components", [])
        spell.duration = data.get("duration", "instantaneous")
        spell.damage = data.get("damage", "")
        
        if damage_type := data.get("damage_type"):
            try:
                spell.damage_type = DamageType(damage_type)
            except ValueError:
                pass
        
        return spell
    
    def _dict_to_game_map(self, data: Dict[str, Any]) -> GameMap:
        """从字典重建GameMap对象"""
        game_map = GameMap()
        game_map.id = data.get("id", game_map.id)
        game_map.name = data.get("name", "")
        game_map.description = data.get("description", "")
        game_map.width = data.get("width", 20)
        game_map.height = data.get("height", 20)
        game_map.depth = data.get("depth", 1)
        game_map.floor_theme = data.get("floor_theme", "normal")  # 【修复】加载地板主题

        # 瓦片
        if tiles_data := data.get("tiles"):
            for coord_str, tile_data in tiles_data.items():
                x, y = map(int, coord_str.split(","))
                tile = self._dict_to_map_tile(tile_data)
                game_map.tiles[(x, y)] = tile

        return game_map
    
    def _dict_to_map_tile(self, data: Dict[str, Any]) -> MapTile:
        """从字典重建MapTile对象"""
        tile = MapTile()
        tile.x = data.get("x", 0)
        tile.y = data.get("y", 0)
        tile.is_explored = data.get("is_explored", False)
        tile.is_visible = data.get("is_visible", False)
        tile.character_id = data.get("character_id")

        # 房间类型信息
        tile.room_type = data.get("room_type", "")
        tile.room_id = data.get("room_id")

        # 事件相关字段
        tile.has_event = data.get("has_event", False)
        tile.event_type = data.get("event_type", "")
        tile.event_data = data.get("event_data", {})
        tile.is_event_hidden = data.get("is_event_hidden", True)
        tile.event_triggered = data.get("event_triggered", False)

        # 物品相关字段
        tile.items_collected = data.get("items_collected", [])

        # 【P0修复】陷阱专属字段（确保状态在序列化/反序列化中不丢失）
        tile.trap_detected = data.get("trap_detected", False)
        tile.trap_disarmed = data.get("trap_disarmed", False)

        # 地形类型
        if terrain := data.get("terrain"):
            try:
                tile.terrain = TerrainType(terrain)
            except ValueError:
                pass

        # 物品
        if items_data := data.get("items"):
            tile.items = [self._dict_to_item(item_data) for item_data in items_data]

        return tile
    
    def _dict_to_quest(self, data: Dict[str, Any]) -> Quest:
        """从字典重建Quest对象"""
        quest = Quest()
        quest.id = data.get("id", quest.id)
        quest.title = data.get("title", "")
        quest.description = data.get("description", "")
        quest.objectives = data.get("objectives", [])
        quest.completed_objectives = data.get("completed_objectives", [])
        quest.experience_reward = data.get("experience_reward", 0)
        quest.is_completed = data.get("is_completed", False)
        quest.is_active = data.get("is_active", False)

        # LLM控制的进度系统
        quest.progress_percentage = data.get("progress_percentage", 0.0)
        quest.story_context = data.get("story_context", "")
        quest.llm_notes = data.get("llm_notes", "")

        # 任务专属内容
        quest.quest_type = data.get("quest_type", "exploration")
        quest.target_floors = data.get("target_floors", [])
        quest.map_themes = data.get("map_themes", [])

        # 奖励物品
        if rewards_data := data.get("rewards"):
            quest.rewards = [self._dict_to_item(item_data) for item_data in rewards_data]

        # 专属事件
        if special_events_data := data.get("special_events"):
            quest.special_events = [self._dict_to_quest_event(event_data) for event_data in special_events_data]

        # 专属怪物
        if special_monsters_data := data.get("special_monsters"):
            quest.special_monsters = [self._dict_to_quest_monster(monster_data) for monster_data in special_monsters_data]

        return quest

    def _dict_to_quest_event(self, data: Dict[str, Any]) -> 'QuestEvent':
        """从字典重建QuestEvent对象"""
        from data_models import QuestEvent

        event = QuestEvent()
        event.id = data.get("id", event.id)
        event.event_type = data.get("event_type", "")
        event.name = data.get("name", "")
        event.description = data.get("description", "")
        event.trigger_condition = data.get("trigger_condition", "")
        event.progress_value = data.get("progress_value", 0.0)
        event.is_mandatory = data.get("is_mandatory", True)
        event.location_hint = data.get("location_hint", "")

        return event

    def _dict_to_quest_monster(self, data: Dict[str, Any]) -> 'QuestMonster':
        """从字典重建QuestMonster对象"""
        from data_models import QuestMonster

        monster = QuestMonster()
        monster.id = data.get("id", monster.id)
        monster.name = data.get("name", "")
        monster.description = data.get("description", "")
        monster.challenge_rating = data.get("challenge_rating", 1.0)
        monster.is_boss = data.get("is_boss", False)
        monster.progress_value = data.get("progress_value", 0.0)
        monster.spawn_condition = data.get("spawn_condition", "")
        monster.location_hint = data.get("location_hint", "")

        return monster

    def _dict_to_event_choice(self, data: Dict[str, Any]) -> 'EventChoice':
        """从字典重建EventChoice对象"""
        from data_models import EventChoice

        choice = EventChoice()
        choice.id = data.get("id", choice.id)
        choice.text = data.get("text", "")
        choice.description = data.get("description", "")
        choice.consequences = data.get("consequences", "")
        choice.requirements = data.get("requirements", {})
        choice.is_available = data.get("is_available", True)

        return choice

    def _dict_to_event_choice_context(self, data: Dict[str, Any]) -> 'EventChoiceContext':
        """从字典重建EventChoiceContext对象"""
        from data_models import EventChoiceContext

        context = EventChoiceContext()
        context.id = data.get("id", context.id)
        context.event_type = data.get("event_type", "")
        context.title = data.get("title", "")
        context.description = data.get("description", "")
        context.context_data = data.get("context_data", {})

        # 重建选项列表
        if choices_data := data.get("choices"):
            context.choices = [self._dict_to_event_choice(choice_data) for choice_data in choices_data]

        # 时间属性
        if created_at := data.get("created_at"):
            context.created_at = datetime.fromisoformat(created_at)

        return context

    def list_saves(self) -> List[Dict[str, Any]]:
        """列出所有存档"""
        saves = []
        
        for save_file in self.saves_dir.glob("*.json"):
            try:
                with open(save_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                save_info = {
                    "id": data.get("id", save_file.stem),
                    "player_name": data.get("player", {}).get("name", "Unknown"),
                    "player_level": data.get("player", {}).get("stats", {}).get("level", 1),
                    "map_name": data.get("current_map", {}).get("name", "Unknown"),
                    "turn_count": data.get("turn_count", 0),
                    "created_at": data.get("created_at", ""),
                    "last_saved": data.get("last_saved", ""),
                    "file_size": save_file.stat().st_size
                }
                saves.append(save_info)
                
            except Exception as e:
                logger.error(f"Failed to read save file {save_file}: {e}")
        
        # 按最后保存时间排序
        saves.sort(key=lambda x: x.get("last_saved", ""), reverse=True)
        return saves
    
    def delete_save(self, save_id: str) -> bool:
        """删除存档"""
        try:
            save_path = self._get_save_path(save_id)
            if save_path.exists():
                save_path.unlink()
                logger.info(f"Save deleted: {save_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete save: {e}")
            return False
    
    def backup_saves(self) -> bool:
        """备份所有存档"""
        try:
            backup_dir = self.data_dir / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            for save_file in self.saves_dir.glob("*.json"):
                shutil.copy2(save_file, backup_dir)
            
            logger.info(f"Saves backed up to: {backup_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to backup saves: {e}")
            return False


# 全局数据管理器实例
data_manager = DataManager()

__all__ = ["DataManager", "data_manager"]
