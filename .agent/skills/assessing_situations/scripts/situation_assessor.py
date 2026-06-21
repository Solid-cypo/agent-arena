"""Skill 1: Situation Assessor — compute SituationScores from a cabt Observation.

Implements the Three-Dimensional Theory from references/ptcg_dimension_theory.md:
  S_hand  = hand count + DrawPotential sum
  S_board = sum of (HP_ratio × MaxDmg × EnergyReadiness) over own board
  S_turn  = TC_opp - TC_me  (positive = we are faster)

No game-engine calls are made here; all inputs come from obs_dict only.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parents[1]
_WEIGHTS_PATH = _SKILL_ROOT / "references" / "card_tactic_weights.json"

_tactic_cfg: dict[str, Any] | None = None


def _cfg() -> dict[str, Any]:
    global _tactic_cfg
    if _tactic_cfg is None:
        _tactic_cfg = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    return _tactic_cfg


@dataclass(frozen=True)
class SituationScores:
    s_hand: float
    s_board: float
    s_turn: float

    tc_me: float
    tc_opp: float
    prize_left_self: int
    prize_left_opp: int

    board_readiness: float
    s_hand_diff: float
    s_board_diff: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pokemon_max_damage(pokemon: Any) -> float:
    """Best-effort max damage from a Pokemon object."""
    try:
        attacks = getattr(pokemon, "attacks", None) or []
        if not attacks:
            return _cfg().get("tc_damage_default", 80.0)
        return float(max(
            (getattr(a, "damage", 0) or 0) for a in attacks
        ))
    except Exception:
        return _cfg().get("tc_damage_default", 80.0)


def _pokemon_hp(pokemon: Any) -> tuple[float, float]:
    """Return (current_hp, max_hp). Falls back to defaults."""
    try:
        max_hp = _safe_float(getattr(pokemon, "maxHp", None),
                             _cfg().get("tc_prize_hp_default", 100.0))
        cur_hp = _safe_float(getattr(pokemon, "hp", None), max_hp)
        max_hp = max(max_hp, 1.0)
        return cur_hp, max_hp
    except Exception:
        d = float(_cfg().get("tc_prize_hp_default", 100))
        return d, d


def _pokemon_energy_readiness(pokemon: Any) -> float:
    """Ratio of attached energy to attack cost. Clamped [0, 1]."""
    try:
        attacks = getattr(pokemon, "attacks", None) or []
        if not attacks:
            return 1.0
        best_attack = max(attacks, key=lambda a: getattr(a, "damage", 0) or 0)
        required = _safe_int(getattr(best_attack, "energyCount", None), 1)
        required = max(required, 1)
        attached = _safe_int(getattr(pokemon, "energyCount", None), 0)
        return min(1.0, attached / required)
    except Exception:
        return 0.5


def _iter_board(player: Any) -> list[Any]:
    """Yield all non-None Pokemon on a player's board (active + bench)."""
    board: list[Any] = []
    try:
        active = getattr(player, "active", None) or []
        bench = getattr(player, "bench", None) or []
        for p in list(active) + list(bench):
            if p is not None:
                board.append(p)
    except Exception:
        pass
    return board


