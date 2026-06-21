"""KO Efficiency math engine for Skill 3: evaluating_actions.

Implements the formula from agent_design_spec.md §5.2 A:

    KO_Efficiency(P_i) = (MaxDmg(P_i) × TypeMult) / OppActiveHP
                         × 1 / (1 + ΔE)

where ΔE = max(0, required_energy - attached_energy)

Used in SETTING_UP_BOARD state to route energy to the highest-efficiency attacker.

All inputs are plain Python values (no cg.api objects required).
"""

from __future__ import annotations


def calculate_ko_efficiency(
    max_damage: float,
    opp_active_hp: float,
    required_energy: int,
    attached_energy: int,
    type_multiplier: float = 1.0,
) -> float:
    """Compute KO efficiency for one attacker against the active opponent.

    Args:
        max_damage:      Best attack damage of the attacker Pokemon.
        opp_active_hp:   Current HP of the opponent's active Pokemon.
        required_energy: Attack energy cost.
        attached_energy: Energy currently on this attacker.
        type_multiplier: 2.0 for weakness hit, 0.5 for resistance, 1.0 default.

    Returns:
        KO_Efficiency score. Higher = better attacker to invest in.
        0.0 if opp_active_hp or max_damage is zero.
    """
    if opp_active_hp <= 0 or max_damage <= 0:
        return 0.0

    delta_e = max(0, required_energy - attached_energy)
    efficiency = (max_damage * type_multiplier) / opp_active_hp
    efficiency /= (1.0 + delta_e)
    return efficiency


def best_attacker_index(
    attackers: list[dict],
    opp_active_hp: float,
) -> int:
    """Return index into `attackers` of the most efficient attacker.

    Each attacker dict must have keys:
      max_damage (float), required_energy (int), attached_energy (int),
      type_multiplier (float, optional, default 1.0)

    Args:
        attackers:    List of attacker parameter dicts (active first).
        opp_active_hp: Current HP of the opponent's active Pokemon.

    Returns:
        Index of best attacker, or 0 if list is empty.
    """
    if not attackers:
        return 0
    scores = [
        calculate_ko_efficiency(
            max_damage=a.get("max_damage", 0.0),
            opp_active_hp=opp_active_hp,
            required_energy=a.get("required_energy", 1),
            attached_energy=a.get("attached_energy", 0),
            type_multiplier=a.get("type_multiplier", 1.0),
        )
        for a in attackers
    ]
    return max(range(len(scores)), key=lambda i: scores[i])


def energy_routing_bonus(
    attacker_idx: int,
    option_target_idx: int,
    base_bonus: float = 0.4,
) -> float:
    """Bonus for attaching energy to the recommended attacker.

    Small nudge toward the best attacker. Must stay within policy.py score
    range (~0-5) so it doesn't override the option_score baseline ranking.
    """
    return base_bonus if option_target_idx == attacker_idx else 0.0
