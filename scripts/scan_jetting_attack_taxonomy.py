#!/usr/bin/env python3
"""Taxonomy: fueled Mega + Jetting offered → JETTING / DELAY_FOR_PREP / LEAK.

Ship-bar evidence for MustClose-Urgent-V1. Distinguishes intentional same-turn
DP prep from true attack leaks. Also re-scores frames with the current pilot
and an optional ``urgent=False`` shadow (pre-knife policy).

Usage:
  PYTHONPATH=submission_starmie:submission_starmie/pilot:scripts:. \\
    OPENING_HANDOFF=0 RL_ENABLED=0 python3 scripts/scan_jetting_attack_taxonomy.py \\
    --sid 55393166 --losses-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "submission_starmie" / "pilot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OPENING_HANDOFF", "0")
os.environ.setdefault("RL_ENABLED", "0")
os.environ.setdefault("PYTHONHASHSEED", "0")

from cg.api import OptionType, to_observation_class  # noqa: E402
import starmie_pilot as sp  # noqa: E402

MEGA_STARMIE = 1031
MUNKIDORI = 112
DARK, WATER = 7, 3
JETTING = 1487
CRISPIN, NIGHT_STRETCHER = 1198, 1152
POFFIN, POKE_PAD = 1193, 1190  # best-effort; LEAK also catches via non-prep
PLAY, ATTACH, EVOLVE, ABILITY, ATTACK, END, RETREAT = 7, 8, 9, 10, 13, 14, 12
MAIN = 0

PREP_REQS = frozenset({"ATTACH_DARK", "ADRENA", "BOSS", "DISPATCH", "EVOLVE_104"})


@dataclass
class Frame:
    sid: int
    eid: int
    si: int
    seat: str
    turn: int
    prize_self: int
    opp_hp: int
    urgent: bool
    online_tax: str
    online_detail: str
    head_tax: str
    head_detail: str
    shadow_tax: str
    shadow_detail: str
    live_prep: tuple[str, ...]


def _ids(cards) -> list[int]:
    out = []
    for c in cards or []:
        if c and c.get("id") is not None:
            out.append(int(c["id"]))
    return out


def _opt_hand_id(opt: dict, hand_ids: list[int]) -> int | None:
    for k in ("cardId", "card_id", "id"):
        v = opt.get(k)
        if v is not None:
            return int(v)
    for k in ("index", "handIndex"):
        idx = opt.get(k)
        if idx is not None and 0 <= int(idx) < len(hand_ids):
            return hand_ids[int(idx)]
    return None


def _fueled_active_mega(me: dict) -> bool:
    act = (me.get("active") or [None])[0]
    if not act or int(act.get("id") or 0) != MEGA_STARMIE:
        return False
    ens = [int(e) for e in (act.get("energies") or []) if e is not None]
    return WATER in ens or 9 in ens  # prism


def _opp_active_hp(opp: dict) -> int:
    act = (opp.get("active") or [None])[0]
    if not act:
        return 10**9
    try:
        return int(act.get("hp") or 10**9)
    except Exception:
        return 10**9


def _is_urgent(prize_self: int, opp_hp: int) -> bool:
    return prize_self <= 2 or 0 < opp_hp <= 120


def _is_delay_prep_option(
    opt: dict,
    hand_ids: list[int],
    me: dict,
    live_prep: tuple[str, ...],
) -> str | None:
    """Return prep tag if this option is intentional same-turn DP/combat prep."""
    t = int(opt.get("type") or -1)
    cid = _opt_hand_id(opt, hand_ids)
    field_ids = {int(p.get("id") or 0) for p in (me.get("active") or []) + (me.get("bench") or []) if p}
    munk = next(
        (p for p in (me.get("active") or []) + (me.get("bench") or []) if p and int(p.get("id") or 0) == MUNKIDORI),
        None,
    )
    munk_has_dark = bool(
        munk and any(int(e) == DARK for e in (munk.get("energies") or []) if e is not None)
    )

    if t == ATTACH and cid == DARK and munk and not munk_has_dark:
        return "ATTACH_DARK"
    if t == PLAY and cid == MUNKIDORI and MUNKIDORI not in field_ids:
        return "SEAT_MUNK"
    if t == PLAY and cid == CRISPIN and munk and not munk_has_dark and DARK not in hand_ids:
        return "DIG_DARK_CRISPIN"
    if t == PLAY and cid == NIGHT_STRETCHER and munk and not munk_has_dark:
        disc = _ids(me.get("discard"))
        if DARK in disc:
            return "DIG_DARK_NS"
    if t == ABILITY and "ADRENA" in live_prep:
        return "ADRENA"
    if t == PLAY and cid == 1182 and "BOSS" in live_prep:  # Boss's Orders
        return "BOSS"
    if t == EVOLVE and "EVOLVE_104" in live_prep:
        return "EVOLVE_104"
    if t == RETREAT and "DISPATCH" in live_prep:
        return "DISPATCH"
    if t == PLAY and cid == 1123 and "DISPATCH" in live_prep:  # Switch
        return "DISPATCH"
    return None


def classify_choice(
    action,
    opts: list[dict],
    hand_ids: list[int],
    me: dict,
    live_prep: tuple[str, ...],
) -> tuple[str, str]:
    if not action:
        return "LEAK", "EMPTY_ACTION"
    try:
        idx = int(action[0])
    except Exception:
        return "LEAK", "BAD_ACTION"
    if not (0 <= idx < len(opts)):
        return "LEAK", "OOB_ACTION"
    opt = opts[idx]
    t = int(opt.get("type") or -1)
    if t == ATTACK and int(opt.get("attackId") or 0) == JETTING:
        return "JETTING", "JETTING"
    if t == ATTACK:
        return "JETTING", f"OTHER_ATK_{opt.get('attackId')}"
    prep = _is_delay_prep_option(opt, hand_ids, me, live_prep)
    if prep:
        return "DELAY_FOR_PREP", prep
    if t == END:
        return "LEAK", "END"
    cid = _opt_hand_id(opt, hand_ids)
    return "LEAK", f"T{t}_cid{cid}"


def _rank_winner(obs, sit, force_urgent: bool | None):
    """Return (tax, detail, live_prep) for pilot argmax.

    ``force_urgent`` is ignored after MustClose-Urgent rollback (kept for API).
    """
    try:
        try:
            sp.reset_for_new_game()
        except Exception:
            pass
        sit = dict(sit)
        sit["select_options"] = list(obs.select.option)
        live_prep = ()
        try:
            live_prep = tuple(
                sp._actionable_pre_attack(obs, sit, sit["turn_plan"].combat)
            )
        except Exception:
            live_prep = ()
        ranked = []
        for i, o in enumerate(obs.select.option):
            sc = float(sp.option_score(obs, o, {}, sit))
            ranked.append((sc, i, o))
        ranked.sort(key=lambda x: x[0], reverse=True)
        _sc, wi, wo = ranked[0]
        me = obs.current.players[sit["my_index"]]
        hand_ids = [int(c.id) for c in (me.hand or []) if c]
        # Classify against a 1-option list (action index must be 0).
        opt_d = {
            "type": int(wo.type),
            "attackId": int(getattr(wo, "attackId", 0) or 0),
            "index": getattr(wo, "index", None),
            "handIndex": getattr(wo, "handIndex", None),
            "cardId": getattr(wo, "cardId", None) or getattr(wo, "id", None),
        }
        me_d = {
            "active": [
                {
                    "id": getattr(p, "id", None),
                    "energies": list(getattr(p, "energies", None) or []),
                }
                for p in (me.active or [])
                if p
            ],
            "bench": [
                {
                    "id": getattr(p, "id", None),
                    "energies": list(getattr(p, "energies", None) or []),
                }
                for p in (me.bench or [])
                if p
            ],
            "hand": [{"id": cid} for cid in hand_ids],
            "discard": [
                {"id": getattr(c, "id", None)}
                for c in (getattr(me, "discard", None) or [])
                if c
            ],
        }
        tax, detail = classify_choice([0], [opt_d], hand_ids, me_d, live_prep)
        return tax, detail, live_prep
    except Exception:
        return "LEAK", "SCORE_ERR", ()


def iter_loss_games(sid: int, sub: Path, losses_only: bool):
    fade_path = ROOT / "data" / "kaggle_episodes" / f"analysis_{sid}_fade.json"
    if fade_path.exists():
        fade = json.loads(fade_path.read_text())
        for g in fade.get("games") or []:
            if "PUBLIC" not in (g.get("type") or ""):
                continue
            if losses_only and g.get("won"):
                continue
            mi = 0 if g.get("seat") == "A" else 1
            path = sub / f"episode-{g['eid']}-replay.json"
            if path.exists():
                yield int(g["eid"]), mi, g.get("seat", "?"), path
        return
    # fallback: all episodes, seat from TeamNames
    for path in sorted(sub.glob("episode-*-replay.json")):
        d = json.loads(path.read_text())
        names = d.get("info", {}).get("TeamNames") or []
        try:
            mi = names.index("Ying Peter")
        except ValueError:
            mi = 0
        eid = int(path.stem.split("-")[1])
        yield eid, mi, "A" if mi == 0 else "B", path


def scan_sid(sid: int, losses_only: bool) -> list[Frame]:
    sub = ROOT / "data" / "kaggle_episodes" / f"sub_{sid}"
    frames: list[Frame] = []
    for eid, mi, seat, path in iter_loss_games(sid, sub, losses_only):
        d = json.loads(path.read_text())
        steps = d.get("steps") or []
        for si, step in enumerate(steps):
            if mi >= len(step):
                continue
            side = step[mi]
            obs_d = side.get("observation") or {}
            cur = obs_d.get("current") or {}
            if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
                continue
            sel = obs_d.get("select") or {}
            raw_ctx = sel.get("context")
            if int(raw_ctx if raw_ctx is not None else -1) != MAIN:
                continue
            opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
            # kaggle-environments off-by-one: the action answering THIS
            # observation is recorded on the NEXT step (same agent slot).
            online_action = None
            if si + 1 < len(steps) and mi < len(steps[si + 1]):
                online_action = steps[si + 1][mi].get("action")
            if not opts or not online_action:
                continue
            if not any(
                int(o.get("type") or -1) == ATTACK and int(o.get("attackId") or 0) == JETTING
                for o in opts
            ):
                continue
            players = cur.get("players") or []
            if mi >= len(players) or not players[mi]:
                continue
            me = players[mi]
            opp = players[1 - mi] or {}
            if not _fueled_active_mega(me):
                continue
            hand_ids = _ids(me.get("hand"))
            prize_self = int(me.get("prizeCount") or len(me.get("prize") or []) or 6)
            opp_hp = _opp_active_hp(opp)
            urgent = _is_urgent(prize_self, opp_hp)

            obs = to_observation_class(obs_d)
            try:
                sp.reset_for_new_game()
            except Exception:
                pass
            sit = sp._compute_situation(obs)
            sit["select_options"] = list(obs.select.option)
            live_prep = ()
            try:
                live_prep = tuple(
                    sp._actionable_pre_attack(obs, sit, sit["turn_plan"].combat)
                )
            except Exception:
                pass

            online_tax, online_detail = classify_choice(
                online_action, opts, hand_ids, me, live_prep
            )
            head_tax, head_detail, _ = _rank_winner(obs, sit, force_urgent=None)
            shadow_tax, shadow_detail, _ = _rank_winner(obs, sit, force_urgent=False)

            frames.append(
                Frame(
                    sid=sid,
                    eid=eid,
                    si=si,
                    seat=seat,
                    turn=int(cur.get("turn") or 0),
                    prize_self=prize_self,
                    opp_hp=opp_hp if opp_hp < 10**8 else -1,
                    urgent=urgent,
                    online_tax=online_tax,
                    online_detail=online_detail,
                    head_tax=head_tax,
                    head_detail=head_detail,
                    shadow_tax=shadow_tax,
                    shadow_detail=shadow_detail,
                    live_prep=live_prep,
                )
            )
    return frames


def summarize(frames: list[Frame], label: str) -> list[str]:
    lines = [f"## {label}", f"n_frames={len(frames)}", ""]
    if not frames:
        return lines + ["(no frames)", ""]

    def bucket(rows: list[Frame], attr: str) -> Counter:
        return Counter(getattr(r, attr) for r in rows)

    for title, rows in (
        ("all", frames),
        ("urgent", [f for f in frames if f.urgent]),
        ("non_urgent", [f for f in frames if not f.urgent]),
    ):
        if not rows:
            continue
        n = len(rows)
        lines.append(f"### {title} (n={n})")
        lines.append("")
        lines.append("| source | JETTING | DELAY_FOR_PREP | LEAK |")
        lines.append("|---|---:|---:|---:|")
        for src, attr in (
            ("online", "online_tax"),
            ("HEAD(current)", "head_tax"),
            ("HEAD(urgent=off)", "shadow_tax"),
        ):
            c = bucket(rows, attr)
            lines.append(
                f"| {src} | {c['JETTING']} ({c['JETTING']/n:.0%}) | "
                f"{c['DELAY_FOR_PREP']} ({c['DELAY_FOR_PREP']/n:.0%}) | "
                f"{c['LEAK']} ({c['LEAK']/n:.0%}) |"
            )
        lines.append("")

        # Knife KPI: urgent + DELAY available under shadow → current should Jetting
        knife = [
            f
            for f in rows
            if f.urgent and f.shadow_tax == "DELAY_FOR_PREP"
        ]
        if knife:
            converted = sum(1 for f in knife if f.head_tax == "JETTING")
            lines.append(
                f"- **紧急窗刀口**：shadow=DELAY 的帧 {len(knife)}，"
                f"current→JETTING {converted}/{len(knife)} ({converted/len(knife):.0%})"
            )
        leak_head = sum(1 for f in rows if f.head_tax == "LEAK")
        lines.append(
            f"- **HEAD LEAK（政策空过）**：{leak_head}/{n} ({leak_head/n:.0%}) — 目标≈0"
        )
        # detail breakdown online LEAK
        leak_d = Counter(f.online_detail for f in rows if f.online_tax == "LEAK")
        if leak_d:
            top = ", ".join(f"{k}:{v}" for k, v in leak_d.most_common(6))
            lines.append(f"- online LEAK 细目：{top}")
        delay_d = Counter(f.online_detail for f in rows if f.online_tax == "DELAY_FOR_PREP")
        if delay_d:
            top = ", ".join(f"{k}:{v}" for k, v in delay_d.most_common(6))
            lines.append(f"- online DELAY 细目：{top}")
        lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, nargs="+", default=[55393166, 55386951])
    ap.add_argument("--losses-only", action="store_true", default=True)
    ap.add_argument("--include-wins", action="store_true")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs" / "diagnose_must_close_v1" / "JETTING_TAXONOMY.md",
    )
    args = ap.parse_args()
    losses_only = not args.include_wins

    all_frames: list[Frame] = []
    sections: list[str] = [
        "# Jetting 攻击空过分类 — MustClose-Urgent 提交证据",
        "",
        "口径：Active 充能 Mega Starmie + MAIN 选项含 Jetting。",
        "",
        "- **JETTING**：选了攻击（优先 1487）",
        "- **DELAY_FOR_PREP**：故意同回合 DP/战斗 prep（ATTACH_DARK / 铺猿 / Crispin·NS 挖暗 / ADRENA / BOSS）",
        "- **LEAK**：END / Poffin / 乱贴 / 空 action 等非 prep 非攻",
        "",
        "`HEAD(urgent=off)` = 同帧强制 `_must_close_urgent=False`，模拟刀前政策。",
        "",
    ]

    by_sid: dict[int, list[Frame]] = {}
    for sid in args.sid:
        frames = scan_sid(sid, losses_only=losses_only)
        by_sid[sid] = frames
        all_frames.extend(frames)
        sections += summarize(frames, f"sid={sid} losses_only={losses_only}")

    sections += summarize(all_frames, f"合计 sids={args.sid}")

    # Verdict block
    urgent = [f for f in all_frames if f.urgent]
    knife = [f for f in urgent if f.shadow_tax == "DELAY_FOR_PREP"]
    converted = sum(1 for f in knife if f.head_tax == "JETTING")
    head_leak = sum(1 for f in all_frames if f.head_tax == "LEAK")
    sections += [
        "## 判决材料",
        "",
        f"- 紧急帧：{len(urgent)} / 全帧 {len(all_frames)}",
        f"- 刀口可转化（urgent ∧ shadow=DELAY）：{len(knife)}；"
        f"current→JETTING **{converted}/{len(knife) if knife else 0}**",
        f"- HEAD LEAK 全帧：{head_leak}/{len(all_frames)}",
        "",
        "放行条件（本脚本可证）：",
        "1. HEAD LEAK ≈ 0（政策不再主动选非 prep 杂项）",
        "2. 刀口可转化帧上 current→JETTING 明显高于 shadow",
        "3. Opening 否决另见 `h2h_audit_mustCloseUrgent_n200/GATE.md`",
        "",
        "> 线上 online 列仍含回放≠现场噪声；**不得**单用 online LEAK 当政策死刑。",
        "",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(sections), encoding="utf-8")
    raw = args.out.with_suffix(".json")
    raw.write_text(
        json.dumps([asdict(f) for f in all_frames], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    print(f"wrote {raw}")
    print("\n".join(sections[-40:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
