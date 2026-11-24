"""Curses and headless render backends behind one protocol."""

from __future__ import annotations

import curses
from collections import deque
from collections.abc import Callable
from typing import Protocol


class Surface(Protocol):
    def getmaxyx(self) -> tuple[int, int]:
        ...

    def timeout(self, ms: int) -> None:
        ...

    def keypad(self, flag: bool) -> None:
        ...


class CursesSurface(Surface, Protocol):
    def getyx(self) -> tuple[int, int]:
        ...

    def clear(self) -> None:
        ...

    def erase(self) -> None:
        ...

    def addstr(self, *args: object) -> None:
        ...

    def addch(self, *args: object) -> None:
        ...

    def insstr(self, *args: object) -> None:
        ...

    def vline(self, *args: object) -> None:
        ...

    def hline(self, *args: object) -> None:
        ...

    def border(self, *args: object) -> None:
        ...

    def move(self, y: int, x: int) -> None:
        ...

    def bkgd(self, *args: object) -> None:
        ...

    def noutrefresh(self, *args: object) -> None:
        ...

    def refresh(self, *args: object) -> None:
        ...

    def redrawwin(self) -> None:
        ...

    def getch(self) -> int:
        ...

    def nodelay(self, flag: bool) -> None:
        ...


class RenderBackend(Protocol):
    def start(self, timeout_ms: int) -> Surface:
        ...

    def newpad(self, rows: int, cols: int) -> Surface:
        ...

    def doupdate(self) -> None:
        ...

    def curs_set(self, visibility: int) -> None:
        ...

    def update_lines_cols(self) -> None:
        ...

    def is_term_resized(self, rows: int, cols: int) -> bool:
        ...

    def has_colors(self) -> bool:
        ...

    def colors(self) -> int:
        """Number of colors the terminal supports, or 0."""

    def color_pairs(self) -> int:
        """Size of the terminal's color-pair table."""

    def start_color(self) -> None:
        ...

    def use_default_colors(self) -> bool:
        """Enable `-1` as "terminal default"; return whether it worked."""

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        ...

    def color_pair(self, pair: int) -> int:
        ...

    def stop(self, scr: Surface | None) -> None:
        ...


class CursesBackend:
    # COLORS/COLOR_PAIRS exist only after start_color(), so capture them there.
    _FALLBACK_COLOR_PAIRS = 64  # the ncurses floor for a color terminal

    def __init__(self) -> None:
        self._colors = 0
        self._color_pairs = 0
        self._default_colors = False

    def start(self, timeout_ms: int) -> Surface:
        scr = curses.initscr()
        curses.set_escdelay(25)
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        scr.keypad(True)
        scr.timeout(timeout_ms)
        scr.clear()
        return scr

    def newpad(self, rows: int, cols: int) -> Surface:
        return curses.newpad(rows, cols)

    def doupdate(self) -> None:
        curses.doupdate()

    def curs_set(self, visibility: int) -> None:
        curses.curs_set(visibility)

    def update_lines_cols(self) -> None:
        curses.update_lines_cols()

    def is_term_resized(self, rows: int, cols: int) -> bool:
        return bool(curses.is_term_resized(rows, cols))

    def has_colors(self) -> bool:
        try:
            return bool(curses.has_colors())
        except curses.error:  # curses not initialized yet
            return False

    def colors(self) -> int:
        if self._colors > 0:
            return self._colors
        try:
            return max(int(getattr(curses, 'COLORS', 0)), 0)
        except (AttributeError, curses.error, TypeError, ValueError):
            return 0

    def color_pairs(self) -> int:
        if self._color_pairs > 0:
            return self._color_pairs
        try:
            pairs = max(int(getattr(curses, 'COLOR_PAIRS', 0)), 0)
        except (AttributeError, curses.error, TypeError, ValueError):
            pairs = 0
        if pairs > 0:
            return pairs
        # Reporting 0 would make a theme install silently do nothing.
        return self._FALLBACK_COLOR_PAIRS if self.colors() > 0 else 0

    def start_color(self) -> None:
        try:
            curses.start_color()
        except curses.error:
            # No color support after all: degrade to monochrome.
            self._colors = 0
            self._color_pairs = 0
            return
        try:
            self._colors = max(int(getattr(curses, 'COLORS', 0)), 0)
        except (AttributeError, curses.error, TypeError, ValueError):
            self._colors = 0
        try:
            self._color_pairs = max(int(getattr(curses, 'COLOR_PAIRS', 0)), 0)
        except (AttributeError, curses.error, TypeError, ValueError):
            self._color_pairs = 0

    def use_default_colors(self) -> bool:
        try:
            curses.use_default_colors()
        except curses.error:
            # Some terminals reject -1; the resolver substitutes concrete defaults.
            self._default_colors = False
        else:
            self._default_colors = True
        return self._default_colors

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        curses.init_pair(pair, fg, bg)

    def color_pair(self, pair: int) -> int:
        return int(curses.color_pair(pair))

    def stop(self, scr: Surface | None) -> None:
        if scr is None:
            return
        curses.nocbreak()
        curses.echo()
        scr.keypad(False)
        try:
            curses.curs_set(1)  # start() hid it; restore the hardware cursor
        except curses.error:  # some terminals cannot show the cursor
            pass
        curses.endwin()


