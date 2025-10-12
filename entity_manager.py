"""
Labyrinthia AI - 实体管理器
Entity Manager for unified character and monster management
"""

import logging
import random
from typing import Dict, Any, Optional, Union, List
from data_models import Character, Monster, Ability, Stats

logger = logging.getLogger(__name__)


class EntityManager:
    """
    实体管理器 - 统一管理角色和怪物
    
    提供:
    1. 统一的属性访问和修改接口
    2. DND机制: 技能检定、豁免检定、攻击检定
    3. 属性计算和验证
    4. 战斗相关计算
    """
    
    def __init__(self):
        pass
    
    # ==================== 属性访问和修改 ====================
    
    def get_ability_score(self, entity: Union[Character, Monster], ability_name: str) -> int:
        """获取实体的属性值
        
        Args:
            entity: 角色或怪物
            ability_name: 属性名称 (strength, dexterity, constitution, intelligence, wisdom, charisma)
            
        Returns:
            属性值
        """
        return getattr(entity.abilities, ability_name.lower(), 10)
    
    def get_ability_modifier(self, entity: Union[Character, Monster], ability_name: str) -> int:
        """获取实体的属性调整值
        
        Args:
            entity: 角色或怪物
            ability_name: 属性名称
            
        Returns:
            调整值
        """
        return entity.abilities.get_modifier(ability_name)
    
    def set_ability_score(self, entity: Union[Character, Monster], ability_name: str, value: int) -> bool:
        """设置实体的属性值
        
        Args:
            entity: 角色或怪物
            ability_name: 属性名称
            value: 新的属性值 (1-30)
            
        Returns:
            是否成功
        """
        try:
            # 验证属性值范围
            value = max(1, min(30, value))
            setattr(entity.abilities, ability_name.lower(), value)
            
            # 重新计算衍生属性
            entity.stats.calculate_derived_stats(entity.abilities)
            
            logger.info(f"Set {entity.name}'s {ability_name} to {value}")
            return True
        except Exception as e:
            logger.error(f"Failed to set ability score: {e}")
            return False
    
    def modify_ability_score(self, entity: Union[Character, Monster], ability_name: str, delta: int) -> bool:
        """修改实体的属性值 (增加或减少)
        
        Args:
            entity: 角色或怪物
            ability_name: 属性名称
            delta: 变化量 (正数为增加,负数为减少)
            
        Returns:
            是否成功
        """
        current_value = self.get_ability_score(entity, ability_name)
        new_value = current_value + delta
        return self.set_ability_score(entity, ability_name, new_value)
    
    # ==================== DND检定机制 ====================
    
    def ability_check(self, entity: Union[Character, Monster], ability_name: str, dc: int = 10, 
                     advantage: bool = False, disadvantage: bool = False) -> Dict[str, Any]:
        """属性检定 (Ability Check)
        
        投1d20 + 属性调整值,与难度等级(DC)比较
        
        Args:
            entity: 角色或怪物
            ability_name: 检定的属性
            dc: 难度等级 (Difficulty Class)
            advantage: 是否有优势 (投两次取高)
            disadvantage: 是否有劣势 (投两次取低)
            
        Returns:
            检定结果字典
        """
        modifier = self.get_ability_modifier(entity, ability_name)
        
        # 投骰子
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20) if (advantage or disadvantage) else roll1
        
        # 选择结果
        if advantage:
            roll = max(roll1, roll2)
        elif disadvantage:
            roll = min(roll1, roll2)
        else:
            roll = roll1
        
        total = roll + modifier
        success = total >= dc
        
        result = {
            "entity_name": entity.name,
            "ability": ability_name,
            "roll": roll,
            "modifier": modifier,
            "total": total,
            "dc": dc,
            "success": success,
            "critical_success": roll == 20,
            "critical_failure": roll == 1,
            "advantage": advantage,
            "disadvantage": disadvantage
        }
        
        logger.info(f"{entity.name} {ability_name} check: {roll}+{modifier}={total} vs DC{dc} - {'Success' if success else 'Failure'}")
        return result
    
    def saving_throw(self, entity: Union[Character, Monster], save_type: str, dc: int = 10,
                    advantage: bool = False, disadvantage: bool = False) -> Dict[str, Any]:
        """豁免检定 (Saving Throw)
        
        与属性检定类似,但用于抵抗特定效果
        常见豁免类型:
        - Strength: 抵抗物理束缚
        - Dexterity: 闪避范围效果
        - Constitution: 抵抗毒素、疾病
        - Intelligence: 抵抗幻术
        - Wisdom: 抵抗魅惑、恐惧
        - Charisma: 抵抗放逐、占据
        
        Args:
            entity: 角色或怪物
            save_type: 豁免类型 (对应六维属性之一)
            dc: 难度等级
            advantage: 是否有优势
            disadvantage: 是否有劣势
            
        Returns:
            豁免结果字典
        """
        result = self.ability_check(entity, save_type, dc, advantage, disadvantage)
        result["check_type"] = "saving_throw"
        return result
    
    def attack_roll(self, attacker: Union[Character, Monster], target: Union[Character, Monster],
                   attack_type: str = "melee", advantage: bool = False, disadvantage: bool = False) -> Dict[str, Any]:
        """攻击检定 (Attack Roll)
        
        Args:
            attacker: 攻击者
            target: 目标
            attack_type: 攻击类型 ("melee"近战使用力量, "ranged"远程使用敏捷, "spell"法术使用智力)
            advantage: 是否有优势
            disadvantage: 是否有劣势
            
        Returns:
            攻击结果字典
        """
        # 确定使用的属性
        ability_map = {
            "melee": "strength",
            "ranged": "dexterity",
            "spell": "intelligence"
        }
        ability = ability_map.get(attack_type, "strength")
        
        modifier = self.get_ability_modifier(attacker, ability)
        
        # 投骰子
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20) if (advantage or disadvantage) else roll1
        
        if advantage:
            roll = max(roll1, roll2)
        elif disadvantage:
            roll = min(roll1, roll2)
        else:
            roll = roll1
        
        total = roll + modifier
        target_ac = target.stats.ac
        hit = total >= target_ac
        
        result = {
            "attacker_name": attacker.name,
            "target_name": target.name,
            "attack_type": attack_type,
            "ability": ability,
            "roll": roll,
            "modifier": modifier,
            "total": total,
            "target_ac": target_ac,
            "hit": hit,
            "critical_hit": roll == 20,
            "critical_miss": roll == 1,
            "advantage": advantage,
            "disadvantage": disadvantage
        }
        
        logger.info(f"{attacker.name} attacks {target.name}: {roll}+{modifier}={total} vs AC{target_ac} - {'Hit' if hit else 'Miss'}")
        return result
    
    # ==================== 战斗计算 ====================
    
    def calculate_damage(self, attacker: Union[Character, Monster], base_damage: int, 
                        damage_type: str = "physical", attack_type: str = "melee") -> int:
        """计算伤害值
        
        Args:
            attacker: 攻击者
            base_damage: 基础伤害
            damage_type: 伤害类型
            attack_type: 攻击类型
            
        Returns:
            最终伤害值
        """
        # 根据攻击类型添加属性调整值
        ability_map = {
            "melee": "strength",
            "ranged": "dexterity",
            "spell": "intelligence"
        }
        ability = ability_map.get(attack_type, "strength")
        modifier = self.get_ability_modifier(attacker, ability)
        
        # 伤害 = 基础伤害 + 属性调整值 (最少1点)
        total_damage = max(1, base_damage + modifier)
        
        return total_damage
    
    def apply_damage(self, entity: Union[Character, Monster], damage: int) -> Dict[str, Any]:
        """对实体造成伤害
        
        Args:
            entity: 目标实体
            damage: 伤害值
            
        Returns:
            伤害结果
        """
        old_hp = entity.stats.hp
        entity.stats.hp = max(0, entity.stats.hp - damage)
        actual_damage = old_hp - entity.stats.hp
        
        result = {
            "entity_name": entity.name,
            "damage": damage,
            "actual_damage": actual_damage,
            "old_hp": old_hp,
            "new_hp": entity.stats.hp,
            "max_hp": entity.stats.max_hp,
            "is_alive": entity.stats.is_alive(),
            "is_dead": not entity.stats.is_alive()
        }
        
        logger.info(f"{entity.name} took {actual_damage} damage: {old_hp} -> {entity.stats.hp} HP")
        return result
    
    def heal(self, entity: Union[Character, Monster], amount: int) -> Dict[str, Any]:
        """治疗实体
        
        Args:
            entity: 目标实体
            amount: 治疗量
            
        Returns:
            治疗结果
        """
        old_hp = entity.stats.hp
        entity.stats.hp = min(entity.stats.max_hp, entity.stats.hp + amount)
        actual_heal = entity.stats.hp - old_hp
        
        result = {
            "entity_name": entity.name,
            "heal_amount": amount,
            "actual_heal": actual_heal,
            "old_hp": old_hp,
            "new_hp": entity.stats.hp,
            "max_hp": entity.stats.max_hp
        }
        
        logger.info(f"{entity.name} healed {actual_heal} HP: {old_hp} -> {entity.stats.hp} HP")
        return result


# 全局实体管理器实例
entity_manager = EntityManager()

__all__ = ["EntityManager", "entity_manager"]

