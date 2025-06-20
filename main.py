"""
Labyrinthia AI - FastAPI主应用
Main FastAPI application for the Labyrinthia AI game
"""

import asyncio
import logging
import random
import time
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from game_engine import game_engine
from data_manager import data_manager
from llm_service import llm_service
from progress_manager import progress_manager
from event_choice_system import event_choice_system
from data_models import GameState


# 配置日志
logging.basicConfig(
    level=logging.INFO if config.game.debug_mode else logging.WARNING,
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


# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的处理"""
    logger.info("Starting Labyrinthia AI server...")
    
    # 启动时的初始化
    try:
        # 这里可以添加启动时的初始化逻辑
        logger.info("Server started successfully")
        yield
    finally:
        # 关闭时的清理
        logger.info("Shutting down Labyrinthia AI server...")
        
        # 保存所有活跃游戏
        for game_id, game_state in game_engine.active_games.items():
            try:
                data_manager.save_game_state(game_state)
                logger.info(f"Saved game: {game_id}")
            except Exception as e:
                logger.error(f"Failed to save game {game_id}: {e}")
        
        # 关闭LLM服务
        llm_service.close()
        
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
async def create_new_game(request: NewGameRequest):
    """创建新游戏"""
    try:
        logger.info(f"Creating new game for player: {request.player_name}")
        
        game_state = await game_engine.create_new_game(
            player_name=request.player_name,
            character_class=request.character_class
        )
        
        return {
            "success": True,
            "game_id": game_state.id,
            "message": f"欢迎 {request.player_name}！你的冒险开始了！",
            "narrative": game_state.last_narrative
        }
        
    except Exception as e:
        logger.error(f"Failed to create new game: {e}")
        raise HTTPException(status_code=500, detail=f"创建游戏失败: {str(e)}")


@app.post("/api/load/{save_id}")
async def load_game(save_id: str):
    """加载游戏"""
    try:
        logger.info(f"Loading game: {save_id}")
        
        game_state = await game_engine.load_game(save_id)
        
        if not game_state:
            raise HTTPException(status_code=404, detail="存档未找到")
        
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
async def get_game_state(game_id: str):
    """获取游戏状态"""
    if game_id not in game_engine.active_games:
        raise HTTPException(status_code=404, detail="游戏未找到")

    game_state = game_engine.active_games[game_id]

    # 获取游戏状态字典
    state_dict = game_state.to_dict()

    # 清理服务器端的pending_effects，避免重复触发
    if hasattr(game_state, 'pending_effects') and game_state.pending_effects:
        # 前端会处理这些特效，所以服务器端可以清理了
        game_state.pending_effects = []

    return state_dict


@app.post("/api/action")
async def perform_action(request: ActionRequest):
    """执行游戏行动"""
    try:
        logger.info(f"Processing action: {request.action} for game: {request.game_id}")
        
        result = await game_engine.process_player_action(
            game_id=request.game_id,
            action=request.action,
            parameters=request.parameters
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to process action: {e}")
        raise HTTPException(status_code=500, detail=f"处理行动失败: {str(e)}")


@app.post("/api/event-choice")
async def process_event_choice(request: EventChoiceRequest):
    """处理事件选择"""
    try:
        logger.info(f"Processing event choice: {request.choice_id} for context: {request.context_id}")

        if request.game_id not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        game_state = game_engine.active_games[request.game_id]

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

    except Exception as e:
        logger.error(f"Failed to process event choice: {e}")
        raise HTTPException(status_code=500, detail=f"处理事件选择失败: {str(e)}")


async def _process_post_choice_updates(game_state: GameState):
    """处理选择后的游戏状态更新"""
    try:
        # 检查是否需要生成新任务（确保玩家始终有活跃任务）
        if hasattr(game_state, 'pending_new_quest_generation') and game_state.pending_new_quest_generation:
            try:
                # 检查是否还有活跃任务
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                if not active_quest:
                    # 生成新任务
                    await game_engine._generate_new_quest_for_player(game_state)
                    logger.info("Generated new quest after choice processing")

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
async def get_pending_choice(game_id: str):
    """获取待处理的选择上下文"""
    try:
        if game_id not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        game_state = game_engine.active_games[game_id]

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


@app.post("/api/save/{game_id}")
async def save_game(game_id: str):
    """保存游戏"""
    try:
        if game_id not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")
        
        game_state = game_engine.active_games[game_id]
        success = data_manager.save_game_state(game_state)
        
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
async def list_saves():
    """获取存档列表"""
    try:
        saves = data_manager.list_saves()
        return saves
    except Exception as e:
        logger.error(f"Failed to list saves: {e}")
        raise HTTPException(status_code=500, detail=f"获取存档列表失败: {str(e)}")





@app.delete("/api/save/{save_id}")
async def delete_save(save_id: str):
    """删除存档"""
    try:
        success = data_manager.delete_save(save_id)

        if success:
            return {"success": True, "message": "存档已删除"}
        else:
            raise HTTPException(status_code=404, detail="存档未找到")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete save: {e}")
        raise HTTPException(status_code=500, detail=f"删除存档失败: {str(e)}")


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
        for section, values in updates.items():
            if hasattr(config, section):
                config.update_config(section, **values)

        return {"success": True, "message": "配置已更新"}

    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@app.post("/api/game/{game_id}/transition")
async def transition_map(game_id: str, transition_data: Dict[str, Any]):
    """手动切换地图"""
    try:
        transition_type = transition_data.get("type")
        if not transition_type:
            raise HTTPException(status_code=400, detail="缺少切换类型")

        result = await game_engine.transition_map(
            game_engine.active_games[game_id],
            transition_type
        )

        if result["success"]:
            # 返回更新后的游戏状态
            game_state = game_engine.active_games[game_id]
            return {
                "success": True,
                "message": result["message"],
                "events": result["events"],
                "game_state": game_state.to_dict()
            }
        else:
            return result

    except KeyError:
        raise HTTPException(status_code=404, detail="游戏未找到")
    except Exception as e:
        logger.error(f"Map transition failed: {e}")
        raise HTTPException(status_code=500, detail=f"地图切换失败: {str(e)}")


@app.get("/api/game/{game_id}/progress")
async def get_progress_summary(game_id: str):
    """获取游戏进度摘要"""
    try:
        if game_id not in game_engine.active_games:
            raise HTTPException(status_code=404, detail="游戏未找到")

        game_state = game_engine.active_games[game_id]
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
    @app.get("/api/debug/games")
    async def debug_list_games():
        """调试：列出所有活跃游戏"""
        games = {}
        for game_id, game_state in game_engine.active_games.items():
            games[game_id] = {
                "player_name": game_state.player.name,
                "player_level": game_state.player.stats.level,
                "turn_count": game_state.turn_count,
                "map_name": game_state.current_map.name
            }
        return games
    
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

    # ==================== 新增调试API端点 ====================

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
                # 检查是否有游戏状态
                for game_id, game_state in game_engine.active_games.items():
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
            for game_id, game_state in game_engine.active_games.items():
                game_info.append({
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

    @app.post("/api/game/{game_id}/debug/trigger-event")
    async def debug_trigger_random_event(game_id: str, request: Request):
        """调试：触发随机事件"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]
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
    async def debug_complete_current_quest(game_id: str):
        """调试：完成当前任务"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]

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
    async def debug_generate_test_item(game_id: str, request: Request):
        """调试：生成测试物品"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]
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

    @app.post("/api/game/{game_id}/debug/teleport")
    async def debug_teleport_to_floor(game_id: str, request: Request):
        """调试：传送到指定楼层"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]
            request_data = await request.json()

            target_floor = request_data.get("target_floor", 1)

            if target_floor < 1 or target_floor > config.game.max_quest_floors:
                return {"success": False, "message": f"楼层数必须在1-{config.game.max_quest_floors}之间"}

            # 直接生成指定楼层的地图
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

            # 清除旧地图上的角色标记
            old_tile = game_state.current_map.get_tile(*game_state.player.position)
            if old_tile:
                old_tile.character_id = None

            for monster in game_state.monsters:
                if monster.position:
                    monster_tile = game_state.current_map.get_tile(*monster.position)
                    if monster_tile:
                        monster_tile.character_id = None

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
                "message": f"已传送到第{target_floor}层",
                "new_map": game_state.current_map.name
            }

        except Exception as e:
            logger.error(f"Debug teleport error: {e}")
            return {"success": False, "message": f"传送失败: {str(e)}"}

    @app.post("/api/game/{game_id}/debug/spawn-enemy")
    async def debug_spawn_enemy_nearby(game_id: str, request: Request):
        """调试：在附近生成敌人"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]
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
    async def debug_clear_all_enemies(game_id: str):
        """调试：清空所有敌人"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]

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
    async def debug_regenerate_current_map(game_id: str, request: Request):
        """调试：重新生成当前地图"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]
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
    async def debug_restore_player_status(game_id: str):
        """调试：恢复玩家状态"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]

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
    async def debug_trigger_event_choice(game_id: str):
        """调试：手动触发事件选择"""
        try:
            if game_id not in game_engine.active_games:
                raise HTTPException(status_code=404, detail="游戏未找到")

            game_state = game_engine.active_games[game_id]

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
