"""Theme registry, color resolution and the theme picker."""

from __future__ import annotations

import curses
import logging
from collections.abc import Callable, Mapping
from typing import ClassVar, Protocol

from . import glyphs, textwidth
from .backend import CursesBackend, RenderBackend

logger = logging.getLogger(__name__)


class _SwatchWindow(Protocol):
    """The part of a host screen the swatch renderer needs."""

    win: object

    def add_body(self, text: str, attr: int | None = None) -> None:
        ...


class ThemeStore(Protocol):
    """Minimal persistence seam for a remembered theme.

    The library never opens a file; the application owns the path, format and
    permissions.  `load()` returning `None` means nothing is remembered.
    """

    def load(self) -> str | None:
        """The remembered theme name, or `None` when nothing is stored."""

    def save(self, name: str) -> None:
        """Remember *name* as the theme to start on next time.

        Args:
            name: A theme name, in any form `Theme.resolve` accepts.
        """


def _discover_cycle_key(screen: object, fallback: str = 't') -> str:
    """Find the printable key the host bound to `spin_theme`, or fall back to `t`."""
    getter = getattr(screen, 'get_spinner', None)
    spinner = getter() if callable(getter) else None
    for option in getattr(spinner, 'options', None) or ():
        if getattr(option, 'attr', None) != 'theme':
            continue
        for key in getattr(option, 'keys', None) or ():
            if isinstance(key, int) and not isinstance(key, bool) and 32 <= key < 127:
                return chr(key)
    return fallback


def _swatch_label_width(rows: list[tuple[int, str, str]], swatch: str,
                        win: object) -> int:
    """Width of the picker's label column, capped to leave room for the swatch."""
    label = max(
        (textwidth.string_width(text) for _, text, _ in rows),
        default=0,
    )
    getter = getattr(win, 'get_pad_width', None)
    total = getter() if callable(getter) else 80
    available = max(1, total - textwidth.string_width(swatch) - 2)
    return min(max(12, label), available)


def _draw_swatch_rows(screen: _SwatchWindow, rows: list[tuple[int, str, str]],
                      swatch: str, attr_for: Callable[[int], int],
                      note: str | None = None) -> None:
    """Paint one tinted line per semantic role onto *screen*."""
    label_width = _swatch_label_width(rows, swatch, screen.win)
    add_body = screen.add_body
    for color_id, label, usage in rows:
        line = f'{textwidth.ljust(label, label_width)} {swatch}  {usage}'
        add_body(line, attr=attr_for(color_id))
    if note:
        add_body(note, attr=curses.A_DIM)


# --- palette model -----------------------------------------------------------
# Standard xterm palette model: 0..15 base colors, 16..231 the 6x6x6 cube,
# 232..255 the grayscale ramp.  Exact fidelity is not required; the values
# only pick the closest entry a low-color terminal can display.
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
    """Conventional xterm RGB value for palette *index*; unknown indices give black."""
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
    """Map 256-color *index* to the nearest entry a *colors*-terminal has.

    Returns *index* unchanged on a 256-color terminal, and `-1` when the
    terminal has no usable colors.
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
    """Resolve a theme's `(fg, bg)` to values *colors* can accept.

    `-1` passes through only when `use_default_colors` succeeded.  Fewer than
    256 colors maps each index to the nearest entry, and a collapsed pair moves
    the foreground to the most contrasting entry.  Returns `None` when no
    legible pair exists.
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
    # A pair of terminal defaults is left alone; the terminal guarantees it.
    if fg != -1 and bg != -1 and fg == bg:
        partner = _contrast_partner(bg, colors)
        if partner is None:
            return None
        fg = partner
    return fg, bg


