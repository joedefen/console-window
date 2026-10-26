import curses
from types import SimpleNamespace

from console_window import (
    BasicHelpScreen,
    BasicTextScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    HeaderLine,
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


# --- BasicTextScreen -------------------------------------------------------

class RecordingWin:
    def __init__(self):
        self.calls = []
        self.pick_modes = []

    def set_pick_mode(self, on=True, pick_size=1):
        self.pick_modes.append(on)

    def add_header(self, text, attr=None, resume=False, context=None):
        self.calls.append(('header', text, attr))

    def add_header_line(self, line, mode='Underline',
                        search_pattern_attr=None, line_attr=None):
        self.calls.append(('header_line', str(line), None))

    def add_body(self, text, attr=None, resume=False, context=None):
        self.calls.append(('body', text, attr))


def test_text_screen_adds_headers_before_body():
    win = RecordingWin()
    screen = BasicTextScreen(SimpleNamespace(win=win), lines=['one'],
                             head='Title')

    screen.draw_screen()

    assert win.calls == [('header', 'Title', None), ('body', 'one', None)]
    assert win.pick_modes == [False]


def test_text_screen_adds_lines_in_order_with_attrs():
    win = RecordingWin()
    screen = BasicTextScreen(
        SimpleNamespace(win=win),
        lines=[('bold', curses.A_BOLD), 'plain', ('dim', curses.A_DIM)],
    )

    screen.draw_screen()

    assert win.calls == [
        ('body', 'bold', curses.A_BOLD),
        ('body', 'plain', None),
        ('body', 'dim', curses.A_DIM),
    ]


def test_text_screen_set_text_replaces_content():
    win = RecordingWin()
    screen = BasicTextScreen(SimpleNamespace(win=win), lines=['old'],
                             head='Old')

    screen.set_text(lines=['new'], head='New')
    screen.draw_screen()

    assert win.calls == [('header', 'New', None), ('body', 'new', None)]


def test_text_screen_accepts_headerline_and_iterables():
    win = RecordingWin()
    line = HeaderLine().text('Title').key('x')
    screen = BasicTextScreen(SimpleNamespace(win=win), head=[line, 'Sub'])

    screen.draw_screen()

    assert win.calls == [
        ('header_line', 'Titlex', None),
        ('header', 'Sub', None),
    ]


def test_text_screen_disables_pick_mode():
    win = _make_window()
    try:
        win.set_pick_mode(True)
        screen = BasicTextScreen(SimpleNamespace(win=win), lines=['row'])

        screen.draw_screen()

        assert win.pick_mode is False
        assert win.body.texts == ['row']
    finally:
        win.stop_curses()


def test_text_screen_tolerates_empty_input():
    win = RecordingWin()
    screen = BasicTextScreen(SimpleNamespace(win=win))

    screen.draw_screen()

    assert win.calls == []


def test_text_screen_resolves_the_window_at_draw_time():
    app = SimpleNamespace(win=None)
    screen = BasicTextScreen(app, lines=['row'])
    assert screen.win is None

    win = RecordingWin()
    app.win = win
    screen.draw_screen()

    assert win.calls == [('body', 'row', None)]
