#!/usr/bin/env python3
"""Quick RSS snapshot for arena/marathon processes."""

from __future__ import annotations

import argparse
import resource
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes; macOS reports bytes.
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure process RSS after a tiny arena workload.")
    parser.add_argument("--games", type=int, default=4)
    args = parser.parse_args()

    from arena.policy import card_meta_table
    from arena.simulator import run_self_play_batch
    from arena.deck import load_deck_csv

    baseline = rss_mb()
    card_meta_table()
    after_cards = rss_mb()
    deck_a = load_deck_csv(PROJECT_ROOT / "data/decks/starmie_froslass.csv")
    deck_b = load_deck_csv(PROJECT_ROOT / "data/decks/walrein_control.csv")
    run_self_play_batch(
        deck_a,
        deck_b,
        games=args.games,
        record_trajectories=True,
        store_metadata=False,
    )
    after_play = rss_mb()
    print(
        {
            "rss_mb_baseline": round(baseline, 2),
            "rss_mb_after_card_meta": round(after_cards, 2),
            "rss_mb_after_play": round(after_play, 2),
            "games": args.games,
        }
    )


if __name__ == "__main__":
    main()
