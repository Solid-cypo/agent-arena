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
    can_retreat_pokemon,
    ENERGY_IDS,
    retreat_cost_for,
)

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


def build_turn_facts(obs: Any, board: Any) -> TurnFacts:
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

    def target(pokemon: Any, area: str, index: int) -> OppTarget:
        return OppTarget(
            area=area,
            index=index,
            card_id=_si(getattr(pokemon, "id", None)),
            hp=_si(getattr(pokemon, "hp", None), 999),
            prizes=_prize_value(pokemon),
            threat=_si(getattr(pokemon, "threat", None)),
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

    # Reserve spaces for roles that are not yet represented.  This is a budget,
    # not a demand to fill every role.
    reserve = 0
    field_ids = {_si(getattr(p, "id", None)) for p in field}
    if not ({STARYU, MEGA_STARMIE} & field_ids):
        reserve += 1
    if MUNKIDORI not in field_ids:
        reserve += 1
    if not ({SNORUNT, FROSLASS, MEGA_FROSLASS} & field_ids):
        reserve += 1
    if MEGA_STARMIE in field_ids and not ({SNORUNT, MEGA_FROSLASS} & field_ids):
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
        dp.append("DAMAGE_PLACER")
    return TurnGap(
        need_base=need_base,
        need_evolution=need_evolution,
        need_energy=need_energy,
        dp_gaps=tuple(dp),
        need_second_attacker=facts.mega_starmie_on_field and not facts.mega_froslass_on_field,
    )


def _expected_froslass_prizes(facts: TurnFacts) -> int:
    damage = 50 * facts.opp_hand_count
    targets = tuple(t for t in ((facts.opp_active,) + facts.opp_bench) if t)
    return max((t.prizes for t in targets if 0 < t.hp <= damage), default=0)


def _double_ko(facts: TurnFacts) -> tuple[OppTarget | None, OppTarget | None]:
    if not facts.active_ready_mega or facts.active_id != MEGA_STARMIE:
        return None, None
    rider_limit = 80 if facts.transferable_damage >= 30 and facts.munkidori_has_dark else 50
    riders = [t for t in facts.opp_bench if 0 < t.hp <= rider_limit]
    if not riders:
        return None, None
    rider = max(riders, key=lambda t: (t.prizes, t.threat, -t.hp))
    active = facts.opp_active
    if active and 0 < active.hp <= 120:
        return rider, None
    bosses = [t for t in facts.opp_bench if t != rider and 0 < t.hp <= 120]
    boss = max(bosses, key=lambda t: (t.prizes, t.threat, -t.hp), default=None)
    return (rider, boss) if boss else (None, None)


def _dp_prep_steps(facts: TurnFacts) -> list[str]:
    """Small, bounded DP actions that never replace the mandatory attack."""
    required: list[str] = []
    if (
        facts.snorunt_can_evolve
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
    froslass_exception = (
        expected_f >= facts.prize_self
        or (
            not facts.mega_starmie_on_field
            and (facts.mega_froslass_on_field or facts.snorunt_on_field)
        )
    )
    froslass_allowed = expected_f >= 2 or froslass_exception

    if facts.active_ready_mega and facts.active_id == MEGA_STARMIE:
        rider, boss = _double_ko(facts)
        required = _dp_prep_steps(facts)
        if (
            rider is None
            and facts.opp_active
            and facts.opp_active.hp > 120
            and BOSS_ORDERS in facts.hand_ids
            and not facts.supporter_played
        ):
            boss = max(
                (t for t in facts.opp_bench if 0 < t.hp <= 120),
                key=lambda t: (t.prizes, t.threat, -t.hp),
                default=None,
            )
        if boss and BOSS_ORDERS in facts.hand_ids and not facts.supporter_played:
            required.append("BOSS")
        elif boss:
            boss = None
        mode: CombatMode = "DOUBLE_KO" if rider else "MEGA_MUST_ATTACK"
        front = boss or facts.opp_active
        return CombatPlan(
            mode=mode,
            attack_required=True,
            required_before_attack=tuple(required),
            next_action=required[0] if required else "ATTACK",
            rider_target=rider,
            boss_target=boss,
            expected_prizes=(front.prizes if front and front.hp <= 120 else 0)
            + (rider.prizes if rider else 0),
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


def _acquire_targets(facts: TurnFacts, gap: TurnGap, objective: Objective) -> tuple[int, ...]:
    if objective == "ATTACK":
        return ()
    hand = set(facts.hand_ids)
    if gap.need_base and STARYU not in hand:
        return (STARYU,)
    if gap.need_evolution and MEGA_STARMIE not in hand:
        return (MEGA_STARMIE,)
    if gap.need_energy and not hand.intersection(_WATER_IDS):
        return (WATER_BASIC,)
    # Once every missing attacker component is already held, spend free search
    # windows on DP before evolving/attaching closes the turn with a mandatory
    # attack.  Ultra Ball remains separately gated pre-Mega below.
    if gap.dp_gaps:
        order = {
            "MUNKIDORI": MUNKIDORI,
            "DARK_ENERGY": DARK_BASIC,
            "DAMAGE_PLACER": (
                RISKY_RUINS
                if RISKY_RUINS in facts.hand_ids
                else (SNORUNT if not facts.snorunt_on_field else FROSLASS)
            ),
        }
        return tuple(dict.fromkeys(order[g] for g in gap.dp_gaps))
    if gap.need_second_attacker:
        if not facts.snorunt_on_field:
            return (SNORUNT, MEGA_FROSLASS)
        return (MEGA_FROSLASS,)
    return ()


def _recover_target(facts: TurnFacts, gap: TurnGap) -> int | None:
    discard = set(facts.discard_ids)
    if gap.need_energy and WATER_BASIC in discard:
        return WATER_BASIC
    if "DARK_ENERGY" in gap.dp_gaps and DARK_BASIC in discard:
        return DARK_BASIC
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
    if targets:
        if POFFIN in hand and any(t in _BASE_ATTACKERS for t in targets):
            sources.append(POFFIN)
        if POKE_PAD in hand and any(t in (STARYU, MEGA_STARMIE, SNORUNT, FROSLASS) for t in targets):
            sources.append(POKE_PAD)
        if HILDA in hand and any(t in (MEGA_STARMIE, FROSLASS, MEGA_FROSLASS) for t in targets):
            sources.append(HILDA)
        if ULTRA_BALL in hand and any(t in (STARYU, MEGA_STARMIE, SNORUNT, FROSLASS, MEGA_FROSLASS, MUNKIDORI) for t in targets):
            sources.append(ULTRA_BALL)
    if recover is not None and NIGHT_STRETCHER in hand:
        sources.append(NIGHT_STRETCHER)

    free_closes_gap = any(s in (POFFIN, POKE_PAD, HILDA) for s in sources)
    target_is_pokemon = any(t not in (WATER_BASIC, DARK_BASIC) for t in targets)
    second_done = facts.active_ready_mega and bool(facts.bench_ready_mega_id)
    if not target_is_pokemon:
        ball_allowed, reason = False, "no current Pokemon gap"
    elif MEGA_STARMIE in hand and (facts.staryu_on_field or facts.mega_starmie_on_field):
        ball_allowed, reason = False, "UB-2 Mega already held with base online"
    elif free_closes_gap:
        ball_allowed, reason = False, "UB-3 free search closes current gap"
    elif not facts.mega_starmie_on_field and any(
        t in (SNORUNT, FROSLASS, MUNKIDORI) for t in targets
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
    allow_draw = not combat.attack_required and bad_hand
    first = duns_count == 0 and facts.bench_open > 0 and not gap.need_base
    second = duns_count == 1 and facts.bench_budget > 0
    reason = "structured single-gap bad hand" if allow_draw else (
        "attack turn" if combat.attack_required else "hand preserves a live path"
    )
    return DrawPlan(allow_draw, first, second, reason)


def build_turn_plan(obs: Any, board: Any, *, phase: Any | None = None, resources: Any | None = None) -> TurnPlan:
    facts = build_turn_facts(obs, board)
    gap = _turn_gap(facts)
    combat = _combat_plan(facts)
    if combat.attack_required and facts.active_ready_mega:
        objective: Objective = "ATTACK"
    elif combat.attack_required:
        objective = "MAKE_ATTACKER"
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
    if not combat.froslass_build_allowed:
        forbidden.append("BUILD_861")
        reasons.append("Mega Froslass attack is projected below two prizes")
    if not acquire.ball_allowed:
        forbidden.append("ULTRA_BALL")
        reasons.append(acquire.ball_reason)
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


def is_basic_attack_forbidden(card_id: int, plan: TurnPlan) -> bool:
    return plan.combat.attack_required and card_id in _BASIC_ATTACK_BAN
