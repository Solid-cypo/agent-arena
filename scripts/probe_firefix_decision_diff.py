#!/usr/bin/env python3
"""Synthetic board probes: ops_firefix vs HEAD hard-rule winners."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("PYTHONHASHSEED", "0")
os.environ.setdefault("RL_ENABLED", "0")
os.environ.setdefault("USE_HYBRID", "0")

from h2h_starmie_vs_baseline import load_starmie_agent, _purge_pilot_modules  # noqa: E402

STARYU, MEGA_ST, SNORUNT, MEGA_F = 1030, 1031, 860, 861
MUNK, BUDEW, DUN_A, DUD = 112, 235, 65, 66
WATER, DARK = 3, 7
LILLIE, BOSS, HILDA = 1189, 1182, 1225
HP = {
    STARYU: 70, MEGA_ST: 310, SNORUNT: 70, MEGA_F: 310,
    MUNK: 110, BUDEW: 30, DUN_A: 70, DUD: 140,
}


def _pkm(pid, hp=None, energies=None):
    mh = HP.get(pid, 100)
    h = mh if hp is None else hp
    return NS(id=pid, hp=h, maxHp=mh, energies=list(energies or []))


def build_obs(*, active, bench, hand_ids, turn=3, first_player=0, mi=0,
              opp_hand_n=5, energy_attached=False, supporter_played=False):
    me = NS(
        active=[active], bench=list(bench),
        hand=[NS(id=i) for i in hand_ids],
        prize=[None] * 6, prizeCount=6, handCount=len(hand_ids),
        discard=[], deckCount=40,
        supporterPlayed=supporter_played, energyAttached=energy_attached,
    )
    opp = NS(
        active=[_pkm(SNORUNT)], bench=[],
        hand=[NS(id=1)] * opp_hand_n,
        prize=[None] * 6, prizeCount=6, handCount=opp_hand_n,
        discard=[], deckCount=40, supporterPlayed=False, energyAttached=False,
    )
    players = [me, opp] if mi == 0 else [opp, me]
    return NS(
        current=NS(turn=turn, yourIndex=mi, firstPlayer=first_player,
                   players=players, stadium=[]),
        select=NS(context=-1, option=[], deck=[]),
    )


def score_case(sp, obs, labeled_opts):
    from cg.api import to_observation_class
    # Keep NS if to_observation_class fails
    try:
        obs2 = to_observation_class(obs) if isinstance(obs, dict) else obs
    except Exception:
        obs2 = obs
    sit = sp._compute_situation(obs2, deck_template=None, agent_state={})
    sit["select_options"] = [o for _, o in labeled_opts]
    w = getattr(sp, "DEFAULT_WEIGHTS", {})
    rows = []
    for label, opt in labeled_opts:
        try:
            hard = float(sp._hard_rule_bonus(obs2, opt, sit))
        except Exception as e:
            hard = float("nan")
            label = f"{label}/HERR:{type(e).__name__}"
        try:
            total = float(sp.option_score(obs2, opt, w, sit))
        except Exception as e:
            total = hard
            label = f"{label}/TERR:{type(e).__name__}"
        rows.append((label.split("/")[0], hard, total, label))
    winner = max(rows, key=lambda r: (
        r[2] if r[2] == r[2] else -1e18,
        r[1] if r[1] == r[1] else -1e18,
    ))[0]
    draw = sit.get("draw_axis_dec")
    return {
        "scores": [{"opt": a, "hard": b, "total": c, "tag": d} for a, b, c, d in rows],
        "winner": winner,
        "phase": getattr(sit.get("phase"), "primary", None),
        "draw_action": getattr(draw, "action", None) if draw else None,
        "draw_rule": getattr(draw, "rule_id", None) if draw else None,
        "has_turn_plan": sit.get("turn_plan") is not None,
        "compute_error": sit.get("compute_error"),
    }


def probe(agent_dir: Path) -> dict:
    _purge_pilot_modules()
    _fn, _reset, sp, _deck, _ = load_starmie_agent(agent_dir)
    from cg.api import OptionType, AreaType
    import opening_cards as oc
    switch_id = int(oc.SWITCH)

    cases = {}

    # A: evolve 66 available
    hand = [DUD, WATER, HILDA]
    obs = build_obs(
        active=_pkm(MUNK, energies=[DARK]),
        bench=[_pkm(DUN_A), _pkm(STARYU)],
        hand_ids=hand, turn=4,
    )
    cases["A_evolve66_vs_end"] = score_case(sp, obs, [
        ("EVOLVE_66", NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0, playerIndex=0)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
        ("PLAY_HILDA", NS(type=OptionType.PLAY, area=AreaType.HAND, index=2, playerIndex=0)),
        ("RETREAT", NS(type=OptionType.RETREAT, area=0, index=0, playerIndex=0)),
    ])

    # B: GF T1 Budew
    obs = build_obs(
        active=_pkm(BUDEW), bench=[_pkm(STARYU)],
        hand_ids=[switch_id, WATER], turn=1, first_player=0,
    )
    cases["B_gf_budew_no_yank_staryu"] = score_case(sp, obs, [
        ("PLAY_SWITCH", NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)),
        ("ITCHY", NS(type=OptionType.ATTACK, area=0, index=0, playerIndex=0, attackId=323)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
    ])

    # C: Mega must fire
    obs = build_obs(
        active=_pkm(MEGA_ST, energies=[WATER]),
        bench=[_pkm(MUNK, energies=[DARK]), _pkm(DUN_A)],
        hand_ids=[switch_id], turn=5, energy_attached=True,
    )
    cases["C_mega_must_fire_not_retreat"] = score_case(sp, obs, [
        ("JETTING", NS(type=OptionType.ATTACK, area=0, index=0, playerIndex=0, attackId=1487)),
        ("RETREAT", NS(type=OptionType.RETREAT, area=0, index=0, playerIndex=0)),
        ("PLAY_SWITCH", NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
    ])

    # D: dry Staryu, Mega on bench
    obs = build_obs(
        active=_pkm(STARYU),
        bench=[_pkm(MEGA_ST, energies=[WATER])],
        hand_ids=[switch_id, WATER], turn=4,
    )
    cases["D_promote_mega_not_watergun"] = score_case(sp, obs, [
        ("WATER_GUN", NS(type=OptionType.ATTACK, area=0, index=0, playerIndex=0, attackId=1486)),
        ("RETREAT", NS(type=OptionType.RETREAT, area=0, index=0, playerIndex=0)),
        ("PLAY_SWITCH", NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
    ])

    # E: 861 must Resentful
    obs = build_obs(
        active=_pkm(MEGA_F, energies=[WATER]),
        bench=[_pkm(MEGA_ST, energies=[WATER])],
        hand_ids=[LILLIE, BOSS], turn=6, opp_hand_n=5,
        energy_attached=True,
    )
    cases["E_861_must_resentful"] = score_case(sp, obs, [
        ("RESENTFUL", NS(type=OptionType.ATTACK, area=0, index=0, playerIndex=0, attackId=1240)),
        ("ABS_SNOW", NS(type=OptionType.ATTACK, area=0, index=0, playerIndex=0, attackId=1241)),
        ("PLAY_LILLIE", NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
    ])

    # F: promote fueled 861 over munk
    obs = build_obs(
        active=_pkm(MUNK),
        bench=[_pkm(MEGA_F, energies=[WATER]), _pkm(STARYU)],
        hand_ids=[switch_id, WATER], turn=5,
    )
    cases["F_promote_861_not_fuel_munk"] = score_case(sp, obs, [
        ("PLAY_SWITCH", NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)),
        ("RETREAT", NS(type=OptionType.RETREAT, area=0, index=0, playerIndex=0)),
        ("END", NS(type=OptionType.END, area=0, index=0, playerIndex=0)),
    ])

    return cases


def main() -> int:
    report = {}
    for label, path in [
        ("firefix", ROOT / "data/restore_peaks/ops_firefix_55115028"),
        ("head", ROOT / "submission_starmie"),
    ]:
        print(f"\n== {label} ==", flush=True)
        report[label] = probe(path)
        for case, data in report[label].items():
            print(
                f"  {case}: win={data['winner']} phase={data['phase']} "
                f"draw={data['draw_action']}/{data['draw_rule']} "
                f"tp={data['has_turn_plan']} err={data['compute_error']}",
                flush=True,
            )
            for row in data["scores"]:
                print(
                    f"    {row['opt']:16} hard={row['hard']:+9.1f} "
                    f"total={row['total']:+9.1f}",
                    flush=True,
                )

    meanings = {
        "A_evolve66_vs_end": "手持66+场上弟弟 → 应 EVOLVE_66",
        "B_gf_budew_no_yank_staryu": "先手T1含羞苞 → 应 ITCHY（禁切海星）",
        "C_mega_must_fire_not_retreat": "Mega有水 → 应 JETTING",
        "D_promote_mega_not_watergun": "干海星+替补Mega → 应 SWITCH/RETREAT 上位",
        "E_861_must_resentful": "861有水手牌≥4 → 应 RESENTFUL",
        "F_promote_861_not_fuel_munk": "愿增猿前+有油861 → 应 SWITCH/RETREAT",
    }
    expect = {
        "A_evolve66_vs_end": {"EVOLVE_66"},
        "B_gf_budew_no_yank_staryu": {"ITCHY", "END"},  # END ok-ish; SWITCH bad
        "C_mega_must_fire_not_retreat": {"JETTING"},
        "D_promote_mega_not_watergun": {"PLAY_SWITCH", "RETREAT"},
        "E_861_must_resentful": {"RESENTFUL"},
        "F_promote_861_not_fuel_munk": {"PLAY_SWITCH", "RETREAT"},
    }

    lines = [
        "# firefix vs HEAD 决策探针",
        "",
        "合成局面对比 `_hard_rule_bonus` / `option_score` 赢家（`RL_ENABLED=0`）。",
        "",
        "| Case | 含义 | firefix | HEAD | 分叉? |",
        "|---|---|---|---|---|",
    ]
    print("\n======== DIFF ========", flush=True)
    ff, hd = report["firefix"], report["head"]
    for case in ff:
        fw, hw = ff[case]["winner"], hd[case]["winner"]
        diverge = fw != hw
        mark = "❌" if diverge else "✅"
        # also mark if HEAD picks known-bad
        bad = False
        if case == "B_gf_budew_no_yank_staryu" and hw == "PLAY_SWITCH":
            bad = True
        if case == "A_evolve66_vs_end" and hw != "EVOLVE_66":
            bad = True
        if case == "C_mega_must_fire_not_retreat" and hw != "JETTING":
            bad = True
        if case == "E_861_must_resentful" and hw != "RESENTFUL":
            bad = True
        if bad:
            mark = "❌LEAK"
        print(f"{case}: {fw} vs {hw} {mark}", flush=True)
        lines.append(
            f"| `{case}` | {meanings[case]} | **{fw}** "
            f"(draw={ff[case]['draw_action']}) | **{hw}** "
            f"(draw={hd[case]['draw_action']}/{hd[case]['draw_rule']}) | {mark} |"
        )

    lines += [
        "",
        "## 代码分叉（已坐实）",
        "",
        "1. **EVOLVE_66**：firefix 无条件 `DOMINATE_OPEN_PATH`；"
        "HEAD 可被 TurnPlan/`draw_axis` `FORBID` → **`-DOMINATE_OPEN_PATH`**。",
        "2. **硬规则前缀**：HEAD 在 ops 块前插入 must_attack / mega_clock / "
        "TurnPlan / Alak / Budew Wave，可短路 66/861/OPENING PATH。",
        "3. **861**：firefix ANY-phase 强制 Resentful；HEAD 叠加伤害门/切回海星。",
        "4. **HR-8**：firefix 861 优先；HEAD 注释为 104 first。",
        "",
        "负局日志：`logs/h2h_audit_firefix_vs_head/AUDIT_USER_CLAIMS.md`",
        "",
        f"明细 JSON：`data/restore_peaks/decision_diff_probe.json`",
        "",
    ]
    out = ROOT / "data/restore_peaks/DECISION_DIFF_firefix_vs_head.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "data/restore_peaks/decision_diff_probe.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
