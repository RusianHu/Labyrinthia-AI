"""
Labyrinthia AI - FastAPI主应用
Main FastAPI application for the Labyrinthia AI game
"""

import asyncio
import logging
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
    description="AI驱动的DnD风格地牢冒险游戏",
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
templates = Jinja2Templates(directory="templates")


# 路由处理器
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页"""
    return templates.TemplateResponse("index.html", {"request": request})


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
    return game_state.to_dict()


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


@app.get("/api/config")
async def get_config():
    """获取游戏配置"""
    try:
        return {
            "game_name": config.game.game_name,
            "version": config.game.version,
            "debug_mode": config.game.debug_mode,
            "show_quest_progress": config.game.show_quest_progress,
            "quest_progress_multiplier": config.game.quest_progress_multiplier,
            "max_quest_floors": config.game.max_quest_floors,
            "max_player_level": config.game.max_player_level,
            "default_map_size": config.game.default_map_size
        }
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail="获取配置失败")


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


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "active_games": len(game_engine.active_games),
        "llm_provider": config.llm.provider.value,
        "version": config.game.version
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
