"""Unit tests for IncrementalSearchBar and InlineConfirmation (no TTY required)."""

import curses

from console_window import IncrementalSearchBar, InlineConfirmation

# --- InlineConfirmation ----------------------------------------------------

def test_inline_single_key_confirm():
    c = InlineConfirmation()
    c.start(mode='y')
    assert c.handle_key(ord('y')) == 'confirmed'
    assert c.input_buffer == 'y'


def test_inline_single_key_other_is_continue():
    c = InlineConfirmation()
    c.start(mode='y')
    assert c.handle_key(ord('n')) == 'continue'


def test_inline_escape_cancels():
    c = InlineConfirmation()
    c.start(mode='yes')
    assert c.handle_key(27) == 'cancelled'


def test_inline_identity_match():
    c = InlineConfirmation()
    c.start(identity='sda1', mode='identity')
    for ch in 'sda1':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'confirmed'
    assert c.input_buffer == 'sda1'


def test_inline_identity_mismatch_resets():
    c = InlineConfirmation()
    c.start(identity='sda1', mode='identity')
    for ch in 'sda2':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'continue'
    assert c.input_buffer == ''


def test_inline_yes_requires_yes():
    c = InlineConfirmation()
    c.start(mode='yes')
    for ch in 'yeah':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'continue'
    c.input_buffer = ''
    for ch in 'yes':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'confirmed'


def test_inline_choices_abbreviation_resolution():
    c = InlineConfirmation()
    c.start(choices=['sda1', 'sdb2', 'nvme0'], mode='choices')
    for ch in 'sda1':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'confirmed'
    assert c.input_buffer == 'sda1'


def test_inline_choices_ambiguous_returns_none():
    c = InlineConfirmation()
    c.start(choices=['sda1', 'sdb2'], mode='choices')
    # single 's' is ambiguous and below min_abbrev; should not resolve
    c.input_buffer = 's'
    assert c._resolve_choice() is None


def test_inline_text_mode_accepts_anything():
    c = InlineConfirmation()
    c.start(mode='text')
    for ch in 'hello world':
        c.handle_key(ord(ch))
    assert c.handle_key(10) == 'confirmed'
    assert c.input_buffer == 'hello world'


def test_inline_backspace_removes_char():
    c = InlineConfirmation()
    c.start(mode='yes')
    c.handle_key(ord('y'))
    c.handle_key(ord('e'))
    c.handle_key(curses.KEY_BACKSPACE)
    assert c.input_buffer == 'y'


def test_inline_hint_text():
    c = InlineConfirmation()
    c.start(mode='yes')
    assert 'yes' in c.get_hint()
    c.handle_key(ord('y'))
    assert c.get_hint() == ''


def test_inline_min_abbrev_auto_calculation():
    c = InlineConfirmation()
    c.start(choices=['alpha', 'beta', 'gamma'], mode='choices')
    # unique at first char -> 1 + 1 = 2, capped at longest (5)
    assert c._get_effective_min_abbrev_chars() == 2


# --- IncrementalSearchBar --------------------------------------------------

def test_searchbar_insert_and_backspace():
    bar = IncrementalSearchBar()
    bar.start()
    for ch in 'abc':
        bar.handle_key(ord(ch))
    assert bar.text == 'abc'
    bar.handle_key(curses.KEY_BACKSPACE)
    assert bar.text == 'ab'


def test_searchbar_cursor_movement_and_insert():
    bar = IncrementalSearchBar()
    bar.start('abc')
    bar.handle_key(curses.KEY_LEFT)
    bar.handle_key(curses.KEY_LEFT)
    bar.handle_key(ord('X'))
    assert bar.text == 'aXbc'


def test_searchbar_home_end():
    bar = IncrementalSearchBar()
    bar.start('abc')
    bar.handle_key(curses.KEY_HOME)
    assert bar.cursor_pos == 0
    bar.handle_key(curses.KEY_END)
    assert bar.cursor_pos == 3


def test_searchbar_accept_callback():
    seen = []
    bar = IncrementalSearchBar(on_accept=lambda t: seen.append(t))
    bar.start('hello')
    assert bar.handle_key(10) is True
    assert seen == ['hello']
    assert bar.is_active is False


def test_searchbar_cancel_restores_start_text():
    seen = []
    bar = IncrementalSearchBar(on_cancel=lambda t: seen.append(t))
    bar.start('orig')
    bar.handle_key(ord('X'))
    assert bar.handle_key(27) is True
    assert seen == ['orig']
    assert bar.is_active is False


def test_searchbar_on_change_fires():
    seen = []
    bar = IncrementalSearchBar(on_change=lambda t: seen.append(t))
    bar.start()
    bar.handle_key(ord('a'))
    assert seen == ['a']


def test_searchbar_inactive_ignores_keys():
    bar = IncrementalSearchBar()
    assert bar.handle_key(ord('a')) is False


def test_searchbar_display_string_active_has_cursor():
    bar = IncrementalSearchBar()
    bar.start('ab')
    s = bar.get_display_string(prefix='/')
    assert '█' in s
    assert s.startswith('/ ')


def test_searchbar_display_string_inactive():
    bar = IncrementalSearchBar()
    bar.start('ab')
    bar.handle_key(10)
    assert bar.get_display_string(prefix='/') == '/ab'


def test_searchbar_display_string_empty():
    bar = IncrementalSearchBar()
    assert bar.get_display_string() == ''
