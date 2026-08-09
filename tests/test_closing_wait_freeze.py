"""Closing knife: WAIT_EVOLVE freeze + EVOLUTION exclusive + EVOLVE_66 yield."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, OptionType
from opening_cards import (
    BUDEW,
    CRISPIN,
    DUDUNSPARCE,
    DUNSPARCE_A,
    HILDA,
    MEGA_STARMIE,
    POFFIN,
    SNORUNT,
    STARYU,
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


def _obs(*, me, opp, turn=1, first_player=0):
    return NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=first_player,
            stadium=[],
            players=[me, opp],
        ),
        select=NS(context=0, deck=[], option=[]),
    )


def test_wait_evolve_freezes_budew_and_hilda():
    """Gold T1 sick window: Mega held + Staryu sick → no side-board noise."""
    hand = (MEGA_STARMIE, BUDEW, HILDA, POFFIN, SNORUNT)
    me = _player(
        active=_pkm(STARYU, canEvolve=False),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "WAIT_EVOLVE"

    budew = NS(type=OptionType.PLAY, index=1)
    hilda = NS(type=OptionType.PLAY, index=2)
    snorunt = NS(type=OptionType.PLAY, index=4)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, budew, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, hilda, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, snorunt, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, end, sit) >= sp._DOMINATE_MID


def test_evolution_closing_hard_illegals_non_mega():
    """When Mega evolve is offered, PLAY/END/66 must not compete."""
    hand = (MEGA_STARMIE, DUDUNSPARCE, HILDA, CRISPIN, WATER_BASIC)
    me = _player(
        active=_pkm(STARYU, canEvolve=True, energies=[NS(id=WATER_BASIC)]),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    mega_evo = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    evo66 = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=1,
    )
    hilda = NS(type=OptionType.PLAY, index=2)
    end = NS(type=OptionType.END)
    opts = [
        NS(type=OptionType.PLAY, index=i) for i in range(len(hand))
    ] + [mega_evo, evo66, end]

    obs = _obs(me=me, opp=opp, turn=3, first_player=1)
    sit = sp._compute_situation(obs)
    sit["select_options"] = opts
    assert sp._plan_primary_step(sit["turn_plan"]) == "EVOLUTION"
    assert sp._mega_evolve_option_offered(obs, sit)

    assert sp._hard_rule_bonus(obs, mega_evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, hilda, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, evo66, sit) <= sp._ATTACH_ILLEGAL


def test_knife_a_yields_when_mega_evolve_offered():
    """EVOLVE_66 PATH must not fire ahead of Mega Closing."""
    hand = (MEGA_STARMIE, DUDUNSPARCE, HILDA)
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    mega_evo = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    evo66 = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=1,
    )
    opts = [
        NS(type=OptionType.PLAY, index=i) for i in range(len(hand))
    ] + [mega_evo, evo66]

    obs = _obs(me=me, opp=opp, turn=3, first_player=1)
    sit = sp._compute_situation(obs)
    sit["select_options"] = opts

    mega_s = sp._hard_rule_bonus(obs, mega_evo, sit)
    evo66_s = sp._hard_rule_bonus(obs, evo66, sit)
    assert mega_s >= sp._DOMINATE_OPEN_PATH
    assert evo66_s <= sp._ATTACH_ILLEGAL
    assert mega_s > evo66_s
