import curses

import pytest

from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


def make_window(demo_mode=False, last_demo_key=''):
    win = object.__new__(ConsoleWindow)
    win.opts = ConsoleWindowOpts(demo_mode=demo_mode)
    win.last_demo_key = last_demo_key
    return win


def test_toggle_on_preserves_last_demo_key():
    # The audit bug: ``enabled is None`` must not be treated as "disable".
    win = make_window(demo_mode=False, last_demo_key='k')
    assert win.set_demo_mode(None) is True
    assert win.opts.demo_mode is True
    assert win.last_demo_key == 'k'


def test_toggle_off_clears_last_demo_key():
    win = make_window(demo_mode=True, last_demo_key='k')
    assert win.set_demo_mode(None) is False
    assert win.opts.demo_mode is False
    assert win.last_demo_key == ''


def test_explicit_enable_preserves_last_demo_key():
    win = make_window(demo_mode=False, last_demo_key='k')
    assert win.set_demo_mode(True) is True
    assert win.opts.demo_mode is True
    assert win.last_demo_key == 'k'


def test_explicit_disable_clears_last_demo_key():
    win = make_window(demo_mode=True, last_demo_key='k')
    assert win.set_demo_mode(False) is False
    assert win.opts.demo_mode is False
    assert win.last_demo_key == ''


def test_return_value_tracks_new_state():
    win = make_window(demo_mode=False)
    assert win.set_demo_mode(True) is True
    assert win.set_demo_mode(True) is True
    assert win.set_demo_mode(False) is False
    assert win.set_demo_mode(None) is True  # toggles back on


@pytest.mark.parametrize(('key', 'label'), [
    (curses.KEY_LEFT, 'LEFT'),
    (curses.KEY_RIGHT, 'RIGHT'),
    (curses.KEY_UP, 'UP'),
    (curses.KEY_DOWN, 'DOWN'),
    (curses.KEY_HOME, 'HOME'),
    (curses.KEY_END, 'END'),
    (curses.KEY_PPAGE, 'PPAGE'),
    (curses.KEY_NPAGE, 'NPAGE'),
    (curses.KEY_F5, 'F5'),
    (curses.KEY_BTAB, 'BTAB'),
    (curses.KEY_RESIZE, 'RESIZE'),
])
def test_curses_keys_get_readable_demo_labels(key, label):
    # A taken LEFT/RIGHT reaches demo mode as an application key; the header
    # must name it instead of showing the old '???' fallback.
    assert make_window()._format_key_for_demo(key) == label  # pylint: disable=protected-access


@pytest.mark.parametrize(('key', 'label'), [
    (ord('p'), ' p '),
    (27, 'ESC'),
    (ord('\t'), 'TAB'),
    (10, 'ENT'),
    (13, 'ENT'),
    (curses.KEY_ENTER, 'ENT'),
    (ord(' '), 'SPC'),
    (8, 'BSP'),
    (127, 'BSP'),
    (curses.KEY_BACKSPACE, 'BSP'),
    (curses.KEY_DC, 'DEL'),
    (ord('\x15'), '^U'),
    (0, '^@'),
    (31, '^_'),
])
def test_known_keys_keep_their_compact_demo_labels(key, label):
    assert make_window()._format_key_for_demo(key) == label  # pylint: disable=protected-access


def test_unknown_keys_show_their_code_instead_of_question_marks():
    win = make_window()
    assert win._format_key_for_demo(999) == '<999>'  # pylint: disable=protected-access
    # Regression: no key code may fall back to the old '???' placeholder.
    for key in [*range(0, 300), 999, 1000]:
        assert win._format_key_for_demo(key) != '???'  # pylint: disable=protected-access
