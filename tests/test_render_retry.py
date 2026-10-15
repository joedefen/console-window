import curses
import time
from types import SimpleNamespace

import pytest

import console_window.window as window_mod
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


class FakeScreen:
    def __init__(self, rows=24, cols=80):
        self._rows = rows
        self._cols = cols

    def getmaxyx(self):
        return (self._rows, self._cols)

    def timeout(self, ms):  # pragma: no cover - not exercised here
        pass


def make_window(scr):
    win = object.__new__(ConsoleWindow)
    win.scr = scr
    win.opts = ConsoleWindowOpts()
    win.rows, win.cols = scr._rows, scr._cols
    # Attributes touched by render()'s diagnostic dump on failure.
    win.head = SimpleNamespace(row_cnt=0, view_cnt=0)
    win.body = SimpleNamespace(row_cnt=0)
    win.hor_line_cnt = 0
    win.scroll_pos = 0
    win.max_scroll_pos = 0
    win.pick_pos = 0
    win.last_pick_pos = -1
    win.pick_mode = False
    win.pick_size = 1
    return win


def test_persistent_error_aborts_within_wall_clock_budget(monkeypatch):
    monkeypatch.setattr(ConsoleWindow, 'render_retry_seconds', 0.05)
    monkeypatch.setattr(ConsoleWindow, 'render_retry_interval', 0.01)

    calls = {'n': 0}

    def boom(redraw=False):
        calls['n'] += 1
        raise curses.error('persistent')

    win = make_window(FakeScreen())
    win.render_once = boom  # instance attribute -> no ``self`` binding

    start = time.monotonic()
    with pytest.raises(curses.error):
        win.render()
    elapsed = time.monotonic() - start

    # Bounded by wall-clock, not the old fixed 128-iteration count (~20 s).
    assert elapsed < 1.0
    assert calls['n'] < 128
    assert calls['n'] >= 2  # at least one retry plus the final dump attempt


def test_transient_error_recovers_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(ConsoleWindow, 'render_retry_seconds', 1.0)
    monkeypatch.setattr(ConsoleWindow, 'render_retry_interval', 0.0)

    state = {'n': 0}

    def flaky(redraw=False):
        state['n'] += 1
        if state['n'] < 3:
            raise curses.error('transient resize')

    win = make_window(FakeScreen())
    win.render_once = flaky

    win.render()  # must not raise
    assert state['n'] == 3


def test_render_retry_budget_is_configurable():
    # The budget is a class-level knob, so apps can tune it.
    assert ConsoleWindow.render_retry_seconds > 0
    assert ConsoleWindow.render_retry_interval > 0
    assert window_mod.ConsoleWindow is ConsoleWindow
