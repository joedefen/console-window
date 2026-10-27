"""ConsoleWindow's in-place prompt lifecycle and drawing helpers."""

import curses

import console_window.window as window_mod
from console_window import textwidth
from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


def _window(rows=10, cols=40, **opts):
    return ConsoleWindow(opts=ConsoleWindowOpts(**opts),
                         backend=HeadlessBackend(rows=rows, cols=cols),
                         singleton=False)


def test_begin_prompt_enables_passthrough_and_end_restores_it():
    win = _window()
    try:
        assert win.passthrough_mode is False
        assert win.begin_prompt('Proceed?') is True
        assert win.prompt_active is True
        assert win.passthrough_mode is True

        win.end_prompt()

        assert win.prompt_active is False
        assert win.passthrough_mode is False
    finally:
        win.stop_curses()


def test_begin_prompt_preserves_an_already_enabled_passthrough():
    win = _window()
    try:
        win.passthrough_mode = True
        win.begin_prompt('Proceed?')

        win.end_prompt()

        assert win.passthrough_mode is True
    finally:
        win.stop_curses()


def test_callback_runs_after_passthrough_is_restored():
    win = _window()
    try:
        seen = []

        def on_confirm(answer):
            seen.append((answer, win.passthrough_mode, win.prompt_active))

        win.begin_prompt('Proceed?', mode='y', on_confirm=on_confirm)
        assert win.handle_prompt_key(ord('y')) == 'confirmed'

        assert seen == [('y', False, False)]
    finally:
        win.stop_curses()


def test_callback_may_begin_the_next_prompt():
    win = _window()
    try:
        def ask_again(_answer):
            assert win.passthrough_mode is False
            win.begin_prompt('Again?', mode='y')

        win.begin_prompt('First?', mode='y', on_confirm=ask_again)
        win.handle_prompt_key(ord('y'))

        assert win.prompt_active is True
        assert win.prompt_line.prompt == 'Again?'
        assert win.passthrough_mode is True

        assert win.handle_prompt_key(ord('y')) == 'confirmed'
        assert win.prompt_active is False
        assert win.passthrough_mode is False
    finally:
        win.stop_curses()


def test_handle_prompt_key_is_continue_when_inactive():
    win = _window()
    try:
        assert win.handle_prompt_key(ord('y')) == 'continue'
    finally:
        win.stop_curses()


def test_add_prompt_header_is_a_noop_when_inactive():
    win = _window()
    try:
        before = win.head.row_cnt
        assert win.add_prompt_header() is False
        assert win.head.row_cnt == before
    finally:
        win.stop_curses()


def test_add_prompt_lines_draws_prompt_then_dim_hint():
    win = _window()
    try:
        win.begin_prompt('Confirm?', hint='Press Y', mode='text', seed='5')

        assert win.add_prompt_lines() is True

        assert win.body.texts == ['Confirm?: 5│', 'Press Y']
        assert win.body.text_attrs[0] == [(curses.A_BOLD, len('Confirm?: 5│'))]
        assert win.body.text_attrs[1] == [(curses.A_DIM, len('Press Y'))]
        for context in win.body.contexts:
            assert context.genre == 'TRANSIENT'
            assert context.pickable is False
    finally:
        win.stop_curses()


def test_add_prompt_header_draws_the_prompt_as_a_bold_header():
    win = _window()
    try:
        win.begin_prompt('Proceed?', mode='y')

        assert win.add_prompt_header() is True
        assert win.head.texts == ['Proceed?  [Press "y" or ESC]']
        assert win.head.text_attrs[0] == [
            (curses.A_BOLD, len('Proceed?  [Press "y" or ESC]'))]
    finally:
        win.stop_curses()


def test_add_prompt_lines_truncates_the_hint():
    win = _window(rows=10, cols=12)
    try:
        win.begin_prompt('X', hint='h' * 100, mode='text')

        win.add_prompt_lines()

        hint_text = win.body.texts[1]
        assert len(hint_text) == max(10, win.cols - 2)
    finally:
        win.stop_curses()


def test_every_key_is_consumable_while_active():
    win = _window()
    try:
        win.begin_prompt('Value', mode='text')

        for key in (ord('j'), curses.KEY_DOWN, ord('q')):
            assert win.handle_prompt_key(key) == 'continue'
            assert win.prompt_active is True
    finally:
        win.stop_curses()


# --- answer hint ------------------------------------------------------------

