"""
Labyrinthia AI - 战斗结果管理器
统一管理战斗结果处理，包括怪物死亡、经验获取、掉落物品和LLM叙述生成
"""

import logging
import math
import random
from numbers import Number
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from data_models import GameState, Monster, Character, Item
from llm_service import llm_service
from prompt_manager import prompt_manager
from config import config
from game_state_modifier import game_state_modifier


logger = logging.getLogger(__name__)


class CombatResultType(Enum):
    """战斗结果类型"""
    MONSTER_DEFEATED = "monster_defeated"
    BOSS_DEFEATED = "boss_defeated"
    QUEST_MONSTER_DEFEATED = "quest_monster_defeated"
    PLAYER_VICTORY = "player_victory"
    PLAYER_DEFEAT = "player_defeat"


@dataclass
class CombatResult:
    """战斗结果数据"""
    result_type: CombatResultType
    defeated_monster: Optional[Monster] = None
    damage_dealt: int = 0
    experience_gained: int = 0
    level_up: bool = False
    loot_items: List[Item] = field(default_factory=list)
    quest_progress: float = 0.0
    is_quest_monster: bool = False
    is_boss: bool = False
    narrative: str = ""
    events: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "result_type": self.result_type.value,
            "defeated_monster": self.defeated_monster.to_dict() if self.defeated_monster else None,
            "damage_dealt": self.damage_dealt,
            "experience_gained": self.experience_gained,
            "level_up": self.level_up,
            "loot_items": [item.to_dict() for item in self.loot_items],
            "quest_progress": self.quest_progress,
            "is_quest_monster": self.is_quest_monster,
            "is_boss": self.is_boss,
            "narrative": self.narrative,
            "events": self.events
        }


