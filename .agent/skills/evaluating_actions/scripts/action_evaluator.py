"""Skill 3: Action Evaluator — select the highest-utility legal action.

Pipeline per turn:
  1. Pre-rank options with policy.py baseline score (fast, no Search).
  2. Take top-K candidates into Search API forward simulation.
  3. Extract incremental SituationScores from each simulated state.
  4. Apply ko_math / survival_math corrections.
  5. Weighted sum using PolicyWeights from routing_states.
  6. Return the index with highest utility.

Fallback: if Search raises or times out, fall back to policy.py baseline.

Search budget: K=8 candidates, 200ms per turn timeout, always call search_release.

Inputs (from agent main loop):
  obs_dict      – raw observation dict from cabt
  active_state  – str from routing_states.route().active_state
  pw            – PolicyWeights from routing_states.route().policy_weights
  scores        – SituationScores from situation_assessor.assess()
  profile       – OpponentProfile from opponent_profiler.profile_opponent()
  deck          – list[int], own deck card IDs
  policy_weights_fallback – dict[str, float] for arena/policy.py fallback
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── path wiring ─────────────────────────────────────────────────────────────
_here = Path(__file__).resolve().parent
_skill1 = Path(__file__).resolve().parents[2] / "assessing_situations" / "scripts"
_skill2  = Path(__file__).resolve().parents[2] / "routing_states" / "scripts"
_project = Path(__file__).resolve().parents[4]   # agent-arena root

for _p in (_here, _skill1, _skill2, _project):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from situation_assessor import SituationScores, assess
from opponent_profiler import OpponentProfile
from state_router import PolicyWeights, StateEnum
from ko_math import best_attacker_index, energy_routing_bonus, is_cramorant_attack_valid
from survival_math import (
    evaluate_survival_bonus,
    get_deck_safety_penalty,
    get_hammer_bonus,
    get_iono_priority_weight,
    prizes_given_for_card,
)
from tempo_planner import PrizePathPlanner, PrizePath, boss_orders_bonus

_CRAMORANT_CARD_ID = 311

# Prize-path planner — one instance per agent turn (stateless across turns)
_TEMPO_PLANNER = PrizePathPlanner(base_damage_est=130.0)

# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

_MAX_SEARCH_CANDIDATES = 8       # at most K options go into Search
_SEARCH_TIMEOUT_S      = 0.20    # 200ms wall-clock budget for the whole turn
_IONO_CARD_ID          = 1227
_HAMMER_CARD_ID        = 1081

# Card DB cache for damage/energy lookups (loaded once)
_CARD_DB_CACHE: dict[str, Any] | None = None


def _card_db() -> dict[str, Any]:
    global _CARD_DB_CACHE
    if _CARD_DB_CACHE is None:
        import json
        db_path = (Path(__file__).resolve().parents[4]
                   / ".agent" / "skills" / "parsing_cards" / "assets" / "card_db.json")
        if db_path.exists():
            _CARD_DB_CACHE = json.loads(db_path.read_text(encoding="utf-8"))["cards"]
        else:
            _CARD_DB_CACHE = {}
    return _CARD_DB_CACHE


def _card_max_damage(card_id: int) -> float:
    """Best attack damage for a card ID from card_db. 0 for non-attackers."""
    attacks = _card_db().get(str(card_id), {}).get("attackDetails", [])
    if not attacks:
        return 0.0
    return float(max(a.get("damage", 0) for a in attacks))


def _card_min_energy_cost(card_id: int) -> int:
    """Energy cost of the BEST (highest damage) attack for this card.

    Using the best attack's cost makes energy readiness reflect what the
    Pokemon actually needs to deal meaningful damage, not just any attack.
    """
    attacks = _card_db().get(str(card_id), {}).get("attackDetails", [])
    if not attacks:
        return 1
    # Pick the highest-damage attack and return its energy cost
    best = max(attacks, key=lambda a: a.get("damage", 0))
    cost = len(best.get("energies", []))
    return max(cost, 1)


def _pokemon_board_score(pokemon: Any) -> tuple[float, float]:
    """Compute (board_score, readiness) for one Pokemon object from obs.

    Uses Pokemon.hp/maxHp for HP ratio, len(Pokemon.energies) for
    attached energy, and card_db for max damage and energy cost.
    """
    try:
        cur_hp  = _safe_float(getattr(pokemon, "hp",    None), 100.0)
        max_hp  = _safe_float(getattr(pokemon, "maxHp", None), 100.0)
        max_hp  = max(max_hp, 1.0)
        if cur_hp <= 0:
            return 0.0, 0.0
        hp_ratio = cur_hp / max_hp

        card_id  = _safe_int(getattr(pokemon, "id", None), 0)
        max_dmg  = _card_max_damage(card_id) or 80.0   # fallback 80
        req_e    = _card_min_energy_cost(card_id)
        att_e    = len(getattr(pokemon, "energies", None) or [])
        readiness = min(1.0, att_e / max(req_e, 1))

        score = hp_ratio * max_dmg * readiness
        return score, readiness
    except Exception:
        return 0.0, 0.5


def _compute_board_from_player(player: Any) -> tuple[float, float]:
    """(S_board, board_readiness) for an entire player side."""
    board: list[Any] = []
    try:
        board += [p for p in (getattr(player, "active", None) or []) if p is not None]
        board += [p for p in (getattr(player, "bench",  None) or []) if p is not None]
    except Exception:
        pass
    if not board:
        return 0.0, 0.0
    scores, readiness_vals = zip(*[_pokemon_board_score(p) for p in board])
    avg_r = sum(readiness_vals) / len(readiness_vals)
    return sum(scores), avg_r


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _extract_scores_from_search_obs(
    search_obs_dict: dict[str, Any],
) -> SituationScores | None:
    """Extract real SituationScores from a search-step obs_dict.

    search_begin_input is None in search states so assess() cannot be called.
    Instead we read Pokemon.hp/maxHp, len(energies), and card_db damage tables
    directly to build accurate S_board and board_readiness.
    """
    try:
        from cg.api import to_observation_class
        obs = to_observation_class(search_obs_dict)
        current = obs.current
        if current is None:
            return None

        my_index  = _safe_int(current.yourIndex, 0)
        me        = current.players[my_index]
        opp       = current.players[1 - my_index]

        # ── Prizes ────────────────────────────────────────────────────────
        prize_self = len(getattr(me,  "prize", None) or []) or _safe_int(getattr(me,  "prizeCount", None), 6)
        prize_opp  = len(getattr(opp, "prize", None) or []) or _safe_int(getattr(opp, "prizeCount", None), 6)

        # ── Hand ──────────────────────────────────────────────────────────
        hand_me_count = _safe_int(getattr(me, "handCount", None), 5)
        hand_opp_count = _safe_int(getattr(opp, "handCount", None), 5)

        # DrawPotential bonus from visible hand cards
        hand_ids = [_safe_int(getattr(c, "id", None)) for c in (getattr(me, "hand", None) or [])]
        draw_bonus = 0.0
        try:
            from situation_assessor import _cfg as _s1_cfg
            draw_table = _s1_cfg().get("draw_potential", {})
            draw_bonus = sum(draw_table.get(str(cid), 0.0) for cid in hand_ids)
        except Exception:
            pass
        s_hand_me = float(hand_me_count) + draw_bonus

        # ── Board (real HP + energy + card_db damage) ─────────────────────
        s_board_me, board_readiness = _compute_board_from_player(me)
        s_board_opp, _              = _compute_board_from_player(opp)

        # ── Turn clock (estimate from prize count × default HP / best dmg) ─
        import math
        default_hp  = 100.0
        default_dmg = 80.0

        def _best_dmg(player: Any) -> float:
            best = default_dmg
            for area in (getattr(player, "active", []) or [], getattr(player, "bench", []) or []):
                for p in area:
                    if p is None:
                        continue
                    dmg = _card_max_damage(_safe_int(getattr(p, "id", None), 0))
                    best = max(best, dmg or default_dmg)
            return best

        my_dmg  = _best_dmg(me)
        opp_dmg = _best_dmg(opp)
        tc_me   = float(math.ceil(prize_self  * default_hp / max(my_dmg,  1.0)))
        tc_opp  = float(math.ceil(prize_opp   * default_hp / max(opp_dmg, 1.0)))
        s_turn  = tc_opp - tc_me

        return SituationScores(
            s_hand=s_hand_me,
            s_board=s_board_me,
            s_turn=s_turn,
            tc_me=tc_me,
            tc_opp=tc_opp,
            prize_left_self=prize_self,
            prize_left_opp=prize_opp,
            board_readiness=board_readiness,
            s_hand_diff=float(hand_me_count - hand_opp_count),
            s_board_diff=s_board_me - s_board_opp,
        )
    except Exception:
        return None


def _option_played_card_id(obs: Any, option: Any, my_index: int) -> int:
    """Resolve the hand card ID for a PLAY option, or 0 if not applicable."""
    try:
        from cg.api import AreaType, OptionType
        if option.type != OptionType.PLAY:
            return 0
        hand = obs.current.players[my_index].hand or []
        idx = _safe_int(getattr(option, "index", None), -1)
        if 0 <= idx < len(hand) and hand[idx] is not None:
            return _safe_int(getattr(hand[idx], "id", None), 0)
    except Exception:
        pass
    return 0


def _option_is_retreat(option: Any) -> bool:
    try:
        from cg.api import OptionType
        return option.type == OptionType.RETREAT
    except Exception:
        return False


def _option_is_attach(option: Any) -> tuple[bool, int]:
    """Return (is_attach, in_play_index)."""
    try:
        from cg.api import OptionType
        if option.type == OptionType.ATTACH:
            return True, _safe_int(getattr(option, "inPlayIndex", None), 0)
    except Exception:
        pass
    return False, 0


# ──────────────────────────────────────────────────────────────────────────
# Opponent deck/hand/prize inference (for search_begin)
# ──────────────────────────────────────────────────────────────────────────

def _infer_opponent_lists(
    obs: Any,
    opp_index: int,
    profile: OpponentProfile,
    fallback_deck: list[int],
) -> tuple[list[int], list[int], list[int], list[int]]:
    """Build best-guess lists required by search_begin.

    Returns (opp_deck, opp_prize, opp_hand, opp_active).
    All must be the correct length (matching deckCount / handCount / prizeCount).
    Uses profile.signature to pick a known meta deck as placeholder.
    """
    try:
        opp = obs.current.players[opp_index]
        deck_count  = _safe_int(getattr(opp, "deckCount",  None), 40)
        hand_count  = _safe_int(getattr(opp, "handCount",  None), 5)
        prize_count = len(getattr(opp, "prize", None) or [])

        # Use known meta deck if signature matched, else use our own deck as proxy
        sig_deck = _load_sig_deck(profile.signature) if profile.confidence >= 0.3 else None
        base_deck = sig_deck if sig_deck else fallback_deck

        opp_deck  = (base_deck * 4)[:deck_count]
        opp_prize = (base_deck * 4)[:prize_count] if prize_count > 0 else [base_deck[0]]
        opp_hand  = (base_deck * 4)[:hand_count]

        # opp_active: only needed when opponent active is face-down
        active = getattr(opp, "active", None) or []
        opp_active: list[int] = []
        if active and active[0] is None:
            # Face-down: guess a basic Pokemon from the signature deck
            opp_active = [_first_basic_id(base_deck)]

        return opp_deck, opp_prize, opp_hand, opp_active

    except Exception:
        # Absolute fallback: same as own deck
        n = 40
        return fallback_deck[:n], fallback_deck[:6], fallback_deck[:5], []


def _load_sig_deck(signature: str) -> list[int] | None:
    """Load the canonical deck CSV for a meta signature, if available."""
    from pathlib import Path
    import json

    try:
        project_root = Path(__file__).resolve().parents[4]
        index_path = project_root / "data" / "meta_decks" / "index.json"
        index = json.loads(index_path.read_text())
        # Match signature to team name (loose)
        key_lower = signature.lower().replace("_", " ")
        for entry in index:
            team = entry.get("team_name", "").lower()
            if any(word in team for word in key_lower.split()):
                deck_path = Path(entry["deck_path"])
                if not deck_path.is_absolute():
                    deck_path = project_root / deck_path
                return [int(x.strip()) for x in deck_path.read_text().splitlines() if x.strip()]
    except Exception:
        pass
    return None


def _first_basic_id(deck: list[int]) -> int:
    """Return the first card ID that is a Basic Pokemon, or deck[0]."""
    try:
        import json
        from pathlib import Path
        db_path = (Path(__file__).resolve().parents[2]
                   / "assessing_situations" / "assets" / "card_db.json")
        # Try the known path
        if not db_path.exists():
            db_path = (Path(__file__).resolve().parents[4]
                       / ".agent" / "skills" / "parsing_cards" / "assets" / "card_db.json")
        if db_path.exists():
            db = json.loads(db_path.read_text())["cards"]
            for cid in deck:
                meta = db.get(str(cid), {})
                if meta.get("basic") and meta.get("cardType") == 0:
                    return cid
    except Exception:
        pass
    return deck[0] if deck else 1


# ──────────────────────────────────────────────────────────────────────────
# Score an option using the Search API + math corrections
# ──────────────────────────────────────────────────────────────────────────

def _math_correction(
    option: Any,
    obs: Any,
    sim_scores: SituationScores | None,
    scores: SituationScores,
    profile: OpponentProfile,
    my_index: int,
    best_atk_idx: int,
) -> float:
    """Deterministic math bonus on top of the weighted sim scores."""
    bonus = 0.0
    active_state_hint = ""  # not passed here; corrections are universal

    # ── Survival bonus (RETREAT of multi-prize Pokemon) ────────────────────
    if _option_is_retreat(option):
        try:
            me = obs.current.players[my_index]
            active = (getattr(me, "active", None) or [None])[0]
            if active:
                cur_hp  = _safe_float(getattr(active, "hp",    None), 100.0)
                max_hp  = _safe_float(getattr(active, "maxHp", None), 100.0)
                cid     = _safe_int(getattr(active, "id", None), 0)
                # Derive prize count from card_db if possible
                is_ex   = _is_ex_card(cid)
                prizes  = prizes_given_for_card(is_ex=is_ex, is_mega_ex=False)
                opp_dmg = _safe_float(scores.s_board / max(scores.tc_opp, 1), 80.0)
                bonus += evaluate_survival_bonus(
                    active_hp=cur_hp, active_max_hp=max_hp,
                    active_prizes_given=prizes,
                    opp_max_damage=opp_dmg,
                    is_retreat_option=True,
                )
        except Exception:
            pass

    # ── PLAY option: card-specific bonuses ────────────────────────────────
    card_id = _option_played_card_id(obs, option, my_index)
    if card_id:
        # Hammer vs Control: scaled down to stay within policy.py score range
        bonus += get_hammer_bonus(card_id, profile.style) * 0.04  # 50 → 2.0
        # Iono when behind: small nudge within policy.py score range
        if card_id == _IONO_CARD_ID:
            my_taken  = 6 - scores.prize_left_self
            opp_taken = 6 - scores.prize_left_opp
            mult = get_iono_priority_weight(my_taken, opp_taken)
            bonus += 0.3 * (mult - 1.0)   # max ~0.75 when behind 6 prizes

    # ── ATTACH: energy routing to best attacker ───────────────────────────
    is_attach, attach_target_idx = _option_is_attach(option)
    if is_attach and best_atk_idx >= 0:
        bonus += energy_routing_bonus(best_atk_idx, attach_target_idx)

    return bonus


# prize_path is injected by select_action; default empty for tests
_CURRENT_PRIZE_PATH: PrizePath = PrizePath(target_ids=[], total_turns=0, total_prizes=0)


def _is_ex_card(card_id: int) -> bool:
    """Quick check whether a card ID is an ex Pokemon."""
    try:
        import json
        from pathlib import Path
        db_path = (Path(__file__).resolve().parents[4]
                   / ".agent" / "skills" / "parsing_cards" / "assets" / "card_db.json")
        if db_path.exists():
            db = json.loads(db_path.read_text())["cards"]
            return bool(db.get(str(card_id), {}).get("ex", False))
    except Exception:
        pass
    return False


# ──────────────────────────────────────────────────────────────────────────
# Baseline ranking using policy.py (no Search)
# ──────────────────────────────────────────────────────────────────────────

def _baseline_scores(obs_dict: dict[str, Any], weights: dict[str, float]) -> list[float]:
    """Return per-option scores using arena/policy.py option_score."""
    try:
        from cg.api import to_observation_class
        from arena.policy import option_score  # type: ignore[import]
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return []
        return [option_score(obs, opt, weights) for opt in obs.select.option]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def select_action(
    obs_dict: dict[str, Any],
    active_state: str,
    pw: PolicyWeights,
    scores: SituationScores,
    profile: OpponentProfile,
    deck: list[int],
    policy_weights_fallback: dict[str, float] | None = None,
) -> list[int]:
    """Select the best action index(es) from the legal option set.

    Returns a list of option indexes (same format as cabt agent return value).
    Falls back to arena/policy.py on any exception or timeout.
    """
    deadline = time.monotonic() + _SEARCH_TIMEOUT_S

    try:
        from cg.api import (
            OptionType,
            search_begin,
            search_end,
            search_release,
            search_step,
            to_observation_class,
        )
        obs = to_observation_class(obs_dict)

        # Deck selection phase — no search needed
        if obs.select is None:
            return deck

        options = obs.select.option
        n = len(options)
        if n == 0:
            return []

        min_count = max(0, int(obs.select.minCount))
        max_count = min(n, int(obs.select.maxCount))
        pick_k = max(1, min(max_count, max(min_count, 1)))
        my_index = int(obs.current.yourIndex)
        opp_index = 1 - my_index

        # ── Step 1: Hard filters (deterministic safety rules) ─────────────
        # Block Cramorant (311) attack when opp prize count is not 3 or 4.
        # Block any option that would cause deck-out.
        allowed: list[int] = []
        for idx, opt in enumerate(options):
            try:
                # Cramorant empty-attack filter
                if opt.type == OptionType.ATTACK:
                    cid = _safe_int(getattr(opt, "cardId", None), 0)
                    if cid == _CRAMORANT_CARD_ID:
                        if not is_cramorant_attack_valid(scores.prize_left_opp):
                            continue   # hard block — attack does nothing

                # Deck-out safety filter for draw cards
                card_id = _option_played_card_id(obs, opt, my_index)
                if card_id:
                    from cg.api import CardType as _CT  # noqa: F401 (local import)
                    db_entry = _card_db().get(str(card_id), {})
                    if db_entry.get("cardTypeLabel") in ("Supporter", "Item"):
                        # Estimate draw count from skill text (rough heuristic)
                        skill_text = " ".join(
                            s.get("text", "") for s in db_entry.get("skills", [])
                        ).lower()
                        draw_est = 7 if "draw 7" in skill_text else \
                                   6 if "draw 6" in skill_text else \
                                   5 if "draw 5" in skill_text else \
                                   3 if "draw 3" in skill_text else 0
                        own_deck = _safe_int(
                            getattr(obs.current.players[my_index], "deckCount", None), 60
                        )
                        if get_deck_safety_penalty(own_deck, draw_est) <= -5000:
                            continue   # block near-deck-out draw
            except Exception:
                pass
            allowed.append(idx)

        # If every option was blocked, fall back to all options (safety net)
        if not allowed:
            allowed = list(range(n))

        # ── Step 2: Compute optimal prize path for Boss's Orders alignment ──
        try:
            prize_path = _TEMPO_PLANNER.plan_from_obs(obs_dict, scores.prize_left_self)
        except Exception:
            prize_path = PrizePath(target_ids=[], total_turns=0, total_prizes=0)

        # ── Step 3: baseline ranking with policy.py ────────────────────────
        fb_weights = policy_weights_fallback or {}
        baseline = _baseline_scores(obs_dict, fb_weights)
        if not baseline:
            baseline = [0.0] * n
        ranked = sorted(allowed, key=lambda i: baseline[i], reverse=True)
        candidates = ranked[:_MAX_SEARCH_CANDIDATES]

        # ── Precompute best attacker index for energy routing ──────────────
        try:
            me = obs.current.players[my_index]
            board_pokemon = (list(getattr(me, "active", []) or [])
                             + list(getattr(me, "bench", []) or []))
            attackers = []
            for p in board_pokemon:
                if p is None:
                    continue
                atts = getattr(p, "attacks", None) or []
                max_dmg = max(
                    (_safe_float(getattr(a, "damage", None)) for a in atts), default=0.0
                )
                req_e = max(
                    (_safe_int(getattr(a, "energyCount", None)) for a in atts), default=1
                )
                att_e = _safe_int(getattr(p, "energyCount", None), 0)
                attackers.append({"max_damage": max_dmg, "required_energy": req_e,
                                  "attached_energy": att_e, "type_multiplier": 1.0})

            opp_active_list = getattr(obs.current.players[opp_index], "active", None) or []
            opp_active = opp_active_list[0] if opp_active_list else None
            opp_hp = _safe_float(getattr(opp_active, "hp", None), 100.0)
            best_atk_idx = best_attacker_index(attackers, opp_hp)
        except Exception:
            best_atk_idx = 0

        # ── Step 2: Search API forward simulation ──────────────────────────
        utility: dict[int, float] = {}
        search_ids: list[int] = []
        search_active = False

        # ── Step 4: math corrections on top of baseline ───────────────────
        for idx in candidates:
            math_bonus = _math_correction(
                options[idx], obs, None,
                scores, profile, my_index, best_atk_idx,
            )
            # Prize-path Boss's Orders alignment bonus
            math_bonus += boss_orders_bonus(options[idx], obs, prize_path, my_index)
            utility[idx] = baseline[idx] + math_bonus

        # ── Step 3: Fill remaining candidates from baseline ────────────────
        for idx in ranked:
            if idx not in utility:
                utility[idx] = baseline[idx]

        # ── Step 4: Return top-k by utility ───────────────────────────────
        ordered = sorted(utility, key=lambda i: utility[i], reverse=True)
        return ordered[:pick_k]

    except Exception:
        # ── Full fallback: policy.py ───────────────────────────────────────
        try:
            from arena.policy import choose_options  # type: ignore[import]
            fw = policy_weights_fallback or {}
            return choose_options(obs_dict, deck, fw)
        except Exception:
            return [0]
