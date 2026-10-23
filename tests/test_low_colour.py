"""Theme installation on terminals with fewer than 256 colours.

The 256-colour themes used to be handed to ``curses.init_pair()`` verbatim, so
an 8-colour terminal (including tmux's stock ``TERM=screen``) raised
``ValueError: Color number is greater than COLORS-1``.  These tests pin the
degradation contract: install the requested theme, resolve every colour to what
the terminal supports, and never raise.
"""

import curses

import pytest

import console_window.backend as backend_mod
from console_window.backend import CursesBackend, HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.theme import (
    Theme,
    nearest_palette_index,
    palette_rgb,
    resolve_color_pair,
)
from console_window.window import ConsoleWindow


def _window(theme_name, backend):
    opts = ConsoleWindowOpts(theme=theme_name, body_rows=10, head_rows=3)
    return ConsoleWindow(opts=opts, backend=backend, singleton=False)


def _assert_within_capability(backend, colors):
    assert backend.init_pair_calls, 'the theme installed no colour pairs'
    for pair_id, fg, bg in backend.init_pair_calls:
        assert pair_id < backend.color_pairs()
        assert -1 <= fg < colors
        assert -1 <= bg < colors
        # A pair of terminal defaults (-1, -1) is the one legitimate exception:
        # the terminal picks a legible foreground/background itself.
        assert fg != bg or (fg == -1 and bg == -1), (pair_id, fg, bg)


# --- every bundled theme on every supported colour depth --------------------

@pytest.mark.parametrize('colors', [8, 16, 88, 256])
@pytest.mark.parametrize('theme_name', Theme.list_all())
def test_every_theme_installs_within_the_terminals_capability(theme_name, colors,
                                                              monkeypatch):
    monkeypatch.setattr(Theme, '_current', theme_name)
    backend = HeadlessBackend(colors=colors)
    win = _window(theme_name, backend)
    try:
        _assert_within_capability(backend, colors)
        assert Theme.DEFAULT_BG in {pair for pair, _fg, _bg in backend.init_pair_calls}
    finally:
        win.stop_curses()


@pytest.mark.parametrize('colors', [1, 2, 4, 7])
def test_below_eight_colours_degrades_to_attributes_without_raising(colors,
                                                                    monkeypatch):
    # There is no legible colour mapping for a 1-colour terminal, so nothing is
    # installed and drawing falls back to A_BOLD/A_REVERSE instead of raising.
    monkeypatch.setattr(Theme, '_current', 'nord')
    backend = HeadlessBackend(colors=colors)
    win = _window('nord', backend)
    try:
        for pair_id, fg, bg in backend.init_pair_calls:
            assert pair_id < backend.color_pairs()
            if colors > 1:
                assert 0 <= fg < colors and 0 <= bg < colors
                assert fg != bg
        if colors == 1:
            assert backend.init_pair_calls == []
    finally:
        win.stop_curses()


# --- the picker path (Theme.set) -------------------------------------------

def test_theme_set_on_an_eight_colour_window_does_not_raise(monkeypatch):
    monkeypatch.setattr(Theme, '_current', None)
    backend = HeadlessBackend(colors=8)
    win = _window('dark-mono', backend)
    try:
        backend.init_pair_calls.clear()
        assert Theme.set('nord') is True
        assert win.theme == 'nord'
        _assert_within_capability(backend, 8)
    finally:
        win.stop_curses()


def test_window_set_theme_on_an_eight_colour_window_does_not_raise(monkeypatch):
    monkeypatch.setattr(Theme, '_current', None)
    backend = HeadlessBackend(colors=8)
    win = _window('nord', backend)
    try:
        assert win.set_theme('solarized-dark') is True
        assert win.theme == 'solarized-dark'
        _assert_within_capability(backend, 8)
    finally:
        win.stop_curses()


# --- 256 colours stay byte-for-byte identical -------------------------------

def test_256_colour_install_uses_the_literal_theme_specs(monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'nord')
    backend = HeadlessBackend(colors=256)
    win = _window('nord', backend)
    try:
        assert backend.init_pair_calls == Theme.pair_specs('nord')
    finally:
        win.stop_curses()


