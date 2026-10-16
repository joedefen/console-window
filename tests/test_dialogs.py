import pytest

import console_window.window as window_mod
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow

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


def test_answer_restores_previous_timeout_on_submit(monkeypatch):
    monkeypatch.setattr(window_mod.curses, 'doupdate', lambda: None)
    monkeypatch.setattr(window_mod.curses, 'curs_set', lambda *args: None)

    scr = FakeScreen(rows=24, cols=80, keys=[10])  # ENTER submits
    win = make_window(scr)
    win._scr_timeout_ms = 250  # non-default timeout in effect before the call

    assert win.answer() == ''

    # Dialog installs its 5000ms refresh timeout, then restores the prior value
    # rather than the class default (ConsoleWindow.timeout_ms).
    assert scr.timeouts == [5000, 250]
    assert win._scr_timeout_ms == 250


def test_answer_restores_previous_timeout_on_esc(monkeypatch):
    monkeypatch.setattr(window_mod.curses, 'doupdate', lambda: None)
    monkeypatch.setattr(window_mod.curses, 'curs_set', lambda *args: None)

    scr = FakeScreen(rows=24, cols=80, keys=[27])  # ESC aborts
    win = make_window(scr)
    win._scr_timeout_ms = 111

    assert win.answer() is None
    assert scr.timeouts == [5000, 111]
    assert win._scr_timeout_ms == 111


def test_answer_leaves_timeout_untouched_when_terminal_too_small():
    scr = FakeScreen(rows=5, cols=10)  # below opts.min_cols_rows (70, 20)
    win = make_window(scr)
    win._scr_timeout_ms = 999

    assert win.answer() is None
    assert scr.timeouts == []
    assert win._scr_timeout_ms == 999

# --- alert() dimension refresh ---------------------------------------------

def test_alert_refreshes_dimensions_after_resize(monkeypatch):
    # rectangle() is the only helper that needs a live terminal (curses.ACS_*).
    monkeypatch.setattr(window_mod, 'rectangle', lambda *a, **k: None)
    monkeypatch.setattr(window_mod.curses, 'is_term_resized', lambda rows, cols: False)

    # Live screen is 24x100, but the cached dims are stale (a resize happened).
    scr = FakeScreen(rows=24, cols=100, keys=[10])  # ENTER acknowledges
    win = make_window(scr, rows=3, cols=5)

    win.alert(message='hello', title='T')

    assert (win.rows, win.cols) == (24, 100)
