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
    EVENT_CHOICE = "event_choice"


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

        # 确保事件选择模板被注册（在配置文件加载后）
        self._register_event_choice_templates()

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
        # 事件选择相关模板
        self._register_event_choice_templates()
    
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
    "description": "地图描述（详细描述环境、氛围和可能的挑战）",
    "floor_theme": "地板主题类型（必须从以下选项中选择一个）"
}}

**地板主题选项说明**：
- "normal": 普通地牢（石质地板+裂纹效果）- 适合常规地牢、走廊、普通房间
- "magic": 魔法房间（大理石+魔法符文）- 适合魔法区域、神殿、法师塔、魔法阵
- "abandoned": 废弃房间（木质地板+苔藓）- 适合废弃建筑、老旧房间、被遗忘的区域
- "cave": 洞穴（泥土地面+水渍）- 适合天然洞穴、地下通道、潮湿区域
- "combat": 战斗区域（石质地板+血迹）- 适合竞技场、战场、屠宰场、血腥场景

**重要**：请根据地图的主题、任务内容和环境氛围，选择最合适的地板主题。
            """.strip(),
            required_params=["width", "height", "depth", "theme"],
            optional_params={"quest_info": ""},
            description="生成地图基本信息（名称、描述和地板主题）"
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
- name: 怪物名称（**必须是中文**，不要使用英文或拼音）
- description: 怪物描述（中文）
- creature_type: 生物类型（中文）
- stats: 属性数据（hp, attack, defense等）
- abilities: 特殊能力列表（中文描述）

**重要要求**：
1. 怪物名称必须是纯中文，例如："暗影狼"、"骷髅战士"、"火焰元素"
2. 不要使用英文名称或拼音
3. 确保怪物适合玩家等级和指定难度
4. 所有描述性文本都应该使用中文
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

    def _register_event_choice_templates(self):
        """注册事件选择相关模板"""
        # 故事事件选择生成
        story_event_choices_template = PromptTemplate(
            name="story_event_choices",
            category=PromptCategory.EVENT_CHOICE,
            template="""
为一个DnD风格的冒险游戏生成一个故事事件的选择情况。

玩家信息：
- 名称：{player_name}
- 等级：{player_level}
- 生命值：{player_hp}/{player_max_hp}
- 位置：({location_x}, {location_y})

地图信息：
- 地图名称：{map_name}
- 地图深度：第{map_depth}层

当前任务信息：
{{% if has_active_quest %}}
- 任务标题：{quest_title}
- 任务描述：{quest_description}
- 任务类型：{quest_type}
- 任务进度：{quest_progress:.1f}%
- 任务目标：{quest_objectives}
- 故事背景：{quest_story_context}
{{% else %}}
- 当前无活跃任务
{{% endif %}}

事件信息：
- 事件类型：{story_type}
- 事件描述：{event_description}

请生成一个与当前任务相关的有趣故事事件，包含：
1. 事件标题和详细描述（要与任务背景呼应）
2. 3-4个不同的选择选项
3. 每个选项都要有明确的后果说明
4. 选项要有不同的风险和收益
5. 如果有活跃任务，事件应该与任务主题、目标或故事背景相关

请返回JSON格式：
{{
    "title": "事件标题",
    "description": "详细的事件描述（100-150字，要体现与任务的关联）",
    "choices": [
        {{
            "text": "选项文本",
            "description": "选项详细说明",
            "consequences": "可能的后果（可能影响任务进度）",
            "requirements": {{"min_level": 1}}
        }}
    ]
}}

注意：
- 事件要符合DnD世界观
- 如果有活跃任务，事件要与任务相关联
- 选择要有意义的后果，可能推进或影响任务
- 描述要生动有趣，体现任务的故事背景
- 选项要平衡风险和收益
- 考虑任务进度，为接近完成的任务提供相关机会
            """.strip(),
            required_params=[
                "player_name", "player_level", "player_hp", "player_max_hp",
                "location_x", "location_y", "map_name", "map_depth", "story_type",
                "has_active_quest", "quest_title", "quest_description", "quest_type",
                "quest_progress", "quest_objectives", "quest_story_context"
            ],
            optional_params={"event_description": ""},
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "description": {"type": "string"},
                                "consequences": {"type": "string"},
                                "requirements": {"type": "object"}
                            },
                            "required": ["text", "description", "consequences"]
                        }
                    }
                },
                "required": ["title", "description", "choices"]
            },
            description="生成与任务相关的故事事件选择"
        )
        self.register_template(story_event_choices_template)

        # 任务完成选择生成
        quest_completion_choices_template = PromptTemplate(
            name="quest_completion_choices",
            category=PromptCategory.EVENT_CHOICE,
            template="""
为一个DnD风格的冒险游戏生成任务完成后的选择情况。

任务信息：
- 标题：{quest_title}
- 描述：{quest_description}
- 类型：{quest_type}
- 经验奖励：{experience_reward}
- 故事背景：{story_context}

玩家信息：
- 名称：{player_name}
- 等级：{player_level}

