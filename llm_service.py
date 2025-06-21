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
from encoding_utils import encoding_converter
from prompt_manager import prompt_manager


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

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """
        健壮的JSON响应解析方法，处理各种编码和格式问题

        Args:
            text: 原始响应文本

        Returns:
            解析后的JSON字典，解析失败时返回空字典
        """
        if not text or not text.strip():
            logger.warning("Empty response text for JSON parsing")
            return {}

        # 清理文本
        cleaned_text = text.strip()

        # 移除BOM字符
        if cleaned_text.startswith('\ufeff'):
            cleaned_text = cleaned_text[1:]

        # 移除markdown代码块标记
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.startswith('```'):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]

        cleaned_text = cleaned_text.strip()

        # 尝试多种解析方法
        parse_attempts = [
            # 方法1：直接解析
            lambda: json.loads(cleaned_text),
            # 方法2：处理可能的列表响应
            lambda: self._handle_list_response(cleaned_text),
            # 方法3：使用编码转换器
            lambda: self._parse_with_encoding_converter(cleaned_text),
            # 方法4：修复常见JSON格式问题
            lambda: self._parse_with_json_fixes(cleaned_text),
        ]

        for i, parse_func in enumerate(parse_attempts, 1):
            try:
                result = parse_func()
                if isinstance(result, dict):
                    logger.debug(f"JSON parsing succeeded with method {i}")
                    return result
                elif isinstance(result, list) and result:
                    # 如果是列表，尝试返回第一个字典元素
                    for item in result:
                        if isinstance(item, dict):
                            logger.debug(f"JSON parsing succeeded with method {i} (extracted from list)")
                            return item
                    logger.warning(f"JSON parsing method {i} returned list without dict elements")
                else:
                    logger.warning(f"JSON parsing method {i} returned unexpected type: {type(result)}")
            except Exception as e:
                logger.debug(f"JSON parsing method {i} failed: {e}")
                continue

        # 所有方法都失败
        logger.error(f"All JSON parsing methods failed for text: {cleaned_text[:200]}...")
        return {}

    def _handle_list_response(self, text: str) -> Dict[str, Any]:
        """处理LLM返回列表而非字典的情况"""
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            # 返回列表中的第一个字典
            for item in parsed:
                if isinstance(item, dict):
                    return item
        elif isinstance(parsed, dict):
            return parsed
        return {}

    def _parse_with_encoding_converter(self, text: str) -> Dict[str, Any]:
        """使用编码转换器解析"""
        if encoding_converter.enabled:
            # 验证编码
            if not encoding_converter.validate_encoding(text):
                logger.warning("Invalid encoding detected in response text")
                return {}

        return json.loads(text)

    def _parse_with_json_fixes(self, text: str) -> Dict[str, Any]:
        """修复常见的JSON格式问题后解析"""
        # 修复常见问题
        fixed_text = text

        # 修复单引号
        fixed_text = fixed_text.replace("'", '"')

        # 修复尾随逗号
        import re
        fixed_text = re.sub(r',(\s*[}\]])', r'\1', fixed_text)

        # 修复未转义的换行符
        fixed_text = fixed_text.replace('\n', '\\n').replace('\r', '\\r')

        return json.loads(fixed_text)

    async def _async_generate(self, prompt: str, **kwargs) -> str:
        """异步生成内容"""
        loop = asyncio.get_event_loop()
        
        def _sync_generate():
            try:
                # 处理内容清理（如果启用）
                processed_prompt = prompt
                try:
                    from content_sanitizer import content_sanitizer
                    if content_sanitizer.enabled:
                        processed_prompt = content_sanitizer.sanitize_text(prompt)
                        if len(processed_prompt) != len(prompt):
                            logger.debug(f"Prompt sanitized: {len(prompt)} -> {len(processed_prompt)} chars")
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning(f"Content sanitization failed: {e}")

                generation_config = {}

                # 只有在启用生成参数时才添加temperature和top_p
                if config.llm.use_generation_params:
                    generation_config.update({
                        "temperature": config.llm.temperature,
                        "top_p": config.llm.top_p,
                    })

                # 如果设置了max_output_tokens，则添加到配置中
                if config.llm.max_output_tokens:
                    generation_config["max_output_tokens"] = config.llm.max_output_tokens

                # 合并用户提供的配置
                generation_config.update(kwargs.get("generation_config", {}))

                # 根据提供商调用不同的客户端
                if self.provider == LLMProvider.GEMINI:
                    response = self.client.single_turn(
                        model=config.llm.model_name,
                        text=processed_prompt,
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
                # 处理内容清理（如果启用）
                processed_prompt = prompt
                try:
                    from content_sanitizer import content_sanitizer
                    if content_sanitizer.enabled:
                        processed_prompt = content_sanitizer.sanitize_text(prompt)
                        if len(processed_prompt) != len(prompt):
                            logger.debug(f"JSON prompt sanitized: {len(prompt)} -> {len(processed_prompt)} chars")
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning(f"Content sanitization failed: {e}")

                generation_config = {}

                # 只有在启用生成参数时才添加temperature和top_p
                if config.llm.use_generation_params:
                    generation_config.update({
                        "temperature": config.llm.temperature,
                        "top_p": config.llm.top_p,
                    })

                # 如果设置了max_output_tokens，则添加到配置中
                if config.llm.max_output_tokens:
                    generation_config["max_output_tokens"] = config.llm.max_output_tokens

                # 合并用户提供的配置
                generation_config.update(kwargs.get("generation_config", {}))

                # 根据提供商调用不同的客户端
                if self.provider == LLMProvider.GEMINI:
                    response = self.client.single_turn_json(
                        model=config.llm.model_name,
                        text=processed_prompt,
                        schema=schema,
                        generation_config=generation_config
                    )
                    
                    # 提取生成的JSON
                    if response.get("candidates") and response["candidates"][0].get("content"):
                        parts = response["candidates"][0]["content"].get("parts", [])
                        if parts and parts[0].get("text"):
                            # 使用健壮的JSON解析方法
                            parsed_json = self._parse_json_response(parts[0]["text"])
                            if parsed_json:
                                return parsed_json

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
        # 使用PromptManager构建提示词
        prompt = prompt_manager.format_prompt(
            "monster_generation",
            player_level=int(challenge_rating * 2),  # 简单的等级转换
            difficulty="easy" if challenge_rating < 1.0 else "medium" if challenge_rating < 2.0 else "hard",
            context=context
        )

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
        # 使用PromptManager构建提示词
        map_context = prompt_manager.build_map_context(map_data)
        map_context["context"] = context

        prompt = prompt_manager.format_prompt("map_description", **map_context)
        return await self._async_generate(prompt)
    
    async def generate_quest(self, player_level: int = 1, context: str = "") -> Optional[Quest]:
        """生成任务"""
        # 使用PromptManager构建提示词
        prompt = prompt_manager.format_prompt(
            "quest_generation",
            player_level=player_level,
            context=context
        )

        # 获取对应的schema
        schema = prompt_manager.get_schema("quest_generation")

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

    async def generate_text(self, prompt: str) -> str:
        """生成文本（通用方法）"""
        return await self._async_generate(prompt)

    async def generate_complex_content(self, prompt: str, context_data: Optional[Dict[str, Any]] = None,
                                     schema: Optional[Dict] = None, **kwargs) -> Union[str, Dict[str, Any]]:
        """
        生成复杂内容，专门处理包含大量上下文信息的请求
        使用内容清理器确保在Ubuntu服务器上的兼容性

        Args:
            prompt: 基础提示词
            context_data: 上下文数据（地图、任务信息等）
            schema: JSON schema（如果需要JSON输出）
            **kwargs: 其他生成配置

        Returns:
            生成的内容（文本或JSON）
        """
        try:
            # 使用内容清理器创建安全的提示词
            from content_sanitizer import content_sanitizer
            if content_sanitizer.enabled:
                safe_prompt = content_sanitizer.create_safe_prompt(prompt, context_data)
                logger.debug(f"Complex content prompt sanitized: {len(prompt)} -> {len(safe_prompt)} chars")
            else:
                safe_prompt = prompt
                # 如果有上下文数据，简单地添加到提示词中
                if context_data:
                    import json
                    context_json = json.dumps(context_data, ensure_ascii=False, indent=2)
                    safe_prompt += f"\n\n上下文信息：\n{context_json}"

            # 根据是否需要JSON输出选择方法
            if schema:
                return await self._async_generate_json(safe_prompt, schema, **kwargs)
            else:
                return await self._async_generate(safe_prompt, **kwargs)

        except Exception as e:
            logger.error(f"Complex content generation failed: {e}")
            # 回退到基本方法
            if schema:
                return await self._async_generate_json(prompt, schema, **kwargs)
            else:
                return await self._async_generate(prompt, **kwargs)

    async def generate_item_on_pickup(self, game_state: GameState,
                                    pickup_context: str = "") -> Optional[Item]:
        """在拾取时生成物品"""
        # 使用PromptManager构建提示词
        player_context = prompt_manager.build_player_context(game_state.player)
        map_context = prompt_manager.build_map_context(game_state.current_map)

        # 合并所有上下文
        context = {**player_context, **map_context, "pickup_context": pickup_context}

        prompt = prompt_manager.format_prompt("item_pickup_generation", **context)
        schema = prompt_manager.get_schema("item_pickup_generation")

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
        # 使用PromptManager构建提示词
        player_context = prompt_manager.build_player_context(game_state.player)
        item_context = prompt_manager.build_item_context(item)

        # 构建地图状态信息
        map_info = {
            "name": game_state.current_map.name,
            "description": game_state.current_map.description,
            "depth": game_state.current_map.depth,
            "player_position": game_state.player.position,
            "nearby_terrain": self._get_nearby_terrain(game_state, game_state.player.position[0], game_state.player.position[1])
        }

        # 合并所有上下文
        context = {**player_context, **item_context, "map_info": map_info}

        prompt = prompt_manager.format_prompt("item_usage_effect", **context)

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

    def get_last_request_payload(self) -> Optional[Dict[str, Any]]:
        """获取最后一次发送给LLM的请求报文。

        注意：在并发请求的环境下，这个方法返回的报文可能不完全准确，
        因为它只保留了最后一次完成的请求的报文。
        在串行调用的场景下（例如测试脚本），这是可靠的。
        """
        if hasattr(self.client, 'last_request_payload'):
            # 返回一个深拷贝以防止外部修改
            import copy
            return copy.deepcopy(self.client.last_request_payload)
        return None

    def get_last_response_payload(self) -> Optional[Dict[str, Any]]:
        """获取最后一次LLM的响应报文。

        注意：在并发请求的环境下，这个方法返回的报文可能不完全准确，
        因为它只保留了最后一次完成的请求的响应。
        在串行调用的场景下（例如测试脚本），这是可靠的。
        """
        if hasattr(self.client, 'last_response_payload'):
            # 返回一个深拷贝以防止外部修改
            import copy
            return copy.deepcopy(self.client.last_response_payload)
        return None
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
