"""Public-card role metadata for opponent target planning.

The table is intentionally card based: target selection must remain useful
before the opponent's full archetype is known.  Matchup-specific overrides can
be layered on top later without changing TurnPlan's target model.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

OpponentRole = Literal[
    "MAIN_ATTACKER_BASE",
    "MAIN_ATTACKER_STAGE",
    "MAIN_ATTACKER",
    "SECONDARY_ATTACKER_BASE",
    "SECONDARY_ATTACKER",
    "ENGINE_BASE",
    "UTILITY",
    "UNKNOWN",
]

SHAYMIN = 343


@dataclass(frozen=True)
class OpponentRoleProfile:
    role: OpponentRole
    line: str
    boss_priority: int
    rider_priority: int
    known: bool = True


UNKNOWN_PROFILE = OpponentRoleProfile("UNKNOWN", "", 0, 0, False)


def _p(
    role: OpponentRole,
    line: str,
    boss: int,
    rider: int,
) -> OpponentRoleProfile:
    return OpponentRoleProfile(role, line, boss, rider)


# Five current combat-eval archetypes.  Priorities are deliberately separate:
# Boss values a developed attacker/engine; Jetting's rider values cutting a
# future attacker off at its low-HP base.
OPPONENT_ROLES: dict[int, OpponentRoleProfile] = {
    # Alakazam
    741: _p("MAIN_ATTACKER_BASE", "ALAKAZAM", 70, 100),  # Abra
    742: _p("MAIN_ATTACKER_STAGE", "ALAKAZAM", 82, 75),  # Kadabra
    743: _p("MAIN_ATTACKER", "ALAKAZAM", 100, 30),
    343: _p("UTILITY", "SHAYMIN", 88, 82),  # Flower Curtain
    140: _p("UTILITY", "FEZANDIPITI", 72, 45),
    305: _p("ENGINE_BASE", "DUDUNSPARCE", 48, 58),
    66: _p("UTILITY", "DUDUNSPARCE", 68, 45),
    # Dragapult
    119: _p("MAIN_ATTACKER_BASE", "DRAGAPULT", 70, 100),  # Dreepy
    120: _p("MAIN_ATTACKER_STAGE", "DRAGAPULT", 90, 78),  # Drakloak draw engine
    121: _p("MAIN_ATTACKER", "DRAGAPULT", 100, 30),
    131: _p("ENGINE_BASE", "DUSKNOIR", 72, 88),  # Duskull
    133: _p("UTILITY", "DUSKNOIR", 96, 35),  # Cursed Blast
    112: _p("UTILITY", "MUNKIDORI", 82, 68),
    235: _p("UTILITY", "BUDEW", 62, 52),
    1071: _p("UTILITY", "MEOWTH_EX", 58, 35),
    # Mega Lucario
    677: _p("MAIN_ATTACKER_BASE", "MEGA_LUCARIO", 72, 100),  # Riolu
    678: _p("MAIN_ATTACKER", "MEGA_LUCARIO", 100, 30),
    673: _p("SECONDARY_ATTACKER_BASE", "HARIYAMA", 68, 88),  # Makuhita
    674: _p("SECONDARY_ATTACKER", "HARIYAMA", 92, 42),
    675: _p("UTILITY", "LUNATONE", 70, 62),
    676: _p("SECONDARY_ATTACKER", "SOLROCK", 76, 70),
    # Marnie's Grimmsnarl
    646: _p("MAIN_ATTACKER_BASE", "MARNIE_GRIMMSNARL", 72, 100),
    647: _p("MAIN_ATTACKER_STAGE", "MARNIE_GRIMMSNARL", 82, 72),
    648: _p("MAIN_ATTACKER", "MARNIE_GRIMMSNARL", 100, 30),
    860: _p("ENGINE_BASE", "FROSLASS_104", 65, 82),  # Snorunt
    104: _p("UTILITY", "FROSLASS_104", 90, 52),
    # Walrein control
    941: _p("MAIN_ATTACKER_BASE", "WALREIN", 72, 100),  # Spheal
    942: _p("MAIN_ATTACKER_STAGE", "WALREIN", 82, 72),
    943: _p("MAIN_ATTACKER", "WALREIN", 100, 30),
    # Archaludon / Duraludon (expert: never build Mega Froslass into this matchup)
    169: _p("MAIN_ATTACKER_BASE", "ARCHALUDON", 72, 100),  # Duraludon
    170: _p("MAIN_ATTACKER", "ARCHALUDON", 96, 35),
    190: _p("MAIN_ATTACKER", "ARCHALUDON", 100, 30),  # Archaludon ex
    839: _p("MAIN_ATTACKER_BASE", "ARCHALUDON", 72, 100),
    840: _p("MAIN_ATTACKER", "ARCHALUDON", 96, 35),
    992: _p("MAIN_ATTACKER_BASE", "ARCHALUDON", 70, 95),
}

# Public-card IDs that confirm an Archaludon/Duraludon line.
ARCHALUDON_LINE_IDS = frozenset({169, 170, 190, 839, 840, 992})

# Hop's Trevenant control — keep Mega Starmie; never pivot into 861.
TREVENANT_LINE_IDS = frozenset({878, 879})

# Dragapult (烈箭 / 「桥龙」侧) — 861 is a bad second attacker.
DRAGAPULT_LINE_IDS = frozenset({119, 120, 121})

# Mega Lucario fast — prefer Mega Froslass as second attacker while Starmie lives.
LUCARIO_LINE_IDS = frozenset({677, 678})

# Optional sticky matchup boosts layered on the card table.  Keys are card ids.
_MATCHUP_OVERRIDES: dict[str, dict[int, tuple[int, int]]] = {
    # (delta_boss, delta_rider)
    "alakazam": {
        741: (10, 15),  # Abra is the primary rider / early cut
        343: (20, 0),   # Shaymin is the DoubleKO blocker — gust high
    },
}


def opponent_role(card_id: int, matchup: str | None = None) -> OpponentRoleProfile:
    base = OPPONENT_ROLES.get(int(card_id), UNKNOWN_PROFILE)
    if not matchup:
        return base
    deltas = _MATCHUP_OVERRIDES.get(matchup, {}).get(int(card_id))
    if not deltas:
        return base
    return replace(
        base,
        boss_priority=base.boss_priority + deltas[0],
        rider_priority=base.rider_priority + deltas[1],
    )


def known_opponent_card(card_id: int) -> bool:
    return opponent_role(card_id).known


def has_rule_box(pokemon: object) -> bool:
    """Rule-box Pokémon are not shielded by Shaymin's Flower Curtain."""
    return bool(
        getattr(pokemon, "ex", False)
        or getattr(pokemon, "megaEx", False)
        or getattr(pokemon, "tera", False)
        or getattr(pokemon, "v", False)
        or getattr(pokemon, "vstar", False)
        or getattr(pokemon, "vmax", False)
    )


def flower_curtain_online(field_ids: set[int] | frozenset[int] | tuple[int, ...]) -> bool:
    return SHAYMIN in set(field_ids)


def is_attack_damage_protected(pokemon: object, field_ids) -> bool:
    """True when Jetting-style attack damage to this bench Pokémon is prevented."""
    if not flower_curtain_online(field_ids):
        return False
    return not has_rule_box(pokemon)


def role_coverage(card_ids) -> float:
    ids = [int(c) for c in card_ids if int(c) > 0]
    if not ids:
        return 1.0
    return sum(1 for cid in ids if known_opponent_card(cid)) / len(ids)
