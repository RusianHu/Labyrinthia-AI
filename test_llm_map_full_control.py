import asyncio
import random
from typing import Dict, Any

import pytest

from data_models import GameState, GameMap, MapTile, TerrainType, Quest, QuestMonster, QuestEvent, EventChoice, EventChoiceContext, Monster
from debug_api import DebugAPI
from event_choice_system import event_choice_system, ChoiceResult
from game_engine import game_engine
from game_state_lock_manager import game_state_lock_manager
from game_state_modifier import game_state_modifier
from generation_contract import resolve_generation_contract, contract_hash
from llm_service import llm_service
from local_map_provider import local_map_provider
from monster_spawn_manager import monster_spawn_manager
from progress_manager import ProgressContext, ProgressEventType, progress_manager
from content_generator import content_generator
from config import config


def _build_basic_map(width: int = 10, height: int = 10, depth: int = 1) -> GameMap:
    game_map = GameMap(width=width, height=height, depth=depth)
    for x in range(width):
        for y in range(height):
            terrain = TerrainType.FLOOR
            if x in {0, width - 1} or y in {0, height - 1}:
                terrain = TerrainType.WALL
            game_map.tiles[(x, y)] = MapTile(x=x, y=y, terrain=terrain)

    # 预放楼梯，便于楼梯合法性与可达性相关逻辑
    game_map.tiles[(1, 1)].terrain = TerrainType.STAIRS_UP
    game_map.tiles[(width - 2, height - 2)].terrain = TerrainType.STAIRS_DOWN
    return game_map


def _build_active_quest(*, final_objective: bool = True) -> Quest:
    quest = Quest(
        title="测试任务",
        description="用于验证进度与守卫逻辑",
        is_active=True,
        is_completed=False,
        progress_percentage=0.0,
        target_floors=[3],
        progress_plan={
            "completion_policy": "single_target_100" if final_objective else "hybrid",
            "budget": {
                "events": 30.0,
                "quest_monsters": 40.0,
                "map_transition": 20.0,
                "exploration_buffer": 10.0,
            },
            "final_objective_id": "qm-final" if final_objective else "",
        },
        completion_guard={
            "require_final_floor": True,
            "require_all_mandatory_events": False,
            "min_progress_before_final_burst": 70.0,
            "max_single_increment_except_final": 25.0,
        },
    )

    quest.special_monsters = [
        QuestMonster(
            id="qm-final",
            name="终局目标",
            is_final_objective=final_objective,
            progress_value=100.0,
            is_boss=True,
            phase_count=2,
            special_status_pack=["shield"],
        ),
        QuestMonster(
            id="qm-normal",
            name="普通任务怪",
            is_final_objective=False,
            progress_value=20.0,
            is_boss=False,
        ),
    ]

    quest.special_events = [
        QuestEvent(
            id="qe-1",
            event_type="story",
            name="关键事件",
            is_mandatory=True,
            progress_value=10.0,
            location_hint="第3层",
        )
    ]
    return quest


@pytest.fixture(autouse=True)
def _isolate_globals():
    old_active_games = dict(game_engine.active_games)
    old_locks = dict(game_state_lock_manager._locks)
    try:
        game_engine.active_games.clear()
        game_state_lock_manager._locks.clear()
        yield
    finally:
        game_engine.active_games.clear()
        game_engine.active_games.update(old_active_games)
        game_state_lock_manager._locks.clear()
        game_state_lock_manager._locks.update(old_locks)


def test_fixed_seed_scenarios_map_generation_library():
    scenarios = [
        {"name": "boss", "quest_type": "boss_fight", "theme": "combat"},
        {"name": "exploration", "quest_type": "exploration", "theme": "abandoned"},
        {"name": "rescue", "quest_type": "rescue", "theme": "cave"},
        {"name": "investigation", "quest_type": "investigation", "theme": "town"},
        {"name": "multi_objective", "quest_type": "exploration", "theme": "magic"},
    ]

    for idx, scenario in enumerate(scenarios):
        random.seed(20260225 + idx)
        quest_context: Dict[str, Any] = {
            "quest_type": scenario["quest_type"],
            "description": f"fixed_seed::{scenario['name']}",
            "special_events": [
                {
                    "id": f"ev-{idx}",
                    "event_type": "relic",
                    "name": "回收点",
                    "is_mandatory": True,
                    "location_hint": "第1层",
                }
            ],
        }
        game_map, _monster_hints = local_map_provider.generate_map(
            width=20,
            height=20,
            depth=1,
            theme=scenario["theme"],
            quest_context=quest_context,
        )
        meta = game_map.generation_metadata
        local_validation = meta.get("local_validation", {})

        assert len(game_map.tiles) == 400
        assert meta.get("contract_version")
        assert isinstance(meta.get("contract_hash"), str)
        assert local_validation.get("connectivity_ok") is True
        assert local_validation.get("key_objective_unreachable") is False
        assert local_validation.get("stairs", {}).get("ok") is True


