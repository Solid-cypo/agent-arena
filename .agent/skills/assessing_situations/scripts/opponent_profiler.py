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
    "last_turn": -1,          # detect new battle
    "hand_counts": [],         # [(turn, count), ...]
    "active_ids": set(),       # all active card IDs seen so far
    "bench_ids": set(),        # all bench card IDs seen
    "peak_hand": 0,            # max hand count in this battle
    "min_hand": 999,           # min hand count in this battle
    "energy_t1": 0,            # opponent energy count at turn 1
}


def _reset_battle_state() -> None:
    """Reset cross-turn state in-place (preserves the dict reference for importers)."""
    _battle_state["last_turn"] = -1
    _battle_state["hand_counts"] = []
    _battle_state["active_ids"] = set()
    _battle_state["bench_ids"] = set()
    _battle_state["peak_hand"] = 0
    _battle_state["min_hand"] = 999
    _battle_state["energy_t1"] = 0


def _update_battle_state(obs_dict: dict[str, Any]) -> None:
    """Accumulate per-turn observable signals into _battle_state."""
    global _battle_state
    try:
        from cg.api import to_observation_class
        obs = to_observation_class(obs_dict)
        current = obs.current
        if current is None:
            return

        turn = int(getattr(current, "turn", 0) or 0)

        # Detect new battle: turn reset
        if turn < _battle_state["last_turn"]:
            _reset_battle_state()
        _battle_state["last_turn"] = turn

        opp_index = 1 - int(current.yourIndex)
        opp = current.players[opp_index]

        # Hand count
        hand_count = int(getattr(opp, "handCount", 5) or 5)
        _battle_state["hand_counts"].append(hand_count)
        _battle_state["peak_hand"] = max(_battle_state["peak_hand"], hand_count)
        _battle_state["min_hand"] = min(_battle_state["min_hand"], hand_count)

        # Active + bench IDs
        for p in (getattr(opp, "active", None) or []):
            if p is not None:
                cid = _safe_int(getattr(p, "id", None))
                if cid:
                    _battle_state["active_ids"].add(cid)

        for p in (getattr(opp, "bench", None) or []):
            if p is not None:
                cid = _safe_int(getattr(p, "id", None))
                if cid:
                    _battle_state["bench_ids"].add(cid)

        # Energy at turn 1 (fast energy = Burst deck signal)
        if turn <= 2 and _battle_state["energy_t1"] == 0:
            for p in (getattr(opp, "active", None) or []):
                if p is not None:
                    energies = getattr(p, "energies", None) or []
                    _battle_state["energy_t1"] = len(energies)

    except Exception:
        pass


def _behavioral_confidence_boost() -> tuple[str, str, float]:
    """Infer style/speed hint and confidence boost from behavioral patterns.

    Returns (style_hint, speed_hint, confidence_boost).
    All inputs come from _battle_state (no card IDs needed).
    """
    state = _battle_state
    counts = state["hand_counts"]

    if len(counts) < 1:
        return "Unknown", "Unknown", 0.0

    peak   = state["peak_hand"]
    low    = state["min_hand"]
    latest = counts[-1]

    # ── Signal A: Hand explosion (≥10 cards) → Tempo/draw-heavy deck ───────
    # Alakazam deck: Dudunsparce draws 2+ per turn, routinely reaches 10-19 cards
    if peak >= 10:
        return "Tempo", "Medium", 0.35

    # ── Signal B: Hand drop then refill → Control discard-draw pattern ──────
    # Tea Party: Carmine drops to 1-2, Lillie's refills to 6+
    # Characteristic: min ≤ 2 AND max ≥ 5 in same battle
    if low <= 2 and peak >= 5 and len(counts) >= 2:
        return "Control", "Slow", 0.28

    # ── Signal C: Consistent mid-range hand + moderate peak ─────────────────
    # Hops Aggro / Tempo decks: hand stays 4-8, no extreme swings
    if 4 <= latest <= 8 and peak < 10:
        return "Tempo", "Medium", 0.15

    # ── Signal D: Early energy attachment (Burst deck) ───────────────────────
    if state["energy_t1"] >= 2:
        return "Burst", "Fast", 0.20

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
    confidence: float  # Jaccard similarity ∈ [0, 1]


_UNKNOWN = OpponentProfile(style="Unknown", speed="Unknown", signature="", confidence=0.0)

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

        return OpponentProfile(
            style=style,
            speed=speed,
            signature=best_key,
            confidence=round(combined_confidence, 4),
        )

    # ── Last resort: card-level heuristic flags ───────────────────────────────
    if visible:
        flags = _heuristic_flags(visible)
        if flags["has_control_flag"]:
            return OpponentProfile(
                style="Control", speed="Unknown",
                signature="heuristic_control", confidence=0.2,
            )
        if flags["has_tempo_flag"]:
            return OpponentProfile(
                style="Tempo", speed="Unknown",
                signature="heuristic_tempo", confidence=0.2,
            )

    return _UNKNOWN


def profile_from_known_ids(card_ids: list[int]) -> OpponentProfile:
    """Profile an opponent given an explicit list of card IDs (e.g. from deck CSV).

    Useful for pre-match analysis or unit tests.
    """
    return _profile_from_set(set(card_ids))


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
    return OpponentProfile(
        style=best_sig.get("style", "Unknown"),
        speed=best_sig.get("speed", "Unknown"),
        signature=best_key,
        confidence=round(best_score, 4),
    )
