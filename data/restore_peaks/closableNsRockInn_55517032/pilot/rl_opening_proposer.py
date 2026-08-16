"""Torch-free RL opening-action proposer for the Kaggle submission.

Loads the exported numpy bundle (rl_opening.npz + rl_opening.json) and, given a
live cabt observation, proposes the OPENING-phase option index the Actor-Expert
policy prefers. Pure numpy — no torch dependency on Kaggle.

Public API:
  RLProposer.load(bundle_prefix) -> RLProposer
  proposer.propose(obs, options, view, my_index) -> (option_index | None, conf)

The proposer only fires on decisions that map to a policy v2 action (PLAY /
ATTACH / EVOLVE / ABILITY / RETREAT). On CARD-search / NUMBER / END / ATTACK
decisions it defers (returns None) so the existing planner route stays in charge.

Ability no-match fix: the view may carry `offered_ability_srcs` (the set of
pokemon ids whose ABILITY option the engine is actually offering this turn).
When present, the ABILITY_* legal predicates only fire for sources that are
offered, so the policy never samples an ability that is already used / not
available (e.g. Meowth ex Last-Ditch Catch after use) and waste a proposal.
"""
from __future__ import annotations

import json
import os
from typing import Any

import numpy as np

from cg.api import AreaType, OptionType
from legal_mask import is_legal_kind
from opening_cards import (
    BOSS_ORDERS,
    CRISPIN,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    HILDA,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    SALVATOR,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    WALLYS_COMPASSION,
    WATER_BASIC,
)
from target_rules import pick_target, rule_kinds

_WATER_IDS = frozenset({WATER_BASIC, 16})  # WATER_BASIC + PRISM(16)


