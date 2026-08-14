"""Traceable ops fixes for four online autopsies (sub_55473608).

Episodes (Ying Peter):
  92535497 si=12  Hilda brick → fetch 66, not Mega Starmie
  92537402 si=19  Crispin Water → Staryu, not Dunsparce
  92537402 si=21  PLAY Meowth vs END (Last-Ditch despite flex cap)
  92538341 si=65  Ultra Ball 861 over Pad; si=71 no retreat of watered Snorunt
  92546850 si=38  Evolve 66 before Jetting closeout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, EnergyType, OptionType, SelectContext, to_observation_class
import starmie_pilot as sp

US = "Ying Peter"
SUB = ROOT / "data/kaggle_episodes/sub_55473608"
WATER = int(EnergyType.WATER)
DARK = int(EnergyType.DARKNESS)

_NAMES = {
    3: "W", 7: "D", 65: "土龙A", 66: "节节", 104: "104", 112: "猿",
    235: "含羞苞", 860: "雪童", 861: "861", 1030: "海星星", 1031: "Mega海星",
    1071: "喵", 1121: "超球", 1152: "垫板", 1189: "萨瓦托", 1198: "克利芬", 1225: "希尔达",
    1487: "喷水",
}


def _pkm(cid, hp=100, max_hp=None, energies=(), **kw):
    return NS(
        id=cid,
        hp=hp,
        maxHp=max_hp if max_hp is not None else hp,
        energies=list(energies),
        **kw,
    )


def _player(*, active=None, bench=(), hand=(), prizes=6, hand_count=None,
            supporter_played=False, energy_attached=False):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=cid) if isinstance(cid, int) else cid for cid in hand],
        discard=[],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=supporter_played,
        energyAttached=energy_attached,
        deckCount=30,
    )


def _obs(me, opp=None, *, turn=5, my_index=0, first_player=0, ctx=0, deck=(), effect=None):
    opp = opp or _player(active=_pkm(999, hp=200), hand_count=2)
    players = [me, opp] if my_index == 0 else [opp, me]
    return NS(
        current=NS(
            turn=turn,
            yourIndex=my_index,
            firstPlayer=first_player,
            stadium=[],
            players=players,
        ),
        select=NS(
            context=int(ctx),
            deck=list(deck),
            option=[],
            effect=effect,
            contextCard=None,
        ),
    )


def _best(obs, sit):
    opts = list(obs.select.option or [])
    sit["select_options"] = opts
    ranked = []
    for i, o in enumerate(opts):
        sc = float(sp.option_score(obs, o, {}, sit))
        ranked.append((sc, i, o))
    ranked.sort(reverse=True)
    return ranked


def _lab(obs, o, mi):
    t = int(o.type)
    me = obs.current.players[mi]
    if t == int(OptionType.PLAY):
        h = me.hand or []
        i = int(getattr(o, "index", -1))
        cid = int(h[i].id) if 0 <= i < len(h) and h[i] else None
        return f"PLAY {_NAMES.get(cid, cid)}"
    if t == int(OptionType.EVOLVE):
        h = me.hand or []
        i = int(getattr(o, "index", -1))
        cid = int(h[i].id) if 0 <= i < len(h) and h[i] else None
        return f"EVOLVE {_NAMES.get(cid, cid)}"
    if t == int(OptionType.ATTACK):
        aid = int(getattr(o, "attackId", 0) or 0)
        return f"ATK {_NAMES.get(aid, aid)}"
    if t == int(OptionType.END):
        return "END"
    if t == int(OptionType.RETREAT):
        return "RETREAT"
    if t == int(OptionType.CARD):
        idx = int(getattr(o, "index", -1))
        area = int(getattr(o, "area", -1) or -1)
        cid = None
        if area in (int(AreaType.ACTIVE), int(AreaType.BENCH)):
            pkm = sp._pokemon_in_area(
                obs, o.area, idx, int(getattr(o, "playerIndex", mi) or mi),
            )
            cid = int(pkm.id) if pkm else None
        else:
            deck = obs.select.deck or []
            if 0 <= idx < len(deck) and deck[idx]:
                cid = int(deck[idx].id)
            else:
                cid = sp._card_option_id(obs, o, mi) or None
        return f"CARD {_NAMES.get(cid, cid)}"
    if t == int(OptionType.ATTACH):
        return f"ATTACH ipa={getattr(o, 'inPlayArea', None)} ipi={getattr(o, 'inPlayIndex', None)}"
    return f"T{t}"


def _load_frame(eid: int, si: int):
    path = SUB / f"episode-{eid}-replay.json"
    if not path.exists():
        pytest.skip(f"missing replay {path}")
    d = json.loads(path.read_text())
    mi = d["info"]["TeamNames"].index(US)
    obs = to_observation_class(d["steps"][si][mi]["observation"])
    sit = sp._compute_situation(obs, agent_state={})
    sit["select_options"] = list(obs.select.option or [])
    return obs, sit, mi


# ── 92535497 Hilda brick → 66 ───────────────────────────────────────────────

def test_92535497_hilda_si12_fetches_66_not_mega():
    """Brick: only Dunsparce on field. Hilda offered {1031,66,104,861} → 66."""
    obs, sit, mi = _load_frame(92535497, 12)
    ranked = _best(obs, sit)
    assert _lab(obs, ranked[0][2], mi).startswith("CARD 节节"), (
        f"92535497 si=12 expected 66, got {_lab(obs, ranked[0][2], mi)} "
        f"top={[_lab(obs, r[2], mi) for r in ranked[:4]]}"
    )
    mega = [r for r in ranked if "Mega海星" in _lab(obs, r[2], mi)]
    d66 = [r for r in ranked if "节节" in _lab(obs, r[2], mi)]
    assert d66 and mega
    assert d66[0][0] > mega[0][0]


def test_hilda_brick_66_synthetic_bans_1031():
    me = _player(
        active=_pkm(sp._CARDS["dunsparce_a"], hp=60),
        bench=(_pkm(sp._CARDS["dunsparce_a"], hp=60),),
        hand=(sp._CARDS["hilda"],),
    )
    obs = _obs(
        me, turn=3, ctx=SelectContext.TO_HAND,
        deck=(
            NS(id=sp._CARDS["mega_starmie_ex"]),
            NS(id=sp._CARDS["dudunsparce"]),
            NS(id=sp._CARDS["mega_froslass_ex"]),
        ),
        effect=NS(id=sp._CARDS["hilda"]),
    )
    c1031 = NS(type=OptionType.CARD, index=0, area=AreaType.DECK)
    c66 = NS(type=OptionType.CARD, index=1, area=AreaType.DECK)
    c861 = NS(type=OptionType.CARD, index=2, area=AreaType.DECK)
    obs.select.option = [c1031, c66, c861]
    sit = sp._compute_situation(obs)
    sit["select_options"] = [c1031, c66, c861]
    assert sp._hilda_brick_66_live(obs, sit)
    assert sp._hard_rule_bonus(obs, c66, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, c1031, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, c861, sit) <= -sp._DOMINATE_OPEN_PATH


# ── 92537402 Crispin water → Staryu ─────────────────────────────────────────

def test_92537402_crispin_si19_water_to_staryu_not_dunsparce():
    obs, sit, mi = _load_frame(92537402, 19)
    ranked = _best(obs, sit)
    best = ranked[0][2]
    pkm = sp._pokemon_in_area(
        obs, best.area, int(best.index),
        int(getattr(best, "playerIndex", mi) or mi),
    )
    assert pkm is not None
    assert int(pkm.id) == sp._OC_STARYU, (
        f"92537402 si=19 expected Staryu, got {int(pkm.id)} "
        f"lab={_lab(obs, best, mi)}"
    )


def test_crispin_attach_to_water_paths_staryu_bans_dunsparce():
    water = 3
    me = _player(
        active=_pkm(sp._OC_SNORUNT, hp=70),
        bench=(
            _pkm(sp._OC_MUNKIDORI, hp=110),
            _pkm(sp._OC_STARYU, hp=70),
            _pkm(sp._CARDS["dunsparce_a"], hp=60),
        ),
        hand=(sp._OC_MEOWTH_EX,),
        supporter_played=True,
    )
    obs = _obs(me, turn=2, first_player=1, ctx=SelectContext.ATTACH_FROM)
    obs.select.contextCard = NS(id=water)
    obs.select.effect = NS(id=sp.CRISPIN)
    staryu = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0)
    duns = NS(type=OptionType.CARD, area=AreaType.BENCH, index=2, playerIndex=0)
    sit = sp._compute_situation(obs)
    assert sp._dry_attacker_needs_water(obs, 0)
    assert sp._hard_rule_bonus(obs, staryu, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, duns, sit) <= sp._ATTACH_ILLEGAL + 1e-6


# ── 92537402 Meowth Last-Ditch vs END ───────────────────────────────────────

def test_92537402_si21_plays_meowth_not_end():
    obs, sit, mi = _load_frame(92537402, 21)
    ranked = _best(obs, sit)
    assert _lab(obs, ranked[0][2], mi) == "PLAY 喵", (
        f"92537402 si=21 expected PLAY Meowth, got {_lab(obs, ranked[0][2], mi)} "
        f"top={[_lab(obs, r[2], mi) for r in ranked[:4]]}"
    )


def test_meowth_lastditch_paths_over_end_when_flex_full():
    """2 Munk occupy flex; engine still has a seat — PLAY Meowth after Crispin."""
    me = _player(
        active=_pkm(sp._OC_SNORUNT, hp=70),
        bench=(
            _pkm(sp._OC_MUNKIDORI, hp=110),
            _pkm(sp._OC_MUNKIDORI, hp=110),
            _pkm(sp._OC_STARYU, hp=70),
            _pkm(sp._CARDS["dunsparce_a"], hp=60),
        ),
        hand=(sp._OC_MEOWTH_EX,),
        supporter_played=True,
    )
    obs = _obs(me, turn=2, first_player=1, ctx=SelectContext.MAIN)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    obs.select.option = [play, end]
    sit = sp._compute_situation(obs)
    sit["select_options"] = [play, end]
    assert sp._meowth_lastditch_seat_live(obs, sit)
    assert not sp._obs_can_bench_card(obs, 0, sp._OC_MEOWTH_EX)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH


def test_meowth_yields_to_unplayed_crispin():
    me = _player(
        active=_pkm(sp._OC_SNORUNT, hp=70),
        bench=(
            _pkm(sp._OC_MUNKIDORI, hp=110),
            _pkm(sp._OC_STARYU, hp=70),
        ),
        hand=(sp.CRISPIN, sp._OC_MEOWTH_EX),
        supporter_played=False,
    )
    obs = _obs(me, turn=2, first_player=1, ctx=SelectContext.MAIN)
    crispin = NS(type=OptionType.PLAY, index=0)
    meowth = NS(type=OptionType.PLAY, index=1)
    sit = sp._compute_situation(obs)
    sit["select_options"] = [crispin, meowth]
    assert sp._hard_rule_bonus(obs, crispin, sit) > sp._hard_rule_bonus(obs, meowth, sit)


# ── 92538341 behind watered Snorunt ─────────────────────────────────────────

def test_92538341_si65_ultra_ball_beats_pad():
    obs, sit, mi = _load_frame(92538341, 65)
    ranked = _best(obs, sit)
    assert _lab(obs, ranked[0][2], mi) == "PLAY 超球", (
        f"92538341 si=65 expected Ultra Ball, got {_lab(obs, ranked[0][2], mi)} "
        f"top={[_lab(obs, r[2], mi) for r in ranked[:6]]}"
    )


def test_92538341_si71_does_not_retreat_watered_snorunt():
    obs, sit, mi = _load_frame(92538341, 71)
    ranked = _best(obs, sit)
    labs = [_lab(obs, r[2], mi) for r in ranked]
    assert labs[0] != "RETREAT"
    retreat = [r for r in ranked if _lab(obs, r[2], mi) == "RETREAT"]
    ub = [r for r in ranked if _lab(obs, r[2], mi) == "PLAY 超球"]
    assert retreat
    assert retreat[0][0] <= sp._ATTACH_ILLEGAL + 1e-6
    if ub:
        assert ub[0][0] > retreat[0][0]


def test_behind_snorunt_ub_to_hand_picks_861():
    water = WATER
    me = _player(
        active=_pkm(sp._OC_SNORUNT, hp=70, energies=(water,)),
        bench=(_pkm(sp._OC_MUNKIDORI, hp=110),),
        hand=(sp._OC_ULTRA_BALL,),
        prizes=6,
        supporter_played=True,
    )
    opp = _player(active=_pkm(678, hp=340), prizes=4, hand_count=6)
    obs = _obs(
        me, opp, turn=6, first_player=1, ctx=SelectContext.TO_HAND,
        deck=(
            NS(id=sp._OC_STARYU),
            NS(id=sp._CARDS["mega_froslass_ex"]),
            NS(id=sp._CARDS["dudunsparce"]),
        ),
        effect=NS(id=sp._OC_ULTRA_BALL),
    )
    c1030 = NS(type=OptionType.CARD, index=0, area=AreaType.DECK)
    c861 = NS(type=OptionType.CARD, index=1, area=AreaType.DECK)
    c66 = NS(type=OptionType.CARD, index=2, area=AreaType.DECK)
    obs.select.option = [c1030, c861, c66]
    sit = sp._compute_situation(obs)
    sit["select_options"] = [c1030, c861, c66]
    assert sit["prize_self"] > sit["prize_opp"]
    assert sp._behind_watered_snorunt_861_live(obs, sit)
    assert sp._hard_rule_bonus(obs, c861, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, c1030, sit) <= -sp._DOMINATE_OPEN_PATH


# ── 92546850 Evolve 66 before Jetting ───────────────────────────────────────

def test_92546850_si38_evolve_66_before_jetting():
    obs, sit, mi = _load_frame(92546850, 38)
    ranked = _best(obs, sit)
    assert _lab(obs, ranked[0][2], mi) == "EVOLVE 节节", (
        f"92546850 si=38 expected EVOLVE 66, got {_lab(obs, ranked[0][2], mi)} "
        f"top={[_lab(obs, r[2], mi) for r in ranked[:8]]}"
    )
    jet = [r for r in ranked if "喷水" in _lab(obs, r[2], mi)]
    evo = [r for r in ranked if _lab(obs, r[2], mi) == "EVOLVE 节节"]
    assert jet and evo
    assert evo[0][0] > jet[0][0]


def test_evolve66_closeout_synthetic_beats_jetting():
    water = WATER
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], hp=330, energies=(water,)),
        bench=(
            _pkm(sp._OC_SNORUNT, hp=70),
            _pkm(sp._CARDS["dunsparce_a"], hp=60),
        ),
        hand=(sp._CARDS["dudunsparce"], sp._CARDS["mega_froslass_ex"], water),
    )
    obs = _obs(me, turn=4, first_player=1, ctx=SelectContext.MAIN)
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0, inPlayArea=AreaType.BENCH)
    jet = NS(type=OptionType.ATTACK, attackId=1487)
    end = NS(type=OptionType.END)
    obs.select.option = [evo, jet, end]
    sit = sp._compute_situation(obs)
    sit["select_options"] = [evo, jet, end]
    assert sp._fueled_mega_must_attack(sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH


# ── Lucario dry-861 to Active ───────────────────────────────────────────────

def test_92537402_si47_does_not_seat_dry_snorunt():
    """After Starmie KO: TO_ACTIVE must not pick dry Snorunt with 861 in hand."""
    obs, sit, mi = _load_frame(92537402, 47)
    ranked = _best(obs, sit)
    labs = [_lab(obs, r[2], mi) for r in ranked]
    sno = [r for r in ranked if _lab(obs, r[2], mi) == "CARD 雪童"]
    assert sno, f"no Snorunt option {labs[:8]}"
    assert sno[0][0] <= sp._ATTACH_ILLEGAL + 1e-6
    assert labs[0] != "CARD 雪童"


def test_92538341_si93_does_not_evolve_dry_861():
    obs, sit, mi = _load_frame(92538341, 93)
    ranked = _best(obs, sit)
    evo = [r for r in ranked if "861" in _lab(obs, r[2], mi)]
    assert evo
    assert evo[0][0] <= sp._ATTACH_ILLEGAL + 1e-6


def test_92545897_si105_does_not_play_salvator():
    obs, sit, mi = _load_frame(92545897, 105)
    ranked = _best(obs, sit)
    assert _lab(obs, ranked[0][2], mi) != "PLAY 萨瓦托"
    salv = [r for r in ranked if "萨瓦托" in _lab(obs, r[2], mi) or "1189" in _lab(obs, r[2], mi)]
    if salv:
        assert salv[0][0] <= sp._ATTACH_ILLEGAL + 1e-6
