"""Reusable input widgets: incremental search bar and inline confirmation."""

from __future__ import annotations

import curses
from typing import Callable

from .header import HeaderLine


class InlineConfirmation:
    """
    Manages stateful inline confirmation prompts for destructive or critical operations.

    This class handles the transition from standard application input to a
    confirmation sub-state, supporting several verification modes. When a match
    is found in 'choices' mode, the input_buffer is updated to the full
    canonical string so the calling application can use it directly.

    Modes:
    - 'Y'/'y': Single-key immediate confirmation.
    - 'yes'/'YES': Explicit string confirmation (case-sensitive for 'YES').
    - 'identity': Requires typing a specific string (e.g., a device node like 'sda1').
    - 'choices': Flexible matching against a list of valid strings.
    - 'text': Free-form text input - accepts any text and confirms on ENTER.

    :param min_abbrev_chars: Minimum characters required for abbreviated choice matching.
                             When None (default), automatically calculates based on choices:
                             (min chars to disambiguate) + 1, capped at longest choice length.
    :type min_abbrev_chars: int or None

    Methods:
    - get_hint(): Returns a hint string when input_buffer is empty (display in dimmed/italic style)
    """
    MODES = 'Y y YES yes identity choices text'.split()

    def __init__(self, min_abbrev_chars: int | None = None) -> None:
        self.active = False
        self.action_type = None  # e.g., 'wipe' or 'verify'
        self.identity = None     # e.g., 'sda1'
        self.choices = None
        self.input_buffer = ''
        self.mode = None
        self.min_abbrev_chars = min_abbrev_chars
        self._calculated_min_abbrev = None  # Cached calculated value

    def start(self, action_type: str | None = None, identity: str | None = None,
              choices: str | list[str] | tuple[str, ...] | None = None,
              mode: str | None = None, min_abbrev_chars: int | None = None) -> None:
        self.active = True
        self.action_type = action_type
        self.identity = identity
        self.choices = (choices if isinstance(choices, (list, tuple))
                    else [choices] if isinstance(choices, str) else None)
        self.input_buffer = ''

        # Override min_abbrev_chars if provided
        if min_abbrev_chars is not None:
            self.min_abbrev_chars = min_abbrev_chars
            self._calculated_min_abbrev = None
        else:
            # Reset calculated value so it's recalculated for new choices
            self._calculated_min_abbrev = None

        # Logic to determine mode based on provided arguments
        self.mode = 'choices' if self.choices else mode if mode else 'yes'
        if self.mode not in self.MODES:
            self.mode = 'yes'
        if self.mode == 'choices' and not self.choices:
            self.mode = 'yes'

    def cancel(self) -> None:
        """Cancel the confirmation"""
        self.active = False
        self.action_type = None
        self.choices = None
        self.input_buffer = ''

    def _calculate_min_abbrev_chars(self) -> int:
        """
        Calculate minimum prefix length needed to disambiguate choices.
        Returns: min_length + 1, capped at longest choice length.
        """
        if not self.choices or len(self.choices) <= 1:
            return 1

        # Find minimum prefix length to distinguish all choices (case-insensitive)
        max_len = max(len(c) for c in self.choices)

        for prefix_len in range(1, max_len + 1):
            prefixes = {}
            for choice in self.choices:
                prefix = choice[:prefix_len].lower()
                if prefix in prefixes:
                    # Collision found
                    break
                prefixes[prefix] = choice
            else:
                # No collision at this length - we can disambiguate
                # Add 1 to make errors less likely, but cap at longest choice
                return min(prefix_len + 1, max_len)

        # If we get here, choices can't be disambiguated (e.g., "Yes" and "yes")
        # Still return a reasonable value
        return max_len

    def _get_effective_min_abbrev_chars(self) -> int:
        """Get the effective min_abbrev_chars value (explicit or calculated)."""
        if self.min_abbrev_chars is not None:
            return self.min_abbrev_chars

        # Calculate if not cached
        if self._calculated_min_abbrev is None:
            self._calculated_min_abbrev = self._calculate_min_abbrev_chars()

        return self._calculated_min_abbrev

    def _resolve_choice(self) -> str | None:
        """
        Tiered matching logic for choices. Returns the full string if
        a unique match is found, otherwise None.
        """
        buf = self.input_buffer
        if not buf: return None
        buf_l = buf.lower()

        # 1. Perfect matches
        if buf in self.choices: return buf

        # 2. Case-insensitive matches
        ci_matches = [c for c in self.choices if c.lower() == buf_l]
        if len(ci_matches) == 1: return ci_matches[0]

        # 3. Leading substring (min_abbrev_chars+ chars only)
        min_chars = self._get_effective_min_abbrev_chars()
        if len(buf) >= min_chars:
            # Case-sensitive substring
            ss_matches = [c for c in self.choices if c.startswith(buf)]
            if len(ss_matches) == 1: return ss_matches[0]

            # Case-insensitive substring
            ss_ci_matches = [c for c in self.choices if c.lower().startswith(buf_l)]
            if len(ss_ci_matches) == 1: return ss_ci_matches[0]

        return None

    def handle_key(self, key: int) -> str:
        if key == 27: return 'cancelled'

        # Handle single-key modes
        if self.mode in ('Y', 'y'):
            expected = self.identity if self.mode == 'identity' else self.mode
            if key == ord(expected[0]):
                self.input_buffer = expected
                return 'confirmed'
            return 'continue'

        # Handle buffered input
        if 32 <= key <= 126:
            self.input_buffer += chr(key)
        elif key in (127, 8, curses.KEY_BACKSPACE, 263): # Backspace (all variants)
            self.input_buffer = self.input_buffer[:-1]
        elif key in (10, 13): # Enter
            match = None

            # 'text' mode: accept any input
            if self.mode == 'text':
                return 'confirmed' if self.input_buffer else 'continue'

            if self.mode == 'choices':
                match = self._resolve_choice()
            elif self.mode == 'identity':
                if self.input_buffer == self.identity: match = self.identity
            elif self.mode == 'YES':
                if self.input_buffer == 'YES': match = 'YES'
            else: # 'yes' or other permissive modes
                if self.input_buffer.lower() == 'yes': match = self.input_buffer

            if match:
                self.input_buffer = match # Canonicalize
                return 'confirmed'

            self.input_buffer = '' # Reset on failure

        return 'continue'

    def get_hint(self) -> str:
        """
        Returns a hint string for display when input_buffer is empty.
        Intended to be shown in dimmed/italic style.
        """
        if self.input_buffer:
            return ''

        if self.mode in ('Y', 'y'):
            return f'Press {self.mode}'
        if self.mode == 'YES':
            return 'Type YES + ENTER or ESC'
        if self.mode == 'yes':
            return 'Type yes + ENTER or ESC'
        if self.mode == 'identity':
            return f'Type {self.identity} + ENTER or ESC'
        if self.mode == 'text':
            return 'Type text + ENTER or ESC'
        if self.mode == 'choices':
            if len(self.choices) == 1:
                return f'Type {self.choices[0]} + ENTER or ESC'
            min_chars = self._get_effective_min_abbrev_chars()
            return f'{min_chars}+ chars + ENTER or ESC'
        return ''


