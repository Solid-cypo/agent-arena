"""Probe the real player object's supporter/energy-attached attribute names."""
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

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

printed = {"once": False}

def probe(obs_dict):
    d = sub_main.agent(obs_dict)
    if printed["once"]:
        return d
    from cg.api import to_observation_class
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return d
    mi = obs.current.yourIndex
    me = obs.current.players[mi]
    attrs = [a for a in dir(me) if "sup" in a.lower() or "attach" in a.lower() or "energy" in a.lower() or "played" in a.lower() or "used" in a.lower()]
    print("candidate attrs:", attrs)
    for a in attrs:
        try:
            print(f"  me.{a} = {getattr(me, a)}  (type {type(getattr(me,a)).__name__})")
        except Exception as e:
            print(f"  me.{a} err {e}")
    # also dump all public attrs
    print("all public:", [a for a in dir(me) if not a.startswith('_')])
    printed["once"] = True
    return d

play_game(probe, base, deck_a, deck_b, max_steps=200)
