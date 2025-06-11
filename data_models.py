"""
Labyrinthia AI - 数据模型定义
Data models for the Labyrinthia AI game
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum
import uuid
from datetime import datetime


class CharacterClass(Enum):
    """角色职业枚举"""
    FIGHTER = "fighter"
    WIZARD = "wizard"
    ROGUE = "rogue"
    CLERIC = "cleric"
    RANGER = "ranger"
    BARBARIAN = "barbarian"
    BARD = "bard"
    PALADIN = "paladin"
    SORCERER = "sorcerer"
    WARLOCK = "warlock"


class CreatureType(Enum):
    """生物类型枚举"""
    HUMANOID = "humanoid"
    BEAST = "beast"
    UNDEAD = "undead"
    DRAGON = "dragon"
    FIEND = "fiend"
    CELESTIAL = "celestial"
    ELEMENTAL = "elemental"
    FEY = "fey"
    ABERRATION = "aberration"
    CONSTRUCT = "construct"


class DamageType(Enum):
    """伤害类型枚举"""
    PHYSICAL = "physical"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    ACID = "acid"
    POISON = "poison"
    NECROTIC = "necrotic"
    RADIANT = "radiant"
    PSYCHIC = "psychic"


class TerrainType(Enum):
    """地形类型枚举"""
    FLOOR = "floor"
    WALL = "wall"
    DOOR = "door"
    TRAP = "trap"
    TREASURE = "treasure"
    STAIRS_UP = "stairs_up"
    STAIRS_DOWN = "stairs_down"
    WATER = "water"
    LAVA = "lava"
    PIT = "pit"


@dataclass
class Ability:
    """能力值"""
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    
    def get_modifier(self, ability_name: str) -> int:
        """获取能力调整值"""
        value = getattr(self, ability_name.lower())
        return (value - 10) // 2


@dataclass
class Stats:
    """角色属性"""
    hp: int = 100
    max_hp: int = 100
    mp: int = 50
    max_mp: int = 50
    ac: int = 10  # 护甲等级
    speed: int = 30
    level: int = 1
    experience: int = 0
    
    def is_alive(self) -> bool:
        return self.hp > 0


@dataclass
class Item:
    """物品"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    item_type: str = "misc"  # weapon, armor, consumable, misc
    value: int = 0
    weight: float = 0.0
    rarity: str = "common"  # common, uncommon, rare, epic, legendary
    properties: Dict[str, Any] = field(default_factory=dict)
    # 新增字段
    usage_description: str = ""  # 使用说明
    llm_generated: bool = False  # 是否由LLM生成
    generation_context: str = ""  # 生成时的上下文

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "value": self.value,
            "weight": self.weight,
            "rarity": self.rarity,
            "properties": self.properties,
            "usage_description": self.usage_description,
            "llm_generated": self.llm_generated,
            "generation_context": self.generation_context
        }


@dataclass
class Spell:
    """法术"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    level: int = 1
    school: str = "evocation"
    casting_time: str = "1 action"
    range: str = "60 feet"
    components: List[str] = field(default_factory=list)
    duration: str = "instantaneous"
    damage: str = ""
    damage_type: DamageType = DamageType.PHYSICAL
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "school": self.school,
            "casting_time": self.casting_time,
            "range": self.range,
            "components": self.components,
            "duration": self.duration,
            "damage": self.damage,
            "damage_type": self.damage_type.value
        }


@dataclass
class Character:
    """角色基类"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    character_class: CharacterClass = CharacterClass.FIGHTER
    creature_type: CreatureType = CreatureType.HUMANOID
    abilities: Ability = field(default_factory=Ability)
    stats: Stats = field(default_factory=Stats)
    inventory: List[Item] = field(default_factory=list)
    spells: List[Spell] = field(default_factory=list)
    position: tuple = (0, 0)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "character_class": self.character_class.value,
            "creature_type": self.creature_type.value,
            "abilities": self.abilities.__dict__,
            "stats": self.stats.__dict__,
            "inventory": [item.to_dict() for item in self.inventory],
            "spells": [spell.to_dict() for spell in self.spells],
            "position": self.position
        }


@dataclass
class Monster(Character):
    """怪物"""
    challenge_rating: float = 1.0
    behavior: str = "aggressive"  # aggressive, defensive, neutral, flee
    loot_table: List[str] = field(default_factory=list)
    attack_range: int = 1  # 攻击范围，1为近战，>1为远程攻击
    # 任务相关属性
    is_boss: bool = False  # 是否为Boss
    quest_monster_id: Optional[str] = None  # 关联的任务怪物ID

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "challenge_rating": self.challenge_rating,
            "behavior": self.behavior,
            "loot_table": self.loot_table,
            "attack_range": self.attack_range,
            "is_boss": self.is_boss,
            "quest_monster_id": self.quest_monster_id
        })
        return data


@dataclass
class MapTile:
    """地图瓦片"""
    x: int = 0
    y: int = 0
    terrain: TerrainType = TerrainType.FLOOR
    is_explored: bool = False
    is_visible: bool = False
    items: List[Item] = field(default_factory=list)
    character_id: Optional[str] = None
    # 事件相关字段
    has_event: bool = False
    event_type: str = ""  # 事件类型：combat, treasure, trap, story, etc.
    event_data: Dict[str, Any] = field(default_factory=dict)  # 事件数据
    is_event_hidden: bool = True  # 事件是否隐藏
    event_triggered: bool = False  # 事件是否已触发
    # 物品相关字段
    items_collected: List[str] = field(default_factory=list)  # 已收集的物品ID列表
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "terrain": self.terrain.value,
            "is_explored": self.is_explored,
            "is_visible": self.is_visible,
            "items": [item.to_dict() for item in self.items],
            "character_id": self.character_id,
            "has_event": self.has_event,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "is_event_hidden": self.is_event_hidden,
            "event_triggered": self.event_triggered
        }


