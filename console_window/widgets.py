from __future__ import annotations

import curses
from typing import Callable, ClassVar

from . import glyphs
from .header import HeaderLine
from .textwidth import cell_to_index, char_width, string_width, truncate

# Keys treated as backspace (all terminal variants).  Shared by both widgets so
# the list cannot drift between them.
_BACKSPACE_KEYS = (127, 8, curses.KEY_BACKSPACE, 263)


class InlineConfirmation:
    """One-line editor that resolves a typed answer against a mode.

    Modes are ``'Y'``/``'y'`` (press the key), ``'yes'``/``'YES'`` (type it),
    ``'identity'`` (type the expected string verbatim), ``'choices'`` (any of a
    list, by exact text or unique prefix) and ``'text'`` (anything non-empty).
    ``handle_key()`` is a pure state machine: it never draws and never calls
    back.
    """

    MODES = 'Y y YES yes identity choices text'.split()

    def __init__(self, min_abbrev_chars: int | None = None) -> None:
        self.active: bool = False
        self.action_type: str | None = None  # e.g., 'wipe' or 'verify'
        self.identity: str | None = None     # e.g., 'sda1'
        self.choices: list[str] | None = None
        self._input_buffer: str = ''
        self._cursor_pos: int = 0
        self.mode: str | None = None
        self.min_abbrev_chars: int | None = min_abbrev_chars
        self._calculated_min_abbrev: int | None = None  # Cached calculated value

    def start(self, action_type: str | None = None, identity: str | None = None,
              choices: str | list[str] | tuple[str, ...] | None = None,
              mode: str | None = None, min_abbrev_chars: int | None = None,
              initial: str = '') -> None:
        """Begin editing, discarding any previous state.

        Args:
            action_type: App label for what is being confirmed, if any.
            identity: The string ``mode='identity'`` requires verbatim.
            choices: Allowed answers for ``'choices'`` mode; a bare string
                becomes a one-entry list.
            mode: One of ``MODES``; defaults to ``'choices'`` when *choices* is
                given, else ``'yes'``.
            min_abbrev_chars: Shortest prefix accepted in ``'choices'`` mode;
                ``None`` keeps the computed default.
            initial: Seed text, with the caret placed after it.
        """
        self.active = True
        self.action_type = action_type
        self.identity = identity
        self.choices = (list(choices) if isinstance(choices, (list, tuple))
                    else [choices] if isinstance(choices, str) else None)
        self._input_buffer = initial
        self._cursor_pos = len(initial)

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
        # Callers and older code seed the buffer by assignment; keeping the
        # caret at the end means the next key appends where a reader expects.
        self._input_buffer = value
        self._cursor_pos = len(value)

    @property
    def cursor_pos(self) -> int:
        """Caret position as a string index, not a display cell."""
        return self._cursor_pos

    @property
    def resolved_choice(self) -> str | None:
        """The canonical choice the current buffer would accept, else ``None``.

        Thin public wrapper over the abbreviation/exact matching used by
        ``handle_key()``; pickers and inline choice menus need to know which
        entry is currently resolved without duplicating that logic.
        """
        return self._resolve_choice()

    @property
    def cursor_cell(self) -> int:
        """Caret column in terminal cells (wide chars occupy two)."""
        pos = self._snap_index(self._cursor_pos)
        return string_width(self._input_buffer[:pos])

    def _snap_index(self, index: int) -> int:
        # The caret is a string index, but a display-cell split must not land
        # between a base character and its combining marks.  textwidth maps the
        # index's cell back to a safe code-point boundary.
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
        """Consume one key and report the resulting state.

        Args:
            key: ``curses`` key code.

        Returns:
            ``'continue'``, ``'confirmed'`` or ``'cancelled'``.
        """
        if key == 27:
            return 'cancelled'

        # Handle single-key modes
        if self.mode in ('Y', 'y'):
            return self._handle_single_key_mode(key)

        # Handle buffered input
        if 32 <= key <= 126:
            self._insert_text(chr(key))
        elif key in _BACKSPACE_KEYS:  # Backspace (all variants)
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

    def get_display_string(self, prompt: str = '', cursor_char: str | None = None) -> str:
        """Return the prompt and editable buffer with a caret glyph.

        The caret index is split on a textwidth cell boundary, so a pasted
        wide character or combining mark cannot put the glyph mid-grapheme.
        Single-key modes (``Y``/``y``) have no editable text and return the
        prompt unchanged; an inactive widget returns ``''`` so a caller can
        decide when the row should disappear.

        ``cursor_char=None`` (the default) uses the registered ``cursor``
        glyph, so a terminal without ``│`` gets ``|`` without an app change.
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

    #: Hints whose text does not depend on runtime state.
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

    Deliberately free of application concepts: it does not know which row or
    item the prompt belongs to, and it never runs callbacks itself (see
    :meth:`take`).  ``start()`` composes an internal
    :class:`InlineConfirmation`; note that ``InlineConfirmation`` forces
    ``mode='choices'`` when ``choices`` is supplied -- that is intended, not a
    bug.  The caller's ``prompt`` text is used verbatim, so decorations such as
    a warning glyph stay in application code rather than in the library.  The
    same goes for the trailing answer hint: pass *answer_hint* to replace the
    default ``[Press "y" or ESC]`` wording, which lets an application bracket
    the whole line with its own glyphs.
    """

    #: Default trailing hint for the one-key confirmation modes.  ``{mode}`` is
    #: replaced with the live mode letter, so ``'y'`` and ``'Y'`` both label
    #: themselves without the caller tracking it.
    DEFAULT_ANSWER_HINT = '[Press "{mode}" or ESC]'

    def __init__(self) -> None:
        self._editor = InlineConfirmation()
        #: Public state, mirrored from start() so a caller can inspect it.
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
            prompt: Leading text, drawn verbatim.
            hint: Hint for the row below; ``''`` for none.
            mode: Editor mode, as ``InlineConfirmation`` accepts.
            identity: Expected string for ``mode='identity'``.
            seed: Initial buffer contents.
            choices: Allowed answers; forces ``mode='choices'``.
            on_confirm: Handed back by :meth:`take`; never called here.
            on_cancel: Handed back by :meth:`take`; never called here.
            min_abbrev_chars: Shortest unique prefix that accepts a choice.
            answer_hint: Replacement for ``DEFAULT_ANSWER_HINT``.
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
        """Feed one key to the editor; return a pure state-machine result.

        Returns ``'continue'``, ``'confirmed'`` or ``'cancelled'``.  No
        callback runs here, which is what makes the widget testable without a
        window (and lets the window restore its own state before callbacks).
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
        """Cancel the widget and hand back ``(answer, on_confirm, on_cancel)``.

        The answer is only non-``None`` for a confirmed result.  This is the
        seam that lets the window tear the prompt down *before* running the
        callbacks; ``take()`` itself never calls them.
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
        """The prompt as one line, with the caret glyph for editable modes.

        Args:
            cursor_char: Caret to draw, or ``None`` for the registered
                ``cursor`` glyph.
        """
        if not self.active:
            return ''
        if cursor_char is None:
            cursor_char = glyphs.get('cursor')
        mode = self._editor.mode or ''
        if mode in ('Y', 'y'):
            hint = self.answer_hint or self.DEFAULT_ANSWER_HINT
            # replace() rather than format(): the template is caller text and
            # may legitimately contain braces (``["y" or ESC] {⚠️}`` style
            # decorations are not worth a formatting error at paint time).
            return f'{self.prompt}  {hint.replace("{mode}", mode)}'
        buffer = self._editor.get_display_string('', cursor_char)
        return f'{self.prompt}: {buffer}'

    def get_hint_string(self, width: int | None = None) -> str:
        """The hint, cut to *width* cells when a width is given.

        Args:
            width: Maximum display cells, or ``None`` for the whole hint.
        """
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
        # One cell plus a space on both branches, so the choices stay in one
        # column whichever glyph the terminal can draw.
        marker = glyphs.get('choice')
        return [f'{marker} {choice}' if choice == resolved else f'  {choice}'
                for choice in (self._editor.choices or [])]


