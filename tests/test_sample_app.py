"""Headless smoke tests for the worked-example app.

The example app lives at ``demos/demo-buffet.py`` (it used to be a repo-level
``SampleApp.py``).  These tests construct it against a HeadlessBackend, draw
every screen through the four-call loop, and assert the wiring (scoped keys,
action handlers, the router) still holds.  No TTY is required.
"""

import curses
import importlib.util
import pathlib

import pytest

from console_window import Appearance, Theme
from console_window.backend import HeadlessBackend

DEMO_PY = pathlib.Path(__file__).resolve().parents[1] / 'demos' / 'demo-buffet.py'
_sample_module = None


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors() and curses.color_pair() raise until initscr() has
    # succeeded, and the demo's drawing code calls both, so stand them in.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)


@pytest.fixture(autouse=True)
def _appearance_state(monkeypatch):
    # The color switch and the process theme are process state; the app
    # reads both when it seeds its theme option, so never leak a test's choice.
    monkeypatch.setattr(Appearance, '_COLORS_ENABLED', True)
    monkeypatch.setattr(Theme, '_current', None)


def _load_sample():
    """Import ``demos/demo-buffet.py`` without making ``demos`` a package."""
    global _sample_module
    if _sample_module is None:
        spec = importlib.util.spec_from_file_location('demo_buffet_under_test',
                                                      DEMO_PY)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _sample_module = module
    return _sample_module


def _app(rows=40, cols=120):
    sample = _load_sample()

    # The suite runs several app instances; keep the process in per-instance
    # window mode (the first construction latches it).
    return sample, sample.SampleApp(backend=HeadlessBackend(rows=rows, cols=cols),
                                    singleton=False)


def _draw(app, num):
    """Run one pass of the documented loop for screen *num*."""
    screen = app.screens[num]
    screen.clear()
    screen.draw_screen()
    return screen


def test_sample_app_builds_headless_and_draws_every_screen():
    sample, app = _app()
    try:
        for num in (sample.MAIN_ST, sample.HELP_ST, sample.HISTORY_ST,
                    sample.THEME_ST):
            _draw(app, num)
            assert app.win.body.row_cnt > 0
        assert app.win.head.row_cnt > 0
    finally:
        app.win.stop_curses()


def test_sample_app_registers_the_folded_options():
    _, app = _app()
    try:
        attrs = {ns.attr for ns in app.spin.options}
        assert {'pick_size', 'name', 'force_redraw', 'stress'} <= attrs
        assert app.opts.pick_size == 1
        assert app.opts.stress is False
        assert app.opts.force_redraw is False
        assert app.opts.name == ''
    finally:
        app.win.stop_curses()


def test_control_c_is_a_bound_key_not_a_terminating_signal():
    _, app = _app()
    try:
        assert app.win.opts.ctrl_c_terminates is False
        assert 0x3 in app.spin.keys
        screens = set(app.screens)
        assert {app.spin.key_scopes[(0x3, num)].attr for num in screens} == {'quit'}
    finally:
        app.win.stop_curses()


def test_t_key_is_scope_subtracted_between_main_and_themes():
    sample, app = _app()
    try:
        # 't' opens the theme screen on MAIN, but cycles themes on THEMES/HELP.
        assert app.spin.key_scopes[(ord('t'), sample.MAIN_ST)].attr == 'theme_screen'
        assert app.spin.key_scopes[(ord('t'), sample.THEME_ST)].attr == 'theme'
    finally:
        app.win.stop_curses()


def test_every_action_option_has_a_handler_on_some_screen():
    _, app = _app()
    try:
        for ns in app.spin.options:
            if ns.genre != 'action':
                continue
            assert any(hasattr(screen, f'{ns.attr}_ACTION')
                       for screen in app.screens.values()), ns.attr
    finally:
        app.win.stop_curses()


def test_router_pushes_and_pops_screens():
    sample, app = _app()
    try:
        app.opts.help_screen = True
        app.stack.perform_actions(app.spin)
        assert app.stack.curr.num == sample.HELP_ST

        app.opts.escape = True
        app.stack.perform_actions(app.spin)
        assert app.stack.curr.num == sample.MAIN_ST
    finally:
        app.win.stop_curses()


