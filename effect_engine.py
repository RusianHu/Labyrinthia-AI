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
    warning_flags: List[str] = field(default_factory=list)
    runtime_debug: List[Dict[str, Any]] = field(default_factory=list)
    replay_logs: List[Dict[str, Any]] = field(default_factory=list)


class EffectEngine:
    """统一处理即时效果与持续效果"""

    CONTROL_ACTION_BLOCKERS: Dict[str, List[str]] = {
        "stun": ["move", "attack", "cast_spell", "use_item", "interact"],
        "silence": ["cast_spell"],
        "disarm": ["attack"],
        "root": ["move"],
    }

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
        effect_scope = str(llm_response.get("effect_scope", "active_use") or "active_use")
        source = str(llm_response.get("source", f"item_use:{getattr(item, 'id', '')}") or f"item_use:{getattr(item, 'id', '')}")

        if "item_consumed" in llm_response:
            consumed = bool(llm_response.get("item_consumed"))
        else:
            if item.is_equippable or item.item_type in {"weapon", "armor"}:
                consumed = False
            elif item.item_type == "consumable":
                consumed = True
            else:
                policy = str((item.properties or {}).get("consumption_policy", "keep_on_use") or "keep_on_use").strip().lower()
                consumed = policy == "consume_on_use"

        result = EffectExecutionResult(
            message=llm_response.get("message", f"使用了{item.name}"),
            events=list(llm_response.get("events", []) or []),
            item_consumed=consumed,
        )
        result.runtime_debug.append({"effect_scope": effect_scope, "source": source})

        effects = llm_response.get("effects", {}) or {}

        self._apply_stat_changes(game_state, item, effects.get("stat_changes", {}), result)
        self._apply_ability_changes(game_state, item, effects.get("ability_changes", {}), result)

        teleport = effects.get("teleport")
        if isinstance(teleport, dict) and teleport.get("type"):
            result.position_change = self._resolve_teleport(game_state, teleport)

        self._apply_map_changes(game_state, item, effects.get("map_changes", []), result)
        self._apply_inventory_changes(game_state, item, effects.get("inventory_changes", {}), result)
        self._apply_status_add(game_state.player, effects.get("apply_status_effects", []), result, source_item=item, source_override=source)
        self._apply_status_remove(game_state.player, effects.get("remove_status_effects", []), result)
        self._apply_special_effects(game_state, item, effects.get("special_effects", []), result)

        self._sync_runtime_logs(game_state, result.replay_logs)
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

            if effect.runtime_type != "one_shot" and effect.duration_turns > 0:
                effect.duration_turns -= 1

            if effect.runtime_type == "one_shot" or effect.duration_turns <= 0:
                events.append(f"状态结束：{effect.name}")
            else:
                kept.append(effect)

        player.active_effects = kept
        self._sync_runtime_logs(game_state, [{"hook": trigger, "events": list(events)}])
        return events

    def process_effect_hooks(
        self,
        game_state: GameState,
        *,
        hook: str,
        actor: Optional[Character] = None,
        target: Optional[Character] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """运行时钩子处理（on_attack/on_hit/on_damage_taken/on_kill 等）"""
        context = context or {}
        events: List[str] = []
        runtime_logs: List[Dict[str, Any]] = []

        entities: List[Character] = []
        if actor is not None:
            entities.append(actor)
        if target is not None and target is not actor:
            entities.append(target)

        for entity in entities:
            normalized = self._normalize_effect_list(entity)
            for effect in normalized:
                trigger_mode = effect.triggers.get("on") if isinstance(effect.triggers, dict) else None
                if trigger_mode not in {hook, "both"}:
                    continue
                payload = effect.hook_payloads.get(hook, {}) if isinstance(effect.hook_payloads, dict) else {}
                if isinstance(payload.get("stat_changes"), dict):
                    for stat_name, delta in payload.get("stat_changes", {}).items():
                        if hasattr(entity.stats, stat_name):
                            before = int(getattr(entity.stats, stat_name) or 0)
                            after = before + self._safe_int(delta, 0) * max(1, int(effect.stacks or 1))
                            setattr(entity.stats, stat_name, after)
                            events.append(f"{effect.name} 触发 {hook}: {stat_name} {after - before:+d}")
                if isinstance(payload.get("events"), list):
                    events.extend([str(v) for v in payload.get("events", [])])
                runtime_logs.append(
                    {
                        "hook": hook,
                        "effect": effect.name,
                        "entity": getattr(entity, "id", ""),
                        "trace_id": str(context.get("trace_id", "") or ""),
                    }
                )

            entity.active_effects = normalized
            self._clamp_primary_stats(entity)

        self._sync_runtime_logs(game_state, runtime_logs)
        return {
            "events": events,
            "runtime_logs": runtime_logs,
        }

    def get_action_availability(self, player: Character) -> Dict[str, Any]:
        """控制类状态导致的行动限制"""
        blocked: Dict[str, List[str]] = {}
        for effect in self._normalize_effect_list(player):
            for flag in (effect.control_flags or []):
                for action in self.CONTROL_ACTION_BLOCKERS.get(str(flag), []):
                    blocked.setdefault(action, []).append(effect.name)
        return {
            "blocked_actions": blocked,
            "can_move": "move" not in blocked,
            "can_attack": "attack" not in blocked,
            "can_cast_spell": "cast_spell" not in blocked,
            "can_use_item": "use_item" not in blocked,
        }

    def build_status_debug_view(self, player: Character) -> List[Dict[str, Any]]:
        """状态调试视图：来源、剩余回合、叠层、即时贡献"""
        view: List[Dict[str, Any]] = []
        for effect in self._normalize_effect_list(player):
            view.append(
                {
                    "id": effect.id,
                    "name": effect.name,
                    "source": effect.source,
                    "remaining_turns": int(effect.duration_turns),
                    "stacks": int(effect.stacks),
                    "control_flags": list(effect.control_flags),
                    "modifiers": dict(effect.modifiers),
                    "tick_effects": dict(effect.tick_effects),
                    "runtime_type": effect.runtime_type,
                }
            )
        return view

    def detect_status_conflicts(self, player: Character) -> List[Dict[str, Any]]:
        """检测互斥状态冲突"""
        conflicts: List[Dict[str, Any]] = []
        grouped: Dict[str, List[str]] = {}
        for effect in self._normalize_effect_list(player):
            key = str(effect.group_mutex or "").strip()
            if not key:
                continue
            grouped.setdefault(key, []).append(effect.name)
        for key, names in grouped.items():
            if len(names) > 1:
                conflicts.append({"group_mutex": key, "effects": names})
        return conflicts

    def dispel_effects(self, player: Character, *, dispel_type: str = "", max_remove: int = 999) -> List[str]:
        """驱散状态，按优先级从高到低"""
        normalized = self._normalize_effect_list(player)
        removable = []
        for effect in normalized:
            if not dispel_type or effect.dispel_type in {dispel_type, "all"}:
                removable.append(effect)
        removable.sort(key=lambda e: int(e.dispel_priority or 0), reverse=True)

        removed_ids = {e.id for e in removable[: max(0, int(max_remove))]}
        removed_names: List[str] = []
        kept: List[StatusEffect] = []
        for effect in normalized:
            if effect.id in removed_ids:
                removed_names.append(effect.name)
            else:
                kept.append(effect)
        player.active_effects = kept
        return removed_names

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
        source_override: str = "",
    ):
        if not isinstance(status_list, list):
            return

        for status_data in status_list:
            if not isinstance(status_data, dict):
                continue

            effect = StatusEffect.from_dict(status_data)
            if source_override and not effect.source:
                effect.source = source_override
            elif source_item and not effect.source:
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
                game_state.player.stats.shield = max(0, int(getattr(game_state.player.stats, "shield", 0) or 0) + shield)
                result.events.append(f"获得护盾 +{shield}")
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

        incoming.metadata = incoming.metadata or {}
        if incoming.snapshot_mode == "snapshot" and "snapshot_stats" not in incoming.metadata:
            incoming.metadata["snapshot_stats"] = {
                "hp": int(getattr(player.stats, "hp", 0) or 0),
                "max_hp": int(getattr(player.stats, "max_hp", 0) or 0),
                "ac": int(getattr(player.stats, "ac", 10) or 10),
            }

        # 互斥组：同组只保留一个（默认强覆盖弱）
        mutex_group = str(incoming.group_mutex or "").strip()
        if mutex_group:
            same_mutex = [e for e in player.active_effects if str(e.group_mutex or "").strip() == mutex_group]
            if same_mutex:
                strongest = max(same_mutex + [incoming], key=self._potency_score)
                player.active_effects = [e for e in player.active_effects if str(e.group_mutex or "").strip() != mutex_group]
                player.active_effects.append(strongest)
                return strongest is not incoming

        # 覆盖组：同组强覆盖弱
        override_group = str(incoming.group_override or "").strip()
        if override_group:
            same_override = [e for e in player.active_effects if str(e.group_override or "").strip() == override_group]
            if same_override:
                strongest = max(same_override + [incoming], key=self._potency_score)
                player.active_effects = [e for e in player.active_effects if str(e.group_override or "").strip() != override_group]
                player.active_effects.append(strongest)
                return strongest is not incoming

        # 独立叠层组：按 group_stack 聚合，不要求同名
        stack_group = str(incoming.group_stack or "").strip()
        if stack_group:
            candidates = [e for e in player.active_effects if str(e.group_stack or "").strip() == stack_group]
        else:
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

                if str(stat_name) == "hp" and delta_value < 0:
                    damage_type = str(effect.metadata.get("damage_type", "physical") if isinstance(effect.metadata, dict) else "physical")
                    immune = set(str(v) for v in (getattr(player, "immunities", []) or []))
                    alias = "physical" if damage_type in {"physical_slash", "physical_pierce", "physical_blunt"} else damage_type
                    if damage_type in immune or alias in immune:
                        delta_value = 0
                    else:
                        resistance = 0.0
                        vulnerability = 0.0
                        raw_res = getattr(player, "resistances", {}) or {}
                        raw_vul = getattr(player, "vulnerabilities", {}) or {}
                        try:
                            resistance = float(raw_res.get(damage_type, raw_res.get(alias, 0.0)) or 0.0)
                        except (TypeError, ValueError):
                            resistance = 0.0
                        try:
                            vulnerability = float(raw_vul.get(damage_type, raw_vul.get(alias, 0.0)) or 0.0)
                        except (TypeError, ValueError):
                            vulnerability = 0.0
                        effective = int(abs(delta_value) * max(0.0, 1.0 - max(0.0, resistance)))
                        effective = int(effective * max(1.0, 1.0 + vulnerability))
                        delta_value = -max(0, effective)

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

    def _normalize_effect_list(self, player: Character) -> List[StatusEffect]:
        if player.active_effects is None:
            player.active_effects = []
        normalized: List[StatusEffect] = []
        for effect in player.active_effects:
            if isinstance(effect, StatusEffect):
                normalized.append(effect)
            elif isinstance(effect, dict):
                try:
                    normalized.append(StatusEffect.from_dict(effect))
                except Exception:
                    continue
        player.active_effects = normalized
        return normalized

    def _clamp_primary_stats(self, entity: Character):
        entity.stats.hp = max(0, min(int(entity.stats.hp), int(entity.stats.max_hp)))
        entity.stats.mp = max(0, min(int(entity.stats.mp), int(entity.stats.max_mp)))
        entity.stats.ac = max(int(getattr(entity.stats, "ac_min", 1) or 1), min(int(getattr(entity.stats, "ac_max", 50) or 50), int(entity.stats.ac)))

    def _sync_runtime_logs(self, game_state: GameState, logs: List[Dict[str, Any]]):
        if not isinstance(logs, list) or not logs:
            return
        if not isinstance(game_state.pending_effects, list):
            game_state.pending_effects = []
        game_state.pending_effects.append({"effect_runtime_logs": logs})
        if not isinstance(game_state.combat_snapshot, dict):
            game_state.combat_snapshot = {}
        replay_logs = game_state.combat_snapshot.get("effect_replay_logs", [])
        if not isinstance(replay_logs, list):
            replay_logs = []
        replay_logs.extend(logs)
        game_state.combat_snapshot["effect_replay_logs"] = replay_logs[-200:]


    def apply_equipment_passive_effects(self, player: Character, item: Item, *, slot: str = "") -> List[str]:
        events: List[str] = []
        source = f"equip:{slot}:{getattr(item, 'id', '')}"
        for payload in getattr(item, "equip_passive_effects", []) or []:
            if not isinstance(payload, dict):
                continue
            status_payload = payload.get("status_effect")
            if isinstance(status_payload, dict):
                effect = StatusEffect.from_dict(status_payload)
                if not effect.source:
                    effect.source = source
                merged = self._merge_or_append_status(player, effect)
                events.append(f"装备效果：{effect.name} ({'叠加' if merged else '新效果'})")
        return events

    def revert_effects_by_source(self, player: Character, source: str) -> int:
        if not player.active_effects:
            return 0
        normalized = self._normalize_effect_list(player)
        kept: List[StatusEffect] = []
        removed = 0
        for effect in normalized:
            if str(getattr(effect, "source", "") or "") == str(source or ""):
                removed += 1
                continue
            kept.append(effect)
        player.active_effects = kept
        return removed

# 全局实例
effect_engine = EffectEngine()

__all__ = ["EffectExecutionResult", "EffectEngine", "effect_engine"]
