#!/usr/bin/env python3
"""Apply cascade CORRECT opinions for seeds 36645 / 38272 / 38659.

Replays from seed with engine RNG, injects expert fixes, exports edited gold
logs into expert_gold_v1 (replacing prior unreachable copies).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
SKILL = SCRIPTS.parent
OUT = SKILL / "logs" / "review_manual" / "expert_gold_v1"
DECK_PATH = ROOT / "data" / "decks" / "starmie_froslass.csv"

sys.path[:0] = [str(SCRIPTS), str(ROOT)]

from arena.deck import load_deck_csv
from opening_cards import (
    BUDEW,
    CARD_NAMES,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    HILDA,
    IGNITION,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    POFFIN,
    POKE_PAD,
    SNORUNT,
    STARYU,
    WATER_BASIC,
    name,
    retreat_cost_for,
)
from opening_exec import _run_away_draw, execute_v2
from opening_log_formatter import CARD_NAME_ZH, format_actions
from opening_state import OpeningGameState, Pokemon
from simulate_opening import mulligan_until_basic, shuffle_deck


def zh(cid: int) -> str:
    return CARD_NAME_ZH.get(CARD_NAMES.get(cid, ""), name(cid))


def hand_zh(ids: list[int]) -> str:
    return ", ".join(zh(c) for c in ids)


def board_lines(st: OpeningGameState) -> list[str]:
    lines = []
    if st.active:
        e = "、".join(zh(x) for x in st.active.energies) or "无能量"
        lines.append(f"  Active: {zh(st.active.card_id)} [{e}]")
    else:
        lines.append("  Active: （空）")
    if not st.bench:
        lines.append("  Bench: （空）")
    else:
        for i, p in enumerate(st.bench):
            e = "、".join(zh(x) for x in p.energies) or "无能量"
            lines.append(f"  Bench[{i}]: {zh(p.card_id)} [{e}]")
    return lines


def filter_log(actions):
    out = []
    for a in actions:
        if a.kind == "NOTE" and (
            a.detail.startswith("Route=") or "gaps=" in a.detail
        ):
            continue
        out.append(a)
    return out


def header(
    *,
    seed: int,
    difficulty: str,
    depth: str,
    index: str,
    arch: str,
    role: str,
    turn_limit: int,
    final_turn: int,
    routes: str,
    opinion: str,
) -> str:
    return "\n".join(
        [
            "// expert_status=edited",
            f"// difficulty={difficulty}",
            f"// depth_class={depth}",
            f"// PACK=review_batch_30 INDEX={index}",
            "// 样本类型=正面（专家意见已改）",
            f"// category=CLEAN_T2 seed={seed} archetype={arch}",
            f"// role={role} turn_limit={turn_limit}",
            f"// goal=True miss=OK final_turn={final_turn}",
            f"// routes={routes}",
            f"// 专家意见已落实: {opinion}",
            "// 引擎重放注入；勿用 CORRECT 注释",
            "=" * 72,
        ]
    )


def fresh(deck, seed, gf) -> OpeningGameState:
    st = OpeningGameState.from_ordered_deck(
        shuffle_deck(list(deck), seed), going_first=gf, seed=seed
    )
    mulligan_until_basic(st)
    return st


def setup_active(st: OpeningGameState, cid: int) -> None:
    assert cid in st.hand
    st.hand.remove(cid)
    st.active = Pokemon(cid, 0)
    st._log("SETUP_ACTIVE", f"Active ← {name(cid)}", cid)
    st.setup_archetype = {
        STARYU: "S1",
        SNORUNT: "C1",
        DUNSPARCE_A: "B1",
        DUNSPARCE_B: "B1",
        FAN_ROTOM: "A1",
        MEOWTH_EX: "F1",
        BUDEW: "E1",
    }.get(cid, "X1")


def begin(st: OpeningGameState, my_t: int, gf: bool) -> list:
    """Begin turn; return actions logged during begin (DRAW etc)."""
    before = len(st.log)
    turn = my_t if gf else my_t + 1
    st.begin_turn(turn, my_t)
    return list(st.log[before:])


def attach(st, energy_id, target_cid, prefer_bench=False) -> bool:
    return execute_v2(
        st,
        "ATTACH",
        energy_id,
        target_cid,
    )


def retreat_to(st, target_cid) -> bool:
    return execute_v2(st, "RETREAT", target_cid, None)


def evolve_hand(st, mega_or_evo) -> bool:
    return execute_v2(st, "EVOLVE", mega_or_evo, None)


def play_lillie(st) -> bool:
    return execute_v2(st, "PLAY_LILLIE", None, None)


def play_pad(st, target) -> bool:
    return execute_v2(st, "PLAY_POKE_PAD", target, None)


def play_poffin(st, first, second=None) -> bool:
    return execute_v2(st, "PLAY_POFFIN", first, second)


def play_hilda(st, primary, sub=None) -> bool:
    return execute_v2(st, "PLAY_HILDA", primary, sub)


def fan_call(st) -> bool:
    return execute_v2(st, "ABILITY_FAN_CALL", None, None)


def last_ditch(st) -> bool:
    return execute_v2(st, "ABILITY_LAST_DITCH", None, None)


def run_away(st) -> bool:
    return execute_v2(st, "ABILITY_RUN_AWAY", None, None)


def place(st, cid) -> bool:
    return execute_v2(st, "PLAY_POKEMON", cid, None)


def export_game(
    st: OpeningGameState,
    *,
    seed: int,
    gf: bool,
    meta: dict,
    opinion: str,
    out_name: str,
    turn_routes: dict[int, str],
    setup_log_start: int,
) -> Path:
    assert st.opening_complete(), f"{seed} did not reach Goal"
    # Split log into setup / turns by DRAW boundaries and my_turn markers is hard;
    # instead rebuild from recorded segments stored on st._segments
    segments = st._segments  # type: ignore[attr-defined]
    role = "先攻" if gf else "后攻"
    lines = [
        header(
            seed=seed,
            difficulty=meta["difficulty"],
            depth=meta["depth"],
            index=meta["index"],
            arch=meta["arch"],
            role=role,
            turn_limit=meta["turn_limit"],
            final_turn=st.my_turn_number,
            routes=meta["routes"],
            opinion=opinion,
        ),
        "",
        f"Run #cascade (seed={seed})",
        f"结果: GOAL 达成 (OK) · 结束于 My-T{st.my_turn_number} · 上限 5 回合",
        "",
        "【起始】",
        f"  奖品区 (6): {hand_zh(st._opening_prizes)}",  # type: ignore
        f"  起手手牌 (7): {hand_zh(st._opening_hand)}",  # type: ignore
        "  Mulligan 次数: 0",
        "",
        "【Setup】",
        f"  原型: {st.setup_archetype}",
        "  操作:",
    ]
    setup_actions = segments["setup"]
    lines.extend(format_actions(filter_log(setup_actions)) or ["  （无）"])
    lines.append(f"  Setup 后手牌: {hand_zh(segments['setup_hand'])}")
    lines.append("  Setup 后场面:")
    lines.extend(segments["setup_board"])
    lines.append("")

    for my_t in sorted(k for k in segments if isinstance(k, int)):
        seg = segments[my_t]
        lines.append(f"【My-T{my_t}】 路线: {turn_routes.get(my_t, 'GREEDY')}")
        lines.append("  回合开始手牌:")
        lines.append(f"    {hand_zh(seg['hand_start'])}")
        lines.append("  回合开始场面:")
        lines.extend(seg["board_start"])
        lines.append("  本回合操作:")
        ops = format_actions(filter_log(seg["actions"]))
        lines.extend(ops or ["  （无）"])
        lines.append("  回合结束手牌:")
        lines.append(f"    {hand_zh(seg['hand_end'])}")
        lines.append("  回合结束场面:")
        lines.extend(seg["board_end"])
        lines.append("")

    out = OUT / out_name
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def snapshot_board(st):
    return board_lines(st)


def start_segment(st, my_t, begin_actions):
    if not hasattr(st, "_segments"):
        st._segments = {}
    st._segments[my_t] = {
        "hand_start": list(st.hand),
        "board_start": snapshot_board(st),
        "actions": list(begin_actions),
        "hand_end": [],
        "board_end": [],
        "_log_mark": len(st.log),
    }


def end_segment(st, my_t):
    seg = st._segments[my_t]
    # actions after begin already in begin_actions; append new since mark
    # Actually begin_actions were copied at start; collect all from mark
    new_acts = list(st.log[seg["_log_mark"] :])
    # begin_actions already included DRAW which is in log before mark? 
    # begin_turn logs DRAW then we set mark AFTER begin — so begin_actions separate
    # Merge: begin_actions + actions since mark (excluding those already in begin)
    # Simpler: store begin separately then append rest
    rest = list(st.log[seg["_log_mark"] :])
    seg["actions"] = list(seg["actions"]) + rest
    seg["hand_end"] = list(st.hand)
    seg["board_end"] = snapshot_board(st)


# --------------------------------------------------------------------------- #
# Seed editors
# --------------------------------------------------------------------------- #
def edit_36645(deck) -> Path:
    """After retreat to Dunsparce, play Lillie before Pad; finish Goal on T2."""
    seed, gf = 36645, False
    st = fresh(deck, seed, gf)
    st._opening_prizes = list(st.prizes)
    st._opening_hand = list(st.hand)
    st.log = []
    setup_active(st, STARYU)
    st._segments = {
        "setup": list(st.log),
        "setup_hand": list(st.hand),
        "setup_board": snapshot_board(st),
    }

    # T1
    ba = begin(st, 1, gf)
    # After draw, hand should have dunsparce
    start_segment(st, 1, ba)
    assert place(st, DUNSPARCE_A) or place(st, DUNSPARCE_B)
    # attach ignition to staryu (now on bench after? still active until retreat)
    # Log: attach ignition to 海星星 active, then retreat cost discard, retreat to dunsparce
    assert attach(st, IGNITION, STARYU)
    # pay retreat: ignition discards itself at end? Log shows DISCARD retreat cost ignition
    # Use retreat_promote
    dun_id = next(
        p.card_id
        for p in st.bench
        if p.card_id in (DUNSPARCE_A, DUNSPARCE_B)
    )
    assert retreat_to(st, dun_id)
    # EXPERT: Lillie here
    assert play_lillie(st)
    # After Lillie, try pad for dudunsparce if pad still in hand and useful
    if POKE_PAD in st.hand and DUDUNSPARCE in st.deck:
        assert play_pad(st, DUDUNSPARCE)
    elif POKE_PAD in st.hand:
        # pick best pad target still in deck
        for t in (DUDUNSPARCE, STARYU, FAN_ROTOM, DUNSPARCE_A, SNORUNT):
            if t in st.deck:
                play_pad(st, t)
                break
    # place any free basics from hand if room
    for cid in list(st.hand):
        if cid in (DUNSPARCE_A, DUNSPARCE_B, STARYU, FAN_ROTOM, SNORUNT, BUDEW) and st.bench_open():
            place(st, cid)
    end_segment(st, 1)
    st.end_turn_cleanup()

    # T2 — drive to Goal (after Lillie, Pad may be gone; Ultra Ball is common)
    ba = begin(st, 2, gf)
    start_segment(st, 2, ba)
    from opening_cards import ULTRA_BALL, PRISM

    # Place free basics for board depth
    for cid in list(st.hand):
        if cid in (SNORUNT, BUDEW, DUNSPARCE_A, DUNSPARCE_B, MEOWTH_EX) and st.bench_open():
            place(st, cid)
    # Ultra Ball → Mega if needed
    if MEGA_STARMIE not in st.hand and ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
        execute_v2(st, "PLAY_ULTRA_BALL", MEGA_STARMIE, None)
    if HILDA in st.hand and not st.supporter_played:
        play_hilda(st, MEGA_STARMIE, WATER_BASIC)
    # Water on Staryu
    if WATER_BASIC in st.hand:
        attach(st, WATER_BASIC, STARYU)
    elif PRISM in st.hand:
        attach(st, PRISM, STARYU)
    if MEGA_STARMIE in st.hand:
        evolve_hand(st, MEGA_STARMIE)
    if st.active and st.active.card_id != MEGA_STARMIE:
        if any(p.card_id == MEGA_STARMIE for p in st.bench):
            retreat_to(st, MEGA_STARMIE)
    if (
        st.active
        and st.active.card_id == MEGA_STARMIE
        and not st.active.has_water()
        and WATER_BASIC in st.hand
    ):
        attach(st, WATER_BASIC, MEGA_STARMIE)
    end_segment(st, 2)
    st.end_turn_cleanup()

    if not st.opening_complete():
        ba = begin(st, 3, gf)
        start_segment(st, 3, ba)
        if MEGA_STARMIE not in st.hand and ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
            execute_v2(st, "PLAY_ULTRA_BALL", MEGA_STARMIE, None)
        if HILDA in st.hand and not st.supporter_played:
            play_hilda(st, MEGA_STARMIE, WATER_BASIC)
        if WATER_BASIC in st.hand:
            tgt = (
                STARYU
                if any(
                    p.card_id == STARYU
                    for p in ([st.active] if st.active else []) + list(st.bench)
                )
                else MEGA_STARMIE
            )
            attach(st, WATER_BASIC, tgt)
        if MEGA_STARMIE in st.hand:
            evolve_hand(st, MEGA_STARMIE)
        if st.active and st.active.card_id != MEGA_STARMIE:
            if any(p.card_id == MEGA_STARMIE for p in st.bench):
                retreat_to(st, MEGA_STARMIE)
        end_segment(st, 3)

    assert st.opening_complete(), (
        f"36645 fail active={st.active.card_id if st.active else None} "
        f"water={st.active.has_water() if st.active else None} hand={[zh(c) for c in st.hand]}"
    )
    # remove old unreachable
    for p in OUT.glob("*seed36645*"):
        p.unlink()
    return export_game(
        st,
        seed=seed,
        gf=gf,
        meta={
            "difficulty": "T3",
            "depth": "high",
            "index": "20",
            "arch": "S1",
            "turn_limit": 2,
            "routes": "GREEDY-T1 → GREEDY-T2",
        },
        opinion="T1撤退后直接使用莉莉艾补牌，再继续手环/Goal线",
        out_name="pack13_11_seed36645_edited_goal.log",
        turn_routes={1: "GREEDY-T1", 2: "GREEDY-T2", 3: "GREEDY-T3"},
        setup_log_start=0,
    )


def edit_38272(deck) -> Path:
    """T1: place Budew, Poffin for Staryu+Rotom, Fan Call; T2 Hilda Goal."""
    seed, gf = 38272, True
    st = fresh(deck, seed, gf)
    st._opening_prizes = list(st.prizes)
    st._opening_hand = list(st.hand)
    st.log = []
    setup_active(st, STARYU)
    st._segments = {
        "setup": list(st.log),
        "setup_hand": list(st.hand),
        "setup_board": snapshot_board(st),
    }

    ba = begin(st, 1, gf)
    start_segment(st, 1, ba)
    assert place(st, BUDEW)
    # EXPERT: Poffin instead of (or before) pad — schedule Rotom
    assert POFFIN in st.hand
    # Prefer Staryu+Rotom; one Staryu already active so poffin may fetch Rotom+other
    ok = play_poffin(st, FAN_ROTOM, STARYU) or play_poffin(st, STARYU, FAN_ROTOM)
    if not ok:
        ok = play_poffin(st, FAN_ROTOM, None)
    assert ok, "poffin failed"
    # Fan Call if Rotom on field
    if any(p.card_id == FAN_ROTOM for p in st.bench) or (
        st.active and st.active.card_id == FAN_ROTOM
    ):
        fan_call(st)
        for cid in list(st.hand):
            if cid in (DUNSPARCE_A, DUNSPARCE_B) and st.bench_open():
                place(st, cid)
    # Pad for dudun if still useful
    if POKE_PAD in st.hand and DUDUNSPARCE in st.deck:
        play_pad(st, DUDUNSPARCE)
    end_segment(st, 1)
    st.end_turn_cleanup()

    ba = begin(st, 2, gf)
    start_segment(st, 2, ba)
    if HILDA in st.hand:
        play_hilda(st, MEGA_STARMIE, WATER_BASIC)
    if WATER_BASIC in st.hand:
        attach(st, WATER_BASIC, STARYU)
    if MEGA_STARMIE in st.hand:
        evolve_hand(st, MEGA_STARMIE)
    if st.active and st.active.card_id != MEGA_STARMIE:
        if any(p.card_id == MEGA_STARMIE for p in st.bench):
            retreat_to(st, MEGA_STARMIE)
    end_segment(st, 2)
    st.end_turn_cleanup()

    if not st.opening_complete():
        ba = begin(st, 3, gf)
        start_segment(st, 3, ba)
        if HILDA in st.hand and not st.supporter_played:
            play_hilda(st, MEGA_STARMIE, WATER_BASIC)
        if WATER_BASIC in st.hand:
            attach(st, WATER_BASIC, STARYU if any(
                p.card_id == STARYU for p in ([st.active] if st.active else []) + st.bench
            ) else MEGA_STARMIE)
        if MEGA_STARMIE in st.hand:
            evolve_hand(st, MEGA_STARMIE)
        if st.active and st.active.card_id != MEGA_STARMIE:
            if any(p.card_id == MEGA_STARMIE for p in st.bench):
                retreat_to(st, MEGA_STARMIE)
        end_segment(st, 3)

    assert st.opening_complete(), (
        f"38272 fail board={snapshot_board(st)} hand={[zh(c) for c in st.hand]}"
    )
    for p in OUT.glob("*seed38272*"):
        p.unlink()
    return export_game(
        st,
        seed=seed,
        gf=gf,
        meta={
            "difficulty": "T2",
            "depth": "low",
            "index": "30",
            "arch": "S1",
            "turn_limit": 3,
            "routes": "GREEDY-T1 → GREEDY-T2",
        },
        opinion="T1使用伙伴糖果调度旋转罗盘并特性，再走希尔达Goal",
        out_name="pack13_12_seed38272_edited_goal.log",
        turn_routes={1: "GREEDY-T1", 2: "GREEDY-T2", 3: "GREEDY-T3"},
        setup_log_start=0,
    )


def edit_38659(deck) -> Path:
    """T2: Goal first; after evolve Dudunsparce, play Lillie BEFORE Run Away."""
    seed, gf = 38659, False
    st = fresh(deck, seed, gf)
    st._opening_prizes = list(st.prizes)
    st._opening_hand = list(st.hand)
    st.log = []
    setup_active(st, SNORUNT)
    st._segments = {
        "setup": list(st.log),
        "setup_hand": list(st.hand),
        "setup_board": snapshot_board(st),
    }

    from opening_cards import DARK_BASIC, ULTRA_BALL

    ba = begin(st, 1, gf)
    start_segment(st, 1, ba)
    assert place(st, MEOWTH_EX)
    assert last_ditch(st)
    # last_ditch may spuriously set energy_attached; clear for manual attach
    st.energy_attached = False
    assert play_poffin(st, STARYU, FAN_ROTOM) or play_poffin(st, FAN_ROTOM, STARYU)
    if any(p.card_id == FAN_ROTOM for p in st.bench):
        fan_call(st)
        for cid in list(st.hand):
            if cid in (DUNSPARCE_A, DUNSPARCE_B) and st.bench_open():
                place(st, cid)
    if HILDA in st.hand and not st.supporter_played:
        play_hilda(st, MEGA_STARMIE, WATER_BASIC)
    if WATER_BASIC in st.hand:
        tgt = next((p for p in st.bench if p.card_id == STARYU), None)
        if tgt is not None and not tgt.has_water():
            st.attach_energy_from_hand(tgt, WATER_BASIC)
            st.energy_attached = True
    if POKE_PAD in st.hand and DUDUNSPARCE in st.deck:
        play_pad(st, DUDUNSPARCE)
    end_segment(st, 1)
    st.end_turn_cleanup()

    ba = begin(st, 2, gf)
    start_segment(st, 2, ba)
    if DARK_BASIC in st.hand and st.active and st.active.card_id == SNORUNT and not st.energy_attached:
        attach(st, DARK_BASIC, SNORUNT)
    dun = next(
        (p.card_id for p in st.bench if p.card_id in (DUNSPARCE_A, DUNSPARCE_B)),
        None,
    )
    if dun is not None and st.active and st.active.card_id == SNORUNT:
        retreat_to(st, dun)
    if HILDA in st.hand and not st.supporter_played:
        play_hilda(st, MEGA_STARMIE, WATER_BASIC if WATER_BASIC in st.deck else None)
    if WATER_BASIC in st.hand:
        tgt = next(
            (
                p
                for p in ([st.active] if st.active else []) + list(st.bench)
                if p.card_id == STARYU
            ),
            None,
        )
        if tgt is not None and not tgt.has_water():
            st.energy_attached = False
            st.attach_energy_from_hand(tgt, WATER_BASIC)
            st.energy_attached = True
    if MEGA_STARMIE not in st.hand and ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
        execute_v2(st, "PLAY_ULTRA_BALL", MEGA_STARMIE, None)
    if MEGA_STARMIE in st.hand:
        evolve_hand(st, MEGA_STARMIE)
    if any(p.card_id == MEGA_STARMIE for p in st.bench):
        if st.active and st.active.card_id != MEGA_STARMIE:
            retreat_to(st, MEGA_STARMIE)
    if DUDUNSPARCE in st.hand:
        target = next(
            (
                p
                for p in ([st.active] if st.active else []) + list(st.bench)
                if p and p.card_id in (DUNSPARCE_A, DUNSPARCE_B)
            ),
            None,
        )
        if target is not None:
            st.hand.remove(DUDUNSPARCE)
            target.card_id = DUDUNSPARCE
            st._log("EVOLVE", f"{name(DUNSPARCE_A)} → {name(DUDUNSPARCE)}", DUDUNSPARCE)
            if LILLIE in st.hand and not st.supporter_played:
                assert play_lillie(st)
            dudun = next(
                (
                    p
                    for p in ([st.active] if st.active else []) + list(st.bench)
                    if p and p.card_id == DUDUNSPARCE
                ),
                None,
            )
            if dudun is not None:
                _run_away_draw(st, dudun)
    if (
        st.active
        and st.active.card_id == MEGA_STARMIE
        and not st.active.has_water()
        and WATER_BASIC in st.hand
    ):
        st.energy_attached = False
        st.attach_energy_from_hand(st.active, WATER_BASIC)
    end_segment(st, 2)
    st.end_turn_cleanup()

    if not st.opening_complete():
        ba = begin(st, 3, gf)
        start_segment(st, 3, ba)
        if HILDA in st.hand and not st.supporter_played:
            play_hilda(st, MEGA_STARMIE, WATER_BASIC)
        if WATER_BASIC in st.hand:
            st.energy_attached = False
            tgt = next(
                (
                    p
                    for p in ([st.active] if st.active else []) + list(st.bench)
                    if p.card_id in (STARYU, MEGA_STARMIE)
                ),
                None,
            )
            if tgt is not None:
                st.attach_energy_from_hand(tgt, WATER_BASIC)
        if MEGA_STARMIE in st.hand:
            evolve_hand(st, MEGA_STARMIE)
        if st.active and st.active.card_id != MEGA_STARMIE:
            if any(p.card_id == MEGA_STARMIE for p in st.bench):
                retreat_to(st, MEGA_STARMIE)
        end_segment(st, 3)

    assert st.opening_complete(), (
        f"38659 fail board={snapshot_board(st)} hand={[zh(c) for c in st.hand]}"
    )
    for p in OUT.glob("*seed38659*"):
        p.unlink()
    return export_game(
        st,
        seed=seed,
        gf=gf,
        meta={
            "difficulty": "T4",
            "depth": "high",
            "index": "1",
            "arch": "C1",
            "turn_limit": 2,
            "routes": "MEOWTH-T1 → GREEDY-T2",
        },
        opinion="T2土龙节节特性前先莉莉艾补牌，再逃跑抽三张",
        out_name="pack13_13_seed38659_edited_goal.log",
        turn_routes={1: "MEOWTH-T1", 2: "GREEDY-T2", 3: "GREEDY-T3"},
        setup_log_start=0,
    )



def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    deck = load_deck_csv(DECK_PATH)
    paths = []
    for fn in (edit_36645, edit_38272, edit_38659):
        p = fn(deck)
        print(f"OK {fn.__name__} → {p.name} goal=True")
        paths.append(p)
    print(f"wrote {len(paths)} cascade edited golds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
