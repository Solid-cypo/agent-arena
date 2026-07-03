"""Hybrid policy+planner evaluation for the OPENING phase.

Two hybrid modes, both measured on the same seed grid:

* per-turn ensemble (v1 style): each my-turn, run the policy on a deepcopy AND
  the planner on another deepcopy; apply whichever end-state scores higher.
  Takes the better of the two every turn -> can exceed both pure baselines.
* episode-level OR fallback: policy plays the whole episode; if it misses Goal,
  re-run the seed with the planner; Goal = either reaches.

The per-turn ensemble is the strong variant; episode-OR is a trivial lower bound.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.deck import load_deck_csv  # noqa: E402
from opening_state import OpeningGameState  # noqa: E402
from opening_planner import _score_opening_state, plan_and_execute_turn  # noqa: E402
from simulate_opening import shuffle_deck, mulligan_until_basic  # noqa: E402
from setup_planner import run_setup  # noqa: E402
from action_space_v2 import StateEncoder, build_vocabs, legal_mask_from_state  # noqa: E402
from opening_exec import execute_v2, COMPOUND_KINDS  # noqa: E402
from train_actor_expert import PolicyNet  # noqa: E402

DATA = ROOT / "data" / "opening_sft"
COMPOUND = set(COMPOUND_KINDS)


def fresh_state(deck, seed, gf):
    st = OpeningGameState.from_ordered_deck(shuffle_deck(deck, seed), going_first=gf)
    mulligan_until_basic(st)
    run_setup(st)
    st.begin_turn(1 if gf else 2, 1)
    return st


def policy_play_turn(st, net, encoder, h1_to_idx, idx_to_head1, h2_to_idx,
                     conf: float = 0.0, max_steps: int = 20):
    """Run the policy on one turn of ``st`` in place (until stall/goal/cap)."""
    for _ in range(max_steps):
        if st.opening_complete():
            return
        legal = legal_mask_from_state(st, h1_to_idx)
        if not legal.any():
            return
        x = torch.from_numpy(encoder.encode(st)).float().unsqueeze(0)
        with torch.no_grad():
            l1, l2, _ = net(x)
        masked = l1.squeeze(0).clone()
        legal_t = torch.from_numpy(legal).bool()
        masked[~legal_t] = float("-inf")
        probs = F.softmax(masked, dim=-1)
        if conf > 0 and float(probs.max()) < conf:
            return
        h1_idx = int(torch.argmax(masked).item())
        kind, primary = idx_to_head1[h1_idx]
        sub = None
        if kind in COMPOUND and legal[h1_idx]:
            sub_idx = int(torch.argmax(l2.squeeze(0)).item())
            sub = idx_to_head2_map[sub_idx]
        if not execute_v2(st, kind, primary, sub):
            return


def rollout_per_turn_ensemble(net, deck, seed, gf, encoder, h1, h1i, h2):
    st = fresh_state(deck, seed, gf)
    limit = 2 if gf else 3
    while st.my_turn_number <= limit and not st.opening_complete():
        # policy trial
        trial_p = copy.deepcopy(st)
        policy_play_turn(trial_p, net, encoder, h1, h1i, h2)
        score_p = _score_opening_state(trial_p)
        # planner trial
        trial_q = copy.deepcopy(st)
        plan_and_execute_turn(trial_q)
        score_q = _score_opening_state(trial_q)
        # pick better end-state
        st = trial_p if score_p >= score_q else trial_q
        if st.opening_complete():
            break
        st.begin_turn(st.current_turn + 2, st.my_turn_number + 1)
    return st.opening_complete()


def rollout_policy_only(net, env, seed, gf):
    from train_actor_expert import rollout_episode
    _, _, goal = rollout_episode(net, env, seed, gf, deterministic=True)
    return goal


def rollout_policy_stoch(net, env, seed, gf):
    from train_actor_expert import rollout_episode
    _, _, goal = rollout_episode(net, env, seed, gf, deterministic=False)
    return goal


def rollout_planner_only(deck, seed, gf):
    st = fresh_state(deck, seed, gf)
    limit = 2 if gf else 3
    while st.my_turn_number <= limit and not st.opening_complete():
        plan_and_execute_turn(st)
        if st.my_turn_number >= limit:
            break
        st.begin_turn(st.current_turn + 2, st.my_turn_number + 1)
    return st.opening_complete()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(DATA / "actor_expert_dagger.pt"))
    ap.add_argument("--deck", default=str(ROOT / "submission_starmie" / "deck.csv"))
    ap.add_argument("--slices", default=str(DATA / "state_action_v2.jsonl"))
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    deck = load_deck_csv(args.deck)
    cv = sorted(set(deck))
    slices = [json.loads(l) for l in open(args.slices, encoding="utf-8") if l.strip()]
    h1, h1i, h2, h2i = build_vocabs(slices, card_vocab=cv)
    encoder = StateEncoder(cv)
    from opening_env import OpeningEnv
    env = OpeningEnv(args.deck, h1, h1i, h2, h2i)
    net = PolicyNet(encoder.feature_dim, len(h1), len(h2))
    ckpt = torch.load(args.weights, map_location="cpu", weights_only=False)
    net.load_state_dict(ckpt["state_dict"])
    net.eval()

    # global idx_to_head2 map for compound sub (id from h2i index)
    global idx_to_head2_map
    idx_to_head2_map = h2i

    seeds = list(range(1000, 1000 + args.n))
    for label, gf in [("going-first", True), ("going-second", False)]:
        pol = sum(rollout_policy_only(net, env, s, gf) for s in seeds)
        pla = sum(rollout_planner_only(deck, s, gf) for s in seeds)
        ens = sum(rollout_per_turn_ensemble(net, deck, s, gf, encoder, h1, h1i, h2)
                  for s in seeds)
        # episode-OR fallback
        eor = 0
        for s in seeds:
            if rollout_policy_only(net, env, s, gf) or rollout_planner_only(deck, s, gf):
                eor += 1
        # best-of-K: 1 deterministic + (K-1) stochastic policy, then planner
        K = 4
        bok = 0
        for s in seeds:
            hit = rollout_policy_only(net, env, s, gf)
            if not hit:
                hit = any(rollout_policy_stoch(net, env, s, gf) for _ in range(K - 1))
            if not hit:
                hit = rollout_planner_only(deck, s, gf)
            if hit:
                bok += 1
        N = len(seeds)
        print(f"{label} (N={N}):")
        print(f"  policy-only   : {pol/N:.1%}")
        print(f"  planner-only  : {pla/N:.1%}")
        print(f"  episode-OR    : {eor/N:.1%}")
        print(f"  per-turn ens  : {ens/N:.1%}")
        print(f"  bestof{K}+plan : {bok/N:.1%}")


if __name__ == "__main__":
    main()
