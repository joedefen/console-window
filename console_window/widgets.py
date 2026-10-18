from __future__ import annotations

import curses
from typing import Callable, ClassVar

from .header import HeaderLine

# Keys treated as backspace (all terminal variants).  Shared by both widgets so
# the list cannot drift between them.
_BACKSPACE_KEYS = (127, 8, curses.KEY_BACKSPACE, 263)


class InlineConfirmation:
    MODES = 'Y y YES yes identity choices text'.split()

    def __init__(self, min_abbrev_chars: int | None = None) -> None:
        self.active: bool = False
        self.action_type: str | None = None  # e.g., 'wipe' or 'verify'
        self.identity: str | None = None     # e.g., 'sda1'
        self.choices: list[str] | None = None
        self.input_buffer: str = ''
        self.mode: str | None = None
        self.min_abbrev_chars: int | None = min_abbrev_chars
        self._calculated_min_abbrev: int | None = None  # Cached calculated value

    def start(self, action_type: str | None = None, identity: str | None = None,
              choices: str | list[str] | tuple[str, ...] | None = None,
              mode: str | None = None, min_abbrev_chars: int | None = None) -> None:
        self.active = True
        self.action_type = action_type
        self.identity = identity
        self.choices = (list(choices) if isinstance(choices, (list, tuple))
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
        self.active = False
        self.action_type = None
        self.choices = None
        self.input_buffer = ''

    def _calculate_min_abbrev_chars(self) -> int:
        choices = self.choices
        if not choices or len(choices) <= 1:
            return 1

        # Find minimum prefix length to distinguish all choices (case-insensitive)
        max_len = max(len(c) for c in choices)

        for prefix_len in range(1, max_len + 1):
            prefixes = {}
            for choice in choices:
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
        if self.min_abbrev_chars is not None:
            return self.min_abbrev_chars

        # Calculate if not cached (local keeps the narrowed type; mypy does not
        # narrow instance attributes across methods).
        calc = self._calculated_min_abbrev
        if calc is None:
            calc = self._calculate_min_abbrev_chars()
            self._calculated_min_abbrev = calc
        return calc

    def _resolve_choice(self) -> str | None:
        buf = self.input_buffer
        if not buf:
            return None

        for match in (self._match_exact,
                      self._match_case_insensitive,
                      self._match_prefix):
            resolved = match(buf)
            if resolved is not None:
                return resolved
        return None

    def _match_exact(self, buf: str) -> str | None:
        choices = self.choices or []
        return buf if buf in choices else None

    def _match_case_insensitive(self, buf: str) -> str | None:
        choices = self.choices or []
        ci_matches = [c for c in choices if c.lower() == buf.lower()]
        return ci_matches[0] if len(ci_matches) == 1 else None

    def _match_prefix(self, buf: str) -> str | None:
        if len(buf) < self._get_effective_min_abbrev_chars():
            return None

        choices = self.choices or []
        ss_matches = [c for c in choices if c.startswith(buf)]
        if len(ss_matches) == 1:
            return ss_matches[0]

        buf_l = buf.lower()
        ss_ci_matches = [c for c in choices if c.lower().startswith(buf_l)]
        return ss_ci_matches[0] if len(ss_ci_matches) == 1 else None

    def handle_key(self, key: int) -> str:
        if key == 27:
            return 'cancelled'

        # Handle single-key modes
        if self.mode in ('Y', 'y'):
            return self._handle_single_key_mode(key)

        # Handle buffered input
        if 32 <= key <= 126:
            self.input_buffer += chr(key)
        elif key in _BACKSPACE_KEYS:  # Backspace (all variants)
            self.input_buffer = self.input_buffer[:-1]
        elif key in (10, 13):  # Enter
            return self._handle_enter()

        return 'continue'

    def _handle_single_key_mode(self, key: int) -> str:
        # Only 'Y'/'y' reach here, so the trigger key is always the mode's
        # first character (the old `self.mode == 'identity'` test was dead).
        mode = self.mode or ''
        if mode and key == ord(mode[0]):
            self.input_buffer = mode
            return 'confirmed'
        return 'continue'

    def _handle_enter(self) -> str:
        # 'text' mode: accept any input
        if self.mode == 'text':
            return 'confirmed' if self.input_buffer else 'continue'

        match = self._match_buffer()
        if match:
            self.input_buffer = match  # Canonicalize
            return 'confirmed'

        self.input_buffer = ''  # Reset on failure
        return 'continue'

    def _match_buffer(self) -> str | None:
        if self.mode == 'choices':
            return self._resolve_choice()
        if self.mode == 'identity':
            return self.identity if self.input_buffer == self.identity else None
        if self.mode == 'YES':
            return 'YES' if self.input_buffer == 'YES' else None
        # 'yes' or other permissive modes
        return self.input_buffer if self.input_buffer.lower() == 'yes' else None

    #: Hints whose text does not depend on runtime state.
    _STATIC_HINTS: ClassVar[dict[str, str]] = {
        'YES': 'Type YES + ENTER or ESC',
        'yes': 'Type yes + ENTER or ESC',
        'text': 'Type text + ENTER or ESC',
    }

    def get_hint(self) -> str:
        if self.input_buffer:
            return ''

        if self.mode in ('Y', 'y'):
            return f'Press {self.mode}'
        if self.mode == 'identity':
            return f'Type {self.identity} + ENTER or ESC'
        if self.mode == 'choices':
            return self._choices_hint()
        return self._STATIC_HINTS.get(self.mode or '', '')

    def _choices_hint(self) -> str:
        choices = self.choices or []
        if len(choices) == 1:
            return f'Type {choices[0]} + ENTER or ESC'
        min_chars = self._get_effective_min_abbrev_chars()
        return f'{min_chars}+ chars + ENTER or ESC'


class IncrementalSearchBar:
    def __init__(self, on_change: Callable[[str], None] | None = None,
                 on_accept: Callable[[str], None] | None = None,
                 on_cancel: Callable[[str], None] | None = None) -> None:
        self._active = False
        self._text = ''
        self._cursor_pos = 0
        self._start_text = ''  # Text when entering search mode

        # Callbacks
        self.on_change = on_change
        self.on_accept = on_accept
        self.on_cancel = on_cancel

        # Key dispatch: single-press key -> handler.  Built per instance so the
        # bound methods are current; Home/End also answer Ctrl-A/Ctrl-E.
        self._key_actions: dict[int, Callable[[], bool]] = {
            10: self._accept, 13: self._accept,
            27: self._cancel,
            curses.KEY_LEFT: self._cursor_left,
            curses.KEY_RIGHT: self._cursor_right,
            curses.KEY_HOME: self._cursor_home, 1: self._cursor_home,
            curses.KEY_END: self._cursor_end, 5: self._cursor_end,
        }
        for code in _BACKSPACE_KEYS:
            self._key_actions[code] = self._backspace

    def start(self, initial_text: str = '') -> None:
        self._active = True
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def handle_key(self, key: int) -> bool:
        if not self._active:
            return False

        action = self._key_actions.get(key)
        if action is not None:
            return action()

        if 32 <= key <= 126:  # Printable characters - insert at cursor
            return self._insert(chr(key))

        return False

    def _accept(self) -> bool:
        self._active = False
        if self.on_accept:
            self.on_accept(self._text)
        return True

    def _cancel(self) -> bool:
        self._text = self._start_text
        self._active = False
        if self.on_cancel:
            self.on_cancel(self._start_text)
        return True

    def _backspace(self) -> bool:
        if self._cursor_pos > 0:
            chars = list(self._text)
            chars.pop(self._cursor_pos - 1)
            self._text = ''.join(chars)
            self._cursor_pos -= 1
            self._notify_change()
        return True

    def _insert(self, char: str) -> bool:
        chars = list(self._text)
        chars.insert(self._cursor_pos, char)
        self._text = ''.join(chars)
        self._cursor_pos += 1
        self._notify_change()
        return True

    def _cursor_left(self) -> bool:
        if self._cursor_pos > 0:
            self._cursor_pos -= 1
        return True

    def _cursor_right(self) -> bool:
        if self._cursor_pos < len(self._text):
            self._cursor_pos += 1
        return True

    def _cursor_home(self) -> bool:
        self._cursor_pos = 0
        return True

    def _cursor_end(self) -> bool:
        self._cursor_pos = len(self._text)
        return True

    def _notify_change(self) -> None:
        if self.on_change:
            self.on_change(self._text)

    def get_display_string(self, prefix: str = '/', suffix: str = '', cursor_char: str = '█') -> str:
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
        return self._active

    @property
    def text(self) -> str:
        return self._text

    @property
    def cursor_pos(self) -> int:
        return self._cursor_pos
