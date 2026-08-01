#!/usr/bin/env python3
"""Batch33 v4 repair: restore backups, apply expert CORRECT with HARD coherence.

Uses log_coherence.sync_turn_starts + audit (empty = pass).
Does NOT ingest gold.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import re
import shutil
import sys
import tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/agent-arena")
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass"
PACK = SKILL / "logs" / "review_manual" / "approved_review_batch_33_il_fill"
BACKUP = PACK / "_pre_autofix_backup"
V2 = SKILL / "approved_review_batch_33_il_fill_v2"
MIRROR = SKILL / "approved_review_batch_33_il_fill"
V4 = SKILL / "approved_review_batch_33_il_fill_v4"
DATA = ROOT / "data" / "opening_sft"
CHECKLIST = V2 / "REVIEW_CHECKLIST.csv"

# log_coherence
_lc_spec = importlib.util.spec_from_file_location(
    "log_coherence",
    SKILL / "scripts" / "log_coherence.py",
)
_lc = importlib.util.module_from_spec(_lc_spec)
assert _lc_spec and _lc_spec.loader
_lc_spec.loader.exec_module(_lc)
sync_turn_starts = _lc.sync_turn_starts
audit = _lc.audit
extract_end_snapshot = _lc.extract_end_snapshot
extract_setup_after = _lc.extract_setup_after
extract_start_snapshot = _lc.extract_start_snapshot
is_placeholder_hand = _lc.is_placeholder_hand
format_board = _lc.format_board
norm_hand = _lc.norm_hand

# apply_review_batch33_consistent_edits helpers (no local sync/audit)
_ar_spec = importlib.util.spec_from_file_location(
    "apply_review_batch33",
    SKILL / "scripts" / "apply_review_batch33_consistent_edits.py",
)
_ar = importlib.util.module_from_spec(_ar_spec)
assert _ar_spec and _ar_spec.loader
_ar_spec.loader.exec_module(_ar)
set_header = _ar.set_header
replace_turn = _ar.replace_turn
replace_setup = _ar.replace_setup
renumber_ops = _ar.renumber_ops
BASE_REWRITERS = dict(_ar.REWRITERS)


# ---------- IO / helpers ----------

def load_checklist() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with CHECKLIST.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[int(r["seed"])] = r
    return out


def find_log(seed: int, root: Path = PACK) -> Path:
    ms = list(root.glob(f"*seed{seed}_*.log"))
    if not ms:
        raise FileNotFoundError(seed)
    return ms[0]


def restore_all() -> None:
    for bp in BACKUP.glob("*.log"):
        shutil.copy2(bp, PACK / bp.name)


def extract_turn(text: str, turn: str) -> str:
    m = re.search(rf"【{turn}】.*?(?=【My-T|\Z)", text, flags=re.S)
    return m.group(0) if m else ""


def extract_draw(block: str) -> str:
    m = re.search(r"  1\. \[抽牌\].*?\n(?:     .*\n)*", block)
    return m.group(0) if m else "  1. [抽牌] 抽到 （略）\n"


def extract_lillie_block(block: str) -> tuple[str, str | None]:
    """Return (ops lines incl. remark, 莉莉艾抽牌后手牌 or None)."""
    m = re.search(
        r"(  \d+\. \[操作\] 使用 莉莉艾[^\n]*\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[操作\] 莉莉艾：[^\n]*\n"
        r"(?:     .*\n)*"
        r"(?:  \d+\. \[备注\] 莉莉艾抽牌后手牌:[^\n]*\n)?)",
        block,
    )
    if not m:
        return "", None
    ops = m.group(1)
    hm = re.search(r"莉莉艾抽牌后手牌:\s*(.+)", ops)
    hand = hm.group(1).strip() if hm else None
    return ops, hand


def set_turn_end(block: str, hand: str, board: str) -> str:
    block = re.sub(
        r"  回合结束手牌:\n(?:    .+\n)+",
        f"  回合结束手牌:\n    {hand}\n",
        block,
        count=1,
    )
    block = re.sub(
        r"  回合结束场面:\n(?:  .+\n)+",
        f"  回合结束场面:\n{board.rstrip()}\n",
        block,
        count=1,
    )
    return block


def set_turn_start(block: str, hand: str, board: str) -> str:
    block = re.sub(
        r"  回合开始手牌:\n    .+\n",
        f"  回合开始手牌:\n    {hand}\n",
        block,
        count=1,
    )
    block = re.sub(
        r"  回合开始场面:\n(?:  .+\n)+  本回合操作:",
        f"  回合开始场面:\n{board.rstrip()}\n  本回合操作:",
        block,
        count=1,
    )
    return block


def finish(text: str) -> str:
    return sync_turn_starts(text)


PAD_FAN_CHAIN = (
    "  N. [操作] 使用宝可梦手环\n"
    "  N. [操作] 宝可梦手环 → 旋转罗盘\n"
    "     检索: 旋转罗盘\n"
    "  N. [放置] 替补席 ← 旋转罗盘\n"
    "  N. [特性] 旋转罗盘特性检索 ['土龙弟弟', '土龙弟弟']\n"
    "     检索: 土龙弟弟、土龙弟弟\n"
    "  N. [放置] 替补席 ← 土龙弟弟\n"
    "  N. [放置] 替补席 ← 土龙弟弟\n"
)


# ---------- v4 rewriters (override broken base) ----------

def rw_50443(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    old_t1 = extract_turn(text, "My-T1")
    draw = extract_draw(old_t1)
    _, lillie_hand = extract_lillie_block(old_t1)
    lillie_ops, _ = extract_lillie_block(old_t1)
    if not lillie_hand:
        lillie_hand = (
            "克里宾, 土龙节节（逃跑抽牌）, 愿增猿, Mega 大海星 ex, "
            "土龙弟弟, 老大的指令, 棱镜能量, 引火能量"
        )
    if not lillie_ops:
        lillie_ops = (
            "  N. [操作] 使用 莉莉艾 (keep/use)\n"
            "  N. [操作] 莉莉艾：手牌洗回牌库并洗切，抽 8 张\n"
            "     抽到: 克里宾、土龙节节（逃跑抽牌）、愿增猿、Mega 大海星 ex、"
            "土龙弟弟、老大的指令、棱镜能量、引火能量\n"
            f"  N. [备注] 莉莉艾抽牌后手牌: {lillie_hand}\n"
        )

    t1_board = format_board("海星星", ["旋转罗盘", "土龙弟弟", "土龙弟弟", "雪童子"])
    t1 = f"""【My-T1】 路线: PAD-T1
  回合开始手牌:
    雪童子, 高级球, 危险废墟, 宝可梦手环, 裁判, 莉莉艾
  回合开始场面:
  Active: 海星星 [无能量]
  Bench: （空）
  本回合操作:
{draw}  N. [操作] 使用高级球（fan）
  N. [操作] 使用高级球检索 旋转罗盘，丢弃 危险废墟、裁判
     检索: 旋转罗盘
  N. [放置] 替补席 ← 旋转罗盘
  N. [特性] 旋转罗盘特性检索 ['土龙弟弟', '土龙弟弟']
     检索: 土龙弟弟、土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [放置] 替补席 ← 雪童子
{lillie_ops}  N. [备注] 专家：高级球找旋转罗盘铺土龙再莉莉艾；不给海星星贴棱镜
  回合结束手牌:
    {lillie_hand}
  回合结束场面:
{t1_board.rstrip()}
"""
    text = replace_turn(text, "My-T1", t1)

    old_t2 = extract_turn(text, "My-T2")
    t2_draw = extract_draw(old_t2)
    t2_rest = re.sub(
        r"  \d+\. \[丢弃\] 非基础宝可梦无法保留棱镜能量.*\n",
        "",
        old_t2,
    )
    # rebuild T2 ops from backup pattern without prism discard
    t2_ops = re.search(r"本回合操作:\n(.*?)  回合结束", t2_rest, re.S)
    ops_body = t2_ops.group(1) if t2_ops else ""
    ops_body = re.sub(
        r"  \d+\. \[丢弃\] 非基础宝可梦无法保留棱镜能量.*\n",
        "",
        ops_body,
    )
    t2_end_board = format_board(
        "Mega 大海星 ex",
        ["雪童子", "土龙弟弟"],
        {"active": "基本水能量"},
    )
    t2_end_hand = (
        "愿增猿, 老大的指令, 引火能量, 基本恶能量, 伙伴糖果, 裁判, 土龙节节（逃跑抽牌）"
    )
    t2 = f"""【My-T2】 路线: GREEDY-T2
  回合开始手牌:
    PLACEHOLDER
  回合开始场面:
  PLACEHOLDER_BOARD
  本回合操作:
{t2_draw}{ops_body}  N. [备注] 专家：手牌 Mega 进化替补海星星；无棱镜丢弃
  回合结束手牌:
    {t2_end_hand}
  回合结束场面:
{t2_end_board.rstrip()}
"""
    text = replace_turn(text, "My-T2", t2)
    return finish(text)


def rw_51561(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    old = extract_turn(text, "My-T1")
    draw = extract_draw(old)
    lillie_ops, lillie_hand = extract_lillie_block(old)
    if not lillie_hand:
        raise ValueError("51561 missing Lillie hand in backup")

    setup = """【Setup】
  原型: A2
  操作:
  1. [布置] 战斗场 ← 土龙弟弟
  2. [布置] 替补席 ← 海星星
  3. [布置] 替补席 ← 旋转罗盘
  Setup 后手牌: 莉莉艾, Mega 大雪妖女 ex, 莉莉艾, 愿增猿
  Setup 后场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [无能量]
  Bench[1]: 旋转罗盘 [无能量]
