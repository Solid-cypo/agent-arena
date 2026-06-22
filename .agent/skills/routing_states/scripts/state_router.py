"""Skill 2: State Router — determine FSM tactical state and PolicyWeights.

Input:  SituationScores  (from assessing_situations.situation_assessor)
        OpponentProfile  (from assessing_situations.opponent_profiler)

Output: active_state: str       — one of RUSHING_PRIZES / SETTING_UP_BOARD / DENYING_RESOURCES
        policy_weights: PolicyWeights — (w_turn, w_board, w_hand) for action evaluator

FSM transition priority (highest first):
  1. Immediate kill check     → RUSHING_PRIZES
  2. Opponent near-win check  → DENYING_RESOURCES
  3. Counter-chain bias       → style-driven override
  4. Hand-deficit override    → boost w_hand
  5. Default                  → SETTING_UP_BOARD

Theory reference: ptcg_dimension_theory.md §2 克制链 / agent_design_spec.md §4
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# Make Skill 1 dataclasses importable when called from project root
_skill1_scripts = Path(__file__).resolve().parents[2] / "assessing_situations" / "scripts"
if str(_skill1_scripts) not in sys.path:
    sys.path.insert(0, str(_skill1_scripts))

from situation_assessor import SituationScores
from opponent_profiler import OpponentProfile


# ──────────────────────────────────────────────────────────────────────────
# Data contracts
# ──────────────────────────────────────────────────────────────────────────

class StateEnum:
    BURST   = "RUSHING_PRIZES"
    TEMPO   = "SETTING_UP_BOARD"
    CONTROL = "DENYING_RESOURCES"


@dataclass(frozen=True)
class PolicyWeights:
    w_turn: float
    w_board: float
    w_hand: float

    def clamp(self) -> "PolicyWeights":
        """Normalise so weights sum to 1.0."""
        total = self.w_turn + self.w_board + self.w_hand
        if total <= 0:
            return PolicyWeights(w_turn=0.33, w_board=0.34, w_hand=0.33)
        return PolicyWeights(
            w_turn=round(self.w_turn / total, 4),
            w_board=round(self.w_board / total, 4),
            w_hand=round(self.w_hand / total, 4),
        )


class RouteResult(NamedTuple):
    active_state: str
    policy_weights: PolicyWeights


# ──────────────────────────────────────────────────────────────────────────
# Base weight table (before any corrections)
# ──────────────────────────────────────────────────────────────────────────

_BASE_WEIGHTS: dict[str, PolicyWeights] = {
    StateEnum.BURST:   PolicyWeights(w_turn=0.90, w_board=0.08, w_hand=0.02),
    StateEnum.TEMPO:   PolicyWeights(w_turn=0.20, w_board=0.60, w_hand=0.20),
    StateEnum.CONTROL: PolicyWeights(w_turn=0.05, w_board=0.35, w_hand=0.60),
}

# Counter-chain style → preferred FSM state bias
# Theory §2: Burst beats Control, Control beats Tempo, Tempo beats Burst
_STYLE_COUNTER_BIAS: dict[str, str] = {
    "Control": StateEnum.TEMPO,   # 运营克控手: 侧面工具（强化锤）解场
    "Burst":   StateEnum.CONTROL, # 控手克爆发: 手牌韧性拖节奏
    "Tempo":   StateEnum.BURST,   # 爆发克运营: 抢轮次压时钟
}

# Root → weight correction mapping
# 理论: 攻击对手的战术根 (ptcg_dimension_theory.md §2 + nine-square image)
_ROOT_WEIGHT_CORRECTIONS: dict[str, dict[str, float]] = {
    # 対手根: 場面 (Burst) → disrupt board early (KO setup attacker)
    # → raise w_board to prioritise targeting the active/bench attacker
    "場面":     {"w_board": 0.15, "w_turn": 0.10, "w_hand": 0.0},

    # 対手根: 手牌→場面 (Tempo) → interrupt BEFORE hand-to-board conversion
    # → raise w_hand to trigger Boss's Orders / Iono to break the evolution chain
    "手牌→場面": {"w_hand": 0.20, "w_board": 0.05, "w_turn": 0.0},

    # 対手根: 多維 (Control) = 規則 + 手牌 + 場面 + 剩余轮次
    # Control resists any single-dimension attack — must pressure ALL dimensions.
    # → balanced boost across board (1081/Ruffian) AND hand (Xerosic) simultaneously
    # → do NOT suppress w_turn completely (still need tempo pressure)
    "多維":     {"w_board": 0.12, "w_hand": 0.10, "w_turn": 0.02},
}

# Thresholds
_BURST_PRIZE_THRESHOLD     = 2      # self prize ≤ this → consider BURST
_BURST_READINESS_THRESHOLD = 0.8    # board readiness ≥ this → BURST fires
_CONTROL_PRIZE_THRESHOLD   = 2      # opp prize ≤ this → danger zone
_CONTROL_LEAD_THRESHOLD    = 1      # opp ahead by ≥ this prizes → CONTROL
_HAND_DEFICIT_THRESHOLD    = -3.0   # s_hand_diff ≤ this → boost w_hand
_HAND_BOOST_AMOUNT         = 0.25   # additive boost to w_hand
_BOARD_BOOST_VS_CONTROL    = 0.15   # additive boost to w_board vs Control opp
_HAND_CAP                  = 0.80   # max w_hand after boost


# ──────────────────────────────────────────────────────────────────────────
# FSM transition logic
# ──────────────────────────────────────────────────────────────────────────

def _determine_base_state(
    scores: SituationScores,
    profile: OpponentProfile,
) -> str:
    """Priority-ordered state determination (no weight adjustment yet)."""

    opp_prizes_taken  = 6 - scores.prize_left_opp
    self_prizes_taken = 6 - scores.prize_left_self

    # ── 1. BURST: we can finish very soon ────────────────────────────────
    if (scores.prize_left_self <= _BURST_PRIZE_THRESHOLD
            and scores.board_readiness >= _BURST_READINESS_THRESHOLD):
        return StateEnum.BURST

    # ── 2. CONTROL: opponent is close to winning and leading ─────────────
    if (scores.prize_left_opp <= _CONTROL_PRIZE_THRESHOLD
            and (opp_prizes_taken - self_prizes_taken) >= _CONTROL_LEAD_THRESHOLD):
        return StateEnum.CONTROL

    # ── 3. Counter-chain bias from opponent style ─────────────────────────
    # Only apply state change if our board CAN support the required posture:
    #   Control opp → TEMPO  (always safe: just prioritise side-tools)
    #   Burst opp   → CONTROL (always safe: defend and disrupt)
    #   Tempo opp   → BURST  (only if board_readiness is high enough to burst;
    #                          otherwise stay TEMPO — don't force Burst on a
    #                          Control deck that lacks burst capability)
    if profile.confidence >= 0.3 and profile.style in _STYLE_COUNTER_BIAS:
        target = _STYLE_COUNTER_BIAS[profile.style]
        if target == StateEnum.BURST and scores.board_readiness < _BURST_READINESS_THRESHOLD:
            target = StateEnum.TEMPO  # can't burst → stay in Tempo
        return target

    # ── 4. Default ───────────────────────────────────────────────────────
    return StateEnum.TEMPO


def _apply_corrections(
    state: str,
    scores: SituationScores,
    profile: OpponentProfile,
) -> PolicyWeights:
    """Start from base weights, then apply dynamic corrections."""

    pw = _BASE_WEIGHTS[state]
    w_turn  = pw.w_turn
    w_board = pw.w_board
    w_hand  = pw.w_hand

    # ── A. Hand-deficit: boost w_hand regardless of state ─────────────────
    if scores.s_hand_diff <= _HAND_DEFICIT_THRESHOLD:
        w_hand = min(_HAND_CAP, w_hand + _HAND_BOOST_AMOUNT)

    # ── B. Root-based weight correction (攻击战术根) ──────────────────────
    opp_root = getattr(profile, "root", "Unknown")
    if opp_root in _ROOT_WEIGHT_CORRECTIONS and profile.confidence >= 0.3:
        corr = _ROOT_WEIGHT_CORRECTIONS[opp_root]
        w_turn  = max(0.02, min(0.95, w_turn  + corr.get("w_turn",  0.0)))
        w_board = max(0.02, min(0.95, w_board + corr.get("w_board", 0.0)))
        w_hand  = max(0.02, min(0.95, w_hand  + corr.get("w_hand",  0.0)))

    # ── C. Opponent is Control: boost w_board for side-tools (1081 etc.) ──
    if profile.style == "Control" and profile.confidence >= 0.3:
        w_board = min(0.85, w_board + _BOARD_BOOST_VS_CONTROL)

    # ── C. TEMPO state but opponent is very fast (s_turn strongly negative)
    #       nudge toward BURST-like weights to avoid falling behind
    if state == StateEnum.TEMPO and scores.s_turn <= -2:
        w_turn = min(0.5, w_turn + 0.15)
        w_hand = max(0.05, w_hand - 0.10)

    return PolicyWeights(w_turn=w_turn, w_board=w_board, w_hand=w_hand).clamp()


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def route(
    scores: SituationScores,
    profile: OpponentProfile,
) -> RouteResult:
    """Determine active FSM state and PolicyWeights.

    Args:
        scores:  Output of situation_assessor.assess()
        profile: Output of opponent_profiler.profile_opponent()

    Returns:
        RouteResult(active_state, policy_weights)
    """
    state   = _determine_base_state(scores, profile)
    weights = _apply_corrections(state, scores, profile)
    return RouteResult(active_state=state, policy_weights=weights)
