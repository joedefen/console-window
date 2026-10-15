"""Per-line metadata for ConsoleWindow body/header rows."""

from __future__ import annotations

import difflib
import warnings
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .geometry import AbutSpec


class Context:
    """
    Base class for line metadata/context.

    Provides structured metadata for each line, avoiding the need to parse text.
    Apps can add custom attributes via **kwargs.

    :param genre: Category/type of the line (e.g., 'header', 'app', 'separator')
                  Special genres with uppercase names:
                  - 'DECOR': Visual decorations (separators, headers) - automatically non-pickable
                  - 'TRANSIENT': Conditional/dropdown content shown below parent row
                    Automatically gets abut to keep TRANSIENT rows visible when parent is picked
    :param pickable: Whether this line can be selected in pick mode (default: True)
                     Automatically set to False for uppercase genres
    :param abut: Explicit, engine-consumed visibility constraint (see below).
                 Declared as a real attribute so it appears in the schema.
    :param kwargs: Custom attributes to attach to this context.  A keyword that
                   closely resembles a known attribute (``genre``/``pickable``/
                   ``abut``) emits a :class:`UserWarning`, since it is almost
                   certainly a typo that would otherwise fail silently.
    :type genre: str
    :type pickable: bool

    **Special attributes for pick_mode:**

    :param abut: Defines visible line range around picked line in pick_mode.
                 When set, only lines within [picked_line + before, picked_line + after] are visible.
                 "After" lines are prioritized when the range exceeds the viewport.

                 Formats:
                   - Negative int: lines before (e.g., abut=-3 shows 3 before, 0 after)
                   - Positive int: lines after (e.g., abut=7 shows 0 before, 7 after)
                   - List/tuple: [before, after] (e.g., abut=[-5, 3] shows 5 before, 3 after)
                   - Mixed list: min negative and max positive values are used
                     (e.g., abut=[-8, 3, -2, 12] → before=-8, after=12)

    Example::

        ctx = Context(genre='app', pickable=True,
                      app_name='firefox', installed=True, version='1.2.3')
        win.add_body("Firefox 1.2.3", context=ctx)

        # Later retrieve without parsing:
        ctx = win.get_picked_context()
        if ctx and ctx.genre == 'app':
            print(f"Selected: {ctx.app_name}")

        # Example with abut to limit visible context:
        ctx = Context(genre='result', pickable=True, abut=[-10, 20])
        win.add_body("Search result", context=ctx)
        # When this line is picked, only 10 lines before and 20 after are visible
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
            near = difflib.get_close_matches(key, self.KNOWN_ATTRS, n=1, cutoff=0.8)
            if near:
                warnings.warn(
                    f'Context: unknown attribute {key!r} closely matches '
                    f'{near[0]!r} (did you mean {near[0]!r}?)',
                    stacklevel=2,
                )
            setattr(self, key, value)
