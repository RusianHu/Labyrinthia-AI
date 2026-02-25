"""
Labyrinthia AI - 异步任务管理器
统一管理所有异步任务，提供任务追踪、监控、取消和错误处理功能
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

from config import config


logger = logging.getLogger(__name__)


class TaskType(Enum):
    """任务类型"""
    AUTO_SAVE = "auto_save"
    LLM_REQUEST = "llm_request"
    CONTENT_GENERATION = "content_generation"
    IO_OPERATION = "io_operation"
    BACKGROUND = "background"
    OTHER = "other"


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_type: TaskType
    task: asyncio.Task
    created_at: float = field(default_factory=time.time)
    description: str = ""
    
    def get_runtime(self) -> float:
        """获取任务运行时间（秒）"""
        return time.time() - self.created_at
    
    def is_done(self) -> bool:
        """检查任务是否完成"""
        return self.task.done()
    
    def get_exception(self) -> Optional[Exception]:
        """获取任务异常（如果有）"""
        if self.task.done() and not self.task.cancelled():
            try:
                return self.task.exception()
            except asyncio.CancelledError:
                return None
        return None


class AsyncTaskManager:
    """异步任务管理器"""
    
    def __init__(self):
        # 任务追踪
        self.tasks: Dict[str, TaskInfo] = {}
        self.task_counter = 0
        
        # 线程池管理
        self.llm_executor: Optional[ThreadPoolExecutor] = None
        self.io_executor: Optional[ThreadPoolExecutor] = None
        
        # 并发控制
        self.llm_semaphore: Optional[asyncio.Semaphore] = None
        
        # 性能统计
        self.task_stats: Dict[TaskType, Dict[str, Any]] = {
            task_type: {
                "total_count": 0,
                "success_count": 0,
                "error_count": 0,
                "cancelled_count": 0,
                "total_time": 0.0,
                "avg_time": 0.0
            }
            for task_type in TaskType
        }
        
        # 初始化标志
        self._initialized = False
    
    def initialize(self):
        """初始化管理器"""
        if self._initialized:
            logger.debug("AsyncTaskManager already initialized")
            return
        
        # 创建LLM专用线程池
        self.llm_executor = ThreadPoolExecutor(
            max_workers=config.game.max_concurrent_llm_requests,
            thread_name_prefix="llm_worker"
        )
        
        # 创建IO专用线程池（用于文件保存等）
        self.io_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="io_worker"
        )
        
        # 创建LLM并发控制信号量
        self.llm_semaphore = asyncio.Semaphore(config.game.max_concurrent_llm_requests)
        
        self._initialized = True
        logger.info("AsyncTaskManager initialized successfully")
    
    def create_task(
        self,
        coro,
        task_type: TaskType = TaskType.OTHER,
        description: str = "",
        task_id: Optional[str] = None
    ) -> asyncio.Task:
        """
        创建并追踪异步任务
        
        Args:
            coro: 协程对象
            task_type: 任务类型
            description: 任务描述
            task_id: 自定义任务ID（可选）
        
        Returns:
            创建的Task对象
        """
        if not self._initialized:
            self.initialize()
        
        # 生成任务ID
        if task_id is None:
            self.task_counter += 1
            task_id = f"{task_type.value}_{self.task_counter}_{int(time.time() * 1000)}"
        
        # 包装协程以添加错误处理和统计
        wrapped_coro = self._wrap_task(coro, task_id, task_type)
        
        # 创建任务
        task = asyncio.create_task(wrapped_coro)
        
        # 记录任务信息
        task_info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            task=task,
            description=description
        )
        self.tasks[task_id] = task_info
        
        # 更新统计
        self.task_stats[task_type]["total_count"] += 1
        
        logger.debug(f"Created task: {task_id} ({task_type.value}) - {description}")
        
        return task
    
    async def _wrap_task(self, coro, task_id: str, task_type: TaskType):
        """包装任务以添加错误处理和统计"""
        start_time = time.time()
        
        try:
            result = await coro
            
            # 更新成功统计
            elapsed = time.time() - start_time
            self.task_stats[task_type]["success_count"] += 1
            self.task_stats[task_type]["total_time"] += elapsed
            self._update_avg_time(task_type)
            
            if config.debug.show_performance_metrics:
                logger.debug(f"Task {task_id} completed in {elapsed:.2f}s")
            
            return result
            
        except asyncio.CancelledError:
            # 任务被取消
            self.task_stats[task_type]["cancelled_count"] += 1
            logger.debug(f"Task {task_id} was cancelled")
            raise
            
        except Exception as e:
            # 任务出错
            elapsed = time.time() - start_time
            self.task_stats[task_type]["error_count"] += 1
            logger.error(f"Task {task_id} failed after {elapsed:.2f}s: {e}")
            raise
            
        finally:
            # 清理任务记录（延迟清理，保留一段时间用于调试）
            await asyncio.sleep(1)
            if task_id in self.tasks:
                del self.tasks[task_id]
    
    def _update_avg_time(self, task_type: TaskType):
        """更新平均时间"""
        stats = self.task_stats[task_type]
        if stats["success_count"] > 0:
            stats["avg_time"] = stats["total_time"] / stats["success_count"]
    
    async def cancel_task(self, task_id: str, wait: bool = True) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            wait: 是否等待任务完成取消
        
        Returns:
            是否成功取消
        """
        if task_id not in self.tasks:
            logger.warning(f"Task {task_id} not found")
            return False
        
        task_info = self.tasks[task_id]
        
        if task_info.is_done():
            logger.debug(f"Task {task_id} already done")
            return False
        
        # 取消任务
        task_info.task.cancel()
        
        # 等待任务完成取消
        if wait:
            try:
                await task_info.task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error while cancelling task {task_id}: {e}")
        
        logger.debug(f"Cancelled task: {task_id}")
        return True
    
    async def cancel_all_tasks(self, task_type: Optional[TaskType] = None, wait: bool = True):
        """
        取消所有任务或指定类型的任务
        
        Args:
            task_type: 任务类型（None表示所有任务）
            wait: 是否等待所有任务完成取消
        """
        tasks_to_cancel = []
        
        for task_id, task_info in list(self.tasks.items()):
            if task_type is None or task_info.task_type == task_type:
                if not task_info.is_done():
                    tasks_to_cancel.append(task_id)
        
        logger.info(f"Cancelling {len(tasks_to_cancel)} tasks...")
        
        # 取消所有任务
        for task_id in tasks_to_cancel:
            await self.cancel_task(task_id, wait=wait)
        
        logger.info(f"Cancelled {len(tasks_to_cancel)} tasks")
    
    def get_active_tasks(self, task_type: Optional[TaskType] = None) -> Dict[str, TaskInfo]:
        """获取活跃任务"""
        active_tasks = {}
        
        for task_id, task_info in self.tasks.items():
            if not task_info.is_done():
                if task_type is None or task_info.task_type == task_type:
                    active_tasks[task_id] = task_info
        
        return active_tasks
    
    def get_task_stats(self) -> Dict[TaskType, Dict[str, Any]]:
        """获取任务统计信息"""
        return self.task_stats.copy()
    
    def print_stats(self):
        """打印统计信息"""
        logger.info("=== Async Task Statistics ===")
        for task_type, stats in self.task_stats.items():
            if stats["total_count"] > 0:
                logger.info(f"{task_type.value}:")
                logger.info(f"  Total: {stats['total_count']}")
                logger.info(f"  Success: {stats['success_count']}")
                logger.info(f"  Error: {stats['error_count']}")
                logger.info(f"  Cancelled: {stats['cancelled_count']}")
                logger.info(f"  Avg Time: {stats['avg_time']:.2f}s")
    
    async def shutdown(self):
        """关闭管理器"""
        logger.info("Shutting down AsyncTaskManager...")
        
        # 取消所有活跃任务
        await self.cancel_all_tasks(wait=True)
        
        # 关闭线程池
        if self.llm_executor:
            self.llm_executor.shutdown(wait=True)
            logger.info("LLM executor shutdown complete")
        
        if self.io_executor:
            self.io_executor.shutdown(wait=True)
            logger.info("IO executor shutdown complete")
        
        # 打印统计信息
        if config.debug.show_performance_metrics:
            self.print_stats()
        
        self._initialized = False
        logger.info("AsyncTaskManager shutdown complete")


