"""Deck resource accounting from visible zones (hand, discard, field, prize count).

AGGRESSION+ uses this to infer remaining copies in the deck pile for
supporter / draw-axis decisions. Does NOT use opponent profiling.

See references/phases/02_draw_axis.md §5.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opening_cards import (
    BOSS_ORDERS,
    CRISPIN,
    DUDUNSPARCE,
    DUDUNSPARCE_EX,
    DUNSPARCE_A,
    DUNSPARCE_B,
    HILDA,
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    POKE_PAD,
    STARYU,
    ULTRA_BALL,
    UNFAIR_STAMP,
)

_SKILL_ROOT = Path(__file__).resolve().parents[1]


def _default_deck_csv() -> Path:
    """Resolve deck template: Kaggle bundle deck.csv or repo data/decks/."""
    here = Path(__file__).resolve()
    for anc in here.parents:
        kaggle_deck = anc / "deck.csv"
        if kaggle_deck.is_file():
            return kaggle_deck
        repo_deck = anc / "data" / "decks" / "starmie_froslass.csv"
        if repo_deck.is_file():
            return repo_deck
    raise FileNotFoundError(
        "starmie deck template not found (expected deck.csv or data/decks/starmie_froslass.csv)"
    )


def _si(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def load_deck_template(csv_path: Path | None = None) -> list[int]:
    path = csv_path or _default_deck_csv()
    ids: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(int(line))
    return ids


try:
    DEFAULT_DECK: list[int] = load_deck_template()
except FileNotFoundError:
    DEFAULT_DECK = []


@dataclass(frozen=True)
class HandContext:
    hand_ids: list[int]
    hand_size: int
    supporter_played: bool
    energy_attached: bool
    has_boss: bool
    has_lillie: bool
    has_crispin: bool
    gust_target_on_opp_bench: bool


@dataclass
class DeckResourceSnapshot:
    """Remaining deck resources inferred from template minus visible zones."""

    template: Counter[int] = field(default_factory=Counter)
    seen: Counter[int] = field(default_factory=Counter)
    remaining: Counter[int] = field(default_factory=Counter)
    deck_count: int = 0
    prize_count: int = 6
    discard_count: int = 0

    def copies_left(self, card_id: int) -> int:
        """Unseen copies (still in deck and/or prize)."""
        return self.remaining.get(card_id, 0)

    def copies_in_hand(self, hand: HandContext, card_id: int) -> int:
        return sum(1 for c in hand.hand_ids if c == card_id)

    def likely_in_deck(self, card_id: int) -> int:
        """Upper bound: unseen copies that could still be in the deck pile."""
        left = self.copies_left(card_id)
        return min(left, self.deck_count)

    def exhausted(self, card_id: int) -> bool:
        return self.copies_left(card_id) <= 0

    @property
    def lillie_left(self) -> int:
        return self.copies_left(LILLIE)

    @property
    def boss_left(self) -> int:
        return self.copies_left(BOSS_ORDERS)

    @property
    def pad_left(self) -> int:
        return self.copies_left(POKE_PAD)

    @property
    def staryu_line_left(self) -> int:
        return self.copies_left(STARYU) + self.copies_left(MEGA_STARMIE)

    @property
    def dudunsparce_66_left(self) -> int:
        return self.copies_left(DUDUNSPARCE)

    @property
    def dunsparce_basic_left(self) -> int:
        return self.copies_left(DUNSPARCE_A) + self.copies_left(DUNSPARCE_B)

    def can_run_away_cycle(self, hand: HandContext, *, on_bench_66: bool = False) -> bool:
        if on_bench_66:
            return True
        if any(c in hand.hand_ids for c in (DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE)):
            return True
        return self.dudunsparce_66_left > 0 or self.dunsparce_basic_left > 0

    def need_lillie_for_missing(self, hand: HandContext, *, want_boss: bool, want_pad: bool) -> bool:
        """True when a key piece is not in hand and still exists unseen."""
        if want_boss and not hand.has_boss and self.boss_left > 0:
            return True
        if want_pad and self.pad_left > 0 and POKE_PAD not in hand.hand_ids:
            return True
        return False

    def prefer_lillie_over_cycle(self, hand: HandContext) -> bool:
        """Burn Lillie when low copies remain or hand critically empty."""
        if hand.hand_size <= 2:
            return True
        if self.lillie_left <= 1 and LILLIE in hand.hand_ids:
            return True
        return False

    def prefer_cycle_over_lillie(self, hand: HandContext) -> bool:
        """Preserve Lillie copies when hand is workable and 66 path exists."""
        if hand.hand_size > 4:
            return False
        if self.lillie_left >= 2 and hand.hand_size >= 3:
            return True
        if hand.has_boss or hand.has_crispin:
            return True
        return False


def _ids_from_cards(cards) -> list[int]:
    out: list[int] = []
    for c in cards or []:
        if c is None:
            continue
        cid = _si(getattr(c, "id", None))
        if cid:
            out.append(cid)
    return out


def _ids_from_pokemon(player) -> list[int]:
    ids: list[int] = []
    try:
        for p in (player.active or []) + (player.bench or []):
            if not p:
                continue
            cid = _si(getattr(p, "id", None))
            if cid:
                ids.append(cid)
            for e in getattr(p, "energies", None) or []:
                eid = _si(e)
                if eid:
                    ids.append(eid)
    except Exception:
        pass
    return ids


def collect_seen_ids(player) -> Counter[int]:
    """All card IDs we can account for outside the deck pile."""
    seen: list[int] = []
    seen.extend(_ids_from_cards(getattr(player, "hand", None)))
    seen.extend(_ids_from_cards(getattr(player, "discard", None)))
    seen.extend(_ids_from_pokemon(player))
    return Counter(seen)


def build_deck_resources(
    obs,
    deck_template: list[int] | None = None,
) -> DeckResourceSnapshot:
    """Build resource snapshot from obs (hand + discard + field + deckCount)."""
    template = Counter(deck_template or DEFAULT_DECK)
    mi = _si(getattr(obs.current, "yourIndex", None))
    me = obs.current.players[mi]

    seen = collect_seen_ids(me)
    deck_count = _si(getattr(me, "deckCount", None), 0)
    prize_count = len(getattr(me, "prize", None) or []) or _si(
        getattr(me, "prizeCount", None), 6
    )
    discard_count = len(getattr(me, "discard", None) or [])

    remaining = Counter(template)
    for cid, n in seen.items():
        remaining[cid] = max(0, remaining[cid] - n)

    return DeckResourceSnapshot(
        template=template,
        seen=seen,
        remaining=remaining,
        deck_count=deck_count,
        prize_count=prize_count,
        discard_count=discard_count,
    )


def build_hand_context_from_obs(obs, *, gust_target_on_opp_bench: bool = False) -> HandContext:
    mi = _si(getattr(obs.current, "yourIndex", None))
    me = obs.current.players[mi]
    hand = me.hand or []
    ids = [_si(getattr(c, "id", None)) for c in hand if c]
    return HandContext(
        hand_ids=ids,
        hand_size=len(ids),
        supporter_played=bool(getattr(me, "supporterPlayed", False)),
        energy_attached=bool(getattr(me, "energyAttached", False)),
        has_boss=BOSS_ORDERS in ids,
        has_lillie=LILLIE in ids,
        has_crispin=CRISPIN in ids,
        gust_target_on_opp_bench=gust_target_on_opp_bench,
    )
