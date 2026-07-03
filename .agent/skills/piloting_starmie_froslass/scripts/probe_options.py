"""Smoke test: run 1 game through the real agent, report RL_STATS + opening completion."""
from __future__ import annotations
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

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))
g = play_game(sub_main.agent, base, deck_a, deck_b, max_steps=400)
s = sp.RL_STATS
print("reward_for_a=", g.reward_for_a, "steps=", g.steps)
print("games_started=", s["games_started"], "opening_complete_games=", s["opening_complete_games"])
print("eligible=", s["opening_eligible"], "takeover=", s["takeover"],
      "blocked=", s["blocked_by_hardrule"], "low_conf=", s["low_confidence"],
      "nomatch=", s["no_option_match"], "non_mappable=", s["non_mappable_decision"],
      "errors=", s["proposer_errors"])
print("nomatch-by-kind:", dict(sp.RL_KIND_STATS.get("nomatch", {})))
print("blocked-by-kind:", dict(sp.RL_KIND_STATS.get("blocked", {})))
