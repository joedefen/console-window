"""Detection, precedence, and how a window seeds the process-wide mode."""

from console_window import ConsoleWindow, ConsoleWindowOpts
from console_window.backend import HeadlessBackend
from console_window.glyphs import (
    GLYPHS_ENV,
    apply_policy,
    ensure_policy,
    is_ascii,
    set_ascii,
    terminal_report,
)


class _Stream:
    """Minimal stand-in for a stdout with a known encoding."""

    def __init__(self, encoding):
        self.encoding = encoding


UTF8 = _Stream('utf-8')


def test_dumb_terminal_requires_ascii():
    report = terminal_report(environ={'TERM': 'dumb'}, stream=UTF8)
    assert report.ascii_required is True
    assert report.utf8 is True
    assert any('TERM=dumb' in note for note in report.notes)


def test_a_non_utf8_encoding_requires_ascii():
    report = terminal_report(environ={'TERM': 'xterm'}, stream=_Stream('ascii'))
    assert report.ascii_required is True
    assert report.utf8 is False
    assert any('encoding' in note for note in report.notes)


def test_the_linux_console_is_advisory_only():
    report = terminal_report(environ={'TERM': 'linux'}, stream=UTF8)
    assert report.ascii_required is False
    assert any('--ascii' in note for note in report.notes)


def test_a_utf8_terminal_gets_the_font_check_line():
    report = terminal_report(environ={'TERM': 'xterm-256color'}, stream=UTF8)
    assert report.ascii_required is False
    check = [note for note in report.notes if 'font check' in note]
    assert check
    # The check must print the real glyphs, never the fallback.
    assert not check[0].split(':', 1)[1].split('(')[0].strip().isascii()


def test_an_explicit_request_wins_and_says_so():
    report = apply_policy(True, environ={'TERM': 'xterm-256color'}, stream=UTF8)
    assert report.ascii_mode is True
    assert report.source == 'request'
    assert is_ascii() is True
    assert any('requested' in note for note in report.notes)


def test_an_explicit_unicode_request_is_honoured_on_a_dumb_terminal():
    report = apply_policy(False, environ={'TERM': 'dumb'}, stream=UTF8)
    assert report.ascii_mode is False
    assert is_ascii() is False
    # ...but the report still tells the truth about what it detected.
    assert report.ascii_required is True


def test_the_environment_beats_detection():
    report = apply_policy(None, environ={'TERM': 'dumb', GLYPHS_ENV: 'unicode'},
                          stream=UTF8)
    assert report.ascii_mode is False
    assert report.source == 'env'
    assert is_ascii() is False


def test_an_invalid_environment_value_is_ignored_with_a_note():
    report = apply_policy(None, environ={'TERM': 'dumb', GLYPHS_ENV: 'maybe'},
                          stream=UTF8)
    assert report.ascii_mode is True  # detection still applies
    assert any('ignoring' in note for note in report.notes)


def test_ensure_policy_does_not_undo_an_earlier_decision():
    set_ascii(True)
    report = ensure_policy(environ={'TERM': 'xterm-256color'}, stream=UTF8)
    assert is_ascii() is True
    assert report.ascii_mode is True
    assert report.source == 'previous'


def test_ensure_policy_detects_when_nothing_has_decided():
    report = ensure_policy(environ={'TERM': 'dumb'}, stream=UTF8)
    assert is_ascii() is True
    assert report.source == 'auto'


def test_a_window_option_seeds_the_process_mode():
    win = ConsoleWindow(opts=ConsoleWindowOpts(ascii=True),
                        backend=HeadlessBackend(), singleton=False)
    try:
        assert win.ascii_mode is True
        assert is_ascii() is True
    finally:
        win.stop_curses()


def test_a_later_window_cannot_undo_a_forced_mode():
    # The app called apply_policy(force_ascii=True) before building its window;
    # auto-detection in the constructor must not revert it.
    set_ascii(True)
    win = ConsoleWindow(backend=HeadlessBackend(), singleton=False)
    try:
        assert win.ascii_mode is True
    finally:
        win.stop_curses()


def test_a_window_registers_the_app_vocabulary_from_opts():
    win = ConsoleWindow(
        opts=ConsoleWindowOpts(glyphs={'tick': ('\u2713', 'OK')}, glyphs_probe=('tick',)),
        backend=HeadlessBackend(),
        singleton=False,
    )
    try:
        assert win.glyph('tick') == '\u2713'
        assert win.ascii_mode is False
    finally:
        win.stop_curses()


def test_opts_validate_the_glyph_options():
    import pytest

    with pytest.raises(TypeError, match='ascii must be'):
        ConsoleWindowOpts(ascii='yes')
    with pytest.raises(TypeError, match='glyphs must be a mapping'):
        ConsoleWindowOpts(glyphs=['x'])
    with pytest.raises(TypeError, match='glyphs_probe'):
        ConsoleWindowOpts(glyphs_probe='cursor')
