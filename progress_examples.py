"""
进程管理器使用示例
Examples of using the progress manager for different game scenarios
"""

import asyncio
from typing import Dict, Any

from progress_manager import (
    progress_manager, ProgressEventType, ProgressRule, ProgressContext
)
from data_models import GameState, Quest, Character, GameMap


class CustomProgressRules:
    """自定义进度规则示例"""
    
    @staticmethod
    def setup_exploration_heavy_quest():
        """设置探索重点任务的进度规则"""
        
        def exploration_calculator(context: Any, current_progress: float) -> float:
            """探索型任务的进度计算器"""
            if not isinstance(context, dict):
                return 2.0  # 默认增量
            
            area_type = context.get("area_type", "normal")
            discovery_type = context.get("discovery_type", "normal")
            
            # 根据区域类型调整进度
            area_multiplier = {
                "normal": 1.0,
                "dangerous": 1.5,
                "secret": 2.0,
                "boss_area": 3.0
            }.get(area_type, 1.0)
            
            # 根据发现类型调整进度
            discovery_multiplier = {
                "normal": 1.0,
                "landmark": 1.5,
                "treasure": 2.0,
                "secret_passage": 2.5,
                "ancient_relic": 3.0
            }.get(discovery_type, 1.0)
            
            base_increment = 5.0
            total_increment = base_increment * area_multiplier * discovery_multiplier
            
            return min(total_increment, 25.0)  # 最大单次增量25%
        
        # 注册探索规则
        exploration_rule = ProgressRule(
            event_type=ProgressEventType.EXPLORATION,
            custom_calculator=exploration_calculator
        )
        progress_manager.register_rule(exploration_rule)
        
        print("已设置探索重点任务的进度规则")
    
    @staticmethod
    def setup_combat_heavy_quest():
        """设置战斗重点任务的进度规则"""
        
        def combat_calculator(context: Any, current_progress: float) -> float:
            """战斗型任务的进度计算器"""
            if not isinstance(context, dict):
                return 5.0
            
            challenge_rating = context.get("challenge_rating", 1.0)
            is_boss = context.get("is_boss", False)
            monster_type = context.get("monster_type", "normal")
            
            # 基础进度
            base_increment = 8.0
            
            # 挑战等级倍数
            cr_multiplier = min(challenge_rating / 2.0, 3.0)
            
            # Boss 额外奖励
            boss_bonus = 2.0 if is_boss else 1.0
            
            # 怪物类型倍数
            type_multiplier = {
                "normal": 1.0,
                "elite": 1.5,
                "boss": 2.0,
                "legendary": 3.0
            }.get(monster_type, 1.0)
            
            total_increment = base_increment * cr_multiplier * boss_bonus * type_multiplier
            
            return min(total_increment, 30.0)  # 最大单次增量30%
        
        # 注册战斗规则
        combat_rule = ProgressRule(
            event_type=ProgressEventType.COMBAT_VICTORY,
            custom_calculator=combat_calculator
        )
        progress_manager.register_rule(combat_rule)
        
        print("已设置战斗重点任务的进度规则")
    
    @staticmethod
    def setup_story_heavy_quest():
        """设置剧情重点任务的进度规则"""
        
        def story_calculator(context: Any, current_progress: float) -> float:
            """剧情型任务的进度计算器"""
            if not isinstance(context, dict):
                return 10.0
            
            story_importance = context.get("importance", "normal")
            character_involved = context.get("character_involved", False)
            plot_advancement = context.get("plot_advancement", "minor")
            
            # 基础进度
            base_increment = 12.0
            
            # 重要性倍数
            importance_multiplier = {
                "minor": 0.5,
                "normal": 1.0,
                "important": 1.5,
                "critical": 2.0,
                "climax": 3.0
            }.get(story_importance, 1.0)
            
            # 角色参与奖励
            character_bonus = 1.3 if character_involved else 1.0
            
            # 剧情推进倍数
            plot_multiplier = {
                "minor": 0.8,
                "moderate": 1.0,
                "major": 1.5,
                "turning_point": 2.0
            }.get(plot_advancement, 1.0)
            
            total_increment = base_increment * importance_multiplier * character_bonus * plot_multiplier
            
            return min(total_increment, 35.0)  # 最大单次增量35%
        
        # 注册剧情规则
        story_rule = ProgressRule(
            event_type=ProgressEventType.STORY_EVENT,
            custom_calculator=story_calculator
        )
        progress_manager.register_rule(story_rule)
        
        print("已设置剧情重点任务的进度规则")


