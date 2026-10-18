import curses

import pytest

import console_window.window as window_mod
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow, TerminalTooSmallError

# ``curses.ACS_*`` attributes only exist once curses has been initialized (i.e.
# after ``initscr()``).  Provide stand-ins so the drawing code can run headless.
_ACS_STANDINS = {
    'ACS_HLINE': '-',
    'ACS_VLINE': '|',
    'ACS_ULCORNER': '+',
    'ACS_URCORNER': '+',
    'ACS_LLCORNER': '+',
    'ACS_LRCORNER': '+',
}


@pytest.fixture(autouse=True)


def _provide_acs_constants(monkeypatch):
    for name, value in _ACS_STANDINS.items():
        if not hasattr(window_mod.curses, name):
            monkeypatch.setattr(window_mod.curses, name, value, raising=False)


class FakeScreen:
    def __init__(self, rows=24, cols=80, keys=()):
        self._rows = rows
        self._cols = cols
        self._keys = list(keys)
        self.timeouts = []

    def getmaxyx(self):
        return (self._rows, self._cols)

    def timeout(self, ms):
        self.timeouts.append(ms)

    def getch(self):
        return self._keys.pop(0) if self._keys else -1

    # no-op drawing surface
    def clear(self): pass
    def border(self, *args, **kwargs): pass
    def addch(self, *args, **kwargs): pass
    def addstr(self, *args, **kwargs): pass
    def insstr(self, *args, **kwargs): pass
    def move(self, *args, **kwargs): pass
    def noutrefresh(self): pass
    def refresh(self): pass


def make_window(scr, rows=None, cols=None, **opts_kwargs):
    win = object.__new__(ConsoleWindow)
    win.scr = scr
    # alert()/answer() draw through the backend seam now; give the bare instance
    # a headless one so no curses.newpad()/newwin() is required (AUDIT.md §3.3).
    win._backend = HeadlessBackend(scr._rows, scr._cols)
    win.opts = ConsoleWindowOpts(**opts_kwargs)
    win.rows = scr._rows if rows is None else rows
    win.cols = scr._cols if cols is None else cols
    return win

# --- answer() timeout restoration ------------------------------------------

def test_set_scr_timeout_records_and_delegates():
    scr = FakeScreen()
    win = make_window(scr)
    win._set_scr_timeout(456)
    assert scr.timeouts == [456]
    assert win._scr_timeout_ms == 456


def test_answer_restores_previous_timeout_on_submit():
    scr = FakeScreen(rows=24, cols=80, keys=[10])  # ENTER submits
    win = make_window(scr)
    win._scr_timeout_ms = 250  # non-default timeout in effect before the call

    assert win.answer() == ''

    # Dialog installs its 5000ms refresh timeout, then restores the prior value
    # rather than the class default (ConsoleWindow.timeout_ms).
    assert scr.timeouts == [5000, 250]
    assert win._scr_timeout_ms == 250
    # doupdate()/curs_set() now go through the backend, not global curses.
    assert win._backend.doupdates >= 1
    assert 0 in win._backend.curs_set_calls


def test_answer_restores_previous_timeout_on_esc():
    scr = FakeScreen(rows=24, cols=80, keys=[27])  # ESC aborts
    win = make_window(scr)
    win._scr_timeout_ms = 111

    assert win.answer() is None
    assert scr.timeouts == [5000, 111]
    assert win._scr_timeout_ms == 111


def test_answer_raises_when_terminal_too_small():
    scr = FakeScreen(rows=5, cols=10)  # below opts.min_cols_rows (70, 20)
    win = make_window(scr)
    win._scr_timeout_ms = 999

    with pytest.raises(TerminalTooSmallError) as excinfo:
        win.answer()

    err = excinfo.value
    assert (err.required_cols, err.required_rows) == (70, 20)
    assert (err.actual_cols, err.actual_rows) == (10, 5)
    assert 'need at least 70x20, have 10x5' in str(err)
    # No dialog loop started, so the caller's timeout is untouched.
    assert scr.timeouts == []
    assert win._scr_timeout_ms == 999


def test_answer_raises_after_curses_error_budget(monkeypatch):
    class RaisingScreen(FakeScreen):
        def clear(self):
            raise curses.error('boom')

    scr = RaisingScreen(rows=24, cols=80)
    win = make_window(scr)
    win._scr_timeout_ms = 321
    monkeypatch.setattr(ConsoleWindow, 'render_retry_seconds', 0.0)
    monkeypatch.setattr(ConsoleWindow, 'render_retry_interval', 0.0)
    win._recover_from_resize = lambda: None

    with pytest.raises(curses.error):
        win.answer()

    # The dialog timeout is restored even though answer() raised.
    assert scr.timeouts == [5000, 321]
    assert win._scr_timeout_ms == 321


def test_answer_raises_when_resize_never_fits(monkeypatch):
    scr = FakeScreen(rows=24, cols=80)
    win = make_window(scr)
    win._scr_timeout_ms = 444
    calls = {'n': 0}

    def geometry(height, width):
        calls['n'] += 1
        if calls['n'] == 1:
            return True, 1, 7, 1, 20
        win.rows, win.cols = 5, 10
        return False, 0, 0, 0, 0

    monkeypatch.setattr(win, '_dialog_geometry', geometry)
    monkeypatch.setattr(win, '_show_too_small_dialog', lambda height: False)
    monkeypatch.setattr(ConsoleWindow, 'render_retry_seconds', 0.0)

    with pytest.raises(TerminalTooSmallError) as excinfo:
        win.answer()

    assert (excinfo.value.actual_cols, excinfo.value.actual_rows) == (10, 5)
    assert scr.timeouts == [5000, 444]

# --- alert() dimension refresh ---------------------------------------------

def test_alert_refreshes_dimensions_after_resize(monkeypatch):
    # rectangle() is the only helper that needs a live terminal (curses.ACS_*).
    monkeypatch.setattr(window_mod, 'rectangle', lambda *a, **k: None)

    # Live screen is 24x100, but the cached dims are stale (a resize happened).
    scr = FakeScreen(rows=24, cols=100, keys=[10])  # ENTER acknowledges
    win = make_window(scr, rows=3, cols=5)

    win.alert(message='hello', title='T')

    assert (win.rows, win.cols) == (24, 100)
