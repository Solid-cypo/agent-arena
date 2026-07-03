"""Dudunsparce draw axis (Axis B): Run Away Draw cycle + 306 ex branch (P-3).

See references/phases/02_draw_axis.md for DD-1~DD-6.
Decisions use board + hand + deck_resources only (no opponent profiling).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deck_resources import DeckResourceSnapshot, HandContext
from hand_snapshot import BoardSnapshot
from opening_cards import DUDUNSPARCE, DUDUNSPARCE_EX, DUNSPARCE_A, DUNSPARCE_B, LILLIE
from phase_fsm import PhaseState

DrawAction = Literal["EVOLVE_66", "ABILITY_DRAW", "PLAY_306", "HOLD", "FORBID"]

_DUNSPARCE_BASIC = frozenset({DUNSPARCE_A, DUNSPARCE_B})


@dataclass(frozen=True)
class DrawAxisDecision:
    action: DrawAction
    rule_id: str
    priority: float
    reason: str


def _has_dunsparce_basic(hand: HandContext) -> bool:
    return any(cid in _DUNSPARCE_BASIC for cid in hand.hand_ids)


def _first_aggression_turn(phase: PhaseState, board: BoardSnapshot) -> bool:
    return (
        phase.opening_complete
        and phase.primary == "AGGRESSION"
        and board.my_turn_number == 2
    )


def should_forbid_cycle(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    on_bench_66: bool = False,
) -> tuple[bool, str]:
    # OPENING: expert gold uses Run Away Draw in the opening (e.g. the My-T2
    # REC retreat-draw line), so the v1 "forbid the 66 cycle in OPENING" rule
    # (DD-OPENING) is outdated. Let the RL policy lead; the gold-aligned draw
    # axis boost below may still fire as fallback.
    if phase.primary == "OPENING":
        return False, ""

    if not phase.opening_complete:
        return True, "DD-OPENING"

    if _first_aggression_turn(phase, board):
        return True, "DD-1"

    if not board.bench_three_core_ready:
        return True, "DD-2"

    if board.bench_open <= 0 and not on_bench_66:
        return True, "DD-2b"

    if hand.hand_size > 4:
        return True, "DD-3"

    if not resources.can_run_away_cycle(hand, on_bench_66=on_bench_66):
        return True, "DD-7"

    if board.prize_self > board.prize_opp and board.active_is_mega_starmie:
        return True, "DD-4"

    if resources.prefer_lillie_over_cycle(hand) and not on_bench_66:
        return True, "DD-8"

    return False, ""


def should_play_306_ex(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    mega_starmie_hp_low: bool = False,
) -> DrawAxisDecision | None:
    """P-3: 306 when backup needed, unseen copy exists, 1031 threatened."""
    if DUDUNSPARCE_EX not in hand.hand_ids:
        return None
    if phase.primary not in ("AGGRESSION", "HARVEST"):
        return None
    if resources.exhausted(DUDUNSPARCE_EX) and hand.hand_ids.count(DUDUNSPARCE_EX) == 0:
        return None
    if not mega_starmie_hp_low and board.active_is_mega_starmie:
        return None
    if resources.staryu_line_left > 0 or board.staryu_on_field:
        return None

    return DrawAxisDecision(
        action="PLAY_306",
        rule_id="DD-6",
        priority=850.0,
        reason="Mega Starmie threatened, no backup Staryu unseen → Dudunsparce ex",
    )


def pick_draw_axis_action(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    dunsparce_on_bench_can_evolve: bool = False,
    dudunsparce_66_on_bench: bool = False,
    mega_starmie_hp_low: bool = False,
) -> DrawAxisDecision | None:
    forbidden, forbid_id = should_forbid_cycle(
        board, phase, hand, resources, on_bench_66=dudunsparce_66_on_bench,
    )
    if forbidden and forbid_id:
        ex = should_play_306_ex(
            board, phase, hand, resources, mega_starmie_hp_low=mega_starmie_hp_low,
        )
        if ex:
            return ex
        return DrawAxisDecision(
            action="FORBID",
            rule_id=forbid_id,
            priority=0.0,
            reason=f"66 cycle forbidden ({forbid_id})",
        )

    if dudunsparce_66_on_bench:
        return DrawAxisDecision(
            action="ABILITY_DRAW",
            rule_id="DR-4",
            priority=900.0,
            reason=f"Run Away Draw +3 ({resources.likely_in_deck(LILLIE)} Lillie likely in deck)",
        )

    if dunsparce_on_bench_can_evolve or _has_dunsparce_basic(hand):
        return DrawAxisDecision(
            action="EVOLVE_66",
            rule_id="DR-4",
            priority=880.0,
            reason="Evolve to Dudunsparce — 66 copies left unseen: "
            f"{resources.dudunsparce_66_left}, basics: {resources.dunsparce_basic_left}",
        )

    if resources.prefer_cycle_over_lillie(hand) and resources.can_run_away_cycle(hand):
        return DrawAxisDecision(
            action="EVOLVE_66",
            rule_id="DR-4b",
            priority=870.0,
            reason="Preserve Lillie — cycle 66 for +3",
        )

    return None
