"""OPENING seat preset: attacker-base×1 · Dunsparce×2 · Munk×1 · flex×1."""
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
from opening_bench import BENCH_ROLE_CAPS, can_bench_card
from opening_cards import (
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    HILDA,
    MEGA_STARMIE,
    MUNKIDORI,
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


def _obs(*, me, opp, turn=2, first_player=0):
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


def test_bench_role_caps_match_preset():
    assert BENCH_ROLE_CAPS == {
        "attacker_base": 1,
        "dunsparce": 2,
        "munk": 1,
        "flex": 1,
    }
    assert can_bench_card(STARYU, [], 5, DUNSPARCE_A)
    assert can_bench_card(STARYU, [DUNSPARCE_A], 4, DUNSPARCE_B)
    assert not can_bench_card(STARYU, [DUNSPARCE_A, DUNSPARCE_B], 3, DUNSPARCE_A)
    assert can_bench_card(STARYU, [DUNSPARCE_A], 4, MUNKIDORI)
    assert not can_bench_card(STARYU, [MUNKIDORI], 4, MUNKIDORI)


def test_hand_dunsparce_paths_over_end():
    hand = (DUNSPARCE_A, HILDA, WATER_BASIC)
    me = _player(active=_pkm(STARYU), hand=hand)
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_MID
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL


def test_second_dunsparce_allowed_under_cap():
    hand = (DUNSPARCE_B, HILDA)
    me = _player(
        active=_pkm(STARYU),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=3)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, play, sit) > -sp._DOMINATE_OPEN_PATH


def test_bench_duns_hand_66_evolves():
    hand = (DUDUNSPARCE, HILDA)
    me = _player(
        active=_pkm(STARYU),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    evo66 = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    end = NS(type=OptionType.END)
    obs = _obs(me=me, opp=opp, turn=3)
    sit = sp._compute_situation(obs)
    sit["select_options"] = [
        NS(type=OptionType.PLAY, index=0),
        NS(type=OptionType.PLAY, index=1),
        evo66,
        end,
    ]
    assert sp._hard_rule_bonus(obs, evo66, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) < 0


def test_hand_munk_benches_after_staryu():
    hand = (MUNKIDORI, HILDA, WATER_BASIC)
    me = _player(active=_pkm(STARYU), hand=hand)
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_MID
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL


def test_wait_evolve_fills_dunsparce_over_end():
    """Sick window: hand Dunsparce must beat blank END."""
    hand = (MEGA_STARMIE, DUNSPARCE_A, HILDA)
    me = _player(
        active=_pkm(STARYU, canEvolve=False),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "WAIT_EVOLVE"
    play = NS(type=OptionType.PLAY, index=1)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN - 30.0
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL
