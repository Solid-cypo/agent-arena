#!/usr/bin/env python3
"""T-C combat eval — opponent pool + loss-tag taxonomy aligned with the
online fade analysis (analysis_55115028_fade.json).

Per-game instrumentation (our side):
  boss plays + gust target quality, dead turns (attack legal but turn ended
  without attacking), prize timeline / prize_stuck, supporter plays, 66 line,
  861/Mega attacks. Losses get the same tags as the online taxonomy:
  zero_boss no_supporter no_attack no_mega no_861 861_no_fire dun_no_66
  no_dun dud_no_ability prize_stuck

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

os.environ.setdefault("RL_ENABLED", "1")
os.environ.setdefault("USE_HYBRID", "1")

from arena.deck import load_deck_csv  # noqa: E402
from arena.simulator import play_game  # noqa: E402
import arena.policy as policy_mod  # noqa: E402
import main as sub_main  # noqa: E402
import starmie_pilot as sp  # noqa: E402

BOSS = 1182
SUPPORTERS = {1182, 1198, 1213, 1225, 1227, 1229, 1189}
DUNSPARCE, DUDUNSPARCE = 65, 66
MEGA_STARMIE, MEGA_FROSLASS = 1031, 861
FROSLASS_104, MUNKIDORI = 104, 112
SNORUNT, STARYU = 860, 1030
DARK_ENERGIES = {7, 16, 17}  # dark basic / prism / ignition
ST_ATKS = {1487, 1488}
MF_ATKS = {1240, 1241}
OPT_PLAY, OPT_ABILITY, OPT_ATTACK, OPT_CARD = 7, 10, 13, 3


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


def reset_agent() -> None:
    sp.reset_for_new_game()


def make_tags(g: dict) -> list[str]:
    tags = []
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
            random.seed(seed0 + i)
            reset_agent()
            g = {
                "deck": deck_name,
                "i": i,
                "we_are_a": i % 2 == 0,
                "boss": 0,
                "boss_targets": [],  # (hp, koable_by_jetting)
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
                "ever_munk": False,
                "ever_munk_dark": False,
                "dp_turn": 0,      # first my-turn with 104(+861 ok) + munk + dark
                "max_snorunt": 0,
                "max_staryu": 0,
                "h104": False,     # 104 ever seen in hand
                "d104": False,     # 104 ever seen in our discard
                "hmunk": False,    # munkidori ever in hand
                "dark_hand": 0,    # max dark basics seen in hand at once
                "dark_disc": 0,    # dark basics in discard (last frame)
                "dark_att": 0,     # max dark attached on our field at once
                "dead_turns": 0,
                "my_turns": 0,
                "prize_timeline": [],  # (my_turn, self_remaining, opp_remaining)
                "prize_stuck": False,
                "winner": None,
            }
            tr = {
                "turn": -1,
                "saw_attack": False,
                "attacked": False,
                "boss_pending": False,
            }

            def our(obs_dict, _g=g, _tr=tr):
                decision = agent0(obs_dict)
                try:
                    cur = obs_dict.get("current") or {}
                    mi = _si(cur.get("yourIndex"))
                    me = (cur.get("players") or [{}, {}])[mi]
                    opp = (cur.get("players") or [{}, {}])[1 - mi]
                    sel = obs_dict.get("select") or {}
                    opts = sel.get("option") or []
                    ctx = _si(sel.get("context"), -1)
                    st = sp._LIVE_AGENT_STATE or {}
                    mt = _si(st.get("max_my_turn"))

                    fid = _field_ids(me)
                    if MEGA_STARMIE in fid:
                        _g["ever_mega"] = True
                    if MEGA_FROSLASS in fid:
                        _g["ever_861"] = True
                    if DUNSPARCE in fid or DUDUNSPARCE in fid:
                        _g["ever_dun"] = True
                    if FROSLASS_104 in fid:
                        _g["ever_104"] = True
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
                        if _g["dp_turn"] == 0 and FROSLASS_104 in fid:
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
                        _tr["turn"] = mt
                        _tr["saw_attack"] = False
                        _tr["attacked"] = False
                        _g["my_turns"] = max(_g["my_turns"], mt)
                        _g["prize_timeline"].append(
                            (mt, len(me.get("prize") or []), len(opp.get("prize") or []))
                        )

                    if ctx == 0:
                        if any(_si(o.get("type")) == OPT_ATTACK for o in opts):
                            _tr["saw_attack"] = True

                    hand = me.get("hand") or []
                    for d in decision:
                        if not (isinstance(d, int) and 0 <= d < len(opts)):
                            continue
                        o = opts[d]
                        t = _si(o.get("type"))
                        if t == OPT_ATTACK:
                            _tr["attacked"] = True
                            aid = _si(o.get("attackId"))
                            if aid in ST_ATKS:
                                _g["st_atk"] += 1
                            elif aid in MF_ATKS:
                                _g["mf_atk"] += 1
                            else:
                                _g["other_atk"] += 1
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
                            if src == DUDUNSPARCE:
                                _g["abil66"] += 1
                        elif t == OPT_CARD and _tr["boss_pending"]:
                            # Boss gust target on opp side
                            if _si(o.get("playerIndex"), mi) != mi:
                                b = opp.get("bench") or []
                                idx = _si(o.get("index"), -1)
                                if 0 <= idx < len(b) and b[idx]:
                                    hp = _si(b[idx].get("hp"), 0)
                                    _g["boss_targets"].append((hp, hp <= 120))
                                _tr["boss_pending"] = False
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
            "rate_munk": sum(1 for g in gs if g["ever_munk"]) / max(1, len(gs)),
            "rate_munk_dark": sum(1 for g in gs if g["ever_munk_dark"])
            / max(1, len(gs)),
            "ns_per_game": sum(g.get("ns", 0) for g in gs) / max(1, len(gs)),
            "snorunt_gt2_share": sum(1 for g in gs if g["max_snorunt"] > 2)
            / max(1, len(gs)),
            "staryu_gt2_share": sum(1 for g in gs if g["max_staryu"] > 2)
            / max(1, len(gs)),
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
        }
    losses = [g for g in all_games if not g["we_win"]]
    tagc = Counter(t for g in losses for t in g["tags"])
    n_loss = max(1, len(losses))
    kpi = {
        "n": len(all_games),
        "win_rate": sum(1 for g in all_games if g["we_win"]) / max(1, len(all_games)),
        "losses": len(losses),
        "loss_tags": dict(tagc.most_common()),
        "zero_boss_share_of_losses": tagc.get("zero_boss", 0) / n_loss,
        "dead_turns_per_game": sum(g["dead_turns"] for g in all_games)
        / max(1, len(all_games)),
        "boss_per_game": sum(g["boss"] for g in all_games) / max(1, len(all_games)),
        "boss_target_koable_rate": (
            sum(1 for g in all_games for _, ko in g["boss_targets"] if ko)
            / max(1, sum(len(g["boss_targets"]) for g in all_games))
        ),
        **_dp_stats(all_games),
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
    for dn, v in by_deck.items():
        print(f"  [{dn}] win {v['win_rate']:.1%} boss/g {v['boss_per_game']:.2f} "
              f"dead/g {v['dead_turns_per_game']:.2f} "
              f"dp {v['dp_rate']:.1%}@T{v['dp_turn_avg']:.1f} "
              f"(104 {v['rate_104']:.0%} munk+dark {v['rate_munk_dark']:.0%}) "
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
