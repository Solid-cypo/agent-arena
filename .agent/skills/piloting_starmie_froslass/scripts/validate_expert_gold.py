#!/usr/bin/env python3
"""Validate expert gold OPENING logs (text audit, no seed re-run)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_DIR = SCRIPTS.parent / "logs" / "review_manual" / "expert_gold_v1"

SUPPORTER_ZH = {
    "裁判",
    "克里宾",
    "希尔达",
    "莉莉艾",
    "萨瓦托",
    "瓦利的慈悲",
    "老大的指令",
}
SUPPORTER_PLAY_PAT = re.compile(
    r"使用\s+(" + "|".join(re.escape(s) for s in SUPPORTER_ZH) + r")(?:\s|$|（)"
)
VALID_STATUS = {"edited", "approved", "unreachable"}
GOAL_BOARD_PAT = re.compile(r"Active:\s*Mega 大海星 ex\s*\[([^\]]*)\]")
STEP_PAT = re.compile(r"^\s*(\d+)[.\s]")
RETREAT_COST_ZH: dict[str, int] = {
    "Mega 大海星 ex": 2,
    "Mega 大雪妖女 ex": 1,
    "海星星": 1,
    "雪童子": 1,
    "旋转罗盘": 1,
    "喵头目 ex": 1,
    "含羞苞": 1,
    "愿增猿": 1,
    "雪妖女": 1,
    "土龙节节（逃跑抽牌）": 1,
    "土龙节节 ex": 1,
    "土龙节节": 1,
    "土龙弟弟": 0,
}
BASIC_ZH = {"含羞苞", "海星星", "雪童子", "土龙弟弟", "旋转罗盘"}
PRISM_ZH = "棱镜能量"
RUN_AWAY_HINTS = ("土龙节节", "逃跑抽牌", "Run Away", "撤退抽")
BOARD_ACTIVE_PAT = re.compile(r"Active:\s*(.+?)(?:\s*\[([^\]]*)\])?\s*$")
BOARD_BENCH_PAT = re.compile(r"Bench\s*\[\d+\]:\s*(.+?)(?:\s*\[([^\]]*)\])?\s*$")


def _parse_energies(bracket: str | None) -> list[str]:
    out: list[str] = []
    if not bracket:
        return out
    for tok in bracket.split(","):
        tok = tok.strip()
        if not tok or tok == "无能量":
            continue
        out.append(tok)
    return out


def _parse_board(lines: list[str], marker: str):
    capture = False
    active_name = None
    active_eng: list[str] = []
    bench: list[tuple[str, list[str]]] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(marker):
            capture = True
            continue
        if not capture:
            continue
        if s.startswith("回合") or s.startswith("【") or s.startswith("本回合"):
            break
        m = BOARD_ACTIVE_PAT.match(s)
        if m:
            active_name = m.group(1).strip()
            active_eng = _parse_energies(m.group(2))
            continue
        m = BOARD_BENCH_PAT.match(s)
        if m:
            bench.append((m.group(1).strip(), _parse_energies(m.group(2))))
            continue
        if s.startswith("Bench:") and "空" in s:
            continue
    return active_name, active_eng, bench


def _hand_list(block: str) -> list[str]:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return []
    joined = " ".join(lines)
    if "略" in joined or joined.startswith("（"):
        return ["__PLACEHOLDER__"]
    parts = []
    for ln in lines:
        parts.extend([p.strip() for p in ln.split(",") if p.strip()])
    return parts


def validate_file(path: Path, *, strict: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # H1
    m = re.search(r"expert_status=(\w+)", text)
    if not m or m.group(1) not in VALID_STATUS:
        errors.append("H1: missing/invalid expert_status")
        status = "?"
    else:
        status = m.group(1)

    # H3
    role_m = re.search(r"role=(\S+)", text)
    lim_m = re.search(r"turn_limit=(\d+)", text)
    if not role_m or not lim_m:
        errors.append("H3: missing role/turn_limit")
    going_first = role_m.group(1) == "先攻" if role_m else False

    goal_m = re.search(r"goal=(\w+)", text)
    goal = goal_m.group(1) == "True" if goal_m else False

    # H2 final board
    actives = re.findall(r"Active:\s*(.+)", text)
    if goal and actives:
        last = actives[-1]
        if "Mega 大海星 ex" not in last:
            errors.append(f"H2: goal=True but last Active={last}")
        else:
            eng = re.search(r"\[([^\]]*)\]", last)
            if eng and "水" not in eng.group(1) and "无能量" in eng.group(1):
                warnings.append("H2: Mega Active has no water energy bracket")

    # Per-turn checks
    for tm in re.finditer(
        r"【My-T(\d+)】.*?本回合操作:\n(.*?)(?:\n  回合结束手牌:)", text, re.S
    ):
        turn = int(tm.group(1))
        ops = tm.group(2)
        # F1 numbering
        nums = [int(m.group(1)) for m in STEP_PAT.finditer(ops)]
        if nums and nums != list(range(1, len(nums) + 1)):
            # allow empty （无）
            if "（无）" not in ops:
                warnings.append(f"F1: T{turn} step numbers {nums}")

        # R3 one attach
        if ops.count("[贴能]") > 1:
            errors.append(f"R3: T{turn} multi-attach")

        # R4 one supporter
        plays = SUPPORTER_PLAY_PAT.findall(ops)
        # count only primary play lines
        play_lines = [
            ln
            for ln in ops.splitlines()
            if re.match(r"\s+\d+\. \[操作\] 使用\s+", ln)
            and SUPPORTER_PLAY_PAT.search(ln)
        ]
        if len(play_lines) > 1:
            errors.append(f"R4: T{turn} multi-supporter {[p for p in plays]}")

        # R1 going-first T1 supporter
        if going_first and turn == 1 and play_lines:
            errors.append(f"R1: 先攻 T1 supporter")

        # C2/C4 draw
        draws = ops.count("[抽牌]")
        if going_first and turn == 1:
            if draws != 0:
                errors.append(f"C2: 先攻 T1 has draw")
        else:
            if draws != 1 and "（无）" not in ops:
                # some edited may omit draw detail — warn
                if draws == 0:
                    warnings.append(f"C4: T{turn} missing draw")
                else:
                    warnings.append(f"C4: T{turn} draw_count={draws}")

        # placeholder ops
        if "（略）" in ops or "（撤退费能量）" in ops:
            warnings.append(f"W: T{turn} has placeholder text")

    if status == "unreachable" and goal:
        warnings.append("unreachable but goal=True")

    if strict and warnings:
        errors.extend(f"strict:{w}" for w in warnings)

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    files = sorted(args.dir.glob("*.log"))
    n_err = n_warn = 0
    bad: list[str] = []
    for f in files:
        errs, warns = validate_file(f, strict=args.strict)
        if errs or warns:
            print(f"== {f.name} ==")
            for e in errs:
                print(f"  ERROR {e}")
            for w in warns:
                print(f"  WARN  {w}")
        if errs:
            n_err += 1
            bad.append(f.name)
        if warns:
            n_warn += 1

    print(
        f"\nvalidated {len(files)} files: "
        f"{len(files) - n_err} clean, {n_err} with errors, {n_warn} with warnings"
    )
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
