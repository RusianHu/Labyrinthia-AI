"""
Labyrinthia AI - Combat Core
Phase 1 minimal unified combat evaluation pipeline.
"""

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from data_models import Character, DamageType, Monster
from roll_resolver import CheckResult, RollResolver, roll_resolver


@dataclass
class CombatSnapshot:
    """战斗快照（最小闭环版本）"""

    entity_id: str
    name: str
    hp: int
    max_hp: int
    ac: int
    level: int
    abilities: Dict[str, int] = field(default_factory=dict)
    shield: int = 0
    temporary_hp: int = 0
    resistances: Dict[str, float] = field(default_factory=dict)
    vulnerabilities: Dict[str, float] = field(default_factory=dict)
    immunities: List[str] = field(default_factory=list)
    status_modifiers: Dict[str, Any] = field(default_factory=dict)
    equipment_modifiers: Dict[str, Any] = field(default_factory=dict)
    terrain_modifiers: Dict[str, Any] = field(default_factory=dict)
    temporary_effects: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DamagePacket:
    """伤害包（最小闭环版本）"""

    source_id: str
    target_id: str
    damage_type: str = DamageType.PHYSICAL.value
    base_damage: int = 0
    damage_multiplier: float = 1.0
    penetration: Dict[str, float] = field(default_factory=dict)
    can_critical: bool = True
    true_damage: bool = False
    damage_components: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MitigationStage:
    """减免链单步记录"""

    stage: str
    before: int
    after: int
    delta: int
    reason: str


@dataclass
class MitigationResult:
    """减免结果"""

    stages: List[MitigationStage] = field(default_factory=list)
    final_damage: int = 0
    shield_absorbed: int = 0
    temporary_hp_absorbed: int = 0
    resistance_multiplier: float = 1.0
    vulnerability_multiplier: float = 1.0
    damage_by_type: Dict[str, int] = field(default_factory=dict)


@dataclass
class CombatEvaluationResult:
    """统一战斗求值结果"""

    hit: bool
    critical: bool
    miss_reason: str
    attack_roll: Dict[str, Any]
    damage_packet: DamagePacket
    mitigation: MitigationResult
    final_damage: int
    target_hp_before: int
    target_hp_after: int
    death: bool
    events: List[str] = field(default_factory=list)
    breakdown: List[Dict[str, Any]] = field(default_factory=list)

    def to_projection(self) -> Dict[str, Any]:
        return {
            "hit": bool(self.hit),
            "damage": int(self.final_damage),
            "death": bool(self.death),
            "exp": 0,
        }