class IncrementalSearchBar:
    """
    Generic incremental search bar with text editing and cursor support.

    Provides a reusable pattern for implementing search-as-you-type functionality
    with full cursor editing capabilities (backspace, arrows, home/end, printable chars).

    Features:
        - Text editing with cursor position tracking
        - ENTER to accept changes, ESC to cancel (restores original text)
        - Callbacks for text changes, accept, and cancel events
        - Formatted display string with cursor indicator
        - Integrates with ConsoleWindow's passthrough_mode

    Example Usage:
        # Define callbacks for your application
        def on_text_change(text):
            # Update filter/search results incrementally
            app.compile_filter(text)

        def on_accept(text):
            # Finalize search, disable passthrough mode
            app.search_complete = True
            win.passthrough_mode = False

        def on_cancel(original_text):
            # Restore original state
            app.compile_filter(original_text)
            win.passthrough_mode = False

        # Create search bar instance
        search_bar = IncrementalSearchBar(
            on_change=on_text_change,
            on_accept=on_accept,
            on_cancel=on_cancel
        )

        # In your key binding action (e.g., slash key):
        def slash_ACTION(self):
            app.search_bar.start(app.current_filter)  # Start with current filter
            app.win.passthrough_mode = True  # Enable key passthrough

        # In your main event loop:
        key = win.prompt()
        if key is not None:
            if search_bar.is_active:
                # Let search bar handle the key first
                if search_bar.handle_key(key):
                    continue  # Key was handled, skip normal processing
            # Normal key handling...

        # In your header/display code (preferred: explicit, unguessable spans):
        line = search_bar.as_header_line(prefix='/')
        if line:
            win.add_header_line(line)

    Key Handling:
        - ENTER (10, 13): Accept current text, exit search mode
        - ESC (27): Cancel, restore original text, exit search mode
        - Backspace (8, 127, 263, KEY_BACKSPACE): Delete char before cursor
        - Left/Right arrows: Move cursor
        - Home/Ctrl-A: Move cursor to start
        - End/Ctrl-E: Move cursor to end
        - Printable chars (32-126): Insert at cursor position
    """

    def __init__(self, on_change: Callable[[str], None] | None = None,
                 on_accept: Callable[[str], None] | None = None,
                 on_cancel: Callable[[str], None] | None = None) -> None:
        """
        Initialize the incremental search bar.

        :param on_change: Callback function(text) called when text changes.
                         Use this to update search results incrementally.
        :param on_accept: Callback function(text) called when ENTER is pressed.
                         Use this to finalize the search.
        :param on_cancel: Callback function(original_text) called when ESC is pressed.
                         Use this to restore previous state.
        """
        self._active = False
        self._text = ''
        self._cursor_pos = 0
        self._start_text = ''  # Text when entering search mode

        # Callbacks
        self.on_change = on_change
        self.on_accept = on_accept
        self.on_cancel = on_cancel

    def start(self, initial_text: str = '') -> None:
        """
        Enter search mode with optional initial text.

        :param initial_text: Starting text for the search bar (default: empty string)
        """
        self._active = True
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def handle_key(self, key: int) -> bool:
        """
        Handle a key press in search mode.

        :param key: Key code from curses
        :returns: True if the key was handled, False otherwise
        """
        if not self._active:
            return False

        # ENTER - accept search
        if key in [10, 13]:
            self._active = False
            if self.on_accept:
                self.on_accept(self._text)
            return True

        # ESC - cancel search, restore original text
        if key == 27:
            self._text = self._start_text
            self._active = False
            if self.on_cancel:
                self.on_cancel(self._start_text)
            return True

        # Backspace - delete character before cursor
        if key in [curses.KEY_BACKSPACE, 127, 8, 263]:
            if self._cursor_pos > 0:
                chars = list(self._text)
                chars.pop(self._cursor_pos - 1)
                self._text = ''.join(chars)
                self._cursor_pos -= 1
                if self.on_change:
                    self.on_change(self._text)
            return True

        # Left arrow - move cursor left
        if key == curses.KEY_LEFT:
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
            return True

        # Right arrow - move cursor right
        if key == curses.KEY_RIGHT:
            if self._cursor_pos < len(self._text):
                self._cursor_pos += 1
            return True

        # Home or Ctrl-A - move to start
        if key in (curses.KEY_HOME, 1):
            self._cursor_pos = 0
            return True

        # End or Ctrl-E - move to end
        if key in (curses.KEY_END, 5):
            self._cursor_pos = len(self._text)
            return True

        # Printable characters - insert at cursor
        if 32 <= key <= 126:
            chars = list(self._text)
            chars.insert(self._cursor_pos, chr(key))
            self._text = ''.join(chars)
            self._cursor_pos += 1
            if self.on_change:
                self.on_change(self._text)
            return True

        return False

    def get_display_string(self, prefix: str = '/', suffix: str = '', cursor_char: str = '█') -> str:
        """
        Get formatted display string with cursor indicator.

        When active (in search mode), shows cursor position with cursor_char (default: block).
        When inactive, just shows the text with prefix/suffix if text is non-empty.

        :param prefix: String to show before the search text (default: '/')
        :param suffix: String to show after the search text (default: '')
        :param cursor_char: Character to use for cursor (default: '█' block)
        :returns: Formatted string for display

        Example:
            Active with cursor: ' /hello█ world'
            Active at end: ' /hello world█'
            Inactive with text: ' /hello world'
            Inactive without text: ''
        """
        if self._active:
            # Show cursor position with cursor_char (block by default for visibility).
            # The space after the prefix keeps the indicator readable; it also kept
            # the string safe from add_fancy_header's parser.  New code should use
            # as_header_line() (explicit SEARCH spans) and not rely on that.
            before = self._text[:self._cursor_pos]
            after = self._text[self._cursor_pos:]
            return f'{prefix} {before}{cursor_char}{after}{suffix}'
        if self._text:
            return f'{prefix}{self._text}{suffix}'
        return ''

    def as_header_line(self, prefix: str = '/', cursor_char: str = '█') -> HeaderLine:
        """
        Build a :class:`~console_window.header.HeaderLine` for this search bar.

        Preferred over :meth:`get_display_string` when feeding a header via
        :meth:`ConsoleWindow.add_header_line`: the search text is emitted as an
        explicit SEARCH span, so it can never be mistaken for other markup (the
        reason the string form had to inject a spacer).

        :param prefix: String shown before the search text (default ``'/'``).
        :param cursor_char: Character marking the cursor while active (block by default).
        :returns: A HeaderLine (empty when inactive with no text).
        :rtype: HeaderLine
        """
        line = HeaderLine()
        if self._active:
            before = self._text[:self._cursor_pos]
            after = self._text[self._cursor_pos:]
            line.text(f'{prefix} {before}{cursor_char}{after}')
        elif self._text:
            line.search(self._text, prefix=prefix)
        return line

    @property
    def is_active(self) -> bool:
        """Whether search mode is currently active."""
        return self._active

    @property
    def text(self) -> str:
        """Current search text."""
        return self._text

    @property
    def cursor_pos(self) -> int:
        """Current cursor position within the text."""
        return self._cursor_pos