def test_stress_mode_pads_the_body_within_pad_capacity():
    sample, app = _app()
    try:
        main = _draw(app, sample.MAIN_ST)
        normal = app.win.body.row_cnt

        main.clear()
        app.opts.stress = True
        main.draw_screen()
        assert app.win.body.row_cnt > normal
        # Nothing is dropped: the pads are viewport-sized, the 2000 filler rows
        # live in the model, and the default max_rows ceiling is far above them.
        assert app.win.rows_dropped == 0
    finally:
        app.win.stop_curses()


# --- the in-place prompt, status and the history screen ---------------------

def test_confirm_prompt_consumes_every_key_and_reports_status():
    sample, app = _app()
    try:
        main = _draw(app, sample.MAIN_ST)
        app.win.pick_pos = 0
        username = app.win.get_picked_context().item['username']

        main.select_ACTION()
        assert app.win.prompt_active is True
        assert app.prompt_item == username
        assert app.win.passthrough_mode is True

        # The prompt swallows an action/navigation key underneath it.
        app.handle_key(ord('j'))
        assert app.win.prompt_active is True
        assert app.win.pick_pos == 0

        app.handle_key(ord('y'))

        assert app.win.prompt_active is False
        assert app.win.passthrough_mode is False
        assert app.prompt_item is None
        assert app.selected_items == {username}
        assert app.operation_count == 1
        assert app.win.current_status[0] == f'✓ Processed {username}'
    finally:
        app.win.stop_curses()


def test_confirm_prompt_rows_are_drawn_after_the_item():
    sample, app = _app()
    try:
        main = _draw(app, sample.MAIN_ST)
        app.win.pick_pos = 0

        main.select_ACTION()
        main.clear()
        main.draw_screen()

        assert any('Process ' in text and '[Press "y" or ESC]' in text
                   for text in app.win.body.texts)
        assert any(text.strip() == 'Marks the row as ✓ Processed'
                   for text in app.win.body.texts)
    finally:
        app.win.stop_curses()


def test_note_prompt_is_buffered_and_rendered_in_the_header():
    sample, app = _app()
    try:
        main = _draw(app, sample.MAIN_ST)
        app.win.pick_pos = 0
        username = app.win.get_picked_context().item['username']

        main.note_ACTION()
        assert app.win.prompt_active is True
        assert app.note_item == username

        main.clear()
        main.draw_screen()
        assert any(text.startswith(f'Note for {username}: ')
                   and '│' in text for text in app.win.head.texts)

        for ch in 'hello':
            app.handle_key(ord(ch))
        assert app.win.prompt_active is True

        app.handle_key(10)  # ENTER

        assert app.win.prompt_active is False
        assert app.note_item is None
        assert app.notes[username] == 'hello'
        assert app.win.current_status[0] == f'✓ Note saved for {username}'
    finally:
        app.win.stop_curses()


# --- the theme picker's mono theme and NO_COLOR ----------------------------

def test_settle_appearance_applies_an_explicit_theme():
    sample, app = _app()
    try:
        theme = sample.settle_appearance(cli_theme='nord')
        assert theme == 'nord'
        assert Theme.get_current() == 'nord'
        assert Appearance.colors_enabled() is True
    finally:
        app.win.stop_curses()


def test_settle_appearance_canonicalizes_a_legacy_alias():
    sample, app = _app()
    try:
        theme = sample.settle_appearance(cli_theme='dark-mono')
        assert theme == 'dark'
        assert Theme.get_current() == 'dark'
    finally:
        app.win.stop_curses()


def test_settle_appearance_honors_the_no_color_convention(monkeypatch):
    sample, app = _app()
    try:
        monkeypatch.setenv('NO_COLOR', '1')
        theme = sample.settle_appearance()
        assert theme == 'mono'
        assert Appearance.colors_enabled() is False
        assert Theme.get_current() == 'mono'
    finally:
        app.win.stop_curses()


