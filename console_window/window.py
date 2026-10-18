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
import time
import warnings
import weakref
from collections.abc import Iterable
from curses.textpad import rectangle
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable, ClassVar, cast

from . import geometry, signals, textwidth
from .backend import CursesBackend, CursesSurface, RenderBackend
from .header import LABEL, PLAIN, SEARCH, HeaderLine, Span, parse_fancy_header
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .theme import Theme

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import Context

logger = logging.getLogger(__name__)

# Navigation help is stored as complete lines, not a dedented triple-quoted
# string: editing the indentation can no longer change what the help screen
# renders.  ``ConsoleWindow.nav_keys`` remains the joined string for callers
# that want the whole blurb at once.
NAV_KEY_LINES: tuple[str, ...] = (
    'Navigation:      H/M/L:      top/middle/end-of-page',
    '  k, UP:  up one row             0, HOME:  first row',
    'j, DOWN:  down one row           $, END:  last row',
    '  Ctrl-u:  half-page up     Ctrl-b, PPAGE:  page up',
    '  Ctrl-d:  half-page down     Ctrl-f, NPAGE:  page down',
)

# Control keys that drive the same movements as the page keys.  They live here
# rather than inside `prompt()` so the navigation map and the help text above
# cannot drift apart silently.
_CTRL_PAGE_UP, _CTRL_HALF_DOWN, _CTRL_PAGE_DOWN, _CTRL_HALF_UP = 2, 4, 6, 21

# Editing keys that passthrough mode hands to the application unchanged, in
# addition to printable characters, navigation keys and `handled_keys`.
_PASSTHROUGH_EDITING_KEYS = frozenset({
    curses.KEY_BACKSPACE, 127, 8, 263,  # backspace variants
    curses.KEY_LEFT, curses.KEY_RIGHT,
    curses.KEY_HOME, curses.KEY_END,
    1, 5,  # Ctrl-A, Ctrl-E
})

# Live ConsoleWindow instances, held by weak reference and keyed by creation
# order.  The registry keeps creation order (so ``primary_window()`` is
# deterministic) and never keeps a window alive.  It serves both models:
# singleton windows share one process screen, while per-instance windows own
# their own screen; the first successful construction latches which model this
# process uses, because mixing them would make teardown ambiguous.
_WINDOWS: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_WINDOW_IDS = itertools.count()

# None until the first ConsoleWindow is constructed.  The value is process-wide
# and deliberately never reset: ConsoleWindow(singleton=...) must agree on every
# construction or the assertion in __init__ fires.
_SINGLETON_MODE: bool | None = None

