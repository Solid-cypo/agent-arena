"""Faithful replay of gold trajectories for DAgger hard-set collection.

The gold log records each my-turn's auto-draw as a DRAW step. Turn sync:

* going-first  : T1 has no draw; the first DRAW step == T2 draw.
* going-second : T1 draws; the FIRST DRAW step == that T1 draw (consumed here
  without advancing the turn), subsequent DRAW steps advance the turn.

``iter_decision_states`` replays a trajectory and yields ``(live_state, v2_action)``
for each expert decision step, with ``live_state`` synced up to *just before* the
decision. This is the DAgger primitive: run the pilot on ``live_state`` and
compare its action to ``v2_action``; disagreements go into the hard set.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from arena.deck import load_deck_csv
from opening_state import OpeningGameState
from simulate_opening import shuffle_deck, mulligan_until_basic
from opening_exec import execute_v2
from export_sft_slices_v2 import v2_action_for_step, _is_effect_step


def _manual_t1_start(st: OpeningGameState, going_first: bool) -> None:
    """Begin T1 without auto-drawing (the gold's DRAW step drives the draw)."""
    st.current_turn = 1 if going_first else 2
    st.my_turn_number = 1
    st.supporter_played = False
    st.energy_attached = False


def iter_decision_states(traj: dict, deck: list[int]) -> Iterator[tuple[OpeningGameState, tuple[str, int | None, int | None], dict]]:
    """Yield (state_before, v2_action, step) for each expert decision in a trajectory."""
    seed = traj["seed"]
    gf = traj["going_first"]
    st = OpeningGameState.from_ordered_deck(shuffle_deck(deck, seed), going_first=gf)
    mulligan_until_basic(st)
    _manual_t1_start(st, gf)

    first_draw_consumed = False
    steps = traj["steps"]
    for i, step in enumerate(steps):
        k = step["action"]["kind"]
        if k == "DRAW":
            if (not gf) and (not first_draw_consumed):
                # going-second T1 draw: draw one card, no turn advance.
                if st.deck:
                    st.hand.append(st.deck.pop(0))
                first_draw_consumed = True
                continue
            # subsequent my-turn draw
            st.my_turn_number += 1
            st.current_turn += 2
            st.supporter_played = False
            st.energy_attached = False
            if st.deck:
                st.hand.append(st.deck.pop(0))
            continue
        if _is_effect_step(step):
            continue
        # decision step: snapshot state BEFORE applying
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        v2 = v2_action_for_step(step, nxt)
        if v2 is None:
            continue
        yield st, v2, step
        # apply the expert decision to advance the state
        execute_v2(st, *v2)


def replay_trajectory(traj: dict, deck: list[int]) -> dict:
    """Replay a full trajectory; return {goal, mismatches, exec_fails, n_decisions}."""
    gf = traj["going_first"]
    st = OpeningGameState.from_ordered_deck(shuffle_deck(deck, traj["seed"]), going_first=gf)
    mulligan_until_basic(st)
    _manual_t1_start(st, gf)
    first_draw_consumed = False
    mism = 0
    fails = 0
    ndec = 0
    steps = traj["steps"]
    for i, step in enumerate(steps):
        k = step["action"]["kind"]
        if k == "DRAW":
            expected = step["action"].get("card_id")
            if (not gf) and (not first_draw_consumed):
                drawn = st.deck.pop(0) if st.deck else None
                if drawn is not None:
                    st.hand.append(drawn)
                first_draw_consumed = True
                if drawn != expected:
                    mism += 1
                continue
            st.my_turn_number += 1
            st.current_turn += 2
            st.supporter_played = False
            st.energy_attached = False
            drawn = st.deck.pop(0) if st.deck else None
            if drawn is not None:
                st.hand.append(drawn)
            if drawn != expected:
                mism += 1
            continue
        if k in ("SETUP_ACTIVE", "SETUP_BENCH"):
            execute_v2(st, k, step["action"]["card_id"], None)
            continue
        if _is_effect_step(step):
            continue
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        v2 = v2_action_for_step(step, nxt)
        if v2 is None:
            continue
        ndec += 1
        if not execute_v2(st, *v2):
            fails += 1
    return {"goal": st.opening_complete(), "mismatches": mism, "exec_fails": fails,
            "n_decisions": ndec, "going_first": gf, "seed": traj["seed"]}


if __name__ == "__main__":
    import json
    from pathlib import Path
    deck = load_deck_csv("submission_starmie/deck.csv")
    traj_path = Path(__file__).resolve().parents[4] / "data" / "opening_sft" / "traj.jsonl"
    results = []
    for line in traj_path.open(encoding="utf-8"):
        o = json.loads(line)
        if o.get("expert_status") != "edited":
            continue
        results.append(replay_trajectory(o, deck))
    goal = sum(1 for r in results if r["goal"])
    mism = sum(r["mismatches"] for r in results)
    fails = sum(r["exec_fails"] for r in results)
    print(f"edited trajectories: {len(results)}  replay-goal: {goal}  draw_mismatch: {mism}  exec_fails: {fails}")
    # show non-goal ones
    for r in results:
        if not r["goal"]:
            print(f"  MISS seed={r['seed']} gf={r['going_first']} mism={r['mismatches']} fails={r['exec_fails']} ndec={r['n_decisions']}")
