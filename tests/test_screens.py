from types import SimpleNamespace

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    OptionSpinner,
)
from console_window.backend import HeadlessBackend


def _make_window():
    return ConsoleWindow(
        opts=ConsoleWindowOpts(head_rows=8, body_rows=8),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )


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
