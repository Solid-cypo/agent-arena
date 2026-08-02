"""Epoch schedulers for Starmie → Froslass dual-attacker.

Epoch 1 (until usable Mega Starmie Active):
  G1 → RETREAT → G2 → G3 → EVOLVE → DONE
  RETREAT = promote usable Mega(+water) from Bench only (never unevolved Staryu).

Epoch 2 (after opening success, while AGGRESSION — build Froslass engine):
  SF1 (Snorunt line) → SF2 (Froslass 104) → SF3 (Munk + Dark) → SF_DONE

Mega Froslass ex (861) evolve/attack stays in HARVEST hard-rules (HR-8/H*).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from opening_cards import (
    BUDEW,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUDUNSPARCE_EX,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    FROSLASS,
    HILDA,
    IGNITION,
    LILLIE,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    POFFIN,
    POKE_PAD,
    PRISM,
    SNORUNT,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
)

PriorityGap = Literal[
    "G1", "RETREAT", "G2", "G3", "EVOLVE", "DONE",
    "SF1", "SF2", "SF3", "SF_DONE",
]

# Tags used by Layer1 matchers (not engine option kinds).
KIND_PLAY_STARYU = "PLAY_STARYU"
KIND_PLAY_POFFIN = "PLAY_POFFIN"
KIND_PLAY_PAD = "PLAY_POKE_PAD"
KIND_PLAY_UB = "PLAY_ULTRA_BALL"
KIND_PLAY_HILDA = "PLAY_HILDA"
KIND_PLAY_CRISPIN = "PLAY_CRISPIN"
KIND_PLAY_MEOWTH = "PLAY_MEOWTH"
KIND_PLAY_SWITCH = "PLAY_SWITCH"
KIND_PLAY_LILLIE = "PLAY_LILLIE"
KIND_PLAY_SNORUNT = "PLAY_SNORUNT"
KIND_PLAY_MUNK = "PLAY_MUNKIDORI"
KIND_ATTACH_WATER_LINE = "ATTACH_WATER_LINE"
KIND_ATTACH_RETREAT = "ATTACH_RETREAT"
KIND_ATTACH_MUNK_DARK = "ATTACH_MUNK_DARK"
KIND_EVOLVE_MEGA = "EVOLVE_MEGA_STARMIE"
KIND_EVOLVE_FROSLASS = "EVOLVE_FROSLASS_104"
KIND_EVOLVE_MEGA_FROSLASS = "EVOLVE_MEGA_FROSLASS"
KIND_ABILITY_MEOWTH = "ABILITY_LAST_DITCH"
KIND_SEARCH_MEGA = "SEARCH_MEGA_STARMIE"
KIND_SEARCH_STARYU = "SEARCH_STARYU"
KIND_SEARCH_SNORUNT = "SEARCH_SNORUNT"
KIND_SEARCH_SWITCH = "SEARCH_SWITCH"
KIND_SEARCH_FROSLASS = "SEARCH_FROSLASS_104"
KIND_SEARCH_FROSLASS_MEGA = "SEARCH_MEGA_FROSLASS"
KIND_SEARCH_D66 = "SEARCH_DUDUNSPARCE"
KIND_DEMOTE_SIDE = "DEMOTE_SIDE_BASIC"
KIND_DEMOTE_POFFIN = "DEMOTE_POFFIN"
KIND_DEMOTE_306 = "DEMOTE_306"
KIND_DEMOTE_BOSS = "DEMOTE_BOSS"

SF_GAP_ORDER: tuple[str, ...] = ("SF1", "SF2", "SF3", "SF_DONE")

# S-strategy (2026-08-01): 861 is insurance/surplus. The pilot refreshes this
# flag every decision (_mega_froslass_window_open); while False the scheduler
# treats SF2 as cleared and drives SF3 (DP set) instead.
_MEGA_FROSLASS_WINDOW_OPEN = True


def set_mega_froslass_window(open_: bool) -> None:
    global _MEGA_FROSLASS_WINDOW_OPEN
    _MEGA_FROSLASS_WINDOW_OPEN = bool(open_)

_SIDE_BASICS = frozenset({
    BUDEW,
    SNORUNT,
    DUNSPARCE_A,
    DUNSPARCE_B,
    MUNKIDORI,
    MEOWTH_EX,
    FAN_ROTOM,
})


@dataclass(frozen=True)
class EpochPlan:
    epoch_id: int
    priority_gap: PriorityGap
    preferred_kinds: tuple[str, ...] = ()
    demote_kinds: tuple[str, ...] = ()
    reason: str = ""


def _hand_has(hand_ids: list[int], *cids: int) -> bool:
    return any(c in hand_ids for c in cids)


def _want_dual_basic_snorunt(board: Any, hand_ids: list[int]) -> bool:
    """After Staryu/Mega is online: prefer a second Basic (Snorunt) for T2 options.

    Investment (water / Mega evolve / Mega search) stays on the Starmie line;
    this only unlocks bench/search preference for Snorunt.
    """
    staryu_on = bool(getattr(board, "staryu_on_field", False))
    mega_on = bool(getattr(board, "mega_starmie_on_field", False))
    if not (staryu_on or mega_on):
        return False
    if bool(getattr(board, "snorunt_line_on_bench", False)):
        return False
    if bool(getattr(board, "froslass_104_on_field", False)):
        return False
    if int(getattr(board, "bench_open", 0) or 0) <= 0 and SNORUNT not in hand_ids:
        # Still allow SEARCH_SNORUNT even if bench full? Skip if no space to place.
        return False
    if int(getattr(board, "bench_open", 0) or 0) <= 0:
        return False
    return True


def _append_dual_basic_prefs(prefs: list[str], board: Any, hand_ids: list[int]) -> None:
    if not _want_dual_basic_snorunt(board, hand_ids):
        return
    if SNORUNT in hand_ids:
        prefs.append(KIND_PLAY_SNORUNT)
    prefs.append(KIND_SEARCH_SNORUNT)


def _build_gap_plan(
    gap: str,
    board: Any,
    hand: Any,
    *,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
) -> EpochPlan | None:
    """Full EpochPlan for a forced gap (preferred+demote always matched). None if illegal."""
    hand_ids = list(getattr(hand, "hand_ids", None) or [])
    mega_on = bool(getattr(board, "mega_starmie_on_field", False))
    staryu_on = bool(getattr(board, "staryu_on_field", False))
    active_id = int(getattr(board, "active_id", 0) or 0)
    mega_in_hand = MEGA_STARMIE in hand_ids
    # Promote only when usable Mega(+water) sits on Bench — never unevolved Staryu.
    bench_mega_water = bool(getattr(board, "bench_mega_starmie_has_water", False))
    if not bench_mega_water:
        # Fallback for callers without the board flag: line water + Mega on field.
        bench_mega_water = bool(mega_on and line_has_water and active_id != MEGA_STARMIE)
    mega_bench_blocked = bench_mega_water and active_id != MEGA_STARMIE

    if gap == "DONE":
        return EpochPlan(1, "DONE", reason="usable Mega Starmie active")

    if gap == "G1":
        if staryu_on or mega_on:
            return None
        prefs: list[str] = []
        if STARYU in hand_ids:
            prefs.append(KIND_PLAY_STARYU)
        if POFFIN in hand_ids:
            prefs.append(KIND_PLAY_POFFIN)
        if POKE_PAD in hand_ids:
            prefs.append(KIND_PLAY_PAD)
        if ULTRA_BALL in hand_ids:
            prefs.append(KIND_PLAY_UB)
        prefs.append(KIND_SEARCH_STARYU)
        if LILLIE in hand_ids and not _hand_has(
            hand_ids, POFFIN, POKE_PAD, ULTRA_BALL, HILDA, CRISPIN
        ):
            prefs.append(KIND_PLAY_LILLIE)
        return EpochPlan(
            1,
            "G1",
            preferred_kinds=tuple(prefs),
            demote_kinds=(KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS, KIND_DEMOTE_306),
            reason="need Staryu on field",
        )

    if gap == "RETREAT":
        if not mega_bench_blocked:
            return None
        return EpochPlan(
            1,
            "RETREAT",
            preferred_kinds=(KIND_PLAY_SWITCH, KIND_ATTACH_RETREAT),
            demote_kinds=(KIND_DEMOTE_POFFIN, KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS),
            reason="bring Mega Starmie (+water) to Active",
        )

    if gap == "G2":
        if not ((staryu_on or mega_on) and not line_has_water):
            return None
        prefs_g2: list[str] = [KIND_ATTACH_WATER_LINE]
        if HILDA in hand_ids:
            prefs_g2.append(KIND_PLAY_HILDA)
        if CRISPIN in hand_ids:
            prefs_g2.append(KIND_PLAY_CRISPIN)
        if ULTRA_BALL in hand_ids:
            prefs_g2.append(KIND_PLAY_UB)
        if POKE_PAD in hand_ids:
            prefs_g2.append(KIND_PLAY_PAD)
        prefs_g2.append(KIND_ABILITY_MEOWTH)
        if LILLIE in hand_ids:
            prefs_g2.append(KIND_PLAY_LILLIE)
        # Dual-basic: after Staryu online, soft-prefer Snorunt bench (below water attach).
        _append_dual_basic_prefs(prefs_g2, board, hand_ids)
        return EpochPlan(
            1,
            "G2",
            preferred_kinds=tuple(prefs_g2),
            demote_kinds=(KIND_DEMOTE_POFFIN, KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS),
            reason="line needs water energy (+ dual-basic Snorunt if free)",
        )

    if gap == "G3":
        if mega_on or mega_in_hand:
            return None
        if not (staryu_on or mega_on):
            return None
        prefs: list[str] = []
        if HILDA in hand_ids:
            prefs.append(KIND_PLAY_HILDA)
        if ULTRA_BALL in hand_ids:
            prefs.append(KIND_PLAY_UB)
        if CRISPIN in hand_ids:
            prefs.append(KIND_PLAY_CRISPIN)
        if MEOWTH_EX in hand_ids:
            prefs.append(KIND_PLAY_MEOWTH)
        prefs.append(KIND_ABILITY_MEOWTH)
        prefs.append(KIND_SEARCH_MEGA)
        if staryu_on and line_has_water:
            prefs.append(KIND_EVOLVE_MEGA)
        if LILLIE in hand_ids:
            prefs.append(KIND_PLAY_LILLIE)
        _append_dual_basic_prefs(prefs, board, hand_ids)
        return EpochPlan(
            1,
            "G3",
            preferred_kinds=tuple(prefs),
            demote_kinds=(KIND_DEMOTE_POFFIN, KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS, KIND_DEMOTE_306),
            reason="need Mega Starmie in hand (+ dual-basic Snorunt if free)",
        )

    if gap == "EVOLVE":
        if not (staryu_on and (mega_in_hand or mega_on)):
            return None
        prefs_ev: list[str] = [KIND_EVOLVE_MEGA, KIND_ATTACH_WATER_LINE]
        # Switch only after Mega is already on field — never before evolve.
        if mega_on:
            prefs_ev.append(KIND_PLAY_SWITCH)
        _append_dual_basic_prefs(prefs_ev, board, hand_ids)
        return EpochPlan(
            1,
            "EVOLVE",
            preferred_kinds=tuple(prefs_ev),
            demote_kinds=(KIND_DEMOTE_POFFIN, KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS),
            reason="evolve Staryu → Mega (+ dual-basic Snorunt if free)",
        )

    return None


def _plan_epoch1_instant(
    board: Any,
    hand: Any,
    resources: Any,
    *,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
) -> EpochPlan:
    """Instantaneous epoch-1 gap from board (no cross-turn memory)."""
    del resources  # reserved for future deck-count gates
    active_mega_water = bool(
        getattr(board, "active_is_mega_starmie", False)
        and getattr(board, "active_has_water", False)
    )
    if active_mega_water:
        return EpochPlan(1, "DONE", reason="usable Mega Starmie active")

    mega_on = bool(getattr(board, "mega_starmie_on_field", False))
    active_id = int(getattr(board, "active_id", 0) or 0)
    bench_mega_water = bool(getattr(board, "bench_mega_starmie_has_water", False))
    if not bench_mega_water:
        bench_mega_water = bool(mega_on and line_has_water and active_id != MEGA_STARMIE)
    if bench_mega_water and active_id != MEGA_STARMIE:
        plan = _build_gap_plan(
            "RETREAT",
            board,
            hand,
            active_can_retreat=active_can_retreat,
            line_has_water=line_has_water,
        )
        if plan:
            return plan

    for gap in ("G1", "RETREAT", "G2", "G3", "EVOLVE"):
        plan = _build_gap_plan(
            gap,
            board,
            hand,
            active_can_retreat=active_can_retreat,
            line_has_water=line_has_water,
        )
        if plan:
            return plan

    return EpochPlan(
        1,
        "G3",
        preferred_kinds=(KIND_PLAY_HILDA, KIND_PLAY_UB, KIND_PLAY_LILLIE, KIND_SEARCH_MEGA),
        demote_kinds=(KIND_DEMOTE_POFFIN, KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS),
        reason="fallback toward Mega",
    )


GAP_ORDER: tuple[PriorityGap, ...] = ("G1", "RETREAT", "G2", "G3", "EVOLVE", "DONE")


def _gap_index(gap: str) -> int:
    """Index within the active epoch's gap order (epoch1 or SF)."""
    if gap in SF_GAP_ORDER:
        try:
            return SF_GAP_ORDER.index(gap)
        except ValueError:
            return 0
    try:
        return GAP_ORDER.index(gap)  # type: ignore[arg-type]
    except ValueError:
        return 0


