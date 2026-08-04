"""Mega land gate: Lillie ban + Hilda priority when base + water path ready."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from deck_resources import DeckResourceSnapshot, HandContext, load_deck_template
from hand_snapshot import BoardSnapshot
from opening_cards import (
    CRISPIN,
    LILLIE,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    STARYU,
    WATER_BASIC,
    hilda_evolution_priority,
    mega_ready_to_land,
)
from phase_fsm import PhaseState
from supporter_planner import lillie_forbidden


def _board(**kw) -> BoardSnapshot:
    defaults = dict(
        turn=5, first_player=0, my_index=0, my_turn_number=2,
        prize_self=6, prize_opp=6, hand_size=4,
        bench_count=1, bench_open=4, active_id=STARYU,
        active_has_water=True, active_is_mega_starmie=False,
        active_is_mega_froslass=False, staryu_on_field=True,
        mega_starmie_on_field=False, bench_mega_starmie_has_water=False,
        snorunt_line_on_bench=False, snorunt_on_field=False,
        mega_froslass_on_field=False,
        froslass_104_on_field=False, munkidori_on_bench=False,
        munkidori_on_field=False, munkidori_has_dark=False,
        bench_three_core_ready=False, fan_rotom_on_field=False,
        fan_rotom_dead=False, line_has_water=True,
    )
    defaults.update(kw)
    return BoardSnapshot(**defaults)


def _hand(**kw) -> HandContext:
    defaults = dict(
        hand_ids=[LILLIE, MEGA_STARMIE], hand_size=2, supporter_played=False,
        energy_attached=False, has_boss=False, has_lillie=True,
        has_crispin=False, gust_target_on_opp_bench=False,
    )
    defaults.update(kw)
    return HandContext(**defaults)


def _resources(**kw) -> DeckResourceSnapshot:
    template = Counter(load_deck_template())
    remaining = Counter(template)
    defaults = dict(
        template=template, seen=Counter(), remaining=remaining,
        deck_count=40, prize_count=6, discard_count=0,
    )
    defaults.update(kw)
    return DeckResourceSnapshot(**defaults)


def test_lillie_forbidden_when_ready_and_mega_in_hand():
    board = _board(line_has_water=True, active_has_water=True)
    hand = _hand(hand_ids=[LILLIE, MEGA_STARMIE], hand_size=2)
    forbidden, rule = lillie_forbidden(board, PhaseState("OPENING", False, False), hand, _resources())
    assert forbidden and rule == "DR-MEGA-LAND"


def test_lillie_allowed_when_dry_no_fetch():
    board = _board(line_has_water=False, active_has_water=False)
    hand = _hand(hand_ids=[LILLIE, MEGA_STARMIE], hand_size=2, has_crispin=False)
    forbidden, rule = lillie_forbidden(board, PhaseState("OPENING", False, False), hand, _resources())
    assert not forbidden, rule


def test_lillie_forbidden_when_crispin_provides_water_path():
    board = _board(line_has_water=False, active_has_water=False)
    hand = _hand(
        hand_ids=[LILLIE, MEGA_STARMIE, CRISPIN],
        hand_size=3,
        has_crispin=True,
    )
    assert mega_ready_to_land(
        staryu_on_field=True,
        mega_starmie_on_field=False,
        line_has_water=False,
        hand_ids=hand.hand_ids,
        supporter_played=False,
    )
    forbidden, rule = lillie_forbidden(board, PhaseState("OPENING", False, False), hand, _resources())
    # Crispin may trip DR-FIX-NOW first; either ban still blocks washing Mega.
    assert forbidden and rule in ("DR-MEGA-LAND", "DR-FIX-NOW")


def test_hilda_priority_ready_locks_mega():
    prio = hilda_evolution_priority(mega_ready=True)
    assert prio[0] == MEGA_STARMIE


def test_hilda_priority_not_ready_demotes_mega():
    prio = hilda_evolution_priority(mega_ready=False)
    assert prio[0] not in (MEGA_STARMIE, MEGA_FROSLASS)
    assert prio[-1] == MEGA_FROSLASS
    assert MEGA_STARMIE in prio


def test_mega_ready_predicate_hand_water():
    assert mega_ready_to_land(
        staryu_on_field=True,
        mega_starmie_on_field=False,
        line_has_water=False,
        hand_ids=[WATER_BASIC, MEGA_STARMIE],
        supporter_played=False,
    )
    assert not mega_ready_to_land(
        staryu_on_field=True,
        mega_starmie_on_field=False,
        line_has_water=False,
        hand_ids=[MEGA_STARMIE],
        supporter_played=False,
    )
