"""
测试LLM交互管理器的功能
"""

import asyncio
import logging
from data_models import GameState, Character, Monster, Stats, Ability, CharacterClass
from llm_interaction_manager import (
    llm_interaction_manager, InteractionType, InteractionContext
)

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_game_state():
    """创建测试游戏状态"""
    game_state = GameState()
    
    # 创建测试玩家
    player = Character()
    player.name = "测试冒险者"
    player.character_class = CharacterClass.FIGHTER
    player.stats = Stats()
    player.stats.level = 3
    player.stats.hp = 80
    player.stats.max_hp = 100
    player.stats.mp = 30
    player.stats.max_mp = 50
    player.abilities = Ability()
    player.position = (5, 5)
    
    game_state.player = player
    game_state.turn_count = 15
    
    # 创建测试怪物
    monster = Monster()
    monster.name = "哥布林战士"
    monster.stats = Stats()
    monster.stats.hp = 25
    monster.stats.max_hp = 30
    monster.challenge_rating = 1.0
    monster.position = (6, 5)
    
    game_state.monsters = [monster]
    
    return game_state


async def test_combat_defense_interaction():
    """测试战斗防御交互"""
    print("\n=== 测试战斗防御交互 ===")
    
    game_state = create_test_game_state()
    
    # 模拟怪物攻击事件
    combat_events = [
        "哥布林战士 攻击了你，造成 12 点伤害！",
        "你感受到了攻击的冲击，血量下降到 68/100"
    ]
    
    # 创建战斗防御上下文
    context = InteractionContext(
        interaction_type=InteractionType.COMBAT_DEFENSE,
        primary_action="遭受怪物攻击",
        events=combat_events,
        combat_data={
            "type": "monster_attack",
            "attacker": "哥布林战士",
            "damage": 12,
            "player_hp_remaining": 68,
            "player_hp_max": 100
        }
    )
    
    # 添加上下文并生成叙述
    llm_interaction_manager.add_context(context)
    
    try:
        narrative = await llm_interaction_manager.generate_contextual_narrative(
            game_state, context
        )
        print(f"生成的叙述: {narrative}")
        return True
    except Exception as e:
        print(f"测试失败: {e}")
        return False


async def test_combat_attack_interaction():
    """测试战斗攻击交互"""
    print("\n=== 测试战斗攻击交互 ===")
    
    game_state = create_test_game_state()
    
    # 模拟玩家攻击事件
    combat_events = [
        "对 哥布林战士 造成了 15 点伤害",
        "哥布林战士 受到重创，摇摇欲坠"
    ]
    
    # 创建战斗攻击上下文
    context = InteractionContext(
        interaction_type=InteractionType.COMBAT_ATTACK,
        primary_action="攻击哥布林战士",
        events=combat_events,
        combat_data={
            "type": "player_attack",
            "target": "哥布林战士",
            "damage": 15,
            "successful": True
        }
    )
    
    # 添加上下文并生成叙述
    llm_interaction_manager.add_context(context)
    
    try:
        narrative = await llm_interaction_manager.generate_contextual_narrative(
            game_state, context
        )
        print(f"生成的叙述: {narrative}")
        return True
    except Exception as e:
        print(f"测试失败: {e}")
        return False


async def test_movement_interaction():
    """测试移动交互"""
    print("\n=== 测试移动交互 ===")
    
    game_state = create_test_game_state()
    
    # 模拟移动事件
    movement_events = [
        "发现了一个古老的石碑",
        "石碑上刻着神秘的符文"
    ]
    
    # 创建移动上下文
    context = InteractionContext(
        interaction_type=InteractionType.MOVEMENT,
        primary_action="移动到 (6, 7)",
        events=movement_events,
        movement_data={
            "new_position": (6, 7),
            "events_triggered": True
        }
    )
    
    # 添加上下文并生成叙述
    llm_interaction_manager.add_context(context)
    
    try:
        narrative = await llm_interaction_manager.generate_contextual_narrative(
            game_state, context
        )
        print(f"生成的叙述: {narrative}")
        return True
    except Exception as e:
        print(f"测试失败: {e}")
        return False


async def test_context_continuity():
    """测试上下文连续性"""
    print("\n=== 测试上下文连续性 ===")
    
    game_state = create_test_game_state()
    
    # 模拟一系列连续的交互
    interactions = [
        # 第一次移动
        InteractionContext(
            interaction_type=InteractionType.MOVEMENT,
            primary_action="移动到 (5, 6)",
            events=["进入了一个昏暗的房间"],
            movement_data={"new_position": (5, 6)}
        ),
        # 遭受攻击
        InteractionContext(
            interaction_type=InteractionType.COMBAT_DEFENSE,
            primary_action="遭受突袭",
            events=["哥布林从阴影中跳出攻击你！", "造成了 8 点伤害"],
            combat_data={"type": "monster_attack", "attacker": "哥布林", "damage": 8}
        ),
        # 反击
        InteractionContext(
            interaction_type=InteractionType.COMBAT_ATTACK,
            primary_action="反击哥布林",
            events=["你挥剑反击", "对哥布林造成了 12 点伤害"],
            combat_data={"type": "player_attack", "target": "哥布林", "damage": 12}
        )
    ]
    
    try:
        for i, context in enumerate(interactions):
            llm_interaction_manager.add_context(context)
            narrative = await llm_interaction_manager.generate_contextual_narrative(
                game_state, context
            )
            print(f"第{i+1}次交互叙述: {narrative}")
            print("-" * 50)
        
        return True
    except Exception as e:
        print(f"测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("开始测试LLM交互管理器...")
    
    tests = [
        test_combat_defense_interaction,
        test_combat_attack_interaction,
        test_movement_interaction,
        test_context_continuity
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"测试 {test.__name__} 出现异常: {e}")
            results.append(False)
    
    print(f"\n=== 测试结果 ===")
    print(f"总测试数: {len(tests)}")
    print(f"成功: {sum(results)}")
    print(f"失败: {len(results) - sum(results)}")
    
    if all(results):
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败")


if __name__ == "__main__":
    asyncio.run(main())
