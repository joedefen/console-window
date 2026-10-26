"""ConsoleWindow's in-place prompt lifecycle and drawing helpers."""

import curses

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