"""
    t1_board = format_board(
        "土龙弟弟",
        ["旋转罗盘", "土龙弟弟", "土龙弟弟", "雪童子"],
    )
    t1 = f"""【My-T1】 路线: GREEDY-T1
  回合开始手牌:
    莉莉艾, Mega 大雪妖女 ex, 莉莉艾, 愿增猿
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [无能量]
  Bench[1]: 旋转罗盘 [无能量]
  本回合操作:
{draw}  N. [特性] 旋转罗盘特性检索 ['土龙弟弟', '土龙弟弟']
     检索: 土龙弟弟、土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [放置] 替补席 ← 雪童子
{lillie_ops}  N. [备注] 本回合因手牌无水能量，跳过附着能量。
  N. [备注] 专家：Setup 土龙前；Fan×2 后莉莉艾
  回合结束手牌:
    {lillie_hand}
  回合结束场面:
{t1_board.rstrip()}
"""
    text = replace_setup(text, setup)
    text = replace_turn(text, "My-T1", t1)

    old_t2 = extract_turn(text, "My-T2")
    t2 = old_t2
    t2 = t2.replace("使用希尔达（energy only）", "使用希尔达（mega+energy）")
    t2 = re.sub(
        r"使用希尔达检索 基本水能量\n",
        "使用希尔达检索 Mega 大海星 ex、基本水能量\n",
        t2,
    )
    t2 = re.sub(
        r"  \d+\. \[贴能\] 基本水能量 → 海星星（战斗场）\n",
        "  N. [贴能] 基本水能量 → 海星星（替补席）\n",
        t2,
        count=1,
    )
    # insert evolve+retreat before dudunsparce evolve if missing order
    if "Retreat → Active ← Mega" not in t2:
        t2 = re.sub(
            r"(  \d+\. \[进化\] 海星星 → Mega 大海星 ex\n)",
            r"\1  N. [撤退] Retreat → Active ← Mega 大海星 ex（土龙弟弟免费撤退）\n",
            t2,
            count=1,
        )
    t2_end_board = format_board(
        "Mega 大海星 ex",
        ["旋转罗盘", "雪童子", "土龙节节（逃跑抽牌）"],
        {"active": "基本水能量"},
    )
    t2_end_hand = (
        "不公平的印章, 夜之伸展器, Mega 大雪妖女 ex, 老大的指令, 危险废墟, "
        "引火能量, 雪童子, 莉莉艾, 土龙节节（逃跑抽牌）"
    )
    t2 = set_turn_end(t2, t2_end_hand, t2_end_board)
    text = replace_turn(text, "My-T2", t2)
    return finish(text)


def rw_55904(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    setup = """【Setup】
  原型: S1
  操作:
  1. [布置] 战斗场 ← 土龙弟弟
  2. [布置] 替补席 ← 海星星
  Setup 后手牌: 老大的指令, 棱镜能量, 高级球, 交替, 伙伴糖果
  Setup 后场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [无能量]
