"""v2 action executor for the OPENING phase.

Shared foundation for: SFT rollout, the RL env, and DAgger hard-set collection.

v2 action representation
------------------------
An action is a triple ``(kind, primary, sub)``:

* ``kind``    - one of ``V2_KINDS`` below. For compound trainers the kind is
  trainer-specific (``PLAY_POFFIN``, ``PLAY_ULTRA_BALL``, ``PLAY_HILDA``, ...)
  so the kind alone determines execution semantics.
* ``primary`` - the main target card id (trainer id / energy id / pokemon id /
  evolution target / promote target / fetched supporter ...). ``None`` when the
  kind has no primary target.
* ``sub``     - the secondary expert-chosen target, used only by compound kinds:
  - ``PLAY_POFFIN``  : second basic to bench (primary = first basic)
  - ``PLAY_HILDA``   : energy to fetch        (primary = evolution target)
  - ``PLAY_CRISPIN`` : energy to hand         (primary = attach-target pokemon id)
  - ``ATTACH``       : attach-target pokemon  (primary = energy id)
  ``None`` otherwise.

Discards for Ultra Ball and the promote target for RETREAT are resolved by the
executor (deterministic heuristics) so the action space stays bounded; only the
expert-valuable decisions are supervised.

This module is reconstructed from bytecode salvage after the original
``inference_rollout.py`` / ``ingest_expert_logs.py`` sources were lost in a
working-tree wipe. The state-mutation API is taken from ``opening_state.py``.
"""
from __future__ import annotations

from typing import Any

from opening_cards import (
    BASIC_IDS,
    BOSS_ORDERS,
    BUDEW,
    CARD_NAMES,
    CRISPIN,
    CRISPIN_BASIC_ENERGY,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    ENERGY_IDS,
    FAN_ROTOM,
    HILDA,
    HILDA_EVOLUTION_IDS,
    IGNITION,
    ITEM_IDS,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    POFFIN,
    POFFIN_IDS,
    POKE_PAD,
    PRISM,
    RULE_BOX_IDS,
    SALVATOR,
    SNORUNT,
    STARYU,
    SUPPORTER_IDS,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
    WATER_ENERGY_IDS,
    WALLYS_COMPASSION,
    can_retreat_pokemon,
    is_pad_legal_target,
    name,
)
from opening_state import OpeningGameState, Pokemon
from opening_bench import can_play_to_bench
from opening_planner import (
    diagnose_gaps,
    _best_attach_target,
    _evolve_best_staryu,
    _meowth_on_bench,
    _pick_ultra_ball_discards,
    _try_salvatore_evolve,
)

# Night Stretcher has no named constant in opening_cards (it is the literal 1097).
NIGHT_STRETCHER = 1097

# Reverse name -> id map for parsing expert detail strings.
# "Dunsparce" is ambiguous (65 / 305); the deck runs 2x65 + 1x305, so prefer 65.
NAME_TO_ID: dict[str, int] = {}
for _cid, _n in CARD_NAMES.items():
    NAME_TO_ID.setdefault(_n, _cid)
NAME_TO_ID["Dunsparce"] = DUNSPARCE_A


def _can_play_supporter(st: OpeningGameState) -> bool:
    return not st.supporter_played


def _run_away_draw(st: OpeningGameState, p: Pokemon) -> bool:
    """Dudunsparce 'Run Away Draw +3': shuffle itself back into the deck, draw 3."""
    if p is st.active:
        st.active = None
    elif p in st.bench:
        st.bench.remove(p)
    else:
        return False
    st.deck.append(DUDUNSPARCE)  # ordered sim: shuffle = append to bottom
    drawn: list[int] = []
    for _ in range(3):
        if not st.deck:
            break
        c = st.deck.pop(0)
        st.hand.append(c)
        drawn.append(c)
    st._log("ABILITY_RUN_AWAY",
            f"Run Away Draw +3 → shuffle {name(DUDUNSPARCE)}; drew {[name(c) for c in drawn]}")
    return True

# v2 action kinds. Compound trainers get their own kind.
V2_KINDS: tuple[str, ...] = (
    "SETUP_ACTIVE", "SETUP_BENCH", "DRAW", "PLAY_POKEMON", "ATTACH", "EVOLVE",
    "PLAY_POFFIN", "PLAY_ULTRA_BALL", "PLAY_HILDA", "PLAY_CRISPIN",
    "PLAY_POKE_PAD", "PLAY_SALVATOR", "PLAY_LILLIE", "PLAY_JUDGE",
    "PLAY_BOSS", "PLAY_COMPASSION", "PLAY_NIGHT_STRETCHER", "PLAY_SWITCH",
    "PLAY_SUPPORTER", "PLAY_ITEM",
    "ABILITY_FAN_CALL", "ABILITY_LAST_DITCH", "ABILITY_RUN_AWAY", "RETREAT",
)

