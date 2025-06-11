"""
Labyrinthia AI - LLM服务封装
LLM service wrapper for the Labyrinthia AI game
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Union
from concurrent.futures import ThreadPoolExecutor

from gemini_api import GeminiAPI
from openrouter_client import OpenRouterClient, ChatError
from config import config, LLMProvider
from data_models import Character, Monster, GameMap, Quest, GameState, Item


logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务封装类"""
    
    def __init__(self):
        self.provider = config.llm.provider
        self.executor = ThreadPoolExecutor(max_workers=config.game.max_concurrent_llm_requests)

        # 准备代理配置
        proxies = {}
        if config.llm.use_proxy and config.llm.proxy_url:
            proxies = {
                'http': config.llm.proxy_url,
                'https': config.llm.proxy_url
            }
            logger.info(f"Using proxy: {config.llm.proxy_url}")

        # 初始化对应的LLM客户端
        if self.provider == LLMProvider.GEMINI:
            self.client = GeminiAPI(
                api_key=config.llm.api_key,
                endpoint=config.llm.gemini_endpoint,
                api_version=config.llm.gemini_api_version,
                default_timeout=config.llm.timeout,
                proxies=proxies
            )
        elif self.provider == LLMProvider.OPENROUTER:
            self.client = OpenRouterClient(
                api_key=config.llm.api_key,
                base_url=config.llm.openrouter_base_url,
                default_model=config.llm.model_name,
                timeout=config.llm.timeout,
                proxies=proxies,
                referer="https://github.com/Labyrinthia-AI/Labyrinthia-AI", # 使用一个有效的URL作为Referer
                title=config.game.game_name
            )
        else:
            raise NotImplementedError(f"LLM provider {self.provider} not implemented yet")
    
    async def _async_generate(self, prompt: str, **kwargs) -> str:
        """异步生成内容"""
        loop = asyncio.get_event_loop()
        
        def _sync_generate():
            try:
                generation_config = {
                    "temperature": config.llm.temperature,
                    "top_p": config.llm.top_p,
                }
                
                # 如果设置了max_output_tokens，则添加到配置中
                if config.llm.max_output_tokens:
                    generation_config["max_output_tokens"] = config.llm.max_output_tokens
                
                # 合并用户提供的配置
                generation_config.update(kwargs.get("generation_config", {}))
                
                # 根据提供商调用不同的客户端
                if self.provider == LLMProvider.GEMINI:
                    response = self.client.single_turn(
                        model=config.llm.model_name,
                        text=prompt,
                        generation_config=generation_config
                    )
                    
                    # 提取生成的文本
                    if response.get("candidates") and response["candidates"][0].get("content"):
                        parts = response["candidates"][0]["content"].get("parts", [])
                        if parts and parts[0].get("text"):
                            return parts[0]["text"]

                    # 检查是否因为其他原因（如MAX_TOKENS）导致没有文本内容
                    if response.get("candidates"):
                        candidate = response["candidates"][0]
                        finish_reason = candidate.get("finishReason", "")
                        if finish_reason in ["MAX_TOKENS", "STOP"]:
                            logger.warning(f"LLM response finished with reason: {finish_reason}")
                            # 尝试从content中获取任何可用文本
                            content = candidate.get("content", {})
                            if content.get("parts"):
                                for part in content["parts"]:
                                    if part.get("text"):
                                        return part["text"]

                    logger.warning("LLM response format unexpected")
                    return ""
                
                elif self.provider == LLMProvider.OPENROUTER:
                    # OpenRouter API使用 `max_tokens` 而不是 `max_output_tokens`
                    if "max_output_tokens" in generation_config:
                        generation_config["max_tokens"] = generation_config.pop("max_output_tokens")
                    
                    return self.client.chat_once(
                        prompt=prompt,
                        model=config.llm.model_name,
                        **generation_config
                    )

            except ChatError as e:
                logger.error(f"LLM generation error (OpenRouter): {e}")
                return ""
            except Exception as e:
                logger.error(f"LLM generation error: {e}")
                return ""
        
        return await loop.run_in_executor(self.executor, _sync_generate)
    
    async def _async_generate_json(self, prompt: str, schema: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """异步生成JSON格式内容"""
        loop = asyncio.get_event_loop()
        
        def _sync_generate_json():
            try:
                generation_config = {
                    "temperature": config.llm.temperature,
                    "top_p": config.llm.top_p,
                }
                
                # 如果设置了max_output_tokens，则添加到配置中
                if config.llm.max_output_tokens:
                    generation_config["max_output_tokens"] = config.llm.max_output_tokens
                
                # 合并用户提供的配置
                generation_config.update(kwargs.get("generation_config", {}))
                
                # 根据提供商调用不同的客户端
                if self.provider == LLMProvider.GEMINI:
                    response = self.client.single_turn_json(
                        model=config.llm.model_name,
                        text=prompt,
                        schema=schema,
                        generation_config=generation_config
                    )
                    
                    # 提取生成的JSON
                    if response.get("candidates") and response["candidates"][0].get("content"):
                        parts = response["candidates"][0]["content"].get("parts", [])
                        if parts and parts[0].get("text"):
                            try:
                                parsed_json = json.loads(parts[0]["text"])
                                if isinstance(parsed_json, dict):
                                    return parsed_json
                                else:
                                    logger.warning(f"LLM returned a non-dict JSON: {type(parsed_json)}")
                                    return {}
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse JSON response: {e}")
                                return {}
                    
                    logger.warning("LLM JSON response format unexpected")
                    return {}

                elif self.provider == LLMProvider.OPENROUTER:
                    # OpenRouter API使用 `max_tokens` 而不是 `max_output_tokens`
                    if "max_output_tokens" in generation_config:
                        generation_config["max_tokens"] = generation_config.pop("max_output_tokens")

                    return self.client.chat_json_once(
                        prompt=prompt,
                        model=config.llm.model_name,
                        schema=schema,
                        **generation_config
                    )
                    
            except ChatError as e:
                logger.error(f"LLM JSON generation error (OpenRouter): {e}")
                return {}
            except Exception as e:
                logger.error(f"LLM JSON generation error: {e}")
                return {}
        
        return await loop.run_in_executor(self.executor, _sync_generate_json)
    
    async def generate_character(self, character_type: str = "npc", context: str = "") -> Optional[Character]:
        """生成角色"""
        prompt = f"""
        请生成一个DnD风格的{character_type}角色。
        
        上下文信息：{context}
        
        请返回JSON格式的角色数据，包含以下字段：
        - name: 角色名称
        - description: 角色描述
        - character_class: 职业（fighter, wizard, rogue, cleric, ranger, barbarian, bard, paladin, sorcerer, warlock）
        - abilities: 能力值对象（strength, dexterity, constitution, intelligence, wisdom, charisma，每个值10-18）
        - stats: 属性对象（hp, max_hp, mp, max_mp, ac, speed, level, experience）
        
        确保角色符合DnD设定，有趣且平衡。
        """
        
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "character_class": {"type": "string"},
                "abilities": {
                    "type": "object",
                    "properties": {
                        "strength": {"type": "integer", "minimum": 8, "maximum": 18},
                        "dexterity": {"type": "integer", "minimum": 8, "maximum": 18},
                        "constitution": {"type": "integer", "minimum": 8, "maximum": 18},
                        "intelligence": {"type": "integer", "minimum": 8, "maximum": 18},
                        "wisdom": {"type": "integer", "minimum": 8, "maximum": 18},
                        "charisma": {"type": "integer", "minimum": 8, "maximum": 18}
                    }
                },
                "stats": {
                    "type": "object",
                    "properties": {
                        "hp": {"type": "integer", "minimum": 1},
                        "max_hp": {"type": "integer", "minimum": 1},
                        "mp": {"type": "integer", "minimum": 0},
                        "max_mp": {"type": "integer", "minimum": 0},
                        "ac": {"type": "integer", "minimum": 8},
                        "speed": {"type": "integer", "minimum": 20},
                        "level": {"type": "integer", "minimum": 1, "maximum": 20},
                        "experience": {"type": "integer", "minimum": 0}
                    }
                }
            },
            "required": ["name", "description", "character_class", "abilities", "stats"]
        }
        
        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                # 创建Character对象
                character = Character()
                character.name = result.get("name", "")
                character.description = result.get("description", "")
                
                # 设置职业
                from data_models import CharacterClass
                try:
                    character.character_class = CharacterClass(result.get("character_class", "fighter"))
                except ValueError:
                    character.character_class = CharacterClass.FIGHTER
                
                # 设置能力值
                if abilities := result.get("abilities"):
                    for attr, value in abilities.items():
                        if hasattr(character.abilities, attr):
                            setattr(character.abilities, attr, value)
                
                # 设置属性
                if stats := result.get("stats"):
                    for attr, value in stats.items():
                        if hasattr(character.stats, attr):
                            setattr(character.stats, attr, value)
                
                return character
        except Exception as e:
            logger.error(f"Failed to generate character: {e}")
        
        return None
    
    async def generate_monster(self, challenge_rating: float = 1.0, context: str = "") -> Optional[Monster]:
        """生成怪物"""
        # 使用generate_character生成基础角色，然后转换为Monster
        monster_context = f"挑战等级{challenge_rating}的怪物。{context}"
        character = await self.generate_character("monster", monster_context)
        if character:
            monster = Monster()
            # 正确复制Character的所有属性，保持对象类型
            monster.id = character.id
            monster.name = character.name
            monster.description = character.description
            monster.character_class = character.character_class
            monster.creature_type = character.creature_type
            monster.abilities = character.abilities  # 保持为Ability对象
            monster.stats = character.stats  # 保持为Stats对象
            monster.inventory = character.inventory
            monster.spells = character.spells
            monster.position = character.position

            monster.challenge_rating = challenge_rating
            monster.behavior = "aggressive"  # 默认行为

            # 根据挑战等级随机设置攻击范围，高等级怪物更可能有远程攻击
            import random
            if challenge_rating >= 2.0 and random.random() < 0.3:  # 30%概率远程攻击
                monster.attack_range = random.randint(2, 4)
            elif challenge_rating >= 1.0 and random.random() < 0.15:  # 15%概率远程攻击
                monster.attack_range = random.randint(2, 3)
            else:
                monster.attack_range = 1  # 默认近战

            return monster

        return None
    
    async def generate_map_description(self, map_data: GameMap, context: str = "") -> str:
        """生成地图描述"""
        prompt = f"""
        请为这个地下城地图生成一个生动的描述。
        
        地图信息：
        - 名称：{map_data.name}
        - 大小：{map_data.width}x{map_data.height}
        - 层数：{map_data.depth}
        
        上下文信息：{context}
        
        请生成一个富有想象力的地图描述，包括环境、氛围、可能的危险等。
        """
        
        return await self._async_generate(prompt)
    
    async def generate_quest(self, player_level: int = 1, context: str = "") -> Optional[Quest]:
        """生成任务"""
        prompt = f"""
        请为等级{player_level}的玩家生成一个DnD风格的任务。
        
        上下文信息：{context}
        
        请返回JSON格式的任务数据，包含：
        - title: 任务标题
        - description: 任务描述
        - objectives: 目标列表（字符串数组）
        - experience_reward: 经验奖励
        
        确保任务适合玩家等级，有趣且具有挑战性。
        """
        
        schema = {
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
        }
        
        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                quest = Quest()
                quest.title = result.get("title", "")
                quest.description = result.get("description", "")
                quest.objectives = result.get("objectives", [])
                quest.completed_objectives = [False] * len(quest.objectives)
                quest.experience_reward = result.get("experience_reward", 0)
                return quest
        except Exception as e:
            logger.error(f"Failed to generate quest: {e}")
        
        return None
    
    async def generate_narrative(self, game_state: GameState, action: str) -> str:
        """生成叙述文本"""
        prompt = f"""
        基于当前游戏状态，为玩家的行动生成叙述文本。
        
        玩家信息：
        - 名称：{game_state.player.name}
        - 等级：{game_state.player.stats.level}
        - 位置：{game_state.player.position}
        
        当前地图：{game_state.current_map.name}
        回合数：{game_state.turn_count}
        
        玩家行动：{action}
        
        请生成一段生动的叙述文本，描述行动的结果和环境变化。
        """
        
        return await self._async_generate(prompt)

    async def generate_opening_narrative(self, game_state: GameState) -> str:
        """生成开场叙述"""
        prompt = f"""
        为一个DnD风格的冒险游戏生成开场叙述。

        玩家信息：
        - 名称：{game_state.player.name}
        - 职业：{game_state.player.character_class.value}
        - 等级：{game_state.player.stats.level}

        当前地图：{game_state.current_map.name}
        地图描述：{game_state.current_map.description}

        请生成一段引人入胜的开场叙述（100-200字），描述玩家刚刚踏入这个地下城的情景，
        包括环境描述、氛围营造和对即将到来的冒险的暗示。
        """

        return await self._async_generate(prompt)

    async def generate_return_narrative(self, game_state: GameState) -> str:
        """生成重新进入游戏的叙述"""
        prompt = f"""
        为一个DnD风格的冒险游戏生成重新进入游戏的叙述。

        玩家信息：
        - 名称：{game_state.player.name}
        - 职业：{game_state.player.character_class.value}
        - 等级：{game_state.player.stats.level}
        - 当前位置：{game_state.player.position}

        当前地图：{game_state.current_map.name}
        回合数：{game_state.turn_count}

        请生成一段简短的叙述（50-100字），描述玩家重新回到游戏世界的情景，
        让玩家快速回忆起当前的状况和环境。
        """

        return await self._async_generate(prompt)

    async def generate_item_on_pickup(self, game_state: GameState,
                                    pickup_context: str = "") -> Optional[Item]:
        """在拾取时生成物品"""
        player = game_state.player
        current_map = game_state.current_map

        prompt = f"""
        为一个DnD风格的冒险游戏生成一个物品，玩家刚刚在地图上发现了它。

        玩家信息：
        - 名称：{player.name}
        - 职业：{player.character_class.value}
        - 等级：{player.stats.level}
        - 当前位置：{player.position}

        地图信息：
        - 地图名称：{current_map.name}
        - 地图描述：{current_map.description}
        - 地图深度：{current_map.depth}层

        拾取上下文：{pickup_context}

        请生成一个适合当前情况的物品，要求：
        1. 必须有中文名称
        2. 详细的功能和使用场景介绍
        3. 物品类型要合理（weapon/armor/consumable/misc）
        4. 稀有度要符合地图深度和玩家等级
        5. 使用说明要清晰明确

        请返回JSON格式：
        {{
            "name": "物品的中文名称",
            "description": "物品的详细描述，包括外观和背景故事",
            "item_type": "物品类型（weapon/armor/consumable/misc）",
            "rarity": "稀有度（common/uncommon/rare/epic/legendary）",
            "value": 物品价值（金币）,
            "weight": 物品重量,
            "usage_description": "详细的使用说明和效果描述",
            "damage": "武器伤害（如果是武器，否则留空）",
            "armor_class": "护甲等级（如果是护甲，否则留空）",
            "healing": 治疗量（如果是治疗物品，否则为0）,
            "mana_restore": 法力恢复量（如果恢复法力，否则为0）,
            "special_effect": "特殊效果描述（如果有特殊效果）"
        }}
        """

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "item_type": {"type": "string", "enum": ["weapon", "armor", "consumable", "misc"]},
                "rarity": {"type": "string", "enum": ["common", "uncommon", "rare", "epic", "legendary"]},
                "value": {"type": "integer", "minimum": 0},
                "weight": {"type": "number", "minimum": 0},
                "usage_description": {"type": "string"},
                "damage": {"type": "string"},
                "armor_class": {"type": "string"},
                "healing": {"type": "integer"},
                "mana_restore": {"type": "integer"},
                "special_effect": {"type": "string"}
            },
            "required": ["name", "description", "item_type", "rarity", "value", "weight", "usage_description"]
        }

        try:
            result = await self._async_generate_json(prompt, schema)
            if result:
                item = Item()
                item.name = result.get("name", "神秘物品")
                item.description = result.get("description", "一个神秘的物品")
                item.item_type = result.get("item_type", "misc")
                item.rarity = result.get("rarity", "common")
                item.value = result.get("value", 10)
                item.weight = result.get("weight", 1.0)
                item.usage_description = result.get("usage_description", "使用方法未知")
                # 构建properties字典
                properties = {}
                if result.get("damage"):
                    properties["damage"] = result["damage"]
                if result.get("armor_class"):
                    properties["armor_class"] = result["armor_class"]
                if result.get("healing"):
                    properties["healing"] = result["healing"]
                if result.get("mana_restore"):
                    properties["mana_restore"] = result["mana_restore"]
                if result.get("special_effect"):
                    properties["special_effect"] = result["special_effect"]

                item.properties = properties
                item.llm_generated = True
                item.generation_context = pickup_context

                return item
        except Exception as e:
            logger.error(f"生成物品失败: {e}")

        return None

    async def process_item_usage(self, game_state: GameState, item: Item) -> Dict[str, Any]:
        """处理物品使用，返回效果数据"""
        player = game_state.player
        current_map = game_state.current_map

        # 构建地图状态信息
        map_info = {
            "name": current_map.name,
            "description": current_map.description,
            "depth": current_map.depth,
            "player_position": player.position,
            "nearby_terrain": self._get_nearby_terrain(game_state, player.position[0], player.position[1])
        }

        prompt = f"""
        玩家正在使用一个物品，请根据物品属性和当前游戏状态，生成使用效果。

        物品信息：
        - 名称：{item.name}
        - 描述：{item.description}
        - 类型：{item.item_type}
        - 稀有度：{item.rarity}
        - 使用说明：{item.usage_description}
        - 属性：{item.properties}

        玩家信息：
        - 名称：{player.name}
        - 职业：{player.character_class.value}
        - 等级：{player.stats.level}
        - 生命值：{player.stats.hp}/{player.stats.max_hp}
        - 法力值：{player.stats.mp}/{player.stats.max_mp}
        - 护甲等级：{player.stats.ac}
        - 经验值：{player.stats.experience}
        - 当前位置：{player.position}

        地图信息：{map_info}

        请根据物品的特性和当前情况，生成合理的使用效果。可以包括：
        - 属性变化（生命值、法力值、经验值等）
        - 传送效果
        - 地图变化
        - 特殊效果

        请返回JSON格式：
        {{
            "message": "使用物品后的描述信息",
            "events": ["事件描述1", "事件描述2"],
            "item_consumed": true,
            "effects": {{
                "stat_changes": {{
                    "hp": 变化量,
                    "mp": 变化量,
                    "experience": 变化量
                }},
                "teleport": {{
                    "type": "random/specific/stairs",
                    "x": 目标x坐标（如果是specific）,
                    "y": 目标y坐标（如果是specific）
                }},
                "map_changes": [
                    {{
                        "x": x坐标,
                        "y": y坐标,
                        "terrain": "新地形类型"
                    }}
                ],
                "special_effects": ["reveal_map", "heal_full", "level_up"]
            }}
        }}
        """

        # 定义物品使用效果的JSON schema
        schema = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "events": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "item_consumed": {"type": "boolean"},
                "effects": {
                    "type": "object",
                    "properties": {
                        "stat_changes": {
                            "type": "object",
                            "properties": {
                                "hp": {"type": "integer"},
                                "mp": {"type": "integer"},
                                "experience": {"type": "integer"},
                                "max_hp": {"type": "integer"},
                                "max_mp": {"type": "integer"}
                            }
                        },
                        "teleport": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["random", "specific", "stairs"]},
                                "x": {"type": "integer"},
                                "y": {"type": "integer"}
                            }
                        },
                        "map_changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "terrain": {"type": "string"}
                                }
                            }
                        },
                        "special_effects": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["message", "events", "item_consumed", "effects"]
        }

        try:
            result = await self._async_generate_json(prompt, schema)
            logger.info(f"物品使用LLM响应: {result}")
            return result or {}
        except Exception as e:
            logger.error(f"处理物品使用失败: {e}")
            return {
                "message": f"使用{item.name}时发生了意外",
                "events": ["物品使用失败"],
                "item_consumed": False,
                "effects": {}
            }

    def _get_nearby_terrain(self, game_state: GameState, x: int, y: int, radius: int = 2) -> List[str]:
        """获取周围地形信息"""
        terrain_list = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = x + dx, y + dy
                if (0 <= nx < game_state.current_map.width and
                    0 <= ny < game_state.current_map.height):
                    tile = game_state.current_map.get_tile(nx, ny)
                    if tile:
                        terrain_list.append(f"({nx},{ny}):{tile.terrain.value}")
        return terrain_list

    def close(self):
        """关闭服务"""
        self.executor.shutdown(wait=True)


# 全局LLM服务实例
llm_service = LLMService()

__all__ = ["LLMService", "llm_service"]
