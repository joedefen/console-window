import curses

import pytest

from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.theme import Theme
from console_window.window import ConsoleWindow


@pytest.fixture
def colour_recorder(monkeypatch):
    # curses colour calls raise until initscr() has succeeded; stand them in and
    # record which pair ids init_pair() is called with.
    inited = []
    monkeypatch.setattr(curses, 'start_color', lambda: None)
    monkeypatch.setattr(curses, 'use_default_colors', lambda: None)
    monkeypatch.setattr(curses, 'has_colors', lambda: True)
    monkeypatch.setattr(curses, 'color_pair', lambda pair: pair << 8)
    monkeypatch.setattr(curses, 'init_pair', lambda pair, fg, bg: inited.append(pair))
    return inited


# --- the shared pair list ---------------------------------------------------

def test_semantic_pairs_is_one_shared_list_including_old_success():
    # Theme.set() and _init_screen() must reinitialise exactly this set; startup
    # used to omit OLD_SUCCESS, leaving it on an uninitialised pair.
    assert Theme.OLD_SUCCESS in Theme.SEMANTIC_PAIRS
    assert set(Theme.SEMANTIC_PAIRS) == {
        Theme.DANGER, Theme.SUCCESS, Theme.OLD_SUCCESS, Theme.WARNING,
        Theme.INFO, Theme.EMPHASIS, Theme.ERROR, Theme.PROGRESS, Theme.HOTSWAP,
    }


def test_default_bg_pair_keeps_its_historic_id():
    # Was the bare literal ``8`` in two places; the id must not drift, or the
    # already-written colour_pair(8) references would point elsewhere.
    assert Theme.DEFAULT_BG == 8


# --- the two initialisation paths agree -------------------------------------

def test_startup_initialises_every_semantic_pair(monkeypatch):
    # Startup must not touch curses directly: a backend that reports colours
    # owns colour initialisation, so make any direct call a hard failure.
    def off_limits(*args, **kwargs):
        raise AssertionError('startup called curses instead of the backend')

    for name in ('start_color', 'use_default_colors', 'color_pair', 'init_pair'):
        monkeypatch.setattr(curses, name, off_limits)
    monkeypatch.setattr(Theme, '_current', 'dark-mono')

    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                        backend=backend)
    try:
        assert backend.start_color_calls == 1
        assert backend.use_default_colors_calls == 1
        initialised = {pair for pair, _fg, _bg in backend.init_pair_calls}
        assert set(Theme.SEMANTIC_PAIRS) <= initialised
        assert Theme.DEFAULT_BG in initialised
        assert Theme.DEFAULT_BG in backend.color_pair_calls
    finally:
        win.stop_curses()


def test_theme_set_initialises_the_same_pair_set(colour_recorder, monkeypatch):
    monkeypatch.setattr(Theme, '_current', None)
    assert Theme.set('dark-mono') is True
    assert set(Theme.SEMANTIC_PAIRS) <= set(colour_recorder)
    assert Theme.DEFAULT_BG in colour_recorder
