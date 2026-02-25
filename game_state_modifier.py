"""
Labyrinthia AI - 游戏状态修改器
统一的游戏状态修改接口，用于处理所有LLM驱动的游戏状态变更
"""

import logging
import copy
from collections import deque
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from data_models import (
    GameState, Character, Monster, Item, MapTile, Quest,
    TerrainType, CharacterClass, Stats
)
from config import config
from entity_manager import entity_manager
from generation_contract import resolve_generation_contract


logger = logging.getLogger(__name__)


class ModificationType(Enum):
    """状态修改类型"""
    PLAYER_STATS = "player_stats"
    PLAYER_ABILITIES = "player_abilities"  # 新增: 六维属性修改
    PLAYER_INVENTORY = "player_inventory"
    MAP_TILE = "map_tile"
    MONSTER = "monster"
    MONSTER_ABILITIES = "monster_abilities"  # 新增: 怪物六维属性修改
    QUEST = "quest"
    GAME_STATE = "game_state"
    PATCH = "patch"


@dataclass
class ModificationRecord:
    """状态修改记录"""
    modification_type: ModificationType
    timestamp: datetime
    source: str  # 修改来源（如 "event_choice", "item_use", "combat"）
    target_id: str  # 目标ID（如玩家ID、怪物ID、瓦片坐标等）
    changes: Dict[str, Any]  # 具体的修改内容
    success: bool = True
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "modification_type": self.modification_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "target_id": self.target_id,
            "changes": self.changes,
            "success": self.success,
            "error_message": self.error_message
        }


@dataclass
class ModificationResult:
    """状态修改结果"""
    success: bool = True
    message: str = ""
    records: List[ModificationRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def add_record(self, record: ModificationRecord):
        """添加修改记录"""
        self.records.append(record)
        if not record.success:
            self.success = False
            self.errors.append(record.error_message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "records": [r.to_dict() for r in self.records],
            "errors": self.errors
        }


@dataclass
class PatchExecutionResult:
    """Patch 执行结果"""
    success: bool = True
    rollback_applied: bool = False
    accepted_patches: List[Dict[str, Any]] = field(default_factory=list)
    rejected_patches: List[Dict[str, Any]] = field(default_factory=list)
    rollback_trace: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "rollback_applied": self.rollback_applied,
            "accepted_patches": self.accepted_patches,
            "rejected_patches": self.rejected_patches,
            "rollback_trace": self.rollback_trace,
            "diagnostics": self.diagnostics,
        }


