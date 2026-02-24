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
    ) -> CombatEvaluationResult:
        local_rng = self._rng
        if deterministic_seed is not None:
            local_rng = random.Random(int(deterministic_seed))

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
        damage_packet = DamagePacket(
            source_id=str(getattr(attacker, "id", "")),
            target_id=str(getattr(defender, "id", "")),
            damage_type=str(damage_type or DamageType.PHYSICAL.value),
            base_damage=max(0, base + int(damage_bonus)),
            can_critical=bool(can_critical),
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

        raw_damage = max(0, int(damage_packet.base_damage))
        if attack_roll.critical_success and damage_packet.can_critical:
            raw_damage = int(raw_damage * 1.5)
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

        mitigation = self._apply_mitigation(
            defender,
            damage=raw_damage,
            damage_type=damage_packet.damage_type,
            minimum_damage=max(0, int(minimum_damage)),
        )

        final_damage = max(0, int(mitigation.final_damage))
        target_hp_after = max(0, target_hp_before - final_damage)
        death = target_hp_after <= 0

        defender.stats.hp = target_hp_after
        if hasattr(defender.stats, "shield"):
            defender.stats.shield = int(getattr(defender.stats, "shield", 0) or 0)
        if hasattr(defender.stats, "temporary_hp"):
            defender.stats.temporary_hp = int(getattr(defender.stats, "temporary_hp", 0) or 0)

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
        if deterministic_seed is None:
            return self.resolver.attack_roll(
                attacker,
                defender,
                attack_type=attack_type,
                proficient=True,
                extra_bonus=attack_bonus,
            )

        global_state = random.getstate()
        random.seed(int(deterministic_seed) ^ 0x9E3779B1)
        try:
            return self.resolver.attack_roll(
                attacker,
                defender,
                attack_type=attack_type,
                proficient=True,
                extra_bonus=attack_bonus,
            )
        finally:
            random.setstate(global_state)

    def _apply_mitigation(
        self,
        defender: Union[Character, Monster],
        *,
        damage: int,
        damage_type: str,
        minimum_damage: int,
    ) -> MitigationResult:
        stages: List[MitigationStage] = []
        remaining = max(0, int(damage))

        resistances = getattr(defender, "resistances", {}) or {}
        vulnerabilities = getattr(defender, "vulnerabilities", {}) or {}
        immunities = getattr(defender, "immunities", []) or []

        if str(damage_type) in [str(v) for v in immunities]:
            stages.append(
                MitigationStage(
                    stage="immunity_short_circuit",
                    before=remaining,
                    after=0,
                    delta=-remaining,
                    reason=f"immunity:{damage_type}",
                )
            )
            return MitigationResult(
                stages=stages,
                final_damage=0,
                shield_absorbed=0,
                temporary_hp_absorbed=0,
                resistance_multiplier=0.0,
                vulnerability_multiplier=1.0,
            )

        shield_val = max(0, int(getattr(defender.stats, "shield", 0) or 0))
        shield_absorbed = min(shield_val, remaining)
        if shield_absorbed > 0:
            before = remaining
            remaining -= shield_absorbed
            defender.stats.shield = shield_val - shield_absorbed
            stages.append(
                MitigationStage(
                    stage="shield",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason="shield_absorb",
                )
            )

        temp_hp_val = max(0, int(getattr(defender.stats, "temporary_hp", 0) or 0))
        temporary_hp_absorbed = min(temp_hp_val, remaining)
        if temporary_hp_absorbed > 0:
            before = remaining
            remaining -= temporary_hp_absorbed
            defender.stats.temporary_hp = temp_hp_val - temporary_hp_absorbed
            stages.append(
                MitigationStage(
                    stage="temporary_hp",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason="temporary_hp_absorb",
                )
            )

        resistance_multiplier = 1.0
        resistance_value = resistances.get(str(damage_type))
        if resistance_value is not None:
            try:
                resistance_multiplier = max(0.0, min(1.0, 1.0 - float(resistance_value)))
            except (TypeError, ValueError):
                resistance_multiplier = 1.0

        vulnerability_multiplier = 1.0
        vulnerability_value = vulnerabilities.get(str(damage_type))
        if vulnerability_value is not None:
            try:
                vulnerability_multiplier = max(1.0, 1.0 + float(vulnerability_value))
            except (TypeError, ValueError):
                vulnerability_multiplier = 1.0

        if resistance_multiplier != 1.0:
            before = remaining
            remaining = int(remaining * resistance_multiplier)
            stages.append(
                MitigationStage(
                    stage="resistance",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason=f"resistance:{damage_type}:{resistance_multiplier}",
                )
            )

        if vulnerability_multiplier != 1.0:
            before = remaining
            remaining = int(remaining * vulnerability_multiplier)
            stages.append(
                MitigationStage(
                    stage="vulnerability",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason=f"vulnerability:{damage_type}:{vulnerability_multiplier}",
                )
            )

        if damage > 0 and remaining < minimum_damage:
            before = remaining
            remaining = minimum_damage
            stages.append(
                MitigationStage(
                    stage="minimum_damage",
                    before=before,
                    after=remaining,
                    delta=remaining - before,
                    reason=f"minimum_damage:{minimum_damage}",
                )
            )

        return MitigationResult(
            stages=stages,
            final_damage=max(0, int(remaining)),
            shield_absorbed=shield_absorbed,
            temporary_hp_absorbed=temporary_hp_absorbed,
            resistance_multiplier=resistance_multiplier,
            vulnerability_multiplier=vulnerability_multiplier,
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
