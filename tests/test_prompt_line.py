"""PromptLine: the window-independent, in-place prompt widget."""

from console_window.widgets import PromptLine


def test_start_sets_prompt_hint_and_seed():
    line = PromptLine()
    line.start('Delete?', hint='ENTER or ESC', mode='text', seed='abc')

    assert line.active is True
    assert line.prompt == 'Delete?'
    assert line.hint == 'ENTER or ESC'
    assert line.get_display_string() == 'Delete?: abc│'


def test_text_mode_appends_and_confirms_on_enter():
    line = PromptLine()
    line.start('Name', mode='text')

    for ch in 'abc':
        assert line.handle_key(ord(ch)) == 'continue'
    assert line.get_display_string() == 'Name: abc│'
    assert line.handle_key(10) == 'confirmed'

    answer, _on_confirm, _on_cancel = line.take()
    assert answer == 'abc'


def test_empty_text_buffer_does_not_confirm():
    # Pins the editor rule: a blank 'text' answer is 'continue', not a confirm.
    line = PromptLine()
    line.start('Name', mode='text')

    assert line.handle_key(10) == 'continue'
    assert line.active is True


def test_single_key_mode_renders_press_hint():
    line = PromptLine()
    line.start('Proceed?', mode='y')

    assert line.get_display_string() == 'Proceed?  [Press "y" or ESC]'


def test_buffered_mode_renders_colon_and_caret():
    line = PromptLine()
    line.start('Value', mode='text', seed='5')

    assert line.get_display_string() == 'Value: 5│'


def test_escape_returns_cancelled_without_answer():
    line = PromptLine()
    line.start('Proceed?', mode='yes')

    assert line.handle_key(27) == 'cancelled'
    answer, _on_confirm, _on_cancel = line.take()
    assert answer is None


def test_ignored_key_returns_continue_and_stays_active():
    line = PromptLine()
    line.start('Proceed?', mode='y')

    assert line.handle_key(ord('n')) == 'continue'
    assert line.active is True


def test_take_clears_state_and_returns_the_callbacks():
    confirmed = []
    cancelled = []

    def on_confirm_cb(answer):
        confirmed.append(answer)

    def on_cancel_cb():
        cancelled.append(1)

    line = PromptLine()
    line.start('Proceed?', mode='y', hint='hint',
               on_confirm=on_confirm_cb, on_cancel=on_cancel_cb)

    assert line.handle_key(ord('y')) == 'confirmed'
    answer, on_confirm, on_cancel = line.take()

    assert answer == 'y'
    assert on_confirm is on_confirm_cb
    assert on_cancel is on_cancel_cb
    on_confirm('y')
    assert confirmed == ['y']
    assert cancelled == []

    assert line.active is False
    assert line.prompt == ''
    assert line.hint == ''
    assert line.get_display_string() == ''

    # A cancelled prompt hands back no answer.
    line.start('Again?', mode='y')
    assert line.handle_key(27) == 'cancelled'
    answer, _on_confirm, _on_cancel = line.take()
    assert answer is None


def test_choice_lines_mark_the_resolved_choice():
    line = PromptLine()
    line.start('Pick', choices=['alpha', 'beta'], seed='beta')

    assert line.get_choice_lines() == ['  alpha', '⮞ beta']

    # A plain text prompt has no choice rows.
    line.start('Value', mode='text')
    assert line.get_choice_lines() == []


def test_hint_is_truncated_to_width():
    line = PromptLine()
    line.start('Value', hint='hint too long', mode='text')

    assert line.get_hint_string(4) == 'hint'
    assert line.get_hint_string() == 'hint too long'


def test_prompt_is_inactive_after_take():
    line = PromptLine()
    line.start('Proceed?', mode='y')

    line.take()

    assert line.active is False
    assert line.get_display_string() == ''
    assert line.get_hint_string() == ''
    assert line.get_choice_lines() == []
