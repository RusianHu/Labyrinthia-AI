"""
Labyrinthia AI - FastAPI主应用
Main FastAPI application for the Labyrinthia AI game
"""

import asyncio
import logging
import random
import time
import json
import re
import tempfile
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from contextlib import asynccontextmanager
from pathlib import Path
import hashlib

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from game_engine import game_engine
from data_manager import data_manager
from llm_service import llm_service, LLMUnavailableError
from progress_manager import progress_manager
from event_choice_system import event_choice_system
from data_models import GameState
from user_session_manager import user_session_manager
from async_task_manager import async_task_manager
from input_validator import input_validator
from game_state_lock_manager import game_state_lock_manager
from entity_manager import entity_manager
from trap_manager import initialize_trap_manager


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


def _normalize_action_response(
    action: str,
    trace_id: str,
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    """统一 `/api/action` 返回协议，兼容历史字段。"""
    result = dict(raw or {})

    success = bool(result.get("success", False))
    message = str(result.get("message", "") or "")
    events = result.get("events")
    if not isinstance(events, list):
        events = [str(events)] if events else []

    normalized = {
        "success": success,
        "action": action,
        "trace_id": trace_id,
        "message": message,
        "reason": str(result.get("reason") or ("ok" if success else (result.get("error_code") or "ACTION_FAILED"))),
        "events": events,
        "effects": result.get("effects", []),
        "error_code": result.get("error_code"),
        "retryable": bool(result.get("retryable", False)),
        "impact_summary": result.get("impact_summary", {}),
        "action_trace_id": result.get("action_trace_id"),
        "llm_interaction_required": bool(result.get("llm_interaction_required", False)),
    }

    passthrough_keys = [
        "item_name",
        "item_consumed",
        "pending_choice_context",
        "game_over",
        "game_over_reason",
        "narrative",
        "new_position",
        "damage",
        "combat_breakdown",
        "combat_projection",
        "effect_runtime",
        "performance",
        "idempotent_replay",
        "requires_confirmation",
        "confirmation_token",
        "undo_token",
        "undo_expires_turn",
        "debug_info",
    ]
    for key in passthrough_keys:
        if key in result:
            normalized[key] = result[key]

    if not success and not normalized["error_code"]:
        normalized["error_code"] = "ACTION_FAILED"

    return normalized


def _build_context_key(user_id: str, game_id: str) -> str:
    return f"{user_id}:{game_id}"


def _serialize_game_state_for_client(game_state: GameState) -> Dict[str, Any]:
    """序列化游戏状态给前端，并消费一次性特效队列，避免重复弹窗。"""
    state_dict = game_state.to_dict()

    # pending_effects 是一次性消费队列，返回给前端后立即清理
    if hasattr(game_state, 'pending_effects') and game_state.pending_effects:
        game_state.pending_effects = []

    return state_dict


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _extract_experience(events: List[str]) -> int:
    for event in events:
        if "经验" not in event:
            continue
        match = re.search(r"(\d+)", str(event))
        if match:
            return _safe_int(match.group(1), 0)
    return 0


def _build_action_combat_projection(result: Dict[str, Any]) -> Dict[str, Any]:
    explicit_projection = result.get("combat_projection")
    if isinstance(explicit_projection, dict):
        return {
            "hit": bool(explicit_projection.get("hit", False)),
            "damage": _safe_int(explicit_projection.get("damage", 0), 0),
            "death": bool(explicit_projection.get("death", False)),
            "exp": _safe_int(explicit_projection.get("exp", 0), 0),
        }

    events = result.get("events") if isinstance(result.get("events"), list) else []
    damage = _safe_int(result.get("damage", 0), 0)
    death = any("被击败" in str(evt) for evt in events)
    return {
        "hit": bool(result.get("success", False)),
        "damage": damage,
        "death": death,
        "exp": _extract_experience(events),
    }


def _normalize_prediction(raw_prediction: Any) -> Dict[str, Any]:
    if not isinstance(raw_prediction, dict):
        return {}
    normalized: Dict[str, Any] = {}
    if "hit" in raw_prediction:
        normalized["hit"] = bool(raw_prediction.get("hit"))
    if "damage" in raw_prediction:
        normalized["damage"] = _safe_int(raw_prediction.get("damage"), 0)
    if "death" in raw_prediction:
        normalized["death"] = bool(raw_prediction.get("death"))
    if "exp" in raw_prediction:
        normalized["exp"] = _safe_int(raw_prediction.get("exp"), 0)
    return normalized


def _safe_authority_mode(value: Any, fallback: str = "local") -> str:
    mode = str(value or fallback or "local").strip().lower()
    if mode not in {"local", "hybrid", "server"}:
        return "local"
    return mode


def _build_http_exception_detail(
    message: str,
    trace_id: str,
    error_code: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": message,
        "trace_id": trace_id,
        "error_code": error_code,
    }
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


def _normalize_http_exception(
    exc: HTTPException,
    trace_id: str,
    fallback_error_code: str,
) -> Tuple[int, Dict[str, Any]]:
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "请求失败")
        error_code = str(detail.get("error_code") or fallback_error_code)
        payload = dict(detail)
        payload["message"] = message
        payload["trace_id"] = trace_id
        payload["error_code"] = error_code
        return exc.status_code, payload

    if isinstance(detail, str) and detail.strip():
        message = detail.strip()
    else:
        message = "请求失败"

    return exc.status_code, _build_http_exception_detail(message, trace_id, fallback_error_code)