class _NoopSurface:
    # Bound the call history: headless runs can draw for hours.
    MAX_CALLS = 1000

    def __init__(self, rows: int = 24, cols: int = 80) -> None:
        self._rows = rows
        self._cols = cols
        self.calls: deque[tuple[str, tuple[object, ...], dict[str, object]]] = deque(
            maxlen=self.MAX_CALLS)
        # Keys handed back by getch(), in order, letting tests drive the loops.
        self.keys: list[int] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        def _noop(*args: object, **kwargs: object) -> object:
            self.calls.append((name, args, kwargs))
            if name == 'getmaxyx':
                return (self._rows, self._cols)
            if name == 'getyx':
                return (0, 0)
            if name == 'get_wch':
                return -1
            return None
        return _noop

    def getch(self) -> int:
        self.calls.append(('getch', (), {}))
        return self.keys.pop(0) if self.keys else -1

    def queue_keys(self, *keys: int) -> None:
        self.keys.extend(keys)

    def getmaxyx(self) -> tuple[int, int]:
        return (self._rows, self._cols)

    def timeout(self, ms: int) -> None:
        self.calls.append(('timeout', (ms,), {}))

    def keypad(self, flag: bool) -> None:
        self.calls.append(('keypad', (flag,), {}))

    def calls_named(self, name: str) -> list[tuple[str, tuple[object, ...], dict[str, object]]]:
        return [c for c in self.calls if c[0] == name]


class HeadlessBackend:
    def __init__(self, rows: int = 24, cols: int = 80,
                 colors: bool | int = False,
                 color_pairs: int | None = None,
                 default_colors: bool = True) -> None:
        self.rows = rows
        self.cols = cols
        self.screen = _NoopSurface(rows, cols)
        self.pads: list[_NoopSurface] = []
        self.stopped = False
        # A bool means a 256-color terminal (or none); an int is the exact count.
        if isinstance(colors, bool):
            self._colors = 256 if colors else 0
        else:
            self._colors = max(int(colors), 0)
        if color_pairs is None:
            color_pairs = 64 if 0 < self._colors <= 16 else 256
        self._color_pairs = max(int(color_pairs), 0)
        self._default_colors = bool(default_colors)
        self.doupdates = 0
        self.curs_set_calls: list[int] = []
        self.update_lines_cols_calls = 0
        self.start_color_calls = 0
        self.use_default_colors_calls = 0
        self.init_pair_calls: list[tuple[int, int, int]] = []
        self.color_pair_calls: list[int] = []

    def start(self, timeout_ms: int) -> Surface:
        self.screen.timeout(timeout_ms)
        self.stopped = False
        return self.screen

    def newpad(self, rows: int, cols: int) -> Surface:
        pad = _NoopSurface(rows, cols)
        self.pads.append(pad)
        return pad

    def doupdate(self) -> None:
        self.doupdates += 1

    def curs_set(self, visibility: int) -> None:
        self.curs_set_calls.append(visibility)

    def update_lines_cols(self) -> None:
        self.update_lines_cols_calls += 1

    def is_term_resized(self, rows: int, cols: int) -> bool:
        # Headless screens have fixed geometry.
        return False

    def queue_keys(self, *keys: int) -> None:
        self.screen.queue_keys(*keys)

    def has_colors(self) -> bool:
        return self._colors > 0

    def colors(self) -> int:
        return self._colors

    def color_pairs(self) -> int:
        return self._color_pairs

    def start_color(self) -> None:
        self.start_color_calls += 1

    def use_default_colors(self) -> bool:
        self.use_default_colors_calls += 1
        return self._default_colors

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        self.init_pair_calls.append((pair, fg, bg))

    def color_pair(self, pair: int) -> int:
        self.color_pair_calls.append(pair)
        # Same encoding as curses: the pair id in the attribute's high bits.
        return pair << 8

    def stop(self, scr: Surface | None) -> None:
        # Nothing to tear down; the argument mirrors `CursesBackend.stop`.
        self.stopped = True
