"""Key constants shared across console_window.

Kept dependency-free (only ``curses``) so that both the window engine and the
option spinner can import it without risking circular imports.
"""

import curses

# Navigation keys are reserved for cursor movement and scrolling.
# They are excluded from application key bindings (see OptionSpinner._register)
# and from demo-mode highlighting.
NAVIGATION_KEYS = {
    curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT,
    curses.KEY_HOME, curses.KEY_END, curses.KEY_PPAGE, curses.KEY_NPAGE,
    ord('j'), ord('k'),  # Vi-style up/down
    ord('0'), ord('$'), ord('H'), ord('M'), ord('L'),  # Line start/end, page positions
    ord('\x15'),  # Ctrl-U (half page up)
    ord('\x04'),  # Ctrl-D (half page down)
    ord('\x02'),  # Ctrl-B (page up)
    ord('\x06'),  # Ctrl-F (page down)
}