def test_answer_hint_replaces_the_default_suffix():
    win = _window()
    try:
        win.begin_prompt('Proceed?', mode='y',
                         answer_hint='["{mode}" or ESC] ⚠️')

        assert win.prompt_line.get_display_string() == 'Proceed?  ["y" or ESC] ⚠️'
    finally:
        win.stop_curses()


def test_answer_hint_substitutes_the_live_mode_letter():
    win = _window()
    try:
        win.begin_prompt('Proceed?', mode='Y',
                         answer_hint='["{mode}" or ESC]')

        assert win.prompt_line.get_display_string() == 'Proceed?  ["Y" or ESC]'
    finally:
        win.stop_curses()


def test_answer_hint_is_plain_text_not_a_format_string():
    # Braces are caller text; a stray '{' must not raise at paint time.
    win = _window()
    try:
        win.begin_prompt('Proceed?', mode='y',
                         answer_hint='["{mode}" or ESC] {⚠️}')

        assert win.prompt_line.get_display_string() == 'Proceed?  ["y" or ESC] {⚠️}'
    finally:
        win.stop_curses()


def test_answer_hint_is_cleared_with_the_prompt():
    win = _window()
    try:
        win.begin_prompt('Proceed?', mode='y', answer_hint='["{mode}" or ESC]')
        win.end_prompt()

        assert win.prompt_line.answer_hint == ''
    finally:
        win.stop_curses()


# --- centered prompt header -------------------------------------------------

def test_add_prompt_header_centers_within_the_pad_width():
    win = _window(rows=10, cols=40)
    try:
        win.begin_prompt('Proceed?', mode='y')

        assert win.add_prompt_header(align='center') is True

        display = 'Proceed?  [Press "y" or ESC]'
        lead = (win.get_pad_width() - textwidth.string_width(display)) // 2
        assert win.head.texts == [' ' * lead + display]
    finally:
        win.stop_curses()


def test_centering_measures_emoji_presentation_width():
    # Each ⚠️ is two cells but two code points (base + VS16), so a correct
    # measurement equals the code-point count.  Counting only the base (the
    # pre-VS16 behaviour) came out two cells short and pushed the line right,
    # which is what made the space after the glyph look cramped.
    win = _window(rows=10, cols=40)
    try:
        win.begin_prompt('⚠️ Go?', mode='y', answer_hint='["{mode}" or ESC] ⚠️')

        display = win.prompt_line.get_display_string()
        assert textwidth.string_width(display) == len(display)

        win.add_prompt_header(align='center')

        lead = (win.get_pad_width() - textwidth.string_width(display)) // 2
        assert win.head.texts == [' ' * lead + display]
    finally:
        win.stop_curses()


def test_add_prompt_header_align_never_adds_padding_when_too_wide():
    # Pad width is cols-1, so a 7-column window cannot hold the prompt plus a
    # pad: centering must degrade to plain (left-aligned, truncated) drawing.
    win = _window(rows=10, cols=8)
    try:
        win.begin_prompt('Proceed?', mode='y')

        win.add_prompt_header(align='center')

        assert win.head.texts[0] == 'Proceed'
    finally:
        win.stop_curses()


# --- separator dimming ------------------------------------------------------

def _hline_attrs(win):
    return [args[4] for _name, args, _kwargs in win._backend.screen.calls_named('hline')]


def test_separator_dims_only_while_a_prompt_is_live(monkeypatch):
    if not hasattr(window_mod.curses, 'ACS_HLINE'):
        monkeypatch.setattr(window_mod.curses, 'ACS_HLINE', '-', raising=False)
    win = _window(rows=10, cols=40)
    try:
        win.prompt_separator_attr = curses.A_DIM

        win._draw_separator_and_indicator()
        assert _hline_attrs(win)[-1] == curses.A_NORMAL

        win.begin_prompt('Proceed?', mode='y')
        win._draw_separator_and_indicator()
        assert _hline_attrs(win)[-1] == curses.A_DIM
    finally:
        win.stop_curses()


def test_separator_stays_plain_when_no_attr_is_configured(monkeypatch):
    if not hasattr(window_mod.curses, 'ACS_HLINE'):
        monkeypatch.setattr(window_mod.curses, 'ACS_HLINE', '-', raising=False)
    win = _window(rows=10, cols=40)
    try:
        win.begin_prompt('Proceed?', mode='y')

        win._draw_separator_and_indicator()

        assert _hline_attrs(win)[-1] == curses.A_NORMAL
    finally:
        win.stop_curses()
