"""Pure, per-decision planning for the Starmie/Froslass pilot.

The planner intentionally owns no cursor or cross-turn state.  Every action
changes the observation and the next call derives a fresh plan.  Epoch memory
remains responsible only for long-lived opening/SF progress.

GapParallel-V1: post-Mega midgame keeps a *parallel open-gap set*
(`midgame_open_gaps`).  Execution picks the highest-priority gap that is
*actionable this decision* (options can advance it) — unreachable primaries
fall through to the next gap.  Not a LIFO task stack.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from opening_cards import (
    BOSS_ORDERS,
    BUDEW,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FROSLASS,
    FAN_ROTOM,
    HILDA,
    JUDGE,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    RISKY_RUINS,
    SNORUNT,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    UNFAIR_STAMP,
    WATER_BASIC,
    LILLIE,
    SALVATOR,
    can_retreat_pokemon,
    ENERGY_IDS,
    hilda_evolution_priority,
    mega_ready_to_land,
    retreat_cost_for,
    two_turn_mega_path_ok,
)
from opponent_roles import (
    ARCHALUDON_LINE_IDS,
    CRUSTLE_LINE_IDS,
    DRAGAPULT_LINE_IDS,
    LUCARIO_LINE_IDS,
    MEGA_KANGA_LINE_IDS,
    TREVENANT_LINE_IDS,
    is_attack_damage_protected,
    is_ex_attack_immune,
    opponent_role,
)

# Budew Itchy Pollen — sole basic-attack exception while stalling.
_ATK_ITCHY_POLLEN = 323

Objective = Literal["MAKE_ATTACKER", "ATTACK", "BUILD_DP", "SECOND_ATTACKER", "DRAW"]
CombatMode = Literal["MEGA_MUST_ATTACK", "DOUBLE_KO", "FROSLASS_ATTACK", "NONE"]

_WATER_IDS = frozenset({WATER_BASIC, 16})
_DARK_IDS = frozenset({DARK_BASIC, 16})
_BASE_ATTACKERS = frozenset({STARYU, SNORUNT})
_BASIC_ATTACK_BAN = frozenset({
    STARYU, SNORUNT, FROSLASS, MUNKIDORI, DUNSPARCE_A, DUNSPARCE_B,
    DUDUNSPARCE, BUDEW, FAN_ROTOM, MEOWTH_EX,
})


def _si(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _cards(zone: Any) -> tuple[int, ...]:
    return tuple(_si(getattr(card, "id", None)) for card in (zone or []) if card)


def _energy_ids(pokemon: Any) -> frozenset[int]:
    return frozenset(_si(e) for e in (getattr(pokemon, "energies", None) or []))


def _has_energy(pokemon: Any, allowed: frozenset[int]) -> bool:
    return bool(_energy_ids(pokemon) & allowed)


# Known Mega ex printings — engine sometimes omits megaEx/prizeValue.
_MEGA_PRIZE_IDS = frozenset({MEGA_STARMIE, MEGA_FROSLASS, 678})  # 678 Mega Lucario
_JETTING_ACTIVE = 120
_JETTING_BENCH = 50
_ADRENA_MAX = 30  # Munkidori moves up to 3 damage counters


def _prize_value(pokemon: Any) -> int:
    explicit = _si(getattr(pokemon, "prizeValue", None))
    if explicit > 0:
        return explicit
    cid = _si(getattr(pokemon, "id", None))
    if cid in _MEGA_PRIZE_IDS or bool(getattr(pokemon, "megaEx", False)):
        return 3
    return 2 if bool(getattr(pokemon, "ex", False)) else 1


@dataclass(frozen=True)
class OppTarget:
    area: str
    index: int
    card_id: int
    hp: int
    prizes: int
    threat: int = 0
    role: str = "UNKNOWN"
    line: str = ""
    boss_priority: int = 0
    rider_priority: int = 0
    attack_protected: bool = False
    known_role: bool = False


@dataclass(frozen=True)
class TurnFacts:
    turn: int
    my_turn_number: int
    active_id: int
    active_hp: int
    active_max_hp: int
    active_has_water: bool
    active_ready_mega: bool
    bench_ready_mega_id: int
    can_dispatch_bench_mega: bool
    mega_starmie_on_field: bool
    mega_froslass_on_field: bool
    staryu_on_field: bool
    line_has_water: bool
    staryu_can_evolve: bool
    snorunt_on_field: bool
    snorunt_can_evolve: bool
    froslass_104_on_field: bool
    risky_ruins_online: bool
    damage_placer_online: bool
    munkidori_on_field: bool
    munkidori_has_dark: bool
    transferable_damage: int
    hand_ids: tuple[int, ...]
    discard_ids: tuple[int, ...]
    bench_ids: tuple[int, ...]
    bench_open: int
    bench_budget: int
    energy_attached: bool
    supporter_played: bool
    prize_self: int
    prize_opp: int
    opp_hand_count: int
    opp_active: OppTarget | None
    opp_bench: tuple[OppTarget, ...]
    # Matchup / public-board gates (expert F3 / MidOps).
    opp_archaludon_threat: bool = False
    opp_dragapult_threat: bool = False
    opp_trevenant_threat: bool = False
    opp_lucario_threat: bool = False
    opp_crustle_wall: bool = False
    ex_immune_active: bool = False
    opp_munk_dp_online: bool = False
    ban_froslass_line: bool = False
    two_turn_mega_path: bool = False
    starmie_line_count: int = 0
    starmie_attacker_ready: bool = False
    opp_attacker_prizes: int = 0


@dataclass(frozen=True)
class TurnGap:
    need_base: bool
    need_evolution: bool
    need_energy: bool
    dp_gaps: tuple[str, ...]
    need_second_attacker: bool
    need_second_starmie: bool = False


@dataclass(frozen=True)
class AcquirePlan:
    targets: tuple[int, ...]
    sources: tuple[int, ...]
    ball_allowed: bool
    ball_reason: str
    discard_values: tuple[tuple[int, int], ...]
    recover_target: int | None

    def value(self, card_id: int) -> int:
        return dict(self.discard_values).get(card_id, 100)


@dataclass(frozen=True)
class CombatPlan:
    mode: CombatMode
    attack_required: bool
    required_before_attack: tuple[str, ...]
    next_action: str
    rider_target: OppTarget | None = None
    boss_target: OppTarget | None = None
    expected_prizes: int = 0
    expected_prize_delta: int = 0
    froslass_build_allowed: bool = False
    adrena_target: OppTarget | None = None


@dataclass(frozen=True)
class DrawPlan:
    allow_run_away_draw: bool
    allow_first_dunsparce: bool
    allow_second_dunsparce: bool  # always False under field preset 土龙×1
    reason: str


# Post-Mega parallel gaps (priority order). Execution filters by actionability.
MIDGAME_GAP_ORDER: tuple[str, ...] = (
    "ATTACH_DARK",
    "DIG_DARK",
    "DIG_MUNK",
    "PLAY_MUNK",
    "PLAY_PLACER",
    "PLAY_SNORUNT",
    "EVOLVE_861",
    "PLAY_STARYU",
    "EVOLVE_SECOND_STARMIE",
    "DRAW_66",
)


@dataclass(frozen=True)
class TurnPlan:
    facts: TurnFacts
    gap: TurnGap
    objective: Objective
    two_turn_path: tuple[str, ...]
    acquire: AcquirePlan
    combat: CombatPlan
    draw: DrawPlan
    forbidden_actions: tuple[str, ...]
    reasons: tuple[str, ...]
    midgame_open_gaps: tuple[str, ...] = ()


def enumerate_midgame_open_gaps(facts: TurnFacts, gap: TurnGap) -> tuple[str, ...]:
    """Board-true post-Mega gaps that may be pursued in parallel.

    Does not check engine options — the pilot filters to actionable gaps.
    """
    if not facts.mega_starmie_on_field:
        return ()
    open_set: set[str] = set()
    hand = set(facts.hand_ids)

    if facts.munkidori_on_field and not facts.munkidori_has_dark:
        if DARK_BASIC in hand and not facts.energy_attached:
            open_set.add("ATTACH_DARK")
        if DARK_BASIC not in hand:
            open_set.add("DIG_DARK")
    elif not facts.munkidori_on_field:
        if MUNKIDORI in hand:
            open_set.add("PLAY_MUNK")
        else:
            # SeatMunk: no held Munk → dig (Pad / Ball / NS) before Jetting starve.
            open_set.add("DIG_MUNK")
    else:
        # Autopsy 93325448: single-Munk DP gate is the *minimum*, not a cap.
        # Once DP min is online (dark or placer), or hand-rich / vs Crustle,
        # seat a second Munk when bench allows.
        munk_n = sum(1 for cid in facts.bench_ids if cid == MUNKIDORI)
        if facts.active_id == MUNKIDORI:
            munk_n += 1
        dp_min_done = bool(facts.munkidori_has_dark or facts.damage_placer_online)
        if (
            munk_n == 1
            and MUNKIDORI in hand
            and facts.bench_open > 0
            and (
                dp_min_done
                or len(facts.hand_ids) >= 6
                or facts.opp_crustle_wall
            )
        ):
            open_set.add("PLAY_MUNK")

    if not facts.damage_placer_online:
        open_set.add("PLAY_PLACER")

    if gap.need_second_attacker and not facts.ban_froslass_line:
        if not facts.snorunt_on_field and not facts.mega_froslass_on_field:
            open_set.add("PLAY_SNORUNT")
        if (
            facts.snorunt_on_field
            and MEGA_FROSLASS in hand
            and not facts.mega_froslass_on_field
        ):
            open_set.add("EVOLVE_861")

    if gap.need_second_starmie:
        n_staryu = sum(1 for cid in facts.bench_ids if cid == STARYU) + (
            1 if facts.active_id == STARYU else 0
        )
        n_mega = sum(1 for cid in facts.bench_ids if cid == MEGA_STARMIE) + (
            1 if facts.active_id == MEGA_STARMIE else 0
        )
        if n_staryu + n_mega < 2:
            open_set.add("PLAY_STARYU")
        if n_staryu > 0 and MEGA_STARMIE in hand and n_mega < 2:
            open_set.add("EVOLVE_SECOND_STARMIE")

    field_ids = set(facts.bench_ids) | (
        {facts.active_id} if facts.active_id else set()
    )
    if DUDUNSPARCE in field_ids:
        open_set.add("DRAW_66")

    return tuple(g for g in MIDGAME_GAP_ORDER if g in open_set)


def build_turn_facts(
    obs: Any,
    board: Any,
    *,
    matchup: str | None = None,
) -> TurnFacts:
    mi = _si(getattr(obs.current, "yourIndex", None))
    me = obs.current.players[mi]
    opp = obs.current.players[1 - mi]
    active = (me.active or [None])[0]
    bench = tuple(p for p in (me.bench or []) if p)
    field = ((active,) if active else ()) + bench
    bench_ids = tuple(_si(getattr(p, "id", None)) for p in bench)
    turn = _si(getattr(obs.current, "turn", None))

    def can_evolve_now(pokemon: Any) -> bool:
        # Engine often sets appearThisTurn without canEvolve/turnPlayed
        # (autopsy 92356962: both Staryu sick → false "staryu_can_evolve").
        if bool(getattr(pokemon, "appearThisTurn", False)):
            return False
        explicit = getattr(pokemon, "canEvolve", None)
        if explicit is not None:
            return bool(explicit)
        played = getattr(pokemon, "turnPlayed", None)
        return played is None or _si(played, -1) < turn

    active_id = _si(getattr(active, "id", None)) if active else 0
    active_has_water = _has_energy(active, _WATER_IDS)
    active_ready = active_id in (MEGA_STARMIE, MEGA_FROSLASS) and active_has_water
    bench_ready = next(
        (
            _si(getattr(p, "id", None))
            for p in bench
            if _si(getattr(p, "id", None)) in (MEGA_STARMIE, MEGA_FROSLASS)
            and _has_energy(p, _WATER_IDS)
        ),
        0,
    )
    active_energies = _energy_ids(active)
    can_dispatch = bool(
        bench_ready
        and (
            can_retreat_pokemon(active_id, active_energies)
            or SWITCH in _cards(me.hand)
            or (
                not bool(getattr(me, "energyAttached", False))
                and any(cid in ENERGY_IDS for cid in _cards(me.hand))
                and len(active_energies) + 1 >= retreat_cost_for(active_id)
            )
        )
    )
    transferable = sum(
        max(0, _si(getattr(p, "maxHp", None)) - _si(getattr(p, "hp", None)))
        for p in field
    )

    opp_field_ids = frozenset(
        _si(getattr(p, "id", None))
        for p in (
            tuple(x for x in (opp.active or []) if x)
            + tuple(x for x in (opp.bench or []) if x)
        )
    )

    def target(pokemon: Any, area: str, index: int) -> OppTarget:
        cid = _si(getattr(pokemon, "id", None))
        profile = opponent_role(cid, matchup)
        engine_threat = _si(getattr(pokemon, "threat", None))
        protected = (
        is_ex_attack_immune(cid)
        or (
            area == "BENCH"
            and is_attack_damage_protected(pokemon, opp_field_ids)
        )
    )
        return OppTarget(
            area=area,
            index=index,
            card_id=cid,
            hp=_si(getattr(pokemon, "hp", None), 999),
            prizes=_prize_value(pokemon),
            threat=max(engine_threat, profile.rider_priority, profile.boss_priority),
            role=profile.role,
            line=profile.line,
            boss_priority=profile.boss_priority,
            rider_priority=profile.rider_priority,
            attack_protected=protected,
            known_role=profile.known,
        )

    opp_active_p = (opp.active or [None])[0]
    opp_active = target(opp_active_p, "ACTIVE", 0) if opp_active_p else None
    opp_bench = tuple(
        target(p, "BENCH", i) for i, p in enumerate(opp.bench or []) if p
    )
    hand_ids = _cards(me.hand)
    discard_ids = _cards(me.discard)
    stadium_ids = _cards(getattr(obs.current, "stadium", None))
    risky_ruins_online = RISKY_RUINS in stadium_ids

    opp_field = tuple(
        p
        for p in (
            tuple(x for x in (opp.active or []) if x)
            + tuple(x for x in (opp.bench or []) if x)
        )
    )
    opp_field_card_ids = frozenset(_si(getattr(p, "id", None)) for p in opp_field)
    opp_archaludon_threat = bool(opp_field_card_ids & ARCHALUDON_LINE_IDS)
    opp_dragapult_threat = bool(opp_field_card_ids & DRAGAPULT_LINE_IDS)
    opp_trevenant_threat = bool(opp_field_card_ids & TREVENANT_LINE_IDS)
    opp_lucario_threat = bool(opp_field_card_ids & LUCARIO_LINE_IDS)
    opp_crustle_wall = bool(
        opp_field_card_ids & CRUSTLE_LINE_IDS
        or opp_field_card_ids & MEGA_KANGA_LINE_IDS
    )
    ex_immune_active = bool(
        opp_active is not None and is_ex_attack_immune(opp_active.card_id)
    )
    opp_has_munk = MUNKIDORI in opp_field_card_ids
    opp_munk_has_dark = any(
        _si(getattr(p, "id", None)) == MUNKIDORI and _has_energy(p, _DARK_IDS)
        for p in opp_field
    )
    opp_has_placer = bool(
        opp_field_card_ids & {FROSLASS, MEGA_FROSLASS}
    ) or risky_ruins_online
    opp_munk_dp_online = opp_has_munk and (opp_munk_has_dark or opp_has_placer)
    # Control / steel-dragon / opp DP: stay on Mega Starmie. Lucario is NOT banned.
    ban_froslass_line = bool(
        matchup == "alakazam"
        or opp_archaludon_threat
        or opp_dragapult_threat
        or opp_trevenant_threat
        or opp_munk_dp_online
    )
    two_turn_mega = two_turn_mega_path_ok(
        staryu_on_field=STARYU in {
            _si(getattr(p, "id", None)) for p in field
        },
        mega_starmie_on_field=MEGA_STARMIE in {
            _si(getattr(p, "id", None)) for p in field
        },
        staryu_can_evolve=any(
            _si(getattr(p, "id", None)) == STARYU and can_evolve_now(p)
            for p in field
        ),
        line_has_water=any(
            _si(getattr(p, "id", None)) in (STARYU, MEGA_STARMIE)
            and _has_energy(p, _WATER_IDS)
            for p in field
        ),
        hand_ids=hand_ids,
        supporter_played=bool(getattr(me, "supporterPlayed", False)),
    )

    # Reserve spaces for roles that are not yet represented.  This is a budget,
    # not a demand to fill every role.
    reserve = 0
    field_ids = {_si(getattr(p, "id", None)) for p in field}
    if not ({STARYU, MEGA_STARMIE} & field_ids):
        reserve += 1
    if MUNKIDORI not in field_ids:
        reserve += 1
    if not ban_froslass_line and not ({SNORUNT, FROSLASS, MEGA_FROSLASS} & field_ids):
        reserve += 1
    if MEGA_STARMIE in field_ids and not ban_froslass_line and not (
        {SNORUNT, MEGA_FROSLASS} & field_ids
    ):
        reserve += 1
    bench_open = max(0, 5 - len(bench))

    return TurnFacts(
        turn=turn,
        my_turn_number=_si(getattr(board, "my_turn_number", None)),
        active_id=active_id,
        active_hp=_si(getattr(active, "hp", None)),
        active_max_hp=_si(getattr(active, "maxHp", None)),
        active_has_water=active_has_water,
        active_ready_mega=active_ready,
        bench_ready_mega_id=bench_ready,
        can_dispatch_bench_mega=can_dispatch,
        mega_starmie_on_field=MEGA_STARMIE in field_ids,
        mega_froslass_on_field=MEGA_FROSLASS in field_ids,
        staryu_on_field=STARYU in field_ids,
        line_has_water=any(
            _si(getattr(p, "id", None)) in (STARYU, MEGA_STARMIE)
            and _has_energy(p, _WATER_IDS)
            for p in field
        ),
        staryu_can_evolve=any(
            _si(getattr(p, "id", None)) == STARYU and can_evolve_now(p)
            for p in field
        ),
        snorunt_on_field=SNORUNT in field_ids,
        snorunt_can_evolve=any(
            _si(getattr(p, "id", None)) == SNORUNT and can_evolve_now(p)
            for p in field
        ),
        froslass_104_on_field=FROSLASS in field_ids,
        risky_ruins_online=risky_ruins_online,
        damage_placer_online=FROSLASS in field_ids or risky_ruins_online,
        munkidori_on_field=MUNKIDORI in field_ids,
        munkidori_has_dark=any(
            _si(getattr(p, "id", None)) == MUNKIDORI and _has_energy(p, _DARK_IDS)
            for p in field
        ),
        transferable_damage=transferable,
        hand_ids=hand_ids,
        discard_ids=discard_ids,
        bench_ids=bench_ids,
        bench_open=bench_open,
        bench_budget=max(0, bench_open - reserve),
        energy_attached=bool(getattr(me, "energyAttached", False)),
        supporter_played=bool(getattr(me, "supporterPlayed", False)),
        prize_self=len(me.prize or []) or _si(getattr(me, "prizeCount", None), 6),
        prize_opp=len(opp.prize or []) or _si(getattr(opp, "prizeCount", None), 6),
        opp_hand_count=_si(
            getattr(opp, "handCount", None),
            len(getattr(opp, "hand", None) or []),
        ),
        opp_active=opp_active,
        opp_bench=opp_bench,
        opp_archaludon_threat=opp_archaludon_threat,
        opp_dragapult_threat=opp_dragapult_threat,
        opp_trevenant_threat=opp_trevenant_threat,
        opp_lucario_threat=opp_lucario_threat,
        opp_crustle_wall=opp_crustle_wall,
        ex_immune_active=ex_immune_active,
        opp_munk_dp_online=opp_munk_dp_online,
        ban_froslass_line=ban_froslass_line,
        two_turn_mega_path=two_turn_mega,
        starmie_line_count=sum(
            1 for cid in field_ids if cid in (STARYU, MEGA_STARMIE)
        ),
        starmie_attacker_ready=bool(
            MEGA_STARMIE in field_ids
            and any(
                _si(getattr(p, "id", None)) in (STARYU, MEGA_STARMIE)
                and _has_energy(p, _WATER_IDS)
                for p in field
            )
        ),
        opp_attacker_prizes=_infer_opp_attacker_prizes(
            opp_active,
            opp_bench,
            lucario=opp_lucario_threat,
            dragapult=opp_dragapult_threat,
            archaludon=opp_archaludon_threat,
            trevenant=opp_trevenant_threat,
        ),
    )


def _turn_gap(facts: TurnFacts) -> TurnGap:
    main_line = facts.staryu_on_field or facts.mega_starmie_on_field
    need_base = not main_line
    need_evolution = facts.staryu_on_field and not facts.mega_starmie_on_field
    main_ready = facts.active_ready_mega or facts.bench_ready_mega_id == MEGA_STARMIE
    need_energy = (facts.staryu_on_field or facts.mega_starmie_on_field) and not main_ready
    dp: list[str] = []
    if not facts.munkidori_on_field:
        dp.append("MUNKIDORI")
    elif not facts.munkidori_has_dark:
        dp.append("DARK_ENERGY")
    if not facts.damage_placer_online:
        # Ban chasing 104/861 vs Archaludon / Alak / opp Munk-DP; prefer ruins.
        if facts.ban_froslass_line:
            if not facts.risky_ruins_online:
                dp.append("DAMAGE_PLACER")
        else:
            dp.append("DAMAGE_PLACER")
    return TurnGap(
        need_base=need_base,
        need_evolution=need_evolution,
        need_energy=need_energy,
        dp_gaps=tuple(dp),
        need_second_attacker=(
            facts.starmie_attacker_ready
            and not facts.mega_froslass_on_field
            and not facts.ban_froslass_line
            # 0 = unknown public prizes (Kaggle often omits prizeValue/megaEx).
            # SecondAtk product: insure 861 when we cannot classify 2 vs 3.
            and facts.opp_attacker_prizes in (0, 3)
        ),
        need_second_starmie=(
            facts.starmie_attacker_ready
            and facts.starmie_line_count < 2
            and (
                facts.ban_froslass_line
                or facts.opp_attacker_prizes == 2
            )
        ),
    )


# Item effects that can close a typed gap (Poffin/Pad/Hilda/Crispin/UB/NS).
_ITEM_COVERABLE = frozenset({
    "BASE", "EVOLUTION", "ENERGY", "MUNKIDORI", "DARK_ENERGY",
    "DAMAGE_PLACER", "SECOND_ATTACKER",
})


def missing_gap_types(facts: TurnFacts, gap: TurnGap) -> tuple[str, ...]:
    """Distinct missing resource types for draw-vs-item valuation.

    A draw-7 dig is modeled as covering ~2 distinct types. Types already held
    in hand (evolution / energy pieces) are not counted as missing.
    """
    hand = set(facts.hand_ids)
    types: list[str] = []
    if gap.need_base and STARYU not in hand:
        types.append("BASE")
    if gap.need_evolution and MEGA_STARMIE not in hand:
        types.append("EVOLUTION")
    if gap.need_energy and not hand.intersection(_WATER_IDS):
        types.append("ENERGY")
    for g in gap.dp_gaps:
        if g == "MUNKIDORI" and MUNKIDORI not in hand:
            types.append("MUNKIDORI")
        elif g == "DARK_ENERGY" and DARK_BASIC not in hand:
            types.append("DARK_ENERGY")
        elif g == "DAMAGE_PLACER":
            has_placer = (
                RISKY_RUINS in hand
                or FROSLASS in hand
                or facts.snorunt_on_field
                or SNORUNT in hand
            )
            if not has_placer:
                types.append("DAMAGE_PLACER")
    if gap.need_second_attacker and MEGA_FROSLASS not in hand and (
        not facts.snorunt_on_field and SNORUNT not in hand
    ):
        types.append("SECOND_ATTACKER")
    if gap.need_second_starmie and STARYU not in hand and MEGA_STARMIE not in hand:
        types.append("SECOND_ATTACKER")
    return tuple(dict.fromkeys(types))


def count_missing_types(facts: TurnFacts, gap: TurnGap) -> int:
    return len(missing_gap_types(facts, gap))


def item_uncoverable_gaps(facts: TurnFacts, gap: TurnGap) -> tuple[str, ...]:
    """Gaps that current hand items cannot close (draw-preferred)."""
    hand = set(facts.hand_ids)
    missing = missing_gap_types(facts, gap)
    uncoverable: list[str] = []
    for t in missing:
        if t == "BASE" and POFFIN not in hand and POKE_PAD not in hand and ULTRA_BALL not in hand:
            uncoverable.append(t)
        # Mega Starmie is Rule-Box — Pad cannot cover the main EVOLUTION gap.
        elif t == "EVOLUTION" and HILDA not in hand and ULTRA_BALL not in hand:
            uncoverable.append(t)
        elif t == "ENERGY" and CRISPIN not in hand and HILDA not in hand and NIGHT_STRETCHER not in hand:
            uncoverable.append(t)
        elif t == "MUNKIDORI" and POFFIN not in hand and ULTRA_BALL not in hand and POKE_PAD not in hand:
            uncoverable.append(t)
        elif t == "DARK_ENERGY" and CRISPIN not in hand and NIGHT_STRETCHER not in hand:
            uncoverable.append(t)
        elif t == "DAMAGE_PLACER" and (
            POFFIN not in hand and POKE_PAD not in hand and ULTRA_BALL not in hand and HILDA not in hand
        ):
            uncoverable.append(t)
        elif t == "SECOND_ATTACKER" and HILDA not in hand and ULTRA_BALL not in hand and POFFIN not in hand:
            uncoverable.append(t)
        elif t not in _ITEM_COVERABLE:
            uncoverable.append(t)
    return tuple(uncoverable)


def must_prioritize_draw(facts: TurnFacts, gap: TurnGap, combat: CombatPlan) -> bool:
    """n≥3 missing types → create and resolve a dig before misc setup.

    Mandatory attack turns (active ready Mega, or DISPATCH then attack) still
    yield — dig never blocks a required attack sequence.

    Before usable Mega Starmie is online, only count the attacker-line gaps
    (BASE / EVOLUTION / ENERGY). DP pieces must not flip objective to DRAW and
    starve Mega search / item plays during OPENING.
    """
    if combat.attack_required:
        return False
    mega_ready = bool(facts.active_ready_mega or facts.bench_ready_mega_id == MEGA_STARMIE)
    if not mega_ready:
        line_missing = tuple(
            t for t in missing_gap_types(facts, gap)
            if t in ("BASE", "EVOLUTION", "ENERGY")
        )
        return len(line_missing) >= 3
    return count_missing_types(facts, gap) >= 3


def _infer_opp_attacker_prizes(
    opp_active: OppTarget | None,
    opp_bench: tuple[OppTarget, ...],
    *,
    lucario: bool,
    dragapult: bool,
    archaludon: bool,
    trevenant: bool,
) -> int:
    """2 vs 3 prize main attacker, from public board. 0 = unknown."""
    if lucario:
        return 3
    if dragapult or archaludon or trevenant:
        return 2
    field = tuple(t for t in ((opp_active,) + opp_bench) if t)
    if any(t.prizes >= 3 or t.card_id in _MEGA_PRIZE_IDS for t in field):
        return 3
    if any(t.prizes == 2 for t in field):
        return 2
    return 0


def _froslass_damage(facts: TurnFacts) -> int:
    """Resentful Refrain: 50 × opponent hand. Core 861 burst, not Abs Snow 150."""
    return 50 * max(0, int(facts.opp_hand_count or 0))


def _expected_froslass_prizes(facts: TurnFacts) -> int:
    damage = _froslass_damage(facts)
    targets = tuple(t for t in ((facts.opp_active,) + facts.opp_bench) if t)
    return max((t.prizes for t in targets if 0 < t.hp <= damage), default=0)


def _froslass_ko_prizes(target: OppTarget | None, damage: int) -> int:
    if target is None or not (0 < target.hp <= damage):
        return 0
    return target.prizes


def _froslass_boss_key(target: OppTarget) -> tuple:
    # Prize first, then developed attacker, then full HP (满血二号打手).
    return (target.prizes, target.boss_priority, target.hp, -target.index)


def _effective_froslass_boss_candidate(
    facts: TurnFacts,
) -> tuple[OppTarget | None, int, int]:
    """Gust a Resentful-KO bench target only when it improves prizes this turn.

    Uses 861 damage (50×hand), not the Jetting 120 HP gate. Does not open
    Boss→Jetting. Equal-prize gusts are skipped — spend the supporter only
    when the grabbed attacker is worth more prizes than the current front.
    """
    damage = _froslass_damage(facts)
    front = _froslass_ko_prizes(facts.opp_active, damage)
    candidates = [t for t in facts.opp_bench if 0 < t.hp <= damage]
    if not candidates:
        return None, front, 0
    best = max(candidates, key=_froslass_boss_key)
    with_boss = best.prizes
    delta = with_boss - front
    if delta > 0:
        return best, with_boss, delta
    return None, front, 0


def _rider_key(target: OppTarget) -> tuple:
    # Knockability is pre-filtered; prefer cutting a main base, then prizes, then HP.
    return (target.rider_priority, target.prizes, -target.hp, -target.index)


def _boss_key(target: OppTarget, *, jetting_damage: int = 120) -> tuple:
    koable = 1 if 0 < target.hp <= jetting_damage else 0
    return (koable, target.prizes, target.boss_priority, -target.hp, -target.index)


def _adrena_extra(facts: TurnFacts) -> int:
    if not facts.munkidori_has_dark:
        return 0
    return min(_ADRENA_MAX, max(0, facts.transferable_damage))


def _pick_jetting_rider(facts: TurnFacts, *, extra_dp: int = 0) -> OppTarget | None:
    limit = _JETTING_BENCH + extra_dp
    riders = [
        t
        for t in facts.opp_bench
        if 0 < t.hp <= limit and not t.attack_protected
    ]
    if not riders:
        return None
    if extra_dp:
        combo = [t for t in riders if t.hp > _JETTING_BENCH]
        if combo:
            return max(combo, key=_rider_key)
    return max(riders, key=_rider_key)


def _pick_adrena_target(
    facts: TurnFacts,
    rider: OppTarget | None,
    *,
    extra_dp: int,
) -> OppTarget | None:
    """Park Adrena on a bench 50+DP KO unless DP is what KOs the active attacker."""
    if extra_dp <= 0:
        return None
    active = facts.opp_active
    jetting_ko_active = bool(active and 0 < active.hp <= _JETTING_ACTIVE)
    dp_enables_active_ko = bool(
        active
        and active.hp > _JETTING_ACTIVE
        and active.hp <= _JETTING_ACTIVE + extra_dp
    )
    if dp_enables_active_ko and not jetting_ko_active:
        return active
    if rider is not None:
        return rider
    return _pick_jetting_rider(facts, extra_dp=extra_dp)


def _double_ko(facts: TurnFacts) -> tuple[OppTarget | None, OppTarget | None]:
    if not facts.active_ready_mega or facts.active_id != MEGA_STARMIE:
        return None, None
    extra = _adrena_extra(facts)
    rider = _pick_jetting_rider(facts, extra_dp=extra)
    if not rider:
        return None, None
    active = facts.opp_active
    if active and 0 < active.hp <= _JETTING_ACTIVE:
        return rider, None
    bosses = [t for t in facts.opp_bench if t != rider and 0 < t.hp <= _JETTING_ACTIVE]
    boss = max(bosses, key=_boss_key, default=None)
    return rider, boss


def _front_prizes(target: OppTarget | None) -> int:
    if target is None or not (0 < target.hp <= 120):
        return 0
    return target.prizes


def _prize_line(
    *,
    front: OppTarget | None,
    rider: OppTarget | None,
) -> int:
    return _front_prizes(front) + (rider.prizes if rider else 0)


def _effective_boss_candidate(
    facts: TurnFacts,
    *,
    rider: OppTarget | None,
    candidate: OppTarget | None,
) -> tuple[OppTarget | None, int, int]:
    """Return (boss, expected_prizes_with_boss, prize_delta vs no-boss).

    Boss is effective only when grabbing it improves prize progress, or when a
    DoubleKO rider exists and the current Active cannot be KO'd for 120.
    """
    baseline = _prize_line(front=facts.opp_active, rider=rider)
    if candidate is None:
        return None, baseline, 0
    with_boss = _prize_line(front=candidate, rider=rider)
    delta = with_boss - baseline
    double_ko_needs_boss = bool(
        rider is not None
        and facts.opp_active is not None
        and facts.opp_active.hp > 120
    )
    if delta > 0 or double_ko_needs_boss:
        return candidate, with_boss, max(delta, 0 if not double_ko_needs_boss else delta)
    # Wave L: closing window — cut a higher-priority KO-able threat even when
    # prize count ties (still Jetting-legal). Does not open OPENING / pre-Mega.
    if (
        facts.prize_self <= 3
        and candidate is not None
        and facts.opp_active is not None
        and 0 < candidate.hp <= 120
        and 0 < facts.opp_active.hp <= 120
        and candidate.prizes == facts.opp_active.prizes
        and candidate.boss_priority > facts.opp_active.boss_priority
    ):
        return candidate, with_boss, 0
    return None, baseline, 0


def _dp_prep_steps(facts: TurnFacts) -> list[str]:
    """Small, bounded DP actions that never replace the mandatory attack."""
    required: list[str] = []
    if (
        not facts.ban_froslass_line
        and facts.snorunt_can_evolve
        and FROSLASS in facts.hand_ids
        and not facts.damage_placer_online
    ):
        required.append("EVOLVE_104")
    if (
        facts.munkidori_on_field
        and not facts.munkidori_has_dark
        and DARK_BASIC in facts.hand_ids
        and not facts.energy_attached
    ):
        required.append("ATTACH_DARK")
    if facts.transferable_damage > 0 and facts.munkidori_has_dark:
        required.append("ADRENA")
    return required


def _combat_plan(facts: TurnFacts) -> CombatPlan:
    expected_f = _expected_froslass_prizes(facts)
    starmie_can_attack = (
        (facts.active_ready_mega and facts.active_id == MEGA_STARMIE)
        or (
            facts.bench_ready_mega_id == MEGA_STARMIE
            and facts.can_dispatch_bench_mega
        )
    )
    froslass_can_attack = (
        (facts.active_ready_mega and facts.active_id == MEGA_FROSLASS)
        or (
            facts.bench_ready_mega_id == MEGA_FROSLASS
            and facts.can_dispatch_bench_mega
        )
    )
    # Expert C2: only lethal clear OR 861 is the sole attackable Mega.
    froslass_exception = (
        expected_f >= facts.prize_self
        or (froslass_can_attack and not starmie_can_attack)
    )
    # Assume Mega Starmie will die: after the attacker is fueled, immediately
    # build the second attacker. 3-prize / unknown → Froslass; 2-prize → 2nd Starmie.
    # Do not use Starmie HP. Lethal 861 already online still allowed.
    # Autopsy 55488542: opp_attacker_prizes==0 on 15/23 ready-Mega frames forbade
    # BUILD_861 → must_close Jetting while 861/Snorunt sat in hand.
    # Autopsy 93324506: 104 already online must NOT block 861 — upgrade 104→861.
    three_prize_build = (
        not facts.ban_froslass_line
        and not facts.opp_crustle_wall
        and not facts.ex_immune_active
        and facts.starmie_attacker_ready
        and facts.opp_attacker_prizes in (0, 3)
        and (
            not facts.damage_placer_online
            or (
                facts.froslass_104_on_field
                and MEGA_FROSLASS in facts.hand_ids
                and not facts.mega_froslass_on_field
            )
        )
    )
    continuity_finish = (
        not facts.ban_froslass_line
        and not facts.opp_crustle_wall
        and not facts.ex_immune_active
        and MEGA_FROSLASS in facts.hand_ids
        and not facts.mega_froslass_on_field
        and facts.munkidori_on_field
        and facts.munkidori_has_dark
        and (
            facts.snorunt_on_field
            or facts.froslass_104_on_field  # Autopsy 93324506: evolve 104→861
        )
        and (expected_f >= 2 or froslass_exception)
    )
    # Hand-rich 104→861 upgrade even before DP dark is done (second attacker).
    upgrade_104_to_861 = (
        not facts.ban_froslass_line
        and not facts.opp_crustle_wall
        and not facts.ex_immune_active
        and facts.froslass_104_on_field
        and MEGA_FROSLASS in facts.hand_ids
        and not facts.mega_froslass_on_field
        and (
            facts.starmie_attacker_ready
            or not facts.mega_starmie_on_field
            or len(facts.hand_ids) >= 6
        )
    )
    # Already attacking on 104/861: finish the Mega. Do not use a benched
    # 104 to open 861 while fueled Starmie is the Active attacker.
    already_on_froslass = facts.active_id in (FROSLASS, MEGA_FROSLASS)
    froslass_allowed = bool(
        froslass_can_attack
        or froslass_exception
        or three_prize_build
        or continuity_finish
        or upgrade_104_to_861
        or (already_on_froslass and expected_f >= 2)
    )

    if facts.active_ready_mega and facts.active_id == MEGA_STARMIE:
        extra = _adrena_extra(facts)
        rider, boss_raw = _double_ko(facts)
        if rider is None:
            rider = _pick_jetting_rider(facts, extra_dp=extra)
        adrena = _pick_adrena_target(facts, rider, extra_dp=extra)
        required = _dp_prep_steps(facts)
        candidate = boss_raw
        can_boss = (
            BOSS_ORDERS in facts.hand_ids and not facts.supporter_played
        )
        # Crustle Rock Inn: ex attack does 0. Gust Active crab before Jetting;
        # Boss-in target is Mega Kanga / best bench (no ≤120 HP gate).
        if facts.ex_immune_active and can_boss:
            wall_bosses = [
                t for t in facts.opp_bench if t is not rider
            ]
            if wall_bosses:
                wall_pick = max(
                    wall_bosses,
                    key=lambda t: (
                        t.boss_priority,
                        t.prizes,
                        -t.hp,
                        -t.index,
                    ),
                )
                required = ["BOSS", *required]
                mode_wall: CombatMode = (
                    "DOUBLE_KO" if rider else "MEGA_MUST_ATTACK"
                )
                return CombatPlan(
                    mode=mode_wall,
                    attack_required=True,
                    required_before_attack=tuple(required),
                    next_action=required[0],
                    rider_target=rider,
                    boss_target=wall_pick,
                    expected_prizes=_prize_line(front=wall_pick, rider=rider),
                    expected_prize_delta=0,
                    froslass_build_allowed=froslass_allowed,
                    adrena_target=adrena,
                )
        if candidate is None:
            # Prize-improving / DoubleKO gust. Keep computing the target even
            # after Boss is played (nested SWITCH still needs it). Exclude rider.
            bosses = [
                t
                for t in facts.opp_bench
                if t is not rider and 0 < t.hp <= 120
            ]
            candidate = max(bosses, key=_boss_key, default=None)
        boss, expected, delta = _effective_boss_candidate(
            facts, rider=rider, candidate=candidate,
        )
        # Wave L: Boss before DP prep so prize gust is not starved by 104/Adrena.
        # (CombatClose-V2 Adrena→Boss 已证伪回滚 — 勿再改此序。)
        # Nested gust: keep boss_target after supporterPlayed; only queue PLAY
        # while Boss is still in hand (92530813: wiping the target let low-HP
        # fallback Boss the 10 HP rider and break DoubleKO).
        if boss is not None and can_boss:
            required = ["BOSS", *required]
        # Empty Jetting into Rock Inn is illegal at pilot; still mark attack
        # required so Boss/non-ex paths stay live after gust.
        mode: CombatMode = "DOUBLE_KO" if rider else "MEGA_MUST_ATTACK"
        return CombatPlan(
            mode=mode,
            attack_required=True,
            required_before_attack=tuple(required),
            next_action=required[0] if required else "ATTACK",
            rider_target=rider,
            boss_target=boss,
            expected_prizes=expected,
            expected_prize_delta=delta,
            froslass_build_allowed=froslass_allowed,
            adrena_target=adrena,
        )

    if (
        facts.active_ready_mega
        and facts.active_id == MEGA_FROSLASS
        and facts.bench_ready_mega_id == MEGA_STARMIE
        and facts.can_dispatch_bench_mega
        and expected_f < 2
        and expected_f < facts.prize_self
    ):
        return CombatPlan(
            mode="MEGA_MUST_ATTACK",
            attack_required=True,
            required_before_attack=("DISPATCH",),
            next_action="DISPATCH",
            expected_prizes=0,
            froslass_build_allowed=froslass_allowed,
        )

    if facts.active_ready_mega and facts.active_id == MEGA_FROSLASS:
        required: list[str] = []
        boss = None
        delta = 0
        expected = expected_f
        can_boss = (
            BOSS_ORDERS in facts.hand_ids and not facts.supporter_played
        )
        if can_boss:
            boss, expected, delta = _effective_froslass_boss_candidate(facts)
            if boss is not None:
                required = ["BOSS"]
            else:
                expected = expected_f
        return CombatPlan(
            mode="FROSLASS_ATTACK",
            attack_required=True,
            required_before_attack=tuple(required),
            next_action=required[0] if required else "ATTACK",
            boss_target=boss,
            expected_prizes=expected,
            expected_prize_delta=delta,
            froslass_build_allowed=froslass_allowed,
        )

    if facts.bench_ready_mega_id and facts.can_dispatch_bench_mega:
        required = _dp_prep_steps(facts)
        required.append("DISPATCH")
        return CombatPlan(
            mode="MEGA_MUST_ATTACK",
            attack_required=True,
            required_before_attack=tuple(required),
            next_action=required[0],
            expected_prizes=0,
            froslass_build_allowed=froslass_allowed,
        )

    return CombatPlan(
        mode="NONE",
        attack_required=False,
        required_before_attack=(),
        next_action="BUILD",
        expected_prizes=expected_f,
        froslass_build_allowed=froslass_allowed,
    )


def _dunsparce_base_id(facts: TurnFacts) -> int:
    """Prefer the free-retreat Dunsparce printing when searching."""
    if DUNSPARCE_A in facts.hand_ids or DUNSPARCE_A in facts.bench_ids:
        return DUNSPARCE_B if DUNSPARCE_B not in facts.bench_ids else DUNSPARCE_A
    return DUNSPARCE_A


def _field_has_dunsparce(facts: TurnFacts) -> bool:
    field = set(facts.bench_ids) | {facts.active_id}
    return bool(field & {DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE})


def _attacker_online(facts: TurnFacts) -> bool:
    return bool(
        facts.active_ready_mega
        or facts.bench_ready_mega_id
        or facts.mega_starmie_on_field
    )


def _attacker_line_online(facts: TurnFacts) -> bool:
    """Staryu or Mega Starmie on field — earlier than ready-to-attack Mega."""
    return bool(facts.staryu_on_field or facts.mega_starmie_on_field)


def _acquire_targets(facts: TurnFacts, gap: TurnGap, objective: Objective) -> tuple[int, ...]:
    """Hand-component-driven minimal activation set.

    Held evolution / DP pieces reshape the search: pair Dudunsparce with a
    Dunsparce base, activate held Munkidori with Dark once an attacker is
    online, and skip gaps already covered by cards in hand.
    """
    if objective == "ATTACK":
        return ()
    hand = set(facts.hand_ids)
    targets: list[int] = []

    # Expert: held Dudunsparce → Poffin can seat attacker base + Dunsparce.
    if (
        DUDUNSPARCE in hand
        and gap.need_base
        and STARYU not in hand
        and not _field_has_dunsparce(facts)
    ):
        targets.extend((STARYU, _dunsparce_base_id(facts)))
        return tuple(dict.fromkeys(targets))

    if gap.need_base and STARYU not in hand:
        return (STARYU,)

    # Held Mega with no Staryu online: only hunt the base, not Dark/Snorunt.
    if MEGA_STARMIE in hand and gap.need_base:
        return (STARYU,)
    # Mega in hand + Staryu can evolve this turn: evolve — no Snorunt dig.
    # If Staryu is online but summoning-sick, fall through to free DP window.
    if MEGA_STARMIE in hand and facts.staryu_can_evolve:
        return ()
    if gap.need_evolution and MEGA_STARMIE not in hand:
        # Unified Ball/Mega dig (autopsy 92356962):
        # - Cannot evolve this turn → never dig Mega (Ball digs Meowth→Lillie).
        # - No Lillie → Ball prefers Meowth; Mega stays listed only when landable
        #   so free Hilda/Salvator can still close (Ball gated separately).
        # - Lillie + supporter free + landable → dig Mega, then play Lillie.
        out: list[int] = []
        if not facts.line_has_water and not hand.intersection(_WATER_IDS):
            out.append(WATER_BASIC)
        can_land = bool(facts.staryu_can_evolve)
        has_lillie = LILLIE in hand
        meowth_online = MEOWTH_EX in facts.bench_ids or facts.active_id == MEOWTH_EX
        meowth_missing = not meowth_online and MEOWTH_EX not in hand
        free_mega_sup = (
            not facts.supporter_played
            and (HILDA in hand or SALVATOR in hand)
        )
        if not can_land:
            # Autopsy 92891770: Hilda/Salvator dig Mega into hand this turn —
            # do NOT Ball-chase Meowth (burns 861).
            if free_mega_sup:
                out.append(MEGA_STARMIE)
                return tuple(dict.fromkeys(out))
            # Autopsy 92356962: no free Mega dig → Meowth, never list Mega for Ball.
            if not has_lillie and meowth_missing:
                out.append(MEOWTH_EX)
            return tuple(dict.fromkeys(out))
        if has_lillie and not facts.supporter_played:
            out.append(MEGA_STARMIE)
            return tuple(dict.fromkeys(out))
        if free_mega_sup:
            # Hilda/Salvator close Mega without Ball — prefer over Meowth dig.
            out.append(MEGA_STARMIE)
            return tuple(dict.fromkeys(out))
        if not has_lillie and meowth_missing:
            # Meowth first so Ball TO_HAND prefers it over Mega.
            out.append(MEOWTH_EX)
            out.append(MEGA_STARMIE)
            return tuple(dict.fromkeys(out))
        # Landable: Lillie held but supporter spent, or Meowth already available.
        out.append(MEGA_STARMIE)
        return tuple(dict.fromkeys(out))

    line_online = _attacker_line_online(facts)
    mega_secured = bool(facts.mega_starmie_on_field or MEGA_STARMIE in hand)
    meowth_online = MEOWTH_EX in facts.bench_ids or facts.active_id == MEOWTH_EX

    # OpsOrder Wave D: post-Mega dry hand → Meowth (→ Lillie → Crispin) before
    # bare water dig or DP Munk (online 91195724).
    if (
        facts.mega_starmie_on_field
        and line_online
        and not meowth_online
        and MEOWTH_EX not in hand
        and LILLIE not in hand
        and CRISPIN not in hand
        and len(facts.hand_ids) <= 4
    ):
        return (MEOWTH_EX,)

    if gap.need_energy and not hand.intersection(_WATER_IDS):
        return (WATER_BASIC,)

    # Hand Munk + line online + Mega secured → seat Munk (not dig side basics).
    if (
        line_online
        and mega_secured
        and MUNKIDORI in hand
        and not facts.munkidori_on_field
    ):
        return (MUNKIDORI,)

    # Fetch Dark once Munk is on field (or Mega secured + Munk held).
    munk_ready_to_activate = (
        line_online
        and not facts.munkidori_has_dark
        and DARK_BASIC not in hand
        and (facts.munkidori_on_field or MUNKIDORI in hand)
        and (mega_secured or facts.munkidori_on_field)
    )
    if munk_ready_to_activate:
        return (DARK_BASIC,)

    if gap.dp_gaps:
        # Skip gaps already satisfied by held pieces; only fetch missing ones.
        order: list[int] = []
        for g in gap.dp_gaps:
            if g == "MUNKIDORI":
                if MUNKIDORI in hand:
                    continue
                # Line not online yet: do not steal seats for Munk before base.
                if not line_online and (
                    gap.need_base or gap.need_evolution or gap.need_energy
                ):
                    continue
                # OpsOrder: Meowth cycle still open — do not Ball-dig Munk first.
                if (
                    facts.mega_starmie_on_field
                    and not meowth_online
                    and MEOWTH_EX not in hand
                    and LILLIE not in hand
                ):
                    continue
                order.append(MUNKIDORI)
            elif g == "DARK_ENERGY":
                if DARK_BASIC in hand:
                    continue
                if not facts.munkidori_on_field and MUNKIDORI not in hand:
                    continue
                if not line_online and not facts.munkidori_on_field:
                    continue
                order.append(DARK_BASIC)
            elif g == "DAMAGE_PLACER":
                if RISKY_RUINS in hand:
                    continue
                # F3: never chase 104/Snorunt when froslass line is banned.
                if facts.ban_froslass_line:
                    if RISKY_RUINS not in hand:
                        order.append(RISKY_RUINS)
                    continue
                if FROSLASS in hand:
                    continue
                if facts.snorunt_on_field:
                    order.append(FROSLASS)
                elif SNORUNT not in hand:
                    order.append(SNORUNT)
                else:
                    order.append(FROSLASS)
        if order:
            return tuple(dict.fromkeys(order))

    if gap.need_second_attacker and not facts.ban_froslass_line:
        if not facts.snorunt_on_field and SNORUNT not in hand:
            return (SNORUNT, MEGA_FROSLASS)
        if MEGA_FROSLASS not in hand:
            return (MEGA_FROSLASS,)
    if gap.need_second_starmie:
        out: list[int] = []
        n_staryu = sum(1 for cid in facts.bench_ids if cid == STARYU) + (
            1 if facts.active_id == STARYU else 0
        )
        n_mega = sum(1 for cid in facts.bench_ids if cid == MEGA_STARMIE) + (
            1 if facts.active_id == MEGA_STARMIE else 0
        )
        if n_staryu + n_mega < 2 and STARYU not in hand:
            out.append(STARYU)
        if n_staryu > 0 and n_mega < 2 and MEGA_STARMIE not in hand:
            out.append(MEGA_STARMIE)
        if out:
            return tuple(dict.fromkeys(out))
    return ()


def _recover_target(facts: TurnFacts, gap: TurnGap) -> int | None:
    discard = set(facts.discard_ids)
    # Wave U4: Mega already online and only needs fuel — water before anything else.
    if (
        facts.mega_starmie_on_field
        and gap.need_energy
        and WATER_BASIC in discard
    ):
        return WATER_BASIC
    # Wave U4: Mega dead/missing, discard has Mega, Staryu line can land — Mega first.
    if (
        not facts.mega_starmie_on_field
        and MEGA_STARMIE in discard
        and (gap.need_evolution or facts.staryu_on_field)
    ):
        return MEGA_STARMIE
    if gap.need_energy and WATER_BASIC in discard:
        return WATER_BASIC
    if "DARK_ENERGY" in gap.dp_gaps and DARK_BASIC in discard:
        return DARK_BASIC
    # Crustle Rock Inn: stretch Boss before side-line recovers.
    if (
        facts.opp_crustle_wall
        and facts.active_ready_mega
        and BOSS_ORDERS in discard
        and BOSS_ORDERS not in facts.hand_ids
    ):
        return BOSS_ORDERS
    # Wave L: fueled Active Mega — stretch Boss back for prize/role gust.
    if (
        facts.active_ready_mega
        and facts.active_id == MEGA_STARMIE
        and BOSS_ORDERS in discard
        and BOSS_ORDERS not in facts.hand_ids
    ):
        return BOSS_ORDERS
    # Wall: prefer stretching 66 as non-ex cleaner.
    if (
        facts.opp_crustle_wall
        and DUDUNSPARCE in discard
        and DUDUNSPARCE not in facts.hand_ids
        and DUDUNSPARCE not in facts.bench_ids
        and facts.active_id != DUDUNSPARCE
    ):
        return DUDUNSPARCE
    for cid in (STARYU, MEGA_STARMIE, SNORUNT, FROSLASS, MUNKIDORI):
        if cid in discard and (
            (cid in (STARYU, MEGA_STARMIE) and (
                gap.need_base or gap.need_evolution or gap.need_second_starmie
            ))
            or (cid == MUNKIDORI and "MUNKIDORI" in gap.dp_gaps)
            or (
                cid in (SNORUNT, FROSLASS)
                and "DAMAGE_PLACER" in gap.dp_gaps
            )
        ):
            return cid
    return None


def _ub_would_force_burn_mega(facts: TurnFacts, gap: TurnGap) -> bool:
    """True when UB's 2 discards must burn held Mega and/or critical water.

    Autopsy 92891770: hand {66, 861, water} after seating Staryu — water is
    "safe" if only Megas are protected, so Ball stayed legal and burned 861.
    Critical water (need_energy) counts as non-fodder alongside both Megas.
    """
    non_fodder = {MEGA_STARMIE, MEGA_FROSLASS}
    if gap.need_energy:
        non_fodder.add(WATER_BASIC)
    if not (non_fodder & set(facts.hand_ids)):
        return False
    counts: Counter[int] = Counter(facts.hand_ids)
    if counts.get(ULTRA_BALL, 0) <= 0:
        return False
    counts[ULTRA_BALL] -= 1
    if counts[ULTRA_BALL] <= 0:
        del counts[ULTRA_BALL]
    safe = sum(n for cid, n in counts.items() if cid not in non_fodder)
    return safe < 2


def _ub_would_force_burn_protected(
    facts: TurnFacts, protected: frozenset[int],
) -> bool:
    """True when UB's 2 discards must include a protected hand card.

    Short hands that simply lack 2 discards are not treated as protected-burn
    (engine won't offer Ball); only force-burn of live protected cards.
    """
    counts: Counter[int] = Counter(facts.hand_ids)
    if counts.get(ULTRA_BALL, 0) <= 0:
        return False
    counts[ULTRA_BALL] -= 1
    if counts[ULTRA_BALL] <= 0:
        del counts[ULTRA_BALL]
    protected_count = sum(n for cid, n in counts.items() if cid in protected)
    if protected_count <= 0:
        return False
    safe = sum(n for cid, n in counts.items() if cid not in protected)
    return safe < 2


def discard_value(card_id: int, plan: TurnPlan | AcquirePlan) -> int:
    acquire = plan.acquire if isinstance(plan, TurnPlan) else plan
    return acquire.value(card_id)


def _acquire_plan(facts: TurnFacts, gap: TurnGap, objective: Objective, combat: CombatPlan) -> AcquirePlan:
    targets = () if combat.attack_required else _acquire_targets(
        facts, gap, objective,
    )
    hand = Counter(facts.hand_ids)
    recover = _recover_target(facts, gap)
    sources: list[int] = []
    need_mega_fetch = gap.need_evolution and MEGA_STARMIE not in facts.hand_ids
    if targets:
        if POFFIN in hand and any(t in _BASE_ATTACKERS for t in targets):
            sources.append(POFFIN)
        # Poké Pad: no Rule Box only — Staryu/Snorunt/Froslass/Dudunsparce/Munk.
        # Mega ex has a Rule Box and cannot be Pad-fetched.
        if POKE_PAD in hand and any(
            t in (STARYU, SNORUNT, FROSLASS, DUDUNSPARCE, MUNKIDORI) for t in targets
        ):
            sources.append(POKE_PAD)
        # Supporters only close the gap if they can still be played this turn.
        if (
            HILDA in hand
            and not facts.supporter_played
            and any(t in (MEGA_STARMIE, FROSLASS, MEGA_FROSLASS) for t in targets)
        ):
            sources.append(HILDA)
        # Salvator fetches Evolution Pokémon — primary Mega dig supporter.
        if SALVATOR in hand and not facts.supporter_played and MEGA_STARMIE in targets:
            sources.append(SALVATOR)
        if ULTRA_BALL in hand and any(
            t in (
                STARYU, MEGA_STARMIE, SNORUNT, FROSLASS, MEGA_FROSLASS,
                MUNKIDORI, MEOWTH_EX,
            )
            for t in targets
        ):
            sources.append(ULTRA_BALL)
        # H1: missing Staryu — Lillie dig is a first-class source (Hilda cannot fetch Basics).
        if (
            LILLIE in hand
            and not facts.supporter_played
            and gap.need_base
            and STARYU not in hand
            and STARYU in targets
        ):
            sources.append(LILLIE)
    if recover is not None and NIGHT_STRETCHER in hand:
        sources.append(NIGHT_STRETCHER)

    free_closes_gap = any(s in (POFFIN, POKE_PAD, HILDA, SALVATOR) for s in sources)
    target_is_pokemon = any(t not in (WATER_BASIC, DARK_BASIC) for t in targets)
    second_done = facts.active_ready_mega and bool(facts.bench_ready_mega_id)
    # G1: digging Mega is never a "side-line" Ball — UB-1 must not block 1031.
    mega_is_target = MEGA_STARMIE in targets
    meowth_is_target = MEOWTH_EX in targets
    mega_held = MEGA_STARMIE in hand
    line_water = bool(facts.line_has_water or WATER_BASIC in hand)
    # Never burn Lillie to Ball; protect Crispin while the water path is open.
    ub_protected: set[int] = {LILLIE}
    if gap.need_energy or not line_water:
        ub_protected.add(CRISPIN)
    if not target_is_pokemon:
        ball_allowed, reason = False, "no current Pokemon gap"
    elif mega_held and (facts.staryu_on_field or facts.mega_starmie_on_field):
        ball_allowed, reason = False, "UB-2 Mega already held with base online"
    elif (
        mega_held
        and line_water
        and facts.staryu_on_field
        and not need_mega_fetch
    ):
        # Wave U2b: land path already complete — keep Ball for Meowth/Lillie later.
        ball_allowed, reason = False, "UB-2b Mega+water path held — defer Ball"
    elif _ub_would_force_burn_mega(facts, gap):
        # Wave U2: engine must discard 2; hand would force Mega (or sole water).
        ball_allowed, reason = False, "UB-forced-burn Mega/critical water"
    elif _ub_would_force_burn_protected(facts, frozenset(ub_protected)):
        ball_allowed, reason = False, "UB-forced-burn Lillie/Crispin"
    elif need_mega_fetch and mega_is_target:
        # Autopsy 92356962: Ball digs Mega only when same-turn land + Lillie
        # ready after evolve. Otherwise dig Meowth, or fall through for free
        # Hilda / last-resort landable Mega.
        if not facts.staryu_can_evolve:
            if meowth_is_target:
                ball_allowed, reason = True, "UB dig Meowth (cannot land Mega)"
            else:
                ball_allowed, reason = False, "UB Mega blocked (cannot evolve this turn)"
        elif LILLIE in hand and not facts.supporter_played:
            ball_allowed, reason = True, "UB Mega: Lillie+landable+supporter free"
        elif meowth_is_target and LILLIE not in hand:
            ball_allowed, reason = True, "UB dig Meowth (no Lillie)"
        else:
            # Landable Mega listed for free search; Ball only if no free close.
            if free_closes_gap:
                ball_allowed, reason = False, "UB-3 free search closes current gap"
            else:
                ball_allowed, reason = True, "UB Mega fallback (landable, no free search)"
    elif free_closes_gap:
        ball_allowed, reason = False, "UB-3 free search closes current gap"
    elif (
        not facts.mega_starmie_on_field
        and not mega_is_target
        and any(t in (SNORUNT, FROSLASS, MUNKIDORI) for t in targets)
    ):
        ball_allowed, reason = False, "UB-1 pre-Mega Ball stays on the attacker line"
    elif second_done:
        ball_allowed, reason = False, "UB-5 second attacker already complete"
    else:
        ball_allowed, reason = True, "current Pokemon gap has no free exact search"

    # UbSurplusDun-V1: field+hand Dunsparce line ≥3 → spare basic PATH-discardable.
    duns_line = (
        sum(1 for cid in facts.hand_ids if cid in (DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE))
        + sum(1 for cid in facts.bench_ids if cid in (DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE))
        + (1 if facts.active_id in (DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE) else 0)
    )

    values: dict[int, int] = {}
    for cid in set(facts.hand_ids):
        value = 100
        if cid in targets or (
            (cid == STARYU and gap.need_base)
            or (cid == MEGA_STARMIE and gap.need_evolution)
        ):
            value = 10_000
        elif cid == MEGA_STARMIE:
            # Wave U2: never soft-burn held Mega even when dig target is a base.
            value = 10_000
        elif cid == MEGA_FROSLASS:
            # Autopsy 92891770: never Ball-burn the second attacker.
            value = 10_000
        elif cid == LILLIE:
            # Autopsy 92356962: Ultra Ball must never discard Lillie.
            value = 10_000
        elif cid == HILDA and (
            gap.need_evolution or not facts.mega_starmie_on_field
        ):
            # Keep Hilda to dig Mega Starmie (92891770 correct line).
            value = 9_500
        elif cid == CRISPIN and (gap.need_energy or not line_water):
            # Crispin is the water/Dark path — do not Ball-burn it dry.
            value = 9_500
        elif cid == WATER_BASIC and (gap.need_energy or combat.attack_required):
            value = 9_500
        elif cid == DARK_BASIC and "DARK_ENERGY" in gap.dp_gaps:
            value = 9_000
        elif cid == BOSS_ORDERS and (
            facts.prize_self <= 2
            or combat.boss_target
            or facts.opp_crustle_wall
            or facts.ex_immune_active
        ):
            value = 9_500 if facts.ex_immune_active or facts.opp_crustle_wall else 8_500
        elif cid == DUDUNSPARCE and facts.opp_crustle_wall:
            # Non-ex cleaner vs Rock Inn — never Ball-burn the last 66.
            value = 9_000 if hand[cid] <= 1 else 7_500
        elif cid == NIGHT_STRETCHER and recover is not None:
            value = 8_000
        elif cid == RISKY_RUINS and not facts.mega_starmie_on_field:
            # Early UB fodder before DP is online (prefer over Hilda/861).
            value = 25
        elif cid == DUDUNSPARCE and (
            gap.need_base or (gap.need_evolution and not facts.mega_starmie_on_field)
        ):
            # Spare evo before engine is online — OK UB fodder vs Hilda/861.
            value = 30
        elif cid in (POFFIN, POKE_PAD) and not any(t in _BASE_ATTACKERS for t in targets):
            value = 20
        elif cid in (STARYU, SNORUNT, MUNKIDORI) and (
            (cid == STARYU and facts.mega_starmie_on_field)
            or (cid == SNORUNT and (facts.froslass_104_on_field or facts.mega_froslass_on_field))
            or (cid == MUNKIDORI and facts.munkidori_on_field)
        ):
            value = 30 if hand[cid] > 1 else 60
        elif cid in (DUNSPARCE_A, DUNSPARCE_B) and duns_line >= 3:
            value = 25
        elif cid == ULTRA_BALL and not ball_allowed:
            value = 25
        values[cid] = value

    # HandQual-V1: when Ball is a live Mega dig, protect continuity capital
    # (Lillie/Judge/Stamp; Poffin/Pad while bench open) from soft-discard.
    # HandQual-V1.1 REJECTED (both knives): plan-step Ball demote → Opening 68%
    # (Hilda soft-tied Evolve under mega_offered DIG lock); discard-protect
    # Hilda/Salvator → Opening 73%. Keep V1 continuity set only.
    # Lillie is always 10_000 above; reinforce Judge/Stamp on live digs.
    if ball_allowed and (need_mega_fetch or meowth_is_target):
        for cid in (JUDGE, UNFAIR_STAMP):
            if cid in hand:
                values[cid] = max(values.get(cid, 100), 7_500)
        if facts.bench_open > 0:
            for cid in (POFFIN, POKE_PAD):
                if cid in hand:
                    values[cid] = max(values.get(cid, 100), 7_000)

    return AcquirePlan(
        targets=targets,
        sources=tuple(dict.fromkeys(sources)),
        ball_allowed=ball_allowed,
        ball_reason=reason,
        discard_values=tuple(sorted(values.items())),
        recover_target=recover,
    )


def _draw_plan(facts: TurnFacts, gap: TurnGap, combat: CombatPlan) -> DrawPlan:
    duns_count = sum(cid in (DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE) for cid in (facts.bench_ids + (facts.active_id,)))
    only_single_gap = sum((gap.need_base, gap.need_evolution, gap.need_energy)) == 1
    evolution_energy_no_base = (
        gap.need_base
        and any(cid in (MEGA_STARMIE, MEGA_FROSLASS, FROSLASS) for cid in facts.hand_ids)
        and any(cid in _WATER_IDS for cid in facts.hand_ids)
    )
    bad_hand = only_single_gap or evolution_energy_no_base
    path_open = gap.need_base or gap.need_evolution or gap.need_energy
    mega_in_hand = MEGA_STARMIE in facts.hand_ids
    # HOLD only when Mega is already held and can land — never block Lillie dig for Mega.
    ready_land = mega_in_hand and (
        facts.two_turn_mega_path
        or mega_ready_to_land(
            staryu_on_field=facts.staryu_on_field,
            mega_starmie_on_field=facts.mega_starmie_on_field,
            line_has_water=facts.line_has_water,
            hand_ids=facts.hand_ids,
            supporter_played=facts.supporter_played,
        )
    )
    # F4: HOLD while held Mega can land; structured bad hands may still dig.
    if combat.attack_required or ready_land:
        allow_draw = False
        reason = "attack/mega-land path owns the turn"
    elif path_open and not bad_hand:
        allow_draw = False
        reason = "MAKE_ATTACKER gap still open"
    else:
        allow_draw = bad_hand
        reason = "structured single-gap bad hand" if allow_draw else (
            "hand preserves a live path"
        )
    # MidOps: post-Mega 66 may cycle when the attacker line is closed AND the
    # hand cannot seat/redraw progress (not RunAway-V1 default post-Mega draw).
    dud_online = (
        DUDUNSPARCE in facts.bench_ids or facts.active_id == DUDUNSPARCE
    )
    if (
        not allow_draw
        and not combat.attack_required
        and not ready_land
        and dud_online
        and facts.mega_starmie_on_field
        and not path_open
        and len(facts.hand_ids) <= 4
    ):
        hand_set = set(facts.hand_ids)
        can_seat_munk = (
            "MUNKIDORI" in gap.dp_gaps
            and MUNKIDORI in hand_set
            and facts.bench_open > 0
        )
        can_seat_snorunt = (
            gap.need_second_attacker
            and not facts.ban_froslass_line
            and SNORUNT in hand_set
            and facts.bench_open > 0
            and not facts.snorunt_on_field
        )
        has_redraw = (
            not facts.supporter_played
            and bool(hand_set & {LILLIE, JUDGE})
        )
        if not can_seat_munk and not can_seat_snorunt and not has_redraw:
            if gap.dp_gaps or gap.need_second_attacker or len(facts.hand_ids) <= 2:
                allow_draw = True
                reason = "post-mega 66: no seatable/redraw cover"
    # Seat preset: Dunsparce-line ≤1 on the 6-seat field. No second copy.
    under_duns_cap = duns_count < 1 and facts.bench_open > 0
    first = duns_count == 0 and under_duns_cap and not gap.need_base
    second = False  # field preset: 土龙×1 only
    return DrawPlan(allow_draw, first, second, reason)


def build_turn_plan(
    obs: Any,
    board: Any,
    *,
    phase: Any | None = None,
    resources: Any | None = None,
    matchup: str | None = None,
) -> TurnPlan:
    facts = build_turn_facts(obs, board, matchup=matchup)
    gap = _turn_gap(facts)
    combat = _combat_plan(facts)
    n_miss = count_missing_types(facts, gap)
    force_draw = must_prioritize_draw(facts, gap, combat)
    if combat.attack_required and facts.active_ready_mega:
        objective: Objective = "ATTACK"
    elif combat.attack_required:
        # DISPATCH / pre-attack setup beats dig — Layer1 yields to attack turns.
        objective = "MAKE_ATTACKER"
    elif force_draw:
        # Draw-7 ≈ two typed searches; three+ gaps → dig first.
        objective = "DRAW"
    elif gap.need_base or gap.need_evolution or gap.need_energy:
        objective = "MAKE_ATTACKER"
    elif gap.dp_gaps:
        objective = "BUILD_DP"
    elif gap.need_second_attacker or gap.need_second_starmie:
        objective = "SECOND_ATTACKER"
    else:
        objective = "DRAW"
    acquire = _acquire_plan(facts, gap, objective, combat)
    draw = _draw_plan(facts, gap, combat)
    path: list[str] = []
    if gap.need_base:
        path.append("BASE")
    if gap.need_evolution:
        if not facts.staryu_can_evolve:
            path.append("WAIT_EVOLVE")
        path.append("EVOLUTION")
    if gap.need_energy:
        path.append("ENERGY")
    if not path and gap.dp_gaps:
        path.extend(gap.dp_gaps)
    forbidden: list[str] = []
    reasons: list[str] = []
    if combat.attack_required:
        forbidden.extend(("END", "BASIC_ATTACK"))
        reasons.append("a ready Mega must attack this turn")
    elif _ban_basic_attack(objective, combat, facts):
        forbidden.append("BASIC_ATTACK")
        reasons.append("basic attacks banned while building/landing Mega")
    elif not combat.attack_required:
        # Wave U1: Staryu gun always illegal — expose via forbidden even when
        # other basics (Itchy) remain legal under the selective ban.
        forbidden.append("BASIC_ATTACK")
        reasons.append("Wave U1: Staryu Water Gun banned")
    if not combat.froslass_build_allowed:
        forbidden.append("BUILD_861")
        reasons.append("Mega Froslass build gated (prizes/matchup)")
    if not acquire.ball_allowed:
        forbidden.append("ULTRA_BALL")
        reasons.append(acquire.ball_reason)
    if force_draw:
        reasons.append(f"n_missing_types={n_miss}≥3 → prioritize dig")
    if facts.two_turn_mega_path:
        reasons.append("two_turn_mega_path live")
    mid_gaps = enumerate_midgame_open_gaps(facts, gap)
    if mid_gaps:
        reasons.append(f"midgame_open_gaps={','.join(mid_gaps)}")
    return TurnPlan(
        facts=facts,
        gap=gap,
        objective=objective,
        two_turn_path=tuple(path),
        acquire=acquire,
        combat=combat,
        draw=draw,
        forbidden_actions=tuple(forbidden),
        reasons=tuple(reasons),
        midgame_open_gaps=mid_gaps,
    )


def _ban_basic_attack(
    objective: Objective,
    combat: CombatPlan,
    facts: TurnFacts,
) -> bool:
    if combat.attack_required:
        return True
    # G0: fueled Mega on bench — never Water Gun / Itchy while it exists.
    if facts.bench_ready_mega_id:
        return True
    mega_in_hand = MEGA_STARMIE in facts.hand_ids
    # Legal Mega evolve / land window — never Water Gun.
    if mega_in_hand and facts.staryu_on_field and facts.staryu_can_evolve:
        return True
    if mega_in_hand and facts.two_turn_mega_path:
        return True
    if mega_in_hand and mega_ready_to_land(
        staryu_on_field=facts.staryu_on_field,
        mega_starmie_on_field=facts.mega_starmie_on_field,
        line_has_water=facts.line_has_water,
        hand_ids=facts.hand_ids,
        supporter_played=facts.supporter_played,
    ):
        return True
    # H1: Active Staryu + water + Mega in hand — never Water Gun over evolve.
    if (
        objective == "MAKE_ATTACKER"
        and facts.active_id == STARYU
        and facts.line_has_water
        and not facts.mega_starmie_on_field
        and mega_in_hand
        and facts.staryu_can_evolve
    ):
        return True
    # Wave U1: Dudunsparce dig available — never Water Gun over evolve-draw.
    if (
        DUDUNSPARCE in facts.hand_ids
        and any(cid in (DUNSPARCE_A, DUNSPARCE_B) for cid in facts.bench_ids + (facts.active_id,))
    ):
        return True
    # MAKE_ATTACKER: ban base attacks only when a dig/setup tool is actually in hand.
    if objective == "MAKE_ATTACKER" and any(
        cid in facts.hand_ids
        for cid in (SALVATOR, HILDA, CRISPIN, ULTRA_BALL, POFFIN, LILLIE, MEGA_STARMIE)
    ):
        return True
    return False


def is_basic_attack_forbidden(
    card_id: int,
    plan: TurnPlan,
    *,
    attack_id: int | None = None,
) -> bool:
    """Ban basic attacks per expert C1; sole exception = Budew Itchy stall."""
    if card_id not in _BASIC_ATTACK_BAN:
        return False
    # Wave U1: Staryu Water Gun is illegal unless a Mega must-attack turn
    # already routes through the shared ban (attack_required → True above).
    if card_id == STARYU and not plan.combat.attack_required:
        return True
    if not _ban_basic_attack(plan.objective, plan.combat, plan.facts):
        return False
    # Itchy stall is illegal once a fueled Mega sits on the bench (G0).
    if (
        card_id == BUDEW
        and not plan.combat.attack_required
        and not plan.facts.bench_ready_mega_id
        and attack_id == _ATK_ITCHY_POLLEN
    ):
        return False
    return True
