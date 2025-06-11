"""
测试物品系统的功能
"""

import asyncio
import json
from data_models import GameState, Character, Item, GameMap, MapTile, TerrainType
from llm_service import llm_service
from item_effect_processor import item_effect_processor


async def test_item_generation():
    """测试物品生成功能"""
    print("=== 测试物品生成功能 ===")
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "测试玩家"
    game_state.player.stats.level = 3
    game_state.player.position = (5, 5)
    
    # 创建测试地图
    game_map = GameMap()
    game_map.name = "测试地下城"
    game_map.description = "一个用于测试的地下城"
    game_map.depth = 1
    game_state.current_map = game_map
    
    # 测试物品生成
    pickup_context = "玩家在宝藏箱中发现了神秘物品"
    
    try:
        item = await llm_service.generate_item_on_pickup(game_state, pickup_context)
        if item:
            print(f"✅ 成功生成物品:")
            print(f"   名称: {item.name}")
            print(f"   描述: {item.description}")
            print(f"   类型: {item.item_type}")
            print(f"   稀有度: {item.rarity}")
            print(f"   使用说明: {item.usage_description}")
            print(f"   LLM生成: {item.llm_generated}")
            return item
        else:
            print("❌ 物品生成失败")
            return None
    except Exception as e:
        print(f"❌ 物品生成出错: {e}")
        return None


async def test_item_usage(item):
    """测试物品使用功能"""
    print("\n=== 测试物品使用功能 ===")
    
    if not item:
        print("❌ 没有可用的物品进行测试")
        return
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "测试玩家"
    game_state.player.stats.level = 3
    game_state.player.stats.hp = 80
    game_state.player.stats.max_hp = 100
    game_state.player.stats.mp = 30
    game_state.player.stats.max_mp = 50
    game_state.player.position = (5, 5)
    
    # 创建测试地图
    game_map = GameMap()
    game_map.name = "测试地下城"
    game_map.description = "一个用于测试的地下城"
    game_map.depth = 1
    game_map.width = 10
    game_map.height = 10
    
    # 初始化地图瓦片
    game_map.tiles = []
    for y in range(game_map.height):
        row = []
        for x in range(game_map.width):
            tile = MapTile()
            tile.x = x
            tile.y = y
            tile.terrain = TerrainType.FLOOR
            row.append(tile)
        game_map.tiles.append(row)
    
    game_state.current_map = game_map
    
    try:
        # 测试物品使用
        llm_response = await llm_service.process_item_usage(game_state, item)
        print(f"✅ LLM响应:")
        print(f"   消息: {llm_response.get('message', '无消息')}")
        print(f"   事件: {llm_response.get('events', [])}")
        print(f"   物品消耗: {llm_response.get('item_consumed', True)}")
        
        # 测试效果处理
        effect_result = item_effect_processor.process_llm_response(
            llm_response, game_state, item
        )
        
        print(f"✅ 效果处理结果:")
        print(f"   成功: {effect_result.success}")
        print(f"   消息: {effect_result.message}")
        print(f"   事件: {effect_result.events}")
        print(f"   属性变化: {effect_result.stat_changes}")
        print(f"   位置变化: {effect_result.position_change}")
        print(f"   物品消耗: {effect_result.item_consumed}")
        
    except Exception as e:
        print(f"❌ 物品使用测试出错: {e}")


async def test_item_pickup_context():
    """测试不同拾取上下文的物品生成"""
    print("\n=== 测试不同拾取上下文 ===")
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "测试玩家"
    game_state.player.stats.level = 5
    game_state.player.position = (3, 3)
    
    # 创建测试地图
    game_map = GameMap()
    game_map.name = "古老的地下城"
    game_map.description = "一个充满魔法的古老地下城"
    game_map.depth = 2
    game_state.current_map = game_map
    
    contexts = [
        "玩家在古老的法师塔中发现了遗留的魔法物品",
        "玩家在战场废墟中找到了战士的装备",
        "玩家在神秘的祭坛上发现了神圣物品",
        "玩家在盗贼的藏身处找到了精巧的工具"
    ]
    
    for i, context in enumerate(contexts, 1):
        print(f"\n--- 测试上下文 {i} ---")
        print(f"上下文: {context}")
        
        try:
            item = await llm_service.generate_item_on_pickup(game_state, context)
            if item:
                print(f"✅ 生成物品: {item.name}")
                print(f"   类型: {item.item_type}")
                print(f"   稀有度: {item.rarity}")
                print(f"   描述: {item.description[:50]}...")
            else:
                print("❌ 物品生成失败")
        except Exception as e:
            print(f"❌ 生成出错: {e}")


async def main():
    """主测试函数"""
    print("开始测试物品管理系统...")
    
    # 测试物品生成
    item = await test_item_generation()
    
    # 测试物品使用
    await test_item_usage(item)
    
    # 测试不同上下文
    await test_item_pickup_context()
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
