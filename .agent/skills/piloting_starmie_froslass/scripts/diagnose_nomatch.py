"""Analyze no-match root cause: is the RL view's hand/supporter reconstruction
accurate vs the real engine obs, or is no-match inherent policy uncertainty?

Runs N RL-ON games, collects RL_NOMATCH_SAMPLES, and reports:
  - view_hand vs real_hand mismatch rate
  - for the top sampled action, whether its precondition holds in the REAL hand
    (e.g. PLAY_LILLIE needs LILLIE in real hand and not supporter_played).
"""
from __future__ import annotations
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
from opening_cards import LILLIE, ULTRA_BALL, BOSS_ORDERS, HILDA, CRISPIN, SALVATOR, JUDGE, POFFIN, NIGHT_STRETCHER, POKE_PAD, WALLYS_COMPASSION, SWITCH

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

# Map primary card id -> name for readability
CID_NAME = {
    LILLIE: "LILLIE", ULTRA_BALL: "ULTRA_BALL", BOSS_ORDERS: "BOSS",
    HILDA: "HILDA", CRISPIN: "CRISPIN", SALVATOR: "SALVATOR", JUDGE: "JUDGE",
    POFFIN: "POFFIN", NIGHT_STRETCHER: "NIGHT_STRETCHER", POKE_PAD: "POKE_PAD",
    WALLYS_COMPASSION: "COMPASSION", SWITCH: "SWITCH",
}


def analyze():
    sp._RL_ENABLED = True
    for _ in range(120):
        sp.reset_for_new_game()
        play_game(sub_main.agent, base, deck_a, deck_b, max_steps=400)
    samples = sp.RL_NOMATCH_SAMPLES
    print(f"collected {len(samples)} no-match samples")
    if not samples:
        return
    hand_mismatch = 0
    sup_mismatch = 0
    precond_fail_real = 0
    by_kind = collections.Counter()
    for s in samples:
        top = s["top"]
        topk = top[0] if top else "?"
        vh = sorted(x for x in s["view_hand"] if x)
        rh = sorted(x for x in s["real_hand"] if x)
        if vh != rh:
            hand_mismatch += 1
        by_kind[topk] += 1
        # check precondition for the common PLAY_* kinds: card must be in real hand
        if top and topk.startswith("PLAY_") and top[1] is not None:
            primary = top[1]
            in_real = primary in rh
            sup = bool(s["supporter_played"])
            is_supporter = primary in (LILLIE, HILDA, JUDGE, SALVATOR, CRISPIN, BOSS_ORDERS)
            ok = in_real and not (is_supporter and sup)
            if not ok:
                precond_fail_real += 1
    n = len(samples)
    print(f"view_hand != real_hand : {hand_mismatch}/{n} ({hand_mismatch/n:.1%})")
    print(f"top-action precondition FALSE in real : {precond_fail_real}/{n} "
          f"({precond_fail_real/n:.1%})  [of PLAY_* kinds]")
    print("no-match by top kind:")
    for k, c in by_kind.most_common(15):
        print(f"  {k:24s} {c}")
    print("\nsample rows (top 20):")
    from cg.api import SelectContext
    ctx_name = {int(v): k for k, v in SelectContext.__members__.items()}
    for s in samples[:20]:
        vh = [CID_NAME.get(x, x) for x in s["view_hand"]]
        rh = [CID_NAME.get(x, x) for x in s["real_hand"]]
        oc = [CID_NAME.get(x, x) for x in s["offered_play_cids"]]
        print(f"  top={s['top']} ctx={ctx_name.get(s['ctx'], s['ctx'])} opt_types={s['opt_types']} sup={s['supporter_played']}")
        print(f"    view_hand={vh}")
        print(f"    real_hand={rh}")
        print(f"    offered_play={oc}")


if __name__ == "__main__":
    analyze()
