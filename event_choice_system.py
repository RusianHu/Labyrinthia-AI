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
from game_state_modifier import game_state_modifier
from llm_context_manager import llm_context_manager, ContextEntryType
from trap_schema import trap_validator


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
        if active_quest:
            quest_info = f"""- 任务标题：{active_quest.title}
- 任务描述：{active_quest.description}
- 任务类型：{active_quest.quest_type}
- 任务进度：{active_quest.progress_percentage:.1f}%
- 任务目标：{active_quest.objectives}
- 故事背景：{active_quest.story_context}"""
        else:
            quest_info = "- 当前无活跃任务"

        # 获取玩家六维属性
        abilities = game_state.player.abilities

        # 构建LLM提示
        prompt = prompt_manager.format_prompt(
            "story_event_choices",
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            player_hp=game_state.player.stats.hp,
            player_max_hp=game_state.player.stats.max_hp,
            player_str=abilities.strength,
            player_dex=abilities.dexterity,
            player_con=abilities.constitution,
            player_int=abilities.intelligence,
            player_wis=abilities.wisdom,
            player_cha=abilities.charisma,
            location_x=tile.x,
            location_y=tile.y,
            map_name=game_state.current_map.name,
            map_depth=game_state.current_map.depth,
            story_type=story_type,
            quest_info=quest_info,
            event_description=event_data.get("description", "")
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
        # 【修复】处理 completed_quest 可能是字典或对象的情况
        quest_title = completed_quest.get('title') if isinstance(completed_quest, dict) else completed_quest.title
        quest_description = completed_quest.get('description') if isinstance(completed_quest, dict) else completed_quest.description
        quest_type = completed_quest.get('quest_type') if isinstance(completed_quest, dict) else completed_quest.quest_type
        experience_reward = completed_quest.get('experience_reward') if isinstance(completed_quest, dict) else completed_quest.experience_reward
        story_context = completed_quest.get('story_context') if isinstance(completed_quest, dict) else completed_quest.story_context

        prompt = prompt_manager.format_prompt(
            "quest_completion_choices",
            quest_title=quest_title,
            quest_description=quest_description,
            quest_type=quest_type,
            player_name=game_state.player.name,
            player_level=game_state.player.stats.level,
            experience_reward=experience_reward,
            story_context=story_context,
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
                    title=llm_response.get("title", f"任务完成：{completed_quest.get('title') if isinstance(completed_quest, dict) else completed_quest.title}"),
                    description=llm_response.get("description", "恭喜完成任务！"),
                    context_data={
                        "completed_quest_id": completed_quest.id if not isinstance(completed_quest, dict) else completed_quest.get("id"),
                        "quest_data": completed_quest if isinstance(completed_quest, dict) else completed_quest.to_dict()
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

        # 添加到统一上下文管理器
        llm_context_manager.add_choice(
            choice_type=context.event_type,
            choice_text=selected_choice.text,
            result=f"处理中..."  # 结果将在处理后更新
        )

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
        # 【修复】处理 completed_quest 可能是字典或对象的情况
        quest_title = completed_quest.get('title') if isinstance(completed_quest, dict) else completed_quest.title
        experience_reward = completed_quest.get('experience_reward') if isinstance(completed_quest, dict) else completed_quest.experience_reward

        context = EventChoiceContext(
            event_type=ChoiceEventType.QUEST_COMPLETION.value,
            title=f"任务完成：{quest_title}",
            description=f"恭喜完成任务！获得了 {experience_reward} 经验值。",
            context_data={
                "completed_quest_id": completed_quest.id if not isinstance(completed_quest, dict) else completed_quest.get("id"),
                "quest_data": completed_quest if isinstance(completed_quest, dict) else completed_quest.to_dict()
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
                text="祈祷整理",
                description="祈祷并整理装备",
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

        # 获取玩家六维属性
        abilities = game_state.player.abilities

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
            player_str=abilities.strength,
            player_dex=abilities.dexterity,
            player_con=abilities.constitution,
            player_int=abilities.intelligence,
            player_wis=abilities.wisdom,
            player_cha=abilities.charisma,
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

                # 【修复问题1】处理新任务创建（如果LLM建议）
                if llm_response.get("new_quest_data"):
                    await self._create_new_quest_from_choice(game_state, llm_response["new_quest_data"], choice)

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
                # 方案A：若存在 completed_quest_id，确保该任务完成并取消激活，保证单活跃任务
                if completed_quest_id:
                    for q in game_state.quests:
                        if q.id == completed_quest_id:
                            q.is_completed = True
                            q.is_active = False
                            break


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

    async def _handle_map_transition(self, game_state: GameState, transition_data: Dict[str, Any],
                                     source: str = "story_event") -> None:
        """统一的地图切换处理

        Args:
            game_state: 游戏状态
            transition_data: 地图切换数据
            source: 触发来源（"story_event" 或 "quest_completion"）
        """
        try:
            from game_engine import game_engine

            transition_type = transition_data.get("transition_type", "new_area")
            target_depth = transition_data.get("target_depth")

            if transition_type == "new_area":
                # 根据来源设置默认深度
                if target_depth is None:
                    if source == "quest_completion":
                        target_depth = game_state.current_map.depth + 1  # 任务完成：下一层
                    else:
                        target_depth = game_state.current_map.depth  # 故事事件：同层

                # 确保楼层数合理
                max_floors = config.game.max_quest_floors
                target_depth = max(1, min(target_depth, max_floors))

                # 获取活跃任务上下文
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                # 【修复】处理 active_quest 可能是字典或对象的情况
                if active_quest:
                    if isinstance(active_quest, dict):
                        quest_context = active_quest
                    else:
                        quest_context = active_quest.to_dict()
                else:
                    quest_context = None

                # 根据来源设置默认主题
                default_theme = (
                    f"冒险区域（第{target_depth}阶段/层级）" if source == "quest_completion"
                    else f"神秘区域（第{target_depth}阶段/层级）"
                )

                # 生成新地图
                from content_generator import content_generator
                new_map = await content_generator.generate_dungeon_map(
                    width=config.game.default_map_size[0],
                    height=config.game.default_map_size[1],
                    depth=target_depth,
                    theme=transition_data.get("theme", default_theme),
                    quest_context=quest_context
                )

                # 确保新地图的深度正确设置
                new_map.depth = target_depth

                # 执行地图切换
                await self._execute_map_transition(game_state, new_map)

                # 添加切换消息
                transition_message = transition_data.get("message", f"进入了{new_map.name}（第{target_depth}层）")
                game_state.pending_events.append(transition_message)

                logger.info(f"{source.capitalize()} map transition completed: {new_map.name} (Depth: {target_depth})")

            elif transition_type == "existing_area":
                # 切换到已存在的区域（如果有的话）
                # 这里可以实现切换到之前访问过的地图的逻辑
                pass

        except Exception as e:
            import traceback
            logger.error(f"Error handling map transition ({source}): {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # 如果地图切换失败，添加错误消息但不中断游戏
            game_state.pending_events.append("地图切换遇到了一些问题，但你的冒险将继续...")

    async def _handle_story_event_map_transition(self, game_state: GameState, transition_data: Dict[str, Any]):
        """处理故事事件中的地图切换

        【修复问题3】简化为调用统一的地图切换方法
        """
        await self._handle_map_transition(game_state, transition_data, source="story_event")

    async def _handle_quest_completion_map_transition(self, game_state: GameState, transition_data: Dict[str, Any]):
        """处理任务完成后的地图切换

        【修复问题3】简化为调用统一的地图切换方法
        """
        await self._handle_map_transition(game_state, transition_data, source="quest_completion")

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

            # 【修复】更新周围瓦片的可见性
            from game_engine import game_engine
            game_engine._update_visibility(game_state, spawn_positions[0][0], spawn_positions[0][1])

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
        """处理陷阱选择

        支持的选项：
        - disarm: 解除陷阱
        - avoid: 规避陷阱
        - trigger: 故意触发陷阱
        - retreat: 后退
        """
        from trap_manager import get_trap_manager

        # 【P0修复】获取并验证陷阱数据
        raw_trap_data = context.context_data.get('trap_data', {})
        trap_data = trap_validator.validate_and_normalize(raw_trap_data)

        position = context.context_data.get('position', [0, 0])
        tile = game_state.current_map.get_tile(position[0], position[1])

        if not tile:
            return ChoiceResult(
                success=False,
                message="无效的位置",
                events=["陷阱位置无效"]
            )

        trap_manager = get_trap_manager()

        # 处理不同的选择
        if choice.id == "disarm":
            # 尝试解除陷阱
            disarm_dc = trap_data.get('disarm_dc', 18)
            result = trap_manager.attempt_disarm(game_state.player, disarm_dc)

            if result['success']:
                # 解除成功
                tile.trap_disarmed = True
                if tile.has_event and tile.event_type == 'trap':
                    tile.event_data['is_disarmed'] = True

                # 陷阱消失，变为普通地板
                from data_models import TerrainType
                if tile.terrain == TerrainType.TRAP:
                    tile.terrain = TerrainType.FLOOR

                message = f"✅ 你成功解除了陷阱！🎲 1d20={result['roll']} + 调整值{result['modifier']:+d} = {result['total']} vs DC {disarm_dc}"
                events = ["陷阱已被安全解除"]

                # 给予经验奖励
                exp_reward = disarm_dc * 10
                game_state.player.stats.experience += exp_reward
                events.append(f"获得 {exp_reward} 点经验值")

                return ChoiceResult(
                    success=True,
                    message=message,
                    events=events,
                    state_updates={
                        "map_updates": {
                            f"{position[0]},{position[1]}": {
                                "terrain": "floor",
                                "trap_disarmed": True,
                                "event_data": tile.event_data if tile.has_event else {}
                            }
                        },
                        "player_updates": {
                            "experience": game_state.player.stats.experience
                        }
                    }
                )
            else:
                # 解除失败，触发陷阱
                trigger_result = trap_manager.trigger_trap(game_state, tile)

                message = f"❌ 解除失败！陷阱被触发了！🎲 1d20={result['roll']} + 调整值{result['modifier']:+d} = {result['total']} vs DC {disarm_dc}"
                events = [trigger_result['description']]

                return ChoiceResult(
                    success=False,
                    message=message,
                    events=events,
                    state_updates={
                        "player_updates": {
                            "hp": game_state.player.stats.hp
                        },
                        "game_over": trigger_result.get('player_died', False)
                    }
                )

        elif choice.id == "avoid":
            # 尝试规避陷阱
            save_dc = trap_data.get('save_dc', 14)
            result = trap_manager.attempt_avoid(game_state.player, save_dc)

            if result['success']:
                # 规避成功，安全通过
                # 使用统一的消息格式（优先使用新引擎的ui_text）
                if "ui_text" in result:
                    message = f"✅ 你灵巧地避开了陷阱！{result['ui_text']}"
                elif "breakdown" in result:
                    message = f"✅ 你灵巧地避开了陷阱！{result['breakdown']} vs DC {save_dc}"
                else:
                    # 旧格式兼容
                    message = f"✅ 你灵巧地避开了陷阱！🎲 1d20={result['roll']} + DEX{result['modifier']:+d} = {result['total']} vs DC {save_dc}"
                events = ["成功规避陷阱"]

                return ChoiceResult(
                    success=True,
                    message=message,
                    events=events
                )
            else:
                # 规避失败，触发陷阱（可能减半伤害）
                trigger_result = trap_manager.trigger_trap(game_state, tile, save_result=result)

                # 使用统一的消息格式
                if "ui_text" in result:
                    message = f"❌ 规避失败！陷阱被触发了！{result['ui_text']}"
                elif "breakdown" in result:
                    message = f"❌ 规避失败！陷阱被触发了！{result['breakdown']} vs DC {save_dc}"
                else:
                    # 旧格式兼容
                    message = f"❌ 规避失败！陷阱被触发了！🎲 1d20={result['roll']} + DEX{result['modifier']:+d} = {result['total']} vs DC {save_dc}"
                events = [trigger_result['description']]

                return ChoiceResult(
                    success=False,
                    message=message,
                    events=events,
                    state_updates={
                        "player_updates": {
                            "hp": game_state.player.stats.hp
                        },
                        "game_over": trigger_result.get('player_died', False)
                    }
                )

        elif choice.id == "trigger":
            # 故意触发陷阱
            trigger_result = trap_manager.trigger_trap(game_state, tile)

            message = "你故意触发了陷阱..."
            events = [trigger_result['description']]

            return ChoiceResult(
                success=True,
                message=message,
                events=events,
                state_updates={
                    "player_updates": {
                        "hp": game_state.player.stats.hp
                    },
                    "game_over": trigger_result.get('player_died', False)
                }
            )

        elif choice.choice_id == "retreat":
            # 后退，返回上一个位置
            # 这个逻辑由前端处理
            return ChoiceResult(
                success=True,
                message="你小心地后退了",
                events=["返回到安全位置"]
            )

        else:
            # 未知选项
            return ChoiceResult(
                success=False,
                message=f"未知的选项：{choice.choice_id}",
                events=["无效的选择"]
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
        """应用选择结果到游戏状态（使用统一的GameStateModifier）"""
        try:
            # 构建LLM响应格式的更新数据
            llm_response = {
                "player_updates": result.player_updates or {},
                "map_updates": result.map_updates or {},
                "quest_updates": result.quest_updates or {},
                "events": result.events or []
            }

            # 使用GameStateModifier应用所有更新
            modification_result = game_state_modifier.apply_llm_updates(
                game_state,
                llm_response,
                source="event_choice"
            )

            # 记录修改结果
            if not modification_result.success:
                logger.warning(f"Some modifications failed: {modification_result.errors}")
            else:
                logger.info(f"Successfully applied choice result: {len(modification_result.records)} modifications")

            # 调试模式下显示详细信息
            if config.game.show_llm_debug:
                logger.info(f"Choice result modification details: {modification_result.to_dict()}")

        except Exception as e:
            logger.error(f"Error applying choice result: {e}")

    def _is_field_missing_or_empty(self, data: Dict, field: str) -> bool:
        """检查字段是否缺失或为空（包括空数组、空字符串）

        Args:
            data: 数据字典
            field: 字段名

        Returns:
            True 如果字段缺失或为空，否则 False
        """
        value = data.get(field)
        if value is None:
            return True
        if isinstance(value, (list, str)) and len(value) == 0:
            return True
        return False

    def _convert_events_to_objects(self, events_data: List[Dict[str, Any]]) -> List:
        """将事件字典数组转换为 QuestEvent 对象数组

        Args:
            events_data: 事件字典数组

        Returns:
            QuestEvent 对象数组
        """
        from data_models import QuestEvent

        events = []
        for event_data in events_data:
            # 如果已经是对象，直接使用
            if hasattr(event_data, 'to_dict'):
                events.append(event_data)
                continue

            # 从字典创建对象
            event = QuestEvent()
            event.id = event_data.get("id", event.id)
            event.event_type = event_data.get("event_type", "")
            event.name = event_data.get("name", "")
            event.description = event_data.get("description", "")
            event.trigger_condition = event_data.get("trigger_condition", "")
            event.progress_value = event_data.get("progress_value", 0.0)
            event.is_mandatory = event_data.get("is_mandatory", True)
            event.location_hint = event_data.get("location_hint", "")
            events.append(event)

        return events

    def _convert_monsters_to_objects(self, monsters_data: List[Dict[str, Any]]) -> List:
        """将怪物字典数组转换为 QuestMonster 对象数组

        Args:
            monsters_data: 怪物字典数组

        Returns:
            QuestMonster 对象数组
        """
        from data_models import QuestMonster

        monsters = []
        for monster_data in monsters_data:
            # 如果已经是对象，直接使用
            if hasattr(monster_data, 'to_dict'):
                monsters.append(monster_data)
                continue

            # 从字典创建对象
            monster = QuestMonster()
            monster.id = monster_data.get("id", monster.id)
            monster.name = monster_data.get("name", "")
            monster.description = monster_data.get("description", "")
            monster.challenge_rating = monster_data.get("challenge_rating", 1.0)
            monster.is_boss = monster_data.get("is_boss", False)
            monster.progress_value = monster_data.get("progress_value", 0.0)
            monster.spawn_condition = monster_data.get("spawn_condition", "")
            monster.location_hint = monster_data.get("location_hint", "")
            monsters.append(monster)

        return monsters

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
            new_quest.quest_type = quest_data.get("quest_type") or quest_data.get("type", "exploration")
            new_quest.experience_reward = quest_data.get("experience_reward", 500)
            new_quest.objectives = quest_data.get("objectives", ["完成新的挑战"])
            new_quest.completed_objectives = [False] * len(new_quest.objectives)
            # 延后统一去激活旧任务，先暂时激活新任务
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

            # 【修复问题4】检查关键字段是否缺失或为空（包括空数组）
            needs_generation = (
                self._is_field_missing_or_empty(quest_data, "title") or
                self._is_field_missing_or_empty(quest_data, "description") or
                self._is_field_missing_or_empty(quest_data, "map_themes") or
                self._is_field_missing_or_empty(quest_data, "special_events") or
                self._is_field_missing_or_empty(quest_data, "special_monsters") or
                self._is_field_missing_or_empty(quest_data, "target_floors")
            )

            if needs_generation:
                # 使用现有的任务生成系统，传递选择上下文
                context_for_generation = f"玩家选择了：{choice.text} - {choice.description}"
                generated_quests = await content_generator.generate_quest_chain(
                    game_state.player.stats.level, 1, context_for_generation
                )

                if generated_quests:
                    generated_quest = generated_quests[0]
                    # 【修复】合并LLM提供的数据和生成的数据，优先使用LLM数据但补充缺失字段
                    new_quest.title = quest_data.get("title") or generated_quest.title
                    new_quest.description = quest_data.get("description") or generated_quest.description
                    new_quest.quest_type = (quest_data.get("quest_type") or quest_data.get("type") or generated_quest.quest_type)
                    new_quest.experience_reward = quest_data.get("experience_reward") or generated_quest.experience_reward
                    new_quest.objectives = quest_data.get("objectives") or generated_quest.objectives
                    new_quest.completed_objectives = [False] * len(new_quest.objectives)

                    # 【关键修复】确保这些字段总是被填充，并转换字典为对象
                    # 优先使用LLM数据（需要转换），否则使用生成器数据（已经是对象）
                    llm_events = quest_data.get("special_events")
                    new_quest.special_events = (
                        self._convert_events_to_objects(llm_events) if llm_events
                        else generated_quest.special_events
                    )

                    llm_monsters = quest_data.get("special_monsters")
                    new_quest.special_monsters = (
                        self._convert_monsters_to_objects(llm_monsters) if llm_monsters
                        else generated_quest.special_monsters
                    )

                    new_quest.target_floors = quest_data.get("target_floors") or generated_quest.target_floors
                    new_quest.map_themes = quest_data.get("map_themes") or generated_quest.map_themes

                    logger.info(f"Quest data supplemented from generator. map_themes: {new_quest.map_themes}")
            else:
                # LLM提供了完整数据，需要转换为对象
                new_quest.special_events = self._convert_events_to_objects(quest_data.get("special_events", []))
                new_quest.special_monsters = self._convert_monsters_to_objects(quest_data.get("special_monsters", []))
                new_quest.target_floors = quest_data.get("target_floors", [1])
                new_quest.map_themes = quest_data.get("map_themes", [])

            # 添加到游戏状态
            game_state.quests.append(new_quest)

            # 添加新任务通知
            # 方案A：在成功添加新任务后再统一取消其他任务激活，避免在创建过程中异常导致无活跃任务
            for q in game_state.quests:
                if q.id != new_quest.id:
                    q.is_active = False
            new_quest.is_active = True

            game_state.pending_events.append(f"新任务：{new_quest.title}")
            game_state.pending_events.append("你的冒险将继续...")

            # 清理新任务生成标志（如果存在）
            if hasattr(game_state, 'pending_new_quest_generation'):
                game_state.pending_new_quest_generation = False

            logger.info(f"Created new quest from choice: {new_quest.title} (type: {new_quest.quest_type}, map_themes: {new_quest.map_themes})")

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
            new_quest.quest_type = quest_data.get("quest_type") or quest_data.get("type", "exploration")
            new_quest.experience_reward = quest_data.get("experience_reward", 500)
            new_quest.objectives = quest_data.get("objectives", ["完成新的挑战"])
            new_quest.completed_objectives = [False] * len(new_quest.objectives)
            # 方案A：保证单活跃任务
            # 延后统一去激活旧任务，先暂时激活新任务
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
                    new_quest.quest_type = quest_data.get("quest_type", quest_data.get("type", generated_quest.quest_type))
                    new_quest.experience_reward = quest_data.get("experience_reward", generated_quest.experience_reward)
                    new_quest.objectives = quest_data.get("objectives", generated_quest.objectives)
                    new_quest.completed_objectives = [False] * len(new_quest.objectives)
                    new_quest.special_events = generated_quest.special_events
                    new_quest.special_monsters = generated_quest.special_monsters
                    new_quest.target_floors = generated_quest.target_floors
                    new_quest.map_themes = generated_quest.map_themes

            # 添加到游戏状态
            game_state.quests.append(new_quest)


            # 方案A：在成功添加新任务后再统一取消其他任务激活，避免在创建过程中异常导致无活跃任务
            for q in game_state.quests:
                if q.id != new_quest.id:
                    q.is_active = False
            new_quest.is_active = True

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
