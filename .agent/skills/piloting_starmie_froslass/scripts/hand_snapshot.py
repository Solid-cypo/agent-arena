"""Board/hand snapshot for phase FSM and pilot hard rules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opening_cards import (
    DARK_BASIC,
    FAN_ROTOM,
    FROSLASS,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MUNKIDORI,
    PRISM,
    RISKY_RUINS,
    SNORUNT,
    STARYU,
    WATER_BASIC,
)

_SNORUNT_LINE = frozenset({SNORUNT, FROSLASS})
_WATER_IDS = frozenset({WATER_BASIC, PRISM})
_DARK_IDS = frozenset({DARK_BASIC, PRISM})


def _si(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def my_turn_number(turn: int, first_player: int, my_index: int) -> int:
    """1 = My-T1, 2 = My-T2, 0 = setup or opponent turn."""
    if turn <= 0:
        return 0
    if my_index == first_player:
        return (turn + 1) // 2
    return turn // 2


def _pokemon_ids(player) -> list[int]:
    ids: list[int] = []
    try:
        active = (player.active or [None])[0]
        if active:
            ids.append(_si(getattr(active, "id", None)))
        for p in player.bench or []:
            if p:
                ids.append(_si(getattr(p, "id", None)))
    except Exception:
        pass
    return ids


def _has_energy(pokemon, allowed: frozenset[int]) -> bool:
    if pokemon is None:
        return False
    try:
        for e in getattr(pokemon, "energies", None) or []:
            if _si(e) in allowed:
                return True
    except Exception:
        pass
    return False


def _find_on_bench(player, card_id: int):
    try:
        for p in player.bench or []:
            if p and _si(getattr(p, "id", None)) == card_id:
                return p
    except Exception:
        pass
    return None


@dataclass
class BoardSnapshot:
    turn: int
    first_player: int
    my_index: int
    my_turn_number: int
    prize_self: int
    prize_opp: int
    hand_size: int
    bench_count: int
    bench_open: int
    active_id: int
    active_has_water: bool
    active_is_mega_starmie: bool
    active_is_mega_froslass: bool
    staryu_on_field: bool
    mega_starmie_on_field: bool
    bench_mega_starmie_has_water: bool
    snorunt_line_on_bench: bool
    snorunt_on_field: bool
    froslass_104_on_field: bool
    mega_froslass_on_field: bool
    munkidori_on_bench: bool
    munkidori_on_field: bool
    munkidori_has_dark: bool
    bench_three_core_ready: bool
    fan_rotom_on_field: bool
    fan_rotom_dead: bool
    risky_ruins_online: bool = False


def build_board_snapshot(obs) -> BoardSnapshot:
    turn = _si(getattr(obs.current, "turn", None))
    mi = _si(getattr(obs.current, "yourIndex", None))
    fp = _si(getattr(obs.current, "firstPlayer", None), mi)
    me = obs.current.players[mi]

    active = (me.active or [None])[0]
    active_id = _si(getattr(active, "id", None)) if active else 0
    field_ids = _pokemon_ids(me)
    bench = [p for p in (me.bench or []) if p]
    bench_ids = [_si(getattr(p, "id", None)) for p in bench]

    # Active Snorunt counts — Mega Froslass evolves from Snorunt (not 104).
    snorunt_line = any(cid in _SNORUNT_LINE for cid in field_ids)
    fro104_on = FROSLASS in field_ids
    mega_f_on = MEGA_FROSLASS in field_ids
    munk_bench = _find_on_bench(me, MUNKIDORI)
    munk_on_bench = munk_bench is not None
    munk = munk_bench
    if active_id == MUNKIDORI:
        munk = active
    munk_on_field = munk is not None
    munk_dark = _has_energy(munk, _DARK_IDS) if munk else False

    prize_self = len(me.prize or []) or _si(getattr(me, "prizeCount", None), 6)
    prize_opp = len(obs.current.players[1 - mi].prize or []) or _si(
        getattr(obs.current.players[1 - mi], "prizeCount", None), 6
    )

    my_t = my_turn_number(turn, fp, mi)
    fan_on = FAN_ROTOM in field_ids
    bench_mega_water = any(
        _si(getattr(p, "id", None)) == MEGA_STARMIE and _has_energy(p, _WATER_IDS)
        for p in bench
    )
    stadium_ids = {
        _si(getattr(card, "id", None))
        for card in (getattr(obs.current, "stadium", None) or [])
        if card
    }

    return BoardSnapshot(
        turn=turn,
        first_player=fp,
        my_index=mi,
        my_turn_number=my_t,
        prize_self=prize_self,
        prize_opp=prize_opp,
        hand_size=len(me.hand or []),
        bench_count=len(bench),
        bench_open=max(0, 5 - len(bench)),
        active_id=active_id,
        active_has_water=_has_energy(active, _WATER_IDS),
        active_is_mega_starmie=active_id == MEGA_STARMIE,
        active_is_mega_froslass=active_id == MEGA_FROSLASS,
        staryu_on_field=STARYU in field_ids,
        mega_starmie_on_field=MEGA_STARMIE in field_ids,
        bench_mega_starmie_has_water=bench_mega_water,
        snorunt_line_on_bench=snorunt_line,
        snorunt_on_field=SNORUNT in field_ids,
        froslass_104_on_field=fro104_on,
        mega_froslass_on_field=mega_f_on,
        munkidori_on_bench=munk_on_bench,
        munkidori_on_field=munk_on_field,
        munkidori_has_dark=munk_dark,
        bench_three_core_ready=snorunt_line and munk_on_field,
        fan_rotom_on_field=fan_on,
        fan_rotom_dead=my_t >= 2 and not fan_on,
        risky_ruins_online=RISKY_RUINS in stadium_ids,
    )
