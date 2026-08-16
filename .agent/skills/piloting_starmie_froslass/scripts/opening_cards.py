"""Card IDs and opening-relevant metadata for starmie_froslass."""
from __future__ import annotations

STARYU = 1030
MEGA_STARMIE = 1031
SNORUNT = 860
FROSLASS = 104
MEGA_FROSLASS = 861
DUDUNSPARCE = 66
DUDUNSPARCE_EX = 306
MUNKIDORI = 112
FAN_ROTOM = 174
BUDEW = 235
DUNSPARCE_A = 65
DUNSPARCE_B = 305
MEOWTH_EX = 1071

WATER_BASIC = 3
DARK_BASIC = 7
PRISM = 16
IGNITION = 17

HILDA = 1225
LILLIE = 1227
POFFIN = 1086
ULTRA_BALL = 1121
POKE_PAD = 1152
SALVATOR = 1189
CRISPIN = 1198
BOSS_ORDERS = 1182
JUDGE = 1213
NIGHT_STRETCHER = 1097
UNFAIR_STAMP = 1080
WALLYS_COMPASSION = 1229
SWITCH = 1123
RISKY_RUINS = 1260

BASIC_IDS = frozenset({
    STARYU, SNORUNT, MUNKIDORI, FAN_ROTOM, BUDEW,
    DUNSPARCE_A, DUNSPARCE_B, MEOWTH_EX,
})

WATER_ENERGY_IDS = frozenset({WATER_BASIC, PRISM})  # Prism kept for legacy sims; deck no longer runs it
ENERGY_IDS = frozenset({WATER_BASIC, DARK_BASIC, PRISM, IGNITION})
# Production deck (2026-08-15+): Water×5 + Dark×3 + Ignition×1 (Nebula fuel).
DECK_BASIC_ENERGY = (WATER_BASIC, DARK_BASIC)
# Crispin (E-CRIS-1): Basic Energy only — not Prism / Ignition
CRISPIN_BASIC_ENERGY = (WATER_BASIC, DARK_BASIC)
# Hilda second pick: any energy (incl. Ignition for Nebula).
HILDA_ENERGY_IDS = frozenset({WATER_BASIC, DARK_BASIC, PRISM, IGNITION})

SUPPORTER_IDS = frozenset({
    HILDA, LILLIE, CRISPIN, SALVATOR, BOSS_ORDERS, JUDGE, WALLYS_COMPASSION,
})

ITEM_IDS = frozenset({POFFIN, ULTRA_BALL, POKE_PAD, NIGHT_STRETCHER, UNFAIR_STAMP, SWITCH})

# Fan Call: {C} Basic Pokémon HP≤100 only — NOT Water/Grass (E-FAN-C1)
FAN_CALL_IDS = frozenset({FAN_ROTOM, DUNSPARCE_A, DUNSPARCE_B})
FAN_CALL_PRIORITY = (DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM)

POFFIN_IDS = frozenset({STARYU, SNORUNT, BUDEW, DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM})

# OPENING Poffin pick order. Field preset: Staryu×2 · Snorunt×1 · Munk×1 ·
# Dunsparce×1 · flex×1 (unreserved — tools OK, but reserve opens for missing
# cores; see opening_bench.can_bench_card).
POFFIN_OPENING_PRIORITY = (
    STARYU, SNORUNT, FAN_ROTOM, DUNSPARCE_A, DUNSPARCE_B, BUDEW,
)

# Meowth Last-Ditch OPENING targets (E-MEOW-2); catch skips cards already in hand.
MEOWTH_OPENING_SUPPORTER_PRIORITY = (HILDA, CRISPIN, SALVATOR, LILLIE, JUDGE)

# Meowth Last-Ditch CONTROL targets (链 E)
MEOWTH_CONTROL_SUPPORTER_PRIORITY = (BOSS_ORDERS, JUDGE, CRISPIN, LILLIE)

# Pokémon ex / V — Poké Pad cannot search (Rule Box)
RULE_BOX_IDS = frozenset({MEGA_STARMIE, MEGA_FROSLASS, MEOWTH_EX, DUDUNSPARCE_EX})

