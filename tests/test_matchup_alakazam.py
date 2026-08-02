"""Alakazam Plan B: going-second LOCK, Budew wall, KO finisher window."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, EnergyType, OptionType, SelectContext
import matchup_alakazam as alak
import starmie_pilot as sp
from hand_snapshot import build_board_snapshot
from turn_planner import build_turn_plan

ABRA, KADABRA, SHAYMIN = 741, 742, 343
WATER = int(EnergyType.WATER)


def _pkm(cid, hp=100, max_hp=None, energies=(), **kw):
    return NS(
        id=cid,
        hp=hp,
        maxHp=max_hp if max_hp is not None else hp,
        energies=list(energies),
        **kw,
    )


def _player(*, active=None, bench=(), hand=(), discard=(), prizes=6, hand_count=None):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=cid) if isinstance(cid, int) else cid for cid in hand],
        discard=[NS(id=cid) if isinstance(cid, int) else cid for cid in discard],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _board(*, my_index=0, first_player=1, my_turn_number=1, **kw):
    """Default going-second: my_index=0, first_player=1."""
    base = dict(
        my_index=my_index,
        first_player=first_player,
        my_turn_number=my_turn_number,
        froslass_104_on_field=False,
        munkidori_on_field=False,
        munkidori_has_dark=False,
        snorunt_on_field=False,
        staryu_on_field=False,
        mega_starmie_on_field=False,
        active_is_mega_starmie=False,
        bench_mega_starmie_has_water=False,
    )
    base.update(kw)
    return NS(**base)


def test_lock_deadline_going_second_is_t2():
    assert alak.lock_deadline(_board(my_index=0, first_player=1)) == 2
    assert alak.lock_deadline(_board(my_index=0, first_player=0)) == 3


def test_alak_lock_pick_order_snorunt_first_when_going_second():
    board = _board(
        my_index=0,
        first_player=1,
        munkidori_on_field=False,
        snorunt_on_field=False,
        froslass_104_on_field=False,
    )
    me = _player(active=_pkm(alak.BUDEW), hand=(alak.POFFIN,))
    opp = _player(active=_pkm(ABRA), discard=(ABRA,))
    obs = NS(
        current=NS(turn=2, yourIndex=0, firstPlayer=1, players=[me, opp], stadium=[]),
        select=NS(deck=[]),
    )
    order = alak.alak_lock_pick_order(obs, board, 0)
    assert order[0] == alak.SNORUNT
    assert alak.MUNKIDORI in order


def test_budew_wall_blocks_retreat_and_switch_out():
    me = _player(
        active=_pkm(alak.BUDEW),
        bench=(_pkm(alak.STARYU),),
        hand=(alak.SWITCH_CARD,),
    )
    opp = _player(active=_pkm(ABRA), discard=(ABRA,))
    obs = NS(
        current=NS(turn=3, yourIndex=0, firstPlayer=1, players=[me, opp], stadium=[]),
        select=NS(deck=[], context=0),
    )
    sit = {
        "matchup_alakazam_confirmed": True,
        "my_index": 0,
        "board": build_board_snapshot(obs),
        "phase": NS(primary="OPENING"),
        "alak_finisher_window": False,
        "alak_follow_window": False,
        "turn_plan": None,
    }
    retreat = NS(type=OptionType.RETREAT)
    switch = NS(type=OptionType.PLAY, index=0)
    bonus_r = alak.alakazam_plan_b_hard_bonus(
        obs,
        retreat,
        sit,
        dominate=1000,
        dominate_mid=800,
        dominate_plus=1200,
        dominate_open=1500,
        dominate_attack=2000,
        hand_card_id_fn=sp._hand_card_id,
        attack_id_fn=sp._attack_id,
        itchy_pollen_id=323,
        jetting_id=1487,
        option_type_play=OptionType.PLAY,
        option_type_attack=OptionType.ATTACK,
        option_type_evolve=OptionType.EVOLVE,
        option_type_card=OptionType.CARD,
        select_switch_contexts=(int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)),
        option_type_retreat=OptionType.RETREAT,
    )
    bonus_s = alak.alakazam_plan_b_hard_bonus(
        obs,
        switch,
        sit,
        dominate=1000,
        dominate_mid=800,
        dominate_plus=1200,
        dominate_open=1500,
        dominate_attack=2000,
        hand_card_id_fn=sp._hand_card_id,
        attack_id_fn=sp._attack_id,
        itchy_pollen_id=323,
        jetting_id=1487,
        option_type_play=OptionType.PLAY,
        option_type_attack=OptionType.ATTACK,
        option_type_evolve=OptionType.EVOLVE,
        option_type_card=OptionType.CARD,
        select_switch_contexts=(int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)),
        option_type_retreat=OptionType.RETREAT,
    )
    assert bonus_r < 0
    assert bonus_s < 0


def test_budew_ko_sets_finisher_on_turn_boundary():
    state: dict = {
        "matchup_alakazam_confirmed": True,
        "alak_prev_my_had_budew": True,
        "alak_last_my_turn": 2,
    }
    me = _player(active=_pkm(alak.STARYU))  # Budew gone
    opp = _player(active=_pkm(KADABRA))
    obs = NS(
        current=NS(turn=5, yourIndex=0, firstPlayer=1, players=[me, opp], stadium=[]),
        select=NS(deck=[]),
    )
    frag = alak.refresh_alakazam_matchup(state, obs, 0, my_turn_number=3)
    assert frag["alak_budew_ko_last_opp_turn"]
    assert frag["alak_finisher_window"]


def test_lock_window_promotes_benched_budew():
    me = _player(
        active=_pkm(alak.STARYU),
        bench=(_pkm(alak.BUDEW),),
        hand=(),
    )
    opp = _player(active=_pkm(ABRA), discard=(ABRA,))
    obs = NS(
        current=NS(turn=2, yourIndex=0, firstPlayer=1, players=[me, opp], stadium=[]),
        select=NS(deck=[], context=int(SelectContext.TO_ACTIVE)),
    )
    board = build_board_snapshot(obs)
    # Force going-second LOCK window fields used by Plan B.
    board = NS(**{**board.__dict__, "my_turn_number": 1, "first_player": 1, "my_index": 0})
    sit = {
        "matchup_alakazam_confirmed": True,
        "my_index": 0,
        "board": board,
        "phase": NS(primary="OPENING"),
        "alak_finisher_window": False,
        "alak_follow_window": False,
        "turn_plan": None,
        "_pokemon_in_area_fn": sp._pokemon_in_area,
    }
    budew = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    bonus = alak.alakazam_plan_b_hard_bonus(
        obs,
        budew,
        sit,
        dominate=1000,
        dominate_mid=800,
        dominate_plus=1200,
        dominate_open=1500,
        dominate_attack=2000,
        dominate_path=1800,
        hand_card_id_fn=sp._hand_card_id,
        attack_id_fn=sp._attack_id,
        itchy_pollen_id=323,
        jetting_id=1487,
        option_type_play=OptionType.PLAY,
        option_type_attack=OptionType.ATTACK,
        option_type_evolve=OptionType.EVOLVE,
        option_type_card=OptionType.CARD,
        select_switch_contexts=(int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)),
        option_type_retreat=OptionType.RETREAT,
        card_option_id_fn=sp._card_option_id,
    )
    # LOCK window should prefer promoting Budew into Active.
    assert bonus > 0


def test_doublekill_ready_frozen_predicate():
    me = _player(
        active=_pkm(alak.MEGA_STARMIE, energies=(WATER,)),
    )
    opp = _player(
        active=_pkm(900, hp=100),
        bench=(_pkm(ABRA, hp=40),),
    )
    obs = NS(
        current=NS(turn=6, yourIndex=0, firstPlayer=0, players=[me, opp], stadium=[]),
        select=NS(deck=[]),
    )
    assert alak.doublekill_ready(obs, 0)


def test_shaymin_blocks_abra_rider_in_turn_plan():
    me = _player(active=_pkm(alak.MEGA_STARMIE, energies=(WATER,)))
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(_pkm(SHAYMIN, hp=80), _pkm(ABRA, hp=50), _pkm(140, hp=50, ex=True)),
        hand_count=3,
    )
    obs = NS(
        current=NS(turn=6, yourIndex=0, firstPlayer=0, players=[me, opp], stadium=[]),
        select=NS(deck=[]),
    )
    plan = build_turn_plan(obs, build_board_snapshot(obs), matchup="alakazam")
    assert plan.combat.rider_target.card_id == 140
    assert next(t for t in plan.facts.opp_bench if t.card_id == ABRA).attack_protected


if __name__ == "__main__":
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(failed)
