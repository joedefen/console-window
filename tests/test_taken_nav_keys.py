"""Per-window navigation-key ownership (``opts.taken_nav_keys``).

The trap these tests exist for: subtracting a key from ``NAVIGATION_KEYS`` is
not enough, because movement is dispatched by a separate hardcoded table in
``_navigation_target()``.  UP/DOWN, the page keys and HOME/END must therefore
be tested specifically: they are the keys that would still scroll if only the
reservation set were changed.
"""

import curses
import logging

import pytest

import console_window.window as window_mod
from console_window import ConsoleWindow, ConsoleWindowOpts, OptionSpinner
from console_window.backend import HeadlessBackend
from console_window.keys import NAVIGATION_KEYS, VERTICAL_NAV_KEYS
from console_window.window import NAV_KEY_LINES

_ACS_STANDINS = {
    'ACS_HLINE': '-',
    'ACS_VLINE': '|',
    'ACS_ULCORNER': '+',
    'ACS_URCORNER': '+',
    'ACS_LLCORNER': '+',
    'ACS_LRCORNER': '+',
}


@pytest.fixture(autouse=True)
def _headless_curses(monkeypatch):
    for name, value in _ACS_STANDINS.items():
        if not hasattr(window_mod.curses, name):
            monkeypatch.setattr(window_mod.curses, name, value, raising=False)


@pytest.fixture
def make():
    created = []

    def _make(backend=None, **opts):
        backend = backend if backend is not None else HeadlessBackend(rows=24, cols=80)
        win = ConsoleWindow(opts=ConsoleWindowOpts(**opts), backend=backend,
                            singleton=False)
        created.append(win)
        return win, backend

    yield _make
    for win in created:
        if win.scr is not None:
            win.stop_curses()


# --- opts normalization and validation --------------------------------------

def test_default_opts_keeps_every_navigation_key():
    opts = ConsoleWindowOpts()
    assert opts.taken_nav_keys == {}
    assert opts.nav_keys == frozenset(NAVIGATION_KEYS)


def test_mapping_labels_are_preserved_and_iterables_normalize_to_empty():
    opts = ConsoleWindowOpts(taken_nav_keys={
        curses.KEY_LEFT: 'prev',
        curses.KEY_RIGHT: 'next',
    })
    assert opts.taken_nav_keys == {
        curses.KEY_LEFT: 'prev',
        curses.KEY_RIGHT: 'next',
    }
    assert curses.KEY_LEFT not in opts.nav_keys

    bare = ConsoleWindowOpts(taken_nav_keys=[curses.KEY_UP, curses.KEY_DOWN])
    assert bare.taken_nav_keys == {curses.KEY_UP: '', curses.KEY_DOWN: ''}


def test_duplicate_keys_collapse_to_the_last_label():
    opts = ConsoleWindowOpts(taken_nav_keys={curses.KEY_LEFT: 'a',
                                             curses.KEY_LEFT: 'b'})
    assert opts.taken_nav_keys == {curses.KEY_LEFT: 'b'}


def test_non_integer_keys_are_rejected():
    with pytest.raises(ValueError, match='integer key codes'):
        ConsoleWindowOpts(taken_nav_keys={'LEFT': 'prev'})
    with pytest.raises(ValueError, match='integer key codes'):
        ConsoleWindowOpts(taken_nav_keys={True: 'yes'})


def test_nav_keys_is_computed_not_passed():
    with pytest.raises(TypeError, match='taken_nav_keys'):
        ConsoleWindowOpts(nav_keys=[ord('j')])


def test_unknown_key_is_kept_but_logged(caplog):
    with caplog.at_level(logging.WARNING, logger='console_window.opts'):
        opts = ConsoleWindowOpts(taken_nav_keys={ord('z'): 'zoom'})
    assert opts.taken_nav_keys == {ord('z'): 'zoom'}
    assert opts.nav_keys == frozenset(NAVIGATION_KEYS)  # nothing was subtracted
    assert any('not a navigation key' in record.message for record in caplog.records)


def test_taking_every_vertical_key_warns_but_constructs(caplog, make):
    with caplog.at_level(logging.WARNING, logger='console_window.opts'):
        win, _backend = make(taken_nav_keys=dict.fromkeys(VERTICAL_NAV_KEYS, ''))
    assert not (win.opts.nav_keys & VERTICAL_NAV_KEYS)
    assert any('reduced' in record.message for record in caplog.records)
    # The help screen reports the reduced navigation instead of lying.
    assert 'no navigation keys' in win.nav_help_lines()[0]


# --- dispatch: taken keys must not scroll -----------------------------------

@pytest.mark.parametrize('key', [
    curses.KEY_UP, curses.KEY_DOWN,
    curses.KEY_PPAGE, curses.KEY_NPAGE,
    curses.KEY_HOME, curses.KEY_END,
    ord('j'), ord('k'), ord('0'), ord('$'), ord('H'), ord('M'), ord('L'),
    2, 4, 6, 21,
])
def test_taken_key_never_scrolls_and_is_returned_to_the_app(make, key):
    win, backend = make(backend=HeadlessBackend(rows=12, cols=80),
                        body_rows=60, head_rows=2, taken_nav_keys={key: 'app'})
    for i in range(40):
        win.add_body(f'row {i}')
    win.fix_positions()
    win.scroll_pos = min(10, win.max_scroll_pos)
    win.fix_positions()
    before = win.scroll_pos

    backend.queue_keys(key)
    assert win.prompt(seconds=0.5) == key  # relax_handled_keys default: app gets it
    assert win.scroll_pos == before