当前环境：
- 地图：{current_map}
- 深度：第{map_depth}层

请生成任务完成后的情况，包含：
1. 庆祝完成的描述
2. 3-4个关于下一步行动的选择，包括：
   - 继续在当前区域探索的选项
   - 寻找新的冒险机会的选项（可以涉及新任务或新区域）
   - 休息整理装备的选项
   - 其他符合故事发展的选项
3. 每个选项要有明确的后果和发展方向
4. 选项应该为玩家提供多样化的发展路径，包括继续冒险的可能性
5. **重要**：每个选项必须在 requirements 对象中设置以下字段：
   - leads_to_new_quest: 是否导向新任务（true/false）
   - leads_to_map_transition: 是否导向地图切换（true/false）
   - quest_theme: 如果导向新任务，新任务的主题（字符串）
   - map_theme: 如果导向地图切换，新地图的主题（字符串）

请返回JSON格式：
{{
    "title": "任务完成标题",
    "description": "任务完成的庆祝描述（100-150字）",
    "choices": [
        {{
            "text": "选项文本",
            "description": "选项详细说明",
            "consequences": "可能的后果和发展",
            "requirements": {{
                "leads_to_new_quest": true,
                "leads_to_map_transition": true,
                "quest_theme": "探索矿井深处的秘密",
                "map_theme": "矿井深层"
            }}
        }}
    ]
}}
            """.strip(),
            required_params=[
                "quest_title", "quest_description", "quest_type", "experience_reward",
                "story_context", "player_name", "player_level", "current_map", "map_depth"
            ],
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "description": {"type": "string"},
                                "consequences": {"type": "string"},
                                "requirements": {
                                    "type": "object",
                                    "properties": {
                                        "leads_to_new_quest": {"type": "boolean"},
                                        "leads_to_map_transition": {"type": "boolean"},
                                        "quest_theme": {"type": "string"},
                                        "map_theme": {"type": "string"}
                                    }
                                }
                            },
                            "required": ["text", "description", "consequences"]
                        }
                    }
                },
                "required": ["title", "description", "choices"]
            },
            description="生成任务完成后的选择情况"
        )
        self.register_template(quest_completion_choices_template)

        # 处理故事选择结果
        process_story_choice_template = PromptTemplate(
            name="process_story_choice",
            category=PromptCategory.EVENT_CHOICE,
            template="""
玩家在一个故事事件中做出了选择，请处理选择的结果。

选择信息：
- 选择文本：{choice_text}
- 选择描述：{choice_description}

事件背景：{event_context}

玩家信息：
- 名称：{player_name}
- 等级：{player_level}
- 生命值：{player_hp}/{player_max_hp}
- 位置：{tile_position}

当前地图信息：
- 地图名称：{current_map}
- 地图深度：第{map_depth}层
- 地图尺寸：{map_width}x{map_height}

当前任务信息：
{{% if quest_id %}}
- 任务ID：{quest_id}
- 任务详情：{quest_info}
{{% else %}}
暂无活跃任务
{{% endif %}}

**重要说明**：你作为AI主持人，拥有完全的权限来修改游戏世界。你可以：
1. 修改地图上任何位置的地形（如创建隐藏通道、新房间等）
2. 在地图上添加新的物品、门、楼梯等元素
3. 改变玩家的属性和状态
4. 推进任务进度
5. 创建新的事件和互动元素
6. **直接切换到全新的地图区域**（如发现传送门、进入异次元空间、被传送到新区域等）

请根据玩家的选择生成合理且有趣的结果。如果选择涉及发现隐藏通道、秘密房间等，请大胆地修改地图结构。
如果选择涉及传送、进入新区域等情况，可以直接切换到新地图。

地图更新格式说明：
- 使用 "x,y" 格式作为坐标键（如 "15,10"）
- 可修改的地形类型：floor, wall, door, stairs_up, stairs_down, treasure, trap, water, lava, pit
- 可添加事件数据、物品、怪物等

怪物操作说明：
- 添加怪物：在 "monster" 字段中设置 "action": "add"
- 更新怪物：在 "monster" 字段中设置 "action": "update"
- 移除怪物：在 "monster" 字段中设置 "action": "remove"

事件操作说明：
- 设置 "has_event": true 来创建事件瓦片
- 使用 "event_type" 指定事件类型：story, combat, treasure, trap, secret_passage, puzzle等
- 在 "event_data" 中添加事件的详细信息

