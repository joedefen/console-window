import subprocess
import sys
import warnings

import pytest

import console_window.backend as backend_mod
import console_window.window as window_mod
from console_window.backend import CursesBackend, HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.theme import Theme
from console_window.window import ConsoleWindow


def _make(backend=None):
    # The suite needs independent windows (and per-instance teardown), so it
    # latches the process-wide mode to per-instance on the first construction.
    return ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                         backend=backend or HeadlessBackend(), singleton=False)


def test_headless_backend_exposes_protocol_surface():
    backend = HeadlessBackend()
    for meth in ('start', 'newpad', 'doupdate', 'curs_set', 'update_lines_cols',
                 'is_term_resized', 'start_color', 'use_default_colors',
                 'init_pair', 'color_pair', 'stop'):
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


def test_headless_backend_records_colour_calls():
    backend = HeadlessBackend(colors=True)
    backend.start_color()
    backend.use_default_colors()
    backend.init_pair(3, 1, -1)
    assert backend.start_color_calls == 1
    assert backend.use_default_colors_calls == 1
    assert backend.init_pair_calls == [(3, 1, -1)]
    # Mirrors curses: the pair id lives in the attribute's high bits.
    assert backend.color_pair(3) == 3 << 8
    assert backend.color_pair_calls == [3]


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


class _FakeCursesScreen:
    def __init__(self):
        self.calls = []

    def keypad(self, flag):
        self.calls.append(('keypad', flag))

    def timeout(self, ms):
        self.calls.append(('timeout', ms))

    def clear(self):
        self.calls.append(('clear',))


class _FakeCursesModule:
    """Only the API surface guaranteed by the Python 3.10 floor.

    ``CursesBackend.start()`` must stay inside this set: an unguarded call to
    something newer raises ``AttributeError`` here, which fails the floor test
    instead of breaking users on 3.10.
    """

    def __init__(self):
        self.calls = []
        self.scr = _FakeCursesScreen()

    def initscr(self):
        self.calls.append(('initscr',))
        return self.scr

    def set_escdelay(self, ms):
        self.calls.append(('set_escdelay', ms))

    def noecho(self):
        self.calls.append(('noecho',))

    def cbreak(self):
        self.calls.append(('cbreak',))

    def curs_set(self, visibility):
        self.calls.append(('curs_set', visibility))


def test_curses_backend_start_uses_only_the_python_310_curses_api(monkeypatch):
    # Pin the `requires-python = ">=3.10"` floor.  The fake module
    # deliberately exposes nothing beyond that floor, so a new unguarded
    # curses call is caught here rather than on an old interpreter.
    fake = _FakeCursesModule()
    monkeypatch.setattr(backend_mod, 'curses', fake)

    scr = CursesBackend().start(timeout_ms=250)

    assert scr is fake.scr
    assert fake.calls == [('initscr',), ('set_escdelay', 25), ('noecho',),
                          ('cbreak',), ('curs_set', 0)]
    assert fake.scr.calls == [('keypad', True), ('timeout', 250), ('clear',)]


def test_noop_surface_history_is_bounded():
    from console_window.backend import _NoopSurface
    surf = _NoopSurface()
    for _ in range(_NoopSurface.MAX_CALLS + 50):
        surf.clear()
    assert len(surf.calls) == _NoopSurface.MAX_CALLS


def test_deprecated_constructor_kwargs_warn():
    backend = HeadlessBackend()
    with pytest.warns(DeprecationWarning, match='opts='):
        win = ConsoleWindow(body_rows=10, backend=backend, singleton=False)
    try:
        assert win.opts.body_rows == 10
    finally:
        win.stop_curses()


def test_opts_constructor_does_not_warn():
    backend = HeadlessBackend()
    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        win = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=10, head_rows=3),
                            backend=backend, singleton=False)
    try:
        assert win.opts.body_rows == 10
    finally:
        win.stop_curses()


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


