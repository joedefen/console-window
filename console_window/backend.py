from __future__ import annotations

import curses
from typing import Callable, Protocol


class Surface(Protocol):
    def getmaxyx(self) -> tuple[int, int]:
        ...

    def timeout(self, ms: int) -> None:
        ...

    def keypad(self, flag: int) -> None:
        ...


class RenderBackend(Protocol):
    def start(self, timeout_ms: int) -> Surface:
        ...

    def newpad(self, rows: int, cols: int) -> Surface:
        ...

    def has_colors(self) -> bool:
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
        scr.keypad(1)
        scr.timeout(timeout_ms)
        scr.clear()
        return scr

    def newpad(self, rows: int, cols: int) -> Surface:
        return curses.newpad(rows, cols)

    def has_colors(self) -> bool:
        try:
            return bool(curses.has_colors())
        except curses.error:  # curses not initialised yet
            return False

    def stop(self, scr: Surface | None) -> None:
        if scr is None:
            return
        curses.nocbreak()
        curses.echo()
        scr.keypad(0)
        curses.endwin()


class _NoopSurface:
    def __init__(self, rows: int = 24, cols: int = 80) -> None:
        self._rows = rows
        self._cols = cols
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        def _noop(*args: object, **kwargs: object) -> object:
            self.calls.append((name, args, kwargs))
            if name == 'getmaxyx':
                return (self._rows, self._cols)
            if name == 'getyx':
                return (0, 0)
            if name in ('getch', 'get_wch'):
                return -1
            return None
        return _noop

    def getmaxyx(self) -> tuple[int, int]:
        return (self._rows, self._cols)

    def timeout(self, ms: int) -> None:
        self.calls.append(('timeout', (ms,), {}))

    def keypad(self, flag: int) -> None:
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

    def start(self, timeout_ms: int) -> Surface:
        self.screen.timeout(timeout_ms)
        return self.screen

    def newpad(self, rows: int, cols: int) -> Surface:
        pad = _NoopSurface(rows, cols)
        self.pads.append(pad)
        return pad

    def has_colors(self) -> bool:
        return self._colors

    def stop(self, scr: Surface | None) -> None:
        self.stopped = True
