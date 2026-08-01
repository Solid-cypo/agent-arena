#!/usr/bin/env python3
"""Finish remaining review_batch_30 gold imports (after partial apply)."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
SKILL = SCRIPTS.parent
SRC = SKILL / "approved_review_batch_30"
OUT = SKILL / "logs" / "review_manual" / "expert_gold_v1"
DECK_PATH = ROOT / "data" / "decks" / "starmie_froslass.csv"

sys.path[:0] = [str(SCRIPTS), str(ROOT)]

from arena.deck import load_deck_csv
from opening_cards import (
    CARD_NAMES,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    LILLIE,
    MEGA_STARMIE,
    POFFIN,
    STARYU,
    WATER_BASIC,
    name,
)
from opening_log_formatter import CARD_NAME_ZH, format_actions
from opening_state import OpeningGameState, Pokemon

ZH_TO_ID: dict[str, int] = {}
for cid, en in CARD_NAMES.items():
    zh = CARD_NAME_ZH.get(en, en)
    ZH_TO_ID.setdefault(zh, cid)
ZH_TO_ID["土龙节节（逃跑抽牌）"] = DUDUNSPARCE
ZH_TO_ID["土龙弟弟"] = DUNSPARCE_A


def zh(tok: str) -> int:
    t = tok.strip()
    if t in ZH_TO_ID:
        return ZH_TO_ID[t]
    t2 = re.sub(r"[（(].*?[)）]\s*$", "", t).strip()
    if t2 in ZH_TO_ID:
        return ZH_TO_ID[t2]
    for k, v in ZH_TO_ID.items():
        if k in t or t in k:
            return v
    raise KeyError(tok)


def find_src(seed: int) -> Path:
    return next(SRC.glob(f"*seed{seed}_*"))


def remain_deck(deck: list[int], used: list[int]) -> list[int]:
    rem = Counter(deck)
    for c in used:
        rem[c] -= 1
        if rem[c] < 0:
            raise ValueError(f"overused {c} ({name(c)})")
    out = []
    for c, n in rem.items():
        out.extend([c] * n)
    return out


def hand_zh(ids: list[int]) -> str:
    return ", ".join(CARD_NAME_ZH.get(CARD_NAMES[c], name(c)) for c in ids)


def board_lines(st: OpeningGameState) -> list[str]:
    lines = []
    if st.active:
        e = "、".join(CARD_NAME_ZH.get(CARD_NAMES[x], name(x)) for x in st.active.energies) or "无能量"
        lines.append(
            f"  Active: {CARD_NAME_ZH.get(CARD_NAMES[st.active.card_id], name(st.active.card_id))} [{e}]"
        )
    else:
        lines.append("  Active: （空）")
    if not st.bench:
        lines.append("  Bench: （空）")
    else:
        for i, p in enumerate(st.bench):
            e = "、".join(CARD_NAME_ZH.get(CARD_NAMES[x], name(x)) for x in p.energies) or "无能量"
            lines.append(
                f"  Bench[{i}]: {CARD_NAME_ZH.get(CARD_NAMES[p.card_id], name(p.card_id))} [{e}]"
            )
    return lines


def play_lillie(st: OpeningGameState) -> None:
    st.play_trainer(LILLIE, "PLAY Lillie (keep/use)")
    st.lillie_draw()


def set_header(text: str, status: str, note: str) -> str:
    text = re.sub(r"// expert_status=\w+", f"// expert_status={status}", text, count=1)
    text = re.sub(r"// 样本类型=.*", "// 样本类型=正面（专家意见已改）", text, count=1)
    text = re.sub(r"// 专家：.*", f"// 专家意见已落实: {note}", text, count=1)
    if status == "unreachable":
        text = re.sub(
            r"// 专家意见已落实:.*",
            f"// 专家意见不可达/驳回: {note}",
            text,
            count=1,
        )
    return text


def edit_34118(deck: list[int]) -> Path:
    src = find_src(34118)
    text = src.read_text(encoding="utf-8")
    text = text.replace(
        "  4. [放置] 替补席 ← 土龙弟弟\n"
        "  5. [备注] 本回合因手牌无水能量，跳过附着能量。\n"
        "  回合结束手牌:\n"
        "    土龙节节 ex, 瓦利的慈悲, 危险废墟, 交替, 莉莉艾, 土龙弟弟\n"
        "  回合结束场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 海星星 [无能量]\n"
        "  Bench[1]: 旋转罗盘 [无能量]\n"
        "  Bench[2]: 土龙弟弟 [无能量]\n",
        "  4. [放置] 替补席 ← 土龙弟弟\n"
        "  5. [放置] 替补席 ← 土龙弟弟\n"
        "  6. [备注] 本回合因手牌无水能量，跳过附着能量。\n"
        "  回合结束手牌:\n"
        "    土龙节节 ex, 瓦利的慈悲, 危险废墟, 交替, 莉莉艾\n"
        "  回合结束场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 海星星 [无能量]\n"
        "  Bench[1]: 旋转罗盘 [无能量]\n"
        "  Bench[2]: 土龙弟弟 [无能量]\n"
        "  Bench[3]: 土龙弟弟 [无能量]\n",
        1,
    )
    text = text.replace(
        "【My-T2】 路线: GREEDY-T2\n"
        "  回合开始手牌:\n"
        "    土龙节节 ex, 瓦利的慈悲, 危险废墟, 交替, 莉莉艾, 土龙弟弟\n"
        "  回合开始场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 海星星 [无能量]\n"
        "  Bench[1]: 旋转罗盘 [无能量]\n"
        "  Bench[2]: 土龙弟弟 [无能量]\n",
        "【My-T2】 路线: GREEDY-T2\n"
        "  回合开始手牌:\n"
        "    土龙节节 ex, 瓦利的慈悲, 危险废墟, 交替, 莉莉艾\n"
        "  回合开始场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 海星星 [无能量]\n"
        "  Bench[1]: 旋转罗盘 [无能量]\n"
        "  Bench[2]: 土龙弟弟 [无能量]\n"
        "  Bench[3]: 土龙弟弟 [无能量]\n",
        1,
    )
    hand_before = [zh(x) for x in ["土龙节节 ex", "瓦利的慈悲", "危险废墟", "交替", "莉莉艾"]]
    prizes = [
        zh(x)
        for x in [
            "Mega 大雪妖女 ex",
            "Mega 大雪妖女 ex",
            "含羞苞",
            "基本水能量",
            "萨瓦托",
            "海星星",
        ]
    ]
    board = [DUNSPARCE_A, STARYU, FAN_ROTOM, DUNSPARCE_A, DUNSPARCE_B]
    used = prizes + board + [WATER_BASIC, POFFIN] + hand_before
    remain = remain_deck(deck, used)
    top = [
        zh(x)
        for x in [
            "夜之伸展器",
            "基本恶能量",
            "宝可梦手环",
            "高级球",
            "老大的指令",
            "不公平的印章",
            "高级球",
            "莉莉艾",
            "Mega 大海星 ex",
            "土龙节节（逃跑抽牌）",
        ]
    ]
    ordered60 = (hand_before + remain + [0] * 60)[:60]
    st = OpeningGameState.from_ordered_deck(ordered60, going_first=True, seed=34118)
    st.hand = list(hand_before)
    st.prizes = [0] * 6
    rem2 = list(remain)
    top2 = []
    for c in top:
        if c in rem2:
            rem2.remove(c)
            top2.append(c)
    st.deck = top2 + rem2
    st.active = Pokemon(DUNSPARCE_A, 0)
    st.bench = [
        Pokemon(STARYU, 0),
        Pokemon(FAN_ROTOM, 0),
        Pokemon(DUNSPARCE_A, 0),
        Pokemon(DUNSPARCE_B, 0),
    ]
    st.bench[0].energies = [WATER_BASIC]
    st.log = []
    play_lillie(st)
    sn = zh("雪童子")
    if sn in st.hand:
        st.play_pokemon_to_bench(sn)
    if MEGA_STARMIE in st.hand:
        st.hand.remove(MEGA_STARMIE)
        for p in [st.active, *st.bench]:
            if p and p.card_id == STARYU:
                p.card_id = MEGA_STARMIE
                st._log("EVOLVE", f"{name(STARYU)} → {name(MEGA_STARMIE)}", MEGA_STARMIE)
                break
    idx = next((i for i, p in enumerate(st.bench) if p.card_id == MEGA_STARMIE), None)
    if idx is not None:
        old = st.active
        st.active = st.bench.pop(idx)
        if old:
            st.bench.append(old)
        st._log("RETREAT", f"Retreat → Active ← {name(st.active.card_id)}")
    formatted = format_actions(st.log)
    renum = [re.sub(r"^\s*\d+\.", f"  {i + 3}.", ln, count=1) for i, ln in enumerate(formatted)]
    m = re.search(
        r"(【My-T2】.*?本回合操作:\n  1\. \[抽牌\].*?\n  2\. \[贴能\].*?\n)(.*?)(\n  回合结束手牌:\n.*?)(?=\Z)",
        text,
        re.S,
    )
    if not m:
        raise ValueError("34118 T2 miss")
    rebuilt = (
        m.group(1)
        + "\n".join(renum)
        + f"\n  回合结束手牌:\n    {hand_zh(st.hand)}\n  回合结束场面:\n"
        + "\n".join(board_lines(st))
        + "\n"
    )
    text = text[: m.start()] + rebuilt + text[m.end() :]
    text = set_header(text, "edited", "T1手牌有土龙弟弟未放置 → T1放置第二张")
    out = OUT / "pack13_03_seed34118_edited_goal.log"
    out.write_text(text, encoding="utf-8")
    return out


def edit_36555() -> Path:
    src = find_src(36555)
    text = src.read_text(encoding="utf-8")
    m = re.search(
        r"(  \d+\. \[操作\] 伙伴糖果 → bench \['海星星', '旋转罗盘'\].*?\n(?:     .*\n)*)",
        text,
    )
    if not m:
        raise ValueError("36555 poffin miss")
    rest = text[m.end() :]
    nm = re.match(r"  (\d+)\.", rest)
    n = int(nm.group(1)) if nm else 6
    # Pull deck-top hint from earlier T1 draw if present
    fan = (
        f"  {n}. [特性] 旋转罗盘特性检索 ['土龙弟弟']\n"
        f"     检索: 土龙弟弟\n"
        f"  {n + 1}. [放置] 替补席 ← 土龙弟弟\n"
    )
    text = text[: m.end()] + fan + rest

    def renum_t1(s: str) -> str:
        m2 = re.search(r"(【My-T1】.*?本回合操作:\n)(.*?)(\n  回合结束手牌:)", s, re.S)
        if not m2:
            return s
        ops = m2.group(2)
        out_lines = []
        step = 0
        for ln in ops.splitlines():
            if re.match(r"\s*\d+\.\s*\[", ln):
                step += 1
                ln = re.sub(r"^\s*\d+\.", f"  {step}.", ln, count=1)
            out_lines.append(ln)
        return s[: m2.start()] + m2.group(1) + "\n".join(out_lines) + m2.group(3) + s[m2.end() :]

    text = renum_t1(text)
    # Add bench slot on T1 end + T2 start
    text = text.replace(
        "  Bench[2]: 旋转罗盘 [无能量]\n\n【My-T2】",
        "  Bench[2]: 旋转罗盘 [无能量]\n  Bench[3]: 土龙弟弟 [无能量]\n\n【My-T2】",
        1,
    )
    text = text.replace(
        "【My-T2】 路线: GREEDY-T2\n"
        "  回合开始手牌:\n"
        "    基本恶能量, 克里宾, Mega 大海星 ex, 基本水能量, 土龙节节（逃跑抽牌）, 土龙节节（逃跑抽牌）\n"
        "  回合开始场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 喵头目 ex [无能量]\n"
        "  Bench[1]: 海星星 [基本水能量]\n"
        "  Bench[2]: 旋转罗盘 [无能量]\n",
        "【My-T2】 路线: GREEDY-T2\n"
        "  回合开始手牌:\n"
        "    基本恶能量, 克里宾, Mega 大海星 ex, 基本水能量, 土龙节节（逃跑抽牌）, 土龙节节（逃跑抽牌）\n"
        "  回合开始场面:\n"
        "  Active: 土龙弟弟 [无能量]\n"
        "  Bench[0]: 喵头目 ex [无能量]\n"
        "  Bench[1]: 海星星 [基本水能量]\n"
        "  Bench[2]: 旋转罗盘 [无能量]\n"
        "  Bench[3]: 土龙弟弟 [无能量]\n",
        1,
    )
    text = set_header(text, "edited", "T1未使用旋转罗盘特性 → 补特性检索并放置土龙弟弟")
    out = OUT / "pack13_10_seed36555_edited_goal.log"
    out.write_text(text, encoding="utf-8")
    return out


def mark_unreachable(seed: int, idx: str, reason: str) -> Path:
    text = set_header(find_src(seed).read_text(encoding="utf-8"), "unreachable", reason)
    out = OUT / f"pack13_{idx}_seed{seed}_unreachable.log"
    out.write_text(text, encoding="utf-8")
    return out


def copy_approved(seed: int, idx: str) -> Path:
    text = find_src(seed).read_text(encoding="utf-8")
    out = OUT / f"pack13_{idx}_seed{seed}_approved_goal.log"
    out.write_text(text, encoding="utf-8")
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    deck = load_deck_csv(DECK_PATH)
    done = []
    done.append(("34118", edit_34118(deck)))
    done.append(("36555", edit_36555()))
    for seed, idx, reason in [
        (37264, "07", "旋转罗盘不在牌库/奖品，意见驳回"),
        (38400, "08", "PARTIAL: 可高级球找喵头目，但莉莉艾不在牌库；暂隔离"),
        (34849, "09", "PARTIAL: T2无莉莉艾；T1改线属偏好；暂隔离"),
        (36645, "11", "CORRECT但莉莉艾洗牌级联重写T2；本批隔离待专脚本"),
        (38272, "12", "CORRECT但糖果调度级联重写T1/T2；本批隔离待专脚本"),
        (38659, "13", "CORRECT但莉莉艾在逃跑前级联重写抽牌；本批隔离待专脚本"),
    ]:
        done.append((str(seed), mark_unreachable(seed, idx, reason)))
    plain = [
        36129,
        38211,
        34309,
        37914,
        35999,
        38761,
        38087,
        38021,
        37890,
        37613,
        37349,
        36827,
        35604,
        35267,
        35072,
        35012,
        34669,
    ]
    for i, seed in enumerate(plain, start=20):
        done.append((str(seed), copy_approved(seed, f"{i:02d}")))
    for seed, path in done:
        print(f"  seed={seed} → {path.name}")
    print("total", len(done))
    # also list already-done from first script
    print("all pack13:", len(list(OUT.glob("pack13_*"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
