"""The ASCII-mode invariant: every cell the library paints is plain ASCII."""

from console_window import ConsoleWindow, ConsoleWindowOpts, InlineConfirmation
from console_window.backend import HeadlessBackend
from console_window.glyphs import set_ascii


def _window(**opts):
    return ConsoleWindow(
        opts=ConsoleWindowOpts(**opts),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )


def _painted_text(win):
    """Every string the window handed to the screen or a pad."""
    texts = []
    surfaces = [win._backend.screen, *win._backend.pads]
    for surface in surfaces:
        for _name, args, _kwargs in surface.calls:
            texts.extend(arg for arg in args if isinstance(arg, str))
    return texts


def test_rows_are_ascii_in_ascii_mode():
    win = _window(ascii=True)
    try:
        win.add_header('header \u2500 with \u2502 art')
        win.add_body('body \u2b9e and \u2192')
        rows = win.head.texts + win.body.texts
        assert rows
        assert all(row.isascii() for row in rows)
    finally:
        win.stop_curses()


def test_rows_keep_their_unicode_in_unicode_mode():
    win = _window(ascii=False)
    try:
        win.add_body('body \u2b9e and \u2192')
        assert any('\u2b9e' in row for row in win.body.texts)
    finally:
        win.stop_curses()


def test_content_survives_both_modes():
    win = _window(ascii=True)
    try:
        win.add_body('Gr\u00fc\u00dfe aus K\u00f6ln')
        assert win.body.texts == ['Gr\u00fc\u00dfe aus K\u00f6ln']
    finally:
        win.stop_curses()


def test_drawn_text_is_transliterated_before_it_is_measured():
    win = _window(ascii=True)
    try:
        win.add_body('x' * 70)
        win.draw(0, 0, '\u2b9e tail', width=10)
        assert win.body.texts[0].isascii()
    finally:
        win.stop_curses()


def test_the_flash_frame_degrades_to_ascii(monkeypatch):
    # flash() repaints the pads on the way out, and a full render needs
    # curses.ACS_* (which only exist after initscr()); the frame is what this
    # test is about, so the repaint is stubbed.
    monkeypatch.setattr(ConsoleWindow, 'render', lambda self, redraw=False: None)
    win = _window(ascii=True)
    try:
        win.flash('done', duration=0)
        painted = [text for text in _painted_text(win) if text]
        assert painted
        assert all(text.isascii() for text in painted), painted
        assert any('+' in text for text in painted)
    finally:
        win.stop_curses()


def test_the_flash_frame_is_box_drawing_in_unicode_mode(monkeypatch):
    monkeypatch.setattr(ConsoleWindow, 'render', lambda self, redraw=False: None)
    win = _window(ascii=False)
    try:
        win.flash('done', duration=0)
        assert any('\u250c' in text for text in _painted_text(win))
    finally:
        win.stop_curses()


def test_the_status_line_degrades():
    win = _window(ascii=True)
    try:
        win.status('loaded \u2502 ok')
        text, _attr = win.current_status
        assert text.isascii()
    finally:
        win.stop_curses()


def test_widget_cursor_uses_the_registered_glyph():
    confirmation = InlineConfirmation()
    confirmation.active = True
    confirmation.mode = 'text'

    assert '\u2502' in confirmation.get_display_string('go')

    set_ascii(True)
    degraded = confirmation.get_display_string('go')
    assert '\u2502' not in degraded
    assert '|' in degraded


def test_the_theme_swatch_degrades():
    win = _window(ascii=True)
    try:
        # The picker is covered in test_theme_picker; here we only need the
        # registry lookup the picker uses, which is what keeps the invariant.
        assert win.glyph('swatch').isascii()
        assert win.glyph('choice').isascii()
        assert len(win.glyph('box_h')) == 1
    finally:
        win.stop_curses()