def default_epoch_memory() -> dict[str, Any]:
    return {
        "epoch_id": 1,
        "deadline_turn": 3,
        "last_my_turn": 0,
        "cleared_gaps": [],
        "last_priority_gap": None,
        "this_turn_task": None,
        "turn_started_gap": None,
    }


def _opening_done(board: Any, opening_complete_flag: bool = False) -> bool:
    return bool(opening_complete_flag) or (
        bool(getattr(board, "active_is_mega_starmie", False))
        and bool(getattr(board, "active_has_water", False))
    )


def compute_cleared_gaps(
    board: Any,
    hand: Any,
    *,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
    opening_complete_flag: bool = False,
) -> list[str]:
    """Gaps already satisfied on the current board (epoch-1 order)."""
    hand_ids = list(getattr(hand, "hand_ids", None) or [])
    mega_on = bool(getattr(board, "mega_starmie_on_field", False))
    staryu_on = bool(getattr(board, "staryu_on_field", False))
    active_id = int(getattr(board, "active_id", 0) or 0)
    mega_in_hand = MEGA_STARMIE in hand_ids
    cleared: list[str] = []

    # Opening complete → epoch-1 gaps are all cleared (caller switches to SF).
    if _opening_done(board, opening_complete_flag):
        return list(GAP_ORDER)

    if staryu_on or mega_on:
        cleared.append("G1")

    # RETREAT uncleared only when usable Mega(+water) sits on bench.
    # Unevolved bench Staryu must NOT keep RETREAT open — evolve first.
    _ = active_can_retreat
    bench_mega_water = bool(getattr(board, "bench_mega_starmie_has_water", False))
    if not bench_mega_water:
        bench_mega_water = bool(mega_on and line_has_water and active_id != MEGA_STARMIE)
    mega_bench_blocked = bench_mega_water and active_id != MEGA_STARMIE
    if not mega_bench_blocked:
        cleared.append("RETREAT")

    if (staryu_on or mega_on) and line_has_water:
        cleared.append("G2")

    if mega_on or mega_in_hand:
        cleared.append("G3")

    if mega_on:
        cleared.append("EVOLVE")

    return cleared


