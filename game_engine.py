"""
Labyrinthia AI - 游戏引擎
Game engine for the Labyrinthia AI game
"""

import asyncio
import random
import logging
import copy
import json
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from collections import Counter

from config import config
from data_models import (
    GameState, Character, Monster, GameMap, Quest, Item, MapTile,
    TerrainType, CharacterClass, Stats, Ability, EventChoiceContext, EventChoice
)
from content_generator import content_generator
from llm_service import llm_service
from data_manager import data_manager
from progress_manager import progress_manager, ProgressEventType, ProgressContext
from item_effect_processor import item_effect_processor
from effect_engine import effect_engine
from combat_core import combat_core_evaluator
from llm_interaction_manager import (
    llm_interaction_manager, InteractionType, InteractionContext
)
from prompt_manager import prompt_manager
from event_choice_system import event_choice_system, ChoiceEventType
from async_task_manager import async_task_manager, TaskType, async_performance_monitor
from game_state_lock_manager import game_state_lock_manager
from game_state_modifier import game_state_modifier


logger = logging.getLogger(__name__)


class GameEngine:
    """游戏引擎类"""

    _EQUIPMENT_AFFIX_DEFAULT_BOUNDS: Dict[str, Tuple[float, float]] = {
        "hit_bonus": (-20.0, 20.0),
        "critical_bonus": (0.0, 1.0),
        "damage_bonus": (-100.0, 300.0),
        "ac_bonus": (-10.0, 20.0),
        "shield_bonus": (0.0, 200.0),
        "resistance_bonus": (0.0, 0.8),
        "vulnerability_reduction": (0.0, 0.8),
        "heal_on_kill": (0.0, 100.0),
        "regen_per_turn": (0.0, 50.0),
    }
    _COMBAT_OVERRIDE_COMPONENT_LIMIT: int = 6
    _COMBAT_OVERRIDE_COMPONENT_MAX_VALUE: int = 5000

    def __init__(self):
        # 使用 (user_id, game_id) 作为键，实现用户级别的游戏状态隔离
        self.active_games: Dict[Tuple[str, str], GameState] = {}
        self.auto_save_tasks: Dict[Tuple[str, str], asyncio.Task] = {}
        self.last_access_time: Dict[Tuple[str, str], float] = {}  # 记录最后访问时间
        self.cleanup_task_started = False  # 标记清理任务是否已启动
        # 幂等结果缓存：key=(user_id, game_id) -> {"{action}:{idempotency_key}": payload}
        # payload 结构：{"result": Dict[str, Any], "fingerprint": str, "created_at": float}
        self.action_idempotency_cache: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self.idempotency_cache_ttl_seconds: int = 120
        self.idempotency_cache_max_entries: int = 256
        # 丢弃撤销缓存：key=(user_id, game_id) -> {undo_token: {item, position, expires_turn}}
        self.drop_undo_cache: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self._map_release_hash_seed = str(getattr(config.game, "map_generation_canary_seed", "labyrinthia-map-canary") or "labyrinthia-map-canary")

    def _make_action_result(
        self,
        success: bool,
        message: str,
        *,
        events: Optional[List[str]] = None,
        error_code: Optional[str] = None,
        retryable: bool = False,
        reason: Optional[str] = None,
        impact_summary: Optional[Dict[str, Any]] = None,
        action_trace_id: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        normalized_events = events if isinstance(events, list) else ([] if events is None else [str(events)])
        result = {
            "success": success,
            "message": message,
            "reason": reason or ("ok" if success else (error_code or "ACTION_FAILED")),
            "events": normalized_events,
            "error_code": error_code,
            "retryable": retryable,
            "impact_summary": impact_summary or {},
            "action_trace_id": action_trace_id,
        }
        for key, value in extra.items():
            result[key] = value
        return result

    def _get_idempotency_cache(self, game_key: Tuple[str, str]) -> Dict[str, Dict[str, Any]]:
        if game_key not in self.action_idempotency_cache:
            self.action_idempotency_cache[game_key] = {}
        return self.action_idempotency_cache[game_key]

    def _make_idempotency_fingerprint(self, action: str, parameters: Dict[str, Any]) -> str:
        safe_params: Dict[str, Any] = {}
        if action == "attack":
            safe_params["target_id"] = str(parameters.get("target_id", "") or "")
        elif action in {"use_item", "drop_item"}:
            safe_params["item_id"] = str(parameters.get("item_id", "") or "")
            safe_params["force"] = bool(parameters.get("force", False))
        elif action == "cast_spell":
            safe_params["spell_id"] = str(parameters.get("spell_id", "") or "")
            safe_params["target_id"] = str(parameters.get("target_id", "") or "")

        return json.dumps(safe_params, sort_keys=True, ensure_ascii=False)

    def _prune_idempotency_cache(self, game_key: Tuple[str, str]):
        cache = self._get_idempotency_cache(game_key)
        if not cache:
            return

        now_ts = datetime.utcnow().timestamp()
        ttl = max(1, int(self.idempotency_cache_ttl_seconds))

        expired_keys: List[str] = []
        for key, payload in cache.items():
            if not isinstance(payload, dict):
                continue
            created_at = payload.get("created_at")
            if isinstance(created_at, (int, float)) and (now_ts - float(created_at)) > ttl:
                expired_keys.append(key)

        for key in expired_keys:
            cache.pop(key, None)

        max_entries = max(1, int(self.idempotency_cache_max_entries))
        if len(cache) > max_entries:
            sortable: List[Tuple[str, float]] = []
            for key, payload in cache.items():
                created_at = 0.0
                if isinstance(payload, dict):
                    created_val = payload.get("created_at")
                    if isinstance(created_val, (int, float)):
                        created_at = float(created_val)
                sortable.append((key, created_at))

            sortable.sort(key=lambda item: item[1])
            trim_count = len(cache) - max_entries
            for key, _ in sortable[:trim_count]:
                cache.pop(key, None)

    def _get_cached_action_result(
        self,
        game_key: Tuple[str, str],
        action: str,
        parameters: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        idempotency_key = str(parameters.get("idempotency_key", "") or "").strip()
        if not idempotency_key:
            return None

        self._prune_idempotency_cache(game_key)

        cache_key = f"{action}:{idempotency_key}"
        cached = self._get_idempotency_cache(game_key).get(cache_key)
        if not cached:
            return None

        cached_result: Optional[Dict[str, Any]] = None
        cached_fingerprint = ""
        if isinstance(cached, dict) and "result" in cached:
            maybe_result = cached.get("result")
            if isinstance(maybe_result, dict):
                cached_result = maybe_result
            cached_fingerprint = str(cached.get("fingerprint", "") or "")
        elif isinstance(cached, dict):
            # 兼容旧结构
            cached_result = cached

        if cached_result is None:
            return None

        request_fingerprint = self._make_idempotency_fingerprint(action, parameters)
        if cached_fingerprint and cached_fingerprint != request_fingerprint:
            logger.warning(
                "Idempotency key fingerprint mismatch for %s, action=%s, key=%s",
                game_key,
                action,
                idempotency_key,
            )
            return None

        replay = copy.deepcopy(cached_result)
        replay["idempotent_replay"] = True
        if "events" not in replay or not isinstance(replay["events"], list):
            replay["events"] = []
        replay["events"] = [f"幂等重放：复用动作结果（{action}）"] + replay["events"]
        logger.info(f"Idempotent replay hit for {game_key}, action={action}")
        return replay

    def _store_action_result(
        self,
        game_key: Tuple[str, str],
        action: str,
        parameters: Dict[str, Any],
        result: Dict[str, Any],
    ):
        idempotency_key = str(parameters.get("idempotency_key", "") or "").strip()
        if not idempotency_key:
            return
        cache_key = f"{action}:{idempotency_key}"
        cached_result = copy.deepcopy(result)
        cached_result.pop("idempotent_replay", None)
        self._get_idempotency_cache(game_key)[cache_key] = {
            "result": cached_result,
            "fingerprint": self._make_idempotency_fingerprint(action, parameters),
            "created_at": datetime.utcnow().timestamp(),
        }
        self._prune_idempotency_cache(game_key)

    def _get_drop_undo_cache(self, game_key: Tuple[str, str]) -> Dict[str, Dict[str, Any]]:
        if game_key not in self.drop_undo_cache:
            self.drop_undo_cache[game_key] = {}
        return self.drop_undo_cache[game_key]

    def _cleanup_drop_undo_entries(self, game_key: Tuple[str, str], current_turn: int):
        cache = self._get_drop_undo_cache(game_key)
        expired = [
            token for token, payload in cache.items()
            if int(payload.get("expires_turn", -1)) < int(current_turn)
        ]
        for token in expired:
            cache.pop(token, None)

    def _ensure_combat_defaults(self, game_state: GameState):
        if not isinstance(game_state.combat_rules, dict) or not game_state.combat_rules:
            game_state.combat_rules = {
                "damage_order": ["hit", "shield", "temporary_hp", "resistance", "vulnerability", "hp"],
                "critical_multiplier": 1.5,
                "minimum_damage": 1,
                "rule_version": int(getattr(game_state, "combat_rule_version", 1) or 1),
                "damage_types": [
                    "physical",
                    "physical_slash",
                    "physical_pierce",
                    "physical_blunt",
                    "fire",
                    "cold",
                    "lightning",
                    "acid",
                    "poison",
                    "necrotic",
                    "radiant",
                    "psychic",
                    "force",
                    "thunder",
                    "arcane",
                    "true",
                ],
                "mitigation": {
                    "allow_multi_damage_components": True,
                    "allow_penetration": True,
                    "allow_true_damage": True,
                    "allow_shield_penetration": True,
                    "allow_temporary_hp_penetration": True,
                    "resistance_clamp_min": 0.0,
                    "resistance_clamp_max": 0.95,
                    "vulnerability_min_multiplier": 1.0,
                    "vulnerability_max_multiplier": 3.0,
                },
                "release_strategy": {
                    "stage": "debug",
                    "canary_percent": 0,
                    "auto_degrade_enabled": True,
                    "degrade_diff_threshold": int(getattr(config.game, "combat_diff_threshold", 5) or 5),
                    "degrade_latency_p95_ms": 500,
                    "degrade_error_rate": 0.05,
                },
                "rollback": {
                    "enabled": True,
                    "last_stable_rule_version": max(1, int(getattr(game_state, "combat_rule_version", 1) or 1)),
                    "fallback_authority_mode": "local",
                    "last_reason": "",
                    "last_trace_id": "",
                },
                "ac_policy": {
                    "mode": "components",
                    "legacy_single_value_compatible": True,
                    "semantic_boundary": "hit_threshold_only",
                },
                "equipment_affix_policy": {
                    "allowed_keys": [
                        "hit_bonus",
                        "critical_bonus",
                        "damage_bonus",
                        "ac_bonus",
                        "shield_bonus",
                        "resistance_bonus",
                        "vulnerability_reduction",
                        "heal_on_kill",
                        "regen_per_turn",
                    ],
                    "value_bounds": {
                        "hit_bonus": [-20, 20],
                        "critical_bonus": [0, 1],
                        "damage_bonus": [-100, 300],
                        "ac_bonus": [-10, 20],
                        "shield_bonus": [0, 200],
                        "resistance_bonus": [0, 0.8],
                        "vulnerability_reduction": [0, 0.8],
                        "heal_on_kill": [0, 100],
                        "regen_per_turn": [0, 50],
                    },
                },
            }

        if not isinstance(game_state.combat_snapshot, dict):
            game_state.combat_snapshot = {}

        if not isinstance(game_state.combat_snapshot.get("latency_metrics", {}), dict):
            game_state.combat_snapshot["latency_metrics"] = {
                "samples_ms": [],
                "p50_ms": 0,
                "p95_ms": 0,
                "max_samples": 200,
            }

        ac_policy = game_state.combat_rules.get("ac_policy")
        if not isinstance(ac_policy, dict):
            game_state.combat_rules["ac_policy"] = {
                "mode": "components",
                "legacy_single_value_compatible": True,
                "semantic_boundary": "hit_threshold_only",
            }
        else:
            ac_policy.setdefault("mode", "components")
            ac_policy.setdefault("legacy_single_value_compatible", True)
            ac_policy.setdefault("semantic_boundary", "hit_threshold_only")

        combat_tests = game_state.combat_snapshot.get("combat_tests")
        if not isinstance(combat_tests, dict):
            game_state.combat_snapshot["combat_tests"] = {
                "ac_baseline": [],
                "ac_hit_curve": [],
            }

        telemetry = game_state.combat_snapshot.get("telemetry")
        if not isinstance(telemetry, dict):
            game_state.combat_snapshot["telemetry"] = {
                "wins": 0,
                "losses": 0,
                "total_turns": 0,
                "completed_combats": 0,
                "combat_attempts": 0,
                "burst_peak": 0,
                "death_sources": {},
                "win_rate": 0.0,
                "avg_turns": 0.0,
                "errors": 0,
            }

        mitigation = game_state.combat_rules.get("mitigation")
        if not isinstance(mitigation, dict):
            game_state.combat_rules["mitigation"] = {
                "allow_multi_damage_components": True,
                "allow_penetration": True,
                "allow_true_damage": True,
                "allow_shield_penetration": True,
                "allow_temporary_hp_penetration": True,
                "resistance_clamp_min": 0.0,
                "resistance_clamp_max": 0.95,
                "vulnerability_min_multiplier": 1.0,
                "vulnerability_max_multiplier": 3.0,
            }
        else:
            mitigation.setdefault("allow_multi_damage_components", True)
            mitigation.setdefault("allow_penetration", True)
            mitigation.setdefault("allow_true_damage", True)
            mitigation.setdefault("allow_shield_penetration", True)
            mitigation.setdefault("allow_temporary_hp_penetration", True)
            mitigation.setdefault("resistance_clamp_min", 0.0)
            mitigation.setdefault("resistance_clamp_max", 0.95)
            mitigation.setdefault("vulnerability_min_multiplier", 1.0)
            mitigation.setdefault("vulnerability_max_multiplier", 3.0)

        release_strategy = game_state.combat_rules.get("release_strategy")
        if not isinstance(release_strategy, dict):
            game_state.combat_rules["release_strategy"] = {
                "stage": "debug",
                "canary_percent": 0,
                "auto_degrade_enabled": True,
                "degrade_diff_threshold": int(getattr(config.game, "combat_diff_threshold", 5) or 5),
                "degrade_latency_p95_ms": 500,
                "degrade_error_rate": 0.05,
            }
        else:
            release_strategy.setdefault("stage", "debug")
            release_strategy.setdefault("canary_percent", 0)
            release_strategy.setdefault("auto_degrade_enabled", True)
            release_strategy.setdefault("degrade_diff_threshold", int(getattr(config.game, "combat_diff_threshold", 5) or 5))
            release_strategy.setdefault("degrade_latency_p95_ms", 500)
            release_strategy.setdefault("degrade_error_rate", 0.05)

        rollback = game_state.combat_rules.get("rollback")
        if not isinstance(rollback, dict):
            game_state.combat_rules["rollback"] = {
                "enabled": True,
                "last_stable_rule_version": max(1, int(getattr(game_state, "combat_rule_version", 1) or 1)),
                "fallback_authority_mode": "local",
                "last_reason": "",
                "last_trace_id": "",
            }
        else:
            rollback.setdefault("enabled", True)
            rollback.setdefault("last_stable_rule_version", max(1, int(getattr(game_state, "combat_rule_version", 1) or 1)))
            rollback.setdefault("fallback_authority_mode", "local")
            rollback.setdefault("last_reason", "")
            rollback.setdefault("last_trace_id", "")

    def _percentile(self, values: List[int], ratio: float) -> int:
        if not values:
            return 0
        sorted_vals = sorted(int(v) for v in values)
        idx = int(max(0, min(len(sorted_vals) - 1, round((len(sorted_vals) - 1) * ratio))))
        return int(sorted_vals[idx])

    def _record_combat_latency(self, game_state: GameState, elapsed_ms: int):
        self._ensure_combat_defaults(game_state)
        metrics = game_state.combat_snapshot.setdefault("latency_metrics", {})
        samples = metrics.setdefault("samples_ms", [])
        samples.append(max(0, int(elapsed_ms)))
        max_samples = max(20, int(metrics.get("max_samples", 200) or 200))
        if len(samples) > max_samples:
            del samples[: len(samples) - max_samples]
        metrics["p50_ms"] = self._percentile(samples, 0.5)
        metrics["p95_ms"] = self._percentile(samples, 0.95)

    def _get_player_defense_runtime(self, player: Character) -> Dict[str, int]:
        runtime = getattr(player, "combat_runtime", None)
        if not isinstance(runtime, dict):
            runtime = {
                "shield": int(getattr(player.stats, "shield", 0) or 0),
                "temporary_hp": int(getattr(player.stats, "temporary_hp", 0) or 0),
            }
            player.combat_runtime = runtime

        runtime.setdefault("shield", int(getattr(player.stats, "shield", 0) or 0))
        runtime.setdefault("temporary_hp", int(getattr(player.stats, "temporary_hp", 0) or 0))
        runtime["shield"] = max(0, int(runtime.get("shield", 0) or 0))
        runtime["temporary_hp"] = max(0, int(runtime.get("temporary_hp", 0) or 0))
        return runtime

    def _sync_player_defense_runtime(self, player: Character):
        runtime = self._get_player_defense_runtime(player)
        player.stats.shield = int(runtime.get("shield", 0) or 0)
        player.stats.temporary_hp = int(runtime.get("temporary_hp", 0) or 0)

    def _rebuild_combat_snapshot(self, game_state: GameState):
        self._ensure_combat_defaults(game_state)
        player = game_state.player
        stats = player.stats
        self._sync_player_defense_runtime(player)

        total_set_counts: Dict[str, int] = {}
        passive_effects: List[Dict[str, Any]] = []
        trigger_affixes: List[Dict[str, Any]] = []
        rarity_profile: Dict[str, int] = {}
        for _, equipped in (player.equipped_items or {}).items():
            if not equipped:
                continue
            set_id = str(getattr(equipped, "set_id", "") or "")
            if set_id:
                total_set_counts[set_id] = total_set_counts.get(set_id, 0) + 1
            rarity = str(getattr(equipped, "rarity", "common") or "common")
            rarity_profile[rarity] = rarity_profile.get(rarity, 0) + 1

            for payload in getattr(equipped, "equip_passive_effects", []) or []:
                if isinstance(payload, dict):
                    passive_effects.append(payload)

            for payload in getattr(equipped, "trigger_affixes", []) or []:
                if isinstance(payload, dict):
                    trigger_affixes.append(payload)

        ac_components = dict(getattr(stats, "ac_components", {}) or {})
        while True:
            before = set(ac_components.keys())
            for key in ("base", "armor", "shield", "status", "situational", "penalty"):
                ac_components.setdefault(key, 0)
            if before == set(ac_components.keys()):
                break
        ac_components["armor"] = 0
        ac_components["shield"] = 0
        for _, equipped in (player.equipped_items or {}).items():
            if not equipped:
                continue
            props = getattr(equipped, "properties", {}) or {}
            ac_components["armor"] += int(props.get("ac_bonus", 0) or 0)
            ac_components["shield"] += int(props.get("shield_bonus", 0) or 0)

        stats.ac_components = ac_components
        stats.ac = stats.get_effective_ac()

        equipment_runtime = self._build_equipment_runtime(player, game_state)
        runtime_bonuses = equipment_runtime.get("combat_bonuses", {}) if isinstance(equipment_runtime, dict) else {}

        # 让装备 runtime 的防御向增益进入快照口径（不覆写基础存档字段）
        base_ac_components = dict(stats.ac_components)
        snapshot_ac_components = dict(base_ac_components)
        if isinstance(runtime_bonuses, dict):
            snapshot_ac_components["status"] = int(snapshot_ac_components.get("status", 0) or 0) + int(runtime_bonuses.get("ac_bonus", 0) or 0)

        snapshot_ac_effective = (
            int(snapshot_ac_components.get("base", 10) or 10)
            + int(snapshot_ac_components.get("armor", 0) or 0)
            + int(snapshot_ac_components.get("shield", 0) or 0)
            + int(snapshot_ac_components.get("status", 0) or 0)
            + int(snapshot_ac_components.get("situational", 0) or 0)
            - int(snapshot_ac_components.get("penalty", 0) or 0)
        )
        snapshot_ac_effective = max(int(getattr(stats, "ac_min", 1) or 1), min(int(getattr(stats, "ac_max", 50) or 50), snapshot_ac_effective))

        effective_resistances = dict(getattr(player, "resistances", {}) or {})
        effective_vulnerabilities = dict(getattr(player, "vulnerabilities", {}) or {})
        if isinstance(runtime_bonuses, dict):
            for damage_type, delta in (runtime_bonuses.get("resistance_bonus", {}) or {}).items():
                dtype = str(damage_type or "")
                if not dtype:
                    continue
                current = float(effective_resistances.get(dtype, 0.0) or 0.0)
                effective_resistances[dtype] = max(0.0, min(0.95, current + float(delta or 0.0)))
            for damage_type, delta in (runtime_bonuses.get("vulnerability_reduction", {}) or {}).items():
                dtype = str(damage_type or "")
                if not dtype:
                    continue
                current = float(effective_vulnerabilities.get(dtype, 0.0) or 0.0)
                effective_vulnerabilities[dtype] = max(0.0, current - float(delta or 0.0))

        control = effect_engine.get_action_availability(player)
        status_view = effect_engine.build_status_debug_view(player)
        conflicts = effect_engine.detect_status_conflicts(player)
        player.runtime_stats = {
            "equipment": dict(runtime_bonuses) if isinstance(runtime_bonuses, dict) else {},
            "set_effects": list(equipment_runtime.get("set_effects", [])) if isinstance(equipment_runtime, dict) else [],
            "trace_id": str(equipment_runtime.get("trace_id", "") or "") if isinstance(equipment_runtime, dict) else "",
        }
        player.derived_runtime = {
            "ac_effective": int(snapshot_ac_effective),
            "ac_components": dict(snapshot_ac_components),
            "resistances": dict(effective_resistances),
            "vulnerabilities": dict(effective_vulnerabilities),
        }

        game_state.combat_snapshot.update(
            {
                "player": {
                    "hp": int(stats.hp),
                    "max_hp": int(stats.max_hp),
                    "ac_effective": int(snapshot_ac_effective),
                    "ac_legacy": int(getattr(stats, "ac", 10) or 10),
                    "ac_bounds": {
                        "min": int(getattr(stats, "ac_min", 1) or 1),
                        "max": int(getattr(stats, "ac_max", 50) or 50),
                    },
                    "ac_components": snapshot_ac_components,
                    "ac_policy": "hit_threshold_only",
                    "shield": int(self._get_player_defense_runtime(player).get("shield", 0) or 0),
                    "temporary_hp": int(self._get_player_defense_runtime(player).get("temporary_hp", 0) or 0),
                    "resistances": effective_resistances,
                    "vulnerabilities": effective_vulnerabilities,
                    "immunities": list(getattr(player, "immunities", []) or []),
                },
                "equipment": {
                    "set_counts": total_set_counts,
                    "passive_effects": passive_effects,
                    "trigger_affixes": trigger_affixes,
                    "rarity_profile": rarity_profile,
                    "affixes": [
                        {
                            "item_id": item.id,
                            "affixes": getattr(item, "affixes", []),
                            "set_id": str(getattr(item, "set_id", "") or ""),
                            "set_thresholds": getattr(item, "set_thresholds", {}),
                        }
                        for item in (player.equipped_items or {}).values()
                        if item is not None
                    ],
                    "runtime": equipment_runtime,
                },
                "status_runtime": {
                    "status_view": status_view,
                    "conflicts": conflicts,
                    "blocked_actions": control.get("blocked_actions", {}),
                    "action_gate": {
                        "can_move": bool(control.get("can_move", True)),
                        "can_attack": bool(control.get("can_attack", True)),
                        "can_cast_spell": bool(control.get("can_cast_spell", True)),
                        "can_use_item": bool(control.get("can_use_item", True)),
                    },
                },
                "defense_layers": {
                    "shield": int(self._get_player_defense_runtime(player).get("shield", 0) or 0),
                    "temporary_hp": int(self._get_player_defense_runtime(player).get("temporary_hp", 0) or 0),
                    "order": list(game_state.combat_rules.get("damage_order", ["hit", "shield", "temporary_hp", "resistance", "vulnerability", "hp"])),
                    "true_damage_enabled": True,
                },
            }
        )

    def _append_ac_baseline_sample(self, game_state: GameState, trace_id: str):
        self._ensure_combat_defaults(game_state)
        tests = game_state.combat_snapshot.setdefault("combat_tests", {})
        baseline = tests.setdefault("ac_baseline", [])
        samples: List[Dict[str, Any]] = list(baseline) if isinstance(baseline, list) else []

        player = game_state.player
        sample = {
            "trace_id": str(trace_id or ""),
            "class": str(getattr(player.character_class, "value", "unknown") or "unknown"),
            "level": int(getattr(player.stats, "level", 1) or 1),
            "ac_effective": int(getattr(player.stats, "ac", 10) or 10),
            "ac_components": dict(getattr(player.stats, "ac_components", {}) or {}),
        }

        samples.append(sample)
        if len(samples) > 120:
            samples = samples[-120:]
        tests["ac_baseline"] = samples

    def _record_ac_hit_curve(self, game_state: GameState, attack_log: Dict[str, Any]):
        self._ensure_combat_defaults(game_state)
        tests = game_state.combat_snapshot.setdefault("combat_tests", {})
        curve = tests.setdefault("ac_hit_curve", [])
        rows: List[Dict[str, Any]] = list(curve) if isinstance(curve, list) else []

        rows.append(
            {
                "trace_id": str(attack_log.get("trace_id", "") or ""),
                "phase": str(attack_log.get("phase", "") or ""),
                "attacker": str(attack_log.get("attacker", "") or ""),
                "target": str(attack_log.get("target", "") or ""),
                "target_ac": int(attack_log.get("target_ac", 10) or 10),
                "attack_total": int(attack_log.get("attack_total", 0) or 0),
                "hit": bool(attack_log.get("hit", False)),
            }
        )
        if len(rows) > 500:
            rows = rows[-500:]
        tests["ac_hit_curve"] = rows

    def _build_equipment_runtime(self, player: Character, game_state: Optional[GameState] = None) -> Dict[str, Any]:
        runtime = {
            "set_effects": [],
            "combat_bonuses": {
                "hit_bonus": 0,
                "critical_bonus": 0.0,
                "damage_bonus": 0,
                "ac_bonus": 0,
                "shield_bonus": 0,
                "resistance_bonus": {},
                "vulnerability_reduction": {},
                "heal_on_kill": 0,
                "regen_per_turn": 0,
            },
            "validation_warnings": [],
            "trace": [],
            "trace_id": f"equip-runtime-{datetime.utcnow().timestamp()}",
        }

        set_counts: Dict[str, int] = {}
        items = [item for item in (player.equipped_items or {}).values() if item is not None]
        for item in items:
            set_id = str(getattr(item, "set_id", "") or "")
            if set_id:
                set_counts[set_id] = set_counts.get(set_id, 0) + 1

        order_stages = {
            "base": 10,
            "equip_passive": 20,
            "affix": 30,
            "set": 40,
            "status": 50,
            "situational": 60,
        }

        def _record_trace(entry: Dict[str, Any]):
            runtime["trace"].append(entry)

        for item in items:
            payloads: List[Dict[str, Any]] = []
            for entry in getattr(item, "equip_passive_effects", []) or []:
                if isinstance(entry, dict):
                    payload = dict(entry)
                    payload.setdefault("effect_scope", "equip_passive")
                    payload["_source"] = f"equip:{getattr(item, 'equip_slot', '')}:{getattr(item, 'id', '')}"
                    payload["_stage"] = "equip_passive"
                    payloads.append(payload)
            for entry in getattr(item, "affixes", []) or []:
                if isinstance(entry, dict):
                    payload = dict(entry)
                    payload.setdefault("effect_scope", "equip_passive")
                    payload["_source"] = f"equip:{getattr(item, 'equip_slot', '')}:{getattr(item, 'id', '')}"
                    payload["_stage"] = "affix"
                    payloads.append(payload)

            set_id = str(getattr(item, "set_id", "") or "")
            thresholds = getattr(item, "set_thresholds", {}) or {}
            if set_id and isinstance(thresholds, dict):
                count = int(set_counts.get(set_id, 0) or 0)
                for raw_need, effect_payload in thresholds.items():
                    try:
                        need = int(raw_need)
                    except (TypeError, ValueError):
                        continue
                    if count >= need and isinstance(effect_payload, dict):
                        runtime["set_effects"].append(
                            {
                                "set_id": set_id,
                                "threshold": need,
                                "item_id": getattr(item, "id", ""),
                                "effect": effect_payload,
                            }
                        )
                        payload = dict(effect_payload)
                        payload.setdefault("effect_scope", "equip_passive")
                        payload["_source"] = f"equip:{getattr(item, 'equip_slot', '')}:{getattr(item, 'id', '')}"
                        payload["_stage"] = "set"
                        payloads.append(payload)

            for payload in payloads:
                parsed = self._sanitize_equipment_affix_payload(payload)
                if not parsed:
                    runtime["validation_warnings"].append(f"ignored_affix:{getattr(item, 'id', 'unknown')}")
                    continue

                key = parsed["key"]
                value = parsed["value"]
                mapping = parsed.get("mapping")
                stage = str(payload.get("_stage", "equip_passive") or "equip_passive")
                source = str(payload.get("_source", "") or "")

                if key in {"resistance_bonus", "vulnerability_reduction"}:
                    if isinstance(mapping, dict):
                        target = runtime["combat_bonuses"][key]
                        for damage_type, amount in mapping.items():
                            dtype = str(damage_type or "")
                            if not dtype:
                                continue
                            before = float(target.get(dtype, 0.0) or 0.0)
                            after = before + float(amount)
                            target[dtype] = after
                            _record_trace(
                                {
                                    "stage": stage,
                                    "stage_order": order_stages.get(stage, 999),
                                    "source": source,
                                    "item_id": getattr(item, "id", ""),
                                    "item_name": getattr(item, "name", ""),
                                    "key": key,
                                    "damage_type": dtype,
                                    "before": before,
                                    "delta": float(amount),
                                    "after": after,
                                }
                            )
                    continue

                if key in runtime["combat_bonuses"]:
                    if key in {"critical_bonus"}:
                        before = float(runtime["combat_bonuses"][key])
                        after = before + float(value)
                        runtime["combat_bonuses"][key] = after
                    else:
                        before = int(runtime["combat_bonuses"][key])
                        after = before + int(value)
                        runtime["combat_bonuses"][key] = after
                    _record_trace(
                        {
                            "stage": stage,
                            "stage_order": order_stages.get(stage, 999),
                            "source": source,
                            "item_id": getattr(item, "id", ""),
                            "item_name": getattr(item, "name", ""),
                            "key": key,
                            "before": before,
                            "delta": value,
                            "after": after,
                        }
                    )

        runtime["trace"] = sorted(
            runtime["trace"],
            key=lambda row: int(row.get("stage_order", 999) or 999),
        )

        if game_state is not None and bool(getattr(config.game, "debug_mode", False)):
            snapshot = game_state.combat_snapshot if isinstance(game_state.combat_snapshot, dict) else {}
            trace_samples = snapshot.get("equipment_trace_samples", [])
            if not isinstance(trace_samples, list):
                trace_samples = []
            trace_samples.append(
                {
                    "trace_id": runtime["trace_id"],
                    "game_id": str(getattr(game_state, "id", "") or ""),
                    "turn": int(getattr(game_state, "turn_count", 0) or 0),
                    "items": [
                        {
                            "item_id": getattr(item, "id", ""),
                            "slot": getattr(item, "equip_slot", ""),
                            "item_name": getattr(item, "name", ""),
                        }
                        for item in items
                    ],
                    "combat_bonuses": runtime["combat_bonuses"],
                    "trace": runtime["trace"],
                }
            )
            snapshot["equipment_trace_samples"] = trace_samples[-100:]
            game_state.combat_snapshot = snapshot

        return runtime

    def _record_combat_telemetry(
        self,
        game_state: GameState,
        *,
        damage: int = 0,
        win: bool = False,
        loss: bool = False,
        death_source: str = "",
        attempt: bool = False,
    ):
        self._ensure_combat_defaults(game_state)
        telemetry = game_state.combat_snapshot.setdefault("telemetry", {})

        telemetry["burst_peak"] = max(
            int(telemetry.get("burst_peak", 0) or 0),
            max(0, int(damage or 0)),
        )
        telemetry["combat_attempts"] = int(telemetry.get("combat_attempts", 0) or 0)
        if attempt:
            telemetry["combat_attempts"] = telemetry["combat_attempts"] + 1

        if win:
            telemetry["wins"] = int(telemetry.get("wins", 0) or 0) + 1
            telemetry["completed_combats"] = int(telemetry.get("completed_combats", 0) or 0) + 1
            telemetry["total_turns"] = int(telemetry.get("total_turns", 0) or 0) + int(
                max(0, int(getattr(game_state, "turn_count", 0) or 0))
            )

        if loss:
            telemetry["losses"] = int(telemetry.get("losses", 0) or 0) + 1
            telemetry["completed_combats"] = int(telemetry.get("completed_combats", 0) or 0) + 1
            if death_source:
                sources = telemetry.get("death_sources", {})
                if not isinstance(sources, dict):
                    sources = {}
                key = str(death_source)
                sources[key] = int(sources.get(key, 0) or 0) + 1
                telemetry["death_sources"] = sources

        completed = int(telemetry.get("completed_combats", 0) or 0)
        wins = int(telemetry.get("wins", 0) or 0)
        total_turns = int(telemetry.get("total_turns", 0) or 0)
        telemetry["win_rate"] = 0.0 if completed <= 0 else round(wins / float(completed), 4)
        telemetry["avg_turns"] = 0.0 if completed <= 0 else round(total_turns / float(completed), 2)

    def _evaluate_release_gate_and_degrade(self, game_state: GameState, trace_id: str = ""):
        self._ensure_combat_defaults(game_state)
        rules = game_state.combat_rules or {}
        release_strategy = rules.get("release_strategy", {}) if isinstance(rules, dict) else {}
        rollback = rules.get("rollback", {}) if isinstance(rules, dict) else {}
        telemetry = game_state.combat_snapshot.get("telemetry", {}) if isinstance(game_state.combat_snapshot, dict) else {}
        latency = game_state.combat_snapshot.get("latency_metrics", {}) if isinstance(game_state.combat_snapshot, dict) else {}

        if not isinstance(release_strategy, dict):
            return
        if not bool(release_strategy.get("auto_degrade_enabled", True)):
            return

        degrade_latency = int(release_strategy.get("degrade_latency_p95_ms", 500) or 500)
        degrade_error_rate = float(release_strategy.get("degrade_error_rate", 0.05) or 0.05)
        p95_ms = int(latency.get("p95_ms", 0) or 0)
        errors = max(0, int(telemetry.get("errors", 0) or 0))
        raw_attempts = max(0, int(telemetry.get("combat_attempts", 0) or 0))
        completed = max(0, int(telemetry.get("completed_combats", 0) or 0))
        attempts = max(raw_attempts, completed)
        effective_errors = min(errors, attempts) if attempts > 0 else errors
        denominator = max(1, attempts)
        error_rate = effective_errors / float(denominator)

        should_degrade = p95_ms > degrade_latency or error_rate > degrade_error_rate
        if not should_degrade:
            return

        fallback_mode = str(rollback.get("fallback_authority_mode", "local") or "local")
        if fallback_mode not in {"local", "hybrid", "server"}:
            fallback_mode = "local"

        previous_mode = str(getattr(game_state, "combat_authority_mode", "local") or "local")
        game_state.combat_authority_mode = fallback_mode
        rollback["last_reason"] = f"auto_degrade:p95={p95_ms},error_rate={round(error_rate, 4)}"
        rollback["last_trace_id"] = str(trace_id or "")
        release_strategy["stage"] = "debug"
        self._capture_combat_anomaly(
            game_state,
            trace_id=str(trace_id or "auto-degrade"),
            error_code="COMBAT_AUTO_DEGRADE",
            message="触发自动降级",
            context={
                "previous_mode": previous_mode,
                "fallback_mode": fallback_mode,
                "p95_ms": p95_ms,
                "error_rate": round(error_rate, 6),
                "errors": errors,
                "effective_errors": effective_errors,
                "attempts": attempts,
                "raw_attempts": raw_attempts,
                "completed_combats": completed,
            },
        )

        logger.warning(
            "Combat auto degrade triggered trace=%s mode=%s->%s p95=%s error_rate=%.4f",
            trace_id,
            previous_mode,
            fallback_mode,
            p95_ms,
            error_rate,
        )

    async def create_new_game(self, user_id: str, player_name: str, character_class: str = "fighter") -> GameState:
        """创建新游戏

        Args:
            user_id: 用户ID
            player_name: 玩家名称
            character_class: 角色职业

        Returns:
            创建的游戏状态
        """
        game_state = GameState()
        game_state.combat_rule_version = 1
        game_state.combat_authority_mode = (config.game.combat_authority_mode or "local").strip().lower()
        if game_state.combat_authority_mode not in {"local", "hybrid", "server"}:
            game_state.combat_authority_mode = "local"

        # 创建玩家角色
        game_state.player = await self._create_player_character(player_name, character_class)

        # 生成初始任务
        initial_quests = await content_generator.generate_quest_chain(
            game_state.player.stats.level, 1
        )
        game_state.quests.extend(initial_quests)

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        # 生成初始地图（考虑任务上下文）
        game_state.current_map = await self._generate_map_with_provider(
            width=config.game.default_map_size[0],
            height=config.game.default_map_size[1],
            depth=1,
            theme="起始区域",
            quest_context=quest_context,
            source="create_new_game",
            user_id=user_id,
            game_state=game_state,
        )

        # 设置玩家初始位置
        spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
        if spawn_positions:
            game_state.player.position = spawn_positions[0]
            # 在地图上标记玩家位置
            tile = game_state.current_map.get_tile(*game_state.player.position)
            if tile:
                tile.character_id = game_state.player.id
                tile.is_explored = True
                tile.is_visible = True

        # 生成初始怪物
        monsters = await self._generate_encounter_monsters_by_map_hints(
            game_state,
            game_state.current_map,
            default_difficulty="easy",
        )

        # 生成任务专属怪物
        quest_monsters = await self._generate_quest_monsters(game_state, game_state.current_map)
        monsters.extend(quest_monsters)

        # 为怪物分配位置
        monster_positions = self._get_monster_spawn_positions(
            game_state.current_map, len(monsters)
        )

        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = game_state.current_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)



        self._rebuild_combat_snapshot(game_state)

        # 生成开场叙述
        try:
            opening_narrative = await llm_service.generate_opening_narrative(game_state)
            game_state.last_narrative = opening_narrative
        except Exception as e:
            logger.error(f"Failed to generate opening narrative: {e}")
            game_state.last_narrative = f"欢迎来到 {game_state.current_map.name}！你的冒险即将开始..."

        # 保存游戏状态（使用用户目录）
        await self._save_game_async(game_state, user_id)

        # 添加到活跃游戏列表（使用 (user_id, game_id) 作为键）
        game_key = (user_id, game_state.id)
        self.active_games[game_key] = game_state

        # 更新访问时间
        self.update_access_time(user_id, game_state.id)

        # 启动自动保存
        self._start_auto_save(user_id, game_state.id)

        logger.info(f"New game created for user {user_id}: {game_state.id}")
        return game_state

    async def _create_player_character(self, name: str, character_class: str) -> Character:
        """创建玩家角色"""
        player = Character()
        player.name = name

        # 设置职业
        try:
            player.character_class = CharacterClass(character_class.lower())
        except ValueError:
            player.character_class = CharacterClass.FIGHTER

        # 根据职业设置初始属性（按DND 5E规则）
        class_configs = {
            CharacterClass.FIGHTER: {
                "abilities": {"strength": 15, "constitution": 14, "dexterity": 12},
                "hp": 120, "mp": 30,
                "saving_throw_proficiencies": ["strength", "constitution"],  # 战士：力量+体质豁免
                "skill_proficiencies": ["athletics", "intimidation"]  # 示例技能
            },
            CharacterClass.WIZARD: {
                "abilities": {"intelligence": 15, "wisdom": 14, "constitution": 12},
                "hp": 80, "mp": 100,
                "saving_throw_proficiencies": ["intelligence", "wisdom"],  # 法师：智力+感知豁免
                "skill_proficiencies": ["arcana", "investigation"]
            },
            CharacterClass.ROGUE: {
                "abilities": {"dexterity": 15, "intelligence": 14, "charisma": 12},
                "hp": 100, "mp": 50,
                "saving_throw_proficiencies": ["dexterity", "intelligence"],  # 盗贼：敏捷+智力豁免
                "skill_proficiencies": ["stealth", "perception", "sleight_of_hand"]
            },
            CharacterClass.CLERIC: {
                "abilities": {"wisdom": 15, "constitution": 14, "strength": 12},
                "hp": 110, "mp": 80,
                "saving_throw_proficiencies": ["wisdom", "charisma"],  # 牧师：感知+魅力豁免
                "skill_proficiencies": ["religion", "medicine"]
            }
        }

        class_config = class_configs.get(player.character_class, class_configs[CharacterClass.FIGHTER])

        # 设置六维属性
        for ability, value in class_config["abilities"].items():
            setattr(player.abilities, ability, value)

        # 设置等级
        player.stats.level = config.game.starting_level

        # 根据六维属性计算衍生属性 (HP, MP, AC等)
        player.stats.calculate_derived_stats(player.abilities)

        # 如果配置中指定了HP/MP,则覆盖计算值
        if "hp" in class_config:
            player.stats.hp = class_config["hp"]
            player.stats.max_hp = class_config["hp"]
        if "mp" in class_config:
            player.stats.mp = class_config["mp"]
            player.stats.max_mp = class_config["mp"]

        # 设置豁免熟练和技能熟练（按DND 5E职业规则）
        if "saving_throw_proficiencies" in class_config:
            player.saving_throw_proficiencies = class_config["saving_throw_proficiencies"]
        if "skill_proficiencies" in class_config:
            player.skill_proficiencies = class_config["skill_proficiencies"]

        # 更新熟练加值（基于等级）
        player.update_proficiency_bonus()

        # 使用LLM生成角色描述
        description_prompt = f"""
        为一个名叫{name}的{character_class}角色生成一个简短的背景描述。
        这是一个DnD风格的角色，刚开始冒险。
        描述应该包含外貌、性格和简单的背景故事。
        """

        try:
            player.description = await llm_service._async_generate(description_prompt)
        except Exception as e:
            logger.error(f"Failed to generate character description: {e}")
            player.description = f"一个勇敢的{character_class}，准备踏上冒险之旅。"

        return player

    async def load_game(self, user_id: str, save_id: str) -> Optional[GameState]:
        """加载游戏

        Args:
            user_id: 用户ID
            save_id: 存档ID

        Returns:
            加载的游戏状态
        """
        # 【修复】使用 user_session_manager 从用户目录加载
        from user_session_manager import user_session_manager

        save_data = user_session_manager.load_game_for_user(user_id, save_id)
        if not save_data:
            logger.warning(f"Failed to load game {save_id} for user {user_id}")
            return None

        # 重建游戏状态
        game_state = data_manager._dict_to_game_state(save_data)

        # 【修复】清除所有瓦片的character_id（防止存档中有错误数据）
        for tile in game_state.current_map.tiles.values():
            tile.character_id = None
        logger.info(f"Cleared all character_id from {len(game_state.current_map.tiles)} tiles")

        # 【修复】重新设置玩家位置的character_id
        player_tile = game_state.current_map.get_tile(*game_state.player.position)
        if player_tile:
            player_tile.character_id = game_state.player.id
            player_tile.is_explored = True
            player_tile.is_visible = True
            logger.info(f"Player position restored: {game_state.player.position}")

        # 【修复】重新设置怪物位置的character_id
        for monster in game_state.monsters:
            monster_tile = game_state.current_map.get_tile(*monster.position)
            if monster_tile:
                monster_tile.character_id = monster.id
                logger.info(f"Monster {monster.name} position restored: {monster.position}")

        # 使用 (user_id, game_id) 作为键
        game_key = (user_id, game_state.id)
        self.active_games[game_key] = game_state

        # 更新访问时间
        self.update_access_time(user_id, game_state.id)

        self._start_auto_save(user_id, game_state.id)

        # 生成重新进入游戏的叙述
        try:
            return_narrative = await llm_service.generate_return_narrative(game_state)
            game_state.last_narrative = return_narrative
        except Exception as e:
            logger.error(f"Failed to generate return narrative: {e}")
            game_state.last_narrative = f"你重新回到了 {game_state.current_map.name}，继续你的冒险..."

        logger.info(f"Game loaded for user {user_id}: {game_state.id}")
        return game_state

    async def process_player_action(self, user_id: str, game_id: str, action: str,
                                  parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """处理玩家行动

        Args:
            user_id: 用户ID
            game_id: 游戏ID
            action: 行动类型
            parameters: 行动参数

        Returns:
            行动结果
        """
        game_key = (user_id, game_id)
        if game_key not in self.active_games:
            return self._make_action_result(
                False,
                "游戏未找到",
                error_code="GAME_NOT_FOUND",
                retryable=False,
            )

        game_state = self.active_games[game_key]
        parameters = parameters or {}

        result = self._make_action_result(True, "", events=[])
        self._cleanup_drop_undo_entries(game_key, game_state.turn_count)
        self._ensure_combat_defaults(game_state)

        if action in {"use_item", "drop_item", "attack"}:
            replay = self._get_cached_action_result(game_key, action, parameters)
            if replay is not None:
                return replay

        try:
            action_gate = effect_engine.get_action_availability(game_state.player)
            blocked_actions = action_gate.get("blocked_actions", {})
            if action in blocked_actions:
                return self._make_action_result(
                    False,
                    f"当前无法执行 {action}：受 {', '.join(blocked_actions[action])} 影响",
                    error_code="ACTION_BLOCKED_BY_STATUS",
                    retryable=False,
                    reason="action_blocked_by_status",
                    impact_summary={"blocked_by": blocked_actions[action]},
                )

            if action == "move":
                result = await self._handle_move(game_state, parameters)
            elif action == "attack":
                result = await self._handle_attack(game_state, parameters)
            elif action == "use_item":
                result = await self._handle_use_item(game_state, parameters)
            elif action == "drop_item":
                result = await self._handle_drop_item(game_state, game_key, parameters)
            elif action == "undo_drop_item":
                result = await self._handle_undo_drop_item(game_state, game_key, parameters)
            elif action == "cast_spell":
                result = await self._handle_cast_spell(game_state, parameters)
            elif action == "interact":
                result = await self._handle_interact(game_state, parameters)
            elif action == "rest":
                result = await self._handle_rest(game_state)
            else:
                result = self._make_action_result(
                    False,
                    f"未知行动: {action}",
                    error_code="UNKNOWN_ACTION",
                    retryable=False,
                )

            # 增加回合数
            if result["success"]:
                turn_start_ms = int(datetime.utcnow().timestamp() * 1000)
                game_state.turn_count += 1
                game_state.game_time += 1  # 每回合1分钟

                # 回合推进：处理状态效果与物品冷却
                try:
                    tick_events = effect_engine.process_turn_effects(game_state, trigger="turn_end")
                    if tick_events:
                        if "events" not in result:
                            result["events"] = []
                        result["events"].extend(tick_events)
                except Exception as e:
                    logger.error(f"Failed to process turn effects: {e}")

                for inv_item in game_state.player.inventory:
                    if getattr(inv_item, "current_cooldown", 0) > 0:
                        inv_item.current_cooldown = max(0, int(inv_item.current_cooldown) - 1)

                # 处理怪物行动（如果游戏没有结束）
                monster_events_occurred = False
                if not game_state.is_game_over:
                    monster_events_occurred = await self._process_monster_turns(game_state)

                # 添加待处理事件到结果中
                if hasattr(game_state, 'pending_events') and game_state.pending_events:
                    if "events" not in result:
                        result["events"] = []
                    result["events"].extend(game_state.pending_events)
                    game_state.pending_events.clear()

                # 检查是否有任务完成需要处理选择
                if hasattr(game_state, 'pending_quest_completion') and game_state.pending_quest_completion:
                    completed_quest = game_state.pending_quest_completion
                    try:
                        # 创建任务完成选择上下文
                        choice_context = await event_choice_system.create_quest_completion_choice(
                            game_state, completed_quest
                        )

                        # 将选择上下文存储到游戏状态中
                        game_state.pending_choice_context = choice_context
                        event_choice_system.active_contexts[choice_context.id] = choice_context

                        # 清理任务完成标志
                        game_state.pending_quest_completion = None

                        logger.info(f"Created quest completion choice for: {completed_quest.title}")

                    except Exception as e:
                        logger.error(f"Error creating quest completion choice: {e}")
                        # 清理标志，避免重复处理
                        game_state.pending_quest_completion = None

                # 检查是否需要生成新任务（确保玩家始终有活跃任务）
                if hasattr(game_state, 'pending_new_quest_generation') and game_state.pending_new_quest_generation:
                    try:
                        # 检查是否还有活跃任务
                        active_quest = next((q for q in game_state.quests if q.is_active), None)
                        if not active_quest:
                            # 生成新任务
                            await self._generate_new_quest_for_player(game_state)

                        # 清理新任务生成标志
                        game_state.pending_new_quest_generation = False

                    except Exception as e:
                        logger.error(f"Error generating new quest: {e}")
                        # 清理标志，避免重复处理
                        game_state.pending_new_quest_generation = False

                # 检查游戏是否结束
                if game_state.is_game_over:
                    result["game_over"] = True
                    result["game_over_reason"] = game_state.game_over_reason

                # 【修复】检查是否有待处理的选择上下文，立即返回给前端
                if hasattr(game_state, 'pending_choice_context') and game_state.pending_choice_context:
                    result["pending_choice_context"] = game_state.pending_choice_context.to_dict()
                    logger.info(f"Returning pending choice context in action result: {game_state.pending_choice_context.title}")

                # 判断是否需要LLM交互
                should_generate_narrative = self._should_generate_narrative(action, result)
                llm_interaction_required = should_generate_narrative or monster_events_occurred

                # 添加LLM交互标识到结果中
                result["llm_interaction_required"] = llm_interaction_required

                self._rebuild_combat_snapshot(game_state)
                turn_elapsed_ms = int(datetime.utcnow().timestamp() * 1000) - turn_start_ms
                self._record_combat_latency(game_state, turn_elapsed_ms)
                self._evaluate_release_gate_and_degrade(
                    game_state,
                    trace_id=str(result.get("action_trace_id", "") or parameters.get("idempotency_key", "") or ""),
                )
                result["performance"] = {
                    "turn_elapsed_ms": max(0, int(turn_elapsed_ms)),
                    "p50_ms": int(game_state.combat_snapshot.get("latency_metrics", {}).get("p50_ms", 0)),
                    "p95_ms": int(game_state.combat_snapshot.get("latency_metrics", {}).get("p95_ms", 0)),
                }

                # 使用LLM交互管理器生成上下文相关的叙述
                if should_generate_narrative and not game_state.is_game_over:
                    # 创建交互上下文
                    interaction_context = self._create_interaction_context(
                        action, result, monster_events_occurred
                    )

                    # 添加上下文到管理器
                    llm_interaction_manager.add_context(interaction_context)

                    # 生成上下文相关的叙述
                    narrative = await llm_interaction_manager.generate_contextual_narrative(
                        game_state, interaction_context
                    )
                    result["narrative"] = narrative

        except Exception as e:
            logger.error(f"Error processing action {action}: {e}")
            trace_id = str(parameters.get("idempotency_key", "") or f"{action}-{game_state.turn_count}")
            try:
                telemetry = game_state.combat_snapshot.setdefault("telemetry", {})
                telemetry["errors"] = int(telemetry.get("errors", 0) or 0) + 1
                if str(action or "") in {"attack", "use_item", "combat_result"}:
                    telemetry["combat_attempts"] = int(telemetry.get("combat_attempts", 0) or 0) + 1
            except Exception:
                pass
            self._capture_combat_anomaly(
                game_state,
                trace_id=trace_id,
                error_code="ACTION_PROCESS_ERROR",
                message=f"行动处理异常: {action}",
                context={
                    "action": action,
                    "error": str(e),
                },
            )
            result = self._make_action_result(
                False,
                f"处理行动时发生错误: {str(e)}",
                events=[f"处理行动时发生错误: {str(e)}"],
                error_code="ACTION_PROCESS_ERROR",
                retryable=True,
                action_trace_id=trace_id,
            )

        if action in {"use_item", "drop_item"}:
            logger.info(
                "inventory_action action=%s success=%s error_code=%s trace=%s reason=%s",
                action,
                bool(result.get("success", False)),
                result.get("error_code"),
                result.get("action_trace_id"),
                result.get("reason"),
            )

        if action in {"use_item", "drop_item", "attack"} and bool(result.get("success", False)):
            self._store_action_result(game_key, action, parameters, result)

        return result

    def _create_interaction_context(self, action: str, result: Dict[str, Any],
                                  monster_events_occurred: bool) -> InteractionContext:
        """创建LLM交互上下文"""
        events = result.get("events", [])

        # 根据行动类型确定交互类型
        if action == "move":
            interaction_type = InteractionType.MOVEMENT
            movement_data = {
                "new_position": result.get("new_position"),
                "events_triggered": len(events) > 0
            }
            return InteractionContext(
                interaction_type=interaction_type,
                primary_action=f"移动到 {result.get('new_position', '未知位置')}",
                events=events,
                movement_data=movement_data
            )

        elif action == "attack":
            interaction_type = InteractionType.COMBAT_ATTACK
            combat_data = {
                "type": "player_attack",
                "damage": result.get("damage", 0),
                "target": result.get("message", "").replace("攻击了 ", ""),
                "successful": result.get("success", False)
            }
            return InteractionContext(
                interaction_type=interaction_type,
                primary_action=result.get("message", "发动攻击"),
                events=events,
                combat_data=combat_data
            )

        elif action == "use_item":
            interaction_type = InteractionType.ITEM_USE
            item_data = {
                "item_name": result.get("item_name", "未知物品"),
                "effects": result.get("effects", []),
                "consumed": result.get("item_consumed", False)
            }
            return InteractionContext(
                interaction_type=interaction_type,
                primary_action=result.get("message", "使用物品"),
                events=events,
                item_data=item_data
            )

        # 如果有怪物事件发生，创建防御上下文
        elif monster_events_occurred:
            interaction_type = InteractionType.COMBAT_DEFENSE
            combat_data = {
                "type": "monster_attack",
                "events": events
            }
            return InteractionContext(
                interaction_type=interaction_type,
                primary_action="遭受攻击",
                events=events,
                combat_data=combat_data
            )

        else:
            # 默认探索类型
            return InteractionContext(
                interaction_type=InteractionType.EXPLORATION,
                primary_action=result.get("message", action),
                events=events
            )

    def _should_generate_narrative(self, action: str, result: Dict[str, Any]) -> bool:
        """判断是否应该生成叙述文本"""
        # 普通移动且没有事件发生时不生成叙述
        if action == "move":
            events = result.get("events", [])
            # 检查是否只是楼梯提示事件（不需要LLM交互）
            if len(events) == 1:
                event_text = events[0]
                # 楼梯事件只是提示，不需要LLM交互
                if ("楼梯" in event_text and ("下一层" in event_text or "上一层" in event_text)):
                    return False
            # 只有当移动触发了真正需要LLM处理的事件时才生成叙述
            return len(events) > 0

        # 其他行动都生成叙述
        return True

    async def _handle_move(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理移动行动 - 后端仅处理生成型逻辑

        【重要架构说明】
        ================
        本游戏采用前后端分离的事件处理架构：

        前端 (LocalGameEngine.js) 负责：
        - 边界检查、地形检查、碰撞检测
        - 陷阱侦测和触发判定（调用 /api/check-trap 和 /api/trap/trigger）
        - 楼梯事件提示（仅显示提示，不自动触发LLM交互）
        - 战斗计算（伤害、经验值、升级检查）
        - 物品拾取的即时交互

        后端 (game_engine.py) 负责：
        - LLM叙述生成
        - 任务进度更新
        - 事件选择系统（EventChoiceSystem）
        - 地图生成和切换
        - 存档管理

        【关于事件触发】
        ===============
        移动后的事件触发（如陷阱、故事事件）完全由前端 LocalGameEngine.js 负责：
        - 前端在 handleMoveResult() 中检查目标瓦片
        - 前端调用 checkAndTriggerTileEvents() 处理事件
        - 前端仅在需要LLM生成叙述时才调用后端 /api/llm-event

        本方法是遗留接口，主要用于不支持 LocalGameEngine 的旧版本客户端。
        新版本前端不应调用此方法处理移动。
        """
        # 前端已完成所有验证，后端直接信任前端传来的位置
        # 这是一个遗留接口，主要用于不支持LocalGameEngine的旧版本客户端
        logger.warning("_handle_move called - this should be handled by frontend LocalGameEngine")

        # 如果前端没有处理，提供基本的回退支持
        direction = parameters.get("direction", "")
        direction_map = {
            "north": (0, -1), "south": (0, 1),
            "east": (1, 0), "west": (-1, 0),
            "northeast": (1, -1), "northwest": (-1, -1),
            "southeast": (1, 1), "southwest": (-1, 1)
        }

        if direction not in direction_map:
            return {"success": False, "message": "无效的移动方向"}

        dx, dy = direction_map[direction]
        current_x, current_y = game_state.player.position
        new_x, new_y = current_x + dx, current_y + dy

        # 简单验证（前端应该已经做过）
        if (new_x < 0 or new_x >= game_state.current_map.width or
            new_y < 0 or new_y >= game_state.current_map.height):
            return {"success": False, "message": "无法移动到地图边界外"}

        target_tile = game_state.current_map.get_tile(new_x, new_y)
        if not target_tile or target_tile.terrain == TerrainType.WALL:
            return {"success": False, "message": "无法移动到该位置"}

        # 执行移动（更新状态）
        old_tile = game_state.current_map.get_tile(current_x, current_y)
        if old_tile:
            old_tile.character_id = None

        target_tile.character_id = game_state.player.id
        target_tile.is_explored = True
        target_tile.is_visible = True
        game_state.player.position = (new_x, new_y)

        # 更新可见性
        self._update_visibility(game_state, new_x, new_y)

        return {
            "success": True,
            "message": f"移动到 ({new_x}, {new_y})",
            "events": [],
            "new_position": (new_x, new_y)
        }

    def _update_visibility(self, game_state: GameState, center_x: int, center_y: int, radius: int = 2):
        """更新可见性"""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = center_x + dx, center_y + dy
                if (0 <= x < game_state.current_map.width and
                    0 <= y < game_state.current_map.height):
                    tile = game_state.current_map.get_tile(x, y)
                    if tile:
                        tile.is_visible = True
                        if abs(dx) + abs(dy) <= 1:  # 相邻瓦片标记为已探索
                            tile.is_explored = True

    async def _handle_attack(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理攻击行动（Phase 1：统一战斗求值最小闭环）"""
        target_id = parameters.get("target_id", "")

        target_monster = None
        for monster in game_state.monsters:
            if monster.id == target_id:
                target_monster = monster
                break

        if not target_monster:
            return self._make_action_result(
                False,
                "目标未找到",
                error_code="TARGET_NOT_FOUND",
                retryable=False,
                reason="target_not_found",
                action_trace_id=str(parameters.get("idempotency_key", "") or ""),
            )

        player_x, player_y = game_state.player.position
        monster_x, monster_y = target_monster.position
        max_distance = max(abs(player_x - monster_x), abs(player_y - monster_y))
        if max_distance > 1:
            return self._make_action_result(
                False,
                "目标距离太远",
                error_code="TARGET_OUT_OF_RANGE",
                retryable=False,
                reason="target_out_of_range",
                action_trace_id=str(parameters.get("idempotency_key", "") or ""),
            )

        authority_mode = str(getattr(game_state, "combat_authority_mode", "local") or "local").strip().lower()
        if authority_mode not in {"local", "hybrid", "server"}:
            authority_mode = "local"

        deterministic_seed = int(hashlib.sha1(
            f"attack|{game_state.id}|{game_state.turn_count}|{game_state.player.id}|{target_monster.id}".encode("utf-8")
        ).hexdigest()[:8], 16)
        trace_id = str(parameters.get("idempotency_key", "") or f"attack-{game_state.turn_count}")
        self._append_ac_baseline_sample(game_state, trace_id)

        equipment_runtime = (((game_state.combat_snapshot or {}).get("equipment", {}) or {}).get("runtime", {}) or {})
        combat_bonuses = equipment_runtime.get("combat_bonuses", {}) if isinstance(equipment_runtime, dict) else {}
        attack_bonus = int(combat_bonuses.get("hit_bonus", 0) or 0)
        damage_bonus = int(combat_bonuses.get("damage_bonus", 0) or 0)
        critical_bonus = float(combat_bonuses.get("critical_bonus", 0.0) or 0.0)
        critical_bonus = max(0.0, min(1.0, critical_bonus))
        critical_rng = random.Random(int(deterministic_seed) ^ 0xA5A5A5A5)
        can_critical = critical_rng.random() < max(0.0, min(1.0, 0.05 + critical_bonus))

        mitigation_rules = (game_state.combat_rules or {}).get("mitigation", {}) if isinstance(game_state.combat_rules, dict) else {}
        if not isinstance(mitigation_rules, dict):
            mitigation_rules = {}

        damage_types = (game_state.combat_rules or {}).get("damage_types", []) if isinstance(game_state.combat_rules, dict) else []
        allowed_damage_types = {str(v) for v in damage_types if str(v)}
        if not allowed_damage_types:
            allowed_damage_types = {"physical"}

        configured_damage_type = str((game_state.combat_rules or {}).get("default_damage_type", "physical") or "physical")
        if configured_damage_type not in allowed_damage_types:
            logger.warning(
                "invalid default_damage_type fallback trace=%s configured=%s",
                trace_id,
                configured_damage_type,
            )
            configured_damage_type = "physical"
        damage_type = configured_damage_type

        if "damage_type" in parameters:
            logger.warning(
                "external damage_type override blocked trace=%s requested=%s applied=%s",
                trace_id,
                str(parameters.get("damage_type", "") or ""),
                damage_type,
            )

        allow_external_override = bool(config.game.debug_mode) and bool(parameters.get("debug_override_combat", False))
        if not allow_external_override:
            damage_components = None
            penetration = {}
            true_damage = False
        else:
            damage_components = parameters.get("damage_components")
            if not isinstance(damage_components, dict):
                damage_components = None
            else:
                sanitized_components: Dict[str, int] = {}
                for key, raw_val in damage_components.items():
                    safe_key = str(key or "")
                    if safe_key not in allowed_damage_types:
                        continue
                    try:
                        safe_val = int(raw_val)
                    except (TypeError, ValueError):
                        continue
                    safe_val = max(0, min(self._COMBAT_OVERRIDE_COMPONENT_MAX_VALUE, safe_val))
                    if safe_val <= 0:
                        continue
                    sanitized_components[safe_key] = safe_val
                    if len(sanitized_components) >= self._COMBAT_OVERRIDE_COMPONENT_LIMIT:
                        break
                damage_components = sanitized_components or None
                if not bool(mitigation_rules.get("allow_multi_damage_components", True)) and damage_components:
                    first_key = next(iter(damage_components.keys()))
                    damage_components = {first_key: int(damage_components[first_key])}

            penetration = parameters.get("penetration")
            if not isinstance(penetration, dict):
                penetration = {}
            sanitized_penetration: Dict[str, float] = {}
            if bool(mitigation_rules.get("allow_penetration", True)):
                for key, raw_val in penetration.items():
                    safe_key = str(key or "")
                    if not safe_key:
                        continue
                    if safe_key in {"shield", "shield_penetration"} and not bool(mitigation_rules.get("allow_shield_penetration", True)):
                        continue
                    if safe_key in {"temporary_hp", "temporary_hp_penetration"} and not bool(mitigation_rules.get("allow_temporary_hp_penetration", True)):
                        continue
                    try:
                        safe_val = float(raw_val)
                    except (TypeError, ValueError):
                        continue
                    if safe_val <= 0:
                        continue
                    sanitized_penetration[safe_key] = max(0.0, min(1.0, safe_val))
            penetration = sanitized_penetration

            true_damage = bool(parameters.get("true_damage", False))
            if not bool(mitigation_rules.get("allow_true_damage", True)):
                true_damage = False

        # local 模式仅给出后端预测，不写回战斗最终状态，避免与前端本地结算双落账
        if authority_mode == "local":
            eval_result = combat_core_evaluator.evaluate_attack(
                game_state.player,
                target_monster,
                attack_type="melee",
                attack_bonus=attack_bonus,
                damage_bonus=damage_bonus,
                can_critical=can_critical,
                damage_type=damage_type,
                damage_components=damage_components,
                penetration=penetration,
                true_damage=true_damage,
                deterministic_seed=deterministic_seed,
                trace_id=trace_id,
                mitigation_policy=mitigation_rules,
            )
            damage = int(eval_result.final_damage)
            projection = eval_result.to_projection()
            projection["exp"] = int(target_monster.challenge_rating * 100) if eval_result.death else 0
            self._record_combat_telemetry(game_state, damage=damage, attempt=True)
            return {
                "success": True,
                "message": f"攻击了 {target_monster.name}",
                "reason": "ok",
                "events": ["local模式：后端仅返回预测，不落账"],
                "damage": damage,
                "impact_summary": {
                    "target_id": target_monster.id,
                    "hit": bool(eval_result.hit),
                    "critical": bool(eval_result.critical),
                    "death": bool(eval_result.death),
                    "authoritative_applied": False,
                    "damage_type": damage_type,
                    "penetration": penetration,
                    "true_damage": bool(true_damage),
                    "equipment_bonuses": {
                        "hit_bonus": attack_bonus,
                        "damage_bonus": damage_bonus,
                        "critical_bonus": critical_bonus,
                    },
                },
                "combat_breakdown": eval_result.breakdown,
                "combat_projection": projection,
            }

        eval_result = combat_core_evaluator.evaluate_attack(
            game_state.player,
            target_monster,
            attack_type="melee",
            attack_bonus=attack_bonus,
            damage_bonus=damage_bonus,
            can_critical=can_critical,
            damage_type=damage_type,
            damage_components=damage_components,
            penetration=penetration,
            true_damage=true_damage,
            deterministic_seed=deterministic_seed,
            trace_id=trace_id,
            mitigation_policy=mitigation_rules,
        )

        damage = int(eval_result.final_damage)
        events = []
        if eval_result.hit:
            events.append(f"对 {target_monster.name} 造成了 {damage} 点伤害")
            for event_text in eval_result.events:
                if event_text in {"造成 0 点伤害", f"造成 {damage} 点伤害", "目标被击败"}:
                    continue
                events.append(event_text)
        else:
            events.append(f"攻击 {target_monster.name} 未命中")

        if eval_result.death:
            events.append(f"{target_monster.name} 被击败了！")
            heal_on_kill = int(combat_bonuses.get("heal_on_kill", 0) or 0)
            if heal_on_kill > 0:
                before_heal = int(game_state.player.stats.hp)
                game_state.player.stats.hp = min(int(game_state.player.stats.max_hp), before_heal + heal_on_kill)
                healed = int(game_state.player.stats.hp) - before_heal
                if healed > 0:
                    events.append(f"装备击杀回复触发，恢复 {healed} 点生命")
            self._record_combat_telemetry(game_state, damage=damage, win=True, attempt=True)

            exp_gain = int(target_monster.challenge_rating * 100)
            game_state.player.stats.experience += exp_gain
            events.append(f"获得了 {exp_gain} 点经验")

            if self._check_level_up(game_state.player):
                events.append("恭喜升级！")

            if target_monster in game_state.monsters:
                game_state.monsters.remove(target_monster)
            tile = game_state.current_map.get_tile(monster_x, monster_y)
            if tile:
                tile.character_id = None

            context_data = {
                "monster_name": target_monster.name,
                "challenge_rating": target_monster.challenge_rating
            }

            if hasattr(target_monster, 'quest_monster_id') and target_monster.quest_monster_id:
                active_quest = next((q for q in game_state.quests if q.is_active), None)
                if active_quest:
                    quest_monster = next(
                        (qm for qm in active_quest.special_monsters if qm.id == target_monster.quest_monster_id),
                        None
                    )
                    if quest_monster:
                        context_data["quest_monster_id"] = target_monster.quest_monster_id
                        context_data["progress_value"] = quest_monster.progress_value
                        logger.info(f"Defeated quest monster: {target_monster.name}, progress: {quest_monster.progress_value}%")

            await self._trigger_progress_event(
                game_state, ProgressEventType.COMBAT_VICTORY, context_data
            )

            from quest_progress_compensator import quest_progress_compensator
            compensation_result = await quest_progress_compensator.check_and_compensate(game_state)
            if compensation_result["compensated"]:
                logger.info(f"Progress compensated: +{compensation_result['compensation_amount']:.1f}% ({compensation_result['reason']})")

        exp_projection = 0
        if eval_result.death:
            exp_projection = int(target_monster.challenge_rating * 100)

        projection = eval_result.to_projection()
        projection["exp"] = exp_projection

        hook_result = effect_engine.process_effect_hooks(
            game_state,
            hook="on_hit" if eval_result.hit else "on_attack",
            actor=game_state.player,
            target=target_monster,
            context={"trace_id": trace_id},
        )
        if hook_result.get("events"):
            events.extend(hook_result["events"])

        self._record_ac_hit_curve(
            game_state,
            {
                "trace_id": trace_id,
                "phase": "player_attack",
                "attacker": str(getattr(game_state.player, "id", "") or ""),
                "target": str(getattr(target_monster, "id", "") or ""),
                "target_ac": int(eval_result.attack_roll.get("target_ac", 10) or 10),
                "attack_total": int(eval_result.attack_roll.get("total", 0) or 0),
                "hit": bool(eval_result.hit),
            },
        )

        return {
            "success": True,
            "message": f"攻击了 {target_monster.name}",
            "reason": "ok",
            "events": events,
            "damage": damage,
            "impact_summary": {
                "target_id": target_monster.id,
                "hit": bool(eval_result.hit),
                "critical": bool(eval_result.critical),
                "death": bool(eval_result.death),
                "authoritative_applied": True,
                "ac_semantic_boundary": "hit_threshold_only",
                "target_ac": int(eval_result.attack_roll.get("target_ac", 10) or 10),
                "attack_total": int(eval_result.attack_roll.get("total", 0) or 0),
                "damage_type": damage_type,
                "penetration": penetration,
                "true_damage": bool(true_damage),
                "equipment_bonuses": {
                    "hit_bonus": attack_bonus,
                    "damage_bonus": damage_bonus,
                    "critical_bonus": critical_bonus,
                },
            },
            "combat_breakdown": eval_result.breakdown,
            "combat_projection": projection,
            "effect_runtime": hook_result,
        }

    def _calculate_damage(self, attacker: Character, defender: Character) -> int:
        """兼容入口：仅估算伤害，不写回状态。

        Phase 2 后 AC 仅用于命中门槛，不再承担减伤语义。
        """
        _ = defender
        base_damage = 10 + attacker.abilities.get_modifier("strength")
        rolled = random.randint(max(1, base_damage - 3), base_damage + 3)
        return max(1, rolled)

    def _check_level_up(self, character: Character) -> bool:
        """检查是否升级"""
        required_exp = character.stats.level * 1000
        if character.stats.experience >= required_exp:
            character.stats.level += 1
            character.stats.max_hp += 10
            character.stats.hp = character.stats.max_hp
            character.stats.max_mp += 5
            character.stats.mp = character.stats.max_mp
            return True
        return False

    def _has_line_of_sight(self, game_map: "GameMap", x1: int, y1: int, x2: int, y2: int) -> bool:
        """检查两点之间是否有视线（简单实现）"""
        # 对于相邻格子，直接返回True
        if abs(x2 - x1) <= 1 and abs(y2 - y1) <= 1:
            return True

        # 使用简单的直线算法检查路径上是否有墙壁
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)

        x, y = x1, y1
        x_inc = 1 if x1 < x2 else -1
        y_inc = 1 if y1 < y2 else -1

        error = dx - dy

        while x != x2 or y != y2:
            # 检查当前位置是否有墙壁（跳过起点和终点）
            if (x != x1 or y != y1) and (x != x2 or y != y2):
                tile = game_map.get_tile(x, y)
                if tile and tile.terrain == TerrainType.WALL:
                    return False

            error2 = 2 * error
            if error2 > -dy:
                error -= dy
                x += x_inc
            if error2 < dx:
                error += dx
                y += y_inc

        return True

    def _apply_equipment_state_change(
        self,
        game_state: GameState,
        item: Item,
        slot: str,
        action_trace_id: str,
    ) -> Dict[str, Any]:
        if slot not in game_state.player.equipped_items:
            return self._make_action_result(
                False,
                f"{item.name} 的装备槽位无效: {slot}",
                error_code="INVALID_EQUIP_SLOT",
                retryable=False,
                reason="invalid_equip_slot",
                action_trace_id=action_trace_id,
            )

        req = getattr(item, "equip_requirements", {}) or {}
        if isinstance(req, dict) and req:
            min_level = int(req.get("level", 0) or 0)
            player_level = int(getattr(game_state.player.stats, "level", 1) or 1)
            if player_level < min_level:
                return self._make_action_result(
                    False,
                    f"等级不足，需 {min_level} 级",
                    error_code="EQUIP_REQUIREMENT_NOT_MET",
                    retryable=False,
                    reason="equip_requirement_not_met",
                    impact_summary={"equip": {"slot": slot, "state": "rejected", "requirement": "level"}},
                    action_trace_id=action_trace_id,
                )

            allowed_classes = req.get("classes", [])
            if isinstance(allowed_classes, list) and allowed_classes:
                cls = str(getattr(game_state.player.character_class, "value", "") or "")
                allowed = {str(v).strip().lower() for v in allowed_classes if str(v).strip()}
                if cls.lower() not in allowed:
                    return self._make_action_result(
                        False,
                        "职业不满足装备要求",
                        error_code="EQUIP_REQUIREMENT_NOT_MET",
                        retryable=False,
                        reason="equip_requirement_not_met",
                        impact_summary={"equip": {"slot": slot, "state": "rejected", "requirement": "class"}},
                        action_trace_id=action_trace_id,
                    )

            ability_req = req.get("abilities", {})
            if isinstance(ability_req, dict):
                for attr, need_raw in ability_req.items():
                    if not hasattr(game_state.player.abilities, str(attr)):
                        continue
                    try:
                        need = int(need_raw)
                    except (TypeError, ValueError):
                        continue
                    cur = int(getattr(game_state.player.abilities, str(attr), 0) or 0)
                    if cur < need:
                        return self._make_action_result(
                            False,
                            f"属性不足：{attr} 需 {need}",
                            error_code="EQUIP_REQUIREMENT_NOT_MET",
                            retryable=False,
                            reason="equip_requirement_not_met",
                            impact_summary={"equip": {"slot": slot, "state": "rejected", "requirement": f"ability:{attr}"}},
                            action_trace_id=action_trace_id,
                        )

        equipped = game_state.player.equipped_items.get(slot)
        if equipped and equipped.id == item.id:
            game_state.player.equipped_items[slot] = None
            effect_engine.revert_effects_by_source(game_state.player, f"equip:{slot}:{item.id}")
            self._rebuild_combat_snapshot(game_state)
            return self._make_action_result(
                True,
                f"卸下了 {item.name}",
                events=[f"{item.name} 已从 {slot} 卸下"],
                llm_interaction_required=False,
                item_name=item.name,
                item_consumed=False,
                effects=["unequip"],
                impact_summary={"inventory": "unchanged", "equip": {"slot": slot, "state": "unequipped"}},
                action_trace_id=action_trace_id,
            )

        if equipped and getattr(equipped, "id", None) != item.id:
            effect_engine.revert_effects_by_source(game_state.player, f"equip:{slot}:{equipped.id}")
            game_state.player.equipped_items[slot] = None
            if equipped in game_state.player.inventory:
                game_state.player.inventory.remove(equipped)
            game_state.player.inventory.append(equipped)

        unique_key = str(getattr(item, "unique_key", "") or "")
        if unique_key:
            for eq_slot, eq_item in list((game_state.player.equipped_items or {}).items()):
                if eq_slot == slot or eq_item is None:
                    continue
                if str(getattr(eq_item, "unique_key", "") or "") == unique_key:
                    effect_engine.revert_effects_by_source(game_state.player, f"equip:{eq_slot}:{eq_item.id}")
                    game_state.player.equipped_items[eq_slot] = None
                    if eq_item in game_state.player.inventory:
                        game_state.player.inventory.remove(eq_item)
                    game_state.player.inventory.append(eq_item)

        game_state.player.equipped_items[slot] = item
        effect_engine.apply_equipment_passive_effects(game_state.player, item, slot=slot)
        self._rebuild_combat_snapshot(game_state)
        return self._make_action_result(
            True,
            f"装备了 {item.name}",
            events=[f"{item.name} 已装备到 {slot}"],
            llm_interaction_required=False,
            item_name=item.name,
            item_consumed=False,
            effects=["equip"],
            impact_summary={"inventory": "unchanged", "equip": {"slot": slot, "state": "equipped"}},
            action_trace_id=action_trace_id,
        )

    def _should_open_item_choice_context(self, llm_response: Dict[str, Any], item: Item) -> bool:
        effect_scope = str((llm_response or {}).get("effect_scope", "") or "").strip().lower()
        if effect_scope == ChoiceEventType.ITEM_USE.value or effect_scope == "trigger":
            return True

        effects = (llm_response or {}).get("effects", {})
        if not isinstance(effects, dict):
            effects = {}
        special_effects = effects.get("special_effects", [])
        if isinstance(special_effects, list):
            for entry in special_effects:
                text = str(entry.get("code") if isinstance(entry, dict) else entry or "").strip().lower()
                if not text:
                    continue
                if any(keyword in text for keyword in ("choice", "trigger", "event", "ritual", "curse", "summon")):
                    return True

        if bool(getattr(item, "requires_use_confirmation", False)):
            return True

        return False

    def _create_item_use_choice_context(
        self,
        game_state: GameState,
        item: Item,
        llm_response: Dict[str, Any],
    ) -> EventChoiceContext:
        outcomes = getattr(item, "expected_outcomes", []) or []
        if isinstance(outcomes, list) and outcomes:
            outcome_text = "；".join(str(v) for v in outcomes[:3])
        else:
            outcome_text = "结果仍有不确定性"

        trigger_hint = str(getattr(item, "trigger_hint", "") or "触发条件未完全明朗")
        risk_hint = str(getattr(item, "risk_hint", "") or "风险未知")

        context = EventChoiceContext(
            event_type=ChoiceEventType.ITEM_USE.value,
            title=f"{item.name} 的后续反应",
            description=(
                f"{trigger_hint}\n"
                f"风险评估: {risk_hint}\n"
                f"可能结果: {outcome_text}"
            ),
            context_data={
                "item_id": item.id,
                "item_name": item.name,
                "effect_scope": str((llm_response or {}).get("effect_scope", "active_use") or "active_use"),
                "risk_hint": risk_hint,
                "trigger_hint": trigger_hint,
            },
        )

        context.choices = [
            EventChoice(
                text="继续观察异动",
                description="接受当前变化，并让异动继续发展",
                consequences="你选择顺势而为，观察后续变化。",
                requirements={},
                is_available=True,
            ),
            EventChoice(
                text="谨慎稳定状态",
                description="采取保守策略，优先稳住局面",
                consequences="你压制了进一步的波动，局势暂时稳定。",
                requirements={},
                is_available=True,
            ),
        ]
        return context

    async def _handle_use_item(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理使用物品行动"""
        item_id = parameters.get("item_id", "")
        action_trace_id = str(parameters.get("idempotency_key", "") or "").strip() or f"use-item-{datetime.now().timestamp()}"

        # 查找物品
        item = None
        for inv_item in game_state.player.inventory:
            if inv_item.id == item_id:
                item = inv_item
                break

        if not item:
            return self._make_action_result(
                False,
                "物品未找到",
                error_code="ITEM_NOT_FOUND",
                retryable=False,
                reason="item_not_found",
                action_trace_id=action_trace_id,
            )

        # 冷却与充能检查
        if getattr(item, "current_cooldown", 0) > 0:
            return self._make_action_result(
                False,
                f"{item.name} 冷却中，还需 {item.current_cooldown} 回合",
                error_code="ITEM_ON_COOLDOWN",
                retryable=False,
                reason="item_on_cooldown",
                action_trace_id=action_trace_id,
            )
        if getattr(item, "max_charges", 0) > 0 and getattr(item, "charges", 0) <= 0:
            return self._make_action_result(
                False,
                f"{item.name} 充能不足",
                error_code="ITEM_NO_CHARGES",
                retryable=False,
                reason="item_no_charges",
                action_trace_id=action_trace_id,
            )

        # 装备型物品：切换装备状态
        if getattr(item, "is_equippable", False):
            slot = getattr(item, "equip_slot", "") or "accessory_1"
            return self._apply_equipment_state_change(game_state, item, slot, action_trace_id)

        try:
            # 优先使用固定效果载荷（便于可测与可控）
            if getattr(item, "effect_payload", None):
                llm_response = item.effect_payload
            else:
                # 使用LLM处理物品使用效果
                llm_response = await llm_service.process_item_usage(game_state, item)

            # 使用效果处理器处理LLM返回的结果
            effect_result = item_effect_processor.process_llm_response(
                llm_response, game_state, item
            )

            # 处理位置变化（传送效果）
            if effect_result.position_change:
                new_x, new_y = effect_result.position_change
                old_tile = game_state.current_map.get_tile(*game_state.player.position)
                if old_tile:
                    old_tile.character_id = None

                new_tile = game_state.current_map.get_tile(new_x, new_y)
                if new_tile:
                    new_tile.character_id = game_state.player.id
                    new_tile.is_explored = True
                    new_tile.is_visible = True
                    game_state.player.position = (new_x, new_y)
                    self._update_visibility(game_state, new_x, new_y)
                    effect_result.events.append(f"传送到了位置 ({new_x}, {new_y})")

            if not effect_result.success:
                return self._make_action_result(
                    False,
                    effect_result.message,
                    events=effect_result.events,
                    error_code="ITEM_EFFECT_FAILED",
                    retryable=True,
                    llm_interaction_required=True,
                    item_name=item.name,
                    item_consumed=False,
                    effects=effect_result.events,
                    reason="item_effect_failed",
                    impact_summary={"inventory": "unchanged", "charges": "unchanged", "cooldown": "unchanged"},
                    action_trace_id=action_trace_id,
                )

            # 使用后回写情报字段，形成可持续的“鉴定”闭环
            if isinstance(llm_response, dict):
                raw_hint_level = str(llm_response.get("hint_level", getattr(item, "hint_level", "vague")) or "vague").strip().lower()
                item.hint_level = raw_hint_level if raw_hint_level in {"none", "vague", "clear"} else "vague"

                trigger_hint = str(llm_response.get("trigger_hint", "") or "").strip()
                if trigger_hint:
                    item.trigger_hint = trigger_hint

                risk_hint = str(llm_response.get("risk_hint", "") or "").strip()
                if risk_hint:
                    item.risk_hint = risk_hint

                outcomes_raw = llm_response.get("expected_outcomes", None)
                if isinstance(outcomes_raw, list):
                    normalized_outcomes = [str(v).strip() for v in outcomes_raw if str(v).strip()]
                    if normalized_outcomes:
                        item.expected_outcomes = normalized_outcomes[:6]
                elif outcomes_raw:
                    single_outcome = str(outcomes_raw).strip()
                    if single_outcome:
                        item.expected_outcomes = [single_outcome]

                if "requires_use_confirmation" in llm_response:
                    item.requires_use_confirmation = bool(llm_response.get("requires_use_confirmation", False))

                consumption_hint = str(llm_response.get("consumption_hint", "") or "").strip()
                if consumption_hint:
                    item.consumption_hint = consumption_hint

            # 消耗充能与设置冷却（仅在效果成功时）
            if getattr(item, "max_charges", 0) > 0:
                item.charges = max(0, int(item.charges) - 1)
            if getattr(item, "cooldown_turns", 0) > 0:
                item.current_cooldown = int(item.cooldown_turns)

            # 移除消耗的物品（仅成功路径）
            if effect_result.item_consumed and item in game_state.player.inventory:
                game_state.player.inventory.remove(item)

            if self._should_open_item_choice_context(llm_response, item):
                choice_context = self._create_item_use_choice_context(game_state, item, llm_response)
                game_state.pending_choice_context = choice_context
                event_choice_system.active_contexts[choice_context.id] = choice_context

            return self._make_action_result(
                True,
                effect_result.message,
                events=effect_result.events,
                llm_interaction_required=True,
                item_name=item.name,
                item_consumed=effect_result.item_consumed,
                effects=effect_result.events,
                impact_summary={
                    "charges": {"current": getattr(item, "charges", 0), "max": getattr(item, "max_charges", 0)},
                    "cooldown": getattr(item, "current_cooldown", 0),
                    "consumed": bool(effect_result.item_consumed),
                    "hint_level": str(getattr(item, "hint_level", "vague") or "vague"),
                    "trigger_hint": str(getattr(item, "trigger_hint", "") or ""),
                    "risk_hint": str(getattr(item, "risk_hint", "") or ""),
                    "consumption_hint": str(getattr(item, "consumption_hint", "") or ""),
                    "expected_outcomes": getattr(item, "expected_outcomes", []) or [],
                },
                action_trace_id=action_trace_id,
            )

        except Exception as e:
            logger.error(f"处理物品使用时出错: {e}")
            return self._make_action_result(
                False,
                f"使用{item.name}时发生错误",
                events=[f"物品使用失败: {str(e)}"],
                error_code="ITEM_USE_EXCEPTION",
                retryable=True,
                reason="item_use_exception",
                action_trace_id=action_trace_id,
            )

    async def _handle_drop_item(
        self,
        game_state: GameState,
        game_key: Tuple[str, str],
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理丢弃物品行动"""
        item_id = parameters.get("item_id", "")
        action_trace_id = str(parameters.get("idempotency_key", "") or "").strip() or f"drop-item-{datetime.now().timestamp()}"

        # 查找物品
        item = None
        for inv_item in game_state.player.inventory:
            if inv_item.id == item_id:
                item = inv_item
                break

        if not item:
            return self._make_action_result(
                False,
                "物品未找到",
                error_code="ITEM_NOT_FOUND",
                retryable=False,
                reason="item_not_found",
                action_trace_id=action_trace_id,
            )

        if getattr(item, "is_quest_item", False) and not bool(parameters.get("force", False)):
            lock_reason = getattr(item, "quest_lock_reason", "") or "任务保护启用"
            return self._make_action_result(
                False,
                f"{item.name} 是任务物品，无法直接丢弃（{lock_reason}）",
                error_code="QUEST_ITEM_LOCKED",
                retryable=False,
                reason="quest_item_locked",
                requires_confirmation=True,
                confirmation_token=f"drop:{item.id}",
                action_trace_id=action_trace_id,
            )

        try:
            # 从玩家背包中移除物品
            game_state.player.inventory.remove(item)

            # 将物品放置到当前位置的地图瓦片上
            player_x, player_y = game_state.player.position
            current_tile = game_state.current_map.get_tile(player_x, player_y)

            if current_tile:
                # 确保瓦片有items列表
                if not hasattr(current_tile, 'items') or current_tile.items is None:
                    current_tile.items = []

                # 将物品添加到地图瓦片
                current_tile.items.append(item)

                undo_token = f"undo-{int(datetime.now().timestamp() * 1000)}-{random.randint(1000, 9999)}"
                self._get_drop_undo_cache(game_key)[undo_token] = {
                    "item": item.to_dict(),
                    "position": [player_x, player_y],
                    "expires_turn": int(game_state.turn_count) + 2,
                }

                return self._make_action_result(
                    True,
                    f"丢弃了 {item.name}",
                    events=[f"你将 {item.name} 丢弃在了地上", "可在2回合内撤销本次丢弃"],
                    impact_summary={"inventory": "item_removed", "map": "item_added_to_tile"},
                    action_trace_id=action_trace_id,
                    undo_token=undo_token,
                    undo_expires_turn=int(game_state.turn_count) + 2,
                )
            else:
                # 如果无法获取当前瓦片，直接移除物品
                return self._make_action_result(
                    True,
                    f"丢弃了 {item.name}",
                    events=[f"你丢弃了 {item.name}"],
                    impact_summary={"inventory": "item_removed", "map": "tile_unavailable"},
                    action_trace_id=action_trace_id,
                )

        except Exception as e:
            logger.error(f"处理物品丢弃时出错: {e}")
            return self._make_action_result(
                False,
                f"丢弃{item.name}时发生错误",
                events=[f"物品丢弃失败: {str(e)}"],
                error_code="ITEM_DROP_EXCEPTION",
                retryable=True,
                reason="item_drop_exception",
                action_trace_id=action_trace_id,
            )

    async def _handle_undo_drop_item(
        self,
        game_state: GameState,
        game_key: Tuple[str, str],
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """撤销最近的丢弃动作"""
        undo_token = str(parameters.get("undo_token", "") or "").strip()
        if not undo_token:
            return self._make_action_result(
                False,
                "缺少撤销令牌",
                error_code="UNDO_TOKEN_MISSING",
                retryable=False,
                reason="undo_token_missing",
            )

        cache = self._get_drop_undo_cache(game_key)
        payload = cache.get(undo_token)
        if not payload:
            return self._make_action_result(
                False,
                "撤销令牌无效或已过期",
                error_code="UNDO_TOKEN_INVALID",
                retryable=False,
                reason="undo_token_invalid",
            )

        if int(payload.get("expires_turn", -1)) < int(game_state.turn_count):
            cache.pop(undo_token, None)
            return self._make_action_result(
                False,
                "撤销窗口已过期",
                error_code="UNDO_EXPIRED",
                retryable=False,
                reason="undo_expired",
            )

        item_data = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        item = data_manager._dict_to_item(item_data)

        px, py = payload.get("position", game_state.player.position)
        tile = game_state.current_map.get_tile(int(px), int(py))
        if tile and hasattr(tile, "items") and tile.items:
            matched = next((it for it in tile.items if it.id == item.id), None)
            if matched:
                tile.items.remove(matched)
                item = matched

        game_state.player.inventory.append(item)
        cache.pop(undo_token, None)

        return self._make_action_result(
            True,
            f"已撤销丢弃：{item.name}",
            events=[f"{item.name} 已回到背包"],
            impact_summary={"inventory": "item_restored"},
        )

    async def _handle_cast_spell(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理施法行动"""
        spell_id = parameters.get("spell_id", "")
        target_id = parameters.get("target_id", "")

        # 查找法术
        spell = None
        for player_spell in game_state.player.spells:
            if player_spell.id == spell_id:
                spell = player_spell
                break

        if not spell:
            return {"success": False, "message": "法术未找到"}

        # 检查法力值
        mp_cost = spell.level * 10
        if game_state.player.stats.mp < mp_cost:
            return {"success": False, "message": "法力值不足"}

        # 统一写入口：消耗法力值
        resource_result = game_state_modifier.apply_player_resource_delta(
            game_state,
            hp_delta=0,
            mp_delta=-int(mp_cost),
            source=f"cast_spell:{spell.name}",
        )
        if not resource_result.success:
            return self._make_action_result(
                False,
                "施法资源更新失败",
                error_code="SPELL_RESOURCE_UPDATE_FAILED",
                retryable=True,
                reason="spell_resource_update_failed",
            )

        events = [f"施放了 {spell.name}"]

        # 根据法术类型处理效果
        if spell.damage and target_id:
            # 攻击法术
            target_monster = None
            for monster in game_state.monsters:
                if monster.id == target_id:
                    target_monster = monster
                    break

            if target_monster:
                damage = random.randint(spell.level * 5, spell.level * 10)
                target_monster.stats.hp -= damage
                events.append(f"对 {target_monster.name} 造成了 {damage} 点魔法伤害")

                if target_monster.stats.hp <= 0:
                    events.append(f"{target_monster.name} 被击败了！")
                    game_state.monsters.remove(target_monster)

        return {
            "success": True,
            "message": f"施放了 {spell.name}",
            "events": events
        }

    async def _handle_interact(self, game_state: GameState, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """处理交互行动"""
        x, y = game_state.player.position
        tile = game_state.current_map.get_tile(x, y)

        if not tile:
            return {"success": False, "message": "无法在此位置交互"}

        events = []

        # 检查地形交互
        if tile.terrain == TerrainType.DOOR:
            events.append("打开了门")
            tile.terrain = TerrainType.FLOOR
        elif tile.terrain == TerrainType.TREASURE:
            # 使用LLM生成宝藏物品
            pickup_context = f"玩家在{game_state.current_map.name}的宝藏箱中发现了物品"
            treasure_item = await llm_service.generate_item_on_pickup(game_state, pickup_context)

            if treasure_item:
                game_state.player.inventory.append(treasure_item)
                events.append(f"从宝藏中获得了 {treasure_item.name}！")
                events.append(treasure_item.description)
            else:
                events.append("宝藏箱是空的...")

            tile.terrain = TerrainType.FLOOR

        elif tile.items:
            # 拾取地图上的物品
            items_to_remove = []
            for item in tile.items:
                # 检查是否已经被拾取过
                if item.id not in tile.items_collected:
                    # 如果物品不是LLM生成的，使用LLM重新生成
                    if not item.llm_generated:
                        pickup_context = f"玩家在{game_state.current_map.name}的地面上发现了{item.name}"
                        new_item = await llm_service.generate_item_on_pickup(game_state, pickup_context)
                        if new_item:
                            game_state.player.inventory.append(new_item)
                            events.append(f"拾取了 {new_item.name}")
                            events.append(new_item.description)
                        else:
                            # 如果LLM生成失败，使用原物品
                            game_state.player.inventory.append(item)
                            events.append(f"拾取了 {item.name}")
                    else:
                        # 直接拾取LLM生成的物品
                        game_state.player.inventory.append(item)
                        events.append(f"拾取了 {item.name}")
                        events.append(item.description)

                    # 标记为已拾取
                    tile.items_collected.append(item.id)
                    items_to_remove.append(item)

            # 移除已拾取的物品
            for item in items_to_remove:
                tile.items.remove(item)

        if not events:
            events.append("这里没有可以交互的东西")

        return {
            "success": True,
            "message": "进行了交互",
            "events": events,
            "llm_interaction_required": len(events) > 1  # 如果有物品拾取则需要LLM交互
        }

    async def transition_map(self, game_state: GameState, transition_type: str) -> Dict[str, Any]:
        """手动切换地图

        后端专注于"生成型"逻辑：生成新地图、怪物、更新任务进度
        前端已经完成了所有"计算型"验证（位置检查、地形验证等）
        """
        logger.info(f"transition_map called: type={transition_type}")

        events = []

        # 直接执行地图切换，不做验证（前端已验证）
        if transition_type == "stairs_down":
            events.append(await self._descend_stairs(game_state))
        elif transition_type == "stairs_up":
            events.append(await self._ascend_stairs(game_state))
        else:
            logger.warning(f"Unknown transition type: {transition_type}")
            return {
                "success": False,
                "message": f"未知的切换类型: {transition_type}"
            }

        # 【修复】地图切换后检查是否有任务完成需要处理选择
        if hasattr(game_state, 'pending_quest_completion') and game_state.pending_quest_completion:
            completed_quest = game_state.pending_quest_completion
            try:
                # 创建任务完成选择上下文
                from event_choice_system import event_choice_system
                choice_context = await event_choice_system.create_quest_completion_choice(
                    game_state, completed_quest
                )

                # 将选择上下文存储到游戏状态中
                game_state.pending_choice_context = choice_context
                event_choice_system.active_contexts[choice_context.id] = choice_context

                # 清理任务完成标志
                game_state.pending_quest_completion = None

                logger.info(f"Created quest completion choice after map transition for: {completed_quest.title}")

            except Exception as e:
                logger.error(f"Error creating quest completion choice after map transition: {e}")
                # 清理标志，避免重复处理
                game_state.pending_quest_completion = None

        # 清除待切换状态（重要！）
        game_state.pending_map_transition = None
        logger.info(f"Map transition completed successfully: {transition_type}")

        return {
            "success": True,
            "message": "成功切换地图",
            "events": events
        }

    async def _handle_rest(self, game_state: GameState) -> Dict[str, Any]:
        """处理休息行动"""
        player = game_state.player

        # 恢复生命值和法力值
        hp_restored = min(player.stats.max_hp - player.stats.hp, player.stats.max_hp // 4)
        mp_restored = min(player.stats.max_mp - player.stats.mp, player.stats.max_mp // 2)

        rest_result = game_state_modifier.apply_player_resource_delta(
            game_state,
            hp_delta=int(hp_restored),
            mp_delta=int(mp_restored),
            source="rest",
        )
        if not rest_result.success:
            return self._make_action_result(
                False,
                "休息恢复失败",
                error_code="REST_RESOURCE_UPDATE_FAILED",
                retryable=True,
                reason="rest_resource_update_failed",
            )

        events = []
        if hp_restored > 0:
            events.append(f"恢复了 {hp_restored} 点生命值")
        if mp_restored > 0:
            events.append(f"恢复了 {mp_restored} 点法力值")

        return {
            "success": True,
            "message": "祈祷了一会儿",
            "events": events
        }

    async def _trigger_trap(self, game_state: GameState) -> str:
        """触发陷阱 - 【已废弃】遗留方法

        ⚠️ DEPRECATED / 已废弃 ⚠️
        ==========================
        此方法已被废弃，请使用 TrapManager.trigger_trap() 代替。

        废弃原因：
        - 陷阱处理逻辑已统一迁移到 TrapManager 类
        - 前端 LocalGameEngine.js 直接调用 /api/trap/trigger 接口
        - 此方法仅为向后兼容保留，未来版本可能移除

        推荐替代方案：
        - 后端：使用 trap_manager.trigger_trap(game_state, tile, save_result)
        - 前端：调用 POST /api/trap/trigger 接口

        保留原因：
        - 兼容不支持 LocalGameEngine 的旧版本客户端
        """
        import warnings
        warnings.warn(
            "_trigger_trap is deprecated, use TrapManager.trigger_trap instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.warning("⚠️ _trigger_trap called - DEPRECATED, use TrapManager.trigger_trap instead")

        # 获取当前玩家位置的瓦片
        tile = game_state.current_map.get_tile(*game_state.player.position)
        if not tile or not tile.is_trap():
            return "没有陷阱"

        # 使用 TrapManager 统一处理
        from trap_manager import get_trap_manager
        trap_manager = get_trap_manager()

        # 获取陷阱数据
        from trap_schema import trap_validator
        raw_trap_data = tile.get_trap_data()
        trap_data = trap_validator.validate_and_normalize(raw_trap_data)

        # 尝试敏捷豁免（如果陷阱允许）
        save_result = None
        if trap_data.get("can_be_avoided", True) and trap_data.get("save_dc", 0) > 0:
            save_result = trap_manager.attempt_avoid(game_state.player, trap_data["save_dc"])

        # 触发陷阱
        trigger_result = trap_manager.trigger_trap(game_state, tile, save_result=save_result)

        return trigger_result.get("description", "触发了陷阱！")

    async def _generate_trap_narrative(self, game_state: GameState, trap_result: Dict[str, Any]) -> str:
        """生成陷阱触发叙述（由 TrapNarrativeService 按配置路由）

        说明：
        - 叙述来源由配置决定（local 或 llm）。
        - 回退策略由 TrapNarrativeService 统一控制，避免多层兜底导致语义不一致。
        """
        from trap_narrative_service import trap_narrative_service

        trap_data = {
            "trap_name": trap_result.get("trap_name", trap_result.get("name", "未知陷阱")),
            "trap_type": trap_result.get("trap_type", trap_result.get("type", "damage")),
            "damage_type": trap_result.get("damage_type", "physical"),
        }
        return await trap_narrative_service.generate_narrative(
            game_state=game_state,
            trap_data=trap_data,
            trigger_result=trap_result,
            save_attempted=trap_result.get("save_attempted", False),
            save_result={"success": trap_result.get("save_success", False)} if trap_result.get("save_attempted", False) else None,
        )

    async def _trigger_tile_event(self, game_state: GameState, tile: MapTile) -> str:
        """触发瓦片事件"""
        try:
            # 标记事件已触发（在游戏状态的地图中）
            map_tile = game_state.current_map.get_tile(tile.x, tile.y)
            if map_tile:
                map_tile.event_triggered = True
                logger.info(f"Marked event as triggered at ({tile.x}, {tile.y})")

            if tile.event_type == "combat":
                return await self._handle_combat_event(game_state, tile)
            elif tile.event_type == "treasure":
                return await self._handle_treasure_event(game_state, tile)
            elif tile.event_type == "story":
                return await self._handle_story_event(game_state, tile)
            elif tile.event_type == "trap":
                return await self._handle_trap_event(game_state, tile)
            elif tile.event_type == "mystery":
                return await self._handle_mystery_event(game_state, tile)
            else:
                return "发现了一些有趣的东西..."
        except Exception as e:
            logger.error(f"Error triggering tile event: {e}")
            return "发生了意外的事情..."

    async def _handle_combat_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理战斗事件"""
        event_data = tile.event_data
        monster_count = event_data.get("monster_count", 1)
        difficulty = event_data.get("difficulty", "medium")

        # 生成怪物
        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level, difficulty
        )

        # 限制怪物数量
        monsters = monsters[:monster_count]

        # 将怪物添加到游戏状态
        for monster in monsters:
            # 在附近找位置放置怪物
            spawn_positions = content_generator.get_spawn_positions(game_state.current_map, 1)
            if spawn_positions:
                monster.position = spawn_positions[0]
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = monster.id
                game_state.monsters.append(monster)

        return f"遭遇了 {len(monsters)} 只怪物！战斗开始！"

    async def _handle_treasure_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理宝藏事件"""
        event_data = tile.event_data
        treasure_type = event_data.get("treasure_type", "gold")
        value = event_data.get("value", 100)

        result_message = ""

        if treasure_type == "gold":
            # 添加金币逻辑（这里简化处理）
            result_message = f"发现了 {value} 金币！"
        elif treasure_type == "item":
            # 生成随机物品
            items = await content_generator.generate_random_items(1, game_state.player.stats.level)
            if items:
                game_state.player.inventory.extend(items)
                result_message = f"发现了 {items[0].name}！"
        elif treasure_type == "magic_item":
            # 生成魔法物品
            items = await content_generator.generate_random_items(1, game_state.player.stats.level)
            if items:
                items[0].rarity = "rare"  # 设为稀有
                game_state.player.inventory.extend(items)
                result_message = f"发现了稀有物品 {items[0].name}！"
        else:
            result_message = "发现了一些有价值的东西！"

        # 触发宝藏发现进度事件
        await self._trigger_progress_event(
            game_state, ProgressEventType.TREASURE_FOUND,
            {"treasure_type": treasure_type, "value": value}
        )

        return result_message

    async def _handle_story_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理故事事件"""
        event_data = tile.event_data
        story_type = event_data.get("story_type", "discovery")

        # 检查是否是任务专属事件
        quest_event_id = event_data.get("quest_event_id")
        is_quest_event = quest_event_id is not None

        if is_quest_event:
            # 处理任务专属事件 - 使用选择系统
            event_name = event_data.get("name", "任务事件")
            event_description = event_data.get("description", "")
            progress_value = event_data.get("progress_value", 0.0)
            is_mandatory = event_data.get("is_mandatory", True)

            # 创建事件选择上下文
            try:
                choice_context = await event_choice_system.create_story_event_choice(game_state, tile)

                # 将选择上下文存储到游戏状态中
                game_state.pending_choice_context = choice_context
                event_choice_system.active_contexts[choice_context.id] = choice_context

                # 触发任务专属事件进度（使用更高的进度值）
                await self._trigger_progress_event(
                    game_state, ProgressEventType.STORY_EVENT,
                    {
                        "story_type": "quest_event",
                        "quest_event_id": quest_event_id,
                        "progress_value": progress_value,
                        "location": (tile.x, tile.y)
                    }
                )

                result_message = f"你发现了重要的线索：{event_name}。请做出选择..."

            except Exception as e:
                logger.error(f"Error creating story event choice: {e}")
                result_message = f"你发现了重要的线索：{event_name}"

        else:
            # 处理普通故事事件 - 使用选择系统
            try:
                choice_context = await event_choice_system.create_story_event_choice(game_state, tile)

                # 将选择上下文存储到游戏状态中
                game_state.pending_choice_context = choice_context
                event_choice_system.active_contexts[choice_context.id] = choice_context

                # 触发普通故事事件进度
                await self._trigger_progress_event(
                    game_state, ProgressEventType.STORY_EVENT,
                    {"story_type": story_type, "location": (tile.x, tile.y)}
                )

                result_message = "你遇到了一个有趣的情况，请做出选择..."

            except Exception as e:
                logger.error(f"Error creating story event choice: {e}")
                result_message = "你发现了一些古老的痕迹..."

        return result_message

    async def _handle_trap_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理陷阱事件 - 【已废弃】遗留接口

        ⚠️ DEPRECATED / 已废弃 ⚠️
        ==========================
        此方法已被废弃。陷阱处理应由前端 LocalGameEngine.js 完成。

        现代架构流程：
        1. 前端检测到陷阱瓦片
        2. 前端调用 POST /api/check-trap 进行被动侦测
        3. 如果未发现陷阱，前端调用 POST /api/trap/trigger 触发陷阱
        4. 如果发现陷阱，前端显示选择对话框（通过 /api/trap-choice/register）

        保留原因：
        - 兼容不支持 LocalGameEngine 的旧版本客户端
        - 此方法内部已升级为调用 TrapManager，确保行为一致性
        """
        import warnings
        warnings.warn(
            "_handle_trap_event is deprecated, trap handling should be done by frontend",
            DeprecationWarning,
            stacklevel=2
        )
        logger.warning("⚠️ _handle_trap_event called - DEPRECATED, should be handled by frontend LocalGameEngine")

        # 使用 TrapManager 统一处理
        from trap_manager import get_trap_manager
        trap_manager = get_trap_manager()

        # 获取陷阱数据
        from trap_schema import trap_validator
        raw_trap_data = tile.get_trap_data()
        trap_data = trap_validator.validate_and_normalize(raw_trap_data)

        # 尝试敏捷豁免（如果陷阱允许）
        save_result = None
        if trap_data.get("can_be_avoided", True) and trap_data.get("save_dc", 0) > 0:
            save_result = trap_manager.attempt_avoid(game_state.player, trap_data["save_dc"])
            logger.info(f"Trap save attempt: {save_result}")

        # 触发陷阱
        trigger_result = trap_manager.trigger_trap(game_state, tile, save_result=save_result)

        return trigger_result.get("description", "触发了一个神秘的陷阱！")

    async def _handle_mystery_event(self, game_state: GameState, tile: MapTile) -> str:
        """处理神秘事件"""
        event_data = tile.event_data
        mystery_type = event_data.get("mystery_type", "puzzle")

        # 使用选择系统处理神秘事件
        try:
            choice_context = await event_choice_system.create_story_event_choice(game_state, tile)

            # 将选择上下文存储到游戏状态中
            game_state.pending_choice_context = choice_context
            event_choice_system.active_contexts[choice_context.id] = choice_context

            return "你遇到了一个神秘的现象，请做出选择..."

        except Exception as e:
            logger.error(f"Error creating mystery event choice: {e}")
            return "你遇到了一个神秘的现象..."

    async def _find_treasure(self, game_state: GameState) -> str:
        """发现宝藏"""
        # 使用LLM生成宝藏物品，与交互系统保持一致
        pickup_context = f"玩家在{game_state.current_map.name}的宝藏箱中发现了物品"
        treasure_item = await llm_service.generate_item_on_pickup(game_state, pickup_context)

        if treasure_item:
            game_state.player.inventory.append(treasure_item)
            # 返回详细的宝藏发现描述，包含物品名称和描述
            return f"发现了宝藏：{treasure_item.name}！{treasure_item.description}"
        else:
            # 如果LLM生成失败，回退到原有逻辑
            treasure_items = await content_generator.generate_random_items(
                count=1,
                item_level=game_state.player.stats.level
            )

            if treasure_items:
                item = treasure_items[0]
                game_state.player.inventory.append(item)
                return f"发现了宝藏：{item.name}"
            else:
                return "发现了一个空的宝藏箱..."

    def _resolve_user_id_for_game_state(self, game_state: GameState) -> str:
        for (user_id, _game_id), gs in self.active_games.items():
            if gs is game_state:
                return user_id
        return ""

    async def _descend_stairs(self, game_state: GameState) -> str:
        """下楼梯"""
        # 记录旧的楼层深度
        old_depth = game_state.current_map.depth

        # 生成新的地图层
        new_depth = old_depth + 1

        # 检查是否超过最大楼层限制
        max_floors = config.game.max_quest_floors
        if new_depth > max_floors:
            return f"你已经到达了本次冒险的最深阶段（第{max_floors}层）！"

        # 清除旧地图上的角色标记（在生成新地图前）
        old_tile = game_state.current_map.get_tile(*game_state.player.position)
        if old_tile:
            old_tile.character_id = None

        for monster in game_state.monsters:
            if monster.position:
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = None

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        user_id = self._resolve_user_id_for_game_state(game_state)
        new_map = await self._generate_map_with_provider(
            width=game_state.current_map.width,
            height=game_state.current_map.height,
            depth=new_depth,
            theme=f"冒险区域（第{new_depth}阶段/层级）",
            quest_context=quest_context,
            source="descend_stairs",
            user_id=user_id,
            game_state=game_state,
        )

        # 更新游戏状态 - 确保正确更新
        game_state.current_map = new_map
        logger.info(f"Map updated: {new_map.name} (depth: {new_map.depth})")

        # 设置玩家位置到新地图的上楼梯附近
        # 下楼时，玩家应该出现在新地图的上楼梯附近
        spawn_position = content_generator.get_stairs_spawn_position(new_map, TerrainType.STAIRS_UP)
        if not spawn_position:
            # 如果没有上楼梯或附近没有空位，使用随机位置
            spawn_positions = content_generator.get_spawn_positions(new_map, 1)
            spawn_position = spawn_positions[0] if spawn_positions else (1, 1)

        game_state.player.position = spawn_position
        tile = new_map.get_tile(*game_state.player.position)
        if tile:
            tile.character_id = game_state.player.id
            tile.is_explored = True
            tile.is_visible = True

        # 【修复】更新周围瓦片的可见性
        self._update_visibility(game_state, spawn_position[0], spawn_position[1])

        # 清空旧怪物列表（重要！）
        game_state.monsters.clear()

        # 生成新的怪物
        monsters = await self._generate_encounter_monsters_by_map_hints(
            game_state,
            new_map,
            default_difficulty="medium",
        )

        # 生成任务专属怪物（如果有活跃任务）
        quest_monsters = await self._generate_quest_monsters(game_state, new_map)
        monsters.extend(quest_monsters)

        monster_positions = self._get_monster_spawn_positions(new_map, len(monsters))
        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = new_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)

        # 【修复】使用新的进程管理器更新任务进度，传递楼层变化信息
        await self._trigger_progress_event(
            game_state,
            ProgressEventType.MAP_TRANSITION,
            {'old_depth': old_depth, 'new_depth': new_depth}
        )

        logger.info(f"Descended to floor {new_depth}: {new_map.name}")
        return f"进入了{new_map.name}"

    async def _ascend_stairs(self, game_state: GameState) -> str:
        """上楼梯"""
        # 记录旧的楼层深度
        old_depth = game_state.current_map.depth

        new_depth = old_depth - 1

        if new_depth < 1:
            return "你已经回到了地面！"

        # 清除旧地图上的角色标记（在生成新地图前）
        old_tile = game_state.current_map.get_tile(*game_state.player.position)
        if old_tile:
            old_tile.character_id = None

        for monster in game_state.monsters:
            if monster.position:
                monster_tile = game_state.current_map.get_tile(*monster.position)
                if monster_tile:
                    monster_tile.character_id = None

        # 获取当前活跃任务的上下文
        quest_context = None
        active_quest = next((q for q in game_state.quests if q.is_active), None)
        if active_quest:
            quest_context = active_quest.to_dict()

        # 这里可以实现返回上一层的逻辑
        # 简化实现：重新生成上一层
        user_id = self._resolve_user_id_for_game_state(game_state)
        new_map = await self._generate_map_with_provider(
            width=game_state.current_map.width,
            height=game_state.current_map.height,
            depth=new_depth,
            theme=f"冒险区域（第{new_depth}阶段/层级）",
            quest_context=quest_context,
            source="ascend_stairs",
            user_id=user_id,
            game_state=game_state,
        )

        # 更新游戏状态 - 确保正确更新
        game_state.current_map = new_map
        logger.info(f"Map updated: {new_map.name} (depth: {new_map.depth})")

        # 设置玩家位置到新地图的下楼梯附近
        # 上楼时，玩家应该出现在新地图的下楼梯附近
        spawn_position = content_generator.get_stairs_spawn_position(new_map, TerrainType.STAIRS_DOWN)
        if not spawn_position:
            # 如果没有下楼梯或附近没有空位，使用随机位置
            spawn_positions = content_generator.get_spawn_positions(new_map, 1)
            spawn_position = spawn_positions[0] if spawn_positions else (1, 1)

        game_state.player.position = spawn_position
        tile = new_map.get_tile(*game_state.player.position)
        if tile:
            tile.character_id = game_state.player.id
            tile.is_explored = True
            tile.is_visible = True

        # 【修复】更新周围瓦片的可见性
        self._update_visibility(game_state, spawn_position[0], spawn_position[1])

        # 清空旧怪物列表（重要！）
        game_state.monsters.clear()

        # 生成新的怪物（上楼时也应该有怪物）
        monsters = await self._generate_encounter_monsters_by_map_hints(
            game_state,
            new_map,
            default_difficulty="medium",
        )

        # 生成任务专属怪物（如果有活跃任务）
        quest_monsters = await self._generate_quest_monsters(game_state, new_map)
        monsters.extend(quest_monsters)

        monster_positions = self._get_monster_spawn_positions(new_map, len(monsters))
        for monster, position in zip(monsters, monster_positions):
            monster.position = position
            tile = new_map.get_tile(*position)
            if tile:
                tile.character_id = monster.id
            game_state.monsters.append(monster)

        # 【修复】使用新的进程管理器更新任务进度，传递楼层变化信息
        await self._trigger_progress_event(
            game_state,
            ProgressEventType.MAP_TRANSITION,
            {'old_depth': old_depth, 'new_depth': new_depth}
        )

        logger.info(f"Ascended to floor {new_depth}: {new_map.name}")
        return f"返回到了{new_map.name}"

    def _build_generation_alert_snapshot(self, game_state: Optional[GameState]) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "has_p1": False,
            "items": [],
            "rates": {},
        }
        if game_state is None or not isinstance(getattr(game_state, "generation_metrics", None), dict):
            return snapshot

        generation_metrics = game_state.generation_metrics
        map_metrics = generation_metrics.get("map_generation") if isinstance(generation_metrics.get("map_generation"), dict) else {}
        progress_metrics = generation_metrics.get("progress_metrics") if isinstance(generation_metrics.get("progress_metrics"), dict) else {}

        map_total = max(1, int(map_metrics.get("total", 0) or 0))
        unreachable_rate = float(map_metrics.get("unreachable_reports", 0) or 0) / float(map_total)
        stairs_violation_rate = float(map_metrics.get("stairs_violations", 0) or 0) / float(map_total)

        progress_total = max(1, int(progress_metrics.get("total_events", 0) or 0))
        anomaly_rate = float(progress_metrics.get("anomaly_events", 0) or 0) / float(progress_total)

        guard_hit = int(progress_metrics.get("final_objective_direct_completion", 0) or 0)
        guard_blocked = int(progress_metrics.get("final_objective_guard_blocked", 0) or 0)
        guard_total = max(1, guard_hit + guard_blocked)
        final_guard_block_rate = float(guard_blocked) / float(guard_total)

        snapshot["rates"] = {
            "key_objective_unreachable_rate": round(unreachable_rate, 6),
            "stairs_violation_rate": round(stairs_violation_rate, 6),
            "progress_anomaly_rate": round(anomaly_rate, 6),
            "final_objective_guard_block_rate": round(final_guard_block_rate, 6),
        }

        def _push(metric: str, value: float, warn: float, block: float):
            severity = "ok"
            if value >= block:
                severity = "p1"
            elif value >= warn:
                severity = "p2"
            if severity != "ok":
                snapshot["items"].append(
                    {
                        "metric": metric,
                        "severity": severity,
                        "value": round(value, 6),
                        "warn_threshold": warn,
                        "block_threshold": block,
                    }
                )

        _push(
            "key_objective_unreachable_rate",
            unreachable_rate,
            float(getattr(config.game, "map_unreachable_rate_warn", 0.001)),
            float(getattr(config.game, "map_unreachable_rate_block", 0.01)),
        )
        _push(
            "stairs_violation_rate",
            stairs_violation_rate,
            float(getattr(config.game, "map_stairs_violation_warn", 0.001)),
            float(getattr(config.game, "map_stairs_violation_block", 0.01)),
        )
        _push(
            "progress_anomaly_rate",
            anomaly_rate,
            float(getattr(config.game, "progress_anomaly_rate_warn", 0.02)),
            float(getattr(config.game, "progress_anomaly_rate_block", 0.1)),
        )
        _push(
            "final_objective_guard_block_rate",
            final_guard_block_rate,
            float(getattr(config.game, "final_objective_guard_block_warn", 0.1)),
            float(getattr(config.game, "final_objective_guard_block_block", 0.3)),
        )

        snapshot["has_p1"] = any(item.get("severity") == "p1" for item in snapshot["items"])
        return snapshot

    def _resolve_map_generation_release_strategy(
        self,
        user_id: str,
        game_state: Optional[GameState],
        source: str,
    ) -> Dict[str, Any]:
        provider = str(getattr(config.game, "map_generation_provider", "llm") or "llm").lower()
        fallback_to_llm = bool(getattr(config.game, "map_generation_fallback_to_llm", True))
        stage = str(getattr(config.game, "map_generation_release_stage", "debug") or "debug").lower()
        if stage not in {"debug", "canary", "stable"}:
            stage = "debug"
        canary_percent = int(getattr(config.game, "map_generation_canary_percent", 0) or 0)
        canary_percent = max(0, min(100, canary_percent))
        force_legacy = bool(getattr(config.game, "map_generation_force_legacy_chain", False))
        disable_high_risk_patch = bool(getattr(config.game, "map_generation_disable_high_risk_patch", True))

        if force_legacy:
            return {
                "provider": provider,
                "fallback_to_llm": fallback_to_llm,
                "release_stage": stage,
                "canary_percent": canary_percent,
                "force_legacy": True,
                "selected_chain": "legacy",
                "canary_hit": False,
                "disable_high_risk_patch": disable_high_risk_patch,
            }

        bucket_base = f"{self._map_release_hash_seed}:{user_id}:{source}"
        bucket = int(hashlib.sha256(bucket_base.encode("utf-8")).hexdigest()[:8], 16) % 100
        canary_hit = bucket < canary_percent

        selected_chain = "contract_v2"
        if stage == "debug":
            selected_chain = "contract_v2"
        elif stage == "canary":
            selected_chain = "contract_v2" if canary_hit else "legacy"
        elif stage == "stable":
            selected_chain = "contract_v2"

        alert_snapshot = self._build_generation_alert_snapshot(game_state)
        if bool(getattr(config.game, "map_alert_blocking_enabled", False)) and alert_snapshot.get("has_p1", False):
            selected_chain = "legacy"

        return {
            "provider": provider,
            "fallback_to_llm": fallback_to_llm,
            "release_stage": stage,
            "canary_percent": canary_percent,
            "canary_bucket": bucket,
            "canary_hit": canary_hit,
            "selected_chain": selected_chain,
            "force_legacy": False,
            "disable_high_risk_patch": disable_high_risk_patch,
            "alerts": alert_snapshot,
        }

    def _record_map_generation_metric(
        self,
        game_state: GameState,
        *,
        release_stage: str,
        selected_chain: str,
        provider: str,
        source: str,
        success: bool,
        fallback_used: bool,
        rollback_used: bool,
        generation_metadata: Optional[Dict[str, Any]] = None,
        error_code: str = "",
    ) -> None:
        if not isinstance(game_state.generation_metrics, dict):
            game_state.generation_metrics = {}

        metrics = game_state.generation_metrics.get("map_generation")
        if not isinstance(metrics, dict):
            metrics = {
                "total": 0,
                "success": 0,
                "failed": 0,
                "fallback_used": 0,
                "rollback_used": 0,
                "repairs": 0,
                "unreachable_reports": 0,
                "stairs_violations": 0,
                "by_stage": {},
                "by_provider": {},
                "error_codes": {},
            }

        metrics["total"] = int(metrics.get("total", 0) or 0) + 1
        if success:
            metrics["success"] = int(metrics.get("success", 0) or 0) + 1
        else:
            metrics["failed"] = int(metrics.get("failed", 0) or 0) + 1
        if fallback_used:
            metrics["fallback_used"] = int(metrics.get("fallback_used", 0) or 0) + 1
        if rollback_used:
            metrics["rollback_used"] = int(metrics.get("rollback_used", 0) or 0) + 1

        by_stage = metrics.get("by_stage") if isinstance(metrics.get("by_stage"), dict) else {}
        by_stage[release_stage] = int(by_stage.get(release_stage, 0) or 0) + 1
        metrics["by_stage"] = by_stage

        provider_key = f"{provider}:{selected_chain}"
        by_provider = metrics.get("by_provider") if isinstance(metrics.get("by_provider"), dict) else {}
        by_provider[provider_key] = int(by_provider.get(provider_key, 0) or 0) + 1
        metrics["by_provider"] = by_provider

        if error_code:
            error_codes = metrics.get("error_codes") if isinstance(metrics.get("error_codes"), dict) else {}
            error_codes[error_code] = int(error_codes.get(error_code, 0) or 0) + 1
            metrics["error_codes"] = error_codes

        meta = generation_metadata if isinstance(generation_metadata, dict) else {}
        repairs = 0
        corridor_report = meta.get("corridor_report") if isinstance(meta.get("corridor_report"), dict) else {}
        if isinstance(corridor_report.get("repairs"), list):
            repairs += len(corridor_report.get("repairs", []))
        local_validation = meta.get("local_validation") if isinstance(meta.get("local_validation"), dict) else {}
        local_repairs = local_validation.get("repairs") if isinstance(local_validation.get("repairs"), list) else []
        repairs += len(local_repairs)
        metrics["repairs"] = int(metrics.get("repairs", 0) or 0) + repairs

        local_stairs = local_validation.get("stairs") if isinstance(local_validation.get("stairs"), dict) else {}
        if local_stairs.get("violations"):
            metrics["stairs_violations"] = int(metrics.get("stairs_violations", 0) or 0) + int(local_stairs.get("violations", 0) or 0)

        if bool(local_validation.get("key_objective_unreachable", False)):
            metrics["unreachable_reports"] = int(metrics.get("unreachable_reports", 0) or 0) + 1
        elif int(local_validation.get("unreachable_targets_after", 0) or 0) > 0:
            metrics["unreachable_reports"] = int(metrics.get("unreachable_reports", 0) or 0) + 1

        patch_batches = game_state.generation_metrics.get("patch_batches") if isinstance(game_state.generation_metrics.get("patch_batches"), list) else []
        if patch_batches and isinstance(patch_batches[-1], dict) and patch_batches[-1].get("rollback_applied"):
            metrics["rollback_used"] = int(metrics.get("rollback_used", 0) or 0) + 1

        game_state.generation_metrics["map_generation"] = metrics
        game_state.generation_metrics["map_generation_last"] = {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "release_stage": release_stage,
            "selected_chain": selected_chain,
            "provider": provider,
            "success": success,
            "fallback_used": fallback_used,
            "rollback_used": rollback_used,
            "error_code": error_code,
        }

    def _should_strip_high_risk_patches(self, release_stage: str, disable_high_risk_patch: bool) -> bool:
        return bool(disable_high_risk_patch and release_stage in {"debug", "canary"})

    def _strip_high_risk_patches_from_context(self, quest_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(quest_context, dict):
            return quest_context
        copied = copy.deepcopy(quest_context)
        llm_updates = copied.get("llm_updates") if isinstance(copied.get("llm_updates"), dict) else None
        if not llm_updates:
            return copied
        patches = llm_updates.get("patches") if isinstance(llm_updates.get("patches"), list) else []
        if not patches:
            return copied

        filtered: List[Dict[str, Any]] = []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            risk = str(patch.get("risk_level", "medium") or "medium").lower()
            if risk in {"high", "critical"}:
                continue
            filtered.append(patch)
        llm_updates["patches"] = filtered
        copied["llm_updates"] = llm_updates
        return copied

    async def _generate_map_with_provider(
        self,
        width: int,
        height: int,
        depth: int,
        theme: str,
        quest_context: Optional[Dict[str, Any]],
        source: str,
        *,
        user_id: str = "",
        game_state: Optional[GameState] = None,
    ) -> GameMap:
        """根据发布阶段、灰度与回滚策略选择地图链路。"""
        strategy = self._resolve_map_generation_release_strategy(user_id=user_id, game_state=game_state, source=source)
        provider = strategy["provider"]
        fallback_to_llm = strategy["fallback_to_llm"]
        release_stage = strategy["release_stage"]
        selected_chain = strategy["selected_chain"]
        fallback_used = False
        rollback_used = False

        working_context = quest_context
        if self._should_strip_high_risk_patches(release_stage, strategy.get("disable_high_risk_patch", False)):
            working_context = self._strip_high_risk_patches_from_context(working_context)

        def _annotate_meta(meta_map: GameMap, payload: Dict[str, Any]) -> None:
            if not isinstance(meta_map.generation_metadata, dict):
                meta_map.generation_metadata = {}
            meta_map.generation_metadata.update(payload)
            if isinstance(strategy.get("alerts"), dict):
                meta_map.generation_metadata["alerts"] = strategy.get("alerts")

        # 旧链路：local provider，必要时回退 llm
        if selected_chain == "legacy" or provider == "local":
            try:
                from local_map_provider import local_map_provider

                local_map, monster_hints = local_map_provider.generate_map(
                    width=width,
                    height=height,
                    depth=depth,
                    theme=theme,
                    quest_context=working_context,
                )
                _annotate_meta(
                    local_map,
                    {
                        "map_provider": "local",
                        "source": source,
                        "monster_hints": monster_hints,
                        "release_stage": release_stage,
                        "selected_chain": selected_chain,
                        "canary_hit": strategy.get("canary_hit", False),
                    },
                )
                if game_state:
                    self._record_map_generation_metric(
                        game_state,
                        release_stage=release_stage,
                        selected_chain=selected_chain,
                        provider="local",
                        source=source,
                        success=True,
                        fallback_used=False,
                        rollback_used=False,
                        generation_metadata=local_map.generation_metadata,
                    )
                logger.info(f"Map generated by local provider ({source}, stage={release_stage}, chain={selected_chain}): {local_map.name}")
                return local_map
            except Exception as e:
                fallback_used = True
                logger.error(f"Local map provider failed at {source}: {e}")
                if not fallback_to_llm:
                    if game_state:
                        self._record_map_generation_metric(
                            game_state,
                            release_stage=release_stage,
                            selected_chain=selected_chain,
                            provider="local",
                            source=source,
                            success=False,
                            fallback_used=fallback_used,
                            rollback_used=False,
                            error_code="LOCAL_PROVIDER_FAILED",
                        )
                    raise

        try:
            llm_map = await content_generator.generate_dungeon_map(
                width=width,
                height=height,
                depth=depth,
                theme=theme,
                quest_context=working_context,
            )
            _annotate_meta(
                llm_map,
                {
                    "map_provider": "llm",
                    "source": source,
                    "release_stage": release_stage,
                    "selected_chain": selected_chain,
                    "canary_hit": strategy.get("canary_hit", False),
                    "fallback_used": fallback_used,
                },
            )
            if game_state:
                self._record_map_generation_metric(
                    game_state,
                    release_stage=release_stage,
                    selected_chain=selected_chain,
                    provider="llm",
                    source=source,
                    success=True,
                    fallback_used=fallback_used,
                    rollback_used=rollback_used,
                    generation_metadata=llm_map.generation_metadata,
                )
            return llm_map
        except Exception:
            if selected_chain != "legacy" and provider != "local":
                try:
                    from local_map_provider import local_map_provider

                    local_map, monster_hints = local_map_provider.generate_map(
                        width=width,
                        height=height,
                        depth=depth,
                        theme=theme,
                        quest_context=working_context,
                    )
                    rollback_used = True
                    _annotate_meta(
                        local_map,
                        {
                            "map_provider": "local",
                            "source": source,
                            "release_stage": release_stage,
                            "selected_chain": "legacy",
                            "rollback_to_legacy": True,
                            "monster_hints": monster_hints,
                        },
                    )
                    if game_state:
                        self._record_map_generation_metric(
                            game_state,
                            release_stage=release_stage,
                            selected_chain="legacy",
                            provider="local",
                            source=source,
                            success=True,
                            fallback_used=True,
                            rollback_used=True,
                            generation_metadata=local_map.generation_metadata,
                        )
                    return local_map
                except Exception as local_exc:
                    logger.error(f"Legacy rollback map generation failed at {source}: {local_exc}")
            if game_state:
                self._record_map_generation_metric(
                    game_state,
                    release_stage=release_stage,
                    selected_chain=selected_chain,
                    provider="llm",
                    source=source,
                    success=False,
                    fallback_used=True,
                    rollback_used=rollback_used,
                    error_code="MAP_GENERATION_FAILED",
                )
            raise

    def _get_monster_hint_context(self, game_map: GameMap) -> Dict[str, Any]:
        """提取地图中可用的monster_hints上下文。"""
        metadata = game_map.generation_metadata if isinstance(game_map.generation_metadata, dict) else {}
        hints = metadata.get("monster_hints") if isinstance(metadata.get("monster_hints"), dict) else {}

        spawn_points = hints.get("spawn_points") if isinstance(hints.get("spawn_points"), list) else []
        difficulty = hints.get("encounter_difficulty") if isinstance(hints.get("encounter_difficulty"), str) else ""
        quest_ctx = hints.get("llm_context") if isinstance(hints.get("llm_context"), dict) else {}

        return {
            "hints": hints,
            "spawn_points": spawn_points,
            "difficulty": difficulty,
            "quest_context": quest_ctx,
        }

    async def _generate_encounter_monsters_by_map_hints(
        self,
        game_state: GameState,
        game_map: GameMap,
        default_difficulty: str,
    ) -> List[Monster]:
        """优先使用地图monster_hints控制遭遇怪物生成参数。"""
        hint_ctx = self._get_monster_hint_context(game_map)
        hints = hint_ctx["hints"]

        encounter_difficulty = hint_ctx["difficulty"] or default_difficulty
        quest_context = hint_ctx["quest_context"] if hint_ctx["quest_context"] else None

        monsters = await content_generator.generate_encounter_monsters(
            game_state.player.stats.level,
            encounter_difficulty,
            quest_context,
        )

        if isinstance(hints.get("encounter_count"), int) and hints["encounter_count"] >= 0:
            monsters = monsters[:hints["encounter_count"]]

        return monsters

    def _get_monster_spawn_positions(self, game_map: GameMap, count: int) -> List[Tuple[int, int]]:
        """优先使用monster_hints中的坐标，否则回退到默认随机点位。"""
        if count <= 0:
            return []

        hint_ctx = self._get_monster_hint_context(game_map)
        hint_points = hint_ctx["spawn_points"]

        positions: List[Tuple[int, int]] = []
        used = set()

        for point in hint_points:
            if not isinstance(point, dict):
                continue
            x = point.get("x")
            y = point.get("y")
            if not isinstance(x, int) or not isinstance(y, int):
                continue
            if (x, y) in used:
                continue

            tile = game_map.get_tile(x, y)
            if not tile:
                continue
            if tile.character_id:
                continue
            if tile.terrain not in {
                TerrainType.FLOOR,
                TerrainType.DOOR,
                TerrainType.TRAP,
                TerrainType.TREASURE,
            }:
                continue

            positions.append((x, y))
            used.add((x, y))
            if len(positions) >= count:
                break

        remain = count - len(positions)
        if remain > 0:
            fallback_positions = content_generator.get_spawn_positions(game_map, remain)
            for pos in fallback_positions:
                if pos not in used:
                    positions.append(pos)
                    used.add(pos)

        return positions[:count]

    async def _generate_quest_monsters(self, game_state: GameState, game_map: GameMap) -> List[Monster]:
        """
        生成任务专属怪物（已重构为使用MonsterSpawnManager）

        Args:
            game_state: 游戏状态
            game_map: 当前地图

        Returns:
            生成的任务专属怪物列表
        """
        from monster_spawn_manager import monster_spawn_manager
        return await monster_spawn_manager.generate_quest_monsters(game_state, game_map)

        return quest_monsters

    async def _trigger_progress_event(self, game_state: GameState, event_type: ProgressEventType, context_data: Any = None):
        """触发进度事件"""
        try:
            # 创建进度上下文
            progress_context = ProgressContext(
                event_type=event_type,
                game_state=game_state,
                context_data=context_data
            )

            # 使用进程管理器处理事件
            result = await progress_manager.process_event(progress_context)

            if result.get("success"):
                logger.info(f"Progress event processed: {event_type.value}, increment: {result.get('progress_increment', 0):.1f}%")

                # 如果有叙述更新，添加到待显示事件
                if result.get("story_update"):
                    game_state.pending_events.append(result["story_update"])
            else:
                logger.warning(f"Failed to process progress event: {result.get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error triggering progress event {event_type.value}: {e}")

    async def _generate_new_quest_for_player(self, game_state: GameState):
        """为玩家生成新任务"""
        try:
            logger.info("Generating new quest for player after quest completion")

            # 生成新任务
            new_quests = await content_generator.generate_quest_chain(
                game_state.player.stats.level, 1
            )

            if new_quests:
                new_quest = new_quests[0]
                game_state.quests.append(new_quest)


                # 方案A兜底：保证仅新任务处于激活状态
                for q in game_state.quests:
                    q.is_active = (q.id == new_quest.id)

                # 添加新任务通知
                quest_message = f"新任务：{new_quest.title}"
                game_state.pending_events.append(quest_message)
                game_state.pending_events.append("你的冒险将继续...")

                logger.info(f"Generated new quest: {new_quest.title}")

                # 为新任务生成适合的地图
                await self._generate_new_quest_map(game_state, new_quest)

            else:
                logger.warning("Failed to generate new quest")
                # 创建一个简单的默认任务
                await self._create_default_quest(game_state)

        except Exception as e:
            logger.error(f"Error generating new quest: {e}")
            # 创建一个简单的默认任务作为后备
            await self._create_default_quest(game_state)

    async def _generate_new_quest_map(self, game_state: GameState, new_quest: 'Quest'):
        """为新任务生成适合的地图"""
        try:
            logger.info(f"Generating new map for quest: {new_quest.title}")

            # 清除旧地图上的角色标记
            old_tile = game_state.current_map.get_tile(*game_state.player.position)
            if old_tile:
                old_tile.character_id = None

            for monster in game_state.monsters:
                if monster.position:
                    monster_tile = game_state.current_map.get_tile(*monster.position)
                    if monster_tile:
                        monster_tile.character_id = None

            # 生成新地图（通常是下一层）
            new_depth = game_state.current_map.depth + 1
            quest_context = new_quest.to_dict()

            user_id = self._resolve_user_id_for_game_state(game_state)
            new_map = await self._generate_map_with_provider(
                width=config.game.default_map_size[0],
                height=config.game.default_map_size[1],
                depth=new_depth,
                theme=f"冒险区域（第{new_depth}阶段/层级） - {new_quest.title}",
                quest_context=quest_context,
                source="generate_new_quest_map",
                user_id=user_id,
                game_state=game_state,
            )

            # 更新游戏状态
            game_state.current_map = new_map

            # 设置玩家位置到新地图的合适位置
            spawn_positions = content_generator.get_spawn_positions(new_map, 1)
            if spawn_positions:
                game_state.player.position = spawn_positions[0]
                tile = new_map.get_tile(*game_state.player.position)
                if tile:
                    tile.character_id = game_state.player.id
                    tile.is_explored = True
                    tile.is_visible = True

            # 清空旧怪物并生成新的
            game_state.monsters.clear()

            # 生成普通怪物
            monsters = await self._generate_encounter_monsters_by_map_hints(
                game_state,
                new_map,
                default_difficulty="normal",
            )

            # 生成任务专属怪物
            quest_monsters = await self._generate_quest_monsters(game_state, new_map)
            monsters.extend(quest_monsters)

            # 放置怪物
            monster_positions = self._get_monster_spawn_positions(new_map, len(monsters))
            for monster, position in zip(monsters, monster_positions):
                monster.position = position
                tile = new_map.get_tile(*position)
                if tile:
                    tile.character_id = monster.id
                game_state.monsters.append(monster)

            # 添加地图切换通知
            game_state.pending_events.append(f"进入了{new_map.name}")

            logger.info(f"Successfully generated new map: {new_map.name}")

        except Exception as e:
            logger.error(f"Error generating new quest map: {e}")
            # 如果生成新地图失败，保持当前地图但添加通知
            game_state.pending_events.append("继续在当前区域探索...")

    async def _create_default_quest(self, game_state: GameState):
        """创建默认任务作为后备"""
        try:
            from data_models import Quest

            default_quest = Quest()
            default_quest.title = "继续探索"
            default_quest.description = "继续在当前区域探索，寻找新的挑战和机遇"
            default_quest.quest_type = "exploration"
            default_quest.experience_reward = max(100, game_state.player.stats.level * 50)
            default_quest.objectives = ["探索当前区域", "寻找有价值的发现"]
            default_quest.completed_objectives = [False, False]
            default_quest.is_active = True
            default_quest.is_completed = False


            default_quest.progress_percentage = 0.0
            default_quest.story_context = "虽然上一个任务已经完成，但这个区域仍有许多未知的秘密等待发现。"

            game_state.quests.append(default_quest)
            game_state.pending_events.append(f"新任务：{default_quest.title}")

            logger.info("Created default exploration quest")

            # 方案A兜底：保证仅默认任务处于激活状态（在成功追加后再统一去激活其他）
            for q in game_state.quests:
                if q.id != default_quest.id:
                    q.is_active = False
            default_quest.is_active = True


        except Exception as e:
            logger.error(f"Error creating default quest: {e}")

    async def _update_quest_progress(self, game_state: GameState, event_type: str, context: Any = None):
        """更新任务进度 - 保留兼容性的包装方法"""
        # 将旧的事件类型映射到新的枚举
        event_mapping = {
            "map_transition": ProgressEventType.MAP_TRANSITION,
            "combat_victory": ProgressEventType.COMBAT_VICTORY,
            "treasure_found": ProgressEventType.TREASURE_FOUND,
            "story_event": ProgressEventType.STORY_EVENT,
            "exploration": ProgressEventType.EXPLORATION
        }

        progress_event_type = event_mapping.get(event_type, ProgressEventType.CUSTOM_EVENT)
        await self._trigger_progress_event(game_state, progress_event_type, context)

    async def _process_monster_turns(self, game_state: GameState) -> bool:
        """处理怪物回合，返回是否有怪物事件发生"""
        combat_events = []
        combat_data_list = []

        for monster in game_state.monsters[:]:  # 使用切片避免修改列表时的问题
            if not monster.stats.is_alive():
                continue

            # 简单的AI：如果玩家在攻击范围内就攻击，否则移动靠近
            player_x, player_y = game_state.player.position
            monster_x, monster_y = monster.position
            distance = max(abs(player_x - monster_x), abs(player_y - monster_y))  # 切比雪夫距离

            # 检查怪物的攻击范围
            monster_attack_range = getattr(monster, 'attack_range', 1)
            if distance <= monster_attack_range:
                deterministic_seed = int(hashlib.sha1(
                    f"monster_attack|{game_state.id}|{game_state.turn_count}|{monster.id}|{game_state.player.id}".encode("utf-8")
                ).hexdigest()[:8], 16)
                trace_id = f"monster-{game_state.turn_count}-{monster.id}"
                mitigation_rules = (game_state.combat_rules or {}).get("mitigation", {}) if isinstance(game_state.combat_rules, dict) else {}
                if not isinstance(mitigation_rules, dict):
                    mitigation_rules = {}

                # 防御向装备效果在怪物攻击时生效（不污染基础存档字段）
                original_resistances = dict(getattr(game_state.player, "resistances", {}) or {})
                original_vulnerabilities = dict(getattr(game_state.player, "vulnerabilities", {}) or {})
                original_ac_components = dict(getattr(game_state.player.stats, "ac_components", {}) or {})
                original_ac = int(getattr(game_state.player.stats, "ac", 10) or 10)

                runtime_bonuses = (
                    (((game_state.combat_snapshot or {}).get("equipment", {}) or {}).get("runtime", {}) or {}).get("combat_bonuses", {})
                )
                if not isinstance(runtime_bonuses, dict):
                    runtime_bonuses = {}

                try:
                    res_min = float(mitigation_rules.get("resistance_clamp_min", 0.0) or 0.0)
                    res_max = float(mitigation_rules.get("resistance_clamp_max", 0.95) or 0.95)
                    if res_max < res_min:
                        res_min, res_max = res_max, res_min
                    vul_min_mul = float(mitigation_rules.get("vulnerability_min_multiplier", 1.0) or 1.0)
                    vul_max_mul = float(mitigation_rules.get("vulnerability_max_multiplier", 3.0) or 3.0)
                    if vul_max_mul < vul_min_mul:
                        vul_min_mul, vul_max_mul = vul_max_mul, vul_min_mul
                    vul_value_max = max(0.0, vul_max_mul - 1.0)

                    for dtype, delta in (runtime_bonuses.get("resistance_bonus", {}) or {}).items():
                        key = str(dtype or "")
                        if not key:
                            continue
                        game_state.player.resistances[key] = max(
                            res_min,
                            min(
                                res_max,
                                float(game_state.player.resistances.get(key, 0.0) or 0.0) + float(delta or 0.0),
                            ),
                        )
                    for dtype, delta in (runtime_bonuses.get("vulnerability_reduction", {}) or {}).items():
                        key = str(dtype or "")
                        if not key:
                            continue
                        game_state.player.vulnerabilities[key] = max(
                            0.0,
                            min(
                                vul_value_max,
                                float(game_state.player.vulnerabilities.get(key, 0.0) or 0.0) - float(delta or 0.0),
                            ),
                        )

                    game_state.player.stats.ac_components = dict(original_ac_components)
                    game_state.player.stats.ac_components["status"] = int(game_state.player.stats.ac_components.get("status", 0) or 0) + int(runtime_bonuses.get("ac_bonus", 0) or 0)
                    game_state.player.stats.ac = game_state.player.stats.get_effective_ac()

                    eval_result = combat_core_evaluator.evaluate_attack(
                        monster,
                        game_state.player,
                        attack_type="melee",
                        deterministic_seed=deterministic_seed,
                        trace_id=trace_id,
                        mitigation_policy=mitigation_rules,
                    )
                finally:
                    # 同步 combat_runtime（新结构）与 legacy stats 字段
                    player_runtime = self._get_player_defense_runtime(game_state.player)
                    player_runtime["shield"] = max(0, int(getattr(game_state.player.stats, "shield", 0) or 0))
                    player_runtime["temporary_hp"] = max(0, int(getattr(game_state.player.stats, "temporary_hp", 0) or 0))
                    self._sync_player_defense_runtime(game_state.player)

                    game_state.player.resistances = original_resistances
                    game_state.player.vulnerabilities = original_vulnerabilities
                    game_state.player.stats.ac_components = original_ac_components
                    game_state.player.stats.ac = original_ac

                damage = int(eval_result.final_damage)
                if eval_result.hit:
                    combat_events.append(f"{monster.name} 攻击了你，造成 {damage} 点伤害！")
                else:
                    combat_events.append(f"{monster.name} 的攻击未命中！")

                if eval_result.critical:
                    combat_events.append(f"{monster.name} 发动了致命一击！")
                logger.info(f"{monster.name} 攻击玩家结算 damage={damage}, hit={eval_result.hit}")
                self._record_combat_telemetry(game_state, damage=damage, attempt=True)
                self._record_ac_hit_curve(
                    game_state,
                    {
                        "trace_id": trace_id,
                        "phase": "monster_attack",
                        "attacker": str(getattr(monster, "id", "") or ""),
                        "target": str(getattr(game_state.player, "id", "") or ""),
                        "target_ac": int(eval_result.attack_roll.get("target_ac", 10) or 10),
                        "attack_total": int(eval_result.attack_roll.get("total", 0) or 0),
                        "hit": bool(eval_result.hit),
                    },
                )

                # 记录战斗数据用于LLM上下文
                combat_data_list.append({
                    "type": "monster_attack",
                    "attacker": monster.name,
                    "damage": damage,
                    "hit": bool(eval_result.hit),
                    "critical": bool(eval_result.critical),
                    "player_hp_remaining": game_state.player.stats.hp,
                    "player_hp_max": game_state.player.stats.max_hp,
                    "monster_position": monster.position,
                    "distance": distance,
                    "combat_breakdown": eval_result.breakdown,
                })

                hook_result = effect_engine.process_effect_hooks(
                    game_state,
                    hook="on_damage_taken",
                    actor=monster,
                    target=game_state.player,
                    context={"trace_id": trace_id},
                )
                regen_bonus = int(
                    ((((game_state.combat_snapshot or {}).get("equipment", {}) or {}).get("runtime", {}) or {})
                    .get("combat_bonuses", {})
                    .get("regen_per_turn", 0)
                    or 0)
                )
                if regen_bonus > 0 and game_state.player.stats.hp > 0:
                    before_hp = int(game_state.player.stats.hp)
                    game_state.player.stats.hp = min(int(game_state.player.stats.max_hp), before_hp + regen_bonus)
                    healed = int(game_state.player.stats.hp) - before_hp
                    if healed > 0:
                        combat_events.append(f"装备回复触发，恢复 {healed} 点生命")
                if hook_result.get("events"):
                    combat_events.extend(hook_result["events"])

                # 检查玩家是否死亡
                if game_state.player.stats.hp <= 0:
                    combat_events.append("你被击败了！游戏结束！")
                    game_state.is_game_over = True
                    game_state.game_over_reason = "被怪物击败"
                    self._record_combat_telemetry(game_state, loss=True, death_source="monster_attack")
                    break  # 玩家死亡，停止处理其他怪物

            elif distance <= 5:
                # 移动靠近玩家
                await self._move_monster_towards_player(game_state, monster)

        # 将战斗事件添加到游戏状态中，以便前端显示
        if combat_events:
            if not hasattr(game_state, 'pending_events'):
                game_state.pending_events = []
            game_state.pending_events.extend(combat_events)

            # 如果有战斗事件，创建防御交互上下文并添加到LLM管理器
            if combat_data_list:
                defense_context = InteractionContext(
                    interaction_type=InteractionType.COMBAT_DEFENSE,
                    primary_action="遭受怪物攻击",
                    events=combat_events,
                    combat_data={
                        "type": "monster_attacks",
                        "attacks": combat_data_list,
                        "total_damage": sum(data["damage"] for data in combat_data_list),
                        "attackers": [data["attacker"] for data in combat_data_list]
                    }
                )
                llm_interaction_manager.add_context(defense_context)

        # 返回是否有怪物事件发生（主要是攻击事件）
        return len(combat_events) > 0

    async def _move_monster_towards_player(self, game_state: GameState, monster: Monster):
        """移动怪物靠近玩家"""
        player_x, player_y = game_state.player.position
        monster_x, monster_y = monster.position

        # 简单的寻路：朝玩家方向移动一格
        dx = 0 if player_x == monster_x else (1 if player_x > monster_x else -1)
        dy = 0 if player_y == monster_y else (1 if player_y > monster_y else -1)

        new_x, new_y = monster_x + dx, monster_y + dy

        # 检查新位置是否有效
        target_tile = game_state.current_map.get_tile(new_x, new_y)
        if (target_tile and target_tile.terrain != TerrainType.WALL and
            not target_tile.character_id):

            # 移动怪物
            old_tile = game_state.current_map.get_tile(monster_x, monster_y)
            if old_tile:
                old_tile.character_id = None

            target_tile.character_id = monster.id
            monster.position = (new_x, new_y)

    @async_performance_monitor
    async def _save_game_async(self, game_state: GameState, user_id: str, retry_count: int = 3):
        """
        异步保存游戏（带重试机制，保存到用户目录）

        使用锁保护，防止保存时与其他操作冲突

        Args:
            game_state: 游戏状态
            user_id: 用户ID
            retry_count: 重试次数
        """
        loop = asyncio.get_event_loop()

        for attempt in range(retry_count):
            try:
                # 导入 user_session_manager
                from user_session_manager import user_session_manager

                # 使用锁保护游戏状态的读取
                async with game_state_lock_manager.lock_game_state(user_id, game_state.id, "auto_save"):
                    # 转换为字典格式（在锁内进行，确保数据一致性）
                    game_data = game_state.to_dict()
                    # 保存最近N条LLM上下文到存档
                    try:
                        from llm_context_manager import llm_context_manager
                        game_data["llm_context_logs"] = [
                            e.to_dict() for e in llm_context_manager.get_recent_context(
                                max_entries=getattr(config.llm, "save_context_entries", 20),
                                context_key=f"{user_id}:{game_state.id}",
                            )
                        ]
                    except Exception as _e:
                        logger.warning(f"[auto_save] Failed to attach LLM context logs: {_e}")

                # 使用统一的IO线程池，保存到用户目录（在锁外进行，避免阻塞）
                await loop.run_in_executor(
                    async_task_manager.io_executor,
                    user_session_manager.save_game_for_user,
                    user_id,
                    game_data
                )

                if attempt > 0:
                    logger.info(f"Game {game_state.id} saved successfully for user {user_id} after {attempt + 1} attempts")

                return

            except Exception as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Failed to save game {game_state.id} for user {user_id} (attempt {attempt + 1}/{retry_count}): {e}")
                    await asyncio.sleep(1)  # 等待1秒后重试
                else:
                    logger.error(f"Failed to save game {game_state.id} for user {user_id} after {retry_count} attempts: {e}")
                    raise

    def _start_auto_save(self, user_id: str, game_id: str):
        """启动自动保存

        Args:
            user_id: 用户ID
            game_id: 游戏ID
        """
        async def auto_save_loop():
            """自动保存循环（带错误处理）"""
            logger.info(f"Auto-save started for user {user_id}, game {game_id}")

            game_key = (user_id, game_id)

            while game_key in self.active_games:
                try:
                    await asyncio.sleep(config.game.auto_save_interval)

                    if game_key in self.active_games:
                        logger.debug(f"Auto-saving game {game_id} for user {user_id}...")
                        await self._save_game_async(self.active_games[game_key], user_id)
                        logger.debug(f"Auto-save completed for game {game_id}")

                except asyncio.CancelledError:
                    logger.info(f"Auto-save cancelled for game {game_id}")
                    raise

                except Exception as e:
                    logger.error(f"Auto-save error for game {game_id}: {e}")
                    # 继续循环，不中断自动保存
                    await asyncio.sleep(5)  # 出错后等待5秒再继续

        # 使用任务管理器创建任务
        task_id = f"auto_save_{user_id}_{game_id}"
        task = async_task_manager.create_task(
            auto_save_loop(),
            task_type=TaskType.AUTO_SAVE,
            description=f"Auto-save for user {user_id}, game {game_id}",
            task_id=task_id
        )

        game_key = (user_id, game_id)
        self.auto_save_tasks[game_key] = task

    async def close_game(self, user_id: str, game_id: str):
        """
        关闭游戏（异步版本，正确处理任务取消）

        Args:
            user_id: 用户ID
            game_id: 游戏ID
        """
        game_key = (user_id, game_id)

        # 先取消自动保存任务
        if game_key in self.auto_save_tasks:
            task_id = f"auto_save_{user_id}_{game_id}"
            logger.info(f"Cancelling auto-save task for user {user_id}, game {game_id}")
            await async_task_manager.cancel_task(task_id, wait=True)
            del self.auto_save_tasks[game_key]

        # 然后保存游戏状态
        if game_key in self.active_games:
            try:
                logger.info(f"Saving game {game_id} for user {user_id} before closing...")
                await self._save_game_async(self.active_games[game_key], user_id)
                logger.info(f"Game {game_id} saved successfully")
            except Exception as e:
                logger.error(f"Failed to save game {game_id} on close: {e}")

            del self.active_games[game_key]
            logger.info(f"Game {game_id} closed for user {user_id}")

        # 清理游戏状态锁
        await game_state_lock_manager.remove_lock(user_id, game_id)

    def _sanitize_equipment_affix_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None

        if "key" in payload:
            key = str(payload.get("key", "") or "")
            value = payload.get("value", 0)
        elif "stat" in payload:
            key = str(payload.get("stat", "") or "")
            value = payload.get("value", payload.get("delta", 0))
        elif "type" in payload:
            key = str(payload.get("type", "") or "")
            value = payload.get("value", payload.get("amount", 0))
        else:
            return None

        if not key:
            return None

        bounds = self._EQUIPMENT_AFFIX_DEFAULT_BOUNDS
        if key not in bounds:
            return None

        min_v, max_v = bounds[key]

        if key in {"resistance_bonus", "vulnerability_reduction"}:
            mapping = payload.get("mapping", payload.get("types", {}))
            if not isinstance(mapping, dict):
                return None
            safe_mapping: Dict[str, float] = {}
            for dtype, raw in mapping.items():
                dtype_s = str(dtype or "")
                if not dtype_s:
                    continue
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                safe_mapping[dtype_s] = max(min_v, min(max_v, val))
            return {"key": key, "value": 0, "mapping": safe_mapping}

        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None

        clamped = max(min_v, min(max_v, numeric))
        if key == "critical_bonus":
            return {"key": key, "value": float(clamped)}
        return {"key": key, "value": int(clamped)}

    def _capture_combat_anomaly(
        self,
        game_state: GameState,
        *,
        trace_id: str,
        error_code: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        self._ensure_combat_defaults(game_state)
        if not isinstance(game_state.combat_snapshot, dict):
            game_state.combat_snapshot = {}

        anomaly = {
            "timestamp": datetime.utcnow().isoformat(),
            "trace_id": str(trace_id or ""),
            "error_code": str(error_code or "UNKNOWN"),
            "message": str(message or ""),
            "turn_count": int(getattr(game_state, "turn_count", 0) or 0),
            "rule_version": int(getattr(game_state, "combat_rule_version", 1) or 1),
            "authority_mode": str(getattr(game_state, "combat_authority_mode", "local") or "local"),
            "context": context or {},
        }

        captures = game_state.combat_snapshot.get("anomaly_captures", [])
        if not isinstance(captures, list):
            captures = []
        captures.append(anomaly)
        game_state.combat_snapshot["anomaly_captures"] = captures[-100:]

    def update_access_time(self, user_id: str, game_id: str):
        """更新游戏的最后访问时间"""
        import time
        game_key = (user_id, game_id)
        self.last_access_time[game_key] = time.time()

    def _start_cleanup_task(self):
        """启动游戏会话清理任务（需要在事件循环中调用）"""
        # 防止重复启动
        if self.cleanup_task_started:
            logger.warning("Cleanup task already started, skipping...")
            return

        self.cleanup_task_started = True

        async def cleanup_loop():
            """定期清理不活跃的游戏会话"""
            import time
            logger.info("Game session cleanup task started")

            while True:
                try:
                    await asyncio.sleep(600)  # 每10分钟检查一次

                    current_time = time.time()
                    timeout = config.game.game_session_timeout

                    games_to_close = []
                    for game_key, last_access in list(self.last_access_time.items()):
                        if current_time - last_access > timeout:
                            games_to_close.append(game_key)

                    for game_key in games_to_close:
                        user_id, game_id = game_key
                        logger.info(f"Closing inactive game session: {game_id} (user: {user_id}, inactive for {int(current_time - self.last_access_time[game_key])}s)")
                        try:
                            await self.close_game(user_id, game_id)
                            # 清理访问时间记录
                            if game_key in self.last_access_time:
                                del self.last_access_time[game_key]
                        except Exception as e:
                            logger.error(f"Failed to close inactive game {game_id}: {e}")

                    if games_to_close:
                        logger.info(f"Cleaned up {len(games_to_close)} inactive game sessions")

                except asyncio.CancelledError:
                    logger.info("Game session cleanup task cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in cleanup loop: {e}")
                    await asyncio.sleep(60)  # 出错后等待1分钟再继续

        # 使用任务管理器创建清理任务
        from async_task_manager import async_task_manager, TaskType
        async_task_manager.create_task(
            cleanup_loop(),
            task_type=TaskType.BACKGROUND,
            description="Game session cleanup",
            task_id="game_session_cleanup"
        )


# 全局游戏引擎实例
game_engine = GameEngine()

__all__ = ["GameEngine", "game_engine"]
