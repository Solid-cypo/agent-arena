"""Wave F expert-alignment: basic-attack ban, 861 gate, matchups, draw HOLD."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import OptionType
from hand_snapshot import build_board_snapshot
from opening_cards import (
    HILDA,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MUNKIDORI,
    SALVATOR,
    SNORUNT,
    STARYU,
    WATER_BASIC,
    hilda_evolution_priority,
)
from turn_planner import build_turn_plan, is_basic_attack_forbidden
import starmie_pilot as sp

DURALUDON = 169
ARCHALUDON_EX = 190
DARK = 7
ITCHY = 323


def _pkm(cid, hp=100, max_hp=None, energies=(), **kw):
    return NS(
        id=cid,
        hp=hp,
        maxHp=max_hp if max_hp is not None else hp,
        energies=list(energies),
        **kw,
    )


def _player(*, active=None, bench=(), hand=(), prizes=6, hand_count=None):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=cid) if isinstance(cid, int) else cid for cid in hand],
        discard=[],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs(me, opp=None, *, turn=3, my_index=0):
    opp = opp or _player(active=_pkm(999, hp=200), hand_count=2)
    return NS(
        current=NS(
            turn=turn,
            yourIndex=my_index,
            firstPlayer=0,
            stadium=[],
            players=[me, opp] if my_index == 0 else [opp, me],
        ),
        select=NS(context=0, deck=[], option=[]),
    )


def _plan(me, opp=None, *, turn=3, matchup=None):
    obs = _obs(me, opp, turn=turn)
    board = build_board_snapshot(obs)
    return build_turn_plan(obs, board, matchup=matchup)


def test_basic_attack_banned_when_mega_ready_to_land():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE, HILDA),
    )
    plan = _plan(me)
    assert plan.objective == "MAKE_ATTACKER" or "BASIC_ATTACK" in plan.forbidden_actions
    assert is_basic_attack_forbidden(STARYU, plan, attack_id=1)
    assert not is_basic_attack_forbidden(
        sp._BUDEW_ID, plan, attack_id=ITCHY,
    ) or plan.combat.attack_required


def test_snorunt_alone_does_not_allow_build_861():
    me = _player(active=_pkm(STARYU), bench=(_pkm(SNORUNT),))
    opp = _player(active=_pkm(900, hp=200), hand_count=2)
    plan = _plan(me, opp)
    assert not plan.combat.froslass_build_allowed
    assert "BUILD_861" in plan.forbidden_actions


def test_sole_861_attackable_allows_froslass():
    me = _player(active=_pkm(MEGA_FROSLASS, energies=(WATER_BASIC,)))
    opp = _player(active=_pkm(900, hp=200), hand_count=2)
    plan = _plan(me, opp)
    assert plan.combat.froslass_build_allowed
    assert plan.combat.attack_required


def test_archaludon_bans_froslass_line():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(active=_pkm(ARCHALUDON_EX, hp=300, ex=True), hand_count=4)
    plan = _plan(me, opp)
    assert plan.facts.ban_froslass_line
    assert not plan.combat.froslass_build_allowed


def test_dragapult_bans_froslass_line():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(active=_pkm(121, hp=300, ex=True), hand_count=4)
    plan = _plan(me, opp)
    assert plan.facts.opp_dragapult_threat
    assert plan.facts.ban_froslass_line
    assert not plan.combat.froslass_build_allowed


def test_dragapult_continuity_does_not_start_861_build():
    """2-prize Dragapult → second Starmie, not a new 861 line (OHKO-proof)."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK,)), _pkm(SNORUNT)),
        hand=(MEGA_FROSLASS, STARYU),
    )
    opp = _player(active=_pkm(121, hp=300, ex=True), hand_count=4)
    plan = _plan(me, opp)
    assert plan.facts.ban_froslass_line
    assert plan.facts.opp_attacker_prizes == 2
    assert not plan.combat.froslass_build_allowed
    assert plan.gap.need_second_starmie
    assert not plan.gap.need_second_attacker
    assert "PLAY_STARYU" in plan.midgame_open_gaps


def test_trevenant_bans_froslass_line():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(active=_pkm(879, hp=280), hand_count=5)
    plan = _plan(me, opp)
    assert plan.facts.opp_trevenant_threat
    assert plan.facts.ban_froslass_line
    assert not plan.gap.need_second_attacker


def test_lucario_allows_second_attacker_and_opens_861_window():
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(MEGA_FROSLASS, SNORUNT),
    )
    opp = _player(active=_pkm(678, hp=300, ex=True), hand_count=4)
    plan = _plan(me, opp)
    assert plan.facts.opp_lucario_threat
    assert not plan.facts.ban_froslass_line
    assert plan.gap.need_second_attacker
    assert plan.combat.froslass_build_allowed
    obs = _obs(me, opp)
    sit = sp._compute_situation(obs)
    assert sp._mega_froslass_window_open(
        obs, 0, sit["board"], sit["phase"], plan=sit["turn_plan"],
    )