def async_performance_monitor(func=None, *, task_type: TaskType = TaskType.OTHER, description: str = ""):
    """
    异步性能监控装饰器（支持带参数和不带参数两种用法）

    用法1（不带参数）:
        @async_performance_monitor
        async def generate_map(...):
            ...

    用法2（带参数）:
        @async_performance_monitor(task_type=TaskType.LLM_REQUEST, description="生成地图")
        async def generate_map(...):
            ...
    """
    def decorator(f):
        async def wrapper(*args, **kwargs):
            if not config.debug.show_performance_metrics:
                # 如果未启用性能监控，直接执行
                return await f(*args, **kwargs)

            start_time = time.time()
            func_name = f.__name__
            desc = description or func_name

            try:
                result = await f(*args, **kwargs)
                elapsed = time.time() - start_time

                logger.debug(f"⏱️ {desc} completed in {elapsed:.2f}s")

                return result

            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"❌ {desc} failed after {elapsed:.2f}s: {e}")
                raise

        # 保留原函数的元数据
        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper

    # 支持不带参数的用法
    if func is not None:
        return decorator(func)

    # 支持带参数的用法
    return decorator


# 全局异步任务管理器实例
async_task_manager = AsyncTaskManager()

__all__ = [
    "AsyncTaskManager",
    "async_task_manager",
    "TaskType",
    "TaskInfo",
    "async_performance_monitor"
]

