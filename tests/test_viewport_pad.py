"""Scheme B: body/head pads are viewport-sized blit buffers.

These tests pin the properties that make `opts.body_rows` a hint rather than a
storage limit: pad size tracks the terminal, the visible page is painted into
pad row 0 on every frame, and `draw()` spans are replayed with their attributes
even when the row was written long before it scrolled into view.
"""

import curses

import pytest

import console_window.window as window_mod
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
    win = ConsoleWindow(opts=ConsoleWindowOpts(**opts), backend=backend, singleton=False)
    return win, backend


def _addstrs(pad):
    calls = pad.calls_named('addstr')
    out = []
    for _name, args, _kw in calls:
        text = args[2]
        if isinstance(text, (bytes, bytearray)):
            text = text.decode('utf-8')
        out.append((args[0], args[1], text, args[3] if len(args) > 3 else None))
    return out


def _row_texts(pad):
    return {y: text for y, x, text, _attr in _addstrs(pad) if x == 0}


def test_pads_are_viewport_sized_regardless_of_body_rows():
    win, backend = _window(rows=10, cols=40, body_rows=5000)
    try:
        assert len(backend.pads) == 2
        assert win.body.pad_rows == 10
        assert win.body.pad_cols == 39
        assert win.head.pad_rows == 10
    finally:
        win.stop_curses()


def test_render_paints_the_visible_page_into_pad_row_zero():
    win, _backend = _window(rows=8, cols=40, head_line=False)
    try:
        for i in range(100):
            win.add_body(f'row {i:03d}')
        win.scroll_pos = 50
        win.render()

        rows = _row_texts(win.body.pad)
        assert 'row 050' in rows[0]
        assert 'row 057' in rows[7]
        assert not any('row 000' in text for text in rows.values())
    finally:
        win.stop_curses()


def test_draw_span_is_replayed_with_its_attribute():
    win, _backend = _window(rows=6, cols=30, head_line=False)
    try:
        win.draw(1, 2, 'X', curses.A_BOLD)
        win.render()

        assert any(y == 1 and x == 2 and text == 'X' and attr == curses.A_BOLD
                   for y, x, text, attr in _addstrs(win.body.pad))
    finally:
        win.stop_curses()


def test_draw_on_an_offscreen_row_survives_until_it_is_scrolled_to():
    win, _backend = _window(rows=6, cols=30, head_line=False)
    try:
        for i in range(40):
            win.add_body(f'r{i}')
        win.draw(30, 5, 'ZZ', curses.A_BOLD)

        win.render()
        assert not any(text == 'ZZ' for _y, _x, text, _a in _addstrs(win.body.pad))

        win.scroll_pos = 30
        win.render()
        assert any(y == 0 and x == 5 and text == 'ZZ' and attr == curses.A_BOLD
                   for y, x, text, attr in _addstrs(win.body.pad))
    finally:
        win.stop_curses()


def test_resize_reallocates_the_pads_to_the_new_viewport():
    win, backend = _window(rows=10, cols=40)
    try:
        backend.screen._rows = 12
        backend.screen._cols = 30
        win.render()

        assert win.rows == 12
        assert win.body.pad_rows == 12
        assert win.body.pad_cols == 29
        assert len(backend.pads) == 4  # two original, two replacements
    finally:
        win.stop_curses()


def test_pick_highlight_follows_the_viewport_without_moving_the_pick():
    # The old pad-as-storage model kept the reverse-video row inside the pad, so
    # scrolling moved it on screen for free.  Painting statelessly must apply
    # the pick attribute wherever the picked row currently lands.
    win, _backend = _window(rows=6, cols=30, head_line=False, pick_mode=True)
    try:
        for i in range(40):
            win.add_body(f'row {i}')
        win.pick_pos = 5

        win.render()
        assert any(text.startswith('row 5') and attr & curses.A_REVERSE
                   for y, _x, text, attr in _addstrs(win.body.pad) if y == 5)

        win.scroll_pos = 2
        win.render()
        assert any(text.startswith('row 5') and attr & curses.A_REVERSE
                   for y, _x, text, attr in _addstrs(win.body.pad) if y == 3)
    finally:
        win.stop_curses()


def test_clear_drops_recorded_draw_spans():
    win, _backend = _window(rows=6, cols=30, head_line=False)
    try:
        win.draw(0, 0, 'X')
        assert win.body.drawn
        win.clear()
        assert win.body.drawn == {}
        assert win.body.row_cnt == 0
    finally:
        win.stop_curses()
