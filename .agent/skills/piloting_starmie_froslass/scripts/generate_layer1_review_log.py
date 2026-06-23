#!/usr/bin/env python3
"""Generate human-review log for Layer1 + draw-axis test coverage."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(SKILL / "scripts")]

from cg.api import AreaType, EnergyType, OptionType
from deck_resources import build_deck_resources, load_deck_template
from draw_axis import pick_draw_axis_action
from hand_snapshot import build_board_snapshot
from opening_cards import BOSS_ORDERS, LILLIE
from phase_fsm import compute_phase
from supporter_planner import pick_supporter

import starmie_pilot as sp


def _pkm(cid, hp=300, energies=None):
    return NS(id=cid, hp=hp, maxHp=hp, energies=energies or [])


def _player(**kw):
    hand = kw.pop("hand", [])
    return NS(
        active=kw.pop("active", []),
        bench=kw.pop("bench", []),
        hand=hand,
        prize=[None] * kw.pop("prize_n", 6),
        prizeCount=kw.pop("prize_n", 6),
        handCount=kw.pop("hand_n", len(hand)),
        discard=kw.pop("discard", []),
        deckCount=kw.pop("deck_count", 30),
        supporterPlayed=kw.pop("supporter_played", False),
        energyAttached=False,
    )


def _obs(turn, me, opp, fp=0):
    players = [me, opp]
    return NS(
        current=NS(turn=turn, yourIndex=0, firstPlayer=fp, players=players),
        select=NS(deck=[], option=[]),
    )


def _scenario(title: str, turn, me, opp, deck_template, lines: list[str]):
    lines.append(f"\n{'='*72}")
    lines.append(f"SCENARIO: {title}")
    lines.append(f"{'='*72}")
    obs = _obs(turn, me, opp)
    sit = sp._compute_situation(obs, deck_template=deck_template)
    board = sit["board"]
    phase = sit["phase"]
    hand = sit["hand"]
    res = sit["resources"]
    lines.append(f"  turn={board.turn}  my_turn={board.my_turn_number}  phase={phase.primary}")
    lines.append(f"  prize={board.prize_self}/{board.prize_opp}  hand_size={hand.hand_size}")
    lines.append(f"  deck_count={res.deck_count}  discard_seen={res.discard_count}")
    lines.append(
        f"  resources: Lillie_left={res.lillie_left} Boss_left={res.boss_left} "
        f"66_left={res.dudunsparce_66_left} basics_left={res.dunsparce_basic_left}"
    )
    sup = sit.get("supporter_dec")
    draw = sit.get("draw_axis_dec")
    lines.append(f"  supporter_dec: {sup}")
    lines.append(f"  draw_axis_dec: {draw}")
    lines.append("  option scores (Layer1):")
    opts = []
    for i, cid in enumerate(hand.hand_ids):
        opt = NS(type=OptionType.PLAY, index=i)
        score = sp._hard_rule_bonus(obs, opt, sit)
        opts.append((score, f"PLAY {cid}"))
    if board.active_is_mega_starmie:
        opts.append((sp._hard_rule_bonus(obs, NS(type=OptionType.ATTACK, attackId=1487), sit), "ATTACK Jetting"))
    for score, label in sorted(opts, reverse=True):
        lines.append(f"    {score:8.1f}  {label}")


def main() -> None:
    out = SKILL / "logs" / "layer1_integration_test_review.log"
    deck = load_deck_template()
    lines: list[str] = [
        "# Layer1 集成测试 — 人工审查日志",
        f"# generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## 1. 测试方法说明",
        "",
        "### A. 单元测试（无完整对局引擎）",
        "- tests/test_starmie_pilot.py — mock obs，断言 _hard_rule_bonus / _soft_bonus",
        "- tests/test_draw_axis_framework.py — supporter_planner + draw_axis + deck_resources",
        "- tests/test_opening_simulator.py — OPENING 模拟器 + opening_validate（20 pytest + 批量10局）",
        "",
        "### B. 本日志 §2 — 场景推演",
        "- 用与单元测试相同的 mock obs，打印 planner 决策 + Layer1 分数",
        "- 未跑真实 cabt 引擎 / 未跑 vs Walrein 完整对局",
        "",
        "## 2. 场景推演（Layer1 决策轨迹）",
    ]

    active = _pkm(sp._CARDS["mega_starmie_ex"], energies=[int(EnergyType.WATER)])
    snorunt = _pkm(sp._CARDS["snorunt"])
    munk = _pkm(sp._MUNKIDORI_ID, energies=[int(EnergyType.DARKNESS)])
    d66 = _pkm(sp._CARDS["dudunsparce"])

    # P-1 My-T2 forbid Lillie
    me = _player(
        active=[active], bench=[snorunt, munk],
        hand=[NS(id=LILLIE)], prize_n=6, hand_n=1, deck_count=32,
    )
    opp = _player(active=[_pkm(999)])
    _scenario("P-1 My-T2 首 AGGRESSION — 禁 Lillie", 4, me, opp, deck, lines)

    # Boss gust
    me = _player(
        active=[active], bench=[snorunt, munk],
        hand=[NS(id=BOSS_ORDERS), NS(id=LILLIE)], prize_n=5, hand_n=2,
    )
    opp = _player(active=[_pkm(999, hp=300)], bench=[_pkm(888, hp=80)])
    _scenario("Boss gust 目标在 bench — PLAY Boss 优先", 7, me, opp, deck, lines)

    # Lillie low hand My-T4
    me = _player(
        active=[active], bench=[snorunt, munk],
        hand=[NS(id=LILLIE), NS(id=LILLIE)], prize_n=5, hand_n=2,
    )
    opp = _player(active=[_pkm(999)])
    _scenario("DR-2 手牌≤2 — PLAY Lillie", 7, me, opp, deck, lines)

    # Run Away Draw
    me = _player(
        active=[active], bench=[snorunt, munk, d66],
        hand=[NS(id=3)], prize_n=4, hand_n=1,
    )
    opp = _player(active=[_pkm(999)])
    _scenario("DR-4 bench 有 66 — Run Away Draw", 7, me, opp, deck, lines)

    # Deck resources after discards
    me = _player(
        active=[active], bench=[snorunt, munk],
        hand=[NS(id=BOSS_ORDERS)],
        discard=[NS(id=1225), NS(id=1225), NS(id=66)],
        prize_n=5, hand_n=1, deck_count=28,
    )
    opp = _player(active=[_pkm(999)])
    _scenario("牌库资源 — 弃牌区含 2×Hilda + 1×66", 7, me, opp, deck, lines)

    lines.extend([
        "",
        "## 3. test_starmie_pilot.py 用例清单（21）",
        "",
        "| # | 用例 | 断言内容 |",
        "|---|------|----------|",
        "| 1 | test_fan_call_fires_turn_one | My-T1 Fan Call → DOMINATE |",
        "| 2 | test_fan_call_silent_late_game | turn5 不触发 Fan Call |",
        "| 3 | test_munkidori_fires_with_dark_energy | AGGRESSION + 暗能 → Adrena-Brain |",
        "| 4 | test_munkidori_silent_without_dark_energy | 无暗能 → 0 |",
        "| 5 | test_munkidori_silent_during_opening | OPENING → 0 |",
        "| 6 | test_budew_fallback_when_no_mega | OPENING Budew Itchy Pollen |",
        "| 7 | test_budew_silent_when_mega_ready | 有 Mega → 0 |",
        "| 8 | test_froslass_harvest_big_hand | 软维 froslass_harvest |",
        "| 9 | test_froslass_no_harvest_small_hand | 小手牌无 harvest |",
        "| 10 | test_jetting_blow_preferred | 软维 jetting_blow_pref |",
        "| 11 | test_aggression_jetting_blow_hard_rule | Jetting DOMINATE |",
        "| 12 | test_aggression_nebula_ko_beats_jetting | Nebula > Jetting |",
        "| 13 | test_aggression_play_snorunt_when_missing | PLAY Snorunt MID |",
        "| 14 | test_aggression_attach_dark_to_munkidori | ATTACH dark MID |",
        "| 15 | test_risky_ruins_after_bench_core | Risky Ruins LOW |",
        "| 16 | test_fan_rotom_play_blocked_when_dead | PLAY 174 → -DOMINATE |",
        "| 17 | test_phase_fsm_opening_vs_aggression | phase_fsm 转移 |",
        "| 18 | test_layer1_boss_play_beats_lillie_when_gust | Boss≥950, Lillie≤-1000 |",
        "| 19 | test_layer1_forbid_lillie_my_t2_aggression | My-T2 Lillie -DOMINATE |",
        "| 20 | test_layer1_lillie_play_low_hand_my_t4 | DR-2 Lillie≥850 |",
        "| 21 | test_layer1_run_away_draw_ability | 66 Ability≥900 |",
        "",
        "## 4. test_draw_axis_framework.py 用例清单（9）",
        "",
        "| # | 用例 | 断言内容 |",
        "|---|------|----------|",
        "| 1 | test_p1_forbid_lillie_my_t2 | DR-5c |",
        "| 2 | test_p1_forbid_66_cycle_my_t2 | DD-1 |",
        "| 3 | test_dr2_lillie_low_hand | pick_supporter PLAY Lillie |",
        "| 4 | test_dr5_forbid_lillie_when_boss_gust | DR-5 |",
        "| 5 | test_sp_boss_priority | Boss 优先 |",
        "| 6 | test_dr4_run_away_draw_when_ready | ABILITY_DRAW |",
        "| 7 | test_dd7_forbid_when_no_66_left | 66 耗尽 DD-7 |",
        "| 8 | test_build_deck_resources_from_obs | seen/remaining 计数 |",
        "| 9 | test_prefer_cycle_preserves_lillie | 有 Boss 时倾向循环 |",
        "",
        "## 5. test_opening_simulator.py",
        "",
        "- pytest 20 项：opening_cards/state/planner/validate 回归",
        "- 批量 simulate_opening seeds 42–51，MAX_TURNS=5",
        "- 详细过程日志见：logs/test_batch_max5.log（OPENING 专用，不含 Layer1 pilot）",
        "",
        "## 6. 未覆盖（人工审查时注意）",
        "",
        "- 未跑真实 cabt 对局验证 Layer1 与引擎选项列表一致性",
        "- 未跑 vs Walrein 完整 marathon",
        "- OPENING 模拟器与 starmie_pilot Layer1 是两套独立路径",
        "- submission/main.py 是否已切换 make_starmie_agent 需单独确认",
        "",
    ])

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
