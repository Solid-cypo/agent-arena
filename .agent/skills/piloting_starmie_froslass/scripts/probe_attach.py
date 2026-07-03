"""Probe ATTACH options: dump field names + target pokemon id resolution."""
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
from cg.api import OptionType, AreaType, to_observation_class

_dumped = 0
_deck = sub_main._read_deck()
import starmie_pilot as sp

orig = sub_main.agent
def probe(obs_dict):
    global _dumped
    decision = orig(obs_dict)
    if _dumped < 6:
        try:
            obs = to_observation_class(obs_dict)
            if obs.select is None:
                return decision
            options = obs.select.option
            attaches = [o for o in options if o.type == OptionType.ATTACH]
            if attaches:
                mi = obs.current.yourIndex
                me = obs.current.players[mi]
                h = me.hand or []
                print(f"--- ATTACH dump #{_dumped} mi={mi} n_attach={len(attaches)} ---")
                for o in attaches:
                    hi = getattr(o, "index", None)
                    eid = None
                    try:
                        if 0 <= (hi or -1) < len(h) and h[hi or 0]:
                            eid = getattr(h[hi or 0], "id", None)
                    except Exception:
                        pass
                    tgt = None
                    try:
                        ipa = o.inPlayArea; ipi = getattr(o, "inPlayIndex", None)
                        if ipa == AreaType.ACTIVE:
                            a = (me.active or [None])[0]
                            tgt = getattr(a, "id", None) if a else None
                        elif ipa == AreaType.BENCH:
                            b = me.bench or []
                            if 0 <= (ipi or -1) < len(b) and b[ipi or 0]:
                                tgt = getattr(b[ipi or 0], "id", None)
                    except Exception as e:
                        tgt = f"err:{e}"
                    print(f"  area={getattr(o,'area',None)} idx={hi} inPlayArea={getattr(o,'inPlayArea',None)} "
                          f"inPlayIdx={getattr(o,'inPlayIndex',None)} -> energy={eid} target={tgt}")
                _dumped += 1
        except Exception as e:
            print("probe err", repr(e))
    return decision

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))
for _ in range(8):
    if _dumped >= 6:
        break
    play_game(probe, base, deck_a, deck_b, max_steps=400)
