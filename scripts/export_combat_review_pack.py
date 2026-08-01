#!/usr/bin/env python3
"""Export a combat expert-review pack: NL .log per game + manifest + README.

Default: T-C-BC pool (alak/lucario/marnie/dragapult), 10 games each, seed0=91000.

Usage:
  PYTHONPATH=submission_starmie:submission_starmie/pilot \
    python3 scripts/export_combat_review_pack.py \
      --games 10 --seed0 91000 \
      --decks alakazam_main,lucario_fighting,marnie_froslass_munk,dragapult \
      --bc alakazam_main,lucario_fighting,marnie_froslass_munk,dragapult \
      --out-dir logs/combat_review_manual
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submission_starmie"
for p in (str(ROOT), str(SUB), str(SUB / "pilot"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("RL_ENABLED", "1")
os.environ.setdefault("USE_HYBRID", "1")

from arena.deck import load_deck_csv  # noqa: E402
from arena.simulator import play_game  # noqa: E402
import arena.policy as policy_mod  # noqa: E402
import main as sub_main  # noqa: E402
import starmie_pilot as sp  # noqa: E402
from combat_log_renderer import render_combat_log  # noqa: E402

# Minimal tag instrumentation (aligned with run_combat_eval taxonomy).
BOSS = 1182
SUPPORTERS = {1182, 1198, 1213, 1225, 1227, 1229, 1189}
DUNSPARCE, DUDUNSPARCE = 65, 66
MEGA_STARMIE, MEGA_FROSLASS = 1031, 861
FROSLASS_104, MUNKIDORI = 104, 112
ST_ATKS = {1487, 1488}
MF_ATKS = {1240, 1241}
OPT_PLAY, OPT_ATTACK = 7, 13
DARK_ENERGIES = {7, 16, 17}


def _si(x, d=0):
    try:
        return int(x)
    except Exception:
        return d


def _field_ids(p: dict) -> list[int]:
    return [
        _si((x or {}).get("id"))
        for x in (p.get("active") or []) + (p.get("bench") or [])
        if x
    ]


def make_tags(g: dict) -> list[str]:
    tags = []
    if g["boss"] == 0:
        tags.append("zero_boss")
    if g["sup"] == 0:
        tags.append("no_supporter")
    if g["st_atk"] + g["mf_atk"] == 0:
        tags.append("no_attack")
    if not g["ever_mega"]:
        tags.append("no_mega")
    if not g["ever_861"]:
        tags.append("no_861")
    if g["ever_861"] and g["mf_atk"] == 0:
        tags.append("861_no_fire")
    if not g["ever_dun"]:
        tags.append("no_dun")
    if g["ever_dun"] and g["evo66"] == 0:
        tags.append("dun_no_66")
    if g.get("prize_stuck"):
        tags.append("prize_stuck")
    if g.get("ever_104") and g.get("ever_munk") and g.get("ever_munk_dark"):
        tags.append("dp_ok")
    elif not g.get("ever_104") or not g.get("ever_munk_dark"):
        tags.append("dp_miss")
    return tags


def _bc_agent_for(deck_name: str):
    from alak_bc import make_alak_bc_agent

    cand = ROOT / "data" / "opening_sft" / f"bc_{deck_name}.npz"
    if deck_name == "alakazam_main":
        cand = ROOT / "data" / "opening_sft" / "alak_bc_opponent.npz"
    if not cand.exists():
        raise FileNotFoundError(f"no BC weights for {deck_name}: {cand}")
    return make_alak_bc_agent(cand)


README = """# 全战专家审阅说明

本包由 `scripts/export_combat_review_pack.py` 生成。每局一个中文 `.log`，
由引擎逐步 Log 渲染（金标风格标签：`[抽牌]` `[放置]` `[操作]` `[贴能]`
`[进化]` `[攻击]` `[伤害]` 等）。

## 审阅焦点

1. **运营**：开局到 Mega 海星、DP 套（愿增猿+雪妖女104+恶能）、支援者
   取舍（莉莉艾/希尔达 vs Boss）、雪童子/海星星铺场是否过量。
2. **战斗**：Boss 时机与目标、攻击选择、奖品路径、第二打手（861）是否
   在海星危险时及时接上。

## 怎么标

在页眉下方新增一行（可多条）：

```
// note_ops=...
// note_combat=...
// expert_status=reviewed
```

