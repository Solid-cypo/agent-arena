"""Re-export clean gold slices using the TRAJ's recorded pre_state (verbatim).

WHY
---
``export_gold_slices_aligned.py`` rebuilds pre_state by REPLAYING the trajectory
with the live simulator. The replay re-derives hand/board card ids from its own
deck shuffle, which DIVERGES from the expert's actual logged game (e.g. the
expert held Dunsparce_A=65 but the replay deals Dunsparce_B=305 at the same
slot). Result: 33% of slices have a pre_state whose hand/board is inconsistent
with the action's primary -> legal_mask marks the gold action illegal -> the
model is trained/evaluated on 33% garbage (state, action) pairs. This is the
single biggest suppressor of the BC metric (39.5% headline vs 58.9% on the
legal subset) and of "no training trace" at inference.

FIX
---
Take ``pre_state.hand_ids / board / deck_len / prize_len`` VERBATIM from the
traj's recorded pre_state (consistent with the logged action's card_id). Keep
the existing slice's ``action.{kind,primary,sub}`` (primary == traj card_id, so
it is consistent with the traj hand). Derive the feature-alignment flags from
the traj step sequence itself (no replay):

  * supporter_played / energy_attached : from traj pre_state.flags
  * fan_call_used   : True iff an ABILITY_FAN_CALL action occurs in an earlier step
  * my_turn_number  : 1 + (#DRAW steps with step_index < current)  (DRAW = turn start;
                      correct for policy steps, which are never DRAW)
  * active_can_evolve / bench_can_evolve : permissive True for now (non-corrupt;
                      same as the pre-feature-aligned default). Can be tightened later.

Reads : data/opening_sft/traj_gold_clean.jsonl
        data/opening_sft/state_action_v2_gold_clean.jsonl  (for action + metadata)
Writes: data/opening_sft/state_action_v2_gold_clean_v2.jsonl
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "opening_sft"


def main() -> None:
    traj_path = DATA / "traj_gold_clean.jsonl"
    slice_path = DATA / "state_action_v2_gold_clean.jsonl"
    out_path = DATA / "state_action_v2_gold_clean_v2.jsonl"

    # index traj steps by (seed, step_index); precompute per-step "before" accumulators
    traj_steps: dict[tuple[int, int], dict] = {}
    fan_call_before: dict[tuple[int, int], bool] = {}
    turn_before: dict[tuple[int, int], int] = {}
    for line in traj_path.open(encoding="utf-8"):
        if not line.strip():
            continue
        t = json.loads(line)
        seed = t["seed"]
        n_draw = 0
        fan = False
        for st in t["steps"]:
            key = (seed, st["step_index"])
            fan_call_before[key] = fan
            turn_before[key] = 1 + n_draw
            kind = st["action"]["kind"]
            if kind == "ABILITY_FAN_CALL":
                fan = True
            if kind == "DRAW":
                n_draw += 1
        for st in t["steps"]:
            traj_steps[(seed, st["step_index"])] = st

    by_kind: Counter = Counter()
    n_out = 0; n_missing = 0
    with out_path.open("w", encoding="utf-8") as fo, slice_path.open(encoding="utf-8") as fi:
        for line in fi:
            if not line.strip():
                continue
            s = json.loads(line)
            kind = s["action"]["kind"]
            key = (seed := s["seed"], s.get("step_index"))
            tstep = traj_steps.get(key)
            if tstep is None:
                n_missing += 1
                continue
            pre = tstep["pre_state"]
            bench = pre["board"]["bench"]
            new_pre = {
                "hand_ids": list(pre["hand_ids"]),
                "board": {
                    "active": dict(pre["board"]["active"]) if pre["board"]["active"] is not None else None,
                    "bench": [dict(b) for b in bench],
                },
                "deck_len": pre.get("deck_len", 0),
                "prize_len": pre.get("prize_len", 0),
                "flags": {
                    "supporter_played": bool(pre.get("flags", {}).get("supporter_played", False)),
                    "energy_attached": bool(pre.get("flags", {}).get("energy_attached", False)),
                    "fan_call_used": bool(fan_call_before.get(key, False)),
                    "my_turn_number": int(turn_before.get(key, 1)),
                    "going_first": bool(s.get("going_first", True)),
                    "active_can_evolve": True,   # permissive (non-corrupt); tighten later if needed
                    "bench_can_evolve": [True] * len(bench),
                },
            }
            rec = {
                "seed": s["seed"],
                "going_first": s.get("going_first"),
                "turn_limit": s.get("turn_limit"),
                "archetype": s.get("archetype", ""),
                "source": s.get("source", ""),
                "goal_reached": s.get("goal_reached"),
                "step_index": s.get("step_index", 0),
                "phase": s.get("phase", ""),
                "difficulty": s.get("difficulty", ""),
                "pre_state": new_pre,
                "action": s["action"],          # keep existing (primary, sub) -- consistent with traj hand
                "action_zh": s.get("action_zh", ""),
            }
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            by_kind[kind] += 1
            n_out += 1

    print(f"wrote {n_out} slices -> {out_path}  (missing traj: {n_missing})")
    print("by_kind:")
    for k, c in by_kind.most_common():
        print(f"  {k:>22} {c}")


if __name__ == "__main__":
    main()
