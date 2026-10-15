"""Key constants shared across console_window.

Kept dependency-free (only ``curses``) so that both the window engine and the
option spinner can import it without risking circular imports.

:data:`NAVIGATION_KEYS` is the set of key codes reserved for cursor movement and
scrolling.  These are rejected by :meth:`OptionSpinner.add_key` (which raises
``ValueError``) and are skipped in demo-mode highlighting, so applications
**cannot bind them**.  That reservation deliberately includes the bare keys
``0``, ``$``, ``H``, ``M`` and ``L`` — surface this in your app's help/docs,
because those characters are unavailable as single-key shortcuts.
"""

from __future__ import annotations

import curses

# Keys reserved for cursor movement and scrolling.  Applications cannot bind
# these: OptionSpinner.add_key rejects them with ValueError, and demo-mode
# highlighting ignores them.
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
