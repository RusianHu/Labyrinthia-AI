"""
Labyrinthia AI - 调试API模块
提供全面的调试接口，用于监控和管理游戏状态
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import Request, Response, HTTPException

from config import config
from game_engine import game_engine
from async_task_manager import async_task_manager, TaskType
from user_session_manager import user_session_manager
from llm_service import llm_service
from data_manager import data_manager
from progress_manager import progress_manager

logger = logging.getLogger(__name__)


class DebugAPI:
    """调试API类 - 提供全面的游戏状态监控和管理接口"""
    
    @staticmethod
    def get_system_status() -> Dict[str, Any]:
        """获取系统整体状态"""
        try:
            # 统计活跃游戏数量
            total_games = len(game_engine.active_games)
            games_by_user = {}
            for (user_id, game_id), game_state in game_engine.active_games.items():
                if user_id not in games_by_user:
                    games_by_user[user_id] = []
                games_by_user[user_id].append({
                    "game_id": game_id,
                    "player_name": game_state.player.name,
                    "level": game_state.player.stats.level,
                    "turn_count": game_state.turn_count
                })
            
            # 统计自动保存任务
            auto_save_tasks = len(game_engine.auto_save_tasks)
            
            # 获取异步任务统计
            task_stats = async_task_manager.get_task_stats()
            active_tasks = async_task_manager.get_active_tasks()
            
            # 格式化任务统计
            formatted_task_stats = {}
            for task_type, stats in task_stats.items():
                if stats["total_count"] > 0:
                    formatted_task_stats[task_type.value] = {
                        "total": stats["total_count"],
                        "success": stats["success_count"],
                        "error": stats["error_count"],
                        "cancelled": stats["cancelled_count"],
                        "avg_time": round(stats["avg_time"], 2)
                    }
            
            # 格式化活跃任务
            formatted_active_tasks = {}
            for task_id, task_info in active_tasks.items():
                formatted_active_tasks[task_id] = {
                    "type": task_info.task_type.value,
                    "description": task_info.description,
                    "runtime": round(task_info.get_runtime(), 2),
                    "is_done": task_info.is_done()
                }
            
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "system": {
                    "debug_mode": config.game.debug_mode,
                    "version": config.game.version,
                    "llm_provider": config.llm.provider.value,
                    "llm_model": config.llm.model_name
                },
                "games": {
                    "total_active": total_games,
                    "by_user": games_by_user,
                    "auto_save_tasks": auto_save_tasks
                },
                "async_tasks": {
                    "statistics": formatted_task_stats,
                    "active_tasks": formatted_active_tasks,
                    "active_count": len(active_tasks)
                }
            }
        except Exception as e:
            logger.error(f"Failed to get system status: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def get_game_detail(user_id: str, game_id: str) -> Dict[str, Any]:
        """获取游戏详细状态"""
        try:
            game_key = (user_id, game_id)
            
            if game_key not in game_engine.active_games:
                return {
                    "success": False,
                    "error": "游戏未找到"
                }
            
            game_state = game_engine.active_games[game_key]
            
            # 玩家信息
            player_info = {
                "id": game_state.player.id,
                "name": game_state.player.name,
                "class": game_state.player.character_class.value,
                "level": game_state.player.stats.level,
                "hp": f"{game_state.player.stats.hp}/{game_state.player.stats.max_hp}",
                "mp": f"{game_state.player.stats.mp}/{game_state.player.stats.max_mp}",
                "experience": game_state.player.stats.experience,
                "position": game_state.player.position,
                "inventory_count": len(game_state.player.inventory)
            }
            
            # 地图信息
            map_info = {
                "id": game_state.current_map.id,
                "name": game_state.current_map.name,
                "size": f"{game_state.current_map.width}x{game_state.current_map.height}",
                "depth": game_state.current_map.depth,
                "tile_count": len(game_state.current_map.tiles)
            }
            
            # 怪物信息
            monsters_info = []
            for monster in game_state.monsters:
                monsters_info.append({
                    "id": monster.id,
                    "name": monster.name,
                    "hp": f"{monster.stats.hp}/{monster.stats.max_hp}",
                    "position": monster.position,
                    "is_quest_monster": getattr(monster, 'is_quest_monster', False)
                })
            
            # 任务信息
            quests_info = []
            for quest in game_state.quests:
                quests_info.append({
                    "id": quest.id,
                    "title": quest.title,
                    "is_active": quest.is_active,
                    "is_completed": quest.is_completed,
                    "progress": f"{quest.progress_percentage:.1f}%",
                    "objectives_completed": f"{len(quest.completed_objectives)}/{len(quest.objectives)}"
                })
            
            # 游戏状态
            game_info = {
                "id": game_state.id,
                "turn_count": game_state.turn_count,
                "game_time": game_state.game_time,
                "is_game_over": game_state.is_game_over,
                "created_at": game_state.created_at.isoformat(),
                "last_saved": game_state.last_saved.isoformat(),
                "pending_events_count": len(game_state.pending_events),
                "pending_effects_count": len(game_state.pending_effects)
            }
            
            # 自动保存状态
            auto_save_info = {
                "enabled": game_key in game_engine.auto_save_tasks,
                "interval": config.game.auto_save_interval
            }
            
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "game": game_info,
                "player": player_info,
                "map": map_info,
                "monsters": monsters_info,
                "quests": quests_info,
                "auto_save": auto_save_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get game detail: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def get_memory_usage() -> Dict[str, Any]:
        """获取内存使用情况"""
        try:
            import sys
            import gc
            
            # 触发垃圾回收
            gc.collect()
            
            # 统计游戏状态占用
            game_states_count = len(game_engine.active_games)
            
            # 统计各类对象数量
            object_counts = {
                "game_states": game_states_count,
                "auto_save_tasks": len(game_engine.auto_save_tasks),
                "async_tasks": len(async_task_manager.tasks)
            }
            
            # 计算总怪物和任务数量
            total_monsters = 0
            total_quests = 0
            total_items = 0
            
            for game_state in game_engine.active_games.values():
                total_monsters += len(game_state.monsters)
                total_quests += len(game_state.quests)
                total_items += len(game_state.player.inventory)
            
            object_counts.update({
                "total_monsters": total_monsters,
                "total_quests": total_quests,
                "total_items": total_items
            })
            
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "object_counts": object_counts,
                "python_version": sys.version
            }
            
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def get_user_sessions() -> Dict[str, Any]:
        """获取用户会话信息"""
        try:
            # 统计每个用户的游戏数量
            user_games = {}
            for (user_id, game_id), game_state in game_engine.active_games.items():
                if user_id not in user_games:
                    user_games[user_id] = {
                        "active_games": [],
                        "total_turns": 0
                    }
                
                user_games[user_id]["active_games"].append({
                    "game_id": game_id,
                    "player_name": game_state.player.name,
                    "turn_count": game_state.turn_count
                })
                user_games[user_id]["total_turns"] += game_state.turn_count
            
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "total_users": len(user_games),
                "users": user_games
            }
            
        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return {
                "success": False,
                "error": str(e)
            }


    @staticmethod
    def get_save_files_info(user_id: str) -> Dict[str, Any]:
        """获取用户存档文件信息"""
        try:
            saves = user_session_manager.list_user_saves(user_id)

            # 统计信息
            total_size = 0
            for save in saves:
                save_path = user_session_manager.get_user_save_path(user_id, save["id"])
                if save_path.exists():
                    total_size += save_path.stat().st_size

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "total_saves": len(saves),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "saves": saves
            }

        except Exception as e:
            logger.error(f"Failed to get save files info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_async_tasks_detail() -> Dict[str, Any]:
        """获取异步任务详细信息"""
        try:
            # 获取所有活跃任务
            all_active_tasks = async_task_manager.get_active_tasks()

            # 按类型分组
            tasks_by_type = {}
            for task_id, task_info in all_active_tasks.items():
                task_type = task_info.task_type.value
                if task_type not in tasks_by_type:
                    tasks_by_type[task_type] = []

                tasks_by_type[task_type].append({
                    "task_id": task_id,
                    "description": task_info.description,
                    "runtime": round(task_info.get_runtime(), 2),
                    "is_done": task_info.is_done(),
                    "created_at": datetime.fromtimestamp(task_info.created_at).isoformat()
                })

            # 获取统计信息
            task_stats = async_task_manager.get_task_stats()

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "total_active": len(all_active_tasks),
                "tasks_by_type": tasks_by_type,
                "statistics": {
                    task_type.value: {
                        "total": stats["total_count"],
                        "success": stats["success_count"],
                        "error": stats["error_count"],
                        "cancelled": stats["cancelled_count"],
                        "avg_time": round(stats["avg_time"], 2)
                    }
                    for task_type, stats in task_stats.items()
                    if stats["total_count"] > 0
                }
            }

        except Exception as e:
            logger.error(f"Failed to get async tasks detail: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_llm_statistics() -> Dict[str, Any]:
        """获取LLM调用统计"""
        try:
            # 从异步任务统计中获取LLM相关数据
            task_stats = async_task_manager.get_task_stats()
            llm_stats = task_stats.get(TaskType.LLM_REQUEST, {})
            content_gen_stats = task_stats.get(TaskType.CONTENT_GENERATION, {})

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "llm_requests": {
                    "total": llm_stats.get("total_count", 0),
                    "success": llm_stats.get("success_count", 0),
                    "error": llm_stats.get("error_count", 0),
                    "avg_time": round(llm_stats.get("avg_time", 0), 2)
                },
                "content_generation": {
                    "total": content_gen_stats.get("total_count", 0),
                    "success": content_gen_stats.get("success_count", 0),
                    "error": content_gen_stats.get("error_count", 0),
                    "avg_time": round(content_gen_stats.get("avg_time", 0), 2)
                },
                "config": {
                    "provider": config.llm.provider.value,
                    "model": config.llm.model_name,
                    "max_tokens": config.llm.max_output_tokens,
                    "temperature": config.llm.temperature
                }
            }

        except Exception as e:
            logger.error(f"Failed to get LLM statistics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_config_info() -> Dict[str, Any]:
        """获取配置信息"""
        try:
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "game": {
                    "version": config.game.version,
                    "debug_mode": config.game.debug_mode,
                    "show_llm_debug": config.game.show_llm_debug,
                    "auto_save_interval": config.game.auto_save_interval
                },
                "llm": {
                    "provider": config.llm.provider.value,
                    "model_name": config.llm.model_name,
                    "max_output_tokens": config.llm.max_output_tokens,
                    "temperature": config.llm.temperature,
                    "timeout": config.llm.timeout
                },
                "data": {
                    "saves_dir": config.data.saves_dir
                },
                "debug": {
                    "show_performance_metrics": config.debug.show_performance_metrics,
                    "log_level": config.debug.log_level
                }
            }

        except Exception as e:
            logger.error(f"Failed to get config info: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# 全局调试API实例
debug_api = DebugAPI()

__all__ = ["DebugAPI", "debug_api"]