# Kinds that the policy head should never pick (auto / setup-only).
NON_POLICY_KINDS = frozenset({"DRAW", "SETUP_ACTIVE", "SETUP_BENCH"})

# Kinds that carry a meaningful sub-target (head2 active).
COMPOUND_KINDS = frozenset({"PLAY_POFFIN", "PLAY_HILDA", "PLAY_CRISPIN", "ATTACH"})


# --------------------------------------------------------------------------- #
# State snapshot (replaces ingest_expert_logs.state_snapshot)
# --------------------------------------------------------------------------- #
def state_snapshot(st: OpeningGameState) -> dict[str, Any]:
    board = {
        "active": ({"card_id": st.active.card_id, "energies": list(st.active.energies)}
                   if st.active else None),
        "bench": [{"card_id": p.card_id, "energies": list(p.energies)} for p in st.bench],
    }
    gaps = diagnose_gaps(st)
    return {
        "hand_ids": list(st.hand),
        "board": board,
        "deck_len": len(st.deck),
        "prize_len": len(st.prizes),
        "flags": {
            "supporter_played": st.supporter_played,
            "energy_attached": st.energy_attached,
        },
        "gaps": {
            "g1": gaps.g1, "g2": gaps.g2, "g3": gaps.g3,
            "g4": gaps.g4, "g5": gaps.g5, "g6": gaps.g6,
        },
    }


# --------------------------------------------------------------------------- #
# Helpers (reconstructed; originals lived inside the lost inference_rollout.py)
# --------------------------------------------------------------------------- #
def _resolve_pokemon(st: OpeningGameState, card_id: int | None) -> Pokemon | None:
    """Find a board pokemon by card id, preferring active then bench order."""
    if card_id is None:
        return None
    if st.active and st.active.card_id == card_id:
        return st.active
    for p in st.bench:
        if p.card_id == card_id:
            return p
    return None


def _best_promote_idx(st: OpeningGameState) -> int | None:
    """Pick bench index to promote on retreat: watered Mega > Mega > Staryu."""
    for i, p in enumerate(st.bench):
        if p.card_id == MEGA_STARMIE and p.has_water():
            return i
    for i, p in enumerate(st.bench):
        if p.card_id == MEGA_STARMIE:
            return i
    for i, p in enumerate(st.bench):
        if p.card_id == STARYU:
            return i
    return None


def _play_pad_target_to_bench(st: OpeningGameState, target: int) -> None:
    """After Poké Pad searches a basic to hand, bench it if a slot is open."""
    if target not in BASIC_IDS or target not in st.hand:
        return
    if st.bench_open() <= 0 or not can_play_to_bench(st, target):
        return
    st.play_pokemon_to_bench(target)


def _try_evolve_dudunsparce_compress(st: OpeningGameState) -> bool:
    """Evolve a Dunsparce on field to Dudunsparce if Dudunsparce in hand."""
    from opening_cards import DUDUNSPARCE  # local for clarity

    if DUDUNSPARCE not in st.hand:
        return False
    cand = None
    if st.active and st.active.card_id in (DUNSPARCE_A, DUNSPARCE_B) and st._can_evolve_now(st.active):
        cand = st.active
    if cand is None:
        for p in st.bench:
            if p.card_id in (DUNSPARCE_A, DUNSPARCE_B) and st._can_evolve_now(p):
                cand = p
                break
    if cand is None:
        return False
    st.hand.remove(DUDUNSPARCE)
    cand.card_id = DUDUNSPARCE
    st._enforce_prism_on_basic_only(cand)
    st._log("EVOLVE", f"{name(DUNSPARCE_A)} → {name(DUDUNSPARCE)}", DUDUNSPARCE)
    return True


