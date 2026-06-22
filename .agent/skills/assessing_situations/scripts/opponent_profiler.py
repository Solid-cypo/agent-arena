"""Skill 1: Opponent Profiler — identify opponent deck style from visible card IDs.

Uses Jaccard similarity against meta_signatures.json fingerprints.
Returns OpponentProfile(style, speed, signature, confidence).

Inputs:
  - Set of card IDs visible from obs (opponent active, bench, discard, hand — all face-up)
  - meta_signatures.json loaded from references/

confidence >= 0.3: return best match
confidence <  0.3: return Unknown (prevents over-triggering FSM state changes)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parents[1]
_SIGNATURES_PATH = _SKILL_ROOT / "references" / "meta_signatures.json"
_TACTIC_PATH = _SKILL_ROOT / "references" / "card_tactic_weights.json"

_sigs: dict[str, Any] | None = None
_tactic_cfg: dict[str, Any] | None = None

# ---------------------------------------------------------------------------
# Cross-turn behavioral state  (resets when game turn number drops → new battle)
# ---------------------------------------------------------------------------

_battle_state: dict[str, Any] = {
    # ── Meta ─────────────────────────────────────────────────────────────
    "last_turn": -1,

    # ── S_hand dimension signals ─────────────────────────────────────────
    # Root: 手牌 → Tempo decks drive from hand; their hand peaks high
    # and recovers quickly after disruption.
    "hand_counts": [],          # per-turn opp handCount values
    "peak_hand": 0,             # highest opp hand count seen
    "min_hand": 999,            # lowest opp hand count seen
    "hand_deltas": [],          # turn-over-turn Δ hand count

    # ── S_board dimension signals ─────────────────────────────────────────
    # Root: 場面 → Burst decks charge energy fast; board grows fast.
    "active_ids": set(),        # all active Pokemon IDs seen
    "bench_ids": set(),         # all bench Pokemon IDs seen
    "bench_count_by_turn": [],  # per-turn bench count
    "energy_counts": [],        # per-turn energy attached to opp active
    "energy_t1": 0,             # energy on opp active at T1-T2 (fast charge = Burst)
    "peak_energy": 0,           # max energy ever seen on one Pokemon
    "hp_loss_per_turn": [],     # opp active HP drops (attack aggressiveness proxy)

    # ── S_turn dimension signals ──────────────────────────────────────────
    # Root: 規則 → Control decks manipulate prize/hand rules, slow TC_opp.
    "prize_counts": [],         # per-turn opp prizeCount
    "prizes_lost": 0,           # total prizes opponent has taken from us
    "first_attack_turn": 999,   # turn when opp first attacked (HP drop detected)
}


def _reset_battle_state() -> None:
    """Reset cross-turn state in-place (preserves the dict reference for importers)."""
    _battle_state["last_turn"] = -1
    _battle_state["hand_counts"] = []
    _battle_state["peak_hand"] = 0
    _battle_state["min_hand"] = 999
    _battle_state["hand_deltas"] = []
    _battle_state["active_ids"] = set()
    _battle_state["bench_ids"] = set()
    _battle_state["bench_count_by_turn"] = []
    _battle_state["energy_counts"] = []
    _battle_state["energy_t1"] = 0
    _battle_state["peak_energy"] = 0
    _battle_state["hp_loss_per_turn"] = []
    _battle_state["prize_counts"] = []
    _battle_state["prizes_lost"] = 0
    _battle_state["first_attack_turn"] = 999


def _update_battle_state(obs_dict: dict[str, Any]) -> None:
    """Accumulate per-turn three-dimensional signals into _battle_state."""
    try:
        from cg.api import to_observation_class
        obs = to_observation_class(obs_dict)
        current = obs.current
        if current is None:
            return

        turn = int(getattr(current, "turn", 0) or 0)
        if turn < _battle_state["last_turn"]:
            _reset_battle_state()
        _battle_state["last_turn"] = turn

        my_index  = int(current.yourIndex)
        opp_index = 1 - my_index
        opp = current.players[opp_index]
        me  = current.players[my_index]

        # ── S_hand: hand count per turn ───────────────────────────────────
        hand_count = int(getattr(opp, "handCount", 5) or 5)
        prev_hand  = _battle_state["hand_counts"][-1] if _battle_state["hand_counts"] else hand_count
        _battle_state["hand_counts"].append(hand_count)
        _battle_state["hand_deltas"].append(hand_count - prev_hand)
        _battle_state["peak_hand"] = max(_battle_state["peak_hand"], hand_count)
        _battle_state["min_hand"]  = min(_battle_state["min_hand"],  hand_count)

        # ── S_board: bench size + energy per active + card IDs ────────────
        bench = getattr(opp, "bench", None) or []
        bench_count = sum(1 for p in bench if p is not None)
        _battle_state["bench_count_by_turn"].append(bench_count)

        active_list = getattr(opp, "active", None) or []
        for p in active_list:
            if p is not None:
                cid = _safe_int(getattr(p, "id", None))
                if cid:
                    _battle_state["active_ids"].add(cid)
                energies = getattr(p, "energies", None) or []
                e_count = len(energies)
                _battle_state["energy_counts"].append(e_count)
                _battle_state["peak_energy"] = max(_battle_state["peak_energy"], e_count)
                if turn <= 2 and _battle_state["energy_t1"] == 0 and e_count > 0:
                    _battle_state["energy_t1"] = e_count

        for p in bench:
            if p is not None:
                cid = _safe_int(getattr(p, "id", None))
                if cid:
                    _battle_state["bench_ids"].add(cid)

        # ── S_turn: prize count + attack detection ────────────────────────
        opp_prize_count = len(getattr(opp, "prize", None) or []) or int(getattr(opp, "prizeCount", 6) or 6)
        _battle_state["prize_counts"].append(opp_prize_count)

        # Detect if opponent attacked (our active HP dropped)
        my_active = (getattr(me, "active", None) or [None])[0]
        if my_active is not None:
            my_hp = int(getattr(my_active, "hp", 999) or 999)
            prev_hp_list = _battle_state["hp_loss_per_turn"]
            if prev_hp_list:
                loss = prev_hp_list[-1] - my_hp
                _battle_state["hp_loss_per_turn"].append(my_hp)
                if loss > 0 and _battle_state["first_attack_turn"] == 999:
                    _battle_state["first_attack_turn"] = turn
            else:
                _battle_state["hp_loss_per_turn"].append(my_hp)

    except Exception:
        pass


def _dimensional_scores() -> dict[str, float]:
    """Compute three normalised dimensional scores [0..1] for the OPPONENT.

    Based on the Three-Dimensional Theory (ptcg_dimension_theory.md):
      S_hand:  hand resource richness & stability
      S_board: board/energy setup speed
      S_turn:  prize clock aggressiveness

    Returns a dict with keys: s_hand, s_board, s_turn, hand_volatility.
    """
    state = _battle_state
    counts = state["hand_counts"]
    n = max(len(counts), 1)

    # ── S_hand proxy ──────────────────────────────────────────────────────
    peak  = state["peak_hand"]
    low   = state["min_hand"] if state["min_hand"] < 999 else peak
    # Tempo root: hand engine drives consistently high hand counts
    s_hand = min(1.0, peak / 15.0)           # normalise: 15 = upper bound (嘟嘟利 max)
    # Volatility: high swing = control discard-draw pattern
    hand_volatility = (peak - low) / max(peak, 1)

    # ── S_board proxy ─────────────────────────────────────────────────────
    # Burst root: energy attaches fast, bench grows fast
    e_counts = state["energy_counts"]
    avg_energy = sum(e_counts) / len(e_counts) if e_counts else 0.0
    bench_counts = state["bench_count_by_turn"]
    avg_bench = sum(bench_counts) / len(bench_counts) if bench_counts else 0.0
    s_board = min(1.0, (avg_energy / 3.0 + avg_bench / 3.0) / 2.0)

    # ── S_turn proxy ──────────────────────────────────────────────────────
    # Burst: attacks early (low first_attack_turn)
    first_atk = state["first_attack_turn"]
    s_turn = 1.0 - min(1.0, first_atk / 8.0)  # T2 attack → s_turn=0.75, T6+ → 0.25

    return {
        "s_hand": s_hand,
        "s_board": s_board,
        "s_turn": s_turn,
        "hand_volatility": hand_volatility,
        "peak_hand": peak,
        "min_hand": low,
        "energy_t1": state["energy_t1"],
    }


def _infer_tactical_root(dim: dict[str, float]) -> str:
    """Identify the deck's 战术根 (tactical root) from dimensional scores.

    Theory (ptcg_dimension_theory.md §2):
      Burst   → root: 场面 (board/energy)  — win by prize-clock speed
      Tempo   → root: 手牌 (hand)          — win by resource accumulation
      Control → root: 規則 (rules)         — win by disrupting opponent resources

    Returns one of: "场面", "手牌", "規則", "Unknown"
    """
    s_hand        = dim["s_hand"]
    s_board       = dim["s_board"]
    hand_vol      = dim["hand_volatility"]
    peak_hand     = dim["peak_hand"]
    energy_t1     = dim["energy_t1"]

    # Control root: high hand volatility (discard-draw cycles are distinctive)
    if hand_vol >= 0.5 and dim["min_hand"] <= 2:
        return "規則"

    # Tempo root: hand dimension clearly dominant (draw engine)
    if peak_hand >= 8 and s_hand >= 0.5 and hand_vol < 0.5:
        return "手牌"

    # Burst root: board/energy setup is fast
    if energy_t1 >= 2 or s_board >= 0.4:
        return "場面"

    return "Unknown"


def _behavioral_confidence_boost() -> tuple[str, str, float]:
    """Three-dimensional style/speed classifier.

    Implements the nine-square grid from ptcg_dimension_theory.md §2.
    Returns (style_hint, speed_hint, confidence_boost).
    """
    state  = _battle_state
    counts = state["hand_counts"]
    if not counts:
        return "Unknown", "Unknown", 0.0

    dim  = _dimensional_scores()
    root = _infer_tactical_root(dim)

    peak      = dim["peak_hand"]
    low       = dim["min_hand"]
    hand_vol  = dim["hand_volatility"]
    energy_t1 = dim["energy_t1"]
    s_board   = dim["s_board"]
    s_turn    = dim["s_turn"]

    # ── Style classification (九宫格 Style axis) ──────────────────────────
    # Control (控手): root = 規則, high hand volatility
    if root == "規則":
        style, boost = "Control", 0.30
        speed = "Slow" if s_turn < 0.4 else "Medium"
        return style, speed, boost

    # Tempo (運營): root = 手牌, draw engine dominant
    if root == "手牌":
        style, boost = "Tempo", 0.35
        speed = "Fast" if s_turn >= 0.6 else "Medium"
        return style, speed, boost

    # Burst (爆発): root = 場面, energy fast
    if root == "場面":
        style, boost = "Burst", 0.28
        speed = "Fast" if energy_t1 >= 2 else "Medium"
        return style, speed, boost

    # Weak signals — use dimensional tiebreakers
    if peak >= 10:
        return "Tempo", "Medium", 0.30
    if low <= 2 and peak >= 5 and len(counts) >= 2:
        return "Control", "Slow", 0.22
    if energy_t1 >= 2:
        return "Burst", "Fast", 0.18

    return "Unknown", "Unknown", 0.05


def _load_sigs() -> dict[str, Any]:
    global _sigs
    if _sigs is None:
        _sigs = json.loads(_SIGNATURES_PATH.read_text(encoding="utf-8"))
    return _sigs


def _load_tactic() -> dict[str, Any]:
    global _tactic_cfg
    if _tactic_cfg is None:
        _tactic_cfg = json.loads(_TACTIC_PATH.read_text(encoding="utf-8"))
    return _tactic_cfg


@dataclass(frozen=True)
class OpponentProfile:
    style: str       # "Burst" | "Tempo" | "Control" | "Unknown"
    speed: str       # "Fast" | "Medium" | "Slow" | "Unknown"
    signature: str   # key from meta_signatures.json, or ""
    confidence: float  # combined Jaccard + behavioral ∈ [0, 1]
    root: str = "Unknown"  # 战术根: "場面" | "手牌" | "規則" | "Unknown"
    # Counter-strategy: what WE should do against this root
    # 場面 → disrupt board (KO setup early)
    # 手牌 → disrupt hand (Xerosic, Iono)
    # 規則 → break rules (Enhanced Hammer 1081)


_UNKNOWN = OpponentProfile(
    style="Unknown", speed="Unknown", signature="", confidence=0.0, root="Unknown"
)

_CONFIDENCE_THRESHOLD = 0.3


# ---------------------------------------------------------------------------
# Card ID extraction helpers
# ---------------------------------------------------------------------------

def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_visible_card_ids(obs_dict: dict[str, Any]) -> set[int]:
    """Collect all card IDs visible from opponent's side of the board."""
    ids: set[int] = []

    try:
        from cg.api import to_observation_class
        obs = to_observation_class(obs_dict)
        current = obs.current
        if current is None:
            return set()

        my_index = int(current.yourIndex)
        opp_index = 1 - my_index
        opp = current.players[opp_index]

        def _add_cards(collection: Any) -> None:
            if not collection:
                return
            for card in collection:
                if card is None:
                    continue
                cid = _safe_int(getattr(card, "id", None))
                if cid is not None and cid > 0:
                    ids.append(cid)

        _add_cards(getattr(opp, "active", []))
        _add_cards(getattr(opp, "bench", []))
        _add_cards(getattr(opp, "discard", []))

        # Revealed hand cards (face-up during search/looking phases)
        looking = getattr(current, "looking", None)
        if looking:
            _add_cards(looking)

    except Exception:
        pass

    return set(ids)


