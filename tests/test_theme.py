import curses
from types import SimpleNamespace

import pytest

from console_window import Appearance
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.screens import Screen
from console_window.theme import Theme
from console_window.window import ConsoleWindow


@pytest.fixture
def color_recorder(monkeypatch):
    # curses color calls raise until initscr() has succeeded; stand them in and
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
    # Theme.set() and _init_screen() must reinitialize exactly this set; startup
    # used to omit OLD_SUCCESS, leaving it on an uninitialized pair.
    assert Theme.OLD_SUCCESS in Theme.SEMANTIC_PAIRS
    assert set(Theme.SEMANTIC_PAIRS) == {
        Theme.DANGER, Theme.SUCCESS, Theme.OLD_SUCCESS, Theme.WARNING,
        Theme.INFO, Theme.EMPHASIS, Theme.ERROR, Theme.PROGRESS, Theme.HOTSWAP,
    }


def test_default_bg_pair_keeps_its_historic_id():
    # Was the bare literal ``8`` in two places; the id must not drift, or the
    # already-written color_pair(8) references would point elsewhere.
    assert Theme.DEFAULT_BG == 8


# --- the two initialization paths agree -------------------------------------

def test_startup_initializes_every_semantic_pair(monkeypatch):
    # Startup must not touch curses directly: a backend that reports colors
    # owns color initialization, so make any direct call a hard failure.
    def off_limits(*args, **kwargs):
        raise AssertionError('startup called curses instead of the backend')

    for name in ('start_color', 'use_default_colors', 'color_pair', 'init_pair'):
        monkeypatch.setattr(curses, name, off_limits)
    monkeypatch.setattr(Theme, '_current', 'dark')

    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                        backend=backend, singleton=False)
    try:
        assert backend.start_color_calls == 1
        assert backend.use_default_colors_calls == 1
        initialized = {pair for pair, _fg, _bg in backend.init_pair_calls}
        assert set(Theme.SEMANTIC_PAIRS) <= initialized
        assert Theme.DEFAULT_BG in initialized
        assert Theme.DEFAULT_BG in backend.color_pair_calls
    finally:
        win.stop_curses()


def test_theme_set_initializes_the_same_pair_set(monkeypatch):
    # Theme.set() must go through the live window's backend, not curses
    # directly: the old direct path bypassed every low-color guard.
    monkeypatch.setattr(Theme, '_current', None)
    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                        backend=backend, singleton=False)
    try:
        backend.init_pair_calls.clear()
        assert Theme.set('dark') is True
        initialized = {pair for pair, _fg, _bg in backend.init_pair_calls}
        assert set(Theme.SEMANTIC_PAIRS) <= initialized
        assert Theme.DEFAULT_BG in initialized
        assert win.theme == 'dark'
    finally:
        win.stop_curses()


# --- the shared picker screen ----------------------------------------------

def _picker_app(theme_name):
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_rows=8, body_rows=24),
                        backend=HeadlessBackend(rows=30, cols=100),
                        singleton=False)
    return win, SimpleNamespace(win=win, opts=SimpleNamespace(theme=theme_name))


def test_create_picker_screen_draws_swatches(color_recorder, monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'dark')
    win, app = _picker_app('dark')
    screen = Theme.create_picker_screen(Screen)(app)
    try:
        screen.draw_screen()
        assert win.pick_mode is False
        assert any('COLOR THEME' in line for line in win.head.texts)
        assert any('DANGER' in line for line in win.body.texts)
    finally:
        win.stop_curses()


def test_create_picker_screen_honors_the_apps_selected_theme(color_recorder, monkeypatch):
    # The sample app drives the picker with an ordinary cycle option, so the
    # factory must apply opts.theme before drawing the swatches.
    monkeypatch.setattr(Theme, '_current', 'dark')
    win, app = _picker_app('nord')
    screen = Theme.create_picker_screen(Screen)(app)
    try:
        screen.draw_screen()
        assert Theme.get_current() == 'nord'
    finally:
        win.stop_curses()


def test_create_picker_screen_spin_action_cycles_and_updates_option(color_recorder, monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'dark')
    win, app = _picker_app('dark')
    screen = Theme.create_picker_screen(Screen)(app)
    themes = Theme.list_all()
    expected = themes[(themes.index('dark') + 1) % len(themes)]
    try:
        screen.spin_theme_ACTION()
        assert win.theme == expected
        assert Theme.get_current() == expected
        assert app.opts.theme == expected
    finally:
        win.stop_curses()


# --- per-window themes (AUDIT.md §3.1) -------------------------------------

def _color_window(theme_name):
    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(theme=theme_name),
        backend=backend,
        singleton=False,
    )
    return win, backend


def test_opts_theme_seeds_the_windows_own_theme(color_recorder):
    win, backend = _color_window('nord')
    try:
        assert win.theme == 'nord'
        assert Theme.get_current() == 'nord'
        # nord's SUCCESS is (150, 236); startup installed it through the backend.
        assert (Theme.SUCCESS, 150, 236) in backend.init_pair_calls
        assert Theme.DEFAULT_BG in backend.color_pair_calls
    finally:
        win.stop_curses()


def test_two_windows_keep_their_own_theme_and_palette(color_recorder):
    first, first_backend = _color_window('nord')
    second, second_backend = _color_window('gruvbox')
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


def test_set_theme_switches_one_window_and_rejects_unknown_names(color_recorder):
    win, backend = _color_window('nord')
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


def test_set_theme_records_the_choice_without_color_support(color_recorder):
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(theme='nord'),
        backend=HeadlessBackend(),  # no color support
        singleton=False,
    )
    try:
        assert win.set_theme('gruvbox') is False
        # The selection is still per-window state, not silently discarded.
        assert win.theme == 'gruvbox'
        assert Theme.get_current() == 'gruvbox'
    finally:
        win.stop_curses()


