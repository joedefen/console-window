from __future__ import annotations

import curses
from collections import deque
from typing import Callable, Protocol


class Surface(Protocol):
    def getmaxyx(self) -> tuple[int, int]:
        ...

    def timeout(self, ms: int) -> None:
        ...

    def keypad(self, flag: bool) -> None:
        ...


class CursesSurface(Surface, Protocol):
    # Full curses surface used by ConsoleWindow's drawing code.  It exists so
    # those calls can be type-checked without pretending the small Surface
    # protocol (the backend seam) covers addstr/border/insstr/...
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

    def start_color(self) -> None:
        ...

    def use_default_colors(self) -> None:
        ...

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        ...

    def color_pair(self, pair: int) -> int:
        ...

    def stop(self, scr: Surface | None) -> None:
        ...


class CursesBackend:
    def start(self, timeout_ms: int) -> Surface:
        scr = curses.initscr()
        curses.set_escdelay(25)  # Reduce ESC key delay from 1000ms to 25ms
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
        except curses.error:  # curses not initialised yet
            return False

    def start_color(self) -> None:
        curses.start_color()

    def use_default_colors(self) -> None:
        curses.use_default_colors()

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
    # Bound the call history: headless runs can draw for hours, and every call
    # would otherwise be retained forever just for test assertions.
    MAX_CALLS = 1000

    def __init__(self, rows: int = 24, cols: int = 80) -> None:
        self._rows = rows
        self._cols = cols
        self.calls: deque[tuple[str, tuple[object, ...], dict[str, object]]] = deque(
            maxlen=self.MAX_CALLS)
        # Ordered queue of key codes returned by getch().  It is empty by
        # default, so getch() reports "no key" (curses.ERR, -1) exactly as
        # before; tests push keys here to drive the interactive loops
        # (prompt/answer/navigation) without a TTY.
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
        # A real method (not the generic no-op) so queued keys are handed back
        # one call at a time instead of the constant -1.
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
    def __init__(self, rows: int = 24, cols: int = 80, colors: bool = False) -> None:
        self.rows = rows
        self.cols = cols
        self.screen = _NoopSurface(rows, cols)
        self.pads: list[_NoopSurface] = []
        self.stopped = False
        self._colors = colors
        # Process-global curses calls the window used to make directly are
        # recorded here instead, so the dialog/render paths are backend-driven
        # and observable headlessly.
        self.doupdates = 0
        self.curs_set_calls: list[int] = []
        self.update_lines_cols_calls = 0
        self.start_color_calls = 0
        self.use_default_colors_calls = 0
        self.init_pair_calls: list[tuple[int, int, int]] = []
        self.color_pair_calls: list[int] = []

    def start(self, timeout_ms: int) -> Surface:
        self.screen.timeout(timeout_ms)
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

    def is_term_resized(self, rows: int, cols: int) -> bool:  # pylint: disable=unused-argument
        # Headless screens have fixed geometry, so the size arguments exist only
        # to satisfy the RenderBackend protocol and are deliberately ignored.
        return False

    def queue_keys(self, *keys: int) -> None:
        # Queue curses key codes for the next getch() calls.  This is the seam
        # that lets the interactive core (prompt/answer/navigation) be exercised
        # headlessly.
        self.screen.queue_keys(*keys)

    def has_colors(self) -> bool:
        return self._colors

    def start_color(self) -> None:
        self.start_color_calls += 1

    def use_default_colors(self) -> None:
        self.use_default_colors_calls += 1

    def init_pair(self, pair: int, fg: int, bg: int) -> None:
        self.init_pair_calls.append((pair, fg, bg))

    def color_pair(self, pair: int) -> int:
        self.color_pair_calls.append(pair)
        # Same encoding as curses: the pair id in the attribute's high bits.
        return pair << 8

    def stop(self, scr: Surface | None) -> None:  # pylint: disable=unused-argument
        # Nothing to tear down; the argument mirrors the CursesBackend signature.
        self.stopped = True
