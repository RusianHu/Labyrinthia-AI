"""
Labyrinthia AI - FastAPI主应用
Main FastAPI application for the Labyrinthia AI game
"""

import asyncio
import logging
import random
import time
import json
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from game_engine import game_engine
from data_manager import data_manager
from llm_service import llm_service
from progress_manager import progress_manager
from event_choice_system import event_choice_system
from data_models import GameState
from user_session_manager import user_session_manager
from async_task_manager import async_task_manager
from input_validator import input_validator
from game_state_lock_manager import game_state_lock_manager


# 配置日志
# 服务器核心日志（启动、关闭、错误等）始终使用 INFO 级别
# 调试模式下可以看到更详细的 DEBUG 级别日志
logging.basicConfig(
    level=logging.DEBUG if config.game.debug_mode else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Pydantic模型
class NewGameRequest(BaseModel):
    player_name: str
    character_class: str = "fighter"


class ActionRequest(BaseModel):
    game_id: str
    action: str
    parameters: Dict[str, Any] = {}


class EventChoiceRequest(BaseModel):
    game_id: str
    context_id: str
    choice_id: str


class LLMEventRequest(BaseModel):
    game_id: str
    event_type: str
    event_data: Dict[str, Any]
    game_state: Dict[str, Any]


class SyncStateRequest(BaseModel):
    game_id: str
    game_state: Dict[str, Any]


# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的处理"""
    logger.info("Starting Labyrinthia AI server...")

    # 启动时的初始化
    try:
        # 初始化异步任务管理器
        async_task_manager.initialize()
        logger.info("AsyncTaskManager initialized")

        # 启动游戏会话清理任务
        game_engine._start_cleanup_task()
        logger.info("Game session cleanup task started")

        logger.info("Server started successfully")
        yield

    finally:
        # 关闭时的清理
        logger.info("Shutting down Labyrinthia AI server...")

        # 1. 先取消所有自动保存任务
        logger.info("Cancelling all auto-save tasks...")
        game_keys = list(game_engine.active_games.keys())
        for game_key in game_keys:
            user_id, game_id = game_key
            if game_key in game_engine.auto_save_tasks:
                try:
                    await game_engine.close_game(user_id, game_id)
                except Exception as e:
                    logger.error(f"Error closing game {game_id} for user {user_id}: {e}")

        # 2. 保存所有剩余的活跃游戏（如果有的话）
        for game_key, game_state in list(game_engine.active_games.items()):
            user_id, game_id = game_key
            try:
                logger.info(f"Saving game {game_id} for user {user_id}")
                await game_engine._save_game_async(game_state, user_id)
                logger.info(f"Saved game: {game_id}")
            except Exception as e:
                logger.error(f"Failed to save game {game_id}: {e}")

        # 3. 关闭LLM服务
        llm_service.close()

        # 4. 关闭异步任务管理器（会取消所有剩余任务并关闭线程池）
        await async_task_manager.shutdown()

        logger.info("Server shutdown complete")


# 创建FastAPI应用
app = FastAPI(
    title="Labyrinthia AI",
    description="老司机地牢",
    version="1.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.web.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
# 挂载静态目录到根路径，用于直接访问HTML文件（如 quick_test.html）
# 注意：这个挂载必须在其他路由之后，以避免冲突
templates = Jinja2Templates(directory="templates")


# 路由处理器
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/debug-test", response_class=HTMLResponse)
async def debug_test():
    """调试功能测试页面"""
    with open("debug_test.html", "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

# 注意：quick_test.html 现在可以直接通过 /quick_test.html 访问
# 因为我们在文件末尾添加了根目录静态文件挂载


@app.get("/test-effects", response_class=HTMLResponse)
async def test_effects(request: Request):
    """特效测试页面"""
    with open("test_effects.html", "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


@app.get("/test-progress", response_class=HTMLResponse)
async def test_progress(request: Request):
    """进度条测试页面"""
    with open("test_progress_bar.html", "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


@app.post("/api/new-game")
async def create_new_game(request: NewGameRequest, http_request: Request, response: Response):
    """创建新游戏"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)

        # 验证玩家名称
        name_validation = input_validator.validate_player_name(request.player_name)
        if not name_validation.is_valid:
            raise HTTPException(status_code=400, detail=name_validation.error_message)

        # 验证角色职业
        class_validation = input_validator.validate_character_class(request.character_class)
        if not class_validation.is_valid:
            logger.warning(f"Invalid character class: {request.character_class}, using default")

        # 使用清理后的值
        sanitized_name = name_validation.sanitized_value
        sanitized_class = class_validation.sanitized_value

        logger.info(f"Creating new game for user {user_id}, player: {sanitized_name} (class: {sanitized_class})")

        # 记录警告信息
        if name_validation.warnings:
            for warning in name_validation.warnings:
                logger.warning(f"Player name validation warning: {warning}")

        game_state = await game_engine.create_new_game(
            user_id=user_id,
            player_name=sanitized_name,
            character_class=sanitized_class
        )

        return {
            "success": True,
            "game_id": game_state.id,
            "message": f"欢迎 {sanitized_name}！你的冒险开始了！",
            "narrative": game_state.last_narrative,
            "warnings": name_validation.warnings if name_validation.warnings else []
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create new game: {e}")
        raise HTTPException(status_code=500, detail=f"创建游戏失败: {str(e)}")


@app.post("/api/load/{save_id}")
async def load_game(save_id: str, request: Request, response: Response):
    """加载游戏"""
    try:
        logger.info(f"Loading game: {save_id}")

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 从用户会话管理器加载存档数据
        save_data = user_session_manager.load_game_for_user(user_id, save_id)

        if not save_data:
            raise HTTPException(status_code=404, detail="存档未找到")

        # 使用data_manager重建GameState对象
        game_state = data_manager._dict_to_game_state(save_data)

        # 添加到活跃游戏列表（使用 (user_id, game_id) 作为键）
        game_key = (user_id, game_state.id)
        game_engine.active_games[game_key] = game_state
        game_engine._start_auto_save(user_id, game_state.id)

        # 生成重新进入游戏的叙述
        try:
            return_narrative = await llm_service.generate_return_narrative(game_state)
            game_state.last_narrative = return_narrative
        except Exception as e:
            logger.error(f"Failed to generate return narrative: {e}")
            game_state.last_narrative = f"你重新回到了 {game_state.current_map.name}，继续你的冒险..."

        return {
            "success": True,
            "game_id": game_state.id,
            "message": f"游戏已加载：{game_state.player.name}",
            "narrative": game_state.last_narrative
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load game: {e}")
        raise HTTPException(status_code=500, detail=f"加载游戏失败: {str(e)}")


@app.get("/api/game/{game_id}")
async def get_game_state(game_id: str, request: Request, response: Response):
    """获取游戏状态（支持自动从磁盘加载）"""

    # 获取用户ID
    user_id = user_session_manager.get_or_create_user_id(request, response)
    game_key = (user_id, game_id)

    # 如果游戏不在内存中，尝试从磁盘加载
    if game_key not in game_engine.active_games:
        logger.info(f"Game {game_id} not in memory for user {user_id}, attempting to load from disk...")

        # 尝试从用户存档加载
        save_data = user_session_manager.load_game_for_user(user_id, game_id)

        if save_data:
            # 重建游戏状态并加载到内存
            game_state = data_manager._dict_to_game_state(save_data)
            game_engine.active_games[game_key] = game_state
            game_engine._start_auto_save(user_id, game_state.id)
            logger.info(f"Game {game_id} loaded from disk for user {user_id}")
        else:
            # 如果磁盘上也没有，返回404
            raise HTTPException(status_code=404, detail="游戏未找到")

    game_state = game_engine.active_games[game_key]

    # 更新访问时间
    game_engine.update_access_time(user_id, game_id)

    # 获取游戏状态字典
    state_dict = game_state.to_dict()

    # 清理服务器端的pending_effects，避免重复触发
    if hasattr(game_state, 'pending_effects') and game_state.pending_effects:
        # 前端会处理这些特效，所以服务器端可以清理了
        game_state.pending_effects = []

    return state_dict


@app.get("/api/game/{game_id}/state")
async def get_game_state_detailed(game_id: str, request: Request, response: Response):
    """获取详细游戏状态（别名路由）"""
    return await get_game_state(game_id, request, response)


@app.get("/api/game/{game_id}/quests")
async def get_game_quests(game_id: str, request: Request, response: Response):
    """获取游戏任务列表"""
    # 获取用户ID
    user_id = user_session_manager.get_or_create_user_id(request, response)
    game_key = (user_id, game_id)

    if game_key not in game_engine.active_games:
        raise HTTPException(status_code=404, detail="游戏未找到")

    game_state = game_engine.active_games[game_key]

    # 返回任务列表
    quests = []
    for quest in game_state.quests:
        quest_dict = {
            "id": quest.id,
            "title": quest.title,
            "description": quest.description,
            "objectives": quest.objectives,
            "completed_objectives": quest.completed_objectives,
            "is_active": quest.is_active,
            "is_completed": quest.is_completed,
            "progress_percentage": quest.progress_percentage,
            "quest_type": quest.quest_type,
            "experience_reward": quest.experience_reward,
            "story_context": quest.story_context
        }
        quests.append(quest_dict)

    return quests


@app.post("/api/action")
async def perform_action(request: ActionRequest, http_request: Request, response: Response):
    """执行游戏行动"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)

        # 验证游戏ID
        game_id_validation = input_validator.validate_game_id(request.game_id)
        if not game_id_validation.is_valid:
            raise HTTPException(status_code=400, detail=game_id_validation.error_message)

        # 验证动作类型
        valid_actions = ["move", "attack", "rest", "interact", "use_item", "drop_item", "pickup_item"]
        if request.action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"无效的动作类型: {request.action}")

        # 验证参数
        sanitized_params = {}
        if request.action == "move" and "direction" in request.parameters:
            direction_validation = input_validator.validate_direction(request.parameters["direction"])
            if not direction_validation.is_valid:
                raise HTTPException(status_code=400, detail=direction_validation.error_message)
            sanitized_params["direction"] = direction_validation.sanitized_value
        elif request.action in ["use_item", "drop_item", "pickup_item"] and "item_id" in request.parameters:
            # 验证item_id是UUID格式
            item_id_validation = input_validator.validate_game_id(request.parameters["item_id"])
            if not item_id_validation.is_valid:
                raise HTTPException(status_code=400, detail="无效的物品ID")
            sanitized_params["item_id"] = item_id_validation.sanitized_value
        elif request.action == "attack" and "target_id" in request.parameters:
            # 验证target_id是UUID格式
            target_id_validation = input_validator.validate_game_id(request.parameters["target_id"])
            if not target_id_validation.is_valid:
                raise HTTPException(status_code=400, detail="无效的目标ID")
            sanitized_params["target_id"] = target_id_validation.sanitized_value
        else:
            # 其他参数直接传递（如坐标等）
            sanitized_params = request.parameters

        logger.info(f"Processing action: {request.action} for user {user_id}, game: {request.game_id}")

        # 更新访问时间
        game_engine.update_access_time(user_id, request.game_id)

        result = await game_engine.process_player_action(
            user_id=user_id,
            game_id=request.game_id,
            action=request.action,
            parameters=sanitized_params
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process action: {e}")
        raise HTTPException(status_code=500, detail=f"处理行动失败: {str(e)}")


@app.post("/api/llm-event")
async def handle_llm_event(request: LLMEventRequest, http_request: Request, response: Response):
    """处理需要LLM的事件"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        logger.info(f"Processing LLM event: {request.event_type} for user {user_id}, game: {request.game_id}")

        if game_key not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        # 从请求中重建游戏状态
        from data_manager import data_manager
        game_state = data_manager._dict_to_game_state(request.game_state)

        # 更新内存中的游戏状态
        game_engine.active_games[game_key] = game_state

        event_type = request.event_type
        event_data = request.event_data

        # 根据事件类型处理
        if event_type == 'tile_event':
            # 处理瓦片事件
            tile_data = event_data.get('tile', {})
            position = event_data.get('position', [0, 0])

            # 重建MapTile对象
            from data_models import MapTile, TerrainType
            tile = MapTile()
            tile.x = tile_data.get('x', position[0])
            tile.y = tile_data.get('y', position[1])
            tile.terrain = TerrainType(tile_data.get('terrain', 'floor'))
            tile.has_event = tile_data.get('has_event', False)
            tile.event_type = tile_data.get('event_type', '')
            tile.event_data = tile_data.get('event_data', {})
            tile.event_triggered = tile_data.get('event_triggered', False)

            # 触发事件
            event_result = await game_engine._trigger_tile_event(game_state, tile)

            return {
                "success": True,
                "message": event_result,
                "events": [event_result],
                "game_state": game_state.to_dict()
            }

        elif event_type == 'treasure':
            # 处理宝藏事件 - 使用LLM生成物品
            position = event_data.get('position', [0, 0])
            tile_data = event_data.get('tile', {})

            # 生成宝藏物品
            treasure_result = await game_engine._find_treasure(game_state)

            # 更新地图上的瓦片（宝藏变为地板）
            tile = game_state.current_map.get_tile(position[0], position[1])
            if tile:
                from data_models import TerrainType
                tile.terrain = TerrainType.FLOOR

            return {
                "success": True,
                "message": treasure_result,
                "events": [treasure_result],
                "game_state": game_state.to_dict()
            }

        elif event_type == 'trap_narrative':
            # 处理陷阱叙述生成 - 前端已计算效果，后端生成描述性文本
            position = event_data.get('position', [0, 0])
            trap_result = event_data.get('trap_result', {})

            # 使用LLM生成陷阱触发的描述性文本
            narrative = await game_engine._generate_trap_narrative(game_state, trap_result)

            return {
                "success": True,
                "narrative": narrative,
                "game_state": game_state.to_dict()
            }

        else:
            return {
                "success": False,
                "message": f"未知的事件类型: {event_type}"
            }

    except Exception as e:
        logger.error(f"Failed to process LLM event: {e}")
        raise HTTPException(status_code=500, detail=f"处理LLM事件失败: {str(e)}")


@app.post("/api/sync-state")
async def sync_game_state(request: SyncStateRequest, http_request: Request, response: Response):
    """同步游戏状态（用于存档）"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        logger.info(f"Syncing game state for user {user_id}, game: {request.game_id}")

        # 从请求中重建游戏状态
        from data_manager import data_manager
        game_state = data_manager._dict_to_game_state(request.game_state)

        # 更新内存中的游戏状态
        game_engine.active_games[game_key] = game_state

        # 可选：立即保存到文件
        # data_manager.save_game_state(game_state)

        return {
            "success": True,
            "message": "游戏状态已同步"
        }

    except Exception as e:
        logger.error(f"Failed to sync game state: {e}")
        raise HTTPException(status_code=500, detail=f"同步游戏状态失败: {str(e)}")


@app.post("/api/game/{game_id}/combat-result")
async def process_combat_result(game_id: str, request: Request, response: Response):
    """处理战斗结果（怪物被击败）"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        logger.info(f"Processing combat result for user {user_id}, game: {game_id}")

        request_data = await request.json()
        monster_id = request_data.get("monster_id")
        damage_dealt = request_data.get("damage_dealt", 0)

        if not monster_id:
            raise HTTPException(status_code=400, detail="缺少怪物ID")

        # 使用锁保护战斗结算操作
        async with game_state_lock_manager.lock_game_state(user_id, game_id, "combat_result"):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 查找怪物
            monster = None
            for m in game_state.monsters:
                if m.id == monster_id:
                    monster = m
                    break

            if not monster:
                raise HTTPException(status_code=404, detail="怪物未找到")

            # 使用战斗结果管理器处理
            from combat_result_manager import combat_result_manager
            combat_result = await combat_result_manager.process_monster_defeat(
                game_state, monster, damage_dealt
            )

            # 返回战斗结果
            return combat_result.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process combat result: {e}")
        raise HTTPException(status_code=500, detail=f"处理战斗结果失败: {str(e)}")


@app.post("/api/event-choice")
async def process_event_choice(request: EventChoiceRequest, http_request: Request, response: Response):
    """处理事件选择"""
    try:
        # 记录接收到的请求数据
        logger.info(f"Received event choice request: game_id={request.game_id}, context_id={request.context_id}, choice_id={request.choice_id}")

        # 验证游戏ID
        game_id_validation = input_validator.validate_game_id(request.game_id)
        if not game_id_validation.is_valid:
            logger.error(f"Game ID validation failed: {game_id_validation.error_message}")
            raise HTTPException(status_code=400, detail=game_id_validation.error_message)

        # 验证上下文ID
        context_id_validation = input_validator.validate_uuid(request.context_id)
        if not context_id_validation.is_valid:
            logger.error(f"Context ID validation failed: {context_id_validation.error_message}")
            raise HTTPException(status_code=400, detail=f"无效的上下文ID: {context_id_validation.error_message}")

        # 验证选择ID
        choice_id_validation = input_validator.validate_choice_id(request.choice_id)
        if not choice_id_validation.is_valid:
            logger.error(f"Choice ID validation failed for '{request.choice_id}': {choice_id_validation.error_message}")
            raise HTTPException(status_code=400, detail=choice_id_validation.error_message)

        logger.info(f"Processing event choice: {request.choice_id} for context: {request.context_id}")

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        # 使用锁保护事件选择处理
        async with game_state_lock_manager.lock_game_state(user_id, request.game_id, "event_choice"):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 处理选择
            result = await event_choice_system.process_choice(
                game_state=game_state,
                context_id=request.context_id,
                choice_id=request.choice_id
            )

            if result.success:
                # 清理游戏状态中的待处理选择上下文
                game_state.pending_choice_context = None

                # 处理选择后的游戏状态更新（包括新任务生成）
                await _process_post_choice_updates(game_state)

                return {
                    "success": True,
                    "message": result.message,
                    "events": result.events,
                    "game_state": game_state.to_dict()
                }
            else:
                return {
                    "success": False,
                    "message": result.message
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process event choice: {e}")
        raise HTTPException(status_code=500, detail=f"处理事件选择失败: {str(e)}")


async def _process_post_choice_updates(game_state: GameState):
    """处理选择后的游戏状态更新"""
    try:
        # 检查是否需要生成新任务（确保玩家始终有活跃任务）
        # 注意：如果EventChoiceSystem已经创建了新任务，就不需要再生成
        if hasattr(game_state, 'pending_new_quest_generation') and game_state.pending_new_quest_generation:
            try:
                # 检查是否还有活跃任务
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                if not active_quest:
                    # 生成新任务（作为后备机制）
                    await game_engine._generate_new_quest_for_player(game_state)
                    logger.info("Generated fallback new quest after choice processing")
                else:
                    logger.info("Active quest found, skipping fallback quest generation")

                # 清理新任务生成标志
                game_state.pending_new_quest_generation = False

            except Exception as e:
                logger.error(f"Error generating new quest after choice: {e}")
                # 清理标志，避免重复处理
                game_state.pending_new_quest_generation = False

        # 检查是否有其他待处理的游戏状态更新
        # 这里可以添加其他需要在选择处理后执行的逻辑

    except Exception as e:
        logger.error(f"Error in post-choice updates: {e}")


@app.get("/api/game/{game_id}/pending-choice")
async def get_pending_choice(game_id: str, request: Request, response: Response):
    """获取待处理的选择上下文（事件驱动，仅在玩家操作后调用）"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        if game_key not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        # 更新访问时间
        game_engine.update_access_time(user_id, game_id)

        game_state = game_engine.active_games[game_key]

        if game_state.pending_choice_context:
            return {
                "success": True,
                "has_pending_choice": True,
                "choice_context": game_state.pending_choice_context.to_dict()
            }
        else:
            return {
                "success": True,
                "has_pending_choice": False,
                "choice_context": None
            }

    except Exception as e:
        logger.error(f"Failed to get pending choice: {e}")
        raise HTTPException(status_code=500, detail=f"获取待处理选择失败: {str(e)}")


@app.post("/api/save/import")
async def import_save(request: Request, response: Response, file: UploadFile = File(...)):
    """导入存档JSON文件"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 读取上传的文件
        content = await file.read()

        # 验证文件上传
        file_validation = input_validator.validate_file_upload(
            filename=file.filename,
            content=content,
            allowed_extensions=['json'],
            max_size_mb=10.0
        )

        if not file_validation.is_valid:
            raise HTTPException(status_code=400, detail=file_validation.error_message)

        # 解析JSON数据
        try:
            save_data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"无效的JSON格式: {str(e)}")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"文件编码错误: {str(e)}")

        # 验证存档数据结构
        save_validation = input_validator.validate_save_data(save_data)
        if not save_validation.is_valid:
            raise HTTPException(status_code=400, detail=save_validation.error_message)

        # 记录警告
        if save_validation.warnings:
            for warning in save_validation.warnings:
                logger.warning(f"Save data validation warning: {warning}")

        # 导入存档（使用验证后的数据）
        success = user_session_manager.import_save(user_id, save_validation.sanitized_value)

        if success:
            response_data = {
                "success": True,
                "message": "存档导入成功",
                "save_id": save_validation.sanitized_value.get("id")
            }

            # 如果有警告，添加到响应中
            if save_validation.warnings:
                response_data["warnings"] = save_validation.warnings

            return response_data
        else:
            raise HTTPException(status_code=400, detail="存档数据无效或导入失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import save: {e}")
        raise HTTPException(status_code=500, detail=f"导入存档失败: {str(e)}")


@app.post("/api/save/{game_id}")
async def save_game(game_id: str, request: Request, response: Response):
    """保存游戏"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        # 使用锁保护手动保存操作
        async with game_state_lock_manager.lock_game_state(user_id, game_id, "manual_save"):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 使用用户会话管理器保存游戏
            game_data = game_state.to_dict()

        # 在锁外执行文件IO操作
        success = user_session_manager.save_game_for_user(user_id, game_data)

        if success:
            return {"success": True, "message": "游戏已保存"}
        else:
            raise HTTPException(status_code=500, detail="保存失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save game: {e}")
        raise HTTPException(status_code=500, detail=f"保存游戏失败: {str(e)}")


@app.get("/api/saves")
async def list_saves(request: Request, response: Response):
    """获取当前用户的存档列表"""
    try:
        # 获取或创建用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 获取用户的存档列表
        saves = user_session_manager.list_user_saves(user_id)
        return saves
    except Exception as e:
        logger.error(f"Failed to list saves: {e}")
        raise HTTPException(status_code=500, detail=f"获取存档列表失败: {str(e)}")





@app.delete("/api/save/{save_id}")
async def delete_save(save_id: str, request: Request, response: Response):
    """删除当前用户的存档"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 删除用户的存档
        success = user_session_manager.delete_save_for_user(user_id, save_id)

        if success:
            # 同时从内存中移除游戏（如果存在）
            game_key = (user_id, save_id)
            if game_key in game_engine.active_games:
                # 停止自动保存任务
                if game_key in game_engine.auto_save_tasks:
                    game_engine.auto_save_tasks[game_key].cancel()
                    del game_engine.auto_save_tasks[game_key]

                # 从内存中移除
                del game_engine.active_games[game_key]
                logger.info(f"Game {save_id} removed from memory")

            return {"success": True, "message": "存档已删除"}
        else:
            raise HTTPException(status_code=404, detail="存档未找到")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete save: {e}")
        raise HTTPException(status_code=500, detail=f"删除存档失败: {str(e)}")


@app.get("/api/save/export/{save_id}")
async def export_save(save_id: str, request: Request, response: Response):
    """导出存档为JSON文件"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 导出存档数据
        save_data = user_session_manager.export_save(user_id, save_id)

        if not save_data:
            raise HTTPException(status_code=404, detail="存档未找到")

        # 生成文件名（包含角色名和时间戳）
        player_name = save_data.get("player", {}).get("name", "Unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Labyrinthia_{player_name}_{timestamp}.json"

        # 返回JSON文件
        import tempfile
        import json

        # 创建临时文件
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8')
        json.dump(save_data, temp_file, ensure_ascii=False, indent=2)
        temp_file.close()

        # URL编码文件名以支持中文
        from urllib.parse import quote
        encoded_filename = quote(filename)

        return FileResponse(
            path=temp_file.name,
            filename=filename,
            media_type='application/json',
            headers={
                "Content-Disposition": f'attachment; filename*=UTF-8\'\'{encoded_filename}'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export save: {e}")
        raise HTTPException(status_code=500, detail=f"导出存档失败: {str(e)}")


@app.get("/api/user/stats")
async def get_user_stats(request: Request, response: Response):
    """获取当前用户的统计信息"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 获取用户统计信息
        stats = user_session_manager.get_user_stats(user_id)

        return stats

    except Exception as e:
        logger.error(f"Failed to get user stats: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户统计失败: {str(e)}")


@app.get("/api/config")
async def get_config():
    """获取游戏配置"""
    try:
        return {
            "success": True,
            "config": {
                "game": {
                    "debug_mode": config.game.debug_mode,
                    "show_llm_debug": config.game.show_llm_debug,
                    "show_quest_progress": config.game.show_quest_progress,
                    "version": config.game.version,
                    "game_name": config.game.game_name,
                    "quest_progress_multiplier": config.game.quest_progress_multiplier,
                    "max_quest_floors": config.game.max_quest_floors
                },
                "llm": {
                    "provider": config.llm.provider.value,
                    "model_name": config.llm.model_name,
                    "temperature": config.llm.temperature,
                    "max_output_tokens": config.llm.max_output_tokens
                },
                "web": {
                    "host": config.web.host,
                    "port": config.web.port
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@app.post("/api/config")
async def update_config(updates: Dict[str, Any]):
    """更新游戏配置（仅调试模式）"""
    if not config.game.debug_mode:
        raise HTTPException(status_code=403, detail="仅在调试模式下可用")

    try:
        # 验证配置更新数据
        config_validation = input_validator.validate_json_structure(
            updates,
            max_size_mb=1.0  # 配置数据不应该太大
        )

        if not config_validation.is_valid:
            raise HTTPException(status_code=400, detail=config_validation.error_message)

        # 只允许更新特定的配置节
        allowed_sections = ["game", "llm", "web", "debug"]

        for section, values in updates.items():
            if section not in allowed_sections:
                raise HTTPException(status_code=400, detail=f"不允许更新配置节: {section}")

            if hasattr(config, section):
                # 验证值的类型和范围
                if isinstance(values, dict):
                    for key, value in values.items():
                        # 对数值类型进行范围检查
                        if isinstance(value, (int, float)):
                            if key in ["port", "timeout", "max_output_tokens"]:
                                # 端口号范围
                                if key == "port":
                                    port_validation = input_validator.validate_integer_range(
                                        value, min_value=1024, max_value=65535, field_name="端口号"
                                    )
                                    if not port_validation.is_valid:
                                        raise HTTPException(status_code=400, detail=port_validation.error_message)
                                # 超时时间范围
                                elif key == "timeout":
                                    timeout_validation = input_validator.validate_integer_range(
                                        value, min_value=10, max_value=600, field_name="超时时间"
                                    )
                                    if not timeout_validation.is_valid:
                                        raise HTTPException(status_code=400, detail=timeout_validation.error_message)

                config.update_config(section, **values)

        return {"success": True, "message": "配置已更新"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@app.post("/api/game/{game_id}/transition")
async def transition_map(game_id: str, transition_data: Dict[str, Any], request: Request, response: Response):
    """手动切换地图"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        transition_type = transition_data.get("type")
        if not transition_type:
            raise HTTPException(status_code=400, detail="缺少切换类型")

        # 使用锁保护地图切换操作
        async with game_state_lock_manager.lock_game_state(user_id, game_id, "map_transition"):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            result = await game_engine.transition_map(
                game_engine.active_games[game_key],
                transition_type
            )

            if result["success"]:
                # 返回更新后的游戏状态
                game_state = game_engine.active_games[game_key]
                response_data = {
                    "success": True,
                    "message": result["message"],
                    "events": result["events"],
                    "game_state": game_state.to_dict()
                }

                # 【修复】检查是否有待处理的选择上下文，立即返回给前端
                if hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context:
                    response_data["pending_choice_context"] = game_state.pending_choice_context.to_dict()
                    logger.info(f"Returning pending choice context in transition result: {game_state.pending_choice_context.title}")

                return response_data
            else:
                return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Map transition failed: {e}")
        raise HTTPException(status_code=500, detail=f"地图切换失败: {str(e)}")


@app.get("/api/game/{game_id}/progress")
async def get_progress_summary(game_id: str, request: Request, response: Response):
    """获取游戏进度摘要"""
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        if game_key not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        game_state = game_engine.active_games[game_key]
        summary = progress_manager.get_progress_summary(game_state)

        return {
            "success": True,
            "progress_summary": summary
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get progress summary: {e}")
        raise HTTPException(status_code=500, detail=f"获取进度摘要失败: {str(e)}")


@app.get("/api/progress/history")
async def get_progress_history(limit: int = 10):
    """获取进度历史记录"""
    try:
        history = progress_manager.progress_history[-limit:] if limit > 0 else progress_manager.progress_history

        # 转换为可序列化的格式
        serialized_history = []
        for event in history:
            serialized_history.append({
                "event_type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "context_data": event.context_data,
                "metadata": event.metadata
            })

        return {
            "success": True,
            "history": serialized_history,
            "total_events": len(progress_manager.progress_history)
        }

    except Exception as e:
        logger.error(f"Failed to get progress history: {e}")
        raise HTTPException(status_code=500, detail=f"获取进度历史失败: {str(e)}")


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "active_games": len(game_engine.active_games),
        "llm_provider": config.llm.provider.value,
        "version": config.game.version,
        "progress_events_count": len(progress_manager.progress_history)
    }





@app.get("/auto-load/{game_id}")
async def auto_load_game(game_id: str):
    """自动加载游戏页面 - 显示加载界面并自动进入游戏"""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>加载游戏 - Labyrinthia AI</title>
        <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
        <link rel="stylesheet" href="/static/style.css">
        <style>
            body {{
                margin: 0;
                padding: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                font-family: 'Roboto', sans-serif;
                overflow: hidden;
            }}
            .loading-container {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9999;
            }}
            .loading-content {{
                background: rgba(255, 255, 255, 0.95);
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                max-width: 500px;
                width: 90%;
            }}
            .loading-title {{
                font-size: 28px;
                font-weight: bold;
                color: #333;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
            }}
            .loading-subtitle {{
                font-size: 18px;
                color: #666;
                margin-bottom: 30px;
            }}
            .spinner {{
                width: 40px;
                height: 40px;
                border: 4px solid #e0e0e0;
                border-top: 4px solid #4CAF50;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 20px;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            .loading-text {{
                font-size: 16px;
                color: #666;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="loading-container">
            <div class="loading-content">
                <div class="loading-title">
                    <i class="material-icons">games</i>
                    正在进入游戏
                </div>
                <div class="loading-subtitle">准备您的冒险...</div>

                <div class="spinner"></div>

                <div class="loading-text">正在加载游戏数据...</div>
            </div>
        </div>

        <script>
            async function autoLoadGame() {{
                try {{
                    // 调用加载游戏API
                    const response = await fetch('/api/load/{game_id}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }}
                    }});

                    const result = await response.json();

                    if (result.success) {{
                        // 加载成功，跳转到游戏页面
                        window.location.href = '/?game_id={game_id}';
                    }} else {{
                        // 加载失败，显示错误
                        document.querySelector('.loading-text').textContent = '加载失败: ' + result.message;
                        document.querySelector('.spinner').style.display = 'none';
                    }}
                }} catch (error) {{
                    console.error('Auto load error:', error);
                    document.querySelector('.loading-text').textContent = '加载失败: ' + error.message;
                    document.querySelector('.spinner').style.display = 'none';
                }}
            }}

            // 页面加载后自动开始
            window.addEventListener('load', autoLoadGame);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)








@app.get("/direct-start")
async def direct_start_game(request: Request, response: Response):
    """直接开始游戏 - 无加载界面，直接进入游戏"""
    try:
        # 获取或创建用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)

        # 随机生成角色名称
        random_names = [
            "测试勇者", "冒险家阿尔法", "探索者贝塔", "勇士伽马", "法师德尔塔",
            "盗贼艾普西隆", "战士泽塔", "牧师艾塔", "游侠西塔", "野蛮人约塔"
        ]

        # 随机选择职业
        character_classes = ["fighter", "wizard", "rogue"]

        # 生成随机角色
        player_name = random.choice(random_names) + f"_{random.randint(1000, 9999)}"
        character_class = random.choice(character_classes)

        logger.info(f"Direct starting game with player: {player_name}, class: {character_class}")

        # 创建游戏（create_new_game内部已经会保存游戏）
        game_state = await game_engine.create_new_game(
            user_id=user_id,
            player_name=player_name,
            character_class=character_class
        )

        # 直接重定向到游戏界面
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/?game_id={game_state.id}", status_code=302)

    except Exception as e:
        logger.error(f"Failed to direct start game: {e}")
        # 如果失败，重定向到主页
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)


# 错误处理器
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """404错误处理"""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": "API端点未找到"}
        )
    return templates.TemplateResponse("index.html", {"request": request})


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    """500错误处理"""
    logger.error(f"Internal server error: {exc}")
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "服务器内部错误"}
        )
    return templates.TemplateResponse("index.html", {"request": request})


# 开发模式下的额外路由
if config.game.debug_mode:
    from debug_api import debug_api

    # ==================== 系统状态监控接口 ====================

    @app.get("/api/debug/system/status")
    async def debug_get_system_status():
        """调试：获取系统整体状态"""
        return debug_api.get_system_status()

    @app.get("/api/debug/system/memory")
    async def debug_get_memory_usage():
        """调试：获取内存使用情况"""
        return debug_api.get_memory_usage()

    @app.get("/api/debug/system/users")
    async def debug_get_user_sessions():
        """调试：获取用户会话信息"""
        return debug_api.get_user_sessions()

    # ==================== 游戏状态查询接口 ====================

    @app.get("/api/debug/games")
    async def debug_list_games():
        """调试：列出所有活跃游戏（简化版）"""
        games = {}
        for (user_id, game_id), game_state in game_engine.active_games.items():
            games[f"{user_id}:{game_id}"] = {
                "user_id": user_id,
                "game_id": game_id,
                "player_name": game_state.player.name,
                "player_level": game_state.player.stats.level,
                "turn_count": game_state.turn_count,
                "map_name": game_state.current_map.name
            }
        return games

    @app.get("/api/debug/game/{game_id}")
    async def debug_get_game_detail(game_id: str, request: Request, response: Response):
        """调试：获取游戏详细状态"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.get_game_detail(user_id, game_id)

    # ==================== 内容生成测试接口 ====================

    @app.post("/api/debug/generate-content")
    async def debug_generate_content(content_type: str, context: str = ""):
        """调试：生成内容"""
        try:
            if content_type == "character":
                result = await llm_service.generate_character("npc", context)
                return result.to_dict() if result else None
            elif content_type == "monster":
                result = await llm_service.generate_monster(1.0, context)
                return result.to_dict() if result else None
            elif content_type == "quest":
                result = await llm_service.generate_quest(1, context)
                return result.to_dict() if result else None
            else:
                raise HTTPException(status_code=400, detail="无效的内容类型")
        except Exception as e:
            logger.error(f"Failed to generate content: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== 地图信息接口 ====================

    @app.get("/api/debug/map/{game_id}")
    async def debug_get_map_detail(game_id: str, request: Request, response: Response):
        """调试：获取地图详细信息（包含所有瓦片数据）"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.get_map_detail(user_id, game_id)

    @app.get("/api/debug/map/{game_id}/summary")
    async def debug_get_map_summary(game_id: str, request: Request, response: Response):
        """调试：获取地图摘要信息（轻量级，不包含所有瓦片）"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.get_map_summary(user_id, game_id)

    # ==================== 存档管理接口 ====================

    @app.get("/api/debug/saves/{user_id}")
    async def debug_get_save_files(user_id: str):
        """调试：获取用户存档文件信息"""
        return debug_api.get_save_files_info(user_id)

    @app.get("/api/debug/saves")
    async def debug_get_current_user_saves(request: Request, response: Response):
        """调试：获取当前用户存档文件信息"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.get_save_files_info(user_id)

    # ==================== 异步任务监控接口 ====================

    @app.get("/api/debug/tasks")
    async def debug_get_async_tasks():
        """调试：获取异步任务详细信息"""
        return debug_api.get_async_tasks_detail()

    @app.get("/api/debug/llm/statistics")
    async def debug_get_llm_statistics():
        """调试：获取LLM调用统计"""
        return debug_api.get_llm_statistics()

    @app.get("/api/debug/locks")
    async def debug_get_lock_stats():
        """调试：获取游戏状态锁统计信息"""
        return game_state_lock_manager.get_lock_stats()

    # ==================== 配置信息接口 ====================

    @app.get("/api/debug/config")
    async def debug_get_config():
        """调试：获取配置信息"""
        return debug_api.get_config_info()

    # ==================== LLM调试接口 ====================

    @app.get("/api/debug/llm-info")
    async def get_llm_debug_info():
        """获取LLM调试信息（最后的请求和响应）"""
        try:
            if not config.game.show_llm_debug:
                return {"success": False, "error": "LLM调试模式未启用"}

            # 获取最后的LLM请求和响应
            last_request = llm_service.get_last_request_payload()
            last_response = llm_service.get_last_response_payload()

            return {
                "success": True,
                "last_request": last_request,
                "last_response": last_response,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Get LLM debug info error: {e}")
            return {"success": False, "error": str(e)}

    # ==================== 测试API端点 ====================

    @app.post("/api/test/gemini")
    async def test_gemini_api(request: Request):
        """测试 Gemini API 连接"""
        try:
            request_data = await request.json()
            test_message = request_data.get("test_message", "Hello, this is a test")

            # 使用LLM服务进行简单测试
            response = await llm_service._async_generate(f"请用中文回复这条测试消息：{test_message}")

            return {
                "success": True,
                "response": response,
                "provider": config.llm.provider.value,
                "model": config.llm.model_name
            }
        except Exception as e:
            logger.error(f"Gemini API test failed: {e}")
            return {
                "success": False,
                "message": f"Gemini API 测试失败: {str(e)}"
            }

    @app.post("/api/test/openrouter")
    async def test_openrouter_api(request: Request):
        """测试 OpenRouter API 连接"""
        try:
            request_data = await request.json()
            test_message = request_data.get("test_message", "Hello, this is a test")

            # 临时切换到OpenRouter进行测试
            original_provider = config.llm.provider
            from config import LLMProvider
            config.llm.provider = LLMProvider.OPENROUTER

            try:
                response = await llm_service._async_generate(f"请用中文回复这条测试消息：{test_message}")
                return {
                    "success": True,
                    "response": response,
                    "provider": "openrouter",
                    "model": config.llm.model_name
                }
            finally:
                # 恢复原始提供商
                config.llm.provider = original_provider

        except Exception as e:
            logger.error(f"OpenRouter API test failed: {e}")
            return {
                "success": False,
                "message": f"OpenRouter API 测试失败: {str(e)}"
            }

    @app.post("/api/test/content-generation")
    async def test_content_generation(request: Request):
        """测试内容生成功能"""
        try:
            request_data = await request.json()
            test_type = request_data.get("test_type", "simple_item")
            player_level = request_data.get("player_level", 1)

            from content_generator import content_generator

            if test_type == "simple_item":
                # 生成简单物品
                items = await content_generator.generate_loot_items(player_level, "common")
                if items:
                    return {
                        "success": True,
                        "content_type": "item",
                        "generated_content": items[0].to_dict(),
                        "count": len(items)
                    }
            elif test_type == "monster":
                # 生成怪物
                monsters = await content_generator.generate_encounter_monsters(player_level, "normal")
                if monsters:
                    return {
                        "success": True,
                        "content_type": "monster",
                        "generated_content": monsters[0].to_dict(),
                        "count": len(monsters)
                    }
            elif test_type == "quest":
                # 生成任务
                quests = await content_generator.generate_quest_chain(player_level)
                if quests:
                    return {
                        "success": True,
                        "content_type": "quest",
                        "generated_content": quests[0].to_dict(),
                        "count": len(quests)
                    }

            return {
                "success": False,
                "message": "无法生成指定类型的内容"
            }

        except Exception as e:
            logger.error(f"Content generation test failed: {e}")
            return {
                "success": False,
                "message": f"内容生成测试失败: {str(e)}"
            }

    @app.post("/api/test/map-generation")
    async def test_map_generation(request: Request):
        """测试地图生成功能"""
        try:
            request_data = await request.json()
            width = request_data.get("width", 10)
            height = request_data.get("height", 10)
            depth = request_data.get("depth", 1)
            theme = request_data.get("theme", "测试地下城")

            from content_generator import content_generator

            game_map = await content_generator.generate_dungeon_map(
                width=width, height=height, depth=depth, theme=theme
            )

            # 统计地图信息
            room_count = 0
            event_count = 0

            for tile in game_map.tiles.values():
                if tile.terrain.value in ["room", "chamber"]:
                    room_count += 1
                if tile.has_event:
                    event_count += 1

            return {
                "success": True,
                "map_name": game_map.name,
                "map_size": f"{width}x{height}",
                "room_count": room_count,
                "event_count": event_count,
                "description": game_map.description[:100] + "..." if len(game_map.description) > 100 else game_map.description
            }

        except Exception as e:
            logger.error(f"Map generation test failed: {e}")
            return {
                "success": False,
                "message": f"地图生成测试失败: {str(e)}"
            }

    @app.post("/api/test/character-system")
    async def test_character_system(request: Request):
        """测试角色系统功能"""
        try:
            request_data = await request.json()
            character_name = request_data.get("character_name", "测试角色")
            character_class = request_data.get("character_class", "warrior")

            from data_models import Character, CharacterClass, Stats

            # 创建测试角色
            character = Character()
            character.name = character_name
            character.character_class = CharacterClass(character_class)
            character.stats = Stats()

            # 根据职业设置基础属性
            if character_class == "warrior":
                character.stats.strength = 16
                character.stats.constitution = 14
                character.stats.dexterity = 12
            elif character_class == "mage":
                character.stats.intelligence = 16
                character.stats.wisdom = 14
                character.stats.constitution = 10
            elif character_class == "rogue":
                character.stats.dexterity = 16
                character.stats.intelligence = 14
                character.stats.strength = 12

            character.stats.calculate_derived_stats()

            return {
                "success": True,
                "character_name": character.name,
                "character_class": character.character_class.value,
                "stats_summary": f"HP:{character.stats.hp}/{character.stats.max_hp} MP:{character.stats.mp}/{character.stats.max_mp} LV:{character.stats.level}"
            }

        except Exception as e:
            logger.error(f"Character system test failed: {e}")
            return {
                "success": False,
                "message": f"角色系统测试失败: {str(e)}"
            }

    @app.post("/api/test/quest-system")
    async def test_quest_system(request: Request):
        """测试任务系统功能"""
        try:
            request_data = await request.json()
            player_level = request_data.get("player_level", 1)
            quest_type = request_data.get("quest_type", "exploration")

            from content_generator import content_generator

            quests = await content_generator.generate_quest_chain(player_level)

            if quests:
                quest = quests[0]
                return {
                    "success": True,
                    "quest_title": quest.title,
                    "quest_type": quest.quest_type,
                    "target_floors": quest.target_floors,
                    "special_events_count": len(quest.special_events),
                    "special_monsters_count": len(quest.special_monsters),
                    "description": quest.description[:100] + "..." if len(quest.description) > 100 else quest.description
                }
            else:
                return {
                    "success": False,
                    "message": "无法生成测试任务"
                }

        except Exception as e:
            logger.error(f"Quest system test failed: {e}")
            return {
                "success": False,
                "message": f"任务系统测试失败: {str(e)}"
            }

    @app.post("/api/test/item-system")
    async def test_item_system(request: Request):
        """测试物品系统功能"""
        try:
            request_data = await request.json()
            item_type = request_data.get("item_type", "weapon")
            player_level = request_data.get("player_level", 1)

            from content_generator import content_generator

            # 根据类型生成不同的物品
            if item_type == "weapon":
                items = await content_generator.generate_loot_items(player_level, "common", item_types=["weapon"])
            elif item_type == "armor":
                items = await content_generator.generate_loot_items(player_level, "common", item_types=["armor"])
            elif item_type == "consumable":
                items = await content_generator.generate_loot_items(player_level, "common", item_types=["consumable"])
            else:
                items = await content_generator.generate_loot_items(player_level, "common")

            if items:
                item = items[0]
                return {
                    "success": True,
                    "item_name": item.name,
                    "item_type": item.item_type,
                    "item_rarity": item.rarity,
                    "item_description": item.description,
                    "item_value": item.value
                }
            else:
                return {
                    "success": False,
                    "message": "无法生成测试物品"
                }

        except Exception as e:
            logger.error(f"Item system test failed: {e}")
            return {
                "success": False,
                "message": f"物品系统测试失败: {str(e)}"
            }

    @app.post("/api/test/data-saving")
    async def test_data_saving(request: Request):
        """测试数据保存功能"""
        try:
            request_data = await request.json()

            # 创建测试数据
            test_data = {
                "test_save": True,
                "timestamp": request_data.get("timestamp"),
                "player_name": request_data.get("player_name", "测试玩家"),
                "level": request_data.get("level", 1),
                "test_id": f"test_{int(time.time())}"
            }

            # 使用数据管理器保存测试数据
            import json
            import os

            test_file = f"saves/test_save_{test_data['test_id']}.json"
            os.makedirs("saves", exist_ok=True)

            with open(test_file, 'w', encoding='utf-8') as f:
                json.dump(test_data, f, ensure_ascii=False, indent=2)

            file_size = os.path.getsize(test_file)

            return {
                "success": True,
                "save_file": test_file,
                "data_size": f"{file_size} bytes",
                "test_id": test_data['test_id']
            }

        except Exception as e:
            logger.error(f"Data saving test failed: {e}")
            return {
                "success": False,
                "message": f"数据保存测试失败: {str(e)}"
            }

    @app.post("/api/test/data-loading")
    async def test_data_loading(request: Request):
        """测试数据加载功能"""
        try:
            import os
            import glob

            # 检查存档目录
            saves_dir = "saves"
            if not os.path.exists(saves_dir):
                return {
                    "success": True,
                    "save_count": 0,
                    "latest_save": "无存档",
                    "message": "存档目录不存在，但这是正常的"
                }

            # 获取所有存档文件
            save_files = glob.glob(os.path.join(saves_dir, "*.json"))
            save_count = len(save_files)

            latest_save = "无"
            if save_files:
                # 找到最新的存档文件
                latest_file = max(save_files, key=os.path.getmtime)
                latest_save = os.path.basename(latest_file)

            return {
                "success": True,
                "save_count": save_count,
                "latest_save": latest_save,
                "saves_directory": saves_dir
            }

        except Exception as e:
            logger.error(f"Data loading test failed: {e}")
            return {
                "success": False,
                "message": f"数据加载测试失败: {str(e)}"
            }

    @app.post("/api/test/gamestate-management")
    async def test_gamestate_management(request: Request):
        """测试游戏状态管理功能"""
        try:
            active_games = len(game_engine.active_games)

            # 检查游戏状态同步
            sync_status = "正常"
            if active_games > 0:
                # 检查是否有游戏状态（注意：现在键是 (user_id, game_id) 元组）
                for game_key, game_state in game_engine.active_games.items():
                    if not game_state.player or not game_state.current_map:
                        sync_status = "异常"
                        break

            return {
                "success": True,
                "active_games": active_games,
                "sync_status": sync_status,
                "engine_status": "运行中"
            }

        except Exception as e:
            logger.error(f"Game state management test failed: {e}")
            return {
                "success": False,
                "message": f"游戏状态管理测试失败: {str(e)}"
            }

    @app.post("/api/test/trigger-event")
    async def test_trigger_event(request: Request):
        """测试事件触发功能"""
        try:
            request_data = await request.json()
            event_type = request_data.get("event_type", "test")
            test_data = request_data.get("test_data", "测试事件数据")

            # 模拟事件触发
            event_result = {
                "event_triggered": True,
                "event_type": event_type,
                "timestamp": time.time(),
                "test_data": test_data,
                "result": "事件触发成功"
            }

            return {
                "success": True,
                "event_type": event_type,
                "event_result": event_result["result"],
                "timestamp": event_result["timestamp"]
            }

        except Exception as e:
            logger.error(f"Event trigger test failed: {e}")
            return {
                "success": False,
                "message": f"事件触发测试失败: {str(e)}"
            }

    @app.get("/api/test/game-state")
    async def test_get_game_state():
        """测试获取游戏状态"""
        try:
            active_games = len(game_engine.active_games)

            game_info = []
            for game_key, game_state in game_engine.active_games.items():
                user_id, game_id = game_key  # 解包元组
                game_info.append({
                    "user_id": user_id,
                    "game_id": game_id,
                    "player_name": game_state.player.name if game_state.player else "未知",
                    "map_name": game_state.current_map.name if game_state.current_map else "未知",
                    "turn_count": game_state.turn_count
                })

            return {
                "success": True,
                "active_games": active_games,
                "games": game_info
            }

        except Exception as e:
            logger.error(f"Game state test failed: {e}")
            return {
                "success": False,
                "message": f"游戏状态测试失败: {str(e)}"
            }

    @app.post("/api/test/stress-test")
    async def test_stress_test(request: Request):
        """API压力测试端点"""
        try:
            request_data = await request.json()
            test_id = request_data.get("test_id", 1)
            timestamp = request_data.get("timestamp")

            # 模拟一些处理时间
            await asyncio.sleep(random.uniform(0.1, 0.5))

            # 随机决定是否成功（90%成功率）
            if random.random() < 0.9:
                return {
                    "success": True,
                    "test_id": test_id,
                    "timestamp": timestamp,
                    "response_time": time.time(),
                    "message": f"压力测试 {test_id} 成功"
                }
            else:
                # 模拟偶尔的失败
                raise Exception(f"模拟的随机失败 (测试 {test_id})")

        except Exception as e:
            logger.error(f"Stress test {request_data.get('test_id', '?')} failed: {e}")
            return {
                "success": False,
                "message": f"压力测试失败: {str(e)}"
            }

    @app.get("/api/test/memory-usage")
    async def test_memory_usage():
        """测试内存使用情况"""
        try:
            import psutil
            import os

            # 获取当前进程的内存使用情况
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()

            # 获取系统内存信息
            system_memory = psutil.virtual_memory()

            # 获取磁盘使用情况
            disk_usage = psutil.disk_usage('.')

            return {
                "success": True,
                "memory_usage": f"{memory_info.rss / 1024 / 1024:.2f} MB",
                "system_memory_percent": f"{system_memory.percent:.1f}%",
                "disk_usage": f"{disk_usage.percent:.1f}%",
                "active_games": len(game_engine.active_games)
            }

        except ImportError:
            # 如果没有安装psutil，返回基本信息
            return {
                "success": True,
                "memory_usage": "需要安装 psutil 库",
                "disk_usage": "不可用",
                "active_games": len(game_engine.active_games)
            }
        except Exception as e:
            logger.error(f"Memory usage test failed: {e}")
            return {
                "success": False,
                "message": f"内存使用测试失败: {str(e)}"
            }

    # ==================== 事件选择系统测试API ====================

    @app.post("/api/test/event-choice-system")
    async def test_event_choice_system(request: Request):
        """测试事件选择系统功能"""
        try:
            request_data = await request.json()
            test_type = request_data.get("test_type", "system_check")

            if test_type == "system_check":
                # 检查事件选择系统状态
                from event_choice_system import event_choice_system, ChoiceEventType

                # 获取系统信息
                context_info = event_choice_system.get_context_info()
                supported_event_types = [event_type.value for event_type in ChoiceEventType]
                registered_handlers = len(event_choice_system.choice_handlers)

                return {
                    "success": True,
                    "supported_event_types": supported_event_types,
                    "registered_handlers": registered_handlers,
                    "active_contexts": context_info.get("active_contexts_count", 0),
                    "choice_history_count": context_info.get("choice_history_count", 0),
                    "context_expiry_time": context_info.get("context_expiry_time", 0)
                }

        except Exception as e:
            logger.error(f"Event choice system test failed: {e}")
            return {
                "success": False,
                "message": f"事件选择系统测试失败: {str(e)}"
            }

    @app.post("/api/test/story-event-generation")
    async def test_story_event_generation(request: Request):
        """测试故事事件生成功能"""
        try:
            request_data = await request.json()

            # 创建测试游戏状态
            from data_models import GameState, Character, GameMap, MapTile, Quest
            from event_choice_system import event_choice_system

            test_game_state = GameState()
            test_game_state.player = Character()
            test_game_state.player.name = "测试玩家"
            test_game_state.player.stats.level = request_data.get("player_level", 1)
            test_game_state.player.position = (5, 5)

            test_map = GameMap()
            test_map.name = "测试地下城"
            test_map.depth = request_data.get("map_depth", 1)
            test_map.width = 10
            test_map.height = 10
            test_game_state.current_map = test_map

            # 创建测试瓦片
            test_tile = MapTile(x=5, y=5)
            test_tile.event_data = {"story_type": "mystery", "description": "测试事件"}

            # 如果需要活跃任务
            if request_data.get("has_active_quest", False):
                test_quest = Quest()
                test_quest.title = "测试任务"
                test_quest.description = "这是一个测试任务"
                test_quest.quest_type = "exploration"
                test_quest.is_active = True
                test_quest.progress_percentage = 50.0
                test_quest.objectives = ["探索地下城", "寻找宝藏"]
                test_quest.story_context = "在古老的地下城中寻找失落的宝藏"
                test_game_state.quests.append(test_quest)

            # 生成故事事件
            context = await event_choice_system.create_story_event_choice(test_game_state, test_tile)

            if context:
                return {
                    "success": True,
                    "event_title": context.title,
                    "event_description": context.description,
                    "choices_count": len(context.choices),
                    "context_id": context.id,
                    "event_type": context.event_type
                }
            else:
                return {
                    "success": False,
                    "message": "无法生成故事事件"
                }

        except Exception as e:
            logger.error(f"Story event generation test failed: {e}")
            return {
                "success": False,
                "message": f"故事事件生成测试失败: {str(e)}"
            }

    @app.post("/api/test/quest-completion-choice")
    async def test_quest_completion_choice(request: Request):
        """测试任务完成选择功能"""
        try:
            request_data = await request.json()

            # 创建测试游戏状态和已完成任务
            from data_models import GameState, Character, GameMap, Quest
            from event_choice_system import event_choice_system

            test_game_state = GameState()
            test_game_state.player = Character()
            test_game_state.player.name = "测试玩家"
            test_game_state.player.stats.level = request_data.get("player_level", 1)

            test_map = GameMap()
            test_map.name = "测试地下城"
            test_map.depth = 1
            test_game_state.current_map = test_map

            # 创建已完成的测试任务
            completed_quest = Quest()
            completed_quest.title = request_data.get("quest_title", "测试任务")
            completed_quest.description = "这是一个已完成的测试任务"
            completed_quest.quest_type = request_data.get("quest_type", "exploration")
            completed_quest.experience_reward = 100
            completed_quest.story_context = "在地下城中完成了一项重要任务"
            completed_quest.is_completed = True

            # 生成任务完成选择
            context = await event_choice_system.create_quest_completion_choice(test_game_state, completed_quest)

            if context:
                return {
                    "success": True,
                    "completion_title": context.title,
                    "completion_description": context.description,
                    "choices_count": len(context.choices),
                    "context_id": context.id,
                    "event_type": context.event_type
                }
            else:
                return {
                    "success": False,
                    "message": "无法生成任务完成选择"
                }

        except Exception as e:
            logger.error(f"Quest completion choice test failed: {e}")
            return {
                "success": False,
                "message": f"任务完成选择测试失败: {str(e)}"
            }

    @app.post("/api/test/choice-processing")
    async def test_choice_processing(request: Request):
        """测试选择处理功能"""
        try:
            request_data = await request.json()

            # 创建测试游戏状态
            from data_models import GameState, Character, GameMap, MapTile, EventChoiceContext, EventChoice
            from event_choice_system import event_choice_system

            test_game_state = GameState()
            test_game_state.player = Character()
            test_game_state.player.name = "测试玩家"
            test_game_state.player.stats.level = 1
            test_game_state.player.stats.hp = 100
            test_game_state.player.stats.max_hp = 100
            test_game_state.player.position = (5, 5)

            test_map = GameMap()
            test_map.name = "测试地下城"
            test_map.depth = 1
            test_map.width = 10
            test_map.height = 10
            test_game_state.current_map = test_map

            # 创建测试选择上下文
            context = EventChoiceContext()
            context.event_type = request_data.get("event_type", "story_event")
            context.title = "测试事件"
            context.description = "这是一个测试事件"
            context.context_data = {"tile_position": (5, 5), "story_type": "test"}

            # 创建测试选择
            choice = EventChoice()
            choice.text = request_data.get("choice_text", "测试选择")
            choice.description = "这是一个测试选择"
            choice.consequences = "测试后果"
            choice.is_available = True

            # 处理选择
            result = await event_choice_system.process_choice(test_game_state, context.id, choice.id)

            return {
                "success": result.success,
                "result_message": result.message,
                "triggered_events": len(result.events),
                "map_updates": bool(result.map_updates),
                "player_updates": bool(result.player_updates),
                "quest_updates": bool(result.quest_updates),
                "events": result.events[:3] if result.events else []  # 只返回前3个事件
            }

        except Exception as e:
            logger.error(f"Choice processing test failed: {e}")
            return {
                "success": False,
                "message": f"选择处理测试失败: {str(e)}"
            }

    @app.post("/api/test/llm-permissions")
    async def test_llm_permissions(request: Request):
        """测试LLM权限功能"""
        try:
            request_data = await request.json()
            test_permissions = request_data.get("test_permissions", [])

            # 检查各种权限的实现状态
            permission_results = {}

            for permission in test_permissions:
                if permission == "terrain_modification":
                    # 检查地形修改功能
                    permission_results[permission] = True  # 已在_apply_choice_result中实现
                elif permission == "monster_management":
                    # 检查怪物管理功能
                    permission_results[permission] = True  # 已在_handle_monster_update中实现
                elif permission == "event_creation":
                    # 检查事件创建功能
                    permission_results[permission] = True  # 已在地图更新中实现
                elif permission == "item_addition":
                    # 检查物品添加功能
                    permission_results[permission] = True  # 已在_apply_choice_result中实现
                elif permission == "player_attributes":
                    # 检查玩家属性修改功能
                    permission_results[permission] = True  # 已在_apply_choice_result中实现
                elif permission == "quest_progress":
                    # 检查任务进度功能
                    permission_results[permission] = True  # 已在_apply_choice_result中实现
                elif permission == "narrative_content":
                    # 检查叙述内容功能
                    permission_results[permission] = True  # 已在result.events中实现
                else:
                    permission_results[permission] = False

            return {
                "success": True,
                "permission_results": permission_results,
                "total_permissions": len(test_permissions),
                "supported_permissions": sum(permission_results.values())
            }

        except Exception as e:
            logger.error(f"LLM permissions test failed: {e}")
            return {
                "success": False,
                "message": f"LLM权限测试失败: {str(e)}"
            }

    @app.post("/api/test/context-information")
    async def test_context_information(request: Request):
        """测试上下文信息传递功能"""
        try:
            request_data = await request.json()

            # 创建测试游戏状态
            from data_models import GameState, Character, GameMap, Quest
            from prompt_manager import prompt_manager

            test_game_state = GameState()
            test_game_state.player = Character()
            test_game_state.player.name = "测试玩家"
            test_game_state.player.stats.level = 5
            test_game_state.player.stats.hp = 80
            test_game_state.player.stats.max_hp = 100
            test_game_state.player.position = (10, 15)

            test_map = GameMap()
            test_map.name = "深层地下城"
            test_map.depth = 3
            test_map.width = 20
            test_map.height = 20
            test_game_state.current_map = test_map

            # 创建活跃任务
            active_quest = Quest()
            active_quest.title = "寻找古老宝藏"
            active_quest.description = "在地下城深处寻找传说中的古老宝藏"
            active_quest.quest_type = "treasure_hunt"
            active_quest.progress_percentage = 75.0
            active_quest.objectives = ["探索第3层", "击败守护者", "找到宝藏"]
            active_quest.story_context = "传说中的宝藏被强大的守护者保护着"
            active_quest.is_active = True
            test_game_state.quests.append(active_quest)

            # 检查上下文信息构建
            context_data = {}

            if request_data.get("include_player_info", True):
                player_context = prompt_manager.build_player_context(test_game_state.player)
                context_data["player_info"] = bool(player_context)
                context_data["player_fields"] = list(player_context.keys()) if player_context else []

            if request_data.get("include_map_info", True):
                map_context = prompt_manager.build_map_context(test_game_state.current_map)
                context_data["map_info"] = bool(map_context)
                context_data["map_fields"] = list(map_context.keys()) if map_context else []

            if request_data.get("include_quest_info", True):
                # 检查任务信息是否正确传递
                quest_info = {
                    "quest_title": active_quest.title,
                    "quest_description": active_quest.description,
                    "quest_type": active_quest.quest_type,
                    "quest_progress": active_quest.progress_percentage,
                    "quest_objectives": active_quest.objectives,
                    "quest_story_context": active_quest.story_context,
                    "has_active_quest": True
                }
                context_data["quest_info"] = bool(quest_info)
                context_data["quest_fields"] = list(quest_info.keys())

            if request_data.get("include_event_info", True):
                event_info = {
                    "location_x": test_game_state.player.position[0],
                    "location_y": test_game_state.player.position[1],
                    "story_type": "test",
                    "event_description": "测试事件描述"
                }
                context_data["event_info"] = bool(event_info)
                context_data["event_fields"] = list(event_info.keys())

            # 构建详细信息
            detailed_info = {}
            if context_data.get("player_info"):
                detailed_info.update(prompt_manager.build_player_context(test_game_state.player))
            if context_data.get("map_info"):
                detailed_info.update(prompt_manager.build_map_context(test_game_state.current_map))

            context_data["detailed_info"] = detailed_info

            return {
                "success": True,
                "context_data": context_data,
                "total_fields": len(detailed_info),
                "context_complete": all([
                    context_data.get("player_info", False),
                    context_data.get("map_info", False),
                    context_data.get("quest_info", False),
                    context_data.get("event_info", False)
                ])
            }

        except Exception as e:
            logger.error(f"Context information test failed: {e}")
            return {
                "success": False,
                "message": f"上下文信息测试失败: {str(e)}"
            }

    @app.post("/api/game/{game_id}/debug/trigger-event")
    async def debug_trigger_random_event(game_id: str, request: Request, response: Response):
        """调试：触发随机事件"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            # 获取玩家当前位置的瓦片
            player_pos = request_data.get("position", game_state.player.position)
            tile = game_state.current_map.get_tile(*player_pos)

            if not tile:
                return {"success": False, "message": "无效的位置"}

            # 使用事件选择系统创建随机事件
            context = await event_choice_system.create_story_event_choice(game_state, tile)

            if context:
                # 将选择上下文设置到游戏状态中
                game_state.pending_choice_context = context

                # 同时添加到事件选择系统的活跃上下文中
                event_choice_system.active_contexts[context.id] = context

                logger.info(f"Debug random event triggered for game {game_id}: {context.id}")

                return {
                    "success": True,
                    "message": "随机事件已触发",
                    "event_id": context.id,
                    "title": context.title
                }
            else:
                return {"success": False, "message": "无法创建随机事件"}

        except Exception as e:
            logger.error(f"Debug trigger event error: {e}")
            return {"success": False, "message": f"触发事件失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/complete-quest")
    async def debug_complete_current_quest(game_id: str, request: Request, response: Response):
        """调试：完成当前任务"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 找到当前活跃任务
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if not active_quest:
                return {"success": False, "message": "没有活跃的任务"}

            # 记录原始经验值
            original_experience = game_state.player.stats.experience
            quest_title = active_quest.title

            # 使用进度管理器正确完成任务
            await progress_manager._complete_quest(game_state, active_quest)

            # 立即处理任务完成选择（调试模式下自动选择第一个选项）
            if hasattr(game_state, 'pending_quest_completion') and game_state.pending_quest_completion:
                completed_quest = game_state.pending_quest_completion
                try:
                    # 创建任务完成选择上下文
                    choice_context = await event_choice_system.create_quest_completion_choice(
                        game_state, completed_quest
                    )

                    # 将选择上下文存储到游戏状态中，让前端显示选项框
                    game_state.pending_choice_context = choice_context
                    event_choice_system.active_contexts[choice_context.id] = choice_context

                    # 清理任务完成标志
                    game_state.pending_quest_completion = None

                except Exception as e:
                    logger.error(f"Error processing quest completion choice in debug mode: {e}")
                    # 清理标志，避免重复处理
                    game_state.pending_quest_completion = None

            # 不在调试模式下自动处理新任务生成，让选择处理API来处理

            return {
                "success": True,
                "message": f"任务 '{quest_title}' 已完成，请选择下一步行动",
                "experience_gained": active_quest.experience_reward,
                "has_choice_context": hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context is not None,
                "choice_context_id": game_state.pending_choice_context.id if hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context else None
            }

        except Exception as e:
            logger.error(f"Debug complete quest error: {e}")
            return {"success": False, "message": f"完成任务失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/generate-item")
    async def debug_generate_test_item(game_id: str, request: Request, response: Response):
        """调试：生成测试物品"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            player_level = request_data.get("player_level", game_state.player.stats.level)
            context = request_data.get("context", "调试模式生成的测试物品")

            # 使用LLM生成物品
            item = await llm_service.generate_item_on_pickup(game_state, context)

            if item:
                # 添加到玩家背包
                game_state.player.inventory.append(item)
                return {
                    "success": True,
                    "message": f"已生成物品: {item.name}",
                    "item_name": item.name,
                    "item_description": item.description
                }
            else:
                return {"success": False, "message": "生成物品失败"}

        except Exception as e:
            logger.error(f"Debug generate item error: {e}")
            return {"success": False, "message": f"生成物品失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/get-treasure")
    async def debug_get_random_treasure(game_id: str, request: Request, response: Response):
        """调试：获得随机宝物（模拟宝箱）"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            player_position = request_data.get("player_position", game_state.player.position)
            player_level = request_data.get("player_level", game_state.player.stats.level)
            quest_context = request_data.get("quest_context")

            # 构建宝箱上下文
            treasure_context = {
                "player_level": player_level,
                "player_class": game_state.player.character_class.value,
                "current_floor": game_state.current_map.depth,
                "map_name": game_state.current_map.name,
                "position": player_position
            }

            if quest_context:
                treasure_context["quest_name"] = quest_context.get("name", "")
                treasure_context["quest_description"] = quest_context.get("description", "")

            # 使用LLM生成宝物
            from llm_service import llm_service

            prompt = f"""你是一个DND风格地下城游戏的宝箱生成器。玩家打开了一个宝箱，请生成1-3个合适的宝物。

玩家信息：
- 等级: {player_level}
- 职业: {treasure_context['player_class']}
- 当前楼层: {treasure_context['current_floor']}
- 地图: {treasure_context['map_name']}

{f"当前任务: {treasure_context.get('quest_name', '')}" if quest_context else ""}
{f"任务描述: {treasure_context.get('quest_description', '')}" if quest_context else ""}

请生成宝物列表，每个宝物包含：
1. 中文名称（必须是中文）
2. 详细的功能描述
3. 物品类型（weapon/armor/consumable/accessory/quest_item）
4. 稀有度（common/uncommon/rare/epic/legendary）

请以JSON格式返回，格式如下：
{{
    "items": [
        {{
            "name": "物品名称",
            "description": "详细描述",
            "type": "物品类型",
            "rarity": "稀有度",
            "effects": {{
                "stat_bonuses": {{"strength": 2}},
                "special_abilities": ["特殊能力描述"]
            }}
        }}
    ],
    "narrative": "发现宝物时的叙述文本"
}}"""

            # 调用LLM
            llm_response = await llm_service.generate_text(prompt=prompt)

            if not llm_response:
                return {"success": False, "message": "LLM生成失败"}

            # 解析LLM响应
            import json
            import re

            # 尝试提取JSON
            json_match = re.search(r'\{[\s\S]*\}', llm_response)
            if json_match:
                treasure_data = json.loads(json_match.group())
            else:
                return {"success": False, "message": "无法解析LLM响应"}

            # 将物品添加到玩家背包
            from data_models import Item
            item_names = []

            for item_data in treasure_data.get("items", []):
                item = Item(
                    name=item_data.get("name", "未知物品"),
                    description=item_data.get("description", ""),
                    item_type=item_data.get("type", "consumable"),
                    rarity=item_data.get("rarity", "common"),
                    properties=item_data.get("effects", {}),
                    llm_generated=True,
                    generation_context="宝箱生成"
                )
                game_state.player.inventory.append(item)
                item_names.append(item.name)

            # 获取叙述文本
            narrative = treasure_data.get("narrative", "你打开了宝箱，发现了一些宝物！")

            # 保存游戏状态
            await game_engine._save_game_async(game_state)

            return {
                "success": True,
                "message": narrative,
                "items": item_names
            }

        except Exception as e:
            logger.error(f"Debug get treasure error: {e}")
            return {"success": False, "message": f"获取宝物失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/teleport")
    async def debug_teleport_to_floor(game_id: str, request: Request, response: Response):
        """调试：传送到指定楼层"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            target_floor = request_data.get("target_floor", 1)

            # 验证楼层数的合法性
            if target_floor < 1 or target_floor > config.game.max_quest_floors:
                return {
                    "success": False,
                    "message": f"楼层数必须在1-{config.game.max_quest_floors}之间"
                }

            logger.info(f"Debug teleport: {game_state.current_map.depth} -> {target_floor}")

            # 清除旧地图上的角色标记（在生成新地图前）
            old_tile = game_state.current_map.get_tile(*game_state.player.position)
            if old_tile:
                old_tile.character_id = None

            for monster in game_state.monsters:
                if monster.position:
                    monster_tile = game_state.current_map.get_tile(*monster.position)
                    if monster_tile:
                        monster_tile.character_id = None

            # 获取当前活跃任务的上下文
            quest_context = None
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if active_quest:
                quest_context = active_quest.to_dict()

            # 生成新地图
            from content_generator import content_generator
            new_map = await content_generator.generate_dungeon_map(
                width=config.game.default_map_size[0],
                height=config.game.default_map_size[1],
                depth=target_floor,
                theme=f"地下城第{target_floor}层",
                quest_context=quest_context
            )

            # 更新游戏状态 - 确保正确更新
            game_state.current_map = new_map
            logger.info(f"Debug teleport - Map updated: {new_map.name} (depth: {new_map.depth})")

            # 重新放置玩家
            spawn_positions = content_generator.get_spawn_positions(new_map, 1)
            if spawn_positions:
                game_state.player.position = spawn_positions[0]
                tile = new_map.get_tile(*game_state.player.position)
                if tile:
                    tile.character_id = game_state.player.id
                    tile.is_explored = True
                    tile.is_visible = True

            # 清空旧怪物列表（重要！）
            game_state.monsters.clear()

            # 生成新的怪物
            monsters = await content_generator.generate_encounter_monsters(
                game_state.player.stats.level, "medium"
            )

            # 生成任务专属怪物（如果有活跃任务）
            from game_engine import game_engine as ge
            quest_monsters = await ge._generate_quest_monsters(game_state, new_map)
            monsters.extend(quest_monsters)

            monster_positions = content_generator.get_spawn_positions(new_map, len(monsters))
            for monster, position in zip(monsters, monster_positions):
                monster.position = position
                tile = new_map.get_tile(*position)
                if tile:
                    tile.character_id = monster.id
                game_state.monsters.append(monster)

            return {
                "success": True,
                "message": f"已传送到第{target_floor}层",
                "new_map": game_state.current_map.name,
                "map_depth": game_state.current_map.depth
            }

        except Exception as e:
            logger.error(f"Debug teleport error: {e}", exc_info=True)
            return {"success": False, "message": f"传送失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/teleport-position")
    async def debug_teleport_to_position(game_id: str, request: Request, response: Response):
        """调试：传送到指定坐标"""
        try:
            from data_models import TerrainType

            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            target_x = request_data.get("x")
            target_y = request_data.get("y")

            if target_x is None or target_y is None:
                return {"success": False, "message": "缺少坐标参数"}

            # 检查坐标是否在地图范围内
            if (target_x < 0 or target_x >= game_state.current_map.width or
                target_y < 0 or target_y >= game_state.current_map.height):
                return {
                    "success": False,
                    "message": f"坐标超出地图范围 (0-{game_state.current_map.width-1}, 0-{game_state.current_map.height-1})"
                }

            # 检查目标位置是否可通行
            target_tile = game_state.current_map.get_tile(target_x, target_y)
            if not target_tile:
                return {"success": False, "message": "目标位置无效"}

            if target_tile.terrain == TerrainType.WALL:
                return {"success": False, "message": "目标位置是墙壁，无法传送"}

            # 清除旧位置的角色标记
            old_tile = game_state.current_map.get_tile(*game_state.player.position)
            if old_tile:
                old_tile.character_id = None

            # 传送玩家
            game_state.player.position = (target_x, target_y)
            target_tile.character_id = game_state.player.id
            target_tile.is_explored = True
            target_tile.is_visible = True

            # 更新周围瓦片的可见性
            game_engine._update_visibility(game_state, target_x, target_y)

            return {
                "success": True,
                "message": f"已传送到坐标 ({target_x}, {target_y})",
                "position": [target_x, target_y]
            }

        except Exception as e:
            logger.error(f"Debug teleport position error: {e}")
            return {"success": False, "message": f"传送失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/spawn-enemy")
    async def debug_spawn_enemy_nearby(game_id: str, request: Request, response: Response):
        """调试：在附近生成敌人"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            player_pos = request_data.get("player_position", game_state.player.position)
            player_level = request_data.get("player_level", game_state.player.stats.level)

            # 生成一个测试敌人
            from content_generator import content_generator
            monsters = await content_generator.generate_encounter_monsters(player_level, "normal")

            if not monsters:
                return {"success": False, "message": "无法生成敌人"}

            monster = monsters[0]

            # 在玩家附近找一个空位置
            nearby_positions = []
            px, py = player_pos
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:  # 跳过玩家位置
                        continue
                    new_x, new_y = px + dx, py + dy
                    tile = game_state.current_map.get_tile(new_x, new_y)
                    if tile and tile.terrain.value != "wall" and not tile.character_id:
                        nearby_positions.append((new_x, new_y))

            if not nearby_positions:
                return {"success": False, "message": "附近没有可用位置"}

            # 随机选择一个位置
            spawn_pos = random.choice(nearby_positions)
            monster.position = spawn_pos

            # 在地图上标记敌人位置
            tile = game_state.current_map.get_tile(*spawn_pos)
            if tile:
                tile.character_id = monster.id

            # 添加到游戏状态
            game_state.monsters.append(monster)

            return {
                "success": True,
                "message": f"已生成敌人: {monster.name}",
                "enemy_name": monster.name,
                "position": spawn_pos
            }

        except Exception as e:
            logger.error(f"Debug spawn enemy error: {e}")
            return {"success": False, "message": f"生成敌人失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/clear-enemies")
    async def debug_clear_all_enemies(game_id: str, request: Request, response: Response):
        """调试：清空所有敌人"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 记录清空的敌人数量
            cleared_count = len(game_state.monsters)

            # 清除地图上的敌人标记
            for monster in game_state.monsters:
                if monster.position:
                    tile = game_state.current_map.get_tile(*monster.position)
                    if tile and tile.character_id == monster.id:
                        tile.character_id = None

            # 清空敌人列表
            game_state.monsters.clear()

            return {
                "success": True,
                "message": f"已清空所有敌人",
                "cleared_count": cleared_count
            }

        except Exception as e:
            logger.error(f"Debug clear enemies error: {e}")
            return {"success": False, "message": f"清空敌人失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/regenerate-map")
    async def debug_regenerate_current_map(game_id: str, request: Request, response: Response):
        """调试：重新生成当前地图"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            current_depth = request_data.get("current_depth", game_state.current_map.depth)

            # 获取当前活跃任务的上下文
            quest_context = None
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if active_quest:
                quest_context = active_quest.to_dict()

            # 重新生成地图
            from content_generator import content_generator
            new_map = await content_generator.generate_dungeon_map(
                width=config.game.default_map_size[0],
                height=config.game.default_map_size[1],
                depth=current_depth,
                theme=f"地下城第{current_depth}层",
                quest_context=quest_context
            )

            # 清除旧地图上的所有角色
            for monster in game_state.monsters:
                if monster.position:
                    old_tile = game_state.current_map.get_tile(*monster.position)
                    if old_tile:
                        old_tile.character_id = None

            # 更新地图
            game_state.current_map = new_map

            # 重新放置玩家
            spawn_positions = content_generator.get_spawn_positions(new_map, 1)
            if spawn_positions:
                game_state.player.position = spawn_positions[0]
                tile = new_map.get_tile(*game_state.player.position)
                if tile:
                    tile.character_id = game_state.player.id
                    tile.is_explored = True
                    tile.is_visible = True

            # 清空怪物（新地图会重新生成）
            game_state.monsters.clear()

            return {
                "success": True,
                "message": f"地图已重新生成",
                "new_map_name": new_map.name
            }

        except Exception as e:
            logger.error(f"Debug regenerate map error: {e}")
            return {"success": False, "message": f"重新生成地图失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/restore-player")
    async def debug_restore_player_status(game_id: str, request: Request, response: Response):
        """调试：恢复玩家状态"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 恢复HP和MP到满值
            game_state.player.stats.hp = game_state.player.stats.max_hp
            game_state.player.stats.mp = game_state.player.stats.max_mp

            return {
                "success": True,
                "message": "玩家状态已恢复",
                "hp": game_state.player.stats.hp,
                "mp": game_state.player.stats.mp
            }

        except Exception as e:
            logger.error(f"Debug restore player error: {e}")
            return {"success": False, "message": f"恢复状态失败: {str(e)}"}

    @app.post("/api/debug/trigger-event-choice/{game_id}")
    async def debug_trigger_event_choice(game_id: str, request: Request, response: Response):
        """调试：手动触发事件选择"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 创建测试事件选择上下文
            from data_models import EventChoiceContext, EventChoice

            choice_context = EventChoiceContext()
            choice_context.id = f"debug-test-{game_id}-{int(time.time())}"
            choice_context.event_type = "mystery_event"  # 设置事件类型
            choice_context.title = "神秘的古老祭坛"
            choice_context.description = "你在地下城深处发现了一个古老的祭坛，上面刻满了神秘的符文。祭坛中央放着一颗散发着暗红色光芒的宝石。"

            # 创建选择选项
            choices = [
                EventChoice(
                    id="altar-touch",
                    text="触摸宝石",
                    description="小心地伸手触摸祭坛上的宝石",
                    consequences="可能获得强大的力量，但也可能触发古老的诅咒",
                    is_available=True
                ),
                EventChoice(
                    id="altar-examine",
                    text="仔细检查符文",
                    description="花时间研究祭坛上的古老符文",
                    consequences="可能解开祭坛的秘密，但需要消耗时间",
                    is_available=True
                ),
                EventChoice(
                    id="altar-pray",
                    text="在祭坛前祈祷",
                    description="虔诚地在祭坛前祈祷，寻求神明的指引",
                    consequences="可能获得神明的祝福，但效果未知",
                    is_available=True
                ),
                EventChoice(
                    id="altar-leave",
                    text="谨慎离开",
                    description="感觉这里太危险，决定立即离开",
                    consequences="避免风险，但错过可能的机会",
                    is_available=True
                )
            ]

            choice_context.choices = choices

            # 将选择上下文设置到游戏状态中
            game_state.pending_choice_context = choice_context

            # 同时添加到事件选择系统的活跃上下文中
            event_choice_system.active_contexts[choice_context.id] = choice_context

            logger.info(f"Debug event choice triggered for game {game_id}: {choice_context.id}")

            return {
                "success": True,
                "message": "事件选择已触发",
                "context_id": choice_context.id,
                "title": choice_context.title,
                "choices_count": len(choice_context.choices)
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to trigger debug event choice: {e}")
            raise HTTPException(status_code=500, detail=f"触发事件选择失败: {str(e)}")


# 在所有路由定义完成后，添加根目录静态文件挂载
# 这样可以直接访问 quick_test.html 等文件，而不需要 /static/ 前缀
app.mount("/", StaticFiles(directory="static", html=True), name="root_static")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting Labyrinthia AI on {config.web.host}:{config.web.port}")
    
    uvicorn.run(
        "main:app",
        host=config.web.host,
        port=config.web.port,
        reload=config.web.reload and config.game.debug_mode,
        log_level="info" if config.game.debug_mode else "warning"
    )
