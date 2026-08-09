#!/usr/bin/env python3
"""Live dump of EVOLVE / Mega-window select options from libcg.

Wraps the current starmie agent, plays vs baseline (or self), and records
raw Option fields whenever Mega Starmie is in hand and Staryu is on field.
Also scores each option with ``_evolve_to_mega_starmie`` so Wave Q autopsy
can see helper hit-rate on real fan-outs.

Usage:
  PYTHONPATH=submission_starmie:submission_starmie/pilot \\
    python3 scripts/dump_evolve_options.py -n 60 --seed 140000 \\
    --out logs/dump_evolve_options
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
from cg.api import AreaType, OptionType, SelectContext, SelectType  # noqa: E402
from cg.api import to_observation_class  # noqa: E402
from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402

STARYU = 1030
MEGA_STARMIE = 1031


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


def _enum_name(enum_cls: type, val: Any) -> str:
    try:
        return enum_cls(_si(val)).name
    except Exception:
        return str(val)


def _hand_ids(me: Any) -> list[int]:
    return [_card_id(c) for c in (getattr(me, "hand", None) or []) if c]


def _field_ids(me: Any) -> dict[str, Any]:
    active = (getattr(me, "active", None) or [None])
    a = active[0] if active else None
    bench = getattr(me, "bench", None) or []
    return {
        "active_id": _card_id(a),
        "active_canEvolve": bool(getattr(a, "canEvolve", False)) if a else False,
        "active_turnPlayed": getattr(a, "turnPlayed", None) if a else None,
        "active_appearThisTurn": getattr(a, "appearThisTurn", None) if a else None,
        "bench_ids": [_card_id(p) for p in bench if p],
        "bench_canEvolve": [
            bool(getattr(p, "canEvolve", False)) for p in bench if p
        ],
    }


def _mega_window(me: Any) -> bool:
    ids = _hand_ids(me)
    if MEGA_STARMIE not in ids:
        return False
    field = _field_ids(me)
    if field["active_id"] == STARYU:
        return True
    return STARYU in field["bench_ids"]


def _option_raw(o: Any) -> dict[str, Any]:
    fields = (
        "type", "number", "area", "index", "playerIndex", "toolIndex",
        "energyIndex", "count", "inPlayArea", "inPlayIndex", "attackId",
        "cardId", "serial", "specialConditionType",
    )
    out: dict[str, Any] = {}
    for k in fields:
        v = getattr(o, k, None)
        if v is None:
            continue
        if hasattr(v, "name") and hasattr(v, "value"):
            out[k] = int(v)
            out[f"{k}_name"] = v.name
        else:
            out[k] = v
    # Friendly names
    if "type" in out and "type_name" not in out:
        out["type_name"] = _enum_name(OptionType, out["type"])
    if "area" in out and "area_name" not in out:
        out["area_name"] = _enum_name(AreaType, out["area"])
    if "inPlayArea" in out and "inPlayArea_name" not in out:
        out["inPlayArea_name"] = _enum_name(AreaType, out["inPlayArea"])
    return out


def _resolve_hint(obs: Any, o: Any, mi: int) -> dict[str, Any]:
    """Human-readable card ids pointed at by the option."""
    hint: dict[str, Any] = {}
    me = obs.current.players[mi]
    t = _si(getattr(o, "type", None), -1)
    area = getattr(o, "area", None)
    idx = _si(getattr(o, "index", None), -1)
    try:
        if t == int(OptionType.PLAY) or (
            t == int(OptionType.EVOLVE) and _si(area) == int(AreaType.HAND)
        ):
            hand = me.hand or []
            if 0 <= idx < len(hand) and hand[idx]:
                hint["hand_card_id"] = _card_id(hand[idx])
        if t == int(OptionType.EVOLVE):
            ipa = getattr(o, "inPlayArea", None)
            ipi = _si(getattr(o, "inPlayIndex", None), -1)
            if ipa is not None:
                if _si(ipa) == int(AreaType.ACTIVE):
                    a = (me.active or [None])[0]
                    hint["in_play_id"] = _card_id(a)
                    hint["in_play_where"] = "ACTIVE"
                elif _si(ipa) == int(AreaType.BENCH):
                    bench = me.bench or []
                    if 0 <= ipi < len(bench) and bench[ipi]:
                        hint["in_play_id"] = _card_id(bench[ipi])
                        hint["in_play_where"] = f"BENCH[{ipi}]"
            # Legacy helper paths: area=ACTIVE/BENCH means base Pokémon
            if _si(area) == int(AreaType.ACTIVE):
                a = (me.active or [None])[0]
                hint["area_as_base_id"] = _card_id(a)
            elif _si(area) == int(AreaType.BENCH):
                bench = me.bench or []
                if 0 <= idx < len(bench) and bench[idx]:
                    hint["area_as_base_id"] = _card_id(bench[idx])
        if t == int(OptionType.CARD):
            pi = _si(getattr(o, "playerIndex", None), mi)
            pl = obs.current.players[pi]
            if _si(area) == int(AreaType.HAND):
                hand = pl.hand or []
                if 0 <= idx < len(hand) and hand[idx]:
                    hint["card_id"] = _card_id(hand[idx])
            elif _si(area) == int(AreaType.ACTIVE):
                hint["card_id"] = _card_id((pl.active or [None])[0])
            elif _si(area) == int(AreaType.BENCH):
                bench = pl.bench or []
                if 0 <= idx < len(bench) and bench[idx]:
                    hint["card_id"] = _card_id(bench[idx])
    except Exception as e:
        hint["resolve_err"] = str(e)
    return hint


def make_dumping_agent(inner_fn, *, store: list[dict], sp_mod, max_events: int):
    """Wrap agent_fn; dump mega-window selects before delegating."""

    def agent(obs_dict: dict) -> list[int]:
        if len(store) >= max_events:
            return inner_fn(obs_dict)
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            return inner_fn(obs_dict)
        if obs.select is None or not obs.select.option:
            return inner_fn(obs_dict)
        mi = int(obs.current.yourIndex)
        me = obs.current.players[mi]
        if not _mega_window(me):
            return inner_fn(obs_dict)

        options = list(obs.select.option)
        field = _field_ids(me)
        hand = _hand_ids(me)
        rows = []
        helper_hits = 0
        evolve_typed = 0
        for i, o in enumerate(options):
            raw = _option_raw(o)
            hint = _resolve_hint(obs, o, mi)
            hit = bool(sp_mod._evolve_to_mega_starmie(obs, o, mi))
            if hit:
                helper_hits += 1
            if _si(getattr(o, "type", None)) == int(OptionType.EVOLVE):
                evolve_typed += 1
            rows.append({"i": i, "helper_hit": hit, **raw, "hint": hint})

        # Only keep interesting dumps: has EVOLVE type, or MAIN with mega window
        sel_type = _si(getattr(obs.select, "type", None), -1)
        sel_ctx = _si(getattr(obs.select, "context", None), -1)
        interesting = (
            evolve_typed > 0
            or sel_ctx in (
                int(SelectContext.EVOLVE),
                int(SelectContext.EVOLVES_FROM),
                int(SelectContext.EVOLVES_TO),
            )
            or sel_type == int(SelectType.MAIN)
        )
        if interesting:
            legal = sp_mod._mega_evolve_legal_now(
                obs,
                {
                    "my_index": mi,
                    "select_options": options,
                    "board": None,
                    "turn_plan": None,
                },
                None,
                None,
            )
            # Also facts path via situation (heavier but once per dump)
            try:
                sit = sp_mod._compute_situation(obs)
                sit["select_options"] = options
                facts_can = bool(sit["turn_plan"].facts.staryu_can_evolve)
                mega_legal_full = sp_mod._mega_evolve_legal_now(
                    obs, sit, sit.get("board"), sit.get("turn_plan"),
                )
                my_turn = int(getattr(sit.get("board"), "my_turn_number", 0) or 0)
            except Exception as e:
                facts_can = None
                mega_legal_full = legal
                my_turn = None
                sit_err = str(e)
            else:
                sit_err = None

            store.append(
                {
                    "n": len(store),
                    "yourIndex": mi,
                    "turn": _si(getattr(obs.current, "turn", None)),
                    "my_turn_number": my_turn,
                    "firstPlayer": _si(getattr(obs.current, "firstPlayer", None)),
                    "select_type": sel_type,
                    "select_type_name": _enum_name(SelectType, sel_type),
                    "select_context": sel_ctx,
                    "select_context_name": _enum_name(SelectContext, sel_ctx),
                    "minCount": _si(getattr(obs.select, "minCount", None)),
                    "maxCount": _si(getattr(obs.select, "maxCount", None)),
                    "hand_ids": hand,
                    "field": field,
                    "n_options": len(options),
                    "n_evolve_typed": evolve_typed,
                    "helper_hits": helper_hits,
                    "mega_legal_opts_only": legal,
                    "facts_staryu_can_evolve": facts_can,
                    "mega_legal_full_waveL": mega_legal_full,
                    "sit_err": sit_err,
                    "options": rows,
                }
            )
        return inner_fn(obs_dict)

    return agent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--current", type=Path, default=ROOT / "submission_starmie",
    )
    ap.add_argument(
        "--baseline", type=Path, default=Path("/tmp/baseline_55202093_f07e541"),
    )
    ap.add_argument("-n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=140000)
    ap.add_argument("--max-events", type=int, default=80)
    ap.add_argument(
        "--out", type=Path, default=ROOT / "logs/dump_evolve_options",
    )
    ap.add_argument("--rules-only", action="store_true", default=True)
    args = ap.parse_args()

    if args.rules_only:
        os.environ["RL_ENABLED"] = "0"

    args.out.mkdir(parents=True, exist_ok=True)
    store: list[dict] = []

    cur_agent, cur_reset, cur_mod, deck, _ = load_starmie_agent(args.current)
    # Import helper module currently on path (current pilot)
    import starmie_pilot as sp  # noqa: WPS433

    dump_agent = make_dumping_agent(
        cur_agent, store=store, sp_mod=sp, max_events=args.max_events,
    )

    if args.baseline.is_dir():
        base_agent, base_reset, _bm, deck_b, _ = load_starmie_agent(args.baseline)
        assert deck == deck_b
        # Re-bind current after baseline load purged modules
        cur_agent, cur_reset, cur_mod, deck, _ = load_starmie_agent(args.current)
        import starmie_pilot as sp  # noqa: WPS433
        dump_agent = make_dumping_agent(
            cur_agent, store=store, sp_mod=sp, max_events=args.max_events,
        )
    else:
        base_agent, base_reset = cur_agent, cur_reset

    rng = random.Random(args.seed)
    t0 = time.time()
    games_done = 0
    for i in range(args.n):
        if len(store) >= args.max_events:
            break
        cur_is_a = (i % 2 == 0)
        if cur_reset:
            cur_reset()
        if base_reset and base_reset is not cur_reset:
            base_reset()
        seed = args.seed + i
        random.seed(seed)
        rng.seed(seed)
        if cur_is_a:
            play_game(dump_agent, base_agent, deck, deck, max_steps=250)
        else:
            play_game(base_agent, dump_agent, deck, deck, max_steps=250)
        games_done += 1
        if (i + 1) % 10 == 0:
            print(
                f"  [{i+1}/{args.n}] events={len(store)} games={games_done}",
                flush=True,
            )

    # Summaries
    type_ctr: Counter[str] = Counter()
    area_ctr: Counter[str] = Counter()
    shape_ctr: Counter[str] = Counter()
    ctx_ctr: Counter[str] = Counter()
    helper_vs_evolve = Counter()
    plateau_risk = 0
    for ev in store:
        ctx_ctr[ev["select_context_name"]] += 1
        if (
            ev.get("facts_staryu_can_evolve")
            and ev["helper_hits"] == 0
            and ev["n_evolve_typed"] == 0
            and ev["select_type_name"] == "MAIN"
        ):
            plateau_risk += 1
        for o in ev["options"]:
            if o.get("type_name") == "EVOLVE" or o.get("helper_hit"):
                type_ctr[o.get("type_name", "?")] += 1
                area_ctr[o.get("area_name", "?")] += 1
                shape = (
                    f"type={o.get('type_name')} area={o.get('area_name')} "
                    f"inPlay={o.get('inPlayArea_name')} "
                    f"idx={o.get('index')} inPlayIdx={o.get('inPlayIndex')} "
                    f"hint={o.get('hint')}"
                )
                shape_ctr[shape] += 1
                helper_vs_evolve[
                    f"evolve_typed={o.get('type_name')=='EVOLVE'} helper={o['helper_hit']}"
                ] += 1

    summary = {
        "games_played": games_done,
        "events": len(store),
        "elapsed_s": round(time.time() - t0, 1),
        "select_context_counts": dict(ctx_ctr),
        "evolve_option_type_counts": dict(type_ctr),
        "evolve_area_counts": dict(area_ctr),
        "helper_vs_type": dict(helper_vs_evolve),
        "top_shapes": shape_ctr.most_common(30),
        "plateau_risk_mains": plateau_risk,
        "note": (
            "plateau_risk_mains = MAIN selects where facts.staryu_can_evolve "
            "but zero EVOLVE-typed options and zero helper hits (Wave Q hazard)"
        ),
    }

    (args.out / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in store) + ("\n" if store else ""),
        encoding="utf-8",
    )
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Markdown report with a few examples
    lines = [
        "# 实机 EVOLVE 选项 dump",
        "",
        f"- games={games_done} events={len(store)} elapsed={summary['elapsed_s']}s",
        f"- seed0={args.seed} RL_ENABLED={os.environ.get('RL_ENABLED')}",
        f"- plateau_risk_mains={plateau_risk}",
        "",
        "## 汇总",
        "",
        "```json",
        json.dumps(summary, indent=2, ensure_ascii=False),
        "```",
        "",
        "## 典型事件（最多 8 条含 EVOLVE 或 helper_hit）",
        "",
    ]
    shown = 0
    for ev in store:
        if ev["n_evolve_typed"] == 0 and ev["helper_hits"] == 0:
            continue
        lines.append(
            f"### event {ev['n']} turn={ev['turn']} my_t={ev['my_turn_number']} "
            f"seat={ev['yourIndex']} ctx={ev['select_context_name']}"
        )
        lines.append(
            f"- hand={ev['hand_ids']} active={ev['field']['active_id']} "
            f"canEvolve={ev['field']['active_canEvolve']} "
            f"facts_can={ev['facts_staryu_can_evolve']} "
            f"helper_hits={ev['helper_hits']}/{ev['n_evolve_typed']} "
            f"mega_legal_full={ev['mega_legal_full_waveL']}"
        )
        for o in ev["options"]:
            if o.get("type_name") == "EVOLVE" or o.get("helper_hit"):
                lines.append(f"  - `{json.dumps(o, ensure_ascii=False)}`")
        lines.append("")
        shown += 1
        if shown >= 8:
            break

    if plateau_risk:
        lines.append("## plateau_risk 样例（最多 5）")
        lines.append("")
        n = 0
        for ev in store:
            if not (
                ev.get("facts_staryu_can_evolve")
                and ev["helper_hits"] == 0
                and ev["n_evolve_typed"] == 0
                and ev["select_type_name"] == "MAIN"
            ):
                continue
            lines.append(
                f"- event {ev['n']} my_t={ev['my_turn_number']} "
                f"active={ev['field']['active_id']} "
                f"canEvolve={ev['field']['active_canEvolve']} "
                f"appear={ev['field'].get('active_appearThisTurn')} "
                f"types={[o.get('type_name') for o in ev['options'][:12]]}"
            )
            n += 1
            if n >= 5:
                break
        lines.append("")

    (args.out / "DUMP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"wrote {args.out / 'DUMP.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
