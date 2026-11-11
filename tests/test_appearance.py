"""The shared appearance layer: mono roles, the switch and the resolver."""

import curses

import pytest

from console_window import Appearance, Theme


@pytest.fixture(autouse=True)
def _fresh_color_switch(monkeypatch):
    monkeypatch.setattr(Appearance, '_COLORS_ENABLED', True)


def test_every_semantic_role_has_a_monochrome_attribute():
    assert set(Appearance.MONO_ROLES) == set(Theme.SEMANTIC_PAIRS)


@pytest.mark.parametrize(('role', 'attribute'), [
    (Theme.DANGER, curses.A_BOLD | curses.A_REVERSE),
    (Theme.ERROR, curses.A_BOLD | curses.A_REVERSE),
    (Theme.WARNING, curses.A_BOLD),
    (Theme.SUCCESS, curses.A_BOLD),
    (Theme.EMPHASIS, curses.A_BOLD),
    (Theme.INFO, curses.A_NORMAL),
    (Theme.PROGRESS, curses.A_NORMAL),
    (Theme.OLD_SUCCESS, curses.A_NORMAL),
    (Theme.HOTSWAP, curses.A_NORMAL),
])
def test_the_monochrome_table_keeps_the_hierarchy(role, attribute):
    assert Appearance.MONO_ROLES[role] == attribute


def test_the_switch_reports_what_was_set():
    assert Appearance.colors_enabled() is True
    Appearance.set_colors_enabled(False)
    assert Appearance.colors_enabled() is False
    Appearance.set_colors_enabled(True)
    assert Appearance.colors_enabled() is True


def test_color_on_returns_the_installed_pair(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)
    monkeypatch.setattr(curses, 'color_pair', lambda pair_id: 1000 + pair_id)
    assert Appearance.semantic_attr(Theme.WARNING) == 1000 + Theme.WARNING


def test_a_terminal_without_color_uses_the_mono_table(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    assert (Appearance.semantic_attr(Theme.WARNING)
            == Appearance.MONO_ROLES[Theme.WARNING])


def test_a_lookup_before_initscr_never_aborts_a_redraw(monkeypatch):
    def broken():
        raise curses.error('must call initscr() first')

    monkeypatch.setattr(curses, 'has_colors', broken)
    assert Appearance.semantic_attr(Theme.WARNING) == 0


def test_a_pair_lookup_can_fail_before_start_color(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)

    def broken(_pair_id):
        raise curses.error('must call start_color() first')

    monkeypatch.setattr(curses, 'color_pair', broken)
    assert Appearance.semantic_attr(Theme.WARNING) == 0


def test_color_off_uses_the_mono_table():
    Appearance.set_colors_enabled(False)
    assert Appearance.semantic_attr(Theme.DANGER) == Appearance.MONO_ROLES[Theme.DANGER]
    assert Appearance.semantic_attr(999) == curses.A_NORMAL


def test_nothing_given_means_the_library_default():
    assert Appearance.resolve_appearance(environ={}) == ''


def test_an_explicit_theme_wins_over_everything():
    assert Appearance.resolve_appearance(
        cli_theme='nord',
        saved_theme='gruvbox',
        environ={'NO_COLOR': '1'},
    ) == 'nord'


def test_the_no_color_convention_selects_mono():
    assert Appearance.resolve_appearance(environ={'NO_COLOR': '1'}) == 'mono'
    assert Appearance.resolve_appearance(environ={'NO_COLOR': ''}) == ''


def test_a_saved_theme_is_honored_and_canonicalized():
    assert Appearance.resolve_appearance(
        saved_theme='gruvbox', environ={}) == 'gruvbox'
    assert Appearance.resolve_appearance(
        saved_theme='dark-mono', environ={}) == 'dark'


def test_no_color_overrides_a_saved_theme():
    assert Appearance.resolve_appearance(
        saved_theme='gruvbox', environ={'NO_COLOR': '1'}) == 'mono'


def test_an_explicit_mono_theme_selects_mono():
    assert Appearance.resolve_appearance(
        cli_theme='mono', environ={}) == 'mono'


def test_an_unknown_theme_resolves_to_the_library_default():
    assert Appearance.resolve_appearance(
        cli_theme='not-a-theme', environ={}) == 'default'
    assert Appearance.resolve_appearance(
        saved_theme='not-a-theme', environ={}) == 'default'


def test_an_empty_remembered_theme_keeps_the_library_default():
    assert Appearance.resolve_appearance(saved_theme=None, environ={}) == ''


def test_the_environment_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    assert Appearance.resolve_appearance() == 'mono'


def test_selecting_mono_turns_color_off_and_a_palette_turns_it_on():
    Theme.set_active('mono')
    assert Appearance.colors_enabled() is False
    Theme.set_active('nord')
    assert Appearance.colors_enabled() is True
