"""
测试进程管理器功能
Test progress manager functionality
"""

import asyncio
import logging
from datetime import datetime

from config import config
from data_models import GameState, Quest, Character, GameMap, Stats, Ability
from progress_manager import (
    progress_manager, ProgressEventType, ProgressContext, ProgressRule
)
from game_engine import GameEngine

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_basic_progress_system():
    """测试基础进度系统"""
    print("\n=== 测试基础进度系统 ===")
    
    # 创建测试游戏状态
    game_state = GameState()
    
    # 创建测试角色
    game_state.player = Character()
    game_state.player.name = "测试玩家"
    game_state.player.stats = Stats(level=1, hp=100, max_hp=100)
    game_state.player.abilities = Ability()
    
    # 创建测试地图
    game_state.current_map = GameMap()
    game_state.current_map.name = "测试地下城"
    game_state.current_map.depth = 1
    
    # 创建测试任务
    quest = Quest()
    quest.title = "探索地下城"
    quest.description = "深入地下城，寻找宝藏"
    quest.objectives = ["到达第2层", "击败怪物", "找到宝藏"]
    quest.completed_objectives = [False, False, False]
    quest.is_active = True
    quest.progress_percentage = 0.0
    quest.experience_reward = 500
    quest.story_context = "你站在地下城的入口，准备开始冒险..."
    
    game_state.quests.append(quest)
    
    print(f"初始任务进度: {quest.progress_percentage}%")
    print(f"任务描述: {quest.description}")
    
    # 测试地图切换事件
    print("\n--- 测试地图切换事件 ---")
    context = ProgressContext(
        event_type=ProgressEventType.MAP_TRANSITION,
        game_state=game_state,
        context_data=2  # 到达第2层
    )
    
    result = await progress_manager.process_event(context)
    print(f"地图切换结果: {result}")
    print(f"更新后进度: {quest.progress_percentage}%")
    print(f"故事背景: {quest.story_context}")
    
    # 测试战斗胜利事件
    print("\n--- 测试战斗胜利事件 ---")
    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={"monster_name": "哥布林", "challenge_rating": 1}
    )
    
    result = await progress_manager.process_event(context)
    print(f"战斗胜利结果: {result}")
    print(f"更新后进度: {quest.progress_percentage}%")
    
    # 测试宝藏发现事件
    print("\n--- 测试宝藏发现事件 ---")
    context = ProgressContext(
        event_type=ProgressEventType.TREASURE_FOUND,
        game_state=game_state,
        context_data={"treasure_type": "magic_item", "value": 200}
    )
    
    result = await progress_manager.process_event(context)
    print(f"宝藏发现结果: {result}")
    print(f"更新后进度: {quest.progress_percentage}%")
    print(f"任务是否完成: {quest.is_completed}")


async def test_custom_progress_rules():
    """测试自定义进度规则"""
    print("\n=== 测试自定义进度规则 ===")
    
    # 创建自定义规则
    def custom_exploration_calculator(context, current_progress):
        """自定义探索进度计算器"""
        if isinstance(context, dict):
            tiles_explored = context.get("tiles_explored", 0)
            return tiles_explored * 0.5  # 每探索一个瓦片增加0.5%进度
        return 2.0  # 默认增量
    
    custom_rule = ProgressRule(
        event_type=ProgressEventType.EXPLORATION,
        custom_calculator=custom_exploration_calculator
    )
    
    # 注册自定义规则
    progress_manager.register_rule(custom_rule)
    print("已注册自定义探索规则")
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "探索者"
    game_state.player.stats = Stats(level=2, hp=120, max_hp=120)
    game_state.player.abilities = Ability()
    
    game_state.current_map = GameMap()
    game_state.current_map.name = "探索测试地图"
    game_state.current_map.depth = 1
    
    # 创建任务
    quest = Quest()
    quest.title = "探索任务"
    quest.description = "探索未知区域"
    quest.is_active = True
    quest.progress_percentage = 10.0
    quest.experience_reward = 300
    
    game_state.quests.append(quest)
    
    print(f"初始进度: {quest.progress_percentage}%")
    
    # 测试自定义探索事件
    context = ProgressContext(
        event_type=ProgressEventType.EXPLORATION,
        game_state=game_state,
        context_data={"tiles_explored": 10}  # 探索了10个瓦片
    )
    
    result = await progress_manager.process_event(context)
    print(f"探索事件结果: {result}")
    print(f"更新后进度: {quest.progress_percentage}%")


async def test_progress_history():
    """测试进度历史记录"""
    print("\n=== 测试进度历史记录 ===")
    
    # 获取进度历史
    history = progress_manager.progress_history
    print(f"当前历史记录数量: {len(history)}")
    
    if history:
        print("\n最近的进度事件:")
        for i, event in enumerate(history[-3:], 1):  # 显示最近3个事件
            print(f"{i}. 事件类型: {event.event_type.value}")
            print(f"   时间: {event.timestamp.strftime('%H:%M:%S')}")
            print(f"   上下文: {event.context_data}")
            print()


async def test_progress_summary():
    """测试进度摘要"""
    print("\n=== 测试进度摘要 ===")
    
    # 创建有活跃任务的游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.current_map = GameMap()
    
    quest = Quest()
    quest.title = "主线任务"
    quest.description = "完成主要目标"
    quest.is_active = True
    quest.progress_percentage = 75.0
    quest.story_context = "你已经接近目标了..."
    quest.objectives = ["目标1", "目标2", "目标3"]
    quest.completed_objectives = [True, True, False]
    
    game_state.quests.append(quest)
    
    # 获取进度摘要
    summary = progress_manager.get_progress_summary(game_state)
    print("进度摘要:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


async def test_integration_with_game_engine():
    """测试与游戏引擎的集成"""
    print("\n=== 测试与游戏引擎的集成 ===")
    
    game_engine = GameEngine()
    
    try:
        # 创建新游戏
        print("创建新游戏...")
        game_state = await game_engine.create_new_game("测试玩家", "fighter")
        print(f"游戏创建成功，ID: {game_state.id}")
        
        # 检查初始任务
        if game_state.quests:
            quest = game_state.quests[0]
            print(f"初始任务: {quest.title}")
            print(f"初始进度: {quest.progress_percentage}%")
        
        # 模拟地图切换
        print("\n模拟地图切换...")
        game_state.pending_map_transition = "stairs_down"
        
        result = await game_engine.transition_map(game_state, "stairs_down")
        print(f"地图切换结果: {result['success']}")
        
        if result["success"] and game_state.quests:
            quest = game_state.quests[0]
            print(f"切换后任务进度: {quest.progress_percentage}%")
            print(f"任务故事: {quest.story_context}")
        
        # 清理
        game_engine.close_game(game_state.id)
        print("游戏已关闭")
        
    except Exception as e:
        logger.error(f"集成测试失败: {e}")
        print(f"集成测试失败: {e}")


async def main():
    """主测试函数"""
    print("开始测试进程管理器...")
    
    try:
        await test_basic_progress_system()
        await test_custom_progress_rules()
        await test_progress_history()
        await test_progress_summary()
        await test_integration_with_game_engine()
        
        print("\n=== 所有测试完成 ===")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        print(f"测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
