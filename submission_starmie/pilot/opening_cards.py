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
UNFAIR_STAMP = 1080
WALLYS_COMPASSION = 1229
SWITCH = 1123
RISKY_RUINS = 1260
NIGHT_STRETCHER = 1097

BASIC_IDS = frozenset({
    STARYU, SNORUNT, MUNKIDORI, FAN_ROTOM, BUDEW,
    DUNSPARCE_A, DUNSPARCE_B, MEOWTH_EX,
})

WATER_ENERGY_IDS = frozenset({WATER_BASIC, PRISM})
ENERGY_IDS = frozenset({WATER_BASIC, DARK_BASIC, PRISM, IGNITION})
# Crispin (E-CRIS-1): Basic Energy only — not Prism / Ignition
CRISPIN_BASIC_ENERGY = (WATER_BASIC, DARK_BASIC)

SUPPORTER_IDS = frozenset({
    HILDA, LILLIE, CRISPIN, SALVATOR, 1182, 1213, 1229,
})

ITEM_IDS = frozenset({POFFIN, ULTRA_BALL, POKE_PAD, 1097, 1080, SWITCH})

# Fan Call: {C} Basic Pokémon HP≤100 only — NOT Water/Grass (E-FAN-C1)
FAN_CALL_IDS = frozenset({FAN_ROTOM, DUNSPARCE_A, DUNSPARCE_B})
FAN_CALL_PRIORITY = (DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM)

POFFIN_IDS = frozenset({STARYU, SNORUNT, BUDEW, DUNSPARCE_A, DUNSPARCE_B, FAN_ROTOM})

# OPENING Poffin pick order (E-POFF-2): not deck-top order
POFFIN_OPENING_PRIORITY = (
    STARYU, FAN_ROTOM, DUNSPARCE_A, DUNSPARCE_B, BUDEW, SNORUNT,
)

# Meowth Last-Ditch OPENING targets (E-MEOW-2)
MEOWTH_OPENING_SUPPORTER_PRIORITY = (HILDA, CRISPIN, SALVATOR)

# Meowth Last-Ditch CONTROL targets (链 E)
MEOWTH_CONTROL_SUPPORTER_PRIORITY = (BOSS_ORDERS, JUDGE, CRISPIN, LILLIE)

# Pokémon ex / V — Poké Pad cannot search (Rule Box)
RULE_BOX_IDS = frozenset({MEGA_STARMIE, MEGA_FROSLASS, MEOWTH_EX, DUDUNSPARCE_EX})

# Poké Pad: deck Pokémon without Rule Box (E-PAD-1)
PAD_SEARCH_IDS = frozenset({
    STARYU, SNORUNT, MUNKIDORI, FAN_ROTOM, BUDEW,
    DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE, FROSLASS,
})

# Hilda: Evolution Pokémon only — never Basic (E-HILDA-1)
HILDA_EVOLUTION_IDS = frozenset({MEGA_STARMIE, MEGA_FROSLASS, FROSLASS, DUDUNSPARCE, DUDUNSPARCE_EX})
HILDA_EVOLUTION_PRIORITY = (
    MEGA_STARMIE, MEGA_FROSLASS, FROSLASS, DUDUNSPARCE, DUDUNSPARCE_EX,
)

# Retreat cost in {C} energy cards required to retreat
RETREAT_COST: dict[int, int] = {
    MEGA_STARMIE: 2,
    STARYU: 1, SNORUNT: 1, MUNKIDORI: 1, MEOWTH_EX: 1,
    FAN_ROTOM: 1, BUDEW: 1, DUNSPARCE_A: 1, DUNSPARCE_B: 1,
    DUDUNSPARCE: 2, FROSLASS: 1, MEGA_FROSLASS: 1,
}

EVOLVES_TO = {STARYU: MEGA_STARMIE}

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


def is_pad_legal_target(card_id: int) -> bool:
    return card_id in PAD_SEARCH_IDS and card_id not in RULE_BOX_IDS