class IncrementalSearchBar:
    """A filter bar: pattern text, a caret and the three search callbacks.

    Arrows and Home/End (also Ctrl-A/Ctrl-E) move the caret, backspace deletes,
    ENTER accepts and ESC restores the text the search started with.  Callbacks
    fire from ``handle_key()``; ``reset()`` is the silent counterpart for a
    caller that changes the pattern itself.
    """

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
        """Enter search mode with *initial_text* and the caret at its end.

        Args:
            initial_text: Pattern to start from; also what ESC restores.
        """
        self._active = True
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def reset(self, initial_text: str = '') -> None:
        """Leave search mode with *initial_text* in the buffer, silently.

        The counterpart to :meth:`start` for a caller that changes the pattern
        itself (a clear action, say): no ``on_change`` or ``on_cancel`` callback
        runs, so the application stays the owner of its filter state.
        """
        self._active = False
        self._text = initial_text
        self._start_text = initial_text
        self._cursor_pos = len(initial_text)

    def handle_key(self, key: int) -> bool:
        """Feed one key to the bar.

        Args:
            key: ``curses`` key code.

        Returns:
            True when the bar consumed the key; False when inactive or for a
            key it does not handle.
        """
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
            prefix: Leading marker, usually ``'/'``.
            suffix: Trailing text for the caller's own decoration.
            cursor_char: Caret to draw, or ``None`` for ``cursor_block``.
        """
        if self._active:
            # Show cursor position with cursor_char (block by default for visibility).
            # The space after the prefix keeps the indicator readable; it also kept
            # the string safe from add_fancy_header's parser.  New code should use
            # as_header_line() (explicit SEARCH spans) and not rely on that.
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

        *invalid* styles only the prefix with the search role (reverse video in
        a fancy header), the caller's cue that the pattern being typed does not
        compile yet.  The text itself stays plain so it remains readable while
        it is being fixed.
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
