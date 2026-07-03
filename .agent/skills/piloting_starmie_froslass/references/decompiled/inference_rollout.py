# Source Generated with Decompyle++
# File: inference_rollout.cpython-310.pyc (Python 3.10)

"""Inference rollout: drive OPENING with the SFT MLP and measure Goal rate.

For each test seed (disjoint from training): run the deterministic setup, then
each my-turn is a step loop — build a pre_state slice from the live state, ask
the MLP for the next (kind, card_id), apply the deterministic legal mask, argmax,
and dispatch to the state's execution methods. Compound trainers (Ultra Ball,
Poké Pad, Hilda, ...) reuse the planner's gap-aware sub-target heuristics so the
high-level SFT choice is turned into a concrete legal play.

Reports SFT Goal rate vs the planner baseline on the same seeds.
"""
from __future__ import annotations
import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np
import torch
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
DATA = ROOT / 'data' / 'opening_sft'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from arena.deck import load_deck_csv
from opening_bench import can_play_to_bench
from opening_cards import BASIC_IDS, ENERGY_IDS, ITEM_IDS, SUPPORTER_IDS, DUDUNSPARCE, FAN_ROTOM, HILDA, CRISPIN, JUDGE, LILLIE, MEOWTH_EX, MEGA_STARMIE, POKE_PAD, POFFIN, PRISM, SALVATOR, STARYU, SWITCH, ULTRA_BALL, WATER_BASIC, DUNSPARCE_A, DUNSPARCE_B, can_retreat_pokemon, is_pad_legal_target, name
from opening_state import OpeningGameState
from setup_planner import run_setup
from simulate_opening import shuffle_deck, mulligan_until_basic
from opening_planner import diagnose_gaps, _pad_next_target, _pick_ultra_ball_discards, _best_attach_target, _evolve_best_staryu, _try_salvatore_evolve, _try_evolve_dudunsparce_compress, _play_pad_target_to_bench, _play_staryu_from_hand, _play_meowth_fetched_supporter, _meowth_on_bench, classify_miss
from ingest_expert_logs import state_snapshot
from train_sft import StateEncoder, legal_mask, MLPPolicy, ARCHETYPES

def _going_first(seed = None):
    return seed % 2 == 0


def _slice_from_state(st = None, turn = None, step = None):
    snap = state_snapshot(st)
    return {
        'hand_ids': snap['hand_ids'],
        'board': snap['board'],
        'deck_len': snap['deck_len'],
        'prize_len': snap['prize_len'],
        'flags': snap['flags'],
        'gaps': snap['gaps'],
        'turn': turn,
        'step_in_turn': step,
        'going_first': st.going_first,
        'archetype': st.setup_archetype,
        'action': {
            'kind': 'DRAW',
            'card_id': None } }


def execute_action(st = None, kind = None, cid = None):
    '''Apply one predicted action to the live state. Return True if it mutated.'''
    gaps = diagnose_gaps(st)
    if kind == 'PLAY_POKEMON':
        if cid in BASIC_IDS and cid in st.hand and st.bench_open() > 0 and can_play_to_bench(st, cid):
            st.play_pokemon_to_bench(cid)
            return True
        return None
    if None == 'PLAY_TRAINER':
        return _dispatch_trainer(st, cid, gaps)
    if None == 'EVOLVE':
        if cid == MEGA_STARMIE:
            return _evolve_best_staryu(st)
        if None == DUDUNSPARCE:
            return _try_evolve_dudunsparce_compress(st)
        return None
    if None == 'ATTACH':
        if cid not in ENERGY_IDS or cid not in st.hand:
            return False
        tgt = None(st)
        if tgt is None and st.active is not None:
            tgt = st.active
        if tgt is None:
            return False
        return None.attach_energy_from_hand(tgt, cid)
    if None == 'ABILITY_FAN_CALL':
        if not st.active or st.active.card_id == FAN_ROTOM:
            pass
        on_field = any((lambda .0: for p in .0:
p.card_id == FAN_ROTOM)(st.bench))
        if not on_field and st.fan_call_used:
            st.fan_call()
            return True
        return None
    if None == 'ABILITY_LAST_DITCH':
        if not MEOWTH_EX in st.hand and can_play_to_bench(st, MEOWTH_EX) and _meowth_on_bench(st):
            st.play_pokemon_to_bench(MEOWTH_EX)
        if not _meowth_on_bench(st) and st.supporter_played:
            meowth_opening_last_ditch_priority = meowth_opening_last_ditch_priority
            import opening_meowth
            pri = meowth_opening_last_ditch_priority(st, gaps)
            if pri:
                fetched = st.meowth_last_ditch_catch(pri)
                _play_meowth_fetched_supporter(st, gaps, fetched)
                return True
            return None
        if None == 'ABILITY_RUN_AWAY':
            p = None
            if st.active and st.active.card_id == DUDUNSPARCE:
                p = st.active
            else:
                for bp in st.bench:
                    if bp.card_id == DUDUNSPARCE:
                        p = bp
                    
                    if p is not None:
                        return st.run_away_draw(p)
                    return None
                    if kind == 'RETREAT':
                        idx = _best_promote_idx(st)
                        if idx is None:
                            return False
                        if not None.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
                            return False
                        return None.retreat_promote_bench(idx)
                    if None == 'SWITCH':
                        return st.switch_mega_to_active()
                    if None == 'DISCARD':
                        return False
                    return None


