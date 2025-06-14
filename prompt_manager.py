"""
Labyrinthia AI - 统一提示词管理器
Unified prompt management system for the Labyrinthia AI game
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from pathlib import Path

from data_models import GameState, Character, GameMap, Quest, Item


logger = logging.getLogger(__name__)


class PromptCategory(Enum):
    """提示词分类"""
    MAP_GENERATION = "map_generation"
    ITEM_SYSTEM = "item_system"
    COMBAT_SYSTEM = "combat_system"
    QUEST_SYSTEM = "quest_system"
    NARRATIVE = "narrative"


@dataclass
class PromptTemplate:
    """提示词模板"""
    name: str
    category: PromptCategory
    template: str
    required_params: List[str] = field(default_factory=list)
    optional_params: Dict[str, Any] = field(default_factory=dict)
    schema: Optional[Dict] = None
    description: str = ""
    version: str = "1.0"


class PromptManager:
    """统一的提示词管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.templates: Dict[str, PromptTemplate] = {}
        self.categories: Dict[PromptCategory, Dict[str, PromptTemplate]] = {
            category: {} for category in PromptCategory
        }
        self.fallback_messages: Dict[str, str] = {}

        # 尝试从配置文件加载，否则使用默认模板
        if config_file and Path(config_file).exists():
            self._load_from_config(config_file)
        else:
            # 尝试加载默认配置文件
            default_config = Path("prompt_templates.json")
            if default_config.exists():
                self._load_from_config(str(default_config))
            else:
                self._load_default_templates()

        logger.info(f"PromptManager initialized with {len(self.templates)} templates")

    def _load_from_config(self, config_file: str):
        """从配置文件加载提示词模板"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            # 加载模板
            templates_data = config_data.get("templates", {})
            for template_name, template_data in templates_data.items():
                try:
                    category = PromptCategory(template_data["category"])
                    template = PromptTemplate(
                        name=template_data["name"],
                        category=category,
                        template=template_data["template"],
                        required_params=template_data.get("required_params", []),
                        optional_params=template_data.get("optional_params", {}),
                        schema=template_data.get("schema"),
                        description=template_data.get("description", ""),
                        version=template_data.get("version", "1.0")
                    )
                    self.register_template(template)
                except Exception as e:
                    logger.error(f"Failed to load template '{template_name}': {e}")

            # 加载备用消息
            self.fallback_messages = config_data.get("fallback_messages", {})

            logger.info(f"Loaded {len(self.templates)} templates from config file: {config_file}")

        except Exception as e:
            logger.error(f"Failed to load config file {config_file}: {e}")
            logger.info("Falling back to default templates")
            self._load_default_templates()

    def _load_default_templates(self):
        """加载默认提示词模板"""
        # 地图生成相关模板
        self._register_map_templates()
        # 物品系统相关模板
        self._register_item_templates()
        # 战斗系统相关模板
        self._register_combat_templates()
        # 任务系统相关模板
        self._register_quest_templates()
        # 叙述生成相关模板
        self._register_narrative_templates()
    
    def _register_map_templates(self):
        """注册地图相关模板"""
        # 地图信息生成
        map_info_template = PromptTemplate(
            name="map_info_generation",
            category=PromptCategory.MAP_GENERATION,
            template="""
为一个{width}x{height}的地下城第{depth}层生成名称和描述。
基础主题：{theme}{quest_info}

请返回JSON格式：
{{
    "name": "地图名称（中文，体现主题和任务特色）",
    "description": "地图描述（详细描述环境、氛围和可能的挑战）"
}}
            """.strip(),
            required_params=["width", "height", "depth", "theme"],
            optional_params={"quest_info": ""},
            description="生成地图基本信息（名称和描述）"
        )
        self.register_template(map_info_template)
        
        # 地图描述生成
        map_description_template = PromptTemplate(
            name="map_description",
            category=PromptCategory.MAP_GENERATION,
            template="""
请为这个地下城地图生成一个生动的描述。

地图信息：
- 名称：{map_name}
- 大小：{width}x{height}
- 层数：{depth}

上下文信息：{context}

