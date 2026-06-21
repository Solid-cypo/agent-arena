"""BDD-style unit tests for Skill 3: evaluating_actions.

Tests cover ko_math, survival_math, and the pure-Python logic paths
in action_evaluator that don't require cg.api.

Run:
    python3 .agent/skills/evaluating_actions/scripts/test_evaluating_actions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

from ko_math import (
    best_attacker_index,
    calculate_ko_efficiency,
    energy_routing_bonus,
)
from survival_math import (
    _IONO_LAMBDA_DEFAULT,
    _SURVIVAL_BONUS_VALUE,
    evaluate_survival_bonus,
    get_hammer_bonus,
    get_iono_priority_weight,
    prizes_given_for_card,
)


# ──────────────────────────────────────────────────────────────────────────
# ko_math tests
# ──────────────────────────────────────────────────────────────────────────

def test_ko_efficiency_ready_attacker():
    """
    Given max_damage=120, opp_hp=100, required=2, attached=2 (ready)
    When calculate_ko_efficiency()
    Then efficiency == 120/100 × 1/(1+0) == 1.2
    """
    eff = calculate_ko_efficiency(
        max_damage=120, opp_active_hp=100,
        required_energy=2, attached_energy=2,
    )
    assert abs(eff - 1.2) < 1e-9, f"expected 1.2, got {eff}"


def test_ko_efficiency_missing_energy():
    """
    Given max_damage=120, opp_hp=100, required=2, attached=0 (missing 2)
    When calculate_ko_efficiency()
    Then efficiency == 1.2 / (1+2) == 0.4
    """
    eff = calculate_ko_efficiency(
        max_damage=120, opp_active_hp=100,
        required_energy=2, attached_energy=0,
    )
    assert abs(eff - 0.4) < 1e-9, f"expected 0.4, got {eff}"


def test_ko_efficiency_weakness_multiplier():
    """
    Given type_multiplier=2.0 (weakness), all else standard
    When calculate_ko_efficiency()
    Then efficiency doubles vs no-multiplier case
    """
    eff_base = calculate_ko_efficiency(80, 100, 2, 2, type_multiplier=1.0)
    eff_weak = calculate_ko_efficiency(80, 100, 2, 2, type_multiplier=2.0)
    assert abs(eff_weak - 2 * eff_base) < 1e-9


def test_ko_efficiency_zero_hp():
    """
    Given opp_active_hp=0
    When calculate_ko_efficiency()
    Then return 0.0 (guard against divide-by-zero)
    """
    assert calculate_ko_efficiency(100, 0, 2, 2) == 0.0


def test_best_attacker_prefers_ready_over_powerful():
    """
    Given attacker A: dmg=200, need=4, has=0  (needs 4 more energy)
         attacker B: dmg=100, need=2, has=2  (ready now)
    When best_attacker_index() vs opp_hp=100
    Then B wins (higher efficiency due to readiness)
    """
    attackers = [
        {"max_damage": 200, "required_energy": 4, "attached_energy": 0},  # idx 0
        {"max_damage": 100, "required_energy": 2, "attached_energy": 2},  # idx 1
    ]
    best = best_attacker_index(attackers, opp_active_hp=100)
    assert best == 1, f"expected idx 1 (ready attacker), got {best}"


def test_energy_routing_bonus_matches():
    """
    Given best attacker is at board index 1, attach option targets index 1
    When energy_routing_bonus(1, 1)
    Then bonus == default value (small nudge within policy.py range)
    """
    bonus = energy_routing_bonus(1, 1)
    assert bonus > 0.0, "matching bonus should be positive"
    assert bonus < 5.0, "matching bonus should stay within policy.py score range"


def test_energy_routing_bonus_mismatch():
    """
    Given best attacker is at board index 1, attach option targets index 0
    When energy_routing_bonus(1, 0)
    Then bonus == 0.0
    """
    assert energy_routing_bonus(1, 0) == 0.0


# ──────────────────────────────────────────────────────────────────────────
# survival_math tests
# ──────────────────────────────────────────────────────────────────────────

def test_survival_bonus_fires_for_ex_about_to_be_koed():
    """
    Given active ex Pokemon (prizes_given=2), hp=50, opp_dmg=80 (would KO)
    And option is RETREAT
    When evaluate_survival_bonus()
    Then returns _SURVIVAL_BONUS_VALUE (large positive)
    """
    bonus = evaluate_survival_bonus(
        active_hp=50, active_max_hp=200,
        active_prizes_given=2,
        opp_max_damage=80,
        is_retreat_option=True,
    )
    assert bonus == _SURVIVAL_BONUS_VALUE, f"expected {_SURVIVAL_BONUS_VALUE}, got {bonus}"


def test_survival_bonus_no_fire_for_normal_pokemon():
    """
    Given single-prize Pokemon (prizes_given=1)
    When evaluate_survival_bonus()
    Then returns 0.0 (no special incentive)
    """
    bonus = evaluate_survival_bonus(
        active_hp=50, active_max_hp=120,
        active_prizes_given=1,
        opp_max_damage=80,
        is_retreat_option=True,
    )
    assert bonus == 0.0


def test_survival_bonus_no_fire_when_not_retreat():
    """
    Given ex Pokemon about to be KO'd but option is NOT RETREAT
    When evaluate_survival_bonus()
    Then returns 0.0
    """
    bonus = evaluate_survival_bonus(
        active_hp=30, active_max_hp=200,
        active_prizes_given=2,
        opp_max_damage=100,
        is_retreat_option=False,
    )
    assert bonus == 0.0


def test_survival_bonus_no_fire_when_safe():
    """
    Given ex Pokemon but opp_damage < active_hp (safe this turn)
    When evaluate_survival_bonus()
    Then returns 0.0
    """
    bonus = evaluate_survival_bonus(
        active_hp=200, active_max_hp=200,
        active_prizes_given=2,
        opp_max_damage=80,
        is_retreat_option=True,
    )
    assert bonus == 0.0


def test_prizes_given_normal():
    assert prizes_given_for_card(is_ex=False, is_mega_ex=False) == 1


def test_prizes_given_ex():
    assert prizes_given_for_card(is_ex=True, is_mega_ex=False) == 2


def test_prizes_given_mega_ex():
    assert prizes_given_for_card(is_ex=True, is_mega_ex=True) == 3


def test_iono_weight_equal_prizes():
    """
    Given my_prize_taken == opp_prize_taken (even)
    When get_iono_priority_weight()
    Then multiplier == 1.0 (no bonus)
    """
    mult = get_iono_priority_weight(my_prize_taken=2, opp_prize_taken=2)
    assert abs(mult - 1.0) < 1e-9


def test_iono_weight_trailing():
    """
    Given trailing by 3 prizes (opp took 3, me took 0)
    When get_iono_priority_weight(lambda=2.5)
    Then mult == 1 + 2.5 × 3/6 == 2.25
    """
    mult = get_iono_priority_weight(
        my_prize_taken=0, opp_prize_taken=3, lmbda=2.5,
    )
    assert abs(mult - 2.25) < 1e-9, f"expected 2.25, got {mult}"


def test_iono_weight_leading_no_boost():
    """
    Given leading (my > opp prize taken)
    When get_iono_priority_weight()
    Then mult == 1.0 (no negative boost)
    """
    mult = get_iono_priority_weight(my_prize_taken=4, opp_prize_taken=1)
    assert abs(mult - 1.0) < 1e-9


def test_hammer_bonus_vs_control():
    """
    Given played_card_id=1081 (Enhanced Hammer), opp_style=Control
    When get_hammer_bonus()
    Then returns HAMMER_VS_CONTROL_BONUS (50.0)
    """
    bonus = get_hammer_bonus(played_card_id=1081, opp_style="Control")
    assert bonus == 50.0


def test_hammer_bonus_vs_tempo():
    """
    Given played_card_id=1081 but opp_style=Tempo
    When get_hammer_bonus()
    Then returns 0.0 (no bonus; hammer not useful vs Tempo)
    """
    bonus = get_hammer_bonus(played_card_id=1081, opp_style="Tempo")
    assert bonus == 0.0


def test_hammer_bonus_wrong_card():
    """
    Given played_card_id != 1081
    When get_hammer_bonus()
    Then returns 0.0 regardless of style
    """
    assert get_hammer_bonus(played_card_id=1182, opp_style="Control") == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