def test_the_theme_choices_are_the_library_themes_with_mono_last():
    _sample, app = _app()
    try:
        themes = Theme.list_all()
        assert themes[-1] == Theme.MONO
        # Color is on, so the option starts on the palette the window got.
        assert app.opts.theme == app.win.theme == 'default'
        assert app.opts.theme in themes
    finally:
        app.win.stop_curses()


def test_starting_with_mono_starts_on_the_mono_theme():
    Theme.set_active('mono')
    _sample, app = _app()
    try:
        assert app.opts.theme == Theme.MONO
        assert app.win.theme == Theme.MONO
        assert Appearance.colors_enabled() is False
    finally:
        app.win.stop_curses()


def test_choosing_mono_turns_color_off_and_a_palette_turns_it_back_on():
    _sample, app = _app()
    try:
        app.apply_theme_choice('nord')
        assert Appearance.colors_enabled() is True
        assert app.win.theme == 'nord'

        app.apply_theme_choice(Theme.MONO)
        assert Appearance.colors_enabled() is False
        assert app.opts.theme == Theme.MONO
        assert app.win.theme == Theme.MONO
    finally:
        app.win.stop_curses()


def test_the_theme_cycle_key_walks_from_the_last_palette_into_mono():
    sample, app = _app()
    try:
        app.stack.push(sample.THEME_ST, 0)  # 't' cycles on THEMES/HELP
        app.apply_theme_choice(Theme.list_all()[-2])
        assert Appearance.colors_enabled() is True

        app.handle_key(ord('t'))
        assert app.opts.theme == Theme.MONO
        assert Appearance.colors_enabled() is False

        app.handle_key(ord('t'))  # mono wraps to the first palette
        assert app.opts.theme == Theme.list_all()[0]
        assert Appearance.colors_enabled() is True
        assert app.win.theme == Theme.list_all()[0]
    finally:
        app.win.stop_curses()


def test_the_picker_header_names_the_mono_theme_and_its_swatches_follow():
    sample, app = _app()
    try:
        _draw(app, sample.THEME_ST)
        assert 'default' in app.win.head.texts[0]

        app.apply_theme_choice(Theme.MONO)
        _draw(app, sample.THEME_ST)

        # One name for one choice: no second 'Color:' line beside the theme.
        assert 'mono' in app.win.head.texts[0]
        assert all('Color:' not in row for row in app.win.head.texts)

        attrs = {}
        for text, runs in zip(app.win.body.texts, app.win.body.text_attrs,
                              strict=False):
            if not text:
                break  # the swatch block ends at the blank line
            if runs:
                attrs[text.split()[0]] = runs[0][0]
        assert attrs['SUCCESS'] == Appearance.MONO_ROLES[Theme.SUCCESS]
        assert attrs['DANGER'] == Appearance.MONO_ROLES[Theme.DANGER]
    finally:
        app.win.stop_curses()


def test_processed_rows_use_the_mono_attribute_without_asking_for_a_pair(monkeypatch):
    sample, app = _app()
    try:
        username = app.get_filtered_items()[0]['username']
        app.selected_items.add(username)
        app.apply_theme_choice(Theme.MONO)

        def _unexpected(pair):
            raise AssertionError(f'color pair {pair} used while color is off')

        monkeypatch.setattr(curses, 'color_pair', _unexpected)
        _draw(app, sample.MAIN_ST)

        row = next(index for index, text in enumerate(app.win.body.texts)
                   if 'Processed' in text)
        assert app.win.body.text_attrs[row][0][0] == (
            Appearance.MONO_ROLES[Theme.SUCCESS])
    finally:
        app.win.stop_curses()


def test_history_screen_draws_its_own_content_at_loop_time():
    sample, app = _app()
    try:
        history = app.screens[sample.HISTORY_ST]
        # The window is resolved through app.win, not captured at __init__.
        assert history.win is app.win

        username = app.get_filtered_items()[0]['username']
        app.selected_items.add(username)

        history.clear()
        history.draw_screen()

        assert app.win.pick_mode is False
        assert app.win.head.texts[0] == 'OPERATION HISTORY'
        assert any(username in text for text in app.win.body.texts)
    finally:
        app.win.stop_curses()
