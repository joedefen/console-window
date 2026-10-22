from types import SimpleNamespace

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    OptionSpinner,
    ScreenStack,
)
from console_window.backend import HeadlessBackend


def _make_window():
    return ConsoleWindow(
        opts=ConsoleWindowOpts(head_rows=8, body_rows=8),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )


def test_act_in_consumes_one_flag_and_tolerates_missing_flags():
    win = _make_window()
    try:
        obj = SimpleNamespace(flag=True)
        stack = ScreenStack(win, obj, ('MAIN', 'OTHER'))

        # A missing flag is a no-op, not an AttributeError (and is not created).
        assert stack.act_in('missing') is False
        assert not hasattr(obj, 'missing')

        # Set on the current screen: returns True exactly once.
        assert stack.act_in('flag', 'MAIN') is True
        assert obj.flag is False
        assert stack.act_in('flag') is False

        # A set flag is still consumed when the screen filter does not match.
        obj.flag = True
        assert stack.act_in('flag', 'OTHER') is False
        assert obj.flag is False
        assert stack.is_curr('MAIN') is True
        assert stack.is_curr(('MAIN', 'OTHER')) is True
        assert stack.is_curr('OTHER') is False
    finally:
        win.stop_curses()


def test_basic_help_screen_resolves_window_created_after_construction():
    # SampleApp creates Screen objects before its ConsoleWindow, so the window
    # captured by Screen.__init__ is None. BasicHelpScreen.draw_screen() must
    # read the current app.win instead of that stale attribute.
    app = SimpleNamespace(win=None, spin=OptionSpinner())
    screen = BasicHelpScreen(app)
    assert screen.win is None

    win = _make_window()
    try:
        app.win = win
        screen.draw_screen()
        assert win.head.texts
        assert win.pick_mode is False
    finally:
        win.stop_curses()
