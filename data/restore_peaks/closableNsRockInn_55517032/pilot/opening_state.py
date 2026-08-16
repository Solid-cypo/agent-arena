"""Mutable opening simulation state (ordered deck; mid-game shuffles via rng)."""
from __future__ import annotations

import random
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
    ITEM_IDS,
    MEGA_STARMIE,
    hilda_evolution_priority,
    mega_ready_to_land,
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
    # Expert-facing deck visibility (ordered sim; not for online features).
    deck_top10_before: list[int] | None = None
    deck_top10_after: list[int] | None = None
    deck_pick_ids: list[int] | None = None
    drawn_ids: list[int] | None = None


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
    # Mid-game shuffle RNG (Lillie / Run Away / Judge). Seeded from sim seed.
    rng: random.Random | None = field(default=None, repr=False)
    _shuffle_ops: int = field(default=0, repr=False)

    @classmethod
    def from_ordered_deck(
        cls,
        deck: list[int],
        *,
        going_first: bool = True,
        seed: int | None = None,
    ) -> OpeningGameState:
        if len(deck) != 60:
            raise ValueError(f"deck must be 60 cards, got {len(deck)}")
        st = cls(deck_order=list(deck), going_first=going_first)
        st.prizes = deck[0:6]
        st.hand = list(deck[6:13])
        st.deck = list(deck[13:])
        if seed is not None:
            # Offset from deck-order seed so mid-game shuffles diverge from initial order.
            st.rng = random.Random(seed ^ 0x4C494C4C)  # "LILL"
        return st

    def _shuffle_deck_inplace(self) -> None:
        """Shuffle remaining deck (deterministic if rng was seeded)."""
        self._shuffle_ops += 1
        if self.rng is None:
            # Unseeded fallback: still shuffle, but not reproducible across runs.
            random.Random(self._shuffle_ops).shuffle(self.deck)
        else:
            self.rng.shuffle(self.deck)

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

    def _deck_top10(self) -> list[int]:
        return list(self.deck[:10])

    def _log(
        self,
        kind: ActionKind,
        detail: str,
        card_id: int | None = None,
        *,
        deck_top10_before: list[int] | None = None,
        deck_top10_after: list[int] | None = None,
        deck_pick_ids: list[int] | None = None,
        drawn_ids: list[int] | None = None,
    ) -> None:
        self.log.append(
            Action(
                kind,
                detail,
                card_id,
                deck_top10_before=deck_top10_before,
                deck_top10_after=deck_top10_after,
                deck_pick_ids=deck_pick_ids,
                drawn_ids=drawn_ids,
            )
        )

    def _log_deck_op(
        self,
        kind: ActionKind,
        detail: str,
        card_id: int | None = None,
        *,
        before: list[int],
        picks: list[int] | None = None,
        drawn: list[int] | None = None,
    ) -> None:
        self._log(
            kind,
            detail,
            card_id,
            deck_top10_before=list(before),
            deck_top10_after=self._deck_top10(),
            deck_pick_ids=list(picks) if picks else None,
            drawn_ids=list(drawn) if drawn else None,
        )

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
                before = self._deck_top10()
                drawn = self.deck.pop(0)
                self.hand.append(drawn)
                self._log_deck_op(
                    "DRAW",
                    f"Draw {name(drawn)}",
                    drawn,
                    before=before,
                    drawn=[drawn],
                )

    def end_turn_cleanup(self) -> None:
        """Discard Ignition Energy attached to any Pokémon (card text)."""
        from opening_cards import IGNITION

        for zone, p in self._iter_field():
            if p is None:
                continue
            kept: list[int] = []
            for e in p.energies:
                if e == IGNITION:
                    self.discard.append(e)
                    self._log(
                        "DISCARD",
                        f"Ignition Energy discarded from {name(p.card_id)} (end of turn)",
                        IGNITION,
                    )
                else:
                    kept.append(e)
            p.energies = kept

    def _iter_field(self):
        yield ("active", self.active)
        for p in self.bench:
            yield ("bench", p)

    def play_pokemon_to_bench(self, card_id: int) -> None:
        self.hand.remove(card_id)
        self.bench.append(Pokemon(card_id, self.current_turn))
        self._log("PLAY_POKEMON", f"Bench ← {name(card_id)}", card_id)

    def can_play_supporter(self) -> bool:
        """True iff a Supporter is still legal this turn (E-SUP-1 + once/turn)."""
        from opening_cards import supporter_blocked_going_first_t1

        if self.supporter_played:
            return False
        if supporter_blocked_going_first_t1(
            going_first=self.going_first, my_turn_number=self.my_turn_number
        ):
            return False
        return True

    def play_trainer(self, card_id: int, detail: str) -> bool:
        """Play a trainer. Supporters blocked on going-first T1 (E-SUP-1)."""
        if card_id in SUPPORTER_IDS and not self.can_play_supporter():
            self._log(
                "NOTE",
                f"Supporter blocked: {name(card_id)} illegal on going-first T1 "
                f"or already used (E-SUP-1)",
                card_id,
            )
            return False
        self.hand.remove(card_id)
        self.discard.append(card_id)
        if card_id in SUPPORTER_IDS:
            self.supporter_played = True
        # Snapshot deck top even when the play itself does not mutate deck
        # (effect may follow in a separate log line; experts need continuity).
        top = self._deck_top10()
        self._log(
            "PLAY_TRAINER",
            detail,
            card_id,
            deck_top10_before=top,
            deck_top10_after=top,
        )
        return True

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

    def fan_call(self) -> list[int]:
        before = self._deck_top10()
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
        self._log_deck_op(
            "ABILITY_FAN_CALL",
            f"Fan Call → {[name(c) for c in picks]}",
            before=before,
            picks=picks,
        )
        return picks

    def bench_fan_call_picks(self, picks: list[int] | None = None) -> None:
        """After Fan Call, bench retrieved Dunsparce / spare Fan Rotom when slots allow."""
        from opening_bench import can_play_to_bench
        from opening_cards import DUNSPARCE_A, DUNSPARCE_B, FAN_CALL_BENCH_PRIORITY, FAN_ROTOM

        order = list(picks) if picks else []
        for cid in FAN_CALL_BENCH_PRIORITY:
            if cid not in order:
                order.append(cid)
        for cid in order:
            if cid not in (DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM):
                continue
            if cid not in self.hand or self.bench_open() <= 0:
                continue
            if cid == FAN_ROTOM and (
                (self.active and self.active.card_id == FAN_ROTOM)
                or any(p.card_id == FAN_ROTOM for p in self.bench)
            ):
                continue
            if not can_play_to_bench(self, cid):
                continue
            self.play_pokemon_to_bench(cid)

    def meowth_last_ditch_catch(
        self,
        priorities: tuple[int, ...] = MEOWTH_OPENING_SUPPORTER_PRIORITY,
    ) -> int | None:
        """Search deck for a Supporter. Skip cards already in hand (expert: don't
        Last-Ditch Hilda when Hilda is already drawn)."""
        from opening_cards import HILDA

        before = self._deck_top10()
        for cid in priorities:
            if cid not in self.deck or cid not in SUPPORTER_IDS:
                continue
            # Prefer a different supporter when the top pick is already in hand.
            if cid in self.hand:
                continue
            self.deck.remove(cid)
            self.hand.append(cid)
            self._log_deck_op(
                "ABILITY_LAST_DITCH",
                f"Last-Ditch Catch → {name(cid)}",
                MEOWTH_EX,
                before=before,
                picks=[cid],
            )
            return cid
        # Fallback: if every preferred supporter is already in hand, still fetch
        # a duplicate only when nothing else is available (rare).
        for cid in priorities:
            if cid in self.deck and cid in SUPPORTER_IDS:
                self.deck.remove(cid)
                self.hand.append(cid)
                self._log_deck_op(
                    "ABILITY_LAST_DITCH",
                    f"Last-Ditch Catch → {name(cid)}",
                    MEOWTH_EX,
                    before=before,
                    picks=[cid],
                )
                return cid
        self._log("NOTE", "Last-Ditch Catch: no Supporter found in deck")
        return None

    def play_meowth_to_bench_with_catch(self) -> int | None:
        """Bench Meowth from hand and fire Last-Ditch (When You Play onto Bench).

        Setup Active Meowth cannot use Last-Ditch — Ability only triggers when
        playing from hand onto the Bench.
        """
        if MEOWTH_EX not in self.hand or self.bench_open() <= 0:
            return None
        self.play_pokemon_to_bench(MEOWTH_EX)
        return self.meowth_last_ditch_catch()

    def poffin_to_bench(self, *, prefer_staryu: bool = True) -> bool:
        from opening_cards import POFFIN

        slots = min(2, self.bench_open())
        if slots <= 0:
            return False
        before = self._deck_top10()
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
        if not picks:
            return False
        for cid in picks:
            self.deck.remove(cid)
            self.bench.append(Pokemon(cid, self.current_turn))
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Poffin → bench {[name(c) for c in picks]}",
            POFFIN,
            before=before,
            picks=picks,
        )
        return True

    def _line_has_water(self) -> bool:
        mons = ([self.active] if self.active else []) + list(self.bench)
        return any(
            p.card_id in (STARYU, MEGA_STARMIE) and p.has_water() for p in mons if p
        )

    def _mega_starmie_on_field(self) -> bool:
        if self.active and self.active.card_id == MEGA_STARMIE:
            return True
        return any(p.card_id == MEGA_STARMIE for p in self.bench)

    def hilda_search(self, *, need_evolution: bool = True, need_energy: bool = True) -> None:
        before = self._deck_top10()
        picks: list[int] = []
        if need_evolution:
            # Hilda itself is fetching energy this resolution → count as water path.
            ready = mega_ready_to_land(
                staryu_on_field=self.staryu_on_field(),
                mega_starmie_on_field=self._mega_starmie_on_field(),
                line_has_water=self._line_has_water(),
                hand_ids=self.hand,
                supporter_played=self.supporter_played,
                hilda_resolving=True,
            )
            for cid in hilda_evolution_priority(mega_ready=ready):
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
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Hilda → {[name(c) for c in picks[:2]]}",
            HILDA,
            before=before,
            picks=picks[:2],
        )

    def crispin_search(self, attach_target: Pokemon | None = None) -> None:
        """Crispin: 2 different Basic Energy — 1 to hand, 1 direct attach (E-CRIS-1)."""
        from opening_cards import CRISPIN_BASIC_ENERGY

        in_deck = [e for e in CRISPIN_BASIC_ENERGY if e in self.deck]
        if not in_deck:
            self._log("NOTE", "Crispin: no Basic Energy in deck")
            return

        before = self._deck_top10()
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
        picks = [to_hand_id]
        if attached is not None:
            picks.append(attached)
        elif attach_id is not None and attach_target is None and attach_id != to_hand_id:
            picks.append(attach_id)
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Crispin → {detail}",
            CRISPIN,
            before=before,
            picks=picks,
        )

    def salvatore_evolve_staryu(self, staryu: Pokemon) -> bool:
        if SALVATOR not in self.hand or MEGA_STARMIE not in self.deck:
            return False
        if not self.can_play_supporter():
            self._log(
                "NOTE",
                "Salvatore blocked: Supporter illegal on going-first T1 or already used (E-SUP-1)",
                SALVATOR,
            )
            return False
        # Salvatore explicitly allows evolving a Pokémon put into play this turn /
        # during setup — do NOT gate on _can_evolve_now.
        self.hand.remove(SALVATOR)
        self.discard.append(SALVATOR)
        self.supporter_played = True
        top = self._deck_top10()
        self._log(
            "PLAY_TRAINER",
            "PLAY Salvatore",
            SALVATOR,
            deck_top10_before=top,
            deck_top10_after=top,
        )
        before = self._deck_top10()
        self.deck.remove(MEGA_STARMIE)
        staryu.card_id = MEGA_STARMIE
        self._enforce_prism_on_basic_only(staryu)
        self._log_deck_op(
            "EVOLVE",
            f"Salvatore: {name(STARYU)} → {name(MEGA_STARMIE)}",
            MEGA_STARMIE,
            before=before,
            picks=[MEGA_STARMIE],
        )
        return True

    def poke_pad_search(self, target: int) -> bool:
        from opening_cards import POKE_PAD

        if not is_pad_legal_target(target):
            self._log(
                "NOTE",
                f"Poké Pad blocked: {name(target)} is not a legal Pad target (E-PAD-1)",
            )
            return False
        before = self._deck_top10()
        picks: list[int] = []
        if target in self.deck:
            self.deck.remove(target)
            self.hand.append(target)
            picks = [target]
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Poké Pad → {name(target)}",
            POKE_PAD,
            before=before,
            picks=picks or None,
        )
        return True

    def lillie_draw(self, n: int | None = None) -> None:
        """Lillie's Determination: shuffle hand into deck, shuffle, draw 6 (or 8 if 6 prizes left).

        Caller must already have played Lillie via play_trainer (card in discard).
        """
        from opening_cards import LILLIE

        if n is None:
            # Card text: draw 8 instead of 6 while you have 6 Prize cards remaining.
            n = 8 if len(self.prizes) >= 6 else 6
        before = self._deck_top10()
        returned = list(self.hand)
        self.deck.extend(returned)
        self.hand.clear()
        self._shuffle_deck_inplace()
        drawn: list[int] = []
        for _ in range(n):
            if not self.deck:
                break
            c = self.deck.pop(0)
            self.hand.append(c)
            drawn.append(c)
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Lillie: shuffle hand ({len(returned)}) into deck, draw {len(drawn)}",
            LILLIE,
            before=before,
            drawn=drawn,
        )
        self._log("NOTE", f"莉莉艾抽牌后手牌: {[name(c) for c in self.hand]}")

    def ultra_ball_search(self, target: int, discard: list[int]) -> None:
        from opening_cards import ULTRA_BALL

        before = self._deck_top10()
        for d in discard:
            if d in self.hand:
                self.hand.remove(d)
                self.discard.append(d)
        picks: list[int] = []
        if target in self.deck:
            self.deck.remove(target)
            self.hand.append(target)
            picks = [target]
        self._log_deck_op(
            "PLAY_TRAINER",
            f"Ultra Ball → {name(target)}, disc {[name(d) for d in discard]}",
            ULTRA_BALL,
            before=before,
            picks=picks or None,
        )

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
