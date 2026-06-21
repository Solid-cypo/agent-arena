"""FSM-Math agent: three-Skill pipeline with policy.py fallback.

Decision chain per turn:
  Skill 1  situation_assessor.assess()     → SituationScores
  Skill 1  opponent_profiler.profile_opp() → OpponentProfile
  Skill 2  state_router.route()            → active_state + PolicyWeights
  Skill 3  action_evaluator.select_action() → action index list

Falls back to arena/policy.py at any layer on exception.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

# ── path wiring ──────────────────────────────────────────────────────────────
_PROJECT = Path(__file__).resolve().parents[1]
_SKILL_SCRIPTS = {
    "s1": _PROJECT / ".agent/skills/assessing_situations/scripts",
    "s2": _PROJECT / ".agent/skills/routing_states/scripts",
    "s3": _PROJECT / ".agent/skills/evaluating_actions/scripts",
}
for _p in _SKILL_SCRIPTS.values():
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from arena.policy import AgentFn, DEFAULT_WEIGHTS, choose_options

# Lazy imports: Skills are only imported when make_fsm_agent() is first called,
# keeping module load fast when only policy.py is needed.
_situation_assessor = None
_opponent_profiler  = None
_state_router       = None
_action_evaluator   = None


def _load_skills() -> None:
    global _situation_assessor, _opponent_profiler, _state_router, _action_evaluator
    if _situation_assessor is not None:
        return
    import situation_assessor as _sa
    import opponent_profiler as _op
    import state_router as _sr
    import action_evaluator as _ae
    _situation_assessor = _sa
    _opponent_profiler  = _op
    _state_router       = _sr
    _action_evaluator   = _ae


# ──────────────────────────────────────────────────────────────────────────
# Public factory
# ──────────────────────────────────────────────────────────────────────────

def make_fsm_agent(
    deck: list[int],
    weights_fallback: dict[str, float] | None = None,
) -> AgentFn:
    """Return an agent function that uses the FSM-Math pipeline.

    Args:
        deck:             60-card deck list for deck-selection phase.
        weights_fallback: policy.py weights used as fallback and for baseline
                          ranking inside action_evaluator.

    Returns:
        An agent(obs_dict) → list[int] callable compatible with simulator.py.
    """
    _load_skills()
    fw = dict(DEFAULT_WEIGHTS if weights_fallback is None else weights_fallback)

    def agent(obs_dict: dict[str, Any]) -> list[int]:
        # Deck-selection phase: no observation yet
        if obs_dict.get("select") is None:
            return deck

        # ── Skill 1: assess ───────────────────────────────────────────────
        try:
            scores = _situation_assessor.assess(obs_dict)
        except Exception:
            return _fallback(obs_dict, deck, fw)

        # ── Skill 1: profile opponent ─────────────────────────────────────
        try:
            profile = _opponent_profiler.profile_opponent(obs_dict)
        except Exception:
            from opponent_profiler import _UNKNOWN
            profile = _UNKNOWN

        # ── Skill 2: route ────────────────────────────────────────────────
        try:
            result = _state_router.route(scores, profile)
            active_state = result.active_state
            pw = result.policy_weights
        except Exception:
            return _fallback(obs_dict, deck, fw)

        # ── Skill 3: select action ────────────────────────────────────────
        try:
            return _action_evaluator.select_action(
                obs_dict=obs_dict,
                active_state=active_state,
                pw=pw,
                scores=scores,
                profile=profile,
                deck=deck,
                policy_weights_fallback=fw,
            )
        except Exception:
            return _fallback(obs_dict, deck, fw)

    return agent


def _fallback(
    obs_dict: dict[str, Any],
    deck: list[int],
    weights: dict[str, float],
) -> list[int]:
    """policy.py baseline fallback."""
    try:
        return choose_options(obs_dict, deck, weights)
    except Exception:
        return [0]