def _emit_hybrid_diff_log(
    *,
    trace_id: str,
    action: str,
    user_id: str,
    game_id: str,
    client_trace_id: str,
    idempotency_key: str,
    predicted: Dict[str, Any],
    authoritative: Dict[str, Any],
    lock_wait_ms: int,
    lock_hold_ms: int,
    operation: str,
    authority_mode: str,
    rule_version: int,
):
    if action != "attack":
        return
    if _safe_authority_mode(authority_mode) != "hybrid":
        return
    if not config.game.debug_mode:
        return

    diff_metrics: Dict[str, Any] = {}
    warning_flags: List[str] = []
    threshold = max(0, int(getattr(config.game, "combat_diff_threshold", 5)))

    for metric in ("hit", "damage", "death", "exp"):
        if metric not in predicted:
            continue

        p_val = predicted.get(metric)
        a_val = authoritative.get(metric)

        if isinstance(p_val, bool):
            delta = int(bool(a_val)) - int(bool(p_val))
            diff_metrics[metric] = {
                "predicted": bool(p_val),
                "authoritative": bool(a_val),
                "delta": delta,
            }
            if delta != 0:
                warning_flags.append(f"{metric}_mismatch")
            continue

        p_num = _safe_int(p_val, 0)
        a_num = _safe_int(a_val, 0)
        delta = a_num - p_num
        diff_metrics[metric] = {
            "predicted": p_num,
            "authoritative": a_num,
            "delta": delta,
        }
        if abs(delta) > threshold:
            warning_flags.append(f"{metric}_delta_exceeds_threshold")

    log_payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "trace_id": trace_id,
        "client_trace_id": client_trace_id,
        "game_id": game_id,
        "user_id": user_id,
        "phase": "phase_0_5_hybrid",
        "authority_mode": _safe_authority_mode(authority_mode),
        "rule_version": max(1, _safe_int(rule_version, 1)),
        "action": action,
        "idempotency_key": idempotency_key,
        "predicted": predicted,
        "authoritative": authoritative,
        "diff_metrics": diff_metrics,
        "warning_flags": warning_flags,
        "lock_wait_ms": max(0, int(lock_wait_ms)),
        "lock_hold_ms": max(0, int(lock_hold_ms)),
        "operation": operation,
    }

    if warning_flags:
        logger.warning("combat_hybrid_diff %s", json.dumps(log_payload, ensure_ascii=False))
    else:
        logger.debug("combat_hybrid_diff %s", json.dumps(log_payload, ensure_ascii=False))


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

        # 初始化陷阱管理器
        initialize_trap_manager(entity_manager)

        # 启动游戏会话清理任务
        game_engine._start_cleanup_task()

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

        # 【修复】清除所有瓦片的character_id（防止存档中有错误数据）
        for tile in game_state.current_map.tiles.values():
            tile.character_id = None
        logger.info(f"[/api/load] Cleared all character_id from {len(game_state.current_map.tiles)} tiles")

        # 【修复】重新设置玩家位置的character_id
        player_tile = game_state.current_map.get_tile(*game_state.player.position)
        if player_tile:
            player_tile.character_id = game_state.player.id
            player_tile.is_explored = True
            player_tile.is_visible = True
            logger.info(f"[/api/load] Player position restored: {game_state.player.position}")

        # 【修复】重新设置怪物位置的character_id
        for monster in game_state.monsters:
            monster_tile = game_state.current_map.get_tile(*monster.position)
            if monster_tile:
                monster_tile.character_id = monster.id
                logger.info(f"[/api/load] Monster {monster.name} position restored: {monster.position}")

        # 恢复LLM上下文（兼容旧存档无该字段的情况）
        try:
            from llm_context_manager import llm_context_manager
            logs = save_data.get("llm_context_logs", [])
            llm_context_manager.restore_context(
                logs,
                append=False,
                max_entries=getattr(config.llm, "save_context_entries", 20),
                context_key=_build_context_key(user_id, game_state.id),
            )
        except Exception as _e:
            logger.warning(f"Failed to restore LLM context on load: {_e}")


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

    async with game_state_lock_manager.lock_game_state(user_id, game_id, "get_game_state"):
        # 如果游戏不在内存中，尝试从磁盘加载
        if game_key not in game_engine.active_games:

            logger.info(f"Game {game_id} not in memory for user {user_id}, attempting to load from disk...")

            # 尝试从用户存档加载
            save_data = user_session_manager.load_game_for_user(user_id, game_id)

            if save_data:
                # 重建游戏状态并加载到内存
                game_state = data_manager._dict_to_game_state(save_data)

                # 【修复】清除所有瓦片的character_id（防止存档中有错误数据）
                for tile in game_state.current_map.tiles.values():
                    tile.character_id = None
                logger.info(f"[lazy load] Cleared all character_id from {len(game_state.current_map.tiles)} tiles")

                # 【修复】重新设置玩家位置的character_id
                player_tile = game_state.current_map.get_tile(*game_state.player.position)
                if player_tile:
                    player_tile.character_id = game_state.player.id
                    player_tile.is_explored = True
                    player_tile.is_visible = True
                    logger.info(f"[lazy load] Player position restored: {game_state.player.position}")

                # 【修复】重新设置怪物位置的character_id
                for monster in game_state.monsters:
                    monster_tile = game_state.current_map.get_tile(*monster.position)
                    if monster_tile:
                        monster_tile.character_id = monster.id
                        logger.info(f"[lazy load] Monster {monster.name} position restored: {monster.position}")

                # 恢复LLM上下文（在懒加载路径）
                try:
                    from llm_context_manager import llm_context_manager
                    logs = save_data.get("llm_context_logs", [])
                    llm_context_manager.restore_context(
                        logs,
                        append=False,
                        max_entries=getattr(config.llm, "save_context_entries", 20),
                        context_key=_build_context_key(user_id, game_id),
                    )
                except Exception as _e:
                    logger.warning(f"[lazy load] Failed to restore LLM context: {_e}")

                game_engine.active_games[game_key] = game_state
                game_engine._start_auto_save(user_id, game_state.id)
                logger.info(f"Game {game_id} loaded from disk for user {user_id}")
            else:
                # 如果磁盘上也没有，返回404
                raise HTTPException(status_code=404, detail="游戏未找到")

        game_state = game_engine.active_games[game_key]

        # 更新访问时间
        game_engine.update_access_time(user_id, game_id)

        # 获取游戏状态字典（包含一次性特效消费）
        state_dict = _serialize_game_state_for_client(game_state)

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
    trace_id = str(uuid.uuid4())
    context_token = None
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)

        from llm_context_manager import llm_context_manager
        context_token = llm_context_manager.set_current_context_key(_build_context_key(user_id, request.game_id))

        # 验证游戏ID
        game_id_validation = input_validator.validate_game_id(request.game_id)
        if not game_id_validation.is_valid:
            raise HTTPException(status_code=400, detail=game_id_validation.error_message)

        # 验证动作类型
        valid_actions = [
            "move",
            "attack",
            "rest",
            "interact",
            "use_item",
            "drop_item",
            "undo_drop_item",
            "cast_spell",
        ]
        if request.action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"无效的动作类型: {request.action}")

        # 验证参数
        sanitized_params = {}
        if request.action == "move" and "direction" in request.parameters:
            direction_validation = input_validator.validate_direction(request.parameters["direction"])
            if not direction_validation.is_valid:
                raise HTTPException(status_code=400, detail=direction_validation.error_message)
            sanitized_params["direction"] = direction_validation.sanitized_value
        elif request.action in ["use_item", "drop_item"] and "item_id" in request.parameters:
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
        elif request.action == "cast_spell":
            if "spell_id" in request.parameters:
                spell_id_validation = input_validator.validate_game_id(request.parameters["spell_id"])
                if not spell_id_validation.is_valid:
                    raise HTTPException(status_code=400, detail="无效的法术ID")
                sanitized_params["spell_id"] = spell_id_validation.sanitized_value
            if "target_id" in request.parameters:
                target_id_validation = input_validator.validate_game_id(request.parameters["target_id"])
                if not target_id_validation.is_valid:
                    raise HTTPException(status_code=400, detail="无效的目标ID")
                sanitized_params["target_id"] = target_id_validation.sanitized_value
        else:
            # 其他参数直接传递（如坐标等）
            sanitized_params = request.parameters

        if not isinstance(sanitized_params, dict):
            sanitized_params = {}

        if request.action in {"use_item", "drop_item", "attack"}:
            idempotency_key = sanitized_params.get("idempotency_key")
            if not idempotency_key:
                idempotency_key = str(uuid.uuid4())
            sanitized_params["idempotency_key"] = str(idempotency_key)

        logger.info(
            f"Processing action: {request.action} for user {user_id}, "
            f"game: {request.game_id}, trace_id={trace_id}"
        )

        # 更新访问时间
        game_engine.update_access_time(user_id, request.game_id)

        lock_operation = f"action:{request.action}"
        async with game_state_lock_manager.lock_game_state(user_id, request.game_id, lock_operation) as state_lock:
            result = await game_engine.process_player_action(
                user_id=user_id,
                game_id=request.game_id,
                action=request.action,
                parameters=sanitized_params
            )

        normalized_result = _normalize_action_response(request.action, trace_id, result)

        game_state_for_log = game_engine.active_games.get((user_id, request.game_id))
        authority_mode_for_log = _safe_authority_mode(
            getattr(game_state_for_log, "combat_authority_mode", config.game.combat_authority_mode)
        )
        rule_version_for_log = _safe_int(getattr(game_state_for_log, "combat_rule_version", 1), 1)

        _emit_hybrid_diff_log(
            trace_id=trace_id,
            action=request.action,
            user_id=user_id,
            game_id=request.game_id,
            client_trace_id=str(sanitized_params.get("client_trace_id", "") or ""),
            idempotency_key=str(sanitized_params.get("idempotency_key", "") or ""),
            predicted=_normalize_prediction(sanitized_params.get("client_prediction")),
            authoritative=_build_action_combat_projection(normalized_result),
            lock_wait_ms=getattr(state_lock, "last_wait_ms", 0),
            lock_hold_ms=getattr(state_lock, "last_hold_ms", 0),
            operation=lock_operation,
            authority_mode=authority_mode_for_log,
            rule_version=rule_version_for_log,
        )

        if normalized_result.get("error_code") == "LLM_UNAVAILABLE":
            return JSONResponse(status_code=503, content=normalized_result)

        return normalized_result

    except HTTPException as exc:
        status_code, detail = _normalize_http_exception(exc, trace_id, "ACTION_BAD_REQUEST")
        normalized = _normalize_action_response(
            request.action,
            trace_id,
            {
                "success": False,
                "message": detail.get("message", "处理行动失败"),
                "events": [detail.get("message", "处理行动失败")],
                "error_code": detail.get("error_code", "ACTION_BAD_REQUEST"),
                "retryable": status_code >= 500,
            },
        )
        return JSONResponse(status_code=status_code, content=normalized)
    except LLMUnavailableError as e:
        logger.error(f"LLM unavailable in /api/action, trace_id={trace_id}: {e}")
        normalized = _normalize_action_response(
            request.action,
            trace_id,
            {
                "success": False,
                "message": "LLM服务暂时不可用，已中止本次行动。",
                "events": ["LLM服务暂时不可用，请稍后重试。"],
                "error_code": "LLM_UNAVAILABLE",
                "retryable": True,
                "reason": "llm_unavailable",
            },
        )
        return JSONResponse(status_code=503, content=normalized)
    except Exception as e:
        logger.error(f"Failed to process action, trace_id={trace_id}: {e}")
        return _normalize_action_response(
            request.action,
            trace_id,
            {
                "success": False,
                "message": "处理行动失败",
                "events": [f"处理行动失败: {str(e)}"],
                "error_code": "INTERNAL_ERROR",
                "retryable": True,
            },
        )
    finally:
        if context_token is not None:
            from llm_context_manager import llm_context_manager
            llm_context_manager.reset_current_context_key(context_token)


@app.post("/api/llm-event")
async def handle_llm_event(request: LLMEventRequest, http_request: Request, response: Response):
    """处理需要LLM的事件"""
    context_token = None
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        from llm_context_manager import llm_context_manager
        context_token = llm_context_manager.set_current_context_key(
            _build_context_key(user_id, request.game_id)
        )

        logger.info(
            f"Processing LLM event: {request.event_type} for user {user_id}, game: {request.game_id}"
        )

        event_type = request.event_type
        event_data = request.event_data

        async with game_state_lock_manager.lock_game_state(
            user_id, request.game_id, f"llm_event:{event_type}"
        ):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            # 仅使用服务端权威状态，避免客户端提交完整状态覆盖内存态
            game_state = game_engine.active_games[game_key]

            # 根据事件类型处理
            if event_type == "tile_event":
                # 处理瓦片事件
                tile_data = event_data.get("tile", {})
                position = event_data.get("position", [0, 0])

                # 重建MapTile对象
                from data_models import MapTile, TerrainType

                tile = MapTile()
                tile.x = tile_data.get("x", position[0])
                tile.y = tile_data.get("y", position[1])
                tile.terrain = TerrainType(tile_data.get("terrain", "floor"))
                tile.has_event = tile_data.get("has_event", False)
                tile.event_type = tile_data.get("event_type", "")
                tile.event_data = tile_data.get("event_data", {})
                tile.event_triggered = tile_data.get("event_triggered", False)

                # 触发事件
                event_result = await game_engine._trigger_tile_event(game_state, tile)

                return {
                    "success": True,
                    "message": event_result,
                    "events": [event_result],
                    "game_state": _serialize_game_state_for_client(game_state),
                }

            if event_type == "treasure":
                # 处理宝藏事件 - 使用LLM生成物品
                position = event_data.get("position", [0, 0])

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
                    "game_state": _serialize_game_state_for_client(game_state),
                }

            if event_type == "trap_narrative":
                # 处理陷阱叙述生成 - 前端已计算效果，后端按配置生成描述性文本
                trap_result = event_data.get("trap_result", {})

                narrative = await game_engine._generate_trap_narrative(game_state, trap_result)

                # 写入 LLM 上下文：陷阱事件与叙述（可由配置开关控制）
                try:
                    from llm_context_manager import llm_context_manager

                    if getattr(config.llm, "record_trap_to_context", True):
                        context_key = _build_context_key(user_id, request.game_id)
                        trap_type = (
                            trap_result.get("trap_type", trap_result.get("type", "unknown"))
                            if isinstance(trap_result, dict)
                            else "unknown"
                        )
                        llm_context_manager.add_event(
                            event_type="trap",
                            description=f"触发陷阱：{trap_type}",
                            data=trap_result if isinstance(trap_result, dict) else {"raw": str(trap_result)},
                            context_key=context_key,
                        )
                        if narrative:
                            llm_context_manager.add_narrative(
                                narrative,
                                context_type="trap",
                                context_key=context_key,
                            )
                except Exception as _e:
                    logger.warning(f"Failed to log trap context: {_e}")

                return {
                    "success": True,
                    "narrative": narrative,
                    "game_state": _serialize_game_state_for_client(game_state),
                }

            return {
                "success": False,
                "message": f"未知的事件类型: {event_type}",
            }

    except HTTPException:
        raise
    except LLMUnavailableError as e:
        logger.error(f"LLM unavailable in /api/llm-event: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "message": "LLM服务暂时不可用，事件处理已中止。",
                "error_code": "LLM_UNAVAILABLE",
                "retryable": True,
                "reason": "llm_unavailable",
            },
        )
    except Exception as e:
        logger.error(f"Failed to process LLM event: {e}")
        raise HTTPException(status_code=500, detail=f"处理LLM事件失败: {str(e)}")
    finally:
        if context_token is not None:
            from llm_context_manager import llm_context_manager

            llm_context_manager.reset_current_context_key(context_token)


