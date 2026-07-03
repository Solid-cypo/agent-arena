# Source Generated with Decompyle++
# File: validate_expert_gold.cpython-310.pyc (Python 3.10)

"""Validate expert gold OPENING logs for format + rule consistency.

Checks (no replay / no seed re-run — pure text audit per expert path):
  H1  expert_status header present and in {approved, edited, unreachable}
  H2  goal header vs final board: Active=Mega 大海星 ex [+水] should match goal=True
  H3  role/turn_limit present
  F1  step numbering sequential (1..N) within each 本回合操作 block
  F2  no bracket typos like `[[` or `8[`
  F3  no empty trailing step lines
  R1  no Supporter (希尔达/莉莉艾/裁判/萨瓦托/克里宾/老大的指令/瓦利的慈悲) played on 先攻 My-T1
  R2  retreat legality: at each `[撤退]`, active's energy >= retreat cost
      (棱镜能量 counts as 1 colorless energy; evolution to non-basic strips prism)
      EXCEPT a `[撤退]` immediately following a `[特性]` Run Away (ability switch, no cost)
  R3  at most one `[贴能]` (energy attach) per turn
  R4  at most one Supporter play per turn
  C1  hand count: each turn end hand count == next turn start hand count
  C2  going-first My-T1 must NOT draw (no `[抽牌]` in T1 ops) ; going-second My-T1 must draw
  C3  no `[备注] ... search →` immediately after a `Supporter blocked` note in same turn
  C4  every turn except 先攻 My-T1 draws exactly once (`[抽牌]` count == 1)
  C5  Bench[i] indices under each board are sequential 0,1,2,...
  C6  board continuity: each turn end board == next turn start board
      (active name+energy, bench names+energies)

Usage:
  python3 validate_expert_gold.py [--dir expert_gold_v1] [--strict]
Exit code: 0 if no errors (warnings allowed), 1 if any error.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_DIR = SCRIPTS.parent / 'logs' / 'review_manual' / 'expert_gold_v1'
SUPPORTER_ZH = {
    '裁判',
    '克里宾',
    '希尔达',
    '莉莉艾',
    '萨瓦托',
    '瓦利的慈悲',
    '老大的指令'}
SUPPORTER_PLAY_PAT = re.compile('使用\\s+(' + '|'.join((lambda .0: for s in .0:
re.escape(s))(SUPPORTER_ZH)) + ')(?:\\s|$|（)')
VALID_STATUS = {
    'edited',
    'approved',
    'unreachable'}
GOAL_BOARD_PAT = re.compile('Active:\\s*Mega 大海星 ex\\s*\\[([^\\]]*)\\]')
STEP_PAT = re.compile('^\\s*(\\d+)[.\\s]')
RETREAT_COST_ZH: 'dict[str, int]' = {
    'Mega 大海星 ex': 2,
    'Mega 大雪妖女 ex': 1,
    '海星星': 1,
    '雪童子': 1,
    '旋转罗盘': 1,
    '喵头目 ex': 1,
    '含羞苞': 1,
    '愿增猿': 1,
    '雪妖女': 1,
    '土龙节节（逃跑抽牌）': 1,
    '土龙节节 ex': 1,
    '土龙节节': 1,
    '土龙弟弟': 0 }
BASIC_ZH = {
    '含羞苞',
    '海星星',
    '雪童子',
    '土龙弟弟',
    '旋转罗盘'}
PRISM_ZH = '棱镜能量'
RUN_AWAY_HINTS = ('土龙节节', '逃跑抽牌', 'Run Away', '撤退抽')
BOARD_ACTIVE_PAT = re.compile('Active:\\s*(.+?)(?:\\s*\\[([^\\]]*)\\])?\\s*$')
BOARD_BENCH_PAT = re.compile('Bench\\s*\\[\\d+\\]:\\s*(.+?)(?:\\s*\\[([^\\]]*)\\])?\\s*$')

def _parse_energies(bracket = None):
    """'棱镜能量' -> ['棱镜能量']; '无能量' -> []; None / '' -> [] (no bracket written)."""
    out = []
    if not bracket:
        return out
    for tok in None.split(','):
        tok = tok.strip()
        if tok or tok == '无能量':
            continue
        out.append(tok)
    return out


def _parse_board(lines = None, marker = None):
    '''Return (active_name, active_energies, bench[(name, energies)]) under `marker`.'''
    capture = False
    active_name = None
    active_eng = []
    bench = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(marker):
            capture = True
            continue
        if not capture:
            continue
        if s == '' and s.startswith('本回合操作') and s.startswith('回合开始') or s.startswith('回合结束'):
            pass
        else:
            ma = BOARD_ACTIVE_PAT.search(s)
            if ma and s.startswith('Active:'):
                active_name = ma.group(1).strip()
                active_eng = _parse_energies(ma.group(2))
                continue
            mb = BOARD_BENCH_PAT.search(s)
            if mb:
                bench.append((mb.group(1).strip(), _parse_energies(mb.group(2))))
        return (active_name, active_eng, bench)


def _check_bench_index(label = None, lines = None, marker = None, issues = ('label', 'str', 'lines', 'list[str]', 'marker', 'str', 'issues', 'list[str]', 'return', 'None')):
    '''C5: Bench[i] indices under `marker` must be 0,1,2,... sequential.'''
    capture = False
    idxs = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(marker):
            capture = True
            continue
        if not capture:
            continue
        if s == '' and s.startswith('本回合操作') and s.startswith('回合开始') or s.startswith('回合结束'):
            pass
        else:
            mb = re.match('Bench\\s*\\[(\\d+)\\]', s)
            if mb:
                idxs.append(int(mb.group(1)))
        if idxs or idxs != list(range(len(idxs))):
            issues.append(f'''{label} C5 bench indices not sequential: {idxs}''')
            return None
        return None
        return None


def _parse_header(text = None):
    h = { }
    for line in text.splitlines():
        if not line.startswith('//'):
            return h
        body = None[2:].strip()
        for key in ('expert_status', 'PACK', 'SAMPLE_LABEL', 'category', 'role', 'goal', 'routes'):
            if body.startswith(key + '=') or body.startswith(key + ' '):
                h[key] = body.split('=', 1)[1].strip() if '=' in body else body.split(' ', 1)[1].strip()
    return h


def _split_turns(text = None):
    '''Return [(turn_label, lines_in_block)] for Setup + each My-Tn.'''
    blocks = []
    cur_label = ''
    cur = []
    for line in text.splitlines():
        if line.startswith('【') and '】' in line:
            if cur_label:
                blocks.append((cur_label, cur))
            cur_label = line
            cur = []
            continue
        cur.append(line)
    if cur_label:
        blocks.append((cur_label, cur))
    return blocks


def _ops_block(lines = None):
    out = []
    in_ops = False
    for ln in lines:
        s = ln.strip()
        if s.startswith('本回合操作'):
            in_ops = True
            continue
        if in_ops:
            if s.startswith('回合结束') and s.startswith('Setup 后') or s == '':
                if s == '':
                    continue
                in_ops = False
                continue
        if in_ops:
            out.append(ln)
    return out


def _hand_after(lines = None, marker = None):
    capture = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(marker):
            for nxt in lines[i + 1:]:
                s = nxt.strip()
                if s:
                    parts = re.split('[,，]', s)
                    return (lambda .0: [ c.strip() for c in .0 if c.strip() ])(parts)
                return []
                return None


def _check_r2(label = None, lines = None, issues = None):
    """R2 retreat legality: walk the turn's ops from the turn-start board and
    verify each `[撤退]` (except a Run Away ability switch) has enough energy."""
    (active_name, active_eng, bench) = _parse_board(lines, '回合开始场面')
    if active_name is None:
        return None
    run_away_pending = None
    for op in _ops_block(lines):
        s = op.strip()
        body = re.sub('^\\s*\\d+\\.\\s*', '', s)
        if body.startswith('[备注]'):
            continue
        if body.startswith('[贴能]'):
            run_away_pending = False
            mm = re.search('\\[贴能\\]\\s*(.+?)\\s*→\\s*(.+?)(?:（(战斗场|替补席)）)?\\s*$', body)
            if not mm:
                continue
            energy = mm.group(1).strip()
            target = mm.group(2).strip()
            loc = mm.group(3)
            if loc == '替补席':
                for bn, be in enumerate(bench):
                    if bn == target:
                        bench[i] = (bn, be + [
                            energy])
                    
                    active_eng = active_eng + [
                        energy]
                    if body.startswith('[进化]'):
                        run_away_pending = False
                        mm = re.search('\\[进化\\]\\s*(.+?)\\s*→\\s*(.+)$', body)
                        if not mm:
                            continue
                        basic = re.sub('（(战斗场|替补席)）', '', mm.group(1)).strip()
                        mega = mm.group(2).strip()
                        if basic == active_name:
                            active_name = mega
                            if mega not in BASIC_ZH and PRISM_ZH in active_eng:
                                active_eng = (lambda .0: [ e for e in .0 if e != PRISM_ZH ])(active_eng)
                            continue
                        for bn, be in enumerate(bench):
                            if bn == basic:
                                new_be = (lambda .0 = None: [ e for e in .0 if e == PRISM_ZH ])(be)
                                bench[i] = (mega, new_be)
                            
                            if body.startswith('[撤退]'):
                                mm = re.search('←\\s*(.+)$', body)
                                promoted = mm.group(1).strip() if mm else None
                                if run_away_pending:
                                    run_away_pending = False
                                    idx = None((lambda .0 = None: 