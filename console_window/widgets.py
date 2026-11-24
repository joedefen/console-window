"""Inline editors and prompt widgets."""

from __future__ import annotations

import curses
from collections.abc import Callable
from typing import ClassVar

from . import glyphs
from .header import HeaderLine
from .textwidth import cell_to_index, char_width, string_width, truncate

# Backspace, in every terminal variant, shared by both widgets.
_BACKSPACE_KEYS = (127, 8, curses.KEY_BACKSPACE, 263)


class InlineConfirmation:
    """One-line editor that resolves a typed answer against a mode.

    Modes are `'Y'`/`'y'` (press the key), `'yes'`/`'YES'` (type it),
    `'identity'` (type the expected string verbatim), `'choices'` (any of a list,
    by exact text or unique prefix) and `'text'` (anything non-empty).
    `handle_key()` is a pure state machine: it never draws and never calls back.
    """

    MODES = 'Y y YES yes identity choices text'.split()

    def __init__(self, min_abbrev_chars: int | None = None) -> None:
        self.active: bool = False
        self.action_type: str | None = None
        self.identity: str | None = None
        self.choices: list[str] | None = None
        self._input_buffer: str = ''
        self._cursor_pos: int = 0
        self.mode: str | None = None
        self.min_abbrev_chars: int | None = min_abbrev_chars
        self._calculated_min_abbrev: int | None = None

    def start(self, action_type: str | None = None, identity: str | None = None,
              choices: str | list[str] | tuple[str, ...] | None = None,
              mode: str | None = None, min_abbrev_chars: int | None = None,
              initial: str = '') -> None:
        """Begin editing, discarding any previous state.

        Args:
            identity: The string `mode='identity'` requires verbatim.
            choices: Allowed answers for `'choices'` mode.
            mode: One of `MODES`; defaults from the arguments.
            min_abbrev_chars: Shortest prefix accepted in `'choices'` mode.
            initial: Seed text, with the caret placed after it.
        """
        self.active = True
        self.action_type = action_type
        self.identity = identity
        self.choices = (list(choices) if isinstance(choices, (list, tuple))
                    else [choices] if isinstance(choices, str) else None)
        self._input_buffer = initial
        self._cursor_pos = len(initial)

        if min_abbrev_chars is not None:
            self.min_abbrev_chars = min_abbrev_chars
            self._calculated_min_abbrev = None
        else:
            self._calculated_min_abbrev = None

        self.mode = 'choices' if self.choices else mode if mode else 'yes'
        if self.mode not in self.MODES:
            self.mode = 'yes'
        if self.mode == 'choices' and not self.choices:
            self.mode = 'yes'

    def cancel(self) -> None:
        """Go inactive and forget the buffer and any pending answer."""
        self.active = False
        self.action_type = None
        self.choices = None
        self._input_buffer = ''
        self._cursor_pos = 0

    @property
    def input_buffer(self) -> str:
        """The text typed so far."""
        return self._input_buffer

    @input_buffer.setter
    def input_buffer(self, value: str) -> None:
        # Seeding by assignment leaves the caret at the end.
        self._input_buffer = value
        self._cursor_pos = len(value)

    @property
    def cursor_pos(self) -> int:
        """Caret position as a string index, not a display cell."""
        return self._cursor_pos

    @property
    def resolved_choice(self) -> str | None:
        """The canonical choice the current buffer would accept, else `None`."""
        return self._resolve_choice()

    @property
    def cursor_cell(self) -> int:
        """Caret column in terminal cells (wide chars occupy two)."""
        pos = self._snap_index(self._cursor_pos)
        return string_width(self._input_buffer[:pos])

    def _snap_index(self, index: int) -> int:
        # Never split a base character from its combining marks.
        index = max(0, min(index, len(self._input_buffer)))
        return cell_to_index(self._input_buffer,
                             string_width(self._input_buffer[:index]))

    def _move_cursor_left(self) -> None:
        pos = self._snap_index(self._cursor_pos)
        if pos <= 0:
            self._cursor_pos = 0
            return
        pos -= 1
        while pos > 0 and char_width(self._input_buffer[pos]) == 0:
            pos -= 1
        self._cursor_pos = pos

    def _move_cursor_right(self) -> None:
        pos = self._snap_index(self._cursor_pos)
        end = len(self._input_buffer)
        if pos >= end:
            self._cursor_pos = end
            return
        pos += 1
        while pos < end and char_width(self._input_buffer[pos]) == 0:
            pos += 1
        self._cursor_pos = pos

    def _insert_text(self, text: str) -> None:
        pos = self._snap_index(self._cursor_pos)
        self._input_buffer = (self._input_buffer[:pos] + text
                              + self._input_buffer[pos:])
        self._cursor_pos = pos + len(text)

    def _delete_backward(self) -> None:
        end = self._snap_index(self._cursor_pos)
        if end <= 0:
            self._cursor_pos = 0
            return
        self._cursor_pos = end
        self._move_cursor_left()
        self._input_buffer = (self._input_buffer[:self._cursor_pos]
                              + self._input_buffer[end:])

    def _delete_forward(self) -> None:
        start = self._snap_index(self._cursor_pos)
        end = len(self._input_buffer)
        if start >= end:
            self._cursor_pos = start
            return
        pos = start + 1
        while pos < end and char_width(self._input_buffer[pos]) == 0:
            pos += 1
        self._input_buffer = self._input_buffer[:start] + self._input_buffer[pos:]
        self._cursor_pos = start

    def _calculate_min_abbrev_chars(self) -> int:
        choices = self.choices
        if not choices or len(choices) <= 1:
            return 1

        max_len = max(len(c) for c in choices)

        for prefix_len in range(1, max_len + 1):
            prefixes = {}
            for choice in choices:
                prefix = choice[:prefix_len].lower()
                if prefix in prefixes:
                    break
                prefixes[prefix] = choice
            else:
                # One spare character makes an early ENTER less likely.
                return min(prefix_len + 1, max_len)

        # The choices cannot be disambiguated (e.g. "Yes" and "yes").
        return max_len

    def _get_effective_min_abbrev_chars(self) -> int:
        if self.min_abbrev_chars is not None:
            return self.min_abbrev_chars

        # A local keeps the narrowed type; mypy does not narrow attributes.
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
        """Consume one key and report `'continue'`, `'confirmed'` or `'cancelled'`."""
        if key == 27:
            return 'cancelled'

        if self.mode in ('Y', 'y'):
            return self._handle_single_key_mode(key)

        if 32 <= key <= 126:
            self._insert_text(chr(key))
        elif key in _BACKSPACE_KEYS:
            self._delete_backward()
        elif key == curses.KEY_DC:
            self._delete_forward()
        elif key == curses.KEY_LEFT:
            self._move_cursor_left()
        elif key == curses.KEY_RIGHT:
            self._move_cursor_right()
        elif key in (curses.KEY_HOME, 1):  # Home / Ctrl-A
            self._cursor_pos = 0
        elif key in (curses.KEY_END, 5):  # End / Ctrl-E
            self._cursor_pos = len(self._input_buffer)
        elif key in (10, 13):  # Enter
            return self._handle_enter()

        return 'continue'

    def _handle_single_key_mode(self, key: int) -> str:
        mode = self.mode or ''
        if mode and key == ord(mode[0]):
            self.input_buffer = mode
            return 'confirmed'
        return 'continue'

    def _handle_enter(self) -> str:
        if self.mode == 'text':
            return 'confirmed' if self.input_buffer else 'continue'

        match = self._match_buffer()
        if match:
            self.input_buffer = match
            return 'confirmed'

        self.input_buffer = ''
        return 'continue'

    def _match_buffer(self) -> str | None:
        if self.mode == 'choices':
            return self._resolve_choice()
        if self.mode == 'identity':
            return self.identity if self.input_buffer == self.identity else None
        if self.mode == 'YES':
            return 'YES' if self.input_buffer == 'YES' else None
        return self.input_buffer if self.input_buffer.lower() == 'yes' else None

    def get_display_string(self, prompt: str = '', cursor_char: str | None = None) -> str:
        """Return the prompt and editable buffer with a caret glyph.

        Single-key modes return the prompt unchanged; an inactive widget
        returns `''`.  `cursor_char=None` uses the registered `cursor` glyph.
        """
        if not self.active:
            return ''
        if self.mode in ('Y', 'y'):
            return prompt
        if cursor_char is None:
            cursor_char = glyphs.get('cursor')
        pos = self._snap_index(self._cursor_pos)
        before = self._input_buffer[:pos]
        after = self._input_buffer[pos:]
        return f'{prompt}{before}{cursor_char}{after}'

    # Hints whose text does not depend on runtime state.
    _STATIC_HINTS: ClassVar[dict[str, str]] = {
        'YES': 'Type YES + ENTER or ESC',
        'yes': 'Type yes + ENTER or ESC',
        'text': 'Type text + ENTER or ESC',
    }

    def get_hint(self) -> str:
        """Hint line for the current mode; empty once any text is typed."""
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