def _hand_card_ids(player: Any) -> list[int]:
    try:
        return [_safe_int(getattr(c, "id", None)) for c in (player.hand or [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Three-dimensional scorers
# ---------------------------------------------------------------------------

def _compute_s_hand(player: Any, hand_card_ids: list[int]) -> float:
    """S_hand = N_hand + sum DrawPotential(c) for c in hand."""
    draw_table: dict[str, float] = _cfg().get("draw_potential", {})
    n_hand = _safe_int(getattr(player, "handCount", None), len(hand_card_ids))
    draw_bonus = sum(draw_table.get(str(cid), 0.0) for cid in hand_card_ids)
    return float(n_hand) + draw_bonus


def _compute_s_board(player: Any) -> tuple[float, float]:
    """Return (S_board, board_readiness).

    S_board = sum over board of HP_ratio × MaxDmg × EnergyReadiness
    board_readiness = mean EnergyReadiness of non-zero-HP Pokemon.
    """
    board = _iter_board(player)
    if not board:
        return 0.0, 0.0

    total_score = 0.0
    readiness_vals: list[float] = []

    for p in board:
        cur_hp, max_hp = _pokemon_hp(p)
        if cur_hp <= 0:
            continue
        hp_ratio = cur_hp / max_hp
        max_dmg = _pokemon_max_damage(p)
        energy_ready = _pokemon_energy_readiness(p)
        total_score += hp_ratio * max_dmg * energy_ready
        readiness_vals.append(energy_ready)

    board_readiness = sum(readiness_vals) / len(readiness_vals) if readiness_vals else 0.0
    return total_score, board_readiness


def _compute_tc(
    attacker_board: list[Any],
    defender_board: list[Any],
    prize_left: int,
) -> float:
    """Estimate minimum turns to take all remaining prizes.

    TC = ceil(sum_opp_prize_HP / my_max_dmg_per_turn)
    prize_left is the number of prizes still remaining for the attacker to win.
    """
    cfg = _cfg()
    default_dmg = float(cfg.get("tc_damage_default", 80))
    default_hp = float(cfg.get("tc_prize_hp_default", 100))

    # Best damage available to attacker (max over board)
    my_max_dmg = default_dmg
    for p in attacker_board:
        cur_hp, _ = _pokemon_hp(p)
        if cur_hp > 0:
            my_max_dmg = max(my_max_dmg, _pokemon_max_damage(p))

    # Total HP attacker must burn through (estimate: prizes × avg HP)
    total_defender_hp = prize_left * default_hp
    for p in defender_board:
        cur_hp, _ = _pokemon_hp(p)
        if cur_hp > 0:
            total_defender_hp = prize_left * max(cur_hp, default_hp)
            break  # use first active as representative

    tc = math.ceil(total_defender_hp / max(my_max_dmg, 1.0))
    return float(max(tc, 1))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess(obs_dict: dict[str, Any]) -> SituationScores:
    """Compute SituationScores from a raw cabt obs_dict.

    Designed to be called at the start of every agent turn.
    Raises ValueError if obs_dict lacks required current-state fields.
    """
    from cg.api import to_observation_class  # imported lazily; not available in tests without cg

    obs = to_observation_class(obs_dict)
    current = obs.current
    if current is None:
        raise ValueError("obs.current is None — cannot assess situation")

    my_index = _safe_int(current.yourIndex, 0)
    opp_index = 1 - my_index

    players = current.players
    me = players[my_index]
    opp = players[opp_index]

    # Prize counts
    prize_left_self = _safe_int(getattr(me, "prizeCount", None), 6)
    prize_left_opp = _safe_int(getattr(opp, "prizeCount", None), 6)

    # Hand
    my_hand_ids = _hand_card_ids(me)
    s_hand_me = _compute_s_hand(me, my_hand_ids)
    opp_hand_count = _safe_int(getattr(opp, "handCount", None), 5)
    s_hand_opp = float(opp_hand_count)  # opponent hand is hidden; no DrawPotential

    s_hand_diff = s_hand_me - s_hand_opp

    # Board
    my_board = _iter_board(me)
    opp_board = _iter_board(opp)
    s_board_me, board_readiness = _compute_s_board(me)
    s_board_opp, _ = _compute_s_board(opp)
    s_board_diff = s_board_me - s_board_opp

    # Turn clocks
    tc_me = _compute_tc(my_board, opp_board, prize_left_self)
    tc_opp = _compute_tc(opp_board, my_board, prize_left_opp)
    s_turn = tc_opp - tc_me  # positive = we finish faster

    return SituationScores(
        s_hand=s_hand_me,
        s_board=s_board_me,
        s_turn=s_turn,
        tc_me=tc_me,
        tc_opp=tc_opp,
        prize_left_self=prize_left_self,
        prize_left_opp=prize_left_opp,
        board_readiness=board_readiness,
        s_hand_diff=s_hand_diff,
        s_board_diff=s_board_diff,
    )
