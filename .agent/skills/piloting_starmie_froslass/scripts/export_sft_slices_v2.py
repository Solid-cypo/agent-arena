"""Export v2 SFT slices from traj.jsonl.

v2 action = (kind, primary, sub). Compound-trainer targets are folded in from
the effect step that follows each "PLAY X" commit step:

    "PLAY Hilda"  +  NOTE "Hilda search -> ['Mega Starmie ex', 'Water Energy']"
        -> (PLAY_HILDA, primary=Mega Starmie ex, sub=Water Energy)

Effect / mechanical steps (NOTE, DISCARD, DRAW, "X -> effect", "Crispin attach",
"Salvatore: ...", SWITCH, "Retreat cost -> discard") are NOT emitted as their own
slices - they are consequences of a decision, not decisions themselves.

Reads : data/opening_sft/traj.jsonl
Writes: data/opening_sft/state_action_v2.jsonl  +  manifest_v2.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from opening_cards import (
    BOSS_ORDERS,
    CARD_NAMES,
    CRISPIN,
    DUDUNSPARCE,
    HILDA,
    HILDA_EVOLUTION_IDS,
    ITEM_IDS,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    POFFIN,
    POKE_PAD,
    PRISM,
    SALVATOR,
    STARYU,
    SUPPORTER_IDS,
    SWITCH,
    ULTRA_BALL,
    WALLYS_COMPASSION,
    WATER_BASIC,
    name,
)
from opening_exec import NAME_TO_ID, V2_KINDS, NIGHT_STRETCHER

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data" / "opening_sft"

# Longest-first so "Mega Starmie ex" wins over "Staryu" / "Mega Froslass ex".
_NAME_KEYS = sorted(NAME_TO_ID.keys(), key=len, reverse=True)


def resolve_token(tok: str) -> int | None:
    """Resolve a card name token (possibly with surrounding junk) to an id."""
    t = tok.strip().strip("'\"").strip()
    if t in NAME_TO_ID:
        return NAME_TO_ID[t]
    for k in _NAME_KEYS:
        if k in t:
            return NAME_TO_ID[k]
    return None


_LIST_RE = re.compile(r"\[([^\]]*)\]")


def parse_list(s: str) -> list[int]:
    """Parse a python-list-literal fragment like ['Staryu', 'Fan Rotom'] -> ids."""
    m = _LIST_RE.search(s)
    if not m:
        return []
    out: list[int] = []
    for part in m.group(1).split(","):
        cid = resolve_token(part)
        if cid is not None:
            out.append(cid)
    return out


def _after_arrow(s: str) -> str:
    i = s.find("→")
    return s[i + 1:].strip() if i >= 0 else ""


def _after_leftarrow(s: str) -> str:
    i = s.find("←")
    return s[i + 1:].strip() if i >= 0 else ""


def _name_after_arrow(s: str) -> int | None:
    """Name between '-> ' and (' on ' | ';' | end)."""
    rest = _after_arrow(s)
    for cut in (" on ", ";", ", disc", ", to"):
        rest = rest.split(cut)[0]
    return resolve_token(rest)


def _name_after_leftarrow(s: str) -> int | None:
    rest = _after_leftarrow(s)
    rest = rest.split(" on ")[0].split(";")[0]
    return resolve_token(rest)


def _is_effect_step(step: dict) -> bool:
    k = step["action"]["kind"]
    d = step["action"].get("detail_en", "") or ""
    if k in ("NOTE", "DISCARD", "DRAW", "SWITCH"):
        return True
    if k == "ATTACH" and d.startswith("Crispin attach"):
        return True
    if k == "EVOLVE" and d.startswith("Salvatore:"):
        return True
    if k == "PLAY_TRAINER" and not d.startswith("PLAY "):
        # "Poffin -> bench [...]", "Poké Pad -> X", "Ultra Ball -> X, disc", ...
        return True
    return False


def _fix_dunsparce(cid: int | None, step: dict) -> int | None:
    """Resolve the Dunsparce multi-ID ambiguity (65 vs 305) using the live hand."""
    from opening_cards import DUNSPARCE_A, DUNSPARCE_B
    if cid == DUNSPARCE_A:
        hand = list(step.get("pre_state", {}).get("hand_ids", []))
        if DUNSPARCE_A not in hand and DUNSPARCE_B in hand:
            return DUNSPARCE_B
    return cid


def _strip_suffix(trainer: str) -> str:
    for suf in (" (SFT)", " (v2)", " (meowth-fetched)", " (planner)"):
        if trainer.endswith(suf):
            trainer = trainer[: -len(suf)]
    return trainer.strip()


def v2_action_for_step(step: dict, next_step: dict | None) -> tuple[str, int | None, int | None] | None:
    a = step["action"]
    k = a["kind"]
    d = a.get("detail_en", "") or ""
    cid = a.get("card_id")

    if k == "SETUP_ACTIVE":
        return ("SETUP_ACTIVE", _fix_dunsparce(cid, step), None)
    if k == "SETUP_BENCH":
        return ("SETUP_BENCH", _fix_dunsparce(cid, step), None)
    if k == "PLAY_POKEMON":
        return ("PLAY_POKEMON", _fix_dunsparce(cid, step), None)

    if k == "ATTACH" and not d.startswith("Crispin attach"):
        # "Water Energy -> Mega Starmie ex on active"
        return ("ATTACH", cid, _name_after_arrow(d))

    if k == "EVOLVE" and not d.startswith("Salvatore:"):
        # "Staryu -> Mega Starmie ex"  /  "Dunsparce -> Dudunsparce (Run Away Draw)"
        return ("EVOLVE", _name_after_arrow(d), None)

    if k == "RETREAT":
        return ("RETREAT", _name_after_leftarrow(d), None)

    if k == "ABILITY_FAN_CALL":
        return ("ABILITY_FAN_CALL", None, None)
    if k == "ABILITY_RUN_AWAY":
        return ("ABILITY_RUN_AWAY", None, None)
    if k == "ABILITY_LAST_DITCH":
        return ("ABILITY_LAST_DITCH", _name_after_arrow(d), None)

    if k == "PLAY_TRAINER" and d.startswith("PLAY "):
        eff = (next_step["action"].get("detail_en", "") or "") if next_step else ""
        # Dispatch by card_id (reliable across edited & approved logs).
        if cid == POFFIN:
            basics = parse_list(eff)
            return ("PLAY_POFFIN",
                    basics[0] if len(basics) >= 1 else None,
                    basics[1] if len(basics) >= 2 else None)
        if cid == ULTRA_BALL:
            return ("PLAY_ULTRA_BALL", _name_after_arrow(eff), None)
        if cid == HILDA:
            items = parse_list(eff)
            evo = next((c for c in items if c in HILDA_EVOLUTION_IDS), None)
            energy = next((c for c in items if c in (WATER_BASIC, PRISM)), None)
            return ("PLAY_HILDA", evo, energy)
        if cid == CRISPIN:
            tgt = _name_after_arrow(eff)
            to_hand: int | None = None
            if "to hand" in eff:
                hl = parse_list(eff.split("to hand", 1)[1])
                to_hand = hl[0] if hl else None
            elif "search " in eff:
                to_hand = resolve_token(eff.split("search", 1)[1])
            return ("PLAY_CRISPIN", tgt, to_hand)
        if cid == POKE_PAD:
            return ("PLAY_POKE_PAD", _name_after_arrow(eff), None)
        if cid == SALVATOR:
            return ("PLAY_SALVATOR", None, None)
        if cid == LILLIE:
            return ("PLAY_LILLIE", None, None)
        if cid == JUDGE:
            return ("PLAY_JUDGE", None, None)
        if cid == BOSS_ORDERS:
            return ("PLAY_BOSS", None, None)
        if cid == WALLYS_COMPASSION:
            return ("PLAY_COMPASSION", None, None)
        if cid == NIGHT_STRETCHER:
            return ("PLAY_NIGHT_STRETCHER", None, None)
        if cid == SWITCH:
            return ("PLAY_SWITCH", _name_after_leftarrow(eff), None)
        if cid in SUPPORTER_IDS:
            return ("PLAY_SUPPORTER", cid, None)
        if cid in ITEM_IDS:
            return ("PLAY_ITEM", cid, None)

        # Fallback: parse the trainer name out of the detail string.
        trainer = _strip_suffix(d[5:])
        if trainer == "Switch":
            return ("PLAY_SWITCH", _name_after_leftarrow(eff), None)
        if cid is not None:
            return ("PLAY_SUPPORTER" if cid in SUPPORTER_IDS else "PLAY_ITEM", cid, None)
        return None

    return None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def export(traj_path: Path, out_path: Path) -> tuple[int, Counter, Counter]:
    by_kind: Counter = Counter()
    by_source: Counter = Counter()
    n_out = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fo, traj_path.open(encoding="utf-8") as fi:
        for line in fi:
            if not line.strip():
                continue
            traj = json.loads(line)
            steps = traj["steps"]
            for i, step in enumerate(steps):
                if _is_effect_step(step):
                    continue
                # find next non-DRAW step as the effect source for commit steps
                next_step = None
                for j in range(i + 1, min(i + 3, len(steps))):
                    if steps[j]["action"]["kind"] != "DRAW":
                        next_step = steps[j]
                        break
                v2 = v2_action_for_step(step, next_step)
                if v2 is None:
                    continue
                kind, primary, sub = v2
                if kind not in V2_KINDS:
                    continue
                rec = {
                    "seed": step.get("seed", traj.get("seed")),
                    "going_first": step.get("going_first", traj.get("going_first")),
                    "turn_limit": step.get("turn_limit", traj.get("turn_limit")),
                    "archetype": step.get("archetype", traj.get("archetype")),
                    "source": step.get("source", traj.get("expert_status", "")),
                    "goal_reached": step.get("goal_reached", traj.get("goal_reached")),
                    "step_index": step.get("step_index", i),
                    "phase": step.get("phase", ""),
                    "difficulty": step.get("difficulty", traj.get("difficulty", "")),
                    "pre_state": step["pre_state"],
                    "action": {"kind": kind, "primary": primary, "sub": sub},
                    "action_zh": step.get("action_zh", ""),
                }
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                by_kind[kind] += 1
                by_source[rec["source"]] += 1
                n_out += 1
    return n_out, by_kind, by_source


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", default=str(DATA / "traj.jsonl"))
    ap.add_argument("--out", default=str(DATA / "state_action_v2.jsonl"))
    args = ap.parse_args()

    n, by_kind, by_source = export(Path(args.traj), Path(args.out))
    manifest = {
        "n_slices": n,
        "by_kind": dict(by_kind),
        "by_source": dict(by_source),
        "n_kinds": len(by_kind),
    }
    (DATA / "manifest_v2.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(f"wrote {n} v2 slices -> {args.out}")
    print("by_kind:")
    for k, c in by_kind.most_common():
        print(f"  {k:>22} {c}")
    print("by_source:", dict(by_source))


if __name__ == "__main__":
    main()
