#!/usr/bin/env python3
"""H2H current vs baseline with live engine_logs → path metrics + loss logs.

Collects logs during the game (no same-seed re-run A/B). Derives path clocks
for both seats from the same engine_logs stream.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from arena.simulator import play_game  # noqa: E402
from combat_log_renderer import render_combat_log  # noqa: E402
from engine_log_metrics import compare_sides  # noqa: E402
from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402
from summarize_engine_audit import summarize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--baseline",
        type=Path,
        default=Path("/tmp/baseline_55202093_f07e541"),
    )
    ap.add_argument(
        "--current",
        type=Path,
        default=ROOT / "submission_starmie",
    )
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=140000)
    ap.add_argument(
        "--tag",
        default=None,
        help="Output dir tag under logs/h2h_audit_<tag>/",
    )
    ap.add_argument(
        "--logs",
        choices=("losses", "all", "none"),
        default="losses",
        help="Which games get Chinese .log (default: losses + short)",
    )
    ap.add_argument(
        "--save-jsonl",
        action="store_true",
        help="Also write raw engine_logs jsonl per game (large)",
    )
    ap.add_argument("--short-steps", type=int, default=40)
    args = ap.parse_args()

    if not args.baseline.is_dir():
        # Re-extract baseline if missing.
        import subprocess

        args.baseline.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [
                "bash", "-c",
                f"git -C {ROOT} archive f07e541:submission_starmie "
                f"| tar -x -C {args.baseline}",
            ]
        )

    tag = args.tag or f"n{args.n}_s{args.seed}"
    out_dir = ROOT / "logs" / f"h2h_audit_{tag}"
    games_dir = out_dir / "games"
    games_dir.mkdir(parents=True, exist_ok=True)

    print(f"baseline: {args.baseline}")
    print(f"current:  {args.current}")
    print(f"out:      {out_dir}")
    print(f"games={args.n} seed0={args.seed} logs={args.logs}")

    base_agent, base_reset, _bm, deck_base = load_starmie_agent(args.baseline)
    cur_agent, cur_reset, _cm, deck_cur = load_starmie_agent(args.current)
    assert deck_base == deck_cur, "deck.csv mismatch"

    wins_cur = wins_base = draws = trunc = 0
    rows: list[dict] = []
    t0 = time.time()

    for i in range(args.n):
        random.seed(args.seed + i)
        cur_reset()
        base_reset()
        cur_is_a = (i % 2 == 0)
        if cur_is_a:
            agent_a, agent_b = cur_agent, base_agent
        else:
            agent_a, agent_b = base_agent, cur_agent

        g = play_game(
            agent_a,
            agent_b,
            deck_cur,
            deck_cur,
            max_steps=700,
            collect_engine_logs=True,
        )

        if g.reward_for_a == 0:
            draws += 1
            cur_win = None
        elif (g.reward_for_a == 1 and cur_is_a) or (
            g.reward_for_a == -1 and not cur_is_a
        ):
            wins_cur += 1
            cur_win = True
        else:
            wins_base += 1
            cur_win = False
        if g.truncated:
            trunc += 1

        cur_pi = 0 if cur_is_a else 1
        sides = compare_sides(g.engine_logs, cur_pi=cur_pi)
        cur_m = sides["cur"]
        opp_m = sides["opp"]

        stem = f"game_{i:03d}"
        log_rel = f"games/{stem}.log"
        write_log = False
        if args.logs == "all":
            write_log = True
        elif args.logs == "losses":
            write_log = (cur_win is False) or (g.steps < args.short_steps)

        if write_log:
            header = {
                "seed": args.seed + i,
                "i": i,
                "opp_deck": "starmie_froslass",
                "opp_policy": "baseline_55202093",
                "we_are_a": cur_is_a,
                "winner": g.winner,
                "reward_for_us": (
                    1 if cur_win is True else (-1 if cur_win is False else 0)
                ),
                "steps": g.steps,
                "truncated": g.truncated,
                "tags": [
                    cur_m.get("path_bucket") or "?",
                    "seat_B" if not cur_is_a else "seat_A",
                    "loss" if cur_win is False else ("win" if cur_win else "draw"),
                ],
                "path_bucket": cur_m.get("path_bucket"),
                "mega_evo_my_t": cur_m.get("mega_evo_my_t"),
                "mega_gap": cur_m.get("mega_gap"),
            }
            text = render_combat_log(
                g.engine_logs,
                header=header,
                our_player_index=cur_pi,
            )
            (games_dir / f"{stem}.log").write_text(text, encoding="utf-8")

        if args.save_jsonl:
            with open(games_dir / f"{stem}.jsonl", "w", encoding="utf-8") as h:
                for lg in g.engine_logs:
                    h.write(json.dumps(lg, ensure_ascii=False) + "\n")

        row = {
            "i": i,
            "seed": args.seed + i,
            "cur_is_a": cur_is_a,
            "cur_pi": cur_pi,
            "cur_win": cur_win,
            "reward_for_a": g.reward_for_a,
            "steps": g.steps,
            "truncated": g.truncated,
            "winner": g.winner,
            "n_engine_logs": len(g.engine_logs),
            "cur": {k: v for k, v in cur_m.items() if k != "prize_curve"},
            "opp": {k: v for k, v in opp_m.items() if k != "prize_curve"},
            "prize_curve_cur": cur_m.get("prize_curve"),
            "mega_evo_delta": sides["mega_evo_delta"],
            "mega_atk_delta": sides["mega_atk_delta"],
            "cur_mega_first": sides["cur_mega_first"],
            "opp_mega_first": sides["opp_mega_first"],
            "cur_boss_first": sides["cur_boss_first"],
            "cur_itchy": sides["cur_itchy"],
            "opp_itchy": sides["opp_itchy"],
            "log_path": log_rel if write_log else None,
        }
        rows.append(row)

        mark = "C" if cur_win is True else ("B" if cur_win is False else "D")
        print(
            f"  [{i + 1:03d}/{args.n}] seat={'cur_A' if cur_is_a else 'cur_B'} "
            f"-> {mark} steps={g.steps} path={cur_m.get('path_bucket')} "
            f"mega_t={cur_m.get('mega_evo_my_t')} "
            f"(cur {wins_cur}-{wins_base} base)",
            flush=True,
        )

    decided = wins_cur + wins_base
    wr = (wins_cur / decided) if decided else 0.0
    elapsed = time.time() - t0
    manifest = {
        "baseline": str(args.baseline),
        "current": str(args.current),
        "n": args.n,
        "seed0": args.seed,
        "tag": tag,
        "wins_current": wins_cur,
        "wins_baseline": wins_base,
        "draws": draws,
        "truncated": trunc,
        "wr_current_decided": wr,
        "elapsed_s": round(elapsed, 1),
        "logs_mode": args.logs,
        "games": rows,
    }
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    summary_text = summarize(manifest)
    sum_path = out_dir / "SUMMARY.md"
    sum_path.write_text(summary_text, encoding="utf-8")

    print()
    print("=== H2H AUDIT ===")
    print(f"current vs baseline: {wins_cur}-{wins_base} (draws={draws})")
    print(f"WR: {wr:.1%}  elapsed={elapsed:.1f}s")
    print(f"wrote {man_path}")
    print(f"wrote {sum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
