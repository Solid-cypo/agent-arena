"""Probe: in RL-OFF games, whenever bench Mega Starmie has water but Active is
not Mega, dump the offered options + v1's pick to see why promotion stalls."""
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
from cg.api import OptionType, to_observation_class
from opening_cards import MEGA_STARMIE, STARYU

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

_dumped = 0
orig = sub_main.agent

def _has_water(p):
    try:
        from hand_snapshot import _has_energy, _WATER_IDS
        return _has_energy(p, _WATER_IDS)
    except Exception:
        return False

def probe(obs_dict):
    global _dumped
    decision = orig(obs_dict)
    if _dumped >= 10:
        return decision
    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return decision
        mi = obs.current.yourIndex
        me = obs.current.players[mi]
        active = (me.active or [None])[0]
        aid = getattr(active, "id", None) if active else None
        # bench Mega with water?
        bench_mega_water = any(
            p and getattr(p, "id", None) == MEGA_STARMIE and _has_water(p)
            for p in (me.bench or [])
        )
        if bench_mega_water and aid != MEGA_STARMIE:
            opts = obs.select.option
            hand_ids = [getattr(c, "id", None) for c in (me.hand or []) if c]
            sit = sp._compute_situation(obs, deck_template=deck_a, agent_state={})
            phase = sit.get("phase")
            ph = phase.primary if phase else "?"
            print(f"--- stall #{_dumped} turn={obs.current.turn} myt={sit.get('board').my_turn_number if sit.get('board') else '?'} "
                  f"phase={ph} active={aid} hand_switch={'SW' if 1123 in hand_ids else 'no'} ---")
            for i, o in enumerate(opts):
                try:
                    hb = sp._hard_rule_bonus(obs, o, sit)
                except Exception as e:
                    hb = f"err{e}"
                cid = sp._hand_card_id(obs, o, mi) if int(o.type) == 7 else None
                print(f"  [{i}] t={int(o.type)} area={getattr(o,'area',None)} idx={getattr(o,'index',None)} "
                      f"cid={cid} hard={hb}")
            pick = max(1, min(len(opts), int(obs.select.maxCount)))
            print(f"  v1 picked: {decision[:pick]}")
            _dumped += 1
    except Exception as e:
        print("probe err", repr(e))
    return decision

sp._RL_ENABLED = False
for _ in range(30):
    if _dumped >= 10:
        break
    play_game(probe, base, deck_a, deck_b, max_steps=400)
print("total stalls dumped:", _dumped)