class PromptLine:
    """An in-place prompt: text, an editable buffer, a hint and callbacks.

    Free of application concepts: the prompt is drawn verbatim and callbacks
    run only when the caller takes them (see `take`).
    """

    # `{mode}` is replaced with the live mode letter.
    DEFAULT_ANSWER_HINT = '[Press "{mode}" or ESC]'

    def __init__(self) -> None:
        self._editor = InlineConfirmation()
        # Public state, mirrored from start() so a caller can inspect it.
        self.active: bool = False
        self.prompt: str = ''
        self.hint: str = ''
        self.answer_hint: str = ''
        self._on_confirm: Callable[[str], object] | None = None
        self._on_cancel: Callable[[], object] | None = None
        self._answer: str | None = None
        self._result: str | None = None

    def start(self, prompt: str, *, hint: str = '', mode: str = 'y',
              identity: str | None = None, seed: str = '',
              choices: str | list[str] | tuple[str, ...] | None = None,
              on_confirm: Callable[[str], object] | None = None,
              on_cancel: Callable[[], object] | None = None,
              min_abbrev_chars: int | None = None,
              answer_hint: str = '') -> None:
        """Compose a prompt and make it active.

        Args:
            mode: Editor mode, as `InlineConfirmation` accepts.
            identity: Expected string for `mode='identity'`.
            choices: Allowed answers; forces `mode='choices'`.
            min_abbrev_chars: Shortest unique prefix that accepts a choice.
            answer_hint: Replacement for `DEFAULT_ANSWER_HINT`.
        """
        self._editor.start(action_type=None, identity=identity, choices=choices,
                           mode=mode, min_abbrev_chars=min_abbrev_chars,
                           initial=seed)
        self.active = True
        self.prompt = prompt
        self.hint = hint
        self.answer_hint = answer_hint
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._answer = None
        self._result = None

    def handle_key(self, key: int) -> str:
        """Feed one key to the editor; return `'continue'`, `'confirmed'` or `'cancelled'`.

        No callback runs here, so the window can restore its state first.
        """
        if not self.active:
            return 'continue'
        result = self._editor.handle_key(key)
        self._result = result
        if result == 'confirmed':
            self._answer = self._editor.input_buffer
        return result

    def take(self) -> tuple[str | None, Callable[[str], object] | None,
                            Callable[[], object] | None]:
        """Cancel the widget and hand back `(answer, on_confirm, on_cancel)`.

        The answer is non-`None` only for a confirmed result.
        """
        answer = self._answer if self._result == 'confirmed' else None
        on_confirm, on_cancel = self._on_confirm, self._on_cancel
        self.cancel()
        return answer, on_confirm, on_cancel

    def cancel(self) -> None:
        """Discard the prompt.  Idempotent."""
        self.active = False
        self._editor.cancel()
        self.prompt = ''
        self.hint = ''
        self.answer_hint = ''
        self._on_confirm = None
        self._on_cancel = None
        self._answer = None
        self._result = None

    def get_display_string(self, cursor_char: str | None = None) -> str:
        """The prompt as one line, with the caret glyph for editable modes."""
        if not self.active:
            return ''
        if cursor_char is None:
            cursor_char = glyphs.get('cursor')
        mode = self._editor.mode or ''
        if mode in ('Y', 'y'):
            hint = self.answer_hint or self.DEFAULT_ANSWER_HINT
            # replace() rather than format(): the template is caller text and
            # may legitimately contain braces (`["y" or ESC] {⚠️}` style
            # decorations are not worth a formatting error at paint time).
            return f'{self.prompt}  {hint.replace("{mode}", mode)}'
        buffer = self._editor.get_display_string('', cursor_char)
        return f'{self.prompt}: {buffer}'

    def get_hint_string(self, width: int | None = None) -> str:
        """The hint, cut to *width* cells when a width is given."""
        if not self.active or not self.hint:
            return ''
        if width is None:
            return self.hint
        return truncate(self.hint, width)

    def get_choice_lines(self) -> list[str]:
        """One line per choice, marking the currently resolved one."""
        if not self.active or self._editor.mode != 'choices':
            return []
        resolved = self._editor.resolved_choice
        marker = glyphs.get('choice')
        return [f'{marker} {choice}' if choice == resolved else f'  {choice}'
                for choice in (self._editor.choices or [])]


