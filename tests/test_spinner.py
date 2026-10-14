"""Unit tests for OptionSpinner scoped key registration (no TTY required)."""

from types import SimpleNamespace

import pytest

from console_window import OptionSpinner
from console_window.keys import NAVIGATION_KEYS


class FakeScreen:
    """Minimal Screen stand-in exposing optional *_ACTION methods."""
    def __init__(self, name, actions=()):
        self.name = name
        for action in actions:
            setattr(self, f'{action}_ACTION', lambda: None)


class FakeStack:
    """Minimal ScreenStack stand-in used for scope computation."""
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
    assert obj.mode == 'compact'  # coerced to first value
    spin.do_key(ord('v'), win=None)
    assert obj.mode == 'full'
    spin.do_key(ord('v'), win=None)
    assert obj.mode == 'compact'


def test_without_stack_duplicate_key_raises():
    spin = OptionSpinner()
    spin.add_key('a_opt', 'a - one', vals=[1, 2], keys=[ord('a')])
    with pytest.raises(ValueError):
        spin.add_key('b_opt', 'a - two', vals=[1, 2], keys=[ord('a')])
