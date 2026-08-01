"""Alakazam BC opponent — shared featurizer + numpy policy (Line 2).

Trained from A1 high-score Kaggle replays (data/kaggle_episodes/alakazam_highscore).
Pointer-style BC: score every legal option, softmax over the decision's options.

The runtime agent is numpy-only and exposes the same interface as
``arena.policy.make_agent`` (obs_dict -> list of option positions).

NOTE: this file was reconstructed from scripts/__pycache__/alak_bc.cpython-310.pyc
(pycdc) after the 2026-08-01 disk-cleanup incident. The feature layout matches
the surviving alak_bc_opponent.npz weights (validated by re-running acceptance).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

TYPE_N = 18
CTX_N = 52
AREA_N = 13
INPLAY_N = 8
OOV = 0


def _si(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def _card_id_of(cards, idx):
    cards = cards or []
    if not (0 <= idx < len(cards)):
        return 0
    c = cards[idx]
    if isinstance(c, dict):
        return _si(c.get("id"))
    return _si(getattr(c, "id", None))


def option_card_id(obs, opt, my_index):
    """Best-effort card id for an option dict (replay/live obs dict form)."""
    sel = obs.get("select") or {}
    cur = obs.get("current") or {}
    players = cur.get("players") or [{}, {}]
    me = players[my_index] if my_index < len(players) else {}
    otype = _si(opt.get("type"))
    idx = _si(opt.get("index"), -1)
    area = _si(opt.get("area"))
    if otype == 13:  # ATTACK
        return 0
    deck = sel.get("deck") or []
    if deck:
        return _card_id_of(deck, idx)
    if area == 2:  # HAND
        return _card_id_of(me.get("hand") or [], idx)
    if area == 5:  # BENCH
        return _card_id_of(me.get("bench") or [], _si(opt.get("inPlayIndex"), idx))
    if area == 4:  # ACTIVE
        return _card_id_of(me.get("active") or [], 0)
    if area == 3:  # DISCARD
        return _card_id_of(me.get("discard") or [], idx)
    if otype in (7, 8, 9):  # PLAY / ATTACH / EVOLVE default to hand
        return _card_id_of(me.get("hand") or [], idx)
    return 0


def _pkm_ids(p):
    out = []
    for x in (p.get("active") or []) + (p.get("bench") or []):
        if x:
            out.append(_si(x.get("id") if isinstance(x, dict) else getattr(x, "id", 0)))
    return out


ABRA, KADABRA, ALAKAZAM = 741, 742, 743


def global_features(obs, my_index):
    cur = obs.get("current") or {}
    players = cur.get("players") or [{}, {}]
    me = players[my_index] if my_index < len(players) else {}
    opp = players[1 - my_index] if 1 - my_index < len(players) else {}
    turn = _si(cur.get("turn"))
    my_field = _pkm_ids(me)
    active = ((me.get("active") or [None])[0]) or {}
    active_id = _si(active.get("id")) if isinstance(active, dict) else 0
    energies = (active.get("energies") if isinstance(active, dict) else None) or []
    opp_active = ((opp.get("active") or [None])[0]) or {}
    opp_active_id = _si(opp_active.get("id")) if isinstance(opp_active, dict) else 0
    hand = me.get("hand") or []
    g = np.array(
        [
            min(turn, 20) / 20,
            1 if _si(cur.get("firstPlayer"), -1) == my_index else 0,
            len(me.get("prize") or []) / 6,
            len(opp.get("prize") or []) / 6,
            _si(me.get("handCount"), len(hand)) / 10,
            _si(me.get("deckCount")) / 60,
            len([x for x in (me.get("bench") or []) if x]) / 5,
            1 if active_id == ABRA else 0,
            1 if active_id == KADABRA else 0,
            1 if active_id == ALAKAZAM else 0,
            len(energies) / 4,
            1 if ABRA in my_field else 0,
            1 if KADABRA in my_field else 0,
            1 if ALAKAZAM in my_field else 0,
            1 if opp_active_id == 235 else 0,
            min(_si(cur.get("turnActionCount")), 20) / 20,
            1 if _si(cur.get("supporterPlayed")) else 0,
            1 if _si(cur.get("energyAttached")) else 0,
        ],
        dtype=np.float32,
    )
    return g


GLOBAL_N = 18


def option_features(
    obs: dict,
    opt: dict,
    my_index: int,
    card_vocab: "dict[int, int]",
    attack_vocab: "dict[int, int]",
) -> np.ndarray:
    sel = obs.get("select") or {}
    ctx = _si(sel.get("context"))
    otype = _si(opt.get("type"))
    area = _si(opt.get("area"))
    inplay = _si(opt.get("inPlayArea"))
    cid = option_card_id(obs, opt, my_index)
    aid = _si(opt.get("attackId"))
    nv = len(card_vocab) + 1
    na = len(attack_vocab) + 1
    f = np.zeros(TYPE_N + CTX_N + AREA_N + INPLAY_N + nv + na, dtype=np.float32)
    off = 0
    f[off + min(otype, TYPE_N - 1)] = 1
    off += TYPE_N
    f[off + min(ctx, CTX_N - 1)] = 1
    off += CTX_N
    f[off + min(area, AREA_N - 1)] = 1
    off += AREA_N
    f[off + min(inplay, INPLAY_N - 1)] = 1
    off += INPLAY_N
    f[off + card_vocab.get(cid, OOV)] = 1
    off += nv
    f[off + attack_vocab.get(aid, OOV)] = 1
    return f


def feature_dim(card_vocab, attack_vocab):
    return (
        GLOBAL_N + TYPE_N + CTX_N + AREA_N + INPLAY_N
        + len(card_vocab) + 1 + len(attack_vocab) + 1
    )


class AlakBCPolicy:
    """Numpy MLP scorer: concat(global, option) -> h1 -> h2 -> scalar."""

    def __init__(self, npz_path, json_path=None):
        npz_path = Path(npz_path)
        if json_path is None:
            json_path = npz_path.with_suffix(".json")
        w = np.load(npz_path)
        self.W1 = w["W1"]
        self.b1 = w["b1"]
        self.W2 = w["W2"]
        self.b2 = w["b2"]
        self.W3 = w["W3"]
        self.b3 = w["b3"]
        meta = json.loads(Path(json_path).read_text())
        self.card_vocab = {int(k): int(v) for k, v in meta["card_vocab"].items()}
        self.attack_vocab = {int(k): int(v) for k, v in meta["attack_vocab"].items()}

    def scores(self, obs: dict, options: "list[dict]", my_index: int) -> np.ndarray:
        g = global_features(obs, my_index)
        feats = np.stack(
            [
                np.concatenate(
                    [g, option_features(obs, o, my_index, self.card_vocab, self.attack_vocab)]
                )
                for o in options
            ]
        )
        h = np.maximum(feats @ self.W1 + self.b1, 0)
        h = np.maximum(h @ self.W2 + self.b2, 0)
        return (h @ self.W3 + self.b3).reshape(-1)


def _pick_count(sel, n):
    ctx = _si(sel.get("context"), -1)
    if ctx == 0:
        return 1
    mx = _si(sel.get("maxCount"), 1)
    mn = _si(sel.get("minCount"), 1)
    return max(1, min(n, max(mn, min(mx, n))))


def make_alak_bc_agent(npz_path, json_path=None):
    """Same interface as arena.policy.make_agent: obs_dict -> [option positions]."""
    policy = AlakBCPolicy(npz_path, json_path)

    def agent(obs):
        sel = obs.get("select") or {}
        options = sel.get("option") or []
        if not options:
            return []
        mi = _si((obs.get("current") or {}).get("yourIndex"))
        try:
            s = policy.scores(obs, options, mi)
            order = list(np.argsort(-s))
        except Exception:
            order = list(range(len(options)))
        return [int(i) for i in order[: _pick_count(sel, len(options))]]

    return agent
