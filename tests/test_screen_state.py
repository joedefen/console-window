"""Screen-owned content and per-screen pick/scroll state.

These cover the parts of the Screen overhaul that have no other witness:
adoption, the pointer-swap stack, per-screen view state, the ``head_line=False``
chrome fix, and the four-call loop from the plan (D3, D4, D10, D14).
"""

from types import SimpleNamespace

import pytest

import console_window.window as window_mod
from console_window import Screen, ScreenStack
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


@pytest.fixture(autouse=True)
def _headless_curses(monkeypatch):
    # ACS_* are unbound until initscr(); the separator/indicator path needs them
    # even when the backing screen is a recorder.
    for name in ('ACS_HLINE', 'ACS_VLINE'):
        if not hasattr(window_mod.curses, name):
            monkeypatch.setattr(window_mod.curses, name, '-', raising=False)


def _window(rows=24, cols=80, **opts):
    backend = HeadlessBackend(rows=rows, cols=cols)
    win = ConsoleWindow(opts=ConsoleWindowOpts(**opts), backend=backend,
                        singleton=False)
    return win, backend


class _App:
    def __init__(self, win):
        self.win = win
        self.opts = SimpleNamespace()


def test_a_screen_can_be_built_before_the_window_exists():
    # D11: Screen.win resolves through app.win at call time, not at __init__.
    app = SimpleNamespace(win=None)
    screen = Screen(app)
    assert screen.win is None

    win, _backend = _window()
    try:
        app.win = win
        assert screen.win is win
    finally:
        win.stop_curses()


def test_clear_adopts_the_screen_and_resets_only_content():
    win, _backend = _window()
    try:
        screen = Screen(_App(win))
        screen.add_body('stale')       # before adoption: still this screen's row
        screen.pick_pos = 4
        screen.scroll_pos = 2
        screen.free_scroll = True

        screen.clear()

        assert win.body.texts == []    # content reset
        assert win.pick_pos == 4       # the user's place survives the pass
        assert win.scroll_pos == 2
        assert win.free_scroll is True
        assert win.head.pad is not None  # adoption sized the pads

        screen.add_body('fresh')
        assert win.body.texts == ['fresh']
    finally:
        win.stop_curses()


def test_opts_seed_the_screen_once_and_then_the_screen_owns_the_fields():
    win, _backend = _window(pick_mode=True, pick_size=3, pick_range=[0, 4],
                            max_rows=7)
    try:
        screen = Screen(_App(win))
        screen.clear()
        assert screen.pick_mode is True
        assert screen.pick_size == 3
        assert screen.pick_range == [0, 4]
        assert screen.body.rows == 7

        # Later writes are per screen and never touch the shared options.
        screen.set_pick_range(1, 2)
        assert win.opts.pick_range == [0, 4]
        assert screen.pick_range == [1, 2]

        other = Screen(_App(win))
        other.clear()
        other.set_pick_range(None, None)
        assert screen.pick_range == [1, 2]
        assert other.pick_range is None
    finally:
        win.stop_curses()


def test_stack_activation_is_a_pointer_swap_not_a_copy():
    win, _backend = _window()
    try:
        app = _App(win)
        main = Screen(app)
        help_screen = Screen(app)
        stack = ScreenStack(win, app.opts, ('MAIN', 'HELP'),
                            {0: main, 1: help_screen})

        # Stack construction pushes HOME and adopts it.
        win.pick_pos, win.scroll_pos = 3, 2
        win.free_scroll = True
        main.add_body('main row')

        stack.push(1)
        assert win.pick_pos == 0 and win.scroll_pos == 0
        assert win.body.texts == []     # HELP's own content, not MAIN's

        win.pick_pos = 5
        win.set_pick_mode(True, 2)
        help_screen.add_body('help row')

        assert stack.pop() == 3          # the parent's row, from the frame
        assert win.pick_pos == 3 and win.scroll_pos == 2
        assert win.free_scroll is True
        assert win.body.texts == ['main row']
        assert win.pick_mode is False    # MAIN's mode, not HELP's
        assert main.pick_pos == 3
        assert help_screen.pick_pos == 5 and help_screen.pick_mode is True
    finally:
        win.stop_curses()


