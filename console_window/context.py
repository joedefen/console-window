from __future__ import annotations

import difflib
import warnings
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .geometry import AbutSpec


class Context:
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
            near = difflib.get_close_matches(key, self.KNOWN_ATTRS, n=1, cutoff=0.8)
            if near:
                warnings.warn(
                    f'Context: unknown attribute {key!r} closely matches '
                    f'{near[0]!r} (did you mean {near[0]!r}?)',
                    stacklevel=2,
                )
            setattr(self, key, value)