本阶段**不要求**改写操作步骤；以问题标注为主，供规则迭代。

## 页眉字段

- `opp_deck` / `opp_policy`：对手卡组与策略（bc / heuristic）
- `we_are_a`：true=我方先手座位 agent_a
- `winner`：0=座位A胜，1=座位B胜；结合 `we_are_a` 看我方胜负
- `tags`：自动损失/结构标签（含 `dp_ok` / `dp_miss`）
"""


def play_one(
    *,
    deck_me: list[int],
    deck_opp: list[int],
    opp_agent,
    seed: int,
    we_are_a: bool,
) -> tuple[object, dict]:
    """Play one game; return (GameResult, stats dict). Seat0 always agent_a."""
    random.seed(seed)
    sp.reset_for_new_game()
    agent0 = sub_main.agent

    gstat = {
        "boss": 0,
        "sup": 0,
        "st_atk": 0,
        "mf_atk": 0,
        "evo66": 0,
        "ever_mega": False,
        "ever_861": False,
        "ever_dun": False,
        "ever_104": False,
        "ever_munk": False,
        "ever_munk_dark": False,
        "prize_stuck": False,
        "prize_timeline": [],
    }
    tr = {"turn": -1, "last_prize_self": None}

    def wrap_our(obs_dict, _gs=gstat, _tr=tr):
        decision = agent0(obs_dict)
        try:
            cur = obs_dict.get("current") or {}
            mi = _si(cur.get("yourIndex"))
            me = (cur.get("players") or [{}, {}])[mi]
            opp = (cur.get("players") or [{}, {}])[1 - mi]
            sel = obs_dict.get("select") or {}
            opts = sel.get("option") or []
            st = sp._LIVE_AGENT_STATE or {}
            mt = _si(st.get("max_my_turn"))
            fid = _field_ids(me)
            if MEGA_STARMIE in fid:
                _gs["ever_mega"] = True
            if MEGA_FROSLASS in fid:
                _gs["ever_861"] = True
            if DUNSPARCE in fid or DUDUNSPARCE in fid:
                _gs["ever_dun"] = True
            if FROSLASS_104 in fid:
                _gs["ever_104"] = True
            for x in (me.get("active") or []) + (me.get("bench") or []):
                if not x:
                    continue
                if _si(x.get("id")) == MUNKIDORI:
                    _gs["ever_munk"] = True
                    ens = [_si(e) for e in (x.get("energies") or [])]
                    if any(e in DARK_ENERGIES for e in ens):
                        _gs["ever_munk_dark"] = True
            if mt != _tr["turn"]:
                _tr["turn"] = mt
                ps = len(me.get("prize") or [])
                po = len(opp.get("prize") or [])
                _gs["prize_timeline"].append((mt, ps, po))
                if (
                    _tr["last_prize_self"] is not None
                    and ps == _tr["last_prize_self"]
                    and mt >= 6
                    and ps > 0
                ):
                    # crude stuck signal: no prize progress late
                    pass
                _tr["last_prize_self"] = ps
            hand = me.get("hand") or []
            for d in decision:
                if not (isinstance(d, int) and 0 <= d < len(opts)):
                    continue
                o = opts[d]
                t = _si(o.get("type"))
                if t == OPT_ATTACK:
                    aid = _si(o.get("attackId"))
                    if aid in ST_ATKS:
                        _gs["st_atk"] += 1
                    elif aid in MF_ATKS:
                        _gs["mf_atk"] += 1
                elif t == OPT_PLAY:
                    idx = _si(o.get("index"), -1)
                    cid = (
                        _si((hand[idx] or {}).get("id"))
                        if 0 <= idx < len(hand)
                        else 0
                    )
                    if cid in SUPPORTERS:
                        _gs["sup"] += 1
                    if cid == BOSS:
                        _gs["boss"] += 1
                    if cid == DUDUNSPARCE:
                        _gs["evo66"] += 1
                elif t == 9:  # EVOLVE
                    idx = _si(o.get("index"), -1)
                    cid = (
                        _si((hand[idx] or {}).get("id"))
                        if 0 <= idx < len(hand)
                        else 0
                    )
                    if cid == DUDUNSPARCE:
                        _gs["evo66"] += 1
        except Exception:
            pass
        return decision

    if we_are_a:
        result = play_game(
            wrap_our,
            opp_agent,
            deck_me,
            deck_opp,
            collect_engine_logs=True,
        )
        our_pi = 0
        reward_for_us = result.reward_for_a
    else:
        result = play_game(
            opp_agent,
            wrap_our,
            deck_opp,
            deck_me,
            collect_engine_logs=True,
        )
        our_pi = 1
        reward_for_us = -result.reward_for_a

    # prize stuck: last 3 my-turns same prize count > 0
    tl = gstat["prize_timeline"]
    if len(tl) >= 3:
        lasts = [x[1] for x in tl[-3:]]
        if lasts[0] == lasts[1] == lasts[2] and lasts[0] > 0 and reward_for_us <= 0:
            gstat["prize_stuck"] = True

    gstat["reward_for_us"] = reward_for_us
    gstat["our_player_index"] = our_pi
    return result, gstat


def main() -> int:
    ap = argparse.ArgumentParser(description="Export combat NL review pack")
    ap.add_argument("--games", type=int, default=10, help="games per deck")
    ap.add_argument("--seed0", type=int, default=91_000)
    ap.add_argument(
        "--decks",
        default="alakazam_main,lucario_fighting,marnie_froslass_munk,dragapult",
    )
    ap.add_argument(
        "--bc",
        default="alakazam_main,lucario_fighting,marnie_froslass_munk,dragapult",
        help="comma list using BC opponents (empty = all heuristic)",
    )
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    decks = [d.strip() for d in args.decks.split(",") if d.strip()]
    bc_set = {d.strip() for d in args.bc.split(",") if d.strip()}
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or (ROOT / "logs" / f"combat_review_{ts}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    deck_me = load_deck_csv(SUB / "deck.csv")
    manifest: list[dict] = []

    for deck_name in decks:
        deck_opp = load_deck_csv(ROOT / "data" / "decks" / f"{deck_name}.csv")
        policy = "bc" if deck_name in bc_set else "heuristic"
        if policy == "bc":
            opp_agent = _bc_agent_for(deck_name)
        else:
            opp_agent = policy_mod.make_agent(deck_opp, dict(policy_mod.DEFAULT_WEIGHTS))

        wins = 0
        for i in range(args.games):
            seed = args.seed0 + i
            we_are_a = i % 2 == 0
            result, gstat = play_one(
                deck_me=deck_me,
                deck_opp=deck_opp,
                opp_agent=opp_agent,
                seed=seed,
                we_are_a=we_are_a,
            )
            tags = make_tags(gstat)
            if gstat["reward_for_us"] > 0:
                wins += 1
                # drop loss-only noise tags for wins except dp
                tags = [t for t in tags if t in ("dp_ok", "dp_miss")]

            our_pi = gstat["our_player_index"]
            header = {
                "seed": seed,
                "opp_deck": deck_name,
                "opp_policy": policy,
                "we_are_a": we_are_a,
                "winner": result.winner,
                "reward_for_us": gstat["reward_for_us"],
                "steps": result.steps,
                "truncated": result.truncated,
                "tags": tags,
                "prize_final": (
                    gstat["prize_timeline"][-1]
                    if gstat["prize_timeline"]
                    else None
                ),
            }
            text = render_combat_log(
                result.engine_logs,
                header=header,
                our_player_index=our_pi,
            )
            fname = f"game_{deck_name}_{seed}.log"
            (out_dir / fname).write_text(text, encoding="utf-8")
            manifest.append({
                **header,
                "file": fname,
                "n_engine_logs": len(result.engine_logs),
                "ever_mega": gstat["ever_mega"],
                "ever_104": gstat["ever_104"],
                "ever_munk_dark": gstat["ever_munk_dark"],
                "boss": gstat["boss"],
                "st_atk": gstat["st_atk"],
                "mf_atk": gstat["mf_atk"],
            })
            print(f"  {fname}: us_reward={gstat['reward_for_us']} tags={tags}")

        print(f"[{deck_name}/{policy}] {wins}/{args.games} wins")

    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "ts": ts,
                "seed0": args.seed0,
                "games_per_deck": args.games,
                "decks": decks,
                "bc": sorted(bc_set),
                "n": len(manifest),
                "games": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "README_专家审阅.md").write_text(README, encoding="utf-8")
    print(f"wrote {len(manifest)} logs → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
