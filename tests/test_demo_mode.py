"""TTY-free tests for :meth:`ConsoleWindow.set_demo_mode`.

Regression guard for the audit finding that toggling demo mode *on* used to
wipe ``last_demo_key`` because the code tested the ``enabled`` argument (which
is ``None`` for a toggle) instead of the resulting ``opts.demo_mode`` state.

The window is built with ``object.__new__`` so ``__init__`` never enters curses;
``set_demo_mode`` only touches ``opts`` and ``last_demo_key``.
"""

from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


def make_window(demo_mode=False, last_demo_key=''):
    """Build a ConsoleWindow without running ``__init__`` (no curses)."""
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
