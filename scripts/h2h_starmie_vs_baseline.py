#!/usr/bin/env python3
"""Head-to-head: current submission_starmie vs a frozen baseline agent dir.

Loads each pilot into isolated module objects (clear sys.modules between loads)
so both AgentFns can coexist in one process. Seat-swaps every game.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import random
import sys
import time
from pathlib import Path

# Wave I0: pin hash seed when parent shell forgot (must be set before many imports
# for full effect; still document PYTHONHASHSEED=0 on the command line).
os.environ.setdefault("PYTHONHASHSEED", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena.simulator import play_game  # noqa: E402

# Modules that live under submission_starmie/pilot/ (flat imports).
_PILOT_MODNAMES = (
    "starmie_pilot",
    "turn_planner",
    "epoch_scheduler",
    "opening_bridge",
    "supporter_planner",
    "deck_resources",
    "draw_axis",
    "hand_snapshot",
    "legal_mask",
    "matchup_alakazam",
    "opening_bench",
    "opening_cards",
    "opening_planner",
    "opening_state",
    "opponent_roles",
    "phase_fsm",
    "rl_opening_proposer",
    "target_rules",
)


def _read_deck(agent_dir: Path) -> list[int]:
    ids: list[int] = []
    with open(agent_dir / "deck.csv", encoding="utf-8") as h:
        for line in h:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(int(line))
    return ids[:60]


def _read_weights(agent_dir: Path) -> dict:
    path = agent_dir / "weights.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as h:
        return json.load(h)


def _purge_pilot_modules() -> None:
    for name in list(sys.modules):
        if name in _PILOT_MODNAMES or name.startswith("starmie_pilot."):
            del sys.modules[name]


def load_starmie_agent(agent_dir: Path):
    """Return (agent_fn, reset_fn, module_keep_alive, deck).

    reset_fn is bound to THIS agent's agent_state so H2H dual-load works
    (global _LIVE_AGENT_STATE would otherwise only reset the last load).
    """
    agent_dir = agent_dir.resolve()
    pilot_dir = agent_dir / "pilot"
    if not pilot_dir.is_dir():
        raise FileNotFoundError(f"no pilot/ under {agent_dir}")

    _purge_pilot_modules()
    # Prefer this agent's pilot on path; keep ROOT for cg/.
    for p in (str(pilot_dir), str(agent_dir)):
        while p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    sp = importlib.import_module("starmie_pilot")
    deck = _read_deck(agent_dir)
    weights = _read_weights(agent_dir)
    agent_fn = sp.make_starmie_agent(deck, weights)
    # Capture state before the next load overwrites module globals.
    agent_state = getattr(sp, "_LIVE_AGENT_STATE", None)
    reset_state = getattr(sp, "reset_agent_state", None)

    def reset_fn() -> None:
        if callable(reset_state):
            reset_state(agent_state)
        else:
            getattr(sp, "reset_for_new_game", lambda: None)()

    return agent_fn, reset_fn, sp, deck


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--baseline",
        type=Path,
        default=Path("/tmp/baseline_55202093_f07e541"),
        help="Frozen baseline agent dir (main.py + pilot/ + deck.csv)",
    )
    ap.add_argument(
        "--current",
        type=Path,
        default=ROOT / "submission_starmie",
        help="Current agent dir under test",
    )
    ap.add_argument("-n", type=int, default=40, help="Total games (half each seat)")
    ap.add_argument("--seed", type=int, default=94000)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--rules-only",
        action="store_true",
        help="Disable RL hybrid (RL_ENABLED=0) for lower agent-side noise",
    )
    args = ap.parse_args()

    if args.rules_only:
        os.environ["RL_ENABLED"] = "0"
    print(f"baseline: {args.baseline}")
    print(f"current:  {args.current}")
    print(f"games={args.n} seed0={args.seed} RL_ENABLED={os.environ.get('RL_ENABLED', '1')}")

    # Load baseline first, then current (current modules stay on sys.path after).
    base_agent, base_reset, _base_mod, deck_base = load_starmie_agent(args.baseline)
    cur_agent, cur_reset, _cur_mod, deck_cur = load_starmie_agent(args.current)
    assert deck_base == deck_cur, "deck.csv mismatch between agents"

    wins_cur = 0
    wins_base = 0
    draws = 0
    trunc = 0
    rows: list[dict] = []
    t0 = time.time()

    for i in range(args.n):
        game_seed = args.seed + i
        random.seed(game_seed)
        os.environ["GAME_SEED"] = str(game_seed)
        try:
            import numpy as np

            np.random.seed(game_seed % (2**32 - 1))
        except Exception:
            pass
        cur_reset()
        base_reset()
        cur_is_a = (i % 2 == 0)
        if cur_is_a:
            agent_a, agent_b = cur_agent, base_agent
        else:
            agent_a, agent_b = base_agent, cur_agent
        g = play_game(agent_a, agent_b, deck_cur, deck_cur, max_steps=700)
        # reward_for_a: +1 if seat0 wins
        if g.reward_for_a == 0:
            draws += 1
            cur_win = None
        elif (g.reward_for_a == 1 and cur_is_a) or (g.reward_for_a == -1 and not cur_is_a):
            wins_cur += 1
            cur_win = True
        else:
            wins_base += 1
            cur_win = False
        if g.truncated:
            trunc += 1
        rows.append({
            "i": i,
            "cur_is_a": cur_is_a,
            "cur_win": cur_win,
            "reward_for_a": g.reward_for_a,
            "steps": g.steps,
            "truncated": g.truncated,
            "winner": g.winner,
        })
        mark = "C" if cur_win is True else ("B" if cur_win is False else "D")
        print(
            f"  [{i+1:03d}/{args.n}] seat={'cur_A' if cur_is_a else 'cur_B'} "
            f"-> {mark} steps={g.steps} "
            f"(cur {wins_cur}-{wins_base} base, d={draws})",
            flush=True,
        )

    decided = wins_cur + wins_base
    wr = (wins_cur / decided) if decided else 0.0
    elapsed = time.time() - t0
    summary = {
        "baseline": str(args.baseline),
        "current": str(args.current),
        "n": args.n,
        "seed0": args.seed,
        "wins_current": wins_cur,
        "wins_baseline": wins_base,
        "draws": draws,
        "truncated": trunc,
        "wr_current_decided": wr,
        "elapsed_s": round(elapsed, 1),
        "games": rows,
    }
    print()
    print("=== H2H SUMMARY ===")
    print(f"current vs baseline: {wins_cur}-{wins_base} (draws={draws}, trunc={trunc})")
    print(f"WR (decided): {wr:.1%}  ({wins_cur}/{decided})")
    print(f"elapsed: {elapsed:.1f}s")

    out = args.out or (ROOT / "logs" / f"h2h_vs_55202093_n{args.n}_s{args.seed}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
