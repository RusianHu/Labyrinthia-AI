"""
Labyrinthia AI - 判定解析引擎
Roll Resolver for DND-style checks and saves
"""

import logging
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass
from data_models import Character, Monster
from dice_roller import DiceRoller, dice_roller

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """检定结果（统一格式）"""
    check_type: str  # "ability_check", "saving_throw", "attack_roll"
    entity_name: str  # 实体名称
    ability: str  # 使用的属性
    dc: Optional[int]  # 难度等级（攻击检定为None）
    target_ac: Optional[int]  # 目标AC（仅攻击检定）
    
    # 投掷详情
    roll: int  # 骰子点数
    ability_modifier: int  # 属性调整值
    proficiency_bonus: int  # 熟练加值
    expertise_bonus: int  # 专精额外加值（专精=双倍熟练）
    extra_bonus: int  # 其他加值
    total: int  # 总值
    
    # 结果标记
    success: bool  # 是否成功
    critical_success: bool  # 致命成功（自然20）
    critical_failure: bool  # 致命失败（自然1）
    advantage: bool  # 是否有优势
    disadvantage: bool  # 是否有劣势
    
    # 格式化文本
    breakdown: str  # 详细过程（如 "🎲 1d20=15 + WIS+3 + PROF+2 = 20"）
    ui_text: str  # UI显示文本（如 "✅ 感知检定成功：20 vs DC 15"）