# Poké Pad: deck Pokémon without Rule Box (E-PAD-1)
PAD_SEARCH_IDS = frozenset({
    STARYU, SNORUNT, MUNKIDORI, FAN_ROTOM, BUDEW,
    DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE, FROSLASS,
})

# Shared OPENING Pad target priority for oracle + RL target_rules.
# Pokémon only (energy is illegal under E-PAD-1). Skip Staryu when Mega is
# already on field — handled by pad_pokemon_candidates().
POKE_PAD_OPENING_PRIORITY = (
    STARYU, SNORUNT, FAN_ROTOM, DUDUNSPARCE, BUDEW, DUNSPARCE_A, DUNSPARCE_B,
)

# Post-Mega Pad pick when Munk is still missing (SeatMunk). Opening priority
# intentionally omits Munk so early Pad still seats the attacker line first.
POKE_PAD_POST_MEGA_PRIORITY = (
    MUNKIDORI, SNORUNT, FROSLASS, DUDUNSPARCE, FAN_ROTOM, BUDEW,
    DUNSPARCE_A, DUNSPARCE_B,
)

# Hilda: Evolution Pokémon only — never Basic (E-HILDA-1)
HILDA_EVOLUTION_IDS = frozenset({MEGA_STARMIE, MEGA_FROSLASS, FROSLASS, DUDUNSPARCE, DUDUNSPARCE_EX})
HILDA_EVOLUTION_PRIORITY = (
    MEGA_STARMIE, MEGA_FROSLASS, FROSLASS, DUDUNSPARCE, DUDUNSPARCE_EX,
)
# When mega_ready_to_land is false: dig non-Mega first; 861 last (never above water/path).
HILDA_EVOLUTION_PRIORITY_NOT_READY = (
    FROSLASS, DUDUNSPARCE, DUDUNSPARCE_EX, MEGA_STARMIE, MEGA_FROSLASS,
)

_WATER_FETCH_SUPPORTERS = frozenset({HILDA, CRISPIN})


def water_path_ok(
    *,
    line_has_water: bool,
    hand_ids: list[int] | tuple[int, ...] | set[int] | frozenset[int],
    supporter_played: bool,
    hilda_resolving: bool = False,
) -> bool:
    """Water already on the Staryu/Mega line, or attachable this/next turn."""
    if line_has_water or hilda_resolving:
        return True
    ids = set(hand_ids)
    if ids & WATER_ENERGY_IDS:
        return True
    if not supporter_played and ids & _WATER_FETCH_SUPPORTERS:
        return True
    return False


def mega_ready_to_land(
    *,
    staryu_on_field: bool,
    mega_starmie_on_field: bool,
    line_has_water: bool,
    hand_ids: list[int] | tuple[int, ...] | set[int] | frozenset[int],
    supporter_played: bool,
    hilda_resolving: bool = False,
) -> bool:
    """Base online, Mega not yet landed, and water path is (or will be) ready."""
    if not staryu_on_field or mega_starmie_on_field:
        return False
    return water_path_ok(
        line_has_water=line_has_water,
        hand_ids=hand_ids,
        supporter_played=supporter_played,
        hilda_resolving=hilda_resolving,
    )


def hilda_evolution_priority(*, mega_ready: bool) -> tuple[int, ...]:
    """Hilda evo pick order — lock Mega Starmie only when mega_ready_to_land."""
    if mega_ready:
        return HILDA_EVOLUTION_PRIORITY
    return HILDA_EVOLUTION_PRIORITY_NOT_READY


def two_turn_mega_path_ok(
    *,
    staryu_on_field: bool,
    mega_starmie_on_field: bool,
    staryu_can_evolve: bool,
    line_has_water: bool,
    hand_ids: list[int] | tuple[int, ...] | set[int] | frozenset[int],
    supporter_played: bool,
) -> bool:
    """Mega is in hand and base+water can land it this or next turn."""
    if mega_starmie_on_field or not staryu_on_field:
        return False
    if MEGA_STARMIE not in set(hand_ids):
        return False
    return water_path_ok(
        line_has_water=line_has_water,
        hand_ids=hand_ids,
        supporter_played=supporter_played,
    )


