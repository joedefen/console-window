
"""The window: terminal, pads, drawing, keys and dialogs."""

from __future__ import annotations

import atexit
import curses
import itertools
import logging
import sys
import time
import warnings
import weakref
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from curses.textpad import rectangle
from typing import ClassVar, cast

from . import geometry, glyphs, signals, textwidth
from ._appearance import _startup_theme
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

# Control keys that drive the same movements as the page keys.
_CTRL_PAGE_UP, _CTRL_HALF_DOWN, _CTRL_PAGE_DOWN, _CTRL_HALF_UP = 2, 4, 6, 21

# Display labels for the keys that can appear in the navigation help.  Arrows are
# included even though the default lines do not use them, so an app that takes
# one has a stable name; control keys use narrow caret notation.
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

# Structured navigation help: one row per action, with its key codes and the gap
# after the chunk.  The rendered text is generated from this table and the
# window's effective key set, so keys the app took disappear instead of lying.
# Keep it in step with `_navigation_target()`.
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

_NAV_HELP_PREFIX = 'NavKeys:    '
# Continuation rows get one space, not a pad as wide as the label.
_NAV_CONTINUATION = ' '


# Every key curses knows, derived from the module constants so terminal-specific
# keys are covered.  KEY_MIN/KEY_MAX are range sentinels, not keys.
_CURSES_KEY_NAMES: dict[int, str] = {
    getattr(curses, name): name.removeprefix('KEY_')
    for name in dir(curses)
    if name.startswith('KEY_') and name not in ('KEY_MIN', 'KEY_MAX')
}


