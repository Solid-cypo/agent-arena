"""Minimal RL env for the OPENING phase (solitaire Goal: Mega Starmie ex + water).

Step model
----------
One env step == one v2 action. The policy emits (head1_idx, head2_idx) each
step. Turns are auto-advanced: a turn ends when the policy stalls (no-op twice
in a row) or hits the per-turn action cap, after which ``begin_turn`` draws and
the next my-turn begins. This keeps the action space identical to the gold v2
slices (no synthetic END_TURN token for BC to fight).

Reward (dense shaping + Goal bonus)
-----------------------------------
    r = (_score_opening_state(s') - _score_opening_state(s)) / 1000
        - ILLEGAL_PENALTY  if the action did not mutate the state
        + GOAL_BONUS        on opening_complete()
The score function lives in ``opening_planner._score_opening_state`` and already
encodes the Goal structure (Mega on field, watered, staryu line, gap penalties).

Done
----
``opening_complete()``  OR  ``my_turn_number > turn_limit``  OR  two consecutive
turns with zero productive actions.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from arena.deck import load_deck_csv
from opening_cards import MEGA_STARMIE, STARYU, WATER_BASIC
from opening_state import OpeningGameState
from opening_planner import _score_opening_state
from simulate_opening import shuffle_deck, mulligan_until_basic
from setup_planner import run_setup
from opening_exec import execute_v2, NON_POLICY_KINDS
from action_space_v2 import StateEncoder, legal_mask_from_state

GOAL_BONUS = 10.0
ILLEGAL_PENALTY = 0.05
SCORE_SCALE = 1000.0
ACTIONS_PER_TURN = 20
STALL_TURNS_DONE = 2  # consecutive dead turns -> terminate


class OpeningEnv:
    """v2 opening env. ``reset(seed, going_first)`` -> obs; ``step(a1, a2)`` -> transition."""

    def __init__(self, deck_path: str, head1_to_idx, idx_to_head1,
                 head2_to_idx, idx_to_head2, turn_limit: int = 3,
                 going_first: bool | None = None):
        self.deck = load_deck_csv(deck_path)
        self.h1 = head1_to_idx
        self.h1i = idx_to_head1
        self.h2 = head2_to_idx
        self.h2i = idx_to_head2
        self.turn_limit = turn_limit
        self.default_going_first = going_first
        self.encoder = StateEncoder(sorted(set(self.deck)))
        self.st: OpeningGameState | None = None
        self._turn_actions = 0
        self._stall_steps = 0
        self._dead_turns = 0
        self._score_prev = 0.0

    # ------------------------------------------------------------------ #
    @property
    def feat_dim(self) -> int:
        return self.encoder.feature_dim

    @property
    def n_head1(self) -> int:
        return len(self.h1)

    @property
    def n_head2(self) -> int:
        return len(self.h2)

    def reset(self, seed: int, going_first: bool | None = None,
              setup_actions: list[tuple[str, int | None, int | None]] | None = None,
              archetype: str = "") -> np.ndarray:
        gf = self.default_going_first if going_first is None else going_first
        if gf is None:
            gf = (seed % 2 == 0)
        ordered = shuffle_deck(self.deck, seed)
        st = OpeningGameState.from_ordered_deck(ordered, going_first=gf)
        mulligan_until_basic(st)
        if setup_actions is None:
            run_setup(st)
        else:
            # Replay the expert's setup choices so DAgger can reproduce gold states.
            for kind, primary, sub in setup_actions:
                execute_v2(st, kind, primary, sub)
            st.setup_archetype = archetype
        # First my-turn: going-first -> turn 1, my_t 1 (no draw); else turn 2, my_t 1 (draw).
        turn = 1 if gf else 2
        st.begin_turn(turn, 1)
        self.st = st
        self._turn_actions = 0
        self._stall_steps = 0
        self._dead_turns = 0
        self._score_prev = float(_score_opening_state(st))
        return self.encoder.encode(st)

    def legal_mask(self) -> np.ndarray:
        return legal_mask_from_state(self.st, self.h1)

    def _begin_next_turn(self) -> None:
        st = self.st
        produced = self._turn_actions
        if produced == 0:
            self._dead_turns += 1
        else:
            self._dead_turns = 0
        self._turn_actions = 0
        self._stall_steps = 0
        next_my_t = st.my_turn_number + 1
        next_turn = st.current_turn + 2  # my turn + opponent turn (unmodelled)
        st.begin_turn(next_turn, next_my_t)
        self._score_prev = float(_score_opening_state(st))

    def step(self, h1_idx: int, h2_idx: int | None = None) -> tuple[
        np.ndarray, float, bool, dict[str, Any]]:
        st = self.st
        kind, primary = self.h1i[h1_idx]
        sub = self.h2i[h2_idx] if h2_idx is not None else None
        if sub is not None and kind not in ("PLAY_POFFIN", "PLAY_HILDA", "PLAY_CRISPIN", "ATTACH"):
            sub = None  # head2 only meaningful on compound kinds

        score_before = float(_score_opening_state(st))
        ok = execute_v2(st, kind, primary, sub)
        score_after = float(_score_opening_state(st))

        shaped = (score_after - score_before) / SCORE_SCALE
        if not ok:
            shaped -= ILLEGAL_PENALTY
            self._stall_steps += 1
        else:
            self._stall_steps = 0
            self._turn_actions += 1

        done = False
        goal = st.opening_complete()
        if goal:
            shaped += GOAL_BONUS
            done = True

        # Turn management: stall twice OR action cap -> advance turn.
        if not done and (self._stall_steps >= 2 or self._turn_actions >= ACTIONS_PER_TURN):
            self._begin_next_turn()
            if st.my_turn_number > self.turn_limit:
                done = True
            elif self._dead_turns >= STALL_TURNS_DONE:
                done = True

        # Re-baseline so next step's Δ is measured from the new turn state.
        if not done:
            self._score_prev = float(_score_opening_state(st))

        info = {
            "ok": ok, "goal": goal, "kind": kind, "primary": primary, "sub": sub,
            "score": score_after, "turn": st.my_turn_number,
        }
        return self.encoder.encode(st), float(shaped), done, info
