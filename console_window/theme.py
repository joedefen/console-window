from __future__ import annotations

import curses
import logging
from typing import ClassVar, Protocol

from . import glyphs
from .backend import CursesBackend, RenderBackend

logger = logging.getLogger(__name__)


class ThemeStore(Protocol):
    """Minimal persistence seam for a remembered theme.

    The library never opens a file: the application owns the path, the format
    and the permissions, and exposes only these two operations.  A
    ``UiPrefs``-style wrapper is one adapter; a two-method stub over a dict is
    another (handy in tests).  ``load()`` returning ``None`` means "nothing
    remembered", which is not an error.
    """

    def load(self) -> str | None:
        ...

    def save(self, name: str) -> None:
        ...


def _discover_cycle_key(screen: object, fallback: str = 't') -> str:
    """Find the printable key the host bound to ``spin_theme``.

    The picker used to hard-code ``t`` in its hint line, which was wrong for any
    app that bound the cycle to another key.  Reading the spinner keeps the hint
    true without adding an option; a host that binds nothing keeps the
    historical ``t``.
    """
    getter = getattr(screen, 'get_spinner', None)
    spinner = getter() if callable(getter) else None
    for option in getattr(spinner, 'options', None) or ():
        if getattr(option, 'attr', None) != 'theme':
            continue
        for key in getattr(option, 'keys', None) or ():
            if isinstance(key, int) and not isinstance(key, bool) and 32 <= key < 127:
                return chr(key)
    return fallback

# --- palette model -----------------------------------------------------------
# Standard xterm palette model.  0..15 are the ANSI/base colours, 16..231 the
# 6x6x6 colour cube with the levels below, and 232..255 the grayscale ramp
# ``8 + 10 * n``.  The RGB values are the conventional xterm ones; exact
# fidelity is not required because the result only picks the closest entry a
# low-colour terminal can actually display.
_ANSI_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),        # 0 black
    (128, 0, 0),      # 1 red
    (0, 128, 0),      # 2 green
    (128, 128, 0),    # 3 yellow
    (0, 0, 128),      # 4 blue
    (128, 0, 128),    # 5 magenta
    (0, 128, 128),    # 6 cyan
    (192, 192, 192),  # 7 white
    (128, 128, 128),  # 8 bright black
    (255, 0, 0),      # 9 bright red
    (0, 255, 0),      # 10 bright green
    (255, 255, 0),    # 11 bright yellow
    (0, 0, 255),      # 12 bright blue
    (255, 0, 255),    # 13 bright magenta
    (0, 255, 255),    # 14 bright cyan
    (255, 255, 255),  # 15 bright white
)
_CUBE_LEVELS: tuple[int, ...] = (0, 95, 135, 175, 215, 255)


