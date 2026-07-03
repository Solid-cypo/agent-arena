"""Kaggle cabt agent entry for the Starmie+Froslass dual-Mega pilot.

Kaggle calls `agent(obs_dict) -> list[int]`. We build the deck-specific pilot
from `pilot/starmie_pilot.py` (which already integrates the opening_planner
route into cabt option scoring) and forward every observation to it.

Assets (next to this main.py on the Kaggle agent dir):
  - deck.csv      60 card ids (comment lines starting with # are skipped)
  - weights.json  soft-dim weights for the pilot
  - pilot/        the pilot package
  - cg/           the cabt engine bindings (libcg.so / cg.dll)
"""
import json
import os
import sys


def _agent_dir() -> str:
    # Anchor to the directory containing this main.py: works both locally
    # (submission_starmie/) and on Kaggle (/kaggle_simulations/agent/).
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(here, "deck.csv")):
        return here
    # Fallbacks for unusual CWDs.
    if os.path.exists(os.path.join(".", "deck.csv")):
        return "."
    return "/kaggle_simulations/agent"


def _bootstrap_path() -> None:
    base = _agent_dir()
    pilot_dir = os.path.join(base, "pilot")
    if os.path.isdir(pilot_dir) and pilot_dir not in sys.path:
        sys.path.insert(0, pilot_dir)
    if base not in sys.path:
        sys.path.insert(0, base)


_BOOTSTRAPPED = False
_DECK: list[int] | None = None
_WEIGHTS: dict | None = None
_AGENT = None


def _read_deck() -> list[int]:
    global _DECK
    if _DECK is not None:
        return _DECK
    path = os.path.join(_agent_dir(), "deck.csv")
    ids: list[int] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(int(line))
    if len(ids) < 60:
        raise ValueError(f"deck.csv has {len(ids)} ids, need 60")
    _DECK = ids[:60]
    return _DECK


def _read_weights() -> dict:
    global _WEIGHTS
    if _WEIGHTS is not None:
        return _WEIGHTS
    path = os.path.join(_agent_dir(), "weights.json")
    _WEIGHTS = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            _WEIGHTS = json.load(handle)
    return _WEIGHTS


def _build_agent():
    global _AGENT, _BOOTSTRAPPED
    if _AGENT is not None:
        return _AGENT
    if not _BOOTSTRAPPED:
        _bootstrap_path()
        _BOOTSTRAPPED = True
    from starmie_pilot import make_starmie_agent  # noqa: E402
    _AGENT = make_starmie_agent(_read_deck(), _read_weights())
    return _AGENT


def agent(obs_dict: dict) -> list[int]:
    """Kaggle entry: return selected option indices (or the deck on setup)."""
    try:
        return _build_agent()(obs_dict)
    except Exception:
        # Last-resort fallback: respect the engine's option count.
        try:
            from cg.api import to_observation_class  # type: ignore
            obs = to_observation_class(obs_dict)
            if obs.select is None:
                return _read_deck()
            n = len(obs.select.option)
            if n == 0:
                return []  # terminal / no-op select — never return a phantom index
            pick = max(1, min(n, int(obs.select.maxCount)))
            return list(range(pick))
        except Exception:
            return []


# Pre-build at import time so a cold first call is not timed out on Kaggle.
try:
    _build_agent()
except Exception:
    # Defer to the first agent() call; never crash the module import.
    pass