def test_theme_set_is_a_process_wide_switch_and_relabels_live_windows(color_recorder):
    first, _ = _color_window('nord')
    second, _ = _color_window('gruvbox')
    try:
        assert Theme.set('dark') is True
        assert first.theme == 'dark'
        assert second.theme == 'dark'
    finally:
        first.stop_curses()
        second.stop_curses()


# --- mono, aliases and the switch -----------------------------------------

def test_mono_is_last_and_defines_only_the_default_background():
    assert Theme.list_all()[-1] == Theme.MONO
    assert Theme.pair_specs('mono') == [(Theme.DEFAULT_BG, -1, -1)]
    assert Theme.is_mono('mono') is True
    assert Theme.is_mono('dark') is False


def test_legacy_theme_aliases_canonicalize():
    assert Theme.canonical('dark-mono') == 'dark'
    assert Theme.canonical('light-mono') == 'light'
    assert Theme.canonical('nonsense') is None
    assert Theme.resolve('dark-mono') == 'dark'
    assert Theme.resolve('nonsense') == 'default'


def test_mono_is_usable_without_color_support_and_palettes_are_not():
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(theme='dark'),
        backend=HeadlessBackend(),  # no color support
        singleton=False,
    )
    try:
        assert win.set_theme('mono') is True
        assert win.theme == 'mono'
        assert Theme.get_current() == 'mono'
        assert Appearance.colors_enabled() is False

        # A palette is recorded but cannot be painted on this terminal; the
        # request for color still lifts the switch.
        assert win.set_theme('nord') is False
        assert win.theme == 'nord'
        assert Appearance.colors_enabled() is True
    finally:
        win.stop_curses()


def test_theme_set_selects_mono_and_turns_color_off():
    backend = HeadlessBackend(colors=True)
    win = ConsoleWindow(opts=ConsoleWindowOpts(), backend=backend, singleton=False)
    try:
        assert Theme.set('mono') is True
        assert win.theme == 'mono'
        assert Theme.get_current() == 'mono'
        assert Appearance.colors_enabled() is False
        # Only the terminal-default background pair is installed.
        assert backend.init_pair_calls[-1] == (Theme.DEFAULT_BG, -1, -1)
    finally:
        win.stop_curses()


# --- role names and picker captions ---------------------------------------

def test_every_semantic_role_has_a_name_and_a_default_caption():
    # The name/caption tables are the picker's vocabulary; keep them from
    # drifting away from the roles the library actually installs.
    assert set(Theme.ROLES.values()) == set(Theme.SEMANTIC_PAIRS)
    assert set(Theme.ROLE_CAPTIONS) == set(Theme.SEMANTIC_PAIRS)


def test_role_id_accepts_constants_and_names():
    assert Theme.role_id(Theme.DANGER) == Theme.DANGER
    assert Theme.role_id('danger') == Theme.DANGER
    assert Theme.role_id('DANGER') == Theme.DANGER
    assert Theme.role_id('old-success') == Theme.OLD_SUCCESS
    assert Theme.role_id('Old Success') == Theme.OLD_SUCCESS


def test_role_id_rejects_unknown_and_non_displayable_roles():
    with pytest.raises(ValueError, match='unknown color role'):
        Theme.role_id('chartreuse')
    with pytest.raises(ValueError, match='not a displayable color role'):
        Theme.role_id(Theme.DEFAULT)
    with pytest.raises(ValueError, match='unknown color role'):
        Theme.role_id(True)


def test_role_captions_default_to_the_library_rows():
    rows = Theme.role_captions()
    assert [role for role, _label, _usage in rows] == list(Theme.ROLE_CAPTIONS)
    assert rows[0] == (Theme.DANGER, 'DANGER', 'Destructive operations')
    assert Theme.role_captions(None, include_defaults=False) == []


def test_role_captions_override_in_place_and_keep_the_library_order():
    rows = Theme.role_captions({
        'danger': ('FAILED', 'Boot failed'),
        Theme.SUCCESS: (None, ''),
    })
    by_role = {role: (label, usage) for role, label, usage in rows}
    assert by_role[Theme.DANGER] == ('FAILED', 'Boot failed')
    # Empty fields inherit the library text rather than blanking the column.
    assert by_role[Theme.SUCCESS] == ('SUCCESS', 'Completed operations')
    assert [role for role, _label, _usage in rows] == list(Theme.ROLE_CAPTIONS)


def test_role_captions_replace_mode_uses_only_the_mapping_in_order():
    rows = Theme.role_captions({
        Theme.INFO: ('SCAN', 'Discovery in progress'),
        'danger': ('FAILED', None),
    }, include_defaults=False)
    assert [role for role, _label, _usage in rows] == [Theme.INFO, Theme.DANGER]
    assert rows[0] == (Theme.INFO, 'SCAN', 'Discovery in progress')
    # A missing usage still inherits the library description.
    assert rows[1] == (Theme.DANGER, 'FAILED', 'Destructive operations')


def test_role_captions_reject_duplicate_roles_after_normalization():
    with pytest.raises(ValueError, match='duplicate caption'):
        Theme.role_captions({
            Theme.DANGER: ('FAILED', None),
            'danger': ('BROKE', None),
        })


def test_role_captions_reject_unknown_roles_and_malformed_text():
    with pytest.raises(ValueError, match='unknown color role'):
        Theme.role_captions({'chartreuse': ('NOPE', None)})
    with pytest.raises(ValueError, match=r'\(label, usage\) pair'):
        Theme.role_captions({Theme.DANGER: 'FAILED'})
    with pytest.raises(ValueError, match='string or None'):
        Theme.role_captions({Theme.DANGER: (1, None)})