def compute_cleared_gaps_epoch2(
    board: Any, *, mega_froslass_window_open: bool = True,
) -> list[str]:
    """SF gaps already satisfied (Froslass engine setup).

    SF2 clears on Mega Froslass (861) — engine evolves 861 from Snorunt, not 104.
    S-strategy (2026-08-01, tightened): while the 861 window is closed (Mega
    Starmie healthy — DP completion no longer opens it), SF2 is treated as
    cleared so the scheduler drives SF3 (DP set) instead of digging 861.
    """
    snorunt_line = bool(getattr(board, "snorunt_line_on_bench", False))
    snorunt_on = bool(getattr(board, "snorunt_on_field", False))
    fro104 = bool(getattr(board, "froslass_104_on_field", False))
    mega_f = bool(getattr(board, "mega_froslass_on_field", False))
    active_id = int(getattr(board, "active_id", 0) or 0)
    if active_id == SNORUNT or snorunt_on:
        snorunt_line = True
    if active_id == MEGA_FROSLASS:
        mega_f = True
    munk_on = bool(getattr(board, "munkidori_on_field", False))
    munk_dark = bool(getattr(board, "munkidori_has_dark", False))

    cleared: list[str] = []
    # SF1: any Snorunt-line piece on field (Snorunt / 104 / 861).
    if snorunt_line or fro104 or mega_f:
        cleared.append("SF1")
    # SF2: Mega Froslass online — or its window closed (insurance only).
    if mega_f or not mega_froslass_window_open:
        cleared.append("SF2")
    if munk_on and munk_dark:
        cleared.append("SF3")
    return cleared


