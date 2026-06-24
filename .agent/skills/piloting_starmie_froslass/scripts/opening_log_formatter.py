#!/usr/bin/env python3
"""Log Formatter: dedupe skips, localize actions, strip planner debug noise."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opening_state import Action

# English card name → 中文（长名优先）
CARD_NAME_ZH: dict[str, str] = {
    "Dudunsparce (Run Away Draw)": "土龙节节（逃跑抽牌）",
    "Mega Starmie ex": "Mega 大海星 ex",
    "Mega Froslass ex": "Mega 大雪妖女 ex",
    "Boss's Orders": "老大的指令",
    "Wally's Compassion": "瓦利的慈悲",
    "Night Stretcher": "夜之伸展器",
    "Unfair Stamp": "不公平的印章",
    "Prism Energy": "棱镜能量",
    "Ignition Energy": "引火能量",
    "Darkness Energy": "基本恶能量",
    "Water Energy": "基本水能量",
    "Ultra Ball": "高级球",
    "Poké Pad": "宝可梦手环",
    "Fan Rotom": "旋转罗盘",
    "Risky Ruins": "危险废墟",
    "Meowth ex": "喵头目 ex",
    "Dudunsparce ex": "土龙节节 ex",
    "Munkidori": "愿增猿",
    "Dunsparce": "土龙弟弟",
    "Salvatore": "萨瓦托",
    "Froslass": "雪妖女",
    "Staryu": "海星星",
    "Snorunt": "雪童子",
    "Crispin": "克里宾",
    "Switch": "交替",
    "Poffin": "伙伴糖果",
    "Budew": "含羞苞",
    "Hilda": "希尔达",
    "Lillie": "莉莉艾",
    "Judge": "裁判",
}

POKEMON_HINT_ZH: dict[str, str] = {
    "staryu": "海星星",
    "meowth": "喵头目 ex",
    "mega": "Mega 大海星 ex",
    "fan": "旋转罗盘",
}

_NAME_ORDER = sorted(CARD_NAME_ZH.keys(), key=len, reverse=True)


def _hint_zh(hint: str) -> str:
    return POKEMON_HINT_ZH.get(hint.lower(), card_names_zh(hint))

KIND_ZH: dict[str, str] = {
    "SETUP_ACTIVE": "布置",
    "SETUP_BENCH": "布置",
    "DRAW": "抽牌",
    "PLAY_POKEMON": "放置",
    "PLAY_TRAINER": "操作",
    "ATTACH": "贴能",
    "ABILITY_FAN_CALL": "特性",
    "ABILITY_LAST_DITCH": "特性",
    "EVOLVE": "进化",
    "SWITCH": "交替",
    "RETREAT": "撤退",
    "DISCARD": "丢弃",
    "NOTE": "备注",
}

# Rule 3: planner / search debug — drop from expert-facing logs
DEBUG_DETAIL_RE = re.compile(
    r"(?:^|\s)(?:gaps=|score=|miss=|Route=.*score=|Archetype=)",
    re.IGNORECASE,
)

# Rule 1: skip/blocked notes — dedupe key → 中文单行
SKIP_NOTE_ZH: dict[str, str] = {
    "ATTACH skipped: no water in hand": "本回合因手牌无水能量，跳过附着能量。",
    "Switch unavailable — cannot promote Mega to Active (E-SW-1)": "无法将超级进化宝可梦换上战斗场（手牌无交替）。",
    "EVOLVE failed: no mega in hand": "无法进化：手牌无 Mega 大海星 ex。",
    "Last-Ditch Catch: no Supporter found in deck": "绝境抓：牌库中未找到支援者。",
    "Crispin: no Basic Energy in deck": "克里宾：牌库中无基本能量。",
}

SKIP_NOTE_PREFIX_RE = re.compile(
    r"^(?:ATTACH skipped|Switch unavailable|EVOLVE blocked|EVOLVE failed|"
    r"Salvatore blocked|Poké Pad blocked|Retreat blocked|Crispin:|Last-Ditch Catch:)",
    re.IGNORECASE,
)

_DISC_RE = re.compile(r",?\s*disc\s+\[(.+?)\]", re.IGNORECASE)
_PLAY_RE = re.compile(r"^PLAY\s+(.+)$", re.IGNORECASE)


def card_names_zh(text: str) -> str:
    out = text
    for en in _NAME_ORDER:
        out = out.replace(en, CARD_NAME_ZH[en])
    return out


def is_debug_detail(detail: str) -> bool:
    return bool(DEBUG_DETAIL_RE.search(detail))


def _skip_dedupe_key(detail: str) -> str | None:
    if detail in SKIP_NOTE_ZH:
        return detail
    if SKIP_NOTE_PREFIX_RE.match(detail):
        return detail.split(":", 1)[0] if ":" in detail else detail
    if "blocked" in detail.lower() or "skipped" in detail.lower():
        return detail
    return None


def localize_detail(detail: str) -> str:
    d = detail
    if d in SKIP_NOTE_ZH:
        return SKIP_NOTE_ZH[d]

    m = re.match(r"^Draw\s+(.+)$", d)
    if m:
        return f"抽到 {card_names_zh(m.group(1))}"

    m = re.match(r"^Active ←\s*(.+)$", d)
    if m:
        return f"战斗场 ← {card_names_zh(m.group(1))}"

    m = re.match(r"^Bench ←\s*(.+)$", d)
    if m:
        return f"替补席 ← {card_names_zh(m.group(1))}"

    m = re.match(
        r"^(.+?) → (.+?) on (active|bench)$",
        d,
        re.IGNORECASE,
    )
    if m and "attach" not in m.group(1).lower():
        energy, target, zone = m.groups()
        zone_zh = "战斗场" if zone.lower() == "active" else "替补席"
        return f"{card_names_zh(energy)} → {card_names_zh(target)}（{zone_zh}）"

    m = re.match(r"^Crispin attach (.+?) → (.+?) on (active|bench)$", d, re.IGNORECASE)
    if m:
        energy, target, zone = m.groups()
        zone_zh = "战斗场" if zone.lower() == "active" else "替补席"
        return f"克里宾直接贴 {card_names_zh(energy)} → {card_names_zh(target)}（{zone_zh}）"

    m = re.match(r"^Ultra Ball → (.+?), disc \[(.+?)\]$", d)
    if m:
        target, disc = m.groups()
        cards = [c.strip().strip("'\"") for c in disc.split(",")]
        disc_zh = "、".join(card_names_zh(c) for c in cards)
        return f"使用高级球检索 {card_names_zh(target)}，丢弃 {disc_zh}"

    def _replace_disc(match: re.Match[str]) -> str:
        inner = match.group(1)
        cards = [c.strip().strip("'\"") for c in inner.split(",")]
        return f"，丢弃 {'、'.join(card_names_zh(c) for c in cards)}"

    d = _DISC_RE.sub(_replace_disc, d)

    m = re.match(r"^Hilda → \[(.+?)\]$", d)
    if m:
        parts = [p.strip().strip("'\"") for p in m.group(1).split(",")]
        return f"使用希尔达检索 {'、'.join(card_names_zh(p) for p in parts)}"

    m = re.match(r"^(.+?) → \[(.+?)\]$", d.replace("'", ""))
    if "Fan Call" in d:
        return card_names_zh(d.replace("Fan Call →", "旋转罗盘特性检索"))

    m = re.match(r"^Last-Ditch Catch → (.+)$", d)
    if m:
        return f"绝境抓 → {card_names_zh(m.group(1))}"

    m = re.match(r"^Salvatore: (.+?) → (.+)$", d)
    if m:
        return f"萨瓦托进化：{card_names_zh(m.group(1))} → {card_names_zh(m.group(2))}"

    m = re.match(r"^(.+?) → (.+)$", d)
    if m and "Crispin" not in m.group(1) and "Hilda" not in m.group(1):
        a, b = m.groups()
        if " → " in d and not d.startswith("PLAY"):
            return f"{card_names_zh(a)} → {card_names_zh(b)}"

    m = re.match(r"^Retreat cost → discard (.+)$", d)
    if m:
        return f"支付撤退费用，丢弃 {card_names_zh(m.group(1))}"

    m = re.match(r"^Prism discarded from (.+?) \(non-Basic\)$", d)
    if m:
        return f"非基础宝可梦无法保留棱镜能量，从 {card_names_zh(m.group(1))} 丢弃棱镜能量"

    m = re.match(r"^Retreat → Active ← (.+)$", d)
    if m:
        return f"撤退后战斗场 ← {card_names_zh(m.group(1))}"

    m = re.match(r"^Lillie draw (\d+) \(no shuffle\)$", d)
    if m:
        return f"莉莉艾抽 {m.group(1)} 张（不洗切）"

    m = re.match(r"^Poké Pad → (.+)$", d)
    if m:
        return f"使用宝可梦手环检索 {card_names_zh(m.group(1))}"

    m = re.match(r"^Crispin → \[(.+?)\]$", d)
    if m:
        parts = [p.strip().strip("'\"") for p in m.group(1).split(",")]
        return f"使用克里宾 → {'、'.join(card_names_zh(p) for p in parts)}"

    m = _PLAY_RE.match(d)
    if m:
        rest = m.group(1).strip()
        ball_m = re.match(r"^Ball \((.+?)\)$", rest, re.IGNORECASE)
        if ball_m:
            return f"使用高级球（检索 {_hint_zh(ball_m.group(1))}）"
        pad_m = re.match(r"^Pad(?: \((.+?)\))?$", rest, re.IGNORECASE)
        if pad_m:
            return "使用宝可梦手环"
        poffin_m = re.match(r"^Poffin(?: \((.+?)\))?$", rest, re.IGNORECASE)
        if poffin_m:
            return "使用伙伴糖果"
        hilda_m = re.match(r"^Hilda(?: \((.+?)\))?$", rest, re.IGNORECASE)
        if hilda_m:
            hint = hilda_m.group(1)
            if hint and "after Meowth" in hint:
                return "使用希尔达（喵头目线）"
            if hint:
                return f"使用希尔达（{card_names_zh(hint)}）"
            return "使用希尔达"
        crispin_m = re.match(r"^Crispin(?: \((.+?)\))?$", rest, re.IGNORECASE)
        if crispin_m:
            return "使用克里宾"
        ultra_m = re.match(r"^Ultra Ball(?: \((.+?)\))?$", rest, re.IGNORECASE)
        if ultra_m:
            hint = ultra_m.group(1)
            if hint:
                return f"使用高级球（{card_names_zh(hint)}）"
            return "使用高级球"
        return f"使用 {card_names_zh(rest)}"

    m = re.match(r"^(.+?): deck → hand (.+)$", d)
    if m:
        return f"{card_names_zh(m.group(1))}：从牌库加入手牌 {card_names_zh(m.group(2))}"

    if d.startswith("Mulligan #"):
        return d.replace("Mulligan", "重开").replace("redraw 7", "重抽 7 张")

    if d.startswith("Salvatore blocked:"):
        return f"萨瓦托无法使用：{card_names_zh(d.split(':', 1)[1].strip())}"

    if d.startswith("EVOLVE blocked:"):
        return f"无法进化：{card_names_zh(d.split(':', 1)[1].strip())}"

    if d.startswith("Poké Pad blocked:"):
        rest = d.split(":", 1)[1].strip()
        m = re.match(r"^(.+?) is not a legal Pad target \(E-PAD-1\)$", rest)
        if m:
            return f"宝可梦手环无法使用：{card_names_zh(m.group(1))} 不是合法检索目标"
        return f"宝可梦手环无法使用：{card_names_zh(rest)}"

    if d.startswith("Retreat blocked:"):
        return f"无法撤退：{card_names_zh(d.split(':', 1)[1].strip())}"

    if d.startswith("Switch unavailable"):
        return SKIP_NOTE_ZH.get(
            "Switch unavailable — cannot promote Mega to Active (E-SW-1)",
            "无法将超级进化宝可梦换上战斗场。",
        )

    return card_names_zh(d)


def format_action(action: Action, *, seen_skips: set[str]) -> str | None:
    """Return formatted line, or None if line should be omitted."""
    if is_debug_detail(action.detail):
        return None

    skip_key = _skip_dedupe_key(action.detail)
    if skip_key is not None:
        if skip_key in seen_skips:
            return None
        seen_skips.add(skip_key)
        detail = localize_detail(action.detail)
        if action.detail in SKIP_NOTE_ZH:
            detail = SKIP_NOTE_ZH[action.detail]
        elif skip_key in SKIP_NOTE_ZH:
            detail = SKIP_NOTE_ZH[skip_key]
        kind_zh = KIND_ZH.get(action.kind, action.kind)
        return f"[{kind_zh}] {detail}"

    kind_zh = KIND_ZH.get(action.kind, action.kind)
    return f"[{kind_zh}] {localize_detail(action.detail)}"


def format_actions(actions: list[Action]) -> list[str]:
    """Format action list for export; renumber after filtering."""
    seen_skips: set[str] = set()
    lines: list[str] = []
    for a in actions:
        formatted = format_action(a, seen_skips=seen_skips)
        if formatted is None:
            continue
        lines.append(formatted)
    out: list[str] = []
    for i, line in enumerate(lines, 1):
        out.append(f"  {i}. {line}")
    return out


def dedupe_blocked_notes(notes: list[str]) -> list[str]:
    """Header BLOCKED_NOTES: one localized line per unique skip type."""
    seen: set[str] = set()
    out: list[str] = []
    for note in notes:
        key = _skip_dedupe_key(note) or note
        if key in seen:
            continue
        seen.add(key)
        if note in SKIP_NOTE_ZH:
            out.append(SKIP_NOTE_ZH[note])
        elif "Switch unavailable" in note:
            out.append(SKIP_NOTE_ZH["Switch unavailable — cannot promote Mega to Active (E-SW-1)"])
        elif "ATTACH skipped" in note:
            out.append(SKIP_NOTE_ZH["ATTACH skipped: no water in hand"])
        else:
            out.append(localize_detail(note))
    return out


def format_log_text(text: str) -> str:
    """Post-process exported .log: card names + action tag localization."""
    lines = text.splitlines()
    out: list[str] = []
    in_turn_actions = False
    turn_seen_skips: set[str] = set()

    action_line_re = re.compile(r"^(\s*)(\d+)\.\s+\[(\w+)\]\s+(.+)$")

    for line in lines:
        if line.strip() == "本回合操作:":
            in_turn_actions = True
            turn_seen_skips.clear()
            out.append(line)
            continue
        if line.startswith("  回合结束") or line.startswith("【My-T") or line.startswith("【Setup"):
            in_turn_actions = False
            turn_seen_skips.clear()

        if line.startswith("// BLOCKED_NOTES:"):
            out.append("// 拦截摘要:")
            continue
        if line.startswith("//   - "):
            note = line[6:].strip()
            key = _skip_dedupe_key(note) or note
            if key in turn_seen_skips:
                continue
            localized = dedupe_blocked_notes([note])
            if localized:
                out.append(f"//   - {localized[0]}")
            continue

        m = action_line_re.match(line)
        if m and in_turn_actions:
            indent, _num, kind, detail = m.groups()
            if is_debug_detail(detail):
                continue
            skip_key = _skip_dedupe_key(detail)
            if skip_key is not None:
                if skip_key in turn_seen_skips:
                    continue
                turn_seen_skips.add(skip_key)
                if detail in SKIP_NOTE_ZH:
                    detail = SKIP_NOTE_ZH[detail]
                else:
                    detail = localize_detail(detail)
            else:
                detail = localize_detail(detail)
            kind_zh = KIND_ZH.get(kind, kind)
            # Renumbering deferred — collect and renumber at end of section
            out.append(f"{indent}__ACTION__{kind_zh}__{detail}")
            continue

        if m and not in_turn_actions:
            indent, _num, kind, detail = m.groups()
            if is_debug_detail(detail):
                continue
            kind_zh = KIND_ZH.get(kind, kind)
            detail = localize_detail(detail)
            out.append(f"{indent}__ACTION__{kind_zh}__{detail}")
            continue

        out.append(card_names_zh(line))

    # Renumber __ACTION__ placeholders
    final: list[str] = []
    action_idx = 0
    for line in out:
        if "__ACTION__" in line:
            action_idx += 1
            m = re.match(r"^(\s*)__ACTION__(.+?)__(.+)$", line)
            if m:
                indent, kind_zh, detail = m.groups()
                final.append(f"{indent}{action_idx}. [{kind_zh}] {detail}")
            else:
                final.append(line)
        else:
            if line.strip() in ("操作:", "本回合操作:") or line.startswith("  Setup 后"):
                action_idx = 0
            final.append(line)

    return "\n".join(final)
