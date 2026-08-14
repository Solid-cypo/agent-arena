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
    # Non-fueled Active so must-attack closeout does not preempt the overlay.
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        hand=[NS(id=sp._CARDS["hilda"])],
    )
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
    assert sp._hard_rule_bonus(obs, opt, sit) >= sp._DOMINATE_OPEN_PATH


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
    # Fat hand + 2-prize Active → expected Froslass prizes ≥ 2 (Wave F gate).
    opp_active = _pkm(999, hp=200)
    opp_active.ex = True
    opp_active.prizeValue = 2
    opp = _player(active=opp_active, hand_n=5)
    obs = _obs(turn=7, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "HARVEST"
    assert sit["turn_plan"].combat.froslass_build_allowed
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

    # HandQual: Meowth is demoted while need_base (MAKE_ATTACKER). Seat Mega
    # first so CONTROL Meowth can PATH on a prize lead.
    meowth = NS(id=sp._CARDS["meowth_ex"])
    mega = _pkm(sp._CARDS["mega_starmie_ex"])
    me = _player(
        active=mega,
        bench=[_pkm(sp._CARDS["snorunt"])],
        hand=[meowth],
        prize_n=4,
    )
    opp = _player(active=_pkm(999), prize_n=6)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    sit["phase"] = PhaseState("AGGRESSION", True, True)
    opt = NS(type=OptionType.PLAY, index=0)
    sit["select_options"] = [opt]
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


# ── Must-attack plug (online 55202093 leaks) ────────────────────────────────

def test_fueled_starmie_poffin_loses_to_jetting():
    """89651017 — Poffin must not outrank Jetting on a fueled Active Mega."""
    from opening_cards import POFFIN

    me = _aggression_me(hand=[NS(id=POFFIN)])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    poffin = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [jet, poffin, end]
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, poffin, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH


def test_fueled_861_bans_lillie_after_water():
    """89660767 — after 861 has water, supporters cannot eat the turn."""
    from opening_cards import LILLIE

    fro = _pkm(sp._CARDS["mega_froslass_ex"], energies=[int(EnergyType.WATER)])
    me = _player(active=fro, hand=[NS(id=LILLIE)])
    opp = _player(active=_pkm(999, hp=200), hand_n=4)
    obs = _obs(turn=6, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    resentful = NS(type=OptionType.ATTACK, attackId=RESENTFUL)
    lillie = NS(type=OptionType.PLAY, index=0)
    sit["select_options"] = [resentful, lillie]
    assert sp._hard_rule_bonus(obs, resentful, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, lillie, sit) <= -sp._DOMINATE_OPEN_PATH


def test_fueled_starmie_bans_retreat_non_rescue():
    """89655562 — fueled Starmie must not Retreat instead of Jetting."""
    me = _aggression_me()
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    retreat = NS(type=OptionType.RETREAT)
    sit["select_options"] = [jet, retreat]
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, retreat, sit) <= -sp._DOMINATE_OPEN_PATH


def test_ghost_adrena_prep_does_not_block_jetting():
    """ADRENA listed as required but not in options must not ban Jetting."""
    from dataclasses import replace
    from turn_planner import CombatPlan

    # Damaged Active + dark Munk → ADRENA still_needed, but omit ability option.
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=200,
        maxHp=330,
        energies=[int(EnergyType.WATER)],
    )
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(active=active, bench=[munk])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sp._pre_attack_req_still_needed(obs, sit, "ADRENA")
    old = sit["turn_plan"].combat
    ghost = CombatPlan(
        mode="MEGA_MUST_ATTACK",
        attack_required=True,
        required_before_attack=("ADRENA",),
        next_action="ADRENA",
        rider_target=old.rider_target,
        boss_target=old.boss_target,
        expected_prizes=old.expected_prizes,
        expected_prize_delta=old.expected_prize_delta,
        froslass_build_allowed=old.froslass_build_allowed,
    )
    sit["turn_plan"] = replace(sit["turn_plan"], combat=ghost)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    poffin = NS(type=OptionType.PLAY, index=0)
    sit["select_options"] = [jet, poffin]  # no Adrena ability offered
    assert "ADRENA" not in sp._actionable_pre_attack(obs, sit, sit["turn_plan"].combat)
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, poffin, sit) <= -sp._DOMINATE_OPEN_PATH


def test_double_ko_adrena_beats_jetting_under_must_close():
    """DkAdrena-V1: DOUBLE_KO + live Adrena → Adrena immediately before Jetting."""
    # Damaged Starmie supplies Adrena fuel; soft rider 70HP needs the transfer.
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=280,
        maxHp=330,
        energies=[int(EnergyType.WATER)],
    )
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    me = _aggression_me(active=active, bench=[munk])
    # Active ≤120 so no Boss required; bench rider in soft window.
    opp = _player(
        active=_pkm(900, hp=100),
        bench=[_pkm(119, hp=70)],  # Riolu-like base
    )
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.mode == "DOUBLE_KO"
    assert sp._munk_can_adrena(obs, 0)
    ab = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [ab, jet]
    assert sp._double_ko_needs_adrena_before_jetting(obs, sit)
    assert sp._hard_rule_bonus(obs, ab, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH


def test_double_ko_boss_still_outranks_adrena_when_both_live():
    """Wave L: needs_boss → Boss before Adrena; knife must not invert."""
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=280,
        maxHp=330,
        energies=[int(EnergyType.WATER)],
    )
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    boss = NS(id=sp._BOSS_ID)
    me = _aggression_me(active=active, bench=[munk], hand=[boss])
    boss_target = _pkm(121, hp=110)
    boss_target.ex = True
    opp = _player(
        active=_pkm(900, hp=200),
        bench=[_pkm(119, hp=70), boss_target],
    )
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.mode == "DOUBLE_KO"
    assert "BOSS" in sit["turn_plan"].combat.required_before_attack
    ab = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    play_boss = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [ab, play_boss, jet]
    # Boss still actionable → knife off; Boss PATH beats Jetting/Adrena starve.
    assert not sp._double_ko_needs_adrena_before_jetting(obs, sit)
    assert sp._hard_rule_bonus(obs, play_boss, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_froslass_cut_switch_beats_jetting_on_multi_prize_oneshot():
    """FroslassCut-V1: watered 861 oneshots multi-prize front Jetting cannot KO."""
    from cg.api import SelectContext

    water = int(EnergyType.WATER)
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=280,
        maxHp=330,
        energies=[water],
    )
    fueled_861 = _pkm(
        sp._CARDS["mega_froslass_ex"],
        hp=300,
        maxHp=300,
        energies=[water],
    )
    switch = NS(id=sp._OC_SWITCH)
    me = _aggression_me(active=active, bench=[fueled_861], hand=[switch])
    # Opp hand 5 → Resentful 250; Active ex 200HP → oneshot; Jetting 120 cannot KO.
    opp_act = _pkm(900, hp=200, maxHp=200)
    opp_act.ex = True
    opp_act.prizeValue = 2
    opp = _player(active=opp_act, hand_n=5)
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.mode != "DOUBLE_KO"
    assert sp._froslass_oneshot_cut_live(obs, sit)
    play_sw = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play_sw, jet]
    assert sp._hard_rule_bonus(obs, play_sw, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH
    # Select: fueled 861 PATH; dry 861 banned.
    obs.select = NS(context=int(SelectContext.SWITCH), deck=[])
    pick_861 = NS(
        type=OptionType.CARD,
        area=AreaType.BENCH,
        index=0,
        playerIndex=0,
    )
    assert sp._hard_rule_bonus(obs, pick_861, sit) >= sp._DOMINATE_OPEN_PATH


def test_froslass_cut_refuses_dry_861():
    """无能861: cut knife off when bench 861 has no water."""
    water = int(EnergyType.WATER)
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=280,
        maxHp=330,
        energies=[water],
    )
    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], hp=300, maxHp=300, energies=[])
    me = _aggression_me(
        active=active, bench=[dry_861], hand=[NS(id=sp._OC_SWITCH)],
    )
    opp_act = _pkm(900, hp=200, maxHp=200)
    opp_act.ex = True
    opp_act.prizeValue = 2
    opp = _player(active=opp_act, hand_n=5)
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert not sp._froslass_oneshot_cut_live(obs, sit)


