"""DAgger-style hard-cell approved generation.

Flow:
1. Load the trained Actor-Expert policy, run it deterministically on a seed
   grid -> collect FAILURE seeds (policy did not reach Goal).
2. For each failure, run the real planner on the same deal -> keep only cells
   the PLANNER can solve (teachable: gold doesn't cover, planner can demo).
3. Pick ~10 with the sparsest archetype coverage.
4. For each, replay the planner's action log forward (replay_gold machinery)
   and snapshot (pre_state, v2_action) at every decision -> hard-cell v2 slices.

Output: data/opening_sft/state_action_v2_hardcell.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.deck import load_deck_csv  # noqa: E402
from opening_cards import name  # noqa: E402
from opening_state import OpeningGameState  # noqa: E402
from opening_planner import diagnose_gaps, plan_and_execute_turn  # noqa: E402
from simulate_opening import shuffle_deck, mulligan_until_basic  # noqa: E402
from setup_planner import run_setup  # noqa: E402
from replay_gold import iter_decision_states  # noqa: E402

DATA = ROOT / "data" / "opening_sft"


# --------------------------------------------------------------------------- #
def snapshot_pre_state(st: OpeningGameState) -> dict:
    def pmon(p):
        return {"card_id": p.card_id, "energies": list(p.energies)} if p else None
    g = diagnose_gaps(st)
    return {
        "hand_ids": list(st.hand),
        "board": {"active": pmon(st.active), "bench": [pmon(p) for p in st.bench]},
        "deck_len": len(st.deck), "prize_len": len(st.prizes),
        "flags": {"supporter_played": st.supporter_played,
                  "energy_attached": st.energy_attached},
        "gaps": {f"g{i}": bool(getattr(g, f"g{i}", False)) for i in range(1, 7)},
    }


# --------------------------------------------------------------------------- #
# 1. policy diagnosis
# --------------------------------------------------------------------------- #
def policy_failures(net, env, seeds, going_first) -> list[dict]:
    from train_actor_expert import rollout_episode
    fails = []
    for seed in seeds:
        traj, ret, goal = rollout_episode(net, env, seed, going_first, deterministic=True)
        if not goal:
            st = env.st
            g = diagnose_gaps(st)
            fails.append({
                "seed": seed, "gf": going_first,
                "archetype": getattr(st, "setup_archetype", ""),
                "gaps": {f"g{i}": bool(getattr(g, f"g{i}", False)) for i in range(1, 7)},
                "my_turn": st.my_turn_number,
            })
    return fails


# --------------------------------------------------------------------------- #
# 2. planner can-solve filter
# --------------------------------------------------------------------------- #
def planner_reaches_goal(deck, seed, gf, turn_limit=None) -> bool:
    st = OpeningGameState.from_ordered_deck(shuffle_deck(deck, seed), going_first=gf)
    mulligan_until_basic(st)
    run_setup(st)
    turn = 1 if gf else 2
    st.begin_turn(turn, 1)
    limit = turn_limit or (2 if gf else 3)
    while st.my_turn_number <= limit and not st.opening_complete():
        plan_and_execute_turn(st)
        if st.my_turn_number >= limit:
            break
        st.begin_turn(turn + 2 * st.my_turn_number, st.my_turn_number + 1)
    return st.opening_complete(), getattr(st, "setup_archetype", ""), list(st.log)


# --------------------------------------------------------------------------- #
# 3+4. generate hard-cell slices
# --------------------------------------------------------------------------- #
def generate_slices_for(deck, seed, gf, planner_log) -> list[dict]:
    fake_traj = {"seed": seed, "going_first": gf,
                 "steps": [{"action": {"kind": e.kind, "detail_en": e.detail,
                                       "card_id": e.card_id}} for e in planner_log]}
    out = []
    step_idx = 0
    for st, v2, step in iter_decision_states(fake_traj, deck):
        kind, primary, sub = v2
        if kind in ("SETUP_ACTIVE", "SETUP_BENCH", "DRAW"):
            continue
        out.append({
            "seed": seed, "going_first": gf, "turn_limit": 2 if gf else 3,
            "archetype": getattr(st, "setup_archetype", ""),
            "source": "approved_hardcell", "goal_reached": True,
            "step_index": step_idx, "phase": "opening", "difficulty": "T2",
            "pre_state": snapshot_pre_state(st),
            "action": {"kind": kind, "primary": primary, "sub": sub},
            "action_zh": step.get("action", {}).get("detail_en", ""),
        })
        step_idx += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(DATA / "actor_expert.pt"))
    ap.add_argument("--deck", default=str(ROOT / "submission_starmie" / "deck.csv"))
    ap.add_argument("--slices", default=str(DATA / "state_action_v2.jsonl"))
    ap.add_argument("--n-diag", type=int, default=240)
    ap.add_argument("--n-pick", type=int, default=10)
    ap.add_argument("--out", default=str(DATA / "state_action_v2_hardcell.jsonl"))
    args = ap.parse_args()

    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    deck = load_deck_csv(args.deck)

    # build env + policy (mirror train_actor_expert)
    slices = [json.loads(l) for l in open(args.slices, encoding="utf-8") if l.strip()]
    cv = sorted(set(deck))
    from action_space_v2 import build_vocabs, StateEncoder
    from opening_env import OpeningEnv
    from train_actor_expert import PolicyNet
    h1, h1i, h2, h2i = build_vocabs(slices, card_vocab=cv)
    env = OpeningEnv(args.deck, h1, h1i, h2, h2i)
    net = PolicyNet(StateEncoder(cv).feature_dim, len(h1), len(h2))
    ckpt = torch.load(args.weights, map_location="cpu", weights_only=False)
    net.load_state_dict(ckpt["state_dict"])
    net.eval()
    print(f"policy loaded; vocab head1={len(h1)} head2={len(h2)}")

    # 1. diagnose failures (alternate gf/gs)
    diag_seeds = [1000 + i for i in range(args.n_diag)]
    fails = []
    for seed in diag_seeds:
        gf = (seed % 2 == 0)
        fails += policy_failures(net, env, [seed], gf)
    print(f"policy failures: {len(fails)}/{args.n_diag}")

    # 2. planner can-solve filter
    teachable = []
    for f in fails:
        ok, arch, log = planner_reaches_goal(deck, f["seed"], f["gf"])
        if ok:
            f["planner_arch"] = arch
            f["log"] = log
            teachable.append(f)
    print(f"teachable (planner solves): {len(teachable)}/{len(fails)}")

    # 3. pick n with sparsest archetype coverage
    arch_count = Counter(f["planner_arch"] for f in teachable)
    teachable.sort(key=lambda f: (arch_count[f["planner_arch"]], f["seed"]))
    picked = teachable[:args.n_pick]
    print("picked archetypes:", Counter(f["planner_arch"] for f in picked))

    # 4. generate slices
    all_slices = []
    for f in picked:
        sl = generate_slices_for(deck, f["seed"], f["gf"], f["log"])
        print(f"  seed {f['seed']} gf={f['gf']} arch={f['planner_arch']}: {len(sl)} slices")
        all_slices.extend(sl)
    Path(args.out).write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in all_slices),
        encoding="utf-8")
    print(f"wrote {len(all_slices)} hard-cell slices -> {args.out}")
    by_kind = Counter(s["action"]["kind"] for s in all_slices)
    print("by_kind:", dict(by_kind))


if __name__ == "__main__":
    main()
