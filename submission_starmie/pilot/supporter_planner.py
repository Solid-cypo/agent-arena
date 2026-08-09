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
    MEGA_STARMIE,
    POFFIN,
    POKE_PAD,
    SNORUNT,
    STARYU,
    UNFAIR_STAMP,
    WALLYS_COMPASSION,
    mega_ready_to_land,
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
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext | None = None,
    *,
    turn_plan=None,
) -> bool:
    """Effective-Boss gate: only allow Boss when TurnPlan expects a prize
    advance (or DoubleKO needs a front swap), or when closing (≤2 prizes).

    ``zero_boss`` is no longer optimized; empty-slot / sole-supporter Boss is
    not a reason to play an ineffective gust.
    """
    if board.prize_self <= 2:
        return True
    if turn_plan is not None:
        combat = getattr(turn_plan, "combat", None)
        if combat is not None:
            if getattr(combat, "boss_target", None) is not None:
                return True
            if int(getattr(combat, "expected_prize_delta", 0) or 0) > 0:
                return True
            # TurnPlan evaluated this turn and rejected Boss — do not soft-open.
            if getattr(combat, "attack_required", False):
                return False
    if not getattr(phase, "opening_complete", False):
        return False
    dp_ready = (
        board.froslass_104_on_field
        or getattr(board, "mega_froslass_on_field", False)
    ) and board.munkidori_on_field
    if dp_ready and hand is not None and getattr(hand, "gust_target_koable", False):
        # Engine ready + immediate KO-able gust (legacy soft path without plan).
        return True
    if hand is not None and getattr(hand, "gust_target_koable", False):
        # Without TurnPlan, keep KO-able gust as the only soft open.
        return True
    return False


def _plan_missing_n(turn_plan) -> int:
    if turn_plan is None:
        return 0
    try:
        from turn_planner import count_missing_types

        return count_missing_types(turn_plan.facts, turn_plan.gap)
    except Exception:
        return 0


def _plan_force_draw(turn_plan) -> bool:
    if turn_plan is None:
        return False
    try:
        from turn_planner import must_prioritize_draw

        return must_prioritize_draw(turn_plan.facts, turn_plan.gap, turn_plan.combat)
    except Exception:
        return False


def _plan_uncoverable(turn_plan) -> tuple[str, ...]:
    if turn_plan is None:
        return ()
    try:
        from turn_planner import item_uncoverable_gaps

        return item_uncoverable_gaps(turn_plan.facts, turn_plan.gap)
    except Exception:
        return ()


def _fix_now_supporter(
    hand: HandContext,
    board: BoardSnapshot,
    phase: PhaseState | None = None,
    *,
    turn_plan=None,
) -> int | None:
    """Return a supporter that immediately advances the board (prefer over Lillie).

    When TurnPlan forces dig (n≥3 missing types), only Boss (effective) or a
    supporter that clearly closes one typed gap beats Lillie.
    """
    force_dig = _plan_force_draw(turn_plan)
    if (
        hand.has_boss
        and hand.gust_target_on_opp_bench
        and _in_hand(hand, BOSS_ORDERS)
        and (
            phase is None
            or _boss_ok(board, phase, hand, turn_plan=turn_plan)
        )
    ):
        return BOSS_ORDERS
    # Hilda closes EVOLUTION (+energy) only — never BASE (E-HILDA-1/2).
    # Crispin closes ENERGY only (two different Basic Energies).
    if not board.active_is_mega_starmie or not board.active_has_water:
        staryu_online = bool(board.staryu_on_field or board.mega_starmie_on_field)
        if (
            _in_hand(hand, HILDA)
            and staryu_online
            and not board.mega_starmie_on_field
        ):
            # G3: Staryu seated, need Mega (+ optional Water) — Hilda is legal.
            return HILDA
        if _in_hand(hand, CRISPIN) and (
            (board.staryu_on_field and not board.active_has_water)
            or (board.munkidori_on_bench and not board.munkidori_has_dark)
        ):
            return CRISPIN
    if force_dig:
        # No misc supporter beats the dig mandate.
        return None
    return None


def lillie_forbidden(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    turn_plan=None,
) -> tuple[bool, str]:
    """Hard bans only — OPENING / hand-size / first-aggression are no longer bans."""
    # Prefer effective Boss gust over washing the hand with Lillie.
    if (
        hand.has_boss
        and hand.gust_target_on_opp_bench
        and _boss_ok(board, phase, hand, turn_plan=turn_plan)
    ):
        return True, "DR-5"

    # Typed fix-now (Hilda/Crispin/Boss) beats dig. Under n≥3 forced dig, only
    # those typed closers still suppress Lillie; otherwise dig wins.
    fix = _fix_now_supporter(hand, board, phase, turn_plan=turn_plan)
    if fix is not None:
        return True, "DR-FIX-NOW"

    if resources.exhausted(LILLIE) and LILLIE not in hand.hand_ids:
        return True, "DR-1b"

    # Mega land gate: do not wash Mega when base + water path can land it now.
    if MEGA_STARMIE in hand.hand_ids and mega_ready_to_land(
        staryu_on_field=board.staryu_on_field,
        mega_starmie_on_field=board.mega_starmie_on_field,
        line_has_water=bool(getattr(board, "line_has_water", False)),
        hand_ids=hand.hand_ids,
        supporter_played=hand.supporter_played,
    ):
        return True, "DR-MEGA-LAND"

    # OpsOrder: seating item that can find+bench a needed basic beats shuffle-redraw.
    if (
        int(getattr(board, "bench_open", 0) or 0) > 0
        and (POFFIN in hand.hand_ids or POKE_PAD in hand.hand_ids)
    ):
        gap = getattr(turn_plan, "gap", None) if turn_plan is not None else None
        need_base = bool(getattr(gap, "need_base", False))
        if need_base or (
            not board.staryu_on_field and STARYU not in hand.hand_ids
        ):
            return True, "DR-SETUP-ITEM"

    # OpsMid-V1: Staryu already in hand — seat before wash.
    if (
        STARYU in hand.hand_ids
        and not board.staryu_on_field
        and not board.mega_starmie_on_field
        and int(getattr(board, "bench_open", 0) or 0) > 0
    ):
        return True, "DR-SEAT-BASE"

    return False, ""