def test_stack_of_bare_numbers_uses_the_window_fallback_view():
    win, _backend = _window()
    try:
        obj = SimpleNamespace()
        stack = ScreenStack(win, obj, ('MAIN', 'HELP'))
        win.pick_pos, win.scroll_pos = 2, 1
        stack.push(1)
        # Entering a bare screen still starts at the top (the old behavior).
        assert win.pick_pos == 0 and win.scroll_pos == 0
        win.pick_pos = 6
        assert stack.pop() == 2
        # The fallback is one shared view: it is reset, not restored per frame.
        assert win.pick_pos == 0
    finally:
        win.stop_curses()


def test_head_line_false_paints_no_rule_indicator_or_status():
    win, backend = _window(rows=8, cols=20, head_line=False)
    try:
        screen = Screen(_App(win))
        screen.clear()
        screen.set_pick_mode(False)
        for i in range(20):
            screen.add_body(f'row {i}')
        win.scroll_pos = 5

        win.render()

        assert not backend.screen.calls_named('hline')
        assert not backend.screen.calls_named('addch')
        # Scroll mode anchors the pick at the top of the viewport, because
        # there is no indicator row to derive an offset from.
        assert win.pick_pos == win.scroll_pos
    finally:
        win.stop_curses()


def test_head_line_false_status_defers_with_one_warning():
    win, _backend = _window(rows=8, cols=20, head_line=False)
    try:
        with pytest.warns(UserWarning, match='no separator row'):
            assert win.status('deferred') is False
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            assert win.status('still deferred') is False
        assert not caught
    finally:
        win.stop_curses()


def test_the_four_call_loop_draws_a_bare_screen():
    # D14: no stack, no spinner, no render_pass().
    win, backend = _window()

    class Pager(Screen):
        def draw_screen(self):
            self.set_pick_mode(False)
            self.add_header('TITLE')
            self.add_body('one')
            self.add_body('two', resume=True)

    screen = Pager(_App(win))
    try:
        screen.clear()          # content reset for the new pass
        screen.draw_screen()    # add_header()/add_body() only
        win.render()            # paints, doupdate() diffs

        assert win.head.texts == ['TITLE']
        assert win.body.texts == ['onetwo']

        # A mid-pass render() must not erase content (D6).
        win.render()
        assert win.body.texts == ['onetwo']
        assert backend.pads  # pads were allocated
    finally:
        win.stop_curses()


def test_window_clear_still_resets_the_current_screen_for_4x_apps():
    win, _backend = _window()
    try:
        screen = Screen(_App(win))
        screen.clear()
        screen.add_body('row')
        win.clear()
        assert win.body.texts == []
        assert screen.body.texts == []
    finally:
        win.stop_curses()


def test_window_body_and_head_are_read_only_views():
    win, _backend = _window()
    try:
        screen = Screen(_App(win))
        screen.clear()
        screen.add_body('row')
        screen.add_header('head')
        assert list(win.body.texts) == ['row']
        assert list(win.head.texts) == ['head']
        with pytest.raises(AttributeError):
            win.body = SimpleNamespace()  # property, no setter
    finally:
        win.stop_curses()


def test_pick_mode_and_range_are_per_screen_through_the_window_proxy():
    win, _backend = _window()
    try:
        app = _App(win)
        main, help_screen = Screen(app), Screen(app)
        stack = ScreenStack(win, app.opts, ('MAIN', 'HELP'),
                            {0: main, 1: help_screen})
        win.set_pick_mode(True, 2)
        win.set_pick_range(0, 3)
        assert main.pick_mode is True and main.pick_size == 2
        assert main.pick_range == [0, 3]

        stack.push(1)
        assert help_screen.pick_mode is False
        help_screen.set_pick_mode(False)
        stack.pop()
        assert win.pick_mode is True
        assert win.pick_range == [0, 3]
    finally:
        win.stop_curses()
