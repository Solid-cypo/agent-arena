# Source Generated with Decompyle++
# File: ingest_expert_logs.cpython-310.pyc (Python 3.10)

"""Ingest expert gold OPENING logs → per-step (state, action) trajectories.

Two paths (roadmap §5.7–5.8):
  approved : re-run simulate_opening(seed) with a snapshotting state subclass.
             Zero parse risk — the planner's Action[] chain IS the trajectory.
  edited   : LOG-ANCHORED replayer. State is initialized from the log's stated
             opening hand + prizes (NOT the seed's shuffle), and each turn is
             replayed strictly from the log's stated ops + 备注 results. No
             seed deck order is used. Two integrity gates reject a log:
               (L) search/draw legality — every retrieved card (抽牌, Fan Call,
                   Run Away, Meowth, Poffin, Ultra Ball, Poké Pad, Hilda,
                   Crispin, Salvatore, Lillie, Judge; Night Stretcher checks
                   the discard pile) must be in the deck at that moment, not in
                   prizes/discard/hand/board. Playing a trainer not in hand is
                   also flagged.
               (C) within-turn coherence — after a turn's ops the running
                   hand/board must match the log's stated 回合结束 hand/board.
             Logs failing either gate (or with an unparseable op) are routed to
             rejected.jsonl for expert QC.

Outputs (under data/opening_sft/):
  traj.jsonl     one line per ingested game: meta + list of per-step records
  rejected.jsonl one line per skipped game: file, reason, detail
"""
from __future__ import annotations
import argparse
import copy
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
SKILL = SCRIPTS.parent
DEFAULT_DIR = SKILL / 'logs' / 'review_manual' / 'expert_gold_v1'
APPROVED_DIR = SKILL / 'logs' / 'review_manual' / 'expert_gold_v1_approved'
OUT_DIR = ROOT / 'data' / 'opening_sft'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from arena.deck import load_deck_csv
from opening_cards import BASIC_IDS, CARD_NAMES, CRISPIN, DUDUNSPARCE, DUNSPARCE_A, DUNSPARCE_B, ENERGY_IDS, HILDA, JUDGE, LILLIE, MEGA_FROSLASS, MEGA_STARMIE, MEOWTH_EX, POFFIN, POKE_PAD, SALVATOR, STARYU, SUPPORTER_IDS, SWITCH, ULTRA_BALL, BOSS_ORDERS, WATER_BASIC, name
from opening_log_formatter import CARD_NAME_ZH, KIND_ZH, localize_detail
from opening_planner import diagnose_gaps, plan_and_execute_turn
from opening_state import Action, OpeningGameState, Pokemon
from setup_planner import run_setup
from simulate_opening import mulligan_until_basic, shuffle_deck
import validate_expert_gold as vg
DECK_PATH = ROOT / 'data' / 'decks' / 'starmie_froslass.csv'
EN_TO_ZH = CARD_NAME_ZH
ZH_TO_EN: 'dict[str, str]' = { }
for _en, _zh in EN_TO_ZH.items():
    ZH_TO_EN.setdefault(_zh, _en)
ZH_BASE_TO_EN: 'dict[str, str]' = { }
for _en, _zh in EN_TO_ZH.items():
    _base = re.sub('[（(].*?[)）]\\s*$', '', _zh).strip()
    if _base:
        ZH_BASE_TO_EN.setdefault(_base, _en)
_ZH_COMPACT_TO_EN: 'dict[str, str]' = { }
for _en, _zh in EN_TO_ZH.items():
    _ZH_COMPACT_TO_EN.setdefault(_zh.replace(' ', ''), _en)
ENERGY_ZH_TO_ID = {
    '基本水能量': 3,
    '基本恶能量': 7,
    '棱镜能量': 16,
    '引火能量': 17 }
ID_BY_EN: 'dict[str, list[int]]' = { }
for _cid, _en in CARD_NAMES.items():
    ID_BY_EN.setdefault(_en, []).append(_cid)
BASIC_EN: 'frozenset[str]' = frozenset((lambda .0: 