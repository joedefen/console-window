"""Rendering backend abstraction for the :class:`ConsoleWindow` engine.

The engine used to create its terminal screen and pads with direct ``curses``
calls inside ``__init__``/``start_curses`` and stash the *one* live screen in
process-wide class attributes (``ConsoleWindow.static_scr`` /
``ConsoleWindow.static_win``).  Those singletons meant that (a) two
``ConsoleWindow`` instances could not coexist and (b) a window could not be
constructed at all without a real terminal — both of which blocked unit testing.

This module isolates everything the engine needs from a display — a main screen
plus off-screen pads — behind :class:`RenderBackend`, and ships two
implementations:

* :class:`CursesBackend` — the real terminal (the default).
* :class:`HeadlessBackend` — an in-memory, no-op backend for tests, so a
  ``ConsoleWindow`` can be built and rendered without a TTY and without touching
  process-global state.

See ``AUDIT.md`` §4.5.
"""

from __future__ import annotations

import curses
from typing import Callable, Protocol


class Surface(Protocol):
    """A curses screen or pad (real, or a headless stand-in)."""

    def getmaxyx(self) -> tuple[int, int]:
        """Return the surface size as ``(rows, cols)``."""
        ...

    def timeout(self, ms: int) -> None:
        """Set the blocking read timeout in milliseconds."""
        ...

    def keypad(self, flag: int) -> None:
        """Enable/disable keypad translation."""
        ...


class RenderBackend(Protocol):
    """The display surface the :class:`ConsoleWindow` engine depends on."""

    def start(self, timeout_ms: int) -> Surface:
        """Create and configure the main screen, returning it.

        :param timeout_ms: The blocking read timeout to install on the screen.
        """
        ...

    def newpad(self, rows: int, cols: int) -> Surface:
        """Create an off-screen pad of ``rows`` x ``cols`` cells."""
        ...

    def has_colors(self) -> bool:
        """Whether the display supports color (checked *after* :meth:`start`)."""
        ...

    def stop(self, scr: Surface | None) -> None:
        """Restore the terminal and release ``scr`` (may be ``None``)."""
        ...


class CursesBackend:
    """Default backend: a real curses terminal."""

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
    """A permissive no-op stand-in for a curses window/pad.

    Any method call is recorded in :attr:`calls` and returns a benign default.
    Unknown attributes resolve to a fresh no-op callable, so the engine can
    drive a headless surface without a bespoke fake per code path.
    """

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
        """Return the recorded calls whose method name is ``name``."""
        return [c for c in self.calls if c[0] == name]


class HeadlessBackend:
    """In-memory backend for tests — no terminal, no process-global state.

    :param rows: Reported screen height (``getmaxyx``).
    :param cols: Reported screen width (``getmaxyx``).
    :param colors: What :meth:`has_colors` should report.
    """

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
