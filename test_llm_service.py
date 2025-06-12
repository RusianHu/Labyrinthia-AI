"""
LLMService 功能测试脚本
"""

import asyncio
import sys
import os
from pprint import pprint

# 将项目根目录添加到Python路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from llm_service import llm_service
from config import config
from data_models import GameState, GameMap, Character, Quest, Item, CharacterClass

# --- Test Helper Functions ---

def print_test_header(name):
    print(f"\n--- 开始测试: {name} ---")

def print_test_footer(name, success):
    status = "成功" if success else "失败"
    print(f"--- 测试结束: {name} | 状态: {status} ---")

def create_mock_game_state() -> GameState:
    """创建一个用于测试的模拟GameState对象"""
    game_state = GameState()
    game_state.player = Character(name="TestPlayer", character_class=CharacterClass.FIGHTER)
    game_state.player.stats.level = 5
    game_state.current_map = GameMap(name="The Echoing Caverns", width=10, height=10, depth=1)
    game_state.current_map.description = "一个潮湿、黑暗的洞穴，墙壁上长满了发光的苔藓。"
    game_state.turn_count = 42
    return game_state

# --- Test Cases ---

async def test_basic_generation():
    """测试基础的文本生成功能 (_async_generate)"""
    test_name = "基础文本生成"
    print_test_header(test_name)
    success = False
    try:
        prompt = "Describe a fantasy tavern in one sentence."
        print(f"发送提示: '{prompt}'")
        response = await llm_service._async_generate(prompt)
        print(f"收到响应: '{response.strip()}'")
        if response and isinstance(response, str) and len(response) > 10:
            success = True
        else:
            print("错误: 未收到有效的文本响应。")
    except Exception as e:
        print(f"错误: {e}")
    
    print_test_footer(test_name, success)
    return success

async def test_json_generation():
    """测试JSON生成功能 (_async_generate_json)"""
    test_name = "JSON 生成"
    print_test_header(test_name)
    success = False
    try:
        prompt = "Create a JSON for a magic potion with 'name' and 'effect' keys."
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "effect": {"type": "string"}
            },
            "required": ["name", "effect"]
        }
        print(f"发送提示: '{prompt}'")
        response = await llm_service._async_generate_json(prompt, schema)
        print("收到响应:")
        pprint(response)
        if isinstance(response, dict) and "name" in response and "effect" in response:
            success = True
        else:
            print("错误: 未收到有效的JSON对象或格式不正确。")
    except Exception as e:
        print(f"错误: {e}")

    print_test_footer(test_name, success)
    return success

async def test_character_generation():
    """测试角色生成功能 (generate_character)"""
    test_name = "角色生成"
    print_test_header(test_name)
    success = False
    try:
        print("正在生成一个 'goblin' 角色...")
        character = await llm_service.generate_character("npc", "A grumpy goblin guard.")
        print("收到响应:")
        if character:
            pprint(character.to_dict())
            if isinstance(character, Character) and character.name and character.description:
                success = True
            else:
                print("错误: 生成的对象不是有效的Character。")
        else:
            print("错误: 未能生成Character对象。")
    except Exception as e:
        print(f"错误: {e}")
        
    print_test_footer(test_name, success)
    return success

async def test_quest_generation():
    """测试任务生成功能 (generate_quest)"""
    test_name = "任务生成"
    print_test_header(test_name)
    success = False
    try:
        print("正在为5级玩家生成任务...")
        quest = await llm_service.generate_quest(5, "The player is in a town plagued by undead.")
        print("收到响应:")
        if quest:
            pprint(quest.to_dict())
            if isinstance(quest, Quest) and quest.title and quest.objectives:
                success = True
            else:
                print("错误: 生成的对象不是有效的Quest。")
        else:
            print("错误: 未能生成Quest对象。")
    except Exception as e:
        print(f"错误: {e}")

    print_test_footer(test_name, success)
    return success

async def test_narrative_generation():
    """测试叙事生成功能 (generate_narrative)"""
    test_name = "叙事生成"
    print_test_header(test_name)
    success = False
    try:
        game_state = create_mock_game_state()
        action = "Player moves to (5, 6) and finds a chest."
        print(f"基于动作生成叙事: '{action}'")
        narrative = await llm_service.generate_narrative(game_state, action)
        print(f"生成的叙事: '{narrative.strip()}'")
        if narrative and isinstance(narrative, str) and len(narrative) > 20:
            success = True
        else:
            print("错误: 未能生成有效的叙事文本。")
    except Exception as e:
        print(f"错误: {e}")

    print_test_footer(test_name, success)
    return success

async def test_item_generation():
    """测试物品生成功能 (generate_item_on_pickup)"""
    test_name = "物品生成"
    print_test_header(test_name)
    success = False
    try:
        game_state = create_mock_game_state()
        context = "The player found it in a dusty, ancient tomb."
        print(f"基于上下文生成物品: '{context}'")
        item = await llm_service.generate_item_on_pickup(game_state, context)
        print("收到响应:")
        if item:
            pprint(item.to_dict())
            if isinstance(item, Item) and item.name and item.description and item.item_type:
                success = True
            else:
                print("错误: 生成的对象不是有效的Item。")
        else:
            print("错误: 未能生成Item对象。")
    except Exception as e:
        print(f"错误: {e}")

    print_test_footer(test_name, success)
    return success


async def main():
    """运行所有LLMService测试。"""
    print("--- 开始 LLMService 功能测试套件 ---")

    # 1. 检查配置
    if not config.llm.api_key:
        print(f"\n错误: {config.llm.provider.value} 的 API 密钥未在 config.py 中配置。")
        print("请在 config.py 文件中为您选择的提供商设置 api_key。")
        return

    print(f"\n使用的服务提供商: {config.llm.provider.value}")
    print(f"使用的模型: {config.llm.model_name}")
    if config.llm.use_proxy:
        print(f"使用代理: {config.llm.proxy_url}")
    else:
        print("不使用代理。")

    # 2. 运行测试
    results = {}
    try:
        results["basic_generation"] = await test_basic_generation()
        results["json_generation"] = await test_json_generation()
        results["character_generation"] = await test_character_generation()
        results["quest_generation"] = await test_quest_generation()
        results["narrative_generation"] = await test_narrative_generation()
        results["item_generation"] = await test_item_generation()
    except Exception as e:
        print(f"\n--- 测试套件因严重错误而中止 ---")
        print(f"错误: {e}")
        print("请检查您的配置和网络连接。")
    finally:
        # 关闭服务的线程池以确保脚本干净地退出
        llm_service.close()
        print("\nLLMService已关闭。")

    # 3. 总结
    print("\n--- 测试套件总结 ---")
    all_passed = True
    if not results:
        all_passed = False
        print("测试未能运行。")
    else:
        for test_name, passed in results.items():
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"- {test_name.replace('_', ' ').title()}: {status}")
            if not passed:
                all_passed = False
    
    print("\n--- 测试结束 ---")
    if not all_passed:
        print("\n部分测试失败，请检查上面的输出。")
        sys.exit(1)
    else:
        print("\n所有测试均已通过！")


if __name__ == "__main__":
    asyncio.run(main())