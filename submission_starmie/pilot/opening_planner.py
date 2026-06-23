"""Gap diagnosis and turn action planning for OPENING (unlimited turns)."""
from __future__ import annotations

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
    """B1/F1+: Meowth → Hilda chain, then Poffin/Fan Call (E-B1-1, E-MEOW-1)."""
    st.play_meowth_to_bench_with_catch()
    if POFFIN in st.hand:
        st.play_trainer(POFFIN, "PLAY Poffin")
        st.poffin_to_bench()
        _maybe_fan_call_after_poffin(st)
    if HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda after Meowth")
        st.hilda_search(need_evolution=True, need_energy=True)
    _play_staryu_from_hand(st)
    tgt = _best_attach_target(st)
    if tgt and not st.energy_attached:
        st.attach_water_to(tgt)
    _finish_goal_sequence(st)


def _fan_call_ready(st: OpeningGameState) -> bool:
    if st.my_turn_number != 1 or st.fan_call_used:
        return False
    on_field = (st.active and st.active.card_id == FAN_ROTOM) or any(
        p.card_id == FAN_ROTOM for p in st.bench
    )
    if on_field:
        return True
    return FAN_ROTOM in st.hand and not fan_rotom_dead(st)


def _pick_ultra_ball_discards(st: OpeningGameState) -> list[int]:
    disc: list[int] = []
    for cid in st.hand:
        if cid == LILLIE:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if fan_rotom_dead(st) and cid == FAN_ROTOM:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid == 1260 and cid not in disc:  # Risky Ruins
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid == POKE_PAD and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in st.hand:
        if cid == POFFIN and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            return disc[:2]
    for cid in list(st.hand):
        if cid != ULTRA_BALL and cid not in disc:
            disc.append(cid)
        if len(disc) >= 2:
            break
    return disc[:2]


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
        return
    if st.active and not can_retreat_pokemon(st.active.card_id, st.active.energies):
        if not st.energy_attached:
            for e in ENERGY_IDS:
                if e in st.hand:
                    st.attach_energy_from_hand(st.active, e)
                    break
    if st.active and can_retreat_pokemon(st.active.card_id, st.active.energies):
        st.retreat_promote_bench(idx)


def _finish_goal_sequence(st: OpeningGameState) -> None:
    """Evolve → Switch → attach until opening_complete or no progress."""
    for _ in range(6):
        if st.opening_complete():
            return
        gaps = diagnose_gaps(st)
        if gaps.g3 and st.all_staryu():
            if not _try_salvatore_evolve(st):
                _evolve_best_staryu(st)
        if st.opening_complete():
            return
        gaps = diagnose_gaps(st)
        if gaps.g5 or (
            st.active and st.active.card_id != MEGA_STARMIE
            and any(p.card_id == MEGA_STARMIE for p in st.bench)
        ):
            if (
                st.active
                and not can_retreat_pokemon(st.active.card_id, st.active.energies)
                and not st.energy_attached
            ):
                for e in ENERGY_IDS:
                    if e in st.hand:
                        st.attach_energy_from_hand(st.active, e)
                        break
            _promote_mega_to_active(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        if st.opening_complete():
            return
        if not gaps.g3 and st.all_staryu() and MEGA_STARMIE in st.hand:
            if _evolve_best_staryu(st):
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
        if gaps.g1 and _meowth_can_fetch_hilda(st):
            return "R-Meowth-T1"
        if gaps.g1 and POFFIN in st.hand:
            return "R2-T1"
        if gaps.g1 and ULTRA_BALL in st.hand:
            return "R3b-T1"
        if st.staryu_on_field() and gaps.g3 and HILDA in st.hand and not st.supporter_played:
            return "R6-T1"
        if gaps.g2 and not st.energy_attached:
            if HILDA in st.hand and not st.supporter_played and not gaps.g1:
                return "R7-T1"
            if CRISPIN in st.hand and not st.supporter_played:
                return "R7c-T1"
            if any(e in st.hand for e in (WATER_BASIC, 16)):
                return "R5-T1"
        if _fan_call_ready(st):
            return "R4-T1"
        if gaps.g1 and POKE_PAD in st.hand:
            return "R3-T1"
        if gaps.g3 and HILDA in st.hand and not st.supporter_played:
            return "R6-T1"
        if gaps.g2 and not st.energy_attached:
            return "R5-T1"
        return "R-IDLE-T1"

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


def plan_and_execute_turn(st: OpeningGameState) -> str:
    gaps = diagnose_gaps(st)
    route = pick_route(st, gaps)
    st._log("NOTE", f"Route={route} T{st.my_turn_number} gaps=G1:{gaps.g1} G2:{gaps.g2} "
             f"G3:{gaps.g3} G4:{gaps.g4} miss={classify_miss(st)}")

    if route == "R8-T1" and _salvatore_ready(st):
        st.play_trainer(SALVATOR, "PLAY Salvatore")
        for _, _, p in st.all_staryu():
            if st._can_evolve_now(p):
                st.evolve_staryu(p, MEGA_STARMIE)
                break
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        _promote_mega_to_active(st)
        return route

    if route == "R-Meowth-T1" and _meowth_can_fetch_hilda(st):
        _execute_meowth_opening_turn(st, gaps)
        return route

    if route == "R7-T1" and HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (energy)")
        st.hilda_search(need_evolution=gaps.g3, need_energy=True)
        _play_staryu_from_hand(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        _finish_goal_sequence(st)
        return route

    if route == "R7c-T1" and CRISPIN in st.hand and not st.supporter_played:
        st.play_trainer(CRISPIN, "PLAY Crispin")
        tgt = _best_attach_target(st)
        st.crispin_search(attach_target=tgt)
        _play_staryu_from_hand(st)
        if tgt and not tgt.has_water() and WATER_BASIC in st.hand:
            st.attach_water_to(tgt)
        return route

    if route == "R4-T1" and _fan_call_ready(st):
        if FAN_ROTOM in st.hand and st.bench_open() > 0:
            if not any(p.card_id == FAN_ROTOM for p in st.bench) and (
                not st.active or st.active.card_id != FAN_ROTOM
            ):
                st.play_pokemon_to_bench(FAN_ROTOM)
        st.fan_call()
        _play_staryu_from_hand(st)
        if gaps.g2 and HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda after Fan Call")
            st.hilda_search(need_evolution=False, need_energy=True)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return route

    if route == "R2-T1" and POFFIN in st.hand:
        st.play_trainer(POFFIN, "PLAY Poffin")
        st.poffin_to_bench()
        _maybe_fan_call_after_poffin(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return route

    if route == "R3-T1" and POKE_PAD in st.hand:
        st.play_trainer(POKE_PAD, "PLAY Poké Pad")
        st.poke_pad_search(STARYU)
        _play_staryu_from_hand(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return route

    if route == "R5-T1" or route == "R4-REC":
        if route == "R4-REC" and POKE_PAD in st.hand and diagnose_gaps(st).g2:
            _pad_search_priority(st, diagnose_gaps(st))
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        _finish_goal_sequence(st)
        return route

    if route == "R6-T1" and HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda (1031)")
        st.hilda_search(need_evolution=True, need_energy=gaps.g2)
        return route

    # Recovery routes T2+
    if route == "R1-REC":
        _finish_goal_sequence(st)
        return route

    if route == "R2-REC":
        _finish_goal_sequence(st)
        return route

    if route == "R3b-T1" and ULTRA_BALL in st.hand:
        disc = _pick_ultra_ball_discards(st)
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball (1030)")
            st.ultra_ball_search(STARYU, disc)
        _play_staryu_from_hand(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        return route

    if route == "R3-REC" and ULTRA_BALL in st.hand:
        disc = _pick_ultra_ball_discards(st)
        target = STARYU if gaps.g1 else MEGA_STARMIE
        if len(disc) >= 2:
            st.play_trainer(ULTRA_BALL, f"PLAY Ultra Ball ({name(target)})")
            st.ultra_ball_search(target, disc)
        _play_staryu_from_hand(st)
        _finish_goal_sequence(st)
        return route

    if route == "R3b-REC" and HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda REC")
        st.hilda_search(need_evolution=gaps.g3, need_energy=gaps.g2)
        if gaps.g1 and STARYU in st.hand:
            _play_staryu_from_hand(st)
        _finish_goal_sequence(st)
        return route

    if route == "R4b-REC" and HILDA in st.hand and not st.supporter_played:
        st.play_trainer(HILDA, "PLAY Hilda energy REC")
        st.hilda_search(need_evolution=False, need_energy=True)
        _finish_goal_sequence(st)
        return route

    if route == "R4c-REC" and CRISPIN in st.hand and not st.supporter_played:
        st.play_trainer(CRISPIN, "PLAY Crispin REC")
        tgt = _best_attach_target(st)
        st.crispin_search(attach_target=tgt)
        _finish_goal_sequence(st)
        return route

    if route == "R5-REC":
        gaps_now = diagnose_gaps(st)
        miss = classify_miss(st)
        if miss == "F-B":
            if _execute_f_b_recovery(st):
                return route
            _finish_goal_sequence(st)
            return route
        if POKE_PAD in st.hand:
            _pad_search_priority(st, gaps_now)
            gaps_now = diagnose_gaps(st)
        elif POFFIN in st.hand and gaps_now.g1:
            st.play_trainer(POFFIN, "PLAY Poffin REC")
            st.poffin_to_bench()
        elif HILDA in st.hand and not st.supporter_played:
            st.play_trainer(HILDA, "PLAY Hilda REC search")
            st.hilda_search(need_evolution=gaps_now.g3, need_energy=gaps_now.g2)
        _play_staryu_from_hand(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        _finish_goal_sequence(st)
        return route

    if route == "R8-REC" and BUDEW in st.hand:
        if st.active is None or st.active.card_id != BUDEW:
            if BUDEW in st.hand and st.bench_open() > 0:
                st.play_pokemon_to_bench(BUDEW)
            elif BUDEW in st.hand:
                st._log("NOTE", "Budew stall — Itchy Pollen")
        return route

    if route.startswith("R-IDLE"):
        gaps_idle = diagnose_gaps(st)
        if gaps_idle.g1 and POFFIN in st.hand:
            st.play_trainer(POFFIN, "PLAY Poffin IDLE")
            st.poffin_to_bench()
            _maybe_fan_call_after_poffin(st)
            _play_staryu_from_hand(st)
        elif gaps_idle.g1 and POKE_PAD in st.hand:
            st.play_trainer(POKE_PAD, "PLAY Poké Pad IDLE")
            st.poke_pad_search(STARYU)
            _play_staryu_from_hand(st)
        elif gaps_idle.g1 and ULTRA_BALL in st.hand:
            disc = _pick_ultra_ball_discards(st)
            if len(disc) >= 2:
                st.play_trainer(ULTRA_BALL, "PLAY Ultra Ball IDLE")
                st.ultra_ball_search(STARYU, disc)
            _play_staryu_from_hand(st)
        tgt = _best_attach_target(st)
        if tgt and not st.energy_attached:
            st.attach_water_to(tgt)
        _finish_goal_sequence(st)

    return route


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
