"""Kaggle agent entry-point for the Starmie + Froslass dual-Mega deck.

Thin wrapper: all decision logic lives in pilot/starmie_pilot.py (skill scripts).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_PILOT = _ROOT / "pilot"
if str(_PILOT) not in sys.path:
    sys.path.insert(0, str(_PILOT))

from starmie_pilot import DEFAULT_WEIGHTS, make_starmie_agent  # noqa: E402

_AGENT = None


def _agent_dir() -> str:
    return "." if os.path.exists("deck.csv") else "/kaggle_simulations/agent"


def policy_weights() -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    path = os.path.join(_agent_dir(), "weights.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                w[str(k)] = float(v)
    return w


def read_deck() -> list[int]:
    path = os.path.join(_agent_dir(), "deck.csv")
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    return [int(l) for l in lines[:60]]


def _get_agent():
    global _AGENT
    if _AGENT is None:
        _AGENT = make_starmie_agent(read_deck(), policy_weights())
    return _AGENT


def agent(obs_dict: dict[str, Any]) -> list[int]:
    return _get_agent()(obs_dict)
