import curses

import pytest

import console_window.window as window_mod
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


class FakeScreen:
    def __init__(self, rows=24, cols=80, keys=()):
        self._rows = rows
        self._cols = cols
        self._keys = list(keys)
        self.timeouts = []
        self.clears = 0

    def getmaxyx(self):
        return (self._rows, self._cols)

    def timeout(self, ms):
        self.timeouts.append(ms)

    def getch(self):
        return self._keys.pop(0) if self._keys else -1

    # no-op drawing surface
    def clear(self):
        self.clears += 1

    def addstr(self, *args, **kwargs): pass
    def noutrefresh(self): pass
    def refresh(self): pass


def make_window(scr, **opts_kwargs):
    win = object.__new__(ConsoleWindow)
    win.scr = scr
    win.opts = ConsoleWindowOpts(**opts_kwargs)
    win.rows = scr._rows
    win.cols = scr._cols
    win.pending_keys = set()
    win._scr_timeout_ms = ConsoleWindow.timeout_ms
    win.rendered = []
    win.render = lambda redraw=False: win.rendered.append(redraw)
    return win


@pytest.fixture(autouse=True)


def _stub_curses(monkeypatch):
    monkeypatch.setattr(window_mod.curses, 'doupdate', lambda: None)
    monkeypatch.setattr(window_mod.curses, 'is_term_resized', lambda *a: False)

# --- non-destructive repaint + timeout bookkeeping --------------------------

def test_flash_repaints_and_restores_timeout():
    scr = FakeScreen(keys=[])
    win = make_window(scr)

    win.flash('hello', duration=0.0)

    # The underlying screen is repainted (forcing a full redraw) so no blank
    # screen is left behind, and the pre-flash timeout is restored.
    assert win.rendered == [True]
    assert scr.timeouts == [ConsoleWindow.flash_poll_ms, ConsoleWindow.timeout_ms]
    assert win.pending_keys == set()


def test_flash_repaint_can_be_disabled():
    scr = FakeScreen(keys=[])
    win = make_window(scr)
    win.flash_repaint = False

    win.flash('hello', duration=0.0)

    assert win.rendered == []
    # Timeout is still restored even when the repaint is skipped.
    assert scr.timeouts == [ConsoleWindow.flash_poll_ms, ConsoleWindow.timeout_ms]

# --- interruptible, key-preserving wait -------------------------------------

def test_flash_preserves_key_and_dismisses_early():
    key = ord('q')
    scr = FakeScreen(keys=[key])
    win = make_window(scr)

    # duration is huge; only the key press should end the wait.
    win.flash('hello', duration=30.0)

    assert win.pending_keys == {key}
    assert win.rendered == [True]


def test_flash_redraws_on_resize_then_dismisses():
    scr = FakeScreen(keys=[curses.KEY_RESIZE, ord('x')])
    win = make_window(scr)

    win.flash('hello', duration=30.0)

    # Initial draw + one redraw after the resize.
    assert scr.clears == 2
    assert win.pending_keys == {ord('x')}
    assert win.rendered == [True]

# --- degenerate terminals ---------------------------------------------------

def test_flash_returns_early_when_terminal_too_small():
    scr = FakeScreen(rows=2, cols=80)
    win = make_window(scr)

    win.flash('hello')

    assert scr.clears == 0
    assert scr.timeouts == []
    assert win.rendered == []


def test_flash_returns_early_when_message_too_wide():
    scr = FakeScreen(rows=24, cols=8)
    win = make_window(scr)

    win.flash('a very long message')

    assert scr.clears == 0
    assert scr.timeouts == []
    assert win.rendered == []