请生成一个富有想象力的地图描述，包括环境、氛围、可能的危险等。
            """.strip(),
            required_params=["map_name", "width", "height", "depth"],
            optional_params={"context": ""},
            description="生成详细的地图环境描述"
        )
        self.register_template(map_description_template)
    
    def _register_item_templates(self):
        """注册物品相关模板"""
        # 物品拾取生成
        item_pickup_template = PromptTemplate(
            name="item_pickup_generation",
            category=PromptCategory.ITEM_SYSTEM,
            template="""
为一个DnD风格的冒险游戏生成一个物品，玩家刚刚在地图上发现了它。

玩家信息：
- 名称：{player_name}
- 职业：{player_class}
- 等级：{player_level}
- 当前位置：{player_position}

地图信息：
- 地图名称：{map_name}
- 地图描述：{map_description}
- 地图深度：{map_depth}层

拾取上下文：{pickup_context}

请生成一个适合当前情况的物品，要求：
1. 必须有中文名称
2. 详细的功能和使用场景介绍
3. 物品类型要合理（weapon/armor/consumable/misc）
4. 稀有度要符合地图深度和玩家等级
5. 使用说明要清晰明确

请返回JSON格式的物品数据。
            """.strip(),
            required_params=[
                "player_name", "player_class", "player_level", "player_position",
                "map_name", "map_description", "map_depth", "pickup_context"
            ],
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "item_type": {"type": "string", "enum": ["weapon", "armor", "consumable", "misc"]},
                    "rarity": {"type": "string", "enum": ["common", "uncommon", "rare", "epic", "legendary"]},
                    "value": {"type": "integer", "minimum": 1},
                    "weight": {"type": "number", "minimum": 0.1},
                    "usage_description": {"type": "string"},
                    "damage": {"type": "integer", "minimum": 0},
                    "armor_class": {"type": "integer", "minimum": 0},
                    "healing": {"type": "integer", "minimum": 0},
                    "mana_restore": {"type": "integer", "minimum": 0}
                },
                "required": ["name", "description", "item_type", "rarity", "value", "weight", "usage_description"]
            },
            description="生成玩家拾取的物品"
        )
        self.register_template(item_pickup_template)
        
        # 物品使用效果
        item_usage_template = PromptTemplate(
            name="item_usage_effect",
            category=PromptCategory.ITEM_SYSTEM,
            template="""
玩家正在使用一个物品，请根据物品属性和当前游戏状态，生成使用效果。

物品信息：
- 名称：{item_name}
- 描述：{item_description}
- 类型：{item_type}
- 稀有度：{item_rarity}
- 使用说明：{item_usage_description}
- 属性：{item_properties}

玩家信息：
- 名称：{player_name}
- 职业：{player_class}
- 等级：{player_level}
- 生命值：{player_hp}/{player_max_hp}
- 法力值：{player_mp}/{player_max_mp}
- 护甲等级：{player_ac}
- 经验值：{player_experience}
- 当前位置：{player_position}

地图信息：{map_info}

请根据物品的特性和当前情况，生成合理的使用效果。可以包括：
- 属性变化（生命值、法力值、经验值等）
- 传送效果
- 地图变化
- 特殊效果

请返回JSON格式的效果数据。
            """.strip(),
            required_params=[
                "item_name", "item_description", "item_type", "item_rarity", 
                "item_usage_description", "item_properties", "player_name", 
                "player_class", "player_level", "player_hp", "player_max_hp",
                "player_mp", "player_max_mp", "player_ac", "player_experience",
                "player_position", "map_info"
            ],
            description="生成物品使用的效果"
        )
        self.register_template(item_usage_template)
    
    def _register_combat_templates(self):
        """注册战斗相关模板"""
        # 怪物生成
        monster_generation_template = PromptTemplate(
            name="monster_generation",
            category=PromptCategory.COMBAT_SYSTEM,
            template="""
为等级{player_level}的玩家生成一个DnD风格的怪物。

难度要求：{difficulty}
上下文信息：{context}

