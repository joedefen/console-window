import curses
import re
from types import SimpleNamespace

import pytest

from console_window import OptionSpinner
from console_window.keys import NAVIGATION_KEYS


class FakeScreen:
    def __init__(self, name, actions=()):
        self.name = name
        for action in actions:
            setattr(self, f'{action}_ACTION', lambda: None)


class FakeStack:
    def __init__(self, screen_objects):
        self.screens = {i: f'SCR{i}' for i in screen_objects}
        self.screen_objects = screen_objects
        self.obj = None
        self.curr = None


def make_stack():
    screens = {
        0: FakeScreen('MAIN', actions=('quit', 'escape', 'clear_filter')),
        1: FakeScreen('HELP', actions=('escape',)),
    }
    return FakeStack(screens)


def test_default_obj_syncs_with_stack():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    assert spin.default_obj is stack.obj


def test_builtin_actions_are_registered_first():
    spin = OptionSpinner()
    assert [ns.attr for ns in spin.options[:2]] == ['quit', 'escape']
    assert all(ns.builtin and ns.reserved for ns in spin.options[:2])
    assert spin.attr_to_option['quit'].genre == 'action'
    assert spin.attr_to_option['escape'].keys == [27, 10, curses.KEY_ENTER]


def test_second_spinner_on_the_same_stack_raises():
    stack = make_stack()
    OptionSpinner(stack=stack)
    with pytest.raises(ValueError, match='only one OptionSpinner'):
        OptionSpinner(stack=stack)


def test_action_scope_detected_from_methods():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('clear_filter', 'ESC - clear', genre='action', keys=[ord('x')])
    ns = spin.attr_to_option['clear_filter']
    # clear_filter_ACTION exists only on screen 0
    assert ns.effective_scope == {0}


def test_new_binding_subtracts_from_earlier_scope():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('zoom', 'x - zoom', genre='action', keys=[ord('x')])
    assert spin.attr_to_option['zoom'].effective_scope == {0, 1}
    # Narrow clear_filter to screen 0 with the same key -> subtract screen 0
    spin.add_key('clear_filter', 'x - clear', genre='action', keys=[ord('x')],
                 scope={0})
    assert spin.attr_to_option['zoom'].effective_scope == {1}
    assert spin.attr_to_option['clear_filter'].effective_scope == {0}


def test_scoped_lookup_by_current_screen():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('zoom', 'x - zoom', genre='action', keys=[ord('x')])
    spin.add_key('clear_filter', 'x - clear', genre='action', keys=[ord('x')],
                 scope={0})
    obj = spin.default_obj

    # On screen 0, key x resolves to clear_filter
    stack.curr = SimpleNamespace(num=0)
    spin.do_key(ord('x'), win=None)
    assert obj.clear_filter is True

    # On screen 1, key x resolves to zoom
    stack.curr = SimpleNamespace(num=1)
    spin.do_key(ord('x'), win=None)
    assert obj.zoom is True


def test_implicit_registration_of_a_reserved_key_raises():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    with pytest.raises(ValueError,
                       match=r"reserved by the built-in.*change escape_keys="):
        spin.add_key('oops', 'ESC - oops', genre='action', keys=[27])


def test_an_explicit_scope_may_take_a_reserved_key():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('clear_filter', 'ESC - clear', genre='action', keys=[27],
                 scope={0})
    assert spin.attr_to_option['escape'].effective_scope == {1}
    assert spin.key_scopes[(27, 0)].attr == 'clear_filter'


def test_duplicate_attr_raises():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('a_opt', 'a - one', genre='action', keys=[ord('a')])
    with pytest.raises(ValueError):
        spin.add_key('a_opt', 'a - again', genre='action', keys=[ord('A')])


def test_navigation_key_conflicts_raise():
    spin = OptionSpinner()
    nav = sorted(NAVIGATION_KEYS)[0]
    with pytest.raises(ValueError):
        spin.add_key('jump', 'j - reserved', genre='action', keys=[nav])


