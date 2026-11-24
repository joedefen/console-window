"""Validated keyword options for `ConsoleWindow`."""

from __future__ import annotations

import curses
import difflib
import logging
import warnings
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .glyphs import Glyph
from .keys import NAVIGATION_KEYS, VERTICAL_NAV_KEYS

logger = logging.getLogger(__name__)


HELP_FONTS_VALUES = ('always', 'once', 'never')


def _normalize_help_fonts(raw: object) -> str:
    """Normalize `help_fonts` to `'always'`, `'once'` or `'never'`; `once` is the default."""
    if raw is None:
        return 'once'
    if isinstance(raw, bool):
        return 'always' if raw else 'never'
    value = str(raw).strip().lower()
    if value not in HELP_FONTS_VALUES:
        raise ValueError(
            "help_fonts must be 'always', 'once' or 'never', "
            f'got {raw!r}'
        )
    return value


def _normalize_ascii_flag(raw: object) -> bool | None:
    """Normalize the `ascii` option to `None` (auto-detect), `True` or `False`."""
    if raw is None or isinstance(raw, bool):
        return raw
    raise TypeError(
        'ascii must be None (auto-detect), True (force ASCII) or False '
        f'(force Unicode), got {raw!r}'
    )


def _normalize_glyphs(raw: object) -> dict[str, Glyph] | None:
    """Normalize `glyphs` to `{name: Glyph}`, accepting pair values too."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError(
            'glyphs must be a mapping of {name: (unicode, ascii)} or '
            f'{{name: Glyph(...)}}, got {type(raw).__name__}'
        )
    normalized: dict[str, Glyph] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name:
            raise TypeError(f'glyph names must be non-empty str, got {name!r}')
        if isinstance(spec, Glyph):
            normalized[name] = spec
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            normalized[name] = Glyph(spec[0], spec[1])
        else:
            raise TypeError(
                f'glyph {name!r} must be a Glyph or a (unicode, ascii) pair, '
                f'got {spec!r}'
            )
    return normalized


def _normalize_glyphs_probe(raw: object) -> tuple[str, ...]:
    """Normalize `glyphs_probe` to a tuple of names in display order."""
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        raise TypeError(
            'glyphs_probe must be an iterable of glyph names (not a bare str), '
            f'got {raw!r}'
        )
    names = tuple(raw)
    for name in names:
        if not isinstance(name, str) or not name:
            raise TypeError(f'glyphs_probe entries must be non-empty str, got {name!r}')
    return names


def _normalize_taken_nav_keys(raw: object) -> list[int]:
    """Normalize `taken_nav_keys` to an ordered list of integer key codes."""
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        warnings.warn(
            'taken_nav_keys as a mapping is deprecated; pass a list of key '
            'codes instead. The mapping values were help labels and are now '
            'ignored: a taken key is removed from the navigation help rather '
            'than documented there again.',
            DeprecationWarning,
            stacklevel=3,
        )
        candidates: Iterable[object] = raw.keys()
    elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        candidates = raw
    else:
        raise TypeError(
            'taken_nav_keys must be an iterable of key codes, got '
            f'{type(raw).__name__}'
        )

    normalized: list[int] = []
    for key in candidates:
        # bool is an int subclass; a True/False key code is always a mistake.
        if isinstance(key, bool) or not isinstance(key, int):
            raise ValueError(
                f'taken_nav_keys entries must be integer key codes, got {key!r}'
            )
        if key not in normalized:
            normalized.append(key)

    unknown = sorted(set(normalized) - NAVIGATION_KEYS)
    if unknown:
        logger.warning(
            'taken_nav_keys: %s not a navigation key; these entries have no effect',
            ', '.join(str(key) for key in unknown),
        )
    return normalized


class ConsoleWindowOpts:
    """Validated keyword options for `ConsoleWindow`.

    Every option is one of the `__slots__` names; an unknown name raises
    `TypeError` with a nearest-match hint.
    """

    __slots__ = ['answer_show_redraws', 'ascii', 'body_cols', 'body_rows',
                 'ctrl_c_terminates', 'demo_mode', 'dialog_abort', 'dialog_return',
                 'glyphs', 'glyphs_probe', 'head_line', 'head_rows',
                 'help_fonts', 'keys',
                 'max_rows', 'min_cols_rows', 'mod_pick', 'nav_keys', 'pick_attr',
                 'pick_mode', 'pick_range', 'relax_handled_keys',
                 'return_if_pos_change', 'single_cell_scroll_indicator',
                 'strip_attrs_in_pick_mode', 'taken_nav_keys', 'theme']

    answer_show_redraws: bool
    # None = detect the terminal, True = force ASCII fallbacks, False = force Unicode.
    ascii: bool | None
    body_cols: int
    body_rows: int | None  # advisory hint only; see max_rows
    ctrl_c_terminates: bool
    demo_mode: bool
    dialog_abort: str | None
    dialog_return: str
    glyphs: dict[str, Glyph] | None
    # Glyph names the font check shows, in reading order.
    glyphs_probe: tuple[str, ...]
    head_line: bool
    head_rows: int | None  # advisory hint only; see max_rows
    help_fonts: str
    max_rows: int | None
    keys: set | list | None
    min_cols_rows: tuple[int, int]
    mod_pick: Callable[[str], str] | None
    nav_keys: frozenset[int]
    taken_nav_keys: list[int]
    pick_attr: int
    pick_mode: bool
    pick_range: list[int] | None
    relax_handled_keys: bool
    return_if_pos_change: bool
    single_cell_scroll_indicator: bool
    strip_attrs_in_pick_mode: bool
    theme: str | None

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401 - dynamic options bag
        unknown = set(kwargs) - set(self.__slots__)
        if unknown:
            details = []
            for name in sorted(unknown):
                match = difflib.get_close_matches(name, self.__slots__, n=1)
                hint = f' (did you mean {match[0]!r}?)' if match else ''
                details.append(f'{name!r}{hint}')
            raise TypeError(
                f'ConsoleWindowOpts() got unknown option(s): {", ".join(details)}.')

        self.head_line = kwargs.get('head_line', True)
        # Row counts are hints; max_rows is the only ceiling and applies to both.
        self.head_rows = kwargs.get('head_rows')
        self.body_rows = kwargs.get('body_rows')
        self.max_rows = kwargs.get('max_rows', 32767)
        self.body_cols = kwargs.get('body_cols', 200)
        self.keys = kwargs.get('keys')
        if 'nav_keys' in kwargs:
            raise TypeError(
                'ConsoleWindowOpts() computes nav_keys from taken_nav_keys; '
                'pass taken_nav_keys=[key, ...] instead of nav_keys.'
            )
        self.taken_nav_keys = _normalize_taken_nav_keys(kwargs.get('taken_nav_keys'))
        self.nav_keys = frozenset(NAVIGATION_KEYS - set(self.taken_nav_keys))
        if self.taken_nav_keys and not (self.nav_keys & VERTICAL_NAV_KEYS):
            # Worth a diagnostic: "arrow keys do nothing" otherwise looks like a bug.
            logger.warning(
                'taken_nav_keys removes every vertical navigation key; this '
                'window has reduced (custom) navigation'
            )
        self.pick_mode = kwargs.get('pick_mode', False)
        self.mod_pick = kwargs.get('mod_pick')
        self.pick_attr = kwargs.get('pick_attr', curses.A_REVERSE)
        self.pick_range = kwargs.get('pick_range')  # [start_col, end_col] or None
        self.ctrl_c_terminates = kwargs.get('ctrl_c_terminates', True)
        self.return_if_pos_change = kwargs.get('return_if_pos_change', True)
        self.min_cols_rows = kwargs.get('min_cols_rows', (20, 5))
        self.dialog_abort = kwargs.get('dialog_abort', 'ESC')
        self.dialog_return = kwargs.get('dialog_return', 'ENTER')
        self.single_cell_scroll_indicator = kwargs.get('single_cell_scroll_indicator', False)
        self.answer_show_redraws = kwargs.get('answer_show_redraws', False)
        self.strip_attrs_in_pick_mode = kwargs.get('strip_attrs_in_pick_mode', False)
        self.demo_mode = kwargs.get('demo_mode', False)
        self.relax_handled_keys = kwargs.get('relax_handled_keys', True)
        self.theme = kwargs.get('theme')
        self.ascii = _normalize_ascii_flag(kwargs.get('ascii'))
        self.glyphs = _normalize_glyphs(kwargs.get('glyphs'))
        self.glyphs_probe = _normalize_glyphs_probe(kwargs.get('glyphs_probe'))
        self.help_fonts = _normalize_help_fonts(kwargs.get('help_fonts'))

        pair = self.min_cols_rows
        if (not isinstance(pair, (tuple, list)) or len(pair) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) or v < 1
                       for v in pair)):
            raise ValueError(
                'min_cols_rows must be a (cols, rows) pair of positive ints, '
                f'got {pair!r}')
        self.min_cols_rows = (pair[0], pair[1])

        if self.dialog_abort not in [None, 'ESC', 'ESC-ESC']:
            raise ValueError(f"dialog_abort must be None, 'ESC', or 'ESC-ESC', got {self.dialog_abort!r}")

        if self.dialog_return not in ['ENTER', 'TAB']:
            raise ValueError(f"dialog_return must be 'ENTER' or 'TAB', got {self.dialog_return!r}")