class RollResolver:
    """
    判定解析引擎
    
    统一处理所有DND风格的检定：
    1. 属性检定（Ability Check）
    2. 豁免检定（Saving Throw）
    3. 攻击检定（Attack Roll）
    4. 技能检定（Skill Check，基于属性检定）
    
    支持特性：
    - 熟练加值（Proficiency）
    - 专精加值（Expertise，双倍熟练）
    - 优势/劣势（Advantage/Disadvantage）
    - 额外加值（如魔法物品、增益效果）
    """
    
    def __init__(self, roller: Optional[DiceRoller] = None):
        """初始化判定解析器
        
        Args:
            roller: 骰子投掷器实例（默认使用全局实例）
        """
        self.roller = roller or dice_roller
    
    def ability_check(self, entity: Union[Character, Monster], ability: str, dc: int,
                     skill: Optional[str] = None, proficient: bool = False, 
                     expertise: bool = False, advantage: bool = False, 
                     disadvantage: bool = False, extra_bonus: int = 0) -> CheckResult:
        """属性检定
        
        Args:
            entity: 角色或怪物
            ability: 属性名称（strength, dexterity, constitution, intelligence, wisdom, charisma）
            dc: 难度等级
            skill: 技能名称（如 "perception", "stealth"，用于判断熟练）
            proficient: 是否熟练（如果提供skill，会自动检查entity.skill_proficiencies）
            expertise: 是否专精（双倍熟练加值）
            advantage: 是否有优势
            disadvantage: 是否有劣势
            extra_bonus: 额外加值
            
        Returns:
            检定结果
        """
        # 获取属性调整值
        ability_mod = entity.abilities.get_modifier(ability.lower())
        
        # 检查技能熟练
        if skill and hasattr(entity, 'skill_proficiencies'):
            proficient = skill.lower() in entity.skill_proficiencies
        
        # 计算熟练加值
        prof_bonus = 0
        expertise_bonus = 0
        if proficient:
            base_prof = getattr(entity, 'proficiency_bonus', 2)
            if expertise:
                # 专精 = 双倍熟练
                prof_bonus = base_prof
                expertise_bonus = base_prof
            else:
                prof_bonus = base_prof
        
        # 投掷1d20
        dice_result = self.roller.roll_d20(advantage=advantage, disadvantage=disadvantage)
        
        # 计算总值
        total = dice_result.picked_roll + ability_mod + prof_bonus + expertise_bonus + extra_bonus
        success = total >= dc
        
        # 构建详细描述
        breakdown_parts = [dice_result.breakdown]
        
        # 添加属性调整值
        ability_abbr = ability[:3].upper()
        breakdown_parts.append(f"+ {ability_abbr}{ability_mod:+d}")
        
        # 添加熟练加值
        if prof_bonus > 0:
            breakdown_parts.append(f"+ PROF{prof_bonus:+d}")
        if expertise_bonus > 0:
            breakdown_parts.append(f"+ EXP{expertise_bonus:+d}")
        
        # 添加额外加值
        if extra_bonus != 0:
            breakdown_parts.append(f"{extra_bonus:+d}")
        
        breakdown_parts.append(f"= {total}")
        breakdown = " ".join(breakdown_parts)
        
        # 构建UI文本
        success_icon = "✅" if success else "❌"
        check_name = f"{skill.capitalize()}检定" if skill else f"{ability.capitalize()}检定"
        ui_text = f"{success_icon} {check_name}：{total} vs DC {dc} - {'成功' if success else '失败'}"
        
        if dice_result.is_critical_20:
            ui_text += " 🎯致命成功！"
        elif dice_result.is_critical_1:
            ui_text += " 💀致命失败！"
        
        return CheckResult(
            check_type="ability_check",
            entity_name=entity.name,
            ability=ability.lower(),
            dc=dc,
            target_ac=None,
            roll=dice_result.picked_roll,
            ability_modifier=ability_mod,
            proficiency_bonus=prof_bonus,
            expertise_bonus=expertise_bonus,
            extra_bonus=extra_bonus,
            total=total,
            success=success,
            critical_success=dice_result.is_critical_20,
            critical_failure=dice_result.is_critical_1,
            advantage=advantage,
            disadvantage=disadvantage,
            breakdown=breakdown,
            ui_text=ui_text
        )
    
    def saving_throw(self, entity: Union[Character, Monster], save_type: str, dc: int,
                    proficient: bool = False, advantage: bool = False, 
                    disadvantage: bool = False, extra_bonus: int = 0) -> CheckResult:
        """豁免检定
        
        Args:
            entity: 角色或怪物
            save_type: 豁免类型（对应六维属性之一）
            dc: 难度等级
            proficient: 是否熟练（如果entity有saving_throw_proficiencies会自动检查）
            advantage: 是否有优势
            disadvantage: 是否有劣势
            extra_bonus: 额外加值
            
        Returns:
            检定结果
        """
        # 检查豁免熟练
        if hasattr(entity, 'saving_throw_proficiencies'):
            proficient = save_type.lower() in entity.saving_throw_proficiencies
        
        # 调用ability_check，但标记为saving_throw
        result = self.ability_check(
            entity, save_type, dc, 
            skill=None, proficient=proficient, expertise=False,
            advantage=advantage, disadvantage=disadvantage, extra_bonus=extra_bonus
        )
        
        # 修改类型和UI文本
        result.check_type = "saving_throw"
        
        save_abbr = save_type[:3].upper()
        success_icon = "✅" if result.success else "❌"
        result.ui_text = f"{success_icon} {save_abbr}豁免：{result.total} vs DC {dc} - {'成功' if result.success else '失败'}"
        
        if result.critical_success:
            result.ui_text += " 🎯致命成功！"
        elif result.critical_failure:
            result.ui_text += " 💀致命失败！"
        
        return result
    
    def attack_roll(self, attacker: Union[Character, Monster], target: Union[Character, Monster],
                   attack_type: str = "melee", proficient: bool = True,
                   advantage: bool = False, disadvantage: bool = False, 
                   extra_bonus: int = 0) -> CheckResult:
        """攻击检定
        
        Args:
            attacker: 攻击者
            target: 目标
            attack_type: 攻击类型（"melee"近战, "ranged"远程, "spell"法术）
            proficient: 是否熟练（默认True，大多数武器都熟练）
            advantage: 是否有优势
            disadvantage: 是否有劣势
            extra_bonus: 额外加值（如魔法武器）
            
        Returns:
            检定结果
        """
        # 确定使用的属性
        ability_map = {
            "melee": "strength",
            "ranged": "dexterity",
            "spell": "intelligence"
        }
        ability = ability_map.get(attack_type, "strength")
        
        # 获取属性调整值
        ability_mod = attacker.abilities.get_modifier(ability)
        
        # 计算熟练加值
        prof_bonus = getattr(attacker, 'proficiency_bonus', 2) if proficient else 0
        
        # 投掷1d20
        dice_result = self.roller.roll_d20(advantage=advantage, disadvantage=disadvantage)
        
        # 计算总值
        total = dice_result.picked_roll + ability_mod + prof_bonus + extra_bonus
        target_ac = target.stats.ac
        hit = total >= target_ac
        
        # 构建详细描述
        breakdown_parts = [dice_result.breakdown]
        
        ability_abbr = ability[:3].upper()
        breakdown_parts.append(f"+ {ability_abbr}{ability_mod:+d}")
        
        if prof_bonus > 0:
            breakdown_parts.append(f"+ PROF{prof_bonus:+d}")
        
        if extra_bonus != 0:
            breakdown_parts.append(f"{extra_bonus:+d}")
        
        breakdown_parts.append(f"= {total}")
        breakdown = " ".join(breakdown_parts)
        
        # 构建UI文本
        hit_icon = "⚔️" if hit else "❌"
        ui_text = f"{hit_icon} 攻击检定：{total} vs AC {target_ac} - {'命中' if hit else '未命中'}"
        
        if dice_result.is_critical_20:
            ui_text += " 🎯致命一击！"
        elif dice_result.is_critical_1:
            ui_text += " 💀大失误！"
        
        return CheckResult(
            check_type="attack_roll",
            entity_name=attacker.name,
            ability=ability,
            dc=None,
            target_ac=target_ac,
            roll=dice_result.picked_roll,
            ability_modifier=ability_mod,
            proficiency_bonus=prof_bonus,
            expertise_bonus=0,
            extra_bonus=extra_bonus,
            total=total,
            success=hit,
            critical_success=dice_result.is_critical_20,
            critical_failure=dice_result.is_critical_1,
            advantage=advantage,
            disadvantage=disadvantage,
            breakdown=breakdown,
            ui_text=ui_text
        )


# 全局判定解析器实例
roll_resolver = RollResolver()

__all__ = ["RollResolver", "CheckResult", "roll_resolver"]

