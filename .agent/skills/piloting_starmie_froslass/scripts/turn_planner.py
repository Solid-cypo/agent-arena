"""Pure, per-decision planning for the Starmie/Froslass pilot.

The planner intentionally owns no cursor or cross-turn state.  Every action
changes the observation and the next call derives a fresh plan.  Epoch memory
remains responsible only for long-lived opening/SF progress.
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
    is_attack_damage_protected,
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


def _prize_value(pokemon: Any) -> int:
    explicit = _si(getattr(pokemon, "prizeValue", None))
    if explicit > 0:
        return explicit
    return 2 if bool(getattr(pokemon, "ex", False) or getattr(pokemon, "megaEx", False)) else 1


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
    # Matchup / public-board gates (expert F3).
    opp_archaludon_threat: bool = False
    opp_munk_dp_online: bool = False
    ban_froslass_line: bool = False
    two_turn_mega_path: bool = False


@dataclass(frozen=True)
class TurnGap:
    need_base: bool
    need_evolution: bool
    need_energy: bool
    dp_gaps: tuple[str, ...]
    need_second_attacker: bool


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


@dataclass(frozen=True)
class DrawPlan:
    allow_run_away_draw: bool
    allow_first_dunsparce: bool
    allow_second_dunsparce: bool
    reason: str


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
            area == "BENCH"
            and is_attack_damage_protected(pokemon, opp_field_ids)
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
    opp_has_munk = MUNKIDORI in opp_field_card_ids
    opp_munk_has_dark = any(
        _si(getattr(p, "id", None)) == MUNKIDORI and _has_energy(p, _DARK_IDS)
        for p in opp_field
    )
    opp_has_placer = bool(
        opp_field_card_ids & {FROSLASS, MEGA_FROSLASS}
    ) or risky_ruins_online
    opp_munk_dp_online = opp_has_munk and (opp_munk_has_dark or opp_has_placer)
    ban_froslass_line = bool(
        matchup == "alakazam"
        or opp_archaludon_threat
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
        opp_munk_dp_online=opp_munk_dp_online,
        ban_froslass_line=ban_froslass_line,
        two_turn_mega_path=two_turn_mega,
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
            facts.mega_starmie_on_field
            and not facts.mega_froslass_on_field
            and not facts.ban_froslass_line
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


def _expected_froslass_prizes(facts: TurnFacts) -> int:
    damage = 50 * facts.opp_hand_count
    targets = tuple(t for t in ((facts.opp_active,) + facts.opp_bench) if t)
    return max((t.prizes for t in targets if 0 < t.hp <= damage), default=0)


def _rider_key(target: OppTarget) -> tuple:
    # Knockability is pre-filtered; prefer cutting a main base, then prizes, then HP.
    return (target.rider_priority, target.prizes, -target.hp, -target.index)


def _boss_key(target: OppTarget, *, jetting_damage: int = 120) -> tuple:
    koable = 1 if 0 < target.hp <= jetting_damage else 0
    return (koable, target.prizes, target.boss_priority, -target.hp, -target.index)


def _double_ko(facts: TurnFacts) -> tuple[OppTarget | None, OppTarget | None]:
    if not facts.active_ready_mega or facts.active_id != MEGA_STARMIE:
        return None, None
    rider_limit = 80 if facts.transferable_damage >= 30 and facts.munkidori_has_dark else 50
    riders = [
        t
        for t in facts.opp_bench
        if 0 < t.hp <= rider_limit and not t.attack_protected
    ]
    if not riders:
        return None, None
    rider = max(riders, key=_rider_key)
    active = facts.opp_active
    if active and 0 < active.hp <= 120:
        return rider, None
    bosses = [t for t in facts.opp_bench if t != rider and 0 < t.hp <= 120]
    boss = max(bosses, key=_boss_key, default=None)
    return (rider, boss) if boss else (None, None)


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
    froslass_allowed = (
        not facts.ban_froslass_line
        and (expected_f >= 2 or froslass_exception)
    )

    if facts.active_ready_mega and facts.active_id == MEGA_STARMIE:
        rider, boss_raw = _double_ko(facts)
        required = _dp_prep_steps(facts)
        candidate = boss_raw
        can_boss = (
            BOSS_ORDERS in facts.hand_ids and not facts.supporter_played
        )
        if can_boss and candidate is None:
            # Also consider a prize-improving gust when the Active is already
            # KO-able (effective Boss), or any KO-able front when it is not.
            bosses = [
                t
                for t in facts.opp_bench
                if t is not rider and 0 < t.hp <= 120
            ]
            candidate = max(bosses, key=_boss_key, default=None)
        if not can_boss:
            candidate = None
        boss, expected, delta = _effective_boss_candidate(
            facts, rider=rider, candidate=candidate,
        )
        # Wave L: Boss before DP prep so prize gust is not starved by 104/Adrena.
        if boss is not None:
            required = ["BOSS", *required]
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
        return CombatPlan(
            mode="FROSLASS_ATTACK",
            attack_required=True,
            required_before_attack=(),
            next_action="ATTACK",
            expected_prizes=expected_f,
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
        # G1: always dig Mega Starmie — never mix FROSLASS/SNORUNT into targets
        # (that tripped UB-1 and caused miss_ub_mega while Ball sat unused).
        out: list[int] = []
        if not facts.line_has_water and not hand.intersection(_WATER_IDS):
            out.append(WATER_BASIC)
        out.append(MEGA_STARMIE)
        return tuple(out)
    if gap.need_energy and not hand.intersection(_WATER_IDS):
        return (WATER_BASIC,)

    line_online = _attacker_line_online(facts)
    mega_secured = bool(facts.mega_starmie_on_field or MEGA_STARMIE in hand)

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
    return ()


def _recover_target(facts: TurnFacts, gap: TurnGap) -> int | None:
    discard = set(facts.discard_ids)
    if gap.need_energy and WATER_BASIC in discard:
        return WATER_BASIC
    if "DARK_ENERGY" in gap.dp_gaps and DARK_BASIC in discard:
        return DARK_BASIC
    # Wave L: fueled Active Mega — stretch Boss back for prize/role gust.
    if (
        facts.active_ready_mega
        and facts.active_id == MEGA_STARMIE
        and BOSS_ORDERS in discard
        and BOSS_ORDERS not in facts.hand_ids
    ):
        return BOSS_ORDERS
    for cid in (STARYU, MEGA_STARMIE, SNORUNT, FROSLASS, MUNKIDORI):
        if cid in discard and (
            (cid in (STARYU, MEGA_STARMIE) and (gap.need_base or gap.need_evolution))
            or (cid == MUNKIDORI and "MUNKIDORI" in gap.dp_gaps)
            or (
                cid in (SNORUNT, FROSLASS)
                and "DAMAGE_PLACER" in gap.dp_gaps
            )
        ):
            return cid
    return None


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
        # Poké Pad: no Rule Box only — Staryu/Snorunt/Froslass/Dudunsparce.
        # Mega ex has a Rule Box and cannot be Pad-fetched.
        if POKE_PAD in hand and any(t in (STARYU, SNORUNT, FROSLASS, DUDUNSPARCE) for t in targets):
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
        if ULTRA_BALL in hand and any(t in (STARYU, MEGA_STARMIE, SNORUNT, FROSLASS, MEGA_FROSLASS, MUNKIDORI) for t in targets):
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
    if not target_is_pokemon:
        ball_allowed, reason = False, "no current Pokemon gap"
    elif MEGA_STARMIE in hand and (facts.staryu_on_field or facts.mega_starmie_on_field):
        ball_allowed, reason = False, "UB-2 Mega already held with base online"
    elif need_mega_fetch and mega_is_target:
        # Plan G1: authorize Ball while Mega is the gap (supporters still score
        # higher in Layer1; do not let a dead held supporter lock Ball out).
        ball_allowed, reason = True, "G1 need Mega — Ball dig authorized"
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

    values: dict[int, int] = {}
    for cid in set(facts.hand_ids):
        value = 100
        if cid in targets or (
            (cid == STARYU and gap.need_base)
            or (cid == MEGA_STARMIE and gap.need_evolution)
        ):
            value = 10_000
        elif cid == WATER_BASIC and (gap.need_energy or combat.attack_required):
            value = 9_500
        elif cid == DARK_BASIC and "DARK_ENERGY" in gap.dp_gaps:
            value = 9_000
        elif cid == BOSS_ORDERS and (facts.prize_self <= 2 or combat.boss_target):
            value = 8_500
        elif cid == NIGHT_STRETCHER and recover is not None:
            value = 8_000
        elif cid in (POFFIN, POKE_PAD) and not any(t in _BASE_ATTACKERS for t in targets):
            value = 20
        elif cid in (STARYU, SNORUNT, MUNKIDORI) and (
            (cid == STARYU and facts.mega_starmie_on_field)
            or (cid == SNORUNT and (facts.froslass_104_on_field or facts.mega_froslass_on_field))
            or (cid == MUNKIDORI and facts.munkidori_on_field)
        ):
            value = 30 if hand[cid] > 1 else 60
        elif cid == ULTRA_BALL and not ball_allowed:
            value = 25
        values[cid] = value

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
    first = duns_count == 0 and facts.bench_open > 0 and not gap.need_base
    second = duns_count == 1 and facts.bench_budget > 0
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
    elif gap.need_second_attacker:
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
