"""Wave Q probe (failed G0) — documents mega_clock −PATH plateau; fix rolled back.

See logs/h2h_audit_waveQ_mega_clock/AUTOPSY.md and
logs/diagnose_seatB_no_mega/DIAGNOSE.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, OptionType
from opening_cards import (
    BOSS_ORDERS,
    DUNSPARCE_A,
    LILLIE,
    MEGA_STARMIE,
    MUNKIDORI,
    NIGHT_STRETCHER,
    STARYU,
)
import starmie_pilot as sp

DARK = 7


def _pkm(cid, hp=70, **kw):
    return NS(id=cid, hp=hp, maxHp=hp, energies=[], **kw)


def _player(*, active=None, bench=(), hand=()):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=c) for c in hand],
        discard=[],
        prize=[None] * 6,
        prizeCount=6,
        handCount=len(hand),
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs_gs(me, opp, *, turn=2):
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


def _game45_hand():
    return (BOSS_ORDERS, BOSS_ORDERS, NIGHT_STRETCHER, MEGA_STARMIE, LILLIE, DARK)


def test_monitor_plateau_when_facts_true_without_evolve_option():
    """Known hazard under Wave L: facts can_evolve + no EVOLVE → flat −PATH."""
    hand = _game45_hand()
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(MUNKIDORI, hp=110), bench=[_pkm(STARYU)])
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(NS(type=OptionType.END))
    obs = _obs_gs(me, opp)
    sit = sp._compute_situation(obs)
    sit["select_options"] = opts
    assert sit["turn_plan"].facts.staryu_can_evolve
    # Current policy still trusts facts → mega_legal True even without EVOLVE.
    assert sp._mega_evolve_legal_now(obs, sit, sit["board"], sit["turn_plan"])
    boss = NS(type=OptionType.PLAY, index=0)
    assert sp._mega_clock_hard_bonus(obs, boss, sit) <= -sp._DOMINATE_OPEN_PATH
    lillie = NS(type=OptionType.PLAY, index=4)
    assert sp._mega_clock_hard_bonus(obs, lillie, sit) <= -sp._DOMINATE_OPEN_PATH


def test_evolve_option_still_owns_turn():
    hand = _game45_hand()
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(MUNKIDORI, hp=110), bench=[_pkm(STARYU)])
    evo = NS(type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=3)
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(evo)
    obs = _obs_gs(me, opp)
    sit = sp._compute_situation(obs)
    sit["select_options"] = opts
    assert sp._hard_rule_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) <= -sp._DOMINATE_OPEN_PATH


@pytest.mark.skip(reason="Wave Q option-ground fix rolled back after G0 red (AUTOPSY)")
def test_q_fix_rolled_back_lillie_beats_plateau():
    hand = _game45_hand()
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(MUNKIDORI, hp=110), bench=[_pkm(STARYU)])
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(NS(type=OptionType.END))
    obs = _obs_gs(me, opp)
    sit = sp._compute_situation(obs)
    sit["select_options"] = opts
    assert not sp._mega_evolve_legal_now(obs, sit, sit["board"], sit["turn_plan"])
