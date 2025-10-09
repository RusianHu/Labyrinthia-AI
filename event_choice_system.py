"""
Labyrinthia AI - 事件选择系统
类似galgame的选项框机制，用于管理游戏中的各种选择事件
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from dataclasses import dataclass

from data_models import (
    GameState, EventChoice, EventChoiceContext, MapTile, Monster, Quest
)
from llm_service import llm_service
from prompt_manager import prompt_manager
from config import config
from async_task_manager import async_task_manager, TaskType


logger = logging.getLogger(__name__)


class ChoiceEventType(Enum):
    """选择事件类型"""
    STORY_EVENT = "story_event"
    MYSTERY_EVENT = "mystery_event"
    COMBAT_EVENT = "combat_event"
    TREASURE_EVENT = "treasure_event"
    TRAP_EVENT = "trap_event"
    QUEST_COMPLETION = "quest_completion"
    MAP_TRANSITION = "map_transition"
    ITEM_USE = "item_use"
    NPC_INTERACTION = "npc_interaction"


@dataclass
class ChoiceResult:
    """选择结果"""
    success: bool = True
    message: str = ""
    events: List[str] = None
    map_updates: Dict[str, Any] = None
    player_updates: Dict[str, Any] = None
    quest_updates: Dict[str, Any] = None
    new_items: List[Dict[str, Any]] = None
    map_transition: Dict[str, Any] = None

    def __post_init__(self):
        if self.events is None:
            self.events = []
        if self.map_updates is None:
            self.map_updates = {}
        if self.player_updates is None:
            self.player_updates = {}
        if self.quest_updates is None:
            self.quest_updates = {}
        if self.new_items is None:
            self.new_items = []
        if self.map_transition is None:
            self.map_transition = {}


class EventChoiceSystem:
    """事件选择系统"""
    
    def __init__(self):
        self.active_contexts: Dict[str, EventChoiceContext] = {}
        self.choice_handlers: Dict[ChoiceEventType, Callable] = {}
        self.choice_history: List[Dict[str, Any]] = []

        # 注册默认处理器
        self._register_default_handlers()

        # 上下文过期时间（秒）
        self.context_expiry_time = 300  # 5分钟
    
    def _register_default_handlers(self):
        """注册默认的选择处理器"""
        self.choice_handlers[ChoiceEventType.STORY_EVENT] = self._handle_story_choice
        self.choice_handlers[ChoiceEventType.MYSTERY_EVENT] = self._handle_mystery_choice
        self.choice_handlers[ChoiceEventType.COMBAT_EVENT] = self._handle_combat_choice
        self.choice_handlers[ChoiceEventType.TREASURE_EVENT] = self._handle_treasure_choice
        self.choice_handlers[ChoiceEventType.TRAP_EVENT] = self._handle_trap_choice
        self.choice_handlers[ChoiceEventType.QUEST_COMPLETION] = self._handle_quest_completion_choice
        self.choice_handlers[ChoiceEventType.MAP_TRANSITION] = self._handle_map_transition_choice
        self.choice_handlers[ChoiceEventType.ITEM_USE] = self._handle_item_use_choice
        self.choice_handlers[ChoiceEventType.NPC_INTERACTION] = self._handle_npc_interaction_choice

    async def _call_llm_with_retry(
        self,
        llm_func: Callable,
        *args,
        max_retries: int = 2,
        timeout: float = 30.0,
        **kwargs
    ) -> Optional[Any]:
        """
        带重试机制的LLM调用

        Args:
            llm_func: LLM函数
            *args: 位置参数
            max_retries: 最大重试次数
            timeout: 超时时间（秒）
            **kwargs: 关键字参数

        Returns:
            LLM响应或None
        """
        for attempt in range(max_retries + 1):
            try:
                # 添加超时参数
                result = await llm_func(*args, timeout=timeout, **kwargs)

                if result:
                    if attempt > 0:
                        logger.info(f"LLM call succeeded after {attempt + 1} attempts")
                    return result
                else:
                    logger.warning(f"LLM returned empty response (attempt {attempt + 1}/{max_retries + 1})")

            except asyncio.TimeoutError:
                logger.warning(f"LLM call timed out after {timeout}s (attempt {attempt + 1}/{max_retries + 1})")

            except Exception as e:
                logger.error(f"LLM call error (attempt {attempt + 1}/{max_retries + 1}): {e}")

            # 如果不是最后一次尝试，等待后重试
            if attempt < max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))  # 递增等待时间

        logger.error(f"LLM call failed after {max_retries + 1} attempts")
        return None
    
    async def create_story_event_choice(self, game_state: GameState, tile: MapTile) -> EventChoiceContext:
        """创建故事事件选择"""
        event_data = tile.event_data or {}
        story_type = event_data.get("story_type", "general")

        # 获取当前活跃任务信息
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        quest_info = {}
        if active_quest:
            quest_info = {
                "quest_title": active_quest.title,
                "quest_description": active_quest.description,
                "quest_type": active_quest.quest_type,
                "quest_progress": active_quest.progress_percentage,
                "quest_objectives": active_quest.objectives,
                "quest_story_context": active_quest.story_context,
                "has_active_quest": True
            }
        else:
            quest_info = {
                "quest_title": "",
                "quest_description": "",
                "quest_type": "",
                "quest_progress": 0,
                "quest_objectives": [],
                "quest_story_context": "",
                "has_active_quest": False
            }

        # 构建LLM提示
        prompt = prompt_manager.format_prompt(
            "story_event_choices",
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            player_hp=game_state.player.stats.hp,
            player_max_hp=game_state.player.stats.max_hp,
            location_x=tile.x,
            location_y=tile.y,
            map_name=game_state.current_map.name,
            map_depth=game_state.current_map.depth,
            story_type=story_type,
            event_description=event_data.get("description", ""),
            **quest_info  # 展开任务信息
        )
        
        # 使用重试机制调用LLM
        llm_response = await self._call_llm_with_retry(
            llm_service._async_generate_json,
            prompt,
            max_retries=2,
            timeout=30.0
        )

        if llm_response:
            try:
                context = EventChoiceContext(
                    event_type=ChoiceEventType.STORY_EVENT.value,
                    title=llm_response.get("title", "神秘事件"),
                    description=llm_response.get("description", "你遇到了一个有趣的情况..."),
                    context_data={
                        "tile_position": (tile.x, tile.y),
                        "story_type": story_type,
                        "event_data": event_data
                    }
                )

                # 创建选择选项
                choices_data = llm_response.get("choices", [])
                for choice_data in choices_data:
                    choice = EventChoice(
                        text=choice_data.get("text", ""),
                        description=choice_data.get("description", ""),
                        consequences=choice_data.get("consequences", ""),
                        requirements=choice_data.get("requirements", {}),
                        is_available=self._check_choice_requirements(
                            game_state, choice_data.get("requirements", {})
                        )
                    )
                    context.choices.append(choice)

                return context

            except Exception as e:
                logger.error(f"Error parsing LLM response for story event: {e}")

        # 降级处理：创建默认选择
        logger.warning("Using fallback default story choice")
        return self._create_default_story_choice(game_state, tile)
    
    async def create_quest_completion_choice(self, game_state: GameState, completed_quest: Quest) -> EventChoiceContext:
        """创建任务完成选择"""
        # 构建LLM提示
        prompt = prompt_manager.format_prompt(
            "quest_completion_choices",
            quest_title=completed_quest.title,
            quest_description=completed_quest.description,
            quest_type=completed_quest.quest_type,
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            experience_reward=completed_quest.experience_reward,
            story_context=completed_quest.story_context,
            current_map=game_state.current_map.name,
            map_depth=game_state.current_map.depth
        )
        
        # 使用重试机制调用LLM
        llm_response = await self._call_llm_with_retry(
            llm_service._async_generate_json,
            prompt,
            max_retries=2,
            timeout=30.0
        )

        if llm_response:
            try:
                context = EventChoiceContext(
                    event_type=ChoiceEventType.QUEST_COMPLETION.value,
                    title=llm_response.get("title", f"任务完成：{completed_quest.title}"),
                    description=llm_response.get("description", "恭喜完成任务！"),
                    context_data={
                        "completed_quest_id": completed_quest.id,
                        "quest_data": completed_quest.to_dict()
                    }
                )

                # 创建选择选项
                choices_data = llm_response.get("choices", [])
                for choice_data in choices_data:
                    choice = EventChoice(
                        text=choice_data.get("text", ""),
                        description=choice_data.get("description", ""),
                        consequences=choice_data.get("consequences", ""),
                        requirements=choice_data.get("requirements", {}),
                        is_available=self._check_choice_requirements(
                            game_state, choice_data.get("requirements", {})
                        )
                    )

                    # 添加额外的选择元数据
                    if "leads_to_new_quest" in choice_data:
                        choice.requirements["leads_to_new_quest"] = choice_data["leads_to_new_quest"]
                    if "leads_to_map_transition" in choice_data:
                        choice.requirements["leads_to_map_transition"] = choice_data["leads_to_map_transition"]
                    if "quest_theme" in choice_data:
                        choice.requirements["quest_theme"] = choice_data["quest_theme"]
                    if "map_theme" in choice_data:
                        choice.requirements["map_theme"] = choice_data["map_theme"]

                    context.choices.append(choice)

                return context

            except Exception as e:
                logger.error(f"Error parsing LLM response for quest completion: {e}")

        # 降级处理：创建默认任务完成选择
        logger.warning("Using fallback default quest completion choice")
        return self._create_default_quest_completion_choice(game_state, completed_quest)
    
    async def process_choice(self, game_state: GameState, context_id: str, choice_id: str) -> ChoiceResult:
        """处理玩家的选择"""
        # 首先检查游戏状态中的待处理上下文
        context = None
        if hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context:
            if game_state.pending_choice_context.id == context_id:
                context = game_state.pending_choice_context

        # 如果游戏状态中没有，再检查活跃上下文
        if not context:
            context = self.active_contexts.get(context_id)

        if not context:
            logger.warning(f"Choice context not found: {context_id}")
            return ChoiceResult(success=False, message="选择上下文不存在")

        # 找到选择的选项
        selected_choice = None
        for choice in context.choices:
            if choice.id == choice_id:
                selected_choice = choice
                break

        if not selected_choice:
            logger.warning(f"Choice option not found: {choice_id} in context {context_id}")
            return ChoiceResult(success=False, message="选择选项不存在")

        if not selected_choice.is_available:
            return ChoiceResult(success=False, message="该选项当前不可用")

        # 记录选择历史
        self.choice_history.append({
            "context_id": context_id,
            "choice_id": choice_id,
            "choice_text": selected_choice.text,
            "timestamp": context.created_at.isoformat()
        })

        # 根据事件类型处理选择
        try:
            event_type = ChoiceEventType(context.event_type)
        except ValueError:
            logger.error(f"Invalid event type: {context.event_type}")
            return ChoiceResult(success=False, message="无效的事件类型")

        handler = self.choice_handlers.get(event_type)

        if handler:
            try:
                result = await handler(game_state, context, selected_choice)

                # 清理已处理的上下文
                if context_id in self.active_contexts:
                    del self.active_contexts[context_id]

                # 清理游戏状态中的待处理上下文
                if hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context:
                    if game_state.pending_choice_context.id == context_id:
                        game_state.pending_choice_context = None

                logger.info(f"Successfully processed choice {choice_id} for context {context_id}")
                return result

            except Exception as e:
                logger.error(f"Error processing choice: {e}")
                return ChoiceResult(success=False, message=f"处理选择时发生错误: {e}")
        else:
            logger.error(f"No handler found for event type: {event_type}")
            return ChoiceResult(success=False, message="未找到对应的选择处理器")
    
    def _check_choice_requirements(self, game_state: GameState, requirements: Dict[str, Any]) -> bool:
        """检查选择要求是否满足"""
        if not requirements:
            return True
        
        player = game_state.player
        
        # 检查等级要求
        if "min_level" in requirements:
            if player.stats.level < requirements["min_level"]:
                return False
        
        # 检查生命值要求
        if "min_hp" in requirements:
            if player.stats.hp < requirements["min_hp"]:
                return False
        
        # 检查物品要求
        if "required_items" in requirements:
            required_items = requirements["required_items"]
            player_items = [item.name for item in player.inventory]
            for required_item in required_items:
                if required_item not in player_items:
                    return False
        
        # 检查属性要求
        if "min_stats" in requirements:
            min_stats = requirements["min_stats"]
            for stat_name, min_value in min_stats.items():
                if hasattr(player.stats, stat_name):
                    if getattr(player.stats, stat_name) < min_value:
                        return False
        
        return True

    def _create_default_story_choice(self, game_state: GameState, tile: MapTile) -> EventChoiceContext:
        """创建默认故事选择"""
        context = EventChoiceContext(
            event_type=ChoiceEventType.STORY_EVENT.value,
            title="神秘事件",
            description="你遇到了一个有趣的情况...",
            context_data={
                "tile_position": (tile.x, tile.y),
                "story_type": "general",
                "event_data": tile.event_data or {}
            }
        )

        # 添加默认选择
        context.choices.extend([
            EventChoice(
                text="仔细调查",
                description="花时间仔细调查这个现象",
                consequences="可能发现有用的信息或物品"
            ),
            EventChoice(
                text="谨慎离开",
                description="保持警惕并离开这里",
                consequences="安全但可能错过机会"
            )
        ])

        return context

    def _create_default_quest_completion_choice(self, game_state: GameState, completed_quest: Quest) -> EventChoiceContext:
        """创建默认任务完成选择"""
        context = EventChoiceContext(
            event_type=ChoiceEventType.QUEST_COMPLETION.value,
            title=f"任务完成：{completed_quest.title}",
            description=f"恭喜完成任务！获得了 {completed_quest.experience_reward} 经验值。",
            context_data={
                "completed_quest_id": completed_quest.id,
                "quest_data": completed_quest.to_dict()
            }
        )

        # 添加默认选择
        context.choices.extend([
            EventChoice(
                text="继续探索",
                description="在当前区域继续探索",
                consequences="可能发现更多秘密"
            ),
            EventChoice(
                text="仔细搜索",
                description="仔细搜索当前区域的隐藏物品",
                consequences="可能发现有价值的物品或线索"
            ),
            EventChoice(
                text="休息整理",
                description="休息并整理装备",
                consequences="恢复状态，准备下一步行动"
            ),
            EventChoice(
                text="回味成就",
                description="回味刚刚完成的任务成就",
                consequences="获得满足感，为下一步做好准备"
            )
        ])

        return context

    # 选择处理器方法
    async def _handle_story_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理故事选择"""
        # 获取事件瓦片位置
        tile_position = context.context_data.get("tile_position", (0, 0))

        # 获取当前活跃任务信息
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        quest_info = ""
        quest_id = ""
        if active_quest:
            quest_info = f"任务：{active_quest.title} - {active_quest.description}"
            quest_id = active_quest.id

        # 构建LLM提示来处理选择结果
        prompt = prompt_manager.format_prompt(
            "process_story_choice",
            choice_text=choice.text,
            choice_description=choice.description,
            event_context=context.description,
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            player_hp=game_state.player.stats.hp,
            player_max_hp=game_state.player.stats.max_hp,
            current_map=game_state.current_map.name,
            map_depth=game_state.current_map.depth,
            map_width=game_state.current_map.width,
            map_height=game_state.current_map.height,
            tile_position=tile_position,
            quest_info=quest_info,
            quest_id=quest_id
        )

        try:
            # 使用LLM处理选择结果
            llm_response = await llm_service._async_generate_json(prompt)

            # 调试日志
            from config import config
            if config.game.show_llm_debug:
                logger.info(f"Story choice LLM prompt: {prompt}")
                logger.info(f"Story choice LLM response: {llm_response}")

            if llm_response:
                result = ChoiceResult(
                    success=True,
                    message=llm_response.get("message", ""),
                    events=llm_response.get("events", []),
                    map_updates=llm_response.get("map_updates", {}),
                    player_updates=llm_response.get("player_updates", {}),
                    quest_updates=llm_response.get("quest_updates", {}),
                    new_items=llm_response.get("new_items", []),
                    map_transition=llm_response.get("map_transition", {})
                )

                # 调试日志：显示将要应用的更新
                if config.game.show_llm_debug:
                    logger.info(f"Applying choice result: {result}")

                # 标记事件瓦片已触发（在应用其他更新之前）
                event_tile = game_state.current_map.get_tile(*tile_position)
                if event_tile and event_tile.has_event:
                    event_tile.event_triggered = True
                    logger.info(f"Marked story event as triggered at {tile_position}")

                # 应用更新到游戏状态
                await self._apply_choice_result(game_state, result)

                # 处理地图切换（如果LLM建议）
                if result.map_transition and result.map_transition.get("should_transition", False):
                    await self._handle_story_event_map_transition(game_state, result.map_transition)

                return result
            else:
                logger.warning("LLM returned empty response for story choice")

        except Exception as e:
            logger.error(f"Error handling story choice: {e}")

        # 降级处理
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "你的选择产生了一些影响..."]
        )

    async def _handle_quest_completion_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理任务完成选择"""
        completed_quest_id = context.context_data.get("completed_quest_id")

        # 从选择数据中提取额外信息
        choice_requirements = choice.requirements or {}
        leads_to_new_quest = choice_requirements.get("leads_to_new_quest", False)
        leads_to_map_transition = choice_requirements.get("leads_to_map_transition", False)
        quest_theme = choice_requirements.get("quest_theme", "")
        map_theme = choice_requirements.get("map_theme", "")

        # 构建LLM提示来处理任务完成选择
        prompt = prompt_manager.format_prompt(
            "process_quest_completion_choice",
            choice_text=choice.text,
            choice_description=choice.description,
            leads_to_new_quest=leads_to_new_quest,
            leads_to_map_transition=leads_to_map_transition,
            quest_theme=quest_theme,
            map_theme=map_theme,
            completed_quest_data=context.context_data.get("quest_data", {}),
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            current_map=game_state.current_map.name,
            map_depth=game_state.current_map.depth
        )

        try:
            # 使用LLM处理任务完成选择
            llm_response = await llm_service._async_generate_json(prompt)

            if llm_response:
                result = ChoiceResult(
                    success=True,
                    message=llm_response.get("message", ""),
                    events=llm_response.get("events", []),
                    quest_updates=llm_response.get("quest_updates", {}),
                    player_updates=llm_response.get("player_updates", {}),
                    map_transition=llm_response.get("map_transition", {})
                )

                # 应用更新到游戏状态
                await self._apply_choice_result(game_state, result)

                # 处理新任务创建（如果LLM建议）
                if llm_response.get("new_quest_data"):
                    await self._create_new_quest_from_choice(game_state, llm_response["new_quest_data"], choice)

                # 处理地图切换（如果LLM建议）
                if result.map_transition and result.map_transition.get("should_transition", False):
                    await self._handle_quest_completion_map_transition(game_state, result.map_transition)

                return result

        except Exception as e:
            logger.error(f"Error handling quest completion choice: {e}")

        # 降级处理
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "你的选择为未来的冒险做好了准备..."]
        )

    async def _handle_story_event_map_transition(self, game_state: GameState, transition_data: Dict[str, Any]):
        """处理故事事件中的地图切换"""
        try:
            from game_engine import game_engine

            transition_type = transition_data.get("transition_type", "new_area")
            target_depth = transition_data.get("target_depth")

            if transition_type == "new_area":
                # 生成新区域
                if target_depth is None:
                    # 故事事件的地图切换可以是同层的不同区域
                    target_depth = game_state.current_map.depth

                # 确保楼层数合理
                max_floors = config.game.max_quest_floors
                if target_depth > max_floors:
                    target_depth = max_floors
                elif target_depth < 1:
                    target_depth = 1

                # 获取活跃任务上下文
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                quest_context = active_quest.to_dict() if active_quest else None

                # 生成新地图
                from content_generator import content_generator
                new_map = await content_generator.generate_dungeon_map(
                    width=config.game.default_map_size[0],
                    height=config.game.default_map_size[1],
                    depth=target_depth,
                    theme=transition_data.get("theme", f"神秘区域（第{target_depth}层）"),
                    quest_context=quest_context
                )

                # 确保新地图的深度正确设置
                new_map.depth = target_depth

                # 执行地图切换
                await self._execute_map_transition(game_state, new_map)

                # 添加切换消息
                transition_message = transition_data.get("message", f"你被传送到了{new_map.name}（第{target_depth}层）")
                game_state.pending_events.append(transition_message)

                logger.info(f"Story event map transition completed: {new_map.name} (Depth: {target_depth})")

            elif transition_type == "existing_area":
                # 切换到已存在的区域（如果有的话）
                # 这里可以实现切换到之前访问过的地图的逻辑
                pass

        except Exception as e:
            logger.error(f"Error handling story event map transition: {e}")
            # 如果地图切换失败，添加错误消息但不中断游戏
            game_state.pending_events.append("地图切换遇到了一些问题，但你的冒险将继续...")

    async def _handle_quest_completion_map_transition(self, game_state: GameState, transition_data: Dict[str, Any]):
        """处理任务完成后的地图切换"""
        try:
            from game_engine import game_engine

            transition_type = transition_data.get("transition_type", "new_area")
            target_depth = transition_data.get("target_depth")

            if transition_type == "new_area":
                # 生成新区域
                if target_depth is None:
                    target_depth = game_state.current_map.depth + 1

                # 确保楼层数合理
                max_floors = config.game.max_quest_floors
                if target_depth > max_floors:
                    target_depth = max_floors
                elif target_depth < 1:
                    target_depth = 1

                # 获取活跃任务上下文
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                quest_context = active_quest.to_dict() if active_quest else None

                # 生成新地图
                from content_generator import content_generator
                new_map = await content_generator.generate_dungeon_map(
                    width=config.game.default_map_size[0],
                    height=config.game.default_map_size[1],
                    depth=target_depth,
                    theme=transition_data.get("theme", f"地下城第{target_depth}层"),
                    quest_context=quest_context
                )

                # 确保新地图的深度正确设置
                new_map.depth = target_depth

                # 执行地图切换
                await self._execute_map_transition(game_state, new_map)

                # 添加切换消息
                transition_message = transition_data.get("message", f"进入了{new_map.name}（第{target_depth}层）")
                game_state.pending_events.append(transition_message)

                logger.info(f"Quest completion map transition completed: {new_map.name} (Depth: {target_depth})")

            elif transition_type == "existing_area":
                # 切换到已存在的区域（如果有的话）
                # 这里可以实现切换到之前访问过的地图的逻辑
                pass

        except Exception as e:
            logger.error(f"Error handling quest completion map transition: {e}")
            # 如果地图切换失败，添加错误消息但不中断游戏
            game_state.pending_events.append("地图切换遇到了一些问题，但你的冒险将继续...")

    async def _execute_map_transition(self, game_state: GameState, new_map: 'GameMap'):
        """执行地图切换的核心逻辑"""
        # 清除旧地图上的角色标记
        old_tile = game_state.current_map.get_tile(*game_state.player.position)
        if old_tile:
            old_tile.character_id = None

        for monster in game_state.monsters:
            if monster.position:
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = None

        # 更新当前地图
        game_state.current_map = new_map

        # 设置玩家位置
        from content_generator import content_generator
        spawn_positions = content_generator.get_spawn_positions(new_map, 1)
        if spawn_positions:
            game_state.player.position = spawn_positions[0]
            tile = new_map.get_tile(*game_state.player.position)
            if tile:
                tile.character_id = game_state.player.id
                tile.is_explored = True
                tile.is_visible = True

        # 清空旧怪物并生成新的
        game_state.monsters.clear()

        # 生成新怪物
        from game_engine import game_engine
        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level, "normal"
        )

        # 生成任务专属怪物
        quest_monsters = await game_engine._generate_quest_monsters(game_state, new_map)
        monsters.extend(quest_monsters)

        # 放置怪物
        monster_positions = content_generator.get_spawn_positions(new_map, len(monsters))
        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = new_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)

    # 其他事件类型的处理器（简化实现）
    async def _handle_mystery_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理神秘事件选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "神秘的力量回应了你的选择..."]
        )

    async def _handle_combat_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理战斗选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "战斗的结果取决于你的选择..."]
        )

    async def _handle_treasure_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理宝藏选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "宝藏的秘密被你发现了..."]
        )

    async def _handle_trap_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理陷阱选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "你的选择决定了陷阱的结果..."]
        )

    async def _handle_map_transition_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理地图切换选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "你准备前往新的区域..."]
        )

    async def _handle_item_use_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理物品使用选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "物品的效果开始显现..."]
        )

    async def _handle_npc_interaction_choice(self, game_state: GameState, context: EventChoiceContext, choice: EventChoice) -> ChoiceResult:
        """处理NPC交互选择"""
        return ChoiceResult(
            success=True,
            message=f"你选择了：{choice.text}",
            events=[choice.consequences or "NPC对你的选择做出了回应..."]
        )

    async def _apply_choice_result(self, game_state: GameState, result: ChoiceResult):
        """应用选择结果到游戏状态"""
        try:
            # 应用玩家更新
            if result.player_updates:
                player = game_state.player
                stats_updates = result.player_updates.get("stats", {})
                for stat_name, value in stats_updates.items():
                    if hasattr(player.stats, stat_name):
                        setattr(player.stats, stat_name, value)

                # 更新物品栏
                if "add_items" in result.player_updates:
                    for item_data in result.player_updates["add_items"]:
                        if isinstance(item_data, dict):
                            from data_models import Item
                            item = Item(
                                name=item_data.get("name", "神秘物品"),
                                description=item_data.get("description", "一个神秘的物品"),
                                item_type=item_data.get("item_type", "misc"),
                                rarity=item_data.get("rarity", "common")
                            )
                            # 设置其他可能的物品属性
                            if "usage_description" in item_data:
                                item.usage_description = item_data["usage_description"]
                            if "properties" in item_data:
                                item.properties = item_data["properties"]

                            player.inventory.append(item)
                            logger.info(f"Added item {item.name} to player inventory")

                if "remove_items" in result.player_updates:
                    items_to_remove = result.player_updates["remove_items"]
                    player.inventory = [item for item in player.inventory
                                     if item.name not in items_to_remove]

            # 应用地图更新
            if result.map_updates:
                current_map = game_state.current_map
                tile_updates = result.map_updates.get("tiles", {})

                for tile_key, tile_data in tile_updates.items():
                    try:
                        # 解析坐标
                        if "," in tile_key:
                            x, y = map(int, tile_key.split(","))
                        else:
                            logger.warning(f"Invalid tile key format: {tile_key}")
                            continue

                        # 获取或创建瓦片
                        tile = current_map.get_tile(x, y)
                        if not tile:
                            # 如果瓦片不存在，创建新的
                            from data_models import MapTile, TerrainType
                            tile = MapTile(x=x, y=y)
                            current_map.set_tile(x, y, tile)

                        # 记录瓦片原本是否有事件
                        had_event = tile.has_event
                        was_triggered = tile.event_triggered

                        # 更新瓦片属性
                        for attr_name, value in tile_data.items():
                            if attr_name == "terrain":
                                # 处理地形类型更新
                                from data_models import TerrainType
                                if hasattr(TerrainType, value.upper()):
                                    tile.terrain = TerrainType(value.lower())
                                else:
                                    logger.warning(f"Unknown terrain type: {value}")
                            elif attr_name == "items" and isinstance(value, list):
                                # 处理物品添加
                                for item_data in value:
                                    if isinstance(item_data, dict):
                                        from data_models import Item
                                        item = Item(
                                            name=item_data.get("name", "神秘物品"),
                                            description=item_data.get("description", "一个神秘的物品"),
                                            item_type=item_data.get("item_type", "misc"),
                                            rarity=item_data.get("rarity", "common")
                                        )
                                        tile.items.append(item)
                            elif attr_name == "monster" and isinstance(value, dict):
                                # 处理怪物添加/更新
                                await self._handle_monster_update(game_state, x, y, value)
                            elif hasattr(tile, attr_name):
                                setattr(tile, attr_name, value)
                            else:
                                logger.debug(f"Unknown tile attribute: {attr_name}")

                        # 如果瓦片原本有事件且已触发，确保更新后仍然保持触发状态
                        # 除非LLM明确设置了event_triggered为False（表示重置事件）
                        if had_event and was_triggered and "event_triggered" not in tile_data:
                            tile.event_triggered = True
                            logger.debug(f"Preserved event_triggered=True for tile at ({x}, {y})")

                        logger.info(f"Updated tile at ({x}, {y}) with data: {tile_data}")

                    except Exception as e:
                        logger.error(f"Error updating tile {tile_key}: {e}")

            # 应用任务更新
            if result.quest_updates:
                for quest in game_state.quests:
                    quest_update = result.quest_updates.get(quest.id)
                    if quest_update:
                        for attr_name, value in quest_update.items():
                            if hasattr(quest, attr_name):
                                setattr(quest, attr_name, value)

            # 添加事件到待显示列表
            if result.events:
                game_state.pending_events.extend(result.events)

        except Exception as e:
            logger.error(f"Error applying choice result: {e}")

    async def _handle_monster_update(self, game_state: GameState, x: int, y: int, monster_data: Dict[str, Any]):
        """处理怪物添加/更新"""
        try:
            from data_models import Monster, Stats, CharacterClass

            action = monster_data.get("action", "add")  # add, update, remove

            if action == "remove":
                # 移除怪物
                tile = game_state.current_map.get_tile(x, y)
                if tile and tile.character_id:
                    # 从怪物列表中移除
                    game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]
                    # 清除瓦片上的角色引用
                    tile.character_id = None
                    logger.info(f"Removed monster from tile ({x}, {y})")

            elif action == "update":
                # 更新现有怪物
                tile = game_state.current_map.get_tile(x, y)
                if tile and tile.character_id:
                    monster = next((m for m in game_state.monsters if m.id == tile.character_id), None)
                    if monster:
                        # 更新怪物属性
                        if "name" in monster_data:
                            monster.name = monster_data["name"]
                        if "description" in monster_data:
                            monster.description = monster_data["description"]
                        if "stats" in monster_data:
                            stats_data = monster_data["stats"]
                            if "hp" in stats_data:
                                monster.stats.hp = min(stats_data["hp"], monster.stats.max_hp)
                            if "max_hp" in stats_data:
                                monster.stats.max_hp = stats_data["max_hp"]
                                monster.stats.hp = min(monster.stats.hp, monster.stats.max_hp)
                        if "challenge_rating" in monster_data:
                            monster.challenge_rating = monster_data["challenge_rating"]
                        if "behavior" in monster_data:
                            monster.behavior = monster_data["behavior"]
                        if "is_boss" in monster_data:
                            monster.is_boss = monster_data["is_boss"]
                        logger.info(f"Updated monster {monster.name} at ({x}, {y})")

            elif action == "add":
                # 添加新怪物
                tile = game_state.current_map.get_tile(x, y)
                if tile:
                    # 如果该位置已有角色，先移除
                    if tile.character_id:
                        game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]

                    # 创建新怪物
                    monster = Monster()
                    monster.name = monster_data.get("name", "神秘生物")
                    monster.description = monster_data.get("description", "一个神秘的生物")
                    monster.character_class = CharacterClass.FIGHTER  # 默认职业
                    monster.position = (x, y)
                    monster.challenge_rating = monster_data.get("challenge_rating", 1.0)
                    monster.behavior = monster_data.get("behavior", "aggressive")
                    monster.is_boss = monster_data.get("is_boss", False)
                    monster.quest_monster_id = monster_data.get("quest_monster_id")
                    monster.attack_range = monster_data.get("attack_range", 1)

                    # 设置怪物属性
                    if "stats" in monster_data:
                        stats_data = monster_data["stats"]
                        monster.stats.max_hp = stats_data.get("max_hp", 20)
                        monster.stats.hp = stats_data.get("hp", monster.stats.max_hp)
                        monster.stats.max_mp = stats_data.get("max_mp", 10)
                        monster.stats.mp = stats_data.get("mp", monster.stats.max_mp)
                        monster.stats.ac = stats_data.get("ac", 12)
                        monster.stats.level = stats_data.get("level", 1)

                    # 添加到游戏状态
                    game_state.monsters.append(monster)
                    tile.character_id = monster.id

                    logger.info(f"Added new monster {monster.name} at ({x}, {y})")

        except Exception as e:
            logger.error(f"Error handling monster update: {e}")

    async def _create_new_quest_from_choice(self, game_state: GameState, quest_data: Dict[str, Any], choice: EventChoice):
        """基于玩家选择创建新任务"""
        try:
            # 导入必要的模块（避免循环导入）
            from content_generator import content_generator
            from data_models import Quest

            # 创建新任务对象
            new_quest = Quest()
            new_quest.title = quest_data.get("title", "新的冒险")
            new_quest.description = quest_data.get("description", "一个新的挑战等待着你...")
            new_quest.quest_type = quest_data.get("type", "exploration")
            new_quest.experience_reward = quest_data.get("experience_reward", 500)
            new_quest.objectives = quest_data.get("objectives", ["完成新的挑战"])
            new_quest.completed_objectives = [False] * len(new_quest.objectives)
            new_quest.is_active = True
            new_quest.is_completed = False
            new_quest.progress_percentage = 0.0
            new_quest.story_context = quest_data.get("story_context", "")

            # 添加选择上下文到任务故事背景中
            choice_context = f"基于你的选择'{choice.text}'，{choice.description}"
            if new_quest.story_context:
                new_quest.story_context = f"{new_quest.story_context}\n\n{choice_context}"
            else:
                new_quest.story_context = choice_context

            # 如果LLM没有提供完整的任务数据，使用任务生成器补充
            if not quest_data.get("title") or not quest_data.get("description"):
                # 使用现有的任务生成系统，传递选择上下文
                context_for_generation = f"玩家选择了：{choice.text} - {choice.description}"
                generated_quests = await content_generator.generate_quest_chain(
                    game_state.player.stats.level, 1, context_for_generation
                )

                if generated_quests:
                    generated_quest = generated_quests[0]
                    # 合并LLM提供的数据和生成的数据
                    new_quest.title = quest_data.get("title", generated_quest.title)
                    new_quest.description = quest_data.get("description", generated_quest.description)
                    new_quest.quest_type = quest_data.get("type", generated_quest.quest_type)
                    new_quest.experience_reward = quest_data.get("experience_reward", generated_quest.experience_reward)
                    new_quest.objectives = quest_data.get("objectives", generated_quest.objectives)
                    new_quest.completed_objectives = [False] * len(new_quest.objectives)
                    new_quest.special_events = generated_quest.special_events
                    new_quest.special_monsters = generated_quest.special_monsters
                    new_quest.target_floors = generated_quest.target_floors
                    new_quest.map_themes = generated_quest.map_themes

            # 添加到游戏状态
            game_state.quests.append(new_quest)

            # 添加新任务通知
            game_state.pending_events.append(f"新任务：{new_quest.title}")
            game_state.pending_events.append("你的冒险将继续...")

            # 清理新任务生成标志（如果存在）
            if hasattr(game_state, 'pending_new_quest_generation'):
                game_state.pending_new_quest_generation = False

            logger.info(f"Created new quest from choice: {new_quest.title}")

        except Exception as e:
            logger.error(f"Error creating new quest from choice: {e}")

    async def _create_new_quest(self, game_state: GameState, quest_data: Dict[str, Any]):
        """创建新任务（通用方法）"""
        try:
            # 导入必要的模块（避免循环导入）
            from content_generator import content_generator
            from data_models import Quest

            # 创建新任务对象
            new_quest = Quest()
            new_quest.title = quest_data.get("title", "新的冒险")
            new_quest.description = quest_data.get("description", "一个新的挑战等待着你...")
            new_quest.quest_type = quest_data.get("type", "exploration")
            new_quest.experience_reward = quest_data.get("experience_reward", 500)
            new_quest.objectives = quest_data.get("objectives", ["完成新的挑战"])
            new_quest.completed_objectives = [False] * len(new_quest.objectives)
            new_quest.is_active = True
            new_quest.is_completed = False
            new_quest.progress_percentage = 0.0
            new_quest.story_context = quest_data.get("story_context", "")

            # 如果LLM没有提供完整的任务数据，使用任务生成器补充
            if not quest_data.get("title") or not quest_data.get("description"):
                # 使用现有的任务生成系统
                generated_quests = await content_generator.generate_quest_chain(
                    game_state.player.stats.level, 1
                )

                if generated_quests:
                    generated_quest = generated_quests[0]
                    # 合并LLM提供的数据和生成的数据
                    new_quest.title = quest_data.get("title", generated_quest.title)
                    new_quest.description = quest_data.get("description", generated_quest.description)
                    new_quest.quest_type = quest_data.get("type", generated_quest.quest_type)
                    new_quest.experience_reward = quest_data.get("experience_reward", generated_quest.experience_reward)
                    new_quest.objectives = quest_data.get("objectives", generated_quest.objectives)
                    new_quest.completed_objectives = [False] * len(new_quest.objectives)
                    new_quest.special_events = generated_quest.special_events
                    new_quest.special_monsters = generated_quest.special_monsters
                    new_quest.target_floors = generated_quest.target_floors
                    new_quest.map_themes = generated_quest.map_themes

            # 添加到游戏状态
            game_state.quests.append(new_quest)

            logger.info(f"Created new quest: {new_quest.title}")

        except Exception as e:
            logger.error(f"Error creating new quest: {e}")

    def cleanup_expired_contexts(self):
        """清理过期的上下文"""
        from datetime import datetime, timedelta

        current_time = datetime.now()
        expired_contexts = []

        for context_id, context in self.active_contexts.items():
            if current_time - context.created_at > timedelta(seconds=self.context_expiry_time):
                expired_contexts.append(context_id)

        for context_id in expired_contexts:
            del self.active_contexts[context_id]
            logger.info(f"Cleaned up expired context: {context_id}")

        return len(expired_contexts)

    def get_context_info(self) -> Dict[str, Any]:
        """获取上下文管理信息"""
        return {
            "active_contexts_count": len(self.active_contexts),
            "choice_history_count": len(self.choice_history),
            "context_expiry_time": self.context_expiry_time
        }


# 创建全局实例
event_choice_system = EventChoiceSystem()
