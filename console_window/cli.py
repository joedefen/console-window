"""Argument-parser boilerplate for the display options.

Supplies `--ascii`, `--glyphs` and `--theme` and applies the
resulting glyph and theme decisions. Absent switches mean detect.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

from . import glyphs
from ._appearance import Appearance
from .glyphs import TerminalReport
from .theme import Theme, ThemeStore

__all__ = [
    'add_display_arguments',
    'apply_display_arguments',
    'resolve_force_ascii',
]

_TRUE_WORDS = frozenset({'1', 'true', 'yes', 'y', 'on'})
_FALSE_WORDS = frozenset({'0', 'false', 'no', 'n', 'off'})
_MODES = ('auto', 'ascii', 'unicode')


def _bool_argument(value: str) -> bool:
    """argparse `type=` for `--ascii=VALUE`; bare `--ascii` uses `const`."""
    lowered = value.strip().lower()
    if lowered in _TRUE_WORDS:
        return True
    if lowered in _FALSE_WORDS:
        return False
    raise argparse.ArgumentTypeError(
        f'expected a boolean (yes/no, true/false, on/off), got {value!r}'
    )


def _theme_argument(value: str) -> str:
    """argparse `type=` for `--theme`: canonicalize and reject unknowns."""
    name = Theme.canonical(value)
    if name is None:
        raise argparse.ArgumentTypeError(
            f'unknown theme {value!r}; choose from {", ".join(Theme.list_all())}'
            f' (legacy aliases: {", ".join(sorted(Theme.ALIASES))})'
        )
    return name


def add_display_arguments(
    parser: argparse.ArgumentParser,
    *,
    theme_store: ThemeStore | None = None,
    prog: str | None = None,
) -> argparse.ArgumentParser:
    """Add `--ascii`, `--glyphs` and `--theme` to the parser.

    Args:
        theme_store: Enables the "remembered" hint in the `--theme` help.
        prog: Name used in the help text instead of `parser.prog`.
    """
    name = prog or parser.prog or 'this program'
    remembered = ' (remembered for the next start)' if theme_store is not None else ''
    parser.add_argument(
        '--ascii',
        nargs='?',
        const=True,
        default=None,
        type=_bool_argument,
        metavar='BOOL',
        help=(
            f'use plain-ASCII symbols; --ascii=no forces the Unicode set. '
            f'Without the switch {name} detects the terminal'
        ),
    )
    parser.add_argument(
        '--glyphs',
        choices=_MODES,
        default=None,
        help=(
            'symbol mode: auto detects the terminal, ascii forces the fallback, '
            'unicode forces the full set (same thing as --ascii / --ascii=no)'
        ),
    )
    parser.add_argument(
        '--theme',
        type=_theme_argument,
        default=None,
        metavar='THEME',
        help=(
            f'color theme: {", ".join(Theme.list_all())}{remembered}. '
            'mono uses the terminal colors and bold/reverse attributes; '
            'NO_COLOR selects it when no theme is given'
        ),
    )
    return parser


def resolve_force_ascii(args: argparse.Namespace) -> bool | None:
    """Map a parsed namespace to `force_ascii`.

    Args:
        args: Namespace with optional `glyphs` and `ascii` attributes.

    Returns:
        True for ASCII, False for Unicode, or None to detect.

    Raises:
        TypeError: If `args.ascii` is neither None nor a bool.
    """
    mode = getattr(args, 'glyphs', None)
    if mode == 'ascii':
        return True
    if mode == 'unicode':
        return False
    if mode == 'auto':
        return None
    flag = getattr(args, 'ascii', None)
    if flag is None or isinstance(flag, bool):
        return flag
    raise TypeError(
        f'args.ascii must be None or a bool (it is {flag!r}); parse it with '
        'add_display_arguments() or pass a bool'
    )


def apply_display_arguments(
    args: argparse.Namespace,
    *,
    printer: Callable[[str], object] = print,
    prog: str = '',
    environ: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> TerminalReport:
    """Set the glyph mode, print the report's notes and seed the theme.

    Call before any window is created so the mode is decided while nothing has
    been drawn.  An explicit `--theme` wins; otherwise a non-empty `NO_COLOR`
    selects `mono`.

    Args:
        prog: Prefix for each printed note.
        environ: Environment mapping used for detection.
        stream: Stream used by glyph detection; defaults to `sys.stdout`.

    Raises:
        TypeError: If `args.ascii` is neither None nor a bool.
    """
    report = glyphs.apply_policy(
        resolve_force_ascii(args),
        environ=environ,
        stream=sys.stdout if stream is None else stream,
    )
    for note in report.notes:
        printer(f'{prog}: {note}' if prog else note)

    raw_theme = getattr(args, 'theme', None)
    if raw_theme and Theme.canonical(raw_theme) is None:
        # A hand-built namespace may bypass the argparse type; report the name.
        message = f'unknown theme {raw_theme!r}; keeping {Theme.resolve(None)!r}'
        printer(f'{prog}: {message}' if prog else message)
        raw_theme = None

    theme = Appearance.resolve_appearance(cli_theme=raw_theme, environ=environ)
    if theme:
        # No window exists yet; record the choice for the first one.
        Theme.set_active(theme)
    return report
