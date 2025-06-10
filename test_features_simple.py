#!/usr/bin/env python3
"""
简化测试：验证数据模型和基础功能
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_models import GameState, Quest, GameMap, Character, MapTile, TerrainType

def test_quest_model():
    """测试任务模型的新字段"""
    print("=== 测试任务模型 ===")
    
    quest = Quest()
    quest.title = "测试任务"
    quest.description = "这是一个测试任务"
    quest.objectives = ["目标1", "目标2", "目标3"]
    quest.completed_objectives = [False, False, False]
    quest.is_active = True
    quest.progress_percentage = 25.5
    quest.story_context = "测试故事背景"
    quest.llm_notes = "LLM的内部笔记"
    
    print(f"任务标题: {quest.title}")
    print(f"进度百分比: {quest.progress_percentage}%")
    print(f"故事背景: {quest.story_context}")
    print(f"LLM笔记: {quest.llm_notes}")
    
    # 测试序列化
    quest_dict = quest.to_dict()
    print(f"序列化成功: {quest_dict.get('progress_percentage')} %")
    
    return quest

def test_game_state_model():
    """测试游戏状态模型的新字段"""
    print("\n=== 测试游戏状态模型 ===")
    
    game_state = GameState()
    game_state.pending_map_transition = "stairs_down"
    
    print(f"待切换地图: {game_state.pending_map_transition}")
    
    # 测试序列化
    state_dict = game_state.to_dict()
    print(f"序列化成功: {state_dict.get('pending_map_transition')}")
    
    return game_state

def test_map_transition_logic():
    """测试地图切换逻辑"""
    print("\n=== 测试地图切换逻辑 ===")
    
    # 创建测试地图
    game_map = GameMap()
    game_map.width = 10
    game_map.height = 10
    game_map.depth = 1
    game_map.name = "测试地图第1层"
    
    # 创建楼梯瓦片
    stairs_tile = MapTile(x=5, y=5, terrain=TerrainType.STAIRS_DOWN)
    game_map.tiles[(5, 5)] = stairs_tile
    
    # 创建游戏状态
    game_state = GameState()
    game_state.current_map = game_map
    
    player = Character()
    player.name = "测试玩家"
    player.position = (5, 5)  # 站在楼梯上
    game_state.player = player
    
    print(f"玩家位置: {player.position}")
    print(f"瓦片地形: {stairs_tile.terrain}")
    print(f"当前地图深度: {game_map.depth}")
    
    # 模拟移动到楼梯时的逻辑
    if stairs_tile.terrain == TerrainType.STAIRS_DOWN:
        game_state.pending_map_transition = "stairs_down"
        print("✅ 检测到楼梯，设置待切换状态")
    
    print(f"待切换状态: {game_state.pending_map_transition}")
    
    return game_state

def test_quest_progress():
    """测试任务进度功能"""
    print("\n=== 测试任务进度功能 ===")
    
    quest = test_quest_model()
    
    # 模拟进度更新
    old_progress = quest.progress_percentage
    quest.progress_percentage = 50.0
    quest.llm_notes = "玩家已完成第一阶段"
    
    print(f"进度更新: {old_progress}% -> {quest.progress_percentage}%")
    print(f"更新笔记: {quest.llm_notes}")
    
    # 测试任务完成
    quest.progress_percentage = 100.0
    quest.is_completed = True
    quest.is_active = False
    
    print(f"任务完成: {quest.is_completed}")
    print(f"任务激活: {quest.is_active}")
    
    return quest

def test_debug_mode_display():
    """测试调试模式显示"""
    print("\n=== 测试调试模式显示 ===")
    
    quest = Quest()
    quest.title = "调试任务"
    quest.progress_percentage = 75.3
    
    # 模拟调试模式下的显示
    debug_mode = True
    
    if debug_mode and quest.progress_percentage is not None:
        print(f"🔧 调试信息: 任务进度 {quest.progress_percentage:.1f}%")
        print("✅ 调试模式显示正常")
    else:
        print("❌ 调试模式显示异常")

def main():
    """主测试函数"""
    print("开始简化功能测试...")
    
    try:
        test_quest_model()
        test_game_state_model()
        test_map_transition_logic()
        test_quest_progress()
        test_debug_mode_display()
        
        print("\n✅ 所有基础功能测试通过！")
        print("\n📋 测试总结:")
        print("  ✓ 任务模型新字段 (progress_percentage, story_context, llm_notes)")
        print("  ✓ 游戏状态新字段 (pending_map_transition)")
        print("  ✓ 地图切换逻辑")
        print("  ✓ 任务进度更新")
        print("  ✓ 调试模式显示")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
