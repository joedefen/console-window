import curses

import pytest

import console_window.window as window_mod
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow, _textbox_edit_on_enter

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


class FakePad:
    def addstr(self, *args, **kwargs): pass
    def clear(self): pass
    def refresh(self, *args, **kwargs): pass


class FakeTextbox:
    def __init__(self, *args, **kwargs): pass

    def edit(self, validate=None):
        return ''


def make_window(scr, rows=None, cols=None, **opts_kwargs):
    win = object.__new__(ConsoleWindow)
    win.scr = scr
    win.opts = ConsoleWindowOpts(**opts_kwargs)
    win.rows = scr._rows if rows is None else rows
    win.cols = scr._cols if cols is None else cols
    return win

# --- the mod_key -> 7 Textbox sentinel -------------------------------------

def test_textbox_sentinel_maps_enter_to_seven():
    assert _textbox_edit_on_enter(10) == 7
    assert _textbox_edit_on_enter(curses.KEY_ENTER) == 7


def test_textbox_sentinel_passes_other_keys_through():
    for key in (ord('a'), 27, curses.KEY_BACKSPACE, 32, 126):
        assert _textbox_edit_on_enter(key) == key

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
    # Stub the pieces that need a real TTY.
    monkeypatch.setattr(window_mod.curses, 'newpad', lambda *a, **k: FakePad())
    monkeypatch.setattr(window_mod.curses, 'newwin', lambda *a, **k: FakeScreen())
    monkeypatch.setattr(window_mod.curses, 'curs_set', lambda *a: None)
    monkeypatch.setattr(window_mod, 'rectangle', lambda *a, **k: None)
    monkeypatch.setattr(window_mod, 'Textbox', FakeTextbox)

    # Live screen is 24x100, but the cached dims are stale (a resize happened).
    scr = FakeScreen(rows=24, cols=100)
    win = make_window(scr, rows=3, cols=5)

    win.alert(message='hello', title='T')

    assert (win.rows, win.cols) == (24, 100)