def test_dp_surplus_does_not_open_861_after_surplus861Rev_rollback():
    """Gate FAIL on munk_dark — DP-ready alone must not sanction BUILD_861."""
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(104), _pkm(MUNKIDORI, energies=(DARK,))),
        hand=(MEGA_FROSLASS, SNORUNT),
    )
    opp = _player(active=_pkm(900, hp=280), hand_count=1)
    plan = _plan(me, opp)
    assert plan.facts.damage_placer_online
    assert plan.facts.munkidori_has_dark
    assert not plan.combat.froslass_build_allowed
    obs = _obs(me, opp)
    sit = sp._compute_situation(obs)
    assert sp._synergy_core_ready(sit["board"])
    assert not sp._mega_froslass_window_open(
        obs, 0, sit["board"], sit["phase"], plan=sit["turn_plan"],
    )


def test_861_prefers_max_damage_and_cuts_low_hand():
    """Resentful when hand≥4; Abs Snow KO keeps 861; low hand + no KO → cut."""
    assert sp._prefer_resentful(4)
    assert not sp._prefer_resentful(3)

    # Stay: Abs Snow can KO despite thin hand.
    me_stay = _player(
        active=_pkm(MEGA_FROSLASS, energies=(WATER_BASIC,)),
        bench=(_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),),
    )
    opp_ko = _player(active=_pkm(900, hp=140, ex=True), hand_count=2)
    obs_stay = _obs(me_stay, opp_ko)
    sit_stay = sp._compute_situation(obs_stay)
    assert sp._froslass_line_worth(obs_stay, 0, sit_stay["board"], sit_stay)
    assert not sp._starmie_promote_over_froslass(
        obs_stay, 0, sit_stay["board"], sit_stay,
    )

    # Cut: thin hand, no Abs Snow KO → switch to fueled Starmie.
    opp_fat = _player(active=_pkm(900, hp=280, ex=True), hand_count=2)
    obs_cut = _obs(me_stay, opp_fat)
    sit_cut = sp._compute_situation(obs_cut)
    assert not sp._froslass_line_worth(obs_cut, 0, sit_cut["board"], sit_cut)
    assert sp._starmie_promote_over_froslass(
        obs_cut, 0, sit_cut["board"], sit_cut,
    )


def test_alakazam_matchup_bans_froslass_line():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(active=_pkm(743, hp=300), hand_count=4)
    plan = _plan(me, opp, matchup="alakazam")
    assert plan.facts.ban_froslass_line
    assert not plan.combat.froslass_build_allowed


def test_opp_munk_dp_bans_froslass_line():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(
        active=_pkm(MUNKIDORI, energies=(DARK,)),
        bench=(_pkm(104),),
        hand_count=4,
    )
    plan = _plan(me, opp)
    assert plan.facts.opp_munk_dp_online
    assert plan.facts.ban_froslass_line


def test_make_attacker_demotes_side_basic_play():
    # No Mega in hand yet — dig tools beat seating Munk before the Staryu line is secured.
    me = _player(
        active=_pkm(65),  # Dunsparce wall, no Staryu online
        hand=(MUNKIDORI, SALVATOR, WATER_BASIC),
    )
    obs = _obs(me)
    sit = sp._compute_situation(obs)
    play_munk = NS(type=OptionType.PLAY, index=0)
    play_salv = NS(type=OptionType.PLAY, index=1)
    assert sit["turn_plan"].objective == "MAKE_ATTACKER"
    assert sp._hard_rule_bonus(obs, play_munk, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, play_salv, sit) >= sp._DOMINATE_OPEN


def test_hilda_not_ready_does_not_lead_with_861():
    prio = hilda_evolution_priority(mega_ready=False)
    assert prio[0] != MEGA_FROSLASS
    assert prio[-1] == MEGA_FROSLASS


def test_draw_hold_when_mega_path_live():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE, WATER_BASIC),
        bench=(_pkm(65),),
    )
    plan = _plan(me)
    assert not plan.draw.allow_run_away_draw


def test_post_mega_66_allows_draw_when_hand_cannot_seat():
    """66 online + Mega on bench + cannot dispatch + no seatable → Run Away."""
    from opening_cards import BOSS_ORDERS

    me = _player(
        active=_pkm(MUNKIDORI),
        bench=(
            _pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
            _pkm(66),
        ),
        hand=(BOSS_ORDERS,),
    )
    me.energyAttached = True  # cannot attach for retreat → no dispatch
    plan = _plan(me)
    assert plan.facts.mega_starmie_on_field
    assert not plan.combat.attack_required
    assert plan.draw.allow_run_away_draw
    assert "post-mega 66" in plan.draw.reason


def test_post_mega_seat_munk_beats_end():
    """OL-E2: dry Mega online + Munk in hand → PLAY ≻ END (not must-close)."""
    me = _player(
        active=_pkm(MEGA_STARMIE),  # dry — not attack_required
        hand=(MUNKIDORI,),
    )
    obs = _obs(me)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    sit["select_options"] = [play, end]
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN_PATH - 1.0
    assert sp._hard_rule_bonus(obs, end, sit) <= -sp._DOMINATE_OPEN_PATH + 1.0