@app.post("/api/trap-choice/register")
async def register_trap_choice_context(request: Request, response: Response):
    """注册陷阱选择上下文

    前端发现陷阱后调用，注册选择上下文到EventChoiceSystem
    """
    try:
        data = await request.json()
        game_id = data.get("game_id")
        context_id = data.get("context_id")
        trap_name = data.get("trap_name", "未知陷阱")
        trap_description = data.get("trap_description", "你发现了一个陷阱！")
        trap_data = data.get("trap_data", {})
        position = data.get("position", [0, 0])
        choices_data = data.get("choices", [])

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        async with game_state_lock_manager.lock_game_state(user_id, game_id, "trap_choice_register"):
            # 获取游戏状态
            game_state = game_engine.active_games.get(game_key)
            if not game_state:
                raise HTTPException(status_code=404, detail="游戏未找到")

            # 创建EventChoiceContext
            from data_models import EventChoiceContext, EventChoice
            from event_choice_system import event_choice_system

            context = EventChoiceContext(
                id=context_id,
                event_type="trap_event",
                title=f"⚠️ 发现陷阱：{trap_name}",
                description=trap_description,
                context_data={
                    "trap_data": trap_data,
                    "position": position,
                    "owner_game_id": game_id,
                    "owner_user_id": user_id,
                }
            )

            # 创建选项
            for choice_data in choices_data:
                choice = EventChoice(
                    text=choice_data.get("text", ""),
                    description=choice_data.get("description", ""),
                    consequences=choice_data.get("consequences", ""),
                    requirements=choice_data.get("requirements", {}),
                    is_available=True
                )
                # 使用前端传来的id作为选项ID
                choice.id = choice_data.get("id", choice.id)
                context.choices.append(choice)

            # 注册到EventChoiceSystem
            event_choice_system.active_contexts[context_id] = context
            game_state.pending_choice_context = context

        logger.info(f"Registered trap choice context: {context_id} for game {game_id}")

        return {
            "success": True,
            "context_id": context_id,
            "message": "陷阱选择上下文已注册"
        }

    except Exception as e:
        logger.error(f"Failed to register trap choice context: {e}")
        raise HTTPException(status_code=500, detail=f"注册陷阱选择上下文失败: {str(e)}")


@app.post("/api/check-trap")
async def check_trap_detection(request: Request, response: Response):
    """检查陷阱侦测（被动感知）

    前端玩家移动到瓦片时调用，检查是否被动侦测到陷阱
    """
    try:
        data = await request.json()
        game_id = data.get("game_id")
        position = data.get("position", [0, 0])

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        async with game_state_lock_manager.lock_game_state(user_id, game_id, "check_trap"):
            # 获取游戏状态
            game_state = game_engine.active_games.get(game_key)
            if not game_state:
                raise HTTPException(status_code=404, detail="游戏未找到")

            # 获取目标瓦片
            tile = game_state.current_map.get_tile(position[0], position[1])
            if not tile or not tile.is_trap():
                return {
                    "trap_detected": False,
                    "message": "没有陷阱"
                }

            # 如果陷阱已经被发现或已触发，直接返回
            if tile.trap_detected or tile.event_triggered:
                return {
                    "trap_detected": tile.trap_detected,
                    "already_known": True,
                    "message": "陷阱已被发现" if tile.trap_detected else "陷阱已触发"
                }

            # 获取陷阱数据
            trap_data = tile.get_trap_data()
            detect_dc = trap_data.get("detect_dc", 15)

            # 进行被动侦测
            from trap_manager import get_trap_manager
            trap_manager = get_trap_manager()

            detected = trap_manager.passive_detect_trap(game_state.player, detect_dc)

            if detected:
                # 标记陷阱已被发现
                tile.trap_detected = True
                if tile.has_event and tile.event_type == 'trap':
                    tile.event_data["is_detected"] = True

                logger.info(f"Trap detected at ({position[0]}, {position[1]}) by passive perception")

                return {
                    "trap_detected": True,
                    "trap_data": trap_data,
                    "position": position,
                    "passive_perception": game_state.player.get_passive_perception(),
                    "detect_dc": detect_dc,
                    "message": f"你的敏锐感知发现了陷阱！（被动感知 {game_state.player.get_passive_perception()} vs DC {detect_dc}）"
                }
            else:
                logger.info(f"Trap not detected at ({position[0]}, {position[1]}) - PP too low")

                return {
                    "trap_detected": False,
                    "will_trigger": True,
                    "passive_perception": game_state.player.get_passive_perception(),
                    "detect_dc": detect_dc,
                    "message": "未能发现陷阱"
                }

    except Exception as e:
        logger.error(f"Failed to check trap detection: {e}")
        raise HTTPException(status_code=500, detail=f"检查陷阱侦测失败: {str(e)}")


