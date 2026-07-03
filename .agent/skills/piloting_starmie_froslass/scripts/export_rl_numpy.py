"""Export the Actor-Expert policy to a torch-free numpy bundle for Kaggle.

Outputs (next to --out):
  rl_opening.npz    trunk/head1/head2 weights + biases as numpy arrays
  rl_opening.json   head1 vocab [(kind, primary)], head2 vocab [sub],
                    card vocab [ids], feature_dim, hidden, going-first info
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.deck import load_deck_csv  # noqa: E402
from action_space_v2 import build_vocabs, StateEncoder  # noqa: E402
from train_actor_expert import PolicyNet  # noqa: E402

DATA = ROOT / "data" / "opening_sft"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(DATA / "actor_expert_dagger.pt"))
    ap.add_argument("--deck", default=str(ROOT / "submission_starmie" / "deck.csv"))
    ap.add_argument("--slices", default=str(DATA / "state_action_v2.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "submission_starmie" / "rl_opening"))
    args = ap.parse_args()

    deck = load_deck_csv(args.deck)
    cv = sorted(set(deck))
    slices = [json.loads(l) for l in open(args.slices, encoding="utf-8") if l.strip()]
    h1, h1i, h2, h2i = build_vocabs(slices, card_vocab=cv)
    encoder = StateEncoder(cv)

    net = PolicyNet(encoder.feature_dim, len(h1), len(h2))
    ckpt = torch.load(args.weights, map_location="cpu", weights_only=False)
    net.load_state_dict(ckpt["state_dict"])
    net.eval()

    sd = net.state_dict()
    arrays = {}
    for k, v in sd.items():
        arrays[k] = v.detach().cpu().numpy()
    np.savez(args.out + ".npz", **arrays)

    meta = {
        "head1": [list(x) for x in h1i],          # [[kind, primary], ...]
        "head2": list(h2i),                        # [sub_id_or_null, ...]
        "card_vocab": list(cv),
        "feature_dim": encoder.feature_dim,
        "hidden": 128,
        "n_head1": len(h1i),
        "n_head2": len(h2i),
    }
    with open(args.out + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f)
    print(f"exported -> {args.out}.npz + {args.out}.json")
    print(f"  feat={encoder.feature_dim} head1={len(h1i)} head2={len(h2i)}")


if __name__ == "__main__":
    main()