def test_contract_compatibility_and_hashing():
    resolved = resolve_generation_contract(requested_version="1.0", source_hint="llm")
    assert resolved.contract["contract_version"] == "2.0.0"
    assert any("unsupported_contract_version" in w for w in resolved.warnings)

    manual = resolve_generation_contract(
        provided_contract={
            "progress": {"completion_policy": "hybrid"},
            "blueprint": {"max_nodes": 16},
        },
        requested_version="v2",
        source_hint="manual",
    )
    assert manual.contract["progress"]["completion_policy"] == "hybrid"
    assert manual.contract["blueprint"]["max_nodes"] == 16
    assert len(contract_hash(manual.contract)) == 64


@pytest.mark.asyncio
async def test_single_target_100_guard_pass(monkeypatch):
    async def _fake_llm_json(_prompt: str):
        return {
            "story_context": "守卫通过",
            "llm_notes": "ok",
            "should_complete": True,
        }

    monkeypatch.setattr(llm_service, "_async_generate_json", _fake_llm_json)

    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=3)

    quest = _build_active_quest(final_objective=True)
    quest.progress_percentage = 80.0
    game_state.quests = [quest]

    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={
            "quest_monster_id": "qm-final",
            "progress_value": 100.0,
        },
    )

    result = await progress_manager.process_event(context)

    assert result["success"] is True
    assert result["new_progress"] == 100.0
    assert quest.is_completed is True
    assert game_state.generation_metrics["progress_metrics"]["final_objective_direct_completion"] >= 1


@pytest.mark.asyncio
async def test_single_target_100_guard_block_with_reason(monkeypatch):
    async def _fake_llm_json(_prompt: str):
        return {
            "story_context": "守卫阻断",
            "llm_notes": "blocked",
            "should_complete": False,
        }

    monkeypatch.setattr(llm_service, "_async_generate_json", _fake_llm_json)

    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=2)

    quest = _build_active_quest(final_objective=True)
    quest.progress_percentage = 60.0
    game_state.quests = [quest]

    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={
            "quest_monster_id": "qm-final",
            "progress_value": 100.0,
        },
    )

    result = await progress_manager.process_event(context)

    assert result["success"] is True
    assert result["new_progress"] < 100.0
    assert quest.is_completed is False
    assert "require_final_floor_not_met" in result.get("guard_reasons", [])
    metrics = game_state.generation_metrics["progress_metrics"]
    assert metrics["final_objective_guard_blocked"] >= 1
    assert metrics["final_objective_guard_blocked_reasons"].get("require_final_floor_not_met", 0) >= 1


@pytest.mark.asyncio
async def test_hybrid_policy_caps_non_final_single_increment(monkeypatch):
    async def _fake_llm_json(_prompt: str):
        return {
            "story_context": "hybrid",
            "llm_notes": "hybrid",
            "should_complete": False,
        }

    monkeypatch.setattr(llm_service, "_async_generate_json", _fake_llm_json)

    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)

    quest = _build_active_quest(final_objective=False)
    quest.progress_percentage = 0.0
    quest.completion_guard["max_single_increment_except_final"] = 25.0
    game_state.quests = [quest]

    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={
            "quest_monster_id": "qm-normal",
            "progress_value": 999.0,
        },
    )

    result = await progress_manager.process_event(context)

    assert result["success"] is True
    assert result["progress_increment"] <= 25.0
    assert result["new_progress"] < 100.0


@pytest.mark.asyncio
async def test_lock_manager_concurrency_consistency():
    user_id = "lock-user"
    game_id = "lock-game"
    counter = {"value": 0}

    async def _worker():
        async with game_state_lock_manager.lock_game_state(user_id, game_id, "test_concurrent"):
            old = counter["value"]
            await asyncio.sleep(0.005)
            counter["value"] = old + 1

    await asyncio.gather(*[_worker() for _ in range(20)])

    assert counter["value"] == 20
    lock_stats = game_state_lock_manager.get_lock_stats()
    assert lock_stats["total_locks"] >= 1


