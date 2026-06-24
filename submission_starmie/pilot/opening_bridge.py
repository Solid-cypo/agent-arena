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
    CRISPIN,
    DARK_BASIC,
    FAN_ROTOM,
    HILDA,
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
    ENERGY_IDS,
)
from opening_planner import classify_miss, diagnose_gaps, pick_route
from phase_fsm import PhaseState

_DOMINATE_OPEN_PATH = 1_150.0
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
    mapping = {
        "R2-T1": POFFIN,
        "R3-T1": POKE_PAD,
        "R3b-T1": ULTRA_BALL,
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
    if route in mapping:
        return mapping[route]
    if route.startswith("R5") or route == "R4-REC":
        return POKE_PAD
    return None


# Per-step memo: the same obs object is passed to every option in a decision, so
# the board-derived adapter/gaps/miss/route are computed once and reused.
_OPEN_CTX: dict[str, object] = {"obs": None}


def _opening_context(obs, board, hand, resources, my_index):
    if _OPEN_CTX.get("obs") is not obs:
        adapter = BattleOpeningAdapter(obs, board, hand, resources, my_index)
        gaps = diagnose_gaps(adapter)
        _OPEN_CTX.update(
            obs=obs, adapter=adapter, gaps=gaps,
            miss=classify_miss(adapter), route=pick_route(adapter, gaps),
        )
    return (_OPEN_CTX["adapter"], _OPEN_CTX["gaps"],
            _OPEN_CTX["miss"], _OPEN_CTX["route"])


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
) -> float:
    """Layer-1 OPENING path score from opening_planner route (HR-O Main)."""
    if phase.primary != "OPENING" or board.my_turn_number < 1:
        return 0.0

    # score_opening_option runs once PER LEGAL OPTION, but the adapter / gaps /
    # miss / route depend only on the board, not the option. Building the adapter
    # rebuilds _LivePokemon objects from obs on every property access, so doing it
    # per option (10-20x/step) is the main OPENING-path latency cost. Memoise the
    # board-derived context for the lifetime of this obs (same obs object is
    # passed to every option in a step).
    adapter, gaps, miss, cached_route = _opening_context(
        obs, board, hand, resources, my_index)
    if route is None:
        route = cached_route

    # Fan Call — R4-T1 / post-Poffin
    if option.type == OptionType.ABILITY and route == "R4-T1":
        if _ability_source_id(obs, option, my_index) == FAN_ROTOM:
            return _DOMINATE_OPEN_PATH

    # Route-mapped supporter / item PLAY
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, my_index)
        want = _route_play_card(route)
        if want and cid == want:
            return _DOMINATE_OPEN_PATH
        if cid == STARYU and gaps.g1 and board.bench_open > 0:
            if route.endswith("-REC") or route.endswith("-T1") or route.startswith("R-IDLE"):
                return _DOMINATE_OPEN_PATH - 20.0
        if cid == SWITCH and (gaps.g5 or miss == "F-F"):
            if route.endswith("-REC") or miss == "F-F":
                return _DOMINATE_OPEN_PATH

    # Deck search picks (Pad / Hilda / Ball)
    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx == int(SelectContext.TO_HAND):
            cid = _card_option_id(obs, option, my_index)
            if route in ("R3-T1", "R5-REC", "R-IDLE-T1", "R-IDLE-REC") and cid == STARYU:
                return _DOMINATE_OPEN_PATH
            if route in ("R6-T1", "R3b-REC", "R3-REC") and cid in (MEGA_STARMIE, STARYU):
                return _DOMINATE_OPEN_PATH
            if gaps.g2 and cid in _WATER_IDS:
                return _DOMINATE_OPEN_PATH - 10.0

    # Evolve Staryu → Mega Starmie (finish sequences)
    if option.type == OptionType.EVOLVE and _evolve_to_mega_starmie(obs, option, my_index):
        if (
            route.endswith("-REC")
            or miss in ("F-A", "F-B", "F-D", "F-E")
            or route == "R8-T1"
        ):
            return _DOMINATE_OPEN_PATH

    # Attach water — G2 gap
    if option.type == OptionType.ATTACH and gaps.g2 and not hand.energy_attached:
        target = _attach_target_pokemon(obs, option, my_index)
        eid = _attach_energy_id(obs, option, my_index)
        if target and eid in ENERGY_IDS:
            tid = _si(getattr(target, "id", None))
            if tid in (STARYU, MEGA_STARMIE):
                energies = [_si(e) for e in (getattr(target, "energies", None) or [])]
                if not any(e in _WATER_IDS for e in energies):
                    return _DOMINATE_OPEN_PATH - 10.0

    # Jetting when goal reached mid-OPENING
    if option.type == OptionType.ATTACK and adapter.opening_complete():
        return _DOMINATE_OPEN_PATH - 175.0

    return 0.0
