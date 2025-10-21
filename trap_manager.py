"""
Labyrinthia AI - 陷阱管理器
Trap Manager for DND 5E trap mechanics
"""

import logging
import random
from typing import Dict, Any, Optional
from data_models import Character, Monster, MapTile, GameState, TerrainType
from entity_manager import EntityManager
from trap_schema import trap_validator

logger = logging.getLogger(__name__)


class TrapManager:
    """
    陷阱管理器 - 实现DND 5E陷阱机制
    
    核心功能：
    1. 被动侦测陷阱（基于被动感知值）
    2. 主动侦测陷阱（感知检定）
    3. 规避陷阱（敏捷豁免）
    4. 解除陷阱（灵巧检定+工具熟练）
    5. 触发陷阱（应用效果）
    """
    
    def __init__(self, entity_manager: EntityManager):
        """初始化陷阱管理器
        
        Args:
            entity_manager: 实体管理器实例
        """
        self.entity_manager = entity_manager
    
    # ==================== 侦测机制 ====================
    
    def passive_detect_trap(self, player: Character, trap_dc: int) -> bool:
        """被动侦测陷阱
        
        使用玩家的被动感知值自动检测陷阱，无需主动行动。
        
        Args:
            player: 玩家角色
            trap_dc: 陷阱的侦测难度等级
            
        Returns:
            True如果被动感知值 >= DC，False否则
        """
        passive_perception = player.get_passive_perception()
        detected = passive_perception >= trap_dc
        
        logger.info(
            f"Passive trap detection: PP={passive_perception} vs DC={trap_dc} - "
            f"{'Detected' if detected else 'Not detected'}"
        )
        
        return detected
    
    def active_detect_trap(self, player: Character, trap_dc: int, 
                          advantage: bool = False) -> Dict[str, Any]:
        """主动侦测陷阱（感知检定）
        
        玩家选择"搜索陷阱"行动时使用。
        
        Args:
            player: 玩家角色
            trap_dc: 陷阱的侦测难度等级
            advantage: 是否有优势（如仔细搜索）
            
        Returns:
            检定结果字典，包含success、roll、total等信息
        """
        result = self.entity_manager.ability_check(
            player, "wisdom", trap_dc, advantage=advantage
        )
        
        # 添加技能熟练加值（如果有perception技能）
        if "perception" in player.skill_proficiencies:
            result["proficiency_bonus"] = player.proficiency_bonus
            result["total"] += player.proficiency_bonus
            result["success"] = result["total"] >= trap_dc
            logger.info(f"Added perception proficiency bonus: +{player.proficiency_bonus}")
        
        logger.info(
            f"Active trap detection: {result['roll']}+{result['modifier']} = {result['total']} "
            f"vs DC={trap_dc} - {'Success' if result['success'] else 'Failure'}"
        )
        
        return result
    
    # ==================== 规避机制 ====================
    
    def attempt_avoid(self, player: Character, trap_dc: int) -> Dict[str, Any]:
        """尝试规避陷阱（敏捷豁免）
        
        发现陷阱后尝试避免触发，或触发后减少伤害。
        
        Args:
            player: 玩家角色
            trap_dc: 陷阱的豁免难度等级
            
        Returns:
            豁免结果字典
        """
        result = self.entity_manager.saving_throw(
            player, "dexterity", trap_dc
        )
        
        logger.info(
            f"Trap avoidance (DEX save): {result['roll']}+{result['modifier']} = {result['total']} "
            f"vs DC={trap_dc} - {'Success' if result['success'] else 'Failure'}"
        )
        
        return result
    
    # ==================== 解除机制 ====================
    
    def attempt_disarm(self, player: Character, trap_dc: int) -> Dict[str, Any]:
        """尝试解除陷阱（灵巧检定+工具熟练）
        
        使用盗贼工具尝试安全解除陷阱。
        
        Args:
            player: 玩家角色
            trap_dc: 陷阱的解除难度等级
            
        Returns:
            检定结果字典
        """
        has_tools = "thieves_tools" in player.tool_proficiencies
        
        # 无工具时有劣势
        result = self.entity_manager.ability_check(
            player, "dexterity", trap_dc, 
            disadvantage=not has_tools
        )
        
        # 有工具熟练时添加熟练加值
        if has_tools:
            result["proficiency_bonus"] = player.proficiency_bonus
            result["total"] += player.proficiency_bonus
            result["success"] = result["total"] >= trap_dc
            logger.info(f"Added thieves' tools proficiency bonus: +{player.proficiency_bonus}")
        
        logger.info(
            f"Trap disarm attempt: {result['roll']}+{result['modifier']} = {result['total']} "
            f"vs DC={trap_dc} - {'Success' if result['success'] else 'Failure'} "
            f"(has_tools={has_tools})"
        )
        
        return result
    
    # ==================== 触发机制 ====================
    
    def trigger_trap(self, game_state: GameState, tile: MapTile,
                    save_result: Optional[Dict] = None) -> Dict[str, Any]:
        """触发陷阱效果

        Args:
            game_state: 游戏状态
            tile: 陷阱所在的瓦片
            save_result: 豁免检定结果（如果有）

        Returns:
            触发结果字典，包含description、damage、state_updates等
        """
        # 【P0修复】获取并验证陷阱数据
        raw_trap_data = tile.get_trap_data()
        trap_data = trap_validator.validate_and_normalize(raw_trap_data)
        trap_type = trap_data.get("trap_type", "damage")
        player = game_state.player
        
        result = {
            "trap_type": trap_type,
            "description": "",
            "damage": 0,
            "state_updates": {},
            "player_died": False
        }
        
        # 标记陷阱已触发
        tile.event_triggered = True
        if tile.has_event and tile.event_type == 'trap':
            tile.event_data["is_triggered"] = True
        
        # 根据陷阱类型处理效果
        if trap_type == "damage":
            result.update(self._trigger_damage_trap(player, trap_data, save_result))
        elif trap_type == "debuff":
            result.update(self._trigger_debuff_trap(player, trap_data, save_result))
        elif trap_type == "teleport":
            result.update(self._trigger_teleport_trap(game_state, trap_data))
        elif trap_type == "alarm":
            result.update(self._trigger_alarm_trap(game_state, trap_data))
        elif trap_type == "restraint":
            result.update(self._trigger_restraint_trap(player, trap_data, save_result))
        else:
            result["description"] = "触发了一个神秘的陷阱！"
        
        # 检查玩家是否死亡
        if player.stats.hp <= 0:
            game_state.is_game_over = True
            game_state.game_over_reason = "被陷阱杀死"
            result["player_died"] = True
            result["description"] += " 你被陷阱杀死了！"
        
        logger.info(f"Trap triggered: {trap_type} - {result['description']}")
        
        return result
    
    def _trigger_damage_trap(self, player: Character, trap_data: Dict[str, Any], 
                            save_result: Optional[Dict] = None) -> Dict[str, Any]:
        """触发伤害型陷阱"""
        base_damage = trap_data.get("damage", 15)
        damage_type = trap_data.get("damage_type", "physical")
        save_half = trap_data.get("save_half_damage", True)
        
        # 如果有豁免检定且成功，可能减半伤害
        if save_result and save_result.get("success") and save_half:
            damage = base_damage // 2
            description = f"触发了陷阱！但你灵巧地避开了部分伤害，受到了 {damage} 点{damage_type}伤害（减半）"
        else:
            damage = base_damage
            description = f"触发了陷阱！受到了 {damage} 点{damage_type}伤害"
        
        player.stats.hp -= damage
        
        return {
            "damage": damage,
            "damage_type": damage_type,
            "description": description
        }
    
    def _trigger_debuff_trap(self, player: Character, trap_data: Dict[str, Any],
                            save_result: Optional[Dict] = None) -> Dict[str, Any]:
        """触发减益型陷阱"""
        debuff_type = trap_data.get("debuff_type", "slow")
        
        # TODO: 实现减益效果系统
        description = f"触发了{debuff_type}陷阱！移动变得困难！"
        
        return {
            "debuff_type": debuff_type,
            "description": description
        }
    
    def _trigger_teleport_trap(self, game_state: GameState, 
                              trap_data: Dict[str, Any]) -> Dict[str, Any]:
        """触发传送型陷阱"""
        # 随机传送到地图上的空地
        from content_generator import content_generator
        
        spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
        if spawn_positions:
            old_pos = game_state.player.position
            new_pos = spawn_positions[0]
            
            # 更新玩家位置
            old_tile = game_state.current_map.get_tile(*old_pos)
            if old_tile:
                old_tile.character_id = None
            
            game_state.player.position = new_pos
            new_tile = game_state.current_map.get_tile(*new_pos)
            if new_tile:
                new_tile.character_id = game_state.player.id
                new_tile.is_explored = True
                new_tile.is_visible = True
            
            description = f"触发了传送陷阱！被传送到了 ({new_pos[0]}, {new_pos[1]})！"
            
            return {
                "teleported": True,
                "new_position": new_pos,
                "description": description
            }
        else:
            return {
                "teleported": False,
                "description": "触发了传送陷阱，但传送失败了！"
            }
    
    def _trigger_alarm_trap(self, game_state: GameState, 
                           trap_data: Dict[str, Any]) -> Dict[str, Any]:
        """触发警报型陷阱"""
        # TODO: 实现警报效果（如召唤怪物、提高警戒等级）
        description = "触发了警报陷阱！刺耳的警报声响彻整个地下城！"
        
        return {
            "alarm_triggered": True,
            "description": description
        }
    
    def _trigger_restraint_trap(self, player: Character, trap_data: Dict[str, Any],
                               save_result: Optional[Dict] = None) -> Dict[str, Any]:
        """触发束缚型陷阱"""
        # TODO: 实现束缚效果系统
        if save_result and save_result.get("success"):
            description = "触发了束缚陷阱！但你成功挣脱了！"
            restrained = False
        else:
            description = "触发了束缚陷阱！你被困住了！"
            restrained = True
        
        return {
            "restrained": restrained,
            "description": description
        }


# 全局实例
trap_manager: Optional[TrapManager] = None


def initialize_trap_manager(entity_manager: EntityManager):
    """初始化全局陷阱管理器实例
    
    Args:
        entity_manager: 实体管理器实例
    """
    global trap_manager
    trap_manager = TrapManager(entity_manager)
    logger.info("TrapManager initialized")


def get_trap_manager() -> TrapManager:
    """获取全局陷阱管理器实例
    
    Returns:
        TrapManager实例
        
    Raises:
        RuntimeError: 如果未初始化
    """
    if trap_manager is None:
        raise RuntimeError("TrapManager not initialized. Call initialize_trap_manager() first.")
    return trap_manager

