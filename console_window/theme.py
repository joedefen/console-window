from __future__ import annotations

import curses
from typing import ClassVar


class Theme:
    # Semantic color-pair IDs.  The pairs themselves are (re)initialized per theme
    # by Theme.set() and, at startup, by ConsoleWindow.start_curses().
    DEFAULT = 0      # Default terminal colors
    DANGER = 1       # For destructive operations (wipe prompts)
    SUCCESS = 2      # For completed operations
    WARNING = 3      # For caution/stopped states
    INFO = 4         # For informational states
    EMPHASIS = 5     # For emphasized text
    ERROR = 6        # For errors
    PROGRESS = 7     # For progress indicators
    HOTSWAP = 9      # For newly inserted devices (hot-swapped)
    OLD_SUCCESS = 10 # For completed operations (dimmer)

    # The pair used for the theme's default fg/bg (screen and pad background).
    # It is not a semantic role, but it shares the pair-id space above and used
    # to be the bare literal ``8`` in two places.
    DEFAULT_BG = 8

    # The semantic roles, in initialisation order.  Both startup
    # (ConsoleWindow._init_screen) and Theme.set() reinitialise exactly this set,
    # so the two paths cannot drift apart: startup used to omit OLD_SUCCESS,
    # leaving it on an uninitialised pair until a theme change.
    SEMANTIC_PAIRS: ClassVar[tuple[int, ...]] = (
        DANGER, SUCCESS, OLD_SUCCESS, WARNING, INFO, EMPHASIS, ERROR, PROGRESS, HOTSWAP,
    )

    # Process default theme name.  It seeds a new window's own ``theme``
    # (ConsoleWindow.theme) and receives the most recently applied theme, so
    # windows created later inherit it.  The authoritative choice for a running
    # window is that window's attribute: curses owns one pair table per terminal,
    # so *applying* a theme is still terminal-global, but two windows no longer
    # have to disagree about which theme they are on (AUDIT.md §3.1).
    _current: ClassVar[str | None] = None

    # Available themes
    THEMES: ClassVar[dict] = {
        'dark-mono': {
            'name': 'Dark Mono',
            'default_fg': 253,
            'default_bg': 232,
            1: (196, 232),  # DANGER
            2: (46, 232),   # SUCCESS - Bright green
            10: (28, 232),  # OLD_SUCCESS - Medium green, darker than SUCCESS but not too dark
            3: (226, 232),  # WARNING
            4: (51, 232),   # INFO
            5: (255, 232),  # EMPHASIS
            6: (196, 232),  # ERROR
            7: (39, 232),   # PROGRESS
            9: (208, 232),  # HOTSWAP
        },
        'light-mono': {
            'name': 'Light Mono',
            'default_fg': 233,
            'default_bg': 253,
            1: (196, 253),  # DANGER
            2: (34, 253),   # SUCCESS - Bright visible green on light background
            10: (22, 253),  # OLD_SUCCESS - Darker muted green, clearly darker than SUCCESS
            3: (208, 253),  # WARNING
            4: (25, 253),   # INFO
            5: (232, 253),  # EMPHASIS
            6: (196, 253),  # ERROR
            7: (27, 253),   # PROGRESS
            9: (166, 253),  # HOTSWAP
        },
        'default': {
            'name': 'Terminal Default',
            'default_fg': -1,
            'default_bg': -1,
            1: (1, -1),   # DANGER
            2: (2, -1),   # SUCCESS - Standard green
            10: (28, -1), # OLD_SUCCESS - Medium green, dimmer than bright SUCCESS
            3: (3, -1),   # WARNING
            4: (6, -1),   # INFO
            5: (7, -1),   # EMPHASIS
            6: (9, -1),   # ERROR
            7: (4, -1),   # PROGRESS
            9: (208, -1), # HOTSWAP
        },
        'solarized-dark': {
            'name': 'Solarized Dark',
            'default_fg': 244,
            'default_bg': 234,
            1: (160, 234),  # DANGER
            2: (70, 234),   # SUCCESS - Brighter solarized green, clearly bright
            10: (28, 234),  # OLD_SUCCESS - Darker muted green, clearly dimmer than SUCCESS
            3: (136, 234),  # WARNING
            4: (37, 234),   # INFO
            5: (230, 234),  # EMPHASIS
            6: (196, 234),  # ERROR
            7: (33, 234),   # PROGRESS
            9: (166, 234),  # HOTSWAP
        },
        'solarized-light': {
            'name': 'Solarized Light',
            'default_fg': 240,
            'default_bg': 230,
            1: (160, 230),  # DANGER
            2: (70, 230),   # SUCCESS - Brighter solarized green, clearly bright
            10: (28, 230),  # OLD_SUCCESS - Darker muted green, clearly dimmer than SUCCESS
            3: (166, 230),  # WARNING
            4: (37, 230),   # INFO
            5: (235, 230),  # EMPHASIS
            6: (196, 230),  # ERROR
            7: (33, 230),   # PROGRESS
            9: (208, 230),  # HOTSWAP
        },
        'gruvbox': {
            'name': 'Gruvbox Dark',
            'default_fg': 223,
            'default_bg': 235,
            1: (167, 235),  # DANGER
            2: (142, 235),  # SUCCESS - Gruvbox green
            10: (106, 235), # OLD_SUCCESS - Gruvbox medium green (dimmer)
            3: (214, 235),  # WARNING
            4: (109, 235),  # INFO
            5: (229, 235),  # EMPHASIS
            6: (203, 235),  # ERROR
            7: (109, 235),  # PROGRESS
            9: (208, 235),  # HOTSWAP
        },
        'nord': {
            'name': 'Nord',
            'default_fg': 252,
            'default_bg': 236,
            1: (203, 236),  # DANGER
            2: (150, 236),  # SUCCESS - Nord aurora green, bright
            10: (114, 236), # OLD_SUCCESS - Nord frost green (dimmer), darker but not too dark
            3: (220, 236),  # WARNING
            4: (116, 236),  # INFO
            5: (231, 236),  # EMPHASIS
            6: (203, 236),  # ERROR
            7: (136, 236),  # PROGRESS
            9: (208, 236),  # HOTSWAP
        },
    }

    @classmethod
    def resolve(cls, theme_name: str | None) -> str:
        """Return *theme_name* if it names a theme, else ``'default'``."""
        if theme_name and theme_name in cls.THEMES:
            return theme_name
        return 'default'

    @classmethod
    def get_current(cls) -> str | None:
        return cls._current

    @classmethod
    def pair_specs(cls, theme_name: str | None) -> list[tuple[int, int, int]]:
        """``(pair_id, fg, bg)`` for every pair *theme_name* defines.

        ``DEFAULT_BG`` comes first (the screen and pad background), then the
        semantic roles in ``SEMANTIC_PAIRS`` order.  Startup
        (``ConsoleWindow._init_screen``), :meth:`set` and
        ``ConsoleWindow.set_theme`` all install colours from this one list, so
        the paths cannot drift apart.
        """
        theme = cls.THEMES[cls.resolve(theme_name)]
        specs: list[tuple[int, int, int]] = []
        if 'default_fg' in theme and 'default_bg' in theme:
            specs.append((cls.DEFAULT_BG, theme['default_fg'], theme['default_bg']))
        for color_id in cls.SEMANTIC_PAIRS:
            if color_id in theme:
                fg, bg = theme[color_id]
                specs.append((color_id, fg, bg))
        return specs

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls.THEMES.keys())

    @classmethod
    def set(cls, theme_name: str) -> bool:
        if theme_name not in cls.THEMES:
            return False

        if not curses.has_colors():
            return False

        cls._current = theme_name
        theme = cls.THEMES[theme_name]

        # Late import to avoid a circular import at module load time.
        from .window import ConsoleWindow

        # Reinitialize every pair this theme defines (DEFAULT_BG first).
        for pair_id, fg, bg in cls.pair_specs(theme_name):
            curses.init_pair(pair_id, fg, bg)

        # Set the screen/pad background too, even when it is (-1, -1) — i.e.
        # "back to the terminal default" — and broadcast it to *every* live
        # window; there is no longer a single process-wide "static" window.
        # Theme.set() is the process-wide entry point, so it owns this internal
        # step; exposing a public hook would only invite apps to bypass the
        # pair-table installation above.
        if 'default_fg' in theme and 'default_bg' in theme:
            ConsoleWindow._apply_default_colors(  # pylint: disable=protected-access
                curses.color_pair(cls.DEFAULT_BG))

        # A process-wide switch leaves every window reporting the same theme,
        # so per-window state cannot contradict the pair table just installed.
        for win in ConsoleWindow.active_windows():
            win.theme = theme_name

        return True

    @classmethod
    def set_active(cls, theme_name: str) -> str:
        cls._current = theme_name
        return theme_name

    @classmethod
    def theme_of(cls, win: object) -> str | None:
        """Return the theme *win* is on (falling back to the process default).

        Host objects that only expose the drawing methods the factory needs do
        not have to carry a ``theme`` attribute.
        """
        return getattr(win, 'theme', cls.get_current())

    @classmethod
    def apply_to(cls, win: object, theme_name: str) -> bool:
        """Apply *theme_name* to *win*, preferring its per-window API.

        A host window without ``set_theme()`` still gets the historical
        process-wide switch, so the factory works on minimal window stubs.
        """
        setter = getattr(win, 'set_theme', None)
        if setter is not None:
            return bool(setter(theme_name))
        return cls.set(theme_name)

    @classmethod
    def create_picker_screen(cls, base_class: type) -> type:
        """Build a theme-picker screen class on top of *base_class*.

        The generated screen renders the current theme, a set of labelled colour
        swatches, and an action (``spin_theme_ACTION``) that cycles themes.  The
        host application is expected to expose ``win``, and may expose
        ``opts.theme``: when present, that option is treated as the selected
        theme, so an ordinary cycle binding and the built-in action stay in sync.
        The theme is applied to ``app.win`` itself (``ConsoleWindow.set_theme``),
        so the window reports the theme it is actually drawing with.
        """
        class ThemePickerScreen(base_class):
            def draw_screen(self) -> None:
                app = self.app
                win = app.win

                win.set_pick_mode(False)

                # Apply a theme selected through the host's option (for example
                # an OptionSpinner cycle binding) before drawing the swatches.
                opts = getattr(app, 'opts', None)
                selected = getattr(opts, 'theme', None) if opts is not None else None
                if selected and selected != cls.theme_of(win):
                    cls.apply_to(win, selected)

                # Name the theme this window is on (default when unset).
                current_theme = cls.theme_of(win)
                display_theme = current_theme if current_theme else '(default)'

                # Add header showing current theme
                win.add_header(f'COLOR THEME:  {display_theme:^18}', attr=curses.A_BOLD)
                win.add_header('   Press [t] to cycle themes, ESC to return', resume=True)

                # Color purpose labels
                color_labels = [
                    (cls.DANGER, 'DANGER', 'Destructive operations'),
                    (cls.SUCCESS, 'SUCCESS', 'Completed operations'),
                    (cls.OLD_SUCCESS, 'OLD_SUCCESS', 'Older completed operations'),
                    (cls.WARNING, 'WARNING', 'Caution/stopped states'),
                    (cls.INFO, 'INFO', 'Informational states'),
                    (cls.EMPHASIS, 'EMPHASIS', 'Emphasized text'),
                    (cls.ERROR, 'ERROR', 'Errors'),
                    (cls.PROGRESS, 'PROGRESS', 'Progress indicators'),
                    (cls.HOTSWAP, 'HOTSWAP', 'Recently added items'),
                ]

                # Show color examples for this theme
                for color_id, label, description in color_labels:
                    # Create line with colored block and description
                    line = f'{label:12} ████████  {description}'
                    attr = curses.color_pair(color_id)
                    win.add_body(line, attr=attr)

            def spin_theme_ACTION(self) -> None:
                win = self.app.win
                vals = cls.list_all()
                opts = getattr(self.app, 'opts', None)
                # Start from the theme the host has selected, falling back to
                # the theme this window is actually on when there is no option.
                value = getattr(opts, 'theme', None) or cls.theme_of(win)
                idx = vals.index(value) if value in vals else -1
                value = vals[(idx+1) % len(vals)]  # choose next
                cls.apply_to(win, value)
                if opts is not None:
                    opts.theme = value

        return ThemePickerScreen
