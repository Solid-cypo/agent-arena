"""BDD-style unit tests for Skill 2: routing_states.

No cg.api dependency — uses dataclass stubs only.

Run:
    python3 .agent/skills/routing_states/scripts/test_routing_states.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

# Skill 1 dataclasses (no cg)
_s1 = Path(__file__).resolve().parents[2] / "assessing_situations" / "scripts"
sys.path.insert(0, str(_s1))

from situation_assessor import SituationScores
from opponent_profiler import OpponentProfile
from state_router import (
    PolicyWeights,
    RouteResult,
    StateEnum,
    _HAND_DEFICIT_THRESHOLD,
    route,
)


# ──────────────────────────────────────────────────────────────────────────
# Score factories
# ──────────────────────────────────────────────────────────────────────────

def _scores(
    prize_self: int = 4, prize_opp: int = 4,
    readiness: float = 0.5,
    s_turn: float = 0.0,
    s_hand_diff: float = 0.0,
    s_board_diff: float = 0.0,
) -> SituationScores:
    return SituationScores(
        s_hand=5.0 + s_hand_diff,
        s_board=80.0,
        s_turn=s_turn,
        tc_me=4.0,
        tc_opp=4.0 + s_turn,
        prize_left_self=prize_self,
        prize_left_opp=prize_opp,
        board_readiness=readiness,
        s_hand_diff=s_hand_diff,
        s_board_diff=s_board_diff,
    )


def _profile(style: str = "Unknown", confidence: float = 0.0) -> OpponentProfile:
    return OpponentProfile(
        style=style, speed="Medium",
        signature="test", confidence=confidence,
    )


# ──────────────────────────────────────────────────────────────────────────
# BDD Scenarios
# ──────────────────────────────────────────────────────────────────────────

def test_burst_fires_when_prize_2_and_readiness_full():
    """
    Given prize_left_self=2, board_readiness=1.0
    When route()
    Then active_state == RUSHING_PRIZES
    """
    result = route(_scores(prize_self=2, readiness=1.0), _profile())
    assert result.active_state == StateEnum.BURST, (
        f"expected BURST, got {result.active_state}"
    )


def test_burst_fires_when_prize_1_and_readiness_high():
    """
    Given prize_left_self=1, board_readiness=0.9
    When route()
    Then active_state == RUSHING_PRIZES
    """
    result = route(_scores(prize_self=1, readiness=0.9), _profile())
    assert result.active_state == StateEnum.BURST


def test_burst_does_not_fire_when_readiness_low():
    """
    Given prize_left_self=2, board_readiness=0.3 (not ready)
    When route()
    Then active_state != RUSHING_PRIZES
    """
    result = route(_scores(prize_self=2, readiness=0.3), _profile())
    assert result.active_state != StateEnum.BURST


def test_control_fires_when_opp_near_win_and_leading():
    """
    Given prize_left_opp=2, self has taken 3 prizes, opp has taken 4 prizes
    (opp_prizes_taken=4, self_prizes_taken=3 → diff=1 ≥ threshold)
    When route()
    Then active_state == DENYING_RESOURCES
    """
    result = route(
        _scores(prize_self=3, prize_opp=2),  # opp took 4, self took 3
        _profile(),
    )
    assert result.active_state == StateEnum.CONTROL, (
        f"expected CONTROL, got {result.active_state}"
    )


def test_counter_chain_control_opp_gives_tempo():
    """
    Given opponent style=Control, confidence=0.8
    And no immediate burst/control condition
    When route()
    Then active_state == SETTING_UP_BOARD  (运营克控手)
    """
    result = route(_scores(), _profile(style="Control", confidence=0.8))
    assert result.active_state == StateEnum.TEMPO, (
        f"expected TEMPO (counter Control), got {result.active_state}"
    )


def test_counter_chain_tempo_opp_gives_burst_when_ready():
    """
    Given opponent style=Tempo, confidence=0.8 AND board_readiness=0.9 (can burst)
    When route()
    Then active_state == RUSHING_PRIZES  (爆发克运营, deck has burst capability)
    """
    result = route(
        _scores(prize_self=4, readiness=0.9),
        _profile(style="Tempo", confidence=0.8),
    )
    assert result.active_state == StateEnum.BURST, (
        f"expected BURST (counter Tempo, ready board), got {result.active_state}"
    )


def test_counter_chain_tempo_opp_stays_tempo_when_not_ready():
    """
    Given opponent style=Tempo, confidence=0.8 BUT board_readiness=0.4 (can't burst)
    When route()
    Then active_state == SETTING_UP_BOARD (Control deck can't burst → stay Tempo)
    """
    result = route(
        _scores(prize_self=4, readiness=0.4),
        _profile(style="Tempo", confidence=0.8),
    )
    assert result.active_state == StateEnum.TEMPO, (
        f"expected TEMPO (can't burst vs Tempo), got {result.active_state}"
    )


def test_counter_chain_burst_opp_gives_control():
    """
    Given opponent style=Burst, confidence=0.8
    And no immediate burst/control condition
    When route()
    Then active_state == DENYING_RESOURCES  (控手克爆发)
    """
    result = route(_scores(), _profile(style="Burst", confidence=0.8))
    assert result.active_state == StateEnum.CONTROL, (
        f"expected CONTROL (counter Burst), got {result.active_state}"
    )


def test_unknown_opp_defaults_to_tempo():
    """
    Given opponent style=Unknown, no immediate conditions
    When route()
    Then active_state == SETTING_UP_BOARD
    """
    result = route(_scores(), _profile(style="Unknown", confidence=0.0))
    assert result.active_state == StateEnum.TEMPO


def test_low_confidence_does_not_trigger_counter_chain():
    """
    Given opponent style=Control but confidence=0.1 (below threshold)
    When route()
    Then counter-chain bias does NOT fire → default SETTING_UP_BOARD
    """
    result = route(_scores(), _profile(style="Control", confidence=0.1))
    assert result.active_state == StateEnum.TEMPO  # default


def test_hand_deficit_boosts_w_hand():
    """
    Given s_hand_diff=-4.0 (falling behind badly)
    When route() in TEMPO state
    Then policy_weights.w_hand > base 0.20
    """
    result = route(_scores(s_hand_diff=-4.0), _profile())
    assert result.active_state == StateEnum.TEMPO
    base_hand = 0.20
    assert result.policy_weights.w_hand > base_hand, (
        f"w_hand={result.policy_weights.w_hand} should exceed {base_hand}"
    )


def test_control_opp_boosts_w_board():
    """
    Given opponent=Control, confidence=0.9
    And state routes to TEMPO (counter-chain)
    Then policy_weights.w_board > base TEMPO w_board (0.60)
    """
    result = route(_scores(), _profile(style="Control", confidence=0.9))
    assert result.active_state == StateEnum.TEMPO
    base_board = 0.60
    assert result.policy_weights.w_board > base_board, (
        f"w_board={result.policy_weights.w_board} should exceed {base_board}"
    )


def test_weights_sum_to_one():
    """
    For any route() call, w_turn + w_board + w_hand ≈ 1.0
    """
    cases = [
        (_scores(prize_self=2, readiness=1.0), _profile()),
        (_scores(), _profile(style="Control", confidence=0.8)),
        (_scores(s_hand_diff=-5.0), _profile(style="Burst", confidence=0.7)),
    ]
    for sc, pr in cases:
        pw = route(sc, pr).policy_weights
        total = pw.w_turn + pw.w_board + pw.w_hand
        assert abs(total - 1.0) < 1e-4, (
            f"weights don't sum to 1: {pw} → total={total:.6f}"
        )


def test_burst_weights_favour_w_turn():
    """
    Given RUSHING_PRIZES state fires
    When route()
    Then w_turn is the dominant weight (> w_board and > w_hand)
    """
    result = route(_scores(prize_self=1, readiness=1.0), _profile())
    pw = result.policy_weights
    assert pw.w_turn > pw.w_board
    assert pw.w_turn > pw.w_hand


def test_control_weights_favour_w_hand():
    """
    Given DENYING_RESOURCES state fires (opp near-win and leading)
    When route()
    Then w_hand is dominant
    """
    result = route(_scores(prize_self=3, prize_opp=2), _profile())
    pw = result.policy_weights
    assert pw.w_hand > pw.w_turn
    assert pw.w_hand > pw.w_board


def test_priority_burst_over_counter_chain():
    """
    Given prize_self=2, readiness=1.0 AND opponent=Control (would → TEMPO)
    When route()
    Then BURST wins (higher priority than counter-chain)
    """
    result = route(
        _scores(prize_self=2, readiness=1.0),
        _profile(style="Control", confidence=0.9),
    )
    assert result.active_state == StateEnum.BURST, (
        f"BURST should override counter-chain, got {result.active_state}"
    )


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
