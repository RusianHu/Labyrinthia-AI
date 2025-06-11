"""
Labyrinthia AI - 游戏引擎
Game engine for the Labyrinthia AI game
"""

import asyncio
import random
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

from config import config
from data_models import (
    GameState, Character, Monster, GameMap, Quest, Item, MapTile,
    TerrainType, CharacterClass, Stats, Ability
)
from content_generator import content_generator
from llm_service import llm_service
from data_manager import data_manager
from progress_manager import progress_manager, ProgressEventType, ProgressContext
from item_effect_processor import item_effect_processor


logger = logging.getLogger(__name__)


class GameEngine:
    """游戏引擎类"""
    
    def __init__(self):
        self.active_games: Dict[str, GameState] = {}
        self.auto_save_tasks: Dict[str, asyncio.Task] = {}
    
    async def create_new_game(self, player_name: str, character_class: str = "fighter") -> GameState:
        """创建新游戏"""
        game_state = GameState()
        
        # 创建玩家角色
        game_state.player = await self._create_player_character(player_name, character_class)
        
        # 生成初始任务
        initial_quests = await content_generator.generate_quest_chain(
            game_state.player.stats.level, 1
        )
        game_state.quests.extend(initial_quests)

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        # 生成初始地图（考虑任务上下文）
        game_state.current_map = await content_generator.generate_dungeon_map(
            width=config.game.default_map_size[0],
            height=config.game.default_map_size[1],
            depth=1,
            theme="新手地下城",
            quest_context=quest_context
        )
        
        # 设置玩家初始位置
        spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
        if spawn_positions:
            game_state.player.position = spawn_positions[0]
            # 在地图上标记玩家位置
            tile = game_state.current_map.get_tile(*game_state.player.position)
            if tile:
                tile.character_id = game_state.player.id
                tile.is_explored = True
                tile.is_visible = True
        
        # 生成初始怪物
        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level, "easy"
        )
        
        # 为怪物分配位置
        monster_positions = content_generator.get_spawn_positions(
            game_state.current_map, len(monsters)
        )
        
        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = game_state.current_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)
        


        # 生成开场叙述
        try:
            opening_narrative = await llm_service.generate_opening_narrative(game_state)
            game_state.last_narrative = opening_narrative
        except Exception as e:
            logger.error(f"Failed to generate opening narrative: {e}")
            game_state.last_narrative = f"欢迎来到 {game_state.current_map.name}！你的冒险即将开始..."

        # 保存游戏状态
        await self._save_game_async(game_state)

        # 添加到活跃游戏列表
        self.active_games[game_state.id] = game_state

        # 启动自动保存
        self._start_auto_save(game_state.id)

        logger.info(f"New game created: {game_state.id}")
        return game_state
    
    async def _create_player_character(self, name: str, character_class: str) -> Character:
        """创建玩家角色"""
        player = Character()
        player.name = name
        
        # 设置职业
        try:
            player.character_class = CharacterClass(character_class.lower())
        except ValueError:
            player.character_class = CharacterClass.FIGHTER
        
        # 根据职业设置初始属性
        class_configs = {
            CharacterClass.FIGHTER: {
                "abilities": {"strength": 15, "constitution": 14, "dexterity": 12},
                "hp": 120, "mp": 30
            },
            CharacterClass.WIZARD: {
                "abilities": {"intelligence": 15, "wisdom": 14, "constitution": 12},
                "hp": 80, "mp": 100
            },
            CharacterClass.ROGUE: {
                "abilities": {"dexterity": 15, "intelligence": 14, "charisma": 12},
                "hp": 100, "mp": 50
            },
            CharacterClass.CLERIC: {
                "abilities": {"wisdom": 15, "constitution": 14, "strength": 12},
                "hp": 110, "mp": 80
            }
        }
        
        class_config = class_configs.get(player.character_class, class_configs[CharacterClass.FIGHTER])
        
        # 设置能力值
        for ability, value in class_config["abilities"].items():
            setattr(player.abilities, ability, value)
        
        # 设置属性
        player.stats.hp = class_config["hp"]
        player.stats.max_hp = class_config["hp"]
        player.stats.mp = class_config["mp"]
        player.stats.max_mp = class_config["mp"]
        player.stats.level = config.game.starting_level
        
        # 使用LLM生成角色描述
        description_prompt = f"""
        为一个名叫{name}的{character_class}角色生成一个简短的背景描述。
        这是一个DnD风格的角色，刚开始冒险。
        描述应该包含外貌、性格和简单的背景故事。
        """
        
        try:
            player.description = await llm_service._async_generate(description_prompt)
        except Exception as e:
            logger.error(f"Failed to generate character description: {e}")
            player.description = f"一个勇敢的{character_class}，准备踏上冒险之旅。"
        
        return player
    
    async def load_game(self, save_id: str) -> Optional[GameState]:
        """加载游戏"""
        game_state = data_manager.load_game_state(save_id)
        if game_state:
            self.active_games[game_state.id] = game_state
            self._start_auto_save(game_state.id)

            # 生成重新进入游戏的叙述
            try:
                return_narrative = await llm_service.generate_return_narrative(game_state)
                game_state.last_narrative = return_narrative
            except Exception as e:
                logger.error(f"Failed to generate return narrative: {e}")
                game_state.last_narrative = f"你重新回到了 {game_state.current_map.name}，继续你的冒险..."

            logger.info(f"Game loaded: {game_state.id}")
        return game_state
    
    async def process_player_action(self, game_id: str, action: str,
                                  parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """处理玩家行动"""
        if game_id not in self.active_games:
            return {"success": False, "message": "游戏未找到"}

        game_state = self.active_games[game_id]
        parameters = parameters or {}

        result = {"success": True, "message": "", "events": []}

        try:
            if action == "move":
                result = await self._handle_move(game_state, parameters)
            elif action == "attack":
                result = await self._handle_attack(game_state, parameters)
            elif action == "use_item":
                result = await self._handle_use_item(game_state, parameters)
            elif action == "cast_spell":
                result = await self._handle_cast_spell(game_state, parameters)
            elif action == "interact":
                result = await self._handle_interact(game_state, parameters)
            elif action == "rest":
                result = await self._handle_rest(game_state)
            else:
                result = {"success": False, "message": f"未知行动: {action}"}

            # 增加回合数
            if result["success"]:
                game_state.turn_count += 1
                game_state.game_time += 1  # 每回合1分钟

                # 处理怪物行动（如果游戏没有结束）
                monster_events_occurred = False
                if not game_state.is_game_over:
                    monster_events_occurred = await self._process_monster_turns(game_state)

                # 添加待处理事件到结果中
                if hasattr(game_state, 'pending_events') and game_state.pending_events:
                    if "events" not in result:
                        result["events"] = []
                    result["events"].extend(game_state.pending_events)
                    game_state.pending_events.clear()

                # 检查游戏是否结束
                if game_state.is_game_over:
                    result["game_over"] = True
                    result["game_over_reason"] = game_state.game_over_reason

                # 判断是否需要LLM交互
                should_generate_narrative = self._should_generate_narrative(action, result)
                llm_interaction_required = should_generate_narrative or monster_events_occurred

                # 添加LLM交互标识到结果中
                result["llm_interaction_required"] = llm_interaction_required

                # 只有特殊行动或有事件发生时才生成叙述文本
                if should_generate_narrative and not game_state.is_game_over:
                    narrative = await llm_service.generate_narrative(game_state, action)
                    result["narrative"] = narrative

        except Exception as e:
            logger.error(f"Error processing action {action}: {e}")
            result = {"success": False, "message": f"处理行动时发生错误: {str(e)}"}

        return result

    def _should_generate_narrative(self, action: str, result: Dict[str, Any]) -> bool:
        """判断是否应该生成叙述文本"""
        # 普通移动且没有事件发生时不生成叙述
        if action == "move":
            events = result.get("events", [])
            # 检查是否只是楼梯提示事件（不需要LLM交互）
            if len(events) == 1:
                event_text = events[0]
                # 楼梯事件只是提示，不需要LLM交互
                if ("楼梯" in event_text and ("下一层" in event_text or "上一层" in event_text)):
                    return False
            # 只有当移动触发了真正需要LLM处理的事件时才生成叙述
            return len(events) > 0

        # 其他行动都生成叙述
        return True

    async def _handle_move(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理移动行动"""
        direction = parameters.get("direction", "")
        
        # 方向映射
        direction_map = {
            "north": (0, -1), "south": (0, 1),
            "east": (1, 0), "west": (-1, 0),
            "northeast": (1, -1), "northwest": (-1, -1),
            "southeast": (1, 1), "southwest": (-1, 1)
        }
        
        if direction not in direction_map:
            return {"success": False, "message": "无效的移动方向"}
        
        dx, dy = direction_map[direction]
        current_x, current_y = game_state.player.position
        new_x, new_y = current_x + dx, current_y + dy
        
        # 检查边界
        if (new_x < 0 or new_x >= game_state.current_map.width or
            new_y < 0 or new_y >= game_state.current_map.height):
            return {"success": False, "message": "无法移动到地图边界外"}
        
        # 检查目标瓦片
        target_tile = game_state.current_map.get_tile(new_x, new_y)
        if not target_tile:
            return {"success": False, "message": "目标位置无效"}
        
        # 检查地形
        if target_tile.terrain == TerrainType.WALL:
            return {"success": False, "message": "无法穿过墙壁"}

        # 检查是否有其他角色
        if target_tile.character_id and target_tile.character_id != game_state.player.id:
            # 检查是否是怪物，如果是则提示攻击
            monster = None
            for m in game_state.monsters:
                if m.id == target_tile.character_id:
                    monster = m
                    break
            if monster:
                return {"success": False, "message": f"该位置有 {monster.name}，请使用攻击命令"}
            else:
                return {"success": False, "message": "该位置已被占据"}
        
        # 执行移动
        old_tile = game_state.current_map.get_tile(current_x, current_y)
        if old_tile:
            old_tile.character_id = None
        
        target_tile.character_id = game_state.player.id
        target_tile.is_explored = True
        target_tile.is_visible = True
        game_state.player.position = (new_x, new_y)
        
        # 更新周围瓦片的可见性
        self._update_visibility(game_state, new_x, new_y)

        # 检查特殊地形
        events = []
        if target_tile.terrain == TerrainType.TRAP:
            events.append(await self._trigger_trap(game_state))
        elif target_tile.terrain == TerrainType.TREASURE:
            events.append(await self._find_treasure(game_state))
        elif target_tile.terrain == TerrainType.STAIRS_DOWN:
            # 不自动切换地图，而是设置待切换状态
            game_state.pending_map_transition = "stairs_down"
            events.append("你发现了通往下一层的楼梯。你可以选择进入下一层。")
        elif target_tile.terrain == TerrainType.STAIRS_UP:
            game_state.pending_map_transition = "stairs_up"
            events.append("你发现了通往上一层的楼梯。你可以选择返回上一层。")

        # 检查瓦片事件
        if target_tile.has_event and not target_tile.event_triggered:
            event_result = await self._trigger_tile_event(game_state, target_tile)
            if event_result:
                events.append(event_result)
                target_tile.event_triggered = True
        
        return {
            "success": True,
            "message": f"移动到 ({new_x}, {new_y})",
            "events": events,
            "new_position": (new_x, new_y)
        }
    
    def _update_visibility(self, game_state: GameState, center_x: int, center_y: int, radius: int = 2):
        """更新可见性"""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = center_x + dx, center_y + dy
                if (0 <= x < game_state.current_map.width and 
                    0 <= y < game_state.current_map.height):
                    tile = game_state.current_map.get_tile(x, y)
                    if tile:
                        tile.is_visible = True
                        if abs(dx) + abs(dy) <= 1:  # 相邻瓦片标记为已探索
                            tile.is_explored = True
    
    async def _handle_attack(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理攻击行动"""
        target_id = parameters.get("target_id", "")

        # 查找目标怪物
        target_monster = None
        for monster in game_state.monsters:
            if monster.id == target_id:
                target_monster = monster
                break

        if not target_monster:
            return {"success": False, "message": "目标未找到"}

        # 检查距离和视线
        player_x, player_y = game_state.player.position
        monster_x, monster_y = target_monster.position

        # 检查攻击距离（包括对角线）
        dx = abs(player_x - monster_x)
        dy = abs(player_y - monster_y)
        max_distance = max(dx, dy)  # 切比雪夫距离，允许对角线攻击

        if max_distance > 1:
            return {"success": False, "message": "目标距离太远，无法攻击"}

        # 检查视线（简单实现：检查是否有墙壁阻挡）
        if not self._has_line_of_sight(game_state.current_map, player_x, player_y, monster_x, monster_y):
            return {"success": False, "message": "视线被阻挡，无法攻击"}

        # 计算伤害
        damage = self._calculate_damage(game_state.player, target_monster)
        target_monster.stats.hp -= damage

        events = [f"对 {target_monster.name} 造成了 {damage} 点伤害"]

        # 检查怪物是否死亡
        if target_monster.stats.hp <= 0:
            events.append(f"{target_monster.name} 被击败了！")

            # 获得经验
            exp_gain = int(target_monster.challenge_rating * 100)
            game_state.player.stats.experience += exp_gain
            events.append(f"获得了 {exp_gain} 点经验")

            # 检查升级
            if self._check_level_up(game_state.player):
                events.append("恭喜升级！")

            # 移除怪物
            game_state.monsters.remove(target_monster)

            # 清除地图上的怪物标记
            tile = game_state.current_map.get_tile(monster_x, monster_y)
            if tile:
                tile.character_id = None

            # 触发战斗胜利进度事件
            await self._trigger_progress_event(
                game_state, ProgressEventType.COMBAT_VICTORY,
                {"monster_name": target_monster.name, "challenge_rating": target_monster.challenge_rating}
            )

        return {
            "success": True,
            "message": f"攻击了 {target_monster.name}",
            "events": events,
            "damage": damage
        }
    
    def _calculate_damage(self, attacker: Character, defender: Character) -> int:
        """计算伤害"""
        base_damage = 10 + attacker.abilities.get_modifier("strength")
        
        # 添加随机性
        damage = random.randint(max(1, base_damage - 3), base_damage + 3)
        
        # 护甲减免
        armor_reduction = max(0, defender.stats.ac - 10)
        damage = max(1, damage - armor_reduction)
        
        return damage
    
    def _check_level_up(self, character: Character) -> bool:
        """检查是否升级"""
        required_exp = character.stats.level * 1000
        if character.stats.experience >= required_exp:
            character.stats.level += 1
            character.stats.max_hp += 10
            character.stats.hp = character.stats.max_hp
            character.stats.max_mp += 5
            character.stats.mp = character.stats.max_mp
            return True
        return False

    def _has_line_of_sight(self, game_map: "GameMap", x1: int, y1: int, x2: int, y2: int) -> bool:
        """检查两点之间是否有视线（简单实现）"""
        # 对于相邻格子，直接返回True
        if abs(x2 - x1) <= 1 and abs(y2 - y1) <= 1:
            return True

        # 使用简单的直线算法检查路径上是否有墙壁
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)

        x, y = x1, y1
        x_inc = 1 if x1 < x2 else -1
        y_inc = 1 if y1 < y2 else -1

        error = dx - dy

        while x != x2 or y != y2:
            # 检查当前位置是否有墙壁（跳过起点和终点）
            if (x != x1 or y != y1) and (x != x2 or y != y2):
                tile = game_map.get_tile(x, y)
                if tile and tile.terrain == TerrainType.WALL:
                    return False

            error2 = 2 * error
            if error2 > -dy:
                error -= dy
                x += x_inc
            if error2 < dx:
                error += dx
                y += y_inc

        return True
    
    async def _handle_use_item(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理使用物品行动"""
        item_id = parameters.get("item_id", "")

        # 查找物品
        item = None
        for inv_item in game_state.player.inventory:
            if inv_item.id == item_id:
                item = inv_item
                break

        if not item:
            return {"success": False, "message": "物品未找到"}

        try:
            # 使用LLM处理物品使用效果
            llm_response = await llm_service.process_item_usage(game_state, item)

            # 使用效果处理器处理LLM返回的结果
            effect_result = item_effect_processor.process_llm_response(
                llm_response, game_state, item
            )

            # 处理位置变化（传送效果）
            if effect_result.position_change:
                new_x, new_y = effect_result.position_change
                old_tile = game_state.current_map.get_tile(*game_state.player.position)
                if old_tile:
                    old_tile.character_id = None

                new_tile = game_state.current_map.get_tile(new_x, new_y)
                if new_tile:
                    new_tile.character_id = game_state.player.id
                    new_tile.is_explored = True
                    new_tile.is_visible = True
                    game_state.player.position = (new_x, new_y)
                    self._update_visibility(game_state, new_x, new_y)
                    effect_result.events.append(f"传送到了位置 ({new_x}, {new_y})")

            # 移除消耗的物品
            if effect_result.item_consumed:
                game_state.player.inventory.remove(item)

            return {
                "success": effect_result.success,
                "message": effect_result.message,
                "events": effect_result.events,
                "llm_interaction_required": True  # 物品使用总是需要LLM交互
            }

        except Exception as e:
            logger.error(f"处理物品使用时出错: {e}")
            return {
                "success": False,
                "message": f"使用{item.name}时发生错误",
                "events": [f"物品使用失败: {str(e)}"]
            }

    async def _handle_cast_spell(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理施法行动"""
        spell_id = parameters.get("spell_id", "")
        target_id = parameters.get("target_id", "")

        # 查找法术
        spell = None
        for player_spell in game_state.player.spells:
            if player_spell.id == spell_id:
                spell = player_spell
                break

        if not spell:
            return {"success": False, "message": "法术未找到"}

        # 检查法力值
        mp_cost = spell.level * 10
        if game_state.player.stats.mp < mp_cost:
            return {"success": False, "message": "法力值不足"}

        # 消耗法力值
        game_state.player.stats.mp -= mp_cost

        events = [f"施放了 {spell.name}"]

        # 根据法术类型处理效果
        if spell.damage and target_id:
            # 攻击法术
            target_monster = None
            for monster in game_state.monsters:
                if monster.id == target_id:
                    target_monster = monster
                    break

            if target_monster:
                damage = random.randint(spell.level * 5, spell.level * 10)
                target_monster.stats.hp -= damage
                events.append(f"对 {target_monster.name} 造成了 {damage} 点魔法伤害")

                if target_monster.stats.hp <= 0:
                    events.append(f"{target_monster.name} 被击败了！")
                    game_state.monsters.remove(target_monster)

        return {
            "success": True,
            "message": f"施放了 {spell.name}",
            "events": events
        }

    async def _handle_interact(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理交互行动"""
        x, y = game_state.player.position
        tile = game_state.current_map.get_tile(x, y)

        if not tile:
            return {"success": False, "message": "无法在此位置交互"}

        events = []

        # 检查地形交互
        if tile.terrain == TerrainType.DOOR:
            events.append("打开了门")
            tile.terrain = TerrainType.FLOOR
        elif tile.terrain == TerrainType.TREASURE:
            # 使用LLM生成宝藏物品
            pickup_context = f"玩家在{game_state.current_map.name}的宝藏箱中发现了物品"
            treasure_item = await llm_service.generate_item_on_pickup(game_state, pickup_context)

            if treasure_item:
                game_state.player.inventory.append(treasure_item)
                events.append(f"从宝藏中获得了 {treasure_item.name}！")
                events.append(treasure_item.description)
            else:
                events.append("宝藏箱是空的...")

            tile.terrain = TerrainType.FLOOR

        elif tile.items:
            # 拾取地图上的物品
            items_to_remove = []
            for item in tile.items:
                # 检查是否已经被拾取过
                if item.id not in tile.items_collected:
                    # 如果物品不是LLM生成的，使用LLM重新生成
                    if not item.llm_generated:
                        pickup_context = f"玩家在{game_state.current_map.name}的地面上发现了{item.name}"
                        new_item = await llm_service.generate_item_on_pickup(game_state, pickup_context)
                        if new_item:
                            game_state.player.inventory.append(new_item)
                            events.append(f"拾取了 {new_item.name}")
                            events.append(new_item.description)
                        else:
                            # 如果LLM生成失败，使用原物品
                            game_state.player.inventory.append(item)
                            events.append(f"拾取了 {item.name}")
                    else:
                        # 直接拾取LLM生成的物品
                        game_state.player.inventory.append(item)
                        events.append(f"拾取了 {item.name}")
                        events.append(item.description)

                    # 标记为已拾取
                    tile.items_collected.append(item.id)
                    items_to_remove.append(item)

            # 移除已拾取的物品
            for item in items_to_remove:
                tile.items.remove(item)

        if not events:
            events.append("这里没有可以交互的东西")

        return {
            "success": True,
            "message": "进行了交互",
            "events": events,
            "llm_interaction_required": len(events) > 1  # 如果有物品拾取则需要LLM交互
        }

    async def transition_map(self, game_state: GameState, transition_type: str) -> Dict[str, Any]:
        """手动切换地图"""
        if not game_state.pending_map_transition:
            return {
                "success": False,
                "message": "当前位置无法进行地图切换"
            }

        if transition_type != game_state.pending_map_transition:
            return {
                "success": False,
                "message": "切换类型不匹配"
            }

        events = []

        if transition_type == "stairs_down":
            events.append(await self._descend_stairs(game_state))
        elif transition_type == "stairs_up":
            events.append(await self._ascend_stairs(game_state))

        # 清除待切换状态
        game_state.pending_map_transition = None

        return {
            "success": True,
            "message": "成功切换地图",
            "events": events
        }

    async def _handle_rest(self, game_state: GameState) -> Dict[str, Any]:
        """处理休息行动"""
        player = game_state.player

        # 恢复生命值和法力值
        hp_restored = min(player.stats.max_hp - player.stats.hp, player.stats.max_hp // 4)
        mp_restored = min(player.stats.max_mp - player.stats.mp, player.stats.max_mp // 2)

        player.stats.hp += hp_restored
        player.stats.mp += mp_restored

        events = []
        if hp_restored > 0:
            events.append(f"恢复了 {hp_restored} 点生命值")
        if mp_restored > 0:
            events.append(f"恢复了 {mp_restored} 点法力值")

        return {
            "success": True,
            "message": "休息了一会儿",
            "events": events
        }

    async def _trigger_trap(self, game_state: GameState) -> str:
        """触发陷阱"""
        damage = random.randint(5, 15)
        game_state.player.stats.hp -= damage

        # 检查玩家是否死亡
        if game_state.player.stats.hp <= 0:
            game_state.is_game_over = True
            game_state.game_over_reason = "被陷阱杀死"
            return f"触发了陷阱！受到了 {damage} 点伤害！你被陷阱杀死了！"

        return f"触发了陷阱！受到了 {damage} 点伤害"

    async def _trigger_tile_event(self, game_state: GameState, tile: MapTile) -> str:
        """触发瓦片事件"""
        try:
            if tile.event_type == "combat":
                return await self._handle_combat_event(game_state, tile)
            elif tile.event_type == "treasure":
                return await self._handle_treasure_event(game_state, tile)
            elif tile.event_type == "story":
                return await self._handle_story_event(game_state, tile)
            elif tile.event_type == "trap":
                return await self._handle_trap_event(game_state, tile)
            elif tile.event_type == "mystery":
                return await self._handle_mystery_event(game_state, tile)
            else:
                return "发现了一些有趣的东西..."
        except Exception as e:
            logger.error(f"Error triggering tile event: {e}")
            return "发生了意外的事情..."

    async def _handle_combat_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理战斗事件"""
        event_data = tile.event_data
        monster_count = event_data.get("monster_count", 1)
        difficulty = event_data.get("difficulty", "medium")

        # 生成怪物
        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level, difficulty
        )

        # 限制怪物数量
        monsters = monsters[:monster_count]

        # 将怪物添加到游戏状态
        for monster in monsters:
            # 在附近找位置放置怪物
            spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
            if spawn_positions:
                monster.position = spawn_positions[0]
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = monster.id
                game_state.monsters.append(monster)

        return f"遭遇了 {len(monsters)} 只怪物！战斗开始！"

    async def _handle_treasure_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理宝藏事件"""
        event_data = tile.event_data
        treasure_type = event_data.get("treasure_type", "gold")
        value = event_data.get("value", 100)

        result_message = ""

        if treasure_type == "gold":
            # 添加金币逻辑（这里简化处理）
            result_message = f"发现了 {value} 金币！"
        elif treasure_type == "item":
            # 生成随机物品
            items = await content_generator.generate_random_items(1, game_state.player.stats.level)
            if items:
                game_state.player.inventory.extend(items)
                result_message = f"发现了 {items[0].name}！"
        elif treasure_type == "magic_item":
            # 生成魔法物品
            items = await content_generator.generate_random_items(1, game_state.player.stats.level)
            if items:
                items[0].rarity = "rare"  # 设为稀有
                game_state.player.inventory.extend(items)
                result_message = f"发现了稀有物品 {items[0].name}！"
        else:
            result_message = "发现了一些有价值的东西！"

        # 触发宝藏发现进度事件
        await self._trigger_progress_event(
            game_state, ProgressEventType.TREASURE_FOUND,
            {"treasure_type": treasure_type, "value": value}
        )

        return result_message

    async def _handle_story_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理故事事件"""
        event_data = tile.event_data
        story_type = event_data.get("story_type", "discovery")

        # 检查是否是任务专属事件
        quest_event_id = event_data.get("quest_event_id")
        is_quest_event = quest_event_id is not None

        if is_quest_event:
            # 处理任务专属事件
            event_name = event_data.get("name", "任务事件")
            event_description = event_data.get("description", "")
            progress_value = event_data.get("progress_value", 0.0)
            is_mandatory = event_data.get("is_mandatory", True)

            # 使用更详细的提示生成任务相关的故事内容
            prompt = f"""
            为玩家生成一个任务相关的故事事件。

            事件信息：
            - 事件名称：{event_name}
            - 事件描述：{event_description}
            - 是否必须：{is_mandatory}

            玩家当前位置：({tile.x}, {tile.y})
            玩家等级：{game_state.player.stats.level}
            地图：{game_state.current_map.name}

            请生成一个与任务相关的生动故事描述（100-150字），体现事件的重要性。
            """

            try:
                story_text = await llm_service.generate_text(prompt)
                result_message = story_text or f"你发现了重要的线索：{event_name}"
            except Exception as e:
                logger.error(f"Error generating quest story event: {e}")
                result_message = f"你发现了重要的线索：{event_name}"

            # 触发任务专属事件进度（使用更高的进度值）
            await self._trigger_progress_event(
                game_state, ProgressEventType.STORY_EVENT,
                {
                    "story_type": "quest_event",
                    "quest_event_id": quest_event_id,
                    "progress_value": progress_value,
                    "location": (tile.x, tile.y)
                }
            )

        else:
            # 处理普通故事事件
            prompt = f"""
            为玩家生成一个{story_type}类型的故事事件。
            玩家当前位置：({tile.x}, {tile.y})
            玩家等级：{game_state.player.stats.level}
            地图：{game_state.current_map.name}

            请生成一个简短但有趣的故事描述（50-100字）。
            """

            try:
                story_text = await llm_service.generate_text(prompt)
                result_message = story_text or "你发现了一些古老的痕迹..."
            except Exception as e:
                logger.error(f"Error generating story event: {e}")
                result_message = "你发现了一些古老的痕迹..."

            # 触发普通故事事件进度
            await self._trigger_progress_event(
                game_state, ProgressEventType.STORY_EVENT,
                {"story_type": story_type, "location": (tile.x, tile.y)}
            )

        return result_message

    async def _handle_trap_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理陷阱事件"""
        event_data = tile.event_data
        trap_type = event_data.get("trap_type", "damage")
        damage = event_data.get("damage", 15)

        if trap_type == "damage":
            game_state.player.stats.hp -= damage

            # 检查玩家是否死亡
            if game_state.player.stats.hp <= 0:
                game_state.is_game_over = True
                game_state.game_over_reason = "被陷阱杀死"
                return f"触发了陷阱！受到了 {damage} 点伤害！你被陷阱杀死了！"

            return f"触发了陷阱！受到了 {damage} 点伤害！"
        elif trap_type == "debuff":
            # 简化处理，减少移动速度
            return "触发了减速陷阱！移动变得困难！"
        elif trap_type == "teleport":
            # 随机传送到其他位置
            spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
            if spawn_positions:
                old_tile = game_state.current_map.get_tile(*game_state.player.position)
                if old_tile:
                    old_tile.character_id = None

                new_pos = spawn_positions[0]
                game_state.player.position = new_pos
                new_tile = game_state.current_map.get_tile(*new_pos)
                if new_tile:
                    new_tile.character_id = game_state.player.id
                    new_tile.is_explored = True
                    new_tile.is_visible = True

                return f"触发了传送陷阱！被传送到了 ({new_pos[0]}, {new_pos[1]})！"

        return "触发了一个神秘的陷阱！"

    async def _handle_mystery_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理神秘事件"""
        event_data = tile.event_data
        mystery_type = event_data.get("mystery_type", "puzzle")

        # 使用LLM生成神秘事件
        prompt = f"""
        为玩家生成一个{mystery_type}类型的神秘事件。
        玩家当前位置：({tile.x}, {tile.y})
        玩家等级：{game_state.player.stats.level}

        请生成一个简短的神秘事件描述和可能的选择（50-100字）。
        """

        try:
            mystery_text = await llm_service.generate_text(prompt)
            return mystery_text or "你遇到了一个神秘的现象..."
        except Exception as e:
            logger.error(f"Error generating mystery event: {e}")
            return "你遇到了一个神秘的现象..."

    async def _find_treasure(self, game_state: GameState) -> str:
        """发现宝藏"""
        treasure_items = await content_generator.generate_random_items(
            count=random.randint(1, 2),
            item_level=game_state.player.stats.level
        )

        for item in treasure_items:
            game_state.player.inventory.append(item)

        item_names = [item.name for item in treasure_items]
        return f"发现了宝藏：{', '.join(item_names)}"

    async def _descend_stairs(self, game_state: GameState) -> str:
        """下楼梯"""
        # 生成新的地图层
        new_depth = game_state.current_map.depth + 1

        # 开发阶段：限制为2层
        if new_depth > 2:
            return "你已经到达了地下城的最深处！"

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        new_map = await content_generator.generate_dungeon_map(
            width=game_state.current_map.width,
            height=game_state.current_map.height,
            depth=new_depth,
            theme=f"地下城第{new_depth}层",
            quest_context=quest_context
        )

        # 更新游戏状态
        game_state.current_map = new_map

        # 设置玩家位置到新地图的上楼梯处
        spawn_positions = content_generator.get_spawn_positions(new_map, 1)
        if spawn_positions:
            game_state.player.position = spawn_positions[0]
            tile = new_map.get_tile(*game_state.player.position)
            if tile:
                tile.character_id = game_state.player.id
                tile.is_explored = True
                tile.is_visible = True

        # 生成新的怪物
        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level, "medium"
        )

        monster_positions = content_generator.get_spawn_positions(new_map, len(monsters))
        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = new_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)

        # 使用新的进程管理器更新任务进度
        await self._trigger_progress_event(
            game_state, ProgressEventType.MAP_TRANSITION, new_depth
        )

        return f"进入了{new_map.name}"

    async def _ascend_stairs(self, game_state: GameState) -> str:
        """上楼梯"""
        new_depth = game_state.current_map.depth - 1

        if new_depth < 1:
            return "你已经回到了地面！"

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        # 这里可以实现返回上一层的逻辑
        # 简化实现：重新生成上一层
        new_map = await content_generator.generate_dungeon_map(
            width=game_state.current_map.width,
            height=game_state.current_map.height,
            depth=new_depth,
            theme=f"地下城第{new_depth}层",
            quest_context=quest_context
        )

        game_state.current_map = new_map

        # 设置玩家位置
        spawn_positions = content_generator.get_spawn_positions(new_map, 1)
        if spawn_positions:
            game_state.player.position = spawn_positions[0]
            tile = new_map.get_tile(*game_state.player.position)
            if tile:
                tile.character_id = game_state.player.id
                tile.is_explored = True
                tile.is_visible = True

        # 使用新的进程管理器更新任务进度
        await self._trigger_progress_event(
            game_state, ProgressEventType.MAP_TRANSITION, new_depth
        )

        return f"返回到了{new_map.name}"

    async def _trigger_progress_event(self, game_state: GameState, event_type: ProgressEventType, context_data: Any = None):
        """触发进度事件"""
        try:
            # 创建进度上下文
            progress_context = ProgressContext(
                event_type=event_type,
                game_state=game_state,
                context_data=context_data
            )

            # 使用进程管理器处理事件
            result = await progress_manager.process_event(progress_context)

            if result.get("success"):
                logger.info(f"Progress event processed: {event_type.value}, increment: {result.get('progress_increment', 0):.1f}%")

                # 如果有叙述更新，添加到待显示事件
                if result.get("story_update"):
                    game_state.pending_events.append(result["story_update"])
            else:
                logger.warning(f"Failed to process progress event: {result.get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error triggering progress event {event_type.value}: {e}")

    async def _update_quest_progress(self, game_state: GameState, event_type: str, context: Any = None):
        """更新任务进度 - 保留兼容性的包装方法"""
        # 将旧的事件类型映射到新的枚举
        event_mapping = {
            "map_transition": ProgressEventType.MAP_TRANSITION,
            "combat_victory": ProgressEventType.COMBAT_VICTORY,
            "treasure_found": ProgressEventType.TREASURE_FOUND,
            "story_event": ProgressEventType.STORY_EVENT,
            "exploration": ProgressEventType.EXPLORATION
        }

        progress_event_type = event_mapping.get(event_type, ProgressEventType.CUSTOM_EVENT)
        await self._trigger_progress_event(game_state, progress_event_type, context)

    async def _process_monster_turns(self, game_state: GameState) -> bool:
        """处理怪物回合，返回是否有怪物事件发生"""
        combat_events = []

        for monster in game_state.monsters[:]:  # 使用切片避免修改列表时的问题
            if not monster.stats.is_alive():
                continue

            # 简单的AI：如果玩家在攻击范围内就攻击，否则移动靠近
            player_x, player_y = game_state.player.position
            monster_x, monster_y = monster.position
            distance = abs(player_x - monster_x) + abs(monster_y - monster_y)

            if distance == 1:
                # 攻击玩家
                damage = self._calculate_damage(monster, game_state.player)
                game_state.player.stats.hp -= damage
                combat_events.append(f"{monster.name} 攻击了你，造成 {damage} 点伤害！")
                logger.info(f"{monster.name} 攻击玩家造成 {damage} 点伤害")

                # 检查玩家是否死亡
                if game_state.player.stats.hp <= 0:
                    combat_events.append("你被击败了！游戏结束！")
                    game_state.is_game_over = True
                    game_state.game_over_reason = "被怪物击败"
                    break  # 玩家死亡，停止处理其他怪物

            elif distance <= 5:
                # 移动靠近玩家
                await self._move_monster_towards_player(game_state, monster)

        # 将战斗事件添加到游戏状态中，以便前端显示
        if combat_events:
            if not hasattr(game_state, 'pending_events'):
                game_state.pending_events = []
            game_state.pending_events.extend(combat_events)

        # 返回是否有怪物事件发生（主要是攻击事件）
        return len(combat_events) > 0
    
    async def _move_monster_towards_player(self, game_state: GameState, monster: Monster):
        """移动怪物靠近玩家"""
        player_x, player_y = game_state.player.position
        monster_x, monster_y = monster.position
        
        # 简单的寻路：朝玩家方向移动一格
        dx = 0 if player_x == monster_x else (1 if player_x > monster_x else -1)
        dy = 0 if player_y == monster_y else (1 if player_y > monster_y else -1)
        
        new_x, new_y = monster_x + dx, monster_y + dy
        
        # 检查新位置是否有效
        target_tile = game_state.current_map.get_tile(new_x, new_y)
        if (target_tile and target_tile.terrain != TerrainType.WALL and 
            not target_tile.character_id):
            
            # 移动怪物
            old_tile = game_state.current_map.get_tile(monster_x, monster_y)
            if old_tile:
                old_tile.character_id = None
            
            target_tile.character_id = monster.id
            monster.position = (new_x, new_y)
    
    async def _save_game_async(self, game_state: GameState):
        """异步保存游戏"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, data_manager.save_game_state, game_state)
    
    def _start_auto_save(self, game_id: str):
        """启动自动保存"""
        async def auto_save_loop():
            while game_id in self.active_games:
                await asyncio.sleep(config.game.auto_save_interval)
                if game_id in self.active_games:
                    await self._save_game_async(self.active_games[game_id])
        
        task = asyncio.create_task(auto_save_loop())
        self.auto_save_tasks[game_id] = task
    
    def close_game(self, game_id: str):
        """关闭游戏"""
        if game_id in self.active_games:
            # 保存游戏状态
            data_manager.save_game_state(self.active_games[game_id])
            del self.active_games[game_id]
        
        # 取消自动保存任务
        if game_id in self.auto_save_tasks:
            self.auto_save_tasks[game_id].cancel()
            del self.auto_save_tasks[game_id]


# 全局游戏引擎实例
game_engine = GameEngine()

__all__ = ["GameEngine", "game_engine"]
