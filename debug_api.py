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
from game_state_lock_manager import game_state_lock_manager

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
            
            aggregate_map_metrics: Dict[str, Any] = {
                "total": 0,
                "success": 0,
                "failed": 0,
                "fallback_used": 0,
                "rollback_used": 0,
                "repairs": 0,
                "stairs_violations": 0,
                "error_codes": {},
            }
            for gs in game_engine.active_games.values():
                gm = gs.generation_metrics if isinstance(getattr(gs, "generation_metrics", None), dict) else {}
                mm = gm.get("map_generation") if isinstance(gm.get("map_generation"), dict) else {}
                aggregate_map_metrics["total"] += int(mm.get("total", 0) or 0)
                aggregate_map_metrics["success"] += int(mm.get("success", 0) or 0)
                aggregate_map_metrics["failed"] += int(mm.get("failed", 0) or 0)
                aggregate_map_metrics["fallback_used"] += int(mm.get("fallback_used", 0) or 0)
                aggregate_map_metrics["rollback_used"] += int(mm.get("rollback_used", 0) or 0)
                aggregate_map_metrics["repairs"] += int(mm.get("repairs", 0) or 0)
                aggregate_map_metrics["stairs_violations"] += int(mm.get("stairs_violations", 0) or 0)
                aggregate_map_metrics["unreachable_reports"] = int(aggregate_map_metrics.get("unreachable_reports", 0) or 0) + int(mm.get("unreachable_reports", 0) or 0)
                error_codes = mm.get("error_codes") if isinstance(mm.get("error_codes"), dict) else {}
                for code, count in error_codes.items():
                    key = str(code)
                    aggregate_map_metrics["error_codes"][key] = int(aggregate_map_metrics["error_codes"].get(key, 0) or 0) + int(count or 0)

            total = max(1, int(aggregate_map_metrics.get("total", 0) or 0))
            unreachable_rate = float(aggregate_map_metrics.get("unreachable_reports", 0) or 0) / float(total)
            stairs_violation_rate = float(aggregate_map_metrics.get("stairs_violations", 0) or 0) / float(total)

            aggregate_progress_metrics: Dict[str, Any] = {
                "total_events": 0,
                "anomaly_events": 0,
                "final_objective_direct_completion": 0,
                "final_objective_guard_blocked": 0,
                "anomaly_codes": {},
                "final_objective_guard_blocked_reasons": {},
            }
            for gs in game_engine.active_games.values():
                gm = gs.generation_metrics if isinstance(getattr(gs, "generation_metrics", None), dict) else {}
                pm = gm.get("progress_metrics") if isinstance(gm.get("progress_metrics"), dict) else {}
                aggregate_progress_metrics["total_events"] += int(pm.get("total_events", 0) or 0)
                aggregate_progress_metrics["anomaly_events"] += int(pm.get("anomaly_events", 0) or 0)
                aggregate_progress_metrics["final_objective_direct_completion"] += int(pm.get("final_objective_direct_completion", 0) or 0)
                aggregate_progress_metrics["final_objective_guard_blocked"] += int(pm.get("final_objective_guard_blocked", 0) or 0)
                anomaly_codes = pm.get("anomaly_codes") if isinstance(pm.get("anomaly_codes"), dict) else {}
                for code, count in anomaly_codes.items():
                    key = str(code)
                    aggregate_progress_metrics["anomaly_codes"][key] = int(aggregate_progress_metrics["anomaly_codes"].get(key, 0) or 0) + int(count or 0)
                blocked_reasons = pm.get("final_objective_guard_blocked_reasons") if isinstance(pm.get("final_objective_guard_blocked_reasons"), dict) else {}
                for reason, count in blocked_reasons.items():
                    key = str(reason)
                    aggregate_progress_metrics["final_objective_guard_blocked_reasons"][key] = int(aggregate_progress_metrics["final_objective_guard_blocked_reasons"].get(key, 0) or 0) + int(count or 0)

            progress_total = max(1, int(aggregate_progress_metrics.get("total_events", 0) or 0))
            anomaly_rate = float(aggregate_progress_metrics.get("anomaly_events", 0) or 0) / float(progress_total)
            guard_total = int(aggregate_progress_metrics.get("final_objective_direct_completion", 0) or 0) + int(aggregate_progress_metrics.get("final_objective_guard_blocked", 0) or 0)
            guard_den = max(1, guard_total)
            final_guard_block_rate = float(aggregate_progress_metrics.get("final_objective_guard_blocked", 0) or 0) / float(guard_den)

            alerts: List[Dict[str, Any]] = []

            def _append_alert(metric: str, value: float, warn: float, block: float):
                severity = "ok"
                if value >= block:
                    severity = "p1"
                elif value >= warn:
                    severity = "p2"
                if severity != "ok":
                    alerts.append(
                        {
                            "metric": metric,
                            "severity": severity,
                            "value": round(value, 6),
                            "warn_threshold": warn,
                            "block_threshold": block,
                        }
                    )

            _append_alert(
                "key_objective_unreachable_rate",
                unreachable_rate,
                float(getattr(config.game, "map_unreachable_rate_warn", 0.001)),
                float(getattr(config.game, "map_unreachable_rate_block", 0.01)),
            )
            _append_alert(
                "stairs_violation_rate",
                stairs_violation_rate,
                float(getattr(config.game, "map_stairs_violation_warn", 0.001)),
                float(getattr(config.game, "map_stairs_violation_block", 0.01)),
            )
            _append_alert(
                "progress_anomaly_rate",
                anomaly_rate,
                float(getattr(config.game, "progress_anomaly_rate_warn", 0.02)),
                float(getattr(config.game, "progress_anomaly_rate_block", 0.1)),
            )
            _append_alert(
                "final_objective_guard_block_rate",
                final_guard_block_rate,
                float(getattr(config.game, "final_objective_guard_block_warn", 0.1)),
                float(getattr(config.game, "final_objective_guard_block_block", 0.3)),
            )

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "system": {
                    "debug_mode": config.game.debug_mode,
                    "version": config.game.version,
                    "llm_provider": config.llm.provider.value,
                    "llm_model": config.llm.model_name,
                    "map_generation_release_stage": getattr(config.game, "map_generation_release_stage", "debug"),
                    "map_generation_canary_percent": getattr(config.game, "map_generation_canary_percent", 0),
                    "map_generation_force_legacy_chain": getattr(config.game, "map_generation_force_legacy_chain", False),
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
                },
                "map_generation_metrics": aggregate_map_metrics,
                "progress_metrics": aggregate_progress_metrics,
                "derived_rates": {
                    "key_objective_unreachable_rate": round(unreachable_rate, 6),
                    "stairs_violation_rate": round(stairs_violation_rate, 6),
                    "progress_anomaly_rate": round(anomaly_rate, 6),
                    "final_objective_guard_block_rate": round(final_guard_block_rate, 6),
                },
                "alerts": {
                    "blocking_enabled": bool(getattr(config.game, "map_alert_blocking_enabled", False)),
                    "items": alerts,
                    "has_p1": any(a.get("severity") == "p1" for a in alerts),
                },
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


    @staticmethod
    def get_map_detail(user_id: str, game_id: str) -> Dict[str, Any]:
        """获取地图详细信息"""
        try:
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                return {
                    "success": False,
                    "error": "游戏未找到"
                }

            game_state = game_engine.active_games[game_key]
            current_map = game_state.current_map

            # 基本地图信息
            map_info = {
                "id": current_map.id,
                "name": current_map.name,
                "width": current_map.width,
                "height": current_map.height,
                "depth": current_map.depth,
                "total_tiles": len(current_map.tiles)
            }

            # 统计地形类型
            terrain_stats = {}
            explored_count = 0
            visible_count = 0

            # 收集所有瓦片信息
            tiles_data = []
            for position, tile in current_map.tiles.items():
                # 统计地形
                terrain_name = tile.terrain.value
                terrain_stats[terrain_name] = terrain_stats.get(terrain_name, 0) + 1

                # 统计探索和可见
                if tile.is_explored:
                    explored_count += 1
                if tile.is_visible:
                    visible_count += 1

                # 收集瓦片详细信息
                tile_info = {
                    "position": [tile.x, tile.y],
                    "terrain": terrain_name,
                    "is_explored": tile.is_explored,
                    "is_visible": tile.is_visible
                }

                # 添加房间信息
                if tile.room_type:
                    tile_info["room_type"] = tile.room_type
                if tile.room_id:
                    tile_info["room_id"] = tile.room_id

                # 添加角色信息
                if tile.character_id:
                    tile_info["character_id"] = tile.character_id

                # 添加物品信息
                if tile.items:
                    tile_info["items"] = [
                        {
                            "id": item.id,
                            "name": item.name,
                            "type": item.item_type.value
                        }
                        for item in tile.items
                    ]

                # 添加事件信息
                if tile.has_event:
                    tile_info["has_event"] = True
                    tile_info["event_type"] = tile.event_type
                    tile_info["event_triggered"] = tile.event_triggered
                    if tile.event_data:
                        tile_info["event_data"] = tile.event_data

                tiles_data.append(tile_info)

            # 统计信息
            stats = {
                "terrain_distribution": terrain_stats,
                "explored_tiles": explored_count,
                "visible_tiles": visible_count,
                "exploration_percentage": round(explored_count / len(current_map.tiles) * 100, 2)
            }

            # 查找特殊位置
            special_positions = {
                "stairs_up": [],
                "stairs_down": [],
                "doors": [],
                "chests": [],
                "events": []
            }

            for position, tile in current_map.tiles.items():
                pos = [tile.x, tile.y]

                if tile.terrain.value == "stairs_up":
                    special_positions["stairs_up"].append(pos)
                elif tile.terrain.value == "stairs_down":
                    special_positions["stairs_down"].append(pos)
                elif tile.terrain.value == "door":
                    special_positions["doors"].append(pos)
                elif tile.terrain.value == "chest":
                    special_positions["chests"].append(pos)

                if tile.has_event:
                    special_positions["events"].append({
                        "position": pos,
                        "type": tile.event_type,
                        "triggered": tile.event_triggered
                    })

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "game_id": game_id,
                "map_info": map_info,
                "statistics": stats,
                "special_positions": special_positions,
                "tiles": tiles_data
            }

        except Exception as e:
            logger.error(f"Failed to get map detail: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_map_summary(user_id: str, game_id: str) -> Dict[str, Any]:
        """获取地图摘要信息（不包含所有瓦片数据，更轻量）"""
        try:
            game_key = (user_id, game_id)

            if game_key not in game_engine.active_games:
                return {
                    "success": False,
                    "error": "游戏未找到"
                }

            game_state = game_engine.active_games[game_key]
            current_map = game_state.current_map

            # 基本信息
            map_info = {
                "id": current_map.id,
                "name": current_map.name,
                "width": current_map.width,
                "height": current_map.height,
                "depth": current_map.depth
            }

            # 统计信息
            terrain_stats = {}
            explored_count = 0

            for position, tile in current_map.tiles.items():
                terrain_name = tile.terrain.value
                terrain_stats[terrain_name] = terrain_stats.get(terrain_name, 0) + 1
                if tile.is_explored:
                    explored_count += 1

            # 特殊位置统计
            special_counts = {
                "stairs_up": sum(1 for t in current_map.tiles.values() if t.terrain.value == "stairs_up"),
                "stairs_down": sum(1 for t in current_map.tiles.values() if t.terrain.value == "stairs_down"),
                "doors": sum(1 for t in current_map.tiles.values() if t.terrain.value == "door"),
                "chests": sum(1 for t in current_map.tiles.values() if t.terrain.value == "chest"),
                "events": sum(1 for t in current_map.tiles.values() if t.has_event)
            }

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "map_info": map_info,
                "terrain_distribution": terrain_stats,
                "exploration_percentage": round(explored_count / len(current_map.tiles) * 100, 2),
                "special_counts": special_counts
            }

        except Exception as e:
            logger.error(f"Failed to get map summary: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    @staticmethod
    def get_generation_trace(user_id: str, game_id: str) -> Dict[str, Any]:
        """获取地图生成/补丁/进度账本的完整调试链路"""
        try:
            game_key = (user_id, game_id)
            if game_key not in game_engine.active_games:
                return {
                    "success": False,
                    "error": "游戏未找到"
                }

            game_state = game_engine.active_games[game_key]
            active_quest = next((q for q in game_state.quests if q.is_active), None)

            generation_metadata = game_state.current_map.generation_metadata if isinstance(game_state.current_map.generation_metadata, dict) else {}
            generation_metrics = game_state.generation_metrics if isinstance(game_state.generation_metrics, dict) else {}

            map_generation_metrics = generation_metrics.get("map_generation", {}) if isinstance(generation_metrics.get("map_generation"), dict) else {}
            map_generation_last = generation_metrics.get("map_generation_last", {}) if isinstance(generation_metrics.get("map_generation_last"), dict) else {}

            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "game_id": game_id,
                "map": {
                    "id": game_state.current_map.id,
                    "name": game_state.current_map.name,
                    "depth": game_state.current_map.depth,
                },
                "release_strategy": {
                    "stage": getattr(config.game, "map_generation_release_stage", "debug"),
                    "canary_percent": getattr(config.game, "map_generation_canary_percent", 0),
                    "force_legacy": getattr(config.game, "map_generation_force_legacy_chain", False),
                    "disable_high_risk_patch": getattr(config.game, "map_generation_disable_high_risk_patch", True),
                },
                "generation_metadata": generation_metadata,
                "map_generation_metrics": map_generation_metrics,
                "map_generation_last": map_generation_last,
                "patch_batches": generation_metrics.get("patch_batches", []),
                "spawn_audit": generation_metrics.get("spawn_audit", []),
                "quest": {
                    "active_quest_id": active_quest.id if active_quest else "",
                    "active_quest_title": active_quest.title if active_quest else "",
                    "progress_plan": getattr(active_quest, "progress_plan", {}) if active_quest else {},
                    "completion_guard": getattr(active_quest, "completion_guard", {}) if active_quest else {},
                    "progress_ledger": getattr(active_quest, "progress_ledger", []) if active_quest else [],
                },
                "progress_metrics": generation_metrics.get("progress_metrics", {}),
                "migration_history": game_state.migration_history if isinstance(getattr(game_state, "migration_history", None), list) else [],
                "lock_stats": game_state_lock_manager.get_lock_stats(),
            }
        except Exception as e:
            logger.error(f"Failed to get generation trace: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def export_debug_package(user_id: str, game_id: str) -> Dict[str, Any]:
        """导出完整调试包（JSON对象）"""
        try:
            trace = DebugAPI.get_generation_trace(user_id, game_id)
            if not trace.get("success"):
                return trace

            llm_debug = {
                "last_request": llm_service.get_last_request_payload(),
                "last_response": llm_service.get_last_response_payload(),
            }

            game_key = (user_id, game_id)
            game_state = game_engine.active_games[game_key]
            package = {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "game_id": game_id,
                "user_id": user_id,
                "game_snapshot": {
                    "turn_count": game_state.turn_count,
                    "game_time": game_state.game_time,
                    "save_version": game_state.save_version,
                    "migration_history": game_state.migration_history if isinstance(game_state.migration_history, list) else [],
                    "player": {
                        "id": game_state.player.id,
                        "name": game_state.player.name,
                        "level": game_state.player.stats.level,
                        "position": game_state.player.position,
                    },
                },
                "trace": trace,
                "llm_debug": llm_debug,
            }
            return package
        except Exception as e:
            logger.error(f"Failed to export debug package: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# 全局调试API实例
debug_api = DebugAPI()

__all__ = ["DebugAPI", "debug_api"]


