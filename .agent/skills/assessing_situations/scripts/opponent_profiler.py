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
    """Identify opponent deck archetype from visible card IDs.

    Returns OpponentProfile with style/speed/signature/confidence.
    confidence < 0.3 → Unknown (prevents over-triggering state changes).
    """
    visible = _extract_visible_card_ids(obs_dict)

    if not visible:
        return _UNKNOWN

    sigs_data = _load_sigs()
    signatures: dict[str, Any] = sigs_data.get("signatures", {})

    best_key = ""
    best_score = 0.0
    best_sig: dict[str, Any] = {}

    for key, sig in signatures.items():
        fp = sig.get("fingerprint_ids", [])
        score = _jaccard(visible, fp)
        if score > best_score:
            best_score = score
            best_key = key
            best_sig = sig

    if best_score < _CONFIDENCE_THRESHOLD:
        # Fall back to heuristic flags before giving up
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

    return OpponentProfile(
        style=best_sig.get("style", "Unknown"),
        speed=best_sig.get("speed", "Unknown"),
        signature=best_key,
        confidence=round(best_score, 4),
    )


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
