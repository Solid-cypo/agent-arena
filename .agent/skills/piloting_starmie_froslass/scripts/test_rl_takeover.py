"""Local cabt-engine takeover audit for the RL opening proposer.

Runs a small batch of real games through the cabt engine (arena.simulator) with
the submission's starmie agent (main.agent) as player A and a generic baseline
as player B, then reports the RL proposer's OPENING takeover rate from
starmie_pilot.RL_STATS.

This verifies the proposer actually fires on real observations (not just the
simulation) and how often it leads vs defers to the v1 planner route.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import arena.simulator FIRST so the root `cg` package is cached before the
# submission's pilot imports cg.api (they share the same libcg binding).
from arena.simulator import play_game  # noqa: E402
from arena.deck import load_deck_csv  # noqa: E402
import arena.policy as policy_mod  # noqa: E402

import main as sub_main  # noqa: E402  (submission entry; pre-builds agent)
import starmie_pilot  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260703)
    args = ap.parse_args()

    random.seed(args.seed)

    deck_a = load_deck_csv(SUB / "deck.csv")  # starmie (matches submission)
    deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
    weights = json.loads((SUB / "weights.json").read_text(encoding="utf-8"))

    starmie_agent = sub_main.agent  # built at import; uses RL proposer
    base_agent = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

    wins = losses = draws = 0
    step_total = 0
    for i in range(args.games):
        if i % 2 == 0:
            g = play_game(starmie_agent, base_agent, deck_a, deck_b,
                          weights_a=weights, weights_b=policy_mod.DEFAULT_WEIGHTS,
                          max_steps=args.max_steps)
            r = g.reward_for_a
        else:
            g = play_game(base_agent, starmie_agent, deck_b, deck_a,
                          weights_a=policy_mod.DEFAULT_WEIGHTS, weights_b=weights,
                          max_steps=args.max_steps)
            r = -g.reward_for_a
        wins += r > 0
        losses += r < 0
        draws += r == 0
        step_total += g.steps
        tag = "W" if r > 0 else "L" if r < 0 else "D"
        print(f"  game {i+1:2d} (starmie {'first' if i%2==0 else 'second'})  "
              f"{tag}  steps={g.steps}")

    s = starmie_pilot.RL_STATS
    elig = s["opening_eligible"]
    nonmap = s["non_mappable_decision"]
    total = elig + nonmap
    print("\n=== RL proposer OPENING takeover audit ===")
    print(f"games={args.games}  W/L/D={wins}/{losses}/{draws}  "
          f"avg_steps={step_total/args.games:.1f}")
    print(f"OPENING single-select decisions total      : {total}")
    print(f"  non-mappable (CARD/END/ATTACK/...) defer  : {nonmap:4d}  ({nonmap/max(total,1):.1%})")
    print(f"  mappable (PLAY/ATTACH/EVOLVE/ABIL/RETREAT): {elig:4d}  ({elig/max(total,1):.1%})")
    if elig:
        print(f"     takeover (led turn)                    : {s['takeover']:4d}  ({s['takeover']/elig:.1%})")
        print(f"     blocked by hard rule (deferred)        : {s['blocked_by_hardrule']:4d}  ({s['blocked_by_hardrule']/elig:.1%})")
        print(f"     low confidence (<3/4, deferred)        : {s['low_confidence']:4d}  ({s['low_confidence']/elig:.1%})")
        print(f"     action not in options (deferred)       : {s['no_option_match']:4d}  ({s['no_option_match']/elig:.1%})")
        print(f"     proposer errors                        : {s['proposer_errors']:4d}")
        print("  blocked-by-kind   :", starmie_pilot.RL_KIND_STATS.get("blocked", {}))
        print("  nomatch-by-kind   :", starmie_pilot.RL_KIND_STATS.get("nomatch", {}))


if __name__ == "__main__":
    main()