def next_turn_task(cleared: list[str] | set[str]) -> PriorityGap:
    cset = set(cleared)
    for g in GAP_ORDER:
        if g == "DONE":
            continue
        if g not in cset:
            return g
    return "DONE"


def next_sf_task(cleared: list[str] | set[str]) -> PriorityGap:
    cset = set(cleared)
    for g in SF_GAP_ORDER:
        if g == "SF_DONE":
            continue
        if g not in cset:
            return g  # type: ignore[return-value]
    return "SF_DONE"


def _sticky_advance_task(
    memory: dict[str, Any],
    board: Any,
    task: str,
) -> None:
    """Advance-only this_turn_task within a my-turn (shared epoch1/2)."""
    mt = int(getattr(board, "my_turn_number", 0) or 0)
    if mt != int(memory.get("last_my_turn") or 0):
        memory["last_priority_gap"] = memory.get("this_turn_task")
        memory["last_my_turn"] = mt
        memory["turn_started_gap"] = task
        memory["this_turn_task"] = task
    else:
        old = memory.get("this_turn_task") or task
        # Only compare within the same gap family.
        same_family = (
            (str(old) in SF_GAP_ORDER and task in SF_GAP_ORDER)
            or (str(old) in GAP_ORDER and task in GAP_ORDER)
        )
        if not same_family or _gap_index(task) >= _gap_index(str(old)):
            memory["this_turn_task"] = task


