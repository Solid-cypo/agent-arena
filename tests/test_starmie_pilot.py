"""BDD tests for the Starmie+Froslass pilot's hard rules and soft dims.

Uses lightweight mock observation objects (no full game simulation) so the
suite runs in milliseconds even under CPU contention.
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for p in (str(ROOT), str(SKILL)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cg.api import AreaType, EnergyType, OptionType
import starmie_pilot as sp

JETTING, NEBULA, RESENTFUL, ITCHY = 1487, 1488, 1240, 323


def _pkm(cid, hp=300, maxHp=None, energies=None):
    mh = maxHp if maxHp is not None else hp
    return NS(id=cid, hp=hp, maxHp=mh, energies=energies or [])


def _obs(turn, my_index, me, opp, first_player=None):
    players = [None, None]
    players[my_index] = me
    players[1 - my_index] = opp
    fp = my_index if first_player is None else first_player
    current = NS(turn=turn, yourIndex=my_index, firstPlayer=fp, players=players)
    return NS(current=current, select=NS(deck=[]))


def _aggression_me(**kwargs):
    """Active Mega Starmie ex + water → AGGRESSION phase."""
    active = kwargs.pop("active", None)
    if active is None:
        active = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    return _player(active=active, **kwargs)


def _player(active=None, bench=None, hand=None, prize_n=6, hand_n=5, discard=None, deck_count=35):
    hand = hand or []
    return NS(
        active=[active] if active else [],
        bench=bench or [],
        hand=hand,
        prize=[None] * prize_n,
        prizeCount=prize_n,
        handCount=hand_n if hand_n else len(hand),
        discard=discard or [],
        deckCount=deck_count,
        supporterPlayed=False,
        energyAttached=False,
    )


# ── Hard rule 1: Fan Rotom Fan Call only on first turn ──────────────────────

def test_fan_call_fires_turn_one():
    me  = _player(bench=[_pkm(sp._FAN_ROTOM_ID)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=1, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE


def test_fan_call_forbidden_late_game():
    me  = _player(bench=[_pkm(sp._FAN_ROTOM_ID)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


# ── Hard rule 2: Munkidori Adrena-Brain requires Darkness energy ────────────

def test_munkidori_fires_with_dark_energy():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    active = _pkm(sp._CARDS["mega_starmie_ex"], hp=280, maxHp=330, energies=[int(EnergyType.WATER)])
    me   = _aggression_me(active=active, bench=[munk])
    opp  = _player(active=_pkm(999))
    obs  = _obs(turn=4, my_index=0, me=me, opp=opp)
    sit  = sp._compute_situation(obs)
    opt  = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_PLUS


def test_munkidori_silent_without_dark_energy():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.WATER)])
    me   = _aggression_me(bench=[munk])
    opp  = _player(active=_pkm(999))
    obs  = _obs(turn=4, my_index=0, me=me, opp=opp)
    sit  = sp._compute_situation(obs)
    opt  = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_munkidori_silent_during_opening():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me   = _player(bench=[munk], active=_pkm(sp._BUDEW_ID, hp=30))
    opp  = _player(active=_pkm(999))
    obs  = _obs(turn=1, my_index=0, me=me, opp=opp)
    sit  = sp._compute_situation(obs)
    opt  = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) == 0.0


def test_munkidori_silent_without_transferable_damage():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me   = _aggression_me(bench=[munk])
    opp  = _player(active=_pkm(999))
    obs  = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit  = sp._compute_situation(obs)
    opt  = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_munkidori_fires_late_opening_with_mega_on_field():
    munk = _pkm(sp._MUNKIDORI_ID, hp=280, maxHp=300, energies=[int(EnergyType.DARKNESS)])
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    me = _player(bench=[munk, starmie], active=_pkm(sp._BUDEW_ID, hp=30))
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_PLUS


def test_ready_mega_defers_snorunt_synergy_window():
    me = _aggression_me(hand=[NS(id=sp._CARDS["snorunt"])])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "AGGRESSION"
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_ready_mega_allows_dp_evolution_but_defers_861():
    snorunt = _pkm(sp._CARDS["snorunt"])
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    me = _player(
        active=starmie,
        bench=[snorunt],
        hand=[NS(id=sp._CARDS["froslass"]), NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    fro = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    mega = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=1)
    assert sp._hard_rule_bonus(obs, fro, sit) >= sp._DOMINATE
    assert sp._hard_rule_bonus(obs, mega, sit) <= -sp._DOMINATE


def test_munkidori_silent_outside_t2_t8():
    """My-T9+ still fires only when own damage exists; no damage → silent."""
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(bench=[munk])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=19, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


# ── Hard rule 3: Budew Itchy Pollen fallback when no Mega ready ─────────────

def test_budew_fallback_when_no_mega():
    me  = _player(active=_pkm(sp._BUDEW_ID, hp=30))
    opp = _player(active=_pkm(999))
    obs = _obs(turn=3, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ATTACK, attackId=ITCHY)
    assert sp._hard_rule_bonus(obs, opt, sit) > 0


def test_budew_silent_when_mega_ready():
    me  = _player(active=_pkm(sp._CARDS["mega_starmie_ex"]))
    opp = _player(active=_pkm(999))
    obs = _obs(turn=3, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ATTACK, attackId=ITCHY)
    assert sp._hard_rule_bonus(obs, opt, sit) == 0.0


def test_ready_bench_mega_forbids_basic_attack():
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=[starmie],
        hand=[NS(id=1123)],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999, hp=300)))
    sit = sp._compute_situation(obs)
    basic_attack = NS(type=OptionType.ATTACK, attackId=99999)
    assert sp._hard_rule_bonus(obs, basic_attack, sit) <= -sp._DOMINATE


def test_alakazam_overlay_precedes_turn_plan():
    me = _aggression_me(hand=[NS(id=sp._CARDS["hilda"])])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    option = NS(type=OptionType.PLAY, index=0)
    original = sp.alakazam_plan_b_hard_bonus
    sp.alakazam_plan_b_hard_bonus = lambda *args, **kwargs: 1234.0
    try:
        assert sp._hard_rule_bonus(obs, option, sit) == 1234.0
    finally:
        sp.alakazam_plan_b_hard_bonus = original


# ── Soft dim: froslass harvest only with big opponent hand ──────────────────

def test_froslass_harvest_big_hand():
    from phase_fsm import PhaseState

    froslass = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _player(
        active=_pkm(sp._CARDS["froslass"]),
        bench=[_pkm(sp._CARDS["snorunt"])],
        hand=[froslass],
    )
    opp = _player(active=_pkm(999), hand_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    obs.select = NS(deck=[])
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("HARVEST", False, True)
    opt = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    assert sp._soft_bonus(obs, opt, sp.DEFAULT_WEIGHTS, sit) >= sp.DEFAULT_WEIGHTS["froslass_harvest"]


def test_froslass_no_harvest_small_hand():
    froslass = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _player(
        active=_pkm(sp._CARDS["mega_froslass_ex"], energies=[int(EnergyType.WATER)]),
        hand=[froslass],
    )
    opp = _player(active=_pkm(999), hand_n=2, prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    obs.select = NS(deck=[])
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    assert sp._soft_bonus(obs, opt, sp.DEFAULT_WEIGHTS, sit) == 0.0


def test_froslass_harvest_soft_dim_inactive_in_aggression():
    froslass = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _player(hand=[froslass], active=_pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)]))
    opp = _player(active=_pkm(999), hand_n=6)
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    obs.select = NS(deck=[])
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "AGGRESSION"
    opt = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    assert sp._soft_bonus(obs, opt, sp.DEFAULT_WEIGHTS, sit) == 0.0


# ── Soft dim: Jetting Blow preferred over generic attack ────────────────────

def test_jetting_blow_preferred():
    me  = _aggression_me()
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._soft_bonus(obs, opt, sp.DEFAULT_WEIGHTS, sit) >= sp.DEFAULT_WEIGHTS["jetting_blow_pref"]


# ── Phase 2 AGGRESSION hard rules ───────────────────────────────────────────

def test_aggression_jetting_blow_hard_rule():
    me  = _aggression_me()
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "AGGRESSION"
    opt = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_ATTACK


def test_adrena_brain_beats_jetting_when_damaged():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    active = _pkm(sp._CARDS["mega_starmie_ex"], hp=260, maxHp=330, energies=[int(EnergyType.WATER)])
    me = _aggression_me(active=active, bench=[munk])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    ab = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, ab, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_ready_mega_prepares_munk_dark_before_attack():
    munk = _pkm(sp._MUNKIDORI_ID)
    dark = NS(id=int(EnergyType.DARKNESS))
    me = _aggression_me(bench=[munk], hand=[dark])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, attach, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_block_mega_froslass_without_104_engine():
    snorunt = _pkm(sp._CARDS["snorunt"])
    mega = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _aggression_me(bench=[snorunt], hand=[mega])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_froslass_104_bench_lock_blocks_861_without_snorunt():
    fro = _pkm(sp._CARDS["froslass"])
    mega = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _player(active=fro, hand=[mega])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=9, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.EVOLVE, area=AreaType.ACTIVE, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_retreat_rescue_switch_beats_jetting():
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _player(active=munk, bench=[starmie], hand=[NS(id=1123)])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=19, my_index=0, me=me, opp=opp)  # My-T10 — outside synergy defer window
    sit = sp._compute_situation(obs)
    sw = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, sw, sit) >= sp._DOMINATE_RESCUE


def test_retreat_rescue_attach_active():
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    munk = _pkm(sp._MUNKIDORI_ID)
    dark = NS(id=int(EnergyType.DARKNESS))
    me = _player(active=munk, bench=[starmie], hand=[dark])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE


def test_ready_mega_defers_second_munkidori_until_after_attack():
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(bench=[munk], hand=[NS(id=sp._MUNKIDORI_ID)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_jetting_uses_attack_tier_score():
    me = _aggression_me()
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, opt, sit) == sp._DOMINATE_ATTACK


def test_aggression_nebula_ko_beats_jetting():
    me  = _aggression_me()
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    neb = NS(type=OptionType.ATTACK, attackId=NEBULA)
    assert sp._hard_rule_bonus(obs, neb, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_ready_mega_defers_playing_snorunt():
    snorunt_card = NS(id=sp._CARDS["snorunt"])
    me  = _aggression_me(hand=[snorunt_card], bench=[])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_ready_mega_allows_dark_attach_to_complete_dp():
    munk = _pkm(sp._MUNKIDORI_ID)
    dark = NS(id=int(EnergyType.DARKNESS))
    me   = _aggression_me(bench=[munk], hand=[dark])
    opp  = _player(active=_pkm(999))
    obs  = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit  = sp._compute_situation(obs)
    opt  = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE


def test_ready_mega_defers_risky_ruins():
    snorunt = _pkm(sp._CARDS["snorunt"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    ruins = NS(id=sp._CARDS["risky_ruins"])
    me = _aggression_me(bench=[snorunt, munk], hand=[ruins])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=6, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_fan_rotom_play_blocked_when_dead():
    rotom = NS(id=sp._FAN_ROTOM_ID)
    me = _aggression_me(hand=[rotom])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=6, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_phase_fsm_opening_vs_aggression():
    from hand_snapshot import build_board_snapshot
    from phase_fsm import compute_phase, opening_complete

    me_open = _player(active=_pkm(sp._BUDEW_ID, hp=30))
    opp = _player(active=_pkm(999))
    obs_open = _obs(turn=3, my_index=0, me=me_open, opp=opp)
    board_open = build_board_snapshot(obs_open)
    assert not opening_complete(board_open)
    assert compute_phase(board_open).primary == "OPENING"

    me_agg = _aggression_me()
    obs_agg = _obs(turn=5, my_index=0, me=me_agg, opp=opp)
    board_agg = build_board_snapshot(obs_agg)
    assert opening_complete(board_agg)
    assert compute_phase(board_agg).primary == "AGGRESSION"


def test_layer1_boss_play_beats_lillie_when_gust():
    from deck_resources import load_deck_template
    from opening_cards import BOSS_ORDERS, LILLIE

    snorunt = _pkm(sp._CARDS["snorunt"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    opp_weak = _pkm(999, hp=80)
    me = _aggression_me(
        bench=[snorunt, munk],
        hand=[NS(id=BOSS_ORDERS), NS(id=LILLIE)],
        prize_n=5,
        hand_n=2,
    )
    opp = _player(active=_pkm(999, hp=300), bench=[opp_weak], prize_n=6)
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs, deck_template=load_deck_template())
    boss_opt = NS(type=OptionType.PLAY, index=0)
    lillie_opt = NS(type=OptionType.PLAY, index=1)
    assert sp._hard_rule_bonus(obs, boss_opt, sit) >= 950.0
    assert sp._hard_rule_bonus(obs, lillie_opt, sit) <= -sp._DOMINATE


def test_ready_mega_defers_lillie_even_with_low_hand():
    from opening_cards import LILLIE

    snorunt = _pkm(sp._CARDS["snorunt"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(
        bench=[snorunt, munk],
        hand=[NS(id=LILLIE), NS(id=LILLIE)],
        prize_n=5,
        hand_n=2,
    )
    opp = _player(active=_pkm(999))
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    from deck_resources import load_deck_template
    sit = sp._compute_situation(obs, deck_template=load_deck_template())
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_layer1_forbid_lillie_my_t2_aggression():
    from opening_cards import LILLIE

    me = _aggression_me(hand=[NS(id=LILLIE)], prize_n=6, hand_n=1)
    opp = _player(active=_pkm(999))
    obs = _obs(turn=4, my_index=0, me=me, opp=opp)
    from deck_resources import load_deck_template
    sit = sp._compute_situation(obs, deck_template=load_deck_template())
    assert sit["board"].my_turn_number == 2
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_ready_mega_defers_run_away_draw():
    from deck_resources import load_deck_template

    d66 = _pkm(sp._CARDS["dudunsparce"])
    snorunt = _pkm(sp._CARDS["snorunt"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(
        bench=[snorunt, munk, d66],
        hand=[NS(id=3)],
        prize_n=4,
        hand_n=1,
    )
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs, deck_template=load_deck_template())
    opt = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=2)
    bonus = sp._hard_rule_bonus(obs, opt, sit)
    assert bonus <= -sp._DOMINATE


def test_opening_g5_switch_beats_synergy_setup():
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    fro = _pkm(sp._CARDS["froslass"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _player(
        active=_pkm(sp._BUDEW_ID, hp=30),
        bench=[starmie, fro, munk],
        hand=[NS(id=1123), NS(id=sp._CARDS["snorunt"])],
    )
    opp = _player(active=_pkm(999))
    obs = _obs(turn=9, my_index=0, me=me, opp=opp)  # My-T5
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "OPENING"
    sw = NS(type=OptionType.PLAY, index=0)
    sn = NS(type=OptionType.PLAY, index=1)
    assert sp._hard_rule_bonus(obs, sw, sit) >= sp._DOMINATE_OPEN
    assert sp._hard_rule_bonus(obs, sw, sit) > sp._hard_rule_bonus(obs, sn, sit)


def test_opening_g5_switch_in_opening_without_synergy_core():
    """Step A: OPENING uses path planner; G5 Switch not blocked by synergy defer."""
    starmie = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    me = _player(
        active=_pkm(sp._CARDS["staryu"], energies=[int(EnergyType.WATER)]),
        bench=[starmie],
        hand=[NS(id=1123)],
    )
    opp = _player(active=_pkm(999))
    obs = _obs(turn=9, my_index=0, me=me, opp=opp)  # My-T5 OPENING
    sit = sp._compute_situation(obs)
    board = sit["board"]
    phase = sit["phase"]
    assert phase.primary == "OPENING"
    assert sp._opening_g5_switch_needed(phase, board, obs, 0)


def test_defer_mega_promotion_skipped_in_opening():
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
    )
    obs = _obs(turn=9, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "OPENING"
    assert not sp._defer_mega_promotion(sit["board"], sit["phase"])


def test_opening_jetting_when_active_mega():
    me = _aggression_me()
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=3, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "AGGRESSION"
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_ATTACK


def test_opening_jetting_hard_rule_before_aggression():
    """Mega on Active with water in OPENING (pre opening_complete edge) — still attacks."""
    me = _player(active=_pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)]))
    opp = _player(active=_pkm(999))
    obs = _obs(turn=3, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "AGGRESSION"
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_ATTACK


def test_end_penalized_when_starmie_should_attack():
    me = _aggression_me()
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    end = NS(type=OptionType.END)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE
    assert sp._hard_rule_bonus(obs, jet, sit) > sp._hard_rule_bonus(obs, end, sit)


# ── Phase 3 HARVEST hard rules (HR-H1–H6) ───────────────────────────────────

def _harvest_me(**kwargs):
    active = kwargs.pop("active", None)
    if active is None:
        active = _pkm(sp._CARDS["mega_froslass_ex"], energies=[int(EnergyType.WATER)])
    return _player(active=active, **kwargs)


def test_phase_fsm_harvest_mega_froslass():
    from hand_snapshot import build_board_snapshot
    from phase_fsm import compute_phase

    me = _harvest_me()
    obs = _obs(turn=10, my_index=0, me=me, opp=_player(active=_pkm(999)))
    board = build_board_snapshot(obs)
    assert compute_phase(board).primary == "HARVEST"


def test_harvest_h1_evolve_861():
    fro = _pkm(sp._CARDS["froslass"])
    mega = NS(id=sp._CARDS["mega_froslass_ex"])
    me = _player(active=fro, bench=[_pkm(sp._CARDS["snorunt"])], hand=[mega])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "HARVEST"
    opt = NS(type=OptionType.EVOLVE, area=AreaType.ACTIVE, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE


def test_harvest_h3_resentful_attack():
    me = _harvest_me()
    opp = _player(active=_pkm(999), hand_n=5)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "HARVEST"
    opt = NS(type=OptionType.ATTACK, attackId=RESENTFUL)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_ATTACK


def test_harvest_h5_block_end_when_should_attack():
    me = _harvest_me()
    opp = _player(active=_pkm(999))
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    end = NS(type=OptionType.END)
    res = NS(type=OptionType.ATTACK, attackId=RESENTFUL)
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE
    assert sp._hard_rule_bonus(obs, res, sit) > sp._hard_rule_bonus(obs, end, sit)


def test_harvest_h6_block_judge_before_resentful():
    from opening_cards import JUDGE

    fro = _pkm(sp._CARDS["froslass"])
    me = _player(active=fro, bench=[_pkm(sp._CARDS["snorunt"])], hand=[NS(id=JUDGE)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "HARVEST"
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE

    snorunt_only = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=[_pkm(sp._CARDS["snorunt"])],
        hand=[NS(id=JUDGE)],
    )
    obs2 = _obs(turn=7, my_index=0, me=snorunt_only, opp=opp)
    sit2 = sp._compute_situation(obs2)
    assert sit2["phase"].primary == "HARVEST"
    assert sp._hard_rule_bonus(obs2, opt, sit2) <= -sp._DOMINATE


def test_harvest_jetting_not_forced_on_backup_starmie():
    """HR-6 must not force Jetting during HARVEST when Active is 861."""
    me = _harvest_me()
    opp = _player(active=_pkm(999))
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE


def test_harvest_h2_attach_water_to_861():
    fro = _pkm(sp._CARDS["mega_froslass_ex"])
    water = NS(id=int(EnergyType.WATER))
    me = _player(active=fro, hand=[water])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, attach, sit) >= sp._DOMINATE_PLUS
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE


def test_harvest_h7_unfair_stamp_after_ko():
    from opening_cards import UNFAIR_STAMP
    from phase_fsm import PhaseState

    fro = _pkm(sp._CARDS["froslass"])
    me = _player(active=fro, hand=[NS(id=UNFAIR_STAMP)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=11, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("HARVEST", False, True)
    sit["harvest_ko_last_turn"] = True
    stamp = NS(type=OptionType.PLAY, index=0)
    mega = NS(id=sp._CARDS["mega_froslass_ex"])
    me2 = _player(active=fro, bench=[_pkm(sp._CARDS["snorunt"])], hand=[mega, NS(id=UNFAIR_STAMP)])
    obs2 = _obs(turn=11, my_index=0, me=me2, opp=opp)
    sit2 = sp._compute_situation(obs2)
    sit2["phase"] = PhaseState("HARVEST", False, True)
    sit2["harvest_ko_last_turn"] = True
    evolve = NS(type=OptionType.EVOLVE, area=AreaType.ACTIVE, index=0)
    assert sp._hard_rule_bonus(obs, stamp, sit) >= sp._DOMINATE_OPEN
    assert sp._hard_rule_bonus(obs, stamp, sit) >= sp._hard_rule_bonus(obs2, evolve, sit2)


def test_harvest_ko_last_turn_detected():
    from hand_snapshot import build_board_snapshot

    state = {
        "last_my_turn": 5,
        "prev_active_was_mega_starmie": True,
        "harvest_ko_last_turn": False,
    }
    me = _player(active=_pkm(sp._CARDS["froslass"]))
    obs = _obs(turn=11, my_index=0, me=me, opp=_player(active=_pkm(999)))
    board = build_board_snapshot(obs)
    sp._refresh_harvest_ko(state, board)
    assert state["harvest_ko_last_turn"]


# ── Phase 4 CONTROL modifier (HR-C1–C4) ─────────────────────────────────────

def test_control_meowth_play_when_leading():
    from phase_fsm import PhaseState

    meowth = NS(id=sp._CARDS["meowth_ex"])
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _player(active=munk, bench=[_pkm(sp._CARDS["snorunt"])], hand=[meowth], prize_n=4)
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("AGGRESSION", True, True)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_MID


def test_control_meowth_blocked_when_starmie_must_attack():
    from phase_fsm import PhaseState

    meowth = NS(id=sp._CARDS["meowth_ex"])
    me = _aggression_me(hand=[meowth], prize_n=4)
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("AGGRESSION", True, True)
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_control_judge_allowed_after_resentful_in_harvest():
    from opening_cards import JUDGE
    from phase_fsm import PhaseState

    me = _player(
        active=_pkm(sp._CARDS["froslass"]),
        bench=[_pkm(sp._CARDS["snorunt"])],
        hand=[NS(id=JUDGE)],
        prize_n=4,
    )
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("HARVEST", True, True)
    sit["harvest_resentful_fired"] = True
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_SUPPORT


def test_control_judge_still_blocked_before_resentful_in_harvest():
    from opening_cards import JUDGE
    from phase_fsm import PhaseState

    fro = _pkm(sp._CARDS["froslass"])
    me = _player(active=fro, bench=[_pkm(sp._CARDS["snorunt"])], hand=[NS(id=JUDGE)], prize_n=4)
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("HARVEST", True, True)
    sit["harvest_resentful_fired"] = False
    opt = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, opt, sit) <= -sp._DOMINATE


def test_poffin_reorder_follows_acquire_targets_dual_pick():
    """Held-66 style AcquirePlan (STARYU, DUNSPARCE) must beat opening table order."""
    from cg.api import SelectContext
    from opening_cards import DUNSPARCE_A, POFFIN, STARYU
    from turn_planner import AcquirePlan, CombatPlan

    me = _player(active=_pkm(sp._BUDEW_ID), hand=[NS(id=POFFIN)])
    opp = _player(active=_pkm(999))
    # Offered: Fan Rotom, Dunsparce, Staryu — opening table prefers Staryu then
    # Fan; AcquirePlan wants Staryu then Dunsparce ahead of Fan.
    deck = [NS(id=174), NS(id=DUNSPARCE_A), NS(id=STARYU)]
    options = [
        NS(type=OptionType.CARD, index=0),
        NS(type=OptionType.CARD, index=1),
        NS(type=OptionType.CARD, index=2),
    ]
    obs = _obs(turn=2, my_index=0, me=me, opp=opp)
    obs.select = NS(
        context=int(SelectContext.TO_BENCH),
        effect=NS(id=POFFIN),
        deck=deck,
        option=options,
        maxCount=2,
    )
    acquire = AcquirePlan(
        targets=(STARYU, DUNSPARCE_A),
        sources=(POFFIN,),
        ball_allowed=False,
        ball_reason="",
        discard_values=(),
        recover_target=None,
    )
    combat = CombatPlan(
        mode="NONE",
        attack_required=False,
        required_before_attack=(),
        next_action="BUILD",
    )
    sit = {
        "turn_plan": NS(acquire=acquire, combat=combat),
        "board": None,
        "matchup_alakazam_confirmed": False,
    }
    order = [0, 1, 2]
    reordered = sp._reorder_poffin_bench(obs, options, order, 0, sit)
    # Staryu (idx 2) then Dunsparce (idx 1) before Fan (idx 0).
    assert reordered[0] == 2
    assert reordered[1] == 1


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
