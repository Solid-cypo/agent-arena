#!/usr/bin/env python3
"""SOP-D dump: Ultra Ball discards Mega Starmie (game_155 family).

Captures SelectContext.DISCARD where select.effect.id == Ultra Ball (1121)
and the agent picks MEGA_STARMIE. Aggregates game-level rate / win-loss lift /
UB-2 conflict / forced-brick rate.

Usage:
  RL_ENABLED=0 PYTHONPATH=submission_starmie:submission_starmie/pilot \\
    python3 scripts/dump_ub_discard_mega.py -n 200 --seed 140000 \\
    --out logs/diagnose_ub_burn_mega
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONHASHSEED", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from arena.simulator import play_game  # noqa: E402
from cg.api import AreaType, OptionType, SelectContext, to_observation_class  # noqa: E402
from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402
from opening_cards import MEGA_STARMIE, STARYU  # noqa: E402

ULTRA_BALL = 1121
PROTECT_THRESHOLD = 8_000


def _si(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        if hasattr(x, "value") and not isinstance(x, (bool, int)):
            return int(x.value)
        return int(x)
    except Exception:
        return default


def _card_id(c: Any) -> int:
    if c is None:
        return 0
    return _si(getattr(c, "id", None) or (c.get("id") if isinstance(c, dict) else None))


def _hand_ids(me: Any) -> list[int]:
    return [_card_id(c) for c in (getattr(me, "hand", None) or []) if c]


def _field_has(me: Any, cid: int) -> bool:
    active = (getattr(me, "active", None) or [None])[0]
    if _card_id(active) == cid:
        return True
    return any(_card_id(p) == cid for p in (getattr(me, "bench", None) or []) if p)


def _option_hand_cid(obs: Any, o: Any, mi: int, sp_mod: Any) -> int:
    try:
        return int(sp_mod._card_option_id(obs, o, mi))
    except Exception:
        area = _si(getattr(o, "area", None), -1)
        idx = _si(getattr(o, "index", None), -1)
        me = obs.current.players[mi]
        if area == int(AreaType.HAND) and me.hand and 0 <= idx < len(me.hand):
            return _card_id(me.hand[idx])
        return 0


def make_ub_dump_agent(
    inner_fn,
    *,
    events: list[dict],
    game_state: dict,
    sp_mod: Any,
):
    def agent(obs_dict: dict) -> list[int]:
        decision = inner_fn(obs_dict)
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            return decision
        if obs.select is None or not obs.select.option:
            return decision

        mi = int(obs.current.yourIndex)
        me = obs.current.players[mi]
        # Track Mega ever on field for no_mega tag.
        if _field_has(me, MEGA_STARMIE):
            game_state["ever_mega"] = True

        ctx = _si(getattr(obs.select, "context", None), -1)
        if ctx != int(SelectContext.DISCARD):
            return decision

        effect = getattr(obs.select, "effect", None)
        effect_id = _card_id(effect)
        if effect_id != ULTRA_BALL:
            return decision

        options = list(obs.select.option)
        # Build discard ranking via discard_value
        try:
            sit = sp_mod._compute_situation(obs)
            plan = sit.get("turn_plan")
        except Exception:
            sit = None
            plan = None

        ranked = []
        for i, o in enumerate(options):
            cid = _option_hand_cid(obs, o, mi, sp_mod)
            dv = None
            if plan is not None:
                try:
                    dv = int(sp_mod.discard_value(cid, plan))
                except Exception:
                    dv = None
            ranked.append({"i": i, "cid": cid, "discard_value": dv})

        selected_idxs = [
            d for d in decision if isinstance(d, int) and 0 <= d < len(options)
        ]
        selected_cids = [ranked[d]["cid"] for d in selected_idxs]
        burned = MEGA_STARMIE in selected_cids
        if not burned:
            if any(r["cid"] == MEGA_STARMIE for r in ranked):
                game_state["ub_mega_offered_not_burned"] = (
                    game_state.get("ub_mega_offered_not_burned", 0) + 1
                )
            return decision

        game_state["ub_burn_mega"] = True
        game_state["ub_burn_count"] = game_state.get("ub_burn_count", 0) + 1

        min_c = _si(getattr(obs.select, "minCount", None), 1) or 1
        max_c = _si(getattr(obs.select, "maxCount", None), min_c) or min_c
        need = max(min_c, max_c)  # UB in this engine is min=max=2
        non_mega_opts = [r for r in ranked if r["cid"] != MEGA_STARMIE]
        safe_non_mega = [
            r for r in non_mega_opts
            if r["discard_value"] is None or r["discard_value"] < PROTECT_THRESHOLD
        ]
        # Forced: cannot fill `need` discard slots without taking Mega.
        forced_no_alt = len(non_mega_opts) < need
        # Wrong-kill: enough safe non-Mega cards to fill slots, yet Mega chosen.
        wrong_kill = (not forced_no_alt) and len(safe_non_mega) >= need

        staryu_on = _field_has(me, STARYU)
        mega_on = _field_has(me, MEGA_STARMIE)
        # UB-2 leak: Ball played while Mega held and Staryu/Mega already online.
        ub2_conflict = staryu_on or mega_on

        hand = _hand_ids(me)
        my_t = 0
        if sit is not None and sit.get("board") is not None:
            my_t = int(getattr(sit["board"], "my_turn_number", 0) or 0)

        events.append(
            {
                "n": len(events),
                "game_i": game_state.get("game_i"),
                "seat": "A" if game_state.get("cur_is_a") else "B",
                "yourIndex": mi,
                "my_turn_number": my_t,
                "hand_ids": hand,
                "active_id": _card_id((me.active or [None])[0]),
                "bench_ids": [_card_id(p) for p in (me.bench or []) if p],
                "staryu_on_field": staryu_on,
                "mega_on_field": mega_on,
                "ub2_conflict": ub2_conflict,
                "forced_no_alt": forced_no_alt,
                "wrong_kill": wrong_kill,
                "min_count": min_c,
                "max_count": max_c,
                "n_options": len(options),
                "selected_cids": selected_cids,
                "ranked": ranked,
                "ball_allowed": (
                    bool(plan.acquire.ball_allowed) if plan is not None else None
                ),
                "ball_reason": (
                    getattr(plan.acquire, "ball_reason", None) if plan is not None else None
                ),
                "need_base": (
                    bool(plan.gap.need_base) if plan is not None else None
                ),
                "need_evolution": (
                    bool(plan.gap.need_evolution) if plan is not None else None
                ),
            }
        )
        return decision

    return agent


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 3)


def _lift(loss_rate: float | None, win_rate: float | None) -> float | None:
    if loss_rate is None or win_rate is None:
        return None
    return round(loss_rate - win_rate, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current", type=Path, default=ROOT / "submission_starmie")
    ap.add_argument(
        "--baseline", type=Path, default=Path("/tmp/baseline_55202093_f07e541"),
    )
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=140000)
    ap.add_argument("--out", type=Path, default=ROOT / "logs/diagnose_ub_burn_mega")
    ap.add_argument("--rules-only", action="store_true", default=True)
    args = ap.parse_args()

    if args.rules_only:
        os.environ["RL_ENABLED"] = "0"

    args.out.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    games: list[dict] = []

    base_agent, base_reset, _bm, deck_b = load_starmie_agent(args.baseline)
    cur_agent, cur_reset, sp, deck = load_starmie_agent(args.current)
    assert deck == deck_b

    t0 = time.time()
    for i in range(args.n):
        game_state: dict[str, Any] = {
            "game_i": i,
            "cur_is_a": (i % 2 == 0),
            "ever_mega": False,
            "ub_burn_mega": False,
            "ub_burn_count": 0,
        }
        dump_agent = make_ub_dump_agent(
            cur_agent, events=events, game_state=game_state, sp_mod=sp,
        )
        cur_reset()
        base_reset()
        seed = args.seed + i
        random.seed(seed)
        os.environ["GAME_SEED"] = str(seed)
        try:
            import numpy as np

            np.random.seed(seed % (2**32 - 1))
        except Exception:
            pass

        if game_state["cur_is_a"]:
            g = play_game(dump_agent, base_agent, deck, deck, max_steps=700)
            cur_win = (
                True if g.reward_for_a == 1
                else False if g.reward_for_a == -1
                else None
            )
        else:
            g = play_game(base_agent, dump_agent, deck, deck, max_steps=700)
            cur_win = (
                True if g.reward_for_a == -1
                else False if g.reward_for_a == 1
                else None
            )

        row = {
            "i": i,
            "seat": "A" if game_state["cur_is_a"] else "B",
            "cur_win": cur_win,
            "ever_mega": bool(game_state["ever_mega"]),
            "no_mega": not bool(game_state["ever_mega"]),
            "ub_burn_mega": bool(game_state["ub_burn_mega"]),
            "ub_burn_count": int(game_state.get("ub_burn_count", 0)),
            "steps": g.steps,
            "truncated": g.truncated,
        }
        games.append(row)
        if (i + 1) % 20 == 0:
            burns = sum(1 for x in games if x["ub_burn_mega"])
            print(
                f"  [{i+1}/{args.n}] burns={burns} events={len(events)}",
                flush=True,
            )

    # Backfill win onto events
    win_by_i = {g["i"]: g["cur_win"] for g in games}
    for e in events:
        e["cur_win"] = win_by_i.get(e["game_i"])

    def subset(pred):
        return [g for g in games if pred(g)]

    decided = [g for g in games if g["cur_win"] is not None]
    wins = [g for g in decided if g["cur_win"] is True]
    losses = [g for g in decided if g["cur_win"] is False]
    seat_b = [g for g in games if g["seat"] == "B"]
    seat_b_loss = [g for g in seat_b if g["cur_win"] is False]
    seat_b_win = [g for g in seat_b if g["cur_win"] is True]
    no_mega_loss = [g for g in losses if g["no_mega"]]

    burn_all = sum(1 for g in games if g["ub_burn_mega"])
    burn_win = sum(1 for g in wins if g["ub_burn_mega"])
    burn_loss = sum(1 for g in losses if g["ub_burn_mega"])
    burn_b_loss = sum(1 for g in seat_b_loss if g["ub_burn_mega"])
    burn_b_win = sum(1 for g in seat_b_win if g["ub_burn_mega"])
    burn_no_mega_loss = sum(1 for g in no_mega_loss if g["ub_burn_mega"])

    rate_all = _rate(burn_all, len(games))
    rate_win = _rate(burn_win, len(wins))
    rate_loss = _rate(burn_loss, len(losses))
    rate_b_loss = _rate(burn_b_loss, len(seat_b_loss))
    rate_b_win = _rate(burn_b_win, len(seat_b_win))
    rate_nm_loss = _rate(burn_no_mega_loss, len(no_mega_loss))
    lift = _lift(rate_loss, rate_win)
    lift_b = _lift(rate_b_loss, rate_b_win)

    ub2_n = sum(1 for e in events if e["ub2_conflict"])
    forced_n = sum(1 for e in events if e["forced_no_alt"])
    wrong_n = sum(1 for e in events if e["wrong_kill"])
    seat_ctr = Counter(e["seat"] for e in events)

    summary = {
        "games": len(games),
        "events_ub_burn_mega": len(events),
        "elapsed_s": round(time.time() - t0, 1),
        "seed0": args.seed,
        "rl_enabled": os.environ.get("RL_ENABLED"),
        "burn_games": burn_all,
        "rate_all_games": rate_all,
        "rate_wins": rate_win,
        "rate_losses": rate_loss,
        "lift_loss_minus_win": lift,
        "rate_seatB_wins": rate_b_win,
        "rate_seatB_losses": rate_b_loss,
        "lift_seatB": lift_b,
        "rate_no_mega_losses": rate_nm_loss,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "n_seatB_wins": len(seat_b_win),
        "n_seatB_losses": len(seat_b_loss),
        "n_no_mega_losses": len(no_mega_loss),
        "events_ub2_conflict": ub2_n,
        "events_ub2_conflict_rate": _rate(ub2_n, len(events)),
        "events_forced_no_alt": forced_n,
        "events_forced_no_alt_rate": _rate(forced_n, len(events)),
        "events_wrong_kill": wrong_n,
        "events_wrong_kill_rate": _rate(wrong_n, len(events)),
        "events_by_seat": dict(seat_ctr),
        "note": (
            "Event = UB (effect=1121) DISCARD select that chose MEGA_STARMIE. "
            "Engine UB discards min=max=2. "
            "UB-2 conflict = Staryu or Mega already on field at discard. "
            "forced_no_alt = non-Mega options < need slots. "
            "wrong_kill = ≥need safe non-Mega options (dv<8000) yet Mega chosen."
        ),
    }

    # GO/NO-GO: WR lift is the primary gate (SOP-D / Wave O style).
    verdict = "NO-GO"
    reasons = []
    if not events:
        reasons.append("zero UB-burn-Mega events — needle not reproducible at scale")
    elif (lift or 0) < 0.05 and (lift_b or 0) < 0.08:
        reasons.append(f"lift≈0 (all={lift}, seatB={lift_b}) — tag≠死因")
        if (summary["events_forced_no_alt_rate"] or 0) >= 0.40:
            reasons.append(
                f"forced brick {summary['events_forced_no_alt_rate']:.0%} "
                "(hand too thin for 2-discard UB)"
            )
        if ub2_n:
            reasons.append(
                f"UB-2 leak rare ({ub2_n}/{len(games)} games, "
                f"{ub2_n}/{len(events)} events) — monitor only, no WR knife"
            )
        verdict = "NO-GO"
    elif (lift or 0) >= 0.08 or (lift_b or 0) >= 0.10:
        reasons.append(f"lift elevated (all={lift}, seatB={lift_b})")
        if (summary["events_ub2_conflict_rate"] or 0) >= 0.25:
            reasons.append("primary knife = UB-2 timing ban Ball")
        elif (summary["events_wrong_kill_rate"] or 0) >= 0.35:
            reasons.append("primary knife = protect sole Mega in 2-discard")
        verdict = "GO"
    else:
        reasons.append(f"borderline lift (all={lift}, seatB={lift_b})")
        verdict = "NO-GO"

    summary["verdict"] = verdict
    summary["verdict_reasons"] = reasons

    (args.out / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
        + ("\n" if events else ""),
        encoding="utf-8",
    )
    (args.out / "games.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in games) + "\n",
        encoding="utf-8",
    )
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# SOP-D：UB 烧 Mega（game_155 族）",
        "",
        f"- games={len(games)} events={len(events)} elapsed={summary['elapsed_s']}s",
        f"- seed0={args.seed} RL_ENABLED={os.environ.get('RL_ENABLED')}",
        f"- 全池 burn 局率: **{rate_all}** ({burn_all}/{len(games)})",
        f"- 胜局 burn 率: {rate_win} ({burn_win}/{len(wins)})",
        f"- 负局 burn 率: {rate_loss} ({burn_loss}/{len(losses)})",
        f"- **lift (负−胜): {lift}**",
        f"- seat B 胜/负 burn 率: {rate_b_win} / {rate_b_loss} → lift_B={lift_b}",
        f"- no_mega 负局 burn 率: {rate_nm_loss} ({burn_no_mega_loss}/{len(no_mega_loss)})",
        "",
        "## 事件拆分",
        "",
        f"- UB-2 冲突（场上已有 Staryu/Mega）: **{ub2_n}/{len(events)}** "
        f"({summary['events_ub2_conflict_rate']})",
        f"- 被迫（非 Mega 选项数 < 弃牌槽 need=2）: **{forced_n}/{len(events)}** "
        f"({summary['events_forced_no_alt_rate']})",
        f"- 错杀（≥2 张 safe 非 Mega 仍弃 Mega）: **{wrong_n}/{len(events)}** "
        f"({summary['events_wrong_kill_rate']})",
        f"- 按座位: {dict(seat_ctr)}",
        "",
        "## 样例（最多 8）",
        "",
    ]
    for e in events[:8]:
        lines.append(
            f"### event {e['n']} game={e['game_i']} seat={e['seat']} "
            f"my_t={e['my_turn_number']} win={e.get('cur_win')} "
            f"ub2={e['ub2_conflict']} forced={e['forced_no_alt']} "
            f"wrong={e['wrong_kill']}"
        )
        lines.append(f"- hand={e['hand_ids']} active={e['active_id']}")
        lines.append(
            f"- ball_allowed={e.get('ball_allowed')} reason={e.get('ball_reason')}"
        )
        top = sorted(
            e["ranked"],
            key=lambda r: (r["discard_value"] is None, r["discard_value"] or 0),
        )[:6]
        for r in top:
            mark = "←PICK" if r["cid"] in e["selected_cids"] else ""
            lines.append(
                f"  - cid={r['cid']} dv={r['discard_value']} {mark}"
            )
        lines.append("")

    lines += [
        "## 假设卡闸",
        "",
        f"> **{verdict}** — {'; '.join(reasons)}",
        "",
    ]
    if verdict == "GO":
        lines.append(
            "下一波另开 Wave T：按主因收窄——"
            "UB-2 冲突→时机禁 Ball；wrong_kill→弃牌保护唯一 Mega；"
            "H2H seat B 硬闸。"
        )
    else:
        lines.append(
            "不改 `discard_value` / Ball 时机；政策停在 Wave L；"
            "UB 烧 Mega 记入挂起表（非主死因或不可刀）。"
        )

    (args.out / "DIAGNOSE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"wrote {args.out / 'DIAGNOSE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
