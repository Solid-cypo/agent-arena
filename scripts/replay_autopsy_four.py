#!/usr/bin/env python3
"""Stateful HEAD agent replay of the four autopsy episodes.

Feeds each observation through make_starmie_agent (submission_starmie, synced)
and compares to the online action. Key frames are printed in full.

  OPENING_HANDOFF=0 RL_ENABLED=0 python3 scripts/replay_autopsy_four.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OPENING_HANDOFF", "0")
os.environ.setdefault("RL_ENABLED", "0")
os.environ.setdefault("PYTHONHASHSEED", "0")

from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402
from cg.api import AreaType, OptionType, to_observation_class  # noqa: E402

US = "Ying Peter"
SUB = ROOT / "data/kaggle_episodes/sub_55473608"
NAMES = {
    3: "W", 7: "D", 65: "土龙A", 66: "节节", 104: "104", 112: "猿",
    174: "风扇", 235: "含羞苞", 305: "土龙B", 860: "雪童", 861: "861",
    1030: "海星星", 1031: "Mega海星", 1071: "喵", 1080: "印章", 1086: "宝芬",
    1097: "夜伸", 1121: "超球", 1123: "替换", 1152: "垫板", 1182: "Boss",
    1189: "萨瓦托", 1198: "克利芬", 1213: "裁判", 1225: "希尔达", 1227: "莉莉艾",
    1260: "废墟", 1487: "喷水", 1486: "水枪", 74: "土龙咬", 1239: "雪童撞",
}
CTX = {
    0: "MAIN", 3: "SWITCH", 4: "TO_ACTIVE", 5: "TO_BENCH", 6: "TO_FIELD",
    7: "TO_HAND", 8: "DISCARD", 21: "ATTACH_FROM", 22: "ATTACH_TO",
}
# (eid, key_si_set, note)
EPISODES = (
    (92535497, {11, 12, 13, 25, 26, 27}, "希尔达砖局摸66"),
    (92537402, {13, 16, 17, 18, 19, 20, 21, 33}, "克利芬贴水+喵头目"),
    (92538341, {64, 65, 66, 71, 74}, "落后带水雪童超球861"),
    (92546850, {37, 38, 41}, "喷水前进化66"),
)


def N(c):
    try:
        return NAMES.get(int(c), str(c))
    except Exception:
        return str(c)


def lab(obs, o, mi, sp):
    t = int(o.type)
    me = obs.current.players[mi]
    if t == int(OptionType.PLAY):
        cid = sp._hand_card_id(obs, o, mi)
        return f"PLAY {N(cid)}"
    if t == int(OptionType.EVOLVE):
        h = me.hand or []
        i = int(getattr(o, "index", -1))
        cid = int(h[i].id) if 0 <= i < len(h) and h[i] else None
        return f"EVOLVE {N(cid)}"
    if t == int(OptionType.ATTACK):
        return f"ATK {N(getattr(o, 'attackId', None))}"
    if t == int(OptionType.END):
        return "END"
    if t == int(OptionType.RETREAT):
        return "RETREAT"
    if t == int(OptionType.ATTACH):
        return f"ATTACH ipa={getattr(o, 'inPlayArea', None)} ipi={getattr(o, 'inPlayIndex', None)}"
    if t == int(OptionType.ABILITY):
        return "ABIL"
    if t == int(OptionType.CARD):
        cid = sp._card_option_id(obs, o, mi)
        area = int(getattr(o, "area", -1) or -1)
        if area in (int(AreaType.ACTIVE), int(AreaType.BENCH)):
            pkm = sp._pokemon_in_area(
                obs, o.area, int(getattr(o, "index", -1)),
                int(getattr(o, "playerIndex", mi) or mi),
            )
            if pkm:
                cid = int(pkm.id)
        return f"CARD {N(cid)}"
    return f"T{t}"


def pkm_s(p):
    if not p:
        return "?"
    es = []
    for e in (getattr(p, "energies", None) or []):
        try:
            es.append(N(int(e) if not hasattr(e, "id") else int(e.id)))
        except Exception:
            pass
    tag = f"[{''.join(es)}]" if es else ""
    hp = getattr(p, "hp", "?")
    mx = getattr(p, "maxHp", hp)
    return f"{N(p.id)} {hp}/{mx}{tag}"


def board_line(obs, mi):
    me = obs.current.players[mi]
    opp = obs.current.players[1 - mi]
    act = (me.active or [None])[0]
    oact = (opp.active or [None])[0]
    bench = [pkm_s(p) for p in (me.bench or []) if p]
    hand = [N(int(c.id)) for c in (me.hand or []) if c]
    pr_s = len(me.prize or []) or getattr(me, "prizeCount", "?")
    pr_o = len(opp.prize or []) or getattr(opp, "prizeCount", "?")
    return (
        f"奖{pr_s}-{pr_o} 前 {pkm_s(act)} 备 {bench}\n"
        f"   对手 {pkm_s(oact)}  手 {hand}"
    )


def pick_idx(action):
    if not action:
        return None
    if isinstance(action, list) and action:
        return int(action[0])
    try:
        return int(action)
    except Exception:
        return None


def main() -> int:
    agent, reset, sp, _deck, _state = load_starmie_agent(ROOT / "submission_starmie")
    lines = [
        "# 四局解剖 有状态 HEAD 复打",
        "",
        "agent = `submission_starmie` `make_starmie_agent`；"
        "`OPENING_HANDOFF=0` `RL_ENABLED=0`。",
        "每步 observation 来自线上回放；HEAD 选完不改后续帧（分叉后只看该帧）。",
        "",
    ]
    summary = []

    for eid, keys, note in EPISODES:
        path = SUB / f"episode-{eid}-replay.json"
        d = json.loads(path.read_text())
        mi = d["info"]["TeamNames"].index(US)
        opp = d["info"]["TeamNames"][1 - mi]
        steps = d.get("steps") or []
        reset()
        lines.append(f"## {eid} vs {opp} — {note}")
        lines.append("")
        n = n_match = n_key = n_key_ok = 0
        key_rows = []
        for si, step in enumerate(steps):
            if mi >= len(step):
                continue
            obs_d = (step[mi].get("observation")) or {}
            if obs_d.get("select") is None:
                try:
                    agent(obs_d)
                except Exception:
                    pass
                continue
            cur = obs_d.get("current") or {}
            if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
                continue
            online = None
            if si + 1 < len(steps) and mi < len(steps[si + 1]):
                online = steps[si + 1][mi].get("action")
            if not online:
                continue
            try:
                mine = agent(obs_d)
            except Exception as exc:
                mine = None
                head_err = str(exc)
            else:
                head_err = None
            same = mine is not None and list(mine) == list(online)
            n += 1
            n_match += int(same)
            is_key = si in keys
            if is_key:
                n_key += 1
                n_key_ok += int(same)
            if not is_key and same:
                continue
            # Detail: key frames always; diffs on our MAIN-ish turns too if key nearby
            if not is_key:
                continue
            obs = to_observation_class(obs_d)
            ctx = int(obs.select.context)
            opts = list(obs.select.option or [])
            oi = pick_idx(online)
            hi = pick_idx(mine)
            o_lab = lab(obs, opts[oi], mi, sp) if oi is not None and 0 <= oi < len(opts) else str(online)
            h_lab = lab(obs, opts[hi], mi, sp) if hi is not None and 0 <= hi < len(opts) else (head_err or str(mine))
            mark = "MATCH" if same else "DIFF"
            row = (
                f"- si={si} t={obs.current.turn} ctx={CTX.get(ctx, ctx)} **{mark}**\n"
                f"  {board_line(obs, mi)}\n"
                f"  线上 `{o_lab}`  HEAD `{h_lab}`"
            )
            if not same and opts:
                sit = sp._compute_situation(obs, agent_state={})
                sit["select_options"] = opts
                ranked = []
                for i, o in enumerate(opts):
                    sc = float(sp.option_score(obs, o, {}, sit))
                    ranked.append((sc, i, lab(obs, o, mi, sp)))
                ranked.sort(reverse=True)
                top = ", ".join(f"{r[2]}={r[0]:.0f}" for r in ranked[:6])
                row += f"\n  top: {top}"
            key_rows.append(row)
            lines.append(row)

        lines.append("")
        lines.append(
            f"全帧 match **{n_match}/{n}**；关键帧 **{n_key_ok}/{n_key}** "
            f"{'全部改对' if n_key_ok == n_key and n_key else ''}。"
        )
        lines.append("")
        summary.append((eid, note, n_match, n, n_key_ok, n_key))

    lines.insert(5, "| eid | 情景 | 全帧 match | 关键帧 HEAD=期望 |")
    lines.insert(6, "|---|---|---:|---|")
    for eid, note, nm, n, ko, k in summary:
        want = "是（与线上不同才算修好）" if ko < k else f"{ko}/{k}"
        # For keys we WANT to differ from online on the bug frames.
        lines.insert(7, f"| {eid} | {note} | {nm}/{n} | {ko}/{k} vs 线上 |")
        # insert in reverse... messy. rebuild summary table at end instead.
    # The inserts above are wrong order. Rewrite header table properly below.
    # Strip the botched inserts: we added 1+2+4 = 7 lines at 5-7 area.

    text = "\n".join(lines)
    # Rebuild a clean summary at the top after the intro.
    intro = [
        "# 四局解剖 有状态 HEAD 复打",
        "",
        "agent = `submission_starmie` `make_starmie_agent`；"
        "`OPENING_HANDOFF=0` `RL_ENABLED=0`。",
        "observation 来自线上回放；HEAD 选完不改后续帧（只看该帧会不会选对）。",
        "**修好 = 关键帧与线上不同，且 HEAD 选的是目标操作。**",
        "",
        "| eid | 情景 | 全帧 match | 关键帧 vs 线上 |",
        "|---|---|---:|---|",
    ]
    for eid, note, nm, n, ko, k in summary:
        intro.append(f"| {eid} | {note} | {nm}/{n} | {ko}/{k} 相同 |")
    intro.append("")
    # body starts at first ##
    body = text[text.index("## "):]
    out = "\n".join(intro) + "\n" + body
    dest = ROOT / "logs" / "autopsy_four_head_replay.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out)
    print(out)
    print(f"\nwrote {dest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
