"""Phase 0+ legality checks for OPENING simulation logs."""
from __future__ import annotations

import ast
import re

from opening_cards import (
    BASIC_IDS,
    FAN_CALL_IDS,
    HILDA,
    MEGA_STARMIE,
    PRISM,
    STARYU,
    can_retreat_pokemon,
    is_pad_legal_target,
    name,
    retreat_cost_for,
)
from opening_state import Action, OpeningGameState, Pokemon


def can_retreat(p: Pokemon | None) -> bool:
    if p is None:
        return True
    return can_retreat_pokemon(p.card_id, p.energies)


def validate_log(st: OpeningGameState) -> list[str]:
    """Return human-readable rule violations found in the action log."""
    violations: list[str] = []
    board = _BoardSnapshot()

    for i, action in enumerate(st.log):
        violations.extend(_check_action(action, board, index=i))
        board.apply(action, st)
        if action.kind == "EVOLVE":
            for p in [board.active, *board.bench]:
                if p and p.card_id not in BASIC_IDS and PRISM in p.energies:
                    violations.append(
                        f"log[{i}] [EVOLVE]: Prism on non-Basic {name(p.card_id)} (E-PRISM-1)"
                    )

    return violations


class _BoardSnapshot:
    """Minimal replay state for post-hoc legality checks."""

    def __init__(self) -> None:
        self.active: Pokemon | None = None
        self.bench: list[Pokemon] = []
        self.retreat_cost_paid: bool = False

    def apply(self, action: Action, st: OpeningGameState) -> None:
        if action.kind == "SETUP_ACTIVE" and action.card_id is not None:
            self.active = Pokemon(action.card_id, 0)
        elif action.kind == "SETUP_BENCH" and action.card_id is not None:
            self.bench.append(Pokemon(action.card_id, 0))
        elif action.kind == "PLAY_POKEMON" and action.card_id is not None:
            self.bench.append(Pokemon(action.card_id, st.current_turn))
        elif action.kind == "ATTACH" and action.card_id is not None:
            target = _parse_attach_target(action.detail, self)
            if target is not None:
                target.energies.append(action.card_id)
        elif action.kind == "DISCARD" and action.card_id is not None:
            target = _parse_discard_target(action.detail, self)
            if target is not None and action.card_id in target.energies:
                target.energies.remove(action.card_id)
            if "Retreat cost" in action.detail:
                self.retreat_cost_paid = True
        elif action.kind == "RETREAT":
            promoted_name = action.detail.split("←")[-1].strip() if "←" in action.detail else ""
            promoted = _find_by_name(promoted_name, self)
            if promoted is not None:
                if self.active:
                    self.bench.append(self.active)
                if promoted in self.bench:
                    self.bench.remove(promoted)
                self.active = promoted
        elif action.kind == "SWITCH":
            idx = next(
                (j for j, p in enumerate(self.bench) if p.card_id == MEGA_STARMIE),
                None,
            )
            if idx is not None and self.active:
                old = self.active
                self.active = self.bench.pop(idx)
                self.bench.append(old)
        elif action.kind == "EVOLVE":
            for p in [self.active, *self.bench]:
                if p and p.card_id == STARYU:
                    p.card_id = MEGA_STARMIE
                    _strip_prism_if_non_basic(p)
                    break


def _strip_prism_if_non_basic(p: Pokemon) -> None:
    if p.card_id in BASIC_IDS:
        return
    p.energies = [e for e in p.energies if e != PRISM]


def _parse_attach_target(detail: str, board: _BoardSnapshot) -> Pokemon | None:
    if "on active" in detail or "→ active" in detail.lower():
        return board.active
    for p in board.bench:
        cname = name(p.card_id)
        if cname in detail:
            return p
    return board.active


def _parse_discard_target(detail: str, board: _BoardSnapshot) -> Pokemon | None:
    if "Retreat cost" in detail:
        return board.active
    if "from" in detail:
        for p in [board.active, *board.bench]:
            if p and name(p.card_id) in detail:
                return p
    return board.active


def _find_by_name(cname: str, board: _BoardSnapshot) -> Pokemon | None:
    if board.active and name(board.active.card_id) == cname:
        return board.active
    for p in board.bench:
        if name(p.card_id) == cname:
            return p
    return None


def _parse_fan_call_picks(detail: str) -> list[str]:
    m = re.search(r"Fan Call → (\[.*\])", detail)
    if not m:
        return []
    try:
        return list(ast.literal_eval(m.group(1)))
    except (SyntaxError, ValueError):
        return []


def _name_to_id(cname: str) -> int | None:
    from opening_cards import CARD_NAMES

    for cid, n in CARD_NAMES.items():
        if n == cname:
            return cid
    return None


def _check_action(action: Action, board: _BoardSnapshot, *, index: int) -> list[str]:
    violations: list[str] = []
    prefix = f"log[{index}] [{action.kind}]"

    if action.kind == "RETREAT":
        if (
            board.active
            and not can_retreat(board.active)
            and not board.retreat_cost_paid
        ):
            violations.append(
                f"{prefix}: illegal retreat — {name(board.active.card_id)} lacks energy"
            )
        board.retreat_cost_paid = False

    if action.kind == "NOTE" and "Retreat promote" in action.detail:
        violations.append(f"{prefix}: deprecated illegal retreat path")

    if action.kind == "ABILITY_FAN_CALL":
        for cname in _parse_fan_call_picks(action.detail):
            cid = _name_to_id(cname)
            if cid is not None and cid not in FAN_CALL_IDS:
                violations.append(
                    f"{prefix}: Fan Call retrieved non-{{C}} Pokémon {cname} (E-FAN-C1)"
                )

    if action.kind == "PLAY_TRAINER" and "Poké Pad →" in action.detail:
        target_name = action.detail.split("→")[-1].strip()
        target_id = _name_to_id(target_name)
        if target_id is not None and not is_pad_legal_target(target_id):
            violations.append(f"{prefix}: Pad searched illegal target {target_name}")

    if (
        action.kind == "PLAY_TRAINER"
        and action.card_id == HILDA
        and "Hilda →" in action.detail
        and "Staryu" in action.detail
        and "Mega Starmie" not in action.detail
    ):
        violations.append(f"{prefix}: Hilda retrieved Basic Staryu (E-HILDA-1)")

    return violations


def assert_legal_simulation(st: OpeningGameState) -> None:
    violations = validate_log(st)
    if violations:
        raise AssertionError("OPENING rule violations:\n" + "\n".join(violations))
