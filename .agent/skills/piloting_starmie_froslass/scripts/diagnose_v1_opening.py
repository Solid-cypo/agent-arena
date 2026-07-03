"""Diagnose v1 (RL OFF) OPENING failure modes on the real cabt engine.

Runs N games with the RL proposer disabled (pure v1 pilot) and categorizes why
the opening failed to complete (Mega Starmie active + water) in each losing
game. Output drives targeted v1 opening-completion fixes.
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.simulator import play_game
from arena.deck import load_deck_csv
import arena.policy as policy_mod
import main as sub_main
import starmie_pilot as sp
from opening_cards import STARYU, MEGA_STARMIE

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))


def categorize(fb):
    """fb = (my_turn, active_id, is_mega, has_water, mega_on_field, staryu_on_field, prize_self, prize_opp)."""
    if fb is None:
        return "no_board"
    _t, _aid, is_mega, has_water, mega_on, staryu_on, ps, po = fb
    if is_mega and not has_water:
        return "mega_active_no_water"
    if mega_on and not is_mega:
        return "mega_bench_not_active"
    if staryu_on and not mega_on:
        return "staryu_no_mega"
    if not staryu_on and not mega_on:
        return "no_staryu_no_mega"
    if is_mega and has_water:
        return "complete_at_end"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--max-steps", type=int, default=400)
    args = ap.parse_args()

    sp._RL_ENABLED = False
    wins = losses = draws = 0
    completed = 0
    fail_cats = collections.Counter()
    fail_max_turn = collections.Counter()
    fail_prize_diff = []          # prize_opp - prize_self at end (positive = we're behind)
    succ_max_turn = collections.Counter()
    for i in range(args.games):
        sp.reset_for_new_game()
        if i % 2 == 0:
            g = play_game(sub_main.agent, base, deck_a, deck_b,
                          weights_a=policy_mod.DEFAULT_WEIGHTS, max_steps=args.max_steps)
            r = g.reward_for_a
        else:
            g = play_game(base, sub_main.agent, deck_b, deck_a,
                          weights_b=policy_mod.DEFAULT_WEIGHTS, max_steps=args.max_steps)
            r = -g.reward_for_a
        wins += r > 0; losses += r < 0; draws += r == 0
        st = sp._LIVE_AGENT_STATE
        ok = bool(st and st.get("opening_complete_this_game"))
        completed += ok
        mt = st.get("max_my_turn", 0) if st else 0
        fb = st.get("final_board") if st else None
        if ok:
            succ_max_turn[mt] += 1
        else:
            fail_cats[categorize(fb)] += 1
            fail_max_turn[mt] += 1
            if fb is not None:
                fail_prize_diff.append(fb[7] - fb[6])

    n = args.games
    print("=" * 64)
    print(f"v1 OPENING FAILURE DIAGNOSIS  (N={n}, RL OFF, vs walrein)")
    print("=" * 64)
    print(f"W/L/D = {wins}/{losses}/{draws}   win {wins/n:.1%}")
    print(f"OPENING completed = {completed}/{n} ({completed/n:.1%})")
    print(f"OPENING failed    = {n-completed}/{n} ({(n-completed)/n:.1%})")
    print("-" * 64)
    print("Failure categories (of games that did NOT complete opening):")
    for cat, c in fail_cats.most_common():
        print(f"  {cat:28s} {c:4d}  ({c/max(n-completed,1):.1%})")
    print("-" * 64)
    print("max_my_turn at failure (how far the opening got):")
    for t in sorted(fail_max_turn):
        print(f"  turn {t}: {fail_max_turn[t]}")
    print("max_my_turn at SUCCESS:")
    for t in sorted(succ_max_turn):
        print(f"  turn {t}: {succ_max_turn[t]}")
    if fail_prize_diff:
        avg = sum(fail_prize_diff) / len(fail_prize_diff)
        behind = sum(1 for d in fail_prize_diff if d > 0)
        print(f"prize_diff at failure (opp-self): avg={avg:.2f}, "
              f"we-behind {behind}/{len(fail_prize_diff)}")


if __name__ == "__main__":
    main()
