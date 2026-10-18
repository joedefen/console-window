import console_window.backend as backend_mod
import console_window.window as window_mod
from console_window.backend import CursesBackend, HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.theme import Theme
from console_window.window import ConsoleWindow


def _make(backend=None):
    return ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                         backend=backend or HeadlessBackend())


def test_headless_backend_exposes_protocol_surface():
    backend = HeadlessBackend()
    for meth in ('start', 'newpad', 'doupdate', 'curs_set', 'update_lines_cols',
                 'is_term_resized', 'stop'):
        assert callable(getattr(backend, meth))


def test_headless_backend_records_process_global_calls():
    backend = HeadlessBackend()
    backend.doupdate()
    backend.doupdate()
    backend.curs_set(0)
    backend.update_lines_cols()
    assert backend.doupdates == 2
    assert backend.curs_set_calls == [0]
    assert backend.update_lines_cols_calls == 1
    assert backend.is_term_resized(24, 80) is False


def test_curses_backend_stop_restores_cursor(monkeypatch):
    calls = []
    monkeypatch.setattr(backend_mod.curses, 'nocbreak',
                        lambda: calls.append('nocbreak'))
    monkeypatch.setattr(backend_mod.curses, 'echo', lambda: calls.append('echo'))
    monkeypatch.setattr(backend_mod.curses, 'curs_set',
                        lambda v: calls.append(('curs_set', v)))
    monkeypatch.setattr(backend_mod.curses, 'endwin', lambda: calls.append('endwin'))

    class Scr:
        def keypad(self, flag):
            calls.append(('keypad', flag))

    CursesBackend().stop(Scr())
    assert calls == ['nocbreak', 'echo', ('keypad', False),
                     ('curs_set', 1), 'endwin']


def test_curses_backend_delegates_process_global_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(backend_mod.curses, 'doupdate', lambda: calls.append('doupdate'))
    monkeypatch.setattr(backend_mod.curses, 'curs_set', lambda v: calls.append(('curs_set', v)))
    monkeypatch.setattr(backend_mod.curses, 'update_lines_cols',
                        lambda: calls.append('update_lines_cols'))
    monkeypatch.setattr(backend_mod.curses, 'is_term_resized', lambda rows, cols: True)

    be = CursesBackend()
    be.doupdate()
    be.curs_set(0)
    be.update_lines_cols()
    assert be.is_term_resized(24, 80) is True
    assert calls == ['doupdate', ('curs_set', 0), 'update_lines_cols']


def test_noop_surface_history_is_bounded():
    from console_window.backend import _NoopSurface
    surf = _NoopSurface()
    for _ in range(_NoopSurface.MAX_CALLS + 50):
        surf.clear()
    assert len(surf.calls) == _NoopSurface.MAX_CALLS


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
        ConsoleWindow._apply_default_colors(Theme.DEFAULT_BG << 8)
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
