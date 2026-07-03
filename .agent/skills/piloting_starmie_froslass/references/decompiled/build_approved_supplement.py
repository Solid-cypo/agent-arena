# Source Generated with Decompyle++
# File: build_approved_supplement.cpython-310.pyc (Python 3.10)

'''Build a difficulty-stratified `approved` supplementary positive set for SFT.

Approved = planner reaches OPENING Goal by My-T2 (final_turn <= 2) with zero
rule violations. The expert does NOT edit steps — they only confirm — so these
are cheap positive samples. The ingest pipeline re-runs the seed to materialise
the exact (state, action) trajectory; this script only emits the human-readable
log + `// expert_status=approved` header for QC.

Difficulty stratification (the "route depth" curriculum):
  The OPENING goal needs three target elements — Staryu (g1), Water Energy
  (g2), Mega Starmie ex (g3) — each acquirable via several equivalent paths.
  Difficulty = number of DISTINCT acquisition methods chained to assemble them:
    T1 (1): one direct search   — Poké Pad / Poffin / Hilda / Lillie / Ultra Ball
    T2 (2): ability-into-search — Meowth ex → supporter, Fan Call → recover, …
    T3 (3): ball/double-chain  — Ultra Ball → Meowth → Hilda/Crispin, …
    T4 (4+): Run Away draw chain or any ≥4-method chain
  Pure deployment ops (ATTACH / RETREAT / EVOLVE-from-hand / PLACE) do NOT
  count; redundant repeats of the same method count once. A Run Away chain gets
  +1 (the evolve-to-Dudunsparce prerequisite is a logical step not counted as
  an acquisition op).

Seeds already present in expert_gold_v1 are excluded so the supplement is
disjoint from the edited gold set. Per-tier quotas are configurable
(default 15/20/30/35 — tilted toward harder tiers because easy T1 positives
are otherwise over-represented).
'''
from __future__ import annotations
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
REVIEW_ROOT = SCRIPTS.parent / 'logs' / 'review_manual'
GOLD_DIR = REVIEW_ROOT / 'expert_gold_v1'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from filter_opening_hard_cases import turn_limit_for_seed
from opening_log_formatter import card_names_zh, format_log_text
from opening_validate import validate_log
from opening_cards import SWITCH, JUDGE, BOSS_ORDERS
from simulate_opening import SetupRecord, SimRecord, export_sim_record, simulate_opening
from arena.deck import load_deck_csv
_UTILITY_TRAINERS = {
    SWITCH,
    JUDGE,
    BOSS_ORDERS}
_ACQ_ABILITY = {
    'ABILITY_FAN_CALL',
    'ABILITY_RUN_AWAY',
    'ABILITY_LAST_DITCH'}
TIER_NAMES = {
    1: 'T1',
    2: 'T2',
    3: 'T3',
    4: 'T4' }
DEFAULT_QUOTA = (15, 20, 30, 35)

def difficulty_tier_from_steps(steps = None):
    '''Count DISTINCT acquisition methods in a traj\'s step list → tier 1..4.

    `steps` is the list of step dicts from traj.jsonl (each has
    `step["action"]["kind"]` and `step["action"]["card_id"]`).
    '''
    cats = set()
    runaway = False
    for s in steps:
        act = s.get('action', { })
        k = act.get('kind')
        cid = act.get('card_id')
        if k in _ACQ_ABILITY:
            cats.add(k)
            if k == 'ABILITY_RUN_AWAY':
                runaway = True
            continue
        if k == 'PLAY_TRAINER' and cid is not None and cid not in _UTILITY_TRAINERS:
            cats.add(('TRAINER', cid))
    eff = len(cats) + 1 if runaway else 0
    return min(max(eff, 1), 4)


def difficulty_tier_from_log(log = None):
    '''Count DISTINCT acquisition methods in the trajectory → tier 1..4.'''
    cats = set()
    runaway = False
    for a in log:
        k = a.kind
        cid = a.card_id
        if k in _ACQ_ABILITY:
            cats.add(k)
            if k == 'ABILITY_RUN_AWAY':
                runaway = True
            continue
        if k == 'PLAY_TRAINER' and cid is not None and cid not in _UTILITY_TRAINERS:
            cats.add(('TRAINER', cid))
    eff = len(cats) + 1 if runaway else 0
    return min(max(eff, 1), 4)


def _existing_gold_seeds():
    seeds = set()
    if not GOLD_DIR.exists():
        return seeds
# WARNING: Decompyle incomplete


def _to_zh_log(header_lines = None, body = None):
    text = '\n'.join(header_lines) + body
    text = format_log_text(card_names_zh(text))
    text = text.replace('SAMPLE_LABEL=positive (正面样本)', '样本类型=正面')
    return text


def _build_header(seed, final_turn, archetype, miss_class = None, routes = None, tier = None, idx = ('seed', 'int', 'final_turn', 'int', 'archetype', 'str', 'miss_class', 'str', 'routes', 'list[str]', 'tier', 'int', 'idx', 'int', 'return', 'list[str]')):
    (going_first, turn_limit) = turn_limit_for_seed(seed)
    role = '先攻' if going_first else '后攻'
    cat = f'''CLEAN_T{final_turn}'''
    if not ' → '.join(routes):
        pass
    lines = [
        '// expert_status=approved',
        f'''// difficulty={TIER_NAMES[tier]}''',
        f'''// PACK=01 INDEX={idx}''',
        '// SAMPLE_LABEL=positive (正面)',
        f'''// category={cat} seed={seed} archetype={archetype}''',
        f'''// role={role} turn_limit={turn_limit}''',
        f'''// goal=True miss={miss_class} final_turn={final_turn}''',
        f'''// routes={'—'}''',
        '// 专家：positive 路线 OK，步骤无需修改；通读无误即保留 approved',
        '// 勿改起始区/回合快照；勿用 CORRECT 注释',
        '']
    return lines


def _going_first(seed = None):
    return seed % 2 == 0


def _sample_cell(buckets = None, *, tier_targets, floor, s1_cap_per_tier, rng):