# Retreat cost in {C} energy cards required to retreat (card_db retreatCost).
# DUNSPARCE_A (65) is free retreat; DUNSPARCE_B (305) costs 1.
RETREAT_COST: dict[int, int] = {
    MEGA_STARMIE: 2,
    STARYU: 1, SNORUNT: 1, MUNKIDORI: 1, MEOWTH_EX: 1,
    FAN_ROTOM: 1, BUDEW: 1, DUNSPARCE_A: 0, DUNSPARCE_B: 1,
    DUDUNSPARCE: 3, FROSLASS: 1, MEGA_FROSLASS: 1,
}

# Basics Fan Call may put into hand that we should bench when slots allow.
FAN_CALL_BENCH_PRIORITY = (DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM)

EVOLVES_TO = {STARYU: MEGA_STARMIE, DUNSPARCE_A: DUDUNSPARCE, DUNSPARCE_B: DUDUNSPARCE}

CARD_NAMES: dict[int, str] = {
    STARYU: "Staryu", MEGA_STARMIE: "Mega Starmie ex", SNORUNT: "Snorunt",
    FROSLASS: "Froslass", MEGA_FROSLASS: "Mega Froslass ex", MUNKIDORI: "Munkidori",
    FAN_ROTOM: "Fan Rotom", BUDEW: "Budew", DUNSPARCE_A: "Dunsparce",
    DUNSPARCE_B: "Dunsparce", MEOWTH_EX: "Meowth ex",
    66: "Dudunsparce (Run Away Draw)", 306: "Dudunsparce ex",
    HILDA: "Hilda", LILLIE: "Lillie", 1182: "Boss's Orders",
    POFFIN: "Poffin", ULTRA_BALL: "Ultra Ball", POKE_PAD: "Poké Pad",
    1097: "Night Stretcher", 1080: "Unfair Stamp", SWITCH: "Switch",
    SALVATOR: "Salvatore", CRISPIN: "Crispin", 1213: "Judge", 1229: "Wally's Compassion",
    1260: "Risky Ruins",
    WATER_BASIC: "Water Energy", DARK_BASIC: "Darkness Energy",
    PRISM: "Prism Energy", IGNITION: "Ignition Energy",
}


def names(cards: list[int]) -> list[str]:
    return [name(c) for c in cards]


def name(cid: int) -> str:
    return CARD_NAMES.get(cid, f"Card({cid})")


def retreat_cost_for(card_id: int) -> int:
    return RETREAT_COST.get(card_id, 1)


def can_retreat_pokemon(card_id: int, energies: list[int]) -> bool:
    return len(energies) >= retreat_cost_for(card_id)


def supporter_blocked_going_first_t1(*, going_first: bool, my_turn_number: int) -> bool:
    """E-SUP-1: player going first cannot play a Supporter on their first turn."""
    return bool(going_first) and int(my_turn_number) == 1


def is_pad_legal_target(card_id: int) -> bool:
    return card_id in PAD_SEARCH_IDS and card_id not in RULE_BOX_IDS


def pad_pokemon_candidates(
    *,
    on_field: set[int] | frozenset[int],
    mega_on_field: bool | None = None,
    priority: tuple[int, ...] | None = None,
) -> list[int]:
    """Legal Pad Pokémon targets not already on field, in priority order.

    Energy is never returned (E-PAD-1). If Mega Starmie is on field, Staryu is
    skipped as the opening-line gap is already closed.

    Autopsy 93317659: once the Staryu/Mega attacker line is online and Munk is
    still missing, use POST_MEGA priority (Munk first) instead of opening.
    """
    if mega_on_field is None:
        mega_on_field = MEGA_STARMIE in on_field
    if priority is None:
        line_online = bool(mega_on_field or STARYU in on_field)
        munk_missing = MUNKIDORI not in on_field
        if line_online and munk_missing:
            priority = POKE_PAD_POST_MEGA_PRIORITY
        else:
            priority = POKE_PAD_OPENING_PRIORITY
    out: list[int] = []
    for cid in priority:
        if not is_pad_legal_target(cid):
            continue
        if cid == STARYU and mega_on_field:
            continue
        if cid in on_field:
            continue
        out.append(cid)
    return out
