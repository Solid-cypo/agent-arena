"""Collect DAgger BC slices from the improved v1 pilot on the REAL cabt engine.

For each OPENING single-select decision where v1 (RL OFF) picks a mappable
option, record (pre_state with CORRECT inferred sup/ea, v2 action label) so a
retrain can learn v1's corrected opening lines (incl. Mega promotion) under
real-engine state transitions — closing the sim-to-real gap that left the
sim-trained proposer ~1pp below v1.

Writes slices in the same format as data/opening_sft/state_action_v2.jsonl.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUB = ROOT / "submission_starmie"
SCRIPTS = ROOT / ".agent" / "skills" / "piloting_starmie_froslass" / "scripts"
for p in (str(ROOT), str(SUB), str(SUB / "pilot"), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.simulator import play_game
from arena.deck import load_deck_csv
import arena.policy as policy_mod
import main as sub_main
import starmie_pilot as sp
from opening_cards import (
    BASIC_IDS, BOSS_ORDERS, CRISPIN, DUDUNSPARCE, DUNSPARCE_A, DUNSPARCE_B,
    ENERGY_IDS, FAN_ROTOM, HILDA, ITEM_IDS, JUDGE, LILLIE, MEGA_STARMIE,
    MEOWTH_EX, NIGHT_STRETCHER, POFFIN, POKE_PAD, SALVATOR, STARYU, SUPPORTER_IDS,
    SWITCH, ULTRA_BALL, WALLYS_COMPASSION,
)
from cg.api import OptionType, AreaType, to_observation_class

deck_a = load_deck_csv(SUB / "deck.csv")
deck_b = load_deck_csv(ROOT / "data" / "decks" / "walrein_control.csv")
base = policy_mod.make_agent(deck_b, dict(policy_mod.DEFAULT_WEIGHTS))

# cid -> v2 kind for simple (non-compound) PLAY labels
_PLAY_KIND = {
    LILLIE: "PLAY_LILLIE", JUDGE: "PLAY_JUDGE", SALVATOR: "PLAY_SALVATOR",
    BOSS_ORDERS: "PLAY_BOSS", WALLYS_COMPASSION: "PLAY_COMPASSION",
    POKE_PAD: "PLAY_POKE_PAD", NIGHT_STRETCHER: "PLAY_NIGHT_STRETCHER",
    SWITCH: "PLAY_SWITCH",
}
# compound trainers whose head2 (fetched target) is in a follow-up select ->
# skip here; the gold already supervises their head2.
_COMPOUND_SKIP = {HILDA, CRISPIN, POFFIN, ULTRA_BALL}
_EVO_TARGET = {STARYU: MEGA_STARMIE, DUNSPARCE_A: DUDUNSPARCE, DUNSPARCE_B: DUDUNSPARCE}
_ABILITY_SRC = {FAN_ROTOM: "ABILITY_FAN_CALL", MEOWTH_EX: "ABILITY_LAST_DITCH",
                DUDUNSPARCE: "ABILITY_RUN_AWAY"}

slices: list[dict] = []
_n_games = 0


def _si(v, d=0):
    try:
        return int(v)
    except Exception:
        return d


def _hand_cid(obs, opt, mi):
    try:
        if int(opt.type) != int(OptionType.PLAY):
            return 0
        h = obs.current.players[mi].hand or []
        i = _si(getattr(opt, "index", None), -1)
        if 0 <= i < len(h) and h[i]:
            return _si(getattr(h[i], "id", None))
    except Exception:
        pass
    return 0


def _ability_src(obs, opt, mi):
    try:
        if int(opt.type) != int(OptionType.ABILITY):
            return 0
        p = obs.current.players[mi]
        area = opt.area
        i = _si(getattr(opt, "index", None), -1)
        if area == AreaType.BENCH:
            b = p.bench or []
            if 0 <= i < len(b) and b[i]:
                return _si(getattr(b[i], "id", None))
        if area == AreaType.ACTIVE:
            a = (p.active or [None])[0]
            if a:
                return _si(getattr(a, "id", None))
    except Exception:
        pass
    return 0


def _attach_ids(obs, opt, mi):
    """Return (energy_cid, target_cid) for an ATTACH option."""
    try:
        if int(opt.type) != int(OptionType.ATTACH):
            return 0, 0
        h = obs.current.players[mi].hand or []
        i = _si(getattr(opt, "index", None), -1)
        eid = _si(getattr(h[i], "id", None)) if 0 <= i < len(h) and h[i] else 0
        # target via inPlayArea / inPlayIndex
        pa = getattr(opt, "inPlayArea", None)
        pi = _si(getattr(opt, "inPlayIndex", None), -1)
        p = obs.current.players[mi]
        tgt = 0
        if pa == AreaType.ACTIVE:
            a = (p.active or [None])[0]
            if a:
                tgt = _si(getattr(a, "id", None))
        elif pa == AreaType.BENCH:
            b = p.bench or []
            if 0 <= pi < len(b) and b[pi]:
                tgt = _si(getattr(b[pi], "id", None))
        return eid, tgt
    except Exception:
        return 0, 0


def _evolve_target(obs, opt, mi):
    """Evolution target id from an EVOLVE option's base pokemon."""
    try:
        if int(opt.type) != int(OptionType.EVOLVE):
            return None
        p = obs.current.players[mi]
        area = opt.area
        i = _si(getattr(opt, "index", None), -1)
        base = 0
        if area == AreaType.ACTIVE:
            a = (p.active or [None])[0]
            if a:
                base = _si(getattr(a, "id", None))
        elif area == AreaType.BENCH:
            b = p.bench or []
            if 0 <= i < len(b) and b[i]:
                base = _si(getattr(b[i], "id", None))
        return _EVO_TARGET.get(base)
    except Exception:
        return None


