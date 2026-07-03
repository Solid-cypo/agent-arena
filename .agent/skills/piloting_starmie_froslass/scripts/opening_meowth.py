"""Meowth ex Last-Ditch Catch - OPENING gap-aware supporter priority (E-MEOW-2).

Priority by Goal gaps (1030 on field / water / Mega 1031 in hand):
  1. Energy only (G2 or retreat energy, have 1031 card) -> Crispin -> Hilda
  2. Mega + energy missing (G2+G3, 1030 on field)        -> Hilda
  3. Mega only missing (G3, 1030 watered)                -> Salvatore -> Hilda
  4. All three missing (G1+G2+G3)                        -> Lillie

Reconstructed from bytecode salvage (original .py was lost in a working-tree wipe).
"""
from __future__ import annotations

from opening_cards import (
    CRISPIN,
    HILDA,
    LILLIE,
    MEGA_STARMIE,
    SALVATOR,
    STARYU,
    can_retreat_pokemon,
)


def meowth_needs_retreat_energy(st) -> bool:
    """Placeholder Active still needs attach before bench EVOLVE / retreat."""
    if st.active is None or st.setup_active_id == STARYU:
        return False
    if MEGA_STARMIE in st.hand:
        return False
    if not can_retreat_pokemon(st.active.card_id, st.active.energies):
        return False
    return st.staryu_on_field()


def meowth_opening_last_ditch_priority(st, gaps) -> tuple[int, ...]:
    """Deck-filtered supporter search order for Last-Ditch Catch."""
    need_staryu = gaps.g1
    need_mega = gaps.g3
    need_energy = gaps.g2 or meowth_needs_retreat_energy(st)

    if need_staryu and need_energy and need_mega:
        order: tuple[int, ...] = (LILLIE,)
    elif need_staryu:
        order = (LILLIE, CRISPIN, HILDA)
    elif need_mega and need_energy:
        order = (HILDA,)
    elif not need_mega and need_energy:
        order = (SALVATOR, HILDA)
    elif not need_energy and need_mega:
        order = (CRISPIN, HILDA)
    else:
        order = (HILDA, CRISPIN, SALVATOR, LILLIE)

    return tuple(c for c in order if c in st.deck)