def test_dry_mega_to_active_hard_ban():
    """Global: selecting dry 861 into Active is illegal."""
    from cg.api import SelectContext

    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], energies=[])
    me = _aggression_me(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)]),
        bench=[dry_861],
    )
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=_pkm(999, hp=50)))
    sit = sp._compute_situation(obs)
    obs.select = NS(context=int(SelectContext.SWITCH), deck=[])
    pick = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    assert sp._hard_rule_bonus(obs, pick, sit) <= -sp._DOMINATE_OPEN_PATH


def test_dry_snorunt_to_active_banned_when_861_in_hand():
    """92537402 si=47: after KO, do not seat dry Snorunt if 861 is in hand."""
    from cg.api import SelectContext

    sno = _pkm(sp._CARDS["snorunt"])
    staryu = _pkm(sp._OC_STARYU)
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _player(
        bench=[sno, munk, staryu],
        hand=[NS(id=sp._OC_MEOWTH_EX), NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    luc = _pkm(678, hp=340, maxHp=340)
    luc.prizeValue = 3
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=luc, hand_n=4))
    sit = sp._compute_situation(obs)
    obs.select = NS(context=int(SelectContext.TO_ACTIVE), deck=[])
    pick_sno = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    pick_staryu = NS(type=OptionType.CARD, area=AreaType.BENCH, index=2, playerIndex=0)
    assert sp._dry_snorunt_to_active_illegal(obs, sit)
    assert sp._hard_rule_bonus(obs, pick_sno, sit) <= sp._ATTACH_ILLEGAL + 1e-6
    assert sp._hard_rule_bonus(obs, pick_staryu, sit) > sp._hard_rule_bonus(obs, pick_sno, sit)


def test_watered_snorunt_to_active_still_legal():
    """Watered egg may still come Active — not the dry-861 suicide."""
    from cg.api import SelectContext

    water = int(EnergyType.WATER)
    sno = _pkm(sp._CARDS["snorunt"], energies=[water])
    staryu = _pkm(sp._OC_STARYU)
    me = _player(
        bench=[sno, staryu],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(turn=6, my_index=0, me=me, opp=_player(active=_pkm(678, hp=340)))
    sit = sp._compute_situation(obs)
    obs.select = NS(context=int(SelectContext.TO_ACTIVE), deck=[])
    pick_sno = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    assert not (sp._dry_snorunt_to_active_illegal(obs, sit) and not sp._has_water_energy(sno))
    assert sp._hard_rule_bonus(obs, pick_sno, sit) > sp._ATTACH_ILLEGAL + 1e-6


def test_salvator_nested_evolves_to_bans_861():
    """92545897 si=106: Salvator EVOLVES_TO must not pick 861 onto dry Active."""
    from cg.api import SelectContext

    sno = _pkm(sp._CARDS["snorunt"])
    me = _player(
        active=sno,
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(turn=9, my_index=0, me=me, opp=_player(active=_pkm(678, hp=270)))
    sit = sp._compute_situation(obs)
    obs.select = NS(
        context=int(SelectContext.EVOLVES_TO),
        deck=[NS(id=sp._CARDS["mega_froslass_ex"])],
        effect=NS(id=sp.SALVATOR),
    )
    pick = NS(type=OptionType.CARD, index=0, area=AreaType.LOOKING, playerIndex=0)
    assert sp._salvator_lands_dry_active_861(obs, sit)
    assert sp._hard_rule_bonus(obs, pick, sit) <= sp._ATTACH_ILLEGAL + 1e-6


def test_starmie_dead_promote_fueled_861_switch_vs_three_prize():
    """海星阵亡 + 三奖对面 + 备战有水861 → 立刻替换，不 END。"""
    from cg.api import SelectContext

    water = int(EnergyType.WATER)
    fueled_861 = _pkm(sp._CARDS["mega_froslass_ex"], energies=[water])
    me = _player(
        active=_pkm(sp._MUNKIDORI_ID, hp=110),
        bench=[fueled_861],
        hand=[NS(id=sp._OC_SWITCH)],
    )
    luc = _pkm(678, hp=340, maxHp=340)
    luc.megaEx = True
    luc.prizeValue = 3
    opp = _player(active=luc, hand_n=6)
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    atk = NS(type=OptionType.ATTACK, attackId=1239)
    sit["select_options"] = [play, end, atk]
    assert sp._starmie_dead_promote_fueled_861_live(obs, sit)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, atk, sit) <= -sp._DOMINATE_OPEN_PATH
    obs.select = NS(context=int(SelectContext.TO_ACTIVE), deck=[])
    pick = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    sit["select_options"] = [pick]
    assert sp._hard_rule_bonus(obs, pick, sit) >= sp._DOMINATE_OPEN_PATH


def test_starmie_dead_promote_skips_dry_861_and_two_prize():
    """干 861 不补位；二奖对面不开这刀。"""
    water = int(EnergyType.WATER)
    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], energies=[])
    me_dry = _player(
        active=_pkm(sp._MUNKIDORI_ID, hp=110),
        bench=[dry_861],
        hand=[NS(id=sp._OC_SWITCH)],
    )
    luc = _pkm(678, hp=340, maxHp=340)
    luc.prizeValue = 3
    obs_dry = _obs(turn=8, my_index=0, me=me_dry, opp=_player(active=luc, hand_n=6))
    sit_dry = sp._compute_situation(obs_dry)
    assert not sp._starmie_dead_promote_fueled_861_live(obs_dry, sit_dry)

    fueled = _pkm(sp._CARDS["mega_froslass_ex"], energies=[water])
    me_2p = _player(
        active=_pkm(sp._MUNKIDORI_ID, hp=110),
        bench=[fueled],
        hand=[NS(id=sp._OC_SWITCH)],
    )
    two = _pkm(999, hp=200, maxHp=200)
    two.ex = True
    two.prizeValue = 2
    obs_2p = _obs(turn=8, my_index=0, me=me_2p, opp=_player(active=two, hand_n=4))
    sit_2p = sp._compute_situation(obs_2p)
    assert not sp._starmie_dead_promote_fueled_861_live(obs_2p, sit_2p)


