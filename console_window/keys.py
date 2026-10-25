from __future__ import annotations

import curses

# Keys reserved for cursor movement and scrolling.  By default
# OptionSpinner.add_key rejects these with ValueError and demo-mode
# highlighting ignores them.  An application may take specific keys for its own
# use through ``ConsoleWindowOpts(taken_nav_keys=...)``; that withdraws them
# from navigation dispatch for that window only.
#
# The set is a plain ``set`` for 2.0 compatibility, but the library never
# mutates it.  Per-window ownership lives in ``ConsoleWindowOpts``: pass
# ``taken_nav_keys`` to withdraw a key from *that* window's navigation
# dispatch, and read ``opts.nav_keys`` for the effective (immutable) set.
# Never monkeypatch this module global; two windows with different bindings
# would contaminate each other.
NAVIGATION_KEYS: set[int] = {
    curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT,
    curses.KEY_HOME, curses.KEY_END, curses.KEY_PPAGE, curses.KEY_NPAGE,
    ord('j'), ord('k'),            # Vi-style up / down
    ord('0'), ord('$'),            # First / last row
    ord('H'), ord('M'), ord('L'),  # Top / middle / bottom of page
    ord('\x15'),  # Ctrl-U (half page up)
    ord('\x04'),  # Ctrl-D (half page down)
    ord('\x02'),  # Ctrl-B (page up)
    ord('\x06'),  # Ctrl-F (page down)
}

# The subset of NAVIGATION_KEYS that moves the viewport vertically.  When an
# application takes all of them (often to implement its own scrolling), the
# window still constructs, but "reduced navigation" deserves a warning.
VERTICAL_NAV_KEYS: frozenset[int] = frozenset({
    curses.KEY_UP, curses.KEY_DOWN,
    curses.KEY_HOME, curses.KEY_END, curses.KEY_PPAGE, curses.KEY_NPAGE,
    ord('j'), ord('k'), ord('0'), ord('$'), ord('H'), ord('M'), ord('L'),
    ord('\x15'), ord('\x04'), ord('\x02'), ord('\x06'),
})
