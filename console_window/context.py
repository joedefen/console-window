from __future__ import annotations

import difflib
import warnings
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .geometry import AbutSpec


class Context:
    """Per-row metadata read by the pick engine.

    Only ``genre``, ``pickable`` and ``abut`` are consumed by the engine; any
    other attribute is app vocabulary, stored as given.

    Args:
        genre: Row genre; ``'DECOR'`` forces it unpickable, ``'TRANSIENT'``
            stays navigable but is expected to be short-lived.
        pickable: Whether pick mode may land on the row.
        abut: Abutment spec from ``console_window.geometry``, or ``None``.
        **kwargs: Extra attributes stored verbatim; a name close to a known
            attribute warns instead of failing silently.
    """

    # Engine-consumed attribute names.  A custom kwarg that closely matches one of
    # these is treated as a likely typo and warns rather than failing silently.
    KNOWN_ATTRS: ClassVar[frozenset[str]] = frozenset({'genre', 'pickable', 'abut'})

    def __init__(self, genre: str = '', pickable: bool = True,
                 abut: AbutSpec = None, **kwargs: object) -> None:
        self.genre = genre
        self.abut = abut
        # Auto-set pickable=False only for DECOR genre
        # TRANSIENT is navigable but ephemeral (handled by app logic)
        if genre == 'DECOR':
            self.pickable = False
        else:
            self.pickable = pickable
        # Allow apps to add custom attributes, but warn on a likely typo of a
        # known attribute (e.g. 'abutt' for 'abut'): such a name would otherwise
        # be attached silently and never read by the engine.
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
    # Advisory typo detection only depends on the attribute name, not its value.
    # Apps construct one Context per row, so without this cache difflib scans
    # the same custom names thousands of times per redraw (info, item, ...).
    matches = difflib.get_close_matches(key, known_attrs, n=1, cutoff=0.8)
    return matches[0] if matches else None
