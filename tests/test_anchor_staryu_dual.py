"""Anchor Staryu wall + dual-Staryu OPENING seat."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, OptionType, SelectContext
from opening_cards import (
    CRISPIN,
    DUNSPARCE_A,
    MEGA_STARMIE,
    SNORUNT,
    STARYU,
    SWITCH,
    WATER_BASIC,
)
import starmie_pilot as sp


def _pkm(cid, hp=70, energies=None, **kw):
    return NS(id=cid, hp=hp, maxHp=hp, energies=list(energies or []), **kw)


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


def _obs_gs(me, opp, *, turn=2, ctx=0):
    return NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=1,
            stadium=[],
            players=[me, opp],
        ),
        select=NS(context=ctx, deck=[], option=[]),
    )


def test_anchor_bans_switch_off_staryu_with_mega_in_hand():
    """game_001/021/161 symptom: Active Staryu + Mega → never cut away."""
    hand = (MEGA_STARMIE, SWITCH, WATER_BASIC, CRISPIN)
    me = _player(
        active=_pkm(STARYU, canEvolve=True, energies=[NS(id=WATER_BASIC)]),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me, opp)
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, index=1)  # SWITCH
    assert sp._hard_rule_bonus(obs, switch, sit) <= sp._ATTACH_ILLEGAL
    evo = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(evo)
    sit["select_options"] = opts
    assert sp._hard_rule_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH


def test_anchor_bans_selecting_dunsparce_over_staryu():
    hand = (MEGA_STARMIE, SWITCH)
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me, opp, ctx=int(SelectContext.SWITCH))
    sit = sp._compute_situation(obs)
    pick_duns = NS(
        type=OptionType.CARD,
        playerIndex=0,
        area=AreaType.BENCH,
        index=0,
    )
    assert sp._hard_rule_bonus(obs, pick_duns, sit) <= sp._ATTACH_ILLEGAL


def test_dual_staryu_paths_second_staryu_in_opening():
    hand = (STARYU, SNORUNT)
    me = _player(
        active=_pkm(DUNSPARCE_A),
        bench=[_pkm(STARYU)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me, opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "OPENING"
    play_sty = NS(type=OptionType.PLAY, index=0)
    play_snorunt = NS(type=OptionType.PLAY, index=1)
    assert sp._dual_staryu_opening_bonus(obs, play_sty, sit) >= sp._DOMINATE_OPEN - 50
    assert sp._dual_staryu_opening_bonus(obs, play_snorunt, sit) == 0.0


def test_count_staryu_on_field():
    me = _player(
        active=_pkm(STARYU),
        bench=[_pkm(STARYU), _pkm(DUNSPARCE_A)],
        hand=(),
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me, opp)
    assert sp._count_staryu_on_field(obs, 0) == 2
