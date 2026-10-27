"""The theme picker factory: hint key, persistence, note, and swatches."""

import curses
from types import SimpleNamespace

import pytest

from console_window import ConsoleWindow, ConsoleWindowOpts, Theme
from console_window.backend import HeadlessBackend


class _Store:
    def __init__(self, remembered=None, fail=False):
        self.remembered = remembered
        self.fail = fail
        self.saved = []

    def load(self):
        return self.remembered

    def save(self, name):
        if self.fail:
            raise OSError('read-only store')
        self.saved.append(name)


class _BaseScreen:
    """Minimal host screen: the factory only needs app.win and app.opts."""

    def __init__(self, app, spinner=None):
        self.app = app
        self._spinner = spinner

    def get_spinner(self):
        return self._spinner


class _BrokenStore:
    def load(self):
        raise OSError('unreadable')

    def save(self, name):
        raise OSError('unwritable')


@pytest.fixture(autouse=True)
def _colour_pairs(monkeypatch):
    # The swatches ask curses for a colour pair; no initscr() runs in tests.
    monkeypatch.setattr(curses, 'color_pair', lambda pair: 0)


@pytest.fixture(autouse=True)
def _forget_the_process_theme(monkeypatch):
    monkeypatch.setattr(Theme, '_current', None)


def _window(theme='default'):
    return ConsoleWindow(
        opts=ConsoleWindowOpts(theme=theme),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )


def _spinner_with(*keys):
    spinner = SimpleNamespace(options=[SimpleNamespace(attr='theme', keys=list(keys))])
    return spinner


def test_initial_prefers_the_command_line_choice():
    assert Theme.initial('nord', _Store('gruvbox')) == 'nord'


def test_initial_uses_the_remembered_theme():
    assert Theme.initial(None, _Store('gruvbox')) == 'gruvbox'


def test_initial_defaults_when_nothing_is_remembered():
    assert Theme.initial(None, _Store(None)) == 'default'
    assert Theme.initial(None, None) == 'default'


def test_initial_survives_a_broken_store():
    assert Theme.initial(None, _BrokenStore()) == 'default'


def test_cycling_saves_the_new_theme():
    store = _Store()
    win = _window(theme='default')
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen, store=store)
        picker(app).spin_theme_ACTION()
        assert store.saved
        assert store.saved[-1] == app.opts.theme
    finally:
        win.stop_curses()


def test_a_failing_store_never_breaks_the_cycle():
    win = _window(theme='default')
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen, store=_BrokenStore())
        picker(app).spin_theme_ACTION()
        # The theme still advanced, and the option records it.
        assert app.opts.theme != 'default'
    finally:
        win.stop_curses()


def test_the_hint_advertises_the_bound_cycle_key():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen)
        picker(app, _spinner_with(ord('n'))).draw_screen()
        assert any('Press [n] to cycle themes' in row for row in win.head.texts)
    finally:
        win.stop_curses()


def test_an_explicit_cycle_key_wins_over_discovery():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen, cycle_key='c')
        picker(app, _spinner_with(ord('n'))).draw_screen()
        assert any('Press [c] to cycle themes' in row for row in win.head.texts)
    finally:
        win.stop_curses()


def test_the_hint_falls_back_to_t_without_a_binding():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen)
        picker(app).draw_screen()
        assert any('Press [t] to cycle themes' in row for row in win.head.texts)
    finally:
        win.stop_curses()


def test_the_note_is_drawn_when_given():
    note = 'The choice is remembered for the next start.'
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen, note=note)
        picker(app).draw_screen()
        assert note in win.body.texts
    finally:
        win.stop_curses()


def test_swatches_use_the_registered_glyph():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen)
        picker(app).draw_screen()
        assert any('\u2588' * 8 in row for row in win.body.texts)
    finally:
        win.stop_curses()
