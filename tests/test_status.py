"""ConsoleWindow.status(): the one-line message on the separator row."""

import curses

import pytest

import console_window.window as window_mod
from console_window import textwidth
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


@pytest.fixture(autouse=True)
def _headless_curses(monkeypatch):
    # curses.ACS_* are unbound until initscr(); the separator/indicator path
    # needs them even when rendering through HeadlessBackend.
    for name in ('ACS_HLINE', 'ACS_VLINE'):
        if not hasattr(window_mod.curses, name):
            monkeypatch.setattr(window_mod.curses, name, '-', raising=False)


def _window(rows=10, cols=40, **opts):
    backend = HeadlessBackend(rows=rows, cols=cols)
    win = ConsoleWindow(opts=ConsoleWindowOpts(**opts), backend=backend,
                        singleton=False)
    return win, backend


def _addstrs(scr):
    calls = []
    for _name, args, _kwargs in scr.calls_named('addstr'):
        text = args[2]
        if isinstance(text, (bytes, bytearray)):
            text = text.decode('utf-8')
        calls.append((args[0], args[1], text,
                      args[3] if len(args) > 3 else None))
    return calls


def _status_draws(win):
    row = win.head.view_cnt
    return [call for call in _addstrs(win.scr) if call[0] == row]


def _clear_calls(win):
    win.scr.calls.clear()


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# --- placement and interplay with the scroll indicator ----------------------

def test_status_is_painted_on_the_separator_row():
    win, _backend = _window(rows=10, cols=40)
    try:
        assert win.status('hello') is True
        win.render()

        draws = _status_draws(win)
        assert (win.head.view_cnt, 0, 'hello') in [(y, x, text)
                                                   for y, x, text, _a in draws]
    finally:
        win.stop_curses()


def test_status_leaves_one_cell_before_the_scroll_indicator():
    win, _backend = _window(rows=10, cols=40)
    try:
        for i in range(200):
            win.add_body(f'row {i:03d}')
        win.scroll_pos = 100
        win.status('status')

        win.render()

        ind_pos = win._scroll_indicator_col()
        assert ind_pos >= 0
        bot, cnt = win._scroll_indicator_span(ind_pos)

        draws = _status_draws(win)
        assert len(draws) == 1
        _y, x, text, _attr = draws[0]
        assert x == 0
        assert textwidth.string_width(text) <= bot - 2

        indicator = [(args[0], args[1], args[3])
                     for _name, args, _kw in win.scr.calls_named('addch')
                     if args[3] == curses.A_REVERSE]
        assert {(row, idx) for row, idx, _a in indicator} >= {
            (win.head.view_cnt, idx) for idx in range(bot, bot + cnt)}
    finally:
        win.stop_curses()


def test_long_status_is_truncated_to_the_free_span():
    win, _backend = _window(rows=8, cols=20)
    try:
        win.status('x' * 100)
        win.render()

        draws = _status_draws(win)
        assert len(draws) == 1
        assert textwidth.string_width(draws[0][2]) <= win.cols - 1
    finally:
        win.stop_curses()


# --- clearing and expiry ----------------------------------------------------

def test_clearing_status_restores_the_plain_separator():
    win, _backend = _window(rows=10, cols=40)
    try:
        win.status('gone')
        assert win.clear_status() is True
        assert win.current_status == ('', None)

        win.render()

        assert _status_draws(win) == []
    finally:
        win.stop_curses()


def test_status_timeout_expires_on_the_next_render(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(window_mod, 'time', clock)
    win, _backend = _window(rows=10, cols=40)
    try:
        win.status('temporary', timeout=1.0)
        win.render()
        assert len(_status_draws(win)) == 1

        clock.now += 2.0
        _clear_calls(win)
        win.render()

        assert _status_draws(win) == []
        assert win.current_status == ('', None)
    finally:
        win.stop_curses()


def test_status_survives_a_redraw():
    win, _backend = _window(rows=10, cols=40)
    try:
        win.status('persistent')

        win.render(redraw=True)
        assert len(_status_draws(win)) == 1
        _clear_calls(win)

        win.render(redraw=True)
        assert len(_status_draws(win)) == 1
        assert _status_draws(win)[0][2] == 'persistent'
    finally:
        win.stop_curses()


# --- levels and attributes --------------------------------------------------

def test_status_level_selects_the_attribute():
    expected = {
        'info': curses.A_DIM,
        'warn': curses.A_BOLD,
        'error': curses.A_BOLD | curses.A_REVERSE,
    }
    win, _backend = _window(rows=10, cols=40)
    try:
        for level, attr in expected.items():
            win.status('message', level=level)
            assert win.current_status == ('message', attr)
            _clear_calls(win)
            win.render()
            draws = _status_draws(win)
            assert len(draws) == 1
            assert draws[0][3] == attr

        # attr= overrides the level for that message only.
        win.status('override', level='error', attr=curses.A_UNDERLINE)
        assert win.current_status == ('override', curses.A_UNDERLINE)
        _clear_calls(win)
        win.render()
        assert _status_draws(win)[0][3] == curses.A_UNDERLINE
    finally:
        win.stop_curses()


def test_unknown_level_falls_back_to_info():
    win, _backend = _window(rows=10, cols=40)
    try:
        assert win.status('typo', level='not-a-level') is True
        assert win.current_status == ('typo', curses.A_DIM)
    finally:
        win.stop_curses()


# --- deferred messages and rendering discipline -----------------------------

def test_status_without_a_separator_row_is_stored_but_not_drawn():
    win, backend = _window(rows=2, cols=40)
    try:
        # Simulate a header band that has consumed every row: there is no
        # separator row to paint on, so the call reports the message deferred.
        win.head.view_cnt = win.rows
        assert win.status('later') is False
        assert win.current_status[0] == 'later'

        # A later resize reveals the row; the stored message is drawn then.
        win.scr._rows = 10
        backend.rows = 10
        win.calc()
        assert win.head.view_cnt < win.rows

        win.render()
        assert any(text == 'later' for _y, _x, text, _a in _status_draws(win))
    finally:
        win.stop_curses()


def test_status_does_not_render_by_itself():
    win, _backend = _window(rows=10, cols=40)
    try:
        renders = []
        win.render = lambda redraw=False: renders.append(redraw)

        win.status('deferred')

        assert renders == []
    finally:
        win.stop_curses()