def refresh_epoch_memory(
    memory: dict[str, Any],
    board: Any,
    hand: Any,
    *,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
    opening_complete_flag: bool = False,
    mega_froslass_window_open: bool | None = None,
) -> dict[str, Any]:
    """Update cleared gaps + this_turn_task (advance-only within a my-turn)."""
    if not memory:
        memory = default_epoch_memory()
    if mega_froslass_window_open is None:
        mega_froslass_window_open = _MEGA_FROSLASS_WINDOW_OPEN

    if _opening_done(board, opening_complete_flag):
        memory["epoch_id"] = 2
        cleared = compute_cleared_gaps_epoch2(
            board, mega_froslass_window_open=mega_froslass_window_open,
        )
        memory["cleared_gaps"] = cleared
        task = next_sf_task(cleared)
        _sticky_advance_task(memory, board, task)
        return memory

    cleared = compute_cleared_gaps(
        board,
        hand,
        active_can_retreat=active_can_retreat,
        line_has_water=line_has_water,
        opening_complete_flag=False,
    )
    memory["cleared_gaps"] = cleared
    task = next_turn_task(cleared)
    _sticky_advance_task(memory, board, task)
    memory["epoch_id"] = 1
    return memory


def _task_drive_enabled() -> bool:
    """Production default ON: Layer1 scores from this_turn_task full plan.

    Set EPOCH_TASK_DRIVE=0 to fall back to annotate-only (instant plan + label).
    """
    import os

    return os.environ.get("EPOCH_TASK_DRIVE", "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def plan_epoch1(
    board: Any,
    hand: Any,
    resources: Any,
    *,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
    memory: dict[str, Any] | None = None,
) -> EpochPlan:
    """Compute epoch-1 gap; optionally drive scoring from this_turn_task.

    Driven mode (default): build a *full* EpochPlan for ``this_turn_task`` via
    ``_build_gap_plan`` so preferred_kinds and demote_kinds always match.
    If the board requires an earlier gap, trust the instantaneous plan.
    """
    instant = _plan_epoch1_instant(
        board,
        hand,
        resources,
        active_can_retreat=active_can_retreat,
        line_has_water=line_has_water,
    )
    if not memory or not memory.get("this_turn_task"):
        return instant

    task = str(memory.get("this_turn_task"))
    if task == "DONE" or instant.priority_gap == "DONE":
        return instant

    if not _task_drive_enabled():
        return EpochPlan(
            instant.epoch_id,
            instant.priority_gap,
            preferred_kinds=instant.preferred_kinds,
            demote_kinds=instant.demote_kinds,
            reason=f"{instant.reason} [task:{task}]",
        )

    cleared = set(memory.get("cleared_gaps") or [])
    if task in cleared:
        return instant

    # Board needs an earlier gap than sticky task → never skip (e.g. retreat).
    if _gap_index(instant.priority_gap) < _gap_index(task):
        return instant

    forced = _build_gap_plan(
        task,
        board,
        hand,
        active_can_retreat=active_can_retreat,
        line_has_water=line_has_water,
    )
    if forced is None:
        return instant

    return EpochPlan(
        forced.epoch_id,
        forced.priority_gap,
        preferred_kinds=forced.preferred_kinds,
        demote_kinds=forced.demote_kinds,
        reason=f"{forced.reason} [driven:{task}]",
    )


