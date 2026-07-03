"""v2 action space + encoding for the OPENING phase.

Two policy heads sharing one state encoder:

* head1 = (kind, primary)  - flat vocab over the v2 kinds x primary card ids.
  Supervised on EVERY gold slice. This is the main action choice.
* head2 = sub              - vocab over secondary target card ids (+ NONE).
  Supervised only on COMPOUND_KINDS (PLAY_POFFIN / PLAY_HILDA / PLAY_CRISPIN /
  ATTACH). NONE everywhere else.

legal_mask is permissive by design (matches the v1 philosophy that produced
workable SFT): it blocks only structurally impossible actions, never borderline
strategy choices. Two entry points:

* ``legal_mask_from_state(st, vocab)``  - authoritative; used by the RL env and
  rollout (knows fan_call_used, can_evolve_now, ...).
* ``legal_mask_from_slice(sl, vocab)``  - permissive; used for the BC sanity
  check on frozen gold slices (evolve-turn / fan_call unknown -> allowed).
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from opening_cards import (
    BASIC_IDS,
    BOSS_ORDERS,
    CRISPIN,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    ENERGY_IDS,
    HILDA,
    ITEM_IDS,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    POFFIN,
    POKE_PAD,
    PRISM,
    SALVATOR,
    STARYU,
    SUPPORTER_IDS,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
    WATER_ENERGY_IDS,
    WALLYS_COMPASSION,
    can_retreat_pokemon,
    name,
)
from opening_exec import V2_KINDS, NON_POLICY_KINDS, COMPOUND_KINDS, NIGHT_STRETCHER

HEAD2_NONE = -1

# card id vocab is built from the deck; placeholder until ``build_vocabs`` fills it.
_CARD_VOCAB: list[int] = []


# --------------------------------------------------------------------------- #
# Vocab construction
# --------------------------------------------------------------------------- #
def build_vocabs(slices: Iterable[dict[str, Any]],
                 card_vocab: list[int] | None = None) -> tuple[
    dict[tuple[str, int | None], int],
    list[tuple[str, int | None]],
    dict[int, int],
    list[int],
]:
    """Build head1 and head2 vocabs from v2 slices.

    Each slice is expected to carry ``action = {'kind', 'primary', 'sub'}``.
    """
    global _CARD_VOCAB
    if card_vocab is None:
        card_vocab = sorted({c for s in slices for c in (s.get("hand_ids") or [])
                             if isinstance(c, int)})
    _CARD_VOCAB = list(card_vocab)

    head1_set: set[tuple[str, int | None]] = set()
    head2_set: set[int] = set()
    for s in slices:
        a = s["action"]
        head1_set.add((a["kind"], a.get("primary")))
        sub = a.get("sub")
        if sub is not None:
            head2_set.add(sub)
    # Always let NONE be reachable on head2.
    head2_set.add(HEAD2_NONE)

    # Guarantee a few structural anchors so the mask has targets even if a kind
    # is rare in the data.
    for k in V2_KINDS:
        if k in NON_POLICY_KINDS:
            continue
        head1_set.add((k, None))

    idx_to_head1 = sorted(head1_set, key=lambda x: (x[0], -1 if x[1] is None else x[1]))
    head1_to_idx = {k: i for i, k in enumerate(idx_to_head1)}

    idx_to_head2 = sorted(head2_set)
    head2_to_idx = {k: i for i, k in enumerate(idx_to_head2)}

    return head1_to_idx, idx_to_head1, head2_to_idx, idx_to_head2


def card_vocab() -> list[int]:
    return list(_CARD_VOCAB)


# --------------------------------------------------------------------------- #
# State / slice views
# --------------------------------------------------------------------------- #
def state_view(st) -> dict[str, Any]:
    return {
        "hand": list(st.hand),
        "active_id": st.active.card_id if st.active else None,
        "active_energies": list(st.active.energies) if st.active else [],
        "bench_ids": [p.card_id for p in st.bench],
        "bench_energies": [list(p.energies) for p in st.bench],
        "supporter_played": st.supporter_played,
        "energy_attached": st.energy_attached,
        "fan_call_used": st.fan_call_used,
        "my_turn_number": st.my_turn_number,
        "deck_len": len(st.deck),
        "prize_len": len(st.prizes),
        "going_first": st.going_first,
        # accurate can-evolve per pokemon
        "active_can_evolve": st._can_evolve_now(st.active) if st.active else False,
        "bench_can_evolve": [st._can_evolve_now(p) for p in st.bench],
    }


def slice_view(sl: dict[str, Any]) -> dict[str, Any]:
    """Permissive view from a frozen pre_state (evolve/fan_call unknown)."""
    pre = sl["pre_state"] if "pre_state" in sl else sl
    board = pre["board"]
    act = board.get("active")
    bench = board.get("bench", [])
    flags = pre.get("flags", {})
    return {
        "hand": list(pre.get("hand_ids", [])),
        "active_id": act["card_id"] if act else None,
        "active_energies": list(act["energies"]) if act else [],
        "bench_ids": [b["card_id"] for b in bench],
        "bench_energies": [list(b["energies"]) for b in bench],
        "supporter_played": flags.get("supporter_played", False),
        "energy_attached": flags.get("energy_attached", False),
        "fan_call_used": False,  # unknown -> permissive
        "my_turn_number": 2,     # unknown -> permissive (allow evolve)
        "deck_len": pre.get("deck_len", 0),
        "prize_len": pre.get("prize_len", 0),
        "going_first": sl.get("going_first", True),
        "active_can_evolve": True,   # permissive
        "bench_can_evolve": [True] * len(bench),
    }


def _has_water(energies: list[int]) -> bool:
    return any(e in WATER_ENERGY_IDS for e in energies)


# --------------------------------------------------------------------------- #
# Legal mask
# --------------------------------------------------------------------------- #
def _is_legal_head1(kind: str, primary: int | None, v: dict[str, Any]) -> bool:
    hand = v["hand"]
    bench_ids = v["bench_ids"]
    active_id = v["active_id"]
    sup = v["supporter_played"]
    ea = v["energy_attached"]

    if kind in NON_POLICY_KINDS:
        return False

    if kind == "PLAY_POKEMON":
        return primary in BASIC_IDS and primary in hand and len(bench_ids) < 5

    if kind == "ATTACH":
        return (primary in ENERGY_IDS and primary in hand and not ea
                and (active_id is not None or bool(bench_ids)))

    if kind == "EVOLVE":
        if primary == MEGA_STARMIE:
            return MEGA_STARMIE in hand and any(
                pid == STARYU and can
                for pid, can in (
                    [(active_id, v["active_can_evolve"])] +
                    list(zip(bench_ids, v["bench_can_evolve"])))
            )
        if primary == DUDUNSPARCE:
            return DUDUNSPARCE in hand and any(
                pid in (DUNSPARCE_A, DUNSPARCE_B) and can
                for pid, can in (
                    [(active_id, v["active_can_evolve"])] +
                    list(zip(bench_ids, v["bench_can_evolve"])))
            )
        return False

    if kind == "PLAY_POFFIN":
        return POFFIN in hand and len(bench_ids) < 5

    if kind == "PLAY_ULTRA_BALL":
        # need Ultra Ball + >=2 discardable cards besides the ball
        return ULTRA_BALL in hand and sum(1 for c in hand if c != ULTRA_BALL) >= 2

    if kind in ("PLAY_HILDA", "PLAY_CRISPIN", "PLAY_SALVATOR",
                "PLAY_LILLIE", "PLAY_JUDGE", "PLAY_BOSS", "PLAY_COMPASSION"):
        cid = {"PLAY_HILDA": HILDA, "PLAY_CRISPIN": CRISPIN, "PLAY_SALVATOR": SALVATOR,
               "PLAY_LILLIE": LILLIE, "PLAY_JUDGE": JUDGE, "PLAY_BOSS": BOSS_ORDERS,
               "PLAY_COMPASSION": WALLYS_COMPASSION}[kind]
        return cid in hand and not sup

    if kind == "PLAY_POKE_PAD":
        return POKE_PAD in hand and len(bench_ids) < 5

    if kind == "PLAY_NIGHT_STRETCHER":
        return NIGHT_STRETCHER in hand

    if kind == "PLAY_SWITCH":
        return SWITCH in hand and MEGA_STARMIE in bench_ids

    if kind == "PLAY_SUPPORTER":
        return primary in SUPPORTER_IDS and primary in hand and not sup

    if kind == "PLAY_ITEM":
        return primary in ITEM_IDS and primary in hand

    if kind == "ABILITY_FAN_CALL":
        on_field = active_id == 174 or 174 in bench_ids  # FAN_ROTOM
        return on_field and not v["fan_call_used"]

    if kind == "ABILITY_LAST_DITCH":
        meowth_on_bench = MEOWTH_EX in bench_ids
        can_place = MEOWTH_EX in hand and len(bench_ids) < 5
        return (meowth_on_bench or can_place) and not sup

    if kind == "ABILITY_RUN_AWAY":
        return active_id == DUDUNSPARCE or DUDUNSPARCE in bench_ids

    if kind == "RETREAT":
        if not bench_ids:
            return False
        if active_id is not None:
            return can_retreat_pokemon(active_id, v["active_energies"])
        return True  # active empty -> pure promotion

    return False


def legal_mask_from_view(v: dict[str, Any],
                         head1_to_idx: dict[tuple[str, int | None], int]) -> np.ndarray:
    m = np.zeros(len(head1_to_idx), dtype=bool)
    for (kind, primary), i in head1_to_idx.items():
        if _is_legal_head1(kind, primary, v):
            m[i] = True
    return m


def legal_mask_from_state(st, head1_to_idx) -> np.ndarray:
    return legal_mask_from_view(state_view(st), head1_to_idx)


def legal_mask_from_slice(sl, head1_to_idx) -> np.ndarray:
    return legal_mask_from_view(slice_view(sl), head1_to_idx)


def head2_legal(sub: int | None, head2_to_idx: dict[int, int]) -> np.ndarray:
    """head2 mask: NONE always legal; any concrete sub always legal (permissive)."""
    m = np.ones(len(head2_to_idx), dtype=bool)
    return m


# --------------------------------------------------------------------------- #
# State encoder
# --------------------------------------------------------------------------- #
class StateEncoder:
    """Fixed-length numerical feature vector for an OPENING pre-state.

    Layout (``feature_dim`` derived from ``len(card_vocab)`` = C):
      [0:C]            hand presence multi-hot
      [C:2C]           field presence multi-hot (active + bench, capped 1)
      [2C:3C]          active card_id one-hot (all-zero if no active)
      [3C]             active_has_water
      [3C+1]           active_n_energy (capped 3)
      [3C+2]           mega_on_field
      [3C+3]           mega_watered
      [3C+4]           mega_in_hand
      [3C+5]           staryu_on_field
      [3C+6]           staryu_in_hand
      [3C+7]           dudunsparce_on_field
      [3C+8]           bench_size
      [3C+9]           supporter_played
      [3C+10]          energy_attached
      [3C+11]          fan_call_used
      [3C+12]          going_first
      [3C+13]          my_turn_number / 5
      [3C+14]          deck_len / 60
      [3C+15]          prize_len / 6
      [3C+16]          hand_size / 10
      [3C+17:3C+23]    gaps g1..g6
    """

    def __init__(self, card_vocab_list: list[int]):
        self.cv = list(card_vocab_list)
        self.cidx = {c: i for i, c in enumerate(self.cv)}
        self.C = len(self.cv)

    @property
    def feature_dim(self) -> int:
        return 3 * self.C + 23

    def encode(self, sl_or_state) -> np.ndarray:
        v = (state_view(sl_or_state) if hasattr(sl_or_state, "hand")
             else slice_view(sl_or_state))
        C = self.C
        f = np.zeros(self.feature_dim, dtype=np.float32)
        hand = v["hand"]
        field_ids = ([v["active_id"]] if v["active_id"] is not None else []) + list(v["bench_ids"])
        for c in hand:
            j = self.cidx.get(c)
            if j is not None:
                f[j] = 1.0
        for c in set(field_ids):
            j = self.cidx.get(c)
            if j is not None:
                f[C + j] = 1.0
        if v["active_id"] is not None:
            j = self.cidx.get(v["active_id"])
            if j is not None:
                f[2 * C + j] = 1.0
        b = 3 * C
        f[b + 0] = float(_has_water(v["active_energies"]))
        f[b + 1] = min(len(v["active_energies"]), 3)
        f[b + 2] = float(MEGA_STARMIE in field_ids)
        f[b + 3] = float(any(pid == MEGA_STARMIE and _has_water(e)
                             for pid, e in zip(field_ids,
                                               [v["active_energies"]] + v["bench_energies"]))
                         or (v["active_id"] == MEGA_STARMIE and _has_water(v["active_energies"])))
        f[b + 4] = float(MEGA_STARMIE in hand)
        f[b + 5] = float(STARYU in field_ids)
        f[b + 6] = float(STARYU in hand)
        f[b + 7] = float(DUDUNSPARCE in field_ids)
        f[b + 8] = float(len(v["bench_ids"]))
        f[b + 9] = float(v["supporter_played"])
        f[b + 10] = float(v["energy_attached"])
        f[b + 11] = float(v["fan_call_used"])
        f[b + 12] = float(v["going_first"])
        f[b + 13] = v["my_turn_number"] / 5.0
        f[b + 14] = v["deck_len"] / 60.0
        f[b + 15] = v["prize_len"] / 6.0
        f[b + 16] = min(len(hand), 10) / 10.0
        # gaps
        gaps = v.get("gaps") if hasattr(v, "get") else None
        if gaps is None:
            gaps = _gaps_from_view(v)
        for k in range(6):
            f[b + 17 + k] = float(bool(gaps[k + 1]) if isinstance(gaps, dict) else bool(gaps[k]))
        return f


def _gaps_from_view(v: dict[str, Any]) -> dict[int, bool]:
    """Best-effort gap flags from a view (used when gaps not precomputed)."""
    field_ids = ([v["active_id"]] if v["active_id"] is not None else []) + list(v["bench_ids"])
    mega_watered = any(pid == MEGA_STARMIE and _has_water(e)
                       for pid, e in [(v["active_id"], v["active_energies"])] +
                       list(zip(v["bench_ids"], v["bench_energies"])))
    return {
        1: STARYU not in field_ids,                         # g1: no staryu on field
        2: not mega_watered and MEGA_STARMIE in field_ids,  # g2: mega lacks water
        3: MEGA_STARMIE not in field_ids,                   # g3: no mega on field
        4: False,
        5: False,
        6: False,
    }
