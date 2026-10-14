"""Per-line metadata for ConsoleWindow body/header rows."""


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
    :param kwargs: Custom attributes to attach to this context
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
    def __init__(self, genre='', pickable=True, **kwargs):
        self.genre = genre
        # Auto-set pickable=False only for DECOR genre
        # TRANSIENT is navigable but ephemeral (handled by app logic)
        if genre == 'DECOR':
            self.pickable = False
        else:
            self.pickable = pickable
        # Allow apps to add custom attributes
        for key, value in kwargs.items():
            setattr(self, key, value)
