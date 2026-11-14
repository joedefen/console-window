import curses
from types import SimpleNamespace

import pytest

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


def test_from_screens_names_objects_and_accepts_object_or_name_push():
    win = _make_window()
    try:
        app = SimpleNamespace(win=win)
        one = BasicTextScreen(app, lines=['one'])
        one.name = 'ONE'
        two = BasicTextScreen(app, lines=['two'])
        two.name = 'TWO'

        stack = ScreenStack.from_screens(win, SimpleNamespace(), [one, two])

        assert stack.screens == ('ONE', 'TWO')
        assert stack.is_curr('ONE')
        assert stack.get_curr_obj() is one

        # push() accepts the Screen object and its name, not just its number.
        assert stack.push(two, 0) == 0
        assert stack.is_curr('TWO')
        assert stack.get_curr_obj() is two
        assert stack.pop() == 0
        assert stack.is_curr('ONE')

        assert stack.push('TWO', 0) == 0
        assert stack.is_curr('TWO')
    finally:
        win.stop_curses()


def test_from_screens_falls_back_to_the_class_name():
    win = _make_window()
    try:
        screen = BasicTextScreen(SimpleNamespace(win=win))
        stack = ScreenStack.from_screens(win, SimpleNamespace(), [screen])
        assert stack.screens == ('BasicTextScreen',)
    finally:
        win.stop_curses()


def test_push_rejects_an_unknown_name_or_object():
    win = _make_window()
    try:
        screen = BasicTextScreen(SimpleNamespace(win=win))
        stack = ScreenStack.from_screens(win, SimpleNamespace(), [screen])
        with pytest.raises(ValueError, match='no screen named'):
            stack.push('NOPE')
        with pytest.raises(ValueError, match='not registered'):
            stack.push(BasicTextScreen(SimpleNamespace(win=win)))
    finally:
        win.stop_curses()


def test_basic_help_screen_resolves_window_created_after_construction():
    # SampleApp creates Screen objects before its ConsoleWindow, so the window
    # captured by Screen.__init__ is None. BasicHelpScreen.draw_screen() must
    # read the current app.win instead of that stale attribute.
    app = SimpleNamespace(win=None)
    screen = BasicHelpScreen(app)
    assert screen.win is None

    win = _make_window()
    try:
        app.win = win
        stack = ScreenStack(win, SimpleNamespace(), ('HELP',), {0: screen})
        OptionSpinner(stack=stack)
        screen.clear()      # the loop's first call: adopts the screen
        screen.draw_screen()
        assert win.head.texts
        assert win.pick_mode is False
    finally:
        win.stop_curses()


def _draw_help_notes(paragraphs=(), *, separator=None, display_notes=False):
    """Draw a help screen with *paragraphs* and return (win, rows, attrs)."""
    win = _make_window()
    screen = BasicHelpScreen(SimpleNamespace(win=win))
    screen.extra_help_paragraphs = lambda: tuple(paragraphs)
    if separator is not None:
        screen.notes_separator = separator
    screen.show_display_notes = display_notes
    OptionSpinner(
        stack=ScreenStack(win, SimpleNamespace(), ('HELP',), {0: screen}))
    screen.clear()
    screen.draw_screen()
    return win, win.body.texts, win.body.text_attrs


def test_help_notes_are_bulleted_instructions_after_a_separator():
    long_paragraph = (
        'This paragraph is long enough to wrap onto a second row, so the '
        'hanging indent has to line up under the text and not under the bullet.')
    win, rows, attrs = _draw_help_notes([long_paragraph])
    try:
        assert rows[0] == '---------- Instructions ----------'
        assert rows[1].startswith(' \u25c6 ')
        assert len(rows) > 2                       # it really wrapped
        assert all(row.startswith('   ') and not row.startswith(' \u25c6 ')
                   for row in rows[2:])
        assert all(attr == curses.A_NORMAL for run in attrs for attr, _ in run)
    finally:
        win.stop_curses()


def test_help_notes_fall_back_to_the_display_note():
    win, rows, _attrs = _draw_help_notes(display_notes=True)
    try:
        assert rows[0] == '---------- Instructions ----------'
        assert rows[1].startswith(' \u25c6 ')
    finally:
        win.stop_curses()


def test_help_notes_are_omitted_when_there_is_nothing_to_say():
    win, rows, _attrs = _draw_help_notes()
    try:
        assert rows == []
    finally:
        win.stop_curses()


def test_the_notes_separator_can_be_turned_off():
    win, rows, _attrs = _draw_help_notes(['short note'], separator='')
    try:
        assert rows[0].startswith(' \u25c6 ')
    finally:
        win.stop_curses()


def test_the_stack_numbers_links_and_supplies_the_spinner():
    win = _make_window()
    try:
        app = SimpleNamespace(win=win)
        screen = BasicTextScreen(app, lines=['row'])
        stack = ScreenStack.from_screens(win, SimpleNamespace(), [screen])

        assert screen.num == 0
        assert screen.stack is stack
        assert screen.get_spinner() is None

        spin = OptionSpinner(stack=stack)
        assert screen.get_spinner() is spin
    finally:
        win.stop_curses()


def test_escape_action_pops_and_quit_action_exits():
    win = _make_window()
    try:
        app = SimpleNamespace(win=win)
        main = BasicTextScreen(app, lines=['main'])
        other = BasicTextScreen(app, lines=['other'])
        stack = ScreenStack.from_screens(win, SimpleNamespace(), [main, other])

        stack.push(other)
        assert stack.curr.num == 1
        stack.get_curr_obj().escape_ACTION()
        assert stack.curr.num == 0

        main.escape_ACTION()  # home: a no-op, not an error
        assert stack.curr.num == 0

        with pytest.raises(SystemExit):
            main.quit_ACTION()
    finally:
        win.stop_curses()


# --- BasicTextScreen -------------------------------------------------------

class RecordingWin:
    """Stands in for the window's private content implementation.

    Screens own their content and delegate to these seam methods with their
    own namespace, so a recording fake is enough to test the draw order.
    """

    def __init__(self):
        self.calls = []
        self.prompt_line = SimpleNamespace(active=False)

    def get_pad_width(self):
        return 78

    def _add(self, ns, text, attr=None, resume=False, context=None, *,
             is_body=False):
        self.calls.append(('body' if is_body else 'header', text, attr))

    def _add_header_line(self, ns, line, mode='Underline',
                         search_pattern_attr=None, line_attr=None):
        self.calls.append(('header_line', str(line), None))

    def _add_fancy_header(self, ns, line, mode='Underline',
                          search_pattern_attr=None, line_attr=None):
        self.calls.append(('fancy', str(line), None))


def test_text_screen_adds_headers_before_body():
    win = RecordingWin()
    screen = BasicTextScreen(SimpleNamespace(win=win), lines=['one'],
                             head='Title')

    screen.draw_screen()

    assert win.calls == [('header', 'Title', None), ('body', 'one', None)]
    assert screen.pick_mode is False


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

        screen.clear()
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
