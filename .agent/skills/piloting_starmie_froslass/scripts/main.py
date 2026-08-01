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
    # Kaggle loads main.py via exec() WITHOUT defining __file__, so we cannot
    # rely on os.path.abspath(__file__). Probe candidate dirs in priority order
    # and return the first that actually contains deck.csv.
    candidates: list[str] = []
    # 1. The directory of this file, when __file__ is defined (local runs).
    try:
        here = os.path.dirname(os.path.abspath(__file__))  # type: ignore[name-defined]
        candidates.append(here)
    except NameError:
        pass
    # 2. Current working directory (Kaggle often chdirs to the agent dir).
    candidates.append(os.path.abspath("."))
    # 3. Entries on sys.path (Kaggle prepends the agent dir for imports).
    candidates.extend(p for p in sys.path if p)
    # 4. Known Kaggle simulation agent roots.
    candidates.extend(["/kaggle_simulations/agent", "/kaggle/working"])
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "deck.csv")):
            return c
    # Last resort: return the most likely Kaggle path so _read_deck fails loudly
    # with a clear FileNotFoundError rather than a NameError.
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
_DIAG_PRINTED = False


def _diag(msg: str) -> None:
    global _DIAG_PRINTED
    if not _DIAG_PRINTED:
        import traceback as _tb
        print(f"[starmie-main] {msg}", file=sys.stderr, flush=True)
        if msg.startswith("ERROR"):
            _tb.print_exc(file=sys.stderr)
    _DIAG_PRINTED = True


def _read_deck() -> list[int]:
    global _DECK
    if _DECK is not None:
        return _DECK
    path = os.path.join(_agent_dir(), "deck.csv")
    ids: list[int] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                ids.append(int(line))
    except Exception:
        _diag(f"ERROR reading deck.csv at {path!r} (agent_dir={_agent_dir()!r}, cwd={os.getcwd()!r})")
        raise
    if len(ids) < 60:
        _diag(f"ERROR deck.csv has {len(ids)} ids at {path!r}, need 60")
        raise ValueError(f"deck.csv has {len(ids)} ids, need 60")
    _DECK = ids[:60]
    _diag(f"OK agent_dir={_agent_dir()!r} deck={len(_DECK)} cards")
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
    except Exception as e:
        # Last-resort fallback: respect the engine's option count.
        import traceback as _tb
        print(f"[starmie-main] agent() primary path failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _tb.print_exc(file=sys.stderr)
        try:
            from cg.api import to_observation_class  # type: ignore
            obs = to_observation_class(obs_dict)
            if obs.select is None:
                return _read_deck()
            n = len(obs.select.option)
            if n == 0:
                return []  # terminal / no-op select — never return a phantom index
            # Prefer maxCount (Poffin allows up to 2); never invent indices.
            try:
                min_c = max(0, int(obs.select.minCount))
                max_c = min(n, int(obs.select.maxCount))
                pick = max_c if max_c >= min_c else min_c
            except Exception:
                pick = min(n, max(1, int(getattr(obs.select, "maxCount", 1) or 1)))
            return list(range(max(0, pick)))
        except Exception as e2:
            print(f"[starmie-main] fallback also failed: {type(e2).__name__}: {e2}", file=sys.stderr, flush=True)
            _tb.print_exc(file=sys.stderr)
            return []


# Pre-build at import time so a cold first call is not timed out on Kaggle.
try:
    _build_agent()
except Exception as _e:
    # Defer to the first agent() call; never crash the module import. Print so
    # Kaggle agent logs surface the cold-start failure cause immediately.
    import traceback as _tb
    print(f"[starmie-main] cold-start _build_agent failed: {type(_e).__name__}: {_e}", file=sys.stderr, flush=True)
    _tb.print_exc(file=sys.stderr)
