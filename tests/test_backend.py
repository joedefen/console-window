import console_window.window as window_mod
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


def _make(backend=None):
    return ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                         backend=backend or HeadlessBackend())


def test_headless_backend_exposes_protocol_surface():
    backend = HeadlessBackend()
    for meth in ('start', 'newpad', 'stop'):
        assert callable(getattr(backend, meth))


def test_window_can_be_constructed_headless():
    backend = HeadlessBackend(rows=30, cols=100)
    win = _make(backend)
    try:
        assert win.scr is backend.screen
        assert (win.rows, win.cols) == (30, 100)
        # head + body pads were created through the backend.
        assert len(backend.pads) == 2
        assert win in ConsoleWindow.active_windows()
    finally:
        win.stop_curses()


def test_two_windows_coexist_and_primary_is_latest():
    first = _make()
    second = _make()
    try:
        active = ConsoleWindow.active_windows()
        assert first in active and second in active
        assert ConsoleWindow.primary_window() is second
    finally:
        first.stop_curses()
        second.stop_curses()


def test_stop_curses_is_per_instance():
    first = _make()
    second = _make()
    try:
        first.stop_curses()
        assert first.scr is None
        assert first not in ConsoleWindow.active_windows()
        # The other window is untouched.
        assert second in ConsoleWindow.active_windows()
        assert second.scr is not None
    finally:
        second.stop_curses()


def test_stop_curses_is_idempotent():
    backend = HeadlessBackend()
    win = _make(backend)
    win.stop_curses()
    win.stop_curses()  # must not raise
    assert backend.stopped is True


def test_context_manager_tears_down():
    backend = HeadlessBackend()
    with _make(backend) as win:
        assert win in ConsoleWindow.active_windows()
    assert backend.stopped is True
    assert win not in ConsoleWindow.active_windows()


def test_start_curses_compat_hook_uses_backend():
    backend = HeadlessBackend()
    scr = ConsoleWindow.start_curses(backend=backend)
    assert scr is backend.screen


def test_theme_broadcast_reaches_all_windows():
    first = _make()
    second = _make()
    try:
        # A color-pair integer is enough here: the headless surfaces record the
        # call without needing an initialised curses terminal.
        ConsoleWindow._apply_default_colors(8 << 8)
        assert first.scr.calls_named('bkgd')
        assert second.scr.calls_named('bkgd')
        assert first.body.pad.calls_named('bkgd')
    finally:
        first.stop_curses()
        second.stop_curses()


def test_no_process_wide_screen_singletons():
    # Regression guard for §4.5: the class-level singletons must be gone.
    assert not hasattr(ConsoleWindow, 'static_scr')
    assert not hasattr(ConsoleWindow, 'static_win')


def test_atexit_is_registered():
    win = _make()
    try:
        assert window_mod._ATEXIT_REGISTERED is True
    finally:
        win.stop_curses()
