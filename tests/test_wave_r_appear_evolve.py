"""Wave R probe (failed G0) — appearThisTurn facts fix re-landed for 92356962.

Same-turn summoning-sick Staryu must not claim staryu_can_evolve (Ball Mega dig).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hand_snapshot import build_board_snapshot
from opening_cards import MEGA_STARMIE, STARYU, WATER_BASIC
from turn_planner import build_turn_plan


def _pkm(cid, hp=70, **kw):
    return NS(id=cid, hp=hp, maxHp=hp, energies=list(kw.pop("energies", ())), **kw)


def _player(*, active=None, hand=()):
    return NS(
        active=[active] if active else [],
        bench=[],
        hand=[NS(id=c) for c in hand],
        discard=[],
        prize=[None] * 6,
        prizeCount=6,
        handCount=len(hand),
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs(me, *, turn=4):
    opp = _player(active=_pkm(999, hp=200))
    return NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=1,
            stadium=[],
            players=[me, opp],
        ),
        select=NS(context=0, deck=[], option=[]),
    )


def test_monitor_appear_blocks_evolvable():
    """appearThisTurn=True must not claim staryu_can_evolve (92356962)."""
    me = _player(
        active=_pkm(STARYU, appearThisTurn=True, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE,),
    )
    plan = build_turn_plan(_obs(me), build_board_snapshot(_obs(me)))
    assert plan.facts.staryu_can_evolve is False


def test_r_appear_blocks_evolve_facts():
    me = _player(
        active=_pkm(STARYU, appearThisTurn=True, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE,),
    )
    plan = build_turn_plan(_obs(me), build_board_snapshot(_obs(me)))
    assert plan.facts.staryu_can_evolve is False