请返回JSON格式：
{{
    "message": "选择结果的主要描述（80-120字）",
    "events": ["详细的事件描述1", "详细的事件描述2"],
    "player_updates": {{
        "stats": {{"hp": 新生命值, "experience": 新经验值}},
        "add_items": [
            {{
                "name": "物品名称",
                "description": "物品描述",
                "item_type": "weapon/armor/consumable/misc",
                "rarity": "common/uncommon/rare/epic/legendary"
            }}
        ],
        "remove_items": ["物品名称"]
    }},
    "map_updates": {{
        "tiles": {{
            "x,y": {{
                "terrain": "新地形类型",
                "has_event": true,
                "event_type": "story",
                "event_data": {{"description": "事件描述"}},
                "items": [物品数据],
                "monster": {{
                    "action": "add/update/remove",
                    "name": "怪物名称",
                    "description": "怪物描述",
                    "challenge_rating": 1.5,
                    "behavior": "aggressive/defensive/neutral",
                    "is_boss": false,
                    "attack_range": 1,
                    "stats": {{
                        "max_hp": 30,
                        "hp": 30,
                        "ac": 14,
                        "level": 2
                    }}
                }}
            }}
        }}
    }},
    "quest_updates": {{
        "{quest_id}": {{"progress_percentage": 新进度}}
    }},
    "map_transition": {{
        "should_transition": false,  // 是否需要切换地图
        "transition_type": "new_area",  // new_area 或 existing_area
        "target_depth": 目标楼层（可选，默认为当前层+1）,
        "theme": "新地图主题描述",
        "message": "地图切换时的提示消息"
    }}
}}

**地图切换说明**：
- 只有在选择涉及传送、进入新区域、发现传送门等情况时才设置 should_transition 为 true
- transition_type 通常使用 "new_area" 来生成全新的地图
- theme 应该描述新地图的风格和特点（如"神秘的地下湖泊"、"古老的图书馆"等）
- message 是玩家看到的切换提示
            """.strip(),
            required_params=[
                "choice_text", "choice_description", "event_context",
                "player_name", "player_level", "player_hp", "player_max_hp",
                "current_map", "map_depth", "map_width", "map_height", "tile_position"
            ],
            optional_params={"quest_info": "", "quest_id": ""},
            schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "string"}},
                    "player_updates": {
                        "type": "object",
                        "properties": {
                            "stats": {"type": "object"},
                            "add_items": {"type": "array"},
                            "remove_items": {"type": "array"}
                        }
                    },
                    "map_updates": {
                        "type": "object",
                        "properties": {
                            "tiles": {"type": "object"}
                        }
                    },
                    "quest_updates": {"type": "object"},
                    "new_items": {"type": "array"},
                    "map_transition": {
                        "type": "object",
                        "properties": {
                            "should_transition": {"type": "boolean"},
                            "transition_type": {"type": "string"},
                            "target_depth": {"type": "integer"},
                            "theme": {"type": "string"},
                            "message": {"type": "string"}
                        }
                    }
                },
                "required": ["message", "events"]
            },
            description="处理故事选择的结果"
        )
        self.register_template(process_story_choice_template)

        # 处理任务完成选择结果
        process_quest_completion_choice_template = PromptTemplate(
            name="process_quest_completion_choice",
            category=PromptCategory.EVENT_CHOICE,
            template="""
玩家在任务完成后做出了选择，请处理选择的结果。

选择信息：
- 选择文本：{choice_text}
- 选择描述：{choice_description}
- 是否导向新任务：{leads_to_new_quest}
- 是否导向地图切换：{leads_to_map_transition}
- 任务主题：{quest_theme}
- 地图主题：{map_theme}

已完成任务：{completed_quest_data}

玩家信息：
- 名称：{player_name}
- 等级：{player_level}

当前环境：
- 地图：{current_map}
- 深度：第{map_depth}层

请根据玩家的选择生成合理的结果：
1. 如果选择导向新任务，生成新任务的基本信息
2. 如果选择导向地图切换，生成地图切换的信息
3. 否则处理当前地图内的活动（玩家状态调整、发现隐藏区域等）

请返回JSON格式：
{{
    "message": "选择结果的主要描述",
    "events": ["事件描述1", "事件描述2"],
    "player_updates": {{
        "stats": {{"hp": 新生命值}}
    }},
    "quest_updates": {{}},
    "new_quest_data": {{
        "title": "新任务标题",
        "description": "新任务描述",
        "type": "任务类型",
        "experience_reward": 经验奖励,
        "objectives": ["目标1", "目标2"],
        "story_context": "故事背景"
    }},
    "map_transition": {{
        "should_transition": true,
        "transition_type": "new_area",
        "target_depth": 目标楼层,
        "theme": "地图主题",
        "message": "切换消息"
    }}
}}
            """.strip(),
            required_params=[
                "choice_text", "choice_description", "completed_quest_data",
                "player_name", "player_level", "current_map", "map_depth"
            ],
            schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "string"}},
                    "player_updates": {"type": "object"},
                    "quest_updates": {"type": "object"},
                    "new_quest_data": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "type": {"type": "string"},
                            "experience_reward": {"type": "integer"},
                            "objectives": {"type": "array", "items": {"type": "string"}},
                            "story_context": {"type": "string"}
                        }
                    },
                    "map_transition": {
                        "type": "object",
                        "properties": {
                            "should_transition": {"type": "boolean"},
                            "transition_type": {"type": "string"},
                            "target_depth": {"type": "integer"},
                            "theme": {"type": "string"},
                            "message": {"type": "string"}
                        }
                    }
                },
                "required": ["message", "events"]
            },
            description="处理任务完成选择的结果"
        )
        self.register_template(process_quest_completion_choice_template)

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
