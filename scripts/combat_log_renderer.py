#!/usr/bin/env python3
"""Render engine Log streams into gold-style Chinese combat review logs.

Consumes GameResult.engine_logs from arena.simulator.play_game(
    collect_engine_logs=True). Perspective: player 0 = 我方 (Starmie agent)
when that seat played as agent_a; the export script remaps seats via header.
"""
from __future__ import annotations

from typing import Any

from cg.api import all_attack, all_card_data, CardType, LogType

# Shared zh map with opening gold logs (long names first for substring replace).
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
    "Basic {W} Energy": "基本水能量",
    "Basic {D} Energy": "基本恶能量",
    "Basic {G} Energy": "基本草能量",
    "Basic {R} Energy": "基本火能量",
    "Basic {L} Energy": "基本雷能量",
    "Basic {P} Energy": "基本超能量",
    "Basic {F} Energy": "基本斗能量",
    "Basic {M} Energy": "基本钢能量",
    "Ultra Ball": "高级球",
    "Poké Pad": "宝可梦手环",
    "Fan Rotom": "旋转罗盘",
    "Risky Ruins": "危险废墟",
    "Meowth ex": "喵头目 ex",
    "Dudunsparce ex": "土龙节节 ex",
    "Munkidori": "愿增猿",
    "Dunsparce": "土龙弟弟",
    "Dudunsparce": "土龙节节",
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
    "Lillie's Determination": "莉莉艾的决心",
    "Judge": "裁判",
    "Alakazam ex": "胡地 ex",
    "Lucario": "路卡利欧",
    "Lucario ex": "路卡利欧 ex",
    "Dragapult ex": "多龙巴鲁托 ex",
    "Fezandipiti ex": "吉雉鸡 ex",
    "Boss’s Orders": "老大的指令",
    "Nighttime Mine": "夜间矿山",
    "Dawn": "道恩",
    "Jetting Blow": "喷射一击",
    "Nebula Beam": "星云光线",
}

_AREA_ZH = {
    1: "牌库",
    2: "手牌",
    3: "弃牌区",
    4: "战斗场",
    5: "替补席",
    6: "奖品",
    7: "竞技场",
}

_CARD_EN: dict[int, str] = {}
_CARD_TYPE: dict[int, int] = {}
_ATK_NAME: dict[int, str] = {}
_ATK_DMG: dict[int, int] = {}
_TABLES_READY = False


def _ensure_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY:
        return
    for c in all_card_data():
        cid = int(c.cardId)
        _CARD_EN[cid] = str(c.name)
        _CARD_TYPE[cid] = int(c.cardType)
    for a in all_attack():
        aid = int(a.attackId)
        _ATK_NAME[aid] = str(a.name)
        _ATK_DMG[aid] = int(getattr(a, "damage", 0) or 0)
    _TABLES_READY = True


def card_zh(card_id: int | None) -> str:
    _ensure_tables()
    if not card_id:
        return "未知卡"
    en = _CARD_EN.get(int(card_id), f"card#{card_id}")
    return CARD_NAME_ZH.get(en, en)


def attack_zh(attack_id: int | None) -> str:
    _ensure_tables()
    if not attack_id:
        return "未知招式"
    en = _ATK_NAME.get(int(attack_id), f"atk#{attack_id}")
    return CARD_NAME_ZH.get(en, en)


def _is_pokemon(card_id: int | None) -> bool:
    _ensure_tables()
    if not card_id:
        return False
    return _CARD_TYPE.get(int(card_id), -1) == int(CardType.POKEMON)


def _si(x, d=0) -> int:
    try:
        return int(x)
    except Exception:
        return d


def _area_zh(a) -> str:
    return _AREA_ZH.get(_si(a, -1), f"区域{_si(a)}")


