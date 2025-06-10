#!/usr/bin/env python3
"""
Labyrinthia AI - 游戏功能测试
Test script for the Labyrinthia AI game functionality
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from game_engine import game_engine
from content_generator import content_generator
from llm_service import llm_service
from data_manager import data_manager


async def test_character_generation():
    """测试角色生成"""
    print("🧙 测试角色生成...")
    
    try:
        character = await llm_service.generate_character("npc", "一个神秘的法师")
        if character:
            print(f"✅ 成功生成角色: {character.name}")
            print(f"   职业: {character.character_class.value}")
            print(f"   描述: {character.description[:50]}...")
            return True
        else:
            print("❌ 角色生成失败")
            return False
    except Exception as e:
        print(f"❌ 角色生成错误: {e}")
        return False


async def test_map_generation():
    """测试地图生成"""
    print("🗺️  测试地图生成...")
    
    try:
        game_map = await content_generator.generate_dungeon_map(10, 10, 1, "测试地下城")
        if game_map:
            print(f"✅ 成功生成地图: {game_map.name}")
            print(f"   大小: {game_map.width}x{game_map.height}")
            print(f"   瓦片数量: {len(game_map.tiles)}")
            return True
        else:
            print("❌ 地图生成失败")
            return False
    except Exception as e:
        print(f"❌ 地图生成错误: {e}")
        return False


async def test_monster_generation():
    """测试怪物生成"""
    print("👹 测试怪物生成...")
    
    try:
        monsters = await content_generator.generate_encounter_monsters(1, "easy")
        if monsters:
            print(f"✅ 成功生成 {len(monsters)} 个怪物")
            for monster in monsters:
                print(f"   - {monster.name} (CR: {monster.challenge_rating})")
            return True
        else:
            print("❌ 怪物生成失败")
            return False
    except Exception as e:
        print(f"❌ 怪物生成错误: {e}")
        return False


async def test_quest_generation():
    """测试任务生成"""
    print("📋 测试任务生成...")
    
    try:
        quest = await llm_service.generate_quest(1, "新手村的第一个任务")
        if quest:
            print(f"✅ 成功生成任务: {quest.title}")
            print(f"   目标数量: {len(quest.objectives)}")
            print(f"   经验奖励: {quest.experience_reward}")
            return True
        else:
            print("❌ 任务生成失败")
            return False
    except Exception as e:
        print(f"❌ 任务生成错误: {e}")
        return False


async def test_game_creation():
    """测试游戏创建"""
    print("🎮 测试游戏创建...")
    
    try:
        game_state = await game_engine.create_new_game("测试玩家", "fighter")
        if game_state:
            print(f"✅ 成功创建游戏: {game_state.id}")
            print(f"   玩家: {game_state.player.name}")
            print(f"   地图: {game_state.current_map.name}")
            print(f"   怪物数量: {len(game_state.monsters)}")
            print(f"   任务数量: {len(game_state.quests)}")
            
            # 清理测试游戏
            game_engine.close_game(game_state.id)
            return True
        else:
            print("❌ 游戏创建失败")
            return False
    except Exception as e:
        print(f"❌ 游戏创建错误: {e}")
        return False


async def test_data_persistence():
    """测试数据持久化"""
    print("💾 测试数据持久化...")
    
    try:
        # 创建测试游戏状态
        game_state = await game_engine.create_new_game("持久化测试", "wizard")
        
        # 保存游戏状态
        success = data_manager.save_game_state(game_state)
        if not success:
            print("❌ 保存游戏状态失败")
            return False
        
        # 加载游戏状态
        loaded_state = data_manager.load_game_state(game_state.id)
        if not loaded_state:
            print("❌ 加载游戏状态失败")
            return False
        
        # 验证数据一致性
        if (loaded_state.player.name == game_state.player.name and
            loaded_state.current_map.name == game_state.current_map.name):
            print("✅ 数据持久化测试通过")
            
            # 清理测试数据
            data_manager.delete_save(game_state.id)
            game_engine.close_game(game_state.id)
            return True
        else:
            print("❌ 数据一致性验证失败")
            return False
            
    except Exception as e:
        print(f"❌ 数据持久化错误: {e}")
        return False


async def test_api_connection():
    """测试API连接"""
    print("🔗 测试API连接...")
    
    try:
        # 测试简单的文本生成
        response = await llm_service._async_generate("请说'Hello, Labyrinthia!'")
        if response and "Hello" in response:
            print("✅ API连接正常")
            return True
        else:
            print("❌ API响应异常")
            return False
    except Exception as e:
        print(f"❌ API连接错误: {e}")
        return False


async def run_all_tests():
    """运行所有测试"""
    print("🏰 Labyrinthia AI - 功能测试")
    print("=" * 50)
    
    tests = [
        ("API连接", test_api_connection),
        ("角色生成", test_character_generation),
        ("地图生成", test_map_generation),
        ("怪物生成", test_monster_generation),
        ("任务生成", test_quest_generation),
        ("游戏创建", test_game_creation),
        ("数据持久化", test_data_persistence),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📝 {test_name}测试:")
        try:
            if await test_func():
                passed += 1
            else:
                print(f"   {test_name}测试失败")
        except Exception as e:
            print(f"   {test_name}测试异常: {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！游戏功能正常")
        return True
    else:
        print("⚠️  部分测试失败，请检查配置和网络连接")
        return False


def main():
    """主函数"""
    # 检查配置
    if not config.llm.api_key or config.llm.api_key == "your-api-key-here":
        print("❌ 请先在config.py中设置Gemini API密钥")
        sys.exit(1)
    
    # 运行测试
    try:
        result = asyncio.run(run_all_tests())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n🛑 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试运行错误: {e}")
        sys.exit(1)
    finally:
        # 清理资源
        llm_service.close()


if __name__ == "__main__":
    main()
