#!/usr/bin/env python3
"""Decision-level probe: does the agent act on DP bottleneck states?

Per my-turn states:
  EGG   = 104 in hand, 104 not on field, spare Snorunt missing, bench open
  DARK  = Munkidori on field lacks dark, dark basic in hand, attach unused
Actions counted within those turns:
  EGG  -> PLAY Snorunt / Poffin / Pad, or select Snorunt TO_BENCH/TO_HAND
  DARK -> ATTACH dark onto Munkidori
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

import os
os.environ.setdefault("RL_ENABLED", "1")
os.environ.setdefault("USE_HYBRID", "1")

from arena.deck import load_deck_csv  # noqa: E402
from arena.simulator import play_game  # noqa: E402
import arena.policy as policy_mod  # noqa: E402
import main as sub_main  # noqa: E402
import starmie_pilot as sp  # noqa: E402

F104, SNORUNT, MUNK, MEGA_F = 104, 860, 112, 861
POFFIN, PAD, BALL = 1086, 1152, 1121
DARKS = {7, 16, 17}
OPT_PLAY, OPT_ATTACH, OPT_CARD, OPT_EVOLVE = 7, 8, 3, 9


def _si(x, d=0):
    try:
        return int(x)
    except Exception:
        return d


def main() -> int:
    deck_me = load_deck_csv(SUB / "deck.csv")
    deck_opp = load_deck_csv(ROOT / "data" / "decks" / "marnie_froslass_munk.csv")
    opp_agent = policy_mod.make_agent(deck_opp, dict(policy_mod.DEFAULT_WEIGHTS))
    agent0 = sub_main.agent

    tot = {
        "egg_turns": 0, "egg_acted": 0,
        "dark_turns": 0, "dark_acted": 0,
        "evo104_turns": 0, "evo104_acted": 0,
        "evo104_ban861": 0,
    }

    for i in range(40):
        random.seed(42_000 + i)
        sp.reset_for_new_game()
        tr = {"turn": -1, "egg": False, "dark": False, "evo": False,
              "egg_act": False, "dark_act": False, "evo_act": False,
              "sn_prev": False, "sn_now": False}

        def flush(_tr=tr, _tot=tot):
            if _tr["turn"] >= 1:
                if _tr["egg"]:
                    _tot["egg_turns"] += 1
                    _tot["egg_acted"] += 1 if _tr["egg_act"] else 0
                if _tr["dark"]:
                    _tot["dark_turns"] += 1
                    _tot["dark_acted"] += 1 if _tr["dark_act"] else 0
                if _tr["evo"]:
                    _tot["evo104_turns"] += 1
                    _tot["evo104_acted"] += 1 if _tr["evo_act"] else 0
                    if _tr.get("evo_ban861") and not _tr["evo_act"]:
                        _tot["evo104_ban861"] += 1

        def our(obs_dict, _tr=tr):
            decision = agent0(obs_dict)
            try:
                cur = obs_dict.get("current") or {}
                mi = _si(cur.get("yourIndex"))
                me = (cur.get("players") or [{}, {}])[mi]
                st = sp._LIVE_AGENT_STATE or {}
                mt = _si(st.get("max_my_turn"))
                if mt != _tr["turn"]:
                    flush()
                    _tr.update(turn=mt, egg=False, dark=False, evo=False,
                               egg_act=False, dark_act=False, evo_act=False,
                               sn_prev=_tr["sn_now"], sn_now=False,
                               evo_ban861=False)

                field = [x for x in (me.get("active") or []) + (me.get("bench") or []) if x]
                fids = [_si(x.get("id")) for x in field]
                hand = me.get("hand") or []
                hids = [_si((c or {}).get("id")) for c in hand]
                sn = fids.count(SNORUNT)
                need = 1 if MEGA_F in fids else 2
                bench_n = len([x for x in (me.get("bench") or []) if x])
                _tr["sn_now"] = _tr["sn_now"] or sn >= 1
                if (F104 in hids and F104 not in fids and sn < need
                        and bench_n < 5 and mt >= 2
                        and any(c in hids for c in (SNORUNT, POFFIN, PAD, BALL))):
                    _tr["egg"] = True
                post_open = 1031 in fids or MEGA_F in fids
                if (F104 in hids and F104 not in fids and sn >= 1 and mt >= 2
                        and _tr["sn_prev"] and post_open):
                    _tr["evo"] = True
                    if MEGA_F in hids and sn == 1 and MEGA_F not in fids:
                        _tr["evo_ban861"] = True
                munk_nodark = any(
                    _si(x.get("id")) == MUNK
                    and not any(_si(e) in DARKS for e in (x.get("energies") or []))
                    for x in field
                )
                if munk_nodark and 7 in hids and not me.get("energyAttached"):
                    _tr["dark"] = True

                sel = obs_dict.get("select") or {}
                opts = sel.get("option") or []
                for d in decision:
                    if not (isinstance(d, int) and 0 <= d < len(opts)):
                        continue
                    o = opts[d]
                    t = _si(o.get("type"))
                    if t == OPT_PLAY:
                        idx = _si(o.get("index"), -1)
                        cid = _si((hand[idx] or {}).get("id")) if 0 <= idx < len(hand) else 0
                        if cid in (SNORUNT, POFFIN, PAD, BALL):
                            _tr["egg_act"] = True
                    elif t == OPT_EVOLVE:
                        idx = _si(o.get("index"), -1)
                        cid = _si((hand[idx] or {}).get("id")) if 0 <= idx < len(hand) else 0
                        if cid == F104:
                            _tr["evo_act"] = True
                    elif t == OPT_ATTACH:
                        idx = _si(o.get("handIndex"), _si(o.get("index"), -1))
                        cid = _si((hand[idx] or {}).get("id")) if 0 <= idx < len(hand) else 0
                        if cid == 7:
                            _tr["dark_act"] = True
            except Exception:
                pass
            return decision

        a, b, da, db = (our, opp_agent, deck_me, deck_opp) if i % 2 == 0 else (
            opp_agent, our, deck_opp, deck_me)
        try:
            play_game(a, b, da, db, max_steps=500)
        except Exception:
            pass
        flush()

    print("EGG state turns:", tot["egg_turns"], " acted:", tot["egg_acted"],
          f"({tot['egg_acted']/max(1,tot['egg_turns']):.0%})")
    print("EVO104-possible turns (post-mega):", tot["evo104_turns"], " evolved:", tot["evo104_acted"],
          f"({tot['evo104_acted']/max(1,tot['evo104_turns']):.0%})",
          " ban861-blocked:", tot["evo104_ban861"])
    print("DARK state turns:", tot["dark_turns"], " attached:", tot["dark_acted"],
          f"({tot['dark_acted']/max(1,tot['dark_turns']):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
