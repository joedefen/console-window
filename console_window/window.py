# pylint: disable=too-many-instance-attributes,too-many-arguments
# pylint: disable=invalid-name,broad-except,too-many-branches,global-statement
# pylint: disable=line-too-long,too-many-statements,too-many-locals
# pylint: disable=too-many-return-statements,too-many-nested-blocks
# pylint: disable=multiple-statements,no-else-return

from __future__ import annotations

import atexit
import curses
import itertools
import logging
import sys
import time
import warnings
import weakref
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from curses.textpad import rectangle
from typing import Callable, ClassVar, cast

from . import geometry, glyphs, signals, textwidth
from .backend import CursesBackend, CursesSurface, RenderBackend
from .context import Context
from .header import (
    LABEL,
    PLAIN,
    SEARCH,
    HeaderLine,
    Span,
    parse_fancy_header,
    strip_key_brackets,
)
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .theme import Theme
from .widgets import PromptLine

logger = logging.getLogger(__name__)

# Control keys that drive the same movements as the page keys.  They live here
# rather than inside `prompt()` so the navigation map and the help text below
# cannot drift apart silently.
_CTRL_PAGE_UP, _CTRL_HALF_DOWN, _CTRL_PAGE_DOWN, _CTRL_HALF_UP = 2, 4, 6, 21

# Display labels for the keys that can appear in the navigation help.  Arrow
# keys are listed too even though the default lines do not use them: an app that
# takes LEFT/RIGHT gets `⬅`/`➡` on the "App:" line without supplying a label.
# Control keys use caret notation, the same spelling `_raw_key_label()` uses for
# them, so the navigation map stays narrow: `^b/^f` costs four columns where
# `Ctrl-b/Ctrl-f` cost eleven.
NAV_KEY_LABELS: dict[int, str] = {
    curses.KEY_UP: 'UP',
    curses.KEY_DOWN: 'DOWN',
    curses.KEY_LEFT: '\u2b05',
    curses.KEY_RIGHT: '\u27a1',
    curses.KEY_HOME: 'HOME',
    curses.KEY_END: 'END',
    curses.KEY_PPAGE: 'PPAGE',
    curses.KEY_NPAGE: 'NPAGE',
    ord('j'): 'j',
    ord('k'): 'k',
    ord('0'): '0',
    ord('$'): '$',
    ord('H'): 'H',
    ord('M'): 'M',
    ord('L'): 'L',
    _CTRL_HALF_UP: '^u',
    _CTRL_HALF_DOWN: '^d',
    _CTRL_PAGE_UP: '^b',
    _CTRL_PAGE_DOWN: '^f',
}

# Structured navigation help: one entry per printed line, each a tuple of rows
# (action, key codes in reading order, gap after the chunk).  The rendered text
# is generated from this table and the window's effective key set, so a key the
# application took disappears from the help instead of being advertised and
# doing nothing.  Keep this table in step with `_navigation_target()`; the two
# are the single sources of truth for "what scrolls" and "what we say scrolls".
#
# One row per action, not one row per key: the action word is stored once and
# every key that performs it hangs off it.  That is what lets the whole map
# print in two lines while still saying what `^u` or `H` does -- a bare list of
# vi keys would advertise them without explaining them.
#
# The gap lives on the row, not on the line, so the columns can be nudged
# individually: `first: 0/HOME` gets three spaces and lands `last:` in the same
# column as `page:` above it.  A uniform gap could not do that, because the
# two lines carry different numbers of chunks.  The final row's gap is empty;
# trailing spaces are stripped anyway, so it never reaches the screen.
NAV_HELP_LINES: tuple[tuple[tuple[str, tuple[int, ...], str], ...], ...] = (
    # Whole-screen and half/full-page moves: the least guessable keys.
    (
        ('pos', (ord('H'), ord('M'), ord('L')), '    '),  # top/mid/end of screen
        ('half', (_CTRL_HALF_UP, _CTRL_HALF_DOWN), '    '),
        ('page', (_CTRL_PAGE_UP, _CTRL_PAGE_DOWN,
                  curses.KEY_PPAGE, curses.KEY_NPAGE), ''),
    ),
    # Single-step moves, where the vi key and the terminal key pair up.
    (
        ('up', (ord('k'), curses.KEY_UP), '  '),
        ('down', (ord('j'), curses.KEY_DOWN), '  '),
        ('first', (ord('0'), curses.KEY_HOME), '   '),
        ('last', (ord('$'), curses.KEY_END), ''),
    ),
)

_NAV_HELP_COLUMN = 38
_NAV_HELP_PREFIX = 'NavKeys:    '
# The second line is a bare row, not a continuation of the label, so it gets a
# single leading space rather than a pad as wide as "NavKeys:".
_NAV_CONTINUATION = ' '
_NAV_APP_PREFIX = 'App:         '


# Every key curses knows, keyed by its integer code.  Deriving the table from
# the module constants keeps terminal-specific keys (F-keys, shift-arrows,
# keypad) covered without a hardcoded list.  KEY_MIN/KEY_MAX are range
# sentinels rather than keys, and KEY_MIN aliases KEY_BREAK, so both are
# skipped; the surviving alias names a real key.
_CURSES_KEY_NAMES: dict[int, str] = {
    getattr(curses, name): name.removeprefix('KEY_')
    for name in dir(curses)
    if name.startswith('KEY_') and name not in ('KEY_MIN', 'KEY_MAX')
}


def _key_label(key: int) -> str:
    """Best human-readable name for a curses key code.

    A ``curses.KEY_*`` name wins (``LEFT``, ``F5``, ``RESIZE``), then control
    characters in caret notation (``^U``), then a printable character.  An
    unknown code is shown as ``<code>`` rather than a bare ``???``, so a label
    never hides *which* key arrived.

    The arrow labels are decorative, so they pass through the glyph registry:
    on a terminal that cannot draw ``⬅`` the help reads ``<-`` instead.
    """
    return glyphs.transliterate(_raw_key_label(key))


def _raw_key_label(key: int) -> str:
    label = _CURSES_KEY_NAMES.get(key)
    if label is not None:
        return label
    if 0 <= key < 32:
        return f'^{chr(key + 64)}'
    if 32 <= key < 127:
        return chr(key)
    return f'<{key}>'


def _nav_key_label(key: int) -> str:
    label = NAV_KEY_LABELS.get(key)
    return label if label is not None else _key_label(key)


def _pair_nav_entries(entries: list[str], prefix: str) -> list[str]:
    """Render two entries per line under a fixed-width prefix."""
    lines = []
    pad = ' ' * len(prefix)
    for index in range(0, len(entries), 2):
        left = entries[index]
        right = entries[index + 1] if index + 1 < len(entries) else ''
        head = prefix if index == 0 else pad
        lines.append(f'{head}{left:<{_NAV_HELP_COLUMN}}{right}'.rstrip())
    return lines


def _nav_row_chunk(action: str, keys: tuple[int, ...],
                   effective: frozenset[int]) -> str | None:
    """One ``action: keys`` chunk, or None when every key in the row was taken.

    Slash-joined with no spaces, because every key after the colon is an
    alternative for the same action: ``page: ^b/^f/PPAGE/NPAGE`` reads as "any
    of these pages", not as a key sequence.
    """
    shown = [_nav_key_label(key) for key in keys if key in effective]
    if not shown:
        return None
    return f'{action}: {"/".join(shown)}'


def render_nav_help(effective: Iterable[int],
                    taken: dict[int, str] | None = None) -> tuple[str, ...]:
    """Render the navigation help for one window's effective key set.

    ``effective`` is the set of key codes still dispatched as navigation;
    ``taken`` maps the app-owned keys to the label the app wants shown.  The
    default (no taken keys) output is the public ``NAV_KEY_LINES`` text: two
    aligned rows of ``action: keys`` chunks covering the whole scroll map.
    """
    effective = frozenset(effective)
    lines = []
    for rows in NAV_HELP_LINES:
        text = ''
        for action, keys, gap in rows:
            chunk = _nav_row_chunk(action, keys, effective)
            if chunk is not None:
                text += chunk + gap
        text = text.rstrip()
        if not text:
            continue
        # The label belongs to the block, not to a particular line: if the top
        # row is entirely taken by the app, the bottom row carries it instead.
        head = _NAV_HELP_PREFIX if not lines else _NAV_CONTINUATION
        lines.append(f'{head}{text}')

    if not lines:
        lines = [
            _NAV_HELP_PREFIX
            + '(no navigation keys: all are bound by the application)'
        ]

    app_entries = []
    for key, label in (taken or {}).items():
        name = _nav_key_label(key)
        app_entries.append(f'{name}: {label}' if label else name)
    if app_entries:
        lines.extend(_pair_nav_entries(app_entries, _NAV_APP_PREFIX))
    return tuple(lines)


# Navigation help for the default key set.  Stored as complete lines, not a
# dedented triple-quoted string: editing the indentation can no longer change
# what the help screen renders.  ``ConsoleWindow.nav_keys`` remains the joined
# string for callers that want the whole blurb at once; live windows render
# through ``nav_help_lines()`` so their own ``taken_nav_keys`` are honored.
NAV_KEY_LINES: tuple[str, ...] = render_nav_help(NAVIGATION_KEYS)

# Editing keys that passthrough mode hands to the application unchanged, in
# addition to printable characters, navigation keys and `handled_keys`.
# ESC and DELETE are editing keys too: an in-place widget such as
# InlineConfirmation must be able to cancel and rub out at the caret, and
# callers should not have to discover `handled_keys` to make that work.
_PASSTHROUGH_EDITING_KEYS = frozenset({
    curses.KEY_BACKSPACE, 127, 8, 263,  # backspace variants
    curses.KEY_DC,                      # delete at the caret
    27,                                 # ESC: cancel an in-place edit
    curses.KEY_LEFT, curses.KEY_RIGHT,
    curses.KEY_HOME, curses.KEY_END,
    1, 5,  # Ctrl-A, Ctrl-E
})

# Compact demo-mode names for the keys whose plain curses name would be
# unwieldy or ambiguous in the header indicator.  Printable keys are handled
# separately (centered with spaces), so this table only covers the rest.
_DEMO_KEY_LABELS: dict[int, str] = {
    27: 'ESC',
    ord('\t'): 'TAB',
    10: 'ENT',  # newline
    13: 'ENT',  # carriage return (KEY_ENTER on some terminals)
    curses.KEY_ENTER: 'ENT',
    ord(' '): 'SPC',
    8: 'BSP',
    127: 'BSP',
    curses.KEY_BACKSPACE: 'BSP',
    curses.KEY_DC: 'DEL',
}

# Live ConsoleWindow instances, held by weak reference and keyed by creation
# order.  The registry keeps creation order (so ``primary_window()`` is
# deterministic) and never keeps a window alive.  It serves both models:
# singleton windows share one process screen, while per-instance windows own
# their own screen; the first successful construction latches which model this
# process uses, because mixing them would make teardown ambiguous.
_WINDOWS: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_WINDOW_IDS = itertools.count()

# Windows that have left curses mode (endwin) but are still resumable.  A
# strong reference is deliberate: the live registry is weak, and a suspended
# window must survive until resume_curses()/start_curses() reattaches it.  The
# screen itself is not kept here: in singleton mode the screen's owner stays
# reachable through ``static_win``/``_static_backend`` (``static_scr`` is None
# while suspended), and a per-instance window keeps its own backend handle.
_SUSPENDED: list[ConsoleWindow] = []

# None until the first ConsoleWindow is constructed.  The value is process-wide
# and deliberately never reset: ConsoleWindow(singleton=...) must agree on every
# construction or the assertion in __init__ fires.
_SINGLETON_MODE: bool | None = None

# ``atexit`` teardown is registered once for the whole process, not once per
# window, so creating multiple windows does not stack up duplicate handlers.
_ATEXIT_REGISTERED = False

# Sentinel for "no content-row ceiling" (opts.max_rows is None).  It only has to
# be larger than any row index a process could allocate; it is never passed to
# curses, because the pads themselves are viewport-sized.
_NO_ROW_LIMIT = sys.maxsize


def _register_window(win: ConsoleWindow) -> None:
    # The module-level registry owns the private back-pointer: only this module
    # allocates and clears the handle, and keeping it private keeps it out of
    # ConsoleWindow's public surface.
    key = next(_WINDOW_IDS)
    win._registry_key = key  # pylint: disable=protected-access
    _WINDOWS[key] = win


def _unregister_window(win: ConsoleWindow) -> None:
    key = getattr(win, '_registry_key', None)
    if key is not None:
        _WINDOWS.pop(key, None)
        win._registry_key = None  # pylint: disable=protected-access


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if not _ATEXIT_REGISTERED:
        atexit.register(ConsoleWindow.stop_all)
        _ATEXIT_REGISTERED = True


class TerminalTooSmallError(RuntimeError):
    # answer() could not present its dialog because the terminal is below the
    # effective minimum (the floor or the one-time first-screen fit) or the
    # requested box size.  This is deliberately a
    # RuntimeError (not a curses.error) so the dialog's own recovery loop cannot
    # swallow it, and it is distinct from answer() returning None, which means
    # the user aborted (AUDIT.md §3.6).
    def __init__(self, required_rows: int, required_cols: int,
                 actual_rows: int, actual_cols: int) -> None:
        self.required_rows = required_rows
        self.required_cols = required_cols
        self.actual_rows = actual_rows
        self.actual_cols = actual_cols
        super().__init__(
            f'terminal too small for dialog: need at least '
            f'{required_cols}x{required_rows}, have {actual_cols}x{actual_rows}')


class _StopCurses:
    """Dual-mode ``stop_curses`` descriptor.

    Pre-2.0 exposed ``stop_curses`` as a static method, so apps called
    ``ConsoleWindow.stop_curses()``; the per-instance model needs the bound
    window.  A descriptor distinguishes the two call shapes, which a plain
    method with ``self=None`` cannot do without lying to type checkers.

    Semantics depend on the window model:

    * singleton (the pre-2.0 model): ``stop_curses()`` *suspends* the shared
      screen and ``start_curses()`` resumes it, which keeps the historical
      stop/start pair working.  Use ``stop_all()`` for a permanent teardown.
    * per-instance: ``stop_curses()`` is a permanent teardown; use
      ``suspend_curses()``/``resume_curses()`` to pause and continue.
    """

    def __get__(self, obj: ConsoleWindow | None,
                objtype: type[ConsoleWindow]) -> Callable[[], None]:
        def stop() -> None:
            # The descriptor lives in the class body, so it deliberately reaches
            # the implementation methods that must stay off the public surface.
            if obj is None:
                objtype._stop_legacy()  # pylint: disable=protected-access
            else:
                obj._stop_instance()  # pylint: disable=protected-access
        return stop


class _Content:
    """One namespace's content: the rows that ``add_header()``/``add_body()`` append.

    A small object rather than a ``SimpleNamespace`` because ``row_cnt`` is
    derived from ``texts`` instead of being a second count that has to be kept
    in step.  The pads live here too: they are viewport-sized paint buffers, and
    keeping them beside the rows they paint is what makes ``win.body.pad``
    (the active view's namespace) keep working.
    """

    __slots__ = (
        'cols',
        'contexts',
        'hint_rows',
        'max_header_len',
        'pad',
        'pad_cols',
        'pad_rows',
        'rows',
        'rows_dropped',
        'text_attrs',
        'texts',
        'view_cnt',
    )

    def __init__(self, rows: int, hint_rows: int | None = None,
                 cols: int = 200) -> None:
        self.texts: list[str] = []
        self.text_attrs: list[list[tuple[int, int]]] = []  # RLE [(attr, count)]
        self.contexts: list[Context | None] = []
        self.rows = rows  # enforced ceiling (opts.max_rows or the sentinel)
        self.rows_dropped = 0
        self.hint_rows = hint_rows  # advisory opts.head_rows/body_rows
        self.cols = cols
        self.view_cnt = 0  # header rows visible (head only)
        self.pad: CursesSurface | None = None
        self.pad_rows = 0
        self.pad_cols = 0
        self.max_header_len = 0  # head only: widest header seen in this pass

    @property
    def row_cnt(self) -> int:
        """Number of rows added (``len(texts)``: there is no other store)."""
        return len(self.texts)

    def reset(self) -> None:
        """Drop the rows for a new pass; the pads are erased at paint time."""
        self.texts.clear()
        self.text_attrs.clear()
        self.contexts.clear()
        self.rows_dropped = 0
        self.view_cnt = 0
        self.max_header_len = 0


