import curses
from types import SimpleNamespace

import pytest

from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.screens import Screen
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
                        backend=backend, singleton=False)
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


# --- the shared picker screen ----------------------------------------------

def _picker_app(theme_name):
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_rows=8, body_rows=24),
                        backend=HeadlessBackend(rows=30, cols=100),
                        singleton=False)
    return win, SimpleNamespace(win=win, opts=SimpleNamespace(theme=theme_name))


def test_create_picker_screen_draws_swatches(colour_recorder, monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'dark-mono')
    win, app = _picker_app('dark-mono')
    screen = Theme.create_picker_screen(Screen)(app)
    try:
        screen.draw_screen()
        assert win.pick_mode is False
        assert any('COLOR THEME' in line for line in win.head.texts)
        assert any('DANGER' in line for line in win.body.texts)
    finally:
        win.stop_curses()


def test_create_picker_screen_honours_the_apps_selected_theme(colour_recorder, monkeypatch):
    # The sample app drives the picker with an ordinary cycle option, so the
    # factory must apply opts.theme before drawing the swatches.
    monkeypatch.setattr(Theme, '_current', 'dark-mono')
    win, app = _picker_app('nord')
    screen = Theme.create_picker_screen(Screen)(app)
    try:
        screen.draw_screen()
        assert Theme.get_current() == 'nord'
    finally:
        win.stop_curses()


def test_create_picker_screen_spin_action_cycles_and_updates_option(colour_recorder, monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'dark-mono')
    win, app = _picker_app('dark-mono')
    screen = Theme.create_picker_screen(Screen)(app)
    themes = Theme.list_all()
    expected = themes[(themes.index('dark-mono') + 1) % len(themes)]
    try:
        screen.spin_theme_ACTION()
        assert win.theme == expected
        assert Theme.get_current() == expected
        assert app.opts.theme == expected
    finally:
        win.stop_curses()


# --- per-window themes (AUDIT.md §3.1) -------------------------------------

def _colour_window(theme_name):
    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(theme=theme_name),
        backend=backend,
        singleton=False,
    )
    return win, backend


def test_opts_theme_seeds_the_windows_own_theme(colour_recorder):
    win, backend = _colour_window('nord')
    try:
        assert win.theme == 'nord'
        assert Theme.get_current() == 'nord'
        # nord's SUCCESS is (150, 236); startup installed it through the backend.
        assert (Theme.SUCCESS, 150, 236) in backend.init_pair_calls
        assert Theme.DEFAULT_BG in backend.color_pair_calls
    finally:
        win.stop_curses()


def test_two_windows_keep_their_own_theme_and_palette(colour_recorder):
    first, first_backend = _colour_window('nord')
    second, second_backend = _colour_window('gruvbox')
    try:
        assert first.theme == 'nord'
        assert second.theme == 'gruvbox'
        # Each window installed its own palette on its own terminal seam.
        assert (Theme.SUCCESS, 150, 236) in first_backend.init_pair_calls
        assert (Theme.SUCCESS, 142, 235) in second_backend.init_pair_calls
        # New windows inherit the most recently applied theme, not a stale one.
        assert Theme.get_current() == 'gruvbox'
    finally:
        first.stop_curses()
        second.stop_curses()


def test_set_theme_switches_one_window_and_rejects_unknown_names(colour_recorder):
    win, backend = _colour_window('nord')
    try:
        assert win.set_theme('does-not-exist') is False
        assert win.theme == 'nord'

        assert win.set_theme('gruvbox') is True
        assert win.theme == 'gruvbox'
        assert Theme.get_current() == 'gruvbox'
        assert (Theme.SUCCESS, 142, 235) in backend.init_pair_calls
        # The pads were repainted with the new background pair.
        assert Theme.DEFAULT_BG in backend.color_pair_calls
    finally:
        win.stop_curses()


def test_set_theme_records_the_choice_without_colour_support(colour_recorder):
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(theme='nord'),
        backend=HeadlessBackend(),  # no colour support
        singleton=False,
    )
    try:
        assert win.set_theme('gruvbox') is False
        # The selection is still per-window state, not silently discarded.
        assert win.theme == 'gruvbox'
        assert Theme.get_current() == 'gruvbox'
    finally:
        win.stop_curses()


def test_theme_set_is_a_process_wide_switch_and_relabels_live_windows(colour_recorder):
    first, _ = _colour_window('nord')
    second, _ = _colour_window('gruvbox')
    try:
        assert Theme.set('dark-mono') is True
        assert first.theme == 'dark-mono'
        assert second.theme == 'dark-mono'
    finally:
        first.stop_curses()
        second.stop_curses()