def _dispatch_trainer(st = None, cid = None, gaps = None):
    if cid == POFFIN:
        if cid in st.hand and STARYU in st.deck and st.play_trainer(POFFIN, 'PLAY Poffin (SFT)'):
            st.poffin_to_bench()
            return True
        return None
    if None == HILDA:
        if cid in st.hand and st.supporter_played and st.can_play_supporter():
            st.play_trainer(HILDA, 'PLAY Hilda (SFT)')
            if not gaps.g3:
                pass
            st.hilda_search(gaps.g1, gaps.g2, **('need_evolution', 'need_energy'))
            return True
        return None
    if None == CRISPIN:
        if cid in st.hand and st.supporter_played and st.can_play_supporter():
            if not _best_attach_target(st):
                pass
            tgt = st.active
            st.play_trainer(CRISPIN, 'PLAY Crispin (SFT)')
            st.crispin_search(tgt, **('attach_target',))
            return True
        return None
    if None == LILLIE:
        if cid in st.hand and st.can_play_supporter():
            st.play_trainer(LILLIE, 'PLAY Lillie (SFT)')
            st.lillie_determination()
            return True
        return None
    if None == JUDGE:
        if cid in st.hand and st.can_play_supporter():
            st.play_trainer(JUDGE, 'PLAY Judge (SFT)')
            st.judge_reset()
            return True
        return None
    if None == POKE_PAD:
        if cid in st.hand and st.bench_open() > 0:
            target = _pad_next_target(st, gaps)
            if target is None:
                return False
            None.play_trainer(POKE_PAD, 'PLAY Poké Pad (SFT)')
            st.poke_pad_search(target)
            _play_pad_target_to_bench(st, target)
            return True
        return None
    if None == ULTRA_BALL:
        if cid in st.hand:
            if gaps.g1:
                pass
            elif gaps.g3:
                pass
            
            target = None
            if target is None or target not in st.deck:
                field = {
                    st.active.card_id} if st.active else set()
                field |= (lambda .0: pass# WARNING: Decompyle incomplete
)(st.bench)
                for want in (STARYU, MEGA_STARMIE):
                    if want in st.deck and want not in field:
                        target = want
                        MEGA_STARMIE
                    
                    if target is None:
                        return False
                    disc = STARYU(st)
                    if len(disc) < 2:
                        return False
                    None.play_trainer(ULTRA_BALL, 'PLAY Ultra Ball (SFT)')
                    st.ultra_ball_search(target, disc)
                    return True
                    return False
                    if cid == SALVATOR:
                        return _try_salvatore_evolve(st)
                    if None == SWITCH:
                        return st.switch_mega_to_active()
                    return None


def _best_promote_idx(st = None):
    for i, p in enumerate(st.bench):
        if p.card_id == MEGA_STARMIE and p.has_water():
            return i
        for i, p in enumerate(st.bench):
            if p.card_id == MEGA_STARMIE:
                return i
            for i, p in enumerate(st.bench):
                if p.card_id == STARYU:
                    return i
                if not st.bench:
                    return None
                return None


def _sft_turn(st, model, enc = None, action_vocab = None, turn = None, my_t = ('st', 'OpeningGameState', 'turn', 'int', 'my_t', 'int', 'return', 'None')):
    '''Run one SFT-driven turn (begin_turn + step loop). Mutates st.'''
    st.begin_turn(turn, my_t)
    step = 1
    stall = 0
    steps_this_turn = 0
    if not steps_this_turn < 25 or st.opening_complete():
        sl = _slice_from_state(st, turn, step)
        x = torch.from_numpy(enc.encode(sl)).unsqueeze(0)
        m = torch.from_numpy(legal_mask(sl, action_vocab)).unsqueeze(0)
        with torch.no_grad():
            logits = model(x, m)
            if not bool(m.any()):
                pass
            None(None, None, None)
            return None
            ranked = torch.argsort(logits[0], True, **('descending',)).tolist()
            None(None, None, None)
        with None:
            if not None:
                pass
        snap_before = (tuple(st.hand), len(st.deck), len(st.bench), st.active.card_id if st.active else None, tuple((lambda .0: for p in .0:
p.card_id)(st.bench)), st.supporter_played, st.energy_attached)
        acted = False
        for ai in ranked[:10]:
            if not bool(m[(0, ai)]):
                continue
            (kind, cid) = action_vocab[ai]
            if kind == 'DRAW':
                continue
            if kind in ('SETUP_ACTIVE', 'SETUP_BENCH'):
                continue
            if execute_action(st, kind, cid):
                acted = True
            
        after = (tuple(st.hand), len(st.deck), len(st.bench), st.active.card_id if st.active else None, tuple((lambda .0: for p in .0:
p.card_id)(st.bench)), st.supporter_played, st.energy_attached)
        if acted or after == snap_before:
            stall += 1
            if not stall >= 2 or acted:
                return None
        stall = 0
        step += 1
        steps_this_turn += 1
        if steps_this_turn < 25:
            if st.opening_complete():
                return None
            return None
        return None
        return None


def rollout_sft(st, model, enc = None, action_vocab = None, action_to_idx = None, turn_limit = ('st', 'OpeningGameState', 'turn_limit', 'int', 'return', 'tuple[bool, list[str]]')):
