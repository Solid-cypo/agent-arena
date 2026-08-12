#!/usr/bin/env python3
"""T-C combat eval — opponent pool + loss-tag taxonomy aligned with the
online fade analysis (analysis_55115028_fade.json).

Per-game instrumentation (our side):
  boss plays + gust target quality, dead turns (attack legal but turn ended
  without attacking), prize timeline / prize_stuck, supporter plays, 66 line,
  861/Mega attacks. Losses get the same tags as the online taxonomy:
  no_effective_boss zero_boss(no_supporter ref) no_supporter no_attack
  no_mega no_861 861_no_fire dun_no_66 no_dun dud_no_ability prize_stuck

Usage:
  PYTHONPATH=submission_starmie:submission_starmie/pilot \
      python3 scripts/run_combat_eval.py --games 60 \
      --decks walrein_control,alakazam_main
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("PYTHONHASHSEED", "0")
os.environ.setdefault("RL_ENABLED", "1")
os.environ.setdefault("USE_HYBRID", "1")

from arena.deck import load_deck_csv  # noqa: E402
from arena.simulator import play_game  # noqa: E402
import arena.policy as policy_mod  # noqa: E402
import main as sub_main  # noqa: E402
import starmie_pilot as sp  # noqa: E402
from cg.api import AreaType, SelectContext  # noqa: E402
from turn_planner import discard_value  # noqa: E402
from opponent_roles import opponent_role  # noqa: E402

BOSS = 1182
BUDEW = 235
SUPPORTERS = {1182, 1198, 1213, 1225, 1227, 1229, 1189}
DUNSPARCE, DUDUNSPARCE = 65, 66
MEGA_STARMIE, MEGA_FROSLASS = 1031, 861
FROSLASS_104, MUNKIDORI = 104, 112
SNORUNT, STARYU = 860, 1030
DARK_ENERGIES = {7, 16, 17}  # dark basic / prism / ignition
ST_ATKS = {1487, 1488}
MF_ATKS = {1240, 1241}
ITCHY_POLLEN = 323
SEARCH_EFFECTS = {1086, 1097, 1121, 1152, 1189, 1225}
OPT_PLAY, OPT_ABILITY, OPT_ATTACK, OPT_CARD, OPT_END = 7, 10, 13, 3, 14
_UNEVOLVED_BASE_ROLES = frozenset({
    "MAIN_ATTACKER_BASE",
    "SECONDARY_ATTACKER_BASE",
    "ENGINE_BASE",
})


def _is_unevolved_base(card_id: int) -> bool:
    return opponent_role(card_id).role in _UNEVOLVED_BASE_ROLES


def _opp_unevolved_bases(opp: dict) -> list[tuple[int, int, int]]:
    """Return [(area_index_or_-1_active, card_id, hp), ...] for unevolved bases."""
    out: list[tuple[int, int, int]] = []
    for i, x in enumerate(opp.get("bench") or []):
        if not x:
            continue
        cid = _si(x.get("id"))
        if _is_unevolved_base(cid):
            out.append((i, cid, _si(x.get("hp"), 0)))
    return out


def _own_transferable_damage(me: dict) -> int:
    total = 0
    for x in (me.get("active") or []) + (me.get("bench") or []):
        if not x:
            continue
        mx = _si(x.get("maxHp"), 0)
        hp = _si(x.get("hp"), mx)
        total += max(0, mx - hp)
    return total


def _has_dark_munk(me: dict) -> bool:
    for x in (me.get("active") or []) + (me.get("bench") or []):
        if not x or _si(x.get("id")) != MUNKIDORI:
            continue
        ens = [_si(e) for e in (x.get("energies") or [])]
        if any(e in DARK_ENERGIES for e in ens):
            return True
    return False


def _si(x, d=0):
    try:
        return int(x)
    except Exception:
        return d


def _field_ids(p: dict) -> list[int]:
    return [
        _si((x or {}).get("id"))
        for x in (p.get("active") or []) + (p.get("bench") or [])
        if x
    ]


def _selected_card_id(obs_dict: dict, option: dict, my_index: int) -> int:
    idx = _si(option.get("index"), -1)
    select_deck = (obs_dict.get("select") or {}).get("deck") or []
    if 0 <= idx < len(select_deck) and select_deck[idx]:
        return _si(select_deck[idx].get("id"))
    players = (obs_dict.get("current") or {}).get("players") or [{}, {}]
    pi = _si(option.get("playerIndex"), my_index)
    player = players[pi] if 0 <= pi < len(players) else {}
    area = _si(option.get("area"), -1)
    zone = []
    if area == int(AreaType.HAND):
        zone = player.get("hand") or []
    elif area == int(AreaType.DISCARD):
        zone = player.get("discard") or []
    elif area == int(AreaType.BENCH):
        zone = player.get("bench") or []
    elif area == int(AreaType.ACTIVE):
        zone = player.get("active") or []
        idx = 0
    if 0 <= idx < len(zone) and zone[idx]:
        return _si(zone[idx].get("id"))
    return 0


def reset_agent() -> None:
    sp.reset_for_new_game()


def make_tags(g: dict) -> list[str]:
    tags = []
    # Primary Boss KPI: did we ever land a prize-advancing Boss?
    if g.get("effective_boss", 0) == 0:
        tags.append("no_effective_boss")
    # zero_boss kept as a reference tag only (not the main KPI).
    if g["boss"] == 0:
        tags.append("zero_boss")
    if g["sup"] == 0:
        tags.append("no_supporter")
    if g["st_atk"] + g["mf_atk"] == 0:
        tags.append("no_attack")
    if not g["ever_mega"]:
        tags.append("no_mega")
    if not g["ever_861"]:
        tags.append("no_861")
    if g["ever_861"] and g["mf_atk"] == 0:
        tags.append("861_no_fire")
    if not g["ever_dun"]:
        tags.append("no_dun")
    if g["ever_dun"] and g["evo66"] == 0:
        tags.append("dun_no_66")
    if g["evo66"] > 0 and g["abil66"] == 0:
        tags.append("dud_no_ability")
    if g["prize_stuck"]:
        tags.append("prize_stuck")
    return tags


def _bc_agent_for(deck_name: str):
    """BC opponent (pointer-BC from online replays) when weights exist."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from alak_bc import make_alak_bc_agent

    cand = ROOT / "data" / "opening_sft" / f"bc_{deck_name}.npz"
    if deck_name == "alakazam_main":
        cand = ROOT / "data" / "opening_sft" / "alak_bc_opponent.npz"
    if not cand.exists():
        raise FileNotFoundError(f"no BC weights for {deck_name}: {cand}")
    return make_alak_bc_agent(cand)


