"""Local cabt-engine audit for the RL opening proposer (A/B + takeover).

Runs two passes through the real cabt engine vs a generic baseline:
  A) RL proposer ENABLED (the deployed config)
  B) RL proposer DISABLED (v1 pilot only — gold-rule cleanup still applies)

and compares W/L plus OPENING completion rate (the metric the RL policy
actually targets). The engine's BattleStart takes no seed, so deals differ
between games/pass; we rely on a large-N aggregate. Also reports the RL
takeover breakdown from starmie_pilot.RL_STATS for pass A.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.simulator import play_game  # noqa: E402
from arena.deck import load_deck_csv  # noqa: E402
import arena.policy as policy_mod  # noqa: E402

import main as sub_main  # noqa: E402
import starmie_pilot  # noqa: E402


def _reset_stats():
    for k in starmie_pilot.RL_STATS:
        starmie_pilot.RL_STATS[k] = 0
    starmie_pilot.RL_KIND_STATS["blocked"].clear()
    starmie_pilot.RL_KIND_STATS["nomatch"].clear()


def _run_pass(starmie_agent, base_agent, deck_a, deck_b, weights, n, max_steps):
    wins = losses = draws = 0
    opening_completed = 0
    for i in range(n):
        starmie_pilot.reset_for_new_game()
        if i % 2 == 0:
            g = play_game(starmie_agent, base_agent, deck_a, deck_b,
                          weights_a=weights, weights_b=policy_mod.DEFAULT_WEIGHTS,
                          max_steps=max_steps)
            r = g.reward_for_a
        else:
            g = play_game(base_agent, starmie_agent, deck_b, deck_a,
                          weights_a=policy_mod.DEFAULT_WEIGHTS, weights_b=weights,
                          max_steps=max_steps)
            r = -g.reward_for_a
        wins += r > 0
        losses += r < 0
        draws += r == 0
        if starmie_pilot._LIVE_AGENT_STATE and starmie_pilot._LIVE_AGENT_STATE.get("opening_complete_this_game"):
            opening_completed += 1
    return wins, losses, draws, opening_completed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40, help="games per pass")
    ap.add_argument("--max-steps", type=int, default=400)
    args = ap.parse_args()

    deck_a = load_deck_csv(SUB / "deck.csv")
    deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
    weights = json.loads((SUB / "weights.json").read_text(encoding="utf-8"))
    starmie_agent = sub_main.agent
    base_agent = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

    # Pass B first (RL off) so the deployed A numbers aren't affected by prior
    # proposer state; reset stats between passes.
    starmie_pilot._RL_ENABLED = False
    _reset_stats()
    wb, lb, db, off_open = _run_pass(starmie_agent, base_agent, deck_a, deck_b,
                                     weights, args.games, args.max_steps)

    starmie_pilot._RL_ENABLED = True
    _reset_stats()
    wa, la, da, on_open = _run_pass(starmie_agent, base_agent, deck_a, deck_b,
                                    weights, args.games, args.max_steps)
    s = starmie_pilot.RL_STATS
    elig = s["opening_eligible"]

    n = args.games
    print("=" * 64)
    print(f"LOCAL CABT AUDIT  (N={n} per pass, vs walrein control)")
    print("=" * 64)
    print(f"{'metric':32s} {'RL ON':>12s} {'RL OFF':>12s}")
    print(f"{'W/L/D':32s} {f'{wa}/{la}/{da}':>12s} {f'{wb}/{lb}/{db}':>12s}")
    print(f"{'win rate':32s} {wa/n:>12.1%} {wb/n:>12.1%}")
    print(f"{'OPENING completed':32s} {on_open/n:>12.1%} {off_open/n:>12.1%}")
    print("-" * 64)
    print("RL proposer takeover breakdown (pass A):")
    total = elig + s["non_mappable_decision"]
    if total:
        print(f"  OPENING single-select decisions : {total}")
        print(f"  non-mappable defer (CARD/END/..) : {s['non_mappable_decision']:4d} "
              f"({s['non_mappable_decision']/total:.1%})")
    if elig:
        print(f"  mappable decisions               : {elig:4d}")
        print(f"    takeover (led)                 : {s['takeover']:4d} ({s['takeover']/elig:.1%})")
        print(f"    blocked by hard rule           : {s['blocked_by_hardrule']:4d} ({s['blocked_by_hardrule']/elig:.1%})")
        print(f"    low confidence (<3/4)          : {s['low_confidence']:4d} ({s['low_confidence']/elig:.1%})")
        print(f"    no option match                : {s['no_option_match']:4d} ({s['no_option_match']/elig:.1%})")
        print(f"    proposer errors                : {s['proposer_errors']:4d}")
    print(f"  blocked-by-kind: {dict(starmie_pilot.RL_KIND_STATS.get('blocked', {}))}")
    print(f"  nomatch-by-kind: {dict(starmie_pilot.RL_KIND_STATS.get('nomatch', {}))}")


if __name__ == "__main__":
    main()