def test_pair_ids_beyond_color_pairs_are_skipped(monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'nord')
    backend = HeadlessBackend(colors=256, color_pairs=8)
    win = _window('nord', backend)
    try:
        assert all(pair < 8 for pair, _fg, _bg in backend.init_pair_calls)
        assert Theme.DEFAULT_BG not in {pair for pair, _fg, _bg
                                        in backend.init_pair_calls}
    finally:
        win.stop_curses()


# --- -1 handling ------------------------------------------------------------

def test_use_default_colors_failure_resolves_minus_one(monkeypatch):
    monkeypatch.setattr(Theme, '_current', 'default')
    backend = HeadlessBackend(colors=8, default_colors=False)
    win = _window('default', backend)
    try:
        pairs = {pair: (fg, bg) for pair, fg, bg in backend.init_pair_calls}
        assert all(-1 not in pair for pair in pairs.values())
        # The theme's (-1, -1) default background becomes concrete elsewhere.
        assert pairs[Theme.DEFAULT_BG] == (7, 0)
        # DANGER is (1, -1) in the 'default' theme.
        assert pairs[Theme.DANGER] == (1, 0)
    finally:
        win.stop_curses()


def test_curses_backend_reports_use_default_colors_failure(monkeypatch):
    def _raise():
        raise curses.error('terminal does not support default colours')

    monkeypatch.setattr(backend_mod.curses, 'use_default_colors', _raise)
    backend = CursesBackend()
    assert backend.use_default_colors() is False


def test_curses_backend_captures_capabilities_after_start_color(monkeypatch):
    monkeypatch.setattr(backend_mod.curses, 'start_color', lambda: None)
    monkeypatch.setattr(backend_mod.curses, 'COLORS', 8, raising=False)
    monkeypatch.setattr(backend_mod.curses, 'COLOR_PAIRS', 64, raising=False)
    backend = CursesBackend()
    backend.start_color()
    assert backend.colors() == 8
    assert backend.color_pairs() == 64


def test_curses_backend_start_color_failure_degrades(monkeypatch):
    def _raise():
        raise curses.error('no colour support')

    monkeypatch.setattr(backend_mod.curses, 'start_color', _raise)
    backend = CursesBackend()
    backend.start_color()  # must not raise
    assert backend.colors() == 0


# --- the pure palette mapping ----------------------------------------------

def test_palette_rgb_uses_the_xterm_model():
    assert palette_rgb(0) == (0, 0, 0)
    assert palette_rgb(16) == (0, 0, 0)
    assert palette_rgb(196) == (255, 0, 0)
    assert palette_rgb(232) == (8, 8, 8)
    assert palette_rgb(255) == (238, 238, 238)
    # Unknown indices never raise.
    assert palette_rgb(-7) == (0, 0, 0)
    assert palette_rgb(9999) == (0, 0, 0)


@pytest.mark.parametrize('index,colors,expected', [
    (232, 16, 0),    # near-black gray -> black
    (232, 8, 0),
    (253, 16, 7),    # gray level 218 -> normal white (192), not bright white
    (255, 16, 15),   # gray level 238 -> bright white
    (253, 8, 7),     # ... and normal white is all an 8-colour terminal has
    (196, 16, 9),    # pure red -> bright red
    (196, 8, 1),     # ... normal red in 8 colours
    (196, 256, 196),  # 256 colours: unchanged
    (1, 8, 1),       # already available
])
def test_nearest_palette_index_known_conversions(index, colors, expected):
    assert nearest_palette_index(index, colors) == expected


def test_nearest_palette_index_without_colours_returns_minus_one():
    assert nearest_palette_index(196, 0) == -1


def test_resolve_color_pair_breaks_a_collapsed_pair():
    # 232 and 16 both map to black on an 8-colour terminal; the foreground must
    # move so the text stays legible.
    fg, bg = resolve_color_pair(232, 16, 8, True)
    assert bg == 0
    assert fg != bg
    assert 0 <= fg < 8


def test_resolve_color_pair_returns_none_for_a_one_colour_terminal():
    assert resolve_color_pair(1, 0, 1, True) is None


def test_resolve_color_pair_keeps_default_pair_when_supported():
    assert resolve_color_pair(-1, -1, 256, True) == (-1, -1)