"""
    text = replace_setup(text, setup)

    old_t1 = extract_turn(text, "My-T1")
    t1 = f"""【My-T1】 路线: GREEDY-T1
  回合开始手牌:
    老大的指令, 棱镜能量, 高级球, 交替, 伙伴糖果
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [无能量]
  本回合操作:
  1. [操作] 使用高级球（mega）
  2. [操作] 使用高级球检索 Mega 大海星 ex，丢弃 老大的指令、伙伴糖果
     检索: Mega 大海星 ex
  3. [贴能] 棱镜能量 → 海星星（替补席）
  4. [备注] 专家：Setup 土龙前；棱镜贴替补海星星
  回合结束手牌:
    交替, Mega 大海星 ex
  回合结束场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [棱镜能量]
"""
    text = replace_turn(text, "My-T1", t1)

    old_t2 = extract_turn(text, "My-T2")
    t2_draw = extract_draw(old_t2)
    t2 = f"""【My-T2】 路线: GREEDY-T2
  回合开始手牌:
    交替, Mega 大海星 ex
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [棱镜能量]
  本回合操作:
{t2_draw}  N. [丢弃] 非基础宝可梦无法保留棱镜能量，从进化前海星星丢弃棱镜能量
  N. [进化] 海星星 → Mega 大海星 ex
  N. [撤退] Retreat → Active ← Mega 大海星 ex（土龙弟弟免费撤退）
  N. [备注] 专家：T2 进化后免费撤退上 Mega
  回合结束手牌:
    交替, 海星星
  回合结束场面:
  Active: Mega 大海星 ex [无能量]
  Bench[0]: 土龙弟弟 [无能量]
