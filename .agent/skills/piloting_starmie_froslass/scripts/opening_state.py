"""Mutable opening simulation state (ordered deck, no shuffle)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from opening_cards import (
    BASIC_IDS,
    CRISPIN,
    ENERGY_IDS,
    EVOLVES_TO,
    FAN_CALL_IDS,
    FAN_CALL_PRIORITY,
    HILDA,
    HILDA_EVOLUTION_PRIORITY,
    ITEM_IDS,
    MEGA_STARMIE,
    MEOWTH_EX,
    MEOWTH_OPENING_SUPPORTER_PRIORITY,
    POFFIN_OPENING_PRIORITY,
    POFFIN_IDS,
    PRISM,
    SALVATOR,
    STARYU,
    SUPPORTER_IDS,
    DARK_BASIC,
    WATER_BASIC,
    WATER_ENERGY_IDS,
    name,
    can_retreat_pokemon,
    is_pad_legal_target,
    retreat_cost_for,
)

ActionKind = Literal[
    "SETUP_ACTIVE", "SETUP_BENCH", "DRAW", "PLAY_POKEMON", "PLAY_TRAINER",
    "ATTACH", "ABILITY_FAN_CALL", "ABILITY_LAST_DITCH", "EVOLVE", "SWITCH",
    "RETREAT", "DISCARD", "ATTACK", "NOTE",
]


@dataclass
class Pokemon:
    card_id: int
    entered_turn: int
    energies: list[int] = field(default_factory=list)

    @property
    def can_evolve(self) -> bool:
        return True  # set by state relative to current_turn

    def has_water(self) -> bool:
        return any(e in WATER_ENERGY_IDS for e in self.energies)


@dataclass
class Action:
    kind: ActionKind
    detail: str
    card_id: int | None = None


@dataclass
class OpeningGameState:
    deck_order: list[int]
    prizes: list[int] = field(default_factory=list)
    hand: list[int] = field(default_factory=list)
    deck: list[int] = field(default_factory=list)
    discard: list[int] = field(default_factory=list)
    active: Pokemon | None = None
    bench: list[Pokemon] = field(default_factory=list)
    current_turn: int = 0
    my_turn_number: int = 0
    going_first: bool = True
    supporter_played: bool = False
    energy_attached: bool = False
    fan_call_used: bool = False
    setup_archetype: str = ""
    setup_active_id: int = 0
    log: list[Action] = field(default_factory=list)

    @classmethod
    def from_ordered_deck(cls, deck: list[int], *, going_first: bool = True) -> OpeningGameState:
        if len(deck) != 60:
            raise ValueError(f"deck must be 60 cards, got {len(deck)}")
        st = cls(deck_order=list(deck), going_first=going_first)
        st.prizes = deck[0:6]
        st.hand = list(deck[6:13])
        st.deck = list(deck[13:])
        return st

    def hand_basics(self) -> list[int]:
        return [c for c in self.hand if c in BASIC_IDS]

    def bench_open(self) -> int:
        return max(0, 5 - len(self.bench))

    def all_staryu(self) -> list[tuple[str, int, Pokemon]]:
        out: list[tuple[str, int, Pokemon]] = []
        if self.active and self.active.card_id == STARYU:
            out.append(("active", 0, self.active))
        for i, p in enumerate(self.bench):
            if p.card_id == STARYU:
                out.append(("bench", i, p))
        return out

    def staryu_on_field(self) -> bool:
        return bool(self.all_staryu())

    def _can_evolve_now(self, p: Pokemon) -> bool:
        if p.entered_turn == 0 and self.my_turn_number < 2:
            return False
        return p.entered_turn < self.current_turn

    def opening_complete(self) -> bool:
        return (
            self.active is not None
            and self.active.card_id == MEGA_STARMIE
            and self.active.has_water()
        )

    def _log(self, kind: ActionKind, detail: str, card_id: int | None = None) -> None:
        self.log.append(Action(kind, detail, card_id))

    def setup_play_active(self, card_id: int) -> None:
        self.hand.remove(card_id)
        self.active = Pokemon(card_id, entered_turn=0)
        self.setup_active_id = card_id
        self._log("SETUP_ACTIVE", f"Active ← {name(card_id)}", card_id)

    def setup_play_bench(self, card_id: int) -> None:
        self.hand.remove(card_id)
        self.bench.append(Pokemon(card_id, entered_turn=0))
        self._log("SETUP_BENCH", f"Bench ← {name(card_id)}", card_id)

    def begin_turn(self, turn: int, my_turn_number: int) -> None:
        self.current_turn = turn
        self.my_turn_number = my_turn_number
        self.supporter_played = False
        self.energy_attached = False
        if my_turn_number > 1 or not self.going_first:
            if self.deck:
                drawn = self.deck.pop(0)
                self.hand.append(drawn)
                self._log("DRAW", f"Draw {name(drawn)}", drawn)

    def play_pokemon_to_bench(self, card_id: int) -> None:
        self.hand.remove(card_id)
        self.bench.append(Pokemon(card_id, self.current_turn))
        self._log("PLAY_POKEMON", f"Bench ← {name(card_id)}", card_id)

    def play_trainer(self, card_id: int, detail: str) -> None:
        self.hand.remove(card_id)
        self.discard.append(card_id)
        self.supporter_played = card_id in SUPPORTER_IDS
        self._log("PLAY_TRAINER", detail, card_id)

    def attach_energy_from_hand(self, target: Pokemon, energy_id: int) -> bool:
        if energy_id not in self.hand:
            return False
        self.hand.remove(energy_id)
        target.energies.append(energy_id)
        self.energy_attached = True
        self._log(
            "ATTACH",
            f"{name(energy_id)} → {name(target.card_id)} on "
            f"{'active' if target is self.active else 'bench'}",
            energy_id,
        )
        return True

    def attach_water_to(self, target: Pokemon) -> None:
        """E-ATT-1: real Water before Prism for Jetting Blow."""
        if WATER_BASIC in self.hand:
            self.attach_energy_from_hand(target, WATER_BASIC)
            return
        if PRISM in self.hand:
            self.attach_energy_from_hand(target, PRISM)
            return
        self._log("NOTE", "ATTACH skipped: no water in hand")

    def search_deck_to_hand(self, card_ids: list[int], reason: str) -> None:
        for cid in card_ids:
            if cid in self.deck:
                self.deck.remove(cid)
                self.hand.append(cid)
                self._log("PLAY_TRAINER", f"{reason}: deck → hand {name(cid)}", cid)

    def fan_call(self) -> None:
        picks: list[int] = []
        for want in FAN_CALL_PRIORITY:
            if want not in FAN_CALL_IDS:
                continue
            if want in self.deck and want not in picks:
                picks.append(want)
            if len(picks) >= 3:
                break
        for cid in picks:
            self.deck.remove(cid)
            self.hand.append(cid)
        self.fan_call_used = True
        self._log("ABILITY_FAN_CALL", f"Fan Call → {[name(c) for c in picks]}")

    def meowth_last_ditch_catch(
        self,
        priorities: tuple[int, ...] = MEOWTH_OPENING_SUPPORTER_PRIORITY,
    ) -> int | None:
        for cid in priorities:
            if cid in self.deck and cid in SUPPORTER_IDS:
                self.deck.remove(cid)
                self.hand.append(cid)
                self._log("ABILITY_LAST_DITCH", f"Last-Ditch Catch → {name(cid)}", MEOWTH_EX)
                return cid
        self._log("NOTE", "Last-Ditch Catch: no Supporter found in deck")
        return None

    def play_meowth_to_bench_with_catch(self) -> int | None:
        if MEOWTH_EX not in self.hand or self.bench_open() <= 0:
            return None
        self.play_pokemon_to_bench(MEOWTH_EX)
        return self.meowth_last_ditch_catch()

    def poffin_to_bench(self, *, prefer_staryu: bool = True) -> bool:
        slots = min(2, self.bench_open())
        if slots <= 0:
            return False
        picks: list[int] = []
        priorities = POFFIN_OPENING_PRIORITY if prefer_staryu else tuple(POFFIN_IDS)
        for want in priorities:
            if want not in POFFIN_IDS:
                continue
            if want == STARYU and not prefer_staryu:
                continue
            if want in picks:
                continue
            if want in self.deck:
                picks.append(want)
            if len(picks) >= slots:
                break
        for cid in picks:
            self.deck.remove(cid)
            self.bench.append(Pokemon(cid, self.current_turn))
        return bool(picks)

    def hilda_search(self, *, need_evolution: bool = True, need_energy: bool = True) -> None:
        picks: list[int] = []
        if need_evolution:
            for cid in HILDA_EVOLUTION_PRIORITY:
                if cid in self.deck:
                    picks.append(cid)
                    break
        if need_energy:
            for e in (WATER_BASIC, PRISM):
                if e in self.deck and e not in picks:
                    picks.append(e)
                    break
        for cid in picks[:2]:
            self.deck.remove(cid)
            self.hand.append(cid)
        self._log("PLAY_TRAINER", f"Hilda → {[name(c) for c in picks[:2]]}", HILDA)

    def crispin_search(self, attach_target: Pokemon | None = None) -> None:
        """Crispin: 2 different Basic Energy — 1 to hand, 1 direct attach (E-CRIS-1)."""
        from opening_cards import CRISPIN_BASIC_ENERGY

        in_deck = [e for e in CRISPIN_BASIC_ENERGY if e in self.deck]
        if not in_deck:
            self._log("NOTE", "Crispin: no Basic Energy in deck")
            return

        attach_id: int | None = None
        to_hand_id = in_deck[0]
        water_ok = WATER_BASIC in in_deck
        dark_ok = DARK_BASIC in in_deck

        if attach_target is not None and len(in_deck) >= 2:
            needs_water = attach_target.card_id in (STARYU, MEGA_STARMIE) and not attach_target.has_water()
            if needs_water and water_ok:
                attach_id = WATER_BASIC
                to_hand_id = DARK_BASIC if dark_ok else WATER_BASIC
            elif dark_ok:
                attach_id = DARK_BASIC
                to_hand_id = WATER_BASIC if water_ok else DARK_BASIC
            else:
                attach_id = in_deck[1]
                to_hand_id = in_deck[0]
        elif len(in_deck) >= 2:
            to_hand_id = in_deck[0]
            attach_id = in_deck[1]

        self.deck.remove(to_hand_id)
        self.hand.append(to_hand_id)
        attached = None
        if (
            attach_id is not None
            and attach_target is not None
            and attach_id != to_hand_id
            and attach_id in self.deck
        ):
            self.deck.remove(attach_id)
            attach_target.energies.append(attach_id)
            self.energy_attached = True
            attached = attach_id
            self._log(
                "ATTACH",
                f"Crispin attach {name(attach_id)} → {name(attach_target.card_id)} on "
                f"{'active' if attach_target is self.active else 'bench'}",
                attach_id,
            )
        elif attach_id is not None and attach_target is None and attach_id in self.deck and attach_id != to_hand_id:
            self.deck.remove(attach_id)
            self.hand.append(attach_id)
        detail = [name(to_hand_id)]
        if attached is not None:
            detail.append(f"attach {name(attached)}")
        elif attach_id is not None and attach_target is None and attach_id != to_hand_id:
            detail.append(name(attach_id))
        self._log("PLAY_TRAINER", f"Crispin → {detail}", CRISPIN)

    def salvatore_evolve_staryu(self, staryu: Pokemon) -> bool:
        if SALVATOR not in self.hand or MEGA_STARMIE not in self.deck:
            return False
        if not self._can_evolve_now(staryu):
            self._log("NOTE", f"Salvatore blocked: {name(staryu.card_id)} cannot evolve yet")
            return False
        self.hand.remove(SALVATOR)
        self.discard.append(SALVATOR)
        self.supporter_played = True
        self._log("PLAY_TRAINER", "PLAY Salvatore", SALVATOR)
        self.deck.remove(MEGA_STARMIE)
        staryu.card_id = MEGA_STARMIE
        self._enforce_prism_on_basic_only(staryu)
        self._log("EVOLVE", f"Salvatore: {name(STARYU)} → {name(MEGA_STARMIE)}", MEGA_STARMIE)
        return True

    def poke_pad_search(self, target: int) -> bool:
        from opening_cards import POKE_PAD

        if not is_pad_legal_target(target):
            self._log(
                "NOTE",
                f"Poké Pad blocked: {name(target)} is not a legal Pad target (E-PAD-1)",
            )
            return False
        if target in self.deck:
            self.deck.remove(target)
            self.hand.append(target)
        self._log("PLAY_TRAINER", f"Poké Pad → {name(target)}", POKE_PAD)
        return True

    def lillie_draw(self, n: int = 6) -> None:
        from opening_cards import LILLIE

        drawn = []
        for _ in range(n):
            if not self.deck:
                break
            c = self.deck.pop(0)
            self.hand.append(c)
            drawn.append(c)
        self._log("PLAY_TRAINER", f"Lillie draw {len(drawn)} (no shuffle)", LILLIE)

    def ultra_ball_search(self, target: int, discard: list[int]) -> None:
        from opening_cards import ULTRA_BALL
        for d in discard:
            if d in self.hand:
                self.hand.remove(d)
                self.discard.append(d)
        if target in self.deck:
            self.deck.remove(target)
            self.hand.append(target)
        self._log("PLAY_TRAINER", f"Ultra Ball → {name(target)}, disc {[name(d) for d in discard]}", ULTRA_BALL)

    def _discard_retreat_cost(self, p: Pokemon) -> None:
        cost = retreat_cost_for(p.card_id)
        for _ in range(cost):
            if not p.energies:
                break
            e = p.energies.pop(0)
            self.discard.append(e)
            self._log("DISCARD", f"Retreat cost → discard {name(e)}", e)

    def _enforce_prism_on_basic_only(self, p: Pokemon) -> None:
        if p.card_id in BASIC_IDS:
            return
        kept: list[int] = []
        for e in p.energies:
            if e == PRISM:
                self.discard.append(e)
                self._log("DISCARD", f"Prism discarded from {name(p.card_id)} (non-Basic)", PRISM)
            else:
                kept.append(e)
        p.energies = kept

    def evolve_staryu(self, staryu: Pokemon, mega_id: int) -> None:
        if mega_id not in self.hand:
            self._log("NOTE", "EVOLVE failed: no mega in hand")
            return
        if not self._can_evolve_now(staryu):
            self._log("NOTE", f"EVOLVE blocked: {name(staryu.card_id)} entered turn {staryu.entered_turn}")
            return
        self.hand.remove(mega_id)
        staryu.card_id = mega_id
        self._enforce_prism_on_basic_only(staryu)
        self._log("EVOLVE", f"{name(STARYU)} → {name(mega_id)}", mega_id)

    def switch_mega_to_active(self) -> bool:
        from opening_cards import SWITCH

        idx = next((i for i, p in enumerate(self.bench) if p.card_id == MEGA_STARMIE), None)
        if idx is None:
            return False
        if SWITCH not in self.hand:
            self._log("NOTE", "Switch unavailable — cannot promote Mega to Active (E-SW-1)")
            return False
        self.hand.remove(SWITCH)
        self.discard.append(SWITCH)
        old_active = self.active
        self.active = self.bench.pop(idx)
        if old_active:
            self.bench.append(old_active)
        self._log("SWITCH", f"Active ← {name(MEGA_STARMIE)}", SWITCH)
        return True

    def retreat_promote_bench(self, bench_idx: int) -> bool:
        if self.active and not can_retreat_pokemon(self.active.card_id, self.active.energies):
            self._log(
                "NOTE",
                f"Retreat blocked: {name(self.active.card_id)} lacks retreat cost (E-RET-1)",
            )
            return False
        promoted = self.bench[bench_idx]
        if self.active:
            self._discard_retreat_cost(self.active)
            old = self.active
            self.bench.pop(bench_idx)
            self.bench.append(old)
        else:
            self.bench.pop(bench_idx)
        self.active = promoted
        self._log("RETREAT", f"Retreat → Active ← {name(promoted.card_id)}")
        return True

    def format_pokemon(self, p: Pokemon | None) -> str:
        if p is None:
            return "（空）"
        en = ", ".join(name(e) for e in p.energies) if p.energies else "无能量"
        return f"{name(p.card_id)} [{en}]"

    def format_board(self) -> str:
        lines = [f"  Active: {self.format_pokemon(self.active)}"]
        if self.bench:
            for i, p in enumerate(self.bench):
                lines.append(f"  Bench[{i}]: {self.format_pokemon(p)}")
        else:
            lines.append("  Bench: （空）")
        return "\n".join(lines)

    def format_hand(self) -> str:
        if not self.hand:
            return "  （空）"
        return "  " + ", ".join(name(c) for c in self.hand)

    def snapshot_summary(self) -> str:
        act = name(self.active.card_id) if self.active else "—"
        bench = [name(p.card_id) for p in self.bench]
        hand = [name(c) for c in self.hand]
        return (
            f"Turn {self.current_turn} (My-T{self.my_turn_number}) | "
            f"Active={act} bench={bench} | hand={hand} | "
            f"deck={len(self.deck)} discard={len(self.discard)}"
        )
