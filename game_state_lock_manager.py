"""
Labyrinthia AI - 游戏状态锁管理器
提供游戏状态的并发访问控制，防止竞态条件
"""

import asyncio
import logging
from typing import Dict, Tuple, Optional
from contextlib import asynccontextmanager
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class GameStateLock:
    """单个游戏状态的锁"""

    def __init__(self, game_key: Tuple[str, str]):
        self.game_key = game_key
        self.lock = asyncio.Lock()
        self.last_access = time.time()
        self.access_count = 0
        self.current_operation: Optional[str] = None
        self.current_acquired_at: float = 0.0
        self.last_wait_ms: int = 0
        self.last_hold_ms: int = 0

    async def acquire(self, operation: str = "unknown"):
        """获取锁"""
        await self.lock.acquire()
        now_ts = time.time()
        self.last_access = now_ts
        self.access_count += 1
        self.current_operation = operation
        self.current_acquired_at = now_ts
        logger.debug(f"Lock acquired for {self.game_key} - operation: {operation}")

    def release(self):
        """释放锁"""
        operation = self.current_operation
        hold_ms = 0
        if self.current_acquired_at > 0:
            hold_ms = int(max(0.0, (time.time() - self.current_acquired_at) * 1000.0))

        self.last_hold_ms = hold_ms
        self.current_acquired_at = 0.0
        self.current_operation = None

        if self.lock.locked():
            self.lock.release()
        logger.debug(f"Lock released for {self.game_key} - operation: {operation}, hold_ms={hold_ms}")
        
    def is_locked(self) -> bool:
        """检查是否已锁定"""
        return self.lock.locked()


class GameStateLockManager:
    """
    游戏状态锁管理器
    
    为每个游戏状态提供独立的锁，防止并发访问导致的数据不一致
    """
    
    def __init__(self):
        self._locks: Dict[Tuple[str, str], GameStateLock] = {}
        self._manager_lock = asyncio.Lock()  # 保护 _locks 字典本身的锁
        
    async def _get_or_create_lock(self, game_key: Tuple[str, str]) -> GameStateLock:
        """获取或创建游戏状态锁"""
        async with self._manager_lock:
            if game_key not in self._locks:
                self._locks[game_key] = GameStateLock(game_key)
                logger.debug(f"Created new lock for game {game_key}")
            return self._locks[game_key]
    
    @asynccontextmanager
    async def lock_game_state(self, user_id: str, game_id: str, operation: str = "unknown"):
        """
        锁定游戏状态的上下文管理器
        
        使用方法:
        async with lock_manager.lock_game_state(user_id, game_id, "save"):
            # 在这里安全地访问和修改游戏状态
            game_state = game_engine.active_games[game_key]
            # ... 进行操作 ...
        
        Args:
            user_id: 用户ID
            game_id: 游戏ID
            operation: 操作描述（用于调试）
        """
        game_key = (user_id, game_id)
        lock = await self._get_or_create_lock(game_key)
        
        # 记录等待时间
        wait_start = time.time()
        lock_acquired = False

        try:
            await lock.acquire(operation)
            lock_acquired = True
            wait_time = time.time() - wait_start
            lock.last_wait_ms = int(max(0.0, wait_time * 1000.0))

            if wait_time > 0.1:  # 如果等待超过100ms，记录警告
                logger.warning(
                    f"Lock wait time for {game_key} ({operation}): {wait_time:.3f}s"
                )

            yield lock

        finally:
            if lock_acquired:
                lock.release()
    
    async def cleanup_unused_locks(self, timeout_seconds: float = 3600):
        """
        清理长时间未使用的锁
        
        Args:
            timeout_seconds: 超时时间（秒），默认1小时
        """
        async with self._manager_lock:
            current_time = time.time()
            keys_to_remove = []
            
            for game_key, lock in self._locks.items():
                # 如果锁未被使用且超过超时时间，标记为待删除
                if not lock.is_locked() and (current_time - lock.last_access) > timeout_seconds:
                    keys_to_remove.append(game_key)
            
            # 删除未使用的锁
            for game_key in keys_to_remove:
                del self._locks[game_key]
                logger.info(f"Cleaned up unused lock for game {game_key}")
            
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} unused locks")
    
    def get_lock_stats(self) -> Dict:
        """获取锁统计信息"""
        stats = {
            "total_locks": len(self._locks),
            "locked_count": sum(1 for lock in self._locks.values() if lock.is_locked()),
            "locks": []
        }
        
        for game_key, lock in self._locks.items():
            stats["locks"].append({
                "game_key": game_key,
                "is_locked": lock.is_locked(),
                "access_count": lock.access_count,
                "last_access": datetime.fromtimestamp(lock.last_access).isoformat(),
                "current_operation": lock.current_operation,
                "last_wait_ms": lock.last_wait_ms,
                "last_hold_ms": lock.last_hold_ms,
            })
        
        return stats
    
    async def remove_lock(self, user_id: str, game_id: str):
        """
        移除指定游戏的锁（游戏关闭时调用）
        
        Args:
            user_id: 用户ID
            game_id: 游戏ID
        """
        game_key = (user_id, game_id)
        async with self._manager_lock:
            if game_key in self._locks:
                lock = self._locks[game_key]
                if lock.is_locked():
                    logger.warning(
                        f"Removing lock for {game_key} while it's still locked! "
                        f"Current operation: {lock.current_operation}"
                    )
                del self._locks[game_key]
                logger.debug(f"Removed lock for game {game_key}")


# 全局锁管理器实例
game_state_lock_manager = GameStateLockManager()

__all__ = ["GameStateLockManager", "game_state_lock_manager"]