class GameStateModifier:
    """
    游戏状态修改器
    
    统一管理所有LLM驱动的游戏状态修改，提供：
    1. 统一的状态修改接口
    2. 验证机制
    3. 错误处理
    4. 日志记录
    5. 修改历史追踪
    """
    
    def __init__(self):
        self.modification_history: List[ModificationRecord] = []
        self.max_history_size = 100
        self.max_patch_batches = 200
        
    def apply_llm_updates(
        self,
        game_state: GameState,
        llm_response: Dict[str, Any],
        source: str = "llm"
    ) -> ModificationResult:
        """
        应用LLM返回的所有更新
        
        Args:
            game_state: 游戏状态
            llm_response: LLM返回的更新数据
            source: 修改来源标识
            
        Returns:
            ModificationResult: 修改结果
        """
        result = ModificationResult()
        
        try:
            # 应用玩家更新
            if "player_updates" in llm_response:
                player_result = self.apply_player_updates(
                    game_state,
                    llm_response["player_updates"],
                    source
                )
                result.records.extend(player_result.records)
                if not player_result.success:
                    result.success = False
                    result.errors.extend(player_result.errors)
            
            # 应用地图更新
            if "map_updates" in llm_response:
                map_result = self.apply_map_updates(
                    game_state,
                    llm_response["map_updates"],
                    source
                )
                result.records.extend(map_result.records)
                if not map_result.success:
                    result.success = False
                    result.errors.extend(map_result.errors)
            
            # 应用 patch 批次
            if "patches" in llm_response and isinstance(llm_response["patches"], list):
                patch_batch = {
                    "patches": llm_response["patches"],
                    "batch_id": llm_response.get("patch_batch_id", ""),
                    "rollback_mode": llm_response.get("patch_rollback_mode", "full"),
                    "depends_on_batch": llm_response.get("patch_depends_on_batch", ""),
                }
                patch_result = self.apply_patch_batch(game_state, patch_batch, source=source)
                if not patch_result.success:
                    result.success = False
                    result.errors.append("PATCH_EXECUTION_FAILED")
                    result.errors.extend([d.get("message", "") for d in patch_result.diagnostics if isinstance(d, dict)])
            
            # 记录到历史
            self._add_to_history(result.records)
            
            logger.info(f"Applied LLM updates from {source}: {len(result.records)} modifications")
            
        except Exception as e:
            logger.error(f"Error applying LLM updates: {e}")
            result.success = False
            result.errors.append(f"应用LLM更新时发生错误: {str(e)}")
        
        return result
    
    def apply_patch_batch(
        self,
        game_state: GameState,
        patch_batch: Dict[str, Any],
        source: str = "llm_patch",
    ) -> PatchExecutionResult:
        """执行 Patch DSL 批次（支持部分/全量回滚）。"""
        result = PatchExecutionResult(success=True)

        if not isinstance(patch_batch, dict):
            result.success = False
            result.diagnostics.append({"code": "PATCH_BATCH_TYPE_ERROR", "message": "patch_batch must be object"})
            return result

        patches = patch_batch.get("patches")
        if not isinstance(patches, list):
            result.success = False
            result.diagnostics.append({"code": "PATCH_BATCH_FIELD_ERROR", "message": "patches must be list"})
            return result

        rollback_mode = str(patch_batch.get("rollback_mode", "full")).strip().lower()
        if rollback_mode not in {"full", "partial"}:
            rollback_mode = "full"

        batch_id = str(patch_batch.get("batch_id", "")).strip() or f"patch_batch_{datetime.now().isoformat()}"

        expected_prev_patch = str(patch_batch.get("depends_on_batch", "")).strip()
        current_prev_patch = ""
        if isinstance(game_state.generation_metrics, dict):
            current_prev_patch = str(game_state.generation_metrics.get("last_patch_batch_id", "") or "")
        if expected_prev_patch and current_prev_patch and expected_prev_patch != current_prev_patch:
            result.success = False
            result.diagnostics.append(
                {
                    "code": "PATCH_BATCH_DEPENDENCY_ERROR",
                    "message": f"depends_on_batch={expected_prev_patch} but last_patch_batch_id={current_prev_patch}",
                }
            )
            return result

        snapshots: List[Dict[str, Any]] = []

        for idx, patch in enumerate(patches):
            if not isinstance(patch, dict):
                result.rejected_patches.append({"index": idx, "reason": "patch must be object", "patch": patch})
                if rollback_mode == "full":
                    result.success = False
                    break
                continue

            patch_id = str(patch.get("id", f"patch_{idx}"))
            op = str(patch.get("op", "")).strip().lower()
            target = str(patch.get("target", "")).strip().lower()
            intent_reason = str(patch.get("intent_reason", "")).strip()
            risk_level = str(patch.get("risk_level", "medium")).strip().lower()

            release_stage = str(getattr(config.game, "map_generation_release_stage", "debug") or "debug").strip().lower()
            if release_stage not in {"debug", "canary", "stable"}:
                release_stage = "debug"
            if isinstance(getattr(game_state, "current_map", None), object):
                meta = (
                    game_state.current_map.generation_metadata
                    if isinstance(getattr(game_state.current_map, "generation_metadata", None), dict)
                    else {}
                )
                stage_value = str(meta.get("release_stage", release_stage) or release_stage).strip().lower()
                if stage_value in {"debug", "canary", "stable"}:
                    release_stage = stage_value

            disable_high_risk = bool(getattr(config.game, "map_generation_disable_high_risk_patch", True))
            high_risk_blocked = bool(disable_high_risk and release_stage in {"debug", "canary"})
            if high_risk_blocked and risk_level in {"high", "critical"}:
                result.rejected_patches.append(
                    {
                        "id": patch_id,
                        "reason": "high_risk_patch_blocked_by_config",
                        "risk_level": risk_level,
                        "release_stage": release_stage,
                    }
                )
                if rollback_mode == "full":
                    result.success = False
                    break
                continue

            if op not in {"add", "remove", "update"}:
                result.rejected_patches.append({"id": patch_id, "reason": "unsupported op", "op": op})
                if rollback_mode == "full":
                    result.success = False
                    break
                continue
            if target not in {"tile", "event", "monster", "quest_binding", "room", "corridor"}:
                result.rejected_patches.append({"id": patch_id, "reason": "unsupported target", "target": target})
                if rollback_mode == "full":
                    result.success = False
                    break
                continue

            snapshot = self._make_patch_snapshot(game_state)
            snapshots.append({"id": patch_id, "snapshot": snapshot})

            patch_apply = self._apply_single_patch(game_state, patch, source)
            patch_apply["intent_reason"] = intent_reason
            patch_apply["risk_level"] = risk_level

            if patch_apply.get("success"):
                result.accepted_patches.append(patch_apply)
            else:
                result.rejected_patches.append(patch_apply)
                if rollback_mode == "partial":
                    if snapshots:
                        latest = snapshots[-1]
                        self._restore_patch_snapshot(game_state, latest["snapshot"])
                        result.rollback_trace.append({"mode": "partial", "patch_id": patch_id, "rolled_back": True})
                else:
                    result.success = False
                    break

        if not result.success and rollback_mode == "full":
            if snapshots:
                first_snapshot = snapshots[0]["snapshot"]
                self._restore_patch_snapshot(game_state, first_snapshot)
                result.rollback_applied = True
                result.rollback_trace.append({"mode": "full", "rolled_back": True, "batch_id": batch_id})

        # 复检
        if result.success:
            post_checks = self._run_patch_post_checks(game_state)
            failed_checks = [item for item in post_checks if not item.get("ok", False)]
            if failed_checks:
                result.success = False
                result.diagnostics.extend(
                    [{"code": "PATCH_POST_CHECK_FAILED", "message": item.get("name", "unknown")} for item in failed_checks]
                )
                if snapshots:
                    first_snapshot = snapshots[0]["snapshot"]
                    self._restore_patch_snapshot(game_state, first_snapshot)
                    result.rollback_applied = True
                    result.rollback_trace.append({"mode": "post_check", "rolled_back": True, "batch_id": batch_id})

        if not isinstance(game_state.generation_metrics, dict):
            game_state.generation_metrics = {}
        patch_history = game_state.generation_metrics.get("patch_batches")
        if not isinstance(patch_history, list):
            patch_history = []
        patch_history.append(
            {
                "batch_id": batch_id,
                "source": source,
                "success": result.success,
                "rollback_applied": result.rollback_applied,
                "accepted_count": len(result.accepted_patches),
                "rejected_count": len(result.rejected_patches),
                "rollback_trace": result.rollback_trace,
                "diagnostics": result.diagnostics,
                "timestamp": datetime.now().isoformat(),
            }
        )
        if len(patch_history) > self.max_patch_batches:
            patch_history = patch_history[-self.max_patch_batches:]
        game_state.generation_metrics["patch_batches"] = patch_history
        game_state.generation_metrics["last_patch_batch_id"] = batch_id

        return result

    def _apply_single_patch(self, game_state: GameState, patch: Dict[str, Any], source: str) -> Dict[str, Any]:
        patch_id = str(patch.get("id", ""))
        op = str(patch.get("op", "")).strip().lower()
        target = str(patch.get("target", "")).strip().lower()

        try:
            if target in {"tile", "event", "monster"}:
                payload = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
                if target in {"tile", "event"}:
                    tile_key = str(patch.get("tile", "")).strip()
                    if "," not in tile_key:
                        return {"id": patch_id, "success": False, "reason": "invalid tile key"}
                    tile_patch = payload if payload else {}
                    if target == "event":
                        tile_patch = {
                            "has_event": bool(payload.get("has_event", True)),
                            "event_type": payload.get("event_type", "story"),
                            "event_data": payload.get("event_data", {}),
                            "is_event_hidden": bool(payload.get("is_event_hidden", True)),
                            "event_triggered": bool(payload.get("event_triggered", False)),
                        }
                    if op == "remove":
                        tile_patch = {
                            "has_event": False,
                            "event_type": "",
                            "event_data": {},
                            "event_triggered": False,
                        }
                    map_updates = {"tiles": {tile_key: tile_patch}}
                    apply_result = self.apply_map_updates(game_state, map_updates, source=f"{source}:patch:{patch_id}")
                    return {
                        "id": patch_id,
                        "success": apply_result.success,
                        "target": target,
                        "op": op,
                        "errors": apply_result.errors,
                    }

                if target == "monster":
                    tile_key = str(patch.get("tile", "")).strip()
                    if "," not in tile_key:
                        return {"id": patch_id, "success": False, "reason": "invalid tile key"}
                    monster_payload = dict(payload)
                    monster_payload.setdefault("action", "add" if op == "add" else ("remove" if op == "remove" else "update"))
                    map_updates = {"tiles": {tile_key: {"monster": monster_payload}}}
                    apply_result = self.apply_map_updates(game_state, map_updates, source=f"{source}:patch:{patch_id}")
                    return {
                        "id": patch_id,
                        "success": apply_result.success,
                        "target": target,
                        "op": op,
                        "errors": apply_result.errors,
                    }

            if target == "quest_binding":
                binding = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
                if not isinstance(game_state.generation_metrics, dict):
                    game_state.generation_metrics = {}
                bindings = game_state.generation_metrics.get("quest_bindings")
                if not isinstance(bindings, list):
                    bindings = []
                if op == "remove":
                    qid = str(binding.get("quest_monster_id", "") or "")
                    bindings = [b for b in bindings if str(b.get("quest_monster_id", "")) != qid]
                else:
                    bindings.append(binding)
                game_state.generation_metrics["quest_bindings"] = bindings
                return {"id": patch_id, "success": True, "target": target, "op": op}

            return {"id": patch_id, "success": False, "reason": "unhandled target"}
        except Exception as exc:
            return {"id": patch_id, "success": False, "reason": str(exc)}

    def _make_patch_snapshot(self, game_state: GameState) -> Dict[str, Any]:
        return {
            "tiles": copy.deepcopy(game_state.current_map.tiles),
            "monsters": copy.deepcopy(game_state.monsters),
            "quests": copy.deepcopy(game_state.quests),
            "pending_events": copy.deepcopy(game_state.pending_events),
            "generation_metrics": copy.deepcopy(game_state.generation_metrics),
        }

    def _restore_patch_snapshot(self, game_state: GameState, snapshot: Dict[str, Any]) -> None:
        game_state.current_map.tiles = snapshot.get("tiles", {})
        game_state.monsters = snapshot.get("monsters", [])
        game_state.quests = snapshot.get("quests", [])
        game_state.pending_events = snapshot.get("pending_events", [])
        game_state.generation_metrics = snapshot.get("generation_metrics", {})

    def _run_patch_post_checks(self, game_state: GameState) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []
        checks.append({"name": "connectivity", "ok": self._check_map_connectivity(game_state)})
        checks.append({"name": "stairs_legality", "ok": self._check_stairs_legality(game_state)})
        checks.append({"name": "mandatory_reachable", "ok": self._check_mandatory_reachable(game_state)})
        checks.append({"name": "monster_event_conflict", "ok": self._check_monster_event_conflict(game_state)})
        checks.append({"name": "progress_budget_valid", "ok": self._check_progress_budget_valid(game_state)})
        return checks

    def _check_map_connectivity(self, game_state: GameState) -> bool:
        walkable = {
            pos for pos, tile in game_state.current_map.tiles.items()
            if tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE, TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}
        }
        if not walkable:
            return False
        start = next(iter(walkable))
        visited = set([start])
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt in walkable and nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return len(visited) == len(walkable)

    def _check_stairs_legality(self, game_state: GameState) -> bool:
        depth = int(game_state.current_map.depth or 1)
        max_floor = int(getattr(config.game, "max_quest_floors", 3) or 3)
        has_up = any(tile.terrain == TerrainType.STAIRS_UP for tile in game_state.current_map.tiles.values())
        has_down = any(tile.terrain == TerrainType.STAIRS_DOWN for tile in game_state.current_map.tiles.values())
        if depth <= 1 and has_up:
            return False
        if depth >= max_floor and has_down:
            return False
        return True

    def _check_mandatory_reachable(self, game_state: GameState) -> bool:
        event_tiles = [
            pos for pos, tile in game_state.current_map.tiles.items()
            if tile.has_event and isinstance(tile.event_data, dict) and tile.event_data.get("is_mandatory")
        ]
        if not event_tiles:
            return True
        walkable = {
            pos for pos, tile in game_state.current_map.tiles.items()
            if tile.terrain in {TerrainType.FLOOR, TerrainType.DOOR, TerrainType.TRAP, TerrainType.TREASURE, TerrainType.STAIRS_UP, TerrainType.STAIRS_DOWN}
        }
        if not walkable:
            return False
        start = next(iter(walkable))
        visited = set([start])
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt in walkable and nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return all(pos in visited for pos in event_tiles)

    def _check_monster_event_conflict(self, game_state: GameState) -> bool:
        for tile in game_state.current_map.tiles.values():
            if tile.character_id and tile.has_event:
                return False
        return True

    def _check_progress_budget_valid(self, game_state: GameState) -> bool:
        active_quest = next((q for q in game_state.quests if q.is_active and not q.is_completed), None)
        if not active_quest:
            return True

        plan = active_quest.progress_plan if isinstance(getattr(active_quest, "progress_plan", None), dict) else {}
        budget = plan.get("budget") if isinstance(plan.get("budget"), dict) else {}
        if not budget:
            return True

        buckets = ["events", "quest_monsters", "map_transition", "exploration_buffer"]
        consumed: Dict[str, float] = {k: 0.0 for k in buckets}

        ledger = active_quest.progress_ledger if isinstance(getattr(active_quest, "progress_ledger", None), list) else []
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            bucket = str(entry.get("bucket", "") or "")
            if bucket not in consumed:
                continue
            try:
                consumed[bucket] += float(entry.get("increment", 0.0) or 0.0)
            except (TypeError, ValueError):
                return False

        for key in buckets:
            try:
                budget_value = float(budget.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                return False
            if budget_value < 0.0:
                return False
            if consumed[key] - budget_value > 1e-6:
                return False

        return True

    def apply_player_updates(
        self,
        game_state: GameState,
        player_updates: Dict[str, Any],
        source: str = "unknown",
    ) -> ModificationResult:
        """应用玩家更新"""
        result = ModificationResult()
        player = game_state.player

        if not isinstance(player_updates, dict):
            result.success = False
            result.errors.append("player_updates 必须是对象")
            return result

        try:
            if "abilities" in player_updates:
                abilities_updates = player_updates["abilities"]
                changes = {}

                if isinstance(abilities_updates, dict):
                    for ability_name, value in abilities_updates.items():
                        if hasattr(player.abilities, ability_name):
                            old_value = getattr(player.abilities, ability_name)
                            success = entity_manager.set_ability_score(player, ability_name, value)

                            if success:
                                new_value = getattr(player.abilities, ability_name)
                                changes[ability_name] = {
                                    "old": old_value,
                                    "new": new_value
                                }
                                logger.debug(f"Updated player ability {ability_name}: {old_value} -> {new_value}")

                if changes:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_ABILITIES,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes=changes
                    )
                    result.add_record(record)

            if "stats" in player_updates:
                stats_updates = player_updates["stats"]
                changes = {}

                if isinstance(stats_updates, dict):
                    for stat_name, value in stats_updates.items():
                        if stat_name in {"shield", "temporary_hp"}:
                            runtime = self._get_combat_runtime(player)
                            old_value = int(runtime.get(stat_name, 0) or 0)
                            validated_value = self._validate_stat_value(stat_name, value, player.stats)
                            runtime[stat_name] = validated_value
                            setattr(player.stats, stat_name, validated_value)
                            changes[stat_name] = {
                                "old": old_value,
                                "new": validated_value
                            }
                            logger.debug(f"Updated player combat_runtime {stat_name}: {old_value} -> {validated_value}")
                            continue

                        if hasattr(player.stats, stat_name):
                            old_value = getattr(player.stats, stat_name)
                            validated_value = self._validate_stat_value(
                                stat_name, value, player.stats
                            )

                            setattr(player.stats, stat_name, validated_value)
                            changes[stat_name] = {
                                "old": old_value,
                                "new": validated_value
                            }

                            logger.debug(f"Updated player stat {stat_name}: {old_value} -> {validated_value}")

                if changes:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_STATS,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes=changes
                    )
                    result.add_record(record)

            if "add_items" in player_updates:
                for item_data in player_updates["add_items"]:
                    if isinstance(item_data, dict):
                        item = self._create_item_from_data(item_data)
                        player.inventory.append(item)

                        record = ModificationRecord(
                            modification_type=ModificationType.PLAYER_INVENTORY,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=player.id,
                            changes={"action": "add", "item": item.to_dict()}
                        )
                        result.add_record(record)

                        logger.info(f"Added item {item.name} to player inventory")

            if "remove_items" in player_updates:
                items_to_remove = player_updates["remove_items"]
                removed_items = []

                if isinstance(items_to_remove, list):
                    for item_name in items_to_remove:
                        for item in player.inventory[:]:
                            if item.name == item_name:
                                player.inventory.remove(item)
                                removed_items.append(item.to_dict())
                                logger.info(f"Removed item {item_name} from player inventory")
                                break

                if removed_items:
                    record = ModificationRecord(
                        modification_type=ModificationType.PLAYER_INVENTORY,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=player.id,
                        changes={"action": "remove", "items": removed_items}
                    )
                    result.add_record(record)

        except Exception as e:
            logger.error(f"Error applying player updates: {e}")
            error_record = ModificationRecord(
                modification_type=ModificationType.PLAYER_STATS,
                timestamp=datetime.now(),
                source=source,
                target_id=player.id,
                changes={},
                success=False,
                error_message=str(e)
            )
            result.add_record(error_record)

        self._sync_legacy_defense_fields(player)
        return result

    def apply_map_updates(
        self,
        game_state: GameState,
        map_updates: Dict[str, Any],
        source: str = "unknown"
    ) -> ModificationResult:
        """应用地图更新"""
        result = ModificationResult()
        current_map = game_state.current_map

        try:
            contract = resolve_generation_contract().contract
            map_update_rules = contract.get("map_updates", {}) if isinstance(contract.get("map_updates"), dict) else {}
            validation_errors = self._validate_map_updates_contract(map_updates, map_update_rules)
            for error in validation_errors:
                result.success = False
                result.errors.append(error)
            if validation_errors:
                return result

            tile_updates = map_updates.get("tiles", {})

            for tile_key, tile_data in tile_updates.items():
                try:
                    # 解析坐标
                    if "," in tile_key:
                        x, y = map(int, tile_key.split(","))
                    else:
                        logger.warning(f"Invalid tile key format: {tile_key}")
                        continue

                    # 验证坐标范围
                    if not self._validate_tile_position(current_map, x, y):
                        logger.warning(f"Invalid tile position: ({x}, {y})")
                        continue

                    # 获取或创建瓦片
                    tile = current_map.get_tile(x, y)
                    if not tile:
                        tile = MapTile(x=x, y=y)
                        current_map.set_tile(x, y, tile)

                    # 记录瓦片原本状态
                    had_event = tile.has_event
                    was_triggered = tile.event_triggered
                    changes = {}

                    # 更新瓦片属性
                    for attr_name, value in tile_data.items():
                        if attr_name == "terrain":
                            old_terrain = tile.terrain
                            new_terrain = self._parse_terrain_type(value)
                            if new_terrain:
                                tile.terrain = new_terrain
                                changes["terrain"] = {"old": old_terrain.value, "new": new_terrain.value}

                        elif attr_name == "items" and isinstance(value, list):
                            added_items = []
                            for item_data in value:
                                if isinstance(item_data, dict):
                                    item = self._create_item_from_data(item_data)
                                    tile.items.append(item)
                                    added_items.append(item.to_dict())
                            if added_items:
                                changes["items_added"] = added_items

                        elif attr_name == "monster" and isinstance(value, dict):
                            monster_result = self._handle_monster_update(game_state, x, y, value, source)
                            if monster_result.records:
                                result.records.extend(monster_result.records)

                        elif hasattr(tile, attr_name):
                            old_value = getattr(tile, attr_name)
                            setattr(tile, attr_name, value)
                            changes[attr_name] = {"old": old_value, "new": value}

                    # 保持事件触发状态
                    if had_event and was_triggered and "event_triggered" not in tile_data:
                        tile.event_triggered = True

                    if changes:
                        record = ModificationRecord(
                            modification_type=ModificationType.MAP_TILE,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=f"{x},{y}",
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated tile at ({x}, {y}): {list(changes.keys())}")

                except Exception as e:
                    logger.error(f"Error updating tile {tile_key}: {e}")
                    error_record = ModificationRecord(
                        modification_type=ModificationType.MAP_TILE,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=tile_key,
                        changes={},
                        success=False,
                        error_message=str(e)
                    )
                    result.add_record(error_record)

        except Exception as e:
            logger.error(f"Error applying map updates: {e}")
            result.success = False
            result.errors.append(f"应用地图更新时发生错误: {str(e)}")

        return result

    def apply_quest_updates(
        self,
        game_state: GameState,
        quest_updates: Dict[str, Any],
        source: str = "unknown"
    ) -> ModificationResult:
        """应用任务更新"""
        result = ModificationResult()

        try:
            # 记录本次更新中被显式设置为激活的任务ID（若有，则强制保持单活跃任务）
            last_set_active_id = None

            for quest in game_state.quests:
                quest_update = quest_updates.get(quest.id)
                if quest_update:
                    changes = {}

                    for attr_name, value in quest_update.items():
                        if hasattr(quest, attr_name):
                            old_value = getattr(quest, attr_name)
                            setattr(quest, attr_name, value)
                            changes[attr_name] = {"old": old_value, "new": value}

                            # 方案A强约束：若有任务被设置为 is_active=True，记录下来
                            if attr_name == "is_active" and bool(value) is True:
                                last_set_active_id = quest.id

                    if changes:
                        record = ModificationRecord(
                            modification_type=ModificationType.QUEST,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=quest.id,
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated quest {quest.title}: {list(changes.keys())}")

            # 方案A收尾：若本次更新显式激活了某个任务，则保证仅此任务处于激活，其他任务全部取消激活
            if last_set_active_id is not None:
                for quest in game_state.quests:
                    quest.is_active = (quest.id == last_set_active_id)
            else:
                # 若未显式设置，依然兜底：如果出现多个任务激活，仅保留第一个激活任务
                active_quests = [q for q in game_state.quests if getattr(q, "is_active", False)]
                if len(active_quests) > 1:
                    keeper_id = active_quests[0].id
                    for quest in game_state.quests:
                        quest.is_active = (quest.id == keeper_id)

        except Exception as e:
            logger.error(f"Error applying quest updates: {e}")
            result.success = False
            result.errors.append(f"应用任务更新时发生错误: {str(e)}")

        return result

    def _validate_map_updates_contract(self, map_updates: Dict[str, Any], rules: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not isinstance(map_updates, dict):
            return ["MAP_UPDATES_CONTRACT_TYPE_ERROR: map_updates must be object"]

        allowed_root_keys = rules.get("allowed_root_keys", ["tiles"])
        if not isinstance(allowed_root_keys, list) or not allowed_root_keys:
            allowed_root_keys = ["tiles"]

        unexpected_roots = [key for key in map_updates.keys() if key not in allowed_root_keys]
        if unexpected_roots:
            errors.append(f"MAP_UPDATES_CONTRACT_UNAUTHORIZED_FIELD: root keys not allowed {unexpected_roots}")

        tiles_payload = map_updates.get("tiles")
        if not isinstance(tiles_payload, dict):
            errors.append("MAP_UPDATES_CONTRACT_TYPE_ERROR: tiles must be object")
            return errors

        allowed_tile_fields = rules.get("allowed_tile_fields", [])
        if not isinstance(allowed_tile_fields, list) or not allowed_tile_fields:
            allowed_tile_fields = [
                "terrain", "items", "monster", "has_event", "event_type", "event_data",
                "is_event_hidden", "event_triggered", "items_collected", "trap_detected",
                "trap_disarmed", "room_type", "room_id", "is_explored", "is_visible", "character_id"
            ]
        allowed_tile_field_set = set(allowed_tile_fields)

        for tile_key, tile_data in tiles_payload.items():
            if not isinstance(tile_key, str) or "," not in tile_key:
                errors.append(f"MAP_UPDATES_CONTRACT_FIELD_MISMATCH: invalid tile key {tile_key}")
                continue
            if not isinstance(tile_data, dict):
                errors.append(f"MAP_UPDATES_CONTRACT_TYPE_ERROR: tile payload must be object for {tile_key}")
                continue
            unexpected_tile_fields = [field for field in tile_data.keys() if field not in allowed_tile_field_set]
            if unexpected_tile_fields:
                errors.append(
                    f"MAP_UPDATES_CONTRACT_UNAUTHORIZED_FIELD: tile {tile_key} has forbidden fields {unexpected_tile_fields}"
                )

        return errors

    def _handle_monster_update(
        self,
        game_state: GameState,
        x: int,
        y: int,
        monster_data: Dict[str, Any],
        source: str
    ) -> ModificationResult:
        """处理怪物添加/更新/移除"""
        result = ModificationResult()

        try:
            action = monster_data.get("action", "add")
            tile = game_state.current_map.get_tile(x, y)

            if not tile:
                return result

            if action == "remove":
                if tile.character_id:
                    game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]
                    tile.character_id = None
                    record = ModificationRecord(
                        modification_type=ModificationType.MONSTER,
                        timestamp=datetime.now(),
                        source=source,
                        target_id=f"{x},{y}",
                        changes={"action": "remove"}
                    )
                    result.add_record(record)
                    logger.info(f"Removed monster from tile ({x}, {y})")

            elif action == "update":
                if tile.character_id:
                    monster = next((m for m in game_state.monsters if m.id == tile.character_id), None)
                    if monster:
                        changes = {}
                        if "name" in monster_data:
                            changes["name"] = {"old": monster.name, "new": monster_data["name"]}
                            monster.name = monster_data["name"]
                        if "description" in monster_data:
                            monster.description = monster_data["description"]

                        # 支持六维属性更新 (新增)
                        if "abilities" in monster_data:
                            abilities_data = monster_data["abilities"]
                            for ability_name, value in abilities_data.items():
                                if hasattr(monster.abilities, ability_name):
                                    old_value = getattr(monster.abilities, ability_name)
                                    entity_manager.set_ability_score(monster, ability_name, value)
                                    new_value = getattr(monster.abilities, ability_name)
                                    changes[f"ability_{ability_name}"] = {"old": old_value, "new": new_value}

                        # 支持衍生属性更新
                        if "stats" in monster_data:
                            stats_data = monster_data["stats"]
                            if "hp" in stats_data:
                                monster.stats.hp = min(stats_data["hp"], monster.stats.max_hp)
                            if "max_hp" in stats_data:
                                monster.stats.max_hp = stats_data["max_hp"]
                                monster.stats.hp = min(monster.stats.hp, monster.stats.max_hp)

                        record = ModificationRecord(
                            modification_type=ModificationType.MONSTER,
                            timestamp=datetime.now(),
                            source=source,
                            target_id=monster.id,
                            changes=changes
                        )
                        result.add_record(record)
                        logger.info(f"Updated monster {monster.name} at ({x}, {y})")

            elif action == "add":
                if tile.character_id:
                    game_state.monsters = [m for m in game_state.monsters if m.id != tile.character_id]

                monster = Monster()
                monster.name = monster_data.get("name", "神秘生物")
                monster.description = monster_data.get("description", "一个神秘的生物")
                monster.character_class = CharacterClass.FIGHTER
                monster.position = (x, y)
                monster.challenge_rating = monster_data.get("challenge_rating", 1.0)
                monster.behavior = monster_data.get("behavior", "aggressive")
                monster.is_boss = monster_data.get("is_boss", False)
                monster.quest_monster_id = monster_data.get("quest_monster_id")
                monster.attack_range = monster_data.get("attack_range", 1)

                if "stats" in monster_data:
                    stats_data = monster_data["stats"]
                    monster.stats.max_hp = stats_data.get("max_hp", 20)
                    monster.stats.hp = stats_data.get("hp", monster.stats.max_hp)
                    monster.stats.max_mp = stats_data.get("max_mp", 10)
                    monster.stats.mp = stats_data.get("mp", monster.stats.max_mp)
                    monster.stats.ac = stats_data.get("ac", 12)
                    monster.stats.level = stats_data.get("level", 1)

                game_state.monsters.append(monster)
                tile.character_id = monster.id

                record = ModificationRecord(
                    modification_type=ModificationType.MONSTER,
                    timestamp=datetime.now(),
                    source=source,
                    target_id=monster.id,
                    changes={"action": "add", "monster": monster.to_dict()}
                )
                result.add_record(record)
                logger.info(f"Added new monster {monster.name} at ({x}, {y})")

        except Exception as e:
            logger.error(f"Error handling monster update: {e}")
            error_record = ModificationRecord(
                modification_type=ModificationType.MONSTER,
                timestamp=datetime.now(),
                source=source,
                target_id=f"{x},{y}",
                changes={},
                success=False,
                error_message=str(e)
            )
            result.add_record(error_record)

        return result

    # ==================== 玩家状态统一写入口 ====================

    def apply_player_progression_updates(
        self,
        game_state: GameState,
        experience_gained: int = 0,
        source: str = "unknown"
    ) -> Dict[str, Any]:
        """统一处理经验与升级写入入口"""
        safe_gain = max(0, int(experience_gained or 0))
        player = game_state.player
        before_level = int(player.stats.level)

        updates = {
            "stats": {
                "experience": int(player.stats.experience) + safe_gain
            }
        }
        apply_result = self.apply_player_updates(game_state, updates, source=source)
        if not apply_result.success:
            return {
                "success": False,
                "errors": apply_result.errors,
                "level_up": False,
                "level_up_count": 0,
            }

        level_up_count = 0
        while int(player.stats.experience) >= int(player.stats.level) * 1000:
            current_level = int(player.stats.level)
            if current_level >= 100:
                # 等级封顶：保留经验，不再继续扣减
                break

            next_level = current_level + 1
            remain_exp = int(player.stats.experience) - (current_level * 1000)
            next_max_hp = int(player.stats.max_hp) + 10
            next_max_mp = int(player.stats.max_mp) + 5
            level_updates = {
                "stats": {
                    "level": next_level,
                    "experience": max(0, remain_exp),
                    "max_hp": next_max_hp,
                    "hp": next_max_hp,
                    "max_mp": next_max_mp,
                    "mp": next_max_mp,
                }
            }
            level_result = self.apply_player_updates(game_state, level_updates, source=f"{source}:level_up")
            if not level_result.success:
                return {
                    "success": False,
                    "errors": level_result.errors,
                    "level_up": level_up_count > 0,
                    "level_up_count": level_up_count,
                }

            # 防御性保护：若等级未实际提升，避免死循环和经验被异常扣减
            if int(player.stats.level) <= current_level:
                logger.warning("Level-up write had no effect, stop progression loop: level=%s", player.stats.level)
                break

            player.update_proficiency_bonus()
            level_up_count += 1

        return {
            "success": True,
            "errors": [],
            "level_up": int(player.stats.level) > before_level,
            "level_up_count": level_up_count,
        }

    def apply_player_resource_delta(
        self,
        game_state: GameState,
        hp_delta: int = 0,
        mp_delta: int = 0,
        source: str = "unknown"
    ) -> ModificationResult:
        """统一处理 HP/MP 资源变化写入入口"""
        player = game_state.player
        try:
            current_hp = int(getattr(player.stats, "hp", 0) or 0)
        except (TypeError, ValueError):
            current_hp = 0

        try:
            current_mp = int(getattr(player.stats, "mp", 0) or 0)
        except (TypeError, ValueError):
            current_mp = 0

        next_hp = current_hp + int(hp_delta or 0)
        next_mp = current_mp + int(mp_delta or 0)
        return self.apply_player_updates(
            game_state,
            {
                "stats": {
                    "hp": next_hp,
                    "mp": next_mp,
                }
            },
            source=source,
        )

    # ==================== 验证方法 ====================

    def _validate_stat_value(self, stat_name: str, value: Any, stats: Stats) -> Any:
        """验证并调整属性值"""
        try:
            # 确保值是数字
            if not isinstance(value, (int, float)):
                value = int(value)

            # 特殊属性的范围限制
            if stat_name == "hp":
                return max(0, min(value, stats.max_hp))
            elif stat_name == "mp":
                return max(0, min(value, stats.max_mp))
            elif stat_name in ["max_hp", "max_mp"]:
                return max(1, value)
            elif stat_name == "experience":
                return max(0, value)
            elif stat_name == "level":
                return max(1, min(value, 100))  # 最高等级100
            elif stat_name == "ac":
                return max(0, min(value, 50))  # 护甲等级上限50
            elif stat_name in ["shield", "temporary_hp"]:
                return max(0, value)
            else:
                # 其他属性（力量、敏捷等）
                return max(1, min(value, 30))  # 属性范围1-30

        except Exception as e:
            logger.error(f"Error validating stat {stat_name}={value}: {e}")
            return getattr(stats, stat_name)  # 返回原值

    def _get_combat_runtime(self, player: Character) -> Dict[str, int]:
        runtime = getattr(player, "combat_runtime", None)

        def _safe_non_negative_int(value: Any, default: int = 0) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return max(0, int(default or 0))

        if not isinstance(runtime, dict):
            runtime = {
                "shield": _safe_non_negative_int(getattr(player.stats, "shield", 0), 0),
                "temporary_hp": _safe_non_negative_int(getattr(player.stats, "temporary_hp", 0), 0),
            }
            player.combat_runtime = runtime

        runtime.setdefault("shield", _safe_non_negative_int(getattr(player.stats, "shield", 0), 0))
        runtime.setdefault("temporary_hp", _safe_non_negative_int(getattr(player.stats, "temporary_hp", 0), 0))
        runtime["shield"] = _safe_non_negative_int(runtime.get("shield", 0), getattr(player.stats, "shield", 0))
        runtime["temporary_hp"] = _safe_non_negative_int(runtime.get("temporary_hp", 0), getattr(player.stats, "temporary_hp", 0))
        return runtime

    def _sync_legacy_defense_fields(self, player: Character):
        runtime = self._get_combat_runtime(player)
        player.stats.shield = int(runtime.get("shield", 0) or 0)
        player.stats.temporary_hp = int(runtime.get("temporary_hp", 0) or 0)

    def _validate_tile_position(self, game_map: 'GameMap', x: int, y: int) -> bool:
        """验证瓦片位置是否有效"""
        return 0 <= x < game_map.width and 0 <= y < game_map.height

    def _parse_terrain_type(self, terrain_value: str) -> Optional[TerrainType]:
        """解析地形类型"""
        try:
            if hasattr(TerrainType, terrain_value.upper()):
                return TerrainType(terrain_value.lower())
            else:
                logger.warning(f"Unknown terrain type: {terrain_value}")
                return None
        except Exception as e:
            logger.error(f"Error parsing terrain type {terrain_value}: {e}")
            return None

    def _create_item_from_data(self, item_data: Dict[str, Any]) -> Item:
        """从数据字典创建物品对象"""
        item = Item(
            name=item_data.get("name", "神秘物品"),
            description=item_data.get("description", "一个神秘的物品"),
            item_type=item_data.get("item_type", "misc"),
            rarity=item_data.get("rarity", "common")
        )

        # 设置其他可选属性
        if "usage_description" in item_data:
            item.usage_description = item_data["usage_description"]
        if "properties" in item_data:
            item.properties = item_data["properties"]
        if "value" in item_data:
            item.value = item_data["value"]
        if "weight" in item_data:
            item.weight = item_data["weight"]
        if "effect_payload" in item_data:
            item.effect_payload = item_data.get("effect_payload", {}) or {}
        if "use_mode" in item_data:
            item.use_mode = item_data.get("use_mode", "active")
        if "is_equippable" in item_data:
            item.is_equippable = bool(item_data.get("is_equippable", False))
        if "equip_slot" in item_data:
            item.equip_slot = item_data.get("equip_slot", "")
        if "max_charges" in item_data:
            item.max_charges = int(item_data.get("max_charges", 0) or 0)
        if "charges" in item_data:
            item.charges = int(item_data.get("charges", item.max_charges) or 0)
        else:
            item.charges = item.max_charges
        if "cooldown_turns" in item_data:
            item.cooldown_turns = int(item_data.get("cooldown_turns", 0) or 0)
        if "current_cooldown" in item_data:
            item.current_cooldown = int(item_data.get("current_cooldown", 0) or 0)
        if "is_quest_item" in item_data:
            item.is_quest_item = bool(item_data.get("is_quest_item", False))
        if "quest_lock_reason" in item_data:
            item.quest_lock_reason = str(item_data.get("quest_lock_reason", "") or "")
        if "hint_level" in item_data:
            hint_level = str(item_data.get("hint_level", "vague") or "vague").strip().lower()
            item.hint_level = hint_level if hint_level in {"none", "vague", "clear"} else "vague"
        if "trigger_hint" in item_data:
            item.trigger_hint = str(item_data.get("trigger_hint", "") or "")
        if "risk_hint" in item_data:
            item.risk_hint = str(item_data.get("risk_hint", "") or "")
        if "expected_outcomes" in item_data:
            outcomes = item_data.get("expected_outcomes", [])
            if isinstance(outcomes, list):
                item.expected_outcomes = [str(v) for v in outcomes if str(v).strip()]
            elif outcomes:
                item.expected_outcomes = [str(outcomes)]
            else:
                item.expected_outcomes = []
        if "requires_use_confirmation" in item_data:
            item.requires_use_confirmation = bool(item_data.get("requires_use_confirmation", False))
        if "consumption_hint" in item_data:
            item.consumption_hint = str(item_data.get("consumption_hint", "") or "")

        return item

    # ==================== 历史记录管理 ====================

    def _add_to_history(self, records: List[ModificationRecord]):
        """添加记录到历史"""
        self.modification_history.extend(records)

        # 限制历史记录大小
        if len(self.modification_history) > self.max_history_size:
            self.modification_history = self.modification_history[-self.max_history_size:]

    def get_modification_history(
        self,
        limit: int = 20,
        modification_type: Optional[ModificationType] = None,
        source: Optional[str] = None
    ) -> List[ModificationRecord]:
        """
        获取修改历史

        Args:
            limit: 返回记录数量限制
            modification_type: 筛选特定类型的修改
            source: 筛选特定来源的修改

        Returns:
            修改记录列表
        """
        filtered_history = self.modification_history

        if modification_type:
            filtered_history = [r for r in filtered_history if r.modification_type == modification_type]

        if source:
            filtered_history = [r for r in filtered_history if r.source == source]

        return filtered_history[-limit:]

    def clear_history(self):
        """清空修改历史"""
        self.modification_history.clear()
        logger.info("Modification history cleared")

    def get_statistics(self) -> Dict[str, Any]:
        """获取修改统计信息"""
        stats = {
            "total_modifications": len(self.modification_history),
            "successful_modifications": sum(1 for r in self.modification_history if r.success),
            "failed_modifications": sum(1 for r in self.modification_history if not r.success),
            "by_type": {},
            "by_source": {}
        }

        # 按类型统计
        for mod_type in ModificationType:
            count = sum(1 for r in self.modification_history if r.modification_type == mod_type)
            if count > 0:
                stats["by_type"][mod_type.value] = count

        # 按来源统计
        sources = set(r.source for r in self.modification_history)
        for source in sources:
            count = sum(1 for r in self.modification_history if r.source == source)
            stats["by_source"][source] = count

        return stats


# 全局实例
game_state_modifier = GameStateModifier()

__all__ = [
    "GameStateModifier",
    "ModificationResult",
    "ModificationRecord",
    "ModificationType",
    "game_state_modifier"
]