"""
    text = replace_turn(text, "My-T2", t2)
    # T3 unchanged from backup — sync_turn_starts will wire boundaries
    return finish(text)


def rw_pad_fan_before_lillie(text: str, note: str, *, keep_after_lillie: str | None = None) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    body = extract_turn(text, "My-T1")
    draw = extract_draw(body)
    lillie_ops, lillie_hand = extract_lillie_block(body)
    if not lillie_hand:
        raise ValueError("missing Lillie hand")

    # remove old pad→海星星 or pad block
    body = re.sub(
        r"  \d+\. \[操作\] 使用宝可梦手环\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[操作\] 宝可梦手环 → 海星星\n"
        r"(?:     .*\n)*",
        "",
        body,
        count=1,
    )
    # remove post-lillie dunsparce place if moved before lillie
    body = re.sub(
        r"  \d+\. \[放置\] 替补席 ← 土龙弟弟\n"
        r"  \d+\. \[放置\] 替补席 ← 土龙弟弟\n",
        "",
        body,
        count=1,
    )

    insert_at = re.search(r"  \d+\. \[操作\] 使用 莉莉艾", body)
    prefix = body[: insert_at.start()] if insert_at else draw
    suffix_ops = ""
    if keep_after_lillie:
        suffix_ops = keep_after_lillie

    # bench composition after pad_fan + optional extras
    bench = ["旋转罗盘", "土龙弟弟", "土龙弟弟"]
    active_e = "无能量"
    active = "海星星"
    extra_ops = ""
    end_hand = lillie_hand

    if "基本水能量 → 海星星（战斗场）" in body:
        extra_ops = "  N. [贴能] 基本水能量 → 海星星（战斗场）\n"
        active_e = "基本水能量"
    if "替补席 ← 雪童子" in body and "放置" in prefix:
        bench = ["雪童子", "旋转罗盘", "土龙弟弟", "土龙弟弟"]
    elif "放置] 替补席 ← 雪童子" in body:
        extra_ops = "  N. [放置] 替补席 ← 雪童子\n" + extra_ops
        bench = ["雪童子", "旋转罗盘", "土龙弟弟", "土龙弟弟"]

    if suffix_ops and "高级球检索 Mega" in suffix_ops:
        # UB after lillie: end hand from backup end if present
        em = re.search(r"回合结束手牌:\n    (.+)\n", body)
        if em:
            end_hand = em.group(1).strip()

    sh = re.search(r"回合开始手牌:\n    (.+)\n", body)
    start_hand = sh.group(1).strip() if sh else ""

    t1 = f"""【My-T1】 路线: PAD-T1
  回合开始手牌:
    {start_hand}
  回合开始场面:
  Active: 海星星 [无能量]
  Bench: （空）
  本回合操作:
{draw}{PAD_FAN_CHAIN}{extra_ops}{lillie_ops}{suffix_ops}  N. [备注] 专家：莉莉艾前 pad→fan→call→place 土龙弟弟
  回合结束手牌:
    {end_hand}
  回合结束场面:
{format_board(active, bench, {'active': active_e}).rstrip()}
"""
    return finish(replace_turn(text, "My-T1", t1))


def rw_53697(text: str, note: str) -> str:
    after = (
        "  N. [操作] 使用高级球（mega）\n"
        "  N. [操作] 使用高级球检索 Mega 大海星 ex，丢弃 不公平的印章、夜之伸展器\n"
        "     检索: Mega 大海星 ex\n"
    )
    return rw_pad_fan_before_lillie(text, note, keep_after_lillie=after)


def rw_54733(text: str, note: str) -> str:
    after = (
        "  N. [操作] 使用高级球（mega）\n"
        "  N. [操作] 使用高级球检索 Mega 大海星 ex，丢弃 危险废墟、宝可梦手环\n"
        "     检索: Mega 大海星 ex\n"
    )
    return rw_pad_fan_before_lillie(text, note, keep_after_lillie=after)


def rw_54747(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    body = extract_turn(text, "My-T1")
    draw = extract_draw(body)
    lillie_ops, lillie_hand = extract_lillie_block(body)
    end_hand = "高级球, 交替, 希尔达, 莉莉艾, 土龙节节（逃跑抽牌）, 雪妖女"
    t1 = f"""【My-T1】 路线: GREEDY-T1
  回合开始手牌:
    莉莉艾, 瓦利的慈悲, 宝可梦手环, 莉莉艾, 危险废墟, 雪童子
  回合开始场面:
  Active: 海星星 [无能量]
  Bench: （空）
  本回合操作:
{draw}  N. [放置] 替补席 ← 雪童子
{PAD_FAN_CHAIN}{lillie_ops}  N. [备注] 本回合因手牌无水能量，跳过附着能量。
  N. [备注] 专家：莉莉艾前 pad→fan→call→place
  回合结束手牌:
    {end_hand}
  回合结束场面:
{format_board('海星星', ['雪童子', '旋转罗盘', '土龙弟弟', '土龙弟弟']).rstrip()}
"""
    return finish(replace_turn(text, "My-T1", t1))


def rw_53541(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    body = extract_turn(text, "My-T1")
    draw = extract_draw(body)
    # pre-Lillie end hand: after UB, before Lillie + pad
    end_hand = "棱镜能量, 莉莉艾, 高级球, Mega 大海星 ex"
    end_board = format_board(
        "土龙弟弟",
        ["海星星", "旋转罗盘", "土龙弟弟", "土龙弟弟", "雪童子"],
    )
    # rebuild T1 without Lillie and post-lillie pad
    ops = re.search(r"本回合操作:\n(.*?)  回合结束", body, re.S)
    ops_text = ops.group(1) if ops else ""
    ops_text = re.sub(
        r"  \d+\. \[操作\] 使用 莉莉艾.*\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[操作\] 莉莉艾：.*\n"
        r"(?:     .*\n)*"
        r"(?:  \d+\. \[备注\] 莉莉艾抽牌后手牌:.*\n)?"
        r"(?:  \d+\. \[操作\] 使用宝可梦手环\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[操作\] 宝可梦手环 → .+\n"
        r"(?:     .*\n)*)?",
        "  N. [备注] 专家：高级球后不打莉莉艾；手牌=UB 后状态\n",
        ops_text,
        count=1,
    )
    t1 = f"""【My-T1】 路线: GREEDY-T1
  回合开始手牌:
    愿增猿, 基本恶能量, 棱镜能量, 莉莉艾, 基本恶能量, 高级球
  回合开始场面:
  Active: 雪童子 [无能量]
  Bench: （空）
  本回合操作:
{ops_text}  N. [备注] 专家：移除莉莉艾后回合结束手牌与 UB 后一致
  回合结束手牌:
    {end_hand}
  回合结束场面:
{end_board.rstrip()}
"""
    text = replace_turn(text, "My-T1", t1)
    return finish(text)


def rw_55388(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    old_t2 = extract_turn(text, "My-T2")
    draw = extract_draw(old_t2)
    lillie_ops, lillie_hand = extract_lillie_block(old_t2)
    if not lillie_hand:
        lillie_hand = "喵头目 ex, 愿增猿, 克里宾, 旋转罗盘, Mega 大海星 ex, 基本水能量, 含羞苞, 基本恶能量"
    end_hand = lillie_hand  # evolve/retreat only; no placements
    t2 = f"""【My-T2】 路线: GREEDY-T2
  回合开始手牌:
    基本恶能量, 莉莉艾
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [基本水能量]
  本回合操作:
{draw}{lillie_ops}  N. [进化] 海星星 → Mega 大海星 ex
  N. [撤退] Retreat → Active ← Mega 大海星 ex（土龙弟弟免费撤退）
  N. [备注] 专家：禁止 T2 再放置旋转罗盘；禁止给免费土龙贴能
  回合结束手牌:
    {end_hand}
  回合结束场面:
{format_board('Mega 大海星 ex', ['土龙弟弟'], {'active': '基本水能量'}).rstrip()}
"""
    return finish(replace_turn(text, "My-T2", t2))


def rw_55499(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    body = extract_turn(text, "My-T1")
    draw = extract_draw(body)
    t1 = f"""【My-T1】 路线: R1-T1
  回合开始手牌:
    伙伴糖果, 土龙节节（逃跑抽牌）, 希尔达, 克里宾, 莉莉艾, Mega 大雪妖女 ex
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench: （空）
  本回合操作:
{draw}  N. [操作] 使用伙伴糖果
  N. [操作] 伙伴糖果 → bench ['海星星', '旋转罗盘']
     检索: 海星星、旋转罗盘
  N. [特性] 旋转罗盘特性检索 ['土龙弟弟', '土龙弟弟']
     检索: 土龙弟弟、土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [放置] 替补席 ← 土龙弟弟
  N. [操作] 使用希尔达（mega+energy）
  N. [操作] 使用希尔达检索 Mega 大海星 ex、基本水能量
     检索: Mega 大海星 ex、基本水能量
  N. [贴能] 基本水能量 → 海星星（替补席）
  N. [备注] 专家：伙伴糖果找海星星+旋转罗盘，保留高级球
  回合结束手牌:
    土龙节节（逃跑抽牌）, 克里宾, 莉莉艾, Mega 大海星 ex
  回合结束场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 海星星 [基本水能量]
  Bench[1]: 旋转罗盘 [无能量]
  Bench[2]: 土龙弟弟 [无能量]
  Bench[3]: 土龙弟弟 [无能量]
