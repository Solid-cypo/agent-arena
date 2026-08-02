"""Gap diagnosis and turn action planning for OPENING (unlimited turns)."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from opening_cards import (
    BOSS_ORDERS,
    BUDEW,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    ENERGY_IDS,
    FAN_CALL_BENCH_PRIORITY,
    FAN_ROTOM,
    HILDA,
    IGNITION,
    JUDGE,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    NIGHT_STRETCHER,
    POKE_PAD,
    POFFIN,
    PRISM,
    RISKY_RUINS,
    SALVATOR,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    UNFAIR_STAMP,
    WALLYS_COMPASSION,
    WATER_BASIC,
    can_retreat_pokemon,
    name,
    pad_pokemon_candidates,
    retreat_cost_for,
)
from opening_state import OpeningGameState, Pokemon
from turn_planner import AcquirePlan, discard_value


@dataclass
class GapFlags:
    g1: bool = False
    g2: bool = False
    g3: bool = False
    g4: bool = False
    g5: bool = False


def diagnose_gaps(st: OpeningGameState) -> GapFlags:
    g = GapFlags()
    staryus = st.all_staryu()
    megas = _megas_on_field(st)
    g.g1 = not staryus and not megas
    if staryus:
        g.g2 = not any(p.has_water() for _, _, p in staryus)
        g.g4 = any(not st._can_evolve_now(p) for _, _, p in staryus)
    elif megas:
        g.g2 = not any(p.has_water() for p in megas)
    g.g3 = MEGA_STARMIE not in st.hand and not megas
    if st.active and st.active.card_id != MEGA_STARMIE:
        for p in st.bench:
            if p.card_id == MEGA_STARMIE and p.has_water():
                g.g5 = True
    return g


def _megas_on_field(st: OpeningGameState) -> list[Pokemon]:
    out: list[Pokemon] = []
    if st.active and st.active.card_id == MEGA_STARMIE:
        out.append(st.active)
    out.extend(p for p in st.bench if p.card_id == MEGA_STARMIE)
    return out


def fan_rotom_dead(st: OpeningGameState) -> bool:
    return st.my_turn_number >= 2 and FAN_ROTOM in st.hand


def prefer_bench_staryu(st: OpeningGameState) -> bool:
    return st.setup_active_id != STARYU


def _has_search(st: OpeningGameState) -> bool:
    return any(c in st.hand for c in (HILDA, POFFIN, POKE_PAD, ULTRA_BALL, CRISPIN))


def _needs_emergency_draw(st: OpeningGameState, gaps: GapFlags) -> bool:
    """Lillie is kept/used when legal — not discarded as Ultra Ball fodder.

    Prefer Lillie when supporter is legal and the hand still misses the opening
    line with no Item search left. Going-first T1 remains blocked by E-SUP-1.
    Pad cannot fetch Mega (Rule Box) — do not let Pad alone block Lillie for g3.
    Never wash Dudunsparce / Ignition retreat fuel / Switch when Goal is close.
    Also allow Lillie for pure water gap (g2) when no energy search remains.
    """
    if LILLIE not in st.hand or not st.can_play_supporter():
        return False
    # Only defer Lillie for Run Away when a Dunsparce on field can actually evolve.
    if DUDUNSPARCE in st.hand and any(
        p.card_id in (DUNSPARCE_A, DUNSPARCE_B) and st._can_evolve_now(p)
        for p in ([st.active] if st.active else []) + list(st.bench)
    ):
        return False  # expert: evolve/Run Away before Lillie when ready
    mega_ready = (
        MEGA_STARMIE in st.hand
        or _mega_ready_on_bench(st)
        or (st.active and st.active.card_id == MEGA_STARMIE)
    )
    # Pure water gap FIRST: Ultra Ball / Poffin cannot fetch energy — don't block Lillie.
    if (
        gaps.g2
        and st.staryu_on_field()
        and mega_ready
        and not any(e in st.hand for e in (WATER_BASIC, PRISM))
        and not any(c in st.hand for c in (HILDA, CRISPIN))
        and (WATER_BASIC in st.deck or PRISM in st.deck)
    ):
        return True
    if any(c in st.hand for c in (HILDA, POFFIN, ULTRA_BALL, SALVATOR, CRISPIN)):
        return False
    if not gaps.g1 and not gaps.g3:
        return False
    # Pad fixes g1 (Staryu) but never g3 (Mega). Block Lillie only when Pad can help.
    if POKE_PAD in st.hand and gaps.g1 and STARYU in st.deck:
        return False
    if POKE_PAD in st.hand and not gaps.g3:
        return False
    # Goal nearly ready: keep Ignition/Switch/Dark for retreat instead of washing.
    if st.staryu_on_field() and any(
        c in st.hand for c in (SWITCH, IGNITION, DARK_BASIC, WATER_BASIC, PRISM)
    ):
        mega_reachable = (
            MEGA_STARMIE in st.hand
            or _mega_ready_on_bench(st)
            or (ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck)
            or (HILDA in st.hand and MEGA_STARMIE in st.deck)
            or (SALVATOR in st.hand and MEGA_STARMIE in st.deck)
        )
        if mega_reachable and not gaps.g2:
            return False
        # If only water is missing, Ignition/Dark don't fix g2 — allow Lillie.
        if mega_reachable and gaps.g2 and any(e in st.hand for e in (WATER_BASIC, PRISM)):
            return False
    return bool(gaps.g1 or gaps.g3 or gaps.g2)


def _try_ignition_retreat_to_free_bench(st: OpeningGameState) -> bool:
    """Fan Rotom / paid Active: Ignition attach → retreat onto free-retreat Bench.

    Expert 33927: Fan Call then retreat same turn with Ignition (don't EOT-discard).
    Do this even if Mega is in hand — free-retreat Active lets the water attach
    go to Staryu next turn while still promoting Mega for free.
    """
    if st.active is None or st.energy_attached:
        return False
    if IGNITION not in st.hand and DARK_BASIC not in st.hand:
        return False
    if can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False
    idx = _free_retreat_bench_idx(st)
    if idx is None:
        return False
    # Don't retreat away if Mega is already on Bench ready to promote this turn.
    if _mega_ready_on_bench(st):
        return False
    fuel = IGNITION if IGNITION in st.hand else DARK_BASIC
    if not st.attach_energy_from_hand(st.active, fuel):
        return False
    return st.retreat_promote_bench(idx)


def _try_play_lillie(st: OpeningGameState) -> bool:
    if LILLIE not in st.hand or not st.can_play_supporter():
        return False
    # Bench hand Basics first so Lillie does not wash them away (expert: 土龙弟弟未放置).
    _bench_hand_basics(st)
    # Attach water to Staryu before washing the hand (expert 28485).
    if not st.energy_attached:
        for _, _, p in st.all_staryu():
            if not p.has_water() and any(e in st.hand for e in (WATER_BASIC, PRISM)):
                st.attach_water_to(p)
                break
    if not st.play_trainer(LILLIE, "PLAY Lillie (keep/use)"):
        return False
    st.lillie_draw()
    return True


def _dudunsparce_on_field(st: OpeningGameState) -> bool:
    if st.active and st.active.card_id == DUDUNSPARCE:
        return True
    return any(p.card_id == DUDUNSPARCE for p in st.bench)


def _maybe_judge_before_runaway(st: OpeningGameState) -> bool:
    """Play Judge only after Dudunsparce is on field (before Run Away).

    Never Judge while Dudunsparce is still only in hand — that washes the evolve piece.
    Never Judge while Goal is unfinished and hand still holds Mega-fetch / retreat tools.
    """
    if JUDGE not in st.hand or not st.can_play_supporter():
        return False
    if not _dudunsparce_on_field(st):
        return False
    if not st.opening_complete():
        # Protect Goal tools from Judge wash (expert 31317/29887).
        if any(c in st.hand for c in (ULTRA_BALL, SWITCH, HILDA, SALVATOR, MEGA_STARMIE)):
            return False
        if st.staryu_on_field() and gaps_need_mega(st):
            return False
    if not st.play_trainer(JUDGE, "PLAY Judge (before Run Away)"):
        return False
    returned = list(st.hand)
    st.deck.extend(returned)
    st.hand.clear()
    st._shuffle_deck_inplace()
    for _ in range(4):
        if not st.deck:
            break
        st.hand.append(st.deck.pop(0))
    st._log("NOTE", f"裁判后手牌: {[name(c) for c in st.hand]}")
    return True


def gaps_need_mega(st: OpeningGameState) -> bool:
    return diagnose_gaps(st).g3


def _mega_ready_on_bench(st: OpeningGameState) -> bool:
    return any(p.card_id == MEGA_STARMIE for p in st.bench)


def _free_retreat_bench_idx(st: OpeningGameState) -> int | None:
    """Bench index of a free-retreat Pokémon (prefer Dunsparce 65)."""
    for i, p in enumerate(st.bench):
        if can_retreat_pokemon(p.card_id, p.energies) and retreat_cost_for(p.card_id) == 0:
            return i
    return None


def _attach_retreat_fuel(st: OpeningGameState) -> bool:
    """Attach one energy to Active for retreat. Skip free-retreat Actives.

    Only call when promotion/retreat will happen this turn — never park Ignition
    on Active and let EOT discard it unused (expert: 引火贴能回合结束丢弃).
    Prefer Dark/Ignition over Water/Prism so Staryu keeps the water attach.
    Never burn the last Water/Prism on Active while any Staryu is still dry.
    """
    if st.active is None or st.energy_attached:
        return False
    if can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False  # already free / paid
    staryu_needs_water = any(not p.has_water() for _, _, p in st.all_staryu())
    for e in (DARK_BASIC, IGNITION):
        if e in st.hand:
            return st.attach_energy_from_hand(st.active, e)
    # Water/Prism only if Staryu already watered (or no Staryu on field).
    if staryu_needs_water:
        return False
    for e in (WATER_BASIC, PRISM):
        if e in st.hand:
            return st.attach_energy_from_hand(st.active, e)
    return False


def _retreat_to_free_bench_if_ignition_parked(st: OpeningGameState) -> bool:
    """If Ignition is on Active and Mega not ready, retreat onto free-retreat Bench.

    Prevents EOT Ignition discard with nothing gained (expert 33927).
    """
    if st.active is None or IGNITION not in st.active.energies:
        return False
    if _mega_ready_on_bench(st):
        return False  # promote path will consume the attach
    if not can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False
    idx = _free_retreat_bench_idx(st)
    if idx is None:
        return False
    return st.retreat_promote_bench(idx)


def _bench_fan_call_picks(st: OpeningGameState, picks: list[int] | None = None) -> None:
    st.bench_fan_call_picks(picks)


def _try_evolve_dudunsparce(st: OpeningGameState) -> bool:
    """Evolve field Dunsparce → Dudunsparce (Run Away Draw engine).

    Prefer Bench over Active so Run Away does not empty the Active slot —
    EXCEPT when Mega is on Bench and Active is Dunsparce: then evolve Active
    so Run Away promotes Mega (expert 31317 / no Switch).

    Never evolve while Mega is still only in hand — finish water+evolve first
    so Dudunsparce remains for Active→Run Away promote (expert 31317).
    """
    if DUDUNSPARCE not in st.hand:
        return False
    if (
        MEGA_STARMIE in st.hand
        and st.staryu_on_field()
        and not _mega_ready_on_bench(st)
        and not st.opening_complete()
    ):
        return False
    cand = None
    mega_needs_promote = _mega_ready_on_bench(st) and (
        st.active is None or st.active.card_id != MEGA_STARMIE
    )
    if (
        mega_needs_promote
        and st.active
        and st.active.card_id in (DUNSPARCE_A, DUNSPARCE_B)
        and st._can_evolve_now(st.active)
    ):
        cand = st.active
    if cand is None:
        for p in st.bench:
            if p.card_id in (DUNSPARCE_A, DUNSPARCE_B) and st._can_evolve_now(p):
                cand = p
                break
    if cand is None and (
        st.active
        and st.active.card_id in (DUNSPARCE_A, DUNSPARCE_B)
        and st._can_evolve_now(st.active)
    ):
        cand = st.active
    if cand is None:
        return False
    st.hand.remove(DUDUNSPARCE)
    base = cand.card_id
    cand.card_id = DUDUNSPARCE
    st._enforce_prism_on_basic_only(cand)
    st._log("EVOLVE", f"{name(base)} → {name(DUDUNSPARCE)}", DUDUNSPARCE)
    return True


def _try_run_away_draw(st: OpeningGameState) -> bool:
    """Use Dudunsparce Run Away Draw when on field (draw 3, shuffle self back).

    Prefer Active Dudunsparce when Mega is on Bench (promote via empty Active).
    Otherwise prefer Bench so Active is not emptied.
    """
    from opening_exec import _run_away_draw

    mega_needs_promote = _mega_ready_on_bench(st) and (
        st.active is None or st.active.card_id != MEGA_STARMIE
    )
    if mega_needs_promote and st.active and st.active.card_id == DUDUNSPARCE:
        return _run_away_draw(st, st.active)
    for p in list(st.bench):
        if p.card_id == DUDUNSPARCE:
            return _run_away_draw(st, p)
    if st.active and st.active.card_id == DUDUNSPARCE:
        return _run_away_draw(st, st.active)
    return False


def _meowth_can_fetch_hilda(st: OpeningGameState) -> bool:
    """True if Meowth is in hand and Last-Ditch can fetch a useful Supporter.

    Last-Ditch only triggers when playing Meowth from hand onto Bench — Setup
    Active Meowth (F1) cannot fire it.
    """
    if MEOWTH_EX not in st.hand or st.bench_open() <= 0:
        return False
    if not st.can_play_supporter():
        return False
    for c in (HILDA, CRISPIN, SALVATOR, LILLIE, JUDGE):
        if c in st.deck and c not in st.hand:
            return True
    return False


def _maybe_fan_call_after_poffin(st: OpeningGameState) -> None:
    if not _fan_call_ready(st):
        return
    if any(p.card_id == FAN_ROTOM for p in st.bench) or (
        st.active and st.active.card_id == FAN_ROTOM
    ):
        picks = st.fan_call()
        _bench_fan_call_picks(st, picks)
        _play_staryu_from_hand(st)


def _try_salvatore_evolve(st: OpeningGameState) -> bool:
    if SALVATOR not in st.hand or not st.can_play_supporter() or MEGA_STARMIE not in st.deck:
        return False
    # Prefer watered Staryu — dry Salvatore leaves Goal incomplete (expert 31317).
    watered = [(z, i, p) for z, i, p in st.all_staryu() if p.has_water()]
    dry = [(z, i, p) for z, i, p in st.all_staryu() if not p.has_water()]
    # If water is still fixable this turn, only Salvatore onto watered Staryu.
    water_fixable = any(e in st.hand for e in (WATER_BASIC, PRISM)) or (
        CRISPIN in st.hand and st.can_play_supporter()
    ) or (HILDA in st.hand and st.can_play_supporter()) or (
        LILLIE in st.hand and st.can_play_supporter() and (WATER_BASIC in st.deck or PRISM in st.deck)
    )
    order = watered if (watered or water_fixable) else (watered + dry)
    if not order and dry and not water_fixable:
        order = dry  # last resort
    order = sorted(order, key=lambda x: 0 if x[2] is st.active else 1)
    for _, _, p in order:
        if st.salvatore_evolve_staryu(p):
            return True
    return False


def _bench_hand_basics(st: OpeningGameState) -> None:
    """Place useful Basics from hand (Dunsparce / Fan / Budew / Snorunt) before draw engines."""
    from opening_bench import can_play_to_bench
    from opening_cards import BUDEW, DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM, SNORUNT

    for cid in (DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM, BUDEW, SNORUNT):
        while cid in st.hand and st.bench_open() > 0 and can_play_to_bench(st, cid):
            # Don't double Fan Rotom.
            if cid == FAN_ROTOM and (
                (st.active and st.active.card_id == FAN_ROTOM)
                or any(p.card_id == FAN_ROTOM for p in st.bench)
            ):
                break
            st.play_pokemon_to_bench(cid)


def _execute_f_b_recovery(st: OpeningGameState) -> bool:
    """F-B: Staryu+water on field, missing 1031."""
    if _try_salvatore_evolve(st):
        _finish_goal_sequence(st)
        return True
    if HILDA in st.hand and st.can_play_supporter():
        _play_hilda(st, "PLAY Hilda F-B", need_evolution=True, need_energy=False)
        _finish_goal_sequence(st)
        return True
    if ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
        disc = _pick_ultra_ball_discards(st)
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball F-B")
            st.ultra_ball_search(MEGA_STARMIE, disc)
        _finish_goal_sequence(st)
        return True
    return False


def _execute_meowth_opening_turn(st: OpeningGameState, gaps: GapFlags) -> None:
    """B1/F1+: Meowth → Hilda chain; must bench 1030 on T1 (CP1)."""
    st.play_meowth_to_bench_with_catch()
    if gaps.g1 and POFFIN in st.hand:
        st.play_trainer(POFFIN, "PLAY Poffin (Meowth line)")
        st.poffin_to_bench()
        _maybe_fan_call_after_poffin(st)
    elif gaps.g1 and POKE_PAD in st.hand and STARYU in st.deck:
        st.play_trainer(POKE_PAD, "PLAY Pad (Meowth line)")
        st.poke_pad_search(STARYU)
    if HILDA in st.hand and st.can_play_supporter():
        _play_hilda(st, "PLAY Hilda after Meowth", need_evolution=True, need_energy=True)
    elif CRISPIN in st.hand and st.can_play_supporter() and gaps.g2:
        _play_crispin(st, "PLAY Crispin (Meowth line)", _best_attach_target(st))
    _play_staryu_from_hand(st)
    tgt = _best_attach_target(st)
    if tgt and not st.energy_attached:
        st.attach_water_to(tgt)
    _ensure_cp1_staryu(st)


def _fan_call_ready(st: OpeningGameState) -> bool:
    if st.my_turn_number != 1 or st.fan_call_used:
        return False
    on_field = (st.active and st.active.card_id == FAN_ROTOM) or any(
        p.card_id == FAN_ROTOM for p in st.bench
    )
    if on_field:
        return True
    return FAN_ROTOM in st.hand and not fan_rotom_dead(st)


def _best_attach_target(st: OpeningGameState) -> Pokemon | None:
    if st.active and st.active.card_id == MEGA_STARMIE and not st.active.has_water():
        return st.active
    for _, _, p in st.all_staryu():
        if not p.has_water():
            return p
    for p in _megas_on_field(st):
        if not p.has_water():
            return p
    return None


def _play_staryu_from_hand(st: OpeningGameState) -> None:
    if STARYU not in st.hand or st.bench_open() <= 0:
        return
    if prefer_bench_staryu(st) or st.active is None or st.active.card_id != STARYU:
        st.play_pokemon_to_bench(STARYU)


def _evolve_best_staryu(st: OpeningGameState) -> bool:
    if MEGA_STARMIE not in st.hand:
        return False
    order = sorted(st.all_staryu(), key=lambda x: 0 if x[2] is st.active else 1)
    for _, _, p in order:
        if st._can_evolve_now(p):
            st.evolve_staryu(p, MEGA_STARMIE)
            return True
    return False


def _has_staryu_source(st: OpeningGameState) -> bool:
    return STARYU in st.hand or STARYU in st.deck or st.staryu_on_field()


def _hilda_can_setup_chain(st: OpeningGameState, gaps: GapFlags) -> bool:
    """R1-T1: Hilda + a way to put 1030 on field (hand, Pad, or Ball)."""
    if HILDA not in st.hand or not st.can_play_supporter():
        return False
    if STARYU in st.hand or st.staryu_on_field():
        return True
    if POKE_PAD in st.hand and STARYU in st.deck:
        return True
    if ULTRA_BALL in st.hand and STARYU in st.deck:
        return True
    return False


def _pick_ultra_ball_discards(st: OpeningGameState, *, exclude: frozenset[int] = frozenset()) -> list[int]:
    """Pick two lowest-value cards using the live AcquirePlan value scale."""
    if not st.staryu_on_field() and STARYU not in st.hand:
        targets = (STARYU,)
    elif MEGA_STARMIE not in st.hand and not _mega_ready_on_bench(st):
        targets = (MEGA_STARMIE,)
    else:
        targets = ()
    protect = {
        STARYU, MEGA_STARMIE, WATER_BASIC, HILDA, POKE_PAD, POFFIN,
        NIGHT_STRETCHER, PRISM,
    } | set(exclude) | set(targets)
    if (
        st.active
        and st.active.card_id != MEGA_STARMIE
        and not can_retreat_pokemon(st.active.card_id, st.active.energies)
    ):
        protect.update({IGNITION, DARK_BASIC, SWITCH})
    release = {RISKY_RUINS, WALLYS_COMPASSION, BOSS_ORDERS, UNFAIR_STAMP}
    if fan_rotom_dead(st):
        release.add(FAN_ROTOM)
    if targets == (MEGA_STARMIE,):
        release.add(JUDGE)
    if st.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
        release.update({IGNITION, DARK_BASIC, SWITCH})

    values: dict[int, int] = {}
    for cid in set(st.hand):
        if cid == ULTRA_BALL:
            values[cid] = 10_000
        elif cid in protect:
            values[cid] = 9_000
        elif cid in release:
            values[cid] = 20
        elif cid in (LILLIE, CRISPIN, SALVATOR, DUDUNSPARCE):
            values[cid] = 500
        else:
            values[cid] = 100
    plan = AcquirePlan(
        targets=targets,
        sources=(ULTRA_BALL,),
        ball_allowed=True,
        ball_reason="opening gap",
        discard_values=tuple(values.items()),
        recover_target=None,
    )
    candidates = [
        (discard_value(cid, plan), index, cid)
        for index, cid in enumerate(st.hand)
        if cid not in exclude and cid != ULTRA_BALL and discard_value(cid, plan) < 8_000
    ]
    candidates.sort()
    return [cid for _, _, cid in candidates[:2]]


def _play_hilda(st: OpeningGameState, detail: str, *, need_evolution: bool, need_energy: bool) -> bool:
    if HILDA not in st.hand or not st.can_play_supporter():
        return False
    if not st.play_trainer(HILDA, detail):
        return False
    st.hilda_search(need_evolution=need_evolution, need_energy=need_energy)
    return True


def _play_crispin(st: OpeningGameState, detail: str, attach_target: Pokemon | None) -> bool:
    if CRISPIN not in st.hand or not st.can_play_supporter():
        return False
    if not st.play_trainer(CRISPIN, detail):
        return False
    st.crispin_search(attach_target=attach_target)
    return True


def _execute_r1_t1(st: OpeningGameState, gaps: GapFlags) -> None:
    """Hilda → 1031+水；Pad/Ball/手牌 → 1030 Bench → ATTACH → finish."""
    if STARYU in st.hand:
        _play_hilda(st, "PLAY Hilda (G1 chain)", need_evolution=True, need_energy=True)
        _play_staryu_from_hand(st)
    elif POKE_PAD in st.hand and STARYU in st.deck and not st.staryu_on_field():
        st.play_trainer(POKE_PAD, "PLAY Poké Pad (pre-Hilda)")
        st.poke_pad_search(STARYU)
        _play_staryu_from_hand(st)
        _play_hilda(st, "PLAY Hilda (G1 chain)", need_evolution=True, need_energy=True)
    elif ULTRA_BALL in st.hand and STARYU in st.deck and not st.staryu_on_field():
        disc = _pick_ultra_ball_discards(st, exclude=frozenset({HILDA}))
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (pre-Hilda)")
            st.ultra_ball_search(STARYU, disc)
        _play_staryu_from_hand(st)
        _play_hilda(st, "PLAY Hilda (G1 chain)", need_evolution=True, need_energy=True)
    else:
        _play_hilda(st, "PLAY Hilda (G1 chain)", need_evolution=True, need_energy=True)
    tgt = _best_attach_target(st)
    if tgt and not st.energy_attached:
        st.attach_water_to(tgt)


def _ensure_cp1_staryu(st: OpeningGameState) -> None:
    """My-T1 must end with Staryu on field (G4 blocks same-turn evolve on T2)."""
    if st.my_turn_number != 1 or st.staryu_on_field():
        return
    for _ in range(4):
        if st.staryu_on_field():
            return
        if STARYU in st.hand:
            _play_staryu_from_hand(st)
            return
        if _fan_call_ready(st):
            if FAN_ROTOM in st.hand and st.bench_open() > 0:
                if not any(p.card_id == FAN_ROTOM for p in st.bench):
                    if not st.active or st.active.card_id != FAN_ROTOM:
                        st.play_pokemon_to_bench(FAN_ROTOM)
            picks = st.fan_call()
            _bench_fan_call_picks(st, picks)
            _play_staryu_from_hand(st)
            if st.staryu_on_field():
                return
        if POFFIN in st.hand and STARYU in st.deck:
            st.play_trainer(POFFIN, "PLAY Poffin (CP1 rescue)")
            st.poffin_to_bench()
            _play_staryu_from_hand(st)
            if st.staryu_on_field():
                return
        if POKE_PAD in st.hand and STARYU in st.deck:
            st.play_trainer(POKE_PAD, "PLAY Pad (CP1 rescue)")
            st.poke_pad_search(STARYU)
            _play_staryu_from_hand(st)
            if st.staryu_on_field():
                return
        if ULTRA_BALL in st.hand and STARYU in st.deck:
            excl = frozenset({HILDA}) if HILDA in st.hand and st.can_play_supporter() else frozenset()
            disc = _pick_ultra_ball_discards(st, exclude=excl)
            if len(disc) >= 2:
                st.play_trainer(ULTRA_BALL, "PLAY Ball (CP1 rescue)")
                st.ultra_ball_search(STARYU, disc)
                _play_staryu_from_hand(st)
                return
        break


def _ensure_cp1_resources(st: OpeningGameState) -> None:
    """After 1030 on field: attach water + fetch 1031 if supporter slot left."""
    if st.my_turn_number != 1 or not st.staryu_on_field():
        return
    gaps = diagnose_gaps(st)
    if gaps.g3 and HILDA in st.hand and st.can_play_supporter():
        _play_hilda(st, "PLAY Hilda (CP1 tail)", need_evolution=True, need_energy=gaps.g2)
        gaps = diagnose_gaps(st)
    tgt = _best_attach_target(st)
    if tgt and gaps.g2 and not st.energy_attached:
        st.attach_water_to(tgt)


def _promote_mega_to_active(st: OpeningGameState) -> None:
    """Promote Mega to Active: free/paid retreat first (keep Switch), Switch last."""
    if st.active and st.active.card_id == MEGA_STARMIE:
        return
    idx = next(
        (i for i, p in enumerate(st.bench) if p.card_id == MEGA_STARMIE and p.has_water()),
        None,
    )
    if idx is None:
        idx = next(
            (i for i, p in enumerate(st.bench) if p.card_id == MEGA_STARMIE),
            None,
        )
    if idx is None:
        return
    # Free retreat or already paid → retreat (preserve Switch).
    if st.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
        st.retreat_promote_bench(idx)
        return
    # Pay retreat with one attach (Ignition OK same-turn before EOT discard).
    # Prefer Dark/Ignition so we don't steal Water from Staryu when attach still free.
    if not st.energy_attached:
        _attach_retreat_fuel(st)
    if st.active and not can_retreat_pokemon(st.active.card_id, st.active.energies):
        if not st.energy_attached:
            if CRISPIN in st.hand and st.can_play_supporter():
                _play_crispin(st, "PLAY Crispin (retreat setup)", st.active)
            elif HILDA in st.hand and st.can_play_supporter():
                _play_hilda(st, "PLAY Hilda (retreat energy)", need_evolution=False, need_energy=True)
                _attach_retreat_fuel(st)
    if st.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
        st.retreat_promote_bench(idx)
        return
    # Last resort: Switch (expert prefers retreat when possible).
    st.switch_mega_to_active()


def _try_resolve_water(st: OpeningGameState, gaps: GapFlags) -> bool:
    """G2 fix: attach / Crispin / Hilda-energy (Pad cannot fetch energy)."""
    if not gaps.g2 or st.energy_attached:
        return False
    tgt = _best_attach_target(st)
    if tgt and any(e in st.hand for e in (WATER_BASIC, PRISM)):
        st.attach_water_to(tgt)
        return True
    if CRISPIN in st.hand and st.can_play_supporter() and tgt is not None:
        _play_crispin(st, "PLAY Crispin (water gap)", tgt)
        return True
    if HILDA in st.hand and st.can_play_supporter():
        _play_hilda(st, "PLAY Hilda (energy only)", need_evolution=False, need_energy=True)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return True
    # Pad cannot fetch energy (E-PAD-1). Do not call Pad as a G2 water fix.
    return False


def _water_fixable_this_turn(st: OpeningGameState) -> bool:
    if any(e in st.hand for e in (WATER_BASIC, PRISM)):
        return True
    if CRISPIN in st.hand and st.can_play_supporter():
        return True
    if HILDA in st.hand and st.can_play_supporter():
        return True
    # Lillie can dig Water/Prism from deck (expert 31317).
    if (
        LILLIE in st.hand
        and st.can_play_supporter()
        and (WATER_BASIC in st.deck or PRISM in st.deck)
    ):
        return True
    # Pad is Pokémon-only — never counts as water-fixable.
    return False


def _try_fetch_mega(st: OpeningGameState, gaps: GapFlags) -> bool:
    """G3 fix when 1030 already on field."""
    if not gaps.g3 or not st.staryu_on_field():
        return False
    if gaps.g2 and not _water_fixable_this_turn(st):
        return False
    if HILDA in st.hand and st.can_play_supporter():
        _play_hilda(st, "PLAY Hilda (mega+energy)", need_evolution=True, need_energy=gaps.g2)
        return True
    if ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
        excl = frozenset({HILDA}) if HILDA in st.hand and st.can_play_supporter() else frozenset()
        disc = _pick_ultra_ball_discards(st, exclude=excl)
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (mega)")
            st.ultra_ball_search(MEGA_STARMIE, disc)
            return True
    if _meowth_on_bench(st):
        fetched = st.meowth_last_ditch_catch()
        if fetched == HILDA and HILDA in st.hand and st.can_play_supporter():
            _play_hilda(st, "PLAY Hilda via Meowth", need_evolution=True, need_energy=gaps.g2)
            return True
    return False


def _staryu_ready_to_evolve(st: OpeningGameState) -> bool:
    """Do not EVOLVE dry Staryu when water is still fixable this turn."""
    staryus = st.all_staryu()
    if not staryus or not any(st._can_evolve_now(p) for _, _, p in staryus):
        return False
    if any(p.has_water() for _, _, p in staryus):
        return True
    gaps = diagnose_gaps(st)
    if not gaps.g2:
        return True
    if any(e in st.hand for e in (WATER_BASIC, PRISM)):
        return True
    if CRISPIN in st.hand and st.can_play_supporter():
        return True
    if HILDA in st.hand and st.can_play_supporter():
        return True
    return False


def _try_complete_goal(st: OpeningGameState) -> bool:
    if st.opening_complete():
        return True
    _bench_hand_basics(st)
    # Always water Staryu before Salvatore / evolve when water is in hand.
    if not st.energy_attached:
        for _, _, p in st.all_staryu():
            if not p.has_water() and any(e in st.hand for e in (WATER_BASIC, PRISM)):
                st.attach_water_to(p)
                break
    if _try_salvatore_evolve(st):
        _promote_mega_to_active(st)
        return st.opening_complete()
    # Only run Dudunsparce engine here when Goal pieces are NOT ready.
    # Otherwise Judge/Run Away can wash Mega/Switch needed for Goal.
    if not _goal_pieces_ready(st) and _try_evolve_dudunsparce(st):
        _maybe_judge_before_runaway(st)
        _try_run_away_draw(st)
        return st.opening_complete()
    gaps = diagnose_gaps(st)
    # Attach retreat fuel only when Mega is already on Bench (will promote this turn).
    # Never park Ignition early — EOT discards unused Ignition (expert 33927/30870).
    if (
        st.active
        and st.active.card_id != MEGA_STARMIE
        and _mega_ready_on_bench(st)
        and not can_retreat_pokemon(st.active.card_id, st.active.energies)
        and SWITCH not in st.hand
    ):
        _attach_retreat_fuel(st)
    if _needs_emergency_draw(st, gaps) and _try_play_lillie(st):
        # After Lillie, immediately try water attach if drawn.
        if not st.energy_attached:
            for _, _, p in st.all_staryu():
                if not p.has_water() and any(e in st.hand for e in (WATER_BASIC, PRISM)):
                    st.attach_water_to(p)
                    break
        return st.opening_complete()
    # S1: Active Staryu evolve in place
    if st.setup_active_id == STARYU and st.active and st.active.card_id == STARYU:
        if not gaps.g3 and MEGA_STARMIE in st.hand and _staryu_ready_to_evolve(st):
            if _evolve_best_staryu(st):
                return st.opening_complete()
    # B1/C1/A1: prepare retreat only when Mega ready (same-turn promote).
    if (
        st.setup_active_id != STARYU
        and st.staryu_on_field()
        and _mega_ready_on_bench(st)
    ):
        _prepare_bench_evolve_line(st)
    gaps = diagnose_gaps(st)
    if not gaps.g3 and st.all_staryu() and MEGA_STARMIE in st.hand and _staryu_ready_to_evolve(st):
        if _evolve_best_staryu(st):
            _promote_mega_to_active(st)
            return st.opening_complete()
    # After watering / evolving Mega onto Bench: if Active is Dunsparce, prefer
    # Active evolve → Run Away to promote Mega (saves Switch / attach slot).
    if (
        not st.opening_complete()
        and _mega_ready_on_bench(st)
        and st.active
        and st.active.card_id in (DUNSPARCE_A, DUNSPARCE_B)
        and DUDUNSPARCE in st.hand
        and st._can_evolve_now(st.active)
    ):
        st.hand.remove(DUDUNSPARCE)
        base = st.active.card_id
        st.active.card_id = DUDUNSPARCE
        st._enforce_prism_on_basic_only(st.active)
        st._log("EVOLVE", f"{name(base)} → {name(DUDUNSPARCE)}", DUDUNSPARCE)
        _try_run_away_draw(st)
        if st.opening_complete():
            return True
    # Or free/paid retreat promote.
    if gaps.g5 or (
        st.active
        and st.active.card_id != MEGA_STARMIE
        and any(p.card_id == MEGA_STARMIE for p in st.bench)
    ):
        _promote_mega_to_active(st)
        return st.opening_complete()
    _retreat_to_free_bench_if_ignition_parked(st)
    return False


def _finish_goal_sequence(st: OpeningGameState) -> None:
    """Water → mega fetch → evolve → promote until opening_complete; then optional draw engine."""
    for _ in range(12):
        if st.opening_complete():
            break
        gaps = diagnose_gaps(st)
        if _try_resolve_water(st, gaps):
            continue
        gaps = diagnose_gaps(st)
        if gaps.g3 and st.staryu_on_field():
            if _try_fetch_mega(st, gaps):
                continue
        if _try_complete_goal(st):
            break
        gaps = diagnose_gaps(st)
        tgt = _best_attach_target(st)
        if tgt and gaps.g2 and not st.energy_attached:
            st.attach_water_to(tgt)
            continue
        gaps = diagnose_gaps(st)
        if gaps.g3 and st.staryu_on_field() and not gaps.g2:
            if HILDA in st.hand and st.can_play_supporter():
                _play_hilda(st, "PLAY Hilda (finish F-B)", need_evolution=True, need_energy=False)
                continue
            if ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
                disc = _pick_ultra_ball_discards(st)
                if len(disc) >= 2:
                    st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (finish F-B)")
                    st.ultra_ball_search(MEGA_STARMIE, disc)
                    continue
        break
    # Mid/post-goal: Pad for Dudunsparce / Run Away when still available (expert depth).
    _mid_goal_draw_engine(st)
    if st.opening_complete():
        _post_goal_draw_engine(st)


def _mid_goal_draw_engine(st: OpeningGameState) -> None:
    """Pad→Dudunsparce / evolve / Judge / Run Away — usable mid- or post-goal."""
    _bench_hand_basics(st)
    # Prefer evolving hand Dudunsparce before Pad (expert 29993: evolve then Lillie).
    if _try_evolve_dudunsparce(st):
        _maybe_judge_before_runaway(st)
        _try_run_away_draw(st)
    if POKE_PAD in st.hand and DUDUNSPARCE in st.deck:
        on_field: set[int] = set()
        if st.active:
            on_field.add(st.active.card_id)
        on_field.update(p.card_id for p in st.bench)
        if DUDUNSPARCE in pad_pokemon_candidates(on_field=on_field) and not _dudunsparce_on_field(st):
            # Only Pad-search if we have a Dunsparce that can evolve next / now.
            has_base = any(
                p.card_id in (DUNSPARCE_A, DUNSPARCE_B)
                for p in ([st.active] if st.active else []) + list(st.bench)
            )
            if has_base or DUDUNSPARCE not in st.hand:
                st.play_trainer(POKE_PAD, "PLAY Pad (Dudunsparce)")
                st.poke_pad_search(DUDUNSPARCE)
    if _try_evolve_dudunsparce(st):
        _maybe_judge_before_runaway(st)
        _try_run_away_draw(st)
    elif _dudunsparce_on_field(st):
        _maybe_judge_before_runaway(st)
        _try_run_away_draw(st)


def _post_goal_draw_engine(st: OpeningGameState) -> None:
    """After Goal: Pad→Dudunsparce / Judge-before-RunAway / evolve / Run Away."""
    _mid_goal_draw_engine(st)


def _deck_has_water(st: OpeningGameState) -> bool:
    from opening_cards import PRISM
    return WATER_BASIC in st.deck or PRISM in st.deck


def _pad_search_priority(st: OpeningGameState, gaps: GapFlags) -> None:
    """Pad fetch via shared Pokémon priority (E-PAD-1: never energy).

    Historical bug: this path used to search WATER_BASIC/PRISM when g2, which
    ``is_pad_legal_target`` rejects — the PLAY was wasted. Energy gaps must be
    closed by Hilda / Crispin / Ultra Ball / attach, not Pad.
    """
    if POKE_PAD not in st.hand:
        return
    on_field: set[int] = set()
    if st.active:
        on_field.add(st.active.card_id)
    on_field.update(p.card_id for p in st.bench)
    cands = [
        c for c in pad_pokemon_candidates(on_field=on_field)
        if c in st.deck
    ]
    if not cands:
        return
    st.play_trainer(POKE_PAD, "PLAY Poké Pad REC")
    st.poke_pad_search(cands[0])


def _salvatore_ready(st: OpeningGameState) -> bool:
    """Salvatore searches Mega from deck and may evolve same-turn / setup Pokémon.

    Skip when Mega is already in hand (expert 35135/33672 — don't waste Salvator).
    """
    if MEGA_STARMIE in st.hand:
        return False
    return (
        st.can_play_supporter()
        and SALVATOR in st.hand
        and MEGA_STARMIE in st.deck
        and st.staryu_on_field()
    )


def can_reach_goal(st: OpeningGameState) -> bool:
    gaps = diagnose_gaps(st)
    if st.opening_complete():
        return True
    if gaps.g1:
        return (
            _has_search(st)
            or (st.my_turn_number == 1 and _fan_call_ready(st))
            or LILLIE in st.hand
            or STARYU in st.deck
        )
    if gaps.g3:
        return _has_search(st) or MEGA_STARMIE in st.deck
    if gaps.g2:
        return (
            any(e in st.hand for e in (WATER_BASIC, 16))
            or HILDA in st.hand
            or CRISPIN in st.hand
            or any(e in st.deck for e in (WATER_BASIC, 16))
        )
    if gaps.g4:
        return MEGA_STARMIE in st.hand or MEGA_STARMIE in st.deck
    return True


def pick_route(st: OpeningGameState, gaps: GapFlags) -> str:
    t = st.my_turn_number
    if st.opening_complete():
        return "GOAL"

    if t == 1:
        if _salvatore_ready(st):
            return "R8-T1"
        # Mega already in hand — only need 1030 + water on field (high priority)
        if MEGA_STARMIE in st.hand:
            if st.staryu_on_field() and gaps.g2 and not st.energy_attached:
                if any(e in st.hand for e in ENERGY_IDS):
                    return "R5-T1"
                if CRISPIN in st.hand and st.can_play_supporter():
                    return "R7c-T1"
            if gaps.g1 and _hilda_can_setup_chain(st, gaps):
                return "R1-T1"
            if gaps.g1 and POFFIN in st.hand:
                return "R2-T1"
            if gaps.g1 and POKE_PAD in st.hand and STARYU in st.deck:
                return "R3-T1"
            if gaps.g1 and ULTRA_BALL in st.hand and STARYU in st.deck:
                return "R3b-T1"
        # R7: S1 Active Staryu — Hilda/Crispin for mega + energy (§5.1 priority)
        if st.setup_active_id == STARYU and st.staryu_on_field():
            if (gaps.g2 or gaps.g3) and HILDA in st.hand and st.can_play_supporter():
                return "R7-T1"
            if gaps.g2 and CRISPIN in st.hand and st.can_play_supporter():
                return "R7c-T1"
        # R5: 1030 on field, attach water
        if st.staryu_on_field() and gaps.g2 and not st.energy_attached:
            if any(e in st.hand for e in ENERGY_IDS):
                return "R5-T1"
        # R4: Fan Call line
        if _fan_call_ready(st):
            return "R4-T1"
        # R1: Hilda + staryu source (before Poffin per §5.1)
        if gaps.g1 and _hilda_can_setup_chain(st, gaps):
            return "R1-T1"
        # Meowth → Hilda (B1/F1)
        if gaps.g1 and _meowth_can_fetch_hilda(st):
            return "R-Meowth-T1"
        # R6: 1030 on field, need 1031
        if st.staryu_on_field() and gaps.g3 and HILDA in st.hand and st.can_play_supporter():
            return "R6-T1"
        if gaps.g1 and ULTRA_BALL in st.hand and STARYU in st.deck:
            return "R3b-T1"
        if gaps.g1 and POKE_PAD in st.hand and STARYU in st.deck:
            return "R3-T1"
        if gaps.g1 and POFFIN in st.hand:
            return "R2-T1"
        if gaps.g3 and HILDA in st.hand and st.can_play_supporter():
            return "R6-T1"
        if gaps.g2 and not st.energy_attached:
            if HILDA in st.hand and st.can_play_supporter() and not gaps.g1:
                return "R7-T1"
            if CRISPIN in st.hand and st.can_play_supporter():
                return "R7c-T1"
            if any(e in st.hand for e in ENERGY_IDS):
                return "R5-T1"
        return "R-IDLE-T1"

    # My-T2 goal routes (§5.2) before recovery typing
    if t == 2:
        if st.opening_complete():
            return "GOAL"
        if gaps.g5:
            return "R2-T2"
        if st.all_staryu() and not gaps.g2 and MEGA_STARMIE in st.hand:
            if any(st._can_evolve_now(p) for _, _, p in st.all_staryu()):
                return "R1-T2"
        if st.all_staryu() and gaps.g2 and MEGA_STARMIE in st.hand:
            return "R3-T2"
        if st.all_staryu() and gaps.g3 and not gaps.g2:
            if HILDA in st.hand and st.can_play_supporter():
                return "R4b-T2"
            if ULTRA_BALL in st.hand:
                return "R4-T2"
        if gaps.g1 and _has_search(st):
            return "R6-T2"

    # T2+ unified recovery
    miss = classify_miss(st)
    if miss == "F-F":
        return "R2-REC"
    if miss == "F-A":
        return "R1-REC"
    if miss == "F-B":
        if HILDA in st.hand and st.can_play_supporter():
            return "R3b-REC"
        if ULTRA_BALL in st.hand:
            return "R3-REC"
        if POFFIN in st.hand:
            return "R2-REC"
        if POKE_PAD in st.hand and STARYU in st.deck:
            return "R5-REC"
        return "R5-REC"
    if miss == "F-C":
        # Water gap only — Pad cannot fetch energy (E-PAD-1). Prefer Hilda/Crispin/attach.
        if not st.energy_attached:
            if HILDA in st.hand and st.can_play_supporter():
                return "R4b-REC"
            if CRISPIN in st.hand and st.can_play_supporter():
                return "R4c-REC"
            return "R4-REC"
        return "R1-REC"
    if miss == "F-D":
        if HILDA in st.hand and st.can_play_supporter():
            return "R3b-REC"
        if POKE_PAD in st.hand:
            return "R5-REC"
        if ULTRA_BALL in st.hand:
            return "R3-REC"
        if CRISPIN in st.hand and st.can_play_supporter():
            return "R4c-REC"
        return "R5-REC"

    # F-E
    if HILDA in st.hand and st.can_play_supporter():
        return "R5-REC"
    if POFFIN in st.hand and gaps.g1:
        return "R2-REC"
    if POKE_PAD in st.hand:
        return "R5-REC"
    if ULTRA_BALL in st.hand and gaps.g1:
        return "R3-REC"
    if not can_reach_goal(st) and BUDEW in st.hand:
        return "R8-REC"
    if CRISPIN in st.hand and st.can_play_supporter() and gaps.g2:
        return "R4c-REC"
    return "R-IDLE-REC"



def _meowth_on_bench(st: OpeningGameState) -> bool:
    return any(p.card_id == MEOWTH_EX for p in st.bench)


def _try_fetch_staryu(st: OpeningGameState, gaps: GapFlags) -> bool:
    """G1 fix: bench 1030 via Meowth / Fan / Hilda chain / items / hand."""
    if not gaps.g1:
        return False
    if _meowth_can_fetch_hilda(st):
        st.play_meowth_to_bench_with_catch()
        if POFFIN in st.hand and STARYU in st.deck:
            st.play_trainer(POFFIN, "PLAY Poffin (Meowth line)")
            st.poffin_to_bench()
        elif POKE_PAD in st.hand and STARYU in st.deck:
            st.play_trainer(POKE_PAD, "PLAY Pad (Meowth line)")
            st.poke_pad_search(STARYU)
        if HILDA in st.hand and st.can_play_supporter():
            _play_hilda(st, "PLAY Hilda (Meowth line)", need_evolution=True, need_energy=True)
        _play_staryu_from_hand(st)
        return True
    if _hilda_can_setup_chain(st, gaps):
        _execute_r1_t1(st, gaps)
        return True
    if _fan_call_ready(st) and st.my_turn_number == 1:
        if FAN_ROTOM in st.hand and st.bench_open() > 0:
            if not any(p.card_id == FAN_ROTOM for p in st.bench):
                if not st.active or st.active.card_id != FAN_ROTOM:
                    st.play_pokemon_to_bench(FAN_ROTOM)
        picks = st.fan_call()
        _bench_fan_call_picks(st, picks)
        _play_staryu_from_hand(st)
        if not st.staryu_on_field() and POFFIN in st.hand and STARYU in st.deck:
            st.play_trainer(POFFIN, "PLAY Poffin (Fan line)")
            st.poffin_to_bench()
            _maybe_fan_call_after_poffin(st)
        elif not st.staryu_on_field() and POKE_PAD in st.hand and STARYU in st.deck:
            st.play_trainer(POKE_PAD, "PLAY Pad (Fan line)")
            st.poke_pad_search(STARYU)
        elif not st.staryu_on_field() and ULTRA_BALL in st.hand and STARYU in st.deck:
            excl = frozenset({HILDA}) if HILDA in st.hand and st.can_play_supporter() else frozenset()
            disc = _pick_ultra_ball_discards(st, exclude=excl)
            if len(disc) >= 2:
                st.play_trainer(ULTRA_BALL, "PLAY Ball (Fan line)")
                st.ultra_ball_search(STARYU, disc)
        _play_staryu_from_hand(st)
        return True
    if MEGA_STARMIE in st.hand and gaps.g1:
        if POFFIN in st.hand and STARYU in st.deck:
            st.play_trainer(POFFIN, "PLAY Poffin (mega-in-hand)")
            st.poffin_to_bench()
            _play_staryu_from_hand(st)
            return True
        if POKE_PAD in st.hand and STARYU in st.deck:
            st.play_trainer(POKE_PAD, "PLAY Pad (mega-in-hand)")
            st.poke_pad_search(STARYU)
            _play_staryu_from_hand(st)
            return True
        if ULTRA_BALL in st.hand and STARYU in st.deck:
            excl = frozenset({HILDA}) if HILDA in st.hand and st.can_play_supporter() else frozenset()
            disc = _pick_ultra_ball_discards(st, exclude=excl)
            if len(disc) >= 2:
                st.play_trainer(ULTRA_BALL, "PLAY Ball (mega-in-hand)")
                st.ultra_ball_search(STARYU, disc)
                _play_staryu_from_hand(st)
                return True
        if STARYU in st.hand:
            _play_staryu_from_hand(st)
            return True
    if POFFIN in st.hand and STARYU in st.deck:
        st.play_trainer(POFFIN, "PLAY Poffin")
        st.poffin_to_bench()
        _maybe_fan_call_after_poffin(st)
        _play_staryu_from_hand(st)
        return True
    if POKE_PAD in st.hand and STARYU in st.deck:
        st.play_trainer(POKE_PAD, "PLAY Pad")
        st.poke_pad_search(STARYU)
        _play_staryu_from_hand(st)
        return True
    if ULTRA_BALL in st.hand and STARYU in st.deck:
        excl = frozenset({HILDA}) if HILDA in st.hand and st.can_play_supporter() else frozenset()
        disc = _pick_ultra_ball_discards(st, exclude=excl)
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ball (staryu)")
            st.ultra_ball_search(STARYU, disc)
            _play_staryu_from_hand(st)
            return True
    if STARYU in st.hand:
        _play_staryu_from_hand(st)
        return True
    return False


def _goal_pieces_ready(st: OpeningGameState) -> bool:
    """True when Mega+water line can finish this turn (evolve and/or promote)."""
    if st.opening_complete():
        return True
    if st.active and st.active.card_id == MEGA_STARMIE:
        return True
    if _mega_ready_on_bench(st):
        return True
    watered = any(p.has_water() for _, _, p in st.all_staryu())
    mega_in_hand = MEGA_STARMIE in st.hand
    return bool(st.staryu_on_field() and watered and mega_in_hand)


def _greedy_opening_turn(st: OpeningGameState) -> None:
    """Phase-ordered turn planner: water → CP1 staryu → mega → evolve → promote."""
    # Fan Call first so Ignition retreat has a free-retreat Bench target (33927).
    if _fan_call_ready(st):
        picks = st.fan_call()
        _bench_fan_call_picks(st, picks)
        _play_staryu_from_hand(st)
    _bench_hand_basics(st)
    for _ in range(20):
        if st.opening_complete():
            _mid_goal_draw_engine(st)
            return
        gaps = diagnose_gaps(st)
        acted = False

        # Early Ignition retreat onto free-retreat Bench (expert 33927).
        if _try_ignition_retreat_to_free_bench(st):
            acted = True
            continue

        # Finish Goal BEFORE draw-engine when pieces are ready (don't burn Judge/supporter).
        if _goal_pieces_ready(st):
            before_complete = st.opening_complete()
            _try_complete_goal(st)
            if st.opening_complete():
                _mid_goal_draw_engine(st)
                return
            # Still unfinished but pieces ready: attach retreat / promote, don't Judge-wash.
            gaps = diagnose_gaps(st)
            if _try_resolve_water(st, gaps):
                acted = True
                continue
            if st.staryu_on_field() and gaps.g3 and _try_fetch_mega(st, gaps):
                acted = True
                continue
            if (
                st.active
                and st.active.card_id != MEGA_STARMIE
                and _mega_ready_on_bench(st)
            ):
                before = st.active.card_id if st.active else None
                _promote_mega_to_active(st)
                if st.opening_complete() or (st.active and st.active.card_id != before):
                    acted = True
                    continue
            # Do not fall through to Run Away / Judge while Goal is finishable.
            if not acted:
                break

        # Prefer Dudunsparce engine only when Goal is not yet finishable
        # AND we are not sitting on Mega-in-hand with a pure water gap (Lillie first).
        gaps = diagnose_gaps(st)
        pure_water_gap = (
            gaps.g2
            and MEGA_STARMIE in st.hand
            and st.staryu_on_field()
            and not any(e in st.hand for e in (WATER_BASIC, PRISM))
        )
        if pure_water_gap and _needs_emergency_draw(st, gaps) and _try_play_lillie(st):
            acted = True
            continue
        # Fetch Mega with Ultra Ball / Hilda BEFORE burning the turn on Run Away.
        if (
            gaps.g3
            and st.staryu_on_field()
            and _try_fetch_mega(st, gaps)
        ):
            acted = True
            continue
        if (
            not _goal_pieces_ready(st)
            and not pure_water_gap
            and DUDUNSPARCE in st.hand
            # Keep Dudunsparce for Active→Run Away Mega promote (expert 31317).
            and not (MEGA_STARMIE in st.hand or _mega_ready_on_bench(st) or (
                ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck and st.staryu_on_field()
            ))
            and _try_evolve_dudunsparce(st)
        ):
            _maybe_judge_before_runaway(st)
            _try_run_away_draw(st)
            acted = True
            continue

        if _try_complete_goal(st):
            _mid_goal_draw_engine(st)
            return

        if gaps.g5 or (
            st.active
            and st.active.card_id != MEGA_STARMIE
            and any(p.card_id == MEGA_STARMIE and p.has_water() for p in st.bench)
        ):
            before = st.active.card_id if st.active else None
            _promote_mega_to_active(st)
            if st.opening_complete() or (st.active and st.active.card_id != before):
                acted = True
                continue

        if _try_resolve_water(st, gaps):
            acted = True
            continue

        # Water gap with Mega in hand: Lillie dig for Water (expert 31317 T2).
        gaps = diagnose_gaps(st)
        if (
            gaps.g2
            and MEGA_STARMIE in st.hand
            and st.staryu_on_field()
            and _needs_emergency_draw(st, gaps)
            and _try_play_lillie(st)
        ):
            acted = True
            continue

        gaps = diagnose_gaps(st)
        if st.staryu_on_field() and gaps.g3:
            if _try_fetch_mega(st, gaps):
                acted = True
                continue

        # After Mega is in hand: dig water BEFORE Run Away (expert 31317).
        gaps = diagnose_gaps(st)
        if (
            gaps.g2
            and MEGA_STARMIE in st.hand
            and st.staryu_on_field()
            and _needs_emergency_draw(st, gaps)
            and _try_play_lillie(st)
        ):
            acted = True
            continue
        if _try_resolve_water(st, diagnose_gaps(st)):
            acted = True
            continue
        # With Mega+water ready: finish Goal before any more Run Away.
        if _goal_pieces_ready(st) and _try_complete_goal(st):
            _mid_goal_draw_engine(st)
            return

        gaps = diagnose_gaps(st)
        if gaps.g1:
            if _try_fetch_staryu(st, gaps):
                acted = True
                continue

        if _try_evolve_dudunsparce(st):
            gaps = diagnose_gaps(st)
            if not (
                gaps.g2
                and MEGA_STARMIE in st.hand
                and st.staryu_on_field()
            ):
                _maybe_judge_before_runaway(st)
                _try_run_away_draw(st)
            acted = True
            continue

        # After failed Lillie dig, try a second Lillie if still pure water gap.
        gaps = diagnose_gaps(st)
        if (
            gaps.g2
            and MEGA_STARMIE in st.hand
            and st.staryu_on_field()
            and LILLIE in st.hand
            and st.can_play_supporter()
            and _try_play_lillie(st)
        ):
            acted = True
            continue

        # Pad → Dudunsparce only when Mega gap is closed (don't delay Goal for depth).
        gaps = diagnose_gaps(st)
        if (
            not gaps.g3
            and not gaps.g2
            and POKE_PAD in st.hand
            and DUDUNSPARCE in st.deck
            and not _dudunsparce_on_field(st)
            and DUDUNSPARCE not in st.hand
            and any(
                p.card_id in (DUNSPARCE_A, DUNSPARCE_B)
                for p in ([st.active] if st.active else []) + list(st.bench)
            )
        ):
            on_field: set[int] = set()
            if st.active:
                on_field.add(st.active.card_id)
            on_field.update(p.card_id for p in st.bench)
            if DUDUNSPARCE in pad_pokemon_candidates(on_field=on_field):
                st.play_trainer(POKE_PAD, "PLAY Pad (Dudunsparce)")
                st.poke_pad_search(DUDUNSPARCE)
                if _try_evolve_dudunsparce(st):
                    _maybe_judge_before_runaway(st)
                    _try_run_away_draw(st)
                acted = True
                continue

        gaps = diagnose_gaps(st)
        if _needs_emergency_draw(st, gaps) and _try_play_lillie(st):
            acted = True
            continue

        if not acted:
            break

    if st.my_turn_number == 1:
        _ensure_cp1_staryu(st)
        _ensure_cp1_resources(st)
    if not st.opening_complete():
        _finish_goal_sequence(st)
    else:
        _mid_goal_draw_engine(st)
    # Last chance: don't leave Ignition to EOT discard if free-retreat Bench exists.
    _retreat_to_free_bench_if_ignition_parked(st)


def _turn_poffin_primary(st: OpeningGameState) -> None:
    if POFFIN in st.hand and STARYU in st.deck:
        st.play_trainer(POFFIN, "PLAY Poffin (search primary)")
        st.poffin_to_bench()
        _maybe_fan_call_after_poffin(st)
        _play_staryu_from_hand(st)


def _turn_pad_primary(st: OpeningGameState) -> None:
    if POKE_PAD in st.hand and STARYU in st.deck:
        st.play_trainer(POKE_PAD, "PLAY Pad (search primary)")
        st.poke_pad_search(STARYU)
        _play_staryu_from_hand(st)


def _turn_water_first(st: OpeningGameState) -> None:
    gaps = diagnose_gaps(st)
    _try_resolve_water(st, gaps)


def _run_turn_pipeline(st: OpeningGameState, *, pre=None, primary=None) -> None:
    if pre:
        pre(st)
    # Do NOT Ignition-retreat before Fan Call — greedy handles Fan Call first.
    if primary == "r1":
        gaps = diagnose_gaps(st)
        if _hilda_can_setup_chain(st, gaps):
            _execute_r1_t1(st, gaps)
        elif not pre:
            _greedy_opening_turn(st)
    elif primary == "meowth":
        gaps = diagnose_gaps(st)
        if _meowth_can_fetch_hilda(st) or MEOWTH_EX in st.hand:
            _execute_meowth_opening_turn(st, gaps)
        elif not pre:
            _greedy_opening_turn(st)
    elif primary == "fan":
        gaps = diagnose_gaps(st)
        if not _try_fetch_staryu(st, gaps) and not pre:
            _greedy_opening_turn(st)
        else:
            _greedy_opening_turn(st)
    else:
        _greedy_opening_turn(st)
    if st.my_turn_number == 1:
        _ensure_cp1_staryu(st)
        _ensure_cp1_resources(st)
    if not st.opening_complete():
        _finish_goal_sequence(st)
    else:
        _mid_goal_draw_engine(st)
    _retreat_to_free_bench_if_ignition_parked(st)


def _prepare_bench_evolve_line(st: OpeningGameState) -> bool:
    """Attach retreat cost only when Active cannot already retreat AND Mega is ready."""
    if st.setup_active_id == STARYU or st.active is None:
        return False
    if SWITCH in st.hand:
        return False
    if not _mega_ready_on_bench(st) and MEGA_STARMIE not in st.hand:
        return False
    if can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False
    return _attach_retreat_fuel(st)


def _score_opening_state(st: OpeningGameState) -> int:
    if st.opening_complete():
        score = 100_000
    else:
        score = 0
    gaps = diagnose_gaps(st)
    if st.staryu_on_field():
        score += 800
        if any(p.has_water() for _, _, p in st.all_staryu()):
            score += 400
    if MEGA_STARMIE in st.hand:
        score += 350
    megas = _megas_on_field(st)
    if megas:
        score += 500
        if any(p.has_water() for p in megas):
            score += 600
        if st.active and st.active.card_id == MEGA_STARMIE and st.active.has_water():
            score = max(score, 100_000)
    if st.my_turn_number == 1 and not st.staryu_on_field():
        score -= 3000
    if gaps.g2:
        score -= 250
    if gaps.g3:
        score -= 200
    # Prefer Run Away / Pad-Dudun depth (expert high-depth feedback).
    for a in st.log:
        if a.kind == "ABILITY_RUN_AWAY":
            score += 80
        if a.kind == "PLAY_TRAINER" and a.card_id == POKE_PAD and a.detail and "Dudun" in a.detail:
            score += 40
        if a.kind == "PLAY_TRAINER" and a.card_id == JUDGE:
            score += 20
    # Penalize wasted Ignition EOT discard without a same-turn retreat.
    ign_attach = False
    retreated = False
    for a in st.log:
        if a.kind == "ATTACH" and a.detail and "Ignition" in a.detail:
            ign_attach = True
            retreated = False
        if a.kind == "RETREAT":
            retreated = True
        if a.kind == "NOTE" and a.detail and "Ignition" in a.detail and "discard" in a.detail.lower():
            if ign_attach and not retreated:
                score -= 120
    return score


def _apply_turn_log(st: OpeningGameState, trial: OpeningGameState, log_start: int) -> None:
    st.hand = copy.deepcopy(trial.hand)
    st.deck = list(trial.deck)
    st.discard = list(trial.discard)
    st.active = copy.deepcopy(trial.active)
    st.bench = copy.deepcopy(trial.bench)
    st.supporter_played = trial.supporter_played
    st.energy_attached = trial.energy_attached
    st.fan_call_used = trial.fan_call_used
    st.log.extend(trial.log[log_start:])


def plan_and_execute_turn(st: OpeningGameState) -> str:
    log_start = len(st.log)
    gaps0 = diagnose_gaps(st)
    st._log(
        "NOTE",
        f"T{st.my_turn_number} gaps=G1:{gaps0.g1} G2:{gaps0.g2} "
        f"G3:{gaps0.g3} G4:{gaps0.g4} miss={classify_miss(st)}",
    )

    if st.my_turn_number == 1:
        candidates: list[tuple[str, object | None, str | None]] = [
            ("GREEDY-T1", None, None),
            ("R1-T1", None, "r1"),
            ("MEOWTH-T1", None, "meowth"),
            ("FAN-T1", None, "fan"),
            ("POFFIN-T1", _turn_poffin_primary, None),
            ("PAD-T1", _turn_pad_primary, None),
        ]
        if _hilda_can_setup_chain(st, gaps0):
            candidates.insert(0, ("R1-T1", None, "r1"))
        if _meowth_can_fetch_hilda(st):
            candidates.insert(0, ("MEOWTH-T1", None, "meowth"))
    else:
        candidates = [
            ("GREEDY-T2", None, None),
            ("BENCH-T2", _prepare_bench_evolve_line, None),
            ("WATER-T2", _turn_water_first, None),
        ]

    best_route = f"GREEDY-T{st.my_turn_number}"
    best_score = -10**9
    best_trial: OpeningGameState | None = None
    for route, pre, primary in candidates:
        trial = copy.deepcopy(st)
        trial.log = list(st.log)
        _run_turn_pipeline(trial, pre=pre, primary=primary)
        score = _score_opening_state(trial)
        if score > best_score:
            best_score = score
            best_route = route
            best_trial = trial

    if best_trial is not None:
        _apply_turn_log(st, best_trial, log_start)
    st._log("NOTE", f"Route={best_route} score={best_score}")
    return best_route


def classify_miss(st: OpeningGameState) -> str:
    if st.opening_complete():
        return "OK"
    gaps = diagnose_gaps(st)
    megas = _megas_on_field(st)
    if megas and not gaps.g2 and st.active and st.active.card_id == MEGA_STARMIE:
        return "OK"
    if gaps.g5:
        return "F-F"
    if st.all_staryu() and not gaps.g2 and MEGA_STARMIE in st.hand:
        if any(st._can_evolve_now(p) for _, _, p in st.all_staryu()):
            return "F-A"
        return "F-E"
    if not gaps.g1 and gaps.g2 and not gaps.g3:
        return "F-C"
    if not gaps.g1 and not gaps.g2 and gaps.g3:
        return "F-B"
    if not gaps.g1 and gaps.g2 and gaps.g3:
        return "F-D"
    return "F-E"