@dataclass
class GameMap:
    """游戏地图"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    width: int = 20
    height: int = 20
    depth: int = 1  # 地下层数
    tiles: Dict[tuple, MapTile] = field(default_factory=dict)
    
    def get_tile(self, x: int, y: int) -> Optional[MapTile]:
        """获取指定位置的瓦片"""
        return self.tiles.get((x, y))
    
    def set_tile(self, x: int, y: int, tile: MapTile):
        """设置指定位置的瓦片"""
        tile.x = x
        tile.y = y
        self.tiles[(x, y)] = tile
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "tiles": {f"{k[0]},{k[1]}": v.to_dict() for k, v in self.tiles.items()}
        }


@dataclass
class QuestEvent:
    """任务专属事件"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""  # combat, treasure, story, boss, etc.
    name: str = ""
    description: str = ""
    trigger_condition: str = ""  # 触发条件描述
    progress_value: float = 0.0  # 完成此事件获得的进度值
    is_mandatory: bool = True  # 是否为必须完成的事件
    location_hint: str = ""  # 位置提示（如"第2层的深处"）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "name": self.name,
            "description": self.description,
            "trigger_condition": self.trigger_condition,
            "progress_value": self.progress_value,
            "is_mandatory": self.is_mandatory,
            "location_hint": self.location_hint
        }


@dataclass
class QuestMonster:
    """任务专属怪物"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    challenge_rating: float = 1.0
    is_boss: bool = False
    progress_value: float = 0.0  # 击败此怪物获得的进度值
    spawn_condition: str = ""  # 生成条件描述
    location_hint: str = ""  # 位置提示

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "challenge_rating": self.challenge_rating,
            "is_boss": self.is_boss,
            "progress_value": self.progress_value,
            "spawn_condition": self.spawn_condition,
            "location_hint": self.location_hint
        }


@dataclass
class Quest:
    """任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    objectives: List[str] = field(default_factory=list)
    completed_objectives: List[bool] = field(default_factory=list)
    rewards: List[Item] = field(default_factory=list)
    experience_reward: int = 0
    is_completed: bool = False
    is_active: bool = False
    # 新增：LLM控制的进度系统
    progress_percentage: float = 0.0  # 隐藏的进度百分比（0-100）
    story_context: str = ""  # 故事背景上下文
    llm_notes: str = ""  # LLM的内部笔记，用于控制节奏

    # 任务专属内容
    quest_type: str = "exploration"  # 任务类型：exploration, combat, story, rescue, etc.
    target_floors: List[int] = field(default_factory=list)  # 目标楼层
    map_themes: List[str] = field(default_factory=list)  # 地图主题建议
    special_events: List[QuestEvent] = field(default_factory=list)  # 专属事件
    special_monsters: List[QuestMonster] = field(default_factory=list)  # 专属怪物
    
    def complete_objective(self, index: int):
        """完成指定目标"""
        if 0 <= index < len(self.completed_objectives):
            self.completed_objectives[index] = True
            if all(self.completed_objectives):
                self.is_completed = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "objectives": self.objectives,
            "completed_objectives": self.completed_objectives,
            "rewards": [item.to_dict() for item in self.rewards],
            "experience_reward": self.experience_reward,
            "is_completed": self.is_completed,
            "is_active": self.is_active,
            "progress_percentage": self.progress_percentage,
            "story_context": self.story_context,
            "llm_notes": self.llm_notes,
            "quest_type": self.quest_type,
            "target_floors": self.target_floors,
            "map_themes": self.map_themes,
            "special_events": [event.to_dict() for event in self.special_events],
            "special_monsters": [monster.to_dict() for monster in self.special_monsters]
        }


@dataclass
class GameState:
    """游戏状态"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    player: Character = field(default_factory=Character)
    current_map: GameMap = field(default_factory=GameMap)
    monsters: List[Monster] = field(default_factory=list)
    quests: List[Quest] = field(default_factory=list)
    turn_count: int = 0
    game_time: int = 0  # 游戏内时间（分钟）
    last_narrative: str = ""  # 最后的叙述文本
    is_game_over: bool = False  # 游戏是否结束
    game_over_reason: str = ""  # 游戏结束原因
    pending_events: List[str] = field(default_factory=list)  # 待显示的事件
    created_at: datetime = field(default_factory=datetime.now)
    last_saved: datetime = field(default_factory=datetime.now)
    # 新增：地图切换控制
    pending_map_transition: Optional[str] = None  # 待切换的地图类型 ("stairs_down", "stairs_up", etc.)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "player": self.player.to_dict(),
            "current_map": self.current_map.to_dict(),
            "monsters": [monster.to_dict() for monster in self.monsters],
            "quests": [quest.to_dict() for quest in self.quests],
            "turn_count": self.turn_count,
            "game_time": self.game_time,
            "last_narrative": self.last_narrative,
            "is_game_over": self.is_game_over,
            "game_over_reason": self.game_over_reason,
            "pending_events": self.pending_events,
            "created_at": self.created_at.isoformat(),
            "last_saved": self.last_saved.isoformat(),
            "pending_map_transition": self.pending_map_transition
        }


# 导出所有模型
__all__ = [
    "CharacterClass", "CreatureType", "DamageType", "TerrainType",
    "Ability", "Stats", "Item", "Spell", "Character", "Monster",
    "MapTile", "GameMap", "QuestEvent", "QuestMonster", "Quest", "GameState"
]