def test_starmie_alive_does_not_force_promote_861():
    """海星还在场：补位刀不开（一击切仍走 FroslassCut）。"""
    water = int(EnergyType.WATER)
    me = _aggression_me(
        bench=[_pkm(sp._CARDS["mega_froslass_ex"], energies=[water])],
        hand=[NS(id=sp._OC_SWITCH)],
    )
    luc = _pkm(678, hp=340, maxHp=340)
    luc.prizeValue = 3
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=luc, hand_n=6))
    sit = sp._compute_situation(obs)
    assert not sp._starmie_dead_promote_fueled_861_live(obs, sit)


def test_draw66_closeout_ability_beats_jetting_when_offered():
    """Draw66Closeout: Run Away before Jetting under fueled must_close."""
    water = int(EnergyType.WATER)
    active = _pkm(
        sp._CARDS["mega_starmie_ex"],
        hp=280,
        maxHp=330,
        energies=[water],
    )
    dud = _pkm(sp._CARDS["dudunsparce"])
    me = _aggression_me(active=active, bench=[dud])
    opp = _player(active=_pkm(900, hp=80))
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    ab = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [ab, jet]
    assert sp._dudunsparce_ability_offered(obs, sit)
    assert sp._hard_rule_bonus(obs, ab, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH


def test_draw66_after_evolve_paths_ability_outside_must_close():
    """进66后抽: dry Mega (no must_close) still PATH Run Away over END."""
    dud = _pkm(sp._CARDS["dudunsparce"])
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"]),  # dry → not must_attack
        bench=[dud],
        hand=[],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    ab = NS(type=OptionType.ABILITY, area=AreaType.BENCH, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [ab, end]
    assert sp._hard_rule_bonus(obs, ab, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH


def test_opening_play_munk_when_mega_secured():
    # Mega on field but dry (not must-attack) — secured for Munk seat PATH.
    # HandQual: dry Mega digs water before Munk; Meowth cycle must be closed;
    # hold water so acquire targets Munk (not WATER_BASIC).
    water = int(EnergyType.WATER)
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"]),
        bench=[_pkm(sp._CARDS["meowth_ex"])],
        hand=[
            NS(id=sp._MUNKIDORI_ID),
            NS(id=sp._CARDS["snorunt"]),
            NS(id=water),
        ],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_munk = NS(type=OptionType.PLAY, index=0)
    play_egg = NS(type=OptionType.PLAY, index=1)
    sit["select_options"] = [play_munk, play_egg]
    assert sit["turn_plan"].acquire.targets == (sp._MUNKIDORI_ID,)
    assert sp._hard_rule_bonus(obs, play_munk, sit) >= sp._DOMINATE_OPEN_PATH - 30.0 - 1e-6
    assert sp._hard_rule_bonus(obs, play_munk, sit) > sp._hard_rule_bonus(obs, play_egg, sit)


def test_opening_play_munk_no_boost_before_mega_secured():
    me = _player(
        active=_pkm(sp._CARDS["staryu"], energies=[int(EnergyType.WATER)]),
        hand=[NS(id=sp._MUNKIDORI_ID), NS(id=sp._CARDS["snorunt"])],
    )
    obs = _obs(turn=3, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_munk = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, play_munk, sit) < sp._DOMINATE_OPEN_PATH - 30.0 - 1e-6


def test_opening_attach_dark_when_munk_already_seated():
    dark = 7
    me = _player(
        active=_pkm(sp._CARDS["staryu"], energies=[int(EnergyType.WATER)]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=dark)],
    )
    me.energyAttached = False
    obs = _obs(turn=2, my_index=0, me=me, opp=_player(active=_pkm(999)), first_player=1)
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    assert sp._hard_rule_bonus(obs, attach, sit) >= sp._DOMINATE_OPEN_PATH - 20.0 - 1e-6


def test_opening_dark_yields_to_water_on_dry_staryu():
    water = int(EnergyType.WATER)
    dark = 7
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=water), NS(id=dark)],
    )
    obs = _obs(turn=3, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    attach_dark = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
        handIndex=1,
        index=1,
    )
    assert sp._hard_rule_bonus(obs, attach_dark, sit) <= -sp._DOMINATE_MID + 1e-6


def test_protected_staryu_bans_switch_to_munk():
    me = _player(
        active=_pkm(sp._CARDS["staryu"], energies=[int(EnergyType.WATER)]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=1123), NS(id=sp._CARDS["mega_starmie_ex"])],
    )
    obs = _obs(turn=3, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, switch, sit) < 0


