"""Bridge live battle observations to opening_planner route/intent (Step A).

Maps BoardSnapshot + hand/resources to the OpeningGameState surface that
`diagnose_gaps`, `pick_route`, and `classify_miss` expect, then scores
individual legal options against the active route.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cg.api import AreaType, EnergyType, OptionType, SelectContext
from deck_resources import DeckResourceSnapshot, HandContext
from hand_snapshot import BoardSnapshot
from opening_cards import (
    BOSS_ORDERS,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUDUNSPARCE_EX,
    DUNSPARCE_A,
    DUNSPARCE_B,
    ENERGY_IDS,
    FAN_ROTOM,
    FROSLASS,
    HILDA,
    LILLIE,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    POKE_PAD,
    POFFIN,
    PRISM,
    SALVATOR,
    SNORUNT,
    STARYU,
    SUPPORTER_IDS,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
    can_retreat_pokemon,
    supporter_blocked_going_first_t1,
)
from epoch_scheduler import (
    KIND_ABILITY_MEOWTH,
    KIND_ATTACH_MUNK_DARK,
    KIND_ATTACH_RETREAT,
    KIND_ATTACH_WATER_LINE,
    KIND_DEMOTE_306,
    KIND_DEMOTE_BOSS,
    KIND_DEMOTE_POFFIN,
    KIND_DEMOTE_SIDE,
    KIND_EVOLVE_FROSLASS,
    KIND_EVOLVE_MEGA_FROSLASS,
    KIND_EVOLVE_MEGA,
    KIND_PLAY_CRISPIN,
    KIND_PLAY_HILDA,
    KIND_PLAY_LILLIE,
    KIND_PLAY_MEOWTH,
    KIND_PLAY_MUNK,
    KIND_PLAY_PAD,
    KIND_PLAY_POFFIN,
    KIND_PLAY_SNORUNT,
    KIND_PLAY_STARYU,
    KIND_PLAY_SWITCH,
    KIND_PLAY_UB,
    KIND_SEARCH_FROSLASS,
    KIND_SEARCH_FROSLASS_MEGA,
    KIND_SEARCH_MEGA,
    KIND_SEARCH_SNORUNT,
    KIND_SEARCH_STARYU,
    KIND_SEARCH_SWITCH,
    is_side_basic,
    plan_epoch,
    refresh_epoch_memory,
    retreat_attach_energy_ok,
    search_card_tag,
    tags_match_demote,
    tags_match_preferred,
)

_DARK_IDS = frozenset({DARK_BASIC, PRISM})
from opening_planner import diagnose_gaps, pick_route
from phase_fsm import PhaseState

_DOMINATE_OPEN_PATH = 1_150.0
_DOMINATE_MID = 920.0
_WATER_IDS = frozenset({WATER_BASIC, int(EnergyType.WATER), PRISM})


def _si(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


@dataclass
class _LivePokemon:
    card_id: int
    appear_this_turn: bool
    energies: list[int]

    def has_water(self) -> bool:
        return any(_si(e) in _WATER_IDS for e in self.energies)


class BattleOpeningAdapter:
    """Minimal OpeningGameState surface for opening_planner routing."""

    def __init__(
        self,
        obs,
        board: BoardSnapshot,
        hand: HandContext,
        resources: DeckResourceSnapshot,
        my_index: int,
    ) -> None:
        self.obs = obs
        self.board = board
        self.hand_ctx = hand
        self.resources = resources
        self.mi = my_index
        self.current_turn = _si(getattr(obs.current, "turn", None))
        self.supporter_played = hand.supporter_played
        self.energy_attached = hand.energy_attached
        self.fan_call_used = board.my_turn_number >= 2
        self.setup_active_id = board.active_id
        self.setup_archetype = ""

    @property
    def my_turn_number(self) -> int:
        return self.board.my_turn_number

    @property
    def going_first(self) -> bool:
        return self.board.my_index == self.board.first_player

    @property
    def prizes(self) -> list:
        try:
            return list(self.obs.current.players[self.mi].prize or [])
        except Exception:
            return []

    def can_play_supporter(self) -> bool:
        from opening_cards import supporter_blocked_going_first_t1

        if self.supporter_played:
            return False
        if supporter_blocked_going_first_t1(
            going_first=self.going_first, my_turn_number=self.my_turn_number
        ):
            return False
        return True

    @property
    def hand(self) -> list[int]:
        return list(self.hand_ctx.hand_ids)

    @property
    def deck(self) -> list[int]:
        out: list[int] = []
        for cid, n in self.resources.remaining.items():
            out.extend([cid] * max(0, n))
        return out

    @property
    def active(self) -> _LivePokemon | None:
        return self._wrap_active()

    @property
    def bench(self) -> list[_LivePokemon]:
        out: list[_LivePokemon] = []
        try:
            for p in self.obs.current.players[self.mi].bench or []:
                if p:
                    out.append(self._wrap(p))
        except Exception:
            pass
        return out

    def _wrap(self, p) -> _LivePokemon:
        return _LivePokemon(
            card_id=_si(getattr(p, "id", None)),
            appear_this_turn=bool(getattr(p, "appearThisTurn", False)),
            energies=[_si(e) for e in (getattr(p, "energies", None) or [])],
        )

    def _wrap_active(self) -> _LivePokemon | None:
        try:
            active = (self.obs.current.players[self.mi].active or [None])[0]
            if active:
                return self._wrap(active)
        except Exception:
            pass
        return None

    def opening_complete(self) -> bool:
        return self.board.active_is_mega_starmie and self.board.active_has_water

    def staryu_on_field(self) -> bool:
        return self.board.staryu_on_field

    def all_staryu(self) -> list[tuple[str, int, _LivePokemon]]:
        out: list[tuple[str, int, _LivePokemon]] = []
        if self.active and self.active.card_id == STARYU:
            out.append(("active", 0, self.active))
        for i, p in enumerate(self.bench):
            if p.card_id == STARYU:
                out.append(("bench", i, p))
        return out

    def bench_open(self) -> int:
        return self.board.bench_open

    def _can_evolve_now(self, p: _LivePokemon) -> bool:
        if p.appear_this_turn and self.my_turn_number < 2:
            return False
        return not p.appear_this_turn or self.my_turn_number >= 2


def compute_opening_route(
    obs,
    board: BoardSnapshot,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    my_index: int,
) -> str:
    adapter = BattleOpeningAdapter(obs, board, hand, resources, my_index)
    gaps = diagnose_gaps(adapter)
    return pick_route(adapter, gaps)


def _hand_card_id(obs, option, my_index: int) -> int:
    try:
        if option.type != OptionType.PLAY:
            return 0
        hand = obs.current.players[my_index].hand or []
        idx = _si(getattr(option, "index", None), -1)
        if 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None))
    except Exception:
        pass
    return 0


def _ability_source_id(obs, option, my_index: int) -> int:
    try:
        if option.type != OptionType.ABILITY:
            return 0
        area = option.area
        idx = _si(getattr(option, "index", None), -1)
        p = obs.current.players[my_index]
        if area == AreaType.BENCH:
            bench = p.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                return _si(getattr(bench[idx], "id", None))
        if area == AreaType.ACTIVE:
            active = (p.active or [None])[0]
            if active:
                return _si(getattr(active, "id", None))
    except Exception:
        pass
    return 0


def _attach_target_pokemon(obs, option, my_index: int):
    try:
        area = option.inPlayArea
        idx = _si(getattr(option, "inPlayIndex", None), _si(getattr(option, "index", None), -1))
        p = obs.current.players[my_index]
        if area == AreaType.ACTIVE:
            return (p.active or [])[idx]
        if area == AreaType.BENCH:
            return (p.bench or [])[idx]
    except Exception:
        pass
    return None


def _attach_energy_id(obs, option, my_index: int) -> int:
    try:
        hand = obs.current.players[my_index].hand or []
        idx = _si(getattr(option, "handIndex", None), _si(getattr(option, "index", None), -1))
        if 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None))
    except Exception:
        pass
    return 0


def _evolve_to_mega_starmie(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == MEGA_STARMIE
        if option.area == AreaType.BENCH:
            bench = me.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                if _si(getattr(bench[idx], "id", None)) != STARYU:
                    return False
                return any(_si(getattr(c, "id", None)) == MEGA_STARMIE for c in hand if c)
        if option.area == AreaType.ACTIVE:
            active = (me.active or [None])[0]
            if active and _si(getattr(active, "id", None)) == STARYU:
                return any(_si(getattr(c, "id", None)) == MEGA_STARMIE for c in hand if c)
    except Exception:
        pass
    return False


def _evolve_to_froslass_104(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == FROSLASS
        if option.area in (AreaType.BENCH, AreaType.ACTIVE):
            return any(_si(getattr(c, "id", None)) == FROSLASS for c in hand if c)
    except Exception:
        pass
    return False


def _evolve_to_mega_froslass(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == MEGA_FROSLASS
    except Exception:
        pass
    return False


def _card_option_id(obs, option, my_index: int) -> int:
    try:
        if option.type != OptionType.CARD:
            return 0
        deck = getattr(obs.select, "deck", None)
        idx = _si(getattr(option, "index", None), -1)
        if deck and 0 <= idx < len(deck) and deck[idx]:
            return _si(getattr(deck[idx], "id", None))
    except Exception:
        pass
    return 0


def _route_play_card(route: str) -> int | None:
    """Map planner route → preferred PLAY card id.

    R5-T1 / R4-REC are attach-water routes (energy already in hand or via
    Hilda/Crispin) — they must NOT map to Poké Pad (E-PAD-1 / historical bug).
    Pad PLAY is only R3-T1 (T1 Staryu search) and R5-REC (recovery Pad search).
    """
    mapping = {
        "R2-T1": POFFIN,
        "R3-T1": POKE_PAD,
        "R3b-T1": ULTRA_BALL,
        "R5-REC": POKE_PAD,
        "R6-T1": HILDA,
        "R7-T1": HILDA,
        "R7c-T1": CRISPIN,
        "R8-T1": SALVATOR,
        "R-Meowth-T1": MEOWTH_EX,
        "R3-REC": ULTRA_BALL,
        "R3b-REC": HILDA,
        "R4b-REC": HILDA,
        "R4c-REC": CRISPIN,
    }
    return mapping.get(route)


def _line_has_water(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        for p in list(me.active or []) + list(me.bench or []):
            if not p:
                continue
            cid = _si(getattr(p, "id", None))
            if cid not in (STARYU, MEGA_STARMIE):
                continue
            energies = [_si(e) for e in (getattr(p, "energies", None) or [])]
            if any(e in _WATER_IDS for e in energies):
                return True
    except Exception:
        pass
    return False


def _active_can_retreat(obs, my_index: int) -> bool:
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        if not active:
            return True
        cid = _si(getattr(active, "id", None))
        energies = [_si(e) for e in (getattr(active, "energies", None) or [])]
        return can_retreat_pokemon(cid, energies)
    except Exception:
        return True


def compute_epoch_plan(
    obs,
    board: BoardSnapshot,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    my_index: int,
    memory: dict | None = None,
    *,
    refresh: bool = True,
):
    """Shared epoch plan for Layer1 + Hybrid gates."""
    active_can_retreat = _active_can_retreat(obs, my_index)
    line_has_water = _line_has_water(obs, my_index)
    opening_done = bool(
        board.active_is_mega_starmie and board.active_has_water
    )
    if memory is not None and refresh:
        refresh_epoch_memory(
            memory,
            board,
            hand,
            active_can_retreat=active_can_retreat,
            line_has_water=line_has_water,
            opening_complete_flag=opening_done,
        )
    return plan_epoch(
        board,
        hand,
        resources,
        opening_complete_flag=opening_done,
        active_can_retreat=active_can_retreat,
        line_has_water=line_has_water,
        memory=memory,
    )


def _option_epoch_tags(obs, option, my_index: int, board: BoardSnapshot) -> set[str]:
    tags: set[str] = set()
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        if cid == STARYU:
            tags.add(KIND_PLAY_STARYU)
        elif cid == SNORUNT:
            tags.add(KIND_PLAY_SNORUNT)
        elif cid == MUNKIDORI:
            tags.add(KIND_PLAY_MUNK)
        elif cid == POFFIN:
            tags.add(KIND_PLAY_POFFIN)
            tags.add(KIND_DEMOTE_POFFIN)
        elif cid == POKE_PAD:
            tags.add(KIND_PLAY_PAD)
        elif cid == ULTRA_BALL:
            tags.add(KIND_PLAY_UB)
        elif cid == HILDA:
            tags.add(KIND_PLAY_HILDA)
        elif cid == CRISPIN:
            tags.add(KIND_PLAY_CRISPIN)
        elif cid == MEOWTH_EX:
            tags.add(KIND_PLAY_MEOWTH)
        elif cid == SWITCH:
            tags.add(KIND_PLAY_SWITCH)
        elif cid == LILLIE:
            tags.add(KIND_PLAY_LILLIE)
        elif cid == BOSS_ORDERS:
            tags.add(KIND_DEMOTE_BOSS)
        elif cid == DUDUNSPARCE_EX:
            tags.add(KIND_DEMOTE_306)
        if is_side_basic(cid):
            tags.add(KIND_DEMOTE_SIDE)
        return tags

    if option.type == OptionType.EVOLVE:
        if _evolve_to_mega_starmie(obs, option, my_index):
            tags.add(KIND_EVOLVE_MEGA)
            return tags
        if _evolve_to_mega_froslass(obs, option, my_index):
            tags.add(KIND_EVOLVE_MEGA_FROSLASS)
            return tags
        if _evolve_to_froslass_104(obs, option, my_index):
            tags.add(KIND_EVOLVE_FROSLASS)
            return tags
        return tags

    if option.type == OptionType.ATTACH:
        target = _attach_target_pokemon(obs, option, my_index)
        eid = _attach_energy_id(obs, option, my_index)
        if target and eid in ENERGY_IDS:
            tid = _si(getattr(target, "id", None))
            energies = [e for e in (getattr(target, "energies", None) or []) if e is not None]
            # Starmie line: Water Basic only (not Prism/Dark).
            if tid in (STARYU, MEGA_STARMIE) and eid == WATER_BASIC and len(energies) == 0:
                tags.add(KIND_ATTACH_WATER_LINE)
            if tid == MUNKIDORI and eid in _DARK_IDS and not any(
                _si(e) in _DARK_IDS for e in energies
            ):
                tags.add(KIND_ATTACH_MUNK_DARK)
            active = (obs.current.players[my_index].active or [None])[0]
            active_id = _si(getattr(active, "id", None)) if active else 0
            if (
                tid == active_id
                and tid not in (STARYU, MEGA_STARMIE)
                and retreat_attach_energy_ok(eid)
                and len(energies) == 0
            ):
                tags.add(KIND_ATTACH_RETREAT)
        return tags

    if option.type == OptionType.ABILITY:
        if _ability_source_id(obs, option, my_index) == MEOWTH_EX:
            tags.add(KIND_ABILITY_MEOWTH)
        return tags

    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (
            int(SelectContext.TO_HAND),
            int(SelectContext.TO_BENCH),
            int(SelectContext.TO_FIELD),
        ):
            cid = _card_option_id(obs, option, my_index)
            tag = search_card_tag(cid)
            if tag:
                tags.add(tag)
            if cid == DUDUNSPARCE_EX:
                tags.add(KIND_DEMOTE_306)
        return tags

    return tags


def _score_epoch2_option(
    obs,
    option,
    *,
    board: BoardSnapshot,
    hand: HandContext,
    plan,
    my_index: int,
) -> float:
    """SF1→SF2→SF3 preferred/demote while AGGRESSION builds Froslass engine."""
    if plan.priority_gap == "SF_DONE":
        return 0.0

    tags = _option_epoch_tags(obs, option, my_index, board)

    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        if cid == BOSS_ORDERS:
            return -_DOMINATE_OPEN_PATH

    if tags_match_demote(tags, plan.demote_kinds):
        if not tags_match_preferred(tags, plan.preferred_kinds):
            return -_DOMINATE_OPEN_PATH

    if tags_match_preferred(tags, plan.preferred_kinds):
        if KIND_EVOLVE_MEGA_FROSLASS in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_EVOLVE_FROSLASS in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_SNORUNT in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_MUNK in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH
        if KIND_ATTACH_MUNK_DARK in tags and not hand.energy_attached:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_POFFIN in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_PAD in tags or KIND_PLAY_UB in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_HILDA in tags or KIND_PLAY_CRISPIN in tags:
            return _DOMINATE_OPEN_PATH
        if (
            KIND_SEARCH_SNORUNT in tags
            or KIND_SEARCH_FROSLASS in tags
            or KIND_SEARCH_FROSLASS_MEGA in tags
        ):
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_LILLIE in tags:
            return _DOMINATE_OPEN_PATH - 30.0
        return _DOMINATE_OPEN_PATH

    # Conflict demote: SF1 side basics (non-Snorunt) steal bench slots.
    # Exception: Dunsparce under role quota — keep the draw-engine bench plan alive.
    if option.type == OptionType.PLAY and plan.priority_gap == "SF1":
        cid = _hand_card_id(obs, option, my_index)
        if is_side_basic(cid) and cid != SNORUNT:
            if cid in (DUNSPARCE_A, DUNSPARCE_B):
                try:
                    from opening_bench import dunsparce_quota_open
                    me = obs.current.players[my_index]
                    active = (me.active or [None])[0]
                    active_id = int(getattr(active, "id", 0) or 0) if active else None
                    bench_ids = [
                        int(getattr(p, "id", 0) or 0)
                        for p in (me.bench or [])
                        if p and getattr(p, "id", None) is not None
                    ]
                    if dunsparce_quota_open(active_id, bench_ids):
                        return _DOMINATE_MID  # below Snorunt PATH, above hard demote
                except Exception:
                    return _DOMINATE_MID
            return -_DOMINATE_OPEN_PATH
        if cid == POFFIN and board.bench_open <= 0:
            return -_DOMINATE_OPEN_PATH

    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (
            int(SelectContext.TO_HAND),
            int(SelectContext.TO_BENCH),
            int(SelectContext.TO_FIELD),
        ):
            cid = _card_option_id(obs, option, my_index)
            if cid == DUDUNSPARCE_EX:
                return -_DOMINATE_OPEN_PATH
            if plan.priority_gap == "SF1" and cid == SNORUNT:
                return _DOMINATE_OPEN_PATH
            if plan.priority_gap == "SF2" and cid == FROSLASS:
                return _DOMINATE_OPEN_PATH
            if plan.priority_gap == "SF3" and cid == MUNKIDORI:
                return _DOMINATE_OPEN_PATH

    return 0.0


def score_opening_option(
    obs,
    option,
    *,
    board: BoardSnapshot,
    hand: HandContext,
    resources: DeckResourceSnapshot,
    phase: PhaseState,
    my_index: int,
    route: str | None = None,
    memory: dict | None = None,
) -> float:
    """Layer-1 path score: epoch1 OPENING (G*) / epoch2 AGGRESSION+HARVEST (SF*)."""
    if board.my_turn_number < 1:
        return 0.0
    if phase.primary not in ("OPENING", "AGGRESSION", "HARVEST"):
        return 0.0

    adapter = BattleOpeningAdapter(obs, board, hand, resources, my_index)
    if route is None and phase.primary == "OPENING":
        gaps = diagnose_gaps(adapter)
        route = pick_route(adapter, gaps)
    plan = compute_epoch_plan(
        obs, board, hand, resources, my_index, memory=memory, refresh=False,
    )

    # Fan Call — My-T1 whenever Fan is on field (OPENING only)
    if phase.primary == "OPENING":
        if option.type == OptionType.ABILITY and board.my_turn_number <= 1 and board.fan_rotom_on_field:
            if _ability_source_id(obs, option, my_index) == FAN_ROTOM:
                return _DOMINATE_OPEN_PATH
        if option.type == OptionType.ABILITY and board.my_turn_number >= 2:
            if _ability_source_id(obs, option, my_index) == FAN_ROTOM:
                return -_DOMINATE_OPEN_PATH

    # Epoch 2: Froslass engine gaps (or SF_DONE → defer to HRs).
    # SF in HARVEST only after usable Mega — early HARVEST (Snorunt@T3, never opened)
    # must still use Epoch-1 OPENING path to finish Mega.
    if plan.epoch_id >= 2:
        if phase.primary == "AGGRESSION" or (
            phase.primary == "HARVEST" and phase.opening_complete
        ):
            return _score_epoch2_option(
                obs, option, board=board, hand=hand, plan=plan, my_index=my_index,
            )
        # Still OPENING but board already usable Starmie — don't dominate fetches.
        if option.type == OptionType.ATTACK and adapter.opening_complete():
            return _DOMINATE_OPEN_PATH - 175.0
        if phase.primary == "OPENING":
            pass  # fall through to Epoch-1 path below
        elif phase.primary == "HARVEST" and not phase.opening_complete:
            pass  # fall through — finish Mega first
        else:
            return 0.0

    # Epoch-1 OPENING path — also when FSM jumped to HARVEST early without Mega.
    if phase.primary != "OPENING" and not (
        phase.primary == "HARVEST" and not phase.opening_complete
    ):
        return 0.0

    # Epoch 1 complete gap (rare while still OPENING) → soft attack nudge.
    if plan.priority_gap == "DONE":
        if option.type == OptionType.ATTACK and adapter.opening_complete():
            return _DOMINATE_OPEN_PATH - 175.0
        return 0.0

    tags = _option_epoch_tags(obs, option, my_index, board)

    # Absolute bans
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        going_first = board.my_index == board.first_player
        if cid in SUPPORTER_IDS and supporter_blocked_going_first_t1(
            going_first=going_first, my_turn_number=board.my_turn_number
        ):
            return -_DOMINATE_OPEN_PATH
        if cid == SALVATOR and MEGA_STARMIE in hand.hand_ids:
            return -_DOMINATE_OPEN_PATH
        if cid == BOSS_ORDERS:
            return -_DOMINATE_OPEN_PATH

    # T2–T3 legal Evolve → Mega always dominates (before any demote).
    if (
        2 <= board.my_turn_number <= 3
        and option.type == OptionType.EVOLVE
        and _evolve_to_mega_starmie(obs, option, my_index)
    ):
        return _DOMINATE_OPEN_PATH

    if tags_match_demote(tags, plan.demote_kinds):
        # Prefer match wins over demote when both apply (e.g. SEARCH tags only).
        if not tags_match_preferred(tags, plan.preferred_kinds):
            return -_DOMINATE_OPEN_PATH

    if tags_match_preferred(tags, plan.preferred_kinds):
        # Soft rank within preferred: Mega search > Froslass > 66 already in pilot search.
        if KIND_SEARCH_MEGA in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_EVOLVE_MEGA in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_STARYU in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH
        if KIND_ATTACH_WATER_LINE in tags and not hand.energy_attached:
            return _DOMINATE_OPEN_PATH
        if KIND_ATTACH_RETREAT in tags and not hand.energy_attached:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_SWITCH in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_SEARCH_SWITCH in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_POFFIN in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_PAD in tags or KIND_PLAY_UB in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_HILDA in tags or KIND_PLAY_CRISPIN in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_PLAY_MEOWTH in tags or KIND_ABILITY_MEOWTH in tags:
            return _DOMINATE_OPEN_PATH
        if KIND_SEARCH_STARYU in tags:
            return _DOMINATE_OPEN_PATH
        # Dual-basic: Snorunt below water/Mega path, above filler.
        if KIND_PLAY_SNORUNT in tags and board.bench_open > 0:
            return _DOMINATE_OPEN_PATH - 40.0
        if KIND_SEARCH_SNORUNT in tags:
            return _DOMINATE_OPEN_PATH - 50.0
        if KIND_PLAY_LILLIE in tags:
            from supporter_planner import lillie_should_play

            if lillie_should_play(board, phase, hand, resources):
                return _DOMINATE_OPEN_PATH - 30.0
            return -_DOMINATE_OPEN_PATH
        return _DOMINATE_OPEN_PATH

    # Conflict-only demote (no blanket −DOMINATE on all off-preferred path plays).
    # G1: side basics steal bench from Staryu/fetch (Snorunt also waits until Staryu lands).
    # G2/G3/EVOLVE/RETREAT: Poffin cannot progress Mega path; other side basics demoted
    # except Snorunt (dual-basic optionality once Staryu/Mega is online).
    # Dunsparce under role quota is allowed (draw-engine bench plan).
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        gap = plan.priority_gap

        def _dun_quota_ok() -> bool:
            if cid not in (DUNSPARCE_A, DUNSPARCE_B):
                return False
            try:
                from opening_bench import dunsparce_quota_open
                me = obs.current.players[my_index]
                active = (me.active or [None])[0]
                active_id = int(getattr(active, "id", 0) or 0) if active else None
                bench_ids = [
                    int(getattr(p, "id", 0) or 0)
                    for p in (me.bench or [])
                    if p and getattr(p, "id", None) is not None
                ]
                return dunsparce_quota_open(active_id, bench_ids)
            except Exception:
                return True

        if gap == "G1" and is_side_basic(cid):
            if _dun_quota_ok():
                return _DOMINATE_MID
            return -_DOMINATE_OPEN_PATH
        if gap in ("G2", "G3", "EVOLVE", "RETREAT") and cid == POFFIN:
            return -_DOMINATE_OPEN_PATH
        if gap in ("G2", "EVOLVE", "RETREAT") and is_side_basic(cid):
            if cid == SNORUNT and (
                board.staryu_on_field or board.mega_starmie_on_field
            ):
                pass
            elif _dun_quota_ok():
                return _DOMINATE_MID
            else:
                return -_DOMINATE_OPEN_PATH

    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.TO_HAND), int(SelectContext.TO_BENCH)):
            cid = _card_option_id(obs, option, my_index)
            if cid == DUDUNSPARCE_EX:
                return -_DOMINATE_OPEN_PATH
            if cid == MEGA_STARMIE:
                return _DOMINATE_OPEN_PATH
            if cid == MEGA_FROSLASS:
                # Opening: never prioritize 861 over Mega Starmie / dual-basic Snorunt.
                return _DOMINATE_OPEN_PATH - 80.0
            if cid == DUDUNSPARCE:
                return _DOMINATE_OPEN_PATH - 90.0
            if plan.priority_gap == "G1" and cid == STARYU:
                return _DOMINATE_OPEN_PATH
            if (
                plan.priority_gap != "G1"
                and cid == SNORUNT
                and (board.staryu_on_field or board.mega_starmie_on_field)
                and not board.snorunt_line_on_bench
            ):
                return _DOMINATE_OPEN_PATH - 45.0
            if plan.priority_gap == "G2" and cid in _WATER_IDS:
                return _DOMINATE_OPEN_PATH - 10.0

    # Legacy route fallback (soft) when epoch tags missed a mapped supporter.
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        want = _route_play_card(route or "")
        if want and cid == want and plan.preferred_kinds:
            # Only if route card is still on epoch preferred set.
            route_tag_ok = (
                (cid == HILDA and KIND_PLAY_HILDA in plan.preferred_kinds)
                or (cid == CRISPIN and KIND_PLAY_CRISPIN in plan.preferred_kinds)
                or (cid == POFFIN and KIND_PLAY_POFFIN in plan.preferred_kinds)
                or (cid == POKE_PAD and KIND_PLAY_PAD in plan.preferred_kinds)
                or (cid == ULTRA_BALL and KIND_PLAY_UB in plan.preferred_kinds)
                or (cid == MEOWTH_EX and KIND_PLAY_MEOWTH in plan.preferred_kinds)
            )
            if route_tag_ok:
                return _DOMINATE_OPEN_PATH

    if option.type == OptionType.ATTACK and adapter.opening_complete():
        return _DOMINATE_OPEN_PATH - 175.0

    return 0.0
