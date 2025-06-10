#!/usr/bin/env python3
"""
测试新功能：地图切换、任务进度、部分遮罩
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_engine import game_engine
from data_models import GameState, Quest
from content_generator import content_generator

async def test_quest_system():
    """测试任务系统的新功能"""
    print("=== 测试任务系统 ===")
    
    # 创建新游戏
    result = await game_engine.create_new_game("测试玩家", "warrior")
    if not result["success"]:
        print(f"创建游戏失败: {result['message']}")
        return
    
    game_id = result["game_id"]
    game_state = game_engine.active_games[game_id]
    
    print(f"游戏ID: {game_id}")
    print(f"玩家: {game_state.player.name}")
    print(f"当前地图: {game_state.current_map.name}")
    print(f"地图深度: {game_state.current_map.depth}")
    
    # 检查任务
    if game_state.quests:
        quest = game_state.quests[0]
        print(f"\n任务信息:")
        print(f"  标题: {quest.title}")
        print(f"  描述: {quest.description}")
        print(f"  进度: {quest.progress_percentage}%")
        print(f"  故事背景: {quest.story_context}")
        print(f"  目标: {quest.objectives}")
    else:
        print("没有找到任务")
    
    return game_id, game_state

async def test_map_transition():
    """测试地图切换功能"""
    print("\n=== 测试地图切换 ===")
    
    game_id, game_state = await test_quest_system()
    
    # 模拟移动到楼梯位置
    print(f"当前待切换状态: {game_state.pending_map_transition}")
    
    # 手动设置待切换状态（模拟移动到楼梯）
    game_state.pending_map_transition = "stairs_down"
    print("模拟移动到下楼梯位置...")
    print(f"待切换状态: {game_state.pending_map_transition}")
    
    # 测试地图切换
    result = await game_engine.transition_map(game_state, "stairs_down")
    print(f"切换结果: {result}")
    
    if result["success"]:
        print(f"新地图: {game_state.current_map.name}")
        print(f"新深度: {game_state.current_map.depth}")
        
        # 检查任务进度是否更新
        if game_state.quests:
            quest = game_state.quests[0]
            print(f"任务进度更新: {quest.progress_percentage}%")
            print(f"LLM笔记: {quest.llm_notes}")
    
    # 清理
    game_engine.close_game(game_id)

async def test_quest_progress_update():
    """测试任务进度更新"""
    print("\n=== 测试任务进度更新 ===")
    
    # 创建测试游戏状态
    game_state = GameState()
    quest = Quest()
    quest.title = "测试任务"
    quest.description = "这是一个测试任务"
    quest.objectives = ["目标1", "目标2", "目标3"]
    quest.completed_objectives = [False, False, False]
    quest.is_active = True
    quest.progress_percentage = 25.0
    quest.story_context = "测试故事背景"
    
    game_state.quests.append(quest)
    
    print(f"初始进度: {quest.progress_percentage}%")
    
    # 测试进度更新
    await game_engine._update_quest_progress(game_state, "map_transition", 2)
    
    print(f"更新后进度: {quest.progress_percentage}%")
    print(f"故事背景: {quest.story_context}")
    print(f"LLM笔记: {quest.llm_notes}")

async def main():
    """主测试函数"""
    print("开始测试新功能...")
    
    try:
        await test_map_transition()
        await test_quest_progress_update()
        print("\n✅ 所有测试完成！")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