def test_boss_path_after_mega_secured_without_attack_debt():
    from dataclasses import replace

    me = _aggression_me(hand=[NS(id=sp._BOSS_ID)])
    opp = _player(active=_pkm(900, hp=200), bench=[_pkm(901, hp=110)])
    obs = _obs(turn=6, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    hand = sit.get("hand")
    assert hand is not None
    sit["hand"] = replace(
        hand, gust_target_on_opp_bench=True, gust_target_koable=True, has_boss=True,
    )
    plan = sit.get("turn_plan")
    if plan is not None:
        sit["turn_plan"] = replace(
            plan,
            combat=replace(
                plan.combat,
                attack_required=False,
                required_before_attack=(),
                expected_prize_delta=max(1, int(plan.combat.expected_prize_delta or 0)),
            ),
        )
    play_boss = NS(type=OptionType.PLAY, index=0)
    score = sp._boss_after_mega_hard_bonus(
        obs, play_boss, sit, 0, sit["board"], sit["phase"], sit.get("turn_plan"),
    )
    assert score >= sp._DOMINATE_OPEN_PATH - 25.0 - 1e-6


# ── Wave D: Mega clock ──────────────────────────────────────────────────────

def test_wave_d_must_evolve_over_water_gun():
    """game_143 shape: Mega in hand + watered Staryu → EVOLVE, not Water Gun."""
    water = int(EnergyType.WATER)
    mega = NS(id=sp._CARDS["mega_starmie_ex"])
    me = _player(
        active=_pkm(sp._CARDS["staryu"], energies=[water]),
        hand=[mega, NS(id=water)],
    )
    # Going-second My-T2 (global turn 4, first_player=1).
    obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)), first_player=1)
    sit = sp._compute_situation(obs)
    assert sit["board"].my_turn_number >= 2
    assert sit["turn_plan"].facts.staryu_can_evolve
    evolve = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    gun = NS(type=OptionType.ATTACK, attackId=0)  # Water Gun / non-mega
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        handIndex=1,
        index=1,
    )
    sit["select_options"] = [evolve, gun, attach]
    assert sp._hard_rule_bonus(obs, evolve, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, gun, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6
    assert sp._hard_rule_bonus(obs, attach, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_wave_d_promote_benched_staryu_over_snorunt():
    """game_011 shape: Snorunt Active, watered Staryu on bench → promote."""
    water = int(EnergyType.WATER)
    me = _player(
        active=_pkm(sp._CARDS["snorunt"]),
        bench=[_pkm(sp._CARDS["staryu"], energies=[water])],
        hand=[NS(id=1123), NS(id=sp._CARDS["mega_starmie_ex"])],
    )
    obs = _obs(turn=3, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, index=0)
    attack = NS(type=OptionType.ATTACK, attackId=0)
    assert sp._hard_rule_bonus(obs, switch, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, attack, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_wave_d_ban_switch_off_fueled_mega():
    """D4: Active Mega+water must not Switch away before Jetting."""
    me = _aggression_me(hand=[NS(id=1123)], bench=[_pkm(sp._MUNKIDORI_ID)])
    opp = _player(active=_pkm(999))
    obs = _obs(turn=5, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, index=0)
    # must_attack_closeout / mega_clock both demote Switch off fueled Mega.
    assert sp._hard_rule_bonus(obs, switch, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_wave_d_opening_ban_munk_to_active_select():
    """OPENING without Mega secured: do not select Munk into Active."""
    from cg.api import SelectContext

    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=1123)],
    )
    obs = _obs(turn=2, my_index=0, me=me, opp=_player(active=_pkm(999)), first_player=1)
    obs.select = NS(context=int(SelectContext.SWITCH), deck=[])
    sit = sp._compute_situation(obs)
    pick_munk = NS(
        type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0,
    )
    assert sp._hard_rule_bonus(obs, pick_munk, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


# ── P0 Crispin wrong-color / HR-E1 water refill (Kaggle 91350842) ─────────────

def test_crispin_to_hand_pockets_dark_when_dry_mega_needs_water():
    """91350842 si=29: pocket Dark so ATTACH_TO can fuel Mega with Water."""
    from cg.api import SelectContext

    water, dark = 3, 7
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"]),
        hand=[NS(id=dark)],
    )
    obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)))
    deck = [NS(id=water), NS(id=dark), NS(id=water)]
    obs.select = NS(
        context=int(SelectContext.TO_HAND),
        deck=deck,
        effect=NS(id=sp.CRISPIN),
        minCount=0,
        maxCount=1,
    )
    sit = sp._compute_situation(obs)
    pick_water = NS(type=OptionType.CARD, area=AreaType.DECK, index=0, playerIndex=0)
    pick_dark = NS(type=OptionType.CARD, area=AreaType.DECK, index=1, playerIndex=0)
    assert sp._hard_rule_bonus(obs, pick_dark, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, pick_water, sit) <= -sp._DOMINATE_MID + 1e-6
    assert sp._hard_rule_bonus(obs, pick_dark, sit) > sp._hard_rule_bonus(
        obs, pick_water, sit
    )


def test_hr_e1_allows_water_refill_on_mega_with_dark_only():
    """After wrong-color lock, MAIN Water attach must beat END (Jetting unlock)."""
    water, dark = 3, 7
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=[dark]),
        hand=[NS(id=water)],
    )
    me.energyAttached = False
    obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    attach_water = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    end = NS(type=OptionType.END)
    assert sp._attach_hard_ban_bonus(obs, attach_water, 0) == sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, attach_water, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, attach_water, sit) > sp._hard_rule_bonus(
        obs, end, sit
    )


def test_hr_e1_still_bans_second_non_water_on_mega():
    water, dark = 3, 7
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=[water]),
        hand=[NS(id=dark)],
    )
    obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)))
    attach_dark = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    assert sp._attach_hard_ban_bonus(obs, attach_dark, 0) == sp._ATTACH_ILLEGAL


# ── NoPathDark-V1: Munk dry → Crispin / ATTACH_DARK before Poffin ────────────

def _nopath_dark_board(hand, discard=None, munk_energies=None):
    """Mega on bench (not Active) so must_close/Jetting does not own the turn."""
    water = int(EnergyType.WATER)
    mega = _pkm(sp._CARDS["mega_starmie_ex"], energies=[water])
    munk = _pkm(sp._MUNKIDORI_ID, energies=munk_energies or [])
    # Active side piece — not a fueled Mega attack seat.
    return _player(
        active=_pkm(sp._CARDS["snorunt"]),
        bench=[mega, munk],
        hand=hand,
        discard=discard or [],
    )


