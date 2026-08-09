"""Going-second: ground EVOLUTION, seat Staryu after Mega dig, T2 Closing."""
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
    DUNSPARCE_A,
    HILDA,
    MEGA_STARMIE,
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


def _obs_gs(*, me, opp, turn=2):
    """Going-second: firstPlayer=1, yourIndex=0."""
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


def test_ground_fake_evolution_to_wait_when_no_evolve_option():
    """Facts can_evolve but MAIN list has no Mega EVOLVE → WAIT, not fake Closing."""
    hand = (MEGA_STARMIE, BUDEW, HILDA)
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(NS(type=OptionType.END))
    sit["select_options"] = opts
    assert sit["turn_plan"].facts.staryu_can_evolve
    assert sp._plan_primary_step(sit["turn_plan"], obs, sit) == "WAIT_EVOLVE"
    # END allowed under WAIT freeze; Budew banned.
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.END), sit) >= sp._DOMINATE_MID
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=1), sit) <= sp._ATTACH_ILLEGAL


def test_gs_seat_bans_end_paths_staryu_when_mega_held():
    """Mega in hand, no Staryu on field → must seat; END illegal."""
    hand = (MEGA_STARMIE, STARYU, SNORUNT, HILDA)
    me = _player(
        active=_pkm(DUNSPARCE_A),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    opts = [NS(type=OptionType.PLAY, index=i) for i in range(len(hand))]
    opts.append(NS(type=OptionType.END))
    sit["select_options"] = opts

    play_sty = NS(type=OptionType.PLAY, index=1)
    play_snorunt = NS(type=OptionType.PLAY, index=2)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play_sty, sit) >= sp._DOMINATE_OPEN_PATH - 1
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, play_snorunt, sit) <= sp._ATTACH_ILLEGAL


def test_gs_t2_deadline_closes_when_evolve_offered():
    hand = (MEGA_STARMIE, HILDA, WATER_BASIC)
    me = _player(
        active=_pkm(STARYU, canEvolve=True, energies=[NS(id=WATER_BASIC)]),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    # my_turn_number comes from board snapshot; turn=4 GS → my turns progressed
    obs = _obs_gs(me=me, opp=opp, turn=4)
    sit = sp._compute_situation(obs)
    assert int(getattr(sit["board"], "my_turn_number", 0) or 0) >= 2

    mega_evo = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    hilda = NS(type=OptionType.PLAY, index=1)
    end = NS(type=OptionType.END)
    sit["select_options"] = [
        NS(type=OptionType.PLAY, index=0),
        NS(type=OptionType.PLAY, index=1),
        NS(type=OptionType.PLAY, index=2),
        mega_evo,
        end,
    ]
    assert sp._gs_t2_evolve_deadline_bonus(obs, mega_evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, mega_evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, hilda, sit) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL


def test_ground_offers_evolution_when_evolve_in_list():
    hand = (MEGA_STARMIE, HILDA)
    me = _player(
        active=_pkm(STARYU, canEvolve=True),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs_gs(me=me, opp=opp, turn=4)
    sit = sp._compute_situation(obs)
    mega_evo = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    sit["select_options"] = [
        NS(type=OptionType.PLAY, index=0),
        NS(type=OptionType.PLAY, index=1),
        mega_evo,
        NS(type=OptionType.END),
    ]
    assert sp._plan_primary_step(sit["turn_plan"], obs, sit) == "EVOLUTION"
