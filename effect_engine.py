"""
Labyrinthia AI - 统一效果引擎
Unified effect engine for item and status effects
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from data_models import Character, GameState, Item, StatusEffect, TerrainType
from game_state_modifier import game_state_modifier

logger = logging.getLogger(__name__)


@dataclass
class EffectExecutionResult:
    """统一效果执行结果"""

    success: bool = True
    message: str = ""
    events: List[str] = field(default_factory=list)
    item_consumed: bool = True
    position_change: Optional[Tuple[int, int]] = None


class EffectEngine:
    """统一处理即时效果与持续效果"""

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def apply_item_effects(
        self,
        game_state: GameState,
        item: Item,
        llm_response: Dict[str, Any],
    ) -> EffectExecutionResult:
        result = EffectExecutionResult(
            message=llm_response.get("message", f"使用了{item.name}"),
            events=list(llm_response.get("events", []) or []),
            item_consumed=bool(llm_response.get("item_consumed", True)),
        )

        effects = llm_response.get("effects", {}) or {}

        self._apply_stat_changes(game_state, item, effects.get("stat_changes", {}), result)
        self._apply_ability_changes(game_state, item, effects.get("ability_changes", {}), result)

        teleport = effects.get("teleport")
        if isinstance(teleport, dict) and teleport.get("type"):
            result.position_change = self._resolve_teleport(game_state, teleport)

        self._apply_map_changes(game_state, item, effects.get("map_changes", []), result)
        self._apply_inventory_changes(game_state, item, effects.get("inventory_changes", {}), result)
        self._apply_status_add(game_state.player, effects.get("apply_status_effects", []), result, source_item=item)
        self._apply_status_remove(game_state.player, effects.get("remove_status_effects", []), result)
        self._apply_special_effects(game_state, item, effects.get("special_effects", []), result)

        return result

    def process_turn_effects(self, game_state: GameState, trigger: str = "turn_end") -> List[str]:
        """处理玩家持续效果tick，返回事件文本"""
        player = game_state.player
        events: List[str] = []

        if not player.active_effects:
            return events

        kept: List[StatusEffect] = []
        for effect in player.active_effects:
            if not isinstance(effect, StatusEffect):
                try:
                    effect = StatusEffect.from_dict(effect)
                except Exception:
                    continue

            trigger_mode = effect.triggers.get("on") if isinstance(effect.triggers, dict) else None
            should_tick = trigger_mode in {None, "both", trigger}
            if should_tick:
                tick_events = self._tick_status_effect(game_state, effect)
                events.extend(tick_events)

            if effect.duration_turns > 0:
                effect.duration_turns -= 1

            if effect.duration_turns <= 0:
                events.append(f"状态结束：{effect.name}")
            else:
                kept.append(effect)

        player.active_effects = kept
        return events

    def _apply_stat_changes(
        self,
        game_state: GameState,
        item: Item,
        stat_changes: Dict[str, Any],
        result: EffectExecutionResult,
    ):
        if not isinstance(stat_changes, dict) or not stat_changes:
            return

        player_updates: Dict[str, Any] = {"stats": {}}
        for stat_name, change in stat_changes.items():
            if hasattr(game_state.player.stats, stat_name):
                current_value = getattr(game_state.player.stats, stat_name)
                player_updates["stats"][stat_name] = current_value + self._safe_int(change, 0)

        if not player_updates["stats"]:
            return

        mod_result = game_state_modifier.apply_player_updates(
            game_state,
            player_updates,
            source=f"item_use:{item.name}:stat_changes",
        )
        if not mod_result.success:
            result.success = False
            result.events.append("部分属性效果应用失败")

        if game_state.player.stats.hp <= 0:
            game_state.is_game_over = True
            game_state.game_over_reason = f"使用{item.name}后死亡"
            result.events.append("你因为物品效果死亡")

    def _apply_ability_changes(
        self,
        game_state: GameState,
        item: Item,
        ability_changes: Dict[str, Any],
        result: EffectExecutionResult,
    ):
        if not isinstance(ability_changes, dict) or not ability_changes:
            return

        updates = {"abilities": {}}
        for key, value in ability_changes.items():
            if hasattr(game_state.player.abilities, key):
                old = getattr(game_state.player.abilities, key)
                updates["abilities"][key] = self._safe_int(old, 0) + self._safe_int(value, 0)

        if not updates["abilities"]:
            return

        mod_result = game_state_modifier.apply_player_updates(
            game_state,
            updates,
            source=f"item_use:{item.name}:ability_changes",
        )
        if not mod_result.success:
            result.success = False
            result.events.append("部分能力值效果应用失败")

    def _apply_map_changes(
        self,
        game_state: GameState,
        item: Item,
        map_changes: List[Dict[str, Any]],
        result: EffectExecutionResult,
    ):
        if not isinstance(map_changes, list) or not map_changes:
            return

        map_updates: Dict[str, Any] = {"tiles": {}}
        for change in map_changes:
            if not isinstance(change, dict):
                continue
            x = change.get("x")
            y = change.get("y")
            if x is None or y is None:
                continue
            tile_key = f"{x},{y}"
            tile_update: Dict[str, Any] = {}
            if "terrain" in change:
                tile_update["terrain"] = change["terrain"]
            if "add_items" in change:
                tile_update["items"] = change["add_items"]
            if tile_update:
                map_updates["tiles"][tile_key] = tile_update

        if not map_updates["tiles"]:
            return

        mod_result = game_state_modifier.apply_map_updates(
            game_state,
            map_updates,
            source=f"item_use:{item.name}:map_changes",
        )
        if not mod_result.success:
            result.success = False
            result.events.append("部分地图效果应用失败")

    def _apply_inventory_changes(
        self,
        game_state: GameState,
        item: Item,
        inventory_changes: Dict[str, Any],
        result: EffectExecutionResult,
    ):
        if not isinstance(inventory_changes, dict) or not inventory_changes:
            return

        updates: Dict[str, Any] = {}
        if isinstance(inventory_changes.get("add_items"), list):
            updates["add_items"] = inventory_changes["add_items"]
        if isinstance(inventory_changes.get("remove_items"), list):
            updates["remove_items"] = inventory_changes["remove_items"]

        if not updates:
            return

        mod_result = game_state_modifier.apply_player_updates(
            game_state,
            updates,
            source=f"item_use:{item.name}:inventory_changes",
        )
        if not mod_result.success:
            result.success = False
            result.events.append("部分背包效果应用失败")

    def _apply_status_add(
        self,
        player: Character,
        status_list: List[Dict[str, Any]],
        result: EffectExecutionResult,
        source_item: Optional[Item] = None,
    ):
        if not isinstance(status_list, list):
            return

        for status_data in status_list:
            if not isinstance(status_data, dict):
                continue

            effect = StatusEffect.from_dict(status_data)
            if source_item and not effect.source:
                effect.source = f"item:{source_item.name}"

            merged = self._merge_or_append_status(player, effect)
            result.events.append(
                f"获得状态：{effect.name} ({'叠加' if merged else '新效果'})"
            )

    def _apply_status_remove(
        self,
        player: Character,
        remove_rules: List[Dict[str, Any]],
        result: EffectExecutionResult,
    ):
        if not isinstance(remove_rules, list) or not player.active_effects:
            return

        kept: List[StatusEffect] = []
        removed_names: List[str] = []

        for effect in player.active_effects:
            if not isinstance(effect, StatusEffect):
                effect = StatusEffect.from_dict(effect)

            should_remove = False
            for rule in remove_rules:
                if not isinstance(rule, dict):
                    continue
                name = str(rule.get("name", "")).strip()
                effect_type = str(rule.get("effect_type", "")).strip()
                tag = str(rule.get("tag", "")).strip()

                if name and effect.name == name:
                    should_remove = True
                if effect_type and effect.effect_type == effect_type:
                    should_remove = True
                if tag and tag in effect.tags:
                    should_remove = True

            if should_remove:
                removed_names.append(effect.name)
            else:
                kept.append(effect)

        if removed_names:
            player.active_effects = kept
            result.events.append(f"移除了状态：{', '.join(removed_names)}")

    def _apply_special_effects(
        self,
        game_state: GameState,
        item: Item,
        special_effects: List[Any],
        result: EffectExecutionResult,
    ):
        if not isinstance(special_effects, list):
            return

        for effect in special_effects:
            if isinstance(effect, str):
                code = effect
                payload: Dict[str, Any] = {}
            elif isinstance(effect, dict):
                code = str(effect.get("code", "")).strip()
                payload = effect
            else:
                continue

            if code == "reveal_map":
                for tile in game_state.current_map.tiles.values():
                    tile.is_explored = True
                    tile.is_visible = True
                result.events.append("地图完全显现")
            elif code == "heal_full":
                game_state.player.stats.hp = game_state.player.stats.max_hp
                game_state.player.stats.mp = game_state.player.stats.max_mp
                result.events.append("生命与法力完全恢复")
            elif code == "cleanse_negative":
                before = len(game_state.player.active_effects)
                game_state.player.active_effects = [
                    e for e in game_state.player.active_effects
                    if (e.effect_type if isinstance(e, StatusEffect) else StatusEffect.from_dict(e).effect_type) != "debuff"
                ]
                removed = before - len(game_state.player.active_effects)
                result.events.append(f"净化完成，移除 {removed} 个减益")
            elif code == "recharge_item":
                target_name = str(payload.get("item_name", "")).strip()
                amount = self._safe_int(payload.get("amount", 1), 1)
                if target_name:
                    for inv_item in game_state.player.inventory:
                        if inv_item.name == target_name and inv_item.max_charges > 0:
                            inv_item.charges = min(inv_item.max_charges, inv_item.charges + amount)
                            result.events.append(f"{inv_item.name} 充能 +{amount}")
            elif code == "grant_shield":
                shield = self._safe_int(payload.get("value", 5), 5)
                game_state.player.stats.ac = min(50, game_state.player.stats.ac + shield)
                result.events.append(f"获得临时护甲 +{shield}")
            elif code == "refresh_cooldowns":
                for inv_item in game_state.player.inventory:
                    inv_item.current_cooldown = 0
                result.events.append("所有物品冷却已刷新")
            elif code == "level_up":
                game_state.player.stats.level += 1
                game_state.player.stats.max_hp += 10
                game_state.player.stats.max_mp += 5
                game_state.player.stats.hp = game_state.player.stats.max_hp
                game_state.player.stats.mp = game_state.player.stats.max_mp
                result.events.append("等级提升")
            elif code:
                logger.info("Unknown special effect code: %s", code)

    def _resolve_teleport(self, game_state: GameState, teleport_data: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        tp_type = teleport_data.get("type", "random")
        if tp_type == "specific":
            x = self._safe_int(teleport_data.get("x", game_state.player.position[0]), game_state.player.position[0])
            y = self._safe_int(teleport_data.get("y", game_state.player.position[1]), game_state.player.position[1])
            return (x, y) if self._is_valid_position(game_state, x, y) else None
        if tp_type == "stairs":
            for (x, y), tile in game_state.current_map.tiles.items():
                if tile.terrain in (TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN):
                    return (x, y)
            return None

        empty_positions: List[Tuple[int, int]] = []
        for (x, y), tile in game_state.current_map.tiles.items():
            if self._is_valid_position(game_state, x, y):
                empty_positions.append((x, y))
        if not empty_positions:
            return None

        import random

        return random.choice(empty_positions)

    def _is_valid_position(self, game_state: GameState, x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= game_state.current_map.width or y >= game_state.current_map.height:
            return False
        tile = game_state.current_map.get_tile(x, y)
        if not tile:
            return False
        if tile.terrain in (TerrainType.WALL, TerrainType.LAVA, TerrainType.PIT):
            return False
        return tile.character_id is None

    def _merge_or_append_status(self, player: Character, incoming: StatusEffect) -> bool:
        if player.active_effects is None:
            player.active_effects = []

        normalized: List[StatusEffect] = []
        for effect in player.active_effects:
            if isinstance(effect, StatusEffect):
                normalized.append(effect)
            else:
                normalized.append(StatusEffect.from_dict(effect))
        player.active_effects = normalized

        candidates = [e for e in player.active_effects if e.name == incoming.name]
        if not candidates:
            player.active_effects.append(incoming)
            return False

        target = candidates[-1]
        policy = incoming.stack_policy or target.stack_policy or "replace"

        if policy == "stack":
            target_cap = max(self._safe_int(target.max_stacks, 1), 1)
            incoming_cap = max(self._safe_int(incoming.max_stacks, 1), 1)
            stack_cap = max(target_cap, incoming_cap)
            target.stacks = min(stack_cap, self._safe_int(target.stacks, 1) + max(self._safe_int(incoming.stacks, 1), 1))
            target.duration_turns = max(target.duration_turns, incoming.duration_turns)
            target.potency = self._merge_numeric_dict(target.potency, incoming.potency)
            target.modifiers = self._merge_numeric_dict(target.modifiers, incoming.modifiers)
            target.tick_effects = self._merge_numeric_dict(target.tick_effects, incoming.tick_effects)
        elif policy == "refresh":
            target.duration_turns = max(target.duration_turns, incoming.duration_turns)
            target.stacks = max(target.stacks, incoming.stacks)
        elif policy == "keep_highest":
            if self._potency_score(incoming) > self._potency_score(target):
                idx = player.active_effects.index(target)
                player.active_effects[idx] = incoming
            else:
                target.duration_turns = max(target.duration_turns, incoming.duration_turns)
        else:
            idx = player.active_effects.index(target)
            player.active_effects[idx] = incoming

        return True

    def _tick_status_effect(self, game_state: GameState, effect: StatusEffect) -> List[str]:
        events: List[str] = []
        player = game_state.player
        multiplier = max(1, effect.stacks)

        for stat_name, delta in effect.tick_effects.items():
            if hasattr(player.stats, stat_name):
                cur = getattr(player.stats, stat_name)
                delta_value = self._safe_int(delta, 0) * multiplier
                setattr(player.stats, stat_name, cur + delta_value)
                events.append(f"{effect.name} 影响 {stat_name} {delta_value:+d}")

        hp_over = player.stats.max_hp
        mp_over = player.stats.max_mp
        player.stats.hp = max(0, min(player.stats.hp, hp_over))
        player.stats.mp = max(0, min(player.stats.mp, mp_over))

        if player.stats.hp <= 0:
            game_state.is_game_over = True
            game_state.game_over_reason = f"状态效果[{effect.name}]导致死亡"
            events.append(f"{effect.name} 让你倒下")

        return events

    def _merge_numeric_dict(self, base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base or {})
        for key, val in (incoming or {}).items():
            if isinstance(val, (int, float)) and isinstance(merged.get(key), (int, float)):
                merged[key] = merged[key] + val
            else:
                merged[key] = val
        return merged

    def _potency_score(self, effect: StatusEffect) -> float:
        score = 0.0
        for dataset in (effect.potency, effect.modifiers, effect.tick_effects):
            for value in dataset.values():
                if isinstance(value, (int, float)):
                    score += abs(float(value))
        return score


# 全局实例
effect_engine = EffectEngine()

__all__ = ["EffectExecutionResult", "EffectEngine", "effect_engine"]
