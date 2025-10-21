"""
Labyrinthia AI - 陷阱数据 Schema 定义与验证
Trap Data Schema Definition and Validation
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TrapSchema:
    """陷阱数据标准 Schema
    
    定义陷阱事件数据的标准字段和默认值，确保前后端数据一致性
    """
    # 陷阱类型
    trap_type: str = "damage"  # damage, debuff, teleport, alarm, restraint
    
    # 陷阱名称和描述
    trap_name: str = "未知陷阱"
    trap_description: str = "你发现了一个陷阱！"
    
    # 难度等级（DC）
    detect_dc: int = 15  # 侦测难度（被动感知/主动感知检定）
    disarm_dc: int = 18  # 解除难度（灵巧检定+工具熟练）
    save_dc: int = 14    # 豁免难度（敏捷豁免，用于规避）
    
    # 伤害型陷阱参数
    damage: int = 15
    damage_type: str = "physical"  # physical, fire, cold, poison, acid, etc.
    save_half_damage: bool = True  # 豁免成功是否减半伤害
    
    # 减益型陷阱参数
    debuff_type: str = "slow"  # slow, poison, blind, restrained, etc.
    debuff_duration: int = 3   # 减益持续回合数
    
    # 传送型陷阱参数
    teleport_range: str = "random"  # random, nearby, far
    
    # 警报型陷阱参数
    alarm_radius: int = 10  # 警报影响半径
    summon_monsters: bool = False  # 是否召唤怪物
    
    # 束缚型陷阱参数
    restraint_dc: int = 15  # 挣脱难度
    restraint_duration: int = 3  # 束缚持续回合数
    
    # 状态标记（运行时字段，不由LLM生成）
    is_detected: bool = False  # 是否已被发现
    is_disarmed: bool = False  # 是否已被解除
    is_triggered: bool = False  # 是否已被触发
    
    # 高级选项
    friendly_to_monsters: bool = False  # 怪物是否免疫此陷阱
    can_be_disarmed: bool = True  # 是否可以被解除
    can_be_avoided: bool = True   # 是否可以被规避
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "trap_type": self.trap_type,
            "trap_name": self.trap_name,
            "trap_description": self.trap_description,
            "detect_dc": self.detect_dc,
            "disarm_dc": self.disarm_dc,
            "save_dc": self.save_dc,
            "damage": self.damage,
            "damage_type": self.damage_type,
            "save_half_damage": self.save_half_damage,
            "debuff_type": self.debuff_type,
            "debuff_duration": self.debuff_duration,
            "teleport_range": self.teleport_range,
            "alarm_radius": self.alarm_radius,
            "summon_monsters": self.summon_monsters,
            "restraint_dc": self.restraint_dc,
            "restraint_duration": self.restraint_duration,
            "is_detected": self.is_detected,
            "is_disarmed": self.is_disarmed,
            "is_triggered": self.is_triggered,
            "friendly_to_monsters": self.friendly_to_monsters,
            "can_be_disarmed": self.can_be_disarmed,
            "can_be_avoided": self.can_be_avoided
        }


class TrapDataValidator:
    """陷阱数据验证器
    
    验证和规范化陷阱事件数据，确保数据完整性和一致性
    """
    
    # 有效的陷阱类型
    VALID_TRAP_TYPES = {"damage", "debuff", "teleport", "alarm", "restraint"}
    
    # 有效的伤害类型
    VALID_DAMAGE_TYPES = {
        "physical", "fire", "cold", "poison", "acid", 
        "lightning", "thunder", "necrotic", "radiant", "psychic", "force"
    }
    
    # 有效的减益类型
    VALID_DEBUFF_TYPES = {
        "slow", "poison", "blind", "restrained", "paralyzed", 
        "stunned", "frightened", "charmed", "exhausted"
    }
    
    @staticmethod
    def validate_and_normalize(trap_data: Dict[str, Any]) -> Dict[str, Any]:
        """验证并规范化陷阱数据
        
        Args:
            trap_data: 原始陷阱数据字典
            
        Returns:
            规范化后的陷阱数据字典
        """
        # 创建默认 schema
        schema = TrapSchema()
        
        # 验证并设置陷阱类型
        trap_type = trap_data.get("trap_type", "damage")
        if trap_type not in TrapDataValidator.VALID_TRAP_TYPES:
            logger.warning(f"Invalid trap_type '{trap_type}', using default 'damage'")
            trap_type = "damage"
        schema.trap_type = trap_type
        
        # 基础信息
        schema.trap_name = trap_data.get("trap_name", schema.trap_name)
        schema.trap_description = trap_data.get("trap_description", schema.trap_description)
        
        # 难度等级（DC）- 确保在合理范围内
        schema.detect_dc = TrapDataValidator._clamp_dc(trap_data.get("detect_dc", 15))
        schema.disarm_dc = TrapDataValidator._clamp_dc(trap_data.get("disarm_dc", 18))
        schema.save_dc = TrapDataValidator._clamp_dc(trap_data.get("save_dc", 14))
        
        # 根据陷阱类型设置特定参数
        if trap_type == "damage":
            schema.damage = max(1, min(100, trap_data.get("damage", 15)))
            damage_type = trap_data.get("damage_type", "physical")
            if damage_type not in TrapDataValidator.VALID_DAMAGE_TYPES:
                logger.warning(f"Invalid damage_type '{damage_type}', using 'physical'")
                damage_type = "physical"
            schema.damage_type = damage_type
            schema.save_half_damage = trap_data.get("save_half_damage", True)
            
        elif trap_type == "debuff":
            debuff_type = trap_data.get("debuff_type", "slow")
            if debuff_type not in TrapDataValidator.VALID_DEBUFF_TYPES:
                logger.warning(f"Invalid debuff_type '{debuff_type}', using 'slow'")
                debuff_type = "slow"
            schema.debuff_type = debuff_type
            schema.debuff_duration = max(1, min(10, trap_data.get("debuff_duration", 3)))
            
        elif trap_type == "teleport":
            schema.teleport_range = trap_data.get("teleport_range", "random")
            
        elif trap_type == "alarm":
            schema.alarm_radius = max(5, min(20, trap_data.get("alarm_radius", 10)))
            schema.summon_monsters = trap_data.get("summon_monsters", False)
            
        elif trap_type == "restraint":
            schema.restraint_dc = TrapDataValidator._clamp_dc(trap_data.get("restraint_dc", 15))
            schema.restraint_duration = max(1, min(10, trap_data.get("restraint_duration", 3)))
        
        # 状态标记（保留原有状态）
        schema.is_detected = trap_data.get("is_detected", False)
        schema.is_disarmed = trap_data.get("is_disarmed", False)
        schema.is_triggered = trap_data.get("is_triggered", False)
        
        # 高级选项
        schema.friendly_to_monsters = trap_data.get("friendly_to_monsters", False)
        schema.can_be_disarmed = trap_data.get("can_be_disarmed", True)
        schema.can_be_avoided = trap_data.get("can_be_avoided", True)
        
        result = schema.to_dict()
        
        # 记录验证结果
        logger.debug(f"Validated trap data: type={trap_type}, detect_dc={schema.detect_dc}, "
                    f"disarm_dc={schema.disarm_dc}, save_dc={schema.save_dc}")
        
        return result
    
    @staticmethod
    def _clamp_dc(value: Any, min_dc: int = 5, max_dc: int = 30) -> int:
        """限制 DC 值在合理范围内
        
        Args:
            value: 原始值
            min_dc: 最小 DC
            max_dc: 最大 DC
            
        Returns:
            限制后的 DC 值
        """
        try:
            dc = int(value)
            return max(min_dc, min(max_dc, dc))
        except (TypeError, ValueError):
            logger.warning(f"Invalid DC value '{value}', using default 15")
            return 15
    
    @staticmethod
    def create_default_trap(trap_type: str = "damage") -> Dict[str, Any]:
        """创建默认陷阱数据
        
        Args:
            trap_type: 陷阱类型
            
        Returns:
            默认陷阱数据字典
        """
        schema = TrapSchema()
        schema.trap_type = trap_type if trap_type in TrapDataValidator.VALID_TRAP_TYPES else "damage"
        return schema.to_dict()


# 全局验证器实例
trap_validator = TrapDataValidator()

