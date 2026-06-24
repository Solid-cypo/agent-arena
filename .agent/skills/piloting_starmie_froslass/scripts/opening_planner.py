"""Gap diagnosis and turn action planning for OPENING (unlimited turns)."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from opening_cards import (
    BUDEW,
    CRISPIN,
    ENERGY_IDS,
    FAN_ROTOM,
    HILDA,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    POKE_PAD,
    POFFIN,
    PRISM,
    SALVATOR,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
    can_retreat_pokemon,
    name,
)
from opening_state import OpeningGameState, Pokemon


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
    """OPENING 禁 Lillie（HR-O6）— 永不触发紧急 Lillie 线。"""
    return False


def _meowth_can_fetch_hilda(st: OpeningGameState) -> bool:
    return (
        MEOWTH_EX in st.hand
        and HILDA in st.deck
        and st.bench_open() > 0
        and not st.supporter_played
    )


def _maybe_fan_call_after_poffin(st: OpeningGameState) -> None:
    if not _fan_call_ready(st):
        return
    if any(p.card_id == FAN_ROTOM for p in st.bench):
        st.fan_call()
        _play_staryu_from_hand(st)


def _try_salvatore_evolve(st: OpeningGameState) -> bool:
    if SALVATOR not in st.hand or st.supporter_played or MEGA_STARMIE not in st.deck:
        return False
    order = sorted(st.all_staryu(), key=lambda x: 0 if x[2] is st.active else 1)
    for _, _, p in order:
        if not st._can_evolve_now(p):
            continue
        if st.salvatore_evolve_staryu(p):
            return True
    return False


def _execute_f_b_recovery(st: OpeningGameState) -> bool:
    """F-B: Staryu+water on field, missing 1031."""
    if _try_salvatore_evolve(st):
        _finish_goal_sequence(st)
        return True
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda F-B")
        st.hilda_search(need_evolution=True, need_energy=False)
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
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda after Meowth")
        st.hilda_search(need_evolution=True, need_energy=True)
    elif CRISPIN in st.hand and not st.supporter_played and gaps.g2:
        st.play_trainer(CRISPIN, "PLAY Crispin (Meowth line)")
        tgt = _best_attach_target(st)
        st.crispin_search(attach_target=tgt)
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
    if HILDA not in st.hand or st.supporter_played:
        return False
    if STARYU in st.hand or st.staryu_on_field():
        return True
    if POKE_PAD in st.hand and STARYU in st.deck:
        return True
    if ULTRA_BALL in st.hand and STARYU in st.deck:
        return True
    return False


def _pick_ultra_ball_discards(st: OpeningGameState, *, exclude: frozenset[int] = frozenset()) -> list[int]:
    disc: list[int] = []
    for cid in st.hand:
        if cid in exclude:
            continue
        if cid == LILLIE:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid in exclude:
            continue
        if fan_rotom_dead(st) and cid == FAN_ROTOM:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid in exclude:
            continue
        if cid == 1260 and cid not in disc:  # Risky Ruins
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid in exclude:
            continue
        if cid == POKE_PAD and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid in exclude:
            continue
        if cid == POFFIN and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in list(st.hand):
        if cid in exclude:
            continue
        if cid != ULTRA_BALL and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            break
    return disc[:2]


def _execute_r1_t1(st: OpeningGameState, gaps: GapFlags) -> None:
    """Hilda → 1031+水；Pad/Ball/手牌 → 1030 Bench → ATTACH → finish."""
    if STARYU in st.hand:
        st.play_trainer(HILDA, "PLAY Hilda (G1 chain)")
        st.hilda_search(need_evolution=True, need_energy=True)
        _play_staryu_from_hand(st)
    elif POKE_PAD in st.hand and STARYU in st.deck and not st.staryu_on_field():
        st.play_trainer(POKE_PAD, "PLAY Poké Pad (pre-Hilda)")
        st.poke_pad_search(STARYU)
        _play_staryu_from_hand(st)
        if HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda (G1 chain)")
            st.hilda_search(need_evolution=True, need_energy=True)
    elif ULTRA_BALL in st.hand and STARYU in st.deck and not st.staryu_on_field():
        disc = _pick_ultra_ball_discards(st, exclude=frozenset({HILDA}))
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (pre-Hilda)")
            st.ultra_ball_search(STARYU, disc)
        _play_staryu_from_hand(st)
        if HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda (G1 chain)")
            st.hilda_search(need_evolution=True, need_energy=True)
    elif HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (G1 chain)")
        st.hilda_search(need_evolution=True, need_energy=True)
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
                    st.play_pokemon_to_bench(FAN_ROTOM)
            st.fan_call()
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
            excl = frozenset({HILDA}) if HILDA in st.hand and not st.supporter_played else frozenset()
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
    if gaps.g3 and HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (CP1 tail)")
        st.hilda_search(need_evolution=True, need_energy=gaps.g2)
        gaps = diagnose_gaps(st)
    tgt = _best_attach_target(st)
    if tgt and gaps.g2 and not st.energy_attached:
        st.attach_water_to(tgt)


def _promote_mega_to_active(st: OpeningGameState) -> None:
    if st.active and st.active.card_id == MEGA_STARMIE:
        return
    if st.switch_mega_to_active():
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
    if st.active and not can_retreat_pokemon(st.active.card_id, st.active.energies):
        if not st.energy_attached:
            for e in ENERGY_IDS:
                if e in st.hand:
                    st.attach_energy_from_hand(st.active, e)
                    break
            if not can_retreat_pokemon(st.active.card_id, st.active.energies):
                if CRISPIN in st.hand and not st.supporter_played:
                    st.play_trainer(CRISPIN, "PLAY Crispin (retreat setup)")
                    st.crispin_search(attach_target=st.active)
                elif HILDA in st.hand and not st.supporter_played:
                    st.play_trainer(HILDA, "PLAY Hilda (retreat energy)")
                    st.hilda_search(need_evolution=False, need_energy=True)
                    for e in ENERGY_IDS:
                        if e in st.hand:
                            st.attach_energy_from_hand(st.active, e)
                            break
    if st.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
        st.retreat_promote_bench(idx)


def _try_resolve_water(st: OpeningGameState, gaps: GapFlags) -> bool:
    """G2 fix: attach / Crispin / Hilda-energy / Pad before evolve or mega fetch."""
    if not gaps.g2 or st.energy_attached:
        return False
    tgt = _best_attach_target(st)
    if tgt and any(e in st.hand for e in (WATER_BASIC, PRISM)):
        st.attach_water_to(tgt)
        return True
    if CRISPIN in st.hand and not st.supporter_played and tgt is not None:
        st.play_trainer(CRISPIN, "PLAY Crispin (water gap)")
        st.crispin_search(attach_target=tgt)
        return True
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (energy only)")
        st.hilda_search(need_evolution=False, need_energy=True)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return True
    if POKE_PAD in st.hand and _deck_has_water(st):
        _pad_search_priority(st, gaps)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return True
    return False


def _water_fixable_this_turn(st: OpeningGameState) -> bool:
    if any(e in st.hand for e in (WATER_BASIC, PRISM)):
        return True
    if CRISPIN in st.hand and not st.supporter_played:
        return True
    if HILDA in st.hand and not st.supporter_played:
        return True
    if POKE_PAD in st.hand and _deck_has_water(st):
        return True
    return False


def _try_fetch_mega(st: OpeningGameState, gaps: GapFlags) -> bool:
    """G3 fix when 1030 already on field."""
    if not gaps.g3 or not st.staryu_on_field():
        return False
    if gaps.g2 and not _water_fixable_this_turn(st):
        return False
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (mega+energy)")
        st.hilda_search(need_evolution=True, need_energy=gaps.g2)
        return True
    if ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
        excl = frozenset({HILDA}) if HILDA in st.hand and not st.supporter_played else frozenset()
        disc = _pick_ultra_ball_discards(st, exclude=excl)
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (mega)")
            st.ultra_ball_search(MEGA_STARMIE, disc)
            return True
    if _meowth_on_bench(st):
        fetched = st.meowth_last_ditch_catch()
        if fetched == HILDA and HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda via Meowth")
            st.hilda_search(need_evolution=True, need_energy=gaps.g2)
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
    if CRISPIN in st.hand and not st.supporter_played:
        return True
    if HILDA in st.hand and not st.supporter_played:
        return True
    if POKE_PAD in st.hand and _deck_has_water(st):
        return True
    return False


def _try_complete_goal(st: OpeningGameState) -> bool:
    if st.opening_complete():
        return True
    if _try_salvatore_evolve(st):
        _promote_mega_to_active(st)
        return st.opening_complete()
    gaps = diagnose_gaps(st)
    # S1: Active Staryu evolve in place
    if st.setup_active_id == STARYU and st.active and st.active.card_id == STARYU:
        if not gaps.g3 and MEGA_STARMIE in st.hand and _staryu_ready_to_evolve(st):
            if _evolve_best_staryu(st):
                return st.opening_complete()
    # B1/C1/A1: prepare retreat then bench evolve
    if st.setup_active_id != STARYU and st.staryu_on_field():
        _prepare_bench_evolve_line(st)
    gaps = diagnose_gaps(st)
    if not gaps.g3 and st.all_staryu() and MEGA_STARMIE in st.hand and _staryu_ready_to_evolve(st):
        if _evolve_best_staryu(st):
            _promote_mega_to_active(st)
            return st.opening_complete()
    if gaps.g5 or (
        st.active
        and st.active.card_id != MEGA_STARMIE
        and any(p.card_id == MEGA_STARMIE for p in st.bench)
    ):
        _promote_mega_to_active(st)
        return st.opening_complete()
    return False


def _finish_goal_sequence(st: OpeningGameState) -> None:
    """Water → mega fetch → evolve → promote until opening_complete."""
    for _ in range(12):
        if st.opening_complete():
            return
        gaps = diagnose_gaps(st)
        if _try_resolve_water(st, gaps):
            continue
        gaps = diagnose_gaps(st)
        if gaps.g3 and st.staryu_on_field():
            if _try_fetch_mega(st, gaps):
                continue
        if _try_complete_goal(st):
            return
        gaps = diagnose_gaps(st)
        tgt = _best_attach_target(st)
        if tgt and gaps.g2 and not st.energy_attached:
            st.attach_water_to(tgt)
            continue
        gaps = diagnose_gaps(st)
        if gaps.g3 and st.staryu_on_field() and not gaps.g2:
            if HILDA in st.hand and not st.supporter_played:
                st.play_trainer(HILDA, "PLAY Hilda (finish F-B)")
                st.hilda_search(need_evolution=True, need_energy=False)
                continue
            if ULTRA_BALL in st.hand and MEGA_STARMIE in st.deck:
                disc = _pick_ultra_ball_discards(st)
                if len(disc) >= 2:
                    st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (finish F-B)")
                    st.ultra_ball_search(MEGA_STARMIE, disc)
                    continue
        break


def _deck_has_water(st: OpeningGameState) -> bool:
    from opening_cards import PRISM
    return WATER_BASIC in st.deck or PRISM in st.deck


def _pad_search_priority(st: OpeningGameState, gaps: GapFlags) -> None:
    if POKE_PAD not in st.hand:
        return
    st.play_trainer(POKE_PAD, "PLAY Poké Pad REC")
    if gaps.g1 and STARYU in st.deck:
        st.poke_pad_search(STARYU)
    elif gaps.g2 and _deck_has_water(st):
        for e in (WATER_BASIC, 16):
            if e in st.deck:
                st.poke_pad_search(e)
                return
    elif gaps.g1 and STARYU in st.deck:
        st.poke_pad_search(STARYU)
    elif _deck_has_water(st):
        st.poke_pad_search(WATER_BASIC)


def _salvatore_ready(st: OpeningGameState) -> bool:
    return (
        st.my_turn_number == 1
        and not st.supporter_played
        and SALVATOR in st.hand
        and MEGA_STARMIE in st.hand
        and st.staryu_on_field()
        and any(st._can_evolve_now(p) for _, _, p in st.all_staryu())
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
                if CRISPIN in st.hand and not st.supporter_played:
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
            if (gaps.g2 or gaps.g3) and HILDA in st.hand and not st.supporter_played:
                return "R7-T1"
            if gaps.g2 and CRISPIN in st.hand and not st.supporter_played:
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
        if st.staryu_on_field() and gaps.g3 and HILDA in st.hand and not st.supporter_played:
            return "R6-T1"
        if gaps.g1 and ULTRA_BALL in st.hand and STARYU in st.deck:
            return "R3b-T1"
        if gaps.g1 and POKE_PAD in st.hand and STARYU in st.deck:
            return "R3-T1"
        if gaps.g1 and POFFIN in st.hand:
            return "R2-T1"
        if gaps.g3 and HILDA in st.hand and not st.supporter_played:
            return "R6-T1"
        if gaps.g2 and not st.energy_attached:
            if HILDA in st.hand and not st.supporter_played and not gaps.g1:
                return "R7-T1"
            if CRISPIN in st.hand and not st.supporter_played:
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
            if HILDA in st.hand and not st.supporter_played:
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
        if HILDA in st.hand and not st.supporter_played:
            return "R3b-REC"
        if ULTRA_BALL in st.hand:
            return "R3-REC"
        if POFFIN in st.hand:
            return "R2-REC"
        if POKE_PAD in st.hand and STARYU in st.deck:
            return "R5-REC"
        return "R5-REC"
    if miss == "F-C":
        if not st.energy_attached:
            if POKE_PAD in st.hand and _deck_has_water(st):
                return "R5-REC"
            if HILDA in st.hand and not st.supporter_played:
                return "R4b-REC"
            if CRISPIN in st.hand and not st.supporter_played:
                return "R4c-REC"
            return "R4-REC"
        return "R1-REC"
    if miss == "F-D":
        if HILDA in st.hand and not st.supporter_played:
            return "R3b-REC"
        if POKE_PAD in st.hand:
            return "R5-REC"
        if ULTRA_BALL in st.hand:
            return "R3-REC"
        if CRISPIN in st.hand and not st.supporter_played:
            return "R4c-REC"
        return "R5-REC"

    # F-E
    if HILDA in st.hand and not st.supporter_played:
        return "R5-REC"
    if POFFIN in st.hand and gaps.g1:
        return "R2-REC"
    if POKE_PAD in st.hand:
        return "R5-REC"
    if ULTRA_BALL in st.hand and gaps.g1:
        return "R3-REC"
    if not can_reach_goal(st) and BUDEW in st.hand:
        return "R8-REC"
    if CRISPIN in st.hand and not st.supporter_played and gaps.g2:
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
        if HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda (Meowth line)")
            st.hilda_search(need_evolution=True, need_energy=True)
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
        st.fan_call()
        _play_staryu_from_hand(st)
        if not st.staryu_on_field() and POFFIN in st.hand and STARYU in st.deck:
            st.play_trainer(POFFIN, "PLAY Poffin (Fan line)")
            st.poffin_to_bench()
            _maybe_fan_call_after_poffin(st)
        elif not st.staryu_on_field() and POKE_PAD in st.hand and STARYU in st.deck:
            st.play_trainer(POKE_PAD, "PLAY Pad (Fan line)")
            st.poke_pad_search(STARYU)
        elif not st.staryu_on_field() and ULTRA_BALL in st.hand and STARYU in st.deck:
            excl = frozenset({HILDA}) if HILDA in st.hand and not st.supporter_played else frozenset()
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
            excl = frozenset({HILDA}) if HILDA in st.hand and not st.supporter_played else frozenset()
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
        excl = frozenset({HILDA}) if HILDA in st.hand and not st.supporter_played else frozenset()
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


def _greedy_opening_turn(st: OpeningGameState) -> None:
    """Phase-ordered turn planner: water → CP1 staryu → mega → evolve → promote."""
    for _ in range(20):
        if st.opening_complete():
            return
        gaps = diagnose_gaps(st)
        acted = False

        if _try_complete_goal(st):
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

        gaps = diagnose_gaps(st)
        if st.staryu_on_field() and gaps.g3:
            if _try_fetch_mega(st, gaps):
                acted = True
                continue

        gaps = diagnose_gaps(st)
        if gaps.g1:
            if _try_fetch_staryu(st, gaps):
                acted = True
                continue

        if not acted:
            break

    if st.my_turn_number == 1:
        _ensure_cp1_staryu(st)
        _ensure_cp1_resources(st)
    if not st.opening_complete():
        _finish_goal_sequence(st)


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
    if st.my_turn_number == 1:
        _ensure_cp1_staryu(st)
        _ensure_cp1_resources(st)
    if not st.opening_complete():
        _finish_goal_sequence(st)


def _prepare_bench_evolve_line(st: OpeningGameState) -> bool:
    """B1/C1/A1: attach retreat cost to placeholder Active before bench EVOLVE."""
    if st.setup_active_id == STARYU or st.active is None:
        return False
    if SWITCH in st.hand:
        return False
    if can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False
    if st.energy_attached:
        return False
    for e in ENERGY_IDS:
        if e in st.hand:
            st.attach_energy_from_hand(st.active, e)
            return True
    if CRISPIN in st.hand and not st.supporter_played:
        st.play_trainer(CRISPIN, "PLAY Crispin (bench-line retreat)")
        st.crispin_search(attach_target=st.active)
        return True
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (bench-line energy)")
        st.hilda_search(need_evolution=False, need_energy=True)
        for e in ENERGY_IDS:
            if e in st.hand:
                st.attach_energy_from_hand(st.active, e)
                return True
    return False


def _score_opening_state(st: OpeningGameState) -> int:
    if st.opening_complete():
        return 100_000
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
            return 100_000
    if st.my_turn_number == 1 and not st.staryu_on_field():
        score -= 3000
    if gaps.g2:
        score -= 250
    if gaps.g3:
        score -= 200
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
