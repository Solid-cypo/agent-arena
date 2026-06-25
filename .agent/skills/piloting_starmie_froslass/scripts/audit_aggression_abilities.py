#!/usr/bin/env python3
"""Audit Pokémon abilities and Froslass+Munkidori synergy in My-T2..T8 real games.

NOTE: `--opponent` explicit deck mapping is for **local functional testing only**.
Kaggle submission (`submission_starmie/main.py`) must route via opponent deck detection
(`opponent_profiler.profile_opponent` / FSM agent), not this CLI table.
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(SKILL / "scripts")]

from cg.api import OptionType, to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from arena.deck import load_deck_csv
from arena.policy import make_agent
from hand_snapshot import build_board_snapshot
from opening_cards import CARD_NAMES, DARK_BASIC, FROSLASS, MUNKIDORI, SNORUNT
from phase_fsm import compute_phase
from starmie_pilot import (
    _ability_source_id,
    _attack_id,
    _hand_card_id,
    make_starmie_agent,
)

MEGA_FROSLASS = 861
MEGA_STARMIE = 1031
JETTING = 1487
NEBULA = 1488

# Explicit opponent pool — no runtime deck fingerprint / profiler detection.
OPPONENT_MATCHUPS: dict[str, str] = {
    "walrein": "data/decks/walrein_control.csv",
    "mirror": "data/decks/starmie_froslass.csv",
}


def _resolve_deck(path: str) -> list[int]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return load_deck_csv(p)


def _name(cid: int) -> str:
    return CARD_NAMES.get(cid, str(cid))


@dataclass
class TurnSnapshot:
    my_turn: int
    phase: str
    active_id: int
    bench_ids: list[int]
    munk_dark: bool
    froslass_104: bool
    snorunt_line: bool
    synergy_ready: bool


@dataclass
class GameAudit:
    opponent: str
    seed: int
    result: int
    steps: int
    turn_snaps: dict[int, TurnSnapshot] = field(default_factory=dict)
    munk_abilities: list[int] = field(default_factory=list)
    froslass_evolved_turn: int | None = None
    munk_played_turn: int | None = None
    dark_attach_turn: int | None = None
    synergy_turns: list[int] = field(default_factory=list)
    jetting_turns: list[int] = field(default_factory=list)
    starmie_combat_turns: set[int] = field(default_factory=set)
    starmie_attack_turns: set[int] = field(default_factory=set)
    events: list[str] = field(default_factory=list)


def _bench_ids(me) -> list[int]:
    return [int(getattr(p, "id", 0)) for p in (me.bench or []) if p]


def audit_game(
    seed: int,
    deck_a,
    deck_b,
    *,
    opponent: str = "walrein",
    max_steps: int = 700,
) -> GameAudit:
    random.seed(seed)
    agent_a = make_starmie_agent(deck_a)
    agent_b = make_agent(deck_b)
    obs, _ = battle_start(deck_a, deck_b)
    audit = GameAudit(opponent=opponent, seed=seed, result=-1, steps=0)
    last_my_t = -1

    try:
        steps = 0
        while obs["current"]["result"] < 0 and steps < max_steps:
            pi = obs["current"]["yourIndex"]
            agent = agent_a if pi == 0 else agent_b

            if pi == 0:
                oc = to_observation_class(obs)
                board = build_board_snapshot(oc)
                phase = compute_phase(board)
                me = oc.current.players[0]
                bench = _bench_ids(me)
                fro104 = board.froslass_104_on_field
                synergy = (
                    2 <= board.my_turn_number <= 8
                    and fro104
                    and board.munkidori_on_field
                    and board.munkidori_has_dark
                )

                if board.my_turn_number != last_my_t and 2 <= board.my_turn_number <= 8:
                    audit.turn_snaps[board.my_turn_number] = TurnSnapshot(
                        my_turn=board.my_turn_number,
                        phase=phase.primary,
                        active_id=board.active_id,
                        bench_ids=bench,
                        munk_dark=board.munkidori_has_dark,
                        froslass_104=fro104,
                        snorunt_line=board.snorunt_line_on_bench,
                        synergy_ready=synergy,
                    )
                    last_my_t = board.my_turn_number

                if synergy and board.my_turn_number not in audit.synergy_turns:
                    audit.synergy_turns.append(board.my_turn_number)

                if (
                    board.active_is_mega_starmie
                    and board.active_has_water
                    and board.my_turn_number >= 2
                ):
                    audit.starmie_combat_turns.add(board.my_turn_number)

                sel = obs.get("select") or {}
                opts = sel.get("option") or []
                action = agent(obs)

                if opts and action:
                    ch = action[0]
                    if 0 <= ch < len(opts):
                        raw = opts[ch]
                        ot = raw.get("type")
                        mt = board.my_turn_number
                        opt = NS(
                            type=ot,
                            area=raw.get("area"),
                            index=raw.get("index"),
                            attackId=raw.get("attackId"),
                        )
                        if ot == OptionType.ABILITY:
                            src = _ability_source_id(oc, opt, 0)
                            if src == MUNKIDORI and 2 <= mt <= 8:
                                audit.munk_abilities.append(mt)
                                audit.events.append(
                                    f"My-T{mt} ABILITY Adrena-Brain (Munkidori)"
                                )
                        elif ot == OptionType.PLAY and 2 <= mt <= 8:
                            cid = _hand_card_id(oc, opt, 0)
                            if cid == MUNKIDORI and audit.munk_played_turn is None:
                                audit.munk_played_turn = mt
                                audit.events.append(f"My-T{mt} PLAY Munkidori")
                            elif cid == SNORUNT:
                                audit.events.append(f"My-T{mt} PLAY Snorunt")
                        elif ot == OptionType.EVOLVE and 2 <= mt <= 8:
                            hand = me.hand or []
                            idx = raw.get("index", -1)
                            if 0 <= idx < len(hand) and hand[idx]:
                                eid = int(hand[idx].id)
                                if eid == FROSLASS and audit.froslass_evolved_turn is None:
                                    audit.froslass_evolved_turn = mt
                                    audit.events.append(
                                        f"My-T{mt} EVOLVE Snorunt→Froslass (104)"
                                    )
                                elif eid == MEGA_FROSLASS:
                                    audit.events.append(
                                        f"My-T{mt} EVOLVE →Mega Froslass ex (861)"
                                    )
                        elif (
                            ot == OptionType.ATTACH
                            and board.munkidori_on_field
                            and 2 <= mt <= 8
                        ):
                            if not board.munkidori_has_dark and audit.dark_attach_turn is None:
                                audit.dark_attach_turn = mt
                                audit.events.append(f"My-T{mt} ATTACH →Munkidori")
                        elif ot == OptionType.ATTACK:
                            atk = _attack_id(opt)
                            if board.active_is_mega_starmie and atk in (JETTING, NEBULA):
                                audit.starmie_attack_turns.add(mt)
                                label = "Jetting Blow" if atk == JETTING else "Nebula Beam"
                                audit.events.append(f"My-T{mt} ATTACK {label}")
                                if atk == JETTING and 2 <= mt <= 8:
                                    audit.jetting_turns.append(mt)
            else:
                action = agent(obs)

            obs = battle_select(action)
            steps += 1

        audit.steps = steps
        audit.result = obs["current"]["result"]
    finally:
        battle_finish()

    for t, snap in audit.turn_snaps.items():
        if snap.froslass_104 and audit.froslass_evolved_turn is None:
            audit.froslass_evolved_turn = t
    return audit


def _starmie_attack_stats(a: GameAudit) -> tuple[int, int, list[int]]:
    """Returns (combat_turns, attack_turns, missed_turn_list)."""
    combat = sorted(a.starmie_combat_turns)
    attacked = sorted(a.starmie_attack_turns)
    missed = sorted(set(combat) - set(attacked))
    return len(combat), len(attacked), missed


def _pass_criteria(a: GameAudit) -> tuple[bool, list[str]]:
    ok = True
    notes: list[str] = []
    if not a.turn_snaps:
        ok = False
        notes.append("无 My-T2..T8 回合记录")
    if a.froslass_evolved_turn is None:
        ok = False
        notes.append("T2-T8 内未进化 Froslass (104)")
    elif not (2 <= a.froslass_evolved_turn <= 8):
        ok = False
        notes.append(f"Froslass 进化在 My-T{a.froslass_evolved_turn}（超出 T2-T8）")
    if a.munk_played_turn is None and not any(
        s.munk_dark or MUNKIDORI in s.bench_ids for s in a.turn_snaps.values()
    ):
        ok = False
        notes.append("T2-T8 内 Munkidori 未上场")
    if not a.munk_abilities:
        ok = False
        notes.append("T2-T8 内未释放 Adrena-Brain")
    if not a.synergy_turns:
        ok = False
        notes.append("Froslass(104)+Munkidori(暗能) 未同时就绪")
    else:
        notes.append(
            f"联动就绪回合: My-T{min(a.synergy_turns)}..{max(a.synergy_turns)} "
            f"({len(a.synergy_turns)} 回合)"
        )
    if a.munk_abilities:
        notes.append(
            f"Adrena-Brain 释放 {len(a.munk_abilities)} 次 @ My-T{a.munk_abilities}"
        )
    combat_n, atk_n, missed = _starmie_attack_stats(a)
    if combat_n:
        notes.append(
            f"大海星 AGGRESSION/HARVEST 战斗回合 {combat_n}，出招 {atk_n}，漏攻 {combat_n - atk_n}"
        )
        if missed:
            notes.append(f"  漏攻 My-T{missed}")
    return ok, notes


def _result_label(result: int) -> str:
    return "胜" if result == 0 else ("负" if result == 1 else "?")


def _opponent_summary(audits: list[GameAudit]) -> list[str]:
    by_opp: dict[str, list[GameAudit]] = {}
    for a in audits:
        by_opp.setdefault(a.opponent, []).append(a)

    lines = [
        "## 对手卡组汇总（CLI 指定，无 fingerprint 检测）",
        "",
        "| 对手类型 | 卡组文件 | 局数 | 胜 | 负 | 联动PASS | Munk能力均值 | 大海星出招 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for opp in sorted(by_opp):
        games = by_opp[opp]
        wins = sum(1 for g in games if g.result == 0)
        losses = sum(1 for g in games if g.result == 1)
        pass_n = sum(1 for g in games if _pass_criteria(g)[0])
        avg_ab = sum(len(g.munk_abilities) for g in games) / max(1, len(games))
        combat_total = sum(len(g.starmie_combat_turns) for g in games)
        attack_total = sum(len(g.starmie_attack_turns) for g in games)
        atk_rate = f"{attack_total}/{combat_total}" if combat_total else "—"
        deck_path = OPPONENT_MATCHUPS.get(opp, "?")
        lines.append(
            f"| `{opp}` | `{deck_path}` | {len(games)} | {wins} | {losses} | "
            f"{pass_n}/{len(games)} | {avg_ab:.1f} | {atk_rate} |"
        )
    lines.append("")
    lines.append("> **胜负**：Player 0（我方 Starmie pilot）奖品拿完=胜；与联动 PASS 无关。")
    lines.append("> **大海星出招率**：Active=1031 且附水 的 My-T2+ 回合中，实际 Jetting/Nebula 次数。")
    return lines


def _kpi_summary(audits: list[GameAudit]) -> list[str]:
    """Global KPI vs targets: Munkidori combo ~15%, starmie attack ≥85%."""
    n = len(audits)
    pass_n = sum(1 for a in audits if _pass_criteria(a)[0])
    combo_rate = 100.0 * pass_n / max(1, n)
    combat_total = sum(len(g.starmie_combat_turns) for g in audits)
    attack_total = sum(len(g.starmie_attack_turns) for g in audits)
    atk_rate = 100.0 * attack_total / max(1, combat_total)
    combo_ok = 10.0 <= combo_rate <= 25.0
    atk_ok = atk_rate >= 85.0 if combat_total else False
    lines = [
        "## KPI 汇总（目标：愿增猿联动 PASS ~15%，大海星出招率 ≥85%）",
        "",
        f"| 指标 | 结果 | 目标 | 状态 |",
        f"|---|---:|---:|:---:|",
        f"| 联动 PASS 率 | {pass_n}/{n} ({combo_rate:.1f}%) | ~15% | {'✓' if combo_ok else '✗'} |",
        f"| 大海星战斗出招率 | {attack_total}/{combat_total} ({atk_rate:.1f}%) | ≥85% | "
        f"{'✓' if atk_ok else ('—' if not combat_total else '✗')} |",
        "",
    ]
    return lines


def format_report(audits: list[GameAudit], *, opponents: list[str]) -> str:
    lines = [
        "# 能力释放 & 雪妖女+愿增猿联动 — 对局审计",
        f"# generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## 测试方法",
        "- 对手卡组由 `--opponent` **显式指定**（见 `OPPONENT_MATCHUPS`）",
        "- **不使用** `opponent_profiler` / 场上 fingerprint 推断对手类型",
        f"- 本次对手池: {', '.join(f'`{o}`' for o in opponents)}",
        "",
        "## 审计标准（My-T2 .. My-T8）",
        "- Froslass `[104]` 在场上（Active 或 Bench）",
        "- Munkidori `[112]` 在场且附有暗能量/Prism",
        "- 每回合优先 `ABILITY` Adrena-Brain（HR-2）",
        "- Freezing Shroud 为引擎被动 Checkup，以 Froslass 104 在场为必要条件",
        "- 大海星 ex：Active=1031 且附水 的 My-T2+ 回合应 Jetting/Nebula 出招（HR-6）",
        "",
    ]
    lines.extend(_kpi_summary(audits))
    lines.extend(_opponent_summary(audits))

    by_opp: dict[str, list[GameAudit]] = {}
    for a in audits:
        by_opp.setdefault(a.opponent, []).append(a)

    total_pass = 0
    for opp in sorted(by_opp):
        games = by_opp[opp]
        opp_pass = sum(1 for g in games if _pass_criteria(g)[0])
        total_pass += opp_pass
        lines.append(f"## 对手 `{opp}` — 明细 ({opp_pass}/{len(games)} PASS)")
        lines.append("")
        lines.append(
            "| seed | 结果 | 步数 | Froslass104 | Munk能力 | 联动回合 | PASS |"
        )
        lines.append("|---:|---|---:|---|---:|---|:---:|")
        for a in games:
            ok, _ = _pass_criteria(a)
            fro = f"T{a.froslass_evolved_turn}" if a.froslass_evolved_turn else "—"
            syn = f"{len(a.synergy_turns)}" if a.synergy_turns else "0"
            lines.append(
                f"| {a.seed} | {_result_label(a.result)} | {a.steps} | {fro} | "
                f"{len(a.munk_abilities)} | {syn} | {'✓' if ok else '✗'} |"
            )
        lines.append("")

        for a in games:
            ok, notes = _pass_criteria(a)
            lines.append(f"### `{opp}` seed={a.seed} {'PASS' if ok else 'FAIL'}")
            for n in notes:
                lines.append(f"- {n}")
            lines.append("")
            lines.append("#### 回合快照 (My-T2..T8)")
            for t in sorted(a.turn_snaps):
                s = a.turn_snaps[t]
                bench = ", ".join(_name(x) for x in s.bench_ids) or "(空)"
                lines.append(
                    f"- My-T{t} `{s.phase}` active={_name(s.active_id)} bench=[{bench}] "
                    f"fro104={s.froslass_104} munk_dark={s.munk_dark} synergy={s.synergy_ready}"
                )
            if a.events:
                lines.append("")
                lines.append("#### 关键动作")
                for ev in a.events:
                    lines.append(f"- {ev}")
            lines.append("")

    lines.append(f"**总联动通过率: {total_pass}/{len(audits)}**")
    return "\n".join(lines)


def _resolve_opponents(names: list[str]) -> list[str]:
    if not names or names == ["all"]:
        return sorted(OPPONENT_MATCHUPS)
    unknown = [n for n in names if n not in OPPONENT_MATCHUPS]
    if unknown:
        valid = ", ".join(sorted(OPPONENT_MATCHUPS))
        raise SystemExit(f"未知对手类型: {unknown}. 可选: {valid}, all")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(42, 52)))
    parser.add_argument(
        "--opponent",
        dest="opponents",
        nargs="+",
        default=["walrein"],
        metavar="TYPE",
        help=(
            "对手卡组类型（可多个或 all）。"
            f"可选: {', '.join(sorted(OPPONENT_MATCHUPS))}, all"
        ),
    )
    parser.add_argument(
        "-o",
        type=Path,
        default=None,
        help="输出日志路径（默认 logs/ability_synergy_audit_<opponents>.log）",
    )
    args = parser.parse_args()

    opponents = _resolve_opponents(args.opponents)
    deck_a = _resolve_deck("data/decks/starmie_froslass.csv")

    audits: list[GameAudit] = []
    for opp in opponents:
        deck_b = _resolve_deck(OPPONENT_MATCHUPS[opp])
        for seed in args.seeds:
            audits.append(audit_game(seed, deck_a, deck_b, opponent=opp))

    out = args.o
    if out is None:
        tag = opponents[0] if len(opponents) == 1 else "multi"
        out = SKILL / "logs" / f"ability_synergy_audit_{tag}.log"

    report = format_report(audits, opponents=opponents)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    pass_n = sum(1 for a in audits if _pass_criteria(a)[0])
    combat_total = sum(len(g.starmie_combat_turns) for g in audits)
    attack_total = sum(len(g.starmie_attack_turns) for g in audits)
    atk_pct = 100.0 * attack_total / max(1, combat_total)
    print(
        f"\nWrote {out} — {pass_n}/{len(audits)} PASS ({100*pass_n/len(audits):.1f}%) "
        f"| starmie atk {attack_total}/{combat_total} ({atk_pct:.1f}%) "
        f"across {len(opponents)} opponent(s)"
    )


if __name__ == "__main__":
    main()
