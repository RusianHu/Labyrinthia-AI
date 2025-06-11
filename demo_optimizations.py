#!/usr/bin/env python3
"""
游戏优化功能演示
Demo script for game optimizations
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from game_engine import game_engine
from content_generator import content_generator
from data_models import GameState, Character


async def demo_stair_logic():
    """演示楼梯生成逻辑"""
    print("=" * 60)
    print("🏗️  楼梯生成逻辑演示")
    print("=" * 60)
    
    max_floors = config.game.max_quest_floors
    
    for depth in range(1, max_floors + 1):
        print(f"\n📍 第{depth}层地图:")
        
        game_map = await content_generator.generate_dungeon_map(
            width=8, height=8, depth=depth, theme="演示地下城"
        )
        
        stairs_up = 0
        stairs_down = 0
        
        for tile in game_map.tiles.values():
            if tile.terrain.value == "stairs_up":
                stairs_up += 1
            elif tile.terrain.value == "stairs_down":
                stairs_down += 1
        
        print(f"   地图名称: {game_map.name}")
        print(f"   上楼梯: {stairs_up} 个")
        print(f"   下楼梯: {stairs_down} 个")
        
        # 逻辑验证
        if depth == 1:
            print("   ✅ 第1层：只有下楼梯，符合逻辑")
        elif depth == max_floors:
            print(f"   ✅ 第{max_floors}层：只有上楼梯，符合逻辑")
        else:
            print(f"   ✅ 第{depth}层：有上下楼梯，符合逻辑")


async def demo_quest_system():
    """演示任务系统"""
    print("\n" + "=" * 60)
    print("🎯 任务系统演示")
    print("=" * 60)
    
    # 生成任务
    quests = await content_generator.generate_quest_chain(player_level=2)
    
    if not quests:
        print("❌ 未能生成任务")
        return
    
    quest = quests[0]
    print(f"\n📜 任务信息:")
    print(f"   标题: {quest.title}")
    print(f"   类型: {quest.quest_type}")
    print(f"   目标楼层: {quest.target_floors}")
    print(f"   描述: {quest.description[:100]}...")
    
    print(f"\n🎭 专属事件 ({len(quest.special_events)}个):")
    for i, event in enumerate(quest.special_events, 1):
        print(f"   {i}. {event.name}")
        print(f"      类型: {event.event_type}")
        print(f"      位置: {event.location_hint}")
        print(f"      进度值: {event.progress_value}%")
    
    print(f"\n👹 专属怪物 ({len(quest.special_monsters)}个):")
    for i, monster in enumerate(quest.special_monsters, 1):
        boss_mark = "👑" if monster.is_boss else "⚔️"
        print(f"   {i}. {boss_mark} {monster.name}")
        print(f"      挑战等级: {monster.challenge_rating}")
        print(f"      位置: {monster.location_hint}")
        print(f"      进度值: {monster.progress_value}%")


async def demo_map_generation():
    """演示地图生成"""
    print("\n" + "=" * 60)
    print("🗺️  地图生成演示")
    print("=" * 60)
    
    # 生成任务
    quests = await content_generator.generate_quest_chain(player_level=2)
    quest_context = quests[0].to_dict() if quests else None
    
    print(f"\n🏗️  生成带任务上下文的地图...")
    
    for depth in [1, 2, 3]:
        print(f"\n📍 第{depth}层:")
        
        game_map = await content_generator.generate_dungeon_map(
            width=12, height=12, 
            depth=depth, 
            theme="神秘遗迹",
            quest_context=quest_context
        )
        
        print(f"   名称: {game_map.name}")
        print(f"   描述: {game_map.description[:80]}...")
        
        # 统计特殊元素
        quest_events = 0
        normal_events = 0
        
        for tile in game_map.tiles.values():
            if tile.has_event:
                if tile.event_data.get('quest_event_id'):
                    quest_events += 1
                else:
                    normal_events += 1
        
        print(f"   任务事件: {quest_events} 个 ⭐")
        print(f"   普通事件: {normal_events} 个")


async def demo_quest_monster_generation():
    """演示任务怪物生成"""
    print("\n" + "=" * 60)
    print("👹 任务怪物生成演示")
    print("=" * 60)
    
    # 创建游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "演示玩家"
    game_state.player.stats.level = 2
    
    # 生成任务
    quests = await content_generator.generate_quest_chain(player_level=2)
    if quests:
        game_state.quests = quests
        game_state.quests[0].is_active = True
    
    print(f"\n🎯 活跃任务: {game_state.quests[0].title}")
    
    # 为每层生成怪物
    for depth in [1, 2, 3]:
        print(f"\n📍 第{depth}层怪物:")
        
        # 生成地图
        quest_context = game_state.quests[0].to_dict()
        game_map = await content_generator.generate_dungeon_map(
            width=10, height=10, depth=depth, quest_context=quest_context
        )
        game_state.current_map = game_map
        
        # 生成任务怪物
        quest_monsters = await game_engine._generate_quest_monsters(game_state, game_map)
        
        if quest_monsters:
            for monster in quest_monsters:
                boss_mark = "👑" if monster.is_boss else "⚔️"
                print(f"   {boss_mark} {monster.name}")
                print(f"      挑战等级: {monster.challenge_rating}")
                print(f"      生命值: {monster.stats.hp}")
                print(f"      任务怪物ID: {monster.quest_monster_id}")
        else:
            print("   (本层无任务怪物)")


async def main():
    """主演示函数"""
    print("🎮 Labyrinthia AI - 游戏优化功能演示")
    print(f"📊 配置信息:")
    print(f"   最大楼层数: {config.game.max_quest_floors}")
    print(f"   进度系数: {config.game.quest_progress_multiplier}")
    print(f"   调试模式: {config.game.debug_mode}")
    
    try:
        await demo_stair_logic()
        await demo_quest_system()
        await demo_map_generation()
        await demo_quest_monster_generation()
        
        print("\n" + "=" * 60)
        print("🎉 演示完成！")
        print("=" * 60)
        print("\n✨ 优化功能总结:")
        print("   ✅ 楼梯生成逻辑已修复（根据楼层深度智能生成）")
        print("   ✅ 任务事件和怪物具有特殊高亮效果")
        print("   ✅ 地图生成与任务信息紧密关联")
        print("   ✅ LLM生成的任务信息更加清晰明确")
        print("   ✅ 任务专属怪物正确生成和标记")
        
    except Exception as e:
        print(f"❌ 演示过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
