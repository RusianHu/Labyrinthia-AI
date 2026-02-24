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
    WARRIOR = "warrior"  # 添加warrior作为fighter的别名
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
    PHYSICAL_SLASH = "physical_slash"
    PHYSICAL_PIERCE = "physical_pierce"
    PHYSICAL_BLUNT = "physical_blunt"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    ACID = "acid"
    POISON = "poison"
    NECROTIC = "necrotic"
    RADIANT = "radiant"
    PSYCHIC = "psychic"
    FORCE = "force"
    THUNDER = "thunder"
    ARCANE = "arcane"
    TRUE = "true"


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
    """DND六维属性 (D&D Ability Scores)

    标准DND六维属性系统:
    - Strength (力量): 物理力量,影响近战攻击和负重
    - Dexterity (敏捷): 灵活性和反应速度,影响AC和远程攻击
    - Constitution (体质): 耐力和生命力,影响HP
    - Intelligence (智力): 学习和推理能力,影响魔法和知识
    - Wisdom (感知): 洞察力和直觉,影响感知检定和意志豁免
    - Charisma (魅力): 个人魅力和说服力,影响社交互动

    属性值范围: 1-30 (10为普通人类平均值)
    调整值计算: (属性值 - 10) // 2
    """
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    def get_modifier(self, ability_name: str) -> int:
        """获取能力调整值 (Ability Modifier)

        Args:
            ability_name: 属性名称 (strength, dexterity, constitution, intelligence, wisdom, charisma)

        Returns:
            调整值 (通常在-5到+10之间)
        """
        value = getattr(self, ability_name.lower())
        return (value - 10) // 2

    def get_all_modifiers(self) -> Dict[str, int]:
        """获取所有属性的调整值"""
        return {
            "strength": self.get_modifier("strength"),
            "dexterity": self.get_modifier("dexterity"),
            "constitution": self.get_modifier("constitution"),
            "intelligence": self.get_modifier("intelligence"),
            "wisdom": self.get_modifier("wisdom"),
            "charisma": self.get_modifier("charisma")
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典,包含属性值和调整值"""
        return {
            "strength": self.strength,
            "dexterity": self.dexterity,
            "constitution": self.constitution,
            "intelligence": self.intelligence,
            "wisdom": self.wisdom,
            "charisma": self.charisma,
            "modifiers": self.get_all_modifiers()
        }


@dataclass
class Stats:
    """角色衍生属性 (Derived Stats)

    这些属性由六维属性计算得出,不应直接设置基础六维属性
    """
    hp: int = 100
    max_hp: int = 100
    mp: int = 50
    max_mp: int = 50
    ac: int = 10  # 护甲等级 (Armor Class)
    ac_components: Dict[str, int] = field(default_factory=lambda: {
        "base": 10,
        "armor": 0,
        "shield": 0,
        "status": 0,
        "situational": 0,
        "penalty": 0,
    })
    ac_min: int = 1
    ac_max: int = 50
    speed: int = 30  # 移动速度
    level: int = 1
    experience: int = 0
    shield: int = 0
    temporary_hp: int = 0

    def __post_init__(self):
        self._normalize_ac_components()
        self.ac = self.get_effective_ac()

    def _normalize_ac_components(self):
        required_keys = ("base", "armor", "shield", "status", "situational", "penalty")

        raw_components = self.ac_components if isinstance(self.ac_components, dict) else {}
        normalized: Dict[str, int] = {}
        fallback_base = int(self.ac or 10)

        for key in required_keys:
            default_value = fallback_base if key == "base" else 0
            try:
                normalized[key] = int(raw_components.get(key, default_value) or default_value)
            except (TypeError, ValueError):
                normalized[key] = default_value

        self.ac_components = normalized

        try:
            self.ac_min = max(1, int(self.ac_min or 1))
        except (TypeError, ValueError):
            self.ac_min = 1

        try:
            self.ac_max = max(int(self.ac_min), int(self.ac_max or 50))
        except (TypeError, ValueError):
            self.ac_max = max(int(self.ac_min), 50)

    def is_alive(self) -> bool:
        """检查是否存活"""
        return self.hp > 0

    def calculate_derived_stats(self, abilities: Ability):
        """根据六维属性计算衍生属性

        Args:
            abilities: 角色的六维属性对象
        """
        # 根据体质调整生命值
        con_modifier = abilities.get_modifier("constitution")
        base_hp = 100 + (con_modifier * 10)
        self.max_hp = max(base_hp, 10)  # 最少10点生命值
        if self.hp > self.max_hp:
            self.hp = self.max_hp

        # 根据智力调整魔法值
        int_modifier = abilities.get_modifier("intelligence")
        base_mp = 50 + (int_modifier * 5)
        self.max_mp = max(base_mp, 0)  # 魔法值可以为0
        if self.mp > self.max_mp:
            self.mp = self.max_mp

        # 根据敏捷调整护甲等级
        dex_modifier = abilities.get_modifier("dexterity")
        self._normalize_ac_components()
        self.ac_components["base"] = 10 + dex_modifier
        self.ac = self.get_effective_ac()

        # 根据敏捷调整速度
        self.speed = 30 + dex_modifier

    def get_effective_ac(self) -> int:
        """计算分层 AC 的聚合值（兼容旧字段 ac）"""
        self._normalize_ac_components()
        components = self.ac_components
        value = (
            int(components.get("base", 10) or 10)
            + int(components.get("armor", 0) or 0)
            + int(components.get("shield", 0) or 0)
            + int(components.get("status", 0) or 0)
            + int(components.get("situational", 0) or 0)
            - int(components.get("penalty", 0) or 0)
        )
        value = max(int(self.ac_min or 1), min(int(self.ac_max or 50), value))
        return value


@dataclass
class StatusEffect:
    """持续状态效果（buff/debuff）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    effect_type: str = "buff"  # buff, debuff, neutral
    runtime_type: str = "duration"  # duration, trigger, one_shot, aura
    duration_turns: int = 1
    stacks: int = 1
    max_stacks: int = 1
    stack_policy: str = "replace"  # replace, stack, refresh, keep_highest
    source: str = ""
    source_trace_id: str = ""
    tags: List[str] = field(default_factory=list)
    group_mutex: str = ""
    group_override: str = ""
    group_stack: str = ""
    dispel_type: str = ""  # curse, poison, magic, physical, all
    dispel_priority: int = 0
    snapshot_mode: str = "realtime"  # realtime, snapshot
    control_flags: List[str] = field(default_factory=list)  # stun, silence, disarm, root
    potency: Dict[str, Any] = field(default_factory=dict)
    modifiers: Dict[str, Any] = field(default_factory=dict)
    tick_effects: Dict[str, Any] = field(default_factory=dict)
    triggers: Dict[str, Any] = field(default_factory=dict)
    hook_payloads: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "effect_type": self.effect_type,
            "runtime_type": self.runtime_type,
            "duration_turns": self.duration_turns,
            "stacks": self.stacks,
            "max_stacks": self.max_stacks,
            "stack_policy": self.stack_policy,
            "source": self.source,
            "source_trace_id": self.source_trace_id,
            "tags": self.tags,
            "group_mutex": self.group_mutex,
            "group_override": self.group_override,
            "group_stack": self.group_stack,
            "dispel_type": self.dispel_type,
            "dispel_priority": self.dispel_priority,
            "snapshot_mode": self.snapshot_mode,
            "control_flags": self.control_flags,
            "potency": self.potency,
            "modifiers": self.modifiers,
            "tick_effects": self.tick_effects,
            "triggers": self.triggers,
            "hook_payloads": self.hook_payloads,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StatusEffect":
        effect = cls()

        def _safe_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        effect.id = data.get("id", effect.id)
        effect.name = data.get("name", "")
        effect.effect_type = data.get("effect_type", "buff")
        effect.runtime_type = str(data.get("runtime_type", "duration") or "duration")
        effect.duration_turns = _safe_int(data.get("duration_turns", 1), 1)
        effect.stacks = _safe_int(data.get("stacks", 1), 1)
        effect.max_stacks = _safe_int(data.get("max_stacks", max(effect.stacks, 1)), max(effect.stacks, 1))
        effect.stack_policy = data.get("stack_policy", "replace")
        effect.source = data.get("source", "")
        effect.source_trace_id = str(data.get("source_trace_id", "") or "")
        effect.tags = data.get("tags", []) or []
        effect.group_mutex = str(data.get("group_mutex", "") or "")
        effect.group_override = str(data.get("group_override", "") or "")
        effect.group_stack = str(data.get("group_stack", "") or "")
        effect.dispel_type = str(data.get("dispel_type", "") or "")
        effect.dispel_priority = _safe_int(data.get("dispel_priority", 0), 0)
        effect.snapshot_mode = str(data.get("snapshot_mode", "realtime") or "realtime")
        effect.control_flags = [str(v) for v in (data.get("control_flags", []) or [])]
        effect.potency = data.get("potency", {}) or {}
        effect.modifiers = data.get("modifiers", {}) or {}
        effect.tick_effects = data.get("tick_effects", {}) or {}

        triggers = data.get("triggers")
        if not isinstance(triggers, dict):
            trigger = data.get("trigger")
            if trigger:
                triggers = {"on": trigger}
            else:
                triggers = {}
        effect.triggers = triggers

        effect.hook_payloads = data.get("hook_payloads", {}) or {}
        effect.metadata = data.get("metadata", {}) or {}
        return effect


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
    effect_payload: Dict[str, Any] = field(default_factory=dict)  # 可选：固定效果载荷
    use_mode: str = "active"  # active, passive, toggle
    is_equippable: bool = False
    equip_slot: str = ""  # weapon, armor, accessory_1, accessory_2
    equip_passive_effects: List[Dict[str, Any]] = field(default_factory=list)
    affixes: List[Dict[str, Any]] = field(default_factory=list)
    trigger_affixes: List[Dict[str, Any]] = field(default_factory=list)
    set_id: str = ""
    set_thresholds: Dict[str, Any] = field(default_factory=dict)
    equip_requirements: Dict[str, Any] = field(default_factory=dict)
    item_power_score: float = 0.0
    unique_key: str = ""
    max_charges: int = 0
    charges: int = 0
    cooldown_turns: int = 0
    current_cooldown: int = 0
    is_quest_item: bool = False
    quest_lock_reason: str = ""
    hint_level: str = "vague"  # none, vague, clear
    trigger_hint: str = ""
    risk_hint: str = ""
    expected_outcomes: List[str] = field(default_factory=list)
    requires_use_confirmation: bool = False
    consumption_hint: str = ""

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
            "generation_context": self.generation_context,
            "effect_payload": self.effect_payload,
            "use_mode": self.use_mode,
            "is_equippable": self.is_equippable,
            "equip_slot": self.equip_slot,
            "equip_passive_effects": self.equip_passive_effects,
            "affixes": self.affixes,
            "trigger_affixes": self.trigger_affixes,
            "set_id": self.set_id,
            "set_thresholds": self.set_thresholds,
            "equip_requirements": self.equip_requirements,
            "item_power_score": self.item_power_score,
            "unique_key": self.unique_key,
            "max_charges": self.max_charges,
            "charges": self.charges,
            "cooldown_turns": self.cooldown_turns,
            "current_cooldown": self.current_cooldown,
            "is_quest_item": self.is_quest_item,
            "quest_lock_reason": self.quest_lock_reason,
            "hint_level": self.hint_level,
            "trigger_hint": self.trigger_hint,
            "risk_hint": self.risk_hint,
            "expected_outcomes": self.expected_outcomes,
            "requires_use_confirmation": self.requires_use_confirmation,
            "consumption_hint": self.consumption_hint
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
    resistances: Dict[str, float] = field(default_factory=dict)
    vulnerabilities: Dict[str, float] = field(default_factory=dict)
    immunities: List[str] = field(default_factory=list)
    inventory: List[Item] = field(default_factory=list)
    equipped_items: Dict[str, Optional[Item]] = field(default_factory=lambda: {
        "weapon": None,
        "armor": None,
        "accessory_1": None,
        "accessory_2": None,
    })
    active_effects: List[StatusEffect] = field(default_factory=list)
    runtime_stats: Dict[str, Any] = field(default_factory=dict)
    derived_runtime: Dict[str, Any] = field(default_factory=dict)
    combat_runtime: Dict[str, int] = field(default_factory=lambda: {
        "shield": 0,
        "temporary_hp": 0,
    })
    spells: List[Spell] = field(default_factory=list)
    position: tuple = (0, 0)
    # DND技能系统
    proficiency_bonus: int = 2  # 熟练加值（基于等级，2-6）
    skill_proficiencies: List[str] = field(default_factory=list)  # 熟练技能列表（如["perception", "stealth"]）
    tool_proficiencies: List[str] = field(default_factory=list)  # 熟练工具列表（如["thieves_tools"]）
    saving_throw_proficiencies: List[str] = field(default_factory=list)  # 豁免熟练列表（如["dexterity", "intelligence"]）

    def get_passive_perception(self) -> int:
        """计算被动感知值 (Passive Perception)

        公式: 10 + 感知调整值 + 熟练加值(如有)

        Returns:
            被动感知值（通常在8-20之间）
        """
        wis_modifier = self.abilities.get_modifier("wisdom")
        proficiency = self.proficiency_bonus if "perception" in self.skill_proficiencies else 0
        return 10 + wis_modifier + proficiency

    def get_proficiency_bonus_by_level(self) -> int:
        """根据等级计算熟练加值

        DND 5E规则：
        - 等级1-4: +2
        - 等级5-8: +3
        - 等级9-12: +4
        - 等级13-16: +5
        - 等级17-20: +6

        Returns:
            熟练加值
        """
        level = self.stats.level
        if level <= 4:
            return 2
        elif level <= 8:
            return 3
        elif level <= 12:
            return 4
        elif level <= 16:
            return 5
        else:
            return 6

    def update_proficiency_bonus(self):
        """根据当前等级更新熟练加值"""
        self.proficiency_bonus = self.get_proficiency_bonus_by_level()

    def to_dict(self) -> Dict[str, Any]:
        combat_runtime = self.combat_runtime if isinstance(self.combat_runtime, dict) else {}

        def _safe_non_negative_int(value: Any, default: int = 0) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return max(0, int(default or 0))

        shield = _safe_non_negative_int(combat_runtime.get("shield", getattr(self.stats, "shield", 0)), getattr(self.stats, "shield", 0))
        temporary_hp = _safe_non_negative_int(combat_runtime.get("temporary_hp", getattr(self.stats, "temporary_hp", 0)), getattr(self.stats, "temporary_hp", 0))

        # 兼容旧字段：仍在 stats 中保留镜像值，避免旧客户端/旧逻辑断裂
        self.stats.shield = shield
        self.stats.temporary_hp = temporary_hp
        self.combat_runtime = {
            "shield": shield,
            "temporary_hp": temporary_hp,
        }

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "character_class": self.character_class.value,
            "creature_type": self.creature_type.value,
            "abilities": self.abilities.__dict__,
            "stats": self.stats.__dict__,
            "resistances": self.resistances,
            "vulnerabilities": self.vulnerabilities,
            "immunities": self.immunities,
            "inventory": [item.to_dict() for item in self.inventory],
            "equipped_items": {
                slot: item.to_dict() if item else None
                for slot, item in self.equipped_items.items()
            },
            "active_effects": [
                effect.to_dict() if hasattr(effect, "to_dict") else effect
                for effect in self.active_effects
            ],
            "spells": [spell.to_dict() for spell in self.spells],
            "runtime_stats": self.runtime_stats,
            "derived_runtime": self.derived_runtime,
            "combat_runtime": {
                "shield": shield,
                "temporary_hp": temporary_hp,
            },
            "position": self.position,
            "proficiency_bonus": self.proficiency_bonus,
            "skill_proficiencies": self.skill_proficiencies,
            "tool_proficiencies": self.tool_proficiencies,
            "saving_throw_proficiencies": self.saving_throw_proficiencies,
            "passive_perception": self.get_passive_perception()
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
    # 房间相关字段
    room_type: str = ""  # 房间类型：entrance, treasure, boss, special, normal, corridor
    room_id: Optional[str] = None  # 房间ID，用于标识同一房间的瓦片
    # 事件相关字段
    has_event: bool = False
    event_type: str = ""  # 事件类型：combat, treasure, trap, story, etc.
    event_data: Dict[str, Any] = field(default_factory=dict)  # 事件数据
    is_event_hidden: bool = True  # 事件是否隐藏
    event_triggered: bool = False  # 事件是否已触发
    # 物品相关字段
    items_collected: List[str] = field(default_factory=list)  # 已收集的物品ID列表
    # 陷阱专属字段（用于地形型陷阱和事件型陷阱）
    trap_detected: bool = False  # 陷阱是否已被发现
    trap_disarmed: bool = False  # 陷阱是否已被解除

    def is_trap(self) -> bool:
        """判断此瓦片是否为陷阱

        Returns:
            True如果是地形型陷阱或事件型陷阱
        """
        return self.terrain == TerrainType.TRAP or \
               (self.has_event and self.event_type == 'trap')

    def get_trap_data(self) -> Dict[str, Any]:
        """获取陷阱数据

        Returns:
            陷阱数据字典，如果不是陷阱则返回空字典
        """
        if not self.is_trap():
            return {}

        # 如果是事件型陷阱，返回event_data
        if self.has_event and self.event_type == 'trap':
            return self.event_data

        # 如果是地形型陷阱，返回默认数据
        return {
            "trap_type": "damage",
            "damage": 15,
            "damage_type": "physical",
            "detect_dc": 15,
            "disarm_dc": 18,
            "save_dc": 14,
            "save_half_damage": True
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "terrain": self.terrain.value,
            "is_explored": self.is_explored,
            "is_visible": self.is_visible,
            "items": [item.to_dict() for item in self.items],
            "character_id": self.character_id,
            "room_type": self.room_type,
            "room_id": self.room_id,
            "has_event": self.has_event,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "is_event_hidden": self.is_event_hidden,
            "event_triggered": self.event_triggered,
            "items_collected": self.items_collected,
            "trap_detected": self.trap_detected,
            "trap_disarmed": self.trap_disarmed
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
    floor_theme: str = "normal"  # 地板主题: normal, magic, abandoned, cave, combat
    tiles: Dict[tuple, MapTile] = field(default_factory=dict)
    generation_metadata: Dict[str, Any] = field(default_factory=dict)
    
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
            "floor_theme": self.floor_theme,
            "generation_metadata": self.generation_metadata,
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
            "special_events": [
                event.to_dict() if hasattr(event, 'to_dict') else event
                for event in self.special_events
            ],
            "special_monsters": [
                monster.to_dict() if hasattr(monster, 'to_dict') else monster
                for monster in self.special_monsters
            ]
        }


@dataclass
class EventChoice:
    """事件选项"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""  # 选项显示文本
    description: str = ""  # 选项详细描述
    consequences: str = ""  # 选择后果描述
    requirements: Dict[str, Any] = field(default_factory=dict)  # 选择要求（如等级、物品等）
    is_available: bool = True  # 是否可选择

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "description": self.description,
            "consequences": self.consequences,
            "requirements": self.requirements,
            "is_available": self.is_available
        }


@dataclass
class EventChoiceContext:
    """事件选择上下文"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""  # 事件类型：story, combat, mystery, quest_completion等
    title: str = ""  # 事件标题
    description: str = ""  # 事件描述
    choices: List[EventChoice] = field(default_factory=list)  # 可选择的选项
    context_data: Dict[str, Any] = field(default_factory=dict)  # 上下文数据
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "choices": [choice.to_dict() for choice in self.choices],
            "context_data": self.context_data,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class GameState:
    """游戏状态"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    save_version: int = 2
    equipment_schema_version: int = 2
    combat_rule_version: int = 1
    combat_authority_mode: str = "local"
    player: Character = field(default_factory=Character)
    current_map: GameMap = field(default_factory=GameMap)
    combat_rules: Dict[str, Any] = field(default_factory=dict)
    combat_snapshot: Dict[str, Any] = field(default_factory=dict)
    monsters: List[Monster] = field(default_factory=list)
    quests: List[Quest] = field(default_factory=list)
    turn_count: int = 0
    game_time: int = 0  # 游戏内时间（分钟）
    last_narrative: str = ""  # 最后的叙述文本
    is_game_over: bool = False  # 游戏是否结束
    game_over_reason: str = ""  # 游戏结束原因
    pending_events: List[str] = field(default_factory=list)  # 待显示的事件
    pending_effects: List[Dict[str, Any]] = field(default_factory=list)  # 待显示的特效
    created_at: datetime = field(default_factory=datetime.now)
    last_saved: datetime = field(default_factory=datetime.now)
    # 新增：地图切换控制
    pending_map_transition: Optional[str] = None  # 待切换的地图类型 ("stairs_down", "stairs_up", etc.)
    # 新增：事件选择系统
    pending_choice_context: Optional[EventChoiceContext] = None  # 待处理的选择上下文

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "save_version": self.save_version,
            "equipment_schema_version": self.equipment_schema_version,
            "combat_rule_version": self.combat_rule_version,
            "combat_authority_mode": self.combat_authority_mode,
            "player": self.player.to_dict(),
            "current_map": self.current_map.to_dict(),
            "combat_rules": self.combat_rules,
            "combat_snapshot": self.combat_snapshot,
            "monsters": [monster.to_dict() for monster in self.monsters],
            "quests": [quest.to_dict() for quest in self.quests],
            "turn_count": self.turn_count,
            "game_time": self.game_time,
            "last_narrative": self.last_narrative,
            "is_game_over": self.is_game_over,
            "game_over_reason": self.game_over_reason,
            "pending_events": self.pending_events,
            "pending_effects": self.pending_effects,
            "created_at": self.created_at.isoformat(),
            "last_saved": self.last_saved.isoformat(),
            "pending_map_transition": self.pending_map_transition,
            "pending_choice_context": self.pending_choice_context.to_dict() if self.pending_choice_context else None
        }


# 导出所有模型
__all__ = [
    "CharacterClass", "CreatureType", "DamageType", "TerrainType",
    "Ability", "Stats", "StatusEffect", "Item", "Spell", "Character", "Monster",
    "MapTile", "GameMap", "QuestEvent", "QuestMonster", "Quest",
    "EventChoice", "EventChoiceContext", "GameState"
]