def _play_meowth_fetched_supporter(st: OpeningGameState, gaps, fetched: int | None) -> bool:
    """After Meowth fetches a supporter to hand, play it if still legal this turn."""
    if fetched is None or fetched not in st.hand:
        return False
    if fetched not in SUPPORTER_IDS or not _can_play_supporter(st):
        return False
    if fetched == HILDA:
        st.play_trainer(HILDA, "PLAY Hilda (meowth-fetched)")
        st.hilda_search(need_evolution=gaps.g3, need_energy=gaps.g2)
        return True
    if fetched == CRISPIN:
        tgt = _best_attach_target(st) or st.active
        st.play_trainer(CRISPIN, "PLAY Crispin (meowth-fetched)")
        st.crispin_search(attach_target=tgt)
        return True
    if fetched == LILLIE:
        st.play_trainer(LILLIE, "PLAY Lillie (meowth-fetched)")
        st.lillie_draw()
        return True
    if fetched == SALVATOR:
        return _try_salvatore_evolve(st)
    # Generic supporter: just commit it.
    st.play_trainer(fetched, f"PLAY {name(fetched)} (meowth-fetched)")
    return True


def _poffin_place_pair(st: OpeningGameState, picks: list[int]) -> bool:
    """Place up to 2 expert-chosen basics from deck to bench (Poffin effect)."""
    slots = min(2, st.bench_open())
    if slots <= 0:
        return False
    placed: list[int] = []
    for want in picks:
        if len(placed) >= slots:
            break
        if want not in POFFIN_IDS or want in placed:
            continue
        if want in st.deck:
            st.deck.remove(want)
            st.bench.append(Pokemon(want, st.current_turn))
            placed.append(want)
    if not placed:
        # fall back to the state's priority-based picker
        return st.poffin_to_bench()
    st._log("PLAY_TRAINER", f"Poffin → bench {[name(c) for c in placed]}", POFFIN)
    return True


def _hilda_search_v2(st: OpeningGameState, evo: int | None, energy: int | None) -> None:
    """Hilda fetch up to 2: expert-chosen evolution + expert-chosen energy."""
    from opening_cards import mega_ready_to_land

    want_evo = evo is not None
    want_energy = energy is not None
    ready = mega_ready_to_land(
        staryu_on_field=st.staryu_on_field(),
        mega_starmie_on_field=st._mega_starmie_on_field(),
        line_has_water=st._line_has_water(),
        hand_ids=st.hand,
        supporter_played=st.supporter_played,
        hilda_resolving=True,
    )
    # Do not lock Mega when the land gate is closed — fall back to dynamic priority.
    if evo == MEGA_STARMIE and not ready:
        evo = None
    picks: list[int] = []
    if evo is not None and evo in HILDA_EVOLUTION_IDS and evo in st.deck:
        picks.append(evo)
    if (
        energy is not None
        and energy in (WATER_BASIC, PRISM, IGNITION, DARK_BASIC)
        and energy in st.deck
        and energy not in picks
    ):
        picks.append(energy)
    # Fallback when expert gave nothing usable, or Mega was demoted leaving no evo.
    has_evo_pick = any(c in HILDA_EVOLUTION_IDS for c in picks)
    if not picks or (want_evo and not has_evo_pick):
        st.hilda_search(need_evolution=want_evo, need_energy=want_energy)
        return
    for cid in picks[:2]:
        st.deck.remove(cid)
        st.hand.append(cid)
    st._log("PLAY_TRAINER", f"Hilda → {[name(c) for c in picks[:2]]}", HILDA)


def _crispin_search_v2(st: OpeningGameState, attach_target: Pokemon | None,
                       to_hand_energy: int | None) -> None:
    """Crispin: 2 different Basic Energy - 1 to hand, 1 direct attach."""
    in_deck = [e for e in CRISPIN_BASIC_ENERGY if e in st.deck]
    if not in_deck:
        st._log("NOTE", "Crispin: no Basic Energy in deck")
        return
    attach_id: int | None = None
    to_hand_id: int | None = None
    if to_hand_energy is not None and to_hand_energy in CRISPIN_BASIC_ENERGY and to_hand_energy in in_deck:
        to_hand_id = to_hand_energy
        # attach = the *other* basic energy if available
        for e in in_deck:
            if e != to_hand_id:
                attach_id = e
                break
    if to_hand_id is None:
        # fall back to state priority logic
        st.crispin_search(attach_target=attach_target)
        return
    st.deck.remove(to_hand_id)
    st.hand.append(to_hand_id)
    attached = None
    if (attach_id is not None and attach_target is not None and attach_id != to_hand_id
            and attach_id in st.deck):
        st.deck.remove(attach_id)
        attach_target.energies.append(attach_id)
        st.energy_attached = True
        attached = attach_id
        st._log("ATTACH",
                f"Crispin attach {name(attach_id)} → {name(attach_target.card_id)} on "
                f"{'active' if attach_target is st.active else 'bench'}", attach_id)
    detail = [name(to_hand_id)]
    if attached is not None:
        detail.append(f"attach {name(attached)}")
    st._log("PLAY_TRAINER", f"Crispin → {detail}", CRISPIN)