请返回JSON格式的怪物数据，包含：
- name: 怪物名称（中文）
- description: 怪物描述
- creature_type: 生物类型
- stats: 属性数据（hp, attack, defense等）
- abilities: 特殊能力列表

确保怪物适合玩家等级和指定难度。
            """.strip(),
            required_params=["player_level", "difficulty"],
            optional_params={"context": ""},
            description="生成适合玩家等级的怪物"
        )
        self.register_template(monster_generation_template)
    
    def _register_quest_templates(self):
        """注册任务相关模板"""
        # 任务生成
        quest_generation_template = PromptTemplate(
            name="quest_generation",
            category=PromptCategory.QUEST_SYSTEM,
            template="""
请为等级{player_level}的玩家生成一个DnD风格的任务。

上下文信息：{context}

请返回JSON格式的任务数据，包含：
- title: 任务标题
- description: 任务描述
- objectives: 目标列表（字符串数组）
- experience_reward: 经验奖励

确保任务适合玩家等级，有趣且具有挑战性。
            """.strip(),
            required_params=["player_level"],
            optional_params={"context": ""},
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "objectives": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "experience_reward": {"type": "integer", "minimum": 0}
                },
                "required": ["title", "description", "objectives", "experience_reward"]
            },
            description="生成适合玩家等级的任务"
        )
        self.register_template(quest_generation_template)
        
        # 任务事件
        quest_event_template = PromptTemplate(
            name="quest_event_story",
            category=PromptCategory.QUEST_SYSTEM,
            template="""
为玩家生成一个任务相关的故事事件。

事件信息：
- 事件名称：{event_name}
- 事件描述：{event_description}
- 是否必须：{is_mandatory}

玩家当前位置：({player_x}, {player_y})
玩家等级：{player_level}
地图：{map_name}

请生成一个与任务相关的生动故事描述（100-150字），体现事件的重要性。
            """.strip(),
            required_params=[
                "event_name", "event_description", "is_mandatory",
                "player_x", "player_y", "player_level", "map_name"
            ],
            description="生成任务相关的故事事件"
        )
        self.register_template(quest_event_template)
    
    def _register_narrative_templates(self):
        """注册叙述相关模板"""
        # 通用叙述模板
        general_narrative_template = PromptTemplate(
            name="general_narrative",
            category=PromptCategory.NARRATIVE,
            template="""
玩家信息：
- 名称：{player_name}
- 等级：{player_level}
- 生命值：{player_hp}/{player_max_hp}
- 位置：{player_position}

当前地图：{map_name}
回合数：{turn_count}

上下文信息：
- 最近事件：{recent_events}
- 战斗情况：{combat_summary}
- 移动情况：{movement_pattern}
- 环境状态：{environmental_state}
- 任务状态：{quest_status}

刚刚发生的事件：{current_events}
主要行动：{primary_action}