def _key_label(key: int) -> str:
    """Best human-readable name for a curses key code.

    A `KEY_*` name wins, then caret notation, then the printable character; an
    unknown code is shown as `<code>`.  Arrows pass through the glyph registry.
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


def _nav_row_chunk(action: str, keys: tuple[int, ...],
                   effective: frozenset[int]) -> str | None:
    """One `action: keys` chunk, or None when every key in the row was taken.

    Keys are alternatives, so they are slash-joined; a partly taken chunk is
    padded to keep later chunks in their default columns.
    """
    shown = [_nav_key_label(key) for key in keys if key in effective]
    if not shown:
        return None
    full = f'{action}: {"/".join(_nav_key_label(key) for key in keys)}'
    return f'{action}: {"/".join(shown)}'.ljust(len(full))


def render_nav_help(effective: Iterable[int]) -> tuple[str, ...]:
    """Render the navigation help for one window's effective key set.

    Keys removed from *effective* disappear; empty chunks, rows and lines are
    dropped.  Taking every key leaves the one-line notice.
    """
    effective = frozenset(effective)
    lines: list[str] = []
    for rows in NAV_HELP_LINES:
        text = ''
        for action, keys, gap in rows:
            chunk = _nav_row_chunk(action, keys, effective)
            if chunk is not None:
                text += chunk + gap
        text = text.rstrip()
        if not text:
            continue
        # The label belongs to the block,
        # not to a particular line: if the top row is entirely taken by the app,
        # the bottom row carries it instead.
        head = _NAV_HELP_PREFIX if not lines else _NAV_CONTINUATION
        lines.append(f'{head}{text}')

    if not lines:
        lines = [
            _NAV_HELP_PREFIX
            + '(no navigation keys: all are bound by the application)'
        ]

    return tuple(lines)


# Navigation help for the default key set, stored as complete lines.
NAV_KEY_LINES: tuple[str, ...] = render_nav_help(NAVIGATION_KEYS)

# Editing keys passthrough mode hands through, so an in-place widget can cancel
# and rub out without the caller discovering `handled_keys`.
_PASSTHROUGH_EDITING_KEYS = frozenset({
    curses.KEY_BACKSPACE, 127, 8, 263,  # backspace variants
    curses.KEY_DC,                      # delete at the caret
    27,                                 # ESC: cancel an in-place edit
    curses.KEY_LEFT, curses.KEY_RIGHT,
    curses.KEY_HOME, curses.KEY_END,
    1, 5,  # Ctrl-A, Ctrl-E
})

# Jumps to an absolute row snap to the nearest pickable row, unlike j/k and pages.
_JUMP_TO_PICKABLE_KEYS = frozenset({
    ord('0'), ord('$'), ord('H'), ord('M'), ord('L'),
    curses.KEY_HOME, curses.KEY_END,
})

# How long the demo-mode key badge stays on the header.
_DEMO_KEY_TTL: float = 2.0

# Compact demo-mode names; printable keys are formatted separately.
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

# Live windows, weak-referenced and kept in creation order so `primary_window()`
# is deterministic.
_WINDOWS: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_WINDOW_IDS = itertools.count()

# Suspended windows are held strongly until resumed; the screen is reachable
# through `static_win`/`_static_backend`.
_SUSPENDED: list[ConsoleWindow] = []

# None until the first window; every construction must agree on the mode.
_SINGLETON_MODE: bool | None = None

# `atexit` teardown is registered once for the process, not per window.
_ATEXIT_REGISTERED = False

# "No content-row ceiling"; only has to exceed any allocatable row index.
_NO_ROW_LIMIT = sys.maxsize


def _register_window(win: ConsoleWindow) -> None:
    key = next(_WINDOW_IDS)
    win._registry_key = key
    _WINDOWS[key] = win


def _unregister_window(win: ConsoleWindow) -> None:
    key = getattr(win, '_registry_key', None)
    if key is not None:
        _WINDOWS.pop(key, None)
        win._registry_key = None


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if not _ATEXIT_REGISTERED:
        atexit.register(ConsoleWindow.stop_all)
        _ATEXIT_REGISTERED = True


class TerminalTooSmallError(RuntimeError):
    """`answer()` could not present its dialog because the terminal is small.

    Distinct from `answer()` returning `None` (the user aborted); a
    `RuntimeError` so the dialog's recovery loop cannot swallow it.
    """

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
    """Dual-mode `stop_curses` descriptor.

    In singleton mode `stop_curses()` suspends the shared screen (use
    `stop_all()` to tear down); per instance it tears the window down (use
    `suspend_curses()`/`resume_curses()` to pause).
    """

    def __get__(self, obj: ConsoleWindow | None,
                objtype: type[ConsoleWindow]) -> Callable[[], None]:
        def stop() -> None:
            """Stop the window: suspend in singleton mode, tear down per instance."""
            if obj is None:
                objtype._stop_legacy()
            else:
                obj._stop_instance()
        return stop


class _Content:
    """One namespace's rows plus the viewport-sized pads that paint them.

    `row_cnt` is derived from `texts`, so there is no second count to keep in step.
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
        """Number of rows added (`len(texts)`: there is no other store)."""
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

    `Screen` inherits this, so a screen *is* its view state, and stack
    activation is a pointer swap.  A window-owned instance is the fallback for
    bare-number stacks.  `reset()` clears content but not the user's position.
    """

    __slots__ = (
        '_opts_seeded',
        'body',
        'free_scroll',
        'head',
        'pick_mode',
        'pick_pos',
        'pick_range',
        'scroll_pos',
    )

    def __init__(self) -> None:
        self.pick_mode = False
        self.pick_pos = 0
        self.scroll_pos = 0
        self.free_scroll = False
        self.pick_range: list[int] | None = None  # [start_col, end_col] or None
        self.head = _Content(_NO_ROW_LIMIT)
        self.body = _Content(_NO_ROW_LIMIT)
        # opts is applied once at adoption, not owned; a Screen may precede the window.
        self._opts_seeded = False

    def set_pick_mode(self, on: bool = True) -> None:
        """Turn the pick highlight on or off for *this* screen."""
        self.pick_mode = bool(on)

    def set_pick_range(self, start_col: int | None = None,
                       end_col: int | None = None) -> None:
        """Set the highlighted column range for *this* screen's picked row.

        Args:
            start_col: First highlighted column; `None` clears the range.
            end_col: Last highlighted column; `None` also clears it.
        """
        self.pick_range = (None if start_col is None or end_col is None
                           else [start_col, end_col])

    def reset(self) -> None:
        """Reset content for a new pass, preserving the view position."""
        self.head.reset()
        self.body.reset()


class ConsoleWindow:
    """A curses pad-based pager with an independent pick/scroll model.

    While `prompt_active` is true, route every key through
    `handle_prompt_key` and swallow a `'continue'` result, so no action key
    fires underneath a live prompt.  Callbacks run after the prompt is gone and
    passthrough is restored, so they may start another prompt.

    Content and position belong to the current `Screen`; the window paints it,
    owns the terminal and routes keys.  `win.head`, `win.body`, `win.pick_*` and
    `win.scroll_pos` are views onto that screen.
    """

    stop_curses = _StopCurses()
    timeout_ms: int = 2000
    # Set by _register_window(); None once stop_curses() unregisters the window.
    _registry_key: int | None = None
    # Retry budgets are class-level knobs, read as `ConsoleWindow.*`; render()
    # and answer() share them.
    render_retry_seconds: float = 2.0
    render_retry_interval: float = 0.16
    STATUS_LEVELS: ClassVar[dict[str, int]] = {
        'info': curses.A_DIM,
        'warn': curses.A_BOLD,
        'error': curses.A_BOLD | curses.A_REVERSE,
    }
    # flash() repaints from the pads unless this is False.
    flash_repaint: bool = True
    flash_poll_ms: int = 50
    alert_poll_ms: int = 250
    # One-time minimum-size policy: the floor grows to fit the first rendered
    # screen, capped, with wiggle room for the gutter and scroll indicator.
    _AUTO_MIN_COLS_CAP: ClassVar[int] = 60
    _AUTO_MIN_WIGGLE_COLS: ClassVar[int] = 3
    _AUTO_MIN_BODY_ROWS: ClassVar[int] = 4
    # Singleton mode only: the process-wide screen and active window.
    static_scr: CursesSurface | None = None
    static_win: ConsoleWindow | None = None
    _static_backend: RenderBackend | None = None
    nav_keys: str = '\n'.join(NAV_KEY_LINES)
    def __init__(self, opts: ConsoleWindowOpts | None = None, head_line: bool | None = None,
                 head_rows: int | None = None, body_rows: int | None = None,
                 body_cols: int | None = None, keys: set | list | None = None,
                 pick_mode: bool | None = None,
                 mod_pick: Callable | None = None, ctrl_c_terminates: bool | None = None,
                 backend: RenderBackend | None = None, singleton: bool = True) -> None:
        has_opts = opts is not None
        has_deprecated = any(p is not None for p in [head_line, head_rows, body_rows, body_cols,
                                                       keys, pick_mode, mod_pick, ctrl_c_terminates])

        if has_opts and has_deprecated:
            raise ValueError("Cannot use both 'opts' and deprecated parameters. Use opts only.")

        # The singleton choice is process-wide; the first construction latches it.
        global _SINGLETON_MODE
        mode = bool(singleton)
        if _SINGLETON_MODE is None:
            _SINGLETON_MODE = mode
        else:
            assert mode == _SINGLETON_MODE, (
                f'ConsoleWindow(singleton={mode}) conflicts with this process '
                f'(singleton={_SINGLETON_MODE}); every window must use the same value')
        self.singleton = mode

        if has_opts:
            assert opts is not None
            self.opts = opts
        elif has_deprecated:
            # Backward compatibility: build opts from the deprecated parameters.
            warnings.warn(
                'ConsoleWindow(head_line=..., head_rows=..., body_rows=..., '
                'body_cols=..., keys=..., pick_mode=..., '
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
                mod_pick=mod_pick,
                ctrl_c_terminates=ctrl_c_terminates if ctrl_c_terminates is not None else True
            )
        else:
            self.opts = ConsoleWindowOpts()

        # Per-window theme: opts seeds it, else the process default; `NO_COLOR`
        # is honored here so a first window without the display helpers starts mono.
        self.theme = Theme.resolve(
            _startup_theme(getattr(self.opts, 'theme', None))
            or Theme.get_current())

        # The glyph *mode* is process-global; the option seeds it.
        self._apply_glyph_mode()

        signals.set_ctrl_c_policy(self.opts.ctrl_c_terminates)
        self.ctrl_c_terminates = self.opts.ctrl_c_terminates

        self._backend: RenderBackend = backend if backend is not None else CursesBackend()
        # `CursesSurface` describes the full drawing API; the Surface protocol is
        # deliberately small so headless surfaces satisfy it too.
        if self.singleton and _SUSPENDED:
            ConsoleWindow._resume_singleton()
        if self.singleton and ConsoleWindow.static_scr is not None:
            # Every singleton instance draws through the process screen and its backend.
            self._backend = ConsoleWindow._static_backend or self._backend
            self.scr = ConsoleWindow.static_scr
        else:
            self.scr = self._new_screen()
            if self.singleton:
                ConsoleWindow.static_scr = self.scr
                ConsoleWindow._static_backend = self._backend
        # curses exposes no gettimeout(); modal dialogs restore the timeout from here.
        self._scr_timeout_ms = ConsoleWindow.timeout_ms

        # Pads are viewport-sized blit buffers; content lives on the current view.
        # The fallback view serves until a Screen is adopted, and bare-number stacks.
        self._fallback_view = _ViewState()
        self._view: _ViewState = self._fallback_view
        self._seed_view(self._fallback_view)

        _register_window(self)
        if self.singleton:
            ConsoleWindow.static_win = self

        self.mod_pick = self.opts.mod_pick  # callback to modify the highlighted row
        self.hor_line_cnt = 1 if self.opts.head_line else 0
        self.max_scroll_pos = 0
        # True while the terminal is handed back but the window can be reattached.
        self.suspended = False
        self.rows, self.cols = 0, 0
        # The one-time minimum is measured from the first painted frame.
        self._has_rendered = False
        self._auto_min_cols_rows: tuple[int, int] | None = None
        self.body_cols, self.body_rows = self.opts.body_cols, self.opts.body_rows
        self.scroll_view_size = 0
        self.handled_keys = set(self.opts.keys) if isinstance(self.opts.keys, (set, list)) else set()
        self.pending_keys: set[int] = set()
        self.last_demo_key = ''
        # No timestamp keeps a key set directly on the attribute visible.
        self._demo_key_at: float | None = None
        self.passthrough_mode = False  # When True, all printable keys pass through
        self.prompt_line = PromptLine()
        self._prompt_prev_passthrough = False
        # App policy for the separator rule while a prompt is live.
        self.prompt_separator_attr: int | None = None
        # Transient status painted on the separator row (see status()).
        self._status_text = ''
        self._status_attr: int | None = None
        self._status_deadline: float | None = None
        self._status_no_row_warned = False
        self._help_fonts_shown = False
        self.relax_handled_keys = self.opts.relax_handled_keys
        self._set_screen_dims()
        self.calc()

    def set_handled_keys(self, keys: object) -> None:
        """Replace `handled_keys` from a spinner, an iterable, or neither."""
        if hasattr(keys, 'keys'):
            self.handled_keys = set(keys.keys) if keys.keys else set()
        elif isinstance(keys, (set, list)):
            self.handled_keys = set(keys)
        else:
            self.handled_keys = set()

    @contextmanager
    def temp_handled_keys(self, *keys: int) -> Iterator[ConsoleWindow]:
        """Temporarily add key codes to `handled_keys`, removing only those."""

        added = {key for key in keys if key not in self.handled_keys}
        self.handled_keys.update(added)
        try:
            yield self
        finally:
            self.handled_keys.difference_update(added)

    def set_demo_mode(self, enabled: bool | None) -> bool:
        """Turn demo mode on or off and return the resulting state.

        Args:
            enabled: True/False to set it explicitly; `None` toggles.
        """
        if enabled is None:
            self.opts.demo_mode = not (self.opts.demo_mode)
        else:
            self.opts.demo_mode = bool(enabled)
        if not self.opts.demo_mode:
            self.last_demo_key = ''
            self._demo_key_at = None
        return self.opts.demo_mode

    def _visible_demo_key(self) -> str:
        """The badge text to draw, or '' once the key has faded."""
        if not self.opts.demo_mode or not self.last_demo_key:
            return ''
        # A window rebuilt without __init__ has no timestamp; treat the key as fresh.
        arrived = getattr(self, '_demo_key_at', None)
        if arrived is not None:
            if time.monotonic() - arrived >= _DEMO_KEY_TTL:
                self.last_demo_key = ''
                self._demo_key_at = None
                return ''
        return self.last_demo_key

    def _format_key_for_demo(self, key: int) -> str:
        label = _DEMO_KEY_LABELS.get(key)
        if label is not None:
            return label
        if 32 < key < 127:
            return f' {chr(key)} '
        return _key_label(key)

    def get_pad_width(self) -> int:
        """Usable pad width: terminal width less one column, capped by `body_cols`."""
        return min(self.cols-1, self.body_cols)

    # --- content and view indirection --------------------------------------
    #
    # Content and position belong to the current screen; these properties keep
    # `win.body`/`win.pick_pos` working without a copy on activation.

    def _seed_view(self, view: _ViewState) -> None:
        """Apply `opts` to *view* the first time it is adopted.

        Adoption is the one moment both exist; after it the screen's own fields
        are authoritative, so two screens can differ.
        """
        if view._opts_seeded:
            return
        row_limit = (self.opts.max_rows if self.opts.max_rows is not None
                     else _NO_ROW_LIMIT)
        for content, hint in ((view.head, self.opts.head_rows),
                              (view.body, self.opts.body_rows)):
            content.rows = row_limit
            content.hint_rows = hint
            content.cols = self.opts.body_cols
        view.pick_mode = bool(self.opts.pick_mode)
        view.pick_range = self.opts.pick_range
        view._opts_seeded = True

    def _adopt_view(self, view: _ViewState) -> None:
        """Point the window at *view* and seed it if it is new.

        Called by `Screen.clear()` and by `ScreenStack` on activation.  A new view
        gets pads sized to the terminal, so its first redraw cannot fail on a
        missing pad.
        """
        self._seed_view(view)
        self._view = view
        if getattr(self, 'scr', None) is not None:
            if view.head.pad is None or view.body.pad is None:
                self._sync_pad_geometry()
            # A theme may have changed while this screen was inactive.
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
        """Set the active screen's pick highlight."""
        self._view.pick_mode = bool(value)

    @property
    def pick_pos(self) -> int:
        """The active screen's picked content row."""
        return self._view.pick_pos

    @pick_pos.setter
    def pick_pos(self, value: int) -> None:
        """Move the pick position on the active screen (not clamped here)."""
        self._view.pick_pos = value

    @property
    def scroll_pos(self) -> int:
        """The active screen's top visible body row."""
        return self._view.scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value: int) -> None:
        """Set the top visible body row (clamped on the next `render()`)."""
        self._view.scroll_pos = value

    @property
    def free_scroll(self) -> bool:
        """True while the active screen is scrolled away from its picked row."""
        return self._view.free_scroll

    @free_scroll.setter
    def free_scroll(self, value: bool) -> None:
        """Detach the viewport from the picked row so the two move apart."""
        self._view.free_scroll = bool(value)

    @property
    def pick_range(self) -> list[int] | None:
        """The active screen's highlighted column range (or None)."""
        return self._view.pick_range

    @pick_range.setter
    def pick_range(self, value: list[int] | None) -> None:
        """`[start_col, end_col]` to highlight on the picked row, or `None`."""
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
        """Return a registered glyph in the active set (see `Glyphs.get`).

        Args:
            name: Registered glyph name, e.g. `'cursor'` or `'bullet'`.
        """
        return glyphs.get(name)

    def _apply_glyph_mode(self) -> None:
        """Register the app's glyphs and seed the process-wide glyph mode.

        `opts.ascii` seeds it when not `None`; otherwise auto-detection runs only
        if nothing has decided yet, so `--ascii` survives later windows.
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

        Returns False for an unknown theme, or for a palette when the backend has
        no color support; the choice is still recorded for a later start.  Color
        pairs are per-terminal, so a palette affects every window on the screen.
        """
        name = Theme.canonical(theme_name)
        if name is None:
            return False
        self.theme = name
        # Record the choice even when nothing can be painted.
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
        # A new pad has no background, so re-apply this window's theme after
        # every reallocation.  The pair is already installed and safely mapped.
        if not self._backend.has_colors():
            return
        theme = Theme.THEMES[Theme.resolve(getattr(self, 'theme', None))]
        if ('default_fg' in theme and 'default_bg' in theme
                and Theme.DEFAULT_BG < self._backend.color_pairs()):
            pad.bkgd(' ', self._backend.color_pair(Theme.DEFAULT_BG))

    def _sync_pad_geometry(self) -> None:
        # Viewport-sized pads (height, cols-1), so pad cost does not track content.
        height = max(1, self.rows)
        width = max(1, self.cols - 1)
        for ns in (self.head, self.body):
            if ns.pad_rows == height and ns.pad_cols == width:
                continue
            ns.pad = cast(CursesSurface, self._backend.newpad(height, width))
            ns.pad_rows, ns.pad_cols = height, width
            self._apply_pad_theme(ns.pad)

    @property
    def rows_dropped(self) -> int:
        """Rows dropped so far by the `opts.max_rows` ceiling (head + body)."""
        # The counter and the one-shot warning keep a runaway append observable.
        return self.head.rows_dropped + self.body.rows_dropped

    @property
    def min_size(self) -> tuple[int, int]:
        """The effective `(cols, rows)` floor in force right now."""
        return self._min_size()

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
        """The `Context` of the picked row, or None when not picking."""
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
        """Multi-line navigation blurb for the default key set."""
        return ConsoleWindow.nav_keys

    @staticmethod
    def get_nav_key_lines() -> tuple[str, ...]:
        """The navigation lines, for a window without per-instance keys."""
        return NAV_KEY_LINES

    def nav_help_lines(self) -> tuple[str, ...]:
        """Navigation help for *this* window's effective key set."""
        return render_nav_help(self.opts.nav_keys)

    def _set_screen_dims(self) -> bool:
        rows, cols = self.scr.getmaxyx()
        same = bool(rows == self.rows and cols == self.cols)
        self.rows, self.cols = rows, cols
        return same

    def _set_scr_timeout(self, ms: int) -> None:
        self._scr_timeout_ms = ms
        self.scr.timeout(ms)

    def _min_size(self) -> tuple[int, int]:
        """The effective `(cols, rows)` floor: the option plus the one-time fit."""
        floor_cols, floor_rows = self.opts.min_cols_rows
        # getattr keeps test windows that bypass __init__ usable.
        fit: tuple[int, int] | None = getattr(self, '_auto_min_cols_rows', None)
        if fit is None:
            return floor_cols, floor_rows
        fit_cols, fit_rows = fit
        return max(floor_cols, fit_cols), max(floor_rows, fit_rows)

    def _finalize_min_size(self) -> None:
        """Fold the first painted screen's shape into the minimum, once.

        Width comes from its widest untruncated header and height from its
        header plus a small body; later screens are ignored.
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

        Dimensions are re-read in the loop, because not every resize delivers
        `KEY_RESIZE` and a headless backend never does.
        """
        self._set_screen_dims()
        min_cols, min_rows = self._min_size()
        if self.rows >= min_rows and self.cols >= min_cols:
            return True

        while True:
            # curses caches LINES/COLS; refresh before re-reading.
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

        A suspended window resumes (in singleton mode, every window sharing the
        screen) so the pads and content model survive.
        """
        if self.suspended:
            scr = self.resume_curses()
            if scr is not None:
                return scr
        if self.scr is not None:
            return self.scr
        # Screen-less: restart a screen and attach this window to it.
        scr = ConsoleWindow.start_curses() if self.singleton else self._new_screen()
        if self.scr is None:  # start_curses() may have reattached it already
            backend = (ConsoleWindow._static_backend if self.singleton else None) \
                or self._backend
            self._attach_screen(scr, backend)
        return scr

    def _attach_screen(self, scr: CursesSurface, backend: RenderBackend) -> None:
        """Point this window at a (re)started screen and force a full repaint.

        Content and pads survive `endwin()`; only the screen handle, backend,
        dimensions and backgrounds are refreshed.
        """
        self._backend = backend
        self.scr = scr
        self.suspended = False
        _register_window(self)
        self.calc()
        self._set_scr_timeout(self._scr_timeout_ms)
        for ns in (self.head, self.body):
            self._apply_pad_theme(cast(CursesSurface, ns.pad))
        self._mark_pads_for_redraw()
        self._clear_surface()

    def suspend_curses(self) -> None:
        """Leave curses mode without destroying this window.

        `endwin()` keeps the screen (and pads) alive, so `resume_curses()` can
        reattach.  In singleton mode all windows suspend together.
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
        """Re-enter curses after `suspend_curses`; the next `render()` repaints."""
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
        """Start (or resume) the process screen and return its surface.

        Args:
            backend: Backend that creates the screen; ignored when resuming,
                since the screen belongs to the backend that created it.
        """
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
            # static_win is kept as the anchor for restarting and theming.

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
            win._attach_screen(scr, backend)
        return scr

    @staticmethod
    def _install_theme(backend: RenderBackend, scr: CursesSurface,
                       theme_name: str | None) -> str:
        """Install *theme_name*'s colors into the terminal's pair table.

        Color pairs are per-terminal; the caller decides whose theme wins.
        `Theme.install` does the low-color mapping and `-1` resolution.
        """
        name = Theme.install(backend, theme_name)
        theme = Theme.THEMES[name]
        # Pair 0 cannot change, so set the screen background directly.
        if ('default_fg' in theme and 'default_bg' in theme
                and Theme.DEFAULT_BG < backend.color_pairs()):
            scr.bkgd(' ', backend.color_pair(Theme.DEFAULT_BG))
        return name

    @staticmethod
    def _init_screen(backend: RenderBackend,
                     theme_name: str | None = None) -> CursesSurface:
        # A screen can start before any window; a resolved name makes this a no-op.
        theme_name = _startup_theme(theme_name)
        _register_atexit()
        signals.setup_ctrl_c()
        scr = cast(CursesSurface, backend.start(ConsoleWindow.timeout_ms))

        if backend.has_colors():
            # start_color() captures COLORS/COLOR_PAIRS for a curses backend.
            backend.start_color()
            name = ConsoleWindow._install_theme(backend, scr, theme_name)
        else:
            # No palette can be painted, but mono is still a real theme.
            name = Theme.resolve(theme_name)
        # New windows inherit the most recently applied theme.
        Theme.set_active(name)

        return scr

    def set_pick_mode(self, on: bool = True) -> None:
        """Set pick mode on the *current* screen (see `Screen.set_pick_mode`)."""
        self._view.set_pick_mode(on)

    def set_pick_range(self, start_col: int | None = None, end_col: int | None = None) -> None:
        """Set the pick column range on the *current* screen."""
        self._view.set_pick_range(start_col, end_col)

    def _stop_instance(self) -> None:
        """Stop this window (and, in singleton mode, suspend the shared screen)."""
        if getattr(self, 'singleton', False):
            # stop_curses() suspends the shared screen; stop_all() tears it down.
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
        """The class-level `ConsoleWindow.stop_curses()` call (suspends in singleton mode)."""
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
            # Already in shell mode; just forget the suspended windows.
            for win in windows + suspended:
                _unregister_window(win)
            return
        try:
            (backend or CursesBackend()).stop(scr)
        finally:
            # One teardown per window, matching the per-window setup.
            for win in windows + suspended:
                _unregister_window(win)
                signals.teardown_ctrl_c()

    def __enter__(self) -> ConsoleWindow:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop_curses()

    @classmethod
    def active_windows(cls) -> list[ConsoleWindow]:
        """Every live window, in creation order."""
        return list(_WINDOWS.values())

    @classmethod
    def primary_window(cls) -> ConsoleWindow | None:
        """The window process-level helpers act on, or None."""
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
                    cast(CursesSurface, ns.pad).bkgd(' ', pair)
                except curses.error:
                    pass

    def calc(self) -> bool:
        """Recompute dimensions and viewport sizes; True warrants a full repaint."""
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
        # Model-only: `ns.rows` is the max_rows ceiling, not the pad height.
        if ns.row_cnt >= ns.rows:
            self._warn_rows_dropped(ns, 'body' if is_body else 'head')
            return

        # Transliterate before measuring: fallbacks can differ in cell width.
        text = glyphs.transliterate(text)

        if attr is None:
            attr = curses.A_NORMAL
        if is_body and self.pick_mode and self.opts.strip_attrs_in_pick_mode:
            attr = curses.A_NORMAL

        if resume and ns.row_cnt > 0 and ns.texts:
            row = min(ns.row_cnt - 1, len(ns.texts) - 1)
            # The model records the row's text, so its display width is the resume column.
            x = textwidth.string_width(ns.texts[row])
            cols = self.get_pad_width() - x
            if cols > 0:
                actual_text = textwidth.truncate(text, cols)
                ns.texts[row] += actual_text
                # Append to the existing attrs list (counts are code points).
                if row < len(ns.text_attrs):
                    ns.text_attrs[row].append((attr, len(actual_text)))
        else:
            if ns is self.head:
                # Measure before truncation so a narrow terminal cannot shrink the fit.
                ns.max_header_len = max(
                    ns.max_header_len, textwidth.string_width(text))
            actual_text = textwidth.truncate(text, self.get_pad_width())
            ns.texts.append(actual_text)
            ns.text_attrs.append([(attr, len(actual_text))])
            ns.contexts.append(context)

    def _warn_rows_dropped(self, ns: _Content, which: str, *,
                           stacklevel: int = 5) -> None:
        # The row is discarded and counted; one warning per fill episode, never fatal.
        # stacklevel 5: warn() <- here <- _add() <- Screen.add_*() <- caller.
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

    # The public writers live on Screen and delegate here with their namespace.

    # --- in-place prompt lifecycle -----------------------------------------

    @property
    def prompt_active(self) -> bool:
        """True while `begin_prompt` is live."""
        return self.prompt_line.active

    def begin_prompt(self, prompt: str, *, hint: str = '', mode: str = 'y',
                     identity: str | None = None, seed: str = '',
                     choices: str | list[str] | tuple[str, ...] | None = None,
                     on_confirm: Callable[[str], object] | None = None,
                     on_cancel: Callable[[], object] | None = None,
                     answer_hint: str = '') -> bool:
        """Start an in-place prompt and enable passthrough key routing.

        Route every key through `handle_prompt_key` and swallow `'continue'`.
        *answer_hint* replaces the default trailing hint; `{mode}` is replaced
        with the live mode letter.
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

        The prompt is torn down and passthrough restored before the callback,
        so a callback may begin the next prompt.
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

        Centering happens here because only the composed line knows its real
        display width.
        """
        if not self.prompt_line.active:
            return False
        text = self.prompt_line.get_display_string()
        attr = attr if attr is not None else curses.A_BOLD
        if align == 'center':
            lead = max(0, (self.get_pad_width() - textwidth.string_width(text)) // 2)
            if lead:
                # Two adds on one row so the padding carries the same attribute.
                self._add(ns, ' ' * lead, attr=attr)
                self._add(ns, text, attr=attr, resume=True)
                return True
        self._add(ns, text, attr=attr)
        return True

    def _add_prompt_lines(self, ns: _Content, attr: int | None = None,
                          hint_attr: int | None = None) -> bool:
        """Draw the prompt and its hint as transient body rows.

        For item-scoped questions the caller draws this after the relevant row.
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
        """Implement `Screen.add_fancy_header()`; see it for the public API."""
        if isinstance(line, str):
            if mode == 'Off':
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
        """Implement `Screen.add_header_line()`; see it for the public API."""
        self._emit_header_spans(ns, list(header_line), mode, search_pattern_attr,
                                line_attr)

    @staticmethod
    def _resolve_header_attr(role: str, mode: str,
                             search_pattern_attr: int | None,
                             line_attr: int | None = None) -> int | None:
        """Map one span *role* and header *mode* to a curses attribute.

        `line_attr` is OR'd into the result, so it reaches every run.
        """
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

        visible_length = sum(textwidth.string_width(text) for text, attr in result_sections)

        is_first_header = (ns.row_cnt == 0)

        # The demo badge sits at the right edge; a full header simply drops it.
        demo_key = self._visible_demo_key() if is_first_header else ''
        if demo_key:
            key_width = textwidth.string_width(demo_key)
            gap = max(1, self.get_pad_width() - visible_length - key_width)
            result_sections.append((' ' * gap, None))
            result_sections.append((demo_key, curses.A_REVERSE))

        for idx, (text, attr) in enumerate(result_sections):
            resume = bool(idx > 0)  # Resume for all but the first section
            self._add(ns, text, attr=attr, resume=resume)

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
        # Pick styling follows the paint, because scrolling moves rows without
        # changing pick_pos.
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

        # Attr runs count code points; the highlight range counts cells.
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
            # draw() may replace text without rewriting text_attrs; paint the tail plain.
            tail = textwidth.truncate(text[pos:], self.get_pad_width() - col)
            if tail:
                pad.addstr(row, col, tail, curses.A_NORMAL)

    def _draw_plain_line(self, pad: CursesSurface, row: int, col_offset: int, text: str,
                         extra_attr: int | None,
                         extra_attr_range: list[int] | tuple[int, int] | None) -> None:
        if extra_attr is not None and extra_attr_range:
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

        if segment_start < range_start and segment_end > segment_start:
            before_end = min(segment_end, range_start)
            parts.append((text[segment_start:before_end], attr, False))

        in_range_start = max(segment_start, range_start)
        in_range_end = min(segment_end, range_end)
        if in_range_start < in_range_end:
            parts.append((text[in_range_start:in_range_end], attr, True))

        if segment_end > range_end and segment_start < segment_end:
            after_start = max(segment_start, range_end)
            parts.append((text[after_start:segment_end], attr, False))

        return parts

    def _scroll_indicator_row(self) -> int:
        # No separator means no indicator; the anchor is the viewport top.
        if not self.hor_line_cnt:
            return self.body_base
        return geometry.scroll_indicator_row(
            self.scroll_pos, self.max_scroll_pos, self.scroll_view_size,
            self.body_base, self.rows)

    def _scroll_indicator_col(self) -> int:
        # While free-scrolling, show the viewport rather than the parked pick.
        pick_mode = self.pick_mode and not self.free_scroll
        return geometry.scroll_indicator_col(
            pick_mode, self.pick_pos, self.scroll_pos,
            self.max_scroll_pos, self.body.row_cnt, self.cols)

    def _calc_indicator(self, pos: int, pos0: int, pos9: int, ind0: int, ind9: int) -> int:
        return geometry.calc_indicator(pos, pos0, pos9, ind0, ind9, self.max_scroll_pos)

    def render(self, redraw: bool = False) -> None:
        """Draw one frame, retrying briefly on `curses.error`."""
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
                'pick_pos=%s pick_mode=%s rows=%s cols=%s',
                self.head.row_cnt, self.head.view_cnt, self.hor_line_cnt,
                self.body.row_cnt, self.scroll_pos, self.max_scroll_pos,
                self.pick_pos, self.pick_mode,
                self.rows, self.cols)
            raise


    def fix_positions(self, delta: int = 0) -> int:
        """Clamp pick/scroll positions after a move.

        Returns the columns of pick gutter to reserve, 0 when pick mode is off.
        """
        self.calc()

        # Keep the old position so abut constraints can be checked before the move.
        old_pick_pos = self.pick_pos if self.pick_mode else -1

        if self.pick_mode:
            self.pick_pos += delta
            # Move both, so DECOR lines can show above and below the pick.
            self.scroll_pos += delta
        else:
            self.scroll_pos += delta
            self.pick_pos += delta

        indent = 0
        if self.body_base < self.rows:
            ind_pos = 0 if self.pick_mode else self._scroll_indicator_row()
            if self.pick_mode:
                abut_range = self._abut_range_at(old_pick_pos)
                self._clamp_pick_pos(abut_range)
                # Re-check at the new position to adjust the scroll.
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

    def _attached(self, row: int, other: int) -> bool:
        """Whether two adjacent rows belong to the same pick block."""
        for probe, neighbor in ((row, other), (other, row)):
            rng = self._abut_range_at(probe)
            if rng is not None and rng[0] <= neighbor <= rng[1]:
                return True
        return False

    def _pick_block(self) -> tuple[int, int]:
        """The first and last rows kept on screen with the picked row.

        Rows joined by `abut` form the block, which scrolling keeps visible
        together; the highlight itself is only the picked row.
        """
        if not self.pick_mode or self.body.row_cnt <= 0:
            return self.pick_pos, self.pick_pos
        lo = hi = max(0, min(self.pick_pos, self.body.row_cnt - 1))
        while hi + 1 < self.body.row_cnt and self._attached(hi, hi + 1):
            hi += 1
        while lo > 0 and self._attached(lo, lo - 1):
            lo -= 1
        return lo, hi

    def _first_pickable(self) -> int:
        """The row `0`/HOME selects: the first pickable row, or row 0."""
        if not self.pick_mode:
            return 0
        first = geometry.find_pickable(self._is_pickable, self.body.row_cnt, 0)
        return 0 if first < 0 else first

    def _last_pickable(self) -> int:
        """The row `$`/END selects: the last pickable row, or the last row."""
        last_row = max(self.body.row_cnt - 1, 0)
        if not self.pick_mode:
            return last_row
        last = geometry.find_pickable(
            self._is_pickable, self.body.row_cnt, last_row)
        return last_row if last < 0 else last

    def _clamp_pick_pos(self, abut_range: tuple[int, int] | None) -> None:
        self.pick_pos = max(self.pick_pos, 0)
        self.pick_pos = min(self.pick_pos, self.body.row_cnt-1)

        if abut_range:
            min_line, max_line = abut_range
            self.pick_pos = max(self.pick_pos, min_line)
            self.pick_pos = min(self.pick_pos, max_line)

        # The pick rests on a pickable row; blocks are defined by abut, so the
        # row above the pick never moves it.
        if not self._is_pickable(self.pick_pos):
            self.pick_pos = geometry.find_pickable(
                self._is_pickable, self.body.row_cnt, self.pick_pos)

    def _adjust_scroll_for_abut(self, abut_range: tuple[int, int] | None) -> None:
        if self.pick_pos < 0:
            self.scroll_pos = 0
        elif abut_range:
            # "After trumps before".
            self._scroll_to_fit_abut(abut_range)
        elif self.free_scroll:
            # The user scrolled deliberately; leave the viewport, clamped below.
            pass
        elif self.scroll_pos > self.pick_pos:
            self.scroll_pos = self.pick_pos
        elif self.pick_pos >= self.scroll_pos + self.scroll_view_size:
            # Scroll down to show the block's last attached row.
            _lo, hi = self._pick_block()
            self.scroll_pos = hi - self.scroll_view_size + 1
        # scroll_pos < pick_pos is allowed, to show DECOR lines above the pick.
        self.scroll_pos = max(self.scroll_pos, 0)
        self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)

    def _scroll_to_fit_abut(self, abut_range: tuple[int, int]) -> None:
        min_line, max_line = abut_range
        range_size = max_line - min_line + 1
        viewport_bottom = self.scroll_pos + self.scroll_view_size - 1

        # Prefer the "after" lines: scroll down before scrolling up.
        if max_line > viewport_bottom:
            self.scroll_pos = max_line - self.scroll_view_size + 1
        elif min_line < self.scroll_pos and self.pick_pos < self.scroll_pos:
            self.scroll_pos = min_line

        if range_size > self.scroll_view_size:
            # Range does not fit: keep the pick visible without scrolling past it.
            if self.pick_pos < self.scroll_pos:
                self.scroll_pos = max(self.scroll_pos, min_line)
            max_scroll = max_line - self.scroll_view_size + 1
            self.scroll_pos = min(self.scroll_pos, max_scroll)

    def render_once(self, redraw: bool = False) -> None:
        """Paint one frame, without the retry loop `render()` adds."""
        if redraw:
            self._mark_pads_for_redraw()

        indent = self.fix_positions()

        # --- 2. Screen Drawing (Highlighting, Scrollbar, Separator) ---

        if indent > 0 and self.pick_mode:
            self._draw_pick_gutter()

        if self._separator_available():
            self._draw_separator_and_indicator()

        # noutrefresh/doupdate is cheaper than refresh(); redrawwin handles repaints.
        self.scr.noutrefresh()

        # --- 3. Pad Drawing (Body and Head) ---

        self._refresh_pads(indent)

        # --- 4. Final Update (Only one physical screen update) ---
        self._backend.doupdate()
        # The first completed frame feeds the one-time minimum-size measurement.
        self._has_rendered = True

    def _mark_pads_for_redraw(self) -> None:
        self.scr.redrawwin()
        cast(CursesSurface, self.head.pad).redrawwin()
        cast(CursesSurface, self.body.pad).redrawwin()

    def _draw_pick_gutter(self) -> None:
        # Blank the whole left column; blanking only the body leaves stale header cells.
        self.scr.vline(0, 0, ' ', self.body_base + self.scroll_view_size)
        if self.pick_pos >= 0:
            pos = self.pick_pos - self.scroll_pos + self.body_base
            # Free-scrolling can park the pick outside the viewport; only mark it
            # on screen so '>' never spills into the header band.
            if self.body_base <= pos < self.body_base + self.scroll_view_size:
                self.scr.addstr(pos, 0, '>', curses.A_REVERSE)

    def _separator_available(self) -> bool:
        """True when the window has a separator row to paint chrome onto.

        Keyed on `head_line`, not `head.view_cnt`, so the rule cannot land on
        body row 0.
        """
        return bool(self.hor_line_cnt) and self.head.view_cnt < self.rows

    def _draw_separator_and_indicator(self) -> None:
        # Reserve the last column, as get_pad_width() does; the corner raises.
        if self.cols < 2:
            return
        # An application may dim the rule behind a live prompt.
        rule_attr = (self.prompt_separator_attr
                     if self.prompt_line.active and self.prompt_separator_attr is not None
                     else curses.A_NORMAL)
        sep_row = self.body_base - 1
        rule_width = self.cols - 1
        self.scr.hline(sep_row, 0, curses.ACS_HLINE, rule_width, rule_attr)
        ind_pos = min(self._scroll_indicator_col(), rule_width - 1)
        bot, cnt = self._scroll_indicator_span(ind_pos) if ind_pos >= 0 else (-1, 0)
        # Status first, so it cannot cover the indicator.
        self._draw_status_line(bot if ind_pos >= 0 else -1)
        if ind_pos >= 0:
            for idx in range(bot, bot + cnt):
                self.scr.addch(sep_row, idx, curses.ACS_HLINE,
                               curses.A_REVERSE)

    def _draw_status_line(self, indicator_start: int) -> None:
        """Paint the current status on the separator row.

        *indicator_start* is the first indicator cell, or -1; the text stops
        one blank cell before it.
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
        width = self.scroll_view_size/self.body.row_cnt*self.cols
        bot = max(round(ind_pos-width/2), 1)
        top = min(round(ind_pos+width/2), limit)
        return bot, max(top - bot, 1)

    def _paint_body(self) -> int:
        # Paint at most one screenful, so cost tracks the terminal, not the document.
        view = min(self.scroll_view_size, self.rows - self.body_base)
        if view <= 0:
            return 0
        pad = cast(CursesSurface, self.body.pad)
        pad.erase()
        for row in range(view):
            pos = self.scroll_pos + row
            if pos < 0 or pos >= self.body.row_cnt or pos >= len(self.body.texts):
                continue
            # Only the picked row is highlighted; abutted rows stay visible but plain.
            picked = self.pick_mode and pos == self.pick_pos
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
            cast(CursesSurface, self.body.pad).noutrefresh(
                0, 0,
                self.body_base, indent, self.rows-1, self.cols-1
            )

        last_row = self._paint_head()
        if last_row >= 0:
            cast(CursesSurface, self.head.pad).noutrefresh(
                0, 0,
                0, indent, last_row, self.cols-1
            )


    def answer(self, prompt: str = 'Type string [then Enter]', seed: str = '', width: int = 80,
               height: int = 5, esc_abort: bool | None = None, prompt_attr: int | None = None,
               hint: str = '') -> str | None:
        """Blocking single-line text dialog.

        Returns the submitted string, or `None` when the user aborts, and raises
        `TerminalTooSmallError` when the dialog cannot fit.  *hint* is drawn on
        the bottom border left of the submit/abort text.
        """
        dialog_abort = self._resolve_abort_mode(esc_abort)

        # Track the timeout ourselves; curses.window has no gettimeout().
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)

        input_string = list(seed)
        cursor_pos = len(input_string)
        v_scroll_top = 0
        last_esc_time = None  # For ESC-ESC tracking

        if not self._dialog_geometry(height, width)[0]:
            # None means the user aborted; a small terminal is a different failure.
            raise self._too_small_error(height)

        # A longer timeout lets recovery redraw every 5 s without flicker.
        self._set_scr_timeout(5000)

        deadline = time.monotonic() + ConsoleWindow.render_retry_seconds

        # DEBUG: Set to True to show redraw indicator in upper-left corner
        debug_show_redraws = self.opts.answer_show_redraws
        debug_redraw_toggle = False

        try:
            while True:
                # Keep geometry current across retries.
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

                    # Wrapping, padding and the cursor are measured in display
                    # cells, so wide input stays aligned.
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
                    # Recover within the budget, then let the error escape.
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(ConsoleWindow.render_retry_interval)
                    self._recover_from_resize()
                    continue
        finally:
            # Every exit path -- submit, abort, raise -- restores the caller's timeout.
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
        # Poll even when getch() timed out: not every terminal delivers KEY_RESIZE,
        # and the caller retries with these dimensions.
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
                for c in range(col0 + 1, c2):
                    scr.addch(r, c, curses.ACS_HLINE)
            if row0 < r < row9:
                scr.addch(r, col0, curses.ACS_VLINE)
                scr.addch(r, c2, curses.ACS_VLINE)
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

            self.scr.addstr(row0 + 1 + r, col0 + 1, ' ' * text_win_width)

            if current_wrapped_line_idx >= total_wrapped_lines:
                continue

            start_char_idx, end_char_idx = wrapped_ranges[current_wrapped_line_idx]
            raw_wrapped_line = input_text[start_char_idx:end_char_idx]

            self.scr.addstr(row0 + 1 + r, col0 + 1,
                            textwidth.ljust(raw_wrapped_line, text_win_width))

            # --- SCROLL INDICATOR LOGIC (cursor line only) ---
            if current_wrapped_line_idx == wrapped_line_idx:
                self._draw_dialog_cursor(row0, col0, r, text_win_width,
                                         cursor_cell, input_text, cursor_pos)

        # Corner markers: content above the window, and below it.
        if v_scroll_top > 0:
            self.scr.addch(row0 + 1, col0, '◀', curses.A_BOLD)
        if (v_scroll_top + height) < total_wrapped_lines:
            self.scr.addch(row9 - 1, col0 + text_win_width + 1, '▶', curses.A_BOLD)

    def _draw_dialog_cursor(self, row0: int, col0: int, r: int, text_win_width: int,
                            cursor_cell: int, input_text: str, cursor_pos: int) -> None:
        # Vertical border markers; hard wrapping needs no horizontal marker.
        self.scr.addch(row0 + 1 + r, col0, curses.ACS_VLINE)
        self.scr.addch(row0 + 1 + r, col0 + text_win_width + 1, curses.ACS_VLINE)

        char_at_cursor = input_text[cursor_pos] if cursor_pos < len(input_text) else " "
        self.scr.addstr(row0 + 1 + r, col0 + 1 + cursor_cell,
                        char_at_cursor, curses.A_REVERSE)
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
            # The hint fills the room left of the submit/abort text.
            self.scr.addstr(row9, col0 + 1,
                            textwidth.truncate(hint, ending_col - (col0 + 1)))
        self.scr.addstr(row9, ending_col, ending)

    # Simple single-keystroke cursor moves: key -> f(cursor_pos, text_len).
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
        if self.opts.dialog_return == 'ENTER' and key in (10, 13):
            return cursor_pos, last_esc_time, 'submit'
        if self.opts.dialog_return == 'TAB' and key == 9:
            return cursor_pos, last_esc_time, 'submit'

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

        Ordinary frames are fully repainted and diffed by `doupdate()`.
        """
        scr = getattr(self, 'scr', None)
        if scr is not None:
            scr.clear()

    def _recover_from_resize(self) -> None:
        """Discard queued input and adopt the new screen geometry.

        Draining covers all queued keys, because curses has no push-back API
        that could replay them safely.
        """
        self._clear_surface()
        self._backend.update_lines_cols()
        self.rows, self.cols = self.scr.getmaxyx()
        # Drain pending events so the resize loop cannot spin.
        self.scr.nodelay(True)  # Make getch() non-blocking
        while True:
            if self.scr.getch() == -1:  # No more keys in queue
                break
        self.scr.nodelay(False)  # Restore blocking mode


    def status(self, text: str = '', level: str = 'info',
               timeout: float | None = None,
               attr: int | None = None) -> bool:
        """Declare a one-line status message for the separator row.

        Painted by the next `render()`/`prompt()`, never taking over the screen.
        *level* picks a `STATUS_LEVELS` attribute; *timeout* expires lazily at
        draw time.  Returns False (and warns once) when no separator row exists;
        an empty *text* clears the message.
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
        """Remove any current status message (equivalent to `status('')`)."""
        return self.status('')

    @property
    def current_status(self) -> tuple[str, int | None]:
        """The stored status text and its attribute (`('', None)` if clear)."""
        return self._status_text, self._status_attr

    def flash(self, message: str = '', duration: float = 2.0) -> None:
        """Show a modal message box for `duration` seconds.

        Clears the screen and repaints afterwards; use `status` for a message
        that must leave the listing visible.
        """
        # Everything below draws from self.rows/self.cols, so refresh them.
        self._set_screen_dims()
        # Painted directly, so transliterate before the width math.
        message = glyphs.transliterate(message)

        if self.rows < 3 or self.cols < textwidth.string_width(message) + 4:
            return

        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)

        def draw_flash() -> None:
            msg_len = min(textwidth.string_width(message), self.cols - 4)
            row = self.rows // 2
            col = max((self.cols - msg_len - 2) // 2, 0)

            # Registered glyphs give ASCII-mode terminals a '+---+' box.
            horizontal = glyphs.get('box_h') * msg_len
            vertical = glyphs.get('box_v')
            top = glyphs.get('box_tl') + horizontal + glyphs.get('box_tr')
            middle = vertical + textwidth.ljust(message, msg_len) + vertical
            bottom = glyphs.get('box_bl') + horizontal + glyphs.get('box_br')
            self.scr.clear()
            try:
                self.scr.addstr(row - 1, col, top, curses.A_BOLD | curses.A_REVERSE)
                self.scr.addstr(row, col, middle, curses.A_BOLD | curses.A_REVERSE)
                self.scr.addstr(row + 1, col, bottom, curses.A_BOLD | curses.A_REVERSE)
            except curses.error:
                pass  # Ignore if terminal too small
            self.scr.noutrefresh()
            self._backend.doupdate()

        draw_flash()

        # Poll instead of sleeping: the wait is interruptible and resize-aware.
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
                # Any real key dismisses early, but is preserved for the app.
                self.pending_keys.add(key)
                break
        finally:
            self._set_scr_timeout(prev_timeout_ms)
            if self.flash_repaint:
                # A full pad repaint restores the cleared screen.
                self.render(redraw=True)


    def alert(self, message: str = '', title: str = 'ALERT',
              _height: int | None = None, _width: int | None = None) -> None:
        """Show a modal, scrollable message box until ENTER.

        Args:
            message: Body text; wrapped, and scrollable when it overflows.
            title: Box title; a title too wide for the border moves inside.
            _height: Content rows to cap the box at, or `None` for the full box.
            _width: Content columns to cap the box at, or `None` for the full box.
        """
        # Reachable with the usual navigation keys; ENTER acknowledges.  Everything
        # goes through self._backend/self.scr, so the dialog works headlessly.
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)
        try:
            self._set_scr_timeout(self.alert_poll_ms)
            while True:
                # A resize may have happened since the last render.
                self._set_screen_dims()

                layout = self._alert_layout(message, title, _height, _width)
                if layout is None:
                    return  # Terminal too small
                (box_title, footer_text, lines, box_height,
                 content_width, row0, row9, col0, col9) = layout

                visible_rows = max(box_height - 2, 1)  # subtract top/bottom borders
                max_scroll = max(len(lines) - visible_rows, 0)

                # One content pad; scrolling moves its viewport via pad.refresh().
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
                        # Notice a resize that arrived without KEY_RESIZE.
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
        # The scroll commands mirror those prompt() honors.
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
        # A 1-cell reverse-video border; _height/_width cap the content, and with
        # both None the box is the full terminal with a 1-cell margin.
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

        if message:
            lines.extend(textwidth.wrap(message, content_width))

        if _height is not None:
            box_height = min(max_box_height, max(3, _height + 2))
        else:
            box_height = max_box_height
        box_width = content_width + 2

        # Center the box; with the full box this leaves a 1-cell margin.
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
        # Both border cells are always repainted, so a marker cannot linger.
        up_glyph = glyphs.get('alert_up')
        down_glyph = glyphs.get('alert_down')
        top_char = up_glyph if scroll_top > 0 else curses.ACS_VLINE
        bottom_char = (down_glyph if scroll_top + visible_rows < content_height
                       else curses.ACS_VLINE)
        markers = (up_glyph, down_glyph)
        for row, char in ((row0 + 1, top_char), (row0 + visible_rows, bottom_char)):
            scr.addch(row, col0, char, curses.A_BOLD if char in markers else curses.A_NORMAL)

        scr.noutrefresh()
        # Pad row scroll_top maps to the box's first interior row.
        pad.refresh(scroll_top, 0, row0 + 1, col0 + 1, row0 + visible_rows, col9 - 1)

    def clear(self) -> None:
        """Reset the current screen's content for a new pass.

        Prefer `Screen.clear()`, which also adopts the screen.  Pick/scroll
        position survives, because it describes where the user is.
        """
        self._view.reset()

    # --- prompt(): key intake, special keys, app passthrough, navigation ------
    #
    # Read a key, classify it, then act; the helpers stay small for C901.

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
            # A timeout also polls for a resize that arrived without KEY_RESIZE.
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
        # Sync curses' cached LINES/COLS before reading the size.
        self._backend.update_lines_cols()
        self._set_screen_dims()
        if not self._check_min_size() and 27 in self.handled_keys:
            return 27
        return None

    def _record_demo_key(self, key: int) -> None:
        # Taken navigation keys are app-owned, so demo mode highlights them too.
        if self.opts.demo_mode and key not in self.opts.nav_keys:
            self.last_demo_key = self._format_key_for_demo(key)
            self._demo_key_at = time.monotonic()

    def _clear_demo_indicator(self) -> None:
        if self.opts.demo_mode:
            self.last_demo_key = ''
            self._demo_key_at = None

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
            return True, key
        if key in self.opts.nav_keys:
            self._clear_demo_indicator()
        return False, None

    def _navigation_target(self, key: int) -> int | None:
        """Map a navigation key to the row it asks for, or None if it is not one."""
        # This guard must precede the moves table: the table is what dispatches.
        if key in self.opts.taken_nav_keys:
            return None
        pos = self.pick_pos if self.pick_mode else self.scroll_pos
        half = self.scroll_view_size // 2
        # 0/HOME and $/END select the first/last pickable row in pick mode.
        moves: dict[int, Callable[[], int]] = {
            ord('k'): lambda: pos - 1,
            curses.KEY_UP: lambda: pos - 1,
            ord('j'): lambda: pos + 1,
            curses.KEY_DOWN: lambda: pos + 1,
            _CTRL_PAGE_UP: lambda: pos - self.scroll_view_size,
            curses.KEY_PPAGE: lambda: pos - self.scroll_view_size,
            _CTRL_HALF_UP: lambda: pos - half,
            _CTRL_HALF_DOWN: lambda: pos + half,
            _CTRL_PAGE_DOWN: lambda: pos + self.scroll_view_size,
            curses.KEY_NPAGE: lambda: pos + self.scroll_view_size,
            ord('0'): self._first_pickable,
            curses.KEY_HOME: self._first_pickable,
            ord('$'): self._last_pickable,
            curses.KEY_END: self._last_pickable,
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
        max_attempts = self.body.row_cnt + 1
        while self._in_body(pos) and not self._is_pickable(pos) and attempts < max_attempts:
            pos += direction
            attempts += 1
        exhausted = not self._in_body(pos) or attempts >= max_attempts
        return pos, exhausted

    def _decor_scroll_adjustment(self, was_pos: int, target: int, direction: int) -> int:
        """Scroll by the raw move when a DECOR block blocks the pick.

        Without this, j/k, the page keys and HOME/END would stall on the last
        pickable row instead of reaching leading or trailing DECOR.
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

    def _resolve_prompt_move(self, target: int, was_pos: int,
                             snap_nearest: bool = False) -> tuple[int, int]:
        """Apply pickability rules to a requested move.

        *snap_nearest* is for the jump keys, which land on the nearest pickable
        row.  Returns the target row and any DECOR-scroll adjustment.
        """
        if not self.pick_mode or target == was_pos:
            return target, 0
        if snap_nearest and not self._is_pickable(target):
            found = geometry.find_pickable(
                self._is_pickable, self.body.row_cnt, target)
            if found >= 0:
                return found, 0
        direction = 1 if target > was_pos else -1
        pos, exhausted = self._skip_to_pickable(target, direction)
        if not exhausted:
            return pos, 0
        return was_pos, self._decor_scroll_adjustment(was_pos, target, direction)

    def _apply_pick_scroll(self, pos: int, was_pos: int, scroll_adjustment: int) -> None:
        # Reveal DECOR by scrolling; latch free-scroll only when the view moves.
        if scroll_adjustment != 0 and pos == was_pos:
            new_scroll = max(0, min(self.scroll_pos + scroll_adjustment,
                                    self.max_scroll_pos))
            if new_scroll != self.scroll_pos:
                self.free_scroll = True
            self.scroll_pos = new_scroll
        elif pos != was_pos:
            # A genuine pick move re-synchronizes the view with the pick.
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
        pos, scroll_adjustment = self._resolve_prompt_move(
            target, was_pos, snap_nearest=key in _JUMP_TO_PICKABLE_KEYS)
        self._apply_prompt_move(pos, was_pos, scroll_adjustment)
        return self._finish_prompt_move(key, pos, was_pos, scroll_adjustment)

    def prompt(self, seconds: float = 1.0) -> int | None:
        """Wait up to *seconds* for a key this window represents; None on timeout."""
        # The first prompt applies the one-time content fit; later ones re-check.
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