# ``atexit`` teardown is registered once for the whole process, not once per
# window, so creating multiple windows does not stack up duplicate handlers.
_ATEXIT_REGISTERED = False


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
    # answer() could not present its dialog because the terminal is below
    # opts.min_cols_rows or the requested box size.  This is deliberately a
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
    """

    def __get__(self, obj: ConsoleWindow | None,
                objtype: type[ConsoleWindow]) -> Callable[[], None]:
        def stop() -> None:
            if obj is None:
                objtype._stop_legacy()
            else:
                obj._stop_instance()
        return stop


class ConsoleWindow:
    stop_curses = _StopCurses()
    timeout_ms: int = 2000
    # Set by _register_window(); None once stop_curses() unregisters the window.
    _registry_key: int | None = None
    # render() retries transient curses errors within this wall-clock budget
    # (seconds) instead of a fixed iteration count, so a persistent error aborts
    # quickly rather than freezing the UI for ~20 s.
    render_retry_seconds: float = 2.0
    render_retry_interval: float = 0.16  # seconds to wait between retries
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
                head_rows=head_rows if head_rows is not None else 50,
                body_rows=body_rows if body_rows is not None else 200,
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

        # Configure SIGINT policy (Ctrl-C terminates, or is delivered as key 0x3).
        signals.set_ctrl_c_policy(self.opts.ctrl_c_terminates)
        self.ctrl_c_terminates = self.opts.ctrl_c_terminates

        self._backend: RenderBackend = backend if backend is not None else CursesBackend()
        # The backend seam's Surface protocol is deliberately small; the full
        # drawing API is described by CursesSurface, which is only a cast target
        # (curses.window and HeadlessBackend's no-op surface both satisfy it at
        # runtime).  This keeps addstr/border/insstr/... type-checked.
        if self.singleton and ConsoleWindow.static_scr is not None:
            # Singleton mode: every instance draws through the process screen
            # and the backend that owns it, even if a different backend was
            # passed to this constructor.
            self._backend = ConsoleWindow._static_backend or self._backend
            self.scr = ConsoleWindow.static_scr
        else:
            self.scr = self._start_curses()
            if self.singleton:
                ConsoleWindow.static_scr = self.scr
                ConsoleWindow._static_backend = self._backend
        # curses.window exposes no gettimeout(), so every place that sets a read
        # timeout records it here (via _set_scr_timeout).  This lets modal
        # dialogs such as answer() restore the timeout that was in effect before
        # they ran, instead of assuming the class default.
        self._scr_timeout_ms = ConsoleWindow.timeout_ms

        self.head = SimpleNamespace(
            pad=self._backend.newpad(self.opts.head_rows, self.opts.body_cols),
            rows=self.opts.head_rows,
            cols=self.opts.body_cols,
            row_cnt=0,  # no. head rows added
            texts = [],
            text_attrs = [],  # run-length encoded: [(attr, count), ...] per line
            contexts = [],  # Context object per line (or None)
            view_cnt=0,  # no. head rows viewable (NOT in body)
            rows_dropped=0,  # rows discarded because the pad was full (see _add)
        )
        self.body = SimpleNamespace(
            pad = self._backend.newpad(self.opts.body_rows, self.opts.body_cols),
            rows= self.opts.body_rows,
            cols= self.opts.body_cols,
            row_cnt = 0,
            texts = [],
            text_attrs = [],  # run-length encoded: [(attr, count), ...] per line
            contexts = [],  # Context object per line (or None)
            rows_dropped = 0,  # rows discarded because the pad was full (see _add)
        )

        # Apply theme background to pads
        if self._backend.has_colors():
            theme = Theme.THEMES.get(Theme.get_current(), Theme.THEMES['default'])
            if 'default_fg' in theme and 'default_bg' in theme:
                default_fg = theme['default_fg']
                default_bg = theme['default_bg']
                if default_fg != -1 or default_bg != -1:
                    self.head.pad.bkgd(' ', self._backend.color_pair(Theme.DEFAULT_BG))
                    self.body.pad.bkgd(' ', self._backend.color_pair(Theme.DEFAULT_BG))

        # Register this instance so theme broadcasts and process teardown reach
        # it.  Singleton mode also republishes the old ``static_win`` pointer.
        _register_window(self)
        if self.singleton:
            ConsoleWindow.static_win = self

        self.mod_pick = self.opts.mod_pick # call back to modify highlighted row
        self.hor_line_cnt = 1 if self.opts.head_line else 0 # no. h-lines in header
        self.scroll_pos = 0  # how far down into body are we?
        self.max_scroll_pos = 0
        self.pick_pos = 0 # in highlight mode, where are we?
        self.last_pick_pos = -1 # last highlighted position, or -1 for none
        # One-shot request to repaint every body row before drawing the pick.
        # Set when pick mode/size/range changes and consumed by highlight_picked().
        self._pick_clear_pending = False
        self.pick_mode = self.opts.pick_mode # whether in highlight mode
        self.pick_size = self.opts.pick_size # whether in highlight mode
        # True while the user has deliberately scrolled past the picked row (or
        # before it) so that non-pickable DECOR rows become viewable: in that
        # state the pick-visibility clamp in _adjust_scroll_for_abut() must not
        # drag the viewport back to pick_pos.  Cleared when navigation moves the
        # pick.  Without it, the trailing filler rows of the stress mode were
        # created but unreachable (the view snapped back to the last pickable
        # row every frame).
        self.free_scroll = False
        self.rows, self.cols = 0, 0
        self.body_cols, self.body_rows = self.opts.body_cols, self.opts.body_rows
        self.scroll_view_size = 0  # no. viewable lines of the body
        self.handled_keys = set(self.opts.keys) if isinstance(self.opts.keys, (set, list)) else set()
        self.pending_keys: set[int] = set()
        self.last_demo_key = ''  # Last key pressed in demo mode
        self.max_header_len = 0  # Max visible header length from previous render
        self.passthrough_mode = False  # When True, all printable keys pass through
        self.relax_handled_keys = self.opts.relax_handled_keys  # When True, pass non-nav keys without checking handled_keys
        self._set_screen_dims()
        self.calc()

    def set_handled_keys(self, keys: object) -> None:
        if hasattr(keys, 'keys'):
            # It's an OptionSpinner or similar object
            self.handled_keys = set(keys.keys) if keys.keys else set()
        elif isinstance(keys, (set, list)):
            self.handled_keys = set(keys)
        else:
            self.handled_keys = set()

    def set_demo_mode(self, enabled: bool | None) -> bool:
        if enabled is None: # toggle if not explicit
            self.opts.demo_mode = not (self.opts.demo_mode)
        else:
            self.opts.demo_mode = bool(enabled)
        if not self.opts.demo_mode:
            self.last_demo_key = ''
        return self.opts.demo_mode

    def _format_key_for_demo(self, key: int) -> str:
        # Special multi-character keys
        if key == 27:  # ESC
            return 'ESC'
        elif key == ord('\t'):
            return 'TAB'
        elif key == ord('\n') or key == curses.KEY_ENTER or key == 10 or key == 13:
            return 'ENT'
        elif key == ord(' '):
            return 'SPC'
        elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
            return 'BSP'
        elif key == curses.KEY_DC:
            return 'DEL'
        # Printable single character keys - center with spaces
        elif 32 < key < 127:
            return f' {chr(key)} '
        # Default for unrecognized keys
        else:
            return '???'

    def get_pad_width(self) -> int:
        return min(self.cols-1, self.body_cols)

    @property
    def rows_dropped(self) -> int:
        # Rows handed to add_body()/add_header() after that pad had filled up.
        # The pads are fixed-size (opts.body_rows/head_rows), so a caller that
        # adds more rows than that used to lose the excess in silence; this
        # counter, plus the one-shot warning in _add(), is how that is now
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

    def _set_screen_dims(self) -> bool:
        rows, cols = self.scr.getmaxyx()
        same = bool(rows == self.rows and cols == self.cols)
        self.rows, self.cols = rows, cols
        return same

    def _set_scr_timeout(self, ms: int) -> None:
        self._scr_timeout_ms = ms
        self.scr.timeout(ms)

    def _check_min_size(self) -> bool:
        min_cols, min_rows = self.opts.min_cols_rows

        while self.rows < min_rows or self.cols < min_cols:
            self.scr.clear()
            msg1 = f"Min size: {min_cols}x{min_rows}"
            msg2 = f"Current: {self.cols}x{self.rows}"
            try:
                self.scr.addstr(0, 0, msg1, curses.A_REVERSE)
                self.scr.addstr(1, 0, msg2, curses.A_REVERSE)
            except curses.error:
                pass  # Terminal too small even for message
            self.scr.refresh()

            # Wait for key
            key = self.scr.getch()
            if key == 27:  # ESC to abort
                return False
            if key == curses.KEY_RESIZE:
                self._backend.update_lines_cols()
                self._set_screen_dims()

        return True

    def _start_curses(self) -> CursesSurface:
        return self._init_screen(self._backend)

    @classmethod
    def start_curses(cls, backend: RenderBackend | None = None) -> CursesSurface:
        # Legacy class-level entry point: in singleton mode it shares the one
        # process screen rather than starting a second terminal session.
        if _SINGLETON_MODE and cls.static_scr is not None:
            return cls.static_scr
        screen_backend = backend if backend is not None else CursesBackend()
        scr = cls._init_screen(screen_backend)
        if _SINGLETON_MODE:
            cls.static_scr = scr
            cls._static_backend = screen_backend
        return scr

    @staticmethod
    def _init_screen(backend: RenderBackend) -> CursesSurface:
        _register_atexit()
        signals.setup_ctrl_c()
        scr = cast(CursesSurface, backend.start(ConsoleWindow.timeout_ms))

        # Initialize color support with theme.  Every colour call goes through
        # the backend, so a non-curses backend that reports colours can use it.
        if backend.has_colors():
            backend.start_color()
            backend.use_default_colors()  # Allow -1 for default terminal colors

            # Select theme from the Theme registry (single source of truth) or
            # fall back to the default.  No environment variable is involved:
            # Theme.get_current() is the one place the active theme lives.
            theme_name = Theme.get_current() or 'default'
            if theme_name not in Theme.THEMES:
                theme_name = 'default'
            Theme.set_active(theme_name)
            theme = Theme.THEMES[theme_name]

            # Set terminal background and foreground from theme
            if 'default_fg' in theme and 'default_bg' in theme:
                default_fg = theme['default_fg']
                default_bg = theme['default_bg']
                # Initialize pair 0 equivalent for default colors
                # Note: Can't change pair 0, so we set screen background directly
                if default_fg != -1 or default_bg != -1:
                    # Create a color pair for default colors and set screen background
                    backend.init_pair(Theme.DEFAULT_BG, default_fg, default_bg)
                    scr.bkgd(' ', backend.color_pair(Theme.DEFAULT_BG))

            # Initialize semantic color pairs based on selected theme.  The set is
            # the shared Theme.SEMANTIC_PAIRS, so startup and Theme.set() always
            # agree (it used to omit OLD_SUCCESS here).
            for color_id in Theme.SEMANTIC_PAIRS:
                if color_id in theme:
                    fg, bg = theme[color_id]
                    backend.init_pair(color_id, fg, bg)

        return scr

    def set_pick_mode(self, on: bool = True, pick_size: int = 1) -> None:
        was_on, was_size = self.pick_mode, self.pick_size
        self.pick_mode = bool(on)
        self.pick_size = max(pick_size, 1)
        if self.pick_mode and (not was_on or was_size != self.pick_size):
            self._pick_clear_pending = True

    def set_pick_range(self, start_col: int | None = None, end_col: int | None = None) -> None:
        if start_col is None or end_col is None:
            self.opts.pick_range = None
        else:
            self.opts.pick_range = [start_col, end_col]
        # Force redraw of pick line
        if self.pick_mode:
            self._pick_clear_pending = True

    def _stop_instance(self) -> None:
        """Stop this window (and, in singleton mode, the shared screen)."""
        if getattr(self, 'singleton', False):
            self._stop_singleton()
            return

        scr = getattr(self, 'scr', None)
        if scr is None:
            return
        try:
            backend = getattr(self, '_backend', None) or CursesBackend()
            backend.stop(scr)
        finally:
            self.scr = cast(CursesSurface, None)
            _unregister_window(self)
            signals.teardown_ctrl_c()

    @classmethod
    def _stop_legacy(cls) -> None:
        """The pre-2.0 ``ConsoleWindow.stop_curses()`` call."""
        assert _SINGLETON_MODE is not False, (
            'ConsoleWindow.stop_curses() without an instance is only valid '
            'in singleton mode; use win.stop_curses() or ConsoleWindow.stop_all()')
        win = cls.static_win
        if win is not None:
            win.stop_curses()

    @classmethod
    def _stop_singleton(cls) -> None:
        """Tear down the shared screen and mark every window stopped."""
        scr = ConsoleWindow.static_scr
        if scr is None:
            return
        backend = ConsoleWindow._static_backend or CursesBackend()
        windows = list(_WINDOWS.values())
        ConsoleWindow.static_scr = None
        ConsoleWindow.static_win = None
        ConsoleWindow._static_backend = None
        for win in windows:
            win.scr = cast(CursesSurface, None)
        try:
            backend.stop(scr)
        finally:
            for win in windows:
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
        self.head.view_cnt = min(self.rows - self.hor_line_cnt, self.head.row_cnt)
        self.scroll_view_size = self.rows - self.head.view_cnt - self.hor_line_cnt
        self.max_scroll_pos = max(self.body.row_cnt - self.scroll_view_size, 0)
        self.body_base = self.head.view_cnt + self.hor_line_cnt
        return not same

    def _add(self, ns: SimpleNamespace, text: str, attr: int | None = None,
             resume: bool = False, context: Context | None = None,
             *, is_body: bool = False) -> None:
        if ns.row_cnt < ns.rows:
            row = max(ns.row_cnt - (1 if resume else 0), 0)
            if attr is None:
                attr = curses.A_NORMAL
            # Apply stripping logic if needed
            if is_body and self.pick_mode and self.opts.strip_attrs_in_pick_mode:
                attr = curses.A_NORMAL

            if resume:
                _, x = ns.pad.getyx()
                cols = self.get_pad_width() - x
                if cols > 0:
                    actual_text = textwidth.truncate(text, cols)
                    ns.pad.addstr(actual_text, attr)
                    ns.texts[row] += actual_text
                    # Append to existing attrs list (counts are code points)
                    if row < len(ns.text_attrs):
                        ns.text_attrs[row].append((attr, len(actual_text)))
                    # Note: context not updated on resume
            else:
                # Truncate to the single "usable width" (get_pad_width), matching
                # the resume branch, draw() and highlight_picked() — not the raw
                # terminal width, which is one column wider and uncapped by the pad.
                actual_text = textwidth.truncate(text, self.get_pad_width())
                ns.pad.addstr(row, 0, actual_text, attr)
                ns.texts.append(actual_text)  # text only history
                ns.text_attrs.append([(attr, len(actual_text))])  # run-length encoded
                ns.contexts.append(context)  # Context metadata (or None)
                ns.row_cnt += 1
        else:
            self._warn_rows_dropped(ns, 'body' if is_body else 'head')

    def _warn_rows_dropped(self, ns: SimpleNamespace, which: str) -> None:
        # The pad is full, so this row is discarded (as it always was).  Counted
        # always, warned about once per fill episode -- clear() resets both, so
        # a bulk overflow produces exactly one message instead of one per row --
        # and never fatal: the app keeps running and can inspect
        # ConsoleWindow.rows_dropped.  A caller that would rather treat this as
        # an error can use the usual warnings machinery
        # (python -W error::UserWarning, or pytest's filterwarnings ini setting).
        ns.rows_dropped += 1
        if ns.rows_dropped != 1:
            return
        warnings.warn(
            f'console-window: the {which} pad is full ({ns.rows} rows), so '
            f'further {which} rows are being discarded.  Raise the '
            f'{which}_rows option (ConsoleWindowOpts({which}_rows=...)) or add '
            f'fewer rows per frame.',
            # warn() <- _warn_rows_dropped() <- _add() <- add_body()/add_header()
            # <- caller, so 4 is the application's own line.
            stacklevel=4,
        )

    def add_header(self, text: str, attr: int | None = None, resume: bool = False,
                   context: Context | None = None) -> None:
        self._add(self.head, text, attr, resume, context, is_body=False)

    def add_body(self, text: str, attr: int | None = None, resume: bool = False,
                 context: Context | None = None) -> None:
        self._add(self.body, text, attr, resume, context, is_body=True)

    def add_fancy_header(self, line: str | HeaderLine, mode: str = 'Underline',
                         search_pattern_attr: int | None = None) -> None:
        if isinstance(line, str):
            if mode == 'Off':
                # Legacy: no markup processing, add the raw line unchanged.
                self.add_header(line)
                return
            spans = parse_fancy_header(line)
        else:
            spans = list(line)
        self._emit_header_spans(spans, mode, search_pattern_attr)

    def add_header_line(self, header_line: HeaderLine | Iterable[Span],
                        mode: str = 'Underline',
                        search_pattern_attr: int | None = None) -> None:
        self._emit_header_spans(list(header_line), mode, search_pattern_attr)

    @staticmethod
    def _resolve_header_attr(role: str, mode: str,
                             search_pattern_attr: int | None) -> int | None:
        if mode == 'Off' or role == PLAIN:
            return None
        if role == LABEL:
            return curses.A_BOLD
        if role == SEARCH:
            if search_pattern_attr is not None:
                return search_pattern_attr
            return curses.A_BOLD | curses.A_REVERSE
        # KEY (and any unknown role) follows the mode's key styling.
        if mode == 'Underline':
            return curses.A_UNDERLINE | curses.A_BOLD
        return curses.A_REVERSE

    def _emit_header_spans(self, spans: Iterable[Span], mode: str,
                           search_pattern_attr: int | None = None) -> None:
        result_sections = [
            (span.text, self._resolve_header_attr(span.role, mode, search_pattern_attr))
            for span in spans
        ]

        # Calculate visible length (in display cells) of this header line
        visible_length = sum(textwidth.string_width(text) for text, attr in result_sections)

        # Check if this is the first header line
        is_first_header = (self.head.row_cnt == 0)

        # Add demo indicator to first header if demo mode is active
        if is_first_header and self.opts.demo_mode and self.last_demo_key:
            # Pad to max_header_len + 2 spaces
            padding_needed = max(0, self.max_header_len + 2 - visible_length)
            if padding_needed > 0:
                result_sections.append((' ' * padding_needed, None))
            # Add demo key in reverse video
            result_sections.append((self.last_demo_key, curses.A_REVERSE))

        # Now output the sections using add_header with resume
        for idx, (text, attr) in enumerate(result_sections):
            resume = bool(idx > 0)  # Resume for all but the first section
            self.add_header(text, attr=attr, resume=resume)

        # Track max header length for next render (excluding demo indicator)
        if visible_length > self.max_header_len:
            self.max_header_len = visible_length

    def draw(self, y: int, x: int, text: str | bytes, text_attr: int | None = None,
             width: int | None = None, leftpad: bool = False, header: bool = False) -> None:
        ns = self.head if header else self.body
        text_attr = text_attr if text_attr else curses.A_NORMAL
        if y < 0 or y >= ns.rows or x < 0 or x >= ns.cols:
            return # nada if out of bounds
        ns.row_cnt = max(ns.row_cnt, y+1)

        uni = text if isinstance(text, str) else text.decode('utf-8')

        if width is not None:
            width = min(width, self.get_pad_width() - x)
            if width <= 0:
                return
            # Pad/truncate to exactly `width` display cells (wide-char safe).
            uni = textwidth.rjust(uni, width) if leftpad else textwidth.ljust(uni, width)
            text = uni.encode('utf-8')
        else:
            text = uni.encode('utf-8')

        try:
            while y >= len(ns.texts):
                ns.texts.append('')
            existing = ns.texts[y]
            left = textwidth.ljust(textwidth.truncate(existing, x), x)
            right_start = textwidth.cell_to_index(existing, x + textwidth.string_width(uni))
            ns.texts[y] = left + uni + existing[right_start:]
            ns.pad.addstr(y, x, text, text_attr)
        except curses.error:
            # curses errors on drawing the last character on the screen; ignore
            pass


    def highlight_picked(self) -> None:
        if not self.pick_mode:
            return

        pos0, pos1 = self.last_pick_pos, self.pick_pos
        if self._pick_clear_pending:
            self._redraw_rows(range(self.body.row_cnt))
            self._pick_clear_pending = False
            # The full clear removed the old highlight even if the row did not
            # move, so force the normal repaint path below.
            pos0 = -1
        if pos0 != pos1:
            if 0 <= pos0 < self.body.row_cnt:
                self._redraw_rows(range(pos0, pos0 + self.pick_size))
            if 0 <= pos1 < self.body.row_cnt:
                self._draw_picked_rows(range(pos1, pos1 + self.pick_size))
                self.last_pick_pos = pos1

    def _body_text(self, pos: int) -> str:
        if pos >= len(self.body.texts):
            return ''
        return textwidth.truncate(self.body.texts[pos], self.cols)

    def _body_attrs(self, pos: int) -> list | None:
        return self.body.text_attrs[pos] if pos < len(self.body.text_attrs) else None

    def _redraw_rows(self, rows: Iterable[int]) -> None:
        for row_idx in rows:
            if row_idx < len(self.body.texts):
                text = textwidth.ljust(self._body_text(row_idx), self.get_pad_width())
                self._draw_line_with_attrs(self.body.pad, row_idx, 0, text,
                                           self._body_attrs(row_idx), extra_attr=None)

    def _draw_picked_rows(self, rows: Iterable[int]) -> None:
        for row_idx in rows:
            if row_idx < len(self.body.texts):
                text = self._body_text(row_idx)
                if self.mod_pick:
                    text = self.mod_pick(text)
                text = textwidth.ljust(text, self.get_pad_width())
                self._draw_line_with_attrs(self.body.pad, row_idx, 0, text,
                                           self._body_attrs(row_idx),
                                           extra_attr=self.opts.pick_attr,
                                           extra_attr_range=self.opts.pick_range)

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
                'pick_pos=%s last_pick_pos=%s pick_clear_pending=%s pick_mode=%s '
                'pick_size=%s rows=%s cols=%s',
                self.head.row_cnt, self.head.view_cnt, self.hor_line_cnt,
                self.body.row_cnt, self.scroll_pos, self.max_scroll_pos,
                self.pick_pos, self.last_pick_pos, self._pick_clear_pending,
                self.pick_mode, self.pick_size, self.rows, self.cols)
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

        if self.head.view_cnt < self.rows:
            self._draw_separator_and_indicator()

        # Instead of self.scr.refresh(), use pnoutrefresh/doupdate for efficiency.
        # The 'redrawwin' above handles the forced repaint, so we just call 'noutrefresh'.
        self.scr.noutrefresh()

        # --- 3. Pad Drawing (Body and Head) ---

        self._refresh_pads(indent)

        # --- 4. Final Update (Only one physical screen update) ---
        self._backend.doupdate()

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

    def _draw_separator_and_indicator(self) -> None:
        self.scr.hline(self.head.view_cnt, 0, curses.ACS_HLINE, self.cols)
        ind_pos = self._scroll_indicator_col()
        if ind_pos < 0:
            return
        bot, cnt = self._scroll_indicator_span(ind_pos)
        for idx in range(bot, bot+cnt):
            self.scr.addch(self.head.view_cnt, idx, curses.ACS_HLINE, curses.A_REVERSE)

    def _scroll_indicator_span(self, ind_pos: int) -> tuple[int, int]:
        if self.opts.single_cell_scroll_indicator or not 0 < ind_pos < self.cols-1:
            return ind_pos, 1
        # Proportional range indicator
        width = self.scroll_view_size/self.body.row_cnt*self.cols
        bot = max(round(ind_pos-width/2), 1)
        top = min(round(ind_pos+width/2), self.cols-1)
        return bot, max(top - bot, 1)

    def _refresh_pads(self, indent: int) -> None:
        if self.body_base < self.rows:
            if self.pick_mode:
                self.highlight_picked()

            self.body.pad.noutrefresh(
                self.scroll_pos, 0,
                self.body_base, indent, self.rows-1, self.cols-1
            )

        if self.rows > 0:
            last_row = min(self.head.view_cnt, self.rows)-1
            if last_row >= 0:
                self.head.pad.noutrefresh(
                    0, 0,
                    0, indent, last_row, self.cols-1
                )


    def answer(self, prompt: str = 'Type string [then Enter]', seed: str = '', width: int = 80,
               height: int = 5, esc_abort: bool | None = None, prompt_attr: int | None = None) -> str | None:
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

                    self._draw_dialog_footer(row9, col0, text_win_width, dialog_abort)
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
        min_cols, min_rows = self.opts.min_cols_rows
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
        if key == curses.KEY_RESIZE:
            self._backend.update_lines_cols()
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
                            dialog_abort: str | None) -> None:
        submit_key = self.opts.dialog_return
        abort = ''
        if dialog_abort == 'ESC':
            abort = ' or ESC to abort'
        elif dialog_abort == 'ESC-ESC':
            abort = ' or ESC-ESC to abort'
        ending = textwidth.truncate(f'{submit_key} to submit{abort}', text_win_width)
        self.scr.addstr(row9, col0 + 1 + text_win_width - textwidth.string_width(ending), ending)

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

    def _recover_from_resize(self) -> None:
        self.scr.clear()
        self._backend.update_lines_cols()
        self.rows, self.cols = self.scr.getmaxyx()
        # Drain any pending resize events to prevent infinite loop
        self.scr.nodelay(True)  # Make getch() non-blocking
        while True:
            if self.scr.getch() == -1:  # No more keys in queue
                break
        self.scr.nodelay(False)  # Restore blocking mode


    def flash(self, message: str = '', duration: float = 2.0) -> None:
        # Refresh cached dimensions: a resize may have happened since the last
        # render and everything below draws from self.rows/self.cols.
        self._set_screen_dims()

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

            self.scr.clear()
            try:
                # Top border
                self.scr.addstr(row - 1, col, '┌' + '─' * msg_len + '┐',
                                curses.A_BOLD | curses.A_REVERSE)
                # Message (padded to msg_len cells so the box stays aligned)
                self.scr.addstr(row, col, '│' + textwidth.ljust(message, msg_len) + '│',
                                curses.A_BOLD | curses.A_REVERSE)
                # Bottom border
                self.scr.addstr(row + 1, col, '└' + '─' * msg_len + '┘',
                                curses.A_BOLD | curses.A_REVERSE)
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
                                  row0, row9, col0, col9)

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
                                          row0, row9, col0, col9)
        finally:
            self._set_scr_timeout(prev_timeout_ms)

    @staticmethod
    def _alert_scroll_target(key: int, scroll_top: int, visible_rows: int,
                             max_scroll: int) -> int:
        # "vim"-style scroll commands, matching the navigation family prompt()
        # honours.  Any other key is not a scroll command and leaves the view put.
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
                     content_height: int, row0: int, row9: int,
                     col0: int, col9: int) -> None:
        scr = self.scr
        # Scroll affordances on the box's left border.  Both cells are always
        # repainted (marker or plain border) so a marker does not linger once
        # the viewport scrolls back to that edge.
        top_char = '▲' if scroll_top > 0 else curses.ACS_VLINE
        bottom_char = '▼' if scroll_top + visible_rows < content_height else curses.ACS_VLINE
        for row, char in ((row0 + 1, top_char), (row0 + visible_rows, bottom_char)):
            scr.addch(row, col0, char, curses.A_BOLD if char in ('▲', '▼') else curses.A_NORMAL)

        scr.noutrefresh()
        # Move the pad viewport: pad row scroll_top maps to the box's first
        # interior row, so content below the fold becomes reachable.
        pad.refresh(scroll_top, 0, row0 + 1, col0 + 1, row0 + visible_rows, col9 - 1)

    def clear(self) -> None:
        self.scr.clear()
        self.head.pad.clear()
        self.body.pad.clear()
        self.head.texts, self.body.texts, self.last_pick_pos = [], [], -1
        self._pick_clear_pending = False
        self.head.text_attrs, self.body.text_attrs = [], []
        self.head.contexts, self.body.contexts = [], []
        self.head.row_cnt = self.body.row_cnt = 0
        self.head.rows_dropped = self.body.rows_dropped = 0

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
            # Nothing was typed; keep waiting for input.
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
        self._set_screen_dims()
        if not self._check_min_size() and 27 in self.handled_keys:
            # User pressed ESC to abort during size check.
            return 27
        # Return to the caller so it can redraw at the new size.
        return None

    def _record_demo_key(self, key: int) -> None:
        if self.opts.demo_mode and key not in NAVIGATION_KEYS:
            self.last_demo_key = self._format_key_for_demo(key)

    def _clear_demo_indicator(self) -> None:
        if self.opts.demo_mode:
            self.last_demo_key = ''

    def _is_passthrough_key(self, key: int) -> bool:
        return (32 <= key <= 126 or key in _PASSTHROUGH_EDITING_KEYS
                or key in NAVIGATION_KEYS or key in self.handled_keys)

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
        if key in NAVIGATION_KEYS:
            self._clear_demo_indicator()
        return False, None

    def _navigation_target(self, key: int) -> int | None:
        """Map a navigation key to the row it asks for, or None if it is not one."""
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