def test_debug_alert_classification_and_blocking_view():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)
    game_state.generation_metrics = {
        "map_generation": {
            "total": 100,
            "success": 96,
            "failed": 4,
            "fallback_used": 3,
            "rollback_used": 1,
            "repairs": 5,
            "unreachable_reports": 2,
            "stairs_violations": 2,
            "error_codes": {"MAP_GENERATION_FAILED": 4},
        },
        "progress_metrics": {
            "total_events": 100,
            "anomaly_events": 12,
            "final_objective_direct_completion": 20,
            "final_objective_guard_blocked": 10,
            "anomaly_codes": {"single_increment_spike": 12},
            "final_objective_guard_blocked_reasons": {"require_final_floor_not_met": 10},
        },
    }

    game_engine.active_games[("u-alert", "g-alert")] = game_state
    status = DebugAPI.get_system_status()

    assert status["success"] is True
    assert status["derived_rates"]["key_objective_unreachable_rate"] == 0.02
    assert status["derived_rates"]["stairs_violation_rate"] == 0.02
    assert status["derived_rates"]["progress_anomaly_rate"] == 0.12
    assert status["derived_rates"]["final_objective_guard_block_rate"] == 0.333333
    assert status["alerts"]["has_p1"] is True


def test_sample_a_relic_recovery_baseline():
    random.seed(2026022501)
    quest_context = {
        "quest_type": "exploration",
        "description": "终局回收遗物",
        "special_events": [
            {
                "id": "relic-event",
                "event_type": "relic_recovery",
                "name": "遗物回收点",
                "is_mandatory": True,
                "location_hint": "第1层",
            }
        ],
        "special_monsters": [
            {
                "id": "guard-1",
                "name": "遗物守卫",
                "is_boss": True,
                "is_final_objective": True,
                "phase_count": 2,
                "special_status_pack": ["shield", "burn", "illegal_status"],
                "challenge_rating": 8.0,
                "progress_value": 20.0,
            }
        ],
    }

    game_map, _ = local_map_provider.generate_map(
        width=22,
        height=22,
        depth=1,
        theme="abandoned",
        quest_context=quest_context,
    )
    local_validation = game_map.generation_metadata.get("local_validation", {})
    assert local_validation.get("mandatory_events_expected", 0) >= 1
    assert local_validation.get("mandatory_events_placed", 0) >= 1
    assert local_validation.get("connectivity_ok") is True


@pytest.mark.asyncio
async def test_sample_b_high_power_final_objective_guard_and_completion_policy(monkeypatch):
    async def _fake_llm_json(_prompt: str):
        return {
            "story_context": "终局守卫",
            "llm_notes": "final objective",
            "should_complete": True,
        }

    monkeypatch.setattr(llm_service, "_async_generate_json", _fake_llm_json)

    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=3)

    quest = _build_active_quest(final_objective=True)
    quest.progress_plan["completion_policy"] = "single_target_100"
    quest.progress_percentage = 85.0
    game_state.quests = [quest]

    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={
            "quest_monster_id": "qm-final",
            "progress_value": 100.0,
        },
    )

    result = await progress_manager.process_event(context)

    assert result["success"] is True
    assert result["new_progress"] == 100.0
    assert quest.is_completed is True


@pytest.mark.asyncio
async def test_sample_b_aggregate_policy_blocks_direct_100(monkeypatch):
    async def _fake_llm_json(_prompt: str):
        return {
            "story_context": "aggregate",
            "llm_notes": "aggregate",
            "should_complete": False,
        }

    monkeypatch.setattr(llm_service, "_async_generate_json", _fake_llm_json)

    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=3)

    quest = _build_active_quest(final_objective=True)
    quest.progress_plan["completion_policy"] = "aggregate"
    quest.progress_percentage = 70.0
    game_state.quests = [quest]

    context = ProgressContext(
        event_type=ProgressEventType.COMBAT_VICTORY,
        game_state=game_state,
        context_data={
            "quest_monster_id": "qm-final",
            "progress_value": 100.0,
        },
    )

    result = await progress_manager.process_event(context)

    assert result["success"] is True
    assert result["new_progress"] < 100.0
    assert quest.is_completed is False
    assert "completion_policy_disallow_final_burst" in result.get("guard_reasons", [])


@pytest.mark.asyncio
async def test_trap_choice_retreat_uses_choice_id_without_crash():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)
    game_state.current_map.tiles[(2, 2)].terrain = TerrainType.TRAP

    context = EventChoiceContext(
        event_type="trap_event",
        title="陷阱测试",
        description="测试退后分支",
        context_data={
            "trap_data": {"trap_type": "damage", "damage": 1},
            "position": [2, 2],
        },
    )
    choice = EventChoice(id="retreat", text="后退")

    result = await event_choice_system._handle_trap_choice(game_state, context, choice)

    assert isinstance(result, ChoiceResult)
    assert result.success is True
    assert "后退" in result.message


def test_apply_player_updates_main_path_available_and_effective():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)
    game_state.player.stats.hp = 50
    game_state.player.stats.max_hp = 100

    mod = game_state_modifier.apply_player_updates(
        game_state,
        {
            "stats": {"hp": 80},
            "add_items": [
                {
                    "name": "测试药剂",
                    "description": "测试",
                    "item_type": "consumable",
                    "rarity": "common",
                }
            ],
        },
        source="test",
    )

    assert mod.success is True
    assert game_state.player.stats.hp == 80
    assert any(item.name == "测试药剂" for item in game_state.player.inventory)


