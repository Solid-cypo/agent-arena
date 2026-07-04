"""Actor-Expert RL for the OPENING phase: PPO + BC anchor on gold v2 slices.

Joint loss each PPO update:

    L = L_PPO(policy, value) + lambda_bc * L_BC(gold)

* PPO collects rollouts in ``opening_env.OpeningEnv`` and optimizes a clipped
  surrogate + value MSE + entropy bonus.
* BC anchor samples a batch of gold v2 slices and adds a masked cross-entropy on
  head1 (kind,primary) and head2 (sub, compound kinds only). This keeps the
  policy from drifting off expert style while RL tunes the reward.

No heavy RL libs - raw PyTorch, per the project Tiny-RL strategy.

Run:
    PYTHONPATH=.agent/skills/piloting_starmie_froslass/scripts \
        python3 train_actor_expert.py --iters 50 --warmstart-epochs 30
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from action_space_v2 import (  # noqa: E402
    HEAD2_NONE,
    StateEncoder,
    build_vocabs,
)
from opening_env import OpeningEnv  # noqa: E402
from opening_exec import COMPOUND_KINDS, NON_POLICY_KINDS  # noqa: E402

DATA = ROOT / "data" / "opening_sft"
DEVICE = torch.device("cpu")

COMPOUND = set(COMPOUND_KINDS)


# --------------------------------------------------------------------------- #
# Policy network
# --------------------------------------------------------------------------- #
class PolicyNet(nn.Module):
    def __init__(self, feat_dim: int, n_head1: int, n_head2: int,
                 hidden: int = 128):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(feat_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.head1 = nn.Linear(hidden, n_head1)
        self.head2 = nn.Linear(hidden, n_head2)
        self.value = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor):
        h = self.trunk(x)
        return self.head1(h), self.head2(h), self.value(h).squeeze(-1)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
@dataclass
class BCSample:
    feat: np.ndarray
    h1: int
    h2: int | None
    is_compound: bool


def load_bc_samples(slices, encoder: StateEncoder, h1_to_idx, h2_to_idx,
                    extra_sources: tuple[str, ...] = (),
                    extra_oversample: int = 1):
    """Gold (expert_edited) always; extra_sources (e.g. approved_hardcell)
    included with ``extra_oversample`` copies for curriculum emphasis."""
    out: list[BCSample] = []
    for s in slices:
        src = s["source"]
        is_extra = src in extra_sources
        if src != "expert_edited" and not is_extra:
            continue
        a = s["action"]
        kind = a["kind"]
        if kind in NON_POLICY_KINDS:
            continue
        key = (kind, a["primary"])
        if key not in h1_to_idx:
            continue
        feat = encoder.encode(s)
        is_c = kind in COMPOUND
        sub = a.get("sub")
        h2 = h2_to_idx.get(sub, h2_to_idx[HEAD2_NONE]) if is_c else None
        copies = extra_oversample if is_extra else 1
        for _ in range(copies):
            out.append(BCSample(feat, h1_to_idx[key], h2, is_c))
    return out


# --------------------------------------------------------------------------- #
# Action sampling
# --------------------------------------------------------------------------- #
def select_action(net: PolicyNet, obs: np.ndarray, legal_mask: np.ndarray,
                  deterministic: bool):
    x = torch.from_numpy(obs).float().unsqueeze(0)
    with torch.no_grad():
        l1, l2, v = net(x)
    l1 = l1.squeeze(0)
    masked = l1.clone()
    legal = torch.from_numpy(legal_mask).bool()
    masked[~legal] = float("-inf")
    probs1 = F.softmax(masked, dim=-1)
    if deterministic:
        h1_idx = int(torch.argmax(masked).item())
    else:
        h1_idx = int(torch.multinomial(probs1, 1).item())
    logp1 = float(F.log_softmax(masked, dim=-1)[h1_idx].item())
    kind, primary = None, None  # filled by caller via idx_to_head1
    return h1_idx, logp1, float(v.item())


# --------------------------------------------------------------------------- #
# SFT warm-start (pure BC)
# --------------------------------------------------------------------------- #
def sft_warmstart(net: PolicyNet, samples: list[BCSample], epochs: int,
                  lr: float = 3e-3, batch_size: int = 64):
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    n = len(samples)
    for ep in range(epochs):
        random.shuffle(samples)
        tot = 0.0
        for i in range(0, n, batch_size):
            batch = samples[i:i + batch_size]
            feats = torch.from_numpy(np.stack([b.feat for b in batch])).float()
            h1 = torch.tensor([b.h1 for b in batch], dtype=torch.long)
            l1, _, _ = net(feats)
            loss1 = F.cross_entropy(l1, h1)
            # head2 only on compound samples
            c_idx = [j for j, b in enumerate(batch) if b.is_compound]
            loss2 = torch.tensor(0.0)
            if c_idx:
                lc = l1.new_zeros((len(c_idx), net.head2.out_features))
                # recompute head2 for compound rows
                with torch.no_grad():
                    pass
                feats_c = feats[c_idx]
                _, l2c, _ = net(feats_c)
                h2c = torch.tensor([batch[j].h2 for j in c_idx], dtype=torch.long)
                loss2 = F.cross_entropy(l2c, h2c)
            loss = loss1 + 0.5 * loss2
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(batch)
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"  [warmstart] epoch {ep+1}/{epochs} loss {tot/n:.4f}")
    return net


# --------------------------------------------------------------------------- #
# PPO rollout
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    feat: np.ndarray
    legal: np.ndarray
    h1: int
    h2: int | None
    logp: float
    value: float
    reward: float
    done: bool


def rollout_episode(net: PolicyNet, env: OpeningEnv, seed: int,
                    going_first: bool, deterministic: bool = False):
    obs = env.reset(seed, going_first=going_first)
    traj: list[Step] = []
    ep_ret = 0.0
    info: dict = {}
    for _ in range(60):
        cur_obs = obs.copy()
        legal = env.legal_mask()
        if not legal.any():
            h1_idx, logp, v = 0, 0.0, 0.0
        else:
            h1_idx, logp, v = select_action(net, cur_obs, legal, deterministic)
        h2_idx = None
        kind_name = env.h1i[h1_idx][0]
        if kind_name in COMPOUND and legal[h1_idx]:
            x = torch.from_numpy(cur_obs).float().unsqueeze(0)
            with torch.no_grad():
                _, l2, _ = net(x)
            if deterministic:
                h2_idx = int(torch.argmax(l2.squeeze(0)).item())
            else:
                p2 = F.softmax(l2.squeeze(0), dim=-1)
                h2_idx = int(torch.multinomial(p2, 1).item())
        obs, r, done, info = env.step(h1_idx, h2_idx)
        traj.append(Step(cur_obs, legal, h1_idx, h2_idx, logp, v, r, done))
        ep_ret += r
        if done:
            break
    return traj, ep_ret, info.get("goal", False)


def compute_advantages(traj: list[Step], gamma: float = 0.99,
                       lam: float = 0.95):
    rewards = [s.reward for s in traj]
    values = [s.value for s in traj]
    T = len(rewards)
    adv = np.zeros(T, dtype=np.float32)
    last_gae = 0.0
    for t in reversed(range(T)):
        next_v = values[t + 1] if t + 1 < T else 0.0
        next_nonterm = 0.0 if (t + 1 == T) else 1.0
        delta = rewards[t] + gamma * next_v * next_nonterm - values[t]
        last_gae = delta + gamma * lam * next_nonterm * last_gae
        adv[t] = last_gae
    returns = adv + np.array(values, dtype=np.float32)
    return adv, returns


# --------------------------------------------------------------------------- #
# PPO + BC joint update
# --------------------------------------------------------------------------- #
def ppo_update(net: PolicyNet, opt, trajectories: list[list[Step]],
               samples: list[BCSample], clip: float, entropy_coef: float,
               value_coef: float, lambda_bc: float, n_epochs: int,
               batch_size: int, n_head1: int):
    # drop all-illegal steps per trajectory (NaN softmax), preserve boundaries
    trajs_f = [[s for s in tr if s.legal.any()] for tr in trajectories]
    trajs_f = [tr for tr in trajs_f if tr]
    flat = [s for tr in trajs_f for s in tr]
    if not flat:
        return 0.0
    feats = torch.from_numpy(np.stack([s.feat for s in flat])).float()
    legals = torch.from_numpy(np.stack([s.legal for s in flat])).bool()
    old_h1 = torch.tensor([s.h1 for s in flat], dtype=torch.long)
    old_logp = torch.tensor([s.logp for s in flat], dtype=torch.float32)
    # GAE per filtered trajectory
    advs, rets = [], []
    for tr in trajs_f:
        a, r = compute_advantages(tr)
        advs.append(a); rets.append(r)
    adv_t = torch.tensor(np.concatenate(advs), dtype=torch.float32)
    ret_t = torch.tensor(np.concatenate(rets), dtype=torch.float32)
    if adv_t.numel() > 1:
        adv_t = (adv_t - adv_t.mean()) / (adv_t.std() + 1e-8)
    # normalize value targets so the value head doesn't dominate the shared trunk
    if ret_t.numel() > 1:
        ret_t = (ret_t - ret_t.mean()) / (ret_t.std() + 1e-8)

    N = len(flat)
    idx = np.arange(N)
    total = 0.0
    steps = 0
    for _ in range(n_epochs):
        np.random.shuffle(idx)
        for i in range(0, N, batch_size):
            b = idx[i:i + batch_size]
            bf = feats[b]; bl = legals[b]
            bh1 = old_h1[b]; bol = old_logp[b]
            ba = adv_t[b]; br = ret_t[b]
            l1, l2, val = net(bf)
            masked = l1.clone()
            masked[~bl] = float("-inf")
            logp_all = F.log_softmax(masked, dim=-1)
            logp = logp_all.gather(1, bh1.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - bol)
            loss_ppo = -torch.min(ratio * ba,
                                  torch.clamp(ratio, 1 - clip, 1 + clip) * ba).mean()
            loss_val = F.mse_loss(val, br)
            probs = F.softmax(masked, dim=-1)
            logp_all_safe = torch.where(torch.isfinite(logp_all), logp_all,
                                        torch.zeros_like(logp_all))
            ent = -(probs * logp_all_safe).sum(dim=-1).mean()
            loss_ent = -entropy_coef * ent
            loss_bc = torch.tensor(0.0)
            if lambda_bc > 0 and samples:
                m = min(len(samples), len(b))
                bc_batch = random.sample(samples, m)
                bf2 = torch.from_numpy(np.stack([s.feat for s in bc_batch])).float()
                bh1g = torch.tensor([s.h1 for s in bc_batch], dtype=torch.long)
                l1g, l2g, _ = net(bf2)
                # permissive: gold target is legal by construction
                loss_bc = F.cross_entropy(l1g, bh1g)
                c_idx = [j for j, s in enumerate(bc_batch) if s.is_compound]
                if c_idx:
                    l2c = l2g[c_idx]
                    h2c = torch.tensor([bc_batch[j].h2 for j in c_idx], dtype=torch.long)
                    loss_bc = loss_bc + 0.5 * F.cross_entropy(l2c, h2c)
            loss = loss_ppo + value_coef * loss_val + loss_ent + lambda_bc * loss_bc
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 0.5)
            opt.step()
            total += loss.item(); steps += 1
    return total / max(steps, 1)


# --------------------------------------------------------------------------- #
# Eval
# --------------------------------------------------------------------------- #
@torch.no_grad()
def evaluate(net: PolicyNet, env: OpeningEnv, seeds, going_first=True):
    goals = 0
    for seed in seeds:
        traj, ret, goal = rollout_episode(net, env, seed, going_first, deterministic=True)
        if goal:
            goals += 1
    return goals / len(seeds)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slices", default=str(DATA / "state_action_v2.jsonl"))
    ap.add_argument("--deck", default=str(ROOT / "submission_starmie" / "deck.csv"))
    ap.add_argument("--warmstart-epochs", type=int, default=30)
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--rollouts", type=int, default=64)
    ap.add_argument("--ppo-epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lambda-bc", type=float, default=0.5)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--entropy", type=float, default=0.01)
    ap.add_argument("--value-coef", type=float, default=0.5)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--eval-seeds", type=int, default=100)
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--out", default=str(DATA / "actor_expert.pt"))
    ap.add_argument("--init-weights", default=None,
                    help="load existing weights and skip warmstart (fine-tune)")
    ap.add_argument("--hardcell-slices", default=None,
                    help="extra BC slices (e.g. approved_hardcell) for curriculum")
    ap.add_argument("--hardcell-oversample", type=int, default=2)
    ap.add_argument("--dagger-slices", default=None,
                    help="DAgger BC slices from the improved v1 on the real engine "
                         "(source=dagger_v1); teaches corrected opening lines incl. "
                         "Mega promotion that the gold barely covers.")
    ap.add_argument("--dagger-oversample", type=int, default=1)
    args = ap.parse_args()

    random.seed(0); np.random.seed(0); torch.manual_seed(0)

    slices = [json.loads(l) for l in open(args.slices, encoding="utf-8") if l.strip()]
    if args.hardcell_slices:
        hc = [json.loads(l) for l in open(args.hardcell_slices, encoding="utf-8") if l.strip()]
        slices = slices + hc
        print(f"hardcell slices appended: {len(hc)}")
    if args.dagger_slices:
        dg = [json.loads(l) for l in open(args.dagger_slices, encoding="utf-8") if l.strip()]
        slices = slices + dg
        print(f"dagger slices appended: {len(dg)}")
    from arena.deck import load_deck_csv
    cv = sorted(set(load_deck_csv(args.deck)))
    h1_to_idx, idx_to_head1, h2_to_idx, idx_to_head2 = build_vocabs(slices, card_vocab=cv)
    encoder = StateEncoder(cv)
    env = OpeningEnv(args.deck, h1_to_idx, idx_to_head1, h2_to_idx, idx_to_head2)
    print(f"vocab: head1={len(h1_to_idx)} head2={len(h2_to_idx)} feat={encoder.feature_dim}")

    net = PolicyNet(encoder.feature_dim, len(h1_to_idx), len(h2_to_idx)).to(DEVICE)
    extra_src = ("approved_hardcell",) if args.hardcell_slices else ()
    if args.dagger_slices:
        extra_src = extra_src + ("dagger_v1",)
    bc_samples = load_bc_samples(slices, encoder, h1_to_idx, h2_to_idx,
                                 extra_sources=extra_src,
                                 extra_oversample=args.hardcell_oversample)
    print(f"BC samples: {len(bc_samples)} (gold + hardcell x{args.hardcell_oversample} + dagger x{args.dagger_oversample})")

    eval_seeds = list(range(1000, 1000 + args.eval_seeds))
    if args.init_weights:
        ckpt = torch.load(args.init_weights, map_location="cpu", weights_only=False)
        net.load_state_dict(ckpt["state_dict"])
        print(f"loaded init weights from {args.init_weights} (skip warmstart)")
        g0 = evaluate(net, env, eval_seeds)
        print(f"goal rate at fine-tune start: {g0:.1%}")
    else:
        print("== SFT warm-start ==")
        sft_warmstart(net, bc_samples, args.warmstart_epochs)
        g0 = evaluate(net, env, eval_seeds)
        print(f"goal rate after warmstart: {g0:.1%}")

    # 2. PPO + BC
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    eval_gf = [True, False]
    for it in range(args.iters):
        trajs = []
        goals_roll = 0
        gf = eval_gf[it % 2]
        for k in range(args.rollouts):
            seed = 1000 + it * args.rollouts + k
            tr, ret, goal = rollout_episode(net, env, seed, going_first=gf)
            trajs.append(tr)
            if goal:
                goals_roll += 1
        loss = ppo_update(net, opt, trajs, bc_samples, args.clip, args.entropy,
                          args.value_coef, args.lambda_bc, args.ppo_epochs,
                          args.batch_size, len(h1_to_idx))
        roll_goal = goals_roll / args.rollouts
        if (it + 1) % args.eval_every == 0 or it == 0:
            g = evaluate(net, env, eval_seeds, going_first=True)
            print(f"iter {it+1}/{args.iters} loss {loss:.4f} "
                  f"roll_goal {roll_goal:.1%} eval_goal(gf) {g:.1%}")
    # final eval both directions
    g_gf = evaluate(net, env, eval_seeds, going_first=True)
    g_gs = evaluate(net, env, eval_seeds, going_first=False)
    print(f"FINAL eval: going-first {g_gf:.1%}  going-second {g_gs:.1%}")

    torch.save({"state_dict": net.state_dict(),
                "h1_to_idx": h1_to_idx, "idx_to_head1": idx_to_head1,
                "h2_to_idx": h2_to_idx, "idx_to_head2": idx_to_head2,
                "card_vocab": cv}, args.out)
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