def lillie_should_play(
    board: BoardSnapshot,
    phase: PhaseState,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    *,
    turn_plan=None,
) -> bool:
    """Gap-driven PLAY gate (positive path).

    Draw-7 ≈ two typed targets. n≥3 → must dig; n==1 allowed when items cannot
    close the last element; prefer uncoverable gaps.
    """
    if not _in_hand(hand, LILLIE):
        return False
    forbidden, _ = lillie_forbidden(board, phase, hand, resources, turn_plan=turn_plan)
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

    n_miss = _plan_missing_n(turn_plan)
    if _plan_force_draw(turn_plan) or n_miss >= 3:
        return True
    if n_miss == 1 and _plan_uncoverable(turn_plan):
        return True
    if n_miss == 1:
        # One element shy of the goal — dig allowed even if item-coverable.
        return True
    if n_miss == 2 and _plan_uncoverable(turn_plan):
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
    *,
    turn_plan=None,
) -> SupporterDecision | None:
    if not _in_hand(hand, LILLIE):
        return None

    forbidden, rule = lillie_forbidden(
        board, phase, hand, resources, turn_plan=turn_plan,
    )
    if forbidden:
        return SupporterDecision("FORBID", LILLIE, rule, 0.0, f"Lillie forbidden ({rule})")

    if not lillie_should_play(
        board, phase, hand, resources, turn_plan=turn_plan,
    ):
        return None

    priority = 800.0
    n_miss = _plan_missing_n(turn_plan)
    if _plan_force_draw(turn_plan) or n_miss >= 3:
        return SupporterDecision(
            "PLAY", LILLIE, "DR-3GAP", priority + 80.0,
            f"n_missing_types={n_miss}≥3 → dig first (draw-7≈2 types)",
        )
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
    turn_plan=None,
) -> SupporterDecision | None:
    if hand.supporter_played:
        return None

    # E-SUP-1 handled per-card; OPENING no longer blank-returns.

    if (
        hand.has_boss
        and hand.gust_target_on_opp_bench
        and _in_hand(hand, BOSS_ORDERS)
        and _boss_ok(board, phase, hand, turn_plan=turn_plan)
    ):
        return SupporterDecision(
            "PLAY", BOSS_ORDERS, "SP-BOSS-1", 950.0,
            f"effective Boss gust — boss unseen left={resources.boss_left}",
        )

    if harvest_ko_last_turn and _in_hand(hand, UNFAIR_STAMP) and phase.primary == "HARVEST":
        return SupporterDecision(
            "PLAY", UNFAIR_STAMP, "DR-6", 920.0,
            "Unfair Stamp after KO — refill us to 5 / opp to 2",
        )

    # n≥3 missing types: dig before soft openers, unless a typed closer is in hand.
    force_dig = _plan_force_draw(turn_plan)
    typed_closer = _fix_now_supporter(hand, board, phase, turn_plan=turn_plan)
    if force_dig and typed_closer is None and _in_hand(hand, LILLIE):
        lillie_forced = lillie_priority(
            board, phase, hand, resources, turn_plan=turn_plan,
        )
        if lillie_forced and lillie_forced.action == "PLAY":
            return lillie_forced

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

    # Soft-prefer Hilda only when Staryu is online and Mega is still missing
    # (E-HILDA-2: G1 must not spend the slot on an evolution-only searcher).
    if (
        (phase.primary == "OPENING" or not phase.opening_complete)
        and _in_hand(hand, HILDA)
        and board.staryu_on_field
        and not board.mega_starmie_on_field
        and not (force_dig and typed_closer is None)
    ):
        return SupporterDecision(
            "PLAY", HILDA, "SP-HILDA-OPEN", 900.0,
            "Hilda evo+energy over Lillie dig",
        )

    if (
        (phase.primary == "OPENING" or not phase.opening_complete)
        and _in_hand(hand, CRISPIN)
        and board.staryu_on_field
        and not board.active_has_water
        and not (force_dig and typed_closer is None)
    ):
        return SupporterDecision(
            "PLAY", CRISPIN, "SP-CRIS-OPEN", 890.0,
            "Crispin water gap over Lillie dig",
        )

    # Post-Mega: gap-driven supporters only (no "spend the slot every turn").
    # Priorities sit below HR-6 attack (975) unless the card closes a real gap.
    # Bare HARVEST without ever opening must not steal the OPENING path window.
    post_mega = bool(phase.opening_complete)
    if post_mega and not (force_dig and typed_closer is None):
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

    lillie = lillie_priority(board, phase, hand, resources, turn_plan=turn_plan)
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