def test_nopath_dark_crispin_beats_poffin():
    """91402412 shape: post-Mega Munk dry, Crispin+Poffin → Crispin wins."""
    crispin, poffin = sp.CRISPIN, sp._OC_POFFIN
    me = _nopath_dark_board([NS(id=crispin), NS(id=poffin)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_crispin = NS(type=OptionType.PLAY, index=0)
    play_poffin = NS(type=OptionType.PLAY, index=1)
    sc = sp._hard_rule_bonus(obs, play_crispin, sit)
    spf = sp._hard_rule_bonus(obs, play_poffin, sit)
    assert sc >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert spf <= -sp._DOMINATE_OPEN_PATH + 1e-6
    assert sc > spf


def test_nopath_dark_attach_beats_poffin_and_end():
    dark = int(EnergyType.DARKNESS)
    poffin = sp._OC_POFFIN
    me = _nopath_dark_board([NS(id=dark), NS(id=poffin)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=1,  # Munk
        handIndex=0,
        index=0,
    )
    play_poffin = NS(type=OptionType.PLAY, index=1)
    end = NS(type=OptionType.END)
    sa = sp._hard_rule_bonus(obs, attach, sit)
    assert sa >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert sa > sp._hard_rule_bonus(obs, play_poffin, sit)
    assert sa > sp._hard_rule_bonus(obs, end, sit)


def test_nopath_dark_ns_beats_poffin_when_dark_in_discard():
    ns_id, poffin = sp._OC_NIGHT_STRETCHER, sp._OC_POFFIN
    dark = int(EnergyType.DARKNESS)
    me = _nopath_dark_board(
        [NS(id=ns_id), NS(id=poffin)],
        discard=[NS(id=dark)],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_ns = NS(type=OptionType.PLAY, index=0)
    play_poffin = NS(type=OptionType.PLAY, index=1)
    assert sp._hard_rule_bonus(obs, play_ns, sit) > sp._hard_rule_bonus(
        obs, play_poffin, sit
    )


def test_nopath_dark_yields_when_munk_already_has_dark():
    """No false PATH on Crispin once Munk is oiled."""
    dark = int(EnergyType.DARKNESS)
    crispin, poffin = sp.CRISPIN, sp._OC_POFFIN
    me = _nopath_dark_board(
        [NS(id=crispin), NS(id=poffin)],
        munk_energies=[dark],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_crispin = NS(type=OptionType.PLAY, index=0)
    assert sp._no_path_dark_hard_bonus(obs, play_crispin, sit) == 0.0


def test_nopath_dark_crispin_beats_poffin_under_must_close():
    """Active fueled Mega + Munk dry: Crispin dig before Poffin/Jetting."""
    crispin, poffin = sp.CRISPIN, sp._OC_POFFIN
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _aggression_me(bench=[munk], hand=[NS(id=crispin), NS(id=poffin)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_crispin = NS(type=OptionType.PLAY, index=0)
    play_poffin = NS(type=OptionType.PLAY, index=1)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sc = sp._hard_rule_bonus(obs, play_crispin, sit)
    assert sc >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert sc > sp._hard_rule_bonus(obs, play_poffin, sit)
    assert sc > sp._hard_rule_bonus(obs, jet, sit)


def test_must_close_oiled_munk_jetting_beats_poffin():
    """91492165 T12/T14 shape: fueled Mega + oiled Munk → Jetting ≻ Poffin."""
    from opening_cards import POFFIN

    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID, energies=[dark])
    me = _aggression_me(bench=[munk], hand=[NS(id=POFFIN)])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=12, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    poffin = NS(type=OptionType.PLAY, index=0)
    sit["select_options"] = [jet, poffin]
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, poffin, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_must_close_attach_dark_beats_jetting_when_munk_dry():
    """Same-turn DP prep: ATTACH_DARK before Jetting when Munk dry (pre-Urgent policy)."""
    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _aggression_me(bench=[munk], hand=[NS(id=dark)])
    opp = _player(active=_pkm(999, hp=300))
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
        handIndex=0,
        index=0,
    )
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [attach, jet]
    assert sp._hard_rule_bonus(obs, attach, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


# ── GapParallel-V1: unreachable primary → secondary ─────────────────────────

def test_gap_parallel_falls_to_placer_when_dark_unreachable():
    """DIG_DARK open but no Crispin/NS; ruins in hand → PLAY_PLACER PATH > END."""
    ruins = sp._RISKY_RUINS
    me = _nopath_dark_board([NS(id=ruins)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    # Only ruins PLAY + END offered — dark dig not actionable.
    opts = [
        NS(type=OptionType.PLAY, index=0),
        NS(type=OptionType.END),
    ]
    sit["select_options"] = opts
    sit.pop("midgame_actionable", None)
    play_ruins = opts[0]
    end = opts[1]
    actionable = sp._midgame_actionable_gaps(obs, sit)
    assert "DIG_DARK" not in actionable
    assert "PLAY_PLACER" in actionable
    assert actionable[0] == "PLAY_PLACER"
    assert sp._hard_rule_bonus(obs, play_ruins, sit) >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_gap_parallel_yields_to_must_close_jetting():
    """Fueled Active Mega: gap-parallel must not outrank Jetting when no dark dig."""
    ruins = sp._RISKY_RUINS
    munk = _pkm(sp._MUNKIDORI_ID)
    me = _aggression_me(bench=[munk], hand=[NS(id=ruins)])
    # Already attached this turn → no Crispin dig seat; must_close owns attack.
    me.energyAttached = True
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    play_ruins = NS(type=OptionType.PLAY, index=0)
    # With energy attached and no dig tools, must_close should prefer Jetting.
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._gap_parallel_hard_bonus(obs, play_ruins, sit) == 0.0


# ── SeatMunk: post-Mega dig Munk (Pad) before Jetting ───────────────────────

def test_seatmunk_pad_beats_jetting_under_must_close():
    """Active fueled Mega, no Munk: Poké Pad dig ≻ Jetting."""
    from opening_cards import POKE_PAD

    me = _aggression_me(hand=[NS(id=POKE_PAD)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    pad = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [pad, jet]
    sit.pop("midgame_actionable", None)
    assert "DIG_MUNK" in (sit.get("turn_plan").midgame_open_gaps or ())
    sp_pad = sp._hard_rule_bonus(obs, pad, sit)
    sp_jet = sp._hard_rule_bonus(obs, jet, sit)
    assert sp_pad >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert sp_pad > sp_jet
    assert sp_jet <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_seatmunk_pad_nested_picks_munk():
    """Pad TO_HAND: Munk PATH over Snorunt when SeatMunk dig live."""
    from cg.api import SelectContext
    from opening_cards import POKE_PAD

    me = _aggression_me(hand=[NS(id=POKE_PAD)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    obs.select = NS(
        context=int(SelectContext.TO_HAND),
        deck=[NS(id=sp._CARDS["snorunt"]), NS(id=sp._MUNKIDORI_ID)],
        effect=NS(id=POKE_PAD),
    )
    sit = sp._compute_situation(obs)
    snorunt = NS(type=OptionType.CARD, index=0)
    munk = NS(type=OptionType.CARD, index=1)
    sit["select_options"] = [snorunt, munk]
    sit.pop("midgame_actionable", None)
    assert sp._hard_rule_bonus(obs, munk, sit) > sp._hard_rule_bonus(obs, snorunt, sit)
    assert sp._hard_rule_bonus(obs, munk, sit) >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6


def test_seatmunk_play_munk_still_beats_jetting_when_held():
    """Hand Munk: DpSeat PLAY ≻ Jetting (unchanged)."""
    me = _aggression_me(hand=[NS(id=sp._MUNKIDORI_ID)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_seatmunk_gap_parallel_pad_when_mega_not_attacking():
    """Mega on bench: GapParallel DIG_MUNK Pad ≻ END."""
    from opening_cards import POKE_PAD

    water = int(EnergyType.WATER)
    mega = _pkm(sp._CARDS["mega_starmie_ex"], energies=[water])
    me = _player(
        active=_pkm(sp._CARDS["snorunt"]),
        bench=[mega],
        hand=[NS(id=POKE_PAD)],
    )
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    opts = [NS(type=OptionType.PLAY, index=0), NS(type=OptionType.END)]
    sit["select_options"] = opts
    sit.pop("midgame_actionable", None)
    actionable = sp._midgame_actionable_gaps(obs, sit)
    assert "DIG_MUNK" in actionable
    assert actionable[0] == "DIG_MUNK"
    assert sp._hard_rule_bonus(obs, opts[0], sit) >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
    assert sp._hard_rule_bonus(obs, opts[1], sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_seatmunk_closeout_ignores_ultra_ball():
    """Jetting closer: Ultra Ball must not block Jetting in fueled closeout."""
    me = _aggression_me(hand=[NS(id=sp._OC_ULTRA_BALL)])
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    ub = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [ub, jet]
    sit.pop("midgame_actionable", None)
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, ub, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_dp_stall_draw_prefers_lillie_over_jetting():
    """DpStallDraw-V2: DP stalled + Lillie offered → redraw before Jetting closer."""
    me = _aggression_me(hand=[NS(id=sp.LILLIE)])
    obs = _obs(turn=6, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    sit.pop("midgame_actionable", None)
    assert sp._DP_STALL_DRAW_ENABLED
    assert sp._dp_stall_draw_live(obs, sit, sit.get("turn_plan"))
    assert sp._hard_rule_bonus(obs, play, sit) > sp._hard_rule_bonus(obs, jet, sit)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6


def test_dp_stall_draw_seated_munk_dry_prefers_lillie():
    """V2.1: Munk seated without Dark + Lillie → redraw before Jetting."""
    munk = _pkm(sp._MUNKIDORI_ID, energies=[])
    me = _aggression_me(hand=[NS(id=sp.LILLIE)], bench=[munk])
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    sit.pop("midgame_actionable", None)
    assert sit["board"].munkidori_on_field
    assert not sit["board"].munkidori_has_dark
    assert sp._dp_stall_draw_live(obs, sit, sit.get("turn_plan"))
    assert sp._hard_rule_bonus(obs, play, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_dp_stall_ghost_does_not_starve_jetting():
    """Autopsy 92357953: Lillie in hand but not offered → do not starve Jetting."""
    me = _aggression_me(hand=[NS(id=sp.LILLIE)])
    obs = _obs(turn=6, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    # Only Jetting offered — draw supporter is a ghost claim.
    sit["select_options"] = [jet]
    sit.pop("midgame_actionable", None)
    assert sp._dp_stall_draw_live(obs, sit, sit.get("turn_plan"))
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6


def test_seatmunk_pad_then_jetting_is_sequencing_not_mutex():
    """After Pad resolves (hand gains Munk), Jetting closer is available next."""
    me = _aggression_me(hand=[NS(id=sp._MUNKIDORI_ID)])
    # Simulate post-Pad: Munk in hand — seat prep, not dig.
    obs = _obs(turn=5, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    assert sp._hard_rule_bonus(obs, play, sit) > sp._hard_rule_bonus(obs, jet, sit)


# ── SeatSnorunt-V1: post-DP egg before Jetting under must_close ──────────────

def test_seatsnorunt_beats_jetting_under_must_close():
    """Fueled Mega + Munk/Dark + open bench + hand Snorunt → PLAY ≻ Jetting.

    3-prize Mega opposite so the Froslass second-attacker line is live.
    """
    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID, energies=[dark])
    me = _aggression_me(bench=[munk], hand=[NS(id=sp._CARDS["snorunt"])])
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(sp._OC_MEGA_STARMIE, hp=330)),
    )
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    assert sp._seat_snorunt_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    sp_play = sp._hard_rule_bonus(obs, play, sit)
    sp_jet = sp._hard_rule_bonus(obs, jet, sit)
    assert sp_play >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp_play > sp_jet
    assert sp_jet <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_seatsnorunt_yields_to_seatmunk_when_munk_missing():
    """No Munk yet: hand Munk still owns prep; Snorunt does not steal the seat."""
    me = _aggression_me(
        hand=[NS(id=sp._MUNKIDORI_ID), NS(id=sp._CARDS["snorunt"])],
    )
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play_munk = NS(type=OptionType.PLAY, index=0)
    play_sno = NS(type=OptionType.PLAY, index=1)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play_munk, play_sno, jet]
    assert not sp._seat_snorunt_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, play_munk, sit) > sp._hard_rule_bonus(obs, play_sno, sit)
    assert sp._hard_rule_bonus(obs, play_munk, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_seatsnorunt_silent_without_munk_dark():
    """Munk dry / missing → knife A off; Jetting still closes when no other prep."""
    me = _aggression_me(hand=[NS(id=sp._CARDS["snorunt"])])
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    assert not sp._seat_snorunt_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, play, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


# ── Evolve861Closeout-V1: egg+861 before Jetting / Active egg evolve ─────────

def test_evolve861_beats_jetting_under_must_close():
    """Fueled Mega + Munk/Dark + bench Snorunt + hand 861 → EVOLVE ≻ Jetting."""
    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID, energies=[dark])
    sno = _pkm(sp._CARDS["snorunt"])
    me = _aggression_me(
        bench=[munk, sno],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(sp._OC_MEGA_STARMIE, hp=330)),
    )
    sit = sp._compute_situation(obs)
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [evo, jet]
    assert sp._evolve_861_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    sp_evo = sp._hard_rule_bonus(obs, evo, sit)
    sp_jet = sp._hard_rule_bonus(obs, jet, sit)
    assert sp_evo >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp_evo > sp_jet
    assert sp_jet <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_active_snorunt_watered_paths_evolve():
    """HARVEST: watered Active Snorunt + 861 in hand → evolve-in-place."""
    water = int(EnergyType.WATER)
    me = _player(
        active=_pkm(sp._CARDS["snorunt"], energies=[water]),
        bench=[_pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    opp_act = _pkm(678, hp=150, maxHp=330)
    opp_act.ex = True
    opp_act.prizeValue = 3
    obs = _obs(turn=10, my_index=0, me=me, opp=_player(active=opp_act, hand_n=5))
    sit = sp._compute_situation(obs)
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [evo, end]
    assert sit["phase"].primary == "HARVEST"
    assert sp._froslass_continuity_live(obs, sit)
    assert sp._hard_rule_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, evo, sit) > sp._hard_rule_bonus(obs, end, sit)


def test_dry_active_snorunt_evolve_861_illegal():
    """Lucario 92537402/92538341: do not evolve dry Active Snorunt into 861."""
    water = int(EnergyType.WATER)
    me = _player(
        active=_pkm(sp._CARDS["snorunt"]),
        bench=[_pkm(sp._CARDS["mega_starmie_ex"], energies=[water])],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=_pkm(678, hp=330)))
    sit = sp._compute_situation(obs)
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [evo, end]
    assert not sp._froslass_continuity_live(obs, sit)
    assert sp._hard_rule_bonus(obs, evo, sit) <= sp._ATTACH_ILLEGAL + 1e-6
    assert sp._hard_rule_bonus(obs, end, sit) > sp._hard_rule_bonus(obs, evo, sit)


def test_seatsnorunt_without_munk_vs_three_prize():
    """861 factory does not wait for Munk: 3-prize + hand Snorunt ≻ Jetting."""
    me = _aggression_me(hand=[NS(id=sp._CARDS["snorunt"])])
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(sp._OC_MEGA_STARMIE, hp=330)),
    )
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [play, jet]
    assert sp._seat_snorunt_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, play, sit) > sp._hard_rule_bonus(obs, jet, sit)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6


def test_evolve861_without_munk_vs_three_prize():
    """861 factory: bench egg + 861 in hand, no Munk, still evolve ≻ Jetting."""
    sno = _pkm(sp._CARDS["snorunt"])
    me = _aggression_me(
        bench=[sno],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(sp._OC_MEGA_STARMIE, hp=330)),
    )
    sit = sp._compute_situation(obs)
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [evo, jet]
    assert sp._evolve_861_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, evo, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_fuel861_setup_vs_lucario_330():
    """Lucario 330: water bench 861 without a lethal gate (Abs Snow is 150)."""
    water = int(EnergyType.WATER)
    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], hp=300, maxHp=300, energies=[])
    me = _aggression_me(bench=[dry_861], hand=[NS(id=water)])
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(678, hp=330, maxHp=330)),
    )
    obs.current.energyAttached = False
    sit = sp._compute_situation(obs)
    assert sp._fuel_861_line_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    attach = NS(
        type=OptionType.ATTACH,
        area=AreaType.HAND,
        index=0,
        inPlayArea=int(AreaType.BENCH),
        inPlayIndex=0,
    )
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [attach, jet]
    assert sp._hard_rule_bonus(obs, attach, sit) > sp._hard_rule_bonus(obs, jet, sit)


def test_water_snorunt_before_evolve_when_861_held():
    """Factory order: attach water to Snorunt before evolving 861."""
    water = int(EnergyType.WATER)
    sno = _pkm(sp._CARDS["snorunt"])
    me = _aggression_me(
        bench=[sno],
        hand=[NS(id=water), NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    obs = _obs(
        turn=8,
        my_index=0,
        me=me,
        opp=_player(active=_pkm(678, hp=330, maxHp=330)),
    )
    obs.current.energyAttached = False
    sit = sp._compute_situation(obs)
    attach = NS(
        type=OptionType.ATTACH,
        area=AreaType.HAND,
        index=0,
        inPlayArea=int(AreaType.BENCH),
        inPlayIndex=0,
    )
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=1)
    sit["select_options"] = [attach, evo]
    assert sp._fuel_861_line_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    assert sp._hard_rule_bonus(obs, attach, sit) > sp._hard_rule_bonus(obs, evo, sit)


def test_salvator_banned_onto_dry_active_snorunt():
    """Lucario 92545897: Salvator would only land 861 on dry Active Snorunt."""
    me = _player(
        active=_pkm(sp._CARDS["snorunt"]),
        bench=[_pkm(sp._MUNKIDORI_ID)],
        hand=[NS(id=sp.SALVATOR)],
    )
    obs = _obs(turn=9, my_index=0, me=me, opp=_player(active=_pkm(678, hp=270)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [play, end]
    assert sp._hard_rule_bonus(obs, play, sit) <= sp._ATTACH_ILLEGAL + 1e-6
    assert sp._hard_rule_bonus(obs, end, sit) > sp._hard_rule_bonus(obs, play, sit)


def test_evolve861_does_not_beat_jetting_vs_dragapult_ban():
    """2-prize Dragapult: second Starmie, not a new 861 line (OHKO-proof)."""
    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID, energies=[dark])
    sno = _pkm(sp._CARDS["snorunt"])
    me = _aggression_me(
        bench=[munk, sno],
        hand=[NS(id=sp._CARDS["mega_froslass_ex"])],
    )
    opp_act = _pkm(121, hp=300, maxHp=320)
    opp_act.ex = True
    opp_act.prizeValue = 2
    obs = _obs(turn=8, my_index=0, me=me, opp=_player(active=opp_act, hand_n=4))
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].facts.ban_froslass_line
    assert sit["turn_plan"].gap.need_second_starmie
    assert not sit["turn_plan"].combat.froslass_build_allowed
    assert not sp._evolve_861_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0)
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [evo, jet]
    assert sp._hard_rule_bonus(obs, jet, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, evo, sit) < sp._hard_rule_bonus(obs, jet, sit)


def test_fuel861_attach_beats_jetting_when_abs_snow_lethal():
    """Fuel861Closeout: dry 861 + water when Absolute Snow KOs, Jetting cannot."""
    water = int(EnergyType.WATER)
    active = _pkm(
        sp._CARDS["mega_starmie_ex"], hp=280, maxHp=330, energies=[water],
    )
    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], hp=300, maxHp=300, energies=[])
    me = _aggression_me(
        active=active,
        bench=[dry_861],
        hand=[NS(id=int(EnergyType.WATER))],
    )
    # energyAttached false
    opp_act = _pkm(900, hp=140, maxHp=200)
    opp_act.ex = True
    opp_act.prizeValue = 2
    opp = _player(active=opp_act, hand_n=2)  # Resentful 100 < 140; Abs Snow 150 OK
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    obs.current.energyAttached = False
    sit = sp._compute_situation(obs)
    assert sp._fuel_861_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    attach = NS(
        type=OptionType.ATTACH,
        area=AreaType.HAND,
        index=0,
        inPlayArea=int(AreaType.BENCH),
        inPlayIndex=0,
    )
    jet = NS(type=OptionType.ATTACK, attackId=JETTING)
    sit["select_options"] = [attach, jet]
    assert sp._hard_rule_bonus(obs, attach, sit) >= sp._DOMINATE_OPEN_PATH - 1e-6
    assert sp._hard_rule_bonus(obs, jet, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6


def test_fuel861_water_to_861_not_staryu_when_active_munk():
    """Autopsy 92362767 t=58: Active Munk + dry 861 → water to 861 ≻ Staryu."""
    water = int(EnergyType.WATER)
    dark = int(EnergyType.DARKNESS)
    munk = _pkm(sp._MUNKIDORI_ID, energies=[dark])
    dry_861 = _pkm(sp._CARDS["mega_froslass_ex"], hp=300, maxHp=300, energies=[])
    staryu = _pkm(sp._CARDS["staryu"])
    me = _player(
        active=munk,
        bench=[dry_861, staryu],
        hand=[NS(id=water)],
    )
    opp_act = _pkm(sp._CARDS["mega_starmie_ex"], hp=20, maxHp=330)
    opp = _player(active=opp_act, hand_n=2)
    obs = _obs(turn=9, my_index=0, me=me, opp=opp)
    obs.current.energyAttached = False
    sit = sp._compute_situation(obs)
    assert sp._fuel_861_prep_live(obs, sit, sit["board"], sit["turn_plan"])
    to_861 = NS(
        type=OptionType.ATTACH, area=AreaType.HAND, index=0,
        inPlayArea=int(AreaType.BENCH), inPlayIndex=0,
    )
    to_staryu = NS(
        type=OptionType.ATTACH, area=AreaType.HAND, index=0,
        inPlayArea=int(AreaType.BENCH), inPlayIndex=1,
    )
    sit["select_options"] = [to_861, to_staryu]
    assert sp._hard_rule_bonus(obs, to_861, sit) > sp._hard_rule_bonus(obs, to_staryu, sit)


def test_froslass_cut_abs_snow_lethal_when_resentful_short():
    """Oneshot cut uses Absolute Snow 150 when Resentful is too low."""
    water = int(EnergyType.WATER)
    active = _pkm(
        sp._CARDS["mega_starmie_ex"], hp=280, maxHp=330, energies=[water],
    )
    fueled_861 = _pkm(
        sp._CARDS["mega_froslass_ex"], hp=300, maxHp=300, energies=[water],
    )
    me = _aggression_me(
        active=active, bench=[fueled_861], hand=[NS(id=sp._OC_SWITCH)],
    )
    opp_act = _pkm(900, hp=140, maxHp=200)
    opp_act.ex = True
    opp_act.prizeValue = 2
    opp = _player(active=opp_act, hand_n=2)  # Resentful=100 < 140
    obs = _obs(turn=8, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sp._froslass_oneshot_cut_live(obs, sit)


# ── HildaDig-V1 / GapSideBan-V1 ──────────────────────────────────────────────

def test_hilda_dig_1031_beats_861_beats_66():
    """Hilda TO_HAND: Mega Starmie ≻ Mega Froslass ≻ ban 66 when peers offered."""
    from cg.api import SelectContext

    # Force-enable for unit coverage (SHIP flag is off).
    prev = sp._HILDA_DIG_ENABLED
    sp._HILDA_DIG_ENABLED = True
    try:
        me = _aggression_me(hand=[NS(id=sp._CARDS["hilda"])])
        obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)))
        obs.select = NS(
            context=int(SelectContext.TO_HAND),
            deck=[
                NS(id=sp._CARDS["dudunsparce"]),
                NS(id=sp._CARDS["mega_froslass_ex"]),
                NS(id=sp._CARDS["mega_starmie_ex"]),
            ],
            effect=NS(id=sp._CARDS["hilda"]),
        )
        sit = sp._compute_situation(obs)
        c66 = NS(type=OptionType.CARD, index=0)
        c861 = NS(type=OptionType.CARD, index=1)
        c1031 = NS(type=OptionType.CARD, index=2)
        sit["select_options"] = [c66, c861, c1031]
        s66 = sp._hard_rule_bonus(obs, c66, sit)
        s861 = sp._hard_rule_bonus(obs, c861, sit)
        s1031 = sp._hard_rule_bonus(obs, c1031, sit)
        assert s1031 > s861 > s66
        assert s1031 >= sp._DOMINATE_OPEN_PATH + 30.0 - 1e-6
        assert s861 >= sp._DOMINATE_OPEN_PATH + 20.0 - 1e-6
        assert s66 <= -sp._DOMINATE_OPEN_PATH + 1e-6
    finally:
        sp._HILDA_DIG_ENABLED = prev


def test_hilda_dig_861_when_1031_absent_bans_66():
    """Autopsy 92295561 shape: {66,861} → 861; 66 demoted."""
    from cg.api import SelectContext

    prev = sp._HILDA_DIG_ENABLED
    sp._HILDA_DIG_ENABLED = True
    try:
        me = _aggression_me(hand=[NS(id=sp._CARDS["hilda"])])
        obs = _obs(turn=4, my_index=0, me=me, opp=_player(active=_pkm(999)))
        obs.select = NS(
            context=int(SelectContext.TO_HAND),
            deck=[NS(id=sp._CARDS["dudunsparce"]), NS(id=sp._CARDS["mega_froslass_ex"])],
            effect=NS(id=sp._CARDS["hilda"]),
        )
        sit = sp._compute_situation(obs)
        c66 = NS(type=OptionType.CARD, index=0)
        c861 = NS(type=OptionType.CARD, index=1)
        sit["select_options"] = [c66, c861]
        assert sp._hard_rule_bonus(obs, c861, sit) > sp._hard_rule_bonus(obs, c66, sit)
        assert sp._hard_rule_bonus(obs, c66, sit) <= -sp._DOMINATE_OPEN_PATH + 1e-6
    finally:
        sp._HILDA_DIG_ENABLED = prev


def test_gap_side_ban_rolled_back_silent():
    """GapSideBan-V1 disabled (mirror WR tax); hook returns 0."""
    duns = _pkm(65)  # DUNSPARCE_A
    me = _aggression_me(
        bench=[duns],
        hand=[NS(id=65)],
    )
    obs = _obs(turn=6, my_index=0, me=me, opp=_player(active=_pkm(999)))
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._GAP_SIDE_BAN_ENABLED is False
    assert sp._gap_side_basic_ban_bonus(obs, play, sit) == 0.0


def test_froslass_boss_play_beats_resentful_on_full_hp_second_attacker():
    """861 Active + fat hand: Boss the bench Mega Lucario before Resentful."""
    from cg.api import SelectContext

    boss = NS(id=sp._BOSS_ID)
    me = _harvest_me(hand=[boss], prize_n=5)
    lucario = _pkm(678, hp=340, maxHp=340)
    lucario.megaEx = True
    wall = _pkm(235, hp=60, maxHp=60)
    opp = _player(active=wall, bench=[lucario], hand_n=7)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "HARVEST"
    combat = sit["turn_plan"].combat
    assert combat.boss_target is not None
    assert combat.boss_target.card_id == 678
    play_boss = NS(type=OptionType.PLAY, index=0)
    resentful = NS(type=OptionType.ATTACK, attackId=RESENTFUL)
    sit["select_options"] = [play_boss, resentful]
    assert sp._hard_rule_bonus(obs, play_boss, sit) > sp._hard_rule_bonus(
        obs, resentful, sit
    )
    assert sp._hard_rule_bonus(obs, play_boss, sit) >= sp._DOMINATE_OPEN_PATH
    # Gust select: Lucario bench index 0 ≻ nothing else.
    obs.select = NS(context=int(SelectContext.SWITCH), deck=[])
    pick = NS(
        type=OptionType.CARD,
        playerIndex=1,
        area=AreaType.BENCH,
        index=0,
    )
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, pick, sit) >= sp._DOMINATE_OPEN_PATH


def test_froslass_resentful_when_no_better_boss_target():
    """Front is already the 3-prize Resentful KO — attack, do not Boss."""
    boss = NS(id=sp._BOSS_ID)
    me = _harvest_me(hand=[boss], prize_n=5)
    lucario = _pkm(678, hp=340, maxHp=340)
    lucario.megaEx = True
    opp = _player(active=lucario, bench=[_pkm(235, hp=60)], hand_n=7)
    obs = _obs(turn=10, my_index=0, me=me, opp=opp)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.boss_target is None
    play_boss = NS(type=OptionType.PLAY, index=0)
    resentful = NS(type=OptionType.ATTACK, attackId=RESENTFUL)
    sit["select_options"] = [play_boss, resentful]
    assert sp._hard_rule_bonus(obs, resentful, sit) > sp._hard_rule_bonus(
        obs, play_boss, sit
    )
