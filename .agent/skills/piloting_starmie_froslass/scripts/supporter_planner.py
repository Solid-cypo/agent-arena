"""Supporter PLAY decisions (Axis B/C) — gap-driven Lillie, soft-prefer fix-now tools.

See references/phases/02_draw_axis.md — board + hand + deck_resources only.

Hard-rule redesign (2026-07):
  * Removed DR-1 (OPENING blanket ban), DR-5b (hand≥5), DR-5c (first AGGRESSION).
  * Lillie is gap-driven: hs≤2 / missing pieces / OPENING dig when no fix-now tool.
  * Soft-prefer Boss/Hilda/Crispin when they solve the board *now*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deck_resources import DeckResourceSnapshot, HandContext, build_hand_context_from_obs
from hand_snapshot import BoardSnapshot
from opening_cards import (
    BOSS_ORDERS,
    CRISPIN,
    HILDA,
    JUDGE,
    LILLIE,
    POKE_PAD,
    SNORUNT,
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


_OTHER_SUPPORTERS = (LILLIE, HILDA, CRISPIN, JUDGE, UNFAIR_STAMP, WALLYS_COMPASSION)


def _boss_ok(
    board: BoardSnapshot, phase: PhaseState, hand: HandContext | None = None,
) -> bool:
    """P2: 运转大于一切 — Boss only after MEGA + DP set are built, or when
    closing (≤2 prizes). Otherwise the slot goes to draw/setup supporters.
    Relaxation: if Boss is the ONLY supporter in hand, playing it beats an
    empty supporter slot (also 运转)."""
    if board.prize_self <= 2:
        return True
    if not getattr(phase, "opening_complete", False):
        return False
    dp_ready = (
        board.froslass_104_on_field
        or getattr(board, "mega_froslass_on_field", False)
    ) and board.munkidori_on_field
    if dp_ready:
        return True
    if hand is not None:
        # Immediate prize this turn — tempo Boss is engine-positive.
        if getattr(hand, "gust_target_koable", False):
            return True
        # Boss as the only supporter beats an empty supporter slot.
        if not any(_in_hand(hand, s) for s in _OTHER_SUPPORTERS):
            return True
    return False


def _fix_now_supporter(
    hand: HandContext, board: BoardSnapshot, phase: PhaseState | None = None,
) -> int | None:
    """Return a supporter that immediately advances the board (prefer over Lillie)."""
    if (
        hand.has_boss
        and hand.gust_target_on_opp_bench
        and _in_hand(hand, BOSS_ORDERS)
        and (phase is None or _boss_ok(board, phase, hand))
    ):
        return BOSS_ORDERS
    # Hilda / Crispin: water or mega line still missing while opening incomplete.
    if not board.active_is_mega_starmie or not board.active_has_water:
        if _in_hand(hand, HILDA) and (
            not board.mega_starmie_on_field or not board.staryu_on_field
        ):
            return HILDA
        if _in_hand(hand, CRISPIN) and (
            (board.staryu_on_field and not board.active_has_water)
            or (board.munkidori_on_bench and not board.munkidori_has_dark)
        ):
            return CRISPIN
    return None


def lillie_forbidden(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
) -> tuple[bool, str]:
    """Hard bans only — OPENING / hand-size / first-aggression are no longer bans."""
    # Prefer Boss gust over washing the hand with Lillie — only once the
    # engine is built (P2: 运转大于一切).
    if hand.has_boss and hand.gust_target_on_opp_bench and _boss_ok(board, phase, hand):
        return True, "DR-5"

    # Soft-prefer fix-now tools (Hilda/Crispin/Boss) over Lillie dig.
    if _fix_now_supporter(hand, board, phase) is not None:
        return True, "DR-FIX-NOW"

    if resources.exhausted(LILLIE) and LILLIE not in hand.hand_ids:
        return True, "DR-1b"

    return False, ""


def lillie_should_play(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
) -> bool:
    """Gap-driven PLAY gate (positive path)."""
    if not _in_hand(hand, LILLIE):
        return False
    forbidden, _ = lillie_forbidden(board, phase, hand, resources)
    if forbidden:
        return False
    if hand.supporter_played:
        return False

    # E-SUP-1: going-first My-T1 cannot play supporters.
    going_first = board.my_index == board.first_player
    if going_first and board.my_turn_number == 1:
        return False

    # hs≤2 — always dig.
    if hand.hand_size <= 2:
        return True

    # OPENING dig: still missing attack line / water / mega promote tools.
    if phase.primary == "OPENING" or not phase.opening_complete:
        if not board.staryu_on_field and resources.staryu_line_left > 0:
            return True
        if board.staryu_on_field and not board.mega_starmie_on_field:
            return True
        if board.mega_starmie_on_field and not board.active_is_mega_starmie:
            return True
        if board.staryu_on_field and not board.active_has_water and hand.hand_size <= 4:
            return True
        # End-of-turn style dig when hand is thin and gaps remain.
        if hand.hand_size <= 4 and (
            resources.need_lillie_for_missing(hand, want_boss=True, want_pad=False)
            or resources.prefer_lillie_over_cycle(hand)
        ):
            return True
        return False

    # Post-OPENING: classic DR-2 / DR-3 / DR-3b triggers.
    if board.prize_self == 6 and resources.staryu_line_left > 0 and not board.staryu_on_field:
        return True
    if resources.need_lillie_for_missing(
        hand, want_boss=True, want_pad=board.bench_three_core_ready,
    ) and resources.prefer_lillie_over_cycle(hand):
        return True
    # Post-usable-Mega: keep spending Supporter — dig when hand is not fat.
    # Require opening_complete (not bare HARVEST — T3+ Snorunt can enter HARVEST early).
    if phase.opening_complete and hand.hand_size <= 5:
        return True
    return False


def lillie_priority(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
) -> SupporterDecision | None:
    if not _in_hand(hand, LILLIE):
        return None

    forbidden, rule = lillie_forbidden(board, phase, hand, resources)
    if forbidden:
        return SupporterDecision("FORBID", LILLIE, rule, 0.0, f"Lillie forbidden ({rule})")

    if not lillie_should_play(board, phase, hand, resources):
        return None

    priority = 800.0
    if hand.hand_size <= 2:
        return SupporterDecision(
            "PLAY", LILLIE, "DR-2", priority + 50.0,
            f"hand_size={hand.hand_size}, Lillie unseen left={resources.lillie_left}",
        )

    if phase.primary == "OPENING" or not phase.opening_complete:
        return SupporterDecision(
            "PLAY", LILLIE, "DR-OPEN", priority + 40.0,
            "OPENING gap dig — Lillie allowed (DR-1 removed)",
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

    return SupporterDecision(
        "PLAY", LILLIE, "DR-GAP", priority + 10.0,
        "gap-driven Lillie",
    )


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

    # E-SUP-1 handled per-card; OPENING no longer blank-returns.

    if (
        hand.has_boss
        and hand.gust_target_on_opp_bench
        and _in_hand(hand, BOSS_ORDERS)
        and _boss_ok(board, phase, hand)
    ):
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

    # Soft-prefer Hilda when opening still needs mega/water and Hilda is in hand.
    if (
        (phase.primary == "OPENING" or not phase.opening_complete)
        and _in_hand(hand, HILDA)
        and (not board.mega_starmie_on_field or not board.staryu_on_field)
    ):
        return SupporterDecision(
            "PLAY", HILDA, "SP-HILDA-OPEN", 900.0,
            "Hilda fix-now over Lillie dig",
        )

    if (
        (phase.primary == "OPENING" or not phase.opening_complete)
        and _in_hand(hand, CRISPIN)
        and board.staryu_on_field
        and not board.active_has_water
    ):
        return SupporterDecision(
            "PLAY", CRISPIN, "SP-CRIS-OPEN", 890.0,
            "Crispin water gap over Lillie dig",
        )

    # Post-Mega: gap-driven supporters only (no "spend the slot every turn").
    # Priorities sit below HR-6 attack (975) unless the card closes a real gap.
    # Bare HARVEST without ever opening must not steal the OPENING path window.
    post_mega = bool(phase.opening_complete)
    if post_mega:
        need_froslass_engine = not board.froslass_104_on_field or not board.active_is_mega_froslass
        if _in_hand(hand, HILDA) and need_froslass_engine:
            return SupporterDecision(
                "PLAY", HILDA, "SP-HILDA-SF", 960.0,
                "Hilda — Mega Froslass / 104 after Starmie online",
            )
        if (
            _in_hand(hand, CRISPIN)
            and board.munkidori_on_field
            and not board.munkidori_has_dark
        ):
            return SupporterDecision(
                "PLAY", CRISPIN, "SP-CRIS-SF", 955.0,
                "Crispin — dark for Munkidori engine",
            )
        if (
            _in_hand(hand, CRISPIN)
            and not board.munkidori_on_field
            and (
                board.snorunt_line_on_bench
                or board.froslass_104_on_field
                or board.active_id == SNORUNT
            )
        ):
            return SupporterDecision(
                "PLAY", CRISPIN, "SP-CRIS-SF2", 940.0,
                "Crispin — energy while Froslass engine builds",
            )

    lillie = lillie_priority(board, phase, hand, resources)
    if lillie and lillie.action == "PLAY":
        return lillie
    # FORBID Lillie must NOT early-return — other supporters may still play.
    # Layer1 still hard-bans the Lillie card itself via lillie_forbidden.

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

    # No SP-FALLBACK / SP-JUDGE-SF / forced post-Mega Lillie — holding is fine.

    return SupporterDecision(
        "HOLD", None, "SP-HOLD", 0.0,
        f"deck={resources.deck_count}, Lillie left={resources.lillie_left}, "
        f"66 left={resources.dudunsparce_66_left}",
    )


__all__ = [
    "SupporterDecision",
    "pick_supporter",
    "lillie_forbidden",
    "lillie_should_play",
    "lillie_priority",
    "build_hand_context_from_obs",
]
