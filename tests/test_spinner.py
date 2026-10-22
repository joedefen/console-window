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


def test_action_scope_detected_from_methods():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('quit', 'q - quit', genre='action', keys=[ord('q')])
    ns = spin.attr_to_option['quit']
    # quit_ACTION exists only on screen 0
    assert ns.effective_scope == {0}


def test_new_binding_subtracts_from_earlier_scope():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    # Global escape (present on screens 0 and 1)
    spin.add_key('escape', 'ESC - back', genre='action', keys=[27])
    assert spin.attr_to_option['escape'].effective_scope == {0, 1}
    # Narrow clear_filter to screen 0 with the same key -> subtract screen 0
    spin.add_key('clear_filter', 'ESC - clear', genre='action', keys=[27], scope={0})
    assert spin.attr_to_option['escape'].effective_scope == {1}
    assert spin.attr_to_option['clear_filter'].effective_scope == {0}


def test_scoped_lookup_by_current_screen():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('escape', 'ESC - back', genre='action', keys=[27])
    spin.add_key('clear_filter', 'ESC - clear', genre='action', keys=[27], scope={0})
    obj = spin.default_obj

    # On screen 0, key 27 resolves to clear_filter
    stack.curr = SimpleNamespace(num=0)
    spin.do_key(27, win=None)
    assert obj.clear_filter is True

    # On screen 1, key 27 resolves to escape
    stack.curr = SimpleNamespace(num=1)
    spin.do_key(27, win=None)
    assert obj.escape is True


def test_duplicate_attr_raises():
    stack = make_stack()
    spin = OptionSpinner(stack=stack)
    spin.add_key('quit', 'q - quit', genre='action', keys=[ord('q')])
    with pytest.raises(ValueError):
        spin.add_key('quit', 'q - quit again', genre='action', keys=[ord('Q')])


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
    """Minimal stand-in for ConsoleWindow.answer()."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def answer(self, prompt=None, seed=''):
        self.calls.append((prompt, seed))
        return self.reply


def test_prompt_genre_accepts_new_value():
    spin = OptionSpinner()
    spin.add_key('name', 'n - name', genre='prompt', prompt='name?', keys=[ord('n')])
    obj = spin.default_obj
    obj.name = 'old'
    win = FakeAnswerWindow('new')
    assert spin.do_key(ord('n'), win=win) == 'new'
    assert obj.name == 'new'
    assert win.calls == [('name?', 'old')]  # current value seeds the dialog


def test_prompt_genre_abort_keeps_previous_value():
    # ESC/abort surfaces as answer() -> None and must mean "no change".
    spin = OptionSpinner()
    spin.add_key('name', 'n - name', genre='prompt', prompt='name?', keys=[ord('n')])
    obj = spin.default_obj
    obj.name = 'kept'
    win = FakeAnswerWindow(None)
    assert spin.do_key(ord('n'), win=win) is None
    assert obj.name == 'kept'


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


def test_normalize_initialises_a_missing_option():
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


def test_legacy_add_is_retired_and_points_at_add_key():
    spin = OptionSpinner()
    with pytest.raises(NotImplementedError, match=r'add_key\('):
        spin.add(spin.default_obj, [('m - mode', 'mode', 'a', 'b')])
    assert spin.options == []
    assert spin.attr_to_option == {}


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