class CombatResultManager:
    """战斗结果管理器"""
    
    def __init__(self):
        self.combat_history: List[CombatResult] = []
        self.total_monsters_defeated: int = 0
        self.total_bosses_defeated: int = 0
        
    async def process_monster_defeat(
        self, 
        game_state: GameState, 
        monster: Monster,
        damage_dealt: int
    ) -> CombatResult:
        """
        处理怪物被击败
        
        Args:
            game_state: 游戏状态
            monster: 被击败的怪物
            damage_dealt: 造成的伤害
            
        Returns:
            CombatResult: 战斗结果
        """
        logger.info(f"Processing monster defeat: {monster.name}")
        
        # 确定战斗结果类型
        result_type = self._determine_result_type(monster)
        
        # 创建战斗结果对象
        combat_result = CombatResult(
            result_type=result_type,
            defeated_monster=monster,
            damage_dealt=damage_dealt,
            is_boss=monster.is_boss,
            is_quest_monster=bool(monster.quest_monster_id)
        )
        
        # 计算并归一化经验值（在写回玩家状态前完成，避免状态与返回值不一致）
        try:
            raw_experience_gained = self._calculate_experience(monster)
        except Exception as e:
            logger.warning(f"Failed to calculate experience for monster {monster.name}, fallback to 0: {e}")
            raw_experience_gained = 0

        safe_experience_gained = self._safe_int(raw_experience_gained, default=0, min_value=0)
        combat_result.experience_gained = safe_experience_gained

        # 应用经验值并检查升级（使用GameStateModifier）
        old_level = game_state.player.stats.level

        # 构建玩家更新数据
        player_updates = {
            "stats": {
                "experience": game_state.player.stats.experience + safe_experience_gained
            }
        }

        # 应用经验值更新
        modification_result = game_state_modifier.apply_player_updates(
            game_state,
            player_updates,
            source=f"combat:{monster.name}"
        )

        if not modification_result.success:
            logger.error(
                f"Failed to apply combat exp updates for monster {monster.name}: {modification_result.errors}"
            )
            # 写回失败时，确保返回值与玩家状态一致，避免“显示获得经验但实际未入账”
            combat_result.experience_gained = 0
            combat_result.level_up = False
        else:
            # 检查升级
            combat_result.level_up = self._check_level_up(game_state.player)
        
        # 生成战利品
        combat_result.loot_items = await self._generate_loot(game_state, monster)

        # 检查任务进度
        if monster.quest_monster_id:
            combat_result.quest_progress = await self._update_quest_progress(
                game_state, monster
            )

        # 数值安全归一化（防御外部/历史脏数据）
        combat_result.damage_dealt = self._safe_int(combat_result.damage_dealt, default=0, min_value=0)
        combat_result.experience_gained = self._safe_int(combat_result.experience_gained, default=0, min_value=0)

        # 构建事件列表
        combat_result.events = self._build_combat_events(combat_result, old_level)

        # 叙述策略
        combat_result.narrative = await self._resolve_combat_narrative(game_state, combat_result)

        # 写入 LLM 上下文（玩家进攻与叙述）
        try:
            from llm_context_manager import llm_context_manager
            if getattr(config.llm, "record_combat_to_context", True):
                attacker = getattr(game_state.player, "name", "玩家")
                target = combat_result.defeated_monster.name if combat_result.defeated_monster else "怪物"
                damage_val = combat_result.damage_dealt
                llm_context_manager.add_combat(
                    is_attack=True,
                    attacker=attacker,
                    target=target,
                    damage=damage_val,
                    result="击败"
                )
                if combat_result.narrative:
                    llm_context_manager.add_narrative(combat_result.narrative, context_type="combat")
        except Exception as _e:
            logger.warning(f"Failed to log combat context: {_e}")

        # 更新统计
        self.total_monsters_defeated += 1
        if monster.is_boss:
            self.total_bosses_defeated += 1

        # 记录到历史
        self.combat_history.append(combat_result)
        self._cleanup_history()

        logger.info(f"Combat result processed: {result_type.value}, exp: {combat_result.experience_gained}")

        return combat_result
    
    def _determine_result_type(self, monster: Monster) -> CombatResultType:
        """确定战斗结果类型"""
        if monster.is_boss:
            return CombatResultType.BOSS_DEFEATED
        elif monster.quest_monster_id:
            return CombatResultType.QUEST_MONSTER_DEFEATED
        else:
            return CombatResultType.MONSTER_DEFEATED
    
    def _calculate_experience(self, monster: Monster) -> int:
        """计算经验值"""
        base_exp = int(monster.challenge_rating * 100)
        
        # Boss额外奖励
        if monster.is_boss:
            base_exp = int(base_exp * 2.0)
        
        # 任务怪物额外奖励
        if monster.quest_monster_id:
            base_exp = int(base_exp * 1.5)
        
        return base_exp
    
    def _check_level_up(self, player: Character) -> bool:
        """检查并处理升级（使用GameStateModifier）"""
        exp_needed = player.stats.level * 1000

        if player.stats.experience >= exp_needed:
            new_level = player.stats.level + 1
            new_experience = player.stats.experience - exp_needed
            new_max_hp = player.stats.max_hp + 10
            new_max_mp = player.stats.max_mp + 5
            new_ac = player.stats.ac + 1

            # 构建升级更新数据
            # 注意：这里需要从game_state获取，但我们只有player引用
            # 为了保持一致性，我们直接修改（因为这是内部方法）
            player.stats.level = new_level
            player.stats.experience = new_experience
            player.stats.max_hp = new_max_hp
            player.stats.hp = new_max_hp  # 升级时完全恢复HP
            player.stats.max_mp = new_max_mp
            player.stats.mp = new_max_mp  # 升级时完全恢复MP
            player.stats.ac = new_ac

            logger.info(f"Player leveled up to {player.stats.level}")
            return True

        return False
    
    async def _generate_loot(self, game_state: GameState, monster: Monster) -> List[Item]:
        """生成战利品"""
        loot_items = []
        
        try:
            # 根据怪物类型决定掉落概率
            drop_chance = 0.3  # 基础30%掉落率
            
            if monster.is_boss:
                drop_chance = 1.0  # Boss必定掉落
            elif monster.quest_monster_id:
                drop_chance = 0.6  # 任务怪物60%掉落
            
            import random
            if random.random() < drop_chance:
                from content_generator import content_generator
                
                # 根据怪物挑战等级生成物品
                rarity = "common"
                if monster.is_boss:
                    rarity = "rare"
                elif monster.challenge_rating >= 3.0:
                    rarity = "uncommon"
                
                items = await content_generator.generate_loot_items(
                    game_state.player.stats.level,
                    rarity=rarity,
                    count=1
                )
                
                if items:
                    loot_items.extend(items)
                    # 将物品添加到玩家背包
                    game_state.player.inventory.extend(items)
                    logger.info(f"Generated loot: {[item.name for item in items]}")
        
        except Exception as e:
            logger.error(f"Failed to generate loot: {e}")
        
        return loot_items
    
    async def _update_quest_progress(self, game_state: GameState, monster: Monster) -> float:
        """更新任务进度"""
        try:
            # 查找活跃任务
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            if not active_quest:
                return 0.0
            
            # 查找对应的任务怪物
            quest_monster = next(
                (qm for qm in active_quest.special_monsters if qm.id == monster.quest_monster_id),
                None
            )
            
            if quest_monster:
                progress_value = quest_monster.progress_value
                logger.info(f"Quest progress updated: +{progress_value}%")
                return progress_value
        
        except Exception as e:
            logger.error(f"Failed to update quest progress: {e}")
        
        return 0.0
    
    def _build_combat_events(self, combat_result: CombatResult, old_level: int) -> List[str]:
        """构建战斗事件列表"""
        events = []
        
        # 击败怪物
        monster_name = combat_result.defeated_monster.name if combat_result.defeated_monster else "怪物"
        events.append(f"{monster_name} 被击败了！")
        
        # 经验值
        events.append(f"获得了 {combat_result.experience_gained} 点经验")
        
        # 升级
        if combat_result.level_up:
            events.append(f"恭喜升级！等级提升至 {old_level + 1}")
        
        # 战利品
        if combat_result.loot_items:
            for item in combat_result.loot_items:
                events.append(f"获得了 {item.name}")
        
        # 任务进度
        if combat_result.quest_progress > 0:
            events.append(f"任务进度 +{combat_result.quest_progress}%")
        
        return events

    def _safe_int(
        self,
        value: Any,
        default: int = 0,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None
    ) -> int:
        """安全转换为整数，避免脏数据导致结算失败"""
        try:
            if value is None:
                parsed = default
            elif isinstance(value, bool):
                parsed = int(value)
            elif isinstance(value, Number):
                parsed = int(value)
            elif isinstance(value, str):
                parsed = int(float(value.strip())) if value.strip() else default
            else:
                parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            parsed = default

        if min_value is not None:
            parsed = max(min_value, parsed)
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    def _safe_float(
        self,
        value: Any,
        default: float = 0.0,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None
    ) -> float:
        """安全转换为浮点数，避免脏数据导致结算失败"""
        try:
            if value is None:
                parsed = default
            elif isinstance(value, bool):
                parsed = float(int(value))
            elif isinstance(value, Number):
                parsed = float(value)
            elif isinstance(value, str):
                parsed = float(value.strip()) if value.strip() else default
            else:
                parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            parsed = default

        if not math.isfinite(parsed):
            parsed = default

        if min_value is not None:
            parsed = max(min_value, parsed)
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    def _should_use_llm_narrative(self, combat_result: CombatResult) -> bool:
        """判断当前战斗结果是否应使用LLM叙述"""
        # 全局叙述开关：关闭后不生成任何长叙述（统一回退短句）
        if not getattr(config.game, "enable_combat_narrative", True):
            return False

        # 通过配置细分控制不同怪物类型是否使用LLM
        if combat_result.is_boss:
            return bool(getattr(config.game, "boss_defeat_full_context", True))
        if combat_result.is_quest_monster:
            return bool(getattr(config.game, "quest_monster_full_context", True))
        return bool(getattr(config.game, "normal_monster_full_context", False))

    def _weighted_random_choice(self, weighted_options: List[Tuple[str, int]]) -> str:
        """从加权候选中随机选择一条文本"""
        if not weighted_options:
            return ""

        total_weight = sum(max(0, weight) for _, weight in weighted_options)
        if total_weight <= 0:
            return weighted_options[0][0]

        pick = random.uniform(0, total_weight)
        cumulative = 0.0
        for text, weight in weighted_options:
            cumulative += max(0, weight)
            if pick <= cumulative:
                return text

        return weighted_options[-1][0]

    def _generate_local_normal_monster_narrative(
        self,
        game_state: GameState,
        combat_result: CombatResult
    ) -> str:
        """普通怪物战斗结算：本地化 + 加权随机 + 多分支叙述"""
        monster = combat_result.defeated_monster
        monster_name = monster.name if monster else "怪物"
        map_name_raw = getattr(game_state.current_map, "name", "未知区域")
        map_name = str(map_name_raw) if map_name_raw else "未知区域"
        map_depth = self._safe_int(getattr(game_state.current_map, "depth", 1), default=1, min_value=1)
        challenge_rating = self._safe_float(
            getattr(monster, "challenge_rating", 1.0) if monster else 1.0,
            default=1.0,
            min_value=0.0
        )
        damage_dealt = self._safe_int(combat_result.damage_dealt, default=0, min_value=0)
        experience_gained = self._safe_int(combat_result.experience_gained, default=0, min_value=0)

        opening_pool: List[Tuple[str, int]] = [
            ("你抓住 {monster_name} 露出的破绽，一击定音结束了这场遭遇。", 16),
            ("短促而凶狠的交锋后，{monster_name} 终于在你面前倒下。", 14),
            ("你稳住呼吸与步伐，在缠斗中完成了对 {monster_name} 的收割。", 12),
            ("战场节奏被你牢牢掌控，{monster_name} 的反扑最终化为徒劳。", 10),
            ("你顺势反击，利落地斩落了 {monster_name}。", 10),
        ]

        if challenge_rating >= 3.0:
            opening_pool.extend([
                (f"面对挑战等级 {challenge_rating:.1f} 的 {monster_name}，你依旧打出了干净利落的终结。", 7),
                (f"即便是挑战等级 {challenge_rating:.1f} 的强敌，也没能在你面前撑住最后一轮攻势。", 6),
            ])

        if damage_dealt >= 25:
            opening_pool.extend([
                ("你的终结一击势大力沉，几乎在瞬间就压垮了对手。", 10),
                ("最后这一记重击干脆狠厉，直接终止了战斗。", 8),
            ])
        elif damage_dealt <= 8:
            opening_pool.extend([
                ("这不是最华丽的一战，但你以稳健与耐心拿下了胜利。", 8),
                ("你没有冒进，而是用精准而克制的节奏磨掉了对手的最后气力。", 7),
            ])

        opening_line = self._weighted_random_choice(opening_pool).format(monster_name=monster_name)

        if damage_dealt >= max(26, int(challenge_rating * 10)):
            tempo_pool: List[Tuple[str, int]] = [
                ("战斗的主动权在这一刻彻底倒向你，压制感极其明显。", 14),
                ("你把握住窗口期连续施压，对手几乎没有还手余地。", 11),
                ("从出手到终结都干净利落，这是一场高效率的击杀。", 9),
            ]
        elif damage_dealt <= 8:
            tempo_pool = [
                ("胜负来自细节与判断，你在消耗战里展现了足够的老练。", 13),
                ("你通过走位与时机慢慢拆解了敌人的进攻节奏。", 10),
                ("这场战斗并不爆裂，却足够扎实且有效。", 9),
            ]
        else:
            tempo_pool = [
                ("你在攻防转换间保持了节奏优势，稳定压过了敌方。", 12),
                ("每一次交换都在向你倾斜，最终形成了决定性的胜势。", 10),
                ("战斗过程紧凑而有序，你以经验拿下了这场遭遇。", 9),
            ]

        tempo_line = self._weighted_random_choice(tempo_pool)

        progress_pool: List[Tuple[str, int]] = [
            (f"这场胜利为你带来 {experience_gained} 点经验，你在 {map_name} 的行动愈发从容。", 13),
            (f"经验 +{experience_gained}，你对第 {map_depth} 层的威胁判断更加清晰。", 11),
            (f"随着 {experience_gained} 点经验入账，你的战斗感觉变得更敏锐了。", 9),
        ]
        if map_depth >= 3:
            progress_pool.extend([
                (f"在更深层的压迫环境中，你依然维持了稳定输出，这份经验尤为可贵。", 8),
                (f"第 {map_depth} 层危机四伏，但这次胜利证明你已逐步适应深层战场。", 7),
            ])
        progress_line = self._weighted_random_choice(progress_pool)

        loot_items = combat_result.loot_items or []
        if combat_result.level_up:
            current_level = game_state.player.stats.level
            reward_pool: List[Tuple[str, int]] = [
                (f"胜利的余韵仍在翻涌，你的等级提升到了 {current_level} 级，状态也随之焕然一新。", 15),
                (f"力量在体内重新校准——你成功晋升到 {current_level} 级。", 11),
                (f"你从这场实战中完成突破，等级达到 {current_level} 级。", 9),
            ]
            reward_line = self._weighted_random_choice(reward_pool)
        elif loot_items:
            loot_names = "、".join(item.name for item in loot_items[:2])
            loot_label = f"{loot_names}等战利品" if len(loot_items) > 2 else f"{loot_names}战利品"
            reward_pool = [
                (f"你迅速清点战场，收获了 {loot_label}。", 14),
                (f"击败敌人后，你从残骸中找到了 {loot_label}。", 10),
                (f"这场交锋并非徒劳，你带走了 {loot_label}。", 8),
            ]
            reward_line = self._weighted_random_choice(reward_pool)
        else:
            reward_pool = [
                ("战场上没有留下太多可用物资，但你已抢得继续推进的先机。", 12),
                ("虽然没有像样的掉落，但你依旧稳稳收下了这场胜利。", 10),
                ("你没发现太多战利品，不过前路的主动权已经回到你手里。", 8),
            ]
            reward_line = self._weighted_random_choice(reward_pool)

        closing_pool: List[Tuple[str, int]] = [
            (f"{map_name} 的阴影仍未散去，而你已经准备好迎接下一次遭遇。", 12),
            (f"第 {map_depth} 层的危险还在蔓延，你握紧武器继续前行。", 10),
            ("你收拢呼吸，重新观察四周，等待下一个值得出手的目标。", 9),
        ]
        closing_line = self._weighted_random_choice(closing_pool)

        # 多段落输出：便于前端按段落展示
        return "\n\n".join([
            opening_line,
            tempo_line,
            progress_line,
            reward_line,
            closing_line,
        ])

    async def _generate_combat_narrative(
        self, 
        game_state: GameState, 
        combat_result: CombatResult
    ) -> str:
        """生成战斗叙述"""
        try:
            # 获取活跃任务信息
            active_quest = next((q for q in game_state.quests if q.is_active), None)
            quest_info = ""
            if active_quest:
                quest_info = f"\n当前任务：{active_quest.title}\n任务进度：{active_quest.progress_percentage:.1f}%"
            
            # 构建提示
            prompt = prompt_manager.format_prompt(
                "combat_victory_narrative",
                player_name=game_state.player.name,
                player_level=game_state.player.stats.level,
                player_hp=game_state.player.stats.hp,
                player_max_hp=game_state.player.stats.max_hp,
                monster_name=combat_result.defeated_monster.name,
                monster_description=combat_result.defeated_monster.description,
                is_boss=combat_result.is_boss,
                is_quest_monster=combat_result.is_quest_monster,
                damage_dealt=combat_result.damage_dealt,
                experience_gained=combat_result.experience_gained,
                level_up=combat_result.level_up,
                loot_items=[item.name for item in combat_result.loot_items],
                quest_progress=combat_result.quest_progress,
                map_name=game_state.current_map.name,
                map_depth=game_state.current_map.depth,
                quest_info=quest_info
            )
            
            # 调用LLM生成叙述
            narrative = await llm_service._async_generate(prompt)
            
            # 调试日志
            if config.game.show_llm_debug:
                logger.info(f"Combat narrative prompt: {prompt}")
                logger.info(f"Combat narrative response: {narrative}")
            
            return narrative
        
        except Exception as e:
            logger.error(f"Failed to generate combat narrative: {e}")
            return self._get_fallback_narrative(combat_result, game_state=game_state)
    
    async def _resolve_combat_narrative(
        self,
        game_state: GameState,
        combat_result: CombatResult
    ) -> str:
        """统一解析战斗叙述，保证开关语义一致且具备异常降级"""
        # 语义：关闭战斗叙述时，所有怪物统一短句
        if not getattr(config.game, "enable_combat_narrative", True):
            return self._get_short_narrative(combat_result)

        # 配置允许时使用LLM
        if self._should_use_llm_narrative(combat_result):
            return await self._generate_combat_narrative(game_state, combat_result)

        # 非LLM路径：普通怪优先本地多段落，重要怪保持短句回退
        if not (combat_result.is_boss or combat_result.is_quest_monster):
            try:
                return self._generate_local_normal_monster_narrative(game_state, combat_result)
            except Exception as e:
                logger.warning(f"Local normal monster narrative failed, fallback to short narrative: {e}")

        return self._get_short_narrative(combat_result)

    def _get_short_narrative(self, combat_result: CombatResult) -> str:
        """统一短句叙述（配置关闭/异常回退使用）"""
        monster_name = combat_result.defeated_monster.name if combat_result.defeated_monster else "怪物"

        if combat_result.is_boss:
            return f"经过激烈的战斗，你终于击败了强大的Boss {monster_name}！这是一场值得铭记的胜利。"
        if combat_result.is_quest_monster:
            return f"你成功击败了任务目标 {monster_name}，离完成任务又近了一步。"
        return f"你击败了 {monster_name}，继续前进吧。"

    def _get_fallback_narrative(
        self,
        combat_result: CombatResult,
        game_state: Optional[GameState] = None
    ) -> str:
        """获取降级叙述（兼容旧调用）"""
        # 保留兼容：默认返回统一短句，不再在此分支生成长叙述
        return self._get_short_narrative(combat_result)
    
    def _cleanup_history(self):
        """清理历史记录"""
        max_history = 20
        if len(self.combat_history) > max_history:
            self.combat_history = self.combat_history[-max_history:]
    
    def get_recent_combats(self, count: int = 5) -> List[CombatResult]:
        """获取最近的战斗记录"""
        return self.combat_history[-count:]
    
    def get_combat_statistics(self) -> Dict[str, Any]:
        """获取战斗统计"""
        return {
            "total_monsters_defeated": self.total_monsters_defeated,
            "total_bosses_defeated": self.total_bosses_defeated,
            "total_experience_gained": sum(c.experience_gained for c in self.combat_history),
            "recent_combats": len(self.combat_history)
        }


# 全局实例
combat_result_manager = CombatResultManager()