def _option_to_v2(obs, opt, mi):
    """Map a chosen cabt option to a v2 (kind, primary, sub) label, or None."""
    t = int(opt.type)
    if t == int(OptionType.PLAY):
        cid = _hand_cid(obs, opt, mi)
        if cid in _COMPOUND_SKIP:
            return None  # head2 supervised by gold
        if cid in _PLAY_KIND:
            return (_PLAY_KIND[cid], None, None)
        if cid in SUPPORTER_IDS:
            return ("PLAY_SUPPORTER", cid, None)
        if cid in ITEM_IDS:
            return ("PLAY_ITEM", cid, None)
        if cid in BASIC_IDS:
            return ("PLAY_POKEMON", cid, None)
        return None
    if t == int(OptionType.ATTACH):
        eid, tgt = _attach_ids(obs, opt, mi)
        if eid in ENERGY_IDS:
            return ("ATTACH", eid, tgt or None)
        return None
    if t == int(OptionType.EVOLVE):
        tgt = _evolve_target(obs, opt, mi)
        if tgt is not None:
            return ("EVOLVE", tgt, None)
        return None
    if t == int(OptionType.ABILITY):
        src = _ability_src(obs, opt, mi)
        if src in _ABILITY_SRC:
            return (_ABILITY_SRC[src], None, None)
        return None
    if t == int(OptionType.RETREAT):
        return ("RETREAT", None, None)
    return None


def _build_pre_state(obs, view, mi):
    me = obs.current.players[mi]
    active = (me.active or [None])[0]
    if active:
        act = {"card_id": _si(getattr(active, "id", None)),
               "energies": [_si(e) for e in (getattr(active, "energies", None) or [])]}
    else:
        act = None
    bench = []
    for p in (me.bench or []):
        if p:
            bench.append({"card_id": _si(getattr(p, "id", None)),
                          "energies": [_si(e) for e in (getattr(p, "energies", None) or [])]})
    return {
        "hand_ids": list(view.get("hand", [])),
        "board": {"active": act, "bench": bench},
        "deck_len": int(view.get("deck_len", 0)),
        "prize_len": int(view.get("prize_len", 0)),
        "flags": {
            "supporter_played": bool(view.get("supporter_played", False)),
            "energy_attached": bool(view.get("energy_attached", False)),
        },
    }


