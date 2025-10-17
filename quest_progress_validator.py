"""
任务进度验证器
确保任务配置的进度分配合理，能够达到100%完成
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from data_models import Quest, QuestEvent, QuestMonster
from config import config

logger = logging.getLogger(__name__)


@dataclass
class ProgressBreakdown:
    """进度分解"""
    events_progress: float = 0.0  # 事件进度总和
    monsters_progress: float = 0.0  # 怪物进度总和
    map_transitions_progress: float = 0.0  # 地图切换进度
    exploration_buffer: float = 0.0  # 探索缓冲进度
    total_guaranteed: float = 0.0  # 保证可获得的总进度
    total_possible: float = 0.0  # 可能获得的最大进度
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "events_progress": self.events_progress,
            "monsters_progress": self.monsters_progress,
            "map_transitions_progress": self.map_transitions_progress,
            "exploration_buffer": self.exploration_buffer,
            "total_guaranteed": self.total_guaranteed,
            "total_possible": self.total_possible
        }


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    issues: List[str]
    warnings: List[str]
    breakdown: ProgressBreakdown
    suggested_adjustments: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": self.issues,
            "warnings": self.warnings,
            "breakdown": self.breakdown.to_dict(),
            "suggested_adjustments": self.suggested_adjustments
        }


class QuestProgressValidator:
    """任务进度验证器"""
    
    # 进度分配建议（总和应为100%）
    RECOMMENDED_ALLOCATION = {
        "mandatory_objectives": 50.0,  # 必须完成的目标（事件+怪物）
        "map_transitions": 30.0,  # 地图切换
        "exploration_buffer": 20.0  # 探索和其他活动的缓冲
    }
    
    # 容差范围
    TOLERANCE = {
        "min_guaranteed": 95.0,  # 最小保证进度（必须能达到）
        "max_total": 120.0,  # 最大总进度（避免过度分配）
        "min_boss_progress": 15.0,  # Boss最小进度值
        "max_single_objective": 35.0  # 单个目标最大进度值
    }
    
    def __init__(self):
        self.max_floors = config.game.max_quest_floors
        self.map_transition_progress = config.game.map_transition_progress
    
    def validate_quest(self, quest: Quest) -> ValidationResult:
        """验证任务配置"""
        issues = []
        warnings = []
        breakdown = self._calculate_progress_breakdown(quest)
        
        # 检查1：必须完成的目标进度是否足够
        if breakdown.total_guaranteed < self.TOLERANCE["min_guaranteed"]:
            issues.append(
                f"保证进度不足：{breakdown.total_guaranteed:.1f}% < {self.TOLERANCE['min_guaranteed']:.1f}%"
            )
        
        # 检查2：总进度是否过高
        if breakdown.total_possible > self.TOLERANCE["max_total"]:
            warnings.append(
                f"总进度过高：{breakdown.total_possible:.1f}% > {self.TOLERANCE['max_total']:.1f}%"
            )
        
        # 检查3：Boss进度值是否合理
        boss_monsters = [m for m in quest.special_monsters if m.is_boss]
        for boss in boss_monsters:
            if boss.progress_value < self.TOLERANCE["min_boss_progress"]:
                warnings.append(
                    f"Boss '{boss.name}' 进度值过低：{boss.progress_value:.1f}% < {self.TOLERANCE['min_boss_progress']:.1f}%"
                )
        
        # 检查4：单个目标进度是否过高
        all_objectives = list(quest.special_events) + list(quest.special_monsters)
        for obj in all_objectives:
            if obj.progress_value > self.TOLERANCE["max_single_objective"]:
                warnings.append(
                    f"目标 '{obj.name}' 进度值过高：{obj.progress_value:.1f}% > {self.TOLERANCE['max_single_objective']:.1f}%"
                )
        
        # 检查5：每个楼层是否都有任务目标
        floor_coverage = self._check_floor_coverage(quest)
        for floor, has_objectives in floor_coverage.items():
            if not has_objectives:
                warnings.append(f"第{floor}层没有任务目标")
        
        # 生成调整建议
        suggested_adjustments = self._generate_adjustments(quest, breakdown, issues, warnings)
        
        is_valid = len(issues) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            warnings=warnings,
            breakdown=breakdown,
            suggested_adjustments=suggested_adjustments
        )
    
    def _calculate_progress_breakdown(self, quest: Quest) -> ProgressBreakdown:
        """计算进度分解"""
        breakdown = ProgressBreakdown()
        
        # 计算事件进度
        mandatory_events = [e for e in quest.special_events if e.is_mandatory]
        breakdown.events_progress = sum(e.progress_value for e in mandatory_events)
        
        # 计算怪物进度
        breakdown.monsters_progress = sum(m.progress_value for m in quest.special_monsters)
        
        # 计算地图切换进度（n层地下城有n-1次切换）
        num_transitions = len(quest.target_floors) - 1 if quest.target_floors else self.max_floors - 1
        breakdown.map_transitions_progress = num_transitions * self.map_transition_progress
        
        # 探索缓冲（预留给普通战斗、探索等）
        breakdown.exploration_buffer = 100.0 - (
            breakdown.events_progress + 
            breakdown.monsters_progress + 
            breakdown.map_transitions_progress
        )
        
        # 保证可获得的进度（必须完成的目标 + 地图切换）
        breakdown.total_guaranteed = (
            breakdown.events_progress + 
            breakdown.monsters_progress + 
            breakdown.map_transitions_progress
        )
        
        # 可能获得的最大进度（包括探索缓冲）
        breakdown.total_possible = breakdown.total_guaranteed + max(0, breakdown.exploration_buffer)
        
        return breakdown
    
    def _check_floor_coverage(self, quest: Quest) -> Dict[int, bool]:
        """检查每个楼层是否都有任务目标"""
        coverage = {floor: False for floor in quest.target_floors}
        
        # 检查事件覆盖
        for event in quest.special_events:
            if event.location_hint:
                for floor in quest.target_floors:
                    if str(floor) in event.location_hint:
                        coverage[floor] = True
        
        # 检查怪物覆盖
        for monster in quest.special_monsters:
            if monster.location_hint:
                for floor in quest.target_floors:
                    if str(floor) in monster.location_hint:
                        coverage[floor] = True
        
        return coverage
    
    def _generate_adjustments(self, quest: Quest, breakdown: ProgressBreakdown,
                            issues: List[str], warnings: List[str]) -> Dict[str, Any]:
        """生成调整建议"""
        adjustments = {}
        
        # 如果保证进度不足，需要增加目标进度值
        if breakdown.total_guaranteed < self.TOLERANCE["min_guaranteed"]:
            deficit = self.TOLERANCE["min_guaranteed"] - breakdown.total_guaranteed
            adjustments["increase_objectives_by"] = deficit
            adjustments["suggestion"] = f"建议增加任务目标的进度值总和 {deficit:.1f}%"
        
        # 如果总进度过高，需要降低目标进度值
        elif breakdown.total_possible > self.TOLERANCE["max_total"]:
            excess = breakdown.total_possible - 100.0
            adjustments["decrease_objectives_by"] = excess
            adjustments["suggestion"] = f"建议降低任务目标的进度值总和 {excess:.1f}%"
        
        # 提供理想的进度分配
        adjustments["recommended_allocation"] = {
            "events_and_monsters": self.RECOMMENDED_ALLOCATION["mandatory_objectives"],
            "map_transitions": breakdown.map_transitions_progress,
            "exploration_buffer": self.RECOMMENDED_ALLOCATION["exploration_buffer"]
        }
        
        return adjustments
    
    def auto_adjust_quest(self, quest: Quest) -> Tuple[Quest, ValidationResult]:
        """自动调整任务进度分配"""
        validation = self.validate_quest(quest)
        
        if validation.is_valid and len(validation.warnings) == 0:
            logger.info(f"Quest '{quest.title}' progress allocation is valid")
            return quest, validation
        
        logger.info(f"Auto-adjusting quest '{quest.title}' progress allocation")
        
        # 计算目标进度总和
        total_objectives_progress = (
            validation.breakdown.events_progress + 
            validation.breakdown.monsters_progress
        )
        
        # 计算理想的目标进度总和（100% - 地图切换进度 - 探索缓冲）
        ideal_objectives_progress = (
            100.0 - 
            validation.breakdown.map_transitions_progress - 
            self.RECOMMENDED_ALLOCATION["exploration_buffer"]
        )
        
        # 如果当前进度为0，无法调整
        if total_objectives_progress == 0:
            logger.warning("Cannot auto-adjust: no objectives with progress values")
            return quest, validation
        
        # 计算调整比例
        adjustment_ratio = ideal_objectives_progress / total_objectives_progress
        
        logger.info(f"Adjustment ratio: {adjustment_ratio:.2f} (from {total_objectives_progress:.1f}% to {ideal_objectives_progress:.1f}%)")
        
        # 调整事件进度
        for event in quest.special_events:
            if event.progress_value > 0:
                old_value = event.progress_value
                event.progress_value = round(event.progress_value * adjustment_ratio, 1)
                logger.debug(f"Event '{event.name}': {old_value:.1f}% -> {event.progress_value:.1f}%")
        
        # 调整怪物进度
        for monster in quest.special_monsters:
            if monster.progress_value > 0:
                old_value = monster.progress_value
                monster.progress_value = round(monster.progress_value * adjustment_ratio, 1)
                # 确保Boss进度不低于最小值
                if monster.is_boss:
                    monster.progress_value = max(monster.progress_value, self.TOLERANCE["min_boss_progress"])
                logger.debug(f"Monster '{monster.name}': {old_value:.1f}% -> {monster.progress_value:.1f}%")
        
        # 重新验证
        new_validation = self.validate_quest(quest)
        logger.info(f"After adjustment: guaranteed={new_validation.breakdown.total_guaranteed:.1f}%, possible={new_validation.breakdown.total_possible:.1f}%")
        
        return quest, new_validation


# 全局验证器实例
quest_progress_validator = QuestProgressValidator()


# 导出
__all__ = [
    "QuestProgressValidator",
    "ProgressBreakdown",
    "ValidationResult",
    "quest_progress_validator"
]

