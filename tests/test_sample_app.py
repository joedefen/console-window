"""Headless smoke tests for SampleApp.

SampleApp is the package's worked example, so it should not be allowed to rot
silently: these tests construct it against a HeadlessBackend, draw every screen,
and assert the wiring (scoped keys, action handlers, the router) still holds.
No TTY is required.
"""

import curses

import pytest

from console_window.backend import HeadlessBackend


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors() and curses.color_pair() raise until initscr() has
    # succeeded, and the sample app's drawing code calls both, so stand them in.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)


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
