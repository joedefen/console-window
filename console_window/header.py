"""Explicit, unambiguous header-line construction (see ``AUDIT.md`` §4.14).

Historically :meth:`ConsoleWindow.add_fancy_header` re-parsed a plain string at
render time, *guessing* which characters were markup (``[x]`` keys, ``WORD:``
labels, ``/patterns``, a bold leading word).  That coupled **content** to
**presentation**: any data that merely *looked* like markup was restyled, and the
search bar had to inject a spacer to avoid a spurious ``/pattern`` match (the
"add space after prefix to prevent pattern matching in fancy_header" hack).

This module separates the two concerns:

* :class:`HeaderLine` builds a line from explicit :class:`Span` tokens, so the
  producer declares intent and nothing is guessed from the text.
* :func:`parse_fancy_header` is the legacy string scanner, kept for backward
  compatibility.  It is now a *pure* function returning roles (not curses
  attributes), so it is unit-testable without a terminal.

Roles are plain strings, so this module needs no ``curses`` import and its tests
run anywhere.
"""

from __future__ import annotations

import re
from typing import Iterator, NamedTuple

# Span roles.  The renderer (:meth:`ConsoleWindow._resolve_header_attr`) maps a
# role + format mode to a curses attribute; keeping roles abstract here keeps
# this module curses-free and the mapping in exactly one place.
PLAIN = 'plain'
KEY = 'key'
LABEL = 'label'
SEARCH = 'search'


class Span(NamedTuple):
    """A run of header text carrying a presentation :data:`role`."""

    text: str
    role: str = PLAIN


class HeaderLine:
    """Builder for a styled header line made of explicit :class:`Span` tokens.

    Example::

        line = HeaderLine()
        line.text('  ').bracket_key('v').text('iew ')
        line.key('SPC').text(':process')
        line.search('alice', prefix='/')
        win.add_header_line(line, mode='Underline')

    Nothing is re-parsed: :meth:`text` content (e.g. a filename like
    ``/etc/passwd``) is never restyled, however much it resembles markup.
    """

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def _add(self, text: str, role: str) -> HeaderLine:
        if text:
            self.spans.append(Span(text, role))
        return self

    def text(self, s: str) -> HeaderLine:
        """Append literal text (never styled, never reinterpreted)."""
        return self._add(s, PLAIN)

    def key(self, k: str, display: str | None = None) -> HeaderLine:
        """Append a key hint, e.g. ``key('a')`` or ``key('ESC', 'ESC')``."""
        return self._add(display if display is not None else k, KEY)

    def bracket_key(self, k: str) -> HeaderLine:
        """Append a bracketed key hint rendered as ``[k]`` with ``k`` styled."""
        self._add('[', PLAIN)
        self._add(k, KEY)
        return self._add(']', PLAIN)

    def label(self, s: str) -> HeaderLine:
        """Append a bold label (e.g. a column title)."""
        return self._add(s, LABEL)

    def search(self, pattern: str, prefix: str = '/') -> HeaderLine:
        """Append a highlighted search pattern as ``prefix + pattern``."""
        return self._add(prefix + pattern, SEARCH)

    def extend(self, other: HeaderLine) -> HeaderLine:
        """Append all spans of ``other`` to this line."""
        self.spans.extend(other.spans)
        return self

    def __iter__(self) -> Iterator[Span]:
        return iter(self.spans)

    def __len__(self) -> int:
        return len(self.spans)

    def __bool__(self) -> bool:
        return bool(self.spans)

    def __str__(self) -> str:
        """Return the line's plain text (all styling stripped)."""
        return ''.join(span.text for span in self.spans)


def _re_match_word(word: str) -> bool:
    """Return True if ``word`` is a simple ``\\w``/``-`` token."""
    return bool(re.match(r'^[\w-]+$', word))


def _re_match_key(s: str) -> str | None:
    """Match a leading multi-character key name followed by ``:`` (e.g. ``ESC:``)."""
    match = re.match(r'([A-Z]{2,}|[A-Z]):', s)
    return match.group(1) if match else None


def _re_match_pattern(s: str) -> str | None:
    """Match a leading ``/search-pattern`` token (including the slash)."""
    match = re.match(r'/(\S+)', s)
    return match.group(0) if match else None


def parse_fancy_header(line: str) -> list[Span]:
    """Parse a legacy marked-up header string into :class:`Span` tokens.

    This preserves the historical ``add_fancy_header`` behaviour *exactly*:

    * a leading ``\\w``/``-`` word becomes a :data:`LABEL` (bold) — note the
      historical quirk that this matches **any** first word, not only all-caps;
    * ``[x]`` becomes a styled ``x`` (brackets removed);
    * ``WORD:`` at a token boundary styles ``WORD`` and leaves ``:`` plain;
    * ``/pattern`` at a token boundary becomes a single :data:`SEARCH` span.

    Because it guesses, it can misfire on data that merely looks like markup;
    prefer :class:`HeaderLine` for content whose intent is known.

    :param line: The marked-up header text.
    :returns: The parsed spans, in order.
    """
    result: list[Span] = []
    i = 0
    current_text = ''

    def flush() -> None:
        nonlocal current_text
        if current_text:
            result.append(Span(current_text, PLAIN))
            current_text = ''

    # Bold the first word (historical quirk: matches any word, not just caps).
    stripped = line.lstrip()
    if stripped:
        first_word = stripped.split()[0] if stripped.split() else ''
        if first_word and _re_match_word(first_word):
            leading = line[:len(line) - len(stripped)]
            if leading:
                result.append(Span(leading, PLAIN))
            result.append(Span(first_word, LABEL))
            i = len(leading) + len(first_word)

    while i < len(line):
        # [x] -> styled x (brackets removed)
        if line[i] == '[' and i + 2 < len(line) and line[i + 2] == ']':
            flush()
            result.append(Span(line[i + 1], KEY))
            i += 3
        elif i == 0 or line[i - 1] == ' ':
            key_match = _re_match_key(line[i:])
            if key_match:
                flush()
                result.append(Span(key_match, KEY))
                result.append(Span(':', PLAIN))
                i += len(key_match) + 1
            else:
                pattern_match = _re_match_pattern(line[i:])
                if pattern_match:
                    flush()
                    result.append(Span(pattern_match, SEARCH))
                    i += len(pattern_match)
                else:
                    current_text += line[i]
                    i += 1
        else:
            current_text += line[i]
            i += 1

    flush()
    return result
