import curses
from types import SimpleNamespace

import pytest

import console_window.window as window_mod
from console_window import textwidth as tw
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow

CJK = '世'  # 2 display cells


class FakePad:
    def __init__(self):
        self.calls = []
        self._yx = (0, 0)

    def addstr(self, *args, **kwargs):
        self.calls.append(args)
        if isinstance(args[0], int):
            payload = args[2]
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode('utf-8')
            self._yx = (args[0], args[1] + tw.string_width(payload))

    def addch(self, *args, **kwargs):
        pass

    def getyx(self):
        return self._yx

    def clear(self):
        pass


class CaptureScreen:
    def __init__(self, rows=24, cols=40):
        self._rows = rows
        self._cols = cols
        self.drawn = []

    def getmaxyx(self):
        return (self._rows, self._cols)

    def timeout(self, ms):
        pass

    def getch(self):
        return -1

    def clear(self):
        pass

    def addstr(self, *args):
        self.drawn.append(args)

    def noutrefresh(self):
        pass

    def refresh(self):
        pass


@pytest.fixture(autouse=True)


def _stub_curses(monkeypatch):
    monkeypatch.setattr(window_mod.curses, 'doupdate', lambda: None)
    monkeypatch.setattr(window_mod.curses, 'is_term_resized', lambda *a: False)


def make_window(cols=10, body_cols=10):
    win = object.__new__(ConsoleWindow)
    win._backend = HeadlessBackend(cols, body_cols)
    win.opts = ConsoleWindowOpts()
    win.pick_mode = False
    win.cols = cols
    win.body_cols = body_cols
    for name in ('head', 'body'):
        setattr(win, name, SimpleNamespace(
            pad=FakePad(), rows=50, cols=body_cols, row_cnt=0,
            texts=[], text_attrs=[], contexts=[]))
    return win

# --- _add truncation --------------------------------------------------------

def test_add_body_truncates_by_display_cells():
    win = make_window(cols=5, body_cols=10)
    win.add_body(CJK * 5)  # 10 cells of content, only 5 columns available

    assert win.body.texts[0] == CJK * 2  # two wide chars (4 cells); a third won't fit
    assert tw.string_width(win.body.texts[0]) <= 5


def test_add_header_attr_run_counts_code_points():
    win = make_window(cols=5, body_cols=10)
    win.add_header(CJK * 5, attr=curses.A_BOLD)

    _attr, count = win.head.text_attrs[0][0]
    assert count == len(win.head.texts[0])


def test_add_body_truncates_to_pad_width_not_terminal_width():
    # body_cols (8) is narrower than cols-1 (9): get_pad_width() must win, so a
    # fresh line is stored no wider than the pad (was previously truncated to the
    # raw terminal width, self.cols == 10).
    win = make_window(cols=10, body_cols=8)
    win.add_body('x' * 20)
    assert win.body.texts[0] == 'x' * 8
    assert tw.string_width(win.body.texts[0]) <= win.get_pad_width()


def test_add_body_reserves_last_terminal_column():
    # get_pad_width() is cols-1 even when the pad is wider: the last terminal
    # column is reserved, matching draw()/highlight_picked().
    win = make_window(cols=10, body_cols=50)
    win.add_body('x' * 20)
    assert win.body.texts[0] == 'x' * 9
    assert tw.string_width(win.body.texts[0]) == win.get_pad_width()

# --- draw padding -----------------------------------------------------------

def test_draw_pads_to_cells():
    win = make_window(cols=8, body_cols=8)
    win.draw(0, 0, CJK, width=6)

    y, x, data, _attr = win.body.pad.calls[-1]
    text = data.decode('utf-8')
    assert (y, x) == (0, 0)
    assert tw.string_width(text) == 6


def test_draw_leftpad_pads_on_the_left():
    win = make_window(cols=8, body_cols=8)
    win.draw(0, 0, CJK, width=4, leftpad=True)

    text = win.body.pad.calls[-1][2].decode('utf-8')
    assert text == '  ' + CJK

# --- pick-range highlighting ------------------------------------------------

def test_highlight_range_covers_leading_wide_char():
    win = make_window(cols=10, body_cols=10)
    pad = FakePad()
    win._draw_line_with_attrs(pad, 0, 0, CJK + 'x', None,
                              extra_attr=curses.A_REVERSE, extra_attr_range=(0, 2))

    assert (0, 0, CJK, curses.A_REVERSE) in pad.calls
    assert (0, 2, 'x', curses.A_NORMAL) in pad.calls


def test_highlight_range_covers_trailing_wide_char():
    win = make_window(cols=10, body_cols=10)
    pad = FakePad()
    win._draw_line_with_attrs(pad, 0, 0, 'x' + CJK, None,
                              extra_attr=curses.A_REVERSE, extra_attr_range=(1, 3))

    assert (0, 0, 'x', curses.A_NORMAL) in pad.calls
    assert (0, 1, CJK, curses.A_REVERSE) in pad.calls


def test_highlight_range_with_attr_runs_is_cell_based():
    win = make_window(cols=10, body_cols=10)
    pad = FakePad()
    attrs = [(curses.A_BOLD, 1), (curses.A_NORMAL, 1)]  # per code point: 'a', '世'
    win._draw_line_with_attrs(pad, 0, 0, 'a' + CJK, attrs,
                              extra_attr=curses.A_REVERSE, extra_attr_range=(1, 3))

    # 'a' keeps its bold run un-highlighted; the wide char gets the extra attr.
    assert (0, 0, 'a', curses.A_BOLD) in pad.calls
    assert (0, 1, CJK, curses.A_NORMAL | curses.A_REVERSE) in pad.calls

# --- flash box --------------------------------------------------------------

def test_flash_wide_message_box_is_aligned():
    scr = CaptureScreen(cols=20)
    win = object.__new__(ConsoleWindow)
    win.scr = scr
    win._backend = HeadlessBackend(scr._rows, scr._cols)
    win.opts = ConsoleWindowOpts()
    win.rows = scr._rows
    win.cols = scr._cols
    win.pending_keys = set()
    win.render = lambda redraw=False: None

    win.flash(CJK * 2, duration=0.0)  # 4 display cells

    body = next(a for a in scr.drawn if isinstance(a[0], int) and a[2].startswith('│'))
    assert body[2] == '│' + CJK * 2 + '│'
