"""
Labyrinthia AI - 用户会话管理模块
User Session Manager for managing user identification and save file organization
"""

import os
import uuid
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import Request, Response
from config import config

logger = logging.getLogger(__name__)


class UserSessionManager:
    """用户会话管理器 - 使用Cookie识别用户"""
    
    def __init__(self):
        self.session_cookie_name = "labyrinthia_user_id"
        self.session_timeout = timedelta(days=30)  # 会话有效期30天
        self.users_dir = Path(config.data.saves_dir) / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        
        # 用户元数据缓存
        self.user_metadata_cache: Dict[str, Dict[str, Any]] = {}
    
    def get_or_create_user_id(self, request: Request, response: Response) -> str:
        """
        从请求中获取或创建用户ID
        
        Args:
            request: FastAPI请求对象
            response: FastAPI响应对象
            
        Returns:
            用户ID字符串
        """
        # 尝试从Cookie中获取用户ID
        user_id = request.cookies.get(self.session_cookie_name)
        
        # 如果没有用户ID或用户ID无效，创建新的
        if not user_id or not self._is_valid_user_id(user_id):
            user_id = self._create_new_user_id()
            logger.info(f"Created new user ID: {user_id}")
        
        # 设置Cookie（每次请求都刷新过期时间）
        response.set_cookie(
            key=self.session_cookie_name,
            value=user_id,
            max_age=int(self.session_timeout.total_seconds()),
            httponly=True,
            samesite="lax"
        )
        
        # 确保用户目录存在
        self._ensure_user_directory(user_id)
        
        return user_id
    
    def _create_new_user_id(self) -> str:
        """创建新的用户ID"""
        return str(uuid.uuid4())
    
    def _is_valid_user_id(self, user_id: str) -> bool:
        """验证用户ID是否有效"""
        try:
            # 检查是否是有效的UUID格式
            uuid.UUID(user_id)
            return True
        except (ValueError, AttributeError):
            return False
    
    def _ensure_user_directory(self, user_id: str):
        """确保用户目录存在"""
        user_dir = self._get_user_directory(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建或更新用户元数据
        self._update_user_metadata(user_id)
    
    def _get_user_directory(self, user_id: str) -> Path:
        """获取用户存档目录"""
        return self.users_dir / user_id
    
    def _get_user_metadata_path(self, user_id: str) -> Path:
        """获取用户元数据文件路径"""
        return self._get_user_directory(user_id) / "user_metadata.json"
    
    def _update_user_metadata(self, user_id: str):
        """更新用户元数据"""
        metadata_path = self._get_user_metadata_path(user_id)
        
        # 读取现有元数据或创建新的
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read user metadata: {e}")
                metadata = {}
        else:
            metadata = {
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
            }
        
        # 更新最后访问时间
        metadata["last_access"] = datetime.now().isoformat()
        
        # 保存元数据
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user metadata: {e}")
    
    def get_user_save_path(self, user_id: str, save_id: str) -> Path:
        """获取用户的存档文件路径"""
        return self._get_user_directory(user_id) / f"{save_id}.json"
    
    def list_user_saves(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户的所有存档"""
        user_dir = self._get_user_directory(user_id)
        saves = []
        
        if not user_dir.exists():
            return saves
        
        for save_file in user_dir.glob("*.json"):
            # 跳过元数据文件
            if save_file.name == "user_metadata.json":
                continue
            
            try:
                with open(save_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                save_info = {
                    "id": data.get("id", save_file.stem),
                    "player_name": data.get("player", {}).get("name", "Unknown"),
                    "player_level": data.get("player", {}).get("stats", {}).get("level", 1),
                    "map_name": data.get("current_map", {}).get("name", "Unknown"),
                    "turn_count": data.get("turn_count", 0),
                    "created_at": data.get("created_at", ""),
                    "last_saved": data.get("last_saved", ""),
                    "file_size": save_file.stat().st_size
                }
                saves.append(save_info)
                
            except Exception as e:
                logger.error(f"Failed to read save file {save_file}: {e}")
        
        # 按最后保存时间排序
        saves.sort(key=lambda x: x.get("last_saved", ""), reverse=True)
        return saves
    
    def save_game_for_user(self, user_id: str, game_data: Dict[str, Any]) -> bool:
        """为用户保存游戏数据"""
        try:
            save_id = game_data.get("id")
            if not save_id:
                logger.error("Game data missing 'id' field")
                return False

            # 确保用户目录存在
            self._ensure_user_directory(user_id)

            save_path = self.get_user_save_path(user_id, save_id)

            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Game saved for user {user_id}: {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save game for user {user_id}: {e}")
            return False
    
    def load_game_for_user(self, user_id: str, save_id: str) -> Optional[Dict[str, Any]]:
        """为用户加载游戏数据"""
        try:
            save_path = self.get_user_save_path(user_id, save_id)
            
            if not save_path.exists():
                logger.warning(f"Save file not found: {save_path}")
                return None
            
            with open(save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"Game loaded for user {user_id}: {save_path}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load game for user {user_id}: {e}")
            return None
    
    def delete_save_for_user(self, user_id: str, save_id: str) -> bool:
        """删除用户的存档"""
        try:
            save_path = self.get_user_save_path(user_id, save_id)
            
            if save_path.exists():
                save_path.unlink()
                logger.info(f"Save deleted for user {user_id}: {save_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to delete save for user {user_id}: {e}")
            return False
    
    def export_save(self, user_id: str, save_id: str) -> Optional[Dict[str, Any]]:
        """导出存档数据（用于下载）"""
        return self.load_game_for_user(user_id, save_id)
    
    def import_save(self, user_id: str, save_data: Dict[str, Any]) -> bool:
        """导入存档数据"""
        try:
            # 验证存档数据的基本结构
            if not self._validate_save_data(save_data):
                logger.error("Invalid save data structure")
                return False
            
            # 生成新的save_id（避免冲突）
            original_id = save_data.get("id", str(uuid.uuid4()))
            new_save_id = str(uuid.uuid4())
            save_data["id"] = new_save_id
            
            # 添加导入标记
            save_data["imported_at"] = datetime.now().isoformat()
            save_data["original_id"] = original_id
            
            # 保存导入的存档
            return self.save_game_for_user(user_id, save_data)
            
        except Exception as e:
            logger.error(f"Failed to import save for user {user_id}: {e}")
            return False
    
    def _validate_save_data(self, save_data: Dict[str, Any]) -> bool:
        """验证存档数据的基本结构"""
        required_fields = ["player", "current_map"]
        return all(field in save_data for field in required_fields)
    
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """获取用户统计信息"""
        saves = self.list_user_saves(user_id)
        
        return {
            "user_id": user_id,
            "total_saves": len(saves),
            "total_playtime": sum(save.get("turn_count", 0) for save in saves),
            "highest_level": max((save.get("player_level", 1) for save in saves), default=1),
            "last_played": max((save.get("last_saved", "") for save in saves), default=""),
        }


# 全局用户会话管理器实例
user_session_manager = UserSessionManager()

__all__ = ["UserSessionManager", "user_session_manager"]