def palette_rgb(index: int) -> tuple[int, int, int]:
    """Return the conventional xterm RGB value for palette *index*.

    Unknown/negative indices (``-1`` is "terminal default", resolved before
    this function is called) fall back to black so callers never raise.
    """
    if 0 <= index < 16:
        return _ANSI_RGB[index]
    if 16 <= index <= 231:
        offset = index - 16
        return (
            _CUBE_LEVELS[offset // 36],
            _CUBE_LEVELS[(offset // 6) % 6],
            _CUBE_LEVELS[offset % 6],
        )
    if 232 <= index <= 255:
        level = 8 + 10 * (index - 232)
        return (level, level, level)
    return (0, 0, 0)


def _rgb_distance(left: tuple[int, int, int],
                  right: tuple[int, int, int]) -> int:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=False))


def nearest_palette_index(index: int, colors: int) -> int:
    """Map 256-colour *index* to the nearest entry a *colors*-terminal has.

    Entries 0..15 are the base palette, so the search is restricted to
    ``0 .. min(colors, 16) - 1``.  A 256-colour terminal gets *index* back
    unchanged (exact theme specs, no visual regression).  Returns ``-1`` when
    the terminal has no usable colours at all.
    """
    if colors >= 256:
        return index
    limit = max(0, min(int(colors), 16))
    if limit <= 0:
        return -1
    if 0 <= index < limit:
        return index
    target = palette_rgb(index)
    best = 0
    best_distance = _rgb_distance(target, palette_rgb(0))
    for candidate in range(1, limit):
        distance = _rgb_distance(target, palette_rgb(candidate))
        if distance < best_distance:
            best = candidate
            best_distance = distance
    return best


def _contrast_partner(color: int, colors: int) -> int | None:
    """Return the palette entry furthest from *color*, or None if impossible."""
    limit = max(0, min(int(colors), 16))
    if limit <= 1:
        return None
    base = palette_rgb(color)
    best: int | None = None
    best_distance = -1
    for candidate in range(limit):
        if candidate == color:
            continue
        distance = _rgb_distance(base, palette_rgb(candidate))
        if distance > best_distance:
            best = candidate
            best_distance = distance
    return best


def resolve_color_pair(fg: int, bg: int, colors: int,
                       default_colors: bool) -> tuple[int, int] | None:
    """Resolve a theme's ``(fg, bg)`` to values *colors* can accept.

    ``-1`` is passed through only when :meth:`RenderBackend.use_default_colors`
    succeeded; otherwise it is replaced with concrete defaults (fg 7, bg 0).
    On terminals with fewer than 256 colours each index is mapped to the
    nearest available palette entry.  If the mapping would collapse the pair to
    ``fg == bg`` the foreground is moved to the most contrasting entry.  Returns
    ``None`` when no legible pair exists (e.g. a 1-colour terminal), in which
    case the caller falls back to attributes and installs nothing.
    """
    if colors <= 0:
        return None
    if fg == -1 and not default_colors:
        fg = 7
    if bg == -1 and not default_colors:
        bg = 0
    if colors < 256:
        if fg != -1:
            fg = nearest_palette_index(fg, colors)
        if bg != -1:
            bg = nearest_palette_index(bg, colors)
    # A pair of terminal defaults is left alone: the terminal guarantees a
    # legible default combination, and preserving (-1, -1) keeps the 256-colour
    # path byte-for-byte identical to the theme spec.
    if fg != -1 and bg != -1 and fg == bg:
        partner = _contrast_partner(bg, colors)
        if partner is None:
            return None
        fg = partner
    return fg, bg


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
    def initial(cls, cli_theme: str | None = None,
                store: ThemeStore | None = None) -> str:
        """The theme to start on: an explicit choice, else the remembered one.

        An explicit ``--theme`` wins, because a one-off override is the reason
        the flag exists.  A store that cannot be read must never stop start-up:
        its failure is logged and the default is used.
        """
        remembered: str | None = None
        if cli_theme is None and store is not None:
            try:
                remembered = store.load()
            except Exception:  # a broken prefs file must not kill start-up
                logger.warning('theme store could not be read; using the default',
                               exc_info=True)
        return cls.resolve(cli_theme or remembered)

    @classmethod
    def pair_specs(cls, theme_name: str | None) -> list[tuple[int, int, int]]:
        """``(pair_id, fg, bg)`` for every pair *theme_name* defines.

        ``DEFAULT_BG`` comes first (the screen and pad background), then the
        semantic roles in ``SEMANTIC_PAIRS`` order.  Startup
        (``ConsoleWindow._init_screen``), :meth:`set` and
        ``ConsoleWindow.set_theme`` all install colours through :meth:`install`
        from this one list, so the paths cannot drift apart.
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
    def install(cls, backend: RenderBackend,
                theme_name: str | None = None) -> str:
        """Install *theme_name*'s colours through *backend*, degrading safely.

        This is the single installation path used by startup
        (``ConsoleWindow._init_screen``), ``ConsoleWindow.set_theme()`` and
        :meth:`set`.  It consults the backend's colour capability instead of the
        ``curses`` globals: on a 256-colour terminal the theme's literal specs
        are used unchanged, while fewer colours are mapped to the nearest
        available palette entry and ``-1`` is only emitted when the terminal
        accepted ``use_default_colors()``.  Pair ids beyond ``COLOR_PAIRS`` and
        pairs with no legible mapping are skipped rather than raising.  Returns
        the resolved theme name.
        """
        name = cls.resolve(theme_name if theme_name is not None
                           else cls.get_current())
        colors = int(backend.colors())
        max_pairs = int(backend.color_pairs())
        default_colors = bool(backend.use_default_colors()) if colors > 0 else False
        for pair_id, fg, bg in cls.pair_specs(name):
            if pair_id >= max_pairs:
                continue
            pair = resolve_color_pair(fg, bg, colors, default_colors)
            if pair is None:
                continue
            backend.init_pair(pair_id, pair[0], pair[1])
        return name

    @classmethod
    def set(cls, theme_name: str) -> bool:
        if theme_name not in cls.THEMES:
            return False

        # Late import to avoid a circular import at module load time.
        from .window import ConsoleWindow

        # Colour pairs are terminal-global, so a live window's backend is the
        # authoritative seam.  Without one, fall back to curses itself, but go
        # through CursesBackend so this method never calls curses.init_pair()
        # directly (that path used to bypass every low-colour guard).
        win = ConsoleWindow.primary_window()
        backend = getattr(win, '_backend', None) if win is not None else None
        if backend is None:
            backend = CursesBackend()
            backend.start_color()
        if not backend.has_colors():
            return False

        cls._current = theme_name
        name = cls.install(backend, theme_name)
        cls._current = name
        theme = cls.THEMES[name]

        # Set the screen/pad background too, even when it is (-1, -1) — i.e.
        # "back to the terminal default" — and broadcast it to *every* live
        # window; there is no longer a single process-wide "static" window.
        # Theme.set() is the process-wide entry point, so it owns this internal
        # step; exposing a public hook would only invite apps to bypass the
        # pair-table installation above.
        if ('default_fg' in theme and 'default_bg' in theme
                and cls.DEFAULT_BG < backend.color_pairs()):
            ConsoleWindow._apply_default_colors(  # pylint: disable=protected-access
                backend.color_pair(cls.DEFAULT_BG))

        # A process-wide switch leaves every window reporting the same theme,
        # so per-window state cannot contradict the pair table just installed.
        for win in ConsoleWindow.active_windows():
            win.theme = name

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
    def create_picker_screen(cls, base_class: type, *,
                             cycle_key: str | None = None,
                             store: ThemeStore | None = None,
                             note: str | None = None) -> type:
        """Build a theme-picker screen class on top of *base_class*.

        The generated screen renders the current theme, a set of labelled colour
        swatches, and an action (``spin_theme_ACTION``) that cycles themes.  The
        host application is expected to expose ``win``, and may expose
        ``opts.theme``: when present, that option is treated as the selected
        theme, so an ordinary cycle binding and the built-in action stay in sync.
        The theme is applied to ``app.win`` itself (``ConsoleWindow.set_theme``),
        so the window reports the theme it is actually drawing with.

        *cycle_key* is the key the hint line advertises; ``None`` discovers it
        from the host's ``spin_theme`` binding and falls back to ``t``.
        *store* makes the choice survive a restart: the factory calls
        ``store.save()`` after each cycle, and a failing store is logged rather
        than raised.  *note* is one extra dim line (for example "the choice is
        remembered for the next start").
        """
        swatch = glyphs.get('swatch') * 8

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
                hint_key = cycle_key or _discover_cycle_key(self)

                # Add header showing current theme
                win.add_header(f'COLOR THEME:  {display_theme:^18}', attr=curses.A_BOLD)
                win.add_header(f'   Press [{hint_key}] to cycle themes, ESC to return',
                               resume=True)

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
                    # Create line with colored block and description.  The block
                    # is a registered glyph, so a terminal that cannot draw U+2588
                    # shows '#' blocks instead of nine empty cells.
                    line = f'{label:12} {swatch}  {description}'
                    attr = curses.color_pair(color_id)
                    win.add_body(line, attr=attr)
                if note:
                    win.add_body(note, attr=curses.A_DIM)

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
                if store is not None:
                    try:
                        store.save(value)
                    except Exception:  # persistence never breaks a cycle
                        logger.warning('could not remember theme %r', value,
                                       exc_info=True)

        return ThemePickerScreen