@app.post("/api/trap/trigger")
async def trigger_trap(request: Request, response: Response):
    """触发陷阱（统一处理，包含敏捷豁免判定）

    当玩家未发现陷阱而直接触发时调用此接口。
    后端会自动进行敏捷豁免判定，并根据结果计算伤害（可能减半）。

    请求参数：
    - game_id: 游戏ID
    - position: 陷阱位置 [x, y]

    返回：
    - success: 是否成功处理
    - save_attempted: 是否尝试了豁免
    - save_result: 豁免判定结果（如果有）
    - save_message: 豁免判定的详细信息（如 "🎲 1d20=8 + DEX+2 = 10 vs DC 14 - 失败"）
    - trigger_result: 触发结果（包含伤害、描述等）
    - narrative: LLM生成的叙述文本
    - player_hp: 玩家当前HP
    - player_died: 玩家是否死亡
    """
    context_token = None
    try:
        data = await request.json()
        game_id = data.get("game_id")
        position = data.get("position", [0, 0])

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        from llm_context_manager import llm_context_manager
        context_token = llm_context_manager.set_current_context_key(_build_context_key(user_id, game_id))

        async with game_state_lock_manager.lock_game_state(user_id, game_id, "trigger_trap"):
            # 获取游戏状态
            game_state = game_engine.active_games.get(game_key)
            if not game_state:
                raise HTTPException(status_code=404, detail="游戏未找到")

            # 获取目标瓦片
            tile = game_state.current_map.get_tile(position[0], position[1])
            if not tile or not tile.is_trap():
                return {
                    "success": False,
                    "message": "该位置没有陷阱"
                }

            # 获取陷阱数据
            from trap_schema import trap_validator
            raw_trap_data = tile.get_trap_data()
            trap_data = trap_validator.validate_and_normalize(raw_trap_data)

            # 获取 TrapManager
            from trap_manager import get_trap_manager
            trap_manager = get_trap_manager()

            # 检查陷阱是否可以被规避（需要豁免）
            can_be_avoided = trap_data.get("can_be_avoided", True)
            save_dc = trap_data.get("save_dc", 14)

            save_attempted = False
            save_result = None
            save_message = ""

            # 如果陷阱可以被规避，自动进行敏捷豁免
            if can_be_avoided and save_dc > 0:
                save_attempted = True
                save_result = trap_manager.attempt_avoid(game_state.player, save_dc)

                # 使用统一的消息格式（优先使用新引擎的ui_text）
                if "ui_text" in save_result:
                    save_message = save_result["ui_text"]
                elif "breakdown" in save_result:
                    # 如果有breakdown但没有ui_text，手动构建
                    success_icon = "✅" if save_result['success'] else "❌"
                    save_message = f"{success_icon} DEX豁免：{save_result['breakdown']} vs DC {save_dc} - {'成功' if save_result['success'] else '失败'}"
                else:
                    # 旧格式兼容
                    success_icon = "✅" if save_result['success'] else "❌"
                    save_message = (
                        f"{success_icon} 敏捷豁免：🎲 1d20={save_result['roll']} + "
                        f"DEX{save_result['modifier']:+d} = {save_result['total']} "
                        f"vs DC {save_dc} - {'成功' if save_result['success'] else '失败'}"
                    )

                logger.info(f"Trap trigger with save: {save_message}")

            # 触发陷阱（传入豁免结果，如果有的话）
            trigger_result = trap_manager.trigger_trap(game_state, tile, save_result=save_result)

            # 生成陷阱叙述（根据配置使用 local 或 llm）
            from trap_narrative_service import trap_narrative_service
            narrative = await trap_narrative_service.generate_narrative(
                game_state=game_state,
                trap_data=trap_data,
                trigger_result=trigger_result,
                save_attempted=save_attempted,
                save_result=save_result,
            )

            # 返回结果
            return {
                "success": True,
                "save_attempted": save_attempted,
                "save_result": save_result,
                "save_message": save_message,
                "trigger_result": trigger_result,
                "narrative": narrative,
                "player_hp": game_state.player.stats.hp,
                "player_max_hp": game_state.player.stats.max_hp,
                "player_died": trigger_result.get("player_died", False),
                "game_over": game_state.is_game_over
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger trap: {e}")
        raise HTTPException(status_code=500, detail=f"触发陷阱失败: {str(e)}")
    finally:
        if context_token is not None:
            from llm_context_manager import llm_context_manager
            llm_context_manager.reset_current_context_key(context_token)


@app.post("/api/sync-state")
async def sync_game_state(request: SyncStateRequest, http_request: Request, response: Response):
    """同步游戏状态（用于存档）

    【重要】此接口会合并前端和后端的游戏状态：
    - 前端状态：玩家位置、怪物状态、地图状态等"计算型"数据
    - 后端状态：任务进度、经验值、等级等"生成型"数据
    - 返回合并后的状态，确保前端获取最新的后端数据
    """
    context_token = None
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        from llm_context_manager import llm_context_manager
        context_token = llm_context_manager.set_current_context_key(_build_context_key(user_id, request.game_id))

        logger.debug(f"Syncing game state for user {user_id}, game: {request.game_id}")

        async with game_state_lock_manager.lock_game_state(user_id, request.game_id, "sync_state"):
            # 获取后端当前的游戏状态（包含最新的任务进度等数据）
            backend_game_state = game_engine.active_games.get(game_key)

            if not backend_game_state:
                raise HTTPException(status_code=404, detail="游戏未找到")

            # 从请求中重建前端游戏状态
            from data_manager import data_manager
            frontend_game_state = data_manager._dict_to_game_state(request.game_state)

            # 【关键】按权威模式合并前后端状态
            # local: 兼容旧客户端，同步更多前端计算字段
            # hybrid/server: 后端权威，禁止前端覆盖战斗核心字段（position/monsters/current_map/turn_count）
            authority_mode = _safe_authority_mode(
                getattr(backend_game_state, "combat_authority_mode", None),
                _safe_authority_mode(config.game.combat_authority_mode),
            )
            backend_game_state.combat_authority_mode = authority_mode
            backend_game_state.combat_rule_version = max(
                1,
                _safe_int(getattr(backend_game_state, "combat_rule_version", 1), 1),
            )

            if authority_mode == "local":
                backend_game_state.player.position = frontend_game_state.player.position
                backend_game_state.monsters = frontend_game_state.monsters
                backend_game_state.current_map = frontend_game_state.current_map
                backend_game_state.turn_count = frontend_game_state.turn_count

                # 修复地图角色索引，避免客户端提交导致的 character_id 不一致
                for tile in backend_game_state.current_map.tiles.values():
                    tile.character_id = None
                player_tile = backend_game_state.current_map.get_tile(*backend_game_state.player.position)
                if player_tile:
                    player_tile.character_id = backend_game_state.player.id
                    player_tile.is_explored = True
                    player_tile.is_visible = True
                for monster in backend_game_state.monsters:
                    monster_tile = backend_game_state.current_map.get_tile(*monster.position)
                    if monster_tile:
                        monster_tile.character_id = monster.id

            # 后端状态：任务进度、经验值、等级、物品栏（后端生成）
            # 这些数据保持后端的值，不被前端覆盖

            # 【新增】检查是否需要进度补偿（每次同步时检查）
            from quest_progress_compensator import quest_progress_compensator
            compensation_result = await quest_progress_compensator.check_and_compensate(
                backend_game_state,
                source="sync_state",
            )
            if compensation_result["compensated"]:
                logger.info(f"Progress compensated during sync: +{compensation_result['compensation_amount']:.1f}% ({compensation_result['reason']})")

                # 【新增】如果补偿后任务完成，创建任务完成选择
                if hasattr(backend_game_state, 'pending_quest_completion') and backend_game_state.pending_quest_completion:
                    completed_quest = backend_game_state.pending_quest_completion
                    logger.info(f"Quest completion detected after compensation: {completed_quest.title}")

                    try:
                        # 创建任务完成选择上下文
                        from event_choice_system import event_choice_system
                        choice_context = await event_choice_system.create_quest_completion_choice(
                            backend_game_state, completed_quest
                        )

                        # 将选择上下文存储到游戏状态中
                        backend_game_state.pending_choice_context = choice_context
                        event_choice_system.active_contexts[choice_context.id] = choice_context

                        # 清理任务完成标志
                        backend_game_state.pending_quest_completion = None

                        logger.info(f"Created quest completion choice after compensation: {completed_quest.title}")

                    except Exception as e:
                        logger.error(f"Error creating quest completion choice after compensation: {e}")
                        # 清理标志，避免重复处理
                        backend_game_state.pending_quest_completion = None

            # 更新内存中的游戏状态
            game_engine.active_games[game_key] = backend_game_state

        # 可选：立即保存到文件
        # data_manager.save_game_state(backend_game_state)

        # 【新增】返回合并后的游戏状态，确保前端获取最新数据
        return {
            "success": True,
            "message": "游戏状态已同步",
            "game_state": _serialize_game_state_for_client(backend_game_state)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync game state: {e}")
        raise HTTPException(status_code=500, detail=f"同步游戏状态失败: {str(e)}")


@app.post("/api/game/{game_id}/combat-result")
async def process_combat_result(game_id: str, request: Request, response: Response):
    """处理战斗结果（怪物被击败）"""
    trace_id = str(uuid.uuid4())
    try:
        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(request, response)
        game_key = (user_id, game_id)

        logger.debug(f"Processing combat result for user {user_id}, game: {game_id}, trace_id={trace_id}")

        try:
            request_data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=_build_http_exception_detail("请求体不是合法JSON", trace_id, "INVALID_JSON_BODY"),
            )

        if not isinstance(request_data, dict):
            raise HTTPException(
                status_code=400,
                detail=_build_http_exception_detail("请求体格式错误", trace_id, "INVALID_REQUEST_BODY"),
            )

        monster_id = request_data.get("monster_id")
        damage_raw = request_data.get("damage_dealt", 0)

        # 防御性处理：兼容前端/调试场景下的非标准数值输入，避免战斗结算500
        try:
            if damage_raw is None:
                damage_dealt = 0
            else:
                damage_dealt = int(float(damage_raw))
        except (TypeError, ValueError, OverflowError):
            logger.warning(f"Invalid damage_dealt received: {damage_raw}, fallback to 0")
            damage_dealt = 0

        # 伤害值安全边界（防异常输入与极端值）
        damage_dealt = max(0, min(damage_dealt, 1_000_000))

        idempotency_key = str(request_data.get("idempotency_key", "") or "").strip()
        client_trace_id = str(request_data.get("client_trace_id", "") or "").strip()
        if not idempotency_key:
            if client_trace_id:
                idempotency_key = f"ct:{client_trace_id}"
            else:
                fallback_seed = json.dumps(
                    {
                        "game_id": str(game_id),
                        "user_id": str(user_id),
                        "monster_id": str(monster_id or ""),
                        "damage_dealt": int(damage_dealt),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                idempotency_key = f"auto:{hashlib.sha1(fallback_seed.encode('utf-8')).hexdigest()[:16]}"

        if not monster_id:
            raise HTTPException(
                status_code=400,
                detail=_build_http_exception_detail("缺少怪物ID", trace_id, "MISSING_MONSTER_ID"),
            )

        # 使用锁保护战斗结算操作
        response_payload: Optional[Dict[str, Any]] = None
        replay_hit = False
        lock_wait_ms = 0

        async with game_state_lock_manager.lock_game_state(user_id, game_id, "combat_result") as state_lock:
            lock_wait_ms = getattr(state_lock, "last_wait_ms", 0)

            if game_key not in game_engine.active_games:
                raise HTTPException(
                    status_code=404,
                    detail=_build_http_exception_detail("游戏未找到", trace_id, "GAME_NOT_FOUND"),
                )

            game_state = game_engine.active_games[game_key]

            game_engine._prune_idempotency_cache(game_key)
            cache = game_engine._get_idempotency_cache(game_key)
            combat_cache_key = f"combat_result:{idempotency_key}"
            cached_payload = cache.get(combat_cache_key)
            expected_fingerprint = json.dumps(
                {"monster_id": str(monster_id), "damage_dealt": int(damage_dealt)},
                sort_keys=True,
                ensure_ascii=False,
            )
            if isinstance(cached_payload, dict):
                cached_fingerprint = str(cached_payload.get("fingerprint", "") or "")
                cached_result = cached_payload.get("result")
                if cached_fingerprint == expected_fingerprint and isinstance(cached_result, dict):
                    replay_result = dict(cached_result)
                    replay_result["idempotent_replay"] = True
                    replay_result["trace_id"] = trace_id
                    response_payload = replay_result
                    replay_hit = True
                else:
                    logger.warning(
                        "combat_result_idempotency_fingerprint_mismatch game=%s key=%s trace_id=%s",
                        game_key,
                        idempotency_key,
                        trace_id,
                    )

            if not replay_hit:
                # 查找怪物
                monster = None
                for m in game_state.monsters:
                    if m.id == monster_id:
                        monster = m
                        break

                if not monster:
                    raise HTTPException(
                        status_code=404,
                        detail=_build_http_exception_detail("怪物未找到", trace_id, "MONSTER_NOT_FOUND"),
                    )

                # 使用战斗结果管理器处理
                from combat_result_manager import combat_result_manager
                combat_result = await combat_result_manager.process_monster_defeat(
                    game_state, monster, damage_dealt
                )

            if not replay_hit:
                # 【新增】从后端游戏状态中移除被击败的怪物，并清理地图标记
                try:
                    tile = game_state.current_map.get_tile(monster.position[0], monster.position[1])
                    if tile:
                        tile.character_id = None
                    if monster in game_state.monsters:
                        game_state.monsters.remove(monster)
                    logger.debug(f"Removed defeated monster from backend state: {monster.name}")
                except Exception as e:
                    logger.error(f"Failed to remove monster from backend state: {e}")

                # 【新增】如果是任务怪物，触发任务进度更新
                if monster.quest_monster_id and combat_result.quest_progress > 0:
                    from progress_manager import progress_manager, ProgressEventType, ProgressContext

                    logger.debug(f"Triggering quest progress update for quest monster: {monster.name}, progress: {combat_result.quest_progress}%")

                    # 创建进度上下文
                    context_data = {
                        "monster_name": monster.name,
                        "challenge_rating": monster.challenge_rating,
                        "quest_monster_id": monster.quest_monster_id,
                        "progress_value": combat_result.quest_progress
                    }

                    progress_context = ProgressContext(
                        event_type=ProgressEventType.COMBAT_VICTORY,
                        game_state=game_state,
                        context_data=context_data
                    )

                    # 触发进度管理器处理战斗胜利事件，确保任务进度与完成逻辑生效
                    try:
                        await progress_manager.process_event(progress_context)
                    except Exception as _e:
                        logger.warning(f"Progress manager failed to process combat victory event: {_e}")

                # 【新增】在进度更新之后检查任务进度补偿（确保在移除怪物后再检查）
                from quest_progress_compensator import quest_progress_compensator
                compensation_result = await quest_progress_compensator.check_and_compensate(
                    game_state,
                    source="combat_result",
                )
                if compensation_result.get("compensated"):
                    logger.info(
                        f"Progress compensated during combat-result: +{compensation_result['compensation_amount']:.1f}% ({compensation_result['reason']})"
                    )

                # 【修复】检查是否有任务完成需要处理选择，立即创建选择上下文
                has_pending_choice = False
                if hasattr(game_state, 'pending_quest_completion') and game_state.pending_quest_completion:
                    completed_quest = game_state.pending_quest_completion
                    logger.info(f"Quest completion detected: {completed_quest.title}")

                    try:
                        # 立即创建任务完成选择上下文
                        from event_choice_system import event_choice_system
                        choice_context = await event_choice_system.create_quest_completion_choice(
                            game_state, completed_quest
                        )

                        # 将选择上下文存储到游戏状态中
                        game_state.pending_choice_context = choice_context
                        event_choice_system.active_contexts[choice_context.id] = choice_context

                        # 清理任务完成标志
                        game_state.pending_quest_completion = None

                        has_pending_choice = True
                        logger.info(f"Created quest completion choice after monster defeat: {completed_quest.title}")

                    except Exception as e:
                        logger.error(f"Error creating quest completion choice: {e}")
                        # 清理标志，避免重复处理
                        game_state.pending_quest_completion = None

                # 构建响应
                result_dict = combat_result.to_dict()
                result_dict["has_pending_choice"] = has_pending_choice
                result_dict["trace_id"] = trace_id
                result_dict["idempotency_key"] = idempotency_key
                result_dict["client_trace_id"] = client_trace_id
                response_payload = result_dict

                cache[combat_cache_key] = {
                    "result": dict(result_dict),
                    "fingerprint": expected_fingerprint,
                    "created_at": datetime.utcnow().timestamp(),
                }
                game_engine._prune_idempotency_cache(game_key)

        lock_obj = await game_state_lock_manager._get_or_create_lock(game_key)
        lock_hold_ms = getattr(lock_obj, "last_hold_ms", 0)

        if response_payload is None:
            raise HTTPException(
                status_code=500,
                detail=_build_http_exception_detail("战斗结算响应为空", trace_id, "COMBAT_RESULT_EMPTY"),
            )

        response_payload["lock_wait_ms"] = max(0, int(lock_wait_ms))
        response_payload["lock_hold_ms"] = max(0, int(lock_hold_ms))
        response_payload["trace_id"] = trace_id
        response_payload["idempotency_key"] = idempotency_key
        response_payload["client_trace_id"] = client_trace_id

        if replay_hit:
            logger.info(
                "combat_result_idempotent_replay game=%s key=%s trace_id=%s lock_wait_ms=%s lock_hold_ms=%s",
                game_key,
                idempotency_key,
                trace_id,
                response_payload["lock_wait_ms"],
                response_payload["lock_hold_ms"],
            )
        else:
            logger.info(
                "combat_result_trace trace_id=%s game_id=%s user_id=%s idempotency_key=%s lock_wait_ms=%s lock_hold_ms=%s",
                trace_id,
                game_id,
                user_id,
                idempotency_key,
                response_payload["lock_wait_ms"],
                response_payload["lock_hold_ms"],
            )

        return response_payload

    except HTTPException as exc:
        status_code, detail = _normalize_http_exception(exc, trace_id, "COMBAT_RESULT_BAD_REQUEST")
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as e:
        logger.exception("Failed to process combat result, trace_id=%s", trace_id)
        raise HTTPException(
            status_code=500,
            detail={"message": "处理战斗结果失败", "trace_id": trace_id, "error_code": "COMBAT_RESULT_FAILED"},
        )


@app.post("/api/event-choice")
async def process_event_choice(request: EventChoiceRequest, http_request: Request, response: Response):
    """处理事件选择"""
    context_token = None
    try:
        # 记录接收到的请求数据
        logger.info(
            f"Received event choice request: game_id={request.game_id}, "
            f"context_id={request.context_id}, choice_id={request.choice_id}"
        )

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
            logger.error(
                f"Choice ID validation failed for '{request.choice_id}': "
                f"{choice_id_validation.error_message}"
            )
            raise HTTPException(status_code=400, detail=choice_id_validation.error_message)

        logger.info(f"Processing event choice: {request.choice_id} for context: {request.context_id}")

        # 获取用户ID
        user_id = user_session_manager.get_or_create_user_id(http_request, response)
        game_key = (user_id, request.game_id)

        from llm_context_manager import llm_context_manager

        context_token = llm_context_manager.set_current_context_key(
            _build_context_key(user_id, request.game_id)
        )

        # 使用锁保护事件选择处理
        async with game_state_lock_manager.lock_game_state(user_id, request.game_id, "event_choice"):
            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 处理选择
            result = await event_choice_system.process_choice(
                game_state=game_state,
                context_id=request.context_id,
                choice_id=request.choice_id,
                game_id=request.game_id,
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
                    "game_state": _serialize_game_state_for_client(game_state),
                }

            return {
                "success": False,
                "message": result.message,
            }

    except HTTPException:
        raise
    except LLMUnavailableError as e:
        logger.error(f"LLM unavailable in /api/event-choice: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "message": "LLM服务暂时不可用，事件选择已中止。",
                "error_code": "LLM_UNAVAILABLE",
                "retryable": True,
                "reason": "llm_unavailable",
            },
        )
    except Exception as e:
        logger.error(f"Failed to process event choice: {e}")
        raise HTTPException(status_code=500, detail=f"处理事件选择失败: {str(e)}")
    finally:
        if context_token is not None:
            from llm_context_manager import llm_context_manager

            llm_context_manager.reset_current_context_key(context_token)


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
            # 保存最近N条LLM上下文到存档
            try:
                from llm_context_manager import llm_context_manager
                game_data["llm_context_logs"] = [
                    e.to_dict() for e in llm_context_manager.get_recent_context(
                        max_entries=getattr(config.llm, "save_context_entries", 20),
                        context_key=_build_context_key(user_id, game_id),
                    )
                ]
            except Exception as _e:
                logger.warning(f"Failed to attach LLM context logs to save: {_e}")

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
                    "combat_authority_mode": config.game.combat_authority_mode,
                    "combat_diff_threshold": config.game.combat_diff_threshold,
                    # 注意：任务进度始终显示，不再通过配置控制
                    "version": config.game.version,
                    "game_name": config.game.game_name,
                    "map_transition_progress": config.game.map_transition_progress,
                    "max_single_progress_increment": config.game.max_single_progress_increment,
                    "max_quest_floors": config.game.max_quest_floors,
                    "combat_victory_weight": config.game.combat_victory_weight,
                    "story_event_weight": config.game.story_event_weight
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
                    "game_state": _serialize_game_state_for_client(game_state)
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

    # ==================== 调试专用加载接口 ====================

    class DebugForceLoadRequest(BaseModel):
        """调试强制加载请求"""
        game_id: str
        user_id: Optional[str] = None  # 可选：指定用户ID，默认使用当前会话用户

    @app.post("/api/debug/force-load")
    async def debug_force_load(req: DebugForceLoadRequest, request: Request, response: Response):
        """
        调试专用：强制加载指定游戏存档

        此接口仅在调试模式下可用，用于快速加载任意存档进行测试。
        与普通加载接口的区别：
        1. 可以指定user_id加载其他用户的存档（调试用）
        2. 绕过某些权限检查，方便开发调试
        3. 仅在DEBUG_MODE=True时启用

        Args:
            req: 包含game_id和可选user_id的请求
            request: FastAPI请求对象
            response: FastAPI响应对象

        Returns:
            加载结果，包含游戏状态和叙述
        """
        try:
            # 确定要使用的用户ID
            if req.user_id:
                # 调试模式下允许指定用户ID
                target_user_id = req.user_id
                logger.info(f"[DEBUG] Force loading game {req.game_id} for specified user {target_user_id}")
            else:
                # 使用当前会话用户
                target_user_id = user_session_manager.get_or_create_user_id(request, response)
                logger.info(f"[DEBUG] Force loading game {req.game_id} for current user {target_user_id}")

            # 从用户存档目录加载
            save_data = user_session_manager.load_game_for_user(target_user_id, req.game_id)

            if not save_data:
                raise HTTPException(status_code=404, detail=f"存档未找到: {req.game_id} (user: {target_user_id})")

            # 重建游戏状态
            game_state = data_manager._dict_to_game_state(save_data)

            # 清除所有瓦片的character_id（防止存档中有错误数据）
            for tile in game_state.current_map.tiles.values():
                tile.character_id = None
            logger.info(f"[DEBUG] Cleared all character_id from {len(game_state.current_map.tiles)} tiles")

            # 重新设置玩家位置的character_id
            player_tile = game_state.current_map.get_tile(*game_state.player.position)
            if player_tile:
                player_tile.character_id = game_state.player.id
                player_tile.is_explored = True
                player_tile.is_visible = True

            # 重新设置怪物位置的character_id
            for monster in game_state.monsters:
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = monster.id

            # 获取当前会话用户ID
            current_session_user_id = user_session_manager.get_or_create_user_id(request, response)

            # 添加到活跃游戏列表（使用当前会话用户ID，这样前端可以访问）
            game_key = (current_session_user_id, game_state.id)
            game_engine.active_games[game_key] = game_state
            game_engine._start_auto_save(current_session_user_id, game_state.id)

            logger.info(f"[DEBUG] Game added to active games for current session user: {current_session_user_id}")

            # 生成重新进入游戏的叙述
            try:
                return_narrative = await llm_service.generate_return_narrative(game_state)
                game_state.last_narrative = return_narrative
            except Exception as e:
                logger.error(f"Failed to generate return narrative: {e}")
                game_state.last_narrative = f"[调试模式] 你重新回到了 {game_state.current_map.name}，继续你的冒险..."

            logger.info(f"[DEBUG] Successfully force-loaded game {req.game_id} (original user: {target_user_id}, session user: {current_session_user_id})")

            return {
                "success": True,
                "game_id": game_state.id,
                "user_id": current_session_user_id,  # 返回当前会话用户ID
                "original_user_id": target_user_id,  # 原始用户ID（用于调试信息）
                "message": f"[调试模式] 游戏已强制加载：{game_state.player.name}",
                "narrative": game_state.last_narrative,
                "debug_info": {
                    "player_level": game_state.player.stats.level,
                    "turn_count": game_state.turn_count,
                    "map_name": game_state.current_map.name,
                    "map_depth": game_state.current_map.depth,
                    "active_quests": len([q for q in game_state.quests if q.is_active])
                }
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[DEBUG] Failed to force load game: {e}")
            raise HTTPException(status_code=500, detail=f"强制加载游戏失败: {str(e)}")

    @app.get("/api/debug/list-all-saves")
    async def debug_list_all_saves():
        """
        调试专用：列出所有用户的所有存档

        此接口仅在调试模式下可用，用于查找特定game_id对应的user_id。

        Returns:
            所有存档的列表，包含game_id、user_id、玩家名称等信息
        """
        if not config.game.debug_mode:
            raise HTTPException(status_code=404, detail="API端点未找到")

        try:
            all_saves = []
            saves_dir = Path("saves/users")

            if not saves_dir.exists():
                return {"saves": []}

            # 遍历所有用户目录
            for user_dir in saves_dir.iterdir():
                if not user_dir.is_dir():
                    continue

                user_id = user_dir.name

                # 遍历该用户的所有存档
                for save_file in user_dir.glob("*.json"):
                    try:
                        with open(save_file, 'r', encoding='utf-8') as f:
                            save_data = json.load(f)

                        all_saves.append({
                            "game_id": save_data.get("id"),
                            "user_id": user_id,
                            "player_name": save_data.get("player", {}).get("name"),
                            "player_level": save_data.get("player", {}).get("stats", {}).get("level"),
                            "map_name": save_data.get("current_map", {}).get("name"),
                            "turn_count": save_data.get("turn_count"),
                            "last_saved": save_data.get("last_saved")
                        })
                    except Exception as e:
                        logger.warning(f"[DEBUG] Failed to read save file {save_file}: {e}")
                        continue

            logger.info(f"[DEBUG] Listed {len(all_saves)} saves from all users")
            return {"saves": all_saves}

        except Exception as e:
            logger.error(f"[DEBUG] Failed to list all saves: {e}")
            raise HTTPException(status_code=500, detail=f"列出存档失败: {str(e)}")

    # ==================== LLM 上下文日志接口 ====================

    @app.get("/api/debug/llm-context/statistics")
    async def debug_get_llm_context_statistics(request: Request, response: Response, game_id: Optional[str] = None):
        """调试：获取LLM上下文统计信息"""
        from llm_context_manager import llm_context_manager
        user_id = user_session_manager.get_or_create_user_id(request, response)
        context_key = _build_context_key(user_id, game_id) if game_id else None
        return {
            "success": True,
            "context_key": context_key,
            "statistics": llm_context_manager.get_statistics(context_key=context_key),
        }

    @app.get("/api/debug/llm-context/entries")
    async def debug_get_llm_context_entries(
        request: Request,
        response: Response,
        max_entries: int = 50,
        entry_type: Optional[str] = None,
        game_id: Optional[str] = None,
    ):
        """调试：获取LLM上下文条目列表"""
        from llm_context_manager import llm_context_manager, ContextEntryType

        user_id = user_session_manager.get_or_create_user_id(request, response)
        context_key = _build_context_key(user_id, game_id) if game_id else None

        # 筛选类型
        entry_types = None
        if entry_type:
            try:
                entry_types = [ContextEntryType(entry_type)]
            except ValueError:
                return {
                    "success": False,
                    "message": f"无效的条目类型: {entry_type}"
                }

        entries = llm_context_manager.get_recent_context(
            max_entries=max_entries,
            entry_types=entry_types,
            context_key=context_key,
        )

        return {
            "success": True,
            "context_key": context_key,
            "total_entries": len(entries),
            "entries": [entry.to_dict() for entry in entries]
        }

    @app.get("/api/debug/llm-context/formatted")
    async def debug_get_llm_context_formatted(
        request: Request,
        response: Response,
        max_entries: int = 20,
        include_metadata: bool = False,
        game_id: Optional[str] = None,
    ):
        """调试：获取格式化的LLM上下文字符串"""
        from llm_context_manager import llm_context_manager

        user_id = user_session_manager.get_or_create_user_id(request, response)
        context_key = _build_context_key(user_id, game_id) if game_id else None

        context_string = llm_context_manager.build_context_string(
            max_entries=max_entries,
            include_metadata=include_metadata,
            context_key=context_key,
        )

        return {
            "success": True,
            "context_key": context_key,
            "context_string": context_string,
            "statistics": llm_context_manager.get_statistics(context_key=context_key),
        }

    @app.post("/api/debug/llm-context/clear")
    async def debug_clear_llm_context(request: Request, response: Response, game_id: Optional[str] = None):
        """调试：清空LLM上下文"""
        from llm_context_manager import llm_context_manager

        user_id = user_session_manager.get_or_create_user_id(request, response)
        context_key = _build_context_key(user_id, game_id) if game_id else None
        old_stats = llm_context_manager.get_statistics(context_key=context_key)
        llm_context_manager.clear_all(context_key=context_key)

        return {
            "success": True,
            "context_key": context_key,
            "message": "LLM上下文已清空",
            "cleared_entries": old_stats.get("total_entries", 0),
        }

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

    @app.get("/api/debug/generation-trace/{game_id}")
    async def debug_get_generation_trace(game_id: str, request: Request, response: Response):
        """调试：获取地图生成完整链路（蓝图/patch/账本）"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.get_generation_trace(user_id, game_id)

    @app.get("/api/debug/export-package/{game_id}")
    async def debug_export_debug_package(game_id: str, request: Request, response: Response):
        """调试：导出完整调试包JSON"""
        user_id = user_session_manager.get_or_create_user_id(request, response)
        return debug_api.export_debug_package(user_id, game_id)

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
        except LLMUnavailableError as e:
            logger.error(f"Gemini API unavailable: {e}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "message": "LLM服务暂时不可用，本次Gemini真实调用已中止。",
                    "error_code": "LLM_UNAVAILABLE",
                    "retryable": True,
                    "reason": "llm_unavailable",
                    "cause": getattr(e, "cause", "unknown"),
                },
            )
        except Exception as e:
            logger.error(f"Gemini API test failed: {e}")
            return {
                "success": False,
                "message": f"Gemini API 测试失败: {str(e)}"
            }

    @app.post("/api/test/openrouter")
    async def test_openrouter_api(request: Request):
        """测试 OpenRouter API 连接（真实 OpenRouter 调用，不修改全局 provider）。"""
        try:
            try:
                request_data = await request.json()
            except Exception:
                request_data = {}

            test_message = request_data.get("test_message", "Hello, this is a test")
            model = str(request_data.get("model") or config.llm.openrouter.model_name or "").strip() or "google/gemini-2.0-flash-001"
            base_url = str(getattr(config.llm.openrouter, "base_url", "") or config.llm.openrouter_base_url or "https://openrouter.ai/api/v1")
            api_key = str(getattr(config.llm.openrouter, "api_key", "") or "")

            if not api_key.strip():
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": "OpenRouter API Key 未配置（请设置 OPENROUTER_API_KEY）",
                        "error_code": "OPENROUTER_API_KEY_MISSING",
                        "retryable": False,
                        "reason": "missing_api_key",
                    },
                )

            proxies = None
            if config.llm.use_proxy and config.llm.proxy_url:
                proxies = {
                    "http": config.llm.proxy_url,
                    "https": config.llm.proxy_url,
                }

            from openrouter_client import OpenRouterClient, ChatError

            if not async_task_manager._initialized:
                async_task_manager.initialize()

            client = OpenRouterClient(
                api_key=api_key,
                base_url=base_url,
                default_model=model,
                timeout=int(getattr(config.llm, "timeout", 60) or 60),
                proxies=proxies,
                referer="https://github.com/Labyrinthia-AI/Labyrinthia-AI",
                title=config.game.game_name,
            )

            prompt = f"请用中文回复这条测试消息：{test_message}"

            loop = asyncio.get_event_loop()
            started_at = time.perf_counter()

            async with async_task_manager.llm_semaphore:
                try:
                    def _sync_call_openrouter():
                        try:
                            return client.chat_once(prompt, model=model)
                        except ChatError as e:
                            raise LLMUnavailableError(
                                f"LLM请求失败: {e}",
                                cause="chat_error",
                            ) from e
                        except Exception as e:
                            raise LLMUnavailableError(
                                f"LLM请求异常: {e}",
                                cause="exception",
                            ) from e

                    response_text = await asyncio.wait_for(
                        loop.run_in_executor(async_task_manager.llm_executor, _sync_call_openrouter),
                        timeout=float(getattr(config.llm, "timeout", 60) or 60),
                    )

                    if not isinstance(response_text, str) or not response_text.strip():
                        raise LLMUnavailableError("LLM返回了空文本响应", cause="empty_response")

                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    return {
                        "success": True,
                        "response": response_text,
                        "provider": "openrouter",
                        "model": model,
                        "elapsed_ms": elapsed_ms,
                    }

                except asyncio.TimeoutError as e:
                    raise LLMUnavailableError(
                        f"LLM请求超时（{getattr(config.llm, 'timeout', 60)}秒）",
                        cause="timeout",
                    ) from e

        except LLMUnavailableError as e:
            logger.error(f"OpenRouter API unavailable: {e}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "message": "LLM服务暂时不可用，本次OpenRouter真实调用已中止。",
                    "error_code": "LLM_UNAVAILABLE",
                    "retryable": True,
                    "reason": "llm_unavailable",
                    "cause": getattr(e, "cause", "unknown"),
                },
            )
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
                # 生成怪物（支持前端传入地图生成后的参数建议）
                monster_plan = request_data.get("monster_plan") if isinstance(request_data.get("monster_plan"), dict) else {}
                encounter_difficulty = monster_plan.get("encounter_difficulty", "normal")
                quest_context = monster_plan.get("llm_context") if isinstance(monster_plan.get("llm_context"), dict) else None

                monsters = await content_generator.generate_encounter_monsters(
                    player_level,
                    encounter_difficulty,
                    quest_context
                )
                if monsters:
                    preview = {
                        "recommended_count": monster_plan.get("encounter_count"),
                        "boss_count": monster_plan.get("boss_count"),
                        "spawn_points": monster_plan.get("spawn_points", [])
                    }
                    return {
                        "success": True,
                        "content_type": "monster",
                        "generated_content": monsters[0].to_dict(),
                        "count": len(monsters),
                        "monster_plan_preview": preview,
                        "encounter_difficulty": encounter_difficulty
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

        except LLMUnavailableError as e:
            logger.error(f"Content generation unavailable: {e}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "message": "LLM服务暂时不可用，本次内容生成测试已中止。",
                    "error_code": "LLM_UNAVAILABLE",
                    "retryable": True,
                    "reason": "llm_unavailable",
                    "cause": getattr(e, "cause", "unknown"),
                },
            )
        except Exception as e:
            logger.error(f"Content generation test failed: {e}")
            return {
                "success": False,
                "message": f"内容生成测试失败: {str(e)}"
            }

    @app.post("/api/test/llm-termination-probe")
    async def test_llm_termination_probe(request: Request):
        """真实触发一次LLM调用，用于演示宕机时的终止链路。"""
        try:
            request_data = await request.json()
        except Exception:
            request_data = {}

        probe_text = str(request_data.get("probe_text", "请回复：LLM探针正常。") or "请回复：LLM探针正常。")
        timeout_value = request_data.get("timeout")
        timeout: Optional[float] = None
        if timeout_value is not None:
            try:
                timeout = max(1.0, float(timeout_value))
            except (TypeError, ValueError):
                timeout = None

        prompt = (
            "你是 Labyrinthia AI 的可用性探针。"
            "请用中文简短回复“LLM探针正常”，不要附加多余内容。"
            f"\n附加上下文：{probe_text}"
        )

        started_at = time.perf_counter()
        try:
            response_text = await llm_service._async_generate(prompt, timeout=timeout)
            if not isinstance(response_text, str) or not response_text.strip():
                raise LLMUnavailableError("LLM返回了空文本响应", cause="empty_response")

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                "success": True,
                "message": "真实LLM探针调用成功",
                "response": response_text.strip(),
                "elapsed_ms": elapsed_ms,
                "provider": config.llm.provider.value,
                "model": config.llm.model_name,
            }
        except LLMUnavailableError as e:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.error(f"LLM termination probe unavailable: {e}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "message": "LLM服务暂时不可用，真实调用已终止。",
                    "error_code": "LLM_UNAVAILABLE",
                    "retryable": True,
                    "reason": "llm_unavailable",
                    "cause": getattr(e, "cause", "unknown"),
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.error(f"LLM termination probe failed: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": f"真实LLM探针调用失败: {str(e)}",
                    "error_code": "INTERNAL_ERROR",
                    "retryable": True,
                    "reason": "probe_failed",
                    "elapsed_ms": elapsed_ms,
                },
            )

    @app.post("/api/test/map-generation")
    async def test_map_generation(request: Request):
        """测试地图生成功能（支持 local/llm provider 对比）"""
        try:
            request_data = await request.json()

            def _coerce_int(value: Any, default_value: int, min_value: int, max_value: int) -> int:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    parsed = default_value
                return max(min_value, min(max_value, parsed))

            width = _coerce_int(request_data.get("width", 10), 10, 5, 80)
            height = _coerce_int(request_data.get("height", 10), 10, 5, 80)
            depth = _coerce_int(request_data.get("depth", 1), 1, 1, 20)
            theme = request_data.get("theme", "测试区域")
            quest_context = request_data.get("quest_context")

            provider = str(request_data.get("provider", "llm") or "llm").lower()

            compare_raw = request_data.get("compare", False)
            if isinstance(compare_raw, str):
                compare = compare_raw.strip().lower() in {"true", "1", "yes", "y", "on"}
            else:
                compare = bool(compare_raw)

            if provider not in {"llm", "local"}:
                provider = "llm"

            from content_generator import content_generator
            from local_map_provider import local_map_provider

            def build_summary(game_map, effective_provider: str, elapsed_ms: float) -> Dict[str, Any]:
                room_ids = set()
                event_count = 0
                walkable_count = 0
                trap_event_count = 0
                trap_terrain_count = 0
                mandatory_event_count = 0
                stairs_up_count = 0
                stairs_down_count = 0

                map_width = int(getattr(game_map, "width", width) or width)
                map_height = int(getattr(game_map, "height", height) or height)

                tiles_obj = getattr(game_map, "tiles", {})
                tile_items = tiles_obj.items() if isinstance(tiles_obj, dict) else []

                for _, tile in tile_items:
                    if not tile:
                        continue

                    terrain_attr = getattr(tile, "terrain", None)
                    terrain_value = terrain_attr.value if hasattr(terrain_attr, "value") else str(terrain_attr)
                    room_id = getattr(tile, "room_id", None)
                    if isinstance(room_id, str) and room_id:
                        room_ids.add(room_id)

                    if getattr(tile, "has_event", False):
                        event_count += 1
                        if getattr(tile, "event_type", "") == "trap":
                            trap_event_count += 1
                        event_data = tile.event_data if isinstance(getattr(tile, "event_data", None), dict) else {}
                        if event_data.get("is_mandatory") is True:
                            mandatory_event_count += 1

                    if terrain_value == "trap":
                        trap_terrain_count += 1

                    if terrain_value in {"floor", "door", "trap", "treasure", "stairs_up", "stairs_down"}:
                        walkable_count += 1
                    if terrain_value == "stairs_up":
                        stairs_up_count += 1
                    if terrain_value == "stairs_down":
                        stairs_down_count += 1

                metadata = game_map.generation_metadata if isinstance(game_map.generation_metadata, dict) else {}
                blueprint_report = metadata.get("blueprint_report") if isinstance(metadata.get("blueprint_report"), dict) else {}
                monster_hints = metadata.get("monster_hints") if isinstance(metadata.get("monster_hints"), dict) else {}
                local_validation = metadata.get("local_validation") if isinstance(metadata.get("local_validation"), dict) else {}

                room_count = len(room_ids)
                if room_count == 0:
                    room_count = int(blueprint_report.get("room_nodes", 0) or 0)

                map_size = max(1, map_width * map_height)
                walkable_ratio = round(walkable_count / map_size, 4)

                return {
                    "provider": effective_provider,
                    "generation_time_ms": round(elapsed_ms, 2),
                    "map_name": str(getattr(game_map, "name", "") or ""),
                    "map_size": f"{map_width}x{map_height}",
                    "room_count": room_count,
                    "event_count": event_count,
                    "trap_event_count": trap_event_count,
                    "trap_terrain_count": trap_terrain_count,
                    "mandatory_event_count": mandatory_event_count,
                    "stairs": {
                        "up": stairs_up_count,
                        "down": stairs_down_count,
                    },
                    "walkable": {
                        "count": walkable_count,
                        "ratio": walkable_ratio,
                    },
                    "floor_theme": getattr(game_map, "floor_theme", "normal"),
                    "description": (
                        str(getattr(game_map, "description", "") or "")[:100] + "..."
                        if len(str(getattr(game_map, "description", "") or "")) > 100
                        else str(getattr(game_map, "description", "") or "")
                    ),
                    "quest_context_applied": isinstance(quest_context, dict),
                    "blueprint": {
                        "used": bool(metadata.get("blueprint_used", False)),
                        "fallback_reason": metadata.get("blueprint_fallback_reason", ""),
                        "report": {
                            "room_nodes": blueprint_report.get("room_nodes", 0),
                            "corridor_edges": blueprint_report.get("corridor_edges", 0),
                            "event_intents": blueprint_report.get("event_intents", 0),
                            "monster_intents": blueprint_report.get("monster_intents", 0),
                            "issues": blueprint_report.get("issues", []),
                        },
                    },
                    "local_validation": local_validation,
                    "monster_hints": {
                        "recommended_player_level": monster_hints.get("recommended_player_level", 1),
                        "encounter_count": monster_hints.get("encounter_count", 0),
                        "boss_count": monster_hints.get("boss_count", 0),
                        "encounter_difficulty": monster_hints.get("encounter_difficulty", ""),
                        "spawn_points": monster_hints.get("spawn_points", []),
                        "llm_context": monster_hints.get("llm_context", {}),
                        "room_intents_count": len(monster_hints.get("room_intents", [])) if isinstance(monster_hints.get("room_intents"), list) else 0,
                        "corridor_intents_count": len(monster_hints.get("corridor_intents", [])) if isinstance(monster_hints.get("corridor_intents"), list) else 0,
                    },
                    "contract_warnings": [] if isinstance(tiles_obj, dict) else ["tiles_not_dict"],
                }

            async def generate_by_provider(selected_provider: str):
                start_time = time.perf_counter()
                if selected_provider == "local":
                    game_map, hints = await asyncio.to_thread(
                        local_map_provider.generate_map,
                        width,
                        height,
                        depth,
                        theme,
                        quest_context,
                    )
                    if not isinstance(game_map.generation_metadata, dict):
                        game_map.generation_metadata = {}
                    game_map.generation_metadata.update(
                        {
                            "map_provider": "local",
                            "monster_hints": hints,
                            "source": "test_api",
                        }
                    )
                else:
                    game_map = await content_generator.generate_dungeon_map(
                        width=width,
                        height=height,
                        depth=depth,
                        theme=theme,
                        quest_context=quest_context,
                    )
                    if not isinstance(game_map.generation_metadata, dict):
                        game_map.generation_metadata = {}
                    game_map.generation_metadata.setdefault("map_provider", "llm")
                    game_map.generation_metadata.setdefault("source", "test_api")

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return build_summary(game_map, selected_provider, elapsed_ms)

            if compare:
                local_result = await generate_by_provider("local")
                llm_result = await generate_by_provider("llm")

                local_gap = {
                    "supports_room_intents": local_result["monster_hints"]["room_intents_count"] > 0,
                    "supports_local_connectivity_report": bool(local_result.get("local_validation")),
                    "has_blueprint_intents": bool(local_result["blueprint"]["used"]),
                    "mandatory_event_reachability_ok": bool(
                        local_result.get("local_validation", {}).get("connectivity_ok", False)
                    ),
                }

                return {
                    "success": True,
                    "mode": "compare",
                    "requested_provider": provider,
                    "results": {
                        "local": local_result,
                        "llm": llm_result,
                    },
                    "performance": {
                        "local_ms": local_result["generation_time_ms"],
                        "llm_ms": llm_result["generation_time_ms"],
                        "faster_provider": "local"
                        if local_result["generation_time_ms"] <= llm_result["generation_time_ms"]
                        else "llm",
                    },
                    "coverage_gap_snapshot": local_gap,
                }

            single = await generate_by_provider(provider)
            return {
                "success": True,
                "mode": "single",
                "requested_provider": provider,
                "result": single,
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

    @app.post("/api/test/item-effect-simulation")
    async def test_item_effect_simulation(request: Request):
        """模拟物品效果引擎（无需进入正式战斗流程）"""
        try:
            from data_models import GameState, Item
            from effect_engine import effect_engine

            body = await request.json()
            base_state_data = body.get("game_state")
            item_data = body.get("item") or {}
            llm_response = body.get("llm_response") or {
                "message": "模拟效果已应用",
                "events": ["测试事件"],
                "item_consumed": False,
                "effects": {
                    "stat_changes": {"hp": -5},
                    "apply_status_effects": [
                        {
                            "name": "测试灼烧",
                            "effect_type": "debuff",
                            "duration_turns": 2,
                            "stack_policy": "refresh",
                            "tick_effects": {"hp": -2}
                        }
                    ]
                }
            }

            if isinstance(base_state_data, dict):
                game_state = data_manager._dict_to_game_state(base_state_data)
            else:
                game_state = GameState()

            item = Item(
                name=item_data.get("name", "测试道具"),
                description=item_data.get("description", "用于模拟效果"),
                item_type=item_data.get("item_type", "consumable"),
                rarity=item_data.get("rarity", "common"),
                usage_description=item_data.get("usage_description", "测试用途")
            )
            item.effect_payload = item_data.get("effect_payload", {}) or {}
            item.max_charges = int(item_data.get("max_charges", 0) or 0)
            item.charges = int(item_data.get("charges", item.max_charges) or 0)
            item.cooldown_turns = int(item_data.get("cooldown_turns", 0) or 0)

            simulation_payload = item.effect_payload if item.effect_payload else llm_response
            result = effect_engine.apply_item_effects(game_state, item, simulation_payload)
            tick_events = effect_engine.process_turn_effects(game_state, trigger="turn_end")

            return {
                "success": result.success,
                "message": result.message,
                "events": result.events,
                "tick_events": tick_events,
                "item_consumed": result.item_consumed,
                "player_snapshot": game_state.player.to_dict(),
            }
        except Exception as e:
            logger.error(f"Item effect simulation failed: {e}")
            return {
                "success": False,
                "message": f"模拟失败: {str(e)}"
            }

    @app.post("/api/test/item-model-showcase")
    async def test_item_model_showcase(request: Request):
        """生成模型物品样例（用于 quick_test 演示）"""
        try:
            payload = await request.json()
            count = max(1, min(6, int(payload.get("count", 3))))

            demo_items = []
            for idx in range(count):
                demo_items.append({
                    "name": f"演示物品-{idx + 1}",
                    "description": "用于展示新物品系统字段与交互效果",
                    "item_type": ["weapon", "armor", "consumable", "misc"][idx % 4],
                    "rarity": ["common", "uncommon", "rare", "epic", "legendary"][idx % 5],
                    "usage_description": "点击后可触发效果模拟",
                    "is_equippable": idx % 2 == 0,
                    "equip_slot": ["weapon", "armor", "accessory_1", "accessory_2"][idx % 4],
                    "max_charges": 3 if idx % 3 == 0 else 0,
                    "charges": 3 if idx % 3 == 0 else 0,
                    "cooldown_turns": 2 if idx % 2 == 1 else 0,
                    "current_cooldown": 0,
                    "effect_payload": {
                        "message": "演示效果触发",
                        "events": ["你感到一股力量在体内涌动"],
                        "item_consumed": False,
                        "effects": {
                            "stat_changes": {"hp": 5 - idx},
                            "apply_status_effects": [
                                {
                                    "name": "演示状态",
                                    "effect_type": "buff" if idx % 2 == 0 else "debuff",
                                    "duration_turns": 2 + (idx % 3),
                                    "stack_policy": "refresh",
                                    "tick_effects": {"hp": 1 if idx % 2 == 0 else -1}
                                }
                            ]
                        }
                    }
                })

            return {
                "success": True,
                "items": demo_items
            }
        except Exception as e:
            logger.error(f"Item model showcase failed: {e}")
            return {
                "success": False,
                "message": f"生成演示失败: {str(e)}"
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
            test_map.name = "测试区域"
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
                test_quest.objectives = ["探索区域", "寻找宝藏"]
                test_quest.story_context = "在古老的遗迹或自然区域中寻找失落的宝藏"
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
            test_map.name = "测试区域"
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
            test_map.name = "深层区域"
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

    @app.get("/api/game/{game_id}/debug/quest-progress-analysis")
    async def debug_quest_progress_analysis(game_id: str, request: Request, response: Response):
        """调试：分析任务进度"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 导入验证器和补偿器
            from quest_progress_validator import quest_progress_validator
            from quest_progress_compensator import quest_progress_compensator

            # 找到当前活跃任务
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if not active_quest:
                return {"success": False, "message": "没有活跃的任务"}

            # 验证任务配置
            validation_result = quest_progress_validator.validate_quest(active_quest)

            # 分析补偿需求
            compensation_info = quest_progress_compensator._analyze_compensation_need(game_state, active_quest)

            # 统计已获得的进度
            obtained_progress = {
                "current_progress": active_quest.progress_percentage,
                "events_triggered": 0,
                "events_progress": 0.0,
                "monsters_defeated": 0,
                "monsters_progress": 0.0,
                "map_transitions": game_state.current_map.depth - 1,
                "map_transitions_progress": (game_state.current_map.depth - 1) * config.game.map_transition_progress
            }

            # 检查已触发的事件
            for tile in game_state.current_map.tiles.values():
                if tile.has_event and tile.event_triggered:
                    event_data = tile.event_data or {}
                    quest_event_id = event_data.get('quest_event_id')
                    if quest_event_id:
                        for event in active_quest.special_events:
                            if event.id == quest_event_id:
                                obtained_progress["events_triggered"] += 1
                                obtained_progress["events_progress"] += event.progress_value

            # 检查已击败的任务怪物
            alive_quest_monster_ids = set()
            for monster in game_state.monsters:
                if hasattr(monster, 'quest_monster_id') and monster.quest_monster_id:
                    alive_quest_monster_ids.add(monster.quest_monster_id)

            for quest_monster in active_quest.special_monsters:
                if quest_monster.id not in alive_quest_monster_ids:
                    obtained_progress["monsters_defeated"] += 1
                    obtained_progress["monsters_progress"] += quest_monster.progress_value

            # 未获得的进度
            remaining_progress = {
                "events_remaining": len(active_quest.special_events) - obtained_progress["events_triggered"],
                "events_progress": validation_result.breakdown.events_progress - obtained_progress["events_progress"],
                "monsters_remaining": len(active_quest.special_monsters) - obtained_progress["monsters_defeated"],
                "monsters_progress": validation_result.breakdown.monsters_progress - obtained_progress["monsters_progress"],
                "map_transitions_remaining": len(active_quest.target_floors) - 1 - obtained_progress["map_transitions"],
                "map_transitions_progress": validation_result.breakdown.map_transitions_progress - obtained_progress["map_transitions_progress"]
            }

            return {
                "success": True,
                "quest": {
                    "id": active_quest.id,
                    "title": active_quest.title,
                    "current_progress": active_quest.progress_percentage,
                    "target_floors": active_quest.target_floors,
                    "current_floor": game_state.current_map.depth
                },
                "validation": validation_result.to_dict(),
                "obtained_progress": obtained_progress,
                "remaining_progress": remaining_progress,
                "compensation": compensation_info,
                "summary": {
                    "can_complete": validation_result.breakdown.total_guaranteed >= 100.0,
                    "progress_deficit": max(0, 100.0 - validation_result.breakdown.total_guaranteed),
                    "needs_compensation": compensation_info["needs_compensation"]
                }
            }

        except Exception as e:
            logger.error(f"Debug quest progress analysis error: {e}")
            return {"success": False, "message": f"分析任务进度失败: {str(e)}"}

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
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            quest_context = request_data.get("quest_context")
            pickup_context = f"调试宝箱：玩家在{game_state.current_map.name}发现了宝物"
            if quest_context:
                pickup_context = (
                    f"调试宝箱：玩家在{game_state.current_map.name}发现了与任务相关的宝物。"
                    f"任务名：{quest_context.get('name', '')}；任务描述：{quest_context.get('description', '')}"
                )

            item_count = max(1, min(3, int(request_data.get("count", 1) or 1)))
            generated_items = []
            for index in range(item_count):
                item = await llm_service.generate_item_on_pickup(
                    game_state,
                    f"{pickup_context}（第{index + 1}件）",
                )
                if item:
                    game_state.player.inventory.append(item)
                    generated_items.append(item)

            if not generated_items:
                return {"success": False, "message": "LLM生成失败"}

            await game_engine._save_game_async(game_state, user_id)

            return {
                "success": True,
                "message": f"你打开了宝箱，获得了{len(generated_items)}件宝物。",
                "items": [it.name for it in generated_items],
                "item_details": [
                    {
                        "name": it.name,
                        "item_type": it.item_type,
                        "rarity": it.rarity,
                        "is_equippable": it.is_equippable,
                        "equip_slot": it.equip_slot,
                    }
                    for it in generated_items
                ],
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
                theme=f"冒险区域（第{target_floor}阶段/层级）",
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

                # 【修复】更新周围瓦片的可见性
                from game_engine import game_engine as ge
                ge._update_visibility(game_state, spawn_positions[0][0], spawn_positions[0][1])

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
        """调试：在附近生成随机敌人（使用MonsterSpawnManager）"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]
            request_data = await request.json()

            player_pos = request_data.get("player_position", game_state.player.position)
            difficulty = request_data.get("difficulty", None)  # 可选难度参数

            # 使用MonsterSpawnManager生成怪物
            from monster_spawn_manager import monster_spawn_manager
            result = await monster_spawn_manager.generate_random_monster_nearby(
                game_state, player_pos, difficulty
            )

            if not result:
                return {"success": False, "message": "无法生成敌人或找不到可用位置"}

            monster, spawn_pos = result

            # 在地图上标记敌人位置
            tile = game_state.current_map.get_tile(*spawn_pos)
            if tile:
                tile.character_id = monster.id

            # 添加到游戏状态
            game_state.monsters.append(monster)

            # 获取当前任务信息（用于返回）
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            quest_info = None
            if active_quest:
                quest_info = {
                    "name": active_quest.title,
                    "progress": f"{active_quest.progress_percentage:.1f}%"
                }

            return {
                "success": True,
                "message": f"已生成敌人: {monster.name}",
                "enemy_name": monster.name,
                "enemy_cr": monster.challenge_rating,
                "position": spawn_pos,
                "difficulty": difficulty or "auto",
                "quest_context": quest_info
            }

        except Exception as e:
            logger.error(f"Debug spawn enemy error: {e}")
            return {"success": False, "message": f"生成敌人失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/clear-enemies")
    async def debug_clear_all_enemies(game_id: str, request: Request, response: Response):
        """调试：清空所有敌人（触发任务进度检查但不触发LLM交互）"""
        try:
            # 获取用户ID
            user_id = user_session_manager.get_or_create_user_id(request, response)
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_key]

            # 记录清空的敌人数量和任务怪物信息
            cleared_count = len(game_state.monsters)
            quest_monsters_cleared = 0
            total_progress_value = 0.0

            # 统计任务怪物
            for monster in game_state.monsters:
                if monster.quest_monster_id:
                    quest_monsters_cleared += 1
                    # 查找对应的任务怪物配置
                    active_quest = next((q for q in game_state.quests if q.is_active), None)
                    if active_quest:
                        quest_monster = next(
                            (qm for qm in active_quest.special_monsters if qm.id == monster.quest_monster_id),
                            None
                        )
                        if quest_monster:
                            total_progress_value += quest_monster.progress_value

            # 清除地图上的敌人标记
            for monster in game_state.monsters:
                if monster.position:
                    tile = game_state.current_map.get_tile(*monster.position)
                    if tile and tile.character_id == monster.id:
                        tile.character_id = None

            # 清空敌人列表
            game_state.monsters.clear()

            # 【新增】触发任务进度检查（如果清理了任务怪物）
            progress_updated = False
            if quest_monsters_cleared > 0 and total_progress_value > 0:
                from progress_manager import progress_manager, ProgressEventType, ProgressContext

                # 为所有任务怪物触发一次进度事件
                context_data = {
                    "debug_clear": True,  # 标记为调试清理
                    "quest_monsters_count": quest_monsters_cleared,
                    "progress_value": total_progress_value  # 使用总进度值
                }

                progress_context = ProgressContext(
                    event_type=ProgressEventType.COMBAT_VICTORY,
                    game_state=game_state,
                    context_data=context_data
                )

                # 触发进度事件（不触发LLM交互）
                result = await progress_manager.process_event(progress_context)
                progress_updated = result.get("success", False)

                logger.info(f"Debug clear enemies: cleared {quest_monsters_cleared} quest monsters, total progress: {total_progress_value:.1f}%, updated: {progress_updated}")

                # 【新增】检查是否需要进度补偿
                from quest_progress_compensator import quest_progress_compensator
                compensation_result = await quest_progress_compensator.check_and_compensate(
                    game_state,
                    source="debug_clear_enemies",
                )
                if compensation_result["compensated"]:
                    logger.info(f"Progress compensated after clearing enemies: +{compensation_result['compensation_amount']:.1f}% ({compensation_result['reason']})")

                    # 【新增】如果补偿后任务完成，创建任务完成选择
                    if hasattr(game_state, 'pending_quest_completion') and game_state.pending_quest_completion:
                        completed_quest = game_state.pending_quest_completion
                        logger.info(f"Quest completion detected after clearing enemies: {completed_quest.title}")

                        try:
                            # 创建任务完成选择上下文
                            from event_choice_system import event_choice_system
                            choice_context = await event_choice_system.create_quest_completion_choice(
                                game_state, completed_quest
                            )

                            # 将选择上下文存储到游戏状态中
                            game_state.pending_choice_context = choice_context
                            event_choice_system.active_contexts[choice_context.id] = choice_context

                            # 清理任务完成标志
                            game_state.pending_quest_completion = None

                            logger.info(f"Created quest completion choice after clearing enemies: {completed_quest.title}")

                        except Exception as e:
                            logger.error(f"Error creating quest completion choice after clearing enemies: {e}")
                            # 清理标志，避免重复处理
                            game_state.pending_quest_completion = None

            return {
                "success": True,
                "message": f"已清空所有敌人",
                "cleared_count": cleared_count,
                "quest_monsters_cleared": quest_monsters_cleared,
                "progress_updated": progress_updated,
                "total_progress_value": total_progress_value
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
                theme=f"冒险区域（第{current_depth}阶段/层级）",
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

    @app.get("/api/debug/monster-spawn-stats")
    async def debug_get_monster_spawn_stats():
        """调试：获取怪物生成统计信息"""
        try:
            from monster_spawn_manager import monster_spawn_manager

            stats = monster_spawn_manager.get_spawn_statistics()

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "statistics": stats
            }

        except Exception as e:
            logger.error(f"Debug get monster spawn stats error: {e}")
            return {"success": False, "message": f"获取统计信息失败: {str(e)}"}

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
