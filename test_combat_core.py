import unittest

from combat_core import CombatCoreEvaluator
from data_manager import DataManager
from data_models import Character, Monster
from roll_resolver import CheckResult


class _FakeResolver:
    def __init__(self, hit=True, critical=False, total=15, target_ac=10, roll=12):
        self._hit = hit
        self._critical = critical
        self._total = total
        self._target_ac = target_ac
        self._roll = roll

    def attack_roll(self, attacker, target, attack_type="melee", proficient=True, extra_bonus=0):
        return CheckResult(
            check_type="attack_roll",
            entity_name=getattr(attacker, "name", "attacker"),
            ability="strength",
            dc=None,
            target_ac=self._target_ac,
            roll=self._roll,
            ability_modifier=0,
            proficiency_bonus=0,
            expertise_bonus=0,
            extra_bonus=extra_bonus,
            total=self._total,
            success=self._hit,
            critical_success=self._critical,
            critical_failure=False,
            advantage=False,
            disadvantage=False,
            breakdown="test_roll",
            ui_text="test_ui",
        )


class CombatCoreTests(unittest.TestCase):
    def _make_entities(self):
        attacker = Character()
        attacker.name = "hero"
        attacker.abilities.strength = 14

        defender = Monster()
        defender.name = "slime"
        defender.stats.hp = 50
        defender.stats.max_hp = 50
        defender.stats.ac = 10
        return attacker, defender

    def test_hit_applies_damage_and_breakdown(self):
        attacker, defender = self._make_entities()
        resolver = _FakeResolver(hit=True, critical=False, total=14, target_ac=10, roll=14)
        evaluator = CombatCoreEvaluator(resolver=resolver, rng_seed=123)

        result = evaluator.evaluate_attack(attacker, defender, base_damage=12)

        self.assertTrue(result.hit)
        self.assertEqual(result.final_damage, 12)
        self.assertEqual(defender.stats.hp, 38)
        self.assertTrue(any(stage.get("stage") == "hp_apply" for stage in result.breakdown))

    def test_miss_has_zero_damage(self):
        attacker, defender = self._make_entities()
        resolver = _FakeResolver(hit=False, critical=False, total=6, target_ac=12, roll=6)
        evaluator = CombatCoreEvaluator(resolver=resolver, rng_seed=123)

        result = evaluator.evaluate_attack(attacker, defender, base_damage=12)

        self.assertFalse(result.hit)
        self.assertEqual(result.final_damage, 0)
        self.assertEqual(defender.stats.hp, 50)

    def test_shield_absorption(self):
        attacker, defender = self._make_entities()
        setattr(defender.stats, "shield", 8)

        resolver = _FakeResolver(hit=True, critical=False, total=16, target_ac=10, roll=16)
        evaluator = CombatCoreEvaluator(resolver=resolver, rng_seed=123)

        result = evaluator.evaluate_attack(attacker, defender, base_damage=12)

        self.assertEqual(result.final_damage, 4)
        self.assertEqual(getattr(defender.stats, "shield", 0), 0)
        self.assertEqual(defender.stats.hp, 46)

    def test_immunity_does_not_consume_shield_or_temp_hp(self):
        attacker, defender = self._make_entities()
        setattr(defender.stats, "shield", 10)
        setattr(defender.stats, "temporary_hp", 6)
        setattr(defender, "immunities", ["physical"])

        resolver = _FakeResolver(hit=True, critical=False, total=18, target_ac=10, roll=18)
        evaluator = CombatCoreEvaluator(resolver=resolver, rng_seed=123)

        result = evaluator.evaluate_attack(attacker, defender, base_damage=20)

        self.assertEqual(result.final_damage, 0)
        self.assertEqual(defender.stats.hp, 50)
        self.assertEqual(getattr(defender.stats, "shield", 0), 10)
        self.assertEqual(getattr(defender.stats, "temporary_hp", 0), 6)

    def test_minimum_damage_applies_after_resistance_rounding(self):
        attacker, defender = self._make_entities()
        setattr(defender, "resistances", {"physical": 0.9})

        resolver = _FakeResolver(hit=True, critical=False, total=18, target_ac=10, roll=18)
        evaluator = CombatCoreEvaluator(resolver=resolver, rng_seed=123)

        result = evaluator.evaluate_attack(attacker, defender, base_damage=1, minimum_damage=1)

        self.assertEqual(result.final_damage, 1)
        self.assertEqual(defender.stats.hp, 49)

    def test_deterministic_seed_produces_stable_projection(self):
        attacker, defender1 = self._make_entities()
        _, defender2 = self._make_entities()

        evaluator = CombatCoreEvaluator(rng_seed=999)
        result1 = evaluator.evaluate_attack(attacker, defender1, deterministic_seed=20260224)
        result2 = evaluator.evaluate_attack(attacker, defender2, deterministic_seed=20260224)

        self.assertEqual(result1.to_projection(), result2.to_projection())
        self.assertEqual(result1.breakdown[0]["reason"], result2.breakdown[0]["reason"])

    def test_data_manager_restores_combat_traits(self):
        manager = DataManager()
        character_data = {
            "id": "char-1",
            "name": "hero",
            "description": "",
            "character_class": "fighter",
            "creature_type": "humanoid",
            "abilities": {
                "strength": 10,
                "dexterity": 10,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 10,
                "charisma": 10,
            },
            "stats": {
                "hp": 100,
                "max_hp": 100,
                "mp": 50,
                "max_mp": 50,
                "ac": 10,
                "speed": 30,
                "level": 1,
                "experience": 0,
                "shield": 12,
                "temporary_hp": 3,
            },
            "resistances": {"physical": 0.5},
            "vulnerabilities": {"fire": 0.25},
            "immunities": ["poison"],
            "inventory": [],
            "equipped_items": {},
            "active_effects": [],
            "spells": [],
            "position": [0, 0],
        }

        character = manager._dict_to_character(character_data)
        self.assertEqual(character.stats.shield, 12)
        self.assertEqual(character.stats.temporary_hp, 3)
        self.assertEqual(character.resistances.get("physical"), 0.5)
        self.assertEqual(character.vulnerabilities.get("fire"), 0.25)
        self.assertIn("poison", character.immunities)


if __name__ == "__main__":
    unittest.main()
