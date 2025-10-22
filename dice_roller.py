"""
Labyrinthia AI - 骰子投掷引擎
Dice Rolling Engine for DND-style mechanics
"""

import logging
import random
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DiceRollResult:
    """骰子投掷结果"""
    dice_notation: str  # 骰子表达式，如 "1d20", "2d6+3"
    rolls: List[int]  # 所有投掷结果
    picked_roll: int  # 最终选择的投掷值（考虑优势/劣势）
    modifier: int  # 修正值
    total: int  # 总值
    is_critical_20: bool  # 是否投出自然20
    is_critical_1: bool  # 是否投出自然1
    advantage: bool  # 是否有优势
    disadvantage: bool  # 是否有劣势
    breakdown: str  # 详细过程描述


class DiceRoller:
    """
    骰子投掷引擎
    
    支持功能：
    1. 标准骰子表达式解析（如 "1d20", "2d6+3", "3d8-1"）
    2. 优势/劣势机制（投两次取高/低）
    3. 重投机制（如 Halfling Lucky）
    4. 详细的投掷过程记录
    """
    
    def __init__(self, seed: Optional[int] = None):
        """初始化骰子投掷器
        
        Args:
            seed: 随机数种子（用于测试）
        """
        if seed is not None:
            random.seed(seed)
    
    def roll_d20(self, advantage: bool = False, disadvantage: bool = False,
                 reroll_ones: bool = False) -> DiceRollResult:
        """投掷1d20（最常用的检定骰）
        
        Args:
            advantage: 是否有优势（投两次取高）
            disadvantage: 是否有劣势（投两次取低）
            reroll_ones: 是否重投1（Halfling Lucky特性）
            
        Returns:
            投掷结果
        """
        return self.roll_dice(1, 20, modifier=0, advantage=advantage, 
                            disadvantage=disadvantage, reroll_ones=reroll_ones)
    
    def roll_dice(self, count: int, sides: int, modifier: int = 0,
                  advantage: bool = False, disadvantage: bool = False,
                  reroll_ones: bool = False, drop_lowest: bool = False) -> DiceRollResult:
        """投掷骰子
        
        Args:
            count: 骰子数量
            sides: 骰子面数
            modifier: 修正值
            advantage: 是否有优势
            disadvantage: 是否有劣势
            reroll_ones: 是否重投1
            drop_lowest: 是否丢弃最低值（用于属性生成等）
            
        Returns:
            投掷结果
        """
        # 优势/劣势只对单个d20有效
        if advantage or disadvantage:
            if count != 1 or sides != 20:
                logger.warning(f"Advantage/disadvantage only applies to 1d20, got {count}d{sides}")
                advantage = disadvantage = False
        
        # 投掷骰子
        rolls = []
        for _ in range(count):
            roll = random.randint(1, sides)
            # Halfling Lucky: 重投1
            if reroll_ones and roll == 1:
                reroll = random.randint(1, sides)
                logger.debug(f"Rerolled 1 -> {reroll}")
                roll = reroll
            rolls.append(roll)
        
        # 处理优势/劣势（投第二次）
        if advantage or disadvantage:
            second_roll = random.randint(1, sides)
            if reroll_ones and second_roll == 1:
                second_roll = random.randint(1, sides)
            
            if advantage:
                picked = max(rolls[0], second_roll)
                rolls = [rolls[0], second_roll]
            else:  # disadvantage
                picked = min(rolls[0], second_roll)
                rolls = [rolls[0], second_roll]
        else:
            # 处理drop_lowest
            if drop_lowest and len(rolls) > 1:
                picked = sum(sorted(rolls)[1:])  # 丢弃最低值后求和
            else:
                picked = sum(rolls)
        
        total = picked + modifier
        
        # 检测致命成功/失败（仅对d20）
        is_crit_20 = sides == 20 and max(rolls) == 20
        is_crit_1 = sides == 20 and min(rolls) == 1
        
        # 构建详细描述
        breakdown = self._build_breakdown(count, sides, rolls, picked, modifier, 
                                         advantage, disadvantage, drop_lowest)
        
        return DiceRollResult(
            dice_notation=f"{count}d{sides}{modifier:+d}" if modifier else f"{count}d{sides}",
            rolls=rolls,
            picked_roll=picked,
            modifier=modifier,
            total=total,
            is_critical_20=is_crit_20,
            is_critical_1=is_crit_1,
            advantage=advantage,
            disadvantage=disadvantage,
            breakdown=breakdown
        )
    
    def roll_expression(self, expression: str, advantage: bool = False, 
                       disadvantage: bool = False) -> DiceRollResult:
        """解析并投掷骰子表达式
        
        支持格式：
        - "1d20"
        - "2d6+3"
        - "3d8-1"
        - "4d6" (drop lowest for ability scores)
        
        Args:
            expression: 骰子表达式
            advantage: 是否有优势（仅对1d20有效）
            disadvantage: 是否有劣势（仅对1d20有效）
            
        Returns:
            投掷结果
        """
        # 解析表达式
        pattern = r'(\d+)d(\d+)([\+\-]\d+)?'
        match = re.match(pattern, expression.strip().lower())
        
        if not match:
            raise ValueError(f"Invalid dice expression: {expression}")
        
        count = int(match.group(1))
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0
        
        return self.roll_dice(count, sides, modifier, advantage, disadvantage)
    
    def _build_breakdown(self, count: int, sides: int, rolls: List[int], 
                        picked: int, modifier: int, advantage: bool, 
                        disadvantage: bool, drop_lowest: bool) -> str:
        """构建详细的投掷过程描述
        
        Returns:
            格式化的描述字符串
        """
        parts = []
        
        # 骰子投掷部分
        if advantage or disadvantage:
            adv_text = "优势" if advantage else "劣势"
            parts.append(f"🎲 1d{sides}({adv_text})=[{rolls[0]}, {rolls[1]}]→{picked}")
        elif drop_lowest and len(rolls) > 1:
            parts.append(f"🎲 {count}d{sides}=[{', '.join(map(str, rolls))}]→{picked}(丢弃最低)")
        elif count == 1:
            parts.append(f"🎲 1d{sides}={rolls[0]}")
        else:
            parts.append(f"🎲 {count}d{sides}=[{', '.join(map(str, rolls))}]={picked}")
        
        # 修正值部分
        if modifier != 0:
            parts.append(f"{modifier:+d}")
        
        # 总值
        total = picked + modifier
        parts.append(f"= {total}")
        
        return " ".join(parts)


# 全局骰子投掷器实例
dice_roller = DiceRoller()

__all__ = ["DiceRoller", "DiceRollResult", "dice_roller"]

