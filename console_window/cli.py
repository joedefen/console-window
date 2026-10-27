"""Argument-parser boilerplate for the display options.

Every curses app ends up writing the same three switches: a way to force the
plain-ASCII symbol set, a way to pick a colour theme, and a way to print what
was detected.  This module supplies them, so an app's ``main()`` gains two
lines instead of sixty:

    parser = cli.add_display_arguments(parser)
    ...
    cli.apply_display_arguments(opts, prog='myapp')

The two switches are deliberately symmetric.  ``--ascii`` accepts an optional
boolean (``--ascii``, ``--ascii=no``) and ``--glyphs`` accepts a mode
(``auto``, ``ascii``, ``unicode``); ``--glyphs`` wins when both are given, and
"absent" everywhere means *detect*, never "assume Unicode".
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

from . import glyphs
from .glyphs import TerminalReport
from .theme import Theme, ThemeStore

__all__ = ['add_display_arguments', 'apply_display_arguments', 'resolve_force_ascii']

_TRUE_WORDS = frozenset({'1', 'true', 'yes', 'y', 'on'})
_FALSE_WORDS = frozenset({'0', 'false', 'no', 'n', 'off'})
_MODES = ('auto', 'ascii', 'unicode')


def _bool_argument(value: str) -> bool:
    """argparse ``type=`` for ``--ascii=VALUE``; bare ``--ascii`` uses ``const``."""
    lowered = value.strip().lower()
    if lowered in _TRUE_WORDS:
        return True
    if lowered in _FALSE_WORDS:
        return False
    raise argparse.ArgumentTypeError(
        f'expected a boolean (yes/no, true/false, on/off), got {value!r}'
    )


def add_display_arguments(
    parser: argparse.ArgumentParser,
    *,
    theme_store: ThemeStore | None = None,
    prog: str | None = None,
) -> argparse.ArgumentParser:
    """Add ``--ascii``, ``--glyphs`` and ``--theme`` to *parser*.

    Returns *parser* so a call site can wrap its own construction.  *theme_store*
    is accepted for symmetry with :func:`apply_display_arguments` (an app that
    passes one here is one that remembers the choice); it does not change the
    switches.  *prog* only shapes the help text.
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
        choices=Theme.list_all(),
        default=None,
        help=f'color theme{remembered}',
    )
    return parser


def resolve_force_ascii(args: argparse.Namespace) -> bool | None:
    """Map a parsed namespace to ``force_ascii``: True, False or None (detect)."""
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
    """Set the glyph mode, print the report's notes, seed the theme.

    Call this once, *before* any window is created, so the mode is decided while
    nothing has been drawn.  Returns the :class:`~console_window.glyphs.
    TerminalReport` so a caller can react to ``ascii_required`` (for example by
    printing a warning of its own).

    *printer* is a callable taking one string; pass ``sys.stderr.write`` style
    wrappers through ``lambda line: print(line, file=...)`` if needed.
    """
    report = glyphs.apply_policy(
        resolve_force_ascii(args),
        environ=environ,
        stream=sys.stdout if stream is None else stream,
    )
    for note in report.notes:
        printer(f'{prog}: {note}' if prog else note)

    theme = getattr(args, 'theme', None)
    if theme:
        if theme in Theme.list_all():
            # No window exists yet, so record the choice for the first one.
            Theme.set_active(theme)
        else:
            message = f'unknown theme {theme!r}; keeping {Theme.resolve(None)!r}'
            printer(f'{prog}: {message}' if prog else message)
    return report