class ProgressEventHandlers:
    """进度事件处理器示例"""
    
    @staticmethod
    async def milestone_handler(context: ProgressContext):
        """里程碑事件处理器"""
        game_state = context.game_state
        
        # 检查是否有活跃任务
        active_quest = None
        for quest in game_state.quests:
            if quest.is_active and not quest.is_completed:
                active_quest = quest
                break
        
        if not active_quest:
            return
        
        # 检查是否达到重要里程碑
        progress = active_quest.progress_percentage
        
        if 25.0 <= progress < 30.0:
            game_state.pending_events.append("🎯 任务进度：25% - 你已经踏上了正确的道路！")
        elif 50.0 <= progress < 55.0:
            game_state.pending_events.append("🎯 任务进度：50% - 你已经完成了一半的旅程！")
        elif 75.0 <= progress < 80.0:
            game_state.pending_events.append("🎯 任务进度：75% - 胜利就在眼前！")
        elif 90.0 <= progress < 95.0:
            game_state.pending_events.append("🎯 任务进度：90% - 最后的冲刺！")
    
    @staticmethod
    async def combat_streak_handler(context: ProgressContext):
        """连胜处理器"""
        if context.event_type != ProgressEventType.COMBAT_VICTORY:
            return
        
        # 在元数据中记录连胜
        if "combat_streak" not in context.metadata:
            context.metadata["combat_streak"] = 1
        else:
            context.metadata["combat_streak"] += 1
        
        streak = context.metadata["combat_streak"]
        
        if streak >= 5:
            context.game_state.pending_events.append(f"🔥 连胜 {streak} 场！你正在势如破竹！")
            
            # 给予额外奖励
            bonus_exp = streak * 10
            context.game_state.player.stats.experience += bonus_exp
            context.game_state.pending_events.append(f"💰 连胜奖励：{bonus_exp} 经验值！")
    
    @staticmethod
    def register_all_handlers():
        """注册所有事件处理器"""
        # 为所有事件类型注册里程碑处理器
        for event_type in ProgressEventType:
            progress_manager.register_event_handler(event_type, ProgressEventHandlers.milestone_handler)
        
        # 为战斗胜利注册连胜处理器
        progress_manager.register_event_handler(
            ProgressEventType.COMBAT_VICTORY, 
            ProgressEventHandlers.combat_streak_handler
        )
        
        print("已注册所有事件处理器")


async def demo_exploration_quest():
    """演示探索型任务"""
    print("\n=== 探索型任务演示 ===")
    
    # 设置探索重点规则
    CustomProgressRules.setup_exploration_heavy_quest()
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "探索者"
    game_state.current_map = GameMap()
    game_state.current_map.name = "神秘森林"
    
    # 创建探索任务
    quest = Quest()
    quest.title = "森林探索"
    quest.description = "探索神秘森林的每个角落"
    quest.is_active = True
    quest.progress_percentage = 0.0
    game_state.quests.append(quest)
    
    # 模拟不同类型的探索事件
    exploration_events = [
        {"area_type": "normal", "discovery_type": "normal"},
        {"area_type": "dangerous", "discovery_type": "landmark"},
        {"area_type": "secret", "discovery_type": "treasure"},
        {"area_type": "boss_area", "discovery_type": "ancient_relic"}
    ]
    
    for i, event_data in enumerate(exploration_events, 1):
        print(f"\n探索事件 {i}: {event_data}")
        
        context = ProgressContext(
            event_type=ProgressEventType.EXPLORATION,
            game_state=game_state,
            context_data=event_data
        )
        
        result = await progress_manager.process_event(context)
        print(f"进度增量: {result.get('progress_increment', 0):.1f}%")
        print(f"当前进度: {quest.progress_percentage:.1f}%")
        
        if quest.is_completed:
            print("🎉 任务完成！")
            break