class IncrementalSearchBar:
    """A filter bar: pattern text, a caret and the three search callbacks.

    ENTER accepts and ESC restores the starting text; `reset()` changes the
    pattern silently.
    """

    def __init__(self, on_change: Callable[[str], None] | None = None,
                 on_accept: Callable[[str], None] | None = None,
                 on_cancel: Callable[[str], None] | None = None) -> None:
        self._active = False
        self._text = ''
        self._cursor_pos = 0
        self._start_text = ''
        self.on_change = on_change
        self.on_accept = on_accept
        self.on_cancel = on_cancel

        # Built per instance so the bound methods are current.
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
        """Enter search mode with *initial_text*, which ESC also restores."""
        self._active = True
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def reset(self, initial_text: str = '') -> None:
        """Leave search mode with *initial_text* in the buffer, silently."""
        self._active = False
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def handle_key(self, key: int) -> bool:
        """Feed one key to the bar; True when the bar consumed it."""
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

    def get_display_string(self, prefix: str = '/', suffix: str = '',
                           cursor_char: str | None = None) -> str:
        """The bar as one line: prefix, pattern and caret.

        Args:
            cursor_char: Caret to draw, or `None` for `cursor_block`.
        """
        if self._active:
            # The space keeps the prefix from starting a SEARCH span.
            if cursor_char is None:
                cursor_char = glyphs.get('cursor_block')
            before = self._text[:self._cursor_pos]
            after = self._text[self._cursor_pos:]
            return f'{prefix} {before}{cursor_char}{after}{suffix}'
        if self._text:
            return f'{prefix}{self._text}{suffix}'
        return ''

    def as_header_line(self, prefix: str = '/', cursor_char: str | None = None,
                       invalid: bool = False) -> HeaderLine:
        """The bar as header spans: the prefix, the pattern and the caret.

        *invalid* styles only the prefix, signaling that the pattern does not
        compile yet while keeping the text readable.
        """
        line = HeaderLine()
        if not self._text and not self._active:
            return line
        if self._active:
            if cursor_char is None:
                cursor_char = glyphs.get('cursor_block')
            before = self._text[:self._cursor_pos]
            after = self._text[self._cursor_pos:]
            content = f'{before}{cursor_char}{after}'
        else:
            content = self._text
        if invalid:
            line.search('', prefix=prefix)
            return line.text(f' {content}' if self._active else content)
        if self._active:
            return line.text(f'{prefix} {content}')
        return line.search(content, prefix=prefix)

    @property
    def is_active(self) -> bool:
        """True while the bar is accepting keys."""
        return self._active

    @property
    def text(self) -> str:
        """The current pattern."""
        return self._text

    @property
    def cursor_pos(self) -> int:
        """Caret position as a string index, not a display cell."""
        return self._cursor_pos