def test_patch_stage_fallback_to_config_when_map_metadata_missing():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)
    game_state.current_map.generation_metadata = {}

    old_stage = config.game.map_generation_release_stage
    old_disable = config.game.map_generation_disable_high_risk_patch

    try:
        config.game.map_generation_release_stage = "stable"
        config.game.map_generation_disable_high_risk_patch = True

        result = game_state_modifier.apply_patch_batch(
            game_state,
            {
                "patches": [
                    {
                        "id": "p1",
                        "op": "update",
                        "target": "event",
                        "tile": "2,2",
                        "risk_level": "high",
                        "payload": {
                            "has_event": True,
                            "event_type": "story",
                            "event_data": {"id": "e1"},
                        },
                    }
                ],
                "rollback_mode": "full",
            },
            source="test",
        )

        assert result.success is False
        assert len(result.accepted_patches) == 1
        assert len(result.rejected_patches) == 0
        assert any(d.get("code") == "PATCH_POST_CHECK_FAILED" for d in result.diagnostics)
    finally:
        config.game.map_generation_release_stage = old_stage
        config.game.map_generation_disable_high_risk_patch = old_disable


def test_patch_post_check_budget_guard_triggers_rollback():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)

    quest = _build_active_quest(final_objective=False)
    quest.progress_plan = {
        "completion_policy": "aggregate",
        "budget": {
            "events": 1.0,
            "quest_monsters": 1.0,
            "map_transition": 1.0,
            "exploration_buffer": 1.0,
        },
        "final_objective_id": "",
    }
    quest.progress_ledger = [{"bucket": "events", "increment": 2.0}]
    game_state.quests = [quest]

    result = game_state_modifier.apply_patch_batch(
        game_state,
        {
            "patches": [
                {
                    "id": "budget-postcheck",
                    "op": "update",
                    "target": "event",
                    "tile": "2,2",
                    "risk_level": "low",
                    "payload": {
                        "has_event": True,
                        "event_type": "story",
                        "event_data": {"id": "e-budget"},
                    },
                }
            ],
            "rollback_mode": "full",
        },
        source="test",
    )

    assert result.success is False
    assert result.rollback_applied is True
    assert any(d.get("code") == "PATCH_POST_CHECK_FAILED" for d in result.diagnostics)


def test_patch_post_check_conflict_guard_triggers_rollback():
    game_state = GameState()
    game_state.current_map = _build_basic_map(depth=1)
    game_state.current_map.tiles[(2, 2)].has_event = True
    game_state.current_map.tiles[(2, 2)].event_type = "story"

    result = game_state_modifier.apply_patch_batch(
        game_state,
        {
            "patches": [
                {
                    "id": "conflict-postcheck",
                    "op": "add",
                    "target": "monster",
                    "tile": "2,2",
                    "risk_level": "low",
                    "payload": {
                        "name": "冲突怪",
                        "stats": {"hp": 10, "max_hp": 10, "level": 1, "ac": 10},
                    },
                }
            ],
            "rollback_mode": "full",
        },
        source="test",
    )

    assert result.success is False
    assert result.rollback_applied is True
    assert any(d.get("code") == "PATCH_POST_CHECK_FAILED" for d in result.diagnostics)


def test_monster_guardrails_allow_666_when_final_and_budget_pass_after_downgrade():
    monster = Monster(name="终局怪")
    monster.stats.max_hp = 666
    monster.stats.hp = 666
    monster.stats.level = 20
    monster.stats.ac = 10

    adjusted, report = monster_spawn_manager._apply_monster_guardrails(
        monster=monster,
        player_level=1,
        current_floor=3,
        max_floor=3,
        is_final_objective=True,
        policy=monster_spawn_manager._build_monster_customization_policy(),
    )

    assert adjusted.stats.max_hp == 666
    assert report.get("power_budget_pass") is True
    assert any(a.get("reason") == "high_hp_allowed_final_objective" for a in report.get("adjustments", []))


def test_blueprint_sanitize_whitelist_follow_contract_override():
    blueprint = {
        "room_nodes": [
            {
                "id": "room-1",
                "role": "entrance",
                "size": "small",
                "placement_policy": "branch",
            }
        ],
        "corridor_edges": [],
    }
    contract = resolve_generation_contract(
        provided_contract={
            "blueprint": {
                "placement_policy_whitelist": ["center"],
                "room_size_whitelist": ["small"],
            }
        },
        source_hint="manual",
    ).contract

    sanitized, _ = content_generator._sanitize_blueprint(blueprint, contract)
    node = sanitized["room_nodes"][0]

    assert node.get("size") == "small"
    assert "placement_policy" not in node