def _build_sf_gap_plan(gap: str, board: Any, hand: Any) -> EpochPlan | None:
    """Full EpochPlan for a forced SF gap. None if gap already cleared."""
    hand_ids = list(getattr(hand, "hand_ids", None) or [])
    snorunt_line = bool(getattr(board, "snorunt_line_on_bench", False))
    fro104 = bool(getattr(board, "froslass_104_on_field", False))
    active_id = int(getattr(board, "active_id", 0) or 0)
    if active_id == SNORUNT:
        snorunt_line = True
    munk_on = bool(getattr(board, "munkidori_on_field", False))
    munk_dark = bool(getattr(board, "munkidori_has_dark", False))
    bench_open = int(getattr(board, "bench_open", 0) or 0)

    if gap == "SF_DONE":
        return EpochPlan(
            2,
            "SF_DONE",
            preferred_kinds=(),
            demote_kinds=(),
            reason="Froslass engine ready — defer to AGGRESSION/HARVEST HRs",
        )

    if gap == "SF1":
        if snorunt_line or fro104:
            return None
        prefs: list[str] = []
        if SNORUNT in hand_ids and bench_open > 0:
            prefs.append(KIND_PLAY_SNORUNT)
        if POFFIN in hand_ids and bench_open > 0:
            prefs.append(KIND_PLAY_POFFIN)
        if POKE_PAD in hand_ids:
            prefs.append(KIND_PLAY_PAD)
        if ULTRA_BALL in hand_ids:
            prefs.append(KIND_PLAY_UB)
        prefs.append(KIND_SEARCH_SNORUNT)
        if HILDA in hand_ids:
            prefs.append(KIND_PLAY_HILDA)
        if LILLIE in hand_ids:
            prefs.append(KIND_PLAY_LILLIE)
        return EpochPlan(
            2,
            "SF1",
            preferred_kinds=tuple(prefs),
            demote_kinds=(KIND_DEMOTE_SIDE, KIND_DEMOTE_BOSS, KIND_DEMOTE_306),
            reason="need Snorunt on bench for Froslass line",
        )

    if gap == "SF2":
        mega_f_on = bool(getattr(board, "mega_froslass_on_field", False))
        if mega_f_on or active_id == MEGA_FROSLASS:
            return None
        has_mega_f = MEGA_FROSLASS in hand_ids
        snorunt_on = snorunt_line or active_id == SNORUNT or bool(
            getattr(board, "snorunt_on_field", False)
        )
        # Primary: Snorunt → Mega Froslass (engine never evolves 861 onto 104).
        if has_mega_f and snorunt_on:
            prefs_861: list[str] = [KIND_EVOLVE_MEGA_FROSLASS]
            if HILDA in hand_ids:
                prefs_861.append(KIND_PLAY_HILDA)
            return EpochPlan(
                2,
                "SF2",
                preferred_kinds=tuple(prefs_861),
                demote_kinds=(
                    KIND_DEMOTE_BOSS,
                    KIND_DEMOTE_306,
                    KIND_DEMOTE_POFFIN,
                    KIND_EVOLVE_FROSLASS,  # don't spend Snorunt on 104
                ),
                reason="evolve Snorunt → Mega Froslass ex (861)",
            )
        if not snorunt_on:
            prefs_sf2_fetch: list[str] = [
                KIND_SEARCH_SNORUNT,
                KIND_SEARCH_FROSLASS_MEGA,
            ]
            if SNORUNT in hand_ids and bench_open > 0:
                prefs_sf2_fetch.insert(0, KIND_PLAY_SNORUNT)
            if HILDA in hand_ids:
                prefs_sf2_fetch.insert(0, KIND_PLAY_HILDA)
            if POFFIN in hand_ids and bench_open > 0:
                prefs_sf2_fetch.append(KIND_PLAY_POFFIN)
            if POKE_PAD in hand_ids:
                prefs_sf2_fetch.append(KIND_PLAY_PAD)
            if ULTRA_BALL in hand_ids:
                prefs_sf2_fetch.append(KIND_PLAY_UB)
            return EpochPlan(
                2,
                "SF2",
                preferred_kinds=tuple(prefs_sf2_fetch),
                demote_kinds=(KIND_DEMOTE_BOSS, KIND_DEMOTE_306),
                reason="need Snorunt then evolve to Mega Froslass 861",
            )
        # Snorunt online, 861 not in hand — dig 861 (104 evolve only as last resort).
        prefs_sf2: list[str] = [
            KIND_SEARCH_FROSLASS_MEGA,
            KIND_EVOLVE_FROSLASS,
            KIND_SEARCH_FROSLASS,
        ]
        if HILDA in hand_ids:
            prefs_sf2.insert(0, KIND_PLAY_HILDA)
        if POKE_PAD in hand_ids:
            prefs_sf2.append(KIND_PLAY_PAD)
        if ULTRA_BALL in hand_ids:
            prefs_sf2.append(KIND_PLAY_UB)
        if LILLIE in hand_ids:
            prefs_sf2.append(KIND_PLAY_LILLIE)
        return EpochPlan(
            2,
            "SF2",
            preferred_kinds=tuple(prefs_sf2),
            demote_kinds=(KIND_DEMOTE_BOSS, KIND_DEMOTE_306, KIND_DEMOTE_POFFIN),
            reason="search Mega Froslass / evolve line from Snorunt",
        )

    if gap == "SF3":
        if munk_on and munk_dark:
            return None
        prefs_sf3: list[str] = []
        if not munk_on:
            if MUNKIDORI in hand_ids and bench_open > 0:
                prefs_sf3.append(KIND_PLAY_MUNK)
            if POKE_PAD in hand_ids:
                prefs_sf3.append(KIND_PLAY_PAD)
            if ULTRA_BALL in hand_ids:
                prefs_sf3.append(KIND_PLAY_UB)
            if POFFIN in hand_ids and bench_open > 0:
                prefs_sf3.append(KIND_PLAY_POFFIN)
        if munk_on and not munk_dark:
            prefs_sf3.append(KIND_ATTACH_MUNK_DARK)
            if CRISPIN in hand_ids:
                prefs_sf3.append(KIND_PLAY_CRISPIN)
            if HILDA in hand_ids:
                prefs_sf3.append(KIND_PLAY_HILDA)
        if HILDA in hand_ids and KIND_PLAY_HILDA not in prefs_sf3:
            prefs_sf3.append(KIND_PLAY_HILDA)
        if LILLIE in hand_ids:
            prefs_sf3.append(KIND_PLAY_LILLIE)
        if not prefs_sf3:
            prefs_sf3 = [KIND_PLAY_MUNK, KIND_ATTACH_MUNK_DARK]
        return EpochPlan(
            2,
            "SF3",
            preferred_kinds=tuple(prefs_sf3),
            demote_kinds=(KIND_DEMOTE_BOSS, KIND_DEMOTE_306),
            reason="need Munkidori with Dark for Adrena-Brain",
        )

    return None


