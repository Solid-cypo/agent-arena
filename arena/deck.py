"""Load deck lists for local arena runs."""

from __future__ import annotations

from pathlib import Path


def load_deck_csv(path: Path | str) -> list[int]:
    deck_path = Path(path)
    ids: list[int] = []
    for line_no, line in enumerate(deck_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            ids.append(int(stripped))
        except ValueError as exc:
            raise ValueError(f"{deck_path}:{line_no}: invalid card id {stripped!r}") from exc
    if len(ids) != 60:
        raise ValueError(f"{deck_path}: expected 60 card IDs, found {len(ids)}")
    return ids