def test_cycle_value_rotates():
    spin = OptionSpinner()
    spin.add_key('mode', 'v - view mode', vals=['compact', 'full'], keys=[ord('v')])
    obj = spin.default_obj
    assert obj.mode == 'compact'  # normalized to the first value at registration
    spin.do_key(ord('v'), win=None)
    assert obj.mode == 'full'
    spin.do_key(ord('v'), win=None)
    assert obj.mode == 'compact'


def test_without_stack_duplicate_key_raises():
    spin = OptionSpinner()
    spin.add_key('a_opt', 'a - one', vals=[1, 2], keys=[ord('a')])
    with pytest.raises(ValueError):
        spin.add_key('b_opt', 'a - two', vals=[1, 2], keys=[ord('a')])


def test_key_scoped_to_multiple_screens_resolves_on_both():
    # Mirrors the demo pattern: a setting active on MAIN *and* HELP.
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('view_mode', 'v - view mode', vals=['a', 'b'],
                 keys=[ord('v')], scope={0, 1})

    # HELP screen (1)
    stack.curr = SimpleNamespace(num=1)
    assert spin.do_key(ord('v'), win=None) == 'b'
    # MAIN screen (0)
    stack.curr = SimpleNamespace(num=0)
    assert spin.do_key(ord('v'), win=None) == 'a'


def test_key_scoped_elsewhere_does_not_resolve():
    # Documents strict per-screen scoping: a MAIN-only key is inert on HELP.
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('view_mode', 'v - view mode', vals=['a', 'b'],
                 keys=[ord('v')], scope={0})
    stack.curr = SimpleNamespace(num=1)
    assert spin.do_key(ord('v'), win=None) is None


def test_genre_inferred_when_omitted():
    # With no explicit genre the kind is derived from vals/prompt/neither.
    spin = OptionSpinner()
    spin.add_key('a_act', 'a - action', keys=[ord('a')])
    spin.add_key('b_cycle', 'b - cycle', vals=[1, 2], keys=[ord('b')])
    spin.add_key('c_prompt', 'c - prompt', prompt='value?', keys=[ord('c')])
    assert spin.attr_to_option['a_act'].genre == 'action'
    assert spin.attr_to_option['b_cycle'].genre == 'cycle'
    assert spin.attr_to_option['c_prompt'].genre == 'prompt'


def test_genre_explicit_matches_inferred():
    # An explicit genre consistent with the arguments is accepted and honored.
    spin = OptionSpinner()
    spin.add_key('a_act', 'a - action', genre='action', keys=[ord('a')])
    spin.add_key('b_cycle', 'b - cycle', genre='cycle', vals=[1, 2], keys=[ord('b')])
    spin.add_key('c_prompt', 'c - prompt', genre='prompt', prompt='value?',
                 keys=[ord('c')])
    assert spin.attr_to_option['a_act'].genre == 'action'
    assert spin.attr_to_option['b_cycle'].genre == 'cycle'
    assert spin.attr_to_option['c_prompt'].genre == 'prompt'


def test_genre_action_with_stray_vals_raises():
    # The trap from the audit: genre='action' must NOT silently become a spinner.
    spin = OptionSpinner()
    with pytest.raises(ValueError):
        spin.add_key('trap', 'a - trap', genre='action', vals=[1, 2], keys=[ord('a')])


def test_genre_cycle_without_vals_raises():
    spin = OptionSpinner()
    with pytest.raises(ValueError):
        spin.add_key('bad', 'a - bad', genre='cycle', keys=[ord('a')])