def run_pool(
    deck_names: list[str], n: int, seed0: int, out_dir: Path,
    bc_decks: set[str] | None = None,
) -> dict:
    deck_me = load_deck_csv(SUB / "deck.csv")
    agent0 = sub_main.agent
    all_games: list[dict] = []
    bc_decks = bc_decks or set()

    for deck_name in deck_names:
        deck_opp = load_deck_csv(ROOT / "data" / "decks" / f"{deck_name}.csv")
        if deck_name in bc_decks:
            opp_agent = _bc_agent_for(deck_name)
        else:
            opp_agent = policy_mod.make_agent(deck_opp, dict(policy_mod.DEFAULT_WEIGHTS))
        for i in range(n):
            game_seed = seed0 + i
            random.seed(game_seed)
            os.environ["GAME_SEED"] = str(game_seed)
            try:
                import numpy as np

                np.random.seed(game_seed % (2**32 - 1))
            except Exception:
                pass
            reset_agent()
            g = {
                "deck": deck_name,
                "i": i,
                "we_are_a": i % 2 == 0,
                "boss": 0,
                "boss_targets": [],  # (hp, koable_by_jetting)
                "effective_boss": 0,
                "ineffective_boss": 0,
                "boss_prize_deltas": [],
                "sup": 0,
                "st_atk": 0,
                "mf_atk": 0,
                "other_atk": 0,
                "evo66": 0,
                "abil66": 0,
                "ever_mega": False,
                "ever_861": False,
                "ever_dun": False,
                "ever_104": False,
                "ever_risky_ruins": False,
                "ever_damage_placer": False,
                "ever_munk": False,
                "ever_munk_dark": False,
                "dp_turn": 0,      # first my-turn with damage placer + Munk + dark
                "max_snorunt": 0,
                "max_staryu": 0,
                "h104": False,     # 104 ever seen in hand
                "d104": False,     # 104 ever seen in our discard
                "hmunk": False,    # munkidori ever in hand
                "dark_hand": 0,    # max dark basics seen in hand at once
                "dark_disc": 0,    # dark basics in discard (last frame)
                "dark_att": 0,     # max dark attached on our field at once
                "dead_turns": 0,
                "ready_mega_no_attack": 0,
                "base_attack_with_ready_mega": 0,
                "double_ko_opportunity": 0,
                "double_ko_attempt": 0,
                "double_ko_success": 0,
                "turns_without_attacker": 0,
                "search_target_checks": 0,
                "search_target_matches_goal": 0,
                "bad_ultra_ball_discard": 0,
                "dudunsparce_draw_good_hand": 0,
                "froslass_expected_prizes": [],
                "my_turns": 0,
                "prize_timeline": [],  # (my_turn, self_remaining, opp_remaining)
                "prize_stuck": False,
                "winner": None,
                "going_second": None,
                "opp_role_known": 0,
                "opp_role_seen": 0,
                "boss_target_matches_plan": 0,
                "boss_target_checks": 0,
                "rider_target_matches_plan": 0,
                "rider_target_checks": 0,
                "boss_grabs_rider": 0,
                "double_ko_prep_order_ok": 0,
                "double_ko_prep_checks": 0,
                # Combat KPIs: unevolved-base kill + prep skips
                "base_ko_opportunity": 0,
                "base_ko_aimed": 0,
                "base_ko_removed": 0,
                "base_ko_wrong_aim": 0,
                "base_ko_soft_aim": 0,
                "base_ko_soft_opportunity": 0,
                "base_ko_soft_removed": 0,
                "adrena_onto_base": 0,
                "adrena_live_frames": 0,
                "adrena_taken": 0,
                "adrena_skip_jet": 0,
                "place_ability_offered": 0,
                "place_ability_taken": 0,
                "place_skip_jet": 0,
                "budew_played": False,
                "budew_dispatched": False,  # PLAY or search-to-field
                "budew_on_field": False,
                "budew_itchy_turns": 0,
                "budew_lock_turns": 0,
                "oa_lock_done": False,
                "oa_lock_done_turn": 0,
            }
            tr = {
                "turn": -1,
                "saw_attack": False,
                "attacked": False,
                "ready_mega": False,
                "boss_pending": False,
                "boss_played_this_turn": False,
                "boss_prizes_at_play": None,
                "double_opp_seen_turn": -1,
                "double_attempt_prizes": None,
                "double_ko_success_this_turn": False,
                "last_prizes": 6,
                "dk_steps": [],
                "dk_required": (),
                "itchy_this_turn": False,
                "budew_active_this_turn": False,
                "jetting_this_turn": False,
                "base_ko_opp_this_turn": False,
                "base_ko_soft_opp_this_turn": False,
                "base_ko_aim_this_turn": False,
                "base_ko_wrong_aim_this_turn": False,
                "base_ko_soft_aim_this_turn": False,
                "adrena_onto_base_this_turn": False,
                "opp_base_ids_turn_start": frozenset(),
                "opp_base_count_turn_start": 0,
                "adrena_live_this_turn": False,
                "adrena_taken_this_turn": False,
                "place_offered_this_turn": False,
                "place_taken_this_turn": False,
            }

            def our(obs_dict, _g=g, _tr=tr):
                decision = agent0(obs_dict)
                try:
                    cur = obs_dict.get("current") or {}
                    mi = _si(cur.get("yourIndex"))
                    me = (cur.get("players") or [{}, {}])[mi]
                    opp = (cur.get("players") or [{}, {}])[1 - mi]
                    _tr["last_prizes"] = len(me.get("prize") or [])
                    sel = obs_dict.get("select") or {}
                    opts = sel.get("option") or []
                    ctx = _si(sel.get("context"), -1)
                    st = sp._LIVE_AGENT_STATE or {}
                    mt = _si(st.get("max_my_turn"))
                    plan = None
                    try:
                        obs_obj = sp.to_observation_class(obs_dict)
                        plan = (sp._LIVE_AGENT_STATE or {}).get("last_turn_plan")
                    except Exception:
                        pass

                    fp = _si(cur.get("firstPlayer"), -1)
                    if _g["going_second"] is None and fp in (0, 1):
                        _g["going_second"] = fp != mi

                    fid = _field_ids(me)
                    ready_mega = bool(plan and plan.combat.attack_required)
                    if plan is not None:
                        opp_targets = [
                            t
                            for t in ((plan.facts.opp_active,) + plan.facts.opp_bench)
                            if t is not None
                        ]
                        if opp_targets:
                            _g["opp_role_seen"] += len(opp_targets)
                            _g["opp_role_known"] += sum(
                                1 for t in opp_targets if t.known_role
                            )
                    if MEGA_STARMIE in fid:
                        _g["ever_mega"] = True
                    if MEGA_FROSLASS in fid:
                        _g["ever_861"] = True
                    if DUNSPARCE in fid or DUDUNSPARCE in fid:
                        _g["ever_dun"] = True
                    if FROSLASS_104 in fid:
                        _g["ever_104"] = True
                    stadium_ids = {
                        _si((card or {}).get("id"))
                        for card in (cur.get("stadium") or [])
                        if card
                    }
                    damage_placer = (
                        FROSLASS_104 in fid or 1260 in stadium_ids
                    )
                    if 1260 in stadium_ids:
                        _g["ever_risky_ruins"] = True
                    if damage_placer:
                        _g["ever_damage_placer"] = True
                    _g["max_snorunt"] = max(_g["max_snorunt"], fid.count(SNORUNT))
                    _g["max_staryu"] = max(_g["max_staryu"], fid.count(STARYU))
                    munk_dark = False
                    dark_att = 0
                    for x in (me.get("active") or []) + (me.get("bench") or []):
                        if not x:
                            continue
                        ens = [_si(e) for e in (x.get("energies") or [])]
                        dark_att += sum(1 for e in ens if e in DARK_ENERGIES)
                        if _si(x.get("id")) == MUNKIDORI:
                            _g["ever_munk"] = True
                            if any(e in DARK_ENERGIES for e in ens):
                                munk_dark = True
                    _g["dark_att"] = max(_g["dark_att"], dark_att)
                    if munk_dark:
                        _g["ever_munk_dark"] = True
                        if _g["dp_turn"] == 0 and damage_placer:
                            _g["dp_turn"] = max(1, mt)
                    hand_ids = [_si((c or {}).get("id")) for c in (me.get("hand") or [])]
                    disc_ids = [_si((c or {}).get("id")) for c in (me.get("discard") or [])]
                    if FROSLASS_104 in hand_ids:
                        _g["h104"] = True
                    if FROSLASS_104 in disc_ids:
                        _g["d104"] = True
                    if MUNKIDORI in hand_ids:
                        _g["hmunk"] = True
                    _g["dark_hand"] = max(_g["dark_hand"], hand_ids.count(7))
                    _g["dark_disc"] = disc_ids.count(7)

                    # turn boundary bookkeeping
                    if mt != _tr["turn"]:
                        if _tr["turn"] >= 1 and _tr["saw_attack"] and not _tr["attacked"]:
                            _g["dead_turns"] += 1
                        prizes_now = len(me.get("prize") or [])
                        if _tr["double_attempt_prizes"] is not None:
                            if _tr["double_attempt_prizes"] - prizes_now >= 2:
                                _g["double_ko_success"] += 1
                                _tr["double_ko_success_this_turn"] = True
                            _tr["double_attempt_prizes"] = None
                        if _tr["boss_played_this_turn"] and _tr["boss_prizes_at_play"] is not None:
                            delta = _tr["boss_prizes_at_play"] - prizes_now
                            _g["boss_prize_deltas"].append(delta)
                            if delta > 0 or _tr["double_ko_success_this_turn"]:
                                _g["effective_boss"] += 1
                            else:
                                _g["ineffective_boss"] += 1
                        if _tr["dk_required"]:
                            _g["double_ko_prep_checks"] += 1
                            req = [s for s in _tr["dk_required"] if s in ("ADRENA", "BOSS")]
                            seen = [s for s in _tr["dk_steps"] if s in ("ADRENA", "BOSS", "ATTACK")]
                            # Prefix of required prep must appear in order before ATTACK.
                            ok = True
                            cursor = 0
                            for step in req:
                                try:
                                    cursor = seen.index(step, cursor) + 1
                                except ValueError:
                                    ok = False
                                    break
                            if ok and "ATTACK" in seen:
                                _g["double_ko_prep_order_ok"] += 1
                        # Unevolved-base kill: opportunity / aim / removal after Jetting
                        if _tr["base_ko_opp_this_turn"]:
                            _g["base_ko_opportunity"] += 1
                            if _tr["base_ko_aim_this_turn"]:
                                _g["base_ko_aimed"] += 1
                            elif _tr["base_ko_soft_aim_this_turn"]:
                                _g["base_ko_soft_aim"] += 1
                            elif _tr["base_ko_wrong_aim_this_turn"]:
                                _g["base_ko_wrong_aim"] += 1
                            if _tr["adrena_onto_base_this_turn"]:
                                _g["adrena_onto_base"] += 1
                            start_n = _tr.get("opp_base_count_turn_start", 0)
                            now_n = len(_opp_unevolved_bases(opp))
                            if start_n > 0 and now_n < start_n:
                                _g["base_ko_removed"] += 1
                        elif _tr["base_ko_soft_opp_this_turn"]:
                            _g["base_ko_soft_opportunity"] += 1
                            if _tr["base_ko_soft_aim_this_turn"] or _tr["base_ko_aim_this_turn"]:
                                _g["base_ko_soft_aim"] += 1
                            if _tr["adrena_onto_base_this_turn"]:
                                _g["adrena_onto_base"] += 1
                            start_n = _tr.get("opp_base_count_turn_start", 0)
                            now_n = len(_opp_unevolved_bases(opp))
                            if start_n > 0 and now_n < start_n:
                                _g["base_ko_soft_removed"] += 1
                        if _tr["adrena_live_this_turn"]:
                            _g["adrena_live_frames"] += 1
                            if _tr["adrena_taken_this_turn"]:
                                _g["adrena_taken"] += 1
                            elif _tr["jetting_this_turn"]:
                                _g["adrena_skip_jet"] += 1
                        if _tr["place_offered_this_turn"]:
                            _g["place_ability_offered"] += 1
                            if _tr["place_taken_this_turn"]:
                                _g["place_ability_taken"] += 1
                            elif _tr["jetting_this_turn"]:
                                _g["place_skip_jet"] += 1
                        if _tr["itchy_this_turn"]:
                            _g["budew_itchy_turns"] += 1
                        if _tr["budew_active_this_turn"]:
                            _g["budew_lock_turns"] += 1
                        _tr["turn"] = mt
                        _tr["saw_attack"] = False
                        _tr["attacked"] = False
                        _tr["ready_mega"] = ready_mega
                        _tr["dk_steps"] = []
                        _tr["dk_required"] = ()
                        _tr["itchy_this_turn"] = False
                        _tr["budew_active_this_turn"] = False
                        _tr["boss_played_this_turn"] = False
                        _tr["boss_prizes_at_play"] = None
                        _tr["double_ko_success_this_turn"] = False
                        _tr["jetting_this_turn"] = False
                        _tr["base_ko_opp_this_turn"] = False
                        _tr["base_ko_soft_opp_this_turn"] = False
                        _tr["base_ko_aim_this_turn"] = False
                        _tr["base_ko_wrong_aim_this_turn"] = False
                        _tr["base_ko_soft_aim_this_turn"] = False
                        _tr["adrena_onto_base_this_turn"] = False
                        _tr["adrena_live_this_turn"] = False
                        _tr["adrena_taken_this_turn"] = False
                        _tr["place_offered_this_turn"] = False
                        _tr["place_taken_this_turn"] = False
                        # Snapshot opp unevolved bases for removal check next boundary
                        bases_now = _opp_unevolved_bases(opp)
                        _tr["opp_base_ids_turn_start"] = frozenset(
                            cid for _, cid, _ in bases_now
                        )
                        _tr["opp_base_count_turn_start"] = len(bases_now)
                        _g["my_turns"] = max(_g["my_turns"], mt)
                        if mt >= 1 and not ready_mega:
                            _g["turns_without_attacker"] += 1
                        _g["prize_timeline"].append(
                            (mt, len(me.get("prize") or []), len(opp.get("prize") or []))
                        )
                    else:
                        _tr["ready_mega"] = _tr["ready_mega"] or ready_mega

                    active_id = _si(((me.get("active") or [{}])[0] or {}).get("id"))
                    if BUDEW in fid:
                        _g["budew_on_field"] = True
                    if active_id == BUDEW:
                        _tr["budew_active_this_turn"] = True
                    # OA-LOCK: Active Budew + 104 + Munk+dark
                    if (
                        active_id == BUDEW
                        and FROSLASS_104 in fid
                        and munk_dark
                        and not _g["oa_lock_done"]
                    ):
                        _g["oa_lock_done"] = True
                        _g["oa_lock_done_turn"] = max(1, mt)

                    if (
                        plan is not None
                        and plan.combat.mode == "DOUBLE_KO"
                        and _tr["double_opp_seen_turn"] != mt
                    ):
                        _g["double_ko_opportunity"] += 1
                        _tr["double_opp_seen_turn"] = mt
                        _tr["dk_required"] = plan.combat.required_before_attack

                    if ctx == 0:
                        if any(_si(o.get("type")) == OPT_ATTACK for o in opts):
                            _tr["saw_attack"] = True
                        # Prep liveness: Adrena / Froslass place offered this MAIN
                        for o in opts:
                            if _si(o.get("type")) != OPT_ABILITY:
                                continue
                            area = _si(o.get("area"))
                            idx = _si(o.get("index"), -1)
                            src = 0
                            if area == 4:
                                src = _si(((me.get("active") or [{}])[0] or {}).get("id"))
                            elif area == 5:
                                b = me.get("bench") or []
                                if 0 <= idx < len(b):
                                    src = _si((b[idx] or {}).get("id"))
                            if src == MUNKIDORI and _has_dark_munk(me) and _own_transferable_damage(me) >= 10:
                                _tr["adrena_live_this_turn"] = True
                            if src == FROSLASS_104:
                                _tr["place_offered_this_turn"] = True

                    hand = me.get("hand") or []
                    offered_goal_ids = set()
                    if plan is not None and plan.acquire.targets:
                        offered_goal_ids = {
                            sp._card_option_id(obs_obj, oo, mi)
                            for oo in obs_obj.select.option
                        }.intersection(plan.acquire.targets)
                    effect = sel.get("effect") or {}
                    effect_id = _si(effect.get("id") or effect.get("cardId"))
                    if offered_goal_ids and effect_id in SEARCH_EFFECTS and ctx in (
                        int(SelectContext.TO_HAND),
                        int(SelectContext.TO_BENCH),
                        int(SelectContext.TO_FIELD),
                    ):
                        selected_ids = [
                            sp._card_option_id(obs_obj, obs_obj.select.option[d], mi)
                            for d in decision
                            if isinstance(d, int) and 0 <= d < len(opts)
                        ]
                        check_slots = min(len(selected_ids), len(offered_goal_ids))
                        _g["search_target_checks"] += check_slots
                        _g["search_target_matches_goal"] += min(
                            sum(
                                cid in plan.acquire.targets
                                or bool(
                                    (sp._LIVE_AGENT_STATE or {}).get(
                                        "last_turn_plan_matchup_override"
                                    )
                                )
                                for cid in selected_ids
                            ),
                            check_slots,
                        )
                    if (
                        plan is not None
                        and ctx == int(SelectContext.DISCARD)
                        and effect_id == 1121
                    ):
                        selected_ids = [
                            sp._card_option_id(obs_obj, obs_obj.select.option[d], mi)
                            for d in decision
                            if isinstance(d, int) and 0 <= d < len(opts)
                        ]
                        safe_available = sum(
                            discard_value(
                                sp._card_option_id(obs_obj, oo, mi), plan,
                            ) < 8_000
                            for oo in obs_obj.select.option
                        )
                        unavoidable = max(0, len(selected_ids) - safe_available)
                        protected_selected = sum(
                            discard_value(cid, plan) >= 8_000
                            for cid in selected_ids
                        )
                        _g["bad_ultra_ball_discard"] += max(
                            0, protected_selected - unavoidable,
                        )
                    for d in decision:
                        if not (isinstance(d, int) and 0 <= d < len(opts)):
                            continue
                        o = opts[d]
                        t = _si(o.get("type"))
                        if t == OPT_ATTACK:
                            _tr["attacked"] = True
                            aid = _si(o.get("attackId"))
                            active_id = _si(((me.get("active") or [{}])[0] or {}).get("id"))
                            if ready_mega and active_id not in (MEGA_STARMIE, MEGA_FROSLASS):
                                _g["base_attack_with_ready_mega"] += 1
                            if aid in ST_ATKS:
                                _g["st_atk"] += 1
                            elif aid in MF_ATKS:
                                _g["mf_atk"] += 1
                                if plan is not None:
                                    _g["froslass_expected_prizes"].append(
                                        plan.combat.expected_prizes
                                    )
                            else:
                                _g["other_atk"] += 1
                            if aid == ITCHY_POLLEN:
                                _tr["itchy_this_turn"] = True
                            if aid == 1487:
                                _tr["jetting_this_turn"] = True
                                # Hard window: Jetting splash alone (−50) can KO.
                                # Soft (51–80) needs Adrena same turn — counted via
                                # soft_aim / adrena_onto_base.
                                bases = _opp_unevolved_bases(opp)
                                if any(0 < hp <= 50 for _, _, hp in bases):
                                    _tr["base_ko_opp_this_turn"] = True
                                elif any(50 < hp <= 80 for _, _, hp in bases):
                                    _tr["base_ko_soft_opp_this_turn"] = True
                            if (
                                aid == 1487
                                and plan is not None
                                and plan.combat.mode == "DOUBLE_KO"
                            ):
                                _g["double_ko_attempt"] += 1
                                _tr["double_attempt_prizes"] = len(me.get("prize") or [])
                                _tr["dk_steps"].append("ATTACK")
                        elif t == OPT_PLAY:
                            idx = _si(o.get("index"), -1)
                            cid = (
                                _si((hand[idx] or {}).get("id"))
                                if 0 <= idx < len(hand)
                                else 0
                            )
                            if cid in SUPPORTERS:
                                _g["sup"] += 1
                            if cid == BOSS:
                                _g["boss"] += 1
                                _tr["boss_pending"] = True
                                _tr["boss_played_this_turn"] = True
                                _tr["boss_prizes_at_play"] = len(me.get("prize") or [])
                                if plan is not None and plan.combat.mode == "DOUBLE_KO":
                                    _tr["dk_steps"].append("BOSS")
                            if cid == BUDEW:
                                _g["budew_played"] = True
                                _g["budew_dispatched"] = True
                            if cid == 1097:  # Night Stretcher
                                _g["ns"] = _g.get("ns", 0) + 1
                        elif t == 9:  # EVOLVE
                            idx = _si(o.get("index"), -1)
                            cid = (
                                _si((hand[idx] or {}).get("id"))
                                if 0 <= idx < len(hand)
                                else 0
                            )
                            if cid == DUDUNSPARCE:
                                _g["evo66"] += 1
                        elif t == OPT_ABILITY:
                            area = _si(o.get("area"))
                            idx = _si(o.get("index"), -1)
                            src = 0
                            if area == 4:
                                src = _si(((me.get("active") or [{}])[0] or {}).get("id"))
                            elif area == 5:
                                b = me.get("bench") or []
                                if 0 <= idx < len(b):
                                    src = _si((b[idx] or {}).get("id"))
                            if src == MUNKIDORI and plan is not None and plan.combat.mode == "DOUBLE_KO":
                                _tr["dk_steps"].append("ADRENA")
                            if src == MUNKIDORI:
                                _tr["adrena_taken_this_turn"] = True
                            if src == FROSLASS_104:
                                _tr["place_taken_this_turn"] = True
                            if src == DUDUNSPARCE:
                                _g["abil66"] += 1
                                if (
                                    plan is not None
                                    and not plan.draw.allow_run_away_draw
                                    and not (sp._LIVE_AGENT_STATE or {}).get(
                                        "last_turn_plan_matchup_override"
                                    )
                                ):
                                    _g["dudunsparce_draw_good_hand"] += 1
                        elif t == OPT_CARD:
                            selected_cid = sp._card_option_id(
                                obs_obj, obs_obj.select.option[d], mi,
                            )
                            pi = _si(o.get("playerIndex"), mi)
                            idx = _si(o.get("index"), -1)
                            if (
                                plan is not None
                                and plan.combat.rider_target is not None
                                and pi != mi
                                and ctx in (
                                    int(SelectContext.DAMAGE),
                                    int(SelectContext.DAMAGE_COUNTER),
                                )
                            ):
                                _g["rider_target_checks"] += 1
                                if idx == plan.combat.rider_target.index:
                                    _g["rider_target_matches_plan"] += 1
                            # Jetting splash = DAMAGE; Adrena transfer = DAMAGE_COUNTER.
                            if (
                                pi != mi
                                and ctx == int(SelectContext.DAMAGE)
                            ):
                                b = opp.get("bench") or []
                                if 0 <= idx < len(b) and b[idx]:
                                    tcid = _si(b[idx].get("id"))
                                    thp = _si(b[idx].get("hp"), 0)
                                    if _is_unevolved_base(tcid):
                                        if 0 < thp <= 50:
                                            _tr["base_ko_aim_this_turn"] = True
                                        elif 0 < thp <= 80:
                                            _tr["base_ko_soft_aim_this_turn"] = True
                                        else:
                                            _tr["base_ko_wrong_aim_this_turn"] = True
                            if (
                                pi != mi
                                and ctx == int(SelectContext.DAMAGE_COUNTER)
                            ):
                                b = opp.get("bench") or []
                                if 0 <= idx < len(b) and b[idx]:
                                    tcid = _si(b[idx].get("id"))
                                    if _is_unevolved_base(tcid):
                                        _tr["adrena_onto_base_this_turn"] = True
                            if (
                                pi == mi
                                and selected_cid == BUDEW
                                and ctx in (
                                    int(SelectContext.TO_BENCH),
                                    int(SelectContext.TO_FIELD),
                                )
                            ):
                                _g["budew_dispatched"] = True
                            if _tr["boss_pending"] and pi != mi:
                                b = opp.get("bench") or []
                                if 0 <= idx < len(b) and b[idx]:
                                    hp = _si(b[idx].get("hp"), 0)
                                    _g["boss_targets"].append((hp, hp <= 120))
                                    if plan is not None and plan.combat.boss_target is not None:
                                        _g["boss_target_checks"] += 1
                                        if idx == plan.combat.boss_target.index:
                                            _g["boss_target_matches_plan"] += 1
                                        if (
                                            plan.combat.rider_target is not None
                                            and idx == plan.combat.rider_target.index
                                        ):
                                            _g["boss_grabs_rider"] += 1
                                _tr["boss_pending"] = False
                        elif (
                            t == 14
                            and plan is not None
                            and plan.combat.attack_required
                            and not _tr["attacked"]
                            and any(_si(x.get("type")) == OPT_ATTACK for x in opts)
                        ):
                            _g["ready_mega_no_attack"] += 1
                except Exception:
                    pass
                return decision

            if g["we_are_a"]:
                a, b, da, db = our, opp_agent, deck_me, deck_opp
            else:
                a, b, da, db = opp_agent, our, deck_opp, deck_me
            try:
                gr = play_game(a, b, da, db, max_steps=500)
                g["winner"] = getattr(gr, "winner", None)
            except Exception as e:
                g["error"] = str(e)[:200]
            if (
                tr["double_attempt_prizes"] is not None
                and tr["double_attempt_prizes"] - tr["last_prizes"] >= 2
            ):
                g["double_ko_success"] += 1
                tr["double_ko_success_this_turn"] = True
            # Flush Boss effectiveness for the final turn (no next-turn boundary).
            if tr["boss_played_this_turn"] and tr["boss_prizes_at_play"] is not None:
                delta = tr["boss_prizes_at_play"] - tr["last_prizes"]
                g["boss_prize_deltas"].append(delta)
                if delta > 0 or tr["double_ko_success_this_turn"]:
                    g["effective_boss"] += 1
                else:
                    g["ineffective_boss"] += 1
                tr["boss_played_this_turn"] = False
            # Flush combat KPIs for the final turn (no next-turn boundary).
            if tr["base_ko_opp_this_turn"]:
                g["base_ko_opportunity"] += 1
                if tr["base_ko_aim_this_turn"]:
                    g["base_ko_aimed"] += 1
                # Removal needs next-obs; skip on terminal flush.
            if tr["adrena_live_this_turn"]:
                g["adrena_live_frames"] += 1
                if tr["adrena_taken_this_turn"]:
                    g["adrena_taken"] += 1
                elif tr["jetting_this_turn"]:
                    g["adrena_skip_jet"] += 1
            if tr["place_offered_this_turn"]:
                g["place_ability_offered"] += 1
                if tr["place_taken_this_turn"]:
                    g["place_ability_taken"] += 1
                elif tr["jetting_this_turn"]:
                    g["place_skip_jet"] += 1
            g["we_win"] = g["winner"] == (0 if g["we_are_a"] else 1)

            # prize_stuck: reached <=2 remaining then >=3 my-turns without
            # taking another prize (and did not win)
            tl = g["prize_timeline"]
            stuck = False
            run_len = 0
            prev = None
            for _, self_rem, _ in tl:
                if self_rem <= 2:
                    if prev is not None and self_rem == prev:
                        run_len += 1
                        if run_len >= 3:
                            stuck = True
                    else:
                        run_len = 0
                    prev = self_rem
            g["prize_stuck"] = stuck and not g["we_win"]
            g["tags"] = make_tags(g) if not g["we_win"] else []
            all_games.append(g)
        w = sum(1 for x in all_games if x["deck"] == deck_name and x["we_win"])
        print(f"  {deck_name}: {w}/{n} wins", flush=True)

    # KPI
    from collections import Counter

    def _dp_stats(gs: list[dict]) -> dict:
        done = [g for g in gs if g["dp_turn"] > 0]
        return {
            "dp_rate": len(done) / max(1, len(gs)),
            "dp_turn_avg": (
                sum(g["dp_turn"] for g in done) / len(done) if done else 0.0
            ),
            "rate_104": sum(1 for g in gs if g["ever_104"]) / max(1, len(gs)),
            "rate_damage_placer": sum(
                1 for g in gs if g["ever_damage_placer"]
            ) / max(1, len(gs)),
            "rate_risky_ruins": sum(
                1 for g in gs if g["ever_risky_ruins"]
            ) / max(1, len(gs)),
            "rate_munk": sum(1 for g in gs if g["ever_munk"]) / max(1, len(gs)),
            "rate_munk_dark": sum(1 for g in gs if g["ever_munk_dark"])
            / max(1, len(gs)),
            "ns_per_game": sum(g.get("ns", 0) for g in gs) / max(1, len(gs)),
            "snorunt_gt2_share": sum(1 for g in gs if g["max_snorunt"] > 2)
            / max(1, len(gs)),
            "staryu_gt2_share": sum(1 for g in gs if g["max_staryu"] > 2)
            / max(1, len(gs)),
        }

    def _plan_stats(gs: list[dict]) -> dict:
        searches = sum(g["search_target_checks"] for g in gs)
        froslass_values = [
            value for g in gs for value in g["froslass_expected_prizes"]
        ]
        role_seen = sum(g.get("opp_role_seen", 0) for g in gs)
        boss_checks = sum(g.get("boss_target_checks", 0) for g in gs)
        rider_checks = sum(g.get("rider_target_checks", 0) for g in gs)
        prep_checks = sum(g.get("double_ko_prep_checks", 0) for g in gs)
        boss_plays = sum(g.get("boss", 0) for g in gs)
        boss_deltas = [d for g in gs for d in g.get("boss_prize_deltas", [])]
        gs2 = [g for g in gs if g.get("going_second")]
        gs1 = [g for g in gs if g.get("going_second") is False]
        return {
            "ready_mega_no_attack": sum(g["ready_mega_no_attack"] for g in gs),
            "base_attack_with_ready_mega": sum(
                g["base_attack_with_ready_mega"] for g in gs
            ),
            "double_ko_opportunity": sum(g["double_ko_opportunity"] for g in gs),
            "double_ko_attempt": sum(g["double_ko_attempt"] for g in gs),
            "double_ko_success": sum(g["double_ko_success"] for g in gs),
            "double_ko_rate": (
                sum(g["double_ko_success"] for g in gs)
                / max(1, sum(g["double_ko_opportunity"] for g in gs))
            ),
            "base_ko_opportunity": sum(g.get("base_ko_opportunity", 0) for g in gs),
            "base_ko_aimed": sum(g.get("base_ko_aimed", 0) for g in gs),
            "base_ko_removed": sum(g.get("base_ko_removed", 0) for g in gs),
            "base_ko_wrong_aim": sum(g.get("base_ko_wrong_aim", 0) for g in gs),
            "base_ko_soft_aim": sum(g.get("base_ko_soft_aim", 0) for g in gs),
            "base_ko_soft_opportunity": sum(g.get("base_ko_soft_opportunity", 0) for g in gs),
            "base_ko_soft_removed": sum(g.get("base_ko_soft_removed", 0) for g in gs),
            "adrena_onto_base": sum(g.get("adrena_onto_base", 0) for g in gs),
            "base_ko_aim_rate": (
                sum(g.get("base_ko_aimed", 0) for g in gs)
                / max(1, sum(g.get("base_ko_opportunity", 0) for g in gs))
            ),
            "base_ko_remove_rate": (
                sum(g.get("base_ko_removed", 0) for g in gs)
                / max(1, sum(g.get("base_ko_opportunity", 0) for g in gs))
            ),
            "base_ko_wrong_aim_rate": (
                sum(g.get("base_ko_wrong_aim", 0) for g in gs)
                / max(1, sum(g.get("base_ko_opportunity", 0) for g in gs))
            ),
            "base_ko_soft_remove_rate": (
                sum(g.get("base_ko_soft_removed", 0) for g in gs)
                / max(1, sum(g.get("base_ko_soft_opportunity", 0) for g in gs))
            ),
            "adrena_live_frames": sum(g.get("adrena_live_frames", 0) for g in gs),
            "adrena_taken": sum(g.get("adrena_taken", 0) for g in gs),
            "adrena_skip_jet": sum(g.get("adrena_skip_jet", 0) for g in gs),
            "adrena_take_rate": (
                sum(g.get("adrena_taken", 0) for g in gs)
                / max(1, sum(g.get("adrena_live_frames", 0) for g in gs))
            ),
            "place_ability_offered": sum(g.get("place_ability_offered", 0) for g in gs),
            "place_ability_taken": sum(g.get("place_ability_taken", 0) for g in gs),
            "place_skip_jet": sum(g.get("place_skip_jet", 0) for g in gs),
            "place_take_rate": (
                sum(g.get("place_ability_taken", 0) for g in gs)
                / max(1, sum(g.get("place_ability_offered", 0) for g in gs))
            ),
            "turns_without_attacker": sum(g["turns_without_attacker"] for g in gs),
            "search_target_matches_goal": (
                sum(g["search_target_matches_goal"] for g in gs) / max(1, searches)
            ),
            "search_target_checks": searches,
            "bad_ultra_ball_discard": sum(g["bad_ultra_ball_discard"] for g in gs),
            "dudunsparce_draw_good_hand": sum(
                g["dudunsparce_draw_good_hand"] for g in gs
            ),
            "froslass_expected_prizes": (
                sum(froslass_values) / len(froslass_values)
                if froslass_values else 0.0
            ),
            "opponent_role_coverage": (
                sum(g.get("opp_role_known", 0) for g in gs) / max(1, role_seen)
            ),
            "effective_boss_rate": (
                sum(g.get("effective_boss", 0) for g in gs) / max(1, boss_plays)
            ),
            "ineffective_boss_count": sum(g.get("ineffective_boss", 0) for g in gs),
            "boss_prize_delta_avg": (
                sum(boss_deltas) / len(boss_deltas) if boss_deltas else 0.0
            ),
            "boss_target_matches_plan": (
                sum(g.get("boss_target_matches_plan", 0) for g in gs)
                / max(1, boss_checks)
            ),
            "boss_target_checks": boss_checks,
            "rider_target_matches_plan": (
                sum(g.get("rider_target_matches_plan", 0) for g in gs)
                / max(1, rider_checks)
            ),
            "rider_target_checks": rider_checks,
            "boss_grabs_rider": sum(g.get("boss_grabs_rider", 0) for g in gs),
            "double_ko_prep_order_ok": (
                sum(g.get("double_ko_prep_order_ok", 0) for g in gs)
                / max(1, prep_checks)
            ),
            "double_ko_prep_checks": prep_checks,
            "win_rate_going_first": (
                sum(1 for g in gs1 if g["we_win"]) / max(1, len(gs1))
            ),
            "win_rate_going_second": (
                sum(1 for g in gs2 if g["we_win"]) / max(1, len(gs2))
            ),
            "budew_play_rate_going_second": (
                sum(1 for g in gs2 if g.get("budew_played")) / max(1, len(gs2))
            ),
            "budew_dispatch_rate_going_second": (
                sum(1 for g in gs2 if g.get("budew_dispatched") or g.get("budew_on_field"))
                / max(1, len(gs2))
            ),
            "budew_itchy_turns_avg_going_second": (
                sum(g.get("budew_itchy_turns", 0) for g in gs2) / max(1, len(gs2))
            ),
            "budew_lock_turns_avg_going_second": (
                sum(g.get("budew_lock_turns", 0) for g in gs2) / max(1, len(gs2))
            ),
            "oa_lock_done_rate_going_second": (
                sum(1 for g in gs2 if g.get("oa_lock_done")) / max(1, len(gs2))
            ),
            "oa_lock_by_t2_rate_going_second": (
                sum(
                    1
                    for g in gs2
                    if g.get("oa_lock_done") and g.get("oa_lock_done_turn", 99) <= 2
                )
                / max(1, len(gs2))
            ),
        }

    by_deck = {}
    for dn in deck_names:
        gs = [g for g in all_games if g["deck"] == dn]
        losses = [g for g in gs if not g["we_win"]]
        tagc = Counter(t for g in losses for t in g["tags"])
        by_deck[dn] = {
            "n": len(gs),
            "win_rate": sum(1 for g in gs if g["we_win"]) / max(1, len(gs)),
            "boss_per_game": sum(g["boss"] for g in gs) / max(1, len(gs)),
            "dead_turns_per_game": sum(g["dead_turns"] for g in gs) / max(1, len(gs)),
            "loss_tags": dict(tagc.most_common()),
            "losses": len(losses),
            **_dp_stats(gs),
            **_plan_stats(gs),
        }
    losses = [g for g in all_games if not g["we_win"]]
    tagc = Counter(t for g in losses for t in g["tags"])
    n_loss = max(1, len(losses))
    kpi = {
        "n": len(all_games),
        "win_rate": sum(1 for g in all_games if g["we_win"]) / max(1, len(all_games)),
        "losses": len(losses),
        "loss_tags": dict(tagc.most_common()),
        "no_effective_boss_share_of_losses": (
            tagc.get("no_effective_boss", 0) / n_loss
        ),
        "zero_boss_share_of_losses": tagc.get("zero_boss", 0) / n_loss,
        "dead_turns_per_game": sum(g["dead_turns"] for g in all_games)
        / max(1, len(all_games)),
        "boss_per_game": sum(g["boss"] for g in all_games) / max(1, len(all_games)),
        "boss_target_koable_rate": (
            sum(1 for g in all_games for _, ko in g["boss_targets"] if ko)
            / max(1, sum(len(g["boss_targets"]) for g in all_games))
        ),
        **_dp_stats(all_games),
        **_plan_stats(all_games),
        "by_deck": by_deck,
    }
    report = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(),
        "decks": deck_names,
        "kpi": kpi,
        "per_game": [
            {k: v for k, v in g.items() if k != "prize_timeline"} for g in all_games
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_bc" if bc_decks else ""
    out = out_dir / f"combat_eval{suffix}_n{len(all_games)}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print("KPI", json.dumps({k: v for k, v in kpi.items() if k != "by_deck"}, indent=2))
    print(
        "COMBAT",
        f"dk {kpi.get('double_ko_success', 0)}/{kpi.get('double_ko_opportunity', 0)}"
        f"={kpi.get('double_ko_rate', 0):.1%}",
        f"base_ko aim {kpi.get('base_ko_aimed', 0)}/{kpi.get('base_ko_opportunity', 0)}"
        f"={kpi.get('base_ko_aim_rate', 0):.1%}",
        f"rm {kpi.get('base_ko_removed', 0)}"
        f"={kpi.get('base_ko_remove_rate', 0):.1%}",
        f"wrong {kpi.get('base_ko_wrong_aim', 0)}"
        f" soft {kpi.get('base_ko_soft_aim', 0)}"
        f" adrena→base {kpi.get('adrena_onto_base', 0)}",
        f"place take {kpi.get('place_ability_taken', 0)}/{kpi.get('place_ability_offered', 0)}"
        f" skip_jet {kpi.get('place_skip_jet', 0)}",
        f"adrena take {kpi.get('adrena_taken', 0)}/{kpi.get('adrena_live_frames', 0)}"
        f" skip_jet {kpi.get('adrena_skip_jet', 0)}",
        flush=True,
    )
    for dn, v in by_deck.items():
        print(f"  [{dn}] win {v['win_rate']:.1%} boss/g {v['boss_per_game']:.2f} "
              f"dead/g {v['dead_turns_per_game']:.2f} "
              f"dp {v['dp_rate']:.1%}@T{v['dp_turn_avg']:.1f} "
              f"(placer {v['rate_damage_placer']:.0%} "
              f"[104 {v['rate_104']:.0%}/ruins {v['rate_risky_ruins']:.0%}] "
              f"munk+dark {v['rate_munk_dark']:.0%}) "
              f"dk {v.get('double_ko_rate', 0):.0%} "
              f"base_ko {v.get('base_ko_remove_rate', 0):.0%} "
              f"place_skip {v.get('place_skip_jet', 0)} "
              f"adrena_skip {v.get('adrena_skip_jet', 0)} "
              f"tags {v['loss_tags']}")
    print(f"wrote {out}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60, help="games per deck")
    ap.add_argument("--seed0", type=int, default=71_000)
    ap.add_argument("--decks", default="walrein_control,alakazam_main")
    ap.add_argument(
        "--bc", default="",
        help="comma list of decks to drive with BC opponents (needs bc_<deck>.npz)",
    )
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "opening_sft")
    args = ap.parse_args()
    run_pool([d.strip() for d in args.decks.split(",") if d.strip()], args.games,
             args.seed0, args.out_dir,
             bc_decks={d.strip() for d in args.bc.split(",") if d.strip()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
