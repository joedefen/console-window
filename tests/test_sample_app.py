"""Headless smoke tests for SampleApp.

SampleApp is the package's worked example, so it should not be allowed to rot
silently: these tests construct it against a HeadlessBackend, draw every screen,
and assert the wiring (scoped keys, action handlers, the router) still holds.
No TTY is required.
"""

import curses

import pytest

from console_window import Appearance, Theme
from console_window.backend import HeadlessBackend


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors() and curses.color_pair() raise until initscr() has
    # succeeded, and the sample app's drawing code calls both, so stand them in.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)


@pytest.fixture(autouse=True)
def _appearance_state(monkeypatch):
    # The color switch and the process theme are process state; the sample
    # reads both when it seeds its theme option, so never leak a test's choice.
    monkeypatch.setattr(Appearance, '_COLORS_ENABLED', True)
    monkeypatch.setattr(Theme, '_current', None)


def _app(rows=40, cols=120):
    import SampleApp as sample

    # The suite runs several app instances; keep the process in per-instance
    # window mode (the first construction latches it).
    return sample, sample.SampleApp(backend=HeadlessBackend(rows=rows, cols=cols),
                                    singleton=False)


def test_sample_app_builds_headless_and_draws_every_screen():
    sample, app = _app()
    try:
        for num in (sample.MAIN_ST, sample.HELP_ST, sample.HISTORY_ST,
                    sample.THEME_ST):
            app.win.clear()
            app.screens[num].draw_screen()
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
        app.screens[sample.MAIN_ST].draw_screen()
        normal = app.win.body.row_cnt

        app.win.clear()
        app.opts.stress = True
        app.screens[sample.MAIN_ST].draw_screen()
        assert app.win.body.row_cnt > normal
        # Nothing is dropped: the pads are viewport-sized, the 2000 filler rows
        # live in the model, and the default max_rows ceiling is far above them.
        assert app.win.rows_dropped == 0
    finally:
        app.win.stop_curses()


# --- the 2.1 in-place prompt, status and BasicTextScreen -------------------

def test_confirm_prompt_consumes_every_key_and_reports_status():
    sample, app = _app()
    try:
        main = app.screens[sample.MAIN_ST]
        main.draw_screen()
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
        main = app.screens[sample.MAIN_ST]
        main.draw_screen()
        app.win.pick_pos = 0

        main.select_ACTION()
        app.win.clear()
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
        main = app.screens[sample.MAIN_ST]
        main.draw_screen()
        app.win.pick_pos = 0
        username = app.win.get_picked_context().item['username']

        main.note_ACTION()
        assert app.win.prompt_active is True
        assert app.note_item == username

        app.win.clear()
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


# --- the theme picker's mono choice and --no-color -------------------------

def test_settle_appearance_puts_no_color_over_theme():
    sample, app = _app()
    try:
        theme, colors = sample.settle_appearance(cli_theme='nord',
                                                 no_color=True)
        assert (theme, colors) == ('nord', False)
        assert Appearance.colors_enabled() is False
        assert Theme.get_current() == 'nord'
    finally:
        app.win.stop_curses()


def test_settle_appearance_honors_the_no_color_convention(monkeypatch):
    sample, app = _app()
    try:
        monkeypatch.setenv('NO_COLOR', '1')
        theme, colors = sample.settle_appearance()
        assert (theme, colors) == ('', False)
        assert Appearance.colors_enabled() is False
        assert Theme.get_current() is None
    finally:
        app.win.stop_curses()


def test_the_theme_choices_include_the_demo_mono_pseudo_theme():
    sample, app = _app()
    try:
        assert sample.MONO_THEME in sample.THEME_CHOICES
        # Color is on, so the option starts on the palette the window got.
        assert app.opts.theme == app.win.theme == 'default'
        assert app.opts.theme in sample.THEME_CHOICES
    finally:
        app.win.stop_curses()


def test_starting_with_color_off_starts_on_the_mono_choice():
    Appearance.set_colors_enabled(False)
    sample, app = _app()
    try:
        assert app.opts.theme == sample.MONO_THEME
        # The palette is still installed; mono is only the color switch.
        assert app.win.theme == 'default'
    finally:
        app.win.stop_curses()


def test_choosing_mono_turns_color_off_and_a_palette_turns_it_back_on():
    sample, app = _app()
    try:
        app.apply_theme_choice('nord')
        assert Appearance.colors_enabled() is True
        assert app.win.theme == 'nord'

        app.apply_theme_choice(sample.MONO_THEME)
        assert Appearance.colors_enabled() is False
        assert app.opts.theme == sample.MONO_THEME
        # mono is a mode, not a palette: the installed theme is untouched.
        assert app.win.theme == 'nord'
    finally:
        app.win.stop_curses()


def test_the_theme_cycle_key_walks_from_the_last_palette_into_mono():
    sample, app = _app()
    try:
        app.stack.push(sample.THEME_ST, 0)  # 't' cycles on THEMES/HELP
        app.apply_theme_choice(Theme.list_all()[-1])
        assert Appearance.colors_enabled() is True

        app.handle_key(ord('t'))
        assert app.opts.theme == sample.MONO_THEME
        assert Appearance.colors_enabled() is False

        app.handle_key(ord('t'))  # mono wraps to the first palette
        assert app.opts.theme == Theme.list_all()[0]
        assert Appearance.colors_enabled() is True
        assert app.win.theme == Theme.list_all()[0]
    finally:
        app.win.stop_curses()


def test_the_picker_header_names_the_mono_choice_and_its_swatches_follow():
    sample, app = _app()
    try:
        app.win.clear()
        app.screens[sample.THEME_ST].draw_screen()
        assert 'default' in app.win.head.texts[0]

        app.apply_theme_choice(sample.MONO_THEME)
        app.win.clear()
        app.screens[sample.THEME_ST].draw_screen()

        # One name for one choice: no second 'Color:' line beside the theme.
        assert 'mono' in app.win.head.texts[0]
        assert all('Color:' not in row for row in app.win.head.texts)

        attrs = {}
        for text, runs in zip(app.win.body.texts, app.win.body.text_attrs,
                              strict=False):
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
        app.apply_theme_choice(sample.MONO_THEME)

        def _unexpected(pair):
            raise AssertionError(f'color pair {pair} used while color is off')

        monkeypatch.setattr(curses, 'color_pair', _unexpected)
        app.win.clear()
        app.screens[sample.MAIN_ST].draw_screen()

        row = next(index for index, text in enumerate(app.win.body.texts)
                   if 'Processed' in text)
        assert app.win.body.text_attrs[row][0][0] == (
            Appearance.MONO_ROLES[Theme.SUCCESS])
    finally:
        app.win.stop_curses()


def test_history_screen_is_a_basic_text_screen_resolved_at_draw_time():
    sample, app = _app()
    try:
        history = app.screens[sample.HISTORY_ST]
        assert isinstance(history.text_screen, sample.BasicTextScreen)
        # Created before the window existed; draw_screen() resolves app.win.
        assert history.text_screen.win is None

        username = app.get_filtered_items()[0]['username']
        app.selected_items.add(username)

        history.draw_screen()

        # The stale ``win`` left by Screen.__init__ is still None; the rows
        # landed on the window resolved from app.win at draw time.
        assert history.text_screen.win is None
        assert app.win.pick_mode is False
        assert app.win.head.texts[0] == 'OPERATION HISTORY'
        assert any(username in text for text in app.win.body.texts)
    finally:
        app.win.stop_curses()
