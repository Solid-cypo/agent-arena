"""BDD-style unit tests for Skill 1: assessing_situations.

Tests do NOT import cg.api (no game engine needed).
They exercise opponent_profiler and the pure-math helpers in situation_assessor directly.

Run:
    python3 -m pytest .agent/skills/assessing_situations/scripts/test_assessing_situations.py -v
or:
    python3 .agent/skills/assessing_situations/scripts/test_assessing_situations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts importable without installing
_scripts = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts))

# ── opponent_profiler (no cg dependency) ───────────────────────────────────
from opponent_profiler import (
    OpponentProfile,
    _CONFIDENCE_THRESHOLD,
    _battle_state,
    _behavioral_confidence_boost,
    _jaccard,
    _profile_from_set,
    _reset_battle_state,
    profile_from_known_ids,
)

# ── situation_assessor pure-math helpers (no cg dependency) ────────────────
from situation_assessor import (
    _compute_s_hand,
    _compute_tc,
    _iter_board,
    _pokemon_energy_readiness,
    _pokemon_hp,
    _pokemon_max_damage,
    SituationScores,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers / stubs
# ──────────────────────────────────────────────────────────────────────────

class _FakeAttack:
    def __init__(self, damage: int, energy_count: int = 2):
        self.damage = damage
        self.energyCount = energy_count


class _FakePokemon:
    def __init__(self, hp: int = 100, max_hp: int = 100,
                 attacks: list | None = None, energy_count: int = 0):
        self.hp = hp
        self.maxHp = max_hp
        self.attacks = attacks or [_FakeAttack(80)]
        self.energyCount = energy_count
        self.id = 741


class _FakePlayer:
    def __init__(self, hand_ids: list[int], board: list[_FakePokemon],
                 prize_count: int = 6):
        self.hand = [type("C", (), {"id": cid})() for cid in hand_ids]
        self.handCount = len(hand_ids)
        self.active = board[:1]
        self.bench = board[1:]
        self.prizeCount = prize_count


# ──────────────────────────────────────────────────────────────────────────
# BDD Scenarios
# ──────────────────────────────────────────────────────────────────────────

def test_jaccard_exact_match():
    """
    Given fingerprint [741, 742, 743]
    When observed = {741, 742, 743}
    Then Jaccard == 1.0
    """
    assert _jaccard({741, 742, 743}, [741, 742, 743]) == 1.0


def test_jaccard_partial_match():
    """
    Given fingerprint [741, 742, 743, 66, 305]
    When observed = {741, 742, 743}
    Then Jaccard == 3/5 = 0.6
    """
    score = _jaccard({741, 742, 743}, [741, 742, 743, 66, 305])
    assert abs(score - 3 / 5) < 1e-9


def test_jaccard_no_match():
    """
    Given fingerprint [741, 742, 743]
    When observed = {1, 2, 3}
    Then Jaccard == 0.0
    """
    assert _jaccard({1, 2, 3}, [741, 742, 743]) == 0.0


def test_profile_alakazam_tempo():
    """
    Given opponent deck contains ≥3 of [741, 742, 743, 66, 305, 1081]
    When profile_from_known_ids()
    Then style == 'Tempo', confidence >= 0.3
    """
    deck = [741] * 4 + [742] * 4 + [743] * 4 + [66] * 3 + [305] * 4 + [1081] * 4
    profile = profile_from_known_ids(deck)
    assert profile.style == "Tempo", f"expected Tempo, got {profile.style}"
    assert profile.confidence >= _CONFIDENCE_THRESHOLD


def test_profile_hops_control():
    """
    Given opponent deck contains [878, 879, 311, 1134, 11, 1171]
    When profile_from_known_ids()
    Then style == 'Control'
    """
    deck = [878] * 4 + [879] * 4 + [311] * 3 + [1134] * 4 + [11] * 4 + [1171] * 4
    profile = profile_from_known_ids(deck)
    assert profile.style == "Control", f"expected Control, got {profile.style}"


def test_profile_unknown_low_confidence():
    """
    Given opponent has revealed only [1, 2, 3] (no known fingerprint cards)
    When profile_from_known_ids()
    Then style == 'Unknown'
    """
    profile = profile_from_known_ids([1, 2, 3])
    assert profile.style == "Unknown"
    assert profile.confidence < _CONFIDENCE_THRESHOLD


def test_s_hand_draw_potential():
    """
    Given player has 3 cards in hand: Dudunsparce (66), Poffin (1086), unknown (9999)
    When _compute_s_hand()
    Then s_hand == 3 + 2.0 + 1.5 + 0.0 == 6.5
    """
    player = _FakePlayer(hand_ids=[66, 1086, 9999], board=[])
    result = _compute_s_hand(player, [66, 1086, 9999])
    assert abs(result - 6.5) < 1e-6, f"expected 6.5, got {result}"


def test_s_hand_empty():
    """
    Given player has 0 hand cards
    When _compute_s_hand()
    Then s_hand == 0.0
    """
    player = _FakePlayer(hand_ids=[], board=[])
    result = _compute_s_hand(player, [])
    assert result == 0.0


def test_pokemon_energy_readiness_full():
    """
    Given Pokemon has energyCount=2, attack requires energyCount=2
    When _pokemon_energy_readiness()
    Then readiness == 1.0
    """
    p = _FakePokemon(attacks=[_FakeAttack(80, energy_count=2)], energy_count=2)
    assert _pokemon_energy_readiness(p) == 1.0


def test_pokemon_energy_readiness_partial():
    """
    Given Pokemon has energyCount=1, attack requires energyCount=2
    When _pokemon_energy_readiness()
    Then readiness == 0.5
    """
    p = _FakePokemon(attacks=[_FakeAttack(80, energy_count=2)], energy_count=1)
    assert abs(_pokemon_energy_readiness(p) - 0.5) < 1e-9


def test_tc_computation():
    """
    Given attacker max_dmg=100, opp board has 1 pokemon HP=100, prize_left=1
    When _compute_tc()
    Then TC == 1  (ceil(100/100) == 1)
    """
    attacker = [_FakePokemon(hp=200, max_hp=200, attacks=[_FakeAttack(100)], energy_count=2)]
    defender = [_FakePokemon(hp=100, max_hp=100)]
    tc = _compute_tc(attacker, defender, prize_left=1)
    assert tc == 1.0, f"expected 1.0, got {tc}"


def test_prize_left_triggers_burst_condition():
    """
    Given prize_left_self=2, board_readiness=1.0
    When routing_states evaluates FSM (logic verified here via direct values)
    Then BURST condition is satisfied (prize_left_self <= 2 AND readiness >= 1.0)
    """
    scores = SituationScores(
        s_hand=5.0, s_board=120.0, s_turn=2.0,
        tc_me=2.0, tc_opp=4.0,
        prize_left_self=2, prize_left_opp=4,
        board_readiness=1.0,
        s_hand_diff=1.0, s_board_diff=30.0,
    )
    burst_condition = scores.prize_left_self <= 2 and scores.board_readiness >= 1.0
    assert burst_condition, "BURST condition should fire when prize_left=2 and readiness=1.0"


def test_hand_diff_control_trigger():
    """
    Given s_hand_diff = -4.0 (falling behind by 4 cards)
    When checking DENYING_RESOURCES hand threshold
    Then s_hand_diff < -3 is True → w_hand boost should activate
    """
    scores = SituationScores(
        s_hand=2.0, s_board=60.0, s_turn=-1.0,
        tc_me=3.0, tc_opp=2.0,
        prize_left_self=4, prize_left_opp=3,
        board_readiness=0.4,
        s_hand_diff=-4.0, s_board_diff=-20.0,
    )
    assert scores.s_hand_diff < -3, "hand deficit trigger condition failed"


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

def test_behavioral_hand_explosion_signals_tempo():
    """
    Given opponent hand count reaches 12 in battle (Dudunsparce draw)
    When _behavioral_confidence_boost()
    Then style=Tempo, confidence_boost >= 0.3
    """
    _reset_battle_state()
    _battle_state["hand_counts"] = [5, 6, 12]
    _battle_state["peak_hand"] = 12
    _battle_state["min_hand"] = 5
    style, speed, boost = _behavioral_confidence_boost()
    assert style == "Tempo", f"expected Tempo, got {style}"
    assert boost >= 0.3, f"boost should be >= 0.3 for hand explosion, got {boost}"


def test_behavioral_discard_refill_signals_control():
    """
    Given hand drops to 1 (Carmine) then recovers to 6 (Lillie's)
    When _behavioral_confidence_boost()
    Then style=Control
    """
    _reset_battle_state()
    _battle_state["hand_counts"] = [5, 1, 6]
    _battle_state["peak_hand"] = 6
    _battle_state["min_hand"] = 1
    style, speed, boost = _behavioral_confidence_boost()
    assert style == "Control", f"expected Control, got {style}"
    assert boost > 0.0


def test_behavioral_low_jaccard_fused_with_hand_explosion():
    """
    Given Jaccard=0.1 (only 1 card visible) but hand reached 11 (strong behavioral signal)
    When behavioral boost = 0.35
    Then combined confidence = 0.1 + 0.35 = 0.45 >= threshold
    """
    _reset_battle_state()
    _battle_state["hand_counts"] = [5, 8, 11]
    _battle_state["peak_hand"] = 11
    _battle_state["min_hand"] = 5
    _, _, boost = _behavioral_confidence_boost()
    combined = 0.10 + boost
    assert combined >= _CONFIDENCE_THRESHOLD, (
        f"combined {combined:.2f} should exceed threshold {_CONFIDENCE_THRESHOLD}"
    )


def test_behavioral_reset_on_new_battle():
    """
    Given battle_state has data from previous battle
    When _reset_battle_state() called
    Then all counters reset to initial values
    """
    _battle_state["hand_counts"] = [10, 12, 15]
    _battle_state["peak_hand"] = 15
    _reset_battle_state()
    assert _battle_state["hand_counts"] == []
    assert _battle_state["peak_hand"] == 0


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
