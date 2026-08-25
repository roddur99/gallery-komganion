from __future__ import annotations

import re
from pathlib import Path

type NaturalSegment = tuple[int, str | int]
type NaturalSortKey = tuple[NaturalSegment, ...]

_DIGIT_PATTERN = re.compile(r"(\d+)")


def natural_sort_key(value: str | Path) -> NaturalSortKey:
    """Create a case-insensitive key that sorts digit groups numerically."""

    name = value.name if isinstance(value, Path) else value
    segments: list[NaturalSegment] = []

    for segment in _DIGIT_PATTERN.split(name.casefold()):
        if not segment:
            continue

        if segment.isdigit():
            segments.append((1, int(segment)))
        else:
            segments.append((0, segment))

    # The final segment makes ties deterministic, such as 2.jpg and 02.jpg.
    segments.append((2, name.casefold()))

    return tuple(segments)


def naturally_sorted[T: str | Path](
    values: list[T],
) -> list[T]:
    return sorted(values, key=natural_sort_key)
