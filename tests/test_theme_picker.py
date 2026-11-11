"""The theme picker factory: hint key, persistence, note, and swatches."""

import curses
from types import SimpleNamespace

import pytest

from console_window import (
    Appearance,
    ConsoleWindow,
    ConsoleWindowOpts,
    Theme,
)
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
def _color_pairs(monkeypatch):
    # The swatches ask curses for a color pair; no initscr() runs in tests.
    monkeypatch.setattr(curses, 'color_pair', lambda pair: 0)


@pytest.fixture(autouse=True)
def _color_switch(monkeypatch):
    # The appearance switch is process state; never leak a test's choice.
    monkeypatch.setattr(Appearance, '_COLORS_ENABLED', True)


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


_SWATCH_ROLES = (
    ('DANGER', Theme.DANGER),
    ('SUCCESS', Theme.SUCCESS),
    ('OLD_SUCCESS', Theme.OLD_SUCCESS),
    ('WARNING', Theme.WARNING),
    ('INFO', Theme.INFO),
    ('EMPHASIS', Theme.EMPHASIS),
    ('ERROR', Theme.ERROR),
    ('PROGRESS', Theme.PROGRESS),
    ('HOTSWAP', Theme.HOTSWAP),
)


def _swatch_attrs(win):
    """The first attribute run of each role row, keyed by its label."""
    attrs = {}
    for text, runs in zip(win.body.texts, win.body.text_attrs, strict=False):
        if runs:
            attrs[text.split()[0]] = runs[0][0]
    return attrs


def test_swatches_use_the_installed_pair_when_color_is_on(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)
    monkeypatch.setattr(curses, 'color_pair', lambda pair: 500 + pair)
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(_BaseScreen)
        picker(app).draw_screen()
        attrs = _swatch_attrs(win)
        for label, role in _SWATCH_ROLES:
            assert attrs[label] == 500 + role
    finally:
        win.stop_curses()


def test_swatches_follow_the_mono_theme(monkeypatch):
    # A picker opened on mono used to re-paint the previous theme's pairs.  It
    # must use the same monochrome hierarchy as the rest of the UI and must not
    # touch curses.color_pair() at all.
    monkeypatch.setattr(curses, 'has_colors', lambda: True)

    def _unexpected(pair):
        raise AssertionError(f'color pair {pair} used while color is off')

    monkeypatch.setattr(curses, 'color_pair', _unexpected)
    win = _window(theme='mono')
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='mono'))
        picker = Theme.create_picker_screen(_BaseScreen)
        picker(app).draw_screen()
        assert Appearance.colors_enabled() is False
        attrs = _swatch_attrs(win)
        for label, role in _SWATCH_ROLES:
            assert attrs[label] == Appearance.MONO_ROLES[role]
    finally:
        win.stop_curses()


def test_the_header_names_the_theme_the_window_is_on():
    win = _window(theme='nord')
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='nord'))
        Theme.create_picker_screen(_BaseScreen)(app).draw_screen()
        assert 'nord' in win.head.texts[0]
    finally:
        win.stop_curses()


def test_a_host_can_override_the_theme_label_hook():
    # A host with a pseudo-theme (mono, say) names its own choice in the
    # header, so the label and the swatches cannot disagree.
    win = _window(theme='nord')
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='nord'))
        base = Theme.create_picker_screen(_BaseScreen)

        class _MonoLabel(base):
            def theme_label(self, theme_name):
                return 'mono'

        _MonoLabel(app).draw_screen()
        assert 'mono' in win.head.texts[0]
        assert 'nord' not in win.head.texts[0]
    finally:
        win.stop_curses()


def test_a_host_can_override_the_swatch_hook(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        base = Theme.create_picker_screen(_BaseScreen)

        class _PlainSwatches(base):
            @staticmethod
            def swatch_attr(color_id):
                return curses.A_UNDERLINE

        _PlainSwatches(app).draw_screen()
        assert set(_swatch_attrs(win).values()) == {curses.A_UNDERLINE}
    finally:
        win.stop_curses()


def test_custom_captions_replace_labels_and_usages():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(
            _BaseScreen,
            captions={
                'danger': ('FAILED', 'Boot or initramfs failed'),
                'warning': ('DEGRADED', ''),
            },
        )
        picker(app).draw_screen()
        assert any('FAILED' in row and 'Boot or initramfs failed' in row
                   for row in win.body.texts)
        # An empty usage falls back to the library description.
        assert any('DEGRADED' in row and 'Caution/stopped states' in row
                   for row in win.body.texts)
        # include_defaults keeps the roles the app did not mention.
        assert any(row.startswith('SUCCESS') for row in win.body.texts)
    finally:
        win.stop_curses()


def test_replace_mode_shows_only_the_apps_rows():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(
            _BaseScreen,
            include_defaults=False,
            captions={
                'danger': ('FAILED', 'Boot failed'),
                'success': ('OK', 'Healthy device'),
            },
        )
        picker(app).draw_screen()
        assert [row.split()[0] for row in win.body.texts] == ['FAILED', 'OK']
    finally:
        win.stop_curses()


def test_a_long_caption_widens_the_label_column():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(
            _BaseScreen,
            include_defaults=False,
            captions={'danger': ('FAILED TO START', 'Boot failed')},
        )
        picker(app).draw_screen()
        row = win.body.texts[0]
        assert row.startswith('FAILED TO START')
        assert '\u2588' * 8 in row
    finally:
        win.stop_curses()


def test_a_very_long_caption_is_truncated_before_the_swatch():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        picker = Theme.create_picker_screen(
            _BaseScreen,
            include_defaults=False,
            captions={'danger': ('X' * 200, 'Boot failed')},
        )
        picker(app).draw_screen()
        row = win.body.texts[0]
        assert '\u2588' * 8 in row
        assert row.index('\u2588') < win.get_pad_width()
    finally:
        win.stop_curses()


def test_a_host_can_override_the_swatch_rows_hook():
    win = _window()
    try:
        app = SimpleNamespace(win=win, opts=SimpleNamespace(theme='default'))
        base = Theme.create_picker_screen(_BaseScreen)

        class _OnlyDanger(base):
            def swatch_rows(self):
                return [(Theme.DANGER, 'FAILED', 'Boot failed')]

        _OnlyDanger(app).draw_screen()
        assert len(win.body.texts) == 1
        assert win.body.texts[0].startswith('FAILED')
    finally:
        win.stop_curses()


def test_the_factory_validates_captions_eagerly():
    with pytest.raises(ValueError, match='unknown color role'):
        Theme.create_picker_screen(
            _BaseScreen,
            captions={'chartreuse': ('NOPE', None)},
        )
