"""Supporter PLAY decisions for AGGRESSION+ (Axis B/C).

See references/phases/02_draw_axis.md — board + hand + deck_resources only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deck_resources import DeckResourceSnapshot, HandContext, build_hand_context_from_obs
from hand_snapshot import BoardSnapshot
from opening_cards import (
    BOSS_ORDERS,
    CRISPIN,
    JUDGE,
    LILLIE,
    POKE_PAD,
    UNFAIR_STAMP,
    WALLYS_COMPASSION,
)
from phase_fsm import PhaseState

SupporterAction = Literal["PLAY", "HOLD", "FORBID"]


@dataclass(frozen=True)
class SupporterDecision:
    action: SupporterAction
    card_id: int | None
    rule_id: str
    priority: float
    reason: str


def _in_hand(hand: HandContext, card_id: int) -> bool:
    return card_id in hand.hand_ids


def _first_aggression_turn(phase: PhaseState, board: BoardSnapshot) -> bool:
    return (
        phase.opening_complete
        and phase.primary == "AGGRESSION"
        and board.my_turn_number == 2
    )


def lillie_forbidden(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
) -> tuple[bool, str]:
    if phase.primary == "OPENING" or not phase.opening_complete:
        return True, "DR-1"

    if _first_aggression_turn(phase, board):
        return True, "DR-5c"

    if hand.has_boss and hand.gust_target_on_opp_bench:
        return True, "DR-5"

    if hand.hand_size >= 5:
        return True, "DR-5b"

    if resources.exhausted(LILLIE) and LILLIE not in hand.hand_ids:
        return True, "DR-1b"

    return False, ""


def lillie_priority(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
) -> SupporterDecision | None:
    if not _in_hand(hand, LILLIE):
        if resources.need_lillie_for_missing(hand, want_boss=True, want_pad=False):
            return None
        return None

    forbidden, rule = lillie_forbidden(board, phase, hand, resources)
    if forbidden:
        return SupporterDecision("FORBID", LILLIE, rule, 0.0, f"Lillie forbidden ({rule})")

    priority = 800.0
    if hand.hand_size <= 2:
        return SupporterDecision(
            "PLAY", LILLIE, "DR-2", priority + 50.0,
            f"hand_size={hand.hand_size}, Lillie unseen left={resources.lillie_left}",
        )

    if board.prize_self == 6 and resources.staryu_line_left > 0 and not board.staryu_on_field:
        return SupporterDecision(
            "PLAY", LILLIE, "DR-3", priority + 30.0,
            f"prize=6, Staryu line unseen={resources.staryu_line_left} → Lillie 8-draw",
        )

    if resources.need_lillie_for_missing(
        hand, want_boss=True, want_pad=board.bench_three_core_ready,
    ) and resources.prefer_lillie_over_cycle(hand):
        return SupporterDecision(
            "PLAY", LILLIE, "DR-3b", priority + 20.0,
            f"seek Boss/Pad — boss unseen={resources.boss_left}, pad unseen={resources.pad_left}",
        )

    return None


def pick_supporter(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    mega_starmie_damaged: bool = False,
    harvest_ko_last_turn: bool = False,
) -> SupporterDecision | None:
    if hand.supporter_played:
        return None

    if phase.primary == "OPENING":
        return None

    if hand.has_boss and hand.gust_target_on_opp_bench and _in_hand(hand, BOSS_ORDERS):
        return SupporterDecision(
            "PLAY", BOSS_ORDERS, "SP-BOSS-1", 950.0,
            f"Boss gust — boss unseen left={resources.boss_left}",
        )

    if harvest_ko_last_turn and _in_hand(hand, UNFAIR_STAMP) and phase.primary == "HARVEST":
        return SupporterDecision(
            "PLAY", UNFAIR_STAMP, "DR-6", 920.0,
            "Unfair Stamp after Mega Starmie KO",
        )

    # Judge in HARVEST+CONTROL: handled by HR-C3 + harvest_resentful_fired in starmie_pilot

    if (
        board.munkidori_on_bench
        and not board.munkidori_has_dark
        and _in_hand(hand, CRISPIN)
    ):
        return SupporterDecision(
            "PLAY", CRISPIN, "SP-CRIS-1", 880.0,
            "Crispin — dark for Munkidori",
        )

    if mega_starmie_damaged and _in_hand(hand, WALLYS_COMPASSION) and board.active_is_mega_starmie:
        return SupporterDecision(
            "PLAY", WALLYS_COMPASSION, "SP-WALLY-1", 860.0,
            "Wally — heal Mega Starmie",
        )

    if _first_aggression_turn(phase, board):
        return SupporterDecision(
            "HOLD", None, "DR-5c", 0.0,
            "First AGGRESSION turn — pits + attack; "
            f"deck={resources.deck_count}, boss unseen={resources.boss_left}",
        )

    lillie = lillie_priority(board, phase, hand, resources)
    if lillie and lillie.action == "PLAY":
        return lillie
    if lillie and lillie.action == "FORBID":
        return lillie

    if (
        resources.need_lillie_for_missing(hand, want_boss=True, want_pad=False)
        and not hand.has_boss
        and resources.boss_left > 0
        and POKE_PAD in hand.hand_ids
    ):
        return SupporterDecision(
            "HOLD", None, "SP-HOLD-BOSS", 0.0,
            f"Boss still in deck ({resources.likely_in_deck(BOSS_ORDERS)} likely) — hold supporter",
        )

    return SupporterDecision(
        "HOLD", None, "SP-HOLD", 0.0,
        f"deck={resources.deck_count}, Lillie left={resources.lillie_left}, "
        f"66 left={resources.dudunsparce_66_left}",
    )


__all__ = [
    "SupporterDecision",
    "pick_supporter",
    "lillie_forbidden",
    "build_hand_context_from_obs",
]