class _ViewState:
    """Pick/scroll state plus content for one screen (package-private).

    :class:`~console_window.screens.Screen` inherits this, so a screen *is* its
    view state and ``screen.pick_pos`` needs no double naming.  The window keeps
    a pointer (``win._view``) at whichever one is current, which is what makes
    stack activation a pointer swap instead of a copy.  A window-owned instance
    is also the fallback for a ``ScreenStack`` built from bare screen numbers.

    ``reset()`` is content-only: ``pick_pos``/``scroll_pos``/``free_scroll``
    describe the user's position in that screen and survive a rebuild pass.
    """

    __slots__ = (
        '_opts_seeded',
        'body',
        'free_scroll',
        'head',
        'pick_mode',
        'pick_pos',
        'pick_range',
        'pick_size',
        'scroll_pos',
    )

    def __init__(self) -> None:
        self.pick_mode = False
        self.pick_size = 1
        self.pick_pos = 0
        self.scroll_pos = 0
        self.free_scroll = False
        self.pick_range: list[int] | None = None  # [start_col, end_col] or None
        self.head = _Content(_NO_ROW_LIMIT)
        self.body = _Content(_NO_ROW_LIMIT)
        # opts is a seed, not an owner: a Screen may be built before the window
        # (and before any opts exist), so the window applies it at adoption.
        self._opts_seeded = False

    def set_pick_mode(self, on: bool = True, pick_size: int = 1) -> None:
        """Turn the pick highlight on or off for *this* screen."""
        self.pick_mode = bool(on)
        self.pick_size = max(pick_size, 1)

    def set_pick_range(self, start_col: int | None = None,
                       end_col: int | None = None) -> None:
        """Set the highlighted column range for *this* screen's picked row."""
        self.pick_range = (None if start_col is None or end_col is None
                           else [start_col, end_col])

    def reset(self) -> None:
        """Reset content for a new pass, preserving the view position."""
        self.head.reset()
        self.body.reset()


