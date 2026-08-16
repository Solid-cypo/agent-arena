"""Deterministic target rules for action kinds whose MLP target layer is weak.

Built from expert-gold analysis (2026-07-05). ``PLAY_POKE_PAD`` target selection
is an information-gap problem: the expert knows the deck/prizes; the agent only
sees the board. These rules encode opening-line logic from board state alone.

``PLAY_ULTRA_BALL`` hand-derived rules were tested and lost to MLP (35% vs 44%),
so they stay disabled — ``_ultra_ball_target`` is kept for reference only.

Public API: ``pick_target(kind, view) -> (primary, sub) | None``.
``view`` needs ``hand``, ``bench_ids``, ``active_id``.
"""
from __future__ import annotations

from typing import Any

from opening_cards import (
    STARYU,
    MEGA_STARMIE,
    DUDUNSPARCE,
    MEOWTH_EX,
    pad_pokemon_candidates,
)

_RULE_KINDS = frozenset({"PLAY_POKE_PAD"})


def _on_field(view: dict[str, Any]) -> set[int]:
    on: set[int] = set()
    aid = view.get("active_id")
    if aid is not None:
        on.add(aid)
    on.update(view.get("bench_ids") or [])
    return on


def _in_hand(view: dict[str, Any], cid: int) -> bool:
    return cid in (view.get("hand") or [])


def _ultra_ball_target(view: dict[str, Any]) -> int:
    """Reference only — not used by pick_target (MLP wins empirically)."""
    on = _on_field(view)
    staryu_field = STARYU in on
    mega_field = MEGA_STARMIE in on
    mega_hand = _in_hand(view, MEGA_STARMIE)
    if staryu_field and not mega_hand and not mega_field:
        return MEGA_STARMIE
    if not staryu_field and not _in_hand(view, STARYU):
        return STARYU
    if mega_field:
        return DUDUNSPARCE
    if staryu_field and mega_hand:
        return MEOWTH_EX
    return STARYU


def _poke_pad_target(view: dict[str, Any]) -> int:
    on = _on_field(view)
    cands = pad_pokemon_candidates(on_field=on)
    return cands[0] if cands else STARYU


def pick_target(kind: str, view: dict[str, Any]) -> tuple[int | None, int | None] | None:
    """Deterministic (primary, sub) for kind, or None to fall back to MLP head2."""
    if kind == "PLAY_POKE_PAD":
        return (_poke_pad_target(view), None)
    return None


def rule_kinds() -> frozenset[str]:
    return _RULE_KINDS
