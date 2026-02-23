"""
Labyrinthia AI - 陷阱叙述服务
Trap narrative service with configurable local/LLM providers
"""

import logging
from typing import Any, Dict, Optional, Protocol

from config import config

logger = logging.getLogger(__name__)


class TrapNarrativeProvider(Protocol):
    """陷阱叙述提供者接口"""

    async def generate(
        self,
        game_state: Any,
        trap_data: Dict[str, Any],
        trigger_result: Dict[str, Any],
        save_attempted: bool,
        save_result: Optional[Dict[str, Any]],
    ) -> str:
        """生成陷阱叙述文本"""


class LocalTrapNarrativeProvider:
    """本地陷阱叙述提供者（稳定、可控、低延迟）"""

    async def generate(
        self,
        game_state: Any,
        trap_data: Dict[str, Any],
        trigger_result: Dict[str, Any],
        save_attempted: bool,
        save_result: Optional[Dict[str, Any]],
    ) -> str:
        trap_name = trap_data.get("trap_name", trigger_result.get("trap_name", "未知陷阱"))
        trap_type = trap_data.get("trap_type", trigger_result.get("trap_type", "damage"))
        raw_damage = trigger_result.get("damage", 0)
        try:
            damage = int(raw_damage) if raw_damage is not None else 0
        except (TypeError, ValueError):
            damage = 0
        damage_type = trap_data.get("damage_type", trigger_result.get("damage_type", "physical"))
        player_died = bool(trigger_result.get("player_died", False))

        save_success = bool(save_result and save_result.get("success"))
        hp_text = self._describe_hp_state(game_state)

        if trap_type == "damage":
            if save_attempted and save_success:
                text = (
                    f"{trap_name}骤然发动，你在千钧一发间侧身避开致命轨迹，"
                    f"仍被余波擦中，受到{damage}点{damage_type}伤害。{hp_text}"
                )
            else:
                text = (
                    f"地面机关猛然咬合，{trap_name}毫无预兆地爆发，"
                    f"你结结实实承受了{damage}点{damage_type}伤害。{hp_text}"
                )
        elif trap_type == "debuff":
            debuff_type = trap_data.get("debuff_type", trigger_result.get("debuff_type", "slow"))
            text = (
                f"{trap_name}释放出诡异力场，{debuff_type}效果迅速缠上你的行动节奏，"
                f"每一步都变得沉重而迟缓。{hp_text}"
            )
        elif trap_type == "teleport":
            if trigger_result.get("teleported") and trigger_result.get("new_position"):
                nx, ny = trigger_result["new_position"]
                text = (
                    f"空间纹路在脚下亮起，{trap_name}将你强行折叠到另一处区域"
                    f"（{nx}, {ny}）。你短暂眩晕后重新站稳。{hp_text}"
                )
            else:
                text = f"{trap_name}尝试扭曲空间，但能量失衡，传送并未成功。{hp_text}"
        elif trap_type == "alarm":
            text = (
                f"{trap_name}发出刺耳共鸣，回声沿着地城墙体层层扩散，"
                "你明显感觉到周围的危险正在被唤醒。"
            )
        elif trap_type == "restraint":
            if trigger_result.get("restrained"):
                text = (
                    f"{trap_name}弹出锁链与钩爪，瞬间缠住你的四肢，"
                    "行动空间被压缩到极限。"
                )
            else:
                text = f"{trap_name}的束缚装置擦身而过，你在最后一刻挣脱了控制。{hp_text}"
        else:
            text = f"你触发了{trap_name}，周围的空气瞬间变得危险而紧绷。{hp_text}"

        if player_died:
            text += " 视野迅速黯淡，意识被冰冷黑暗吞没。"

        return text.strip()

    @staticmethod
    def _describe_hp_state(game_state: Any) -> str:
        try:
            hp = int(game_state.player.stats.hp)
            max_hp = max(1, int(game_state.player.stats.max_hp))
            ratio = hp / max_hp
            if ratio >= 0.75:
                return "你仍保持着较稳定的战斗姿态。"
            if ratio >= 0.4:
                return "疼痛开始累积，但你还能维持阵脚。"
            if ratio > 0:
                return "伤势已经明显影响动作，需要尽快调整节奏。"
            return "你的生命力已经被彻底榨干。"
        except Exception:
            return ""


class LLMTrapNarrativeProvider:
    """LLM陷阱叙述提供者（高表现力）"""

    async def generate(
        self,
        game_state: Any,
        trap_data: Dict[str, Any],
        trigger_result: Dict[str, Any],
        save_attempted: bool,
        save_result: Optional[Dict[str, Any]],
    ) -> str:
        from llm_service import llm_service

        trap_context = {
            "trap_name": trap_data.get("trap_name", trigger_result.get("trap_name", "未知陷阱")),
            "trap_type": trap_data.get("trap_type", trigger_result.get("trap_type", "damage")),
            "damage": trigger_result.get("damage", 0),
            "damage_type": trap_data.get("damage_type", trigger_result.get("damage_type", "physical")),
            "save_attempted": save_attempted,
            "save_success": save_result.get("success", False) if save_result else False,
            "player_name": game_state.player.name,
            "player_hp": game_state.player.stats.hp,
            "player_max_hp": game_state.player.stats.max_hp,
        }
        return await llm_service.generate_trap_narrative(game_state, trap_context)


class TrapNarrativeService:
    """陷阱叙述路由服务：根据配置选择本地或LLM实现"""

    def __init__(self):
        self.local_provider = LocalTrapNarrativeProvider()
        self.llm_provider = LLMTrapNarrativeProvider()

    async def generate_narrative(
        self,
        game_state: Any,
        trap_data: Dict[str, Any],
        trigger_result: Dict[str, Any],
        save_attempted: bool,
        save_result: Optional[Dict[str, Any]],
    ) -> str:
        mode = str(getattr(config.game, "trap_narrative_mode", "local")).lower()
        fallback_to_local = bool(getattr(config.game, "trap_narrative_fallback_to_local", True))

        if mode == "llm":
            try:
                return await self.llm_provider.generate(
                    game_state, trap_data, trigger_result, save_attempted, save_result
                )
            except Exception as e:
                logger.warning(f"LLM trap narrative failed, fallback_to_local={fallback_to_local}: {e}")
                if not fallback_to_local:
                    raise
                return await self.local_provider.generate(
                    game_state, trap_data, trigger_result, save_attempted, save_result
                )

        if mode != "local":
            logger.warning(f"Unknown trap_narrative_mode '{mode}', fallback to local")

        return await self.local_provider.generate(
            game_state, trap_data, trigger_result, save_attempted, save_result
        )


trap_narrative_service = TrapNarrativeService()