class CombatCoreEvaluator:
    """统一战斗求值器（Phase 1 最小闭环）"""

    def __init__(self, resolver: Optional[RollResolver] = None, rng_seed: Optional[int] = None):
        self.resolver = resolver or roll_resolver
        self._rng = random.Random(rng_seed)

    def _get_defense_runtime(self, entity: Union[Character, Monster]) -> Dict[str, int]:
        runtime = getattr(entity, "combat_runtime", None)
        if not isinstance(runtime, dict):
            runtime = {
                "shield": int(getattr(entity.stats, "shield", 0) or 0),
                "temporary_hp": int(getattr(entity.stats, "temporary_hp", 0) or 0),
            }
            setattr(entity, "combat_runtime", runtime)

        runtime.setdefault("shield", int(getattr(entity.stats, "shield", 0) or 0))
        runtime.setdefault("temporary_hp", int(getattr(entity.stats, "temporary_hp", 0) or 0))
        runtime["shield"] = max(0, int(runtime.get("shield", 0) or 0))
        runtime["temporary_hp"] = max(0, int(runtime.get("temporary_hp", 0) or 0))
        return runtime

    def _sync_legacy_defense_fields(self, entity: Union[Character, Monster]):
        runtime = self._get_defense_runtime(entity)
        entity.stats.shield = int(runtime.get("shield", 0) or 0)
        entity.stats.temporary_hp = int(runtime.get("temporary_hp", 0) or 0)

    def evaluate_attack(
        self,
        attacker: Union[Character, Monster],
        defender: Union[Character, Monster],
        *,
        attack_type: str = "melee",
        base_damage: Optional[int] = None,
        damage_type: str = DamageType.PHYSICAL.value,
        can_critical: bool = True,
        attack_bonus: int = 0,
        damage_bonus: int = 0,
        minimum_damage: int = 1,
        deterministic_seed: Optional[int] = None,
        damage_components: Optional[Dict[str, int]] = None,
        penetration: Optional[Dict[str, float]] = None,
        true_damage: bool = False,
        trace_id: str = "",
        mitigation_policy: Optional[Dict[str, Any]] = None,
    ) -> CombatEvaluationResult:
        local_rng = self._rng
        if deterministic_seed is not None:
            local_rng = random.Random(int(deterministic_seed))

        self._ensure_effective_ac(defender)

        attack_roll = self._roll_attack_with_seed(
            attacker,
            defender,
            attack_type=attack_type,
            attack_bonus=int(attack_bonus),
            deterministic_seed=deterministic_seed,
        )

        attack_info = self._serialize_attack_roll(attack_roll)
        target_hp_before = int(getattr(defender.stats, "hp", 0) or 0)

        base = int(base_damage) if base_damage is not None else self._roll_base_damage(attacker, rng=local_rng)
        normalized_damage_components = self._normalize_damage_components(
            damage_type=str(damage_type or DamageType.PHYSICAL.value),
            base_damage=max(0, base + int(damage_bonus)),
            damage_components=damage_components,
        )
        damage_packet = DamagePacket(
            source_id=str(getattr(attacker, "id", "")),
            target_id=str(getattr(defender, "id", "")),
            damage_type=str(damage_type or DamageType.PHYSICAL.value),
            base_damage=max(0, sum(normalized_damage_components.values())),
            can_critical=bool(can_critical),
            penetration=dict(penetration or {}),
            true_damage=bool(true_damage),
            damage_components=normalized_damage_components,
            metadata={"trace_id": trace_id},
        )

        breakdown: List[Dict[str, Any]] = []
        breakdown.append(
            {
                "stage": "hit_check",
                "before": int(attack_roll.total),
                "after": int(attack_roll.total),
                "delta": 0,
                "reason": f"roll={attack_roll.roll}, total={attack_roll.total}, target_ac={attack_roll.target_ac}",
            }
        )

        if not attack_roll.success:
            events = [f"攻击未命中（{attack_roll.total} vs AC {attack_roll.target_ac}）"]
            return CombatEvaluationResult(
                hit=False,
                critical=False,
                miss_reason="attack_roll_failed",
                attack_roll=attack_info,
                damage_packet=damage_packet,
                mitigation=MitigationResult(final_damage=0),
                final_damage=0,
                target_hp_before=target_hp_before,
                target_hp_after=target_hp_before,
                death=False,
                events=events,
                breakdown=breakdown,
            )

        raw_damage_components = dict(damage_packet.damage_components)
        raw_damage = max(0, int(damage_packet.base_damage))
        if attack_roll.critical_success and damage_packet.can_critical:
            raw_damage_components = {
                k: int(max(0, int(v)) * 1.5) for k, v in raw_damage_components.items()
            }
            raw_damage = int(sum(raw_damage_components.values()))
            breakdown.append(
                {
                    "stage": "critical",
                    "before": int(damage_packet.base_damage),
                    "after": raw_damage,
                    "delta": raw_damage - int(damage_packet.base_damage),
                    "reason": "critical_hit_multiplier_1.5",
                }
            )
        else:
            breakdown.append(
                {
                    "stage": "critical",
                    "before": int(damage_packet.base_damage),
                    "after": raw_damage,
                    "delta": raw_damage - int(damage_packet.base_damage),
                    "reason": "no_critical",
                }
            )

        damage_packet.base_damage = raw_damage
        damage_packet.damage_components = raw_damage_components

        mitigation = self._apply_mitigation(
            defender,
            minimum_damage=max(0, int(minimum_damage)),
            damage_packet=damage_packet,
            mitigation_policy=mitigation_policy,
        )

        final_damage = max(0, int(mitigation.final_damage))
        target_hp_after = max(0, target_hp_before - final_damage)
        death = target_hp_after <= 0

        defender.stats.hp = target_hp_after
        self._sync_legacy_defense_fields(defender)

        breakdown.extend(
            {
                "stage": stage.stage,
                "before": stage.before,
                "after": stage.after,
                "delta": stage.delta,
                "reason": stage.reason,
            }
            for stage in mitigation.stages
        )
        breakdown.append(
            {
                "stage": "hp_apply",
                "before": target_hp_before,
                "after": target_hp_after,
                "delta": target_hp_after - target_hp_before,
                "reason": "apply_final_damage",
            }
        )

        events = []
        if attack_roll.critical_success and damage_packet.can_critical:
            events.append("致命一击！")
        events.append(f"造成 {final_damage} 点伤害")
        if mitigation.shield_absorbed > 0:
            events.append(f"护盾吸收 {mitigation.shield_absorbed} 点伤害")
        if mitigation.temporary_hp_absorbed > 0:
            events.append(f"临时生命吸收 {mitigation.temporary_hp_absorbed} 点伤害")
        if death:
            events.append("目标被击败")

        return CombatEvaluationResult(
            hit=True,
            critical=bool(attack_roll.critical_success and damage_packet.can_critical),
            miss_reason="",
            attack_roll=attack_info,
            damage_packet=damage_packet,
            mitigation=mitigation,
            final_damage=final_damage,
            target_hp_before=target_hp_before,
            target_hp_after=target_hp_after,
            death=death,
            events=events,
            breakdown=breakdown,
        )

    def _roll_base_damage(self, attacker: Union[Character, Monster], *, rng: Optional[random.Random] = None) -> int:
        abilities = getattr(attacker, "abilities", None)
        get_modifier = getattr(abilities, "get_modifier", None)
        if not callable(get_modifier):
            strength_mod = 0
        else:
            strength_mod = int(get_modifier("strength"))
        base = 10 + strength_mod
        low = max(1, base - 3)
        high = max(low, base + 3)
        roller = rng or self._rng
        return roller.randint(low, high)

    def _roll_attack_with_seed(
        self,
        attacker: Union[Character, Monster],
        defender: Union[Character, Monster],
        *,
        attack_type: str,
        attack_bonus: int,
        deterministic_seed: Optional[int],
    ) -> CheckResult:
        attack_rng = None
        if deterministic_seed is not None:
            attack_rng = random.Random(int(deterministic_seed) ^ 0x9E3779B1)

        return self.resolver.attack_roll(
            attacker,
            defender,
            attack_type=attack_type,
            proficient=True,
            extra_bonus=attack_bonus,
            rng=attack_rng,
        )

    def _apply_mitigation(
        self,
        defender: Union[Character, Monster],
        *,
        minimum_damage: int,
        damage_packet: Optional[DamagePacket] = None,
        damage: int = 0,
        damage_type: str = DamageType.PHYSICAL.value,
        mitigation_policy: Optional[Dict[str, Any]] = None,
    ) -> MitigationResult:
        stages: List[MitigationStage] = []

        if damage_packet is None:
            damage_packet = DamagePacket(
                source_id="",
                target_id="",
                damage_type=damage_type,
                base_damage=max(0, int(damage)),
                damage_components={str(damage_type): max(0, int(damage))},
            )

        components = dict(damage_packet.damage_components or {})
        if not components:
            components = {str(damage_packet.damage_type): max(0, int(damage_packet.base_damage))}

        total_incoming = max(0, int(sum(max(0, int(v)) for v in components.values())))
        remaining = total_incoming

        if total_incoming <= 0:
            return MitigationResult(stages=stages, final_damage=0)

        penetration = dict(damage_packet.penetration or {})
        policy = mitigation_policy if isinstance(mitigation_policy, dict) else {}

        runtime = self._get_defense_runtime(defender)
        shield_val = max(0, int(runtime.get("shield", 0) or 0))
        allow_shield_pen = bool(policy.get("allow_shield_penetration", True))
        shield_penetration = max(
            0.0,
            float(
                penetration.get("shield", penetration.get("shield_penetration", 0.0)) or 0.0
            ),
        ) if allow_shield_pen else 0.0
        if shield_penetration > 0.0 and shield_val > 0:
            reduced = min(shield_val, int(shield_val * min(1.0, shield_penetration)))
            shield_val = max(0, shield_val - reduced)
            runtime["shield"] = shield_val
            defender.stats.shield = shield_val
            stages.append(
                MitigationStage(
                    stage="shield_penetration",
                    before=shield_val + reduced,
                    after=shield_val,
                    delta=-reduced,
                    reason=f"shield_penetration:{shield_penetration}",
                )
            )

        shield_absorbed = min(shield_val, remaining)
        if shield_absorbed > 0:
            before = remaining
            remaining -= shield_absorbed
            runtime["shield"] = shield_val - shield_absorbed
            defender.stats.shield = runtime["shield"]
            stages.append(
                MitigationStage(
                    stage="shield",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason="shield_absorb",
                )
            )

        temp_hp_val = max(0, int(runtime.get("temporary_hp", 0) or 0))
        allow_temp_hp_pen = bool(policy.get("allow_temporary_hp_penetration", True))
        temp_hp_penetration = max(
            0.0,
            float(
                penetration.get("temporary_hp", penetration.get("temporary_hp_penetration", 0.0)) or 0.0
            ),
        ) if allow_temp_hp_pen else 0.0
        if temp_hp_penetration > 0.0 and temp_hp_val > 0:
            reduced = min(temp_hp_val, int(temp_hp_val * min(1.0, temp_hp_penetration)))
            temp_hp_val = max(0, temp_hp_val - reduced)
            runtime["temporary_hp"] = temp_hp_val
            defender.stats.temporary_hp = temp_hp_val
            stages.append(
                MitigationStage(
                    stage="temporary_hp_penetration",
                    before=temp_hp_val + reduced,
                    after=temp_hp_val,
                    delta=-reduced,
                    reason=f"temporary_hp_penetration:{temp_hp_penetration}",
                )
            )

        temporary_hp_absorbed = min(temp_hp_val, remaining)
        if temporary_hp_absorbed > 0:
            before = remaining
            remaining -= temporary_hp_absorbed
            runtime["temporary_hp"] = temp_hp_val - temporary_hp_absorbed
            defender.stats.temporary_hp = runtime["temporary_hp"]
            stages.append(
                MitigationStage(
                    stage="temporary_hp",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason="temporary_hp_absorb",
                )
            )

        if remaining <= 0:
            return MitigationResult(
                stages=stages,
                final_damage=0,
                shield_absorbed=shield_absorbed,
                temporary_hp_absorbed=temporary_hp_absorbed,
                resistance_multiplier=1.0,
                vulnerability_multiplier=1.0,
                damage_by_type={},
            )

        if total_incoming > 0 and remaining != total_incoming:
            ratio = remaining / float(total_incoming)
            scaled: Dict[str, int] = {}
            for key, value in components.items():
                scaled[key] = max(0, int(int(value) * ratio))
            components = scaled

        resistances = getattr(defender, "resistances", {}) or {}
        vulnerabilities = getattr(defender, "vulnerabilities", {}) or {}
        immunities = {str(v) for v in (getattr(defender, "immunities", []) or [])}

        final_by_type: Dict[str, int] = {}
        accum_before = 0
        accum_after = 0

        for comp_type, comp_damage in components.items():
            comp_before = max(0, int(comp_damage))
            accum_before += comp_before
            alias_type = self._map_damage_type_alias(comp_type)

            if alias_type in immunities and not damage_packet.true_damage:
                stages.append(
                    MitigationStage(
                        stage="immunity",
                        before=comp_before,
                        after=0,
                        delta=-comp_before,
                        reason=f"immunity:{alias_type}",
                    )
                )
                final_by_type[comp_type] = 0
                continue

            value = comp_before

            if not damage_packet.true_damage:
                resistance_multiplier = 1.0
                resistance_value = resistances.get(comp_type)
                if resistance_value is None:
                    resistance_value = resistances.get(alias_type)
                if resistance_value is not None:
                    try:
                        resistance_penetration = float(
                            damage_packet.penetration.get(
                                comp_type,
                                damage_packet.penetration.get(
                                    alias_type,
                                    damage_packet.penetration.get("resistance", 0.0),
                                ),
                            )
                            or 0.0
                        )
                        applied_res = max(0.0, float(resistance_value) - max(0.0, resistance_penetration))
                        res_min = float(policy.get("resistance_clamp_min", 0.0) or 0.0)
                        res_max = float(policy.get("resistance_clamp_max", 0.95) or 0.95)
                        if res_max < res_min:
                            res_min, res_max = res_max, res_min
                        applied_res = max(res_min, min(res_max, applied_res))
                        resistance_multiplier = max(0.0, min(1.0, 1.0 - applied_res))
                    except (TypeError, ValueError):
                        resistance_multiplier = 1.0
                    before = value
                    value = int(value * resistance_multiplier)
                    stages.append(
                        MitigationStage(
                            stage="resistance",
                            before=before,
                            after=value,
                            delta=value - before,
                            reason=f"resistance:{comp_type}:{resistance_multiplier}",
                        )
                    )

                vulnerability_multiplier = 1.0
                vulnerability_value = vulnerabilities.get(comp_type)
                if vulnerability_value is None:
                    vulnerability_value = vulnerabilities.get(alias_type)
                if vulnerability_value is not None:
                    try:
                        vul_min = float(policy.get("vulnerability_min_multiplier", 1.0) or 1.0)
                        vul_max = float(policy.get("vulnerability_max_multiplier", 3.0) or 3.0)
                        if vul_max < vul_min:
                            vul_min, vul_max = vul_max, vul_min
                        vulnerability_multiplier = max(vul_min, min(vul_max, 1.0 + float(vulnerability_value)))
                    except (TypeError, ValueError):
                        vulnerability_multiplier = 1.0
                    before = value
                    value = int(value * vulnerability_multiplier)
                    stages.append(
                        MitigationStage(
                            stage="vulnerability",
                            before=before,
                            after=value,
                            delta=value - before,
                            reason=f"vulnerability:{comp_type}:{vulnerability_multiplier}",
                        )
                    )

            final_by_type[comp_type] = max(0, int(value))
            accum_after += final_by_type[comp_type]

        final_total = max(0, int(sum(final_by_type.values())))
        if total_incoming > 0 and final_total < max(0, int(minimum_damage)):
            before = final_total
            final_total = max(0, int(minimum_damage))
            stages.append(
                MitigationStage(
                    stage="minimum_damage",
                    before=before,
                    after=final_total,
                    delta=final_total - before,
                    reason=f"minimum_damage:{minimum_damage}",
                )
            )

        return MitigationResult(
            stages=stages,
            final_damage=final_total,
            shield_absorbed=shield_absorbed,
            temporary_hp_absorbed=temporary_hp_absorbed,
            resistance_multiplier=1.0 if accum_before <= 0 else max(0.0, min(2.0, accum_after / float(max(1, accum_before)))),
            vulnerability_multiplier=1.0,
            damage_by_type=final_by_type,
        )

    @staticmethod
    def _serialize_attack_roll(attack_roll: CheckResult) -> Dict[str, Any]:
        return {
            "check_type": attack_roll.check_type,
            "entity_name": attack_roll.entity_name,
            "ability": attack_roll.ability,
            "target_ac": attack_roll.target_ac,
            "roll": attack_roll.roll,
            "ability_modifier": attack_roll.ability_modifier,
            "proficiency_bonus": attack_roll.proficiency_bonus,
            "extra_bonus": attack_roll.extra_bonus,
            "total": attack_roll.total,
            "success": attack_roll.success,
            "critical_success": attack_roll.critical_success,
            "critical_failure": attack_roll.critical_failure,
            "advantage": attack_roll.advantage,
            "disadvantage": attack_roll.disadvantage,
            "breakdown": attack_roll.breakdown,
            "ui_text": attack_roll.ui_text,
        }

    @staticmethod
    def _map_damage_type_alias(damage_type: str) -> str:
        value = str(damage_type or DamageType.PHYSICAL.value)
        if value in {
            DamageType.PHYSICAL_SLASH.value,
            DamageType.PHYSICAL_PIERCE.value,
            DamageType.PHYSICAL_BLUNT.value,
        }:
            return DamageType.PHYSICAL.value
        return value

    @staticmethod
    def _normalize_damage_components(
        *,
        damage_type: str,
        base_damage: int,
        damage_components: Optional[Dict[str, int]],
    ) -> Dict[str, int]:
        if isinstance(damage_components, dict) and damage_components:
            normalized: Dict[str, int] = {}
            for key, value in damage_components.items():
                safe_key = str(key or DamageType.PHYSICAL.value)
                try:
                    normalized[safe_key] = max(0, int(value))
                except (TypeError, ValueError):
                    normalized[safe_key] = 0
            if normalized:
                return normalized
        return {str(damage_type or DamageType.PHYSICAL.value): max(0, int(base_damage))}

    @staticmethod
    def _ensure_effective_ac(entity: Union[Character, Monster]):
        stats = getattr(entity, "stats", None)
        if not stats:
            return
        get_effective = getattr(stats, "get_effective_ac", None)
        if callable(get_effective):
            try:
                stats.ac = int(get_effective())
            except Exception:
                pass


combat_core_evaluator = CombatCoreEvaluator()

__all__ = [
    "CombatSnapshot",
    "DamagePacket",
    "MitigationStage",
    "MitigationResult",
    "CombatEvaluationResult",
    "CombatCoreEvaluator",
    "combat_core_evaluator",
]