def _si(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return d


def ability_sources_in_options(obs, options, my_index: int) -> set[int]:
    """Return the set of pokemon ids whose ABILITY option is currently offered."""
    srcs: set[int] = set()
    try:
        p = obs.current.players[my_index]
    except Exception:
        return srcs
    for opt in options:
        if getattr(opt, "type", None) != OptionType.ABILITY:
            continue
        try:
            area = opt.area
            i = _si(getattr(opt, "index", None), -1)
            if area == AreaType.BENCH:
                b = p.bench or []
                if 0 <= i < len(b) and b[i]:
                    srcs.add(_si(getattr(b[i], "id", None)))
            elif area == AreaType.ACTIVE:
                a = (p.active or [None])[0]
                if a:
                    srcs.add(_si(getattr(a, "id", None)))
        except Exception:
            pass
    return srcs


# ── numpy feature encoder (mirrors action_space_v2.StateEncoder.encode) ────────

class _Encoder:
    def __init__(self, card_vocab: list[int]):
        self.cv = list(card_vocab)
        self.cidx = {c: i for i, c in enumerate(self.cv)}
        self.C = len(self.cv)
        self.dim = 3 * self.C + 23

    def encode(self, v: dict[str, Any]) -> np.ndarray:
        C = self.C
        f = np.zeros(self.dim, dtype=np.float32)
        hand = v["hand"]
        active_id = v["active_id"]
        bench_ids = list(v["bench_ids"])
        field_ids = ([active_id] if active_id is not None else []) + bench_ids
        for c in hand:
            j = self.cidx.get(c)
            if j is not None:
                f[j] = 1.0
        for c in set(field_ids):
            j = self.cidx.get(c)
            if j is not None:
                f[C + j] = 1.0
        if active_id is not None:
            j = self.cidx.get(active_id)
            if j is not None:
                f[2 * C + j] = 1.0
        b = 3 * C
        act_e = list(v["active_energies"]) if v["active_energies"] else []
        bench_e = v["bench_energies"]
        mega_watered = any(
            pid == MEGA_STARMIE and any(_si(e) in _WATER_IDS for e in (e_list or []))
            for pid, e_list in [(active_id, act_e)] + list(zip(bench_ids, bench_e))
        )
        f[b + 0] = float(any(_si(e) in _WATER_IDS for e in act_e))
        f[b + 1] = min(len(act_e), 3)
        f[b + 2] = float(MEGA_STARMIE in field_ids)
        f[b + 3] = float(mega_watered or (active_id == MEGA_STARMIE and any(_si(e) in _WATER_IDS for e in act_e)))
        f[b + 4] = float(MEGA_STARMIE in hand)
        f[b + 5] = float(STARYU in field_ids)
        f[b + 6] = float(STARYU in hand)
        f[b + 7] = float(DUDUNSPARCE in field_ids)
        f[b + 8] = float(len(bench_ids))
        f[b + 9] = float(v["supporter_played"])
        f[b + 10] = float(v["energy_attached"])
        f[b + 11] = float(v["fan_call_used"])
        f[b + 12] = float(v["going_first"])
        f[b + 13] = v["my_turn_number"] / 5.0
        f[b + 14] = v["deck_len"] / 60.0
        f[b + 15] = v["prize_len"] / 6.0
        f[b + 16] = min(len(hand), 10) / 10.0
        # gaps (best-effort)
        f[b + 17] = float(STARYU not in field_ids)
        f[b + 18] = float(not mega_watered and MEGA_STARMIE in field_ids)
        f[b + 19] = float(MEGA_STARMIE not in field_ids)
        f[b + 20] = 0.0
        f[b + 21] = 0.0
        f[b + 22] = 0.0
        return f


# ── legal-mask predicates (shared with action_space_v2 via legal_mask) ────────

def _is_legal(kind: str, primary: int | None, v: dict[str, Any]) -> bool:
    return is_legal_kind(kind, primary, v)


# ── Proposer ───────────────────────────────────────────────────────────────────

class RLProposer:
    def __init__(self, npz: dict, meta: dict):
        self.W = {k: npz[k] for k in npz.files}
        self.head1: list[list] = meta["head1"]            # [[kind, primary]]
        self.head2: list = meta["head2"]                  # [sub_id_or_null]
        self.h1_to_idx = {(k[0], k[1]): i for i, k in enumerate(self.head1)}
        self.feat_dim = meta["feature_dim"]
        self.n1 = meta["n_head1"]
        self.n2 = meta["n_head2"]
        self.encoder = _Encoder(meta["card_vocab"])
        self.last_action = None  # last sampled (kind, primary), for instrumentation

    @classmethod
    def load(cls, prefix: str) -> "RLProposer":
        npz = np.load(prefix + ".npz")
        with open(prefix + ".json", encoding="utf-8") as f:
            meta = json.load(f)
        return cls(npz, meta)

    # ── numpy MLP forward ──────────────────────────────────────────────────────
    def _forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # trunk: Linear(feat,128) -> ReLU -> Linear(128,128) -> ReLU
        w0, b0 = self.W["trunk.0.weight"], self.W["trunk.0.bias"]
        w2, b2 = self.W["trunk.2.weight"], self.W["trunk.2.bias"]
        h = np.maximum(0.0, x @ w0.T + b0)
        h = np.maximum(0.0, h @ w2.T + b2)
        l1 = h @ self.W["head1.weight"].T + self.W["head1.bias"]
        l2 = h @ self.W["head2.weight"].T + self.W["head2.bias"]
        return l1, l2

    def _legal_mask(self, v: dict[str, Any]) -> np.ndarray:
        m = np.zeros(self.n1, dtype=bool)
        for (kind, primary), i in self.h1_to_idx.items():
            if _is_legal(kind, primary, v):
                m[i] = True
        return m

    def _sample_action(self, v: dict[str, Any], deterministic: bool, rng: np.random.Generator):
        legal = self._legal_mask(v)
        if not legal.any():
            return None, 0.0
        x = self.encoder.encode(v)
        l1, l2 = self._forward(x)
        masked = l1.copy()
        masked[~legal] = -1e9
        # softmax
        e = np.exp(masked - masked.max())
        p = e / e.sum()
        if deterministic:
            idx = int(np.argmax(masked))
        else:
            idx = int(rng.choice(self.n1, p=p))
        conf = float(p[idx])
        kind, primary = self.head1[idx]
        # Target-rule override: for rule-kinds (PLAY_POKE_PAD) the MLP target is
        # weak (info gap); replace primary with the deterministic board-derived
        # rule pick when that (kind, primary) is a legal head1 entry. Falls back
        # to the MLP pick if the rule target is off/illegal. See target_rules.py
        # & references/gold_pipeline_and_eval.md.
        if kind in rule_kinds():
            rt = pick_target(kind, v)
            if rt is not None and rt[0] is not None and (kind, rt[0]) in self.h1_to_idx:
                ridx = self.h1_to_idx[(kind, rt[0])]
                if legal[ridx]:
                    idx = ridx
                    kind, primary = self.head1[idx]
                    conf = float(p[idx]) if p[idx] > 0 else conf
        return (kind, primary), conf

    def propose(self, obs, options, view: dict[str, Any], my_index: int,
                k: int = 4, rng: np.random.Generator | None = None,
                min_votes: int = 3, ranked: bool = True) -> tuple[int | None, float]:
        """Return (preferred_option_index, confidence) or (None, 0).

        Samples the policy k times (1 deterministic + k-1 stochastic), votes on
        the (kind, primary) action. When `ranked` is True, maps the HIGHEST-voted
        action that (a) reaches `min_votes` consensus AND (b) is actually offered
        as a cabt option this turn — walking down the vote ranking converts "top
        preference not in hand → no-match" deferrals into leads on the policy's
        next-best available action. When `ranked` is False, maps only the top-
        voted action (original behaviour). Defers (None) when no offered action
        reaches `min_votes` (ranked) or the top action isn't offered / lacks
        consensus (non-ranked).
        """
        if rng is None:
            rng = np.random.default_rng()
        votes: dict[tuple, int] = {}
        det_action, _ = self._sample_action(view, True, rng)
        if det_action is not None:
            votes[det_action] = votes.get(det_action, 0) + 1
        for _ in range(k - 1):
            a, _ = self._sample_action(view, False, rng)
            if a is not None:
                votes[a] = votes.get(a, 0) + 1
        if not votes:
            self.last_action = None
            return None, 0.0
        ranked_list = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
        # Top preference is recorded for instrumentation even if we defer.
        self.last_action = ranked_list[0][0]
        if not ranked:
            best_action, best_votes = ranked_list[0]
            if best_votes < min_votes:
                return None, float(best_votes) / k
            idx = self._map_action_to_option(obs, options, best_action, view, my_index)
            self.last_action = best_action
            return idx, float(best_votes) / k
        for action, v in ranked_list:
            if v < min_votes:
                break  # rest of the ranking has even fewer votes
            idx = self._map_action_to_option(obs, options, action, view, my_index)
            if idx is not None:
                self.last_action = action
                return idx, float(v) / k
        return None, float(ranked_list[0][1]) / k

    # ── v2 action → cabt option mapping ───────────────────────────────────────
    def _map_action_to_option(self, obs, options, action, view, my_index: int):
        kind, primary = action

        def hand_card_id(opt) -> int:
            try:
                if opt.type != OptionType.PLAY:
                    return 0
                h = obs.current.players[my_index].hand or []
                i = _si(getattr(opt, "index", None), -1)
                if 0 <= i < len(h) and h[i]:
                    return _si(getattr(h[i], "id", None))
            except Exception:
                pass
            return 0

        def ability_src_id(opt) -> int:
            try:
                if opt.type != OptionType.ABILITY:
                    return 0
                area = opt.area
                i = _si(getattr(opt, "index", None), -1)
                p = obs.current.players[my_index]
                if area == AreaType.BENCH:
                    b = p.bench or []
                    if 0 <= i < len(b) and b[i]:
                        return _si(getattr(b[i], "id", None))
                if area == AreaType.ACTIVE:
                    a = (p.active or [None])[0]
                    if a:
                        return _si(getattr(a, "id", None))
            except Exception:
                pass
            return 0

        # PLAY family: match hand card id
        play_kind_to_cid = {
            "PLAY_POFFIN": POFFIN,
            "PLAY_ULTRA_BALL": ULTRA_BALL,
            "PLAY_HILDA": HILDA,
            "PLAY_CRISPIN": CRISPIN,
            "PLAY_SALVATOR": SALVATOR,
            "PLAY_LILLIE": LILLIE,
            "PLAY_JUDGE": JUDGE,
            "PLAY_BOSS": BOSS_ORDERS,
            "PLAY_COMPASSION": WALLYS_COMPASSION,
            "PLAY_POKE_PAD": POKE_PAD,
            "PLAY_NIGHT_STRETCHER": NIGHT_STRETCHER,
            "PLAY_SWITCH": SWITCH,
        }
        if kind in play_kind_to_cid:
            want = play_kind_to_cid[kind]
            for i, opt in enumerate(options):
                if opt.type == OptionType.PLAY and hand_card_id(opt) == want:
                    return i
            return None
        if kind == "PLAY_POKEMON":
            for i, opt in enumerate(options):
                if opt.type == OptionType.PLAY and hand_card_id(opt) == primary:
                    return i
            return None
        if kind in ("PLAY_SUPPORTER", "PLAY_ITEM"):
            for i, opt in enumerate(options):
                if opt.type == OptionType.PLAY and hand_card_id(opt) == primary:
                    return i
            return None
        if kind == "ATTACH":
            # primary = energy id in hand; pick the ATTACH option with that energy.
            for i, opt in enumerate(options):
                if opt.type != OptionType.ATTACH:
                    continue
                try:
                    h = obs.current.players[my_index].hand or []
                    hi = _si(getattr(opt, "handIndex", None),
                             _si(getattr(opt, "index", None), -1))
                    if 0 <= hi < len(h) and h[hi] and _si(getattr(h[hi], "id", None)) == primary:
                        return i
                except Exception:
                    pass
            return None
        if kind == "EVOLVE":
            # EVOLVE options come in two shapes: area=HAND (select the evolution
            # card) or area=BENCH/ACTIVE (select the base to evolve). Match both.
            try:
                me = obs.current.players[my_index]
                h = me.hand or []
                hand_ids = [_si(getattr(c, "id", None)) for c in h if c]
            except Exception:
                hand_ids = []
                me = None
            for i, opt in enumerate(options):
                if opt.type != OptionType.EVOLVE:
                    continue
                try:
                    oi = _si(getattr(opt, "index", None), -1)
                    if opt.area == AreaType.HAND and me is not None:
                        if 0 <= oi < len(h) and h[oi] and _si(getattr(h[oi], "id", None)) == primary:
                            return i
                    if opt.area == AreaType.BENCH and me is not None:
                        b = me.bench or []
                        if 0 <= oi < len(b) and b[oi]:
                            base = _si(getattr(b[oi], "id", None))
                            if primary == MEGA_STARMIE and base == STARYU and MEGA_STARMIE in hand_ids:
                                return i
                            if primary == DUDUNSPARCE and base in (DUNSPARCE_A, DUNSPARCE_B) and DUDUNSPARCE in hand_ids:
                                return i
                    if opt.area == AreaType.ACTIVE and me is not None:
                        a = (me.active or [None])[0]
                        if a:
                            base = _si(getattr(a, "id", None))
                            if primary == MEGA_STARMIE and base == STARYU and MEGA_STARMIE in hand_ids:
                                return i
                            if primary == DUDUNSPARCE and base in (DUNSPARCE_A, DUNSPARCE_B) and DUDUNSPARCE in hand_ids:
                                return i
                except Exception:
                    pass
            return None
        if kind == "ABILITY_FAN_CALL":
            for i, opt in enumerate(options):
                if opt.type == OptionType.ABILITY and ability_src_id(opt) == FAN_ROTOM:
                    return i
            return None
        if kind == "ABILITY_LAST_DITCH":
            for i, opt in enumerate(options):
                if opt.type == OptionType.ABILITY and ability_src_id(opt) == MEOWTH_EX:
                    return i
            return None
        if kind == "ABILITY_RUN_AWAY":
            for i, opt in enumerate(options):
                if opt.type == OptionType.ABILITY and ability_src_id(opt) == DUDUNSPARCE:
                    return i
            return None
        if kind == "RETREAT":
            for i, opt in enumerate(options):
                if opt.type == OptionType.RETREAT:
                    return i
            return None
        return None