class FakeAnswerWindow:
    """Minimal stand-in for ConsoleWindow.answer().

    Each call pops the next queued reply, so a test can script a rejected
    answer followed by an accepted one.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def answer(self, prompt=None, seed='', hint=''):
        self.calls.append((prompt, seed, hint))
        return self.replies.pop(0) if self.replies else None


def test_prompt_genre_accepts_new_value():
    spin = OptionSpinner()
    spin.add_key('name', 'n - name', genre='prompt', prompt='name?', keys=[ord('n')])
    obj = spin.default_obj
    obj.name = 'old'
    win = FakeAnswerWindow('new')
    assert spin.do_key(ord('n'), win=win) == 'new'
    assert obj.name == 'new'
    # The current value seeds the dialog and no hint is shown.
    assert win.calls == [('name?', 'old', '')]


def test_prompt_genre_abort_keeps_previous_value():
    # ESC/abort surfaces as answer() -> None and must mean "no change".
    spin = OptionSpinner()
    spin.add_key('name', 'n - name', genre='prompt', prompt='name?', keys=[ord('n')])
    obj = spin.default_obj
    obj.name = 'kept'
    win = FakeAnswerWindow(None)
    assert spin.do_key(ord('n'), win=win) is None
    assert obj.name == 'kept'


def test_prompt_check_ans_regex_reopens_with_the_rejected_text():
    spin = OptionSpinner()
    spin.add_key('port', 'p - port', genre='prompt', prompt='port?',
                 keys=[ord('p')], check_ans='[0-9]+')
    obj = spin.default_obj
    obj.port = '80'
    win = FakeAnswerWindow('nope', '8080')
    assert spin.do_key(ord('p'), win=win) == '8080'
    assert obj.port == '8080'
    assert win.calls == [
        ('port?', '80', ''),
        ('port?', 'nope', "must match '[0-9]+'"),
    ]


def test_prompt_check_ans_accepts_a_compiled_pattern():
    spin = OptionSpinner()
    spin.add_key('port', 'p - port', genre='prompt', prompt='port?',
                 keys=[ord('p')], check_ans=re.compile('[0-9]+'))
    obj = spin.default_obj
    obj.port = ''
    win = FakeAnswerWindow('8080')
    assert spin.do_key(ord('p'), win=win) == '8080'
    assert obj.port == '8080'


def test_prompt_check_ans_callable_reopens_with_its_description():
    seen = []

    def even(answer):
        seen.append(answer)
        ok = answer.isdigit() and int(answer) % 2 == 0
        return None if ok else 'want an even number'

    spin = OptionSpinner()
    spin.add_key('n', 'e - even', genre='prompt', prompt='even?',
                 keys=[ord('e')], check_ans=even)
    obj = spin.default_obj
    obj.n = '2'
    win = FakeAnswerWindow('3', '4')
    assert spin.do_key(ord('e'), win=win) == '4'
    assert obj.n == '4'
    assert seen == ['3', '4']
    assert win.calls == [
        ('even?', '2', ''),
        ('even?', '3', 'want an even number'),
    ]


def test_prompt_check_ans_abort_during_retry_keeps_previous_value():
    spin = OptionSpinner()
    spin.add_key('n', 'n - n', genre='prompt', prompt='n?',
                 keys=[ord('n')], check_ans='[0-9]+')
    obj = spin.default_obj
    obj.n = '7'
    win = FakeAnswerWindow('bad', None)
    assert spin.do_key(ord('n'), win=win) is None
    assert obj.n == '7'


def test_check_ans_requires_a_prompt_option():
    spin = OptionSpinner()
    with pytest.raises(ValueError, match='only meaningful for a prompt'):
        spin.add_key('mode', 'm - mode', vals=['a', 'b'], keys=[ord('m')],
                     check_ans='a|b')


def test_check_ans_rejects_an_invalid_regex():
    spin = OptionSpinner()
    with pytest.raises(ValueError, match='not a valid regular expression'):
        spin.add_key('n', 'n - n', genre='prompt', prompt='n?',
                     keys=[ord('n')], check_ans='[unclosed')


def test_genre_prompt_without_prompt_raises():
    spin = OptionSpinner()
    with pytest.raises(ValueError):
        spin.add_key('bad', 'a - bad', genre='prompt', keys=[ord('a')])


def test_genre_invalid_value_raises():
    spin = OptionSpinner()
    with pytest.raises(ValueError):
        spin.add_key('bad', 'a - bad', genre='spinner', keys=[ord('a')])


class FakeBodyWindow:
    """Records add_body() calls made by the help renderer."""

    def __init__(self):
        self.calls = []

    def add_body(self, text, attr=None, resume=False):
        self.calls.append((text, attr, resume))


def test_get_value_is_a_pure_read():
    spin = OptionSpinner()
    spin.add_key('mode', 'm - mode', vals=['a', 'b'], keys=[ord('m')])
    obj = spin.default_obj
    obj.mode = None
    assert spin.get_value('mode') is None
    assert obj.mode is None  # not re-initialized behind the caller's back


def test_normalize_initializes_a_missing_option():
    spin = OptionSpinner()
    spin.add_key('mode', 'm - mode', vals=['a', 'b'], keys=[ord('m')])
    obj = spin.default_obj
    del obj.mode
    assert spin.normalize('mode') == 'a'
    assert obj.mode == 'a'


def test_normalize_prompt_uses_empty_string():
    spin = OptionSpinner()
    spin.add_key('name', 'n - name', genre='prompt', prompt='name?', keys=[ord('n')])
    obj = spin.default_obj
    obj.name = None
    assert spin.normalize('name') == ''
    assert obj.name == ''


def test_normalize_unknown_attr_returns_none():
    spin = OptionSpinner()
    assert spin.normalize('missing') is None


def test_help_body_renders_placeholder_for_unset_option():
    spin = OptionSpinner()
    spin.add_key('mode', 'm - mode', vals=['a', 'b'], keys=[ord('m')])
    ns = spin.attr_to_option['mode']
    del spin.default_obj.mode
    win = FakeBodyWindow()
    spin._write_option_body(win, ns)
    texts = [text for text, _attr, _resume in win.calls]
    assert any('unset' in text for text in texts)
    assert not any('None' in text for text in texts)


class FakeBodyScreen(FakeBodyWindow):
    """A body sink that also knows its own stack number."""

    def __init__(self, num=None):
        super().__init__()
        self.num = num


def test_help_body_lists_only_options_for_the_screens_number():
    spin = OptionSpinner(stack=make_stack())
    spin.add_key('everywhere', 'e - everywhere', vals=['a'], keys=[ord('e')])
    spin.add_key('main_only', 'm - main', vals=['a'], keys=[ord('m')], scope={0})

    help_screen = FakeBodyScreen(num=1)
    spin.show_help_body(help_screen)
    texts = [text for text, _attr, _resume in help_screen.calls]

    assert any('Type keys to alter choice' in text for text in texts)
    assert any('everywhere' in text for text in texts)
    assert not any('main_only' in text for text in texts)


def test_help_body_without_a_stack_lists_every_option():
    spin = OptionSpinner()
    spin.add_key('mode', 'm - mode', vals=['a'], keys=[ord('m')])

    screen = FakeBodyScreen()
    spin.show_help_body(screen)
    texts = [text for text, _attr, _resume in screen.calls]

    assert any('mode' in text for text in texts)


def test_help_body_with_nothing_to_list_draws_no_heading():
    spin = OptionSpinner(stack=make_stack())
    screen = FakeBodyScreen(num=0)

    spin.show_help_body(screen)

    assert screen.calls == []


class FakeNavScreen:
    """Header sink for the navigation block."""

    def __init__(self):
        self.win = SimpleNamespace(nav_help_lines=lambda: ['NavKeys:    up: k'])
        self.headers = []

    def add_header(self, text, *args, **kwargs):
        self.headers.append(text)


def test_help_nav_block_advertises_the_builtin_actions():
    spin = OptionSpinner()
    screen = FakeNavScreen()

    spin.show_help_nav_keys(screen)

    assert screen.headers == [
        'NavKeys:    up: k',
        'quit: q/^C   back: ESC/^J/ENTER',
    ]