def test_taken_key_without_binding_may_be_swallowed_when_not_relaxed(make):
    # Existing handled_keys/relax_handled_keys rules apply; ownership does not
    # implicitly add the key to handled_keys.
    win, backend = make(relax_handled_keys=False, taken_nav_keys={curses.KEY_DOWN: ''})
    for i in range(40):
        win.add_body(f'row {i}')
    win.fix_positions()
    before = win.scroll_pos
    backend.queue_keys(curses.KEY_DOWN)
    assert win.prompt(seconds=0.02) is None
    assert win.scroll_pos == before


def test_spinner_accepts_a_taken_key_and_the_action_fires(make):
    opts = ConsoleWindowOpts(
        taken_nav_keys={curses.KEY_RIGHT: 'next'},
        relax_handled_keys=False,
    )
    win, backend = make(taken_nav_keys=opts.taken_nav_keys,
                        relax_handled_keys=False)
    spin = OptionSpinner(nav_keys=opts.nav_keys)
    spin.add_key('next', '→ - next', genre='action', keys=[curses.KEY_RIGHT])
    win.set_handled_keys(spin)

    backend.queue_keys(curses.KEY_RIGHT)
    assert win.prompt(seconds=0.5) == curses.KEY_RIGHT
    assert win.scroll_pos == 0

    spin.do_key(curses.KEY_RIGHT, win)
    assert spin.default_obj.next is True


def test_spinner_still_rejects_a_retained_navigation_key():
    opts = ConsoleWindowOpts(taken_nav_keys={curses.KEY_LEFT: 'prev'})
    spin = OptionSpinner(nav_keys=opts.nav_keys)
    with pytest.raises(ValueError, match='navigation key'):
        spin.add_key('jump', 'UP - reserved', genre='action', keys=[curses.KEY_UP])


# --- isolation --------------------------------------------------------------

def test_two_windows_with_different_bindings_do_not_affect_each_other(make):
    global_keys = frozenset(NAVIGATION_KEYS)

    left, _left_backend = make(taken_nav_keys={curses.KEY_LEFT: 'prev'})
    for i in range(40):
        left.add_body(f'row {i}')
    left.fix_positions()

    right, right_backend = make()
    for i in range(40):
        right.add_body(f'row {i}')
    right.fix_positions()
    right.scroll_pos = min(5, right.max_scroll_pos)
    right.fix_positions()
    before = right.scroll_pos

    assert left.opts.nav_keys == global_keys - {curses.KEY_LEFT}
    assert right.opts.nav_keys == global_keys
    # The untouched window still navigates normally.
    right_backend.queue_keys(curses.KEY_DOWN)
    right.prompt()
    assert right.scroll_pos == before + 1
    # And the module global was never mutated.
    assert frozenset(NAVIGATION_KEYS) == global_keys
    assert left.opts.taken_nav_keys == {curses.KEY_LEFT: 'prev'}


# --- dialogs and help -------------------------------------------------------

def test_dialogs_still_edit_with_taken_arrow_and_home_end_keys(make):
    win, backend = make(taken_nav_keys={
        curses.KEY_LEFT: '', curses.KEY_RIGHT: '',
        curses.KEY_HOME: '', curses.KEY_END: '',
    })
    backend.queue_keys(ord('h'), ord('i'), curses.KEY_LEFT,
                       curses.KEY_BACKSPACE, 10)
    assert win.answer() == 'i'

    backend.queue_keys(curses.KEY_HOME, curses.KEY_DC, 10)
    assert win.answer(seed='ab') == 'b'


def test_default_help_is_generated_from_the_structured_table():
    opts = ConsoleWindowOpts()
    lines = window_mod.render_nav_help(opts.nav_keys, opts.taken_nav_keys)
    assert lines == NAV_KEY_LINES
    # Two aligned rows: one action per chunk, each key an alternative for it.
    assert len(lines) == 2
    assert lines[0] == ('NavKeys:    pos: H/M/L    half: ^u/^d    '
                        'page: ^b/^f/PPAGE/NPAGE')
    assert lines[1] == (' up: k/UP  down: j/DOWN  first: 0/HOME   '
                        'last: $/END')
    # The gap on the last row's "first" chunk exists to land its last column
    # under the top row's "page".
    assert lines[0].index('page:') == lines[1].index('last:')
    # The compact form exists to stay readable at terminal width.
    assert all(len(line) <= 78 for line in lines)


def test_help_omits_taken_nav_keys_and_shows_app_labels(make):
    win, _backend = make(taken_nav_keys={
        curses.KEY_UP: 'app up',
        curses.KEY_LEFT: 'prev',
        curses.KEY_RIGHT: 'next',
    })
    lines = win.nav_help_lines()
    # Everything from the App: line onward is the app's block; its second line
    # is indented, so split at the boundary instead of filtering on "App:".
    app_start = next(
        index for index, line in enumerate(lines) if line.startswith('App:'))
    nav_text = '\n'.join(lines[:app_start])
    app_text = '\n'.join(lines[app_start:])

    # UP is gone from its action chunk, but its vi sibling k remains.
    assert 'k/UP' not in nav_text
    assert 'up: k' in nav_text
    assert 'down: j/DOWN' in nav_text
    # Taken keys are advertised under App: with the caller's labels.
    assert '←: prev' in app_text
    assert '→: next' in app_text
    assert 'UP: app up' in app_text
    assert lines[-2].startswith('App:') or lines[-1].startswith('App:')


def test_spinner_help_renders_from_the_window(make):
    win, _backend = make(taken_nav_keys={curses.KEY_LEFT: 'prev'})
    spin = OptionSpinner(nav_keys=win.opts.nav_keys)
    spin.show_help_nav_keys(win)
    header_text = '\n'.join(win.head.texts)
    assert '←: prev' in header_text
