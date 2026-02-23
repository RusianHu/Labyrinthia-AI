"""
Labyrinthia AI - 物品效果处理器（兼容层）
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from data_models import GameState, Item
from effect_engine import effect_engine

logger = logging.getLogger(__name__)


@dataclass
class ItemEffectResult:
    """保持历史接口兼容"""

    success: bool = True
    message: str = ""
    events: List[str] = None
    stat_changes: Dict[str, int] = None
    position_change: Optional[Tuple[int, int]] = None
    map_changes: List[Dict[str, Any]] = None
    item_consumed: bool = True

    def __post_init__(self):
        if self.events is None:
            self.events = []
        if self.stat_changes is None:
            self.stat_changes = {}
        if self.map_changes is None:
            self.map_changes = []


class ItemEffectProcessor:
    """兼容旧调用，内部委托给统一效果引擎"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def process_llm_response(
        self,
        llm_response: Dict[str, Any],
        game_state: GameState,
        item: Item,
    ) -> ItemEffectResult:
        try:
            result = effect_engine.apply_item_effects(game_state, item, llm_response)
            return ItemEffectResult(
                success=result.success,
                message=result.message,
                events=result.events,
                position_change=result.position_change,
                item_consumed=result.item_consumed,
            )
        except Exception as e:
            self.logger.error(f"处理物品效果时出错: {e}")
            return ItemEffectResult(
                success=False,
                message=f"使用{item.name}时发生错误",
                events=[f"物品使用失败: {str(e)}"],
                item_consumed=False,
            )


item_effect_processor = ItemEffectProcessor()

__all__ = ["ItemEffectProcessor", "ItemEffectResult", "item_effect_processor"]