def _plan_epoch2_instant(board: Any, hand: Any) -> EpochPlan:
    cleared = compute_cleared_gaps_epoch2(board)
    task = next_sf_task(cleared)
    if task == "SF_DONE":
        return EpochPlan(
            2,
            "SF_DONE",
            preferred_kinds=(),
            demote_kinds=(),
            reason="Froslass engine ready — defer to AGGRESSION/HARVEST HRs",
        )
    forced = _build_sf_gap_plan(task, board, hand)
    if forced is not None:
        return forced
    # Cleared set lag — advance.
    return EpochPlan(
        2,
        "SF_DONE",
        preferred_kinds=(),
        demote_kinds=(),
        reason="SF gap cleared mid-plan",
    )


def plan_epoch2(
    board: Any,
    hand: Any,
    resources: Any,
    *,
    memory: dict[str, Any] | None = None,
) -> EpochPlan:
    """Epoch-2 Froslass engine: SF1→SF2→SF3→SF_DONE (+ task-drive)."""
    del resources  # reserved for deck-left fetch bias later
    instant = _plan_epoch2_instant(board, hand)
    if not memory or not memory.get("this_turn_task"):
        return instant

    task = str(memory.get("this_turn_task"))
    if task not in SF_GAP_ORDER:
        return instant
    if task == "SF_DONE" or instant.priority_gap == "SF_DONE":
        return instant

    if not _task_drive_enabled():
        return EpochPlan(
            instant.epoch_id,
            instant.priority_gap,
            preferred_kinds=instant.preferred_kinds,
            demote_kinds=instant.demote_kinds,
            reason=f"{instant.reason} [task:{task}]",
        )

    cleared = set(memory.get("cleared_gaps") or [])
    if task in cleared:
        return instant

    if _gap_index(instant.priority_gap) < _gap_index(task):
        return instant

    forced = _build_sf_gap_plan(task, board, hand)
    if forced is None:
        return instant

    return EpochPlan(
        forced.epoch_id,
        forced.priority_gap,
        preferred_kinds=forced.preferred_kinds,
        demote_kinds=forced.demote_kinds,
        reason=f"{forced.reason} [driven:{task}]",
    )