def _collector(obs_dict):
    """Wrap v1: record (pre_state, v2 label) for the chosen mappable option."""
    decision = sub_main.agent(obs_dict)
    if not decision:
        return decision
    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return decision
        max_c = _si(getattr(obs.select, "maxCount", None), 1)
        min_c = _si(getattr(obs.select, "minCount", None), 1)
        pick = max(1, min(max_c, max(min_c, 1)))
        if pick != 1:
            return decision  # only single-select (matches proposer gating)
        sit = sp._compute_situation(obs, deck_template=deck_a, agent_state={})
        phase = sit.get("phase")
        board = sit.get("board")
        if phase is None or phase.primary != "OPENING" or board is None:
            return decision
        if board.my_turn_number < 1:
            return decision
        mi = sit["my_index"]
        options = obs.select.option
        _MAPPABLE = (int(OptionType.PLAY), int(OptionType.ATTACH),
                     int(OptionType.EVOLVE), int(OptionType.ABILITY),
                     int(OptionType.RETREAT))
        if not any(int(o.type) in _MAPPABLE for o in options):
            return decision
        chosen = decision[0]
        if chosen < 0 or chosen >= len(options):
            return decision
        opt = options[chosen]
        if int(opt.type) not in _MAPPABLE:
            return decision
        label = _option_to_v2(obs, opt, mi)
        if label is None:
            return decision
        # Build the view with CORRECT inferred sup/ea (same as proposer integration)
        from opening_bridge import BattleOpeningAdapter
        adapter = BattleOpeningAdapter(obs, board, sit["hand"], sit["resources"], mi)
        view = sp._build_rl_view(adapter)
        _off_sup = False
        _off_attach = False
        for o in options:
            if int(o.type) == int(OptionType.ATTACH):
                _off_attach = True
            elif int(o.type) == int(OptionType.PLAY):
                if _hand_cid(obs, o, mi) in SUPPORTER_IDS:
                    _off_sup = True
        _vh = view.get("hand", []) or []
        _has_sup = any(c in SUPPORTER_IDS for c in _vh)
        view["supporter_played"] = bool(_has_sup and not _off_sup)
        view["energy_attached"] = bool(not _off_attach)
        pre = _build_pre_state(obs, view, mi)
        slices.append({
            "seed": None,
            "going_first": bool(view.get("going_first", True)),
            "source": "dagger_v1",
            "goal_reached": None,
            "step_index": len(slices),
            "phase": "OPENING",
            "difficulty": "",
            "pre_state": pre,
            "action": {"kind": label[0], "primary": label[1], "sub": label[2]},
            "action_zh": "",
        })
    except Exception:
        pass
    return decision


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--out", default=str(ROOT / "data" / "opening_sft" / "dagger_v1_slices.jsonl"))
    args = ap.parse_args()

    sp._RL_ENABLED = False  # pure v1 expert
    for i in range(args.games):
        sp.reset_for_new_game()
        if i % 2 == 0:
            play_game(_collector, base, deck_a, deck_b, max_steps=args.max_steps)
        else:
            play_game(base, _collector, deck_b, deck_a, max_steps=args.max_steps)
        if (i + 1) % 50 == 0:
            print(f"  games {i+1}/{args.games}  slices {len(slices)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fo:
        for s in slices:
            fo.write(json.dumps(s, ensure_ascii=False) + "\n")
    # kind distribution
    from collections import Counter
    by_kind = Counter(s["action"]["kind"] for s in slices)
    print(f"wrote {len(slices)} DAgger slices -> {out}")
    print("by_kind:")
    for k, c in by_kind.most_common():
        print(f"  {k:>22} {c}")


if __name__ == "__main__":
    main()