def _heuristic_flags(visible_ids: set[int]) -> dict[str, bool]:
    """Quick heuristic flags from card_tactic_weights.board_tactic."""
    cfg = _load_tactic().get("board_tactic", {})
    flags: dict[str, bool] = {"has_control_flag": False, "has_tempo_flag": False}
    for cid in visible_ids:
        card_cfg = cfg.get(str(cid), {})
        if card_cfg.get("control_flag"):
            flags["has_control_flag"] = True
        if card_cfg.get("tempo_flag"):
            flags["has_tempo_flag"] = True
    return flags


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

def _jaccard(observed: set[int], fingerprint: list[int]) -> float:
    fp_set = set(fingerprint)
    if not fp_set:
        return 0.0
    intersection = len(observed & fp_set)
    union = len(observed | fp_set)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def profile_opponent(obs_dict: dict[str, Any]) -> OpponentProfile:
    """Identify opponent deck archetype using card ID fingerprints + behavioral signals.

    Two-signal fusion:
      1. Jaccard similarity against meta_signatures.json fingerprints (card IDs)
      2. Behavioral patterns: hand count history, energy speed, draw rhythm

    confidence >= 0.3 → return profile; < 0.3 → Unknown
    """
    # Update cross-turn behavioral state first (always, even if no visible cards)
    _update_battle_state(obs_dict)

    # ── Signal 1: Jaccard card-ID fingerprint ────────────────────────────────
    visible = _extract_visible_card_ids(obs_dict)

    sigs_data = _load_sigs()
    signatures: dict[str, Any] = sigs_data.get("signatures", {})

    best_key = ""
    best_jaccard = 0.0
    best_sig: dict[str, Any] = {}

    for key, sig in signatures.items():
        fp = sig.get("fingerprint_ids", [])
        score = _jaccard(visible, fp)
        if score > best_jaccard:
            best_jaccard = score
            best_key = key
            best_sig = sig

    # ── Signal 2: Behavioral confidence boost ────────────────────────────────
    beh_style, beh_speed, beh_boost = _behavioral_confidence_boost()

    # ── Fusion: combine both signals ─────────────────────────────────────────
    combined_confidence = min(1.0, best_jaccard + beh_boost)

    if combined_confidence >= _CONFIDENCE_THRESHOLD:
        # Prefer card-ID style when Jaccard is strong; fallback to behavioral
        if best_jaccard >= _CONFIDENCE_THRESHOLD:
            style = best_sig.get("style", beh_style)
            speed = best_sig.get("speed", beh_speed)
        else:
            style = beh_style
            speed = beh_speed
            best_key = f"behavioral_{beh_style.lower()}"

        dim  = _dimensional_scores()
        root = _infer_tactical_root(dim)

        return OpponentProfile(
            style=style,
            speed=speed,
            signature=best_key,
            confidence=round(combined_confidence, 4),
            root=root,
        )

    # ── Last resort: card-level heuristic flags ───────────────────────────────
    if visible:
        flags = _heuristic_flags(visible)
        if flags["has_control_flag"]:
            return OpponentProfile(
                style="Control", speed="Unknown",
                signature="heuristic_control", confidence=0.2, root="規則",
            )
        if flags["has_tempo_flag"]:
            return OpponentProfile(
                style="Tempo", speed="Unknown",
                signature="heuristic_tempo", confidence=0.2, root="手牌",
            )

    return _UNKNOWN


def profile_from_known_ids(card_ids: list[int]) -> OpponentProfile:
    """Profile an opponent given an explicit list of card IDs (e.g. from deck CSV).

    Useful for pre-match analysis or unit tests.
    """
    return _profile_from_set(set(card_ids))


_STYLE_TO_ROOT: dict[str, str] = {
    "Burst":   "場面",
    "Tempo":   "手牌",
    "Control": "規則",
}


def _profile_from_set(visible: set[int]) -> OpponentProfile:
    sigs_data = _load_sigs()
    signatures: dict[str, Any] = sigs_data.get("signatures", {})
    best_key, best_score, best_sig = "", 0.0, {}
    for key, sig in signatures.items():
        score = _jaccard(visible, sig.get("fingerprint_ids", []))
        if score > best_score:
            best_score, best_key, best_sig = score, key, sig
    if best_score < _CONFIDENCE_THRESHOLD:
        return _UNKNOWN
    style = best_sig.get("style", "Unknown")
    return OpponentProfile(
        style=style,
        speed=best_sig.get("speed", "Unknown"),
        signature=best_key,
        confidence=round(best_score, 4),
        root=_STYLE_TO_ROOT.get(style, "Unknown"),
    )
