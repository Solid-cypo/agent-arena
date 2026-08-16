"""Unit tests for draw-axis framework v2 (board + hand + deck_resources)."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for p in (str(ROOT), str(SKILL)):
    if p not in sys.path:
        sys.path.insert(0, p)

from collections import Counter

from deck_resources import DeckResourceSnapshot, HandContext, build_deck_resources, load_deck_template
from draw_axis import pick_draw_axis_action, should_forbid_cycle
from hand_snapshot import BoardSnapshot
from opening_cards import BOSS_ORDERS, CRISPIN, DUDUNSPARCE, LILLIE
from phase_fsm import PhaseState
from supporter_planner import lillie_forbidden, pick_supporter


def _board(**kw) -> BoardSnapshot:
    defaults = dict(
        turn=5, first_player=0, my_index=0, my_turn_number=3,
        prize_self=5, prize_opp=6, hand_size=4,
        bench_count=3, bench_open=2, active_id=1031,
        active_has_water=True, active_is_mega_starmie=True,
        active_is_mega_froslass=False, staryu_on_field=False,
        mega_starmie_on_field=True, bench_mega_starmie_has_water=False,
        snorunt_line_on_bench=True, snorunt_on_field=True,
        mega_froslass_on_field=False,
        froslass_104_on_field=True, munkidori_on_bench=True,
        munkidori_on_field=True, munkidori_has_dark=True,
        bench_three_core_ready=True, fan_rotom_on_field=False,
        fan_rotom_dead=True,
    )
    defaults.update(kw)
    return BoardSnapshot(**defaults)


def _hand(**kw) -> HandContext:
    defaults = dict(
        hand_ids=[LILLIE], hand_size=1, supporter_played=False,
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
        deck_count=30, prize_count=5, discard_count=2,
    )
    defaults.update(kw)
    return DeckResourceSnapshot(**defaults)


def _phase(primary="AGGRESSION", control=False, opening_done=True):
    return PhaseState(primary, control, opening_done)


def _obs_with_zones(hand_ids, discard_ids, deck_count=25):
    hand = [NS(id=c) for c in hand_ids]
    discard = [NS(id=c) for c in discard_ids]
    me = NS(
        hand=hand, discard=discard, active=[], bench=[],
        deckCount=deck_count, prize=[None] * 5, prizeCount=5,
        supporterPlayed=False, energyAttached=False,
    )
    opp = NS(hand=[], discard=[], active=[], bench=[], deckCount=30, prize=[None] * 6)
    current = NS(turn=5, yourIndex=0, firstPlayer=0, players=[me, opp])
    return NS(current=current)


def test_no_blanket_lillie_ban_my_t2():
    board = _board(my_turn_number=2)
    hand = _hand(hand_ids=[LILLIE], hand_size=1)
    res = _resources()
    forbidden, rule = lillie_forbidden(board, _phase(), hand, res)
    assert not forbidden and rule == ""


def test_hand_starved_relaxes_cycle_tempo_ban_my_t2():
    board = _board(my_turn_number=2)
    hand = _hand(hand_ids=[65, 305], hand_size=2, has_lillie=False)
    res = _resources()
    forbidden, rule = should_forbid_cycle(board, _phase(), hand, res)
    assert not forbidden and rule == ""


def test_dr2_lillie_low_hand():
    board = _board(my_turn_number=4, prize_self=5)
    hand = _hand(hand_ids=[LILLIE], hand_size=2)
    res = _resources()
    dec = pick_supporter(board, _phase(), hand, res)
    assert dec and dec.action == "PLAY" and dec.card_id == LILLIE


def test_dr5_forbid_lillie_when_boss_gust():
    board = _board(my_turn_number=4)
    hand = _hand(
        hand_ids=[LILLIE, BOSS_ORDERS], hand_size=2,
        has_boss=True, gust_target_on_opp_bench=True,
        gust_target_koable=True,
    )
    res = _resources()
    forbidden, rule = lillie_forbidden(board, _phase(), hand, res)
    assert forbidden and rule == "DR-5"


def test_sp_boss_priority():
    board = _board(my_turn_number=4)
    hand = _hand(
        hand_ids=[BOSS_ORDERS, LILLIE], hand_size=2,
        has_boss=True, gust_target_on_opp_bench=True,
        gust_target_koable=True,
    )
    res = _resources(remaining=Counter(load_deck_template()) - Counter([BOSS_ORDERS]))
    dec = pick_supporter(board, _phase(), hand, res)
    assert dec and dec.action == "PLAY" and dec.card_id == BOSS_ORDERS


def test_dr4_run_away_draw_when_ready():
    board = _board(my_turn_number=4)
    hand = HandContext(
        hand_ids=[CRISPIN], hand_size=3, supporter_played=False,
        energy_attached=False, has_boss=False, has_lillie=False,
        has_crispin=True, gust_target_on_opp_bench=False,
    )
    res = _resources(deck_count=20)
    dec = pick_draw_axis_action(
        board, _phase(), hand, res, dudunsparce_66_on_bench=True,
    )
    assert dec and dec.action == "ABILITY_DRAW"


def test_dd7_forbid_when_no_66_left():
    board = _board(my_turn_number=4, prize_self=4, prize_opp=6)
    hand = _hand(hand_ids=[CRISPIN], hand_size=3, has_lillie=False)
    template = Counter(load_deck_template())
    # Exhaust all 66 + free-retreat 65 copies (deck no longer runs 305).
    seen = Counter({DUDUNSPARCE: template[DUDUNSPARCE], 65: template[65], 305: template[305]})
    remaining = Counter(template)
    for cid, n in seen.items():
        remaining[cid] = max(0, remaining[cid] - n)
    res = DeckResourceSnapshot(
        template=template, seen=seen, remaining=remaining,
        deck_count=15, prize_count=4,
    )
    forbidden, rule = should_forbid_cycle(board, _phase(), hand, res)
    assert forbidden and rule == "DD-7"


def test_build_deck_resources_from_obs():
    obs = _obs_with_zones(hand_ids=[LILLIE, BOSS_ORDERS], discard_ids=[1225, 1225])
    res = build_deck_resources(obs)
    assert res.copies_left(LILLIE) == 3
    assert res.copies_left(1225) == 1
    assert res.seen[LILLIE] == 1
    assert res.seen[BOSS_ORDERS] == 1


def test_prefer_cycle_preserves_lillie():
    board = _board(my_turn_number=4, prize_self=5, prize_opp=6)
    hand = _hand(
        hand_ids=[BOSS_ORDERS, CRISPIN, LILLIE], hand_size=3,
        has_boss=True, has_lillie=True, has_crispin=True,
    )
    res = _resources(deck_count=22)
    assert res.prefer_cycle_over_lillie(hand)
    forbidden, rule = should_forbid_cycle(board, _phase(), hand, res)
    assert not forbidden or rule != "DD-8"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
