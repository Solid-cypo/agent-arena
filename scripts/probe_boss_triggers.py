#!/usr/bin/env python3
"""Verify the C2a Boss trigger expansion actually fires in live games.

Spies on starmie_pilot internals to count, per decision point where the gust
flag ended up True, which trigger produced it:
  path   — original SP-BOSS-1 (opp bench ∩ prize_path)
  tempo/stuck — SP-BOSS-2/3 expansion (Active survives + bench KO-able, or
  prize_stuck relaxation)
Also counts games where each trigger appeared.
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

from arena.deck import load_deck_csv  # noqa: E402
from arena.simulator import play_game  # noqa: E402
import arena.policy as policy_mod  # noqa: E402
import main as sub_main  # noqa: E402
import starmie_pilot as sp  # noqa: E402


def main() -> int:
    deck_name = sys.argv[1] if len(sys.argv) > 1 else "lucario_fighting"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    # spy: remember the raw (path-based) gust result per _compute_situation call
    last = {"raw": False}
    orig_raw = sp._gust_target_on_opp_bench

    def spy_raw(obs, mi, ids):
        r = orig_raw(obs, mi, ids)
        last["raw"] = r
        return r

    sp._gust_target_on_opp_bench = spy_raw

    counts = {"path": 0, "tempo_or_stuck": 0}
    game_flags: set[str] = set()
    orig_build = sp.build_hand_context_from_obs

    def spy_build(obs, gust_target_on_opp_bench=False, **kw):
        if gust_target_on_opp_bench:
            if last["raw"]:
                counts["path"] += 1
                game_flags.add("path")
            else:
                counts["tempo_or_stuck"] += 1
                game_flags.add("expanded")
        return orig_build(
            obs, gust_target_on_opp_bench=gust_target_on_opp_bench, **kw
        )

    sp.build_hand_context_from_obs = spy_build

    deck_me = load_deck_csv(SUB / "deck.csv")
    deck_opp = load_deck_csv(ROOT / "data" / "decks" / f"{deck_name}.csv")
    opp = policy_mod.make_agent(deck_opp, dict(policy_mod.DEFAULT_WEIGHTS))

    g_path = g_exp = g_stuck = wins = 0
    for i in range(n):
        random.seed(71_000 + i)
        sp.reset_for_new_game()
        game_flags.clear()
        if i % 2 == 0:
            gr = play_game(sub_main.agent, opp, deck_me, deck_opp, max_steps=500)
            win = gr.winner == 0
        else:
            gr = play_game(opp, sub_main.agent, deck_opp, deck_me, max_steps=500)
            win = gr.winner == 1
        wins += win
        st = sp._LIVE_AGENT_STATE or {}
        pp = st.get("prize_progress") or {}
        if "path" in game_flags:
            g_path += 1
        if "expanded" in game_flags:
            g_exp += 1
        if pp.get("last", 6) <= 2:
            g_stuck += 1

    print(f"deck={deck_name} n={n} wins={wins}")
    print(f"decision points with gust flag: path={counts['path']} "
          f"expanded(tempo/stuck)={counts['tempo_or_stuck']}")
    print(f"games with path-gust={g_path}, with expanded-gust={g_exp}, "
          f"reached prize<=2: {g_stuck}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