"""
    text = replace_turn(text, "My-T1", t1)

    old_t2 = extract_turn(text, "My-T2")
    t2 = old_t2
    t2 = re.sub(
        r"  \d+\. \[贴能\] 克里宾直接贴 基本恶能量 → 土龙弟弟（战斗场）\n"
        r"  \d+\. \[操作\] 使用克里宾 → 基本水能量、attach 基本恶能量\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[丢弃\] Retreat cost → discard 基本恶能量\n",
        "  N. [贴能] 克里宾直接贴 基本恶能量 → Mega 大海星 ex（替补席）\n"
        "  N. [操作] 使用克里宾 → 基本水能量、attach 基本恶能量\n"
        "     检索: 基本水能量、基本恶能量\n",
        t2,
        count=1,
    )
    t2 = re.sub(
        r"  \d+\. \[撤退\] Retreat → Active ← Mega 大海星 ex\n",
        "  N. [撤退] Retreat → Active ← Mega 大海星 ex（土龙弟弟免费撤退；恶能在 Mega）\n",
        t2,
        count=1,
    )
    t2_end_board = format_board("Mega 大海星 ex", ["土龙弟弟"], {"active": "基本水能量", "b0": "无能量"})
    t2 = set_turn_end(
        t2,
        "莉莉艾, 基本水能量, 土龙节节（逃跑抽牌）, 土龙节节（逃跑抽牌）, 不公平的印章",
        t2_end_board,
    )
    return finish(replace_turn(text, "My-T2", t2))


def rw_51432(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    old_t2 = extract_turn(text, "My-T2")
    draw = extract_draw(old_t2)
    sh = re.search(r"回合开始手牌:\n    (.+)\n", old_t2)
    sb = re.search(r"回合开始场面:\n((?:  .+\n)+)  本回合操作:", old_t2)
    start_hand = sh.group(1) if sh else "基本水能量, 土龙节节（逃跑抽牌）, 危险废墟, 莉莉艾"
    start_board = sb.group(1) if sb else (
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 旋转罗盘 [无能量]\n"
        "  Bench[1]: 土龙弟弟 [无能量]\n"
        "  Bench[2]: 海星星 [无能量]\n"
    )
    lillie_ops, lillie_hand = extract_lillie_block(old_t2)
    if not lillie_ops:
        lillie_ops = (
            "  N. [操作] 使用 莉莉艾 (keep/use)\n"
            "  N. [操作] 莉莉艾：手牌洗回牌库并洗切，抽 8 张\n"
            "  N. [备注] 莉莉艾抽牌后手牌: （按引擎）\n"
        )
        lillie_hand = "莉莉艾, 愿增猿, 夜之伸展器, Mega 大海星 ex"
    run_block = re.search(
        r"  \d+\. \[进化\] 土龙弟弟 → 土龙节节（逃跑抽牌）\n"
        r"  \d+\. \[特性\] 土龙节节特性→逃跑抽三张.*\n"
        r"(?:     .*\n)*"
        r"(?:  \d+\. \[备注\] 土龙节节特性后手牌:.*\n)?",
        old_t2,
        re.S,
    )
    run = run_block.group(0) if run_block else (
        "  N. [特性] 土龙节节特性→逃跑抽三张\n"
        "     抽到: 高级球、夜之伸展器、伙伴糖果\n"
    )
    end_board = format_board(
        "Mega 大海星 ex",
        ["旋转罗盘", "土龙弟弟"],
        {"active": "基本水能量"},
    )
    end_hand = "莉莉艾, 愿增猿, 夜之伸展器"
    t2 = f"""【My-T2】 路线: GREEDY-T2
  回合开始手牌:
    {start_hand}
  回合开始场面:
{start_board}  本回合操作:
{draw}  N. [进化] 土龙弟弟 → 土龙节节（逃跑抽牌）
  N. [贴能] 基本水能量 → 海星星（替补席）
{lillie_ops}{run}  N. [操作] 使用高级球（mega）
  N. [操作] 使用高级球检索 Mega 大海星 ex，丢弃 危险废墟、伙伴糖果
     检索: Mega 大海星 ex
  N. [进化] 海星星 → Mega 大海星 ex
  N. [撤退] Retreat → Active ← Mega 大海星 ex
  N. [备注] 专家：先进化土龙节节贴水，莉莉艾，再逃跑抽牌
  回合结束手牌:
    {end_hand}
  回合结束场面:
{end_board.rstrip()}
"""
    return finish(replace_turn(text, "My-T2", t2))


def rw_51578(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    text = re.sub(
        r"旋转罗盘特性检索 \['土龙弟弟'\]",
        "旋转罗盘特性检索 ['土龙弟弟', '土龙弟弟']",
        text,
        count=1,
    )
    old_t3 = extract_turn(text, "My-T3")
    if not old_t3:
        return finish(text)
    sh = re.search(r"回合开始手牌:\n    (.+)\n", old_t3)
    draw = extract_draw(old_t3)
    start_hand = sh.group(1) if sh else ""
    end_hand = ", ".join(
        c for c in norm_hand(start_hand) if c not in {"萨瓦托", "土龙弟弟"}
    )
    end_board = format_board(
        "Mega 大海星 ex",
        ["雪童子", "旋转罗盘", "土龙弟弟", "土龙弟弟"],
        {"active": "基本水能量"},
    )
    t3 = f"""【My-T3】 路线: GREEDY-T2
  回合开始手牌:
    {start_hand}
  回合开始场面:
  Active: 土龙弟弟 [无能量]
  Bench[0]: 雪童子 [无能量]
  Bench[1]: 海星星 [基本水能量]
  Bench[2]: 旋转罗盘 [无能量]
  本回合操作:
{draw}  N. [操作] 使用 萨瓦托
  N. [进化] 萨瓦托进化：海星星 → Mega 大海星 ex
  N. [撤退] Retreat → Active ← Mega 大海星 ex
  N. [备注] 专家：删除给免费土龙贴恶能；萨瓦托进化后直接撤上 Mega
  回合结束手牌:
    {end_hand}
  回合结束场面:
{end_board.rstrip()}
"""
    return finish(replace_turn(text, "My-T3", t3))


def rw_55767(text: str, note: str) -> str:
    text = set_header(text, status="edited", opinion=f"CORRECT — {note}")
    body = extract_turn(text, "My-T1")
    draw = extract_draw(body)
    body = re.sub(
        r"  \d+\. \[操作\] 使用 莉莉艾.*\n"
        r"(?:     .*\n)*"
        r"  \d+\. \[操作\] 莉莉艾：.*\n"
        r"(?:     .*\n)*"
        r"(?:  \d+\. \[备注\] 莉莉艾抽牌后手牌:.*\n)?",
        "",
        body,
        count=1,
    )
    body = re.sub(
        r"  \d+\. \[贴能\] 引火能量 → 含羞苞（战斗场）\n"
        r"  \d+\. \[丢弃\] Retreat cost → discard 引火能量\n"
        r"  \d+\. \[撤退\] Retreat → Active ← 土龙弟弟\n",
        "  N. [操作] 使用 交替\n"
        "  N. [撤退] Retreat → Active ← 土龙弟弟\n",
        body,
        count=1,
    )
    # fix UB discards to cards actually in hand (no Lillie draw)
    body = re.sub(
        r"使用高级球检索 Mega 大海星 ex，丢弃 危险废墟、宝可梦手环\n",
        "使用高级球检索 Mega 大海星 ex，丢弃 夜之伸展器、高级球\n",
        body,
        count=1,
    )
    end_hand = "莉莉艾, 莉莉艾, 希尔达, 基本恶能量, 基本水能量, Mega 大海星 ex"
    end_board = format_board(
        "土龙弟弟",
        ["海星星", "旋转罗盘", "含羞苞", "土龙弟弟"],
    )
    ops = re.search(r"本回合操作:\n(.*?)  回合结束", body, re.S)
    ops_text = renumber_ops(ops.group(1)) if ops else ""
    t1 = f"""【My-T1】 路线: FAN-T1
  回合开始手牌:
    莉莉艾, 伙伴糖果, 莉莉艾, Mega 大海星 ex, 夜之伸展器, 交替
  回合开始场面:
  Active: 含羞苞 [无能量]
  Bench: （空）
  本回合操作:
{ops_text}  N. [备注] 专家：手牌有 Mega 不打莉莉艾；用交替撤退
  回合结束手牌:
    {end_hand}
  回合结束场面:
{end_board.rstrip()}
"""
    return finish(replace_turn(text, "My-T1", t1))


def wrap_base(fn):
    def _w(text: str, note: str) -> str:
        return finish(fn(text, note))

    return _w


REWRITERS = {k: wrap_base(v) for k, v in BASE_REWRITERS.items()}
REWRITERS.update(
    {
        50443: rw_50443,
        51561: rw_51561,
        55904: rw_55904,
        53697: rw_53697,
        54733: rw_54733,
        54747: rw_54747,
        53541: rw_53541,
        55388: rw_55388,
        55499: rw_55499,
        51432: rw_51432,
        51578: rw_51578,
        55767: rw_55767,
    }
)


def save_all(seed: int, text: str, filename: str) -> None:
    for dest in (PACK, V2, MIRROR, V4):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / filename).write_text(text, encoding="utf-8")


def main() -> int:
    cl = load_checklist()
    restore_all()

    if V4.exists():
        shutil.rmtree(V4)
    V4.mkdir(parents=True)

    results: list[dict] = []
    for seed, meta in sorted(cl.items()):
        bp = find_log(seed, BACKUP)
        text = bp.read_text(encoding="utf-8")
        verdict = meta["expert_verdict"]
        note = meta["expert_note"]
        filename = bp.name

        try:
            if verdict == "KEEP":
                text = set_header(text, status="approved", opinion=f"KEEP — {note}")
                text = finish(text)
                errs = audit(text)
                action = "KEEP"
                if errs:
                    action = "FAIL"
            else:
                fn = REWRITERS.get(seed)
                if not fn:
                    text = set_header(
                        text, status="edited", opinion=f"CORRECT pending — {note}"
                    )
                    text = finish(text)
                    errs = audit(text)
                    action = "FAIL" if errs else "STAMP_ONLY"
                    if action == "STAMP_ONLY":
                        errs = ["no_rewriter"]
                else:
                    text = fn(text, note)
                    errs = audit(text)
                    action = "REWRITE" if not errs else "FAIL"

            if action != "FAIL":
                save_all(seed, text, filename)
            else:
                # still write FAIL attempt to v4 only for inspection
                (V4 / filename).write_text(text, encoding="utf-8")

            results.append({"seed": seed, "action": action, "errors": errs})
            print(f"{seed}: {action} errs={errs or 'ok'}")
        except Exception as e:
            results.append({"seed": seed, "action": "FAIL", "errors": [str(e)]})
            print(f"{seed}: FAIL {e}")

    audit_failed = [r for r in results if r["errors"] or r["action"] == "FAIL"]
    counts = Counter(r["action"] for r in results)

    # checklist update
    rows = list(csv.DictReader(CHECKLIST.open(encoding="utf-8")))
    by = {int(r["seed"]): r for r in results}
    for r in rows:
        info = by.get(int(r["seed"]), {})
        r["rewrite_action"] = info.get("action", "")
        r["audit_errors"] = "|".join(info.get("errors") or [])
    fields = list(rows[0].keys())
    if "audit_errors" not in fields:
        fields.append("audit_errors")
    for dest in (V4, V2, PACK, MIRROR):
        with (dest / "REVIEW_CHECKLIST.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    report = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "counts": dict(counts),
        "audit_failed": len(audit_failed),
        "results": results,
    }
    report_path = DATA / "batch33_v4_repair_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (V4 / "repair_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    readme = f"""# review_batch_33_il_fill_v4 — HARD 一致性修复

时间：{report['ts']}

## 规则
- **仅当 audit_failed==0 才可发货**；本脚本已尽力修复，请核对 repair_report.json
- **在用户明确同意前禁止 ingest 金标**
- 自 `_pre_autofix_backup` 恢复后，CORRECT 整段重写 + `log_coherence.sync_turn_starts` + `audit`

## 机器结果
- KEEP: {counts.get('KEEP', 0)}
- REWRITE: {counts.get('REWRITE', 0)}
- FAIL: {counts.get('FAIL', 0)}
- audit_failed: {len(audit_failed)}
"""
    (V4 / "README_专家审阅.md").write_text(readme, encoding="utf-8")

    tar_path = DATA / "expert_review_pack_review_batch_33_il_fill_v4.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for p in sorted(V4.iterdir()):
            if p.is_file():
                tar.add(p, arcname=f"approved_review_batch_33_il_fill_v4/{p.name}")

    print("TAR", tar_path)
    print("summary", dict(counts))
    print("audit_failed", len(audit_failed))
    for r in audit_failed:
        print(" ", r)
    return 1 if audit_failed else 0


if __name__ == "__main__":
    sys.exit(main())
