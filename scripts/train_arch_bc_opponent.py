#!/usr/bin/env python3
"""Train a pointer-BC opponent for an online archetype from sub_* replays.

Data: opponent-side decisions from data/kaggle_episodes/sub_55115028 episodes
of the given archetype (obs at step t pairs with action at step t+1).
Features/network layout identical to scripts/alak_bc.py (D->128->64->1), so
the runtime is the same make_alak_bc_agent.

Usage:
  python3 scripts/train_arch_bc_opponent.py --arch lucario_fighting
Output:
  data/opening_sft/bc_<arch>.npz / .json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from alak_bc import (  # noqa: E402
    GLOBAL_N,
    _si,
    feature_dim,
    global_features,
    option_card_id,
    option_features,
)

US = "Ying Peter"
SUB_DIR = ROOT / "data" / "kaggle_episodes" / "sub_55115028"
FADE = ROOT / "data" / "kaggle_episodes" / "analysis_55115028_fade.json"


def extract_decisions(arch: str) -> list[dict]:
    fade = json.loads(FADE.read_text())
    eids = [g["eid"] for g in fade["games"] if g["arch"] == arch]
    decisions = []
    for eid in eids:
        f = SUB_DIR / f"episode-{eid}-replay.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        oi = 1 - d["info"]["TeamNames"].index(US)
        steps = d["steps"]
        for t in range(len(steps) - 1):
            entry = steps[t][oi] or {}
            obs = entry.get("observation") or {}
            sel = obs.get("select") or {}
            opts = sel.get("option") or []
            act = (steps[t + 1][oi] or {}).get("action")
            if not opts or not isinstance(act, list) or not act:
                continue
            if not all(isinstance(a, int) and 0 <= a < len(opts) for a in act):
                continue
            decisions.append({"obs": obs, "opts": opts, "chosen": act, "eid": eid})
    return decisions


def build_vocabs(decisions: list[dict]) -> tuple[dict, dict]:
    cids, aids = set(), set()
    for dec in decisions:
        obs = dec["obs"]
        mi = _si((obs.get("current") or {}).get("yourIndex"))
        for o in dec["opts"]:
            cids.add(option_card_id(obs, o, mi))
            aids.add(_si(o.get("attackId")))
    cids.discard(0)
    aids.discard(0)
    card_vocab = {cid: i + 1 for i, cid in enumerate(sorted(cids))}
    attack_vocab = {aid: i + 1 for i, aid in enumerate(sorted(aids))}
    return card_vocab, attack_vocab


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "opening_sft")
    args = ap.parse_args()

    import torch
    import torch.nn as nn

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    decisions = extract_decisions(args.arch)
    print(f"{args.arch}: {len(decisions)} expert decisions")
    if len(decisions) < 50:
        print("WARNING: very little data — BC quality will be limited")
    card_vocab, attack_vocab = build_vocabs(decisions)
    D = feature_dim(card_vocab, attack_vocab)
    print(f"vocab: {len(card_vocab)} cards, {len(attack_vocab)} attacks, D={D}")

    # Flatten: rows = (decision, option); groups via offsets
    rows, offsets, labels = [], [0], []
    for dec in decisions:
        obs = dec["obs"]
        mi = _si((obs.get("current") or {}).get("yourIndex"))
        g = global_features(obs, mi)
        for o in dec["opts"]:
            rows.append(
                np.concatenate(
                    [g, option_features(obs, o, mi, card_vocab, attack_vocab)]
                )
            )
        offsets.append(len(rows))
        labels.append(dec["chosen"][0])  # first pick = pointer label
    X = torch.tensor(np.stack(rows), dtype=torch.float32)
    print(f"rows={len(rows)}")

    model = nn.Sequential(
        nn.Linear(D + 0, 128), nn.ReLU(), nn.Linear(128, 64), nn.ReLU(),
        nn.Linear(64, 1),
    )
    # sanity: feature_dim already includes GLOBAL_N
    assert X.shape[1] == D, (X.shape, D)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    n_dec = len(decisions)
    idx_all = np.arange(n_dec)
    for ep in range(args.epochs):
        np.random.shuffle(idx_all)
        tot_loss = tot_acc = 0.0
        bs = 256
        for s in range(0, n_dec, bs):
            batch = idx_all[s : s + bs]
            # gather rows for these decisions
            segs = [(offsets[i], offsets[i + 1]) for i in batch]
            rows_idx = np.concatenate([np.arange(a, b) for a, b in segs])
            scores = model(X[rows_idx]).reshape(-1)
            loss = 0.0
            acc = 0
            pos = 0
            losses = []
            for j, i in enumerate(batch):
                k = segs[j][1] - segs[j][0]
                sc = scores[pos : pos + k]
                pos += k
                lbl = torch.tensor(labels[i])
                losses.append(nn.functional.cross_entropy(sc.unsqueeze(0), lbl.unsqueeze(0)))
                if int(sc.argmax()) == labels[i]:
                    acc += 1
            loss = torch.stack(losses).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot_loss += float(loss) * len(batch)
            tot_acc += acc
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"ep {ep+1}: loss {tot_loss/n_dec:.4f} top1 {tot_acc/n_dec:.3f}")

    out = args.out_dir / f"bc_{args.arch}.npz"
    layers = [m for m in model if isinstance(m, nn.Linear)]
    np.savez(
        out,
        W1=layers[0].weight.detach().numpy().T, b1=layers[0].bias.detach().numpy(),
        W2=layers[1].weight.detach().numpy().T, b2=layers[1].bias.detach().numpy(),
        W3=layers[2].weight.detach().numpy().T, b3=layers[2].bias.detach().numpy(),
    )
    out.with_suffix(".json").write_text(json.dumps({
        "card_vocab": {str(k): v for k, v in card_vocab.items()},
        "attack_vocab": {str(k): v for k, v in attack_vocab.items()},
        "in_dim": D,
        "global_n": GLOBAL_N,
        "decisions": len(decisions),
        "arch": args.arch,
    }, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