async def demo_combat_quest():
    """演示战斗型任务"""
    print("\n=== 战斗型任务演示 ===")
    
    # 设置战斗重点规则
    CustomProgressRules.setup_combat_heavy_quest()
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "战士"
    game_state.current_map = GameMap()
    game_state.current_map.name = "竞技场"
    
    # 创建战斗任务
    quest = Quest()
    quest.title = "竞技场挑战"
    quest.description = "在竞技场中证明你的实力"
    quest.is_active = True
    quest.progress_percentage = 0.0
    game_state.quests.append(quest)
    
    # 模拟不同类型的战斗事件
    combat_events = [
        {"challenge_rating": 1.0, "is_boss": False, "monster_type": "normal"},
        {"challenge_rating": 2.0, "is_boss": False, "monster_type": "elite"},
        {"challenge_rating": 3.0, "is_boss": True, "monster_type": "boss"},
        {"challenge_rating": 5.0, "is_boss": True, "monster_type": "legendary"}
    ]
    
    for i, event_data in enumerate(combat_events, 1):
        print(f"\n战斗事件 {i}: {event_data}")
        
        context = ProgressContext(
            event_type=ProgressEventType.COMBAT_VICTORY,
            game_state=game_state,
            context_data=event_data
        )
        
        result = await progress_manager.process_event(context)
        print(f"进度增量: {result.get('progress_increment', 0):.1f}%")
        print(f"当前进度: {quest.progress_percentage:.1f}%")
        
        if quest.is_completed:
            print("🎉 任务完成！")
            break


async def demo_story_quest():
    """演示剧情型任务"""
    print("\n=== 剧情型任务演示 ===")
    
    # 设置剧情重点规则
    CustomProgressRules.setup_story_heavy_quest()
    
    # 创建测试游戏状态
    game_state = GameState()
    game_state.player = Character()
    game_state.player.name = "冒险者"
    game_state.current_map = GameMap()
    game_state.current_map.name = "王城"
    
    # 创建剧情任务
    quest = Quest()
    quest.title = "王国的秘密"
    quest.description = "揭开王国隐藏的真相"
    quest.is_active = True
    quest.progress_percentage = 0.0
    game_state.quests.append(quest)
    
    # 模拟不同类型的剧情事件
    story_events = [
        {"importance": "normal", "character_involved": False, "plot_advancement": "minor"},
        {"importance": "important", "character_involved": True, "plot_advancement": "moderate"},
        {"importance": "critical", "character_involved": True, "plot_advancement": "major"},
        {"importance": "climax", "character_involved": True, "plot_advancement": "turning_point"}
    ]
    
    for i, event_data in enumerate(story_events, 1):
        print(f"\n剧情事件 {i}: {event_data}")
        
        context = ProgressContext(
            event_type=ProgressEventType.STORY_EVENT,
            game_state=game_state,
            context_data=event_data
        )
        
        result = await progress_manager.process_event(context)
        print(f"进度增量: {result.get('progress_increment', 0):.1f}%")
        print(f"当前进度: {quest.progress_percentage:.1f}%")
        
        if quest.is_completed:
            print("🎉 任务完成！")
            break


async def main():
    """主演示函数"""
    print("进程管理器自定义规则演示")
    
    # 注册事件处理器
    ProgressEventHandlers.register_all_handlers()
    
    # 运行各种演示
    await demo_exploration_quest()
    await demo_combat_quest()
    await demo_story_quest()
    
    print("\n=== 演示完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