# --------------------------------------------------------------------------- #
# Main executor
# --------------------------------------------------------------------------- #
def execute_v2(st: OpeningGameState, kind: str,
               primary: int | None = None, sub: int | None = None) -> bool:
    """Apply one v2 action to ``st``. Return True if it mutated the state."""
    gaps = diagnose_gaps(st)

    if kind == "SETUP_ACTIVE":
        if primary in st.hand and st.active is None:
            st.setup_play_active(primary)
            return True
        return False

    if kind == "SETUP_BENCH":
        if primary in st.hand and st.bench_open() > 0:
            st.setup_play_bench(primary)
            return True
        return False

    if kind == "PLAY_POKEMON":
        if (primary in BASIC_IDS and primary in st.hand and st.bench_open() > 0
                and can_play_to_bench(st, primary)):
            st.play_pokemon_to_bench(primary)
            return True
        return False

    if kind == "ATTACH":
        if primary not in ENERGY_IDS or primary not in st.hand or st.energy_attached:
            return False
        tgt = _resolve_pokemon(st, sub) or _best_attach_target(st)
        if tgt is None and st.active is not None:
            tgt = st.active
        if tgt is None:
            return False
        return st.attach_energy_from_hand(tgt, primary)

    if kind == "EVOLVE":
        if primary == MEGA_STARMIE:
            return _evolve_best_staryu(st)
        if primary == DUDUNSPARCE:
            return _try_evolve_dudunsparce_compress(st)
        return False

    if kind == "PLAY_POFFIN":
        if POFFIN not in st.hand:
            return False
        st.play_trainer(POFFIN, "PLAY Poffin (v2)")
        picks = [p for p in (primary, sub) if p is not None]
        _poffin_place_pair(st, picks)
        return True

    if kind == "PLAY_ULTRA_BALL":
        if ULTRA_BALL not in st.hand:
            return False
        target = primary
        if target is None or target not in st.deck:
            # fallback: prefer Staryu then Mega
            field = ({st.active.card_id} if st.active else set()) | {p.card_id for p in st.bench}
            for want in (STARYU, MEGA_STARMIE, DUDUNSPARCE, MEOWTH_EX):
                if want in st.deck and want not in field:
                    target = want
                    break
        if target is None or target not in st.deck:
            return False
        disc = _pick_ultra_ball_discards(st, exclude=frozenset({target, ULTRA_BALL}))
        if len(disc) < 2:
            return False
        st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (v2)")
        st.ultra_ball_search(target, disc)
        return True

    if kind == "PLAY_HILDA":
        if HILDA not in st.hand or not _can_play_supporter(st):
            return False
        st.play_trainer(HILDA, "PLAY Hilda (v2)")
        _hilda_search_v2(st, primary, sub)
        return True

    if kind == "PLAY_CRISPIN":
        if CRISPIN not in st.hand or not _can_play_supporter(st):
            return False
        tgt = _resolve_pokemon(st, primary) or _best_attach_target(st) or st.active
        st.play_trainer(CRISPIN, "PLAY Crispin (v2)")
        _crispin_search_v2(st, tgt, sub)
        return True

    if kind == "PLAY_POKE_PAD":
        if POKE_PAD not in st.hand or st.bench_open() <= 0:
            return False
        target = primary
        if target is None or not is_pad_legal_target(target) or target not in st.deck:
            return False
        st.play_trainer(POKE_PAD, "PLAY Poké Pad (v2)")
        st.poke_pad_search(target)
        _play_pad_target_to_bench(st, target)
        return True

    if kind == "PLAY_SALVATOR":
        if SALVATOR not in st.hand or not _can_play_supporter(st):
            return False
        return _try_salvatore_evolve(st)

    if kind == "PLAY_LILLIE":
        if LILLIE not in st.hand or not _can_play_supporter(st):
            return False
        st.play_trainer(LILLIE, "PLAY Lillie (v2)")
        st.lillie_draw()
        return True

    if kind == "PLAY_JUDGE":
        if JUDGE not in st.hand or not _can_play_supporter(st):
            return False
        st.play_trainer(JUDGE, "PLAY Judge (v2)")
        return True

    if kind == "PLAY_BOSS":
        if BOSS_ORDERS not in st.hand or not _can_play_supporter(st):
            return False
        st.play_trainer(BOSS_ORDERS, "PLAY Boss's Orders (v2)")
        return True

    if kind == "PLAY_COMPASSION":
        if WALLYS_COMPASSION not in st.hand or not _can_play_supporter(st):
            return False
        st.play_trainer(WALLYS_COMPASSION, "PLAY Wally's Compassion (v2)")
        return True

    if kind == "PLAY_NIGHT_STRETCHER":
        if NIGHT_STRETCHER not in st.hand:
            return False
        st.play_trainer(NIGHT_STRETCHER, "PLAY Night Stretcher (v2)")
        # Best-effort: retrieve a basic from discard to hand.
        for cid in (STARYU, FAN_ROTOM, DUNSPARCE_A, BUDEW, SNORUNT):
            if cid in st.discard:
                st.discard.remove(cid)
                st.hand.append(cid)
                st._log("PLAY_TRAINER", f"Night Stretcher → hand {name(cid)}", NIGHT_STRETCHER)
                break
        return True

    if kind == "PLAY_SWITCH":
        if SWITCH not in st.hand:
            return False
        # primary = bench pokemon to promote (defaults to Mega for back-compat).
        if primary is not None:
            idx = next((i for i, p in enumerate(st.bench) if p.card_id == primary), None)
        else:
            idx = next((i for i, p in enumerate(st.bench) if p.card_id == MEGA_STARMIE), None)
        if idx is None:
            return False
        st.hand.remove(SWITCH)
        st.discard.append(SWITCH)
        old_active = st.active
        st.active = st.bench.pop(idx)
        if old_active:
            st.bench.append(old_active)
        st._log("PLAY_SWITCH", f"Switch → Active ← {name(st.active.card_id)}", SWITCH)
        return True

    if kind == "PLAY_SUPPORTER":
        if primary is None or primary not in SUPPORTER_IDS or not _can_play_supporter(st):
            return False
        st.play_trainer(primary, f"PLAY {name(primary)} (v2)")
        return True

    if kind == "PLAY_ITEM":
        if primary is None or primary not in ITEM_IDS or primary not in st.hand:
            return False
        st.play_trainer(primary, f"PLAY {name(primary)} (v2)")
        return True

    if kind == "ABILITY_FAN_CALL":
        on_field = (st.active is not None and st.active.card_id == FAN_ROTOM) or \
                   any(p.card_id == FAN_ROTOM for p in st.bench)
        if on_field and not st.fan_call_used:
            st.fan_call()
            return True
        return False

    if kind == "ABILITY_LAST_DITCH":
        meowth_on_field = (st.active is not None and st.active.card_id == MEOWTH_EX) \
                          or any(p.card_id == MEOWTH_EX for p in st.bench)
        if st.supporter_played:
            return False
        if not meowth_on_field:
            # place Meowth to bench from hand if possible, then it's on field
            if MEOWTH_EX in st.hand and st.bench_open() > 0 and can_play_to_bench(st, MEOWTH_EX):
                st.play_pokemon_to_bench(MEOWTH_EX)
                meowth_on_field = True
            if not meowth_on_field:
                return False
        from opening_meowth import meowth_opening_last_ditch_priority
        pri = (primary,) if primary is not None and primary in SUPPORTER_IDS else \
              meowth_opening_last_ditch_priority(st, gaps)
        if not pri:
            return False
        fetched = st.meowth_last_ditch_catch(pri)
        _play_meowth_fetched_supporter(st, gaps, fetched)
        return True

    if kind == "ABILITY_RUN_AWAY":
        p = None
        if st.active and st.active.card_id == DUDUNSPARCE:
            p = st.active
        else:
            for bp in st.bench:
                if bp.card_id == DUDUNSPARCE:
                    p = bp
                    break
        if p is None:
            return False
        return _run_away_draw(st, p)

    if kind == "RETREAT":
        idx = _best_promote_idx(st) if primary is None else None
        if primary is not None:
            for i, p in enumerate(st.bench):
                if p.card_id == primary:
                    idx = i
                    break
        if idx is None:
            return False
        if not st.active or not can_retreat_pokemon(st.active.card_id, st.active.energies):
            return False
        return st.retreat_promote_bench(idx)

    return False