class Theme:
    """Palette registry plus the process-wide current theme.

    `set` installs colors and records the choice; `resolve` normalizes an
    unknown name to `'default'`.
    """

    DEFAULT = 0
    DANGER = 1
    SUCCESS = 2
    WARNING = 3
    INFO = 4
    EMPHASIS = 5
    ERROR = 6
    PROGRESS = 7
    HOTSWAP = 9
    OLD_SUCCESS = 10

    # The theme's default fg/bg pair; not a semantic role, but in the same id space.
    DEFAULT_BG = 8

    # The semantic roles, in initialization order.
    SEMANTIC_PAIRS: ClassVar[tuple[int, ...]] = (
        DANGER, SUCCESS, OLD_SUCCESS, WARNING, INFO, EMPHASIS, ERROR, PROGRESS, HOTSWAP,
    )

    # Stable string names; `role_id` normalizes case, hyphen and space.
    ROLES: ClassVar[dict[str, int]] = {
        'danger': DANGER,
        'success': SUCCESS,
        'old_success': OLD_SUCCESS,
        'warning': WARNING,
        'info': INFO,
        'emphasis': EMPHASIS,
        'error': ERROR,
        'progress': PROGRESS,
        'hotswap': HOTSWAP,
    }

    # The picker's default vocabulary: `role -> (label, usage)`, in row order.
    ROLE_CAPTIONS: ClassVar[dict[int, tuple[str, str]]] = {
        DANGER: ('DANGER', 'Destructive operations'),
        SUCCESS: ('SUCCESS', 'Completed operations'),
        OLD_SUCCESS: ('OLD_SUCCESS', 'Older completed operations'),
        WARNING: ('WARNING', 'Caution/stopped states'),
        INFO: ('INFO', 'Informational states'),
        EMPHASIS: ('EMPHASIS', 'Emphasized text'),
        ERROR: ('ERROR', 'Errors'),
        PROGRESS: ('PROGRESS', 'Progress indicators'),
        HOTSWAP: ('HOTSWAP', 'Recently added items'),
    }

    _current: ClassVar[str | None] = None

    # The theme for "no semantic color".
    MONO: ClassVar[str] = 'mono'

    # Legacy names, normalized to their canonical replacements.
    ALIASES: ClassVar[dict[str, str]] = {
        'dark-mono': 'dark',
        'light-mono': 'light',
    }

    THEMES: ClassVar[dict] = {
        'dark': {
            'name': 'Dark',
            'default_fg': 253,
            'default_bg': 232,
            1: (196, 232),
            2: (46, 232),
            10: (28, 232),
            3: (226, 232),
            4: (51, 232),
            5: (255, 232),
            6: (196, 232),
            7: (39, 232),
            9: (208, 232),
        },
        'light': {
            'name': 'Light',
            'default_fg': 233,
            'default_bg': 253,
            1: (196, 253),
            2: (34, 253),
            10: (22, 253),
            3: (208, 253),
            4: (25, 253),
            5: (232, 253),
            6: (196, 253),
            7: (27, 253),
            9: (166, 253),
        },
        'default': {
            'name': 'Terminal Default',
            'default_fg': -1,
            'default_bg': -1,
            1: (1, -1),
            2: (2, -1),
            10: (28, -1),
            3: (3, -1),
            4: (6, -1),
            5: (7, -1),
            6: (9, -1),
            7: (4, -1),
            9: (208, -1),
        },
        'solarized-dark': {
            'name': 'Solarized Dark',
            'default_fg': 244,
            'default_bg': 234,
            1: (160, 234),
            2: (70, 234),
            10: (28, 234),
            3: (136, 234),
            4: (37, 234),
            5: (230, 234),
            6: (196, 234),
            7: (33, 234),
            9: (166, 234),
        },
        'solarized-light': {
            'name': 'Solarized Light',
            'default_fg': 240,
            'default_bg': 230,
            1: (160, 230),
            2: (70, 230),
            10: (28, 230),
            3: (166, 230),
            4: (37, 230),
            5: (235, 230),
            6: (196, 230),
            7: (33, 230),
            9: (208, 230),
        },
        'gruvbox': {
            'name': 'Gruvbox Dark',
            'default_fg': 223,
            'default_bg': 235,
            1: (167, 235),
            2: (142, 235),
            10: (106, 235),
            3: (214, 235),
            4: (109, 235),
            5: (229, 235),
            6: (203, 235),
            7: (109, 235),
            9: (208, 235),
        },
        'nord': {
            'name': 'Nord',
            'default_fg': 252,
            'default_bg': 236,
            1: (203, 236),
            2: (150, 236),
            10: (114, 236),
            3: (220, 236),
            4: (116, 236),
            5: (231, 236),
            6: (203, 236),
            7: (136, 236),
            9: (208, 236),
        },
        'mono': {
            'name': 'Mono',
            'default_fg': -1,
            'default_bg': -1,
        },
    }

    @classmethod
    def canonical(cls, theme_name: str | None) -> str | None:
        """Return the canonical theme name for *theme_name*, or `None`."""
        if not theme_name:
            return None
        name = cls.ALIASES.get(theme_name, theme_name)
        return name if name in cls.THEMES else None

    @classmethod
    def is_mono(cls, theme_name: str | None) -> bool:
        """True when *theme_name* is the monochrome (no semantic color) theme."""
        return cls.canonical(theme_name) == cls.MONO

    @classmethod
    def role_id(cls, role: int | str) -> int:
        """Normalize a semantic role id or name to its integer id.

        Accepts a `Theme` constant or a case-insensitive name.  Unknown names
        and ids without a picker caption raise `ValueError`.
        """
        if isinstance(role, bool) or not isinstance(role, (int, str)):
            raise ValueError(f'unknown color role {role!r}')
        if isinstance(role, str):
            key = role.strip().lower().replace('-', '_').replace(' ', '_')
            resolved = cls.ROLES.get(key)
            if resolved is None:
                raise ValueError(
                    f'unknown color role {role!r}; choose from '
                    f'{", ".join(cls.ROLES)}'
                )
            role = resolved
        if role not in cls.ROLE_CAPTIONS:
            raise ValueError(
                f'{role!r} is not a displayable color role; choose from '
                f'{", ".join(cls.ROLES)}'
            )
        return role

    @classmethod
    def role_captions(
        cls,
        captions: Mapping[int | str, tuple[str | None, str | None]] | None = None,
        include_defaults: bool = True,
    ) -> list[tuple[int, str, str]]:
        """Resolve an application's caption mapping to picker rows.

        Each entry is `role -> (label, usage)`; `None` or `''` keeps the
        library text.  With *include_defaults* the overrides replace captions
        in place, otherwise the mapping is the row list.  Duplicate or unknown
        roles raise `ValueError`.
        """
        resolved: dict[int, tuple[str | None, str | None]] = {}
        for role, caption in (captions or {}).items():
            role_id = cls.role_id(role)
            if role_id in resolved:
                raise ValueError(f'duplicate caption for color role {role_id!r}')
            if isinstance(caption, str):
                raise ValueError(
                    f'caption for color role {role!r} must be a '
                    '(label, usage) pair'
                )
            try:
                label, usage = caption
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f'caption for color role {role!r} must be a '
                    '(label, usage) pair'
                ) from exc
            for field in (label, usage):
                if field is not None and not isinstance(field, str):
                    raise ValueError(
                        f'caption text for color role {role!r} must be a '
                        'string or None'
                    )
            resolved[role_id] = (label, usage)

        if include_defaults:
            rows: list[tuple[int, str, str]] = []
            for role, (label, usage) in cls.ROLE_CAPTIONS.items():
                override_label, override_usage = resolved.get(role, (None, None))
                rows.append((
                    role,
                    override_label or label,
                    override_usage or usage,
                ))
            return rows

        rows = []
        for role, (label, usage) in resolved.items():
            default_label, default_usage = cls.ROLE_CAPTIONS[role]
            rows.append((
                role,
                label or default_label,
                usage or default_usage,
            ))
        return rows

    @classmethod
    def resolve(cls, theme_name: str | None) -> str:
        """Return canonical *theme_name* if it names a theme, else `'default'`."""
        return cls.canonical(theme_name) or 'default'

    @classmethod
    def get_current(cls) -> str | None:
        """The active theme name, or `None` until a theme has been installed."""
        return cls._current

    @classmethod
    def initial(cls, cli_theme: str | None = None,
                store: ThemeStore | None = None) -> str:
        """The theme to start on: an explicit choice, else the remembered one.

        A store that cannot be read is logged and ignored.
        """
        remembered: str | None = None
        if cli_theme is None and store is not None:
            try:
                remembered = store.load()
            except Exception:
                logger.warning('theme store could not be read; using the default',
                               exc_info=True)
        return cls.resolve(cli_theme or remembered)

    @classmethod
    def pair_specs(cls, theme_name: str | None) -> list[tuple[int, int, int]]:
        """`(pair_id, fg, bg)` for every pair *theme_name* defines.

        `DEFAULT_BG` comes first, then the roles in `SEMANTIC_PAIRS` order.
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
        """Every canonical theme name, in registry order (aliases excluded)."""
        return list(cls.THEMES.keys())

    @classmethod
    def install(cls, backend: RenderBackend,
                theme_name: str | None = None) -> str:
        """Install *theme_name*'s colors through *backend*, degrading safely.

        Colors come from the backend's capability, not the `curses` globals.
        Pair ids beyond the table and pairs with no legible mapping are skipped.
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
        """Install *theme_name* for the whole process and record it as current.

        Returns False for an unknown name, or when the terminal has no colors
        and the theme is not `mono`.
        """
        name = cls.canonical(theme_name)
        if name is None:
            return False

        # Late import to avoid a circular import
        from .window import ConsoleWindow

        # Color pairs are terminal-global.
        win = ConsoleWindow.primary_window()
        backend = getattr(win, '_backend', None) if win is not None else None
        if backend is None:
            backend = CursesBackend()
            backend.start_color()
        if not backend.has_colors() and not cls.is_mono(name):
            return False

        cls._current = name
        name = cls.install(backend, name)
        cls._current = name
        theme = cls.THEMES[name]

        if ('default_fg' in theme and 'default_bg' in theme
                and cls.DEFAULT_BG < backend.color_pairs()):
            ConsoleWindow._apply_default_colors(
                backend.color_pair(cls.DEFAULT_BG))

        for win in ConsoleWindow.active_windows():
            win.theme = name

        cls.set_active(name)

        return True

    @classmethod
    def set_active(cls, theme_name: str | None) -> str | None:
        """Record *theme_name* as the process theme and synchronize color.

        A palette enables semantic color; `mono` disables it.
        """
        name = cls.canonical(theme_name) or theme_name
        cls._current = name
        # Late import: _appearance imports Theme at module load time.
        from ._appearance import Appearance
        if name in cls.THEMES:
            Appearance.set_colors_enabled(not cls.is_mono(name))
        return name

    @classmethod
    def theme_of(cls, win: object) -> str | None:
        """Return the theme *win* is on, falling back to the process default."""
        return getattr(win, 'theme', cls.get_current())

    @classmethod
    def apply_to(cls, win: object, theme_name: str) -> bool:
        """Apply *theme_name* to *win*, preferring its per-window API."""
        setter = getattr(win, 'set_theme', None)
        if setter is not None:
            return bool(setter(theme_name))
        return cls.set(theme_name)

    @classmethod
    def create_picker_screen(
        cls,
        base_class: type,
        *,
        cycle_key: str | None = None,
        store: ThemeStore | None = None,
        note: str | None = None,
        captions: Mapping[int | str, tuple[str | None, str | None]] | None = None,
        include_defaults: bool = True,
    ) -> type:
        """Build a theme-picker screen class on top of *base_class*.

        The screen draws labeled swatches and cycles themes via
        `spin_theme_ACTION`.  The host exposes `win` and may expose
        `opts.theme`, which the cycle action keeps in sync.  Override
        `swatch_rows`, `swatch_attr` or `theme_label` to customize.

        Args:
            cycle_key: Key the hint advertises; `None` discovers it from the
                `spin_theme` binding, falling back to `t`.
            store: Persists the choice after each cycle; failures are logged.
            note: One extra dim line under the swatches.
            captions: `role -> (label, usage)` overrides; `None` or `''`
                keeps the library text.
            include_defaults: Replace captions in place (True) or take the
                mapping as the whole row list (False).
        """
        swatch = glyphs.get('swatch') * 8
        default_rows = cls.role_captions(captions, include_defaults)

        class ThemePickerScreen(base_class):
            def draw_screen(self) -> None:
                app = self.app
                win = app.win

                self.set_pick_mode(False)

                opts = getattr(app, 'opts', None)
                selected = getattr(opts, 'theme', None) if opts is not None else None
                canonical = cls.canonical(selected) if selected else None
                if canonical and canonical != cls.theme_of(win):
                    cls.apply_to(win, canonical)
                if canonical and opts is not None:
                    opts.theme = canonical

                current_theme = cls.theme_of(win)
                display_theme = self.theme_label(current_theme)
                hint_key = cycle_key or _discover_cycle_key(self)

                self.add_header(f'COLOR THEME:  {display_theme:^18}', attr=curses.A_BOLD)
                self.add_header(f'   Press [{hint_key}] to cycle themes, ESC to return',
                                resume=True)

                _draw_swatch_rows(
                    self,
                    self.swatch_rows(),
                    swatch,
                    self.swatch_attr,
                    note,
                )

            def theme_label(self, theme_name: str | None) -> str:
                """Header label for the theme the window is on; override as a hook."""
                return theme_name if theme_name else '(default)'

            def swatch_rows(self) -> list[tuple[int, str, str]]:
                """Rows the picker draws, as `(role, label, usage)`.

                Seeded from the factory's `captions`; override to compute
                captions per draw.  Return a list, not an iterator.
                """
                return default_rows

            @staticmethod
            def swatch_attr(color_id: int) -> int:
                """Attribute for one role's swatch, via `Appearance.semantic_attr`.

                Override this hook to style swatches differently.
                """
                # Late import: _appearance imports Theme at module load time.
                from ._appearance import Appearance

                return Appearance.semantic_attr(color_id)

            def spin_theme_ACTION(self) -> None:
                win = self.app.win
                vals = cls.list_all()
                opts = getattr(self.app, 'opts', None)
                # Start from the host's selection, else the window's theme.
                value = getattr(opts, 'theme', None) or cls.theme_of(win)
                idx = vals.index(value) if value in vals else -1
                value = vals[(idx+1) % len(vals)]
                cls.apply_to(win, value)
                if opts is not None:
                    opts.theme = value
                if store is not None:
                    try:
                        store.save(value)
                    # Persistence never breaks a cycle.
                    except Exception:
                        logger.warning('could not remember theme %r', value,
                                       exc_info=True)

        return ThemePickerScreen