def render_combat_log(
    engine_logs: list[dict[str, Any]],
    *,
    header: dict[str, Any],
    our_player_index: int = 0,
) -> str:
    """Render full game NL log. our_player_index = seat of Starmie agent."""
    _ensure_tables()
    lines: list[str] = []
    lines.append("// combat_review_log v1")
    for k in (
        "seed", "opp_deck", "opp_policy", "we_are_a", "winner",
        "reward_for_us", "steps", "truncated", "tags", "prize_final",
    ):
        if k in header:
            lines.append(f"// {k}={header[k]}")
    lines.append("")
    lines.append("【对局】 我方=海星Agent  对手=%s（%s）" % (
        header.get("opp_deck", "?"),
        header.get("opp_policy", "?"),
    ))
    w = header.get("winner")
    if w is None:
        outcome = "未完/截断" if header.get("truncated") else "平局"
    elif w == our_player_index:
        outcome = "我方胜"
    else:
        outcome = "对手胜"
    lines.append(f"【结果】 {outcome}  steps={header.get('steps', '?')}")
    if header.get("tags"):
        lines.append(f"【标签】 {', '.join(header['tags'])}")
    lines.append("")

    our_turn_n = 0
    opp_turn_n = 0
    step_n = 0
    in_turn = False
    turn_side: str | None = None

    def _side_label(pi: int) -> str:
        return "我方" if pi == our_player_index else "对手"

    def _emit_turn_header(pi: int) -> None:
        nonlocal our_turn_n, opp_turn_n, step_n, in_turn, turn_side
        if pi == our_player_index:
            our_turn_n += 1
            n = our_turn_n
        else:
            opp_turn_n += 1
            n = opp_turn_n
        turn_side = _side_label(pi)
        in_turn = True
        step_n = 0
        lines.append(f"【{turn_side}-T{n}】")

    i = 0
    nlogs = len(engine_logs)
    while i < nlogs:
        lg = engine_logs[i]
        typ = lg.get("type")

        # Synthetic board snapshot right after TURN_START
        if typ == "SNAPSHOT":
            pi = _si(lg.get("playerIndex"), -1)
            if pi == our_player_index:
                hand = [card_zh(c) for c in (lg.get("hand") or []) if c]
                if hand:
                    lines.append(f"  回合开始手牌: {', '.join(hand)}")
                act = lg.get("active") or []
                ben = lg.get("bench") or []
                if act:
                    a0 = act[0]
                    lines.append(
                        "  场上: 战斗场=%s(HP%d) 替补=%s 奖品 %d:%d"
                        % (
                            card_zh(a0.get("id")),
                            _si(a0.get("hp")),
                            "/".join(card_zh(b.get("id")) for b in ben) or "空",
                            _si(lg.get("prize_self")),
                            _si(lg.get("prize_opp")),
                        )
                    )
            else:
                act = lg.get("active") or []
                if act:
                    lines.append(
                        "  对手场上: 战斗场=%s(HP%d) 奖品 对手%d / 我方%d"
                        % (
                            card_zh(act[0].get("id")),
                            _si(act[0].get("hp")),
                            _si(lg.get("prize_self")),
                            _si(lg.get("prize_opp")),
                        )
                    )
            i += 1
            continue

        t = _si(typ, -1)

        if t == int(LogType.TURN_START):
            if in_turn:
                lines.append("")
            _emit_turn_header(_si(lg.get("playerIndex"), -1))
            i += 1
            continue

        if t == int(LogType.TURN_END):
            i += 1
            continue

        if t == int(LogType.SHUFFLE):
            i += 1
            continue

        if t == int(LogType.HAS_BASIC_POKEMON):
            i += 1
            continue

        # Batch consecutive DRAWs for same player
        if t == int(LogType.DRAW):
            pi = _si(lg.get("playerIndex"), -1)
            cards: list[str] = []
            while i < nlogs and _si(engine_logs[i].get("type"), -1) == int(LogType.DRAW) \
                    and _si(engine_logs[i].get("playerIndex"), -1) == pi:
                cards.append(card_zh(engine_logs[i].get("cardId")))
                i += 1
            step_n += 1
            if pi == our_player_index:
                lines.append(f"  {step_n}. [抽牌] {', '.join(cards)}")
            else:
                lines.append(f"  {step_n}. [对手抽牌] ×{len(cards)}")
            continue

        if t == int(LogType.DRAW_REVERSE):
            # Opponent drew from our perspective — usually redundant with DRAW.
            i += 1
            continue

        if t == int(LogType.PLAY):
            pi = _si(lg.get("playerIndex"), -1)
            cid = lg.get("cardId")
            step_n += 1
            tag = "放置" if _is_pokemon(cid) else "操作"
            who = "" if pi == our_player_index else "对手"
            lines.append(f"  {step_n}. [{tag}] {who}使用 {card_zh(cid)}".replace("使用 使用", "使用 "))
            # fix awkward "对手使用" for pokemon placement
            if _is_pokemon(cid):
                lines[-1] = (
                    f"  {step_n}. [放置] {card_zh(cid)} 上场"
                    if pi == our_player_index
                    else f"  {step_n}. [放置] 对手上场 {card_zh(cid)}"
                )
            else:
                lines[-1] = (
                    f"  {step_n}. [操作] 使用 {card_zh(cid)}"
                    if pi == our_player_index
                    else f"  {step_n}. [操作] 对手使用 {card_zh(cid)}"
                )
            i += 1
            continue

        if t == int(LogType.ATTACH):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            src = card_zh(lg.get("cardId"))
            tgt = card_zh(lg.get("cardIdTarget"))
            pref = "" if pi == our_player_index else "对手"
            lines.append(f"  {step_n}. [贴能] {pref}{src} → {tgt}")
            i += 1
            continue

        if t == int(LogType.EVOLVE):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            evo = card_zh(lg.get("cardId"))
            base = card_zh(lg.get("cardIdTarget"))
            pref = "" if pi == our_player_index else "对手"
            lines.append(f"  {step_n}. [进化] {pref}{base} → {evo}")
            i += 1
            continue

        if t == int(LogType.SWITCH):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            out_p = card_zh(lg.get("cardIdActive"))
            in_p = card_zh(lg.get("cardIdBench"))
            pref = "" if pi == our_player_index else "对手"
            lines.append(f"  {step_n}. [撤退/交替] {pref}{out_p} ⇄ {in_p}")
            i += 1
            continue

        if t == int(LogType.CHANGE):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            before = card_zh(lg.get("cardIdBefore"))
            after = card_zh(lg.get("cardIdAfter"))
            pref = "" if pi == our_player_index else "对手"
            lines.append(f"  {step_n}. [换人] {pref}{before} → {after}")
            i += 1
            continue

        if t == int(LogType.ATTACK):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            user = card_zh(lg.get("cardId"))
            aid = lg.get("attackId")
            atk = attack_zh(aid)
            dmg = _ATK_DMG.get(_si(aid), 0)
            pref = "" if pi == our_player_index else "对手"
            dmg_s = f" 印刷伤害{dmg}" if dmg else ""
            lines.append(f"  {step_n}. [攻击] {pref}{user} 使用 {atk}{dmg_s}")
            i += 1
            continue

        if t == int(LogType.HP_CHANGE):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            mon = card_zh(lg.get("cardId"))
            val = _si(lg.get("value"))
            pref = "我方" if pi == our_player_index else "对手"
            if val < 0:
                tag = "伤害"
                detail = f"{pref}{mon} HP {val}"
            else:
                tag = "回复"
                detail = f"{pref}{mon} HP +{val}"
            if lg.get("putDamageCounter"):
                detail += "（伤害指示物）"
            lines.append(f"  {step_n}. [{tag}] {detail}")
            i += 1
            continue

        if t == int(LogType.MOVE_CARD):
            # Only surface search / discard / prize-relevant moves.
            fr, to = _si(lg.get("fromArea"), -1), _si(lg.get("toArea"), -1)
            cid = lg.get("cardId")
            pi = _si(lg.get("playerIndex"), -1)
            interesting = (
                (fr == 1 and to == 2)  # deck → hand (search)
                or (fr == 2 and to == 3)  # hand → discard
                or (fr == 3 and to == 2)  # discard → hand (Night Stretcher)
                or (to == 6 or fr == 6)  # prize
            )
            if not interesting:
                i += 1
                continue
            step_n += 1
            pref = "" if pi == our_player_index else "对手"
            if pi != our_player_index and fr == 1 and to == 2:
                # Don't reveal opponent searched card name if face-down? cardId is present.
                lines.append(
                    f"  {step_n}. [检索] {pref}{_area_zh(fr)} → {_area_zh(to)} ← {card_zh(cid)}"
                )
            elif fr == 2 and to == 3:
                lines.append(f"  {step_n}. [丢弃] {pref}{card_zh(cid)}")
            elif fr == 3 and to == 2:
                lines.append(f"  {step_n}. [回收] {pref}弃牌区 → 手牌 ← {card_zh(cid)}")
            elif to == 6 or fr == 6:
                lines.append(
                    f"  {step_n}. [奖品] {pref}{card_zh(cid)} "
                    f"{_area_zh(fr)} → {_area_zh(to)}"
                )
            else:
                lines.append(
                    f"  {step_n}. [移动] {pref}{card_zh(cid)} "
                    f"{_area_zh(fr)} → {_area_zh(to)}"
                )
            i += 1
            continue

        if t == int(LogType.MOVE_CARD_REVERSE):
            i += 1
            continue

        if t == int(LogType.MOVE_ATTACHED):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            pref = "" if pi == our_player_index else "对手"
            lines.append(
                f"  {step_n}. [移能] {pref}{card_zh(lg.get('cardId'))} "
                f"{card_zh(lg.get('cardIdBefore'))} → {card_zh(lg.get('cardIdAfter'))}"
            )
            i += 1
            continue

        if t == int(LogType.RESULT):
            step_n += 1
            lines.append(
                f"  {step_n}. [终局] result={lg.get('result')} reason={lg.get('reason')}"
            )
            i += 1
            continue

        # Status / coin — compact
        if t in (
            int(LogType.POISONED), int(LogType.BURNED), int(LogType.ASLEEP),
            int(LogType.PARALYZED), int(LogType.CONFUSED),
        ):
            step_n += 1
            names = {
                int(LogType.POISONED): "中毒",
                int(LogType.BURNED): "灼伤",
                int(LogType.ASLEEP): "睡眠",
                int(LogType.PARALYZED): "麻痹",
                int(LogType.CONFUSED): "混乱",
            }
            pi = _si(lg.get("playerIndex"), -1)
            pref = "我方" if pi == our_player_index else "对手"
            verb = "解除" if lg.get("isRecover") else "陷入"
            lines.append(
                f"  {step_n}. [状态] {pref}{card_zh(lg.get('cardId'))} {verb}{names[t]}"
            )
            i += 1
            continue

        if t == int(LogType.COIN):
            step_n += 1
            lines.append(
                f"  {step_n}. [掷币] {'正面' if lg.get('head') else '反面'}"
            )
            i += 1
            continue

        if t == int(LogType.DEVOLVE):
            step_n += 1
            pi = _si(lg.get("playerIndex"), -1)
            pref = "" if pi == our_player_index else "对手"
            lines.append(
                f"  {step_n}. [退化] {pref}{card_zh(lg.get('cardIdTarget'))} "
                f"← {card_zh(lg.get('cardId'))}"
            )
            i += 1
            continue

        i += 1

    lines.append("")
    lines.append("// end")
    return "\n".join(lines) + "\n"
