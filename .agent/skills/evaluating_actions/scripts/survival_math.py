"""Survival & disruption math engine for Skill 3: evaluating_actions.

Implements two models from agent_design_spec.md §5.2:

B. Survival_Bonus — reward retreating a low-HP multi-prize Pokemon
   before it gets knocked out and donates 2+ prizes.

   Survival_Bonus = BIG × I(opp_cannot_win_this_turn_after_retreat)

C. Iono_Priority — dynamically raise the value of Iono (card 1227)
   when falling behind on prizes.

   iono_mult = 1 + λ × max(0, opp_prize_taken - my_prize_taken) / 6

No cg.api dependency. All inputs are plain Python values.
"""

from __future__ import annotations

_SURVIVAL_BONUS_VALUE    = 1000.0   # high enough to override normal scoring
_IONO_LAMBDA_DEFAULT     = 2.5
_IONO_CARD_ID            = 1227
_HAMMER_CARD_ID          = 1081
_HAMMER_VS_CONTROL_BONUS = 50.0

# ──────────────────────────────────────────────────────────────────────────
# B. Survival bonus
# ──────────────────────────────────────────────────────────────────────────

def evaluate_survival_bonus(
    active_hp: float,
    active_max_hp: float,
    active_prizes_given: int,
    opp_max_damage: float,
    is_retreat_option: bool,
) -> float:
    """Return Survival_Bonus for a retreat option.

    Logic:
      - Only applies to RETREAT options.
      - Active Pokemon must give > 1 prize (ex or Mega ex).
      - Opponent's best damage >= active_hp  (would KO next turn without retreat).
      - Post-retreat the opponent cannot immediately win (assumed: there is a
        bench Pokemon to send out, captured by `has_bench_backup`).

    Args:
        active_hp:           Current HP of our active Pokemon.
        active_max_hp:       Max HP.
        active_prizes_given: Prizes opponent takes if KO'd (1 for normal, 2 for ex, 3 for Mega ex).
        opp_max_damage:      Highest damage the opponent can deal next turn.
        is_retreat_option:   True only when scoring a RETREAT option.

    Returns:
        _SURVIVAL_BONUS_VALUE if retreat saves a multi-prize Pokemon from KO, else 0.0.
    """
    if not is_retreat_option:
        return 0.0
    if active_prizes_given <= 1:
        return 0.0
    if active_hp <= 0:
        return 0.0
    # Opponent would KO us next turn
    would_be_koed = opp_max_damage >= active_hp
    if not would_be_koed:
        return 0.0
    return _SURVIVAL_BONUS_VALUE


def prizes_given_for_card(is_ex: bool, is_mega_ex: bool) -> int:
    """Helper: how many prizes does this Pokemon give when KO'd."""
    if is_mega_ex:
        return 3
    if is_ex:
        return 2
    return 1


# ──────────────────────────────────────────────────────────────────────────
# C. Iono priority weight
# ──────────────────────────────────────────────────────────────────────────

def get_iono_priority_weight(
    my_prize_taken: int,
    opp_prize_taken: int,
    lmbda: float = _IONO_LAMBDA_DEFAULT,
) -> float:
    """Iono (1227) score multiplier when trailing on prizes.

    Formula:
        iono_mult = 1 + λ × max(0, opp_prize_taken - my_prize_taken) / 6

    Returns a multiplier >= 1.0. Equal to 1.0 when not behind.
    """
    deficit = max(0, opp_prize_taken - my_prize_taken)
    return 1.0 + lmbda * deficit / 6.0


# ──────────────────────────────────────────────────────────────────────────
# D. Enhanced Hammer vs Control bonus
# ──────────────────────────────────────────────────────────────────────────

def get_deck_safety_penalty(current_deck_size: int, draw_count: int) -> float:
    """Prevent self-deck-out by penalising draw actions that would empty the deck.

    In cabt the losing condition triggers when a player must draw but can't.
    Penalty tiers (additive, not multiplied):
      remaining ≤ 0  → -100000  (certain loss — hard block)
      remaining ≤ 3  → -5000    (near-certain loss — strong deterrent)
      remaining ≤ 5  → -500     (risky — soft deterrent)
      otherwise      → 0.0

    Args:
        current_deck_size: Cards left in own deck before drawing.
        draw_count:        Number of cards this action would draw.
    """
    remaining = current_deck_size - draw_count
    if remaining <= 0:
        return -100_000.0
    if remaining <= 3:
        return -5_000.0
    if remaining <= 5:
        return -500.0
    return 0.0


def get_hammer_bonus(
    played_card_id: int,
    opp_style: str,
) -> float:
    """Return Enhanced Hammer (1081) bonus vs Control archetype.

    Logic from ptcg_dimension_theory.md §3:
    Hammer removes the special energy that Control decks depend on,
    directly inverting the counter-chain.
    """
    if played_card_id == _HAMMER_CARD_ID and opp_style == "Control":
        return _HAMMER_VS_CONTROL_BONUS
    return 0.0
