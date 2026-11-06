"""The shared appearance layer: mono roles, the switch and the resolver."""

import curses

import pytest

from console_window import Theme, appearance


@pytest.fixture(autouse=True)
def _fresh_colour_switch(monkeypatch):
    monkeypatch.setattr(appearance, '_COLORS_ENABLED', True)


def test_every_semantic_role_has_a_monochrome_attribute():
    assert set(appearance.MONO_ROLES) == set(Theme.SEMANTIC_PAIRS)


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
    assert appearance.MONO_ROLES[role] == attribute


def test_the_switch_reports_what_was_set():
    assert appearance.colors_enabled() is True
    appearance.set_colors_enabled(False)
    assert appearance.colors_enabled() is False
    appearance.set_colors_enabled(True)
    assert appearance.colors_enabled() is True


def test_colour_on_returns_the_installed_pair(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)
    monkeypatch.setattr(curses, 'color_pair', lambda pair_id: 1000 + pair_id)
    assert appearance.semantic_attr(Theme.WARNING) == 1000 + Theme.WARNING


def test_a_terminal_without_colour_falls_back_to_plain(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    assert appearance.semantic_attr(Theme.WARNING) == 0


def test_a_lookup_before_initscr_never_aborts_a_redraw(monkeypatch):
    def broken():
        raise curses.error('must call initscr() first')

    monkeypatch.setattr(curses, 'has_colors', broken)
    assert appearance.semantic_attr(Theme.WARNING) == 0


def test_a_pair_lookup_can_fail_before_start_color(monkeypatch):
    monkeypatch.setattr(curses, 'has_colors', lambda: True)

    def broken(_pair_id):
        raise curses.error('must call start_color() first')

    monkeypatch.setattr(curses, 'color_pair', broken)
    assert appearance.semantic_attr(Theme.WARNING) == 0


def test_colour_off_uses_the_mono_table():
    appearance.set_colors_enabled(False)
    assert appearance.semantic_attr(Theme.DANGER) == appearance.MONO_ROLES[Theme.DANGER]
    assert appearance.semantic_attr(999) == curses.A_NORMAL


def test_nothing_given_means_the_library_default_and_colour_on():
    assert appearance.resolve_appearance(environ={}) == ('', True)


def test_no_color_flag_wins_over_everything():
    assert appearance.resolve_appearance(
        cli_theme='nord',
        no_color=True,
        saved_theme='gruvbox',
        environ={'NO_COLOR': '1'},
    ) == ('nord', False)


def test_an_explicit_theme_is_a_request_for_colour():
    assert appearance.resolve_appearance(
        cli_theme='nord', environ={'NO_COLOR': '1'}) == ('nord', True)


def test_the_no_color_convention_needs_a_non_empty_value():
    assert appearance.resolve_appearance(environ={'NO_COLOR': '1'}) == ('', False)
    assert appearance.resolve_appearance(environ={'NO_COLOR': ''}) == ('', True)


def test_a_saved_theme_and_its_colour_preference_are_honoured():
    assert appearance.resolve_appearance(
        saved_theme='gruvbox', saved_colors=True, environ={}) == ('gruvbox', True)
    assert appearance.resolve_appearance(
        saved_theme='gruvbox', saved_colors=False, environ={}) == ('gruvbox', False)


def test_no_color_keeps_the_saved_theme_but_not_its_colour():
    assert appearance.resolve_appearance(
        no_color=True, saved_theme='gruvbox', environ={}) == ('gruvbox', False)
    assert appearance.resolve_appearance(
        saved_theme='gruvbox', environ={'NO_COLOR': '1'}) == ('gruvbox', False)


def test_an_unknown_theme_resolves_to_the_library_default():
    assert appearance.resolve_appearance(
        cli_theme='not-a-theme', environ={}) == ('default', True)
    assert appearance.resolve_appearance(
        saved_theme='not-a-theme', environ={}) == ('default', True)


def test_an_empty_remembered_theme_means_the_library_default():
    assert appearance.resolve_appearance(saved_theme=None, environ={}) == ('', True)


def test_the_environment_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    assert appearance.resolve_appearance() == ('', False)
