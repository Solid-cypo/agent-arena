# Source Generated with Decompyle++
# File: train_sft.cpython-310.pyc (Python 3.10)

'''SFT (behaviour cloning) for the OPENING phase.

Pipeline:  train.jsonl / val.jsonl  (state, expert_action) slices
        →  StateEncoder  (state  → fixed-length feature vector)
        →  ActionVocab   ((kind, choice_card_id) → class index)
        →  legal_mask    (deterministic rule mask over the action vocab)
        →  MLP classifier with masked softmax + class-weighted CE
        →  top-1 / top-5 action accuracy on val

Design notes
------------
* `choice_card_id` is the card the expert *chose*. Kinds whose card is not a
  choice (DRAW = deck top, RETREAT = logged None, ABILITY_FAN_CALL = None) are
  collapsed to `choice_card_id = None` so the model never predicts a card it
  cannot choose.
* The legal mask is a deterministic Python rule layer (Write Software, Not
  Rules). It is approximate but sound: the expert target is always legal by
  construction (ingest validates), so the mask never zeroes the gold action.
* No heavy RL libs — a raw PyTorch MLP, per the project Tiny-RL strategy.
'''
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import torch
from torch.nn import nn
import torch.nn.functional
F = functional
nn
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
DATA = ROOT / 'data' / 'opening_sft'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from opening_cards import BASIC_IDS, ENERGY_IDS, ITEM_IDS, SUPPORTER_IDS, DUDUNSPARCE, FAN_ROTOM, MEOWTH_EX, RETREAT_COST, WATER_ENERGY_IDS
NO_CHOICE_KINDS = {
    'DRAW',
    'RETREAT',
    'ABILITY_FAN_CALL'}
PREDICT_KINDS = [
    'SETUP_ACTIVE',
    'SETUP_BENCH',
    'DRAW',
    'PLAY_POKEMON',
    'PLAY_TRAINER',
    'ATTACH',
    'ABILITY_FAN_CALL',
    'ABILITY_LAST_DITCH',
    'ABILITY_RUN_AWAY',
    'EVOLVE',
    'SWITCH',
    'RETREAT',
    'DISCARD']
ENERGY_TYPE_IDS = sorted(ENERGY_IDS)
ARCHETYPES = [
    'A1',
    'A2',
    'B1',
    'C1',
    'E1',
    'F1',
    'S1',
    'X1']
MAX_BENCH = 5
HAND_COUNT_CAP = 4

def _choice_cid(s = None):
    k = s['action']['kind']
    if k in NO_CHOICE_KINDS:
        return None
    return None['action'].get('card_id')


def build_vocabs(train = None):
    card_ids = set()
    for s in train:
        card_ids.update(s['hand_ids'])
        b = s['board']
        if b.get('active'):
            card_ids.add(b['active']['card_id'])
        for x in b.get('bench', []):
            card_ids.add(x['card_id'])
        c = _choice_cid(s)
        if c is not None:
            card_ids.add(c)
    card_vocab = (lambda .0: pass# WARNING: Decompyle incomplete
)(enumerate(sorted(card_ids)))
    action_set = set()
    for s in train:
        action_set.add((s['action']['kind'], _choice_cid(s)))
    action_vocab = sorted(action_set, (lambda x: if x[1] is not None:
(x[0], x[1])(None, x[0])), **('key',))
    action_to_idx = (lambda .0: pass# WARNING: Decompyle incomplete
)(enumerate(action_vocab))
    return (card_vocab, action_to_idx)


class StateEncoder:
    
    def __init__(self = None, card_vocab = None):
        self.card_vocab = card_vocab
        self.V = len(card_vocab) + 1
        self.dim = self.V + self.V + len(ENERGY_TYPE_IDS) + MAX_BENCH * (self.V + len(ENERGY_TYPE_IDS)) + 2 + 6 + 5 + len(ARCHETYPES)

    
    def _card_onehot(self = None, cid = None):
        v = np.zeros(self.V, np.float32, **('dtype',))
        if cid is not None:
            v[self.card_vocab.get(cid, 0)] = 1
        return v

    
    def _energy_counts(self = None, energies = None):
        v = np.zeros(len(ENERGY_TYPE_IDS), np.float32, **('dtype',))
        for e in energies:
            if e in ENERGY_TYPE_IDS:
                v[ENERGY_TYPE_IDS.index(e)] += 1
        return v

    
    def encode(self = None, s = None):
        feat = []
        hand = np.zeros(self.V, np.float32, **('dtype',))
        for cid in s['hand_ids']:
            idx = self.card_vocab.get(cid, 0)
            hand[idx] = min(HAND_COUNT_CAP, hand[idx] + 1)
        feat.append(hand)
        b = s['board']
        act = b.get('active')
        if act:
            feat.append(self._card_onehot(act['card_id']))
            feat.append(self._energy_counts(act.get('energies', [])))
        else:
            feat.append(np.zeros(self.V, np.float32, **('dtype',)))
            feat.append(np.zeros(len(ENERGY_TYPE_IDS), np.float32, **('dtype',)))
        if not b.get('bench', []):
            pass
        bench = []
        for i in range(MAX_BENCH):
            if i < len(bench):
                feat.append(self._card_onehot(bench[i]['card_id']))
                feat.append(self._energy_counts(bench[i].get('energies', [])))
                continue
            feat.append(np.zeros(self.V, np.float32, **('dtype',)))
            feat.append(np.zeros(len(ENERGY_TYPE_IDS), np.float32, **('dtype',)))
        flags = s['flags']
        feat.append(np.array([
            float(flags['supporter_played']),
            float(flags['energy_attached'])], np.float32, **('dtype',)))
        gaps = s['gaps']
        None(None((lambda .0 = None: [ float(gaps[f'''g{i}''']) for i in .0 ])(range(1, 7)), np.float32, **('dtype',)))
        feat.append(np.array([
            s['deck_len'] / 60,
            s['prize_len'] / 6,
            s['turn'] / 3,
            min(s['step_in_turn'], 10) / 10,
            float(s['going_first'])], np.float32, **('dtype',)))
        arch = np.zeros(len(ARCHETYPES), np.float32, **('dtype',))
        if s['archetype'] in ARCHETYPES:
            arch[ARCHETYPES.index(s['archetype'])] = 1
        feat.append(arch)
        return np.concatenate(feat)



def _active_can_retreat(active = None):
    cid = active['card_id']
    cost = RETREAT_COST.get(cid, 1)
    if cost == 0:
        return True
    n_water = None((lambda .0: 