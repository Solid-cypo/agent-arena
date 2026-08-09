#!/usr/bin/env python3
"""Same-seed Opening/megaT3对照: agent dirs vs walrein (+ optional H2H).

Collects the same KPIs historically printed by ops_firefix hybrid cabt eval:
  opening_complete_this_game, mega_on_field_by_my_turn_{3,4}, win.

Example:
  PYTHONHASHSEED=0 python3 scripts/compare_opening_agents.py \\
    --agents firefix=data/restore_peaks/ops_firefix_55115028,head=submission_starmie \\
    --games 200 --seed0 71000 --h2h 80
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONHASHSEED", "0")
os.environ.setdefault("RL_ENABLED", "1")
os.environ.setdefault("USE_HYBRID", "1")

from arena.deck import load_deck_csv  # noqa: E402
from arena.policy import make_agent  # noqa: E402
from arena.simulator import play_game  # noqa: E402

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
    "opening_exec",
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
    agent_dir = agent_dir.resolve()
    pilot_dir = agent_dir / "pilot"
    if not pilot_dir.is_dir():
        raise FileNotFoundError(f"no pilot/ under {agent_dir}")

    _purge_pilot_modules()
    for p in (str(pilot_dir), str(agent_dir)):
        while p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    # Force cg from agent_dir if present, else ROOT
    sp = importlib.import_module("starmie_pilot")
    deck = _read_deck(agent_dir)
    weights = _read_weights(agent_dir)
    agent_fn = sp.make_starmie_agent(deck, weights)
    agent_state = getattr(sp, "_LIVE_AGENT_STATE", None)
    reset_state = getattr(sp, "reset_agent_state", None)
    reset_for_new = getattr(sp, "reset_for_new_game", None)

    def reset_fn() -> None:
        if callable(reset_state) and agent_state is not None:
            reset_state(agent_state)
        elif callable(reset_for_new):
            reset_for_new()

    return agent_fn, reset_fn, sp, deck, agent_state


def _seed_game(seed: int) -> None:
    random.seed(seed)
    os.environ["GAME_SEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed % (2**32 - 1))
    except Exception:
        pass


def eval_vs_opp(
    label: str,
    agent_dir: Path,
    opp_deck: list[int],
    games: int,
    seed0: int,
) -> dict:
    agent_fn, reset_fn, sp, deck, state = load_starmie_agent(agent_dir)
    opp_agent = make_agent(opp_deck, None)
    rows = []
    open_n = mega3_n = mega4_n = usable3_n = wins = losses = draws = 0
    t0 = time.time()
    for i in range(games):
        seed = seed0 + i
        _seed_game(seed)
        reset_fn()
        # Seat swap: even → we are A (going-first bias depends on engine)
        we_are_a = (i % 2 == 0)
        if we_are_a:
            g = play_game(agent_fn, opp_agent, deck, opp_deck, max_steps=700)
            reward = g.reward_for_a
        else:
            g = play_game(opp_agent, agent_fn, opp_deck, deck, max_steps=700)
            reward = -g.reward_for_a
        st = getattr(sp, "_LIVE_AGENT_STATE", None) or state or {}
        opened = bool(st.get("opening_complete_this_game"))
        m3 = bool(st.get("mega_on_field_by_my_turn_3"))
        m4 = bool(st.get("mega_on_field_by_my_turn_4"))
        u3 = bool(st.get("usable_mega_by_my_turn_3"))
        if opened:
            open_n += 1
        if m3:
            mega3_n += 1
        if m4:
            mega4_n += 1
        if u3:
            usable3_n += 1
        if reward > 0:
            wins += 1
            won = True
        elif reward < 0:
            losses += 1
            won = False
        else:
            draws += 1
            won = None
        rows.append(
            {
                "i": i,
                "seed": seed,
                "we_are_a": we_are_a,
                "won": won,
                "opening": opened,
                "mega_t3": m3,
                "mega_t4": m4,
                "usable_mega_t3": u3,
                "steps": g.steps,
                "truncated": g.truncated,
            }
        )
        if (i + 1) % 25 == 0 or i + 1 == games:
            n = i + 1
            print(
                f"  [{label}] {n}/{games} open={open_n/n:.1%} "
                f"megaT3={mega3_n/n:.1%} megaT4={mega4_n/n:.1%} "
                f"win={wins/n:.1%}",
                flush=True,
            )
    n = games
    return {
        "label": label,
        "agent_dir": str(agent_dir),
        "games": n,
        "seed0": seed0,
        "elapsed_s": round(time.time() - t0, 1),
        "opening": open_n / n,
        "mega_t3": mega3_n / n,
        "mega_t4": mega4_n / n,
        "usable_mega_t3": usable3_n / n,
        "win": wins / n,
        "W": wins,
        "L": losses,
        "D": draws,
        "rows": rows,
    }


def h2h(a_dir: Path, b_dir: Path, games: int, seed0: int) -> dict:
    a_fn, a_reset, _a_mod, deck_a, _ = load_starmie_agent(a_dir)
    b_fn, b_reset, _b_mod, deck_b, _ = load_starmie_agent(b_dir)
    assert deck_a == deck_b, "deck.csv mismatch"
    wa = wb = dr = 0
    rows = []
    t0 = time.time()
    for i in range(games):
        seed = seed0 + i
        _seed_game(seed)
        a_reset()
        b_reset()
        a_is_seat_a = (i % 2 == 0)
        if a_is_seat_a:
            g = play_game(a_fn, b_fn, deck_a, deck_a, max_steps=700)
            a_won = g.reward_for_a == 1
            b_won = g.reward_for_a == -1
        else:
            g = play_game(b_fn, a_fn, deck_a, deck_a, max_steps=700)
            a_won = g.reward_for_a == -1
            b_won = g.reward_for_a == 1
        if a_won:
            wa += 1
        elif b_won:
            wb += 1
        else:
            dr += 1
        rows.append(
            {
                "i": i,
                "seed": seed,
                "a_is_seat_a": a_is_seat_a,
                "a_won": a_won if (a_won or b_won) else None,
                "steps": g.steps,
            }
        )
        if (i + 1) % 20 == 0 or i + 1 == games:
            decided = wa + wb
            wr = wa / decided if decided else 0.0
            print(
                f"  [h2h] {i+1}/{games} firefix {wa}-{wb} head "
                f"(decided WR_firefix={wr:.1%} d={dr})",
                flush=True,
            )
    decided = wa + wb
    return {
        "games": games,
        "seed0": seed0,
        "elapsed_s": round(time.time() - t0, 1),
        "firefix_wins": wa,
        "head_wins": wb,
        "draws": dr,
        "firefix_wr_decided": (wa / decided) if decided else None,
        "rows": rows,
    }


def _parse_agents(spec: str) -> list[tuple[str, Path]]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"bad --agents item (want label=path): {part}")
        label, path = part.split("=", 1)
        out.append((label.strip(), Path(path.strip())))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--agents",
        default=(
            "firefix=data/restore_peaks/ops_firefix_55115028,"
            "head=submission_starmie"
        ),
    )
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=71_000)
    ap.add_argument("--opp", default="walrein_control")
    ap.add_argument("--h2h", type=int, default=0, help="H2H games firefix vs head")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "restore_peaks" / "compare_firefix_vs_head.json",
    )
    args = ap.parse_args()

    agents = _parse_agents(args.agents)
    opp_path = ROOT / "data" / "decks" / f"{args.opp}.csv"
    if not opp_path.exists():
        raise SystemExit(f"missing opp deck {opp_path}")
    opp_deck = load_deck_csv(opp_path)

    print(
        f"compare Opening vs {args.opp}: games={args.games} seed0={args.seed0} "
        f"RL={os.environ.get('RL_ENABLED')} HYBRID={os.environ.get('USE_HYBRID')}",
        flush=True,
    )
    results = []
    for label, path in agents:
        p = path if path.is_absolute() else ROOT / path
        print(f"\n== {label}: {p} ==", flush=True)
        results.append(eval_vs_opp(label, p, opp_deck, args.games, args.seed0))

    h2h_result = None
    if args.h2h > 0 and len(agents) >= 2:
        a_path = agents[0][1] if agents[0][1].is_absolute() else ROOT / agents[0][1]
        b_path = agents[1][1] if agents[1][1].is_absolute() else ROOT / agents[1][1]
        print(f"\n== H2H {agents[0][0]} vs {agents[1][0]} n={args.h2h} ==", flush=True)
        h2h_result = h2h(a_path, b_path, args.h2h, args.seed0 + 10_000)

    summary = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(),
        "opp": args.opp,
        "games": args.games,
        "seed0": args.seed0,
        "agents": [
            {k: v for k, v in r.items() if k != "rows"} for r in results
        ],
        "h2h": (
            {k: v for k, v in h2h_result.items() if k != "rows"}
            if h2h_result
            else None
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **summary,
        "detail": {r["label"]: r["rows"] for r in results},
        "h2h_detail": (h2h_result or {}).get("rows"),
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n======== SUMMARY ========", flush=True)
    print(f"{'label':12} {'open':>8} {'megaT3':>8} {'megaT4':>8} {'win':>8} {'W-L-D'}", flush=True)
    for r in results:
        print(
            f"{r['label']:12} {r['opening']:8.1%} {r['mega_t3']:8.1%} "
            f"{r['mega_t4']:8.1%} {r['win']:8.1%} "
            f"{r['W']}-{r['L']}-{r['D']}  ({r['elapsed_s']}s)",
            flush=True,
        )
    if h2h_result:
        print(
            f"H2H firefix vs head: {h2h_result['firefix_wins']}-"
            f"{h2h_result['head_wins']} (d={h2h_result['draws']}) "
            f"WR_firefix={h2h_result['firefix_wr_decided']}",
            flush=True,
        )
    print(f"wrote {args.out}", flush=True)

    md = args.out.with_suffix(".md")
    lines = [
        "# ops_firefix vs HEAD Opening 对照",
        "",
        f"- 对手：`{args.opp}`  ·  每侧 N={args.games}  ·  seed0={args.seed0}",
        f"- 时间：{summary['ts']}",
        "",
        "| 包 | open | megaT3 | megaT4 | win | W-L-D |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['label']} | {r['opening']:.1%} | {r['mega_t3']:.1%} | "
            f"{r['mega_t4']:.1%} | {r['win']:.1%} | {r['W']}-{r['L']}-{r['D']} |"
        )
    if h2h_result and h2h_result["firefix_wr_decided"] is not None:
        lines += [
            "",
            f"H2H（N={args.h2h}）：firefix **{h2h_result['firefix_wins']}** – "
            f"head **{h2h_result['head_wins']}** "
            f"（draw {h2h_result['draws']}），firefix 胜率 "
            f"**{h2h_result['firefix_wr_decided']:.1%}**",
        ]
    hist = (
        "\n历史 ops_firefix ship 闸（不同 seed 批次）：Hybrid 3×200 "
        "open **81.2%** / megaT3 **77%** / win **96%**。"
    )
    lines.append(hist)
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
