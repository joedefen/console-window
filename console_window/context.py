"""Per-row metadata read by the pick engine."""

from __future__ import annotations

import difflib
import warnings
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .geometry import AbutSpec


class Context:
    """Per-row metadata read by the pick engine.

    Only `genre`, `pickable` and `abut` are consumed by the engine; other
    attributes are app vocabulary, stored as given.

    Args:
        genre: `'DECOR'` forces `pickable` off; `'TRANSIENT'` marks a
            short-lived but navigable row.
        pickable: Whether pick mode may land on the row.
        abut: Abutment spec from `console_window.geometry`.
        **kwargs: Extra attributes stored verbatim; a name close to a known
            attribute warns rather than failing silently.
    """

    KNOWN_ATTRS: ClassVar[frozenset[str]] = frozenset({'genre', 'pickable', 'abut'})

    def __init__(self, genre: str = '', pickable: bool = True,
                 abut: AbutSpec = None, **kwargs: object) -> None:
        self.genre = genre
        self.abut = abut
        if genre == 'DECOR':
            self.pickable = False
        else:
            self.pickable = pickable
        for key, value in kwargs.items():
            near = _near_miss(key, self.KNOWN_ATTRS)
            if near is not None:
                warnings.warn(
                    f'Context: unknown attribute {key!r} closely matches '
                    f'{near!r} (did you mean {near!r}?)',
                    stacklevel=2,
                )
            setattr(self, key, value)


@lru_cache(maxsize=256)
def _near_miss(key: str, known_attrs: frozenset[str]) -> str | None:
    # Cached: rows are constructed in bulk and difflib is the hot path.
    matches = difflib.get_close_matches(key, known_attrs, n=1, cutoff=0.8)
    return matches[0] if matches else None
