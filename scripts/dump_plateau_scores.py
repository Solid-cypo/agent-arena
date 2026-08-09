#!/usr/bin/env python3
"""Dump option_score rankings on mega_clock −PATH plateau MAIN selects.

Plateau = Mega in hand + Staryu on field + facts.staryu_can_evolve + zero
EVOLVE-typed options. Answers: who wins the flat demote? Boss or other?

Usage:
  PYTHONPATH=submission_starmie:submission_starmie/pilot \\
    python3 scripts/dump_plateau_scores.py -n 100 --seed 140000 \\
    --out logs/dump_plateau_scores
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
from cg.api import AreaType, OptionType, SelectType, to_observation_class  # noqa: E402
from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402
from opening_cards import (  # noqa: E402
    BOSS_ORDERS,
    BUDEW,
    LILLIE,
    MEGA_STARMIE,
    MUNKIDORI,
    SNORUNT,
    STARYU,
    SWITCH,
    WATER_BASIC,
)

DARK = 7
POFFIN = 1086
HILDA = 1225
ULTRA_BALL = 1121


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


def _mega_window(me: Any) -> bool:
    if MEGA_STARMIE not in _hand_ids(me):
        return False
    active = (getattr(me, "active", None) or [None])[0]
    if _card_id(active) == STARYU:
        return True
    return any(_card_id(p) == STARYU for p in (getattr(me, "bench", None) or []) if p)


def _label_option(obs: Any, o: Any, mi: int) -> str:
    t = _si(getattr(o, "type", None), -1)
    if t == int(OptionType.END):
        return "END"
    if t == int(OptionType.RETREAT):
        return "RETREAT"
    if t == int(OptionType.ATTACK):
        return f"ATTACK:{_si(getattr(o, 'attackId', None))}"
    if t == int(OptionType.ATTACH):
        # energy from hand area/index
        try:
            area = _si(getattr(o, "area", None))
            idx = _si(getattr(o, "index", None), -1)
            me = obs.current.players[mi]
            if area == int(AreaType.HAND):
                eid = _card_id((me.hand or [])[idx] if me.hand and 0 <= idx < len(me.hand) else None)
                return f"ATTACH:{eid}"
        except Exception:
            pass
        return "ATTACH"
    if t == int(OptionType.ABILITY):
        return "ABILITY"
    if t == int(OptionType.EVOLVE):
        return "EVOLVE"
    if t == int(OptionType.PLAY):
        try:
            idx = _si(getattr(o, "index", None), -1)
            hand = obs.current.players[mi].hand or []
            cid = _card_id(hand[idx]) if 0 <= idx < len(hand) else 0
        except Exception:
            cid = 0
        names = {
            BOSS_ORDERS: "Boss",
            LILLIE: "Lillie",
            HILDA: "Hilda",
            ULTRA_BALL: "UltraBall",
            POFFIN: "Poffin",
            SWITCH: "Switch",
            MEGA_STARMIE: "MegaStarmie_PLAY",
            STARYU: "Staryu",
            SNORUNT: "Snorunt",
            MUNKIDORI: "Munk",
            BUDEW: "Budew",
            WATER_BASIC: "Water",
            DARK: "Dark",
        }
        return names.get(cid, f"PLAY:{cid}")
    if t == int(OptionType.CARD):
        return f"CARD:ctx={_si(getattr(obs.select, 'context', None))}"
    try:
        return OptionType(t).name
    except Exception:
        return f"TYPE:{t}"


def make_plateau_agent(inner_fn, *, store: list[dict], sp_mod, max_events: int):
    def agent(obs_dict: dict) -> list[int]:
        if len(store) >= max_events:
            return inner_fn(obs_dict)
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            return inner_fn(obs_dict)
        if obs.select is None or not obs.select.option:
            return inner_fn(obs_dict)
        if _si(getattr(obs.select, "type", None)) != int(SelectType.MAIN):
            return inner_fn(obs_dict)
        mi = int(obs.current.yourIndex)
        me = obs.current.players[mi]
        if not _mega_window(me):
            return inner_fn(obs_dict)

        options = list(obs.select.option)
        if any(_si(getattr(o, "type", None)) == int(OptionType.EVOLVE) for o in options):
            return inner_fn(obs_dict)

        try:
            sit = sp_mod._compute_situation(obs)
            sit["select_options"] = options
        except Exception:
            return inner_fn(obs_dict)

        facts_can = bool(sit["turn_plan"].facts.staryu_can_evolve)
        if not facts_can:
            return inner_fn(obs_dict)

        mega_legal = sp_mod._mega_evolve_legal_now(
            obs, sit, sit.get("board"), sit.get("turn_plan"),
        )
        if not mega_legal:
            # Not a mega_clock D1 plateau under Wave L
            return inner_fn(obs_dict)

        w: dict = {}
        ranked = []
        for i, o in enumerate(options):
            hard = float(sp_mod._hard_rule_bonus(obs, o, sit))
            score = float(sp_mod.option_score(obs, o, w, sit))
            lab = _label_option(obs, o, mi)
            mc = float(sp_mod._mega_clock_hard_bonus(obs, o, sit))
            ranked.append(
                {
                    "i": i,
                    "label": lab,
                    "type": _si(getattr(o, "type", None)),
                    "hard": hard,
                    "score": score,
                    "mega_clock": mc,
                }
            )
        # Match agent sort: score desc, stable by original index
        order = sorted(
            range(len(ranked)),
            key=lambda j: ranked[j]["score"],
            reverse=True,
        )
        for rank, j in enumerate(order):
            ranked[j]["rank"] = rank
        winner = ranked[order[0]]
        active = (me.active or [None])[0]
        store.append(
            {
                "n": len(store),
                "yourIndex": mi,
                "turn": _si(getattr(obs.current, "turn", None)),
                "my_turn_number": int(getattr(sit.get("board"), "my_turn_number", 0) or 0),
                "hand_ids": _hand_ids(me),
                "active_id": _card_id(active),
                "active_appearThisTurn": getattr(active, "appearThisTurn", None) if active else None,
                "bench_ids": [_card_id(p) for p in (me.bench or []) if p],
                "facts_staryu_can_evolve": facts_can,
                "mega_legal": mega_legal,
                "n_options": len(options),
                "winner_i": winner["i"],
                "winner_label": winner["label"],
                "winner_score": winner["score"],
                "winner_hard": winner["hard"],
                "winner_mega_clock": winner["mega_clock"],
                "all_scores_equal": len({r["score"] for r in ranked}) == 1,
                "ranked": sorted(ranked, key=lambda r: r["rank"]),
            }
        )
        return inner_fn(obs_dict)

    return agent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current", type=Path, default=ROOT / "submission_starmie")
    ap.add_argument(
        "--baseline", type=Path, default=Path("/tmp/baseline_55202093_f07e541"),
    )
    ap.add_argument("-n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=140000)
    ap.add_argument("--max-events", type=int, default=60)
    ap.add_argument("--out", type=Path, default=ROOT / "logs/dump_plateau_scores")
    ap.add_argument("--rules-only", action="store_true", default=True)
    args = ap.parse_args()

    if args.rules_only:
        os.environ["RL_ENABLED"] = "0"

    args.out.mkdir(parents=True, exist_ok=True)
    store: list[dict] = []

    if args.baseline.is_dir():
        base_agent, base_reset, _bm, deck_b, _ = load_starmie_agent(args.baseline)
    else:
        base_agent = base_reset = deck_b = None

    cur_agent, cur_reset, _cm, deck, _ = load_starmie_agent(args.current)
    import starmie_pilot as sp  # noqa: WPS433

    if deck_b is not None:
        assert deck == deck_b
    else:
        base_agent, base_reset = cur_agent, cur_reset

    dump_agent = make_plateau_agent(
        cur_agent, store=store, sp_mod=sp, max_events=args.max_events,
    )

    t0 = time.time()
    games = 0
    for i in range(args.n):
        if len(store) >= args.max_events:
            break
        if cur_reset:
            cur_reset()
        if base_reset and base_reset is not cur_reset:
            base_reset()
        seed = args.seed + i
        random.seed(seed)
        os.environ["GAME_SEED"] = str(seed)
        if i % 2 == 0:
            play_game(dump_agent, base_agent, deck, deck, max_steps=250)
        else:
            play_game(base_agent, dump_agent, deck, deck, max_steps=250)
        games += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{args.n}] plateau_events={len(store)}", flush=True)

    win_ctr = Counter(e["winner_label"] for e in store)
    equal_ctr = sum(1 for e in store if e["all_scores_equal"])
    boss_wins = sum(1 for e in store if e["winner_label"] == "Boss")
    boss_hand = sum(1 for e in store if BOSS_ORDERS in e["hand_ids"])
    boss_opt = sum(
        1 for e in store if any(r["label"] == "Boss" for r in e["ranked"])
    )
    # Top-2 when not equal
    runner = Counter()
    for e in store:
        if len(e["ranked"]) >= 2:
            runner[e["ranked"][1]["label"]] += 1

    # Family buckets
    def family(lab: str) -> str:
        if lab == "Boss":
            return "Boss"
        if lab in ("Lillie", "Hilda"):
            return "DigSupporter"
        if lab.startswith("ATTACH:"):
            return "ATTACH"
        if lab in ("Snorunt", "Munk", "Budew", "Staryu"):
            return "SideOrBasePLAY"
        if lab in ("END", "RETREAT"):
            return lab
        if lab.startswith("ATTACK"):
            return "ATTACK"
        if lab in ("Poffin", "UltraBall", "Switch"):
            return "Item"
        if lab == "MegaStarmie_PLAY":
            return "MegaPLAY"
        return "Other"

    fam = Counter(family(e["winner_label"]) for e in store)
    appear_win = Counter(
        (bool(e.get("active_appearThisTurn")), e["winner_label"])
        for e in store
        if e.get("active_id") == STARYU
    )

    summary = {
        "games_played": games,
        "plateau_events": len(store),
        "elapsed_s": round(time.time() - t0, 1),
        "seed0": args.seed,
        "winner_labels": dict(win_ctr.most_common()),
        "winner_families": dict(fam.most_common()),
        "boss_win_rate": round(boss_wins / len(store), 3) if store else None,
        "boss_in_hand_rate": round(boss_hand / len(store), 3) if store else None,
        "boss_in_options_rate": round(boss_opt / len(store), 3) if store else None,
        "all_scores_equal_rate": round(equal_ctr / len(store), 3) if store else None,
        "runner_up_labels": dict(runner.most_common(15)),
        "active_staryu_appear_x_winner": {
            f"appear={a}|{w}": n for (a, w), n in appear_win.most_common(20)
        },
        "note": (
            "Plateau = MAIN + mega window + facts.staryu_can_evolve + no EVOLVE "
            "option + mega_legal True (Wave L mega_clock D1 engaged)."
        ),
    }

    (args.out / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in store)
        + ("\n" if store else ""),
        encoding="utf-8",
    )
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# 平台拍 option_score 排名 dump",
        "",
        f"- games={games} plateau_events={len(store)} elapsed={summary['elapsed_s']}s",
        f"- seed0={args.seed} RL_ENABLED={os.environ.get('RL_ENABLED')}",
        f"- Boss 胜出率: **{summary['boss_win_rate']}** "
        f"(手牌有 Boss: {summary['boss_in_hand_rate']}；"
        f"选项含 Boss PLAY: {summary['boss_in_options_rate']})",
        f"- 全员同分率: **{summary['all_scores_equal_rate']}**",
        "",
        "## 赢家分布（label）",
        "",
        "| winner | n |",
        "|---|---:|",
    ]
    for lab, n in win_ctr.most_common():
        lines.append(f"| {lab} | {n} |")
    lines += [
        "",
        "## 赢家族",
        "",
        "| family | n |",
        "|---|---:|",
    ]
    for lab, n in fam.most_common():
        lines.append(f"| {lab} | {n} |")

    lines += ["", "## 样例（最多 10；含完整 top-5 排名）", ""]
    for e in store[:10]:
        lines.append(
            f"### event {e['n']} my_t={e['my_turn_number']} "
            f"active={e['active_id']} appear={e.get('active_appearThisTurn')} "
            f"winner=**{e['winner_label']}** score={e['winner_score']} "
            f"equal={e['all_scores_equal']}"
        )
        lines.append(f"- hand={e['hand_ids']}")
        for r in e["ranked"][:5]:
            lines.append(
                f"  - #{r['rank']} `{r['label']}` score={r['score']} "
                f"hard={r['hard']} mega_clock={r['mega_clock']}"
            )
        lines.append("")

    # Decision for Wave S
    lines += [
        "## 对 Wave S 的含义",
        "",
    ]
    if not store:
        lines.append("> 未采到 plateau 事件——加大 `-n` / `--max-events`。")
    else:
        br = summary["boss_win_rate"] or 0
        if br >= 0.35:
            lines.append(
                f"> Boss 胜出率 {br:.0%} ≥35% → **支持**「假窗口 Boss 单卡再降权」假设；"
                "仍须保留其它 D1 demote。"
            )
        elif boss_opt == 0:
            lines.append(
                f"> **平台拍选项里从未出现 Boss PLAY**（手牌有 Boss={boss_hand}/{len(store)}）"
                "→ Wave S「假窗口 Boss 单卡再降权」**无标的 / NO-GO**；"
                f"主赢家族={fam.most_common(3)}。"
            )
        elif br < 0.10:
            lines.append(
                f"> Boss 胜出率仅 {br:.0%}（选项含 Boss={boss_opt}/{len(store)}）≪35% "
                "→ Wave S **NO-GO**；假窗口赢家不是 Boss；"
                f"主赢家族={fam.most_common(3)}。"
            )
        else:
            lines.append(
                f"> Boss 胜出率 {br:.0%} → Boss 单卡刀 **ROI 存疑**；"
                f"先看主赢家族 {fam.most_common(3)}。"
            )

    (args.out / "DUMP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"wrote {args.out / 'DUMP.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