def plan_epoch(
    board: Any,
    hand: Any,
    resources: Any,
    *,
    opening_complete_flag: bool,
    active_can_retreat: bool = True,
    line_has_water: bool = False,
    memory: dict[str, Any] | None = None,
) -> EpochPlan:
    """Top-level: epoch 1 until opening complete; then epoch-2 Froslass engine."""
    if _opening_done(board, opening_complete_flag):
        return plan_epoch2(board, hand, resources, memory=memory)
    return plan_epoch1(
        board,
        hand,
        resources,
        active_can_retreat=active_can_retreat,
        line_has_water=line_has_water,
        memory=memory,
    )


def search_card_tag(cid: int) -> str | None:
    if cid == MEGA_STARMIE:
        return KIND_SEARCH_MEGA
    if cid == STARYU:
        return KIND_SEARCH_STARYU
    if cid == SNORUNT:
        return KIND_SEARCH_SNORUNT
    if cid == SWITCH:
        return KIND_SEARCH_SWITCH
    if cid == FROSLASS:
        return KIND_SEARCH_FROSLASS
    if cid == MEGA_FROSLASS:
        return KIND_SEARCH_FROSLASS_MEGA
    if cid == DUDUNSPARCE:
        return KIND_SEARCH_D66
    if cid == DUDUNSPARCE_EX:
        return KIND_DEMOTE_306
    return None


def is_side_basic(cid: int) -> bool:
    return cid in _SIDE_BASICS


def retreat_attach_energy_ok(eid: int) -> bool:
    """Energies allowed as Active retreat oil under E1/E2 (not for Staryu).

    Production deck is Water+Dark only; Ignition/Prism kept for legacy hands.
    """
    return eid in (DARK_BASIC, IGNITION, WATER_BASIC, PRISM)


def tags_match_preferred(tags: set[str] | frozenset[str], preferred: tuple[str, ...]) -> bool:
    return bool(tags.intersection(preferred))


def tags_match_demote(tags: set[str] | frozenset[str], demote: tuple[str, ...]) -> bool:
    return bool(tags.intersection(demote))
