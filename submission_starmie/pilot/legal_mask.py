"""Shared OPENING legal-mask predicates (train + inference).

Single source of truth for structural legality. Training
(``action_space_v2``) and Kaggle inference (``rl_opening_proposer``) must
import from here — do not re-copy the predicates.

Optional ``view['offered_ability_srcs']`` (set[int] | None): when populated by
the live engine, ABILITY_* kinds are only legal if that source is offered.
Training/sim leave it unset (None) → state-only legality.
"""
from __future__ import annotations

from typing import Any

from opening_cards import (
    BASIC_IDS,
    BOSS_ORDERS,
    CRISPIN,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    ENERGY_IDS,
    FAN_ROTOM,
    HILDA,
    ITEM_IDS,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    SALVATOR,
    STARYU,
    SUPPORTER_IDS,
    SWITCH,
    ULTRA_BALL,
    WALLYS_COMPASSION,
    can_retreat_pokemon,
    supporter_blocked_going_first_t1,
)

NON_POLICY_KINDS = frozenset({"DRAW", "SETUP_ACTIVE", "SETUP_BENCH"})

_SUPPORTER_KIND_TO_ID = {
    "PLAY_HILDA": HILDA,
    "PLAY_CRISPIN": CRISPIN,
    "PLAY_SALVATOR": SALVATOR,
    "PLAY_LILLIE": LILLIE,
    "PLAY_JUDGE": JUDGE,
    "PLAY_BOSS": BOSS_ORDERS,
    "PLAY_COMPASSION": WALLYS_COMPASSION,
}


def is_legal_kind(kind: str, primary: int | None, v: dict[str, Any]) -> bool:
    """Return True iff (kind, primary) is structurally legal under view ``v``."""
    hand = v["hand"]
    bench_ids = v["bench_ids"]
    active_id = v["active_id"]
    sup = v["supporter_played"]
    ea = v["energy_attached"]
    offered = v.get("offered_ability_srcs")

    def offered_ok(src: int) -> bool:
        return offered is None or src in offered

    if kind in NON_POLICY_KINDS:
        return False

    if kind == "PLAY_POKEMON":
        return primary in BASIC_IDS and primary in hand and len(bench_ids) < 5

    if kind == "ATTACH":
        return (
            primary in ENERGY_IDS
            and primary in hand
            and not ea
            and (active_id is not None or bool(bench_ids))
        )

    if kind == "EVOLVE":
        ev = [(active_id, v["active_can_evolve"])] + list(
            zip(bench_ids, v["bench_can_evolve"])
        )
        if primary == MEGA_STARMIE:
            return MEGA_STARMIE in hand and any(
                pid == STARYU and can for pid, can in ev
            )
        if primary == DUDUNSPARCE:
            return DUDUNSPARCE in hand and any(
                pid in (DUNSPARCE_A, DUNSPARCE_B) and can for pid, can in ev
            )
        return False

    if kind == "PLAY_POFFIN":
        return POFFIN in hand and len(bench_ids) < 5

    if kind == "PLAY_ULTRA_BALL":
        return ULTRA_BALL in hand and sum(1 for c in hand if c != ULTRA_BALL) >= 2

    if kind in _SUPPORTER_KIND_TO_ID:
        if supporter_blocked_going_first_t1(
            going_first=bool(v.get("going_first", False)),
            my_turn_number=int(v.get("my_turn_number", 2) or 2),
        ):
            return False
        return _SUPPORTER_KIND_TO_ID[kind] in hand and not sup

    if kind == "PLAY_POKE_PAD":
        return POKE_PAD in hand and len(bench_ids) < 5

    if kind == "PLAY_NIGHT_STRETCHER":
        return NIGHT_STRETCHER in hand

    if kind == "PLAY_SWITCH":
        return SWITCH in hand and MEGA_STARMIE in bench_ids

    if kind == "PLAY_SUPPORTER":
        if supporter_blocked_going_first_t1(
            going_first=bool(v.get("going_first", False)),
            my_turn_number=int(v.get("my_turn_number", 2) or 2),
        ):
            return False
        return primary in SUPPORTER_IDS and primary in hand and not sup

    if kind == "PLAY_ITEM":
        return primary in ITEM_IDS and primary in hand

    if kind == "ABILITY_FAN_CALL":
        on_field = active_id == FAN_ROTOM or FAN_ROTOM in bench_ids
        return on_field and not v["fan_call_used"] and offered_ok(FAN_ROTOM)

    if kind == "ABILITY_LAST_DITCH":
        # Engine: ability only while Meowth ex is ON FIELD (not hand-only).
        meowth_on_field = active_id == MEOWTH_EX or MEOWTH_EX in bench_ids
        return meowth_on_field and not sup and offered_ok(MEOWTH_EX)

    if kind == "ABILITY_RUN_AWAY":
        on_field = active_id == DUDUNSPARCE or DUDUNSPARCE in bench_ids
        return on_field and offered_ok(DUDUNSPARCE)

    if kind == "RETREAT":
        if not bench_ids:
            return False
        if active_id is not None:
            return can_retreat_pokemon(active_id, v["active_energies"])
        return True

    return False
