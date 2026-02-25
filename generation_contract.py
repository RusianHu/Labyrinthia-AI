"""
Labyrinthia AI - 生成契约工具
统一管理地图生成契约（Generation Contract）的版本、哈希与降级策略。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


CONTRACT_VERSION = "2.0.0"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def default_generation_contract() -> Dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "blueprint": {
            "schema_version": "v2",
            "max_nodes": 32,
            "max_edges": 96,
            "max_intents_per_item": 8,
            "allow_absolute_coordinates": False,
            "room_size_whitelist": ["small", "medium", "large"],
            "placement_policy_whitelist": [
                "center",
                "edge",
                "branch",
                "corridor_adjacent",
            ],
            "event_policy_whitelist": ["mandatory", "optional", "forbidden"],
            "corridor_kind_whitelist": ["direct", "branch", "loop"],
            "corridor_gate_whitelist": ["none", "locked", "key", "boss_gate"],
            "corridor_risk_whitelist": ["low", "medium", "high", "deadly"],
        },
        "safety": {
            "trap_density_cap": 0.35,
            "enforce_connectivity": True,
            "enforce_key_path": True,
            "enforce_stair_legality": True,
            "require_entrance": True,
            "require_objective_or_boss": True,
            "max_room_must_contain": 8,
            "max_quest_bindings": 64,
        },
        "progress": {
            "max_single_increment_except_final": 25.0,
            "min_progress_before_final_burst": 70.0,
            "completion_policy": "aggregate",
            "require_final_floor": False,
            "require_all_mandatory_events": False,
        },
        "map_updates": {
            "schema": "tiles_dict_v1",
            "allowed_root_keys": ["tiles"],
            "allowed_tile_fields": [
                "terrain",
                "items",
                "monster",
                "has_event",
                "event_type",
                "event_data",
                "is_event_hidden",
                "event_triggered",
                "items_collected",
                "trap_detected",
                "trap_disarmed",
                "room_type",
                "room_id",
                "is_explored",
                "is_visible",
                "character_id",
            ],
        },
    }


def contract_hash(contract: Dict[str, Any]) -> str:
    payload = json.dumps(contract or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ContractResolution:
    contract: Dict[str, Any]
    source: str
    warnings: List[str]



def resolve_generation_contract(
    *,
    provided_contract: Optional[Dict[str, Any]] = None,
    requested_version: Optional[str] = None,
    source_hint: Optional[str] = None,
) -> ContractResolution:
    base = default_generation_contract()
    warnings: List[str] = []
    source = source_hint or "default"

    if requested_version and str(requested_version).strip() not in {CONTRACT_VERSION, "v2", "2"}:
        warnings.append(f"unsupported_contract_version:{requested_version}")

    if provided_contract is None:
        return ContractResolution(contract=base, source=source, warnings=warnings)

    if not isinstance(provided_contract, dict):
        warnings.append("invalid_contract_type_fallback_default")
        logger.warning("Generation contract is not a dict, fallback to default")
        return ContractResolution(contract=base, source="default", warnings=warnings)

    try:
        merged = _deep_merge(base, provided_contract)
        merged["contract_version"] = CONTRACT_VERSION
        return ContractResolution(contract=merged, source=source, warnings=warnings)
    except Exception as exc:
        warnings.append("contract_merge_failed_fallback_default")
        logger.warning("Failed to merge generation contract, fallback to default: %s", exc)
        return ContractResolution(contract=base, source="default", warnings=warnings)



def extract_contract_request(quest_context: Optional[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    if not isinstance(quest_context, dict):
        return None, None, "default"

    provided = quest_context.get("generation_contract")
    requested_version = quest_context.get("contract_version")

    source = "default"
    if isinstance(provided, dict):
        source = "manual"
    elif requested_version:
        source = "llm"

    return provided if isinstance(provided, dict) else None, str(requested_version or "") or None, source
