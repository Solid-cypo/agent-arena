"""Prize Path Planner — combinatorial shortest-path optimiser.

Given the opponent's visible board, finds the minimum-turns subset of targets
whose combined prize value satisfies the remaining prize requirement.

    Minimise:  sum T_KO(p_i)   subject to:  sum V_prize(p_i) >= R

where T_KO(p_i) = ceil(HP(p_i) / D_est)

No cg.api dependency — all inputs are plain Python values.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TargetPokemon:
    pokemon_id: int
    hp: float
    prize_value: int      # 1 = normal, 2 = ex/V, 3 = Mega ex
    turns_to_ko: int = 1  # computed by PrizePathPlanner


@dataclass
class PrizePath:
    target_ids: list[int]   # card IDs in the optimal target set
    total_turns: int         # minimum turns to clear the path
    total_prizes: int        # prizes earned by clearing


_CARD_DB_CACHE: dict[str, Any] | None = None
_DB_PATH = (
    Path(__file__).resolve().parents[4]
    / ".agent" / "skills" / "parsing_cards" / "assets" / "card_db.json"
)


def _card_prize_value(card_id: int) -> int:
    """Return how many prize cards the opponent takes when this Pokemon is KO'd."""
    global _CARD_DB_CACHE
    if _CARD_DB_CACHE is None:
        try:
            import json
            _CARD_DB_CACHE = json.loads(_DB_PATH.read_text(encoding="utf-8"))["cards"]
        except Exception:
            _CARD_DB_CACHE = {}
    c = _CARD_DB_CACHE.get(str(card_id), {})
    if c.get("megaEx"):
        return 3
    if c.get("ex"):
        return 2
    return 1


def extract_targets_from_obs(obs_dict: dict[str, Any]) -> list[TargetPokemon]:
    """Build a TargetPokemon list from the raw cabt obs_dict.

    Reads opponent's active + bench Pokemon via cg.api.
    Returns empty list on any error (planner degrades gracefully).
    """
    targets: list[TargetPokemon] = []
    try:
        from cg.api import to_observation_class
        obs = to_observation_class(obs_dict)
        current = obs.current
        if current is None:
            return targets
        opp_index = 1 - int(current.yourIndex)
        opp = current.players[opp_index]

        board: list[Any] = []
        board += [p for p in (getattr(opp, "active", None) or []) if p is not None]
        board += [p for p in (getattr(opp, "bench",  None) or []) if p is not None]

        for p in board:
            cid = int(getattr(p, "id", 0) or 0)
            hp  = float(getattr(p, "hp", 100) or 100)
            targets.append(TargetPokemon(
                pokemon_id=cid,
                hp=max(hp, 1.0),
                prize_value=_card_prize_value(cid),
            ))
    except Exception:
        pass
    return targets


class PrizePathPlanner:
    """Find the minimum-turns prize-winning target combination.

    Args:
        base_damage_est: Expected damage per attack turn.
                         Should reflect current board state (attacker + buffs).
    """

    def __init__(self, base_damage_est: float = 130.0):
        self.base_damage_est = max(base_damage_est, 1.0)

    def plan(
        self,
        targets: list[TargetPokemon],
        remaining_prizes: int,
    ) -> PrizePath:
        """Compute the optimal prize path.

        Complexity: O(2^n) where n = len(targets) ≤ 6 bench + 1 active = 7.
        At most 128 combinations — trivially fast.

        Returns PrizePath with empty target_ids if no valid combination exists.
        """
        if not targets or remaining_prizes <= 0:
            return PrizePath(target_ids=[], total_turns=0, total_prizes=0)

        # Annotate turns_to_ko
        for t in targets:
            t.turns_to_ko = math.ceil(t.hp / self.base_damage_est)

        best: PrizePath = PrizePath(target_ids=[], total_turns=999_999, total_prizes=0)

        for r in range(1, len(targets) + 1):
            for combo in itertools.combinations(targets, r):
                total_prizes = sum(t.prize_value for t in combo)
                if total_prizes < remaining_prizes:
                    continue
                total_turns = sum(t.turns_to_ko for t in combo)
                if total_turns < best.total_turns:
                    best = PrizePath(
                        target_ids=[t.pokemon_id for t in combo],
                        total_turns=total_turns,
                        total_prizes=total_prizes,
                    )

        return best

    def plan_from_obs(
        self,
        obs_dict: dict[str, Any],
        remaining_prizes: int,
    ) -> PrizePath:
        """Convenience wrapper that extracts targets from a cabt obs_dict."""
        targets = extract_targets_from_obs(obs_dict)
        return self.plan(targets, remaining_prizes)


# ---------------------------------------------------------------------------
# Action alignment helpers (called from action_evaluator.py)
# ---------------------------------------------------------------------------

# Bonus added to S_turn when Boss's Orders targets a prize-path Pokemon.
# Kept within policy.py score range (~0-5) so it nudges but doesn't dominate.
BOSS_ORDERS_PATH_BONUS = 2.5

# Bonus to S_board when attaching energy to attacker that can reach a target.
ATTACH_PATH_ALIGN_BONUS = 0.5


def boss_orders_bonus(option: Any, obs: Any, prize_path: PrizePath, my_index: int) -> float:
    """Return BOSS_ORDERS_PATH_BONUS if this PLAY option is Boss's Orders
    and the nominated target is in the optimal prize path.

    Boss's Orders (1182) is a PLAY option; the target is encoded as the bench
    index of the opponent's Pokemon via option.index + AreaType.BENCH.
    """
    try:
        from cg.api import AreaType, OptionType
        if option.type != OptionType.PLAY:
            return 0.0
        # Resolve played card id from hand
        opp_index = 1 - my_index
        hand = obs.current.players[my_index].hand or []
        idx = int(getattr(option, "index", -1))
        if 0 <= idx < len(hand) and hand[idx] is not None:
            played_id = int(getattr(hand[idx], "id", 0))
            if played_id != 1182:   # not Boss's Orders
                return 0.0
        else:
            return 0.0

        # Target Pokemon is on opponent's bench (the option carries a bench index)
        bench = obs.current.players[opp_index].bench or []
        bench_idx = int(getattr(option, "index", -1))
        if 0 <= bench_idx < len(bench) and bench[bench_idx] is not None:
            target_cid = int(getattr(bench[bench_idx], "id", 0))
            if target_cid in prize_path.target_ids:
                return BOSS_ORDERS_PATH_BONUS
    except Exception:
        pass
    return 0.0