class ConsoleWindow:
    """A curses pad-based pager with an independent pick/scroll model.

    In-place prompts
    ----------------
    While :attr:`prompt_active` is true, the application must route *every*
    key through :meth:`handle_prompt_key` and swallow a ``'continue'`` result.
    Doing so guarantees that no action key fires underneath a live prompt.
    Completion callbacks run after the prompt is gone and passthrough mode has
    been restored, so a callback may safely call :meth:`begin_prompt` again
    (that is how a "re-edit, then ENTER or ESC" flow re-asks).  The application
    decides where prompt rows are drawn: ``add_prompt_header()`` for screen-wide
    questions, ``add_prompt_lines()`` from its own row loop for item-scoped
    ones.  The window never learns which row that is.

    Content and the pick/scroll position belong to the current
    :class:`~console_window.screens.Screen`; the window paints it, owns the
    terminal and routes keys.  The ``win.head``/``win.body`` and
    ``win.pick_*``/``win.scroll_pos`` attributes below are views onto that
    current screen.
    """

    stop_curses = _StopCurses()
    timeout_ms: int = 2000
    # Set by _register_window(); None once stop_curses() unregisters the window.
    _registry_key: int | None = None
    # Wall-clock budget (seconds) for retrying transient curses errors, instead
    # of a fixed iteration count, so a persistent error aborts quickly rather
    # than freezing the UI for ~20 s.  It is deliberately a class-level knob and
    # is read as ``ConsoleWindow.render_retry_seconds``; render() and answer()
    # share it (AUDIT.md §3.2).  Tune it on the class before starting a window:
    # assigning it on one instance has no effect because the lookup bypasses the
    # instance, and there is no dialog-specific budget by design.
    render_retry_seconds: float = 2.0
    # Seconds to wait between retries; class-level for the same reason.
    render_retry_interval: float = 0.16
    #: Level -> attribute for :meth:`status`.  A class attribute so a theme or
    #: application can patch it without subclassing the window.
    STATUS_LEVELS: ClassVar[dict[str, int]] = {
        'info': curses.A_DIM,
        'warn': curses.A_BOLD,
        'error': curses.A_BOLD | curses.A_REVERSE,
    }
    # flash() repaints the underlying screen from the pads when it finishes, so
    # callers no longer have to re-render afterwards. Set False to make flash()
    # purely additive (e.g. when the caller is about to redraw anyway).
    flash_repaint: bool = True
    # How often (milliseconds) flash() polls for a key while the message is up.
    flash_poll_ms: int = 50
    # How often (milliseconds) alert() polls for a key while its box is up.  A
    # finite interval keeps the modal resize-aware (and lets a headless backend
    # drive the loop) without changing what the user sees.
    alert_poll_ms: int = 250
    # One-time minimum-size policy.  opts.min_cols_rows is the floor; after the
    # first rendered screen the floor grows to fit that screen's header plus a
    # small body.  The width is capped so a long header cannot demand an
    # unreasonable terminal, and the wiggle room covers the pick gutter, the
    # scroll indicator and header values that grow later (a pass counter, a
    # filename).  The values are policy, not options: apps that need a different
    # floor pass min_cols_rows explicitly.
    _AUTO_MIN_COLS_CAP: ClassVar[int] = 60
    _AUTO_MIN_WIGGLE_COLS: ClassVar[int] = 3
    _AUTO_MIN_BODY_ROWS: ClassVar[int] = 4
    # Populated only in singleton mode (the default).  The old API exposed these
    # as the process-wide screen and active window; they are kept for the apps
    # that relied on that model and remain None in per-instance mode.
    static_scr: CursesSurface | None = None
    static_win: ConsoleWindow | None = None
    # Backend that created ``static_scr``; teardown must use it even after a
    # later instance (with a different backend) has replaced ``static_win``.
    _static_backend: RenderBackend | None = None
    nav_keys: str = '\n'.join(NAV_KEY_LINES)
    def __init__(self, opts: ConsoleWindowOpts | None = None, head_line: bool | None = None,
                 head_rows: int | None = None, body_rows: int | None = None,
                 body_cols: int | None = None, keys: set | list | None = None,
                 pick_mode: bool | None = None, pick_size: int | None = None,
                 mod_pick: Callable | None = None, ctrl_c_terminates: bool | None = None,
                 backend: RenderBackend | None = None, singleton: bool = True) -> None:
        # Enforce either opts OR deprecated parameters, not both
        has_opts = opts is not None
        has_deprecated = any(p is not None for p in [head_line, head_rows, body_rows, body_cols,
                                                       keys, pick_mode, pick_size, mod_pick, ctrl_c_terminates])

        if has_opts and has_deprecated:
            raise ValueError("Cannot use both 'opts' and deprecated parameters. Use opts only.")

        # The singleton choice is process-wide: mixing modes would make screen
        # ownership and teardown ambiguous, so the first successful construction
        # latches it and any later disagreement is a programming error.
        global _SINGLETON_MODE
        mode = bool(singleton)
        if _SINGLETON_MODE is None:
            _SINGLETON_MODE = mode
        else:
            assert mode == _SINGLETON_MODE, (
                f'ConsoleWindow(singleton={mode}) conflicts with this process '
                f'(singleton={_SINGLETON_MODE}); every window must use the same value')
        self.singleton = mode

        # Use opts or create default
        if has_opts:
            assert opts is not None  # guaranteed by has_opts
            self.opts = opts
        elif has_deprecated:
            # Backward compatibility: create opts from deprecated parameters.
            # Warn so applications get a migration signal before these are
            # removed; stacklevel=2 points at the caller, not this module.
            warnings.warn(
                'ConsoleWindow(head_line=..., head_rows=..., body_rows=..., '
                'body_cols=..., keys=..., pick_mode=..., pick_size=..., '
                'mod_pick=..., ctrl_c_terminates=...) is deprecated; pass '
                'ConsoleWindowOpts through opts= instead.',
                DeprecationWarning,
                stacklevel=2,
            )
            self.opts = ConsoleWindowOpts(
                head_line=head_line if head_line is not None else True,
                head_rows=head_rows,
                body_rows=body_rows,
                body_cols=body_cols if body_cols is not None else 200,
                keys=keys,
                pick_mode=pick_mode if pick_mode is not None else False,
                pick_size=pick_size if pick_size is not None else 1,
                mod_pick=mod_pick,
                ctrl_c_terminates=ctrl_c_terminates if ctrl_c_terminates is not None else True
            )
        else:
            # No parameters provided - use all defaults
            self.opts = ConsoleWindowOpts()

        # Per-window theme (AUDIT.md §3.1).  opts.theme seeds it; otherwise the
        # window inherits the process default, which is what existing apps saw
        # before themes were per-window.  curses owns a single pair table per
        # terminal, so *applying* a theme is still terminal-global; what is now
        # per-window is the choice, its use at startup and when pads are
        # reallocated, and the far more common case of several windows in one
        # process that are not drawn at the same time.
        self.theme = Theme.resolve(
            getattr(self.opts, 'theme', None) or Theme.get_current())

        # Glyph mode and vocabulary.  Like the theme, the *mode* is
        # process-global (there is one terminal); the option seeds it.
        self._apply_glyph_mode()

        # Configure SIGINT policy (Ctrl-C terminates, or is delivered as key 0x3).
        signals.set_ctrl_c_policy(self.opts.ctrl_c_terminates)
        self.ctrl_c_terminates = self.opts.ctrl_c_terminates

        self._backend: RenderBackend = backend if backend is not None else CursesBackend()
        # The backend seam's Surface protocol is deliberately small; the full
        # drawing API is described by CursesSurface, which is only a cast target
        # (curses.window and HeadlessBackend's no-op surface both satisfy it at
        # runtime).  This keeps addstr/border/insstr/... type-checked.
        if self.singleton and _SUSPENDED:
            # A suspended shared screen must be resumed before another window
            # can join it; otherwise the new window would draw into a terminal
            # that is still in shell mode.
            ConsoleWindow._resume_singleton()
        if self.singleton and ConsoleWindow.static_scr is not None:
            # Singleton mode: every instance draws through the process screen
            # and the backend that owns it, even if a different backend was
            # passed to this constructor.  The shared screen's palette was
            # installed by the window that created it; a later window records
            # its own theme but does not repaint the others (use set_theme()).
            self._backend = ConsoleWindow._static_backend or self._backend
            self.scr = ConsoleWindow.static_scr
        else:
            self.scr = self._new_screen()
            if self.singleton:
                ConsoleWindow.static_scr = self.scr
                ConsoleWindow._static_backend = self._backend
        # curses.window exposes no gettimeout(), so every place that sets a read
        # timeout records it here (via _set_scr_timeout).  This lets modal
        # dialogs such as answer() restore the timeout that was in effect before
        # they ran, instead of assuming the class default.
        self._scr_timeout_ms = ConsoleWindow.timeout_ms

        # Scheme B: the pads are viewport-sized blit buffers, not content
        # stores.  Content lives on the current screen's _ViewState, so
        # `win.head`/`win.body` are properties onto it and nothing is copied on
        # activation.  The fallback view is used until a Screen is adopted, and
        # permanently by a stack built from bare screen numbers.
        # _sync_pad_geometry() creates/sizes the pads once the terminal
        # dimensions are known (calc() runs at the end of __init__), so no
        # oversized placeholder is ever allocated.
        self._fallback_view = _ViewState()
        self._view: _ViewState = self._fallback_view
        self._seed_view(self._fallback_view)

        # Register this instance so theme broadcasts and process teardown reach
        # it.  Singleton mode also republishes the old ``static_win`` pointer.
        _register_window(self)
        if self.singleton:
            ConsoleWindow.static_win = self

        self.mod_pick = self.opts.mod_pick # call back to modify highlighted row
        self.hor_line_cnt = 1 if self.opts.head_line else 0 # no. h-lines in header
        self.max_scroll_pos = 0
        # True between suspend_curses() and resume_curses()/start_curses(): the
        # terminal was handed back (endwin) but the pads and content model stay
        # valid, so the window can be reattached to a screen later.
        self.suspended = False
        self.rows, self.cols = 0, 0
        # True once a frame has actually been painted; the one-time minimum is
        # measured from that first frame (see _finalize_min_size).
        self._has_rendered = False
        self._auto_min_cols_rows: tuple[int, int] | None = None
        self.body_cols, self.body_rows = self.opts.body_cols, self.opts.body_rows
        self.scroll_view_size = 0  # no. viewable lines of the body
        self.handled_keys = set(self.opts.keys) if isinstance(self.opts.keys, (set, list)) else set()
        self.pending_keys: set[int] = set()
        self.last_demo_key = ''  # Last key pressed in demo mode
        self.passthrough_mode = False  # When True, all printable keys pass through
        # In-place prompt widget and the passthrough value to restore when it
        # ends, so a callback can start the next prompt (see begin_prompt()).
        self.prompt_line = PromptLine()
        self._prompt_prev_passthrough = False
        # Extra attribute for the separator rule while a prompt is live, so the
        # chrome can recede behind the only interactive line on screen.  None
        # (the default) leaves the rule undifferentiated.  This is app policy,
        # like pick_attr: the window only decides *when* to apply it.
        self.prompt_separator_attr: int | None = None
        # Transient status shown on the separator row (see status()).  Kept on
        # the window rather than a pad because the row belongs to the screen,
        # not to either pad (render_once() paints it directly on self.scr).
        self._status_text = ''
        self._status_attr: int | None = None
        self._status_deadline: float | None = None
        self._status_no_row_warned = False
        self.relax_handled_keys = self.opts.relax_handled_keys  # When True, pass non-nav keys without checking handled_keys
        self._set_screen_dims()
        self.calc()  # also creates the viewport-sized pads

    def set_handled_keys(self, keys: object) -> None:
        if hasattr(keys, 'keys'):
            # It's an OptionSpinner or similar object
            self.handled_keys = set(keys.keys) if keys.keys else set()
        elif isinstance(keys, (set, list)):
            self.handled_keys = set(keys)
        else:
            self.handled_keys = set()

    @contextmanager
    def temp_handled_keys(self, *keys: int) -> Iterator[ConsoleWindow]:
        """Temporarily add key codes to ``handled_keys``.

        ``prompt()`` only returns a key that is in ``handled_keys`` (or one of
        the built-in passthrough editing keys).  This context manager makes
        that forwarding reversible by construction: only the keys it actually
        added are removed on exit, so nested uses leave a pre-existing binding
        intact.

        Example: forwarding an application key for one inline edit::

            win.passthrough_mode = True
            with win.temp_handled_keys(27):
                key = win.prompt(seconds=0.5)
            win.passthrough_mode = False
        """
        added = {key for key in keys if key not in self.handled_keys}
        self.handled_keys.update(added)
        try:
            yield self
        finally:
            self.handled_keys.difference_update(added)

    def set_demo_mode(self, enabled: bool | None) -> bool:
        if enabled is None: # toggle if not explicit
            self.opts.demo_mode = not (self.opts.demo_mode)
        else:
            self.opts.demo_mode = bool(enabled)
        if not self.opts.demo_mode:
            self.last_demo_key = ''
        return self.opts.demo_mode

    def _format_key_for_demo(self, key: int) -> str:
        label = _DEMO_KEY_LABELS.get(key)
        if label is not None:
            return label
        # Printable single character keys - center with spaces
        if 32 < key < 127:
            return f' {chr(key)} '
        # Named curses key, control character, or an explicit <code>
        return _key_label(key)

    def get_pad_width(self) -> int:
        return min(self.cols-1, self.body_cols)

    # --- content and view indirection --------------------------------------
    #
    # Content and pick/scroll state belong to the current screen (a _ViewState,
    # which Screen inherits).  These properties keep every existing internal
    # read/write -- and the documented ``win.body``/``win.pick_pos`` surface --
    # working without a copy on screen activation.

    def _seed_view(self, view: _ViewState) -> None:
        """Apply ``opts`` to *view* the first time it is adopted.

        Screens may be built before the window (and before its opts), so the
        defaults cannot live in their constructor; adoption is the one moment
        both exist.  ``opts`` is a seed, never an owner: after this call the
        screen's own fields are authoritative, so two screens can hold
        different pick ranges and modes.
        """
        if view._opts_seeded:  # pylint: disable=protected-access
            return
        row_limit = (self.opts.max_rows if self.opts.max_rows is not None
                     else _NO_ROW_LIMIT)
        for content, hint in ((view.head, self.opts.head_rows),
                              (view.body, self.opts.body_rows)):
            content.rows = row_limit
            content.hint_rows = hint
            content.cols = self.opts.body_cols
        view.pick_mode = bool(self.opts.pick_mode)
        view.pick_size = max(self.opts.pick_size, 1)
        view.pick_range = self.opts.pick_range
        view._opts_seeded = True  # pylint: disable=protected-access

    def _adopt_view(self, view: _ViewState) -> None:
        """Point the window at *view* and seed it if it is new.

        Called by ``Screen.clear()`` (the loop's first call, which is why that
        order is fixed) and by ``ScreenStack`` on activation.  A window cannot
        discover a screen on its own, so the screen hands itself over.

        The pads are viewport buffers owned by the content they paint, so a
        newly adopted view gets its own pair sized to the current terminal.
        Without this, a screen that has never been rendered has ``pad is None``
        and the first ``render(redraw=True)`` would fail on ``redrawwin()``.
        """
        self._seed_view(view)
        self._view = view
        if getattr(self, 'scr', None) is not None:
            if view.head.pad is None or view.body.pad is None:
                self._sync_pad_geometry()
            # A theme may have changed while this screen was inactive; the pad
            # background is per-pad, so re-apply it to the incoming view's pads.
            for content in (view.head, view.body):
                if content.pad is not None:
                    self._apply_pad_theme(cast(CursesSurface, content.pad))

    @property
    def head(self) -> _Content:
        """The active screen's header content (write it through a Screen)."""
        return self._view.head

    @property
    def body(self) -> _Content:
        """The active screen's body content (write it through a Screen)."""
        return self._view.body

    @property
    def pick_mode(self) -> bool:
        """Whether the active screen shows a pick highlight."""
        return self._view.pick_mode

    @pick_mode.setter
    def pick_mode(self, value: bool) -> None:
        self._view.pick_mode = bool(value)

    @property
    def pick_size(self) -> int:
        """How many rows the active screen's pick highlight spans."""
        return self._view.pick_size

    @pick_size.setter
    def pick_size(self, value: int) -> None:
        self._view.pick_size = max(int(value), 1)

    @property
    def pick_pos(self) -> int:
        """The active screen's picked content row."""
        return self._view.pick_pos

    @pick_pos.setter
    def pick_pos(self, value: int) -> None:
        self._view.pick_pos = value

    @property
    def scroll_pos(self) -> int:
        """The active screen's top visible body row."""
        return self._view.scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value: int) -> None:
        self._view.scroll_pos = value

    @property
    def free_scroll(self) -> bool:
        """True while the active screen is scrolled away from its picked row."""
        return self._view.free_scroll

    @free_scroll.setter
    def free_scroll(self, value: bool) -> None:
        self._view.free_scroll = bool(value)

    @property
    def pick_range(self) -> list[int] | None:
        """The active screen's highlighted column range (or None)."""
        return self._view.pick_range

    @pick_range.setter
    def pick_range(self, value: list[int] | None) -> None:
        self._view.pick_range = value

    @property
    def max_rows(self) -> int | None:
        """The enforced per-namespace content ceiling (None = unlimited)."""
        return self.opts.max_rows

    @property
    def ascii_mode(self) -> bool:
        """True when this process draws the plain-ASCII glyph set."""
        return glyphs.is_ascii()

    def glyph(self, name: str) -> str:
        """Return a registered glyph in the active set (see ``Glyphs.get``)."""
        return glyphs.get(name)

    def _apply_glyph_mode(self) -> None:
        """Register the app's glyphs and seed the process-wide glyph mode.

        ``opts.ascii`` seeds the mode only when it is not ``None``; otherwise
        auto-detection runs, but only if nothing has decided yet (see
        :func:`console_window.glyphs.ensure_policy`).  That is what keeps an
        app-wide ``--ascii`` from being undone by the next window constructed.
        """
        if self.opts.glyphs:
            glyphs.register_many(self.opts.glyphs, probe=self.opts.glyphs_probe)
        elif self.opts.glyphs_probe:
            glyphs.probe(*self.opts.glyphs_probe)
        if self.opts.ascii is not None:
            glyphs.set_ascii(self.opts.ascii)
        else:
            glyphs.ensure_policy()

    def set_theme(self, theme_name: str) -> bool:
        """Make *theme_name* this window's theme and install its colors.

        Returns False for an unknown theme, or for a palette when the backend
        has no color support (the choice is still recorded, so a later
        color-capable start uses it).  ``mono`` is always applicable: it needs
        no color pairs and is the attribute hierarchy itself.  Color pairs are
        per-terminal, so installing a palette necessarily also affects any
        other window drawing on the same screen — that is a curses constraint,
        not a choice.  What is per-window is the selection: it is used at
        startup, when pads are reallocated, and reported by ``window.theme``.
        """
        name = Theme.canonical(theme_name)
        if name is None:
            return False
        self.theme = name
        # The choice is real even when nothing can be painted, and new windows
        # inherit the most recently applied theme.  This also synchronizes the
        # appearance switch (mono off, palettes on).
        Theme.set_active(name)
        if not self._backend.has_colors() and not Theme.is_mono(name):
            return False
        self.theme = self._install_theme(self._backend, self.scr, name)
        for ns in (self.head, self.body):
            pad = getattr(ns, 'pad', None)
            if pad is not None:
                self._apply_pad_theme(cast(CursesSurface, pad))
        Theme.set_active(self.theme)
        return True

    def _apply_pad_theme(self, pad: CursesSurface) -> None:
        # A freshly created pad has no background, so re-apply the theme color
        # after every reallocation; otherwise a resize leaves the new pad on the
        # terminal default instead of the configured background.  The color
        # comes from *this window's* theme, not the process default.
        if not self._backend.has_colors():
            return
        theme = Theme.THEMES[Theme.resolve(getattr(self, 'theme', None))]
        if ('default_fg' in theme and 'default_bg' in theme
                and Theme.DEFAULT_BG < self._backend.color_pairs()):
            # Theme.install() has already installed this pair with either the
            # literal values or the low-color mapping, so bkgd() never sees a
            # stale/out-of-range pair.
            pad.bkgd(' ', self._backend.color_pair(Theme.DEFAULT_BG))

    def _sync_pad_geometry(self) -> None:
        # Viewport-sized pads: height is the terminal height and width is the
        # blittable width (cols-1 with the last column reserved), so neither
        # content length nor opts.body_rows has any effect on pad memory or on
        # pad clear()/erase() cost.  Called from calc(), i.e. once per frame,
        # but it only allocates when the terminal dimensions actually changed.
        height = max(1, self.rows)
        width = max(1, self.cols - 1)
        for ns in (self.head, self.body):
            if ns.pad_rows == height and ns.pad_cols == width:
                continue
            ns.pad = self._backend.newpad(height, width)
            ns.pad_rows, ns.pad_cols = height, width
            self._apply_pad_theme(cast(CursesSurface, ns.pad))

    @property
    def rows_dropped(self) -> int:
        # Rows handed to add_body()/add_header() after that namespace reached
        # opts.max_rows (the only ceiling; None disables it).  body_rows and
        # head_rows are advisory hints and never drop anything.  This counter,
        # plus the one-shot warning in _add(), keeps a runaway append loop
        # observable without the library deciding to abort the app.
        return self.head.rows_dropped + self.body.rows_dropped

    def _is_pickable(self, row: int) -> bool:
        if row < 0 or row >= len(self.body.contexts):
            return True  # Default to pickable if no context
        ctx = self.body.contexts[row]
        if ctx is None:
            return True  # Default to pickable if no context
        return ctx.pickable

    def _count_pickable_rows(self, start_pos: int, count: int, direction: int = 1) -> int:
        return geometry.count_pickable_rows(
            self._is_pickable, self.body.row_cnt, start_pos, count, direction)

    def get_picked_context(self) -> Context | None:
        if not self.pick_mode:
            return None
        if self.pick_pos < 0 or self.pick_pos >= len(self.body.contexts):
            return None
        return self.body.contexts[self.pick_pos]

    def _cook_abut(self, abut_value: geometry.AbutSpec) -> tuple[int, int] | None:
        return geometry.cook_abut(abut_value)

    def _get_effective_abut(self, row: int) -> geometry.AbutSpec:
        if row < 0 or row >= len(self.body.contexts):
            return None

        ctx = self.body.contexts[row]
        if ctx is None:
            return None

        # Explicit abut takes precedence
        explicit = getattr(ctx, 'abut', None)

        # Auto-abut for TRANSIENT: count consecutive TRANSIENT rows below
        transient_count = 0
        for i in range(row + 1, self.body.row_cnt):
            next_ctx = self.body.contexts[i] if i < len(self.body.contexts) else None
            if next_ctx and next_ctx.genre == 'TRANSIENT':
                transient_count += 1
            else:
                break

        return geometry.compute_abut(explicit, transient_count)

    @staticmethod
    def get_nav_keys_blurb() -> str:
        return ConsoleWindow.nav_keys

    @staticmethod
    def get_nav_key_lines() -> tuple[str, ...]:
        return NAV_KEY_LINES

    def nav_help_lines(self) -> tuple[str, ...]:
        """Navigation help for *this* window's effective key set."""
        return render_nav_help(self.opts.nav_keys, self.opts.taken_nav_keys)

    def _set_screen_dims(self) -> bool:
        rows, cols = self.scr.getmaxyx()
        same = bool(rows == self.rows and cols == self.cols)
        self.rows, self.cols = rows, cols
        return same

    def _set_scr_timeout(self, ms: int) -> None:
        self._scr_timeout_ms = ms
        self.scr.timeout(ms)

    def _min_size(self) -> tuple[int, int]:
        """The effective ``(cols, rows)`` floor: the option plus the one-time fit."""
        floor_cols, floor_rows = self.opts.min_cols_rows
        fit: tuple[int, int] | None = getattr(self, '_auto_min_cols_rows', None)
        if fit is None:
            return floor_cols, floor_rows
        return max(floor_cols, fit[0]), max(floor_rows, fit[1])

    def _finalize_min_size(self) -> None:
        """Fold the first painted screen's shape into the minimum, once.

        The first screen is the application's "first impression": its widest
        header (measured before truncation, so drawing on a narrow terminal
        cannot shrink the answer) sets the width, and its header height plus a
        small body sets the height.  Later screens and later passes are
        deliberately ignored; the wiggle room and the explicit
        ``min_cols_rows`` floor cover header values that grow.
        """
        if (getattr(self, '_auto_min_cols_rows', None) is not None
                or not getattr(self, '_has_rendered', False)):
            return
        floor_cols, floor_rows = self.opts.min_cols_rows
        fit_cols = min(self._AUTO_MIN_COLS_CAP,
                       self.head.max_header_len + self._AUTO_MIN_WIGGLE_COLS)
        fit_rows = (self.head.row_cnt + self._AUTO_MIN_BODY_ROWS
                    + self.hor_line_cnt)
        self._auto_min_cols_rows = (max(floor_cols, fit_cols),
                                    max(floor_rows, fit_rows))

    def _check_min_size(self) -> bool:
        """Wait until the terminal meets the effective minimum.

        Dimensions are re-read in the wait loop rather than only on
        ``KEY_RESIZE``: a terminal can be resized without delivering that key,
        and a headless backend never does.  The fast path is one ``getmaxyx``.
        """
        self._set_screen_dims()
        min_cols, min_rows = self._min_size()
        if self.rows >= min_rows and self.cols >= min_cols:
            return True

        while True:
            # curses caches LINES/COLS; refresh before re-reading so growing
            # out of the notice is noticed within one getch() timeout.
            self._backend.update_lines_cols()
            self._set_screen_dims()
            min_cols, min_rows = self._min_size()
            if self.rows >= min_rows and self.cols >= min_cols:
                return True
            self.scr.clear()
            msg1 = f"Min size: {min_cols}x{min_rows}"
            msg2 = f"Current: {self.cols}x{self.rows}"
            try:
                self.scr.addstr(0, 0, msg1, curses.A_REVERSE)
                self.scr.addstr(1, 0, msg2, curses.A_REVERSE)
            except curses.error:
                pass  # Terminal too small even for message
            self.scr.refresh()

            key = self.scr.getch()
            if key == 27:  # ESC to abort
                return False

    def _new_screen(self) -> CursesSurface:
        """Create and initialize a brand-new screen for this window."""
        return self._init_screen(self._backend, self.theme)

    def _start_curses(self) -> CursesSurface:
        """Re-enter curses for this window and return the live screen.

        Pre-2.0 exposed ``_start_curses()`` as the "come back after
        ``stop_curses()``" call, and applications (psistat among them) kept
        calling it on the instance.  It therefore has to *reattach* the
        window, not merely create a screen: the old implementation returned a
        fresh screen without storing it, so ``self.scr`` stayed ``None`` and
        the first ``clear()``/``render()`` after returning from shell mode
        raised ``AttributeError: 'NoneType' object has no attribute 'clear'``.

        A suspended window resumes through :meth:`resume_curses` (in singleton
        mode that reattaches every window sharing the screen), so the pads and
        the content model survive.  ``start_curses()`` remains the class-level
        entry point for both models.
        """
        if self.suspended:
            scr = self.resume_curses()
            if scr is not None:
                return scr
        if self.scr is not None:
            return self.scr
        # Not suspended but screen-less: restart a screen and attach this
        # window to it.  Singleton mode owns a process-wide screen, so reuse the
        # class-level starter; per-instance windows create their own.
        scr = ConsoleWindow.start_curses() if self.singleton else self._new_screen()
        if self.scr is None:  # start_curses() may have reattached it already
            backend = (ConsoleWindow._static_backend if self.singleton else None) \
                or self._backend
            self._attach_screen(scr, backend)
        return scr

    def _attach_screen(self, scr: CursesSurface, backend: RenderBackend) -> None:
        """Point this window at a (re)started screen and force a full repaint.

        Used by resume_curses()/start_curses() after a suspend.  The content
        model and pads survive ``endwin()``; only the screen handle, the
        backend that owns it, the dimensions, the pad backgrounds and the
        redraw bookkeeping have to be refreshed.
        """
        self._backend = backend
        self.scr = scr
        self.suspended = False
        _register_window(self)
        self.calc()  # dimensions + pad reallocation through the new backend
        self._set_scr_timeout(self._scr_timeout_ms)
        for ns in (self.head, self.body):
            self._apply_pad_theme(cast(CursesSurface, ns.pad))
        self._mark_pads_for_redraw()
        self._clear_surface()

    def suspend_curses(self) -> None:
        """Leave curses mode without destroying this window.

        ``endwin()`` restores the terminal but keeps the curses SCREEN (and
        therefore the pads) alive, so the next :meth:`resume_curses` can
        reattach a screen and the next ``render()`` repaints.  In singleton
        mode all windows share one screen, so this suspends them together.
        Use :meth:`stop_curses` when the window is finished for good.
        """
        if getattr(self, 'singleton', False):
            ConsoleWindow._suspend_singleton()
            return
        scr = getattr(self, 'scr', None)
        if scr is None or self.suspended:
            return
        try:
            backend = getattr(self, '_backend', None) or CursesBackend()
            backend.stop(scr)
        finally:
            self.scr = cast(CursesSurface, None)
            self.suspended = True
            _unregister_window(self)
            signals.teardown_ctrl_c()

    def resume_curses(self) -> CursesSurface | None:
        """Re-enter curses after :meth:`suspend_curses`.

        Returns the (new) screen, or None when the window was not suspended.
        The next ``render()`` repaints from the preserved content model.
        """
        if getattr(self, 'singleton', False):
            return ConsoleWindow._resume_singleton()
        if not self.suspended:
            return self.scr
        backend = getattr(self, '_backend', None) or CursesBackend()
        scr = self._init_screen(backend, self.theme)
        self._attach_screen(scr, backend)
        return scr

    @classmethod
    def start_curses(cls, backend: RenderBackend | None = None) -> CursesSurface:
        # Legacy class-level entry point: in singleton mode it shares the one
        # process screen rather than starting a second terminal session.  When
        # windows were suspended by stop_curses()/suspend_curses(), this is the
        # matching resume: every suspended window is reattached to the screen
        # (the backend argument is ignored then -- the screen belongs to the
        # backend that created it).
        if _SINGLETON_MODE and _SUSPENDED:
            scr = cls._resume_singleton()
            if scr is not None:
                return scr
        if _SINGLETON_MODE and cls.static_scr is not None:
            return cls.static_scr
        screen_backend = backend if backend is not None else CursesBackend()
        # No window exists yet at this point, so the process default is used.
        scr = cls._init_screen(screen_backend)
        if _SINGLETON_MODE:
            cls.static_scr = scr
            cls._static_backend = screen_backend
        return scr

    @classmethod
    def _suspend_singleton(cls) -> None:
        """Leave the shared screen, keeping every window resumable."""
        scr = cls.static_scr
        if scr is None:
            return
        backend = cls._static_backend or CursesBackend()
        windows = list(_WINDOWS.values())
        try:
            backend.stop(scr)
        finally:
            cls.static_scr = None
            for win in windows:
                win.scr = cast(CursesSurface, None)
                win.suspended = True
                _unregister_window(win)
                signals.teardown_ctrl_c()
                if win not in _SUSPENDED:
                    _SUSPENDED.append(win)
            # static_win is deliberately kept: it is the anchor that
            # start_curses()/resume_curses() uses to restore the theme and is
            # replaced by the next singleton window construction.

    @classmethod
    def _resume_singleton(cls) -> CursesSurface | None:
        """Re-enter the shared screen and reattach every suspended window."""
        if not _SUSPENDED:
            return cls.static_scr
        backend = cls._static_backend or CursesBackend()
        anchor = cls.static_win
        scr = cls._init_screen(backend, anchor.theme if anchor is not None else None)
        cls.static_scr = scr
        cls._static_backend = backend
        windows = list(_SUSPENDED)
        del _SUSPENDED[:]
        for win in windows:
            win._attach_screen(scr, backend)  # pylint: disable=protected-access
        return scr

    @staticmethod
    def _install_theme(backend: RenderBackend, scr: CursesSurface,
                       theme_name: str | None) -> str:
        """Install *theme_name*'s colors into the terminal's pair table.

        Color pairs are per-terminal (one table, not one per window), so both
        startup and ``set_theme()`` call this; the caller decides *whose*
        theme wins.  The actual installation (including low-color mapping and
        ``-1`` resolution) lives in :meth:`Theme.install`, which ``Theme.set()``
        uses too, so the two entry points cannot diverge.  Returns the resolved
        theme name.
        """
        name = Theme.install(backend, theme_name)
        theme = Theme.THEMES[name]
        # Can't change pair 0, so the screen background is set directly.  The
        # pair has just been installed above (with mapped values on low-color
        # terminals), so this never references a stale or out-of-range pair.
        if ('default_fg' in theme and 'default_bg' in theme
                and Theme.DEFAULT_BG < backend.color_pairs()):
            scr.bkgd(' ', backend.color_pair(Theme.DEFAULT_BG))
        return name

    @staticmethod
    def _init_screen(backend: RenderBackend,
                     theme_name: str | None = None) -> CursesSurface:
        _register_atexit()
        signals.setup_ctrl_c()
        scr = cast(CursesSurface, backend.start(ConsoleWindow.timeout_ms))

        # Initialize color support with theme.  Every color call goes through
        # the backend, so a non-curses backend that reports colors can use it.
        if backend.has_colors():
            # start_color() is where a curses backend captures COLORS and
            # COLOR_PAIRS; Theme.install() then enables default colors (and
            # remembers whether -1 is usable) before resolving each pair.
            backend.start_color()
            # The window's own theme (per-window since AUDIT.md §3.1) or the
            # process default for a window that has not chosen one yet.
            name = ConsoleWindow._install_theme(backend, scr, theme_name)
        else:
            # No color support: a palette cannot be painted, but mono is still
            # a real theme and must be recorded so the attribute hierarchy and
            # the window label agree.
            name = Theme.resolve(theme_name)
        # New windows inherit the most recently applied theme.  set_active()
        # also synchronizes the appearance switch.
        Theme.set_active(name)

        return scr

    def set_pick_mode(self, on: bool = True, pick_size: int = 1) -> None:
        """Set pick mode on the *current* screen (see ``Screen.set_pick_mode``)."""
        self._view.set_pick_mode(on, pick_size)

    def set_pick_range(self, start_col: int | None = None, end_col: int | None = None) -> None:
        """Set the pick column range on the *current* screen.

        Kept on the window for 4.x compatibility; it no longer writes
        ``opts.pick_range``, so two screens can hold different ranges.
        """
        self._view.set_pick_range(start_col, end_col)

    def _stop_instance(self) -> None:
        """Stop this window (and, in singleton mode, suspend the shared screen)."""
        if getattr(self, 'singleton', False):
            # Backward compatibility: in singleton mode the legacy
            # stop_curses()/start_curses() pair is a suspend/resume pair, so
            # stop_curses() leaves the screen resumable.  stop_all() is the
            # permanent teardown.
            ConsoleWindow._suspend_singleton()
            return

        scr = getattr(self, 'scr', None)
        if scr is None:
            self.suspended = False
            return
        try:
            backend = getattr(self, '_backend', None) or CursesBackend()
            backend.stop(scr)
        finally:
            self.scr = cast(CursesSurface, None)
            self.suspended = False
            _unregister_window(self)
            signals.teardown_ctrl_c()

    @classmethod
    def _stop_legacy(cls) -> None:
        """The pre-2.0 ``ConsoleWindow.stop_curses()`` call (suspends in singleton mode)."""
        assert _SINGLETON_MODE is not False, (
            'ConsoleWindow.stop_curses() without an instance is only valid '
            'in singleton mode; use win.stop_curses() or ConsoleWindow.stop_all()')
        win = cls.static_win
        if win is not None:
            win.stop_curses()

    @classmethod
    def _stop_singleton(cls) -> None:
        """Tear down the shared screen and forget every window (including suspended)."""
        scr = ConsoleWindow.static_scr
        windows = list(_WINDOWS.values())
        suspended = list(_SUSPENDED)
        del _SUSPENDED[:]
        ConsoleWindow.static_scr = None
        ConsoleWindow.static_win = None
        backend = ConsoleWindow._static_backend
        ConsoleWindow._static_backend = None
        for win in windows + suspended:
            win.scr = cast(CursesSurface, None)
            win.suspended = False
        if scr is None:
            # Already in shell mode (all windows suspended); nothing to end,
            # but the suspended windows still have to be forgotten.
            for win in windows + suspended:
                _unregister_window(win)
            return
        try:
            (backend or CursesBackend()).stop(scr)
        finally:
            # One teardown per window, matching the per-window setup in
            # _init_screen: the SIGINT handler is only restored once the last
            # live window is gone (AUDIT.md §3.1).
            for win in windows + suspended:
                _unregister_window(win)
                signals.teardown_ctrl_c()

    def __enter__(self) -> ConsoleWindow:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop_curses()

    @classmethod
    def active_windows(cls) -> list[ConsoleWindow]:
        return list(_WINDOWS.values())

    @classmethod
    def primary_window(cls) -> ConsoleWindow | None:
        # Singleton mode restores the old "the last constructed window is the
        # active one" pointer; per-instance mode keeps the creation-order rule.
        if _SINGLETON_MODE:
            return cls.static_win
        windows = cls.active_windows()
        return windows[-1] if windows else None

    @classmethod
    def stop_all(cls) -> None:
        """Permanently tear down every window (the atexit hook)."""
        if _SINGLETON_MODE:
            cls._stop_singleton()
            return
        for win in cls.active_windows():
            win.stop_curses()

    @classmethod
    def _apply_default_colors(cls, pair: int) -> None:
        for win in cls.active_windows():
            scr = getattr(win, 'scr', None)
            if scr is not None:
                try:
                    scr.bkgd(' ', pair)
                except curses.error:
                    pass
            for ns in (win.head, win.body):
                try:
                    ns.pad.bkgd(' ', pair)
                except curses.error:
                    pass

    def calc(self) -> bool:
        same = self._set_screen_dims()
        self._sync_pad_geometry()
        self.head.view_cnt = min(self.rows - self.hor_line_cnt, self.head.row_cnt)
        self.scroll_view_size = self.rows - self.head.view_cnt - self.hor_line_cnt
        self.max_scroll_pos = max(self.body.row_cnt - self.scroll_view_size, 0)
        self.body_base = self.head.view_cnt + self.hor_line_cnt
        return not same

    def _add(self, ns: _Content, text: str, attr: int | None = None,
             resume: bool = False, context: Context | None = None,
             *, is_body: bool = False) -> None:
        # Model-only: the row is stored here and painted by _paint_body()/
        # _paint_head() on the frames where it is actually visible.  `ns.rows`
        # is ops.max_rows (or the no-limit sentinel), not the pad height and not
        # the advisory hint, so nothing is dropped unless a ceiling was set.
        if ns.row_cnt >= ns.rows:
            self._warn_rows_dropped(ns, 'body' if is_body else 'head')
            return

        # Downgrade decoration *before* the width math below: an emoji is two
        # cells and its ASCII fallback is one or two, so substituting afterwards
        # would truncate at the wrong column and mis-size the attribute runs.
        text = glyphs.transliterate(text)

        if attr is None:
            attr = curses.A_NORMAL
        # Apply stripping logic if needed
        if is_body and self.pick_mode and self.opts.strip_attrs_in_pick_mode:
            attr = curses.A_NORMAL

        if resume and ns.row_cnt > 0 and ns.texts:
            row = min(ns.row_cnt - 1, len(ns.texts) - 1)
            # The old code read the pad cursor with getyx(); the model already
            # records the row's text, so its display width is the resume column.
            x = textwidth.string_width(ns.texts[row])
            cols = self.get_pad_width() - x
            if cols > 0:
                actual_text = textwidth.truncate(text, cols)
                ns.texts[row] += actual_text
                # Append to existing attrs list (counts are code points)
                if row < len(ns.text_attrs):
                    ns.text_attrs[row].append((attr, len(actual_text)))
                # Note: context not updated on resume
        else:
            if ns is self.head:
                # Measure before truncation: the first screen's header sets the
                # one-time minimum even when it was drawn on a narrow terminal.
                ns.max_header_len = max(
                    ns.max_header_len, textwidth.string_width(text))
            # Truncate to the single "usable width" (get_pad_width), matching
            # the resume branch, not the raw terminal width, which is one column
            # wider and uncapped by the pad.
            actual_text = textwidth.truncate(text, self.get_pad_width())
            ns.texts.append(actual_text)  # text only history
            ns.text_attrs.append([(attr, len(actual_text))])  # run-length encoded
            ns.contexts.append(context)  # Context metadata (or None)

    def _warn_rows_dropped(self, ns: _Content, which: str, *,
                           stacklevel: int = 5) -> None:
        # The content cap is reached, so this row is discarded (as it always
        # was when the pad was the storage).  Counted always, warned about once
        # per fill episode -- Screen.clear() resets both, so
        # a bulk overflow produces exactly one message instead of one per row --
        # and never fatal: the app keeps running and can inspect
        # ConsoleWindow.rows_dropped.  A caller that would rather treat this as
        # an error can use the usual warnings machinery
        # (python -W error::UserWarning, or pytest's filterwarnings ini setting).
        #
        # stacklevel is 5 for the content path:
        # warn() <- _warn_rows_dropped() <- _add() <- Screen.add_body()/add_header()
        # <- caller.
        ns.rows_dropped += 1
        if ns.rows_dropped != 1:
            return
        warnings.warn(
            f'console-window: the {which} content limit is full ({ns.rows} '
            f'rows), so further {which} rows are being discarded.  Raise '
            f'ConsoleWindowOpts(max_rows=...) or pass max_rows=None to remove '
            f'the ceiling entirely.',
            stacklevel=stacklevel,
        )

    # The public content writers live on Screen (see screens.Screen.add_body
    # and friends); they delegate here with their own namespace, so a screen
    # can fill its content before it is adopted.

    # --- in-place prompt lifecycle -----------------------------------------

    @property
    def prompt_active(self) -> bool:
        """True while :meth:`begin_prompt` is live."""
        return self.prompt_line.active

    def begin_prompt(self, prompt: str, *, hint: str = '', mode: str = 'y',
                     identity: str | None = None, seed: str = '',
                     choices: str | list[str] | tuple[str, ...] | None = None,
                     on_confirm: Callable[[str], object] | None = None,
                     on_cancel: Callable[[], object] | None = None,
                     answer_hint: str = '') -> bool:
        """Start an in-place prompt and enable passthrough key routing.

        The window *is* the receiver, so there is no window-existence branch
        here; an application whose window may be ``None`` guards at its own
        call site.  Every key must then go through :meth:`handle_prompt_key`
        and a ``'continue'`` result must be swallowed.

        *answer_hint* replaces the default trailing ``[Press "y" or ESC]`` text
        for the one-key modes; ``{mode}`` in it is replaced with the live mode
        letter.  Use it when the application wants its own bracketing or a
        trailing decoration (see :class:`PromptLine`).
        """
        self.prompt_line.start(prompt, hint=hint, mode=mode, identity=identity,
                               seed=seed, choices=choices,
                               on_confirm=on_confirm, on_cancel=on_cancel,
                               answer_hint=answer_hint)
        self._prompt_prev_passthrough = self.passthrough_mode
        self.passthrough_mode = True
        return True

    def end_prompt(self) -> None:
        """Discard the prompt and restore the previous passthrough setting."""
        self.prompt_line.cancel()
        self.passthrough_mode = self._prompt_prev_passthrough

    def handle_prompt_key(self, key: int) -> str:
        """Route one key to the active prompt and run its completion callback.

        Returns ``'continue'``, ``'confirmed'`` or ``'cancelled'``.  The
        ordering below is the contract: the prompt is torn down and passthrough
        is restored *before* the callback runs, so a callback may begin the
        next prompt (the re-ask path).
        """
        if not self.prompt_line.active:
            return 'continue'
        result = self.prompt_line.handle_key(key)
        if result == 'continue':
            return result
        answer, on_confirm, on_cancel = self.prompt_line.take()
        self.end_prompt()                     # passthrough restored FIRST
        if result == 'confirmed' and on_confirm:
            assert answer is not None
            on_confirm(answer)                # may begin_prompt() the next prompt
        elif result == 'cancelled' and on_cancel:
            on_cancel()
        return result

    def _add_prompt_header(self, ns: _Content, attr: int | None = None,
                           align: str | None = None) -> bool:
        """Draw the prompt as a header row; False when no prompt is active.

        *align* of ``'center'`` pads the row so the prompt sits in the middle of
        the usable width.  Centering is done here rather than by the caller
        because the display width of the line is only known after the prompt is
        composed (glyphs, an emoji presentation selector and the hint all
        count), and a caller-side ``len()`` would be one cell out for exactly
        the lines that need centering most.  ``Screen.add_prompt_header()``
        supplies its own header namespace.
        """
        if not self.prompt_line.active:
            return False
        text = self.prompt_line.get_display_string()
        attr = attr if attr is not None else curses.A_BOLD
        if align == 'center':
            lead = max(0, (self.get_pad_width() - textwidth.string_width(text)) // 2)
            if lead:
                # Two adds on one row: the pad spaces carry the prompt's own
                # attribute so the whole band, not just its text, is painted.
                self._add(ns, ' ' * lead, attr=attr)
                self._add(ns, text, attr=attr, resume=True)
                return True
        self._add(ns, text, attr=attr)
        return True

    def _add_prompt_lines(self, ns: _Content, attr: int | None = None,
                          hint_attr: int | None = None) -> bool:
        """Draw the prompt and its hint as transient body rows.

        For item-scoped questions the application calls this from its own row
        loop right after the row the prompt belongs to; the window never learns
        which row that is.  Returns False when no prompt is active.
        """
        if not self.prompt_line.active:
            return False
        transient = Context(genre='TRANSIENT', pickable=False)
        self._add(ns, self.prompt_line.get_display_string(),
                  attr=attr if attr is not None else curses.A_BOLD,
                  context=transient, is_body=True)
        hint = self.prompt_line.get_hint_string()
        if hint:
            self._add(ns, textwidth.truncate(hint, max(10, self.cols - 2)),
                      attr=hint_attr if hint_attr is not None else curses.A_DIM,
                      context=Context(genre='TRANSIENT', pickable=False),
                      is_body=True)
        return True

    def _add_fancy_header(self, ns: _Content, line: str | HeaderLine,
                          mode: str = 'Underline',
                          search_pattern_attr: int | None = None,
                          line_attr: int | None = None) -> None:
        """Add a header line with legacy ``[x]``/``KEY:``/``/pattern`` markup.

        String input is parsed unless ``mode='Off'``.  A :class:`HeaderLine`
        keeps its declared span roles, but its ``bracket_key()`` delimiters are
        treated as markup too: in every mode except ``'Off'`` they are removed,
        while the enclosed key keeps its ``KEY`` styling.  Use
        ``add_header_line()`` when literal brackets are wanted.

        *line_attr* is OR'd into the attribute of every span (and into the raw
        line emitted for ``mode='Off'``), so a caller can, for example, dim a
        whole header with ``line_attr=curses.A_DIM`` while keeping each span's
        own bold/underline/reverse styling.  ``Screen`` supplies its own header
        namespace.
        """
        if isinstance(line, str):
            if mode == 'Off':
                # Legacy: no markup processing, add the raw line unchanged
                # (except for the caller's whole-line attribute).
                self._add(ns, line, attr=line_attr)
                return
            spans = parse_fancy_header(line)
        else:
            spans = list(line)
            if mode != 'Off':
                spans = strip_key_brackets(spans)
        self._emit_header_spans(ns, spans, mode, search_pattern_attr, line_attr)

    def _add_header_line(self, ns: _Content, header_line: HeaderLine | Iterable[Span],
                         mode: str = 'Underline',
                         search_pattern_attr: int | None = None,
                         line_attr: int | None = None) -> None:
        """Render explicit header spans; see ``Screen.add_fancy_header()``.

        *line_attr* is OR'd into every span's resolved attribute, including
        plain spans, so the whole line can carry an extra style such as
        ``curses.A_DIM``.
        """
        self._emit_header_spans(ns, list(header_line), mode, search_pattern_attr,
                                line_attr)

    @staticmethod
    def _resolve_header_attr(role: str, mode: str,
                             search_pattern_attr: int | None,
                             line_attr: int | None = None) -> int | None:
        if mode == 'Off' or role == PLAIN:
            attr = None
        elif role == LABEL:
            attr = curses.A_BOLD
        elif role == SEARCH:
            if search_pattern_attr is not None:
                attr = search_pattern_attr
            else:
                attr = curses.A_BOLD | curses.A_REVERSE
        # KEY (and any unknown role) follows the mode's key styling.
        elif mode == 'Underline':
            attr = curses.A_UNDERLINE | curses.A_BOLD
        else:
            attr = curses.A_REVERSE
        if line_attr is not None:
            attr = (attr or 0) | line_attr
        return attr

    def _emit_header_spans(self, ns: _Content, spans: Iterable[Span], mode: str,
                           search_pattern_attr: int | None = None,
                           line_attr: int | None = None) -> None:
        result_sections = [
            (span.text,
             self._resolve_header_attr(span.role, mode, search_pattern_attr,
                                       line_attr))
            for span in spans
        ]

        # Calculate visible length (in display cells) of this header line
        visible_length = sum(textwidth.string_width(text) for text, attr in result_sections)

        # Check if this is the first header line
        is_first_header = (ns.row_cnt == 0)

        # Add demo indicator to first header if demo mode is active
        if is_first_header and self.opts.demo_mode and self.last_demo_key:
            # Pad to max_header_len + 2 spaces
            padding_needed = max(0, ns.max_header_len + 2 - visible_length)
            if padding_needed > 0:
                result_sections.append((' ' * padding_needed, None))
            # Add demo key in reverse video
            result_sections.append((self.last_demo_key, curses.A_REVERSE))

        # Now output the sections onto the header row, resuming each segment
        for idx, (text, attr) in enumerate(result_sections):
            resume = bool(idx > 0)  # Resume for all but the first section
            self._add(ns, text, attr=attr, resume=resume)

        # Track max header length for next render (excluding demo indicator)
        if visible_length > ns.max_header_len:
            ns.max_header_len = visible_length

    def _body_text(self, pos: int) -> str:
        if pos >= len(self.body.texts):
            return ''
        return textwidth.truncate(self.body.texts[pos], self.cols)

    def _body_attrs(self, pos: int) -> list | None:
        return self.body.text_attrs[pos] if pos < len(self.body.text_attrs) else None

    def _paint_row(self, pad: CursesSurface, pad_row: int, pos: int, *,
                   picked: bool) -> None:
        # One content row -> one pad row, with the pick styling applied here
        # rather than incrementally: a scrolled viewport moves rows on screen
        # without changing pick_pos, so highlight state must follow the paint,
        # not the last pick position.
        text = self._body_text(pos)
        if picked and self.mod_pick:
            text = self.mod_pick(text)
        text = textwidth.ljust(text, self.get_pad_width())
        extra_attr = self.opts.pick_attr if picked else None
        extra_range = self.pick_range if picked else None
        self._draw_line_with_attrs(pad, pad_row, 0, text,
                                   self._body_attrs(pos),
                                   extra_attr=extra_attr,
                                   extra_attr_range=extra_range)

    def _draw_line_with_attrs(self, pad: CursesSurface, row: int, col_offset: int,
                              text: str, attrs: list | None,
                              extra_attr: int | None = None,
                              extra_attr_range: list[int] | tuple[int, int] | None = None) -> None:
        if not attrs:
            self._draw_plain_line(pad, row, col_offset, text, extra_attr, extra_attr_range)
            return

        # Handle run-length encoded attributes with optional range highlighting.
        # Attr run lengths are measured in code points while the highlight range
        # is measured in display cells, so convert the range to code-point indices.
        range_start, range_end = self._highlight_range(text, extra_attr_range)

        col = col_offset
        pos = 0
        for attr, count in attrs:
            if pos >= len(text):
                break
            col = self._draw_attr_run(pad, row, col, text, attr, pos, count,
                                      range_start, range_end, extra_attr)
            pos += count
        if pos < len(text):
            # draw() can replace part of a row without rewriting text_attrs[],
            # so the run list may not cover the whole string.  Paint the tail in
            # the normal attribute rather than leaving a hole in the row.
            tail = textwidth.truncate(text[pos:], self.get_pad_width() - col)
            if tail:
                pad.addstr(row, col, tail, curses.A_NORMAL)

    def _draw_plain_line(self, pad: CursesSurface, row: int, col_offset: int, text: str,
                         extra_attr: int | None,
                         extra_attr_range: list[int] | tuple[int, int] | None) -> None:
        if extra_attr is not None and extra_attr_range:
            # Apply extra_attr only to the specified range
            start_col, end_col = extra_attr_range
            max_width = self.get_pad_width() - col_offset
            text = textwidth.truncate(text, max_width)
            start_idx = textwidth.cell_to_index(text, start_col)
            end_idx = textwidth.cell_to_index(text, end_col)

            # Before range
            if start_col > 0:
                pad.addstr(row, col_offset, text[:start_idx], curses.A_NORMAL)
            # Inside range
            range_text = text[start_idx:end_idx]
            if range_text:
                pad.addstr(row, col_offset + start_col, range_text, extra_attr)
            # After range
            if end_idx < len(text):
                pad.addstr(row, col_offset + end_col, text[end_idx:], curses.A_NORMAL)
        else:
            final_attr = extra_attr if extra_attr is not None else curses.A_NORMAL
            pad.addstr(row, col_offset,
                       textwidth.truncate(text, self.get_pad_width() - col_offset),
                       final_attr)

    @staticmethod
    def _highlight_range(text: str,
                         extra_attr_range: list[int] | tuple[int, int] | None) -> tuple[int, int]:
        if extra_attr_range:
            range_start, range_end = extra_attr_range
        else:
            range_start, range_end = 0, textwidth.string_width(text)
        return (textwidth.cell_to_index(text, range_start),
                textwidth.cell_to_index(text, range_end))

    def _draw_attr_run(self, pad: CursesSurface, row: int, col: int, text: str, attr: int,
                       pos: int, count: int, range_start: int, range_end: int,
                       extra_attr: int | None) -> int:
        segment = text[pos:pos+count]
        segment_start = pos
        segment_end = pos + len(segment)

        parts = self._split_segment(text, segment_start, segment_end,
                                    range_start, range_end, attr)
        for part_text, part_attr, in_highlight in parts:
            if not part_text:
                continue

            final_attr = part_attr
            if extra_attr is not None and in_highlight:
                final_attr = part_attr | extra_attr

            # Ensure we don't exceed pad width (measured in display cells)
            max_len = self.get_pad_width() - col
            if max_len <= 0:
                break
            part_text = textwidth.truncate(part_text, max_len)

            pad.addstr(row, col, part_text, final_attr)
            col += textwidth.string_width(part_text)
        return col

    @staticmethod
    def _split_segment(text: str, segment_start: int, segment_end: int,
                       range_start: int, range_end: int, attr: int) -> list:
        parts = []

        # Part before highlight range
        if segment_start < range_start and segment_end > segment_start:
            before_end = min(segment_end, range_start)
            parts.append((text[segment_start:before_end], attr, False))

        # Part inside highlight range
        in_range_start = max(segment_start, range_start)
        in_range_end = min(segment_end, range_end)
        if in_range_start < in_range_end:
            parts.append((text[in_range_start:in_range_end], attr, True))

        # Part after highlight range
        if segment_end > range_end and segment_start < segment_end:
            after_start = max(segment_start, range_end)
            parts.append((text[after_start:segment_end], attr, False))

        return parts

    def _scroll_indicator_row(self) -> int:
        # With no separator row there is no indicator either, so the anchor is
        # simply the top of the viewport: pick_pos tracks scroll_pos exactly.
        if not self.hor_line_cnt:
            return self.body_base
        return geometry.scroll_indicator_row(
            self.scroll_pos, self.max_scroll_pos, self.scroll_view_size,
            self.body_base, self.rows)

    def _scroll_indicator_col(self) -> int:
        # While free-scrolling through DECOR rows the picked row no longer tracks
        # the viewport, so show the scroll position rather than the (parked) pick.
        pick_mode = self.pick_mode and not self.free_scroll
        return geometry.scroll_indicator_col(
            pick_mode, self.pick_pos, self.scroll_pos,
            self.max_scroll_pos, self.body.row_cnt, self.cols)

    def _calc_indicator(self, pos: int, pos0: int, pos9: int, ind0: int, ind9: int) -> int:
        return geometry.calc_indicator(pos, pos0, pos9, ind0, ind9, self.max_scroll_pos)

    def render(self, redraw: bool = False) -> None:
        deadline = time.monotonic() + ConsoleWindow.render_retry_seconds
        while time.monotonic() < deadline:
            try:
                self.render_once(redraw)
                return
            except curses.error:
                time.sleep(ConsoleWindow.render_retry_interval)
                self._set_screen_dims()
                continue
        try:
            self.render_once(redraw)
        except curses.error:
            self.stop_curses()
            logger.exception(
                'curses error while rendering: head.row_cnt=%s head.view_cnt=%s '
                'hor_line_cnt=%s body.row_cnt=%s scroll_pos=%s max_scroll_pos=%s '
                'pick_pos=%s pick_mode=%s pick_size=%s rows=%s cols=%s',
                self.head.row_cnt, self.head.view_cnt, self.hor_line_cnt,
                self.body.row_cnt, self.scroll_pos, self.max_scroll_pos,
                self.pick_pos, self.pick_mode, self.pick_size,
                self.rows, self.cols)
            raise


    def fix_positions(self, delta: int = 0) -> int:
        self.calc()

        # Save old pick position to check for abut constraints before applying delta
        old_pick_pos = self.pick_pos if self.pick_mode else -1

        if self.pick_mode:
            self.pick_pos += delta
            # Also adjust scroll_pos in pick mode to allow showing DECOR lines
            # above/below the pick_pos when scrolling
            self.scroll_pos += delta
        else:
            self.scroll_pos += delta
            self.pick_pos += delta

        indent = 0
        if self.body_base < self.rows:
            ind_pos = 0 if self.pick_mode else self._scroll_indicator_row()
            if self.pick_mode:
                # First, get abut range from the PREVIOUS pick position (before delta was applied)
                abut_range = self._abut_range_at(old_pick_pos)

                self._clamp_pick_pos(abut_range)

                # Re-check for abut in the CURRENT pick position for scroll adjustment
                abut_range = self._abut_range_at(self.pick_pos)

                self._adjust_scroll_for_abut(abut_range)
                indent = 1
            else:
                self.scroll_pos = max(self.scroll_pos, 0)
                self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)
                self.pick_pos = self.scroll_pos + ind_pos - self.body_base
        return indent

    def _abut_range_at(self, pos: int) -> tuple[int, int] | None:
        if not 0 <= pos < len(self.body.contexts):
            return None
        effective_abut = self._get_effective_abut(pos)
        if effective_abut is None:
            return None
        cooked = self._cook_abut(effective_abut)
        if not cooked:
            return None
        before, after = cooked
        min_line = max(0, pos + before)
        max_line = min(self.body.row_cnt - 1, pos + after)
        return (min_line, max_line)

    def _clamp_pick_pos(self, abut_range: tuple[int, int] | None) -> None:
        self.pick_pos = max(self.pick_pos, 0)
        self.pick_pos = min(self.pick_pos, self.body.row_cnt-1)

        # If abut range exists, further constrain pick_pos within that range
        if abut_range:
            min_line, max_line = abut_range
            self.pick_pos = max(self.pick_pos, min_line)
            self.pick_pos = min(self.pick_pos, max_line)

        if self.pick_pos >= 0:
            self.pick_pos -= (self.pick_pos % self.pick_size)

        # Ensure pick_pos is on a pickable line (skip DECOR lines)
        if not self._is_pickable(self.pick_pos):
            self.pick_pos = geometry.find_pickable(
                self._is_pickable, self.body.row_cnt, self.pick_pos)

    def _adjust_scroll_for_abut(self, abut_range: tuple[int, int] | None) -> None:
        if self.pick_pos < 0:
            self.scroll_pos = 0
        elif abut_range:
            # Apply abut constraints: "after trumps before"
            self._scroll_to_fit_abut(abut_range)
        elif self.free_scroll:
            # The user deliberately scrolled past the picked row to reveal
            # non-pickable DECOR rows (see prompt()); leave the viewport where
            # they put it -- clamped to range below -- instead of dragging it
            # back to the picked row.
            pass
        elif self.scroll_pos > self.pick_pos:
            # picked line would be above viewport - scroll up to show it
            self.scroll_pos = self.pick_pos
        elif self.pick_pos >= self.scroll_pos + self.scroll_view_size:
            # picked line would be below viewport bottom - scroll down to show it
            self.scroll_pos = self.pick_pos - (self.scroll_view_size - self.pick_size)
        # Note: We allow scroll_pos < pick_pos to show DECOR lines above the picked item

        # Final clamping
        self.scroll_pos = max(self.scroll_pos, 0)
        self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)

    def _scroll_to_fit_abut(self, abut_range: tuple[int, int]) -> None:
        min_line, max_line = abut_range
        range_size = max_line - min_line + 1
        viewport_bottom = self.scroll_pos + self.scroll_view_size - 1

        # Scroll down if the range would go below the viewport (prioritize "after"
        # lines), else scroll up if it would go above it (allowing DECOR lines above).
        if max_line > viewport_bottom:
            self.scroll_pos = max_line - self.scroll_view_size + 1
        elif min_line < self.scroll_pos and self.pick_pos < self.scroll_pos:
            self.scroll_pos = min_line

        if range_size > self.scroll_view_size:
            # Range doesn't fit: keep the picked line visible and don't scroll past
            # max_line, while still allowing scrolling above min_line for DECOR.
            if self.pick_pos < self.scroll_pos:
                self.scroll_pos = max(self.scroll_pos, min_line)
            max_scroll = max_line - self.scroll_view_size + 1
            self.scroll_pos = min(self.scroll_pos, max_scroll)

    def render_once(self, redraw: bool = False) -> None:
        # --- 1. Preparation and Conditional Redrawwin ---
        if redraw:
            self._mark_pads_for_redraw()

        indent = self.fix_positions()

        # --- 2. Screen Drawing (Highlighting, Scrollbar, Separator) ---

        if indent > 0 and self.pick_mode:
            self._draw_pick_gutter()

        if self._separator_available():
            self._draw_separator_and_indicator()

        # Instead of self.scr.refresh(), use pnoutrefresh/doupdate for efficiency.
        # The 'redrawwin' above handles the forced repaint, so we just call 'noutrefresh'.
        self.scr.noutrefresh()

        # --- 3. Pad Drawing (Body and Head) ---

        self._refresh_pads(indent)

        # --- 4. Final Update (Only one physical screen update) ---
        self._backend.doupdate()
        # The first completed frame is the app's "first impression"; prompt()
        # uses this flag to take the one-time minimum-size measurement.
        self._has_rendered = True

    def _mark_pads_for_redraw(self) -> None:
        self.scr.redrawwin()
        self.head.pad.redrawwin()
        self.body.pad.redrawwin()

    def _draw_pick_gutter(self) -> None:
        self.scr.vline(self.body_base, 0, ' ', self.scroll_view_size)
        if self.pick_pos >= 0:
            pos = self.pick_pos - self.scroll_pos + self.body_base
            # While free-scrolling through trailing/leading DECOR the picked row
            # can sit outside the viewport; only mark it when it is on screen,
            # so the '>' never spills into the header band.
            if self.body_base <= pos < self.body_base + self.scroll_view_size:
                self.scr.addstr(pos, 0, '>', curses.A_REVERSE)

    def _separator_available(self) -> bool:
        """True when the window has a separator row to paint chrome onto.

        ``head_line=False`` reserves no row, so there is nothing to paint a
        rule, a scroll indicator or a status message on.  This is the single
        test render_once() and status() share; keying it on the flag (not on
        ``head.view_cnt``) is what stops the rule from landing on body row 0.
        """
        return bool(self.hor_line_cnt) and self.head.view_cnt < self.rows

    def _draw_separator_and_indicator(self) -> None:
        # A one-column terminal has no safe cell to paint, and writing the
        # bottom-right corner raises curses.error, so reserve the last column
        # exactly as get_pad_width() does for the pads.
        if self.cols < 2:
            return
        # While an in-place prompt is live it is the only thing keys can reach,
        # so an application may ask for the rule to recede behind it.
        rule_attr = (self.prompt_separator_attr
                     if self.prompt_line.active and self.prompt_separator_attr is not None
                     else curses.A_NORMAL)
        sep_row = self.body_base - 1
        rule_width = self.cols - 1
        self.scr.hline(sep_row, 0, curses.ACS_HLINE, rule_width, rule_attr)
        ind_pos = min(self._scroll_indicator_col(), rule_width - 1)
        bot, cnt = self._scroll_indicator_span(ind_pos) if ind_pos >= 0 else (-1, 0)
        # Status first: it must not be able to cover the indicator, and it must
        # still draw when there is no indicator to draw.
        self._draw_status_line(bot if ind_pos >= 0 else -1)
        if ind_pos >= 0:
            for idx in range(bot, bot + cnt):
                self.scr.addch(sep_row, idx, curses.ACS_HLINE,
                               curses.A_REVERSE)

    def _draw_status_line(self, indicator_start: int) -> None:
        """Paint the current status on the separator row.

        Only called when :meth:`_separator_available` is true, so there is
        always a row above the body.  ``indicator_start`` is the first cell of
        the scroll indicator, or -1 when no indicator is being drawn.  The text
        never touches that span and one blank cell is always left between the
        two.  With no separator row ``status()`` warns on the caller instead of
        painting over body row 0.
        """
        if not self._status_text:
            return
        if (self._status_deadline is not None
                and time.monotonic() >= self._status_deadline):
            self.clear_status()
            return
        budget = (max(indicator_start - 2, 0) if indicator_start >= 0
                  else self.cols - 1)
        if budget < 2:
            return
        text = textwidth.truncate(self._status_text, budget)
        self.scr.addstr(self.body_base - 1, 0, text,
                        self._status_attr if self._status_attr is not None
                        else curses.A_NORMAL)

    def _scroll_indicator_span(self, ind_pos: int) -> tuple[int, int]:
        limit = max(1, self.cols - 2)  # reserve the bottom-right cell
        if self.opts.single_cell_scroll_indicator or not 0 < ind_pos < limit:
            return min(ind_pos, limit), 1
        # Proportional range indicator
        width = self.scroll_view_size/self.body.row_cnt*self.cols
        bot = max(round(ind_pos-width/2), 1)
        top = min(round(ind_pos+width/2), limit)
        return bot, max(top - bot, 1)

    def _paint_body(self) -> int:
        # Paint the visible page into the viewport-sized body pad.  Unlike the
        # old pad-as-storage model, every frame redraws at most one screenful,
        # so cost tracks the terminal, not the document.
        view = min(self.scroll_view_size, self.rows - self.body_base)
        if view <= 0:
            return 0
        pad = cast(CursesSurface, self.body.pad)
        pad.erase()
        for row in range(view):
            pos = self.scroll_pos + row
            if pos < 0 or pos >= self.body.row_cnt or pos >= len(self.body.texts):
                continue
            picked = (self.pick_mode
                      and self.pick_pos <= pos < self.pick_pos + self.pick_size)
            self._paint_row(pad, row, pos, picked=picked)
        return view

    def _paint_head(self) -> int:
        last_row = min(self.head.view_cnt, self.rows) - 1
        if last_row < 0:
            return -1
        pad = cast(CursesSurface, self.head.pad)
        pad.erase()
        width = self.get_pad_width()
        for row in range(last_row + 1):
            if row >= len(self.head.texts):
                continue
            text = textwidth.ljust(self.head.texts[row], width)
            attrs = self.head.text_attrs[row] if row < len(self.head.text_attrs) else None
            self._draw_line_with_attrs(pad, row, 0, text, attrs, extra_attr=None)
        return last_row

    def _refresh_pads(self, indent: int) -> None:
        if self._paint_body() > 0:
            self.body.pad.noutrefresh(
                0, 0,
                self.body_base, indent, self.rows-1, self.cols-1
            )

        last_row = self._paint_head()
        if last_row >= 0:
            self.head.pad.noutrefresh(
                0, 0,
                0, indent, last_row, self.cols-1
            )


    def answer(self, prompt: str = 'Type string [then Enter]', seed: str = '', width: int = 80,
               height: int = 5, esc_abort: bool | None = None, prompt_attr: int | None = None,
               hint: str = '') -> str | None:
        """Blocking single-line text dialog.

        Returns the submitted string, or ``None`` when the user aborts.  Raises
        ``TerminalTooSmallError`` when no dialog of the requested size can be
        shown; that is an environment failure, never a user cancel.

        ``hint`` is an optional one-line message drawn on the bottom border,
        left of the submit/abort text.  A validator that re-opens the dialog
        after a rejected answer uses it to say what the answer should look
        like; ``OptionSpinner``'s ``check_ans`` does exactly that.

        Transient ``curses.error`` and too-small redraws retry within the shared
        class-level ``render_retry_seconds`` budget (see the attribute comment);
        a persistent failure re-raises.  Recovery drains the input queue, so
        keys typed while the screen is recovering are discarded (AUDIT.md §3.2).
        """
        # Handle deprecated esc_abort parameter for backward compatibility
        dialog_abort = self._resolve_abort_mode(esc_abort)

        # Remember the timeout in effect before the dialog so every exit path can
        # restore it; curses.window has no gettimeout(), so we track it ourselves.
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)

        input_string = list(seed)
        cursor_pos = len(input_string)
        v_scroll_top = 0
        last_esc_time = None  # For ESC-ESC tracking

        if not self._dialog_geometry(height, width)[0]:
            # No dialog can be shown at all.  Raise instead of returning None:
            # None means the user aborted, and callers must not act on a cancel
            # the user never made (AUDIT.md §3.6).
            raise self._too_small_error(height)

        # Set longer timeout for dialog - redraw every 5s for screen recovery
        # This prevents flicker (was 200ms) while recovering from corruption
        self._set_scr_timeout(5000)  # 5 second timeout for auto-refresh

        # Bound the curses.error recovery loop exactly like render(): a persistent
        # error is an environment failure, not a user abort.
        deadline = time.monotonic() + ConsoleWindow.render_retry_seconds

        # DEBUG: Set to True to show redraw indicator in upper-left corner
        debug_show_redraws = self.opts.answer_show_redraws
        debug_redraw_toggle = False

        try:
            while True:
                # Keep geometry current across retries; a resize may have
                # arrived without refreshing our cached dimensions.
                self._set_screen_dims()
                try:
                    success, row0, row9, col0, text_win_width = self._dialog_geometry(height, width)

                    # --- RESIZE/TOO SMALL CHECK ---
                    if not success:
                        if self._show_too_small_dialog(height):
                            return None  # ESC on the notice: a real user abort
                        if time.monotonic() >= deadline:
                            raise self._too_small_error(height)
                        continue

                    self.scr.clear()
                    self._draw_dialog_box(row0, col0, row9, col0 + text_win_width + 1)

                    # DEBUG: Toggle indicator to visualize redraws
                    if debug_show_redraws:
                        debug_redraw_toggle = self._draw_debug_indicator(
                            row0, col0, debug_redraw_toggle)

                    self._draw_dialog_prompt(prompt, prompt_attr, row0, col0, text_win_width)

                    # --- Core Display and Scroll Indicator Logic ---
                    # Wrapping, the padding and the cursor highlight are all measured
                    # in display cells, so wide (CJK/emoji) input stays aligned.
                    input_text = "".join(input_string)
                    wrapped_ranges = textwidth.wrap_ranges(input_text, text_win_width)
                    wrapped_line_idx, cursor_cell = self._resolve_cursor_line(
                        input_text, cursor_pos, wrapped_ranges, text_win_width)
                    v_scroll_top = self._clamp_dialog_scroll(
                        v_scroll_top, wrapped_line_idx, height)

                    self._draw_dialog_content(
                        row0, row9, col0, text_win_width, height, input_text,
                        wrapped_ranges, len(wrapped_ranges), wrapped_line_idx,
                        cursor_cell, cursor_pos, v_scroll_top)

                    self._draw_dialog_footer(row9, col0, text_win_width, dialog_abort,
                                             hint)
                    self.scr.noutrefresh()
                    self._backend.doupdate()
                    self._backend.curs_set(0)  # Hide hardware cursor; reverse video shows position

                    key = self.scr.getch()

                    # --- Key Handling Logic ---
                    cursor_pos, last_esc_time, action = self._handle_dialog_key(
                        key, input_string, cursor_pos, last_esc_time, dialog_abort,
                        input_text, wrapped_ranges, wrapped_line_idx, cursor_cell)

                    if action is not None:
                        self._backend.curs_set(0)
                        if action == 'submit':
                            return "".join(input_string)
                        if action == 'abort':
                            return None
                        continue  # 'resize'

                except curses.error:
                    # Catch exceptions from drawing outside bounds during resize.
                    # Recover only within the budget, then let the error escape.
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(ConsoleWindow.render_retry_interval)
                    self._recover_from_resize()
                    continue
        finally:
            # Every exit path -- submit, abort, raise -- restores the caller's
            # timeout (an exception used to leak the 5000ms dialog value).
            self._set_scr_timeout(prev_timeout_ms)

    def _resolve_abort_mode(self, esc_abort: bool | None) -> str | None:
        if esc_abort is not None:
            return 'ESC' if esc_abort else None
        return self.opts.dialog_abort

    def _too_small_error(self, height: int) -> TerminalTooSmallError:
        required_cols, required_rows = self._dialog_min_size(height)
        return TerminalTooSmallError(required_rows, required_cols, self.rows, self.cols)

    def _dialog_min_size(self, height: int) -> tuple[int, int]:
        min_cols, min_rows = self._min_size()
        return max(30, min_cols), max(height + 4, min_rows)

    def _dialog_geometry(self, height: int, width: int) -> tuple[bool, int, int, int, int]:
        self.rows, self.cols = self.scr.getmaxyx()
        required_cols, required_rows = self._dialog_min_size(height)
        if self.rows < required_rows or self.cols < required_cols:
            return False, 0, 0, 0, 0

        max_display_width = self.cols - 6
        text_win_width = min(width, max_display_width)
        row0 = self.rows // 2 - (height // 2 + 1)
        row9 = row0 + height + 1
        col0 = (self.cols - (text_win_width + 2)) // 2
        return True, row0, row9, col0, text_win_width

    def _show_too_small_dialog(self, height: int) -> bool:
        required_cols, required_rows = self._dialog_min_size(height)
        self.scr.clear()
        msg = f"Min size: {required_cols}x{required_rows}"
        try:
            self.scr.addstr(0, 0, msg, curses.A_REVERSE)
        except curses.error:
            pass  # Terminal too small even for message
        self.scr.noutrefresh()
        self._backend.doupdate()
        key = self.scr.getch()
        if key == 27:
            return True
        # Poll even when getch() timed out: not every terminal delivers
        # KEY_RESIZE, and the caller retries with these dimensions.
        self._backend.update_lines_cols()
        self._set_screen_dims()
        return False

    def _draw_debug_indicator(self, row0: int, col0: int, toggle: bool) -> bool:
        toggle = not toggle
        self.scr.addstr(row0, col0, '*' if toggle else '+')
        return toggle

    def _draw_dialog_box(self, row0: int, col0: int, row9: int, c2: int) -> None:
        scr = self.scr
        scr.border(0)
        for r in range(row0, row9 + 1):
            if r == row0 or r == row9:
                # Draw horizontal lines
                for c in range(col0 + 1, c2):
                    scr.addch(r, c, curses.ACS_HLINE)
            if row0 < r < row9:
                # Draw vertical lines
                scr.addch(r, col0, curses.ACS_VLINE)
                scr.addch(r, c2, curses.ACS_VLINE)
        # Draw corners
        scr.addch(row0, col0, curses.ACS_ULCORNER)
        scr.addch(row0, c2, curses.ACS_URCORNER)
        scr.addch(row9, col0, curses.ACS_LLCORNER)
        scr.addch(row9, c2, curses.ACS_LRCORNER)

    def _draw_dialog_prompt(self, prompt: str, prompt_attr: int | None,
                            row0: int, col0: int, text_win_width: int) -> None:
        prompt_display = textwidth.truncate(prompt, text_win_width)
        if prompt_attr is not None:
            self.scr.addstr(row0, col0 + 1, prompt_display, prompt_attr | curses.A_BOLD)
        else:
            self.scr.addstr(row0, col0 + 1, prompt_display)

    @staticmethod
    def _resolve_cursor_line(input_text: str, cursor_pos: int,
                             wrapped_ranges: list, text_win_width: int) -> tuple[int, int]:
        wrapped_line_idx, cursor_cell = textwidth.wrap_position(
            input_text, cursor_pos, text_win_width)
        return min(wrapped_line_idx, len(wrapped_ranges) - 1), cursor_cell

    @staticmethod
    def _clamp_dialog_scroll(v_scroll_top: int, wrapped_line_idx: int, height: int) -> int:
        if wrapped_line_idx < v_scroll_top:
            return wrapped_line_idx
        if wrapped_line_idx >= v_scroll_top + height:
            return wrapped_line_idx - height + 1
        return v_scroll_top

    def _draw_dialog_content(self, row0: int, row9: int, col0: int, text_win_width: int,
                             height: int, input_text: str, wrapped_ranges: list,
                             total_wrapped_lines: int, wrapped_line_idx: int,
                             cursor_cell: int, cursor_pos: int,
                             v_scroll_top: int) -> None:
        for r in range(height):
            current_wrapped_line_idx = v_scroll_top + r

            # 1. Clear the content area (important for redraw integrity)
            self.scr.addstr(row0 + 1 + r, col0 + 1, ' ' * text_win_width)

            if current_wrapped_line_idx >= total_wrapped_lines:
                continue

            start_char_idx, end_char_idx = wrapped_ranges[current_wrapped_line_idx]
            raw_wrapped_line = input_text[start_char_idx:end_char_idx]

            # 2. Display the text (padded to full width so wide chars align)
            self.scr.addstr(row0 + 1 + r, col0 + 1,
                            textwidth.ljust(raw_wrapped_line, text_win_width))

            # --- SCROLL INDICATOR LOGIC (cursor line only) ---
            if current_wrapped_line_idx == wrapped_line_idx:
                self._draw_dialog_cursor(row0, col0, r, text_win_width,
                                         cursor_cell, input_text, cursor_pos)

        # --- CORNER OVERFLOW INDICATORS ---
        # Upper left (one line down): content scrolled above
        if v_scroll_top > 0:
            self.scr.addch(row0 + 1, col0, '◀', curses.A_BOLD)

        # Lower right (one line up): content below the window
        if (v_scroll_top + height) < total_wrapped_lines:
            self.scr.addch(row9 - 1, col0 + text_win_width + 1, '▶', curses.A_BOLD)

    def _draw_dialog_cursor(self, row0: int, col0: int, r: int, text_win_width: int,
                            cursor_cell: int, input_text: str, cursor_pos: int) -> None:
        # Vertical border markers. Hard wrapping never overflows a line, so
        # there is no horizontal-scroll marker.
        self.scr.addch(row0 + 1 + r, col0, curses.ACS_VLINE)
        self.scr.addch(row0 + 1 + r, col0 + text_win_width + 1, curses.ACS_VLINE)

        # Highlight the cursor (position measured in cells)
        char_at_cursor = input_text[cursor_pos] if cursor_pos < len(input_text) else " "
        self.scr.addstr(row0 + 1 + r, col0 + 1 + cursor_cell,
                        char_at_cursor, curses.A_REVERSE)

        # Set the actual hardware cursor
        self.scr.move(row0 + 1 + r, col0 + 1 + cursor_cell)

    def _draw_dialog_footer(self, row9: int, col0: int, text_win_width: int,
                            dialog_abort: str | None, hint: str = '') -> None:
        submit_key = self.opts.dialog_return
        abort = ''
        if dialog_abort == 'ESC':
            abort = ' or ESC to abort'
        elif dialog_abort == 'ESC-ESC':
            abort = ' or ESC-ESC to abort'
        ending = textwidth.truncate(f'{submit_key} to submit{abort}', text_win_width)
        ending_col = col0 + 1 + text_win_width - textwidth.string_width(ending)
        if hint:
            # The hint takes the room left of the submit/abort text, so the
            # escape hatch stays readable however long the expectation is.
            self.scr.addstr(row9, col0 + 1,
                            textwidth.truncate(hint, ending_col - (col0 + 1)))
        self.scr.addstr(row9, ending_col, ending)

    #: Simple single-keystroke cursor moves: key -> f(cursor_pos, text_len).
    _DIALOG_SIMPLE_MOVES: ClassVar[dict] = {
        curses.KEY_LEFT: lambda pos, n: max(0, pos - 1),
        curses.KEY_RIGHT: lambda pos, n: min(n, pos + 1),
        curses.KEY_HOME: lambda pos, n: 0,
        curses.KEY_END: lambda pos, n: n,
    }

    def _handle_dialog_key(self, key: int, input_string: list, cursor_pos: int,
                           last_esc_time: float | None, dialog_abort: str | None,
                           input_text: str, wrapped_ranges: list,
                           wrapped_line_idx: int, cursor_cell: int) -> tuple:
        # Handle dialog_return (submit)
        if self.opts.dialog_return == 'ENTER' and key in (10, 13):
            return cursor_pos, last_esc_time, 'submit'
        if self.opts.dialog_return == 'TAB' and key == 9:
            return cursor_pos, last_esc_time, 'submit'

        # Handle dialog_abort (ESC and ESC-ESC)
        if key == 27:
            action, last_esc_time = self._dialog_abort_action(dialog_abort, last_esc_time)
            return cursor_pos, last_esc_time, action

        cursor_pos, action = self._apply_dialog_edit(
            key, input_string, cursor_pos, input_text, wrapped_ranges,
            wrapped_line_idx, cursor_cell)
        return cursor_pos, last_esc_time, action

    @staticmethod
    def _dialog_abort_action(dialog_abort: str | None,
                             last_esc_time: float | None) -> tuple[str | None, float | None]:
        if dialog_abort == 'ESC':
            return 'abort', last_esc_time
        if dialog_abort == 'ESC-ESC':
            current_time = time.time()
            if last_esc_time is not None and (current_time - last_esc_time) <= 1.0:
                return 'abort', last_esc_time  # Double ESC within timeout
            # Single ESC - just update time and continue
            return None, current_time
        return None, last_esc_time

    def _apply_dialog_edit(self, key: int, input_string: list, cursor_pos: int,
                           input_text: str, wrapped_ranges: list,
                           wrapped_line_idx: int, cursor_cell: int) -> tuple[int, str | None]:
        move = self._DIALOG_SIMPLE_MOVES.get(key)
        if move is not None:
            return move(cursor_pos, len(input_string)), None

        if key in (curses.KEY_UP, curses.KEY_DOWN):
            return self._move_dialog_cursor_vertically(
                key, cursor_pos, input_text, wrapped_ranges,
                wrapped_line_idx, cursor_cell), None

        if key in (curses.KEY_BACKSPACE, 127, 8):
            return self._dialog_delete(input_string, cursor_pos, forward=False), None

        if key == curses.KEY_DC:
            return self._dialog_delete(input_string, cursor_pos, forward=True), None

        if key == curses.KEY_RESIZE:
            self._backend.update_lines_cols()
            return cursor_pos, 'resize'

        return self._dialog_insert(key, input_string, cursor_pos), None

    @staticmethod
    def _dialog_delete(input_string: list, cursor_pos: int, forward: bool) -> int:
        if forward:
            if cursor_pos < len(input_string):
                input_string.pop(cursor_pos)
        elif cursor_pos > 0:
            input_string.pop(cursor_pos - 1)
            cursor_pos -= 1
        return cursor_pos

    def _dialog_insert(self, key: int, input_string: list, cursor_pos: int) -> int:
        if key in (9, 10, 13):
            # Map special characters to space unless they're the dialog_return key
            if self._is_dialog_return_key(key):
                return cursor_pos
            char = ' '
        elif 32 <= key <= 126:
            char = chr(key)
        else:
            return cursor_pos
        input_string.insert(cursor_pos, char)
        return cursor_pos + 1

    @staticmethod
    def _move_dialog_cursor_vertically(key: int, cursor_pos: int, input_text: str,
                                       wrapped_ranges: list, wrapped_line_idx: int,
                                       cursor_cell: int) -> int:
        delta = -1 if key == curses.KEY_UP else 1
        target_pos = textwidth.index_at_cell(
            input_text, wrapped_ranges, wrapped_line_idx + delta, cursor_cell)
        return target_pos if target_pos is not None else cursor_pos

    def _is_dialog_return_key(self, key: int) -> bool:
        if self.opts.dialog_return == 'TAB' and key == 9:
            return True
        return self.opts.dialog_return == 'ENTER' and key in (10, 13)

    def _clear_surface(self) -> None:
        """Wipe the physical screen, for lifecycle paths only.

        Ordinary frames never need it: the pads are erased and fully repainted
        every render, and ``doupdate()`` diffs them against the physical screen.
        The wipe is for a screen that has just appeared (resume/start), where
        the terminal may still hold whatever the app before us left there.
        """
        scr = getattr(self, 'scr', None)
        if scr is not None:
            scr.clear()

    def _recover_from_resize(self) -> None:
        """Discard queued input and adopt the new screen geometry.

        Draining is intentional and covers *all* queued key codes, not just
        ``KEY_RESIZE``: curses has no push-back API, so preserving them would
        mean replaying raw codes read after a failed redraw, where duplicates
        and partial escape sequences are indistinguishable from real input.
        The loss is limited to the retry window bounded by
        ``render_retry_seconds``; keys typed after recovery are read normally.
        """
        self._clear_surface()
        self._backend.update_lines_cols()
        self.rows, self.cols = self.scr.getmaxyx()
        # Drain any pending events to prevent an infinite resize loop.  Keys
        # typed during this window are dropped by design (see the docstring).
        self.scr.nodelay(True)  # Make getch() non-blocking
        while True:
            if self.scr.getch() == -1:  # No more keys in queue
                break
        self.scr.nodelay(False)  # Restore blocking mode


    def status(self, text: str = '', level: str = 'info',
               timeout: float | None = None,
               attr: int | None = None) -> bool:
        """Declare a one-line status message for the separator row.

        Unlike :meth:`flash`, this never takes over the screen: the message is
        painted on the row that holds the separator and scroll indicator, and
        only when the next ``render()``/``prompt()`` runs.  Calling it does not
        render by itself.

        ``level`` selects a default attribute from :attr:`STATUS_LEVELS`
        (``'info'``, ``'warn'`` or ``'error'``); an unknown level falls back to
        ``'info'`` rather than raising, so an application typo cannot crash a
        TUI mid-session.  ``attr`` overrides that choice for this message only.

        ``timeout`` is evaluated lazily at draw time: ``None`` keeps the
        message until it is replaced or cleared, while a number makes it expire
        that many seconds after this call (no timer and no thread).

        The text is always stored, even when the window currently has no
        separator row; the return value is ``False`` in that case so a caller
        can tell that the message is deferred, not lost.  A later resize will
        reveal it.  An empty ``text`` clears the status and returns ``True``.

        ``head_line=False`` reserves no row, so painting a status there would
        mean overwriting the first body row.  That case returns ``False`` and
        warns once per episode (the same shape as the ``max_rows`` warning), so
        a caller is told rather than silently losing the message.
        """
        if text == '':
            self._status_text = ''
            self._status_attr = None
            self._status_deadline = None
            self._status_no_row_warned = False
            return True
        level_attr = self.STATUS_LEVELS.get(level)
        if level_attr is None:
            level_attr = self.STATUS_LEVELS['info']
        self._status_text = glyphs.transliterate(text)
        self._status_attr = attr if attr is not None else level_attr
        self._status_deadline = (None if timeout is None
                                 else time.monotonic() + max(timeout, 0.0))
        # Same availability test render_once() uses for the separator row.
        available = self._separator_available()
        if available:
            self._status_no_row_warned = False
        elif not self._status_no_row_warned:
            self._status_no_row_warned = True
            warnings.warn(
                'console-window: status() has no separator row to draw on '
                '(head_line=False reserves none), so the message is kept but '
                'not shown; it will appear if a later resize/call frees a row.',
                stacklevel=2,
            )
        return available

    def clear_status(self) -> bool:
        """Remove any current status message (equivalent to ``status('')``)."""
        return self.status('')

    @property
    def current_status(self) -> tuple[str, int | None]:
        """The stored status text and its attribute (``('', None)`` if clear)."""
        return self._status_text, self._status_attr

    def flash(self, message: str = '', duration: float = 2.0) -> None:
        """Show a modal message box for ``duration`` seconds.

        Note that this clears the whole screen before drawing the box (and
        repaints the pads afterwards), which is why a transient message that
        must leave the listing visible should use :meth:`status` instead.
        """
        # Refresh cached dimensions: a resize may have happened since the last
        # render and everything below draws from self.rows/self.cols.
        self._set_screen_dims()
        # This message is painted directly, so it never passes through _add();
        # downgrade its decoration here, before the width math and the frame.
        message = glyphs.transliterate(message)

        if self.rows < 3 or self.cols < textwidth.string_width(message) + 4:
            return

        # Remember the timeout in effect so it can be restored on exit (curses
        # windows expose no gettimeout(); _set_scr_timeout tracks the last value).
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)

        def draw_flash() -> None:
            # Calculate centered position (widths measured in display cells).
            msg_len = min(textwidth.string_width(message), self.cols - 4)
            row = self.rows // 2
            col = max((self.cols - msg_len - 2) // 2, 0)

            # The frame is built from registered glyphs, so an ASCII-mode
            # terminal gets a '+---+' box instead of blank cells.
            horizontal = glyphs.get('box_h') * msg_len
            vertical = glyphs.get('box_v')
            top = glyphs.get('box_tl') + horizontal + glyphs.get('box_tr')
            middle = vertical + textwidth.ljust(message, msg_len) + vertical
            bottom = glyphs.get('box_bl') + horizontal + glyphs.get('box_br')
            self.scr.clear()
            try:
                self.scr.addstr(row - 1, col, top, curses.A_BOLD | curses.A_REVERSE)
                # Message (padded to msg_len cells so the box stays aligned)
                self.scr.addstr(row, col, middle, curses.A_BOLD | curses.A_REVERSE)
                self.scr.addstr(row + 1, col, bottom, curses.A_BOLD | curses.A_REVERSE)
            except curses.error:
                pass  # Ignore if terminal too small
            self.scr.noutrefresh()
            self._backend.doupdate()

        draw_flash()

        # Poll for keys instead of time.sleep()ing: the wait is interruptible,
        # resize-aware, and never swallows an application key.
        deadline = time.monotonic() + max(duration, 0.0)
        try:
            self._set_scr_timeout(self.flash_poll_ms)
            while time.monotonic() < deadline:
                key = self.scr.getch()
                if key == curses.ERR:
                    continue
                if key == curses.KEY_RESIZE or self._backend.is_term_resized(self.rows, self.cols):
                    self._set_screen_dims()
                    draw_flash()
                    continue
                # Any real key dismisses the flash early, but is preserved so
                # the application still sees it via the next prompt() call.
                self.pending_keys.add(key)
                break
        finally:
            self._set_scr_timeout(prev_timeout_ms)
            if self.flash_repaint:
                # redraw=True forces a full pad repaint so the cleared screen is
                # fully restored (blank areas elsewhere stay blank).
                self.render(redraw=True)


    def alert(self, message: str = '', title: str = 'ALERT',
              _height: int | None = None, _width: int | None = None) -> None:
        # Modal, scrollable message box.  Content taller than the box is
        # reachable with the usual navigation keys (j/k, arrows, PageUp/Down,
        # Home/End, Space); ENTER acknowledges and returns.  Everything is drawn
        # through self._backend/self.scr, so there is no curses.newpad()/newwin()/
        # Textbox escape and the dialog is exercisable headlessly.
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)
        try:
            self._set_scr_timeout(self.alert_poll_ms)
            while True:
                # Refresh the cached dimensions from the live screen first: a
                # resize may have happened since the last render, and everything
                # below draws from self.rows/self.cols.
                self._set_screen_dims()

                layout = self._alert_layout(message, title, _height, _width)
                if layout is None:
                    return  # Terminal too small
                (box_title, footer_text, lines, box_height,
                 content_width, row0, row9, col0, col9) = layout

                visible_rows = max(box_height - 2, 1)  # subtract top/bottom borders
                max_scroll = max(len(lines) - visible_rows, 0)

                # Build the content pad once (all lines); scrolling only moves
                # the viewport via pad.refresh(scroll_top, ...), so a message
                # taller than the box is reachable instead of being clipped.
                pad = cast(CursesSurface,
                           self._backend.newpad(max(len(lines), 1), content_width + 1))
                for idx, line in enumerate(lines):
                    pad.addstr(idx, 0, textwidth.truncate(line, content_width))

                self._draw_alert_frame(box_title, footer_text, row0, row9, col0, col9,
                                       content_width)
                scroll_top = 0
                self._paint_alert(pad, scroll_top, visible_rows, len(lines),
                                  row0, col0, col9)

                # Inner key loop: scroll until the user acknowledges the alert.
                while True:
                    key = self.scr.getch()
                    if key == curses.ERR:
                        # A polling getch() also notices a resize that arrived
                        # without a KEY_RESIZE (mirrors flash()).
                        if self._backend.is_term_resized(self.rows, self.cols):
                            break  # redraw from scratch
                        continue
                    if key in (10, 13, curses.KEY_ENTER):
                        return  # acknowledged
                    if key == curses.KEY_RESIZE:
                        break  # redraw from scratch
                    new_top = self._alert_scroll_target(key, scroll_top, visible_rows, max_scroll)
                    if new_top != scroll_top:
                        scroll_top = new_top
                        self._paint_alert(pad, scroll_top, visible_rows, len(lines),
                                          row0, col0, col9)
        finally:
            self._set_scr_timeout(prev_timeout_ms)

    @staticmethod
    def _alert_scroll_target(key: int, scroll_top: int, visible_rows: int,
                             max_scroll: int) -> int:
        # "vim"-style scroll commands, matching the navigation family prompt()
        # honors.  Any other key is not a scroll command and leaves the view put.
        if key in (ord('k'), curses.KEY_UP):
            target = scroll_top - 1
        elif key in (ord('j'), curses.KEY_DOWN):
            target = scroll_top + 1
        elif key in (2, curses.KEY_PPAGE):            # Ctrl-B / PageUp
            target = scroll_top - visible_rows
        elif key in (6, curses.KEY_NPAGE, ord(' ')):  # Ctrl-F / PageDown / Space
            target = scroll_top + visible_rows
        elif key in (ord('0'), curses.KEY_HOME):
            target = 0
        elif key in (ord('$'), curses.KEY_END):
            target = max_scroll
        else:
            return scroll_top
        return min(max(target, 0), max_scroll)

    def _alert_layout(self, message: str, title: str, _height: int | None,
                      _width: int | None) -> tuple | None:
        # Auto-calculate dimensions with a 1-cell reverse-video border on all
        # sides.  _height/_width (content rows / content columns) cap the box so
        # a caller can force a scrollable dialog; None keeps the full box.  With
        # both None this reproduces the old full-box, 1-cell-margin geometry.
        max_box_width = self.cols - 2   # 1 cell left, 1 cell right
        max_box_height = self.rows - 2  # 1 cell top, 1 cell bottom
        if max_box_width < 20 or max_box_height < 5:
            return None  # terminal too small

        content_width = max_box_width - 2  # subtract the box borders
        if _width is not None:
            content_width = max(1, min(content_width, _width))

        # Determine if the title fits on the box border, or needs to go inside.
        footer_text = 'Press ENTER to ack'
        title_available_width = content_width - textwidth.string_width(footer_text) - 2

        lines: list[str] = []
        if textwidth.string_width(title) > title_available_width:
            # Title too long - use "alert" as the box title, put the real title inside.
            box_title = 'alert'
            lines.extend(textwidth.wrap(title, content_width))
            lines.append('')  # blank line separator
        else:
            box_title = title

        # Wrap the message content (cell-aware).
        if message:
            lines.extend(textwidth.wrap(message, content_width))

        if _height is not None:
            box_height = min(max_box_height, max(3, _height + 2))
        else:
            box_height = max_box_height
        box_width = content_width + 2

        # Centre the (possibly capped) box inside the reverse-video frame; with
        # the full box this is exactly the old 1-cell margin on every side.
        row0 = max(1, (self.rows - box_height) // 2)
        row9 = row0 + box_height - 1
        col0 = max(1, (self.cols - box_width) // 2)
        col9 = col0 + box_width - 1
        return box_title, footer_text, lines, box_height, content_width, row0, row9, col0, col9

    def _draw_alert_frame(self, box_title: str, footer_text: str, row0: int, row9: int,
                          col0: int, col9: int, content_width: int) -> None:
        scr = self.scr
        scr.clear()
        # 1-cell reverse-video frame around the whole screen.
        scr.insstr(0, 0, ' ' * self.cols, curses.A_REVERSE)
        scr.insstr(self.rows - 1, 0, ' ' * self.cols, curses.A_REVERSE)
        for row in range(1, self.rows - 1):
            scr.addch(row, 0, ' ', curses.A_REVERSE)
            scr.addch(row, self.cols - 1, ' ', curses.A_REVERSE)

        rectangle(cast(curses.window, scr), row0, col0, row9, col9)
        # Fill the box interior with the normal background (over the reverse video).
        for row in range(row0 + 1, row9):
            scr.addstr(row, col0 + 1, ' ' * (col9 - col0 - 1))

        scr.addstr(row0, col0 + 1, textwidth.truncate(box_title, content_width), curses.A_REVERSE)
        footer_pos = col0 + 1 + content_width - textwidth.string_width(footer_text)
        scr.addstr(row9, footer_pos, textwidth.truncate(footer_text, content_width))

    def _paint_alert(self, pad: CursesSurface, scroll_top: int, visible_rows: int,
                     content_height: int, row0: int, col0: int, col9: int) -> None:
        scr = self.scr
        # Scroll affordances on the box's left border.  Both cells are always
        # repainted (marker or plain border) so a marker does not linger once
        # the viewport scrolls back to that edge.  The markers are registered
        # glyphs, so a terminal without triangles gets ``^`` and ``v``.
        up_glyph = glyphs.get('alert_up')
        down_glyph = glyphs.get('alert_down')
        top_char = up_glyph if scroll_top > 0 else curses.ACS_VLINE
        bottom_char = (down_glyph if scroll_top + visible_rows < content_height
                       else curses.ACS_VLINE)
        markers = (up_glyph, down_glyph)
        for row, char in ((row0 + 1, top_char), (row0 + visible_rows, bottom_char)):
            scr.addch(row, col0, char, curses.A_BOLD if char in markers else curses.A_NORMAL)

        scr.noutrefresh()
        # Move the pad viewport: pad row scroll_top maps to the box's first
        # interior row, so content below the fold becomes reachable.
        pad.refresh(scroll_top, 0, row0 + 1, col0 + 1, row0 + visible_rows, col9 - 1)

    def clear(self) -> None:
        """Reset the current screen's content for a new pass.

        The screen-level ``Screen.clear()`` is the supported spelling (it also
        adopts the screen); this stays for 4.x compatibility and for the window
        itself.  Only content is reset: the pick/scroll position describes the
        user's place in the screen and survives a rebuild.  No surface wipe is
        needed -- the pads erase and repaint themselves every frame.
        """
        self._view.reset()

    # --- prompt(): key intake, special keys, app passthrough, navigation ------
    #
    # `prompt()` used to be a single 160-line function with a cyclomatic
    # complexity of 43 (AUDIT.md §3.5).  The seams below mirror the ones already
    # used by `answer()` and the two `handle_key()` implementations: read a key,
    # classify it, then act.  Each helper is small enough for `C901` to protect.

    def _pop_pending_key(self) -> int | None:
        """Return the next queued key that this window handles, if any."""
        while self.pending_keys:
            key = self.pending_keys.pop()
            if key in self.handled_keys:
                return key
        return None

    def _handle_prompt_key(self, key: int) -> tuple[bool, int | None]:
        """Classify one key.  The flag is True when prompt() should return."""
        if signals.ctrl_c_flag or key == curses.ERR or self._is_resize(key):
            return self._handle_prompt_control(key)
        return self._handle_prompt_app_or_navigation(key)

    def _is_resize(self, key: int) -> bool:
        return key == curses.KEY_RESIZE or self._backend.is_term_resized(self.rows, self.cols)

    def _handle_prompt_control(self, key: int) -> tuple[bool, int | None]:
        if signals.ctrl_c_flag:
            return self._handle_prompt_ctrl_c(key)
        if key == curses.ERR:
            # A timeout is also the polling point for a resize that arrived
            # without KEY_RESIZE; otherwise keep waiting for input.
            if self._backend.is_term_resized(self.rows, self.cols):
                return True, self._handle_prompt_resize()
            return False, None
        return True, self._handle_prompt_resize()

    def _handle_prompt_ctrl_c(self, key: int) -> tuple[bool, int | None]:
        # Re-queue the key that raced the signal so the app still sees it.
        if key in self.handled_keys:
            self.pending_keys.add(key)
        signals.ctrl_c_flag = False  # Reset flag
        if 0x3 in self.handled_keys:
            return True, 0x3  # Return the ETX key code
        return False, None

    def _handle_prompt_resize(self) -> int | None:
        # Sync curses' cached LINES/COLS before reading the window size; an
        # ERR-driven resize (no KEY_RESIZE) leaves the cache stale otherwise.
        self._backend.update_lines_cols()
        self._set_screen_dims()
        if not self._check_min_size() and 27 in self.handled_keys:
            # User pressed ESC to abort during size check.
            return 27
        # Return to the caller so it can redraw at the new size.
        return None

    def _record_demo_key(self, key: int) -> None:
        # Taken navigation keys are app-owned, so demo mode highlights them
        # just like any other application key.
        if self.opts.demo_mode and key not in self.opts.nav_keys:
            self.last_demo_key = self._format_key_for_demo(key)

    def _clear_demo_indicator(self) -> None:
        if self.opts.demo_mode:
            self.last_demo_key = ''

    def _is_passthrough_key(self, key: int) -> bool:
        return (32 <= key <= 126 or key in _PASSTHROUGH_EDITING_KEYS
                or key in NAVIGATION_KEYS or key in self.opts.taken_nav_keys
                or key in self.handled_keys)

    def _passthrough_result(self, key: int) -> int | None:
        if not self.passthrough_mode or not self._is_passthrough_key(key):
            return None
        self._record_demo_key(key)
        return key

    def _handle_prompt_app_or_navigation(self, key: int) -> tuple[bool, int | None]:
        done, result = self._handle_prompt_app_key(key)
        if done:
            return done, result
        return self._handle_prompt_navigation(key)

    def _handle_prompt_app_key(self, key: int) -> tuple[bool, int | None]:
        passed = self._passthrough_result(key)
        if passed is not None:
            return True, passed
        if key in self.handled_keys and not self.relax_handled_keys:
            self._record_demo_key(key)
            return True, key  # return for handling
        if key in self.opts.nav_keys:
            self._clear_demo_indicator()
        return False, None

    def _navigation_target(self, key: int) -> int | None:
        """Map a navigation key to the row it asks for, or None if it is not one."""
        # A key the application took is withdrawn from navigation dispatch.
        # This guard must come before the moves table: removing the key from
        # NAVIGATION_KEYS alone would still let UP/DOWN/page keys scroll,
        # because the table is what actually dispatches.
        if key in self.opts.taken_nav_keys:
            return None
        pos = self.pick_pos if self.pick_mode else self.scroll_pos
        delta = self.pick_size if self.pick_mode else 1
        half = self.scroll_view_size // 2
        moves: dict[int, Callable[[], int]] = {
            ord('k'): lambda: pos - delta,
            curses.KEY_UP: lambda: pos - delta,
            ord('j'): lambda: pos + delta,
            curses.KEY_DOWN: lambda: pos + delta,
            _CTRL_PAGE_UP: lambda: pos - self.scroll_view_size,
            curses.KEY_PPAGE: lambda: pos - self.scroll_view_size,
            _CTRL_HALF_UP: lambda: pos - half,
            _CTRL_HALF_DOWN: lambda: pos + half,
            _CTRL_PAGE_DOWN: lambda: pos + self.scroll_view_size,
            curses.KEY_NPAGE: lambda: pos + self.scroll_view_size,
            ord('0'): lambda: 0,
            curses.KEY_HOME: lambda: 0,
            ord('$'): lambda: self.body.row_cnt - 1,
            curses.KEY_END: lambda: self.body.row_cnt - 1,
            ord('H'): lambda: self.scroll_pos,
            ord('M'): lambda: self.scroll_pos + half,
            ord('L'): lambda: self.scroll_pos + self.scroll_view_size - 1,
        }
        move = moves.get(key)
        return None if move is None else move()

    def _in_body(self, pos: int) -> bool:
        return 0 <= pos < self.body.row_cnt

    def _skip_to_pickable(self, pos: int, direction: int) -> tuple[int, bool]:
        """Advance to the next pickable row; report if none was found."""
        attempts = 0
        max_attempts = self.body.row_cnt + 1  # Prevent infinite loop
        while self._in_body(pos) and not self._is_pickable(pos) and attempts < max_attempts:
            pos += direction
            attempts += 1
        exhausted = not self._in_body(pos) or attempts >= max_attempts
        return pos, exhausted

    def _decor_scroll_adjustment(self, was_pos: int, target: int, direction: int) -> int:
        """Scroll by the raw move when a DECOR block blocks the pick.

        `target`/`was_pos` are the raw move the key asked for (before
        DECOR-skipping): when no pickable row lies in that direction we scroll by
        that same amount, so j/k, the page keys and HOME/END still reach
        trailing/leading DECOR instead of stalling on the last pickable row.
        """
        limit = min(max(target, 0), self.body.row_cnt - 1)
        probe = was_pos + direction
        while self._in_body(probe):
            if not self._is_pickable(probe):
                return target - was_pos
            if probe == limit:
                return 0
            probe += direction
        return 0

    def _resolve_prompt_move(self, target: int, was_pos: int) -> tuple[int, int]:
        """Apply pickability rules to a requested move.

        Returns the row the pick should land on and the scroll adjustment to
        apply when a DECOR block made the requested move impossible.
        """
        if not self.pick_mode or target == was_pos:
            return target, 0
        direction = 1 if target > was_pos else -1
        pos, exhausted = self._skip_to_pickable(target, direction)
        if not exhausted:
            return pos, 0
        return was_pos, self._decor_scroll_adjustment(was_pos, target, direction)

    def _apply_pick_scroll(self, pos: int, was_pos: int, scroll_adjustment: int) -> None:
        # If pick_pos didn't move but there are DECOR lines to reveal, scroll
        # instead; latch free-scroll only when the view actually moves so a
        # blocked move at the very top/bottom is a no-op.
        if scroll_adjustment != 0 and pos == was_pos:
            new_scroll = max(0, min(self.scroll_pos + scroll_adjustment,
                                    self.max_scroll_pos))
            if new_scroll != self.scroll_pos:
                self.free_scroll = True
            self.scroll_pos = new_scroll
        elif pos != was_pos:
            # A genuine pick move re-synchronises the view with the pick.
            self.free_scroll = False

    def _apply_prompt_move(self, pos: int, was_pos: int, scroll_adjustment: int) -> None:
        if not self.pick_mode:
            self.scroll_pos = pos
            self.pick_pos = pos
        else:
            self.pick_pos = pos
            self._apply_pick_scroll(pos, was_pos, scroll_adjustment)
        self.fix_positions()

    def _finish_prompt_move(self, key: int, pos: int, was_pos: int,
                            scroll_adjustment: int) -> tuple[bool, int | None]:
        # Render if position changed OR if we adjusted scroll to reveal DECOR.
        if pos != was_pos or scroll_adjustment != 0:
            if self.opts.return_if_pos_change:
                # Don't render with stale content; return immediately to allow full redraw
                return True, None
            self.render()
            return False, None
        # The key was not a navigation key: in relax mode the app gets it.
        if self.relax_handled_keys:
            self._record_demo_key(key)
            return True, key
        return False, None

    def _handle_prompt_navigation(self, key: int) -> tuple[bool, int | None]:
        was_pos = self.pick_pos if self.pick_mode else self.scroll_pos
        target = self._navigation_target(key)
        if target is None:
            target = was_pos
        pos, scroll_adjustment = self._resolve_prompt_move(target, was_pos)
        self._apply_prompt_move(pos, was_pos, scroll_adjustment)
        return self._finish_prompt_move(key, pos, was_pos, scroll_adjustment)

    def prompt(self, seconds: float = 1.0) -> int | None:
        # Enforce the minimum before blocking.  The first prompt after the first
        # render is where the one-time content fit is applied, and every later
        # call re-checks in case the terminal changed between waits.
        self._finalize_min_size()
        if not self._check_min_size():
            return 27 if 27 in self.handled_keys else None
        begin_mono = time.monotonic()
        while True:
            if time.monotonic() - begin_mono >= seconds:
                return None
            key = self._pop_pending_key()
            if key is not None:
                return key
            done, result = self._handle_prompt_key(self.scr.getch())
            if done:
                return result