请根据当前情况和上下文信息，生成一段连贯的叙述文本，
描述行动的结果、环境的变化和玩家的感受。(80-120字)
            """.strip(),
            required_params=[
                "player_name", "player_level", "player_hp", "player_max_hp",
                "player_position", "map_name", "turn_count", "recent_events",
                "combat_summary", "movement_pattern", "environmental_state",
                "quest_status", "current_events", "primary_action"
            ],
            description="生成通用的游戏叙述文本"
        )
        self.register_template(general_narrative_template)

    def register_template(self, template: PromptTemplate):
        """注册提示词模板"""
        self.templates[template.name] = template
        self.categories[template.category][template.name] = template
        logger.debug(f"Registered template: {template.name} in category {template.category.value}")

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """获取提示词模板"""
        return self.templates.get(name)

    def get_templates_by_category(self, category: PromptCategory) -> Dict[str, PromptTemplate]:
        """按分类获取提示词模板"""
        return self.categories.get(category, {})

    def format_prompt(self, template_name: str, **kwargs) -> str:
        """格式化提示词"""
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        # 检查必需参数
        missing_params = []
        for param in template.required_params:
            if param not in kwargs:
                missing_params.append(param)

        if missing_params:
            raise ValueError(f"Missing required parameters for template '{template_name}': {missing_params}")

        # 合并可选参数的默认值
        format_kwargs = template.optional_params.copy()
        format_kwargs.update(kwargs)

        try:
            formatted_prompt = template.template.format(**format_kwargs)
            logger.debug(f"Formatted prompt for template: {template_name}")
            return formatted_prompt
        except KeyError as e:
            raise ValueError(f"Parameter {e} not provided for template '{template_name}'")

    def get_schema(self, template_name: str) -> Optional[Dict]:
        """获取模板的JSON Schema"""
        template = self.get_template(template_name)
        return template.schema if template else None

    def validate_template(self, template: PromptTemplate) -> bool:
        """验证模板格式"""
        try:
            # 检查模板是否包含所有必需参数的占位符
            template_text = template.template
            for param in template.required_params:
                if f"{{{param}}}" not in template_text:
                    logger.warning(f"Required parameter '{param}' not found in template '{template.name}'")
                    return False

            # 尝试用默认值格式化模板
            test_kwargs = {param: f"test_{param}" for param in template.required_params}
            test_kwargs.update(template.optional_params)
            template.template.format(**test_kwargs)

            return True
        except Exception as e:
            logger.error(f"Template validation failed for '{template.name}': {e}")
            return False

    def list_templates(self) -> List[str]:
        """列出所有模板名称"""
        return list(self.templates.keys())

    def list_categories(self) -> List[PromptCategory]:
        """列出所有分类"""
        return list(PromptCategory)

    def get_fallback_message(self, interaction_type: str) -> str:
        """获取备用消息"""
        return self.fallback_messages.get(interaction_type, self.fallback_messages.get("default", "继续冒险..."))

    def save_to_config(self, config_file: str):
        """保存模板到配置文件"""
        config_data = {
            "templates": {},
            "fallback_messages": self.fallback_messages
        }

        for template_name, template in self.templates.items():
            config_data["templates"][template_name] = {
                "name": template.name,
                "category": template.category.value,
                "template": template.template,
                "required_params": template.required_params,
                "optional_params": template.optional_params,
                "schema": template.schema,
                "description": template.description,
                "version": template.version
            }

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self.templates)} templates to config file: {config_file}")
        except Exception as e:
            logger.error(f"Failed to save config file {config_file}: {e}")

    # 便捷方法：构建常用的上下文信息
    def build_player_context(self, player: Character) -> Dict[str, Any]:
        """构建玩家上下文信息"""
        return {
            "player_name": player.name,
            "player_class": player.character_class.value,
            "player_level": player.stats.level,
            "player_hp": player.stats.hp,
            "player_max_hp": player.stats.max_hp,
            "player_mp": player.stats.mp,
            "player_max_mp": player.stats.max_mp,
            "player_ac": player.stats.ac,
            "player_experience": player.stats.experience,
            "player_position": player.position
        }

    def build_map_context(self, game_map: GameMap) -> Dict[str, Any]:
        """构建地图上下文信息"""
        return {
            "map_name": game_map.name,
            "map_description": game_map.description,
            "map_depth": game_map.depth,
            "width": game_map.width,
            "height": game_map.height
        }

    def build_item_context(self, item: Item) -> Dict[str, Any]:
        """构建物品上下文信息"""
        return {
            "item_name": item.name,
            "item_description": item.description,
            "item_type": item.item_type,
            "item_rarity": item.rarity,
            "item_usage_description": getattr(item, 'usage_description', ''),
            "item_properties": getattr(item, 'properties', {})
        }

    def build_game_context(self, game_state: GameState) -> Dict[str, Any]:
        """构建完整的游戏上下文信息"""
        context = {}

        # 玩家信息
        context.update(self.build_player_context(game_state.player))

        # 地图信息
        context.update(self.build_map_context(game_state.current_map))

        # 游戏状态信息
        context.update({
            "turn_count": game_state.turn_count,
            "is_game_over": game_state.is_game_over
        })

        return context


# 全局提示词管理器实例
prompt_manager = PromptManager()

__all__ = ["PromptManager", "PromptTemplate", "PromptCategory", "prompt_manager"]