def test_unbound_stop_curses_is_rejected_in_per_instance_mode():
    win = _make()
    try:
        with pytest.raises(AssertionError, match='singleton'):
            ConsoleWindow.stop_curses()
    finally:
        win.stop_curses()


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


def test_singleton_mode_shares_the_process_screen():
    # Singleton mode is process-wide, so prove it in a fresh interpreter rather
    # than perturb the per-instance mode this test session has latched.
    code = '''
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow

first_backend = HeadlessBackend()
first = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                      backend=first_backend, singleton=True)
second = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                       backend=HeadlessBackend())
assert ConsoleWindow.static_scr is first.scr
assert second.scr is first.scr
assert ConsoleWindow.static_win is second
assert ConsoleWindow.primary_window() is second
ConsoleWindow.stop_all()   # permanent teardown
assert first.scr is None and second.scr is None
assert ConsoleWindow.static_scr is None and ConsoleWindow.static_win is None
assert first_backend.stopped is True
assert ConsoleWindow.active_windows() == []
'''
    subprocess.run([sys.executable, '-c', code], check=True)


def test_singleton_stop_curses_suspends_and_start_curses_resumes():
    # The pre-2.0 stop_curses()/start_curses() pair must keep working: in
    # singleton mode it is a suspend/resume pair, not a one-way teardown.
    code = '''
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow

first_backend = HeadlessBackend()
first = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                      backend=first_backend, singleton=True)
second = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                       backend=HeadlessBackend())
first.add_body('kept across the suspend')
old_screen = first.scr

ConsoleWindow.stop_curses()   # the pre-2.0 unbound call: suspend
assert first_backend.stopped is True
assert first.scr is None and second.scr is None
assert first.suspended and second.suspended
assert ConsoleWindow.static_scr is None
assert ConsoleWindow.active_windows() == []
# static_win is kept as the resume anchor.
assert ConsoleWindow.static_win is second

scr = ConsoleWindow.start_curses()   # matching resume
assert scr is not None
assert ConsoleWindow.static_scr is scr
assert first.scr is scr and second.scr is scr
assert not first.suspended and not second.suspended
assert first_backend.stopped is False
assert ConsoleWindow.active_windows() == [first, second]
# The content model and pads survived endwin().
assert first.body.texts == ['kept across the suspend']
assert first.body.pad is not None

ConsoleWindow.stop_all()   # permanent teardown
assert first.scr is None and second.scr is None
assert ConsoleWindow.static_scr is None and ConsoleWindow.static_win is None
assert ConsoleWindow.active_windows() == []
'''
    subprocess.run([sys.executable, '-c', code], check=True)


def test_per_instance_suspend_and_resume_curses():
    backend = HeadlessBackend()
    win = _make(backend)
    try:
        win.add_body('kept across the suspend')
        win.suspend_curses()
        assert win.suspended is True
        assert win.scr is None
        assert backend.stopped is True
        assert win not in ConsoleWindow.active_windows()

        scr = win.resume_curses()
        assert scr is not None
        assert win.scr is scr
        assert win.suspended is False
        assert backend.stopped is False
        assert win in ConsoleWindow.active_windows()
        assert win.body.texts == ['kept across the suspend']
        # A second resume is a no-op that returns the live screen.
        assert win.resume_curses() is scr
    finally:
        win.stop_curses()
    assert win.scr is None
    assert win not in ConsoleWindow.active_windows()


def test_mixing_singleton_modes_asserts():
    code = '''
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow

win = ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                    backend=HeadlessBackend(), singleton=True)
try:
    try:
        ConsoleWindow(opts=ConsoleWindowOpts(body_rows=3, head_rows=2),
                      backend=HeadlessBackend(), singleton=False)
    except AssertionError as exc:
        assert 'singleton' in str(exc)
    else:
        raise SystemExit('expected AssertionError')
finally:
    win.stop_curses()
'''
    subprocess.run([sys.executable, '-c', code], check=True)


def test_atexit_is_registered():
    win = _make()
    try:
        assert window_mod._ATEXIT_REGISTERED is True
    finally:
        win.stop_curses()
