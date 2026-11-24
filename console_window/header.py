"""Header spans and the header markup grammar."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import NamedTuple

# Roles stay abstract here so this module is curses-free; the window maps them
# to attributes.
PLAIN = 'plain'
KEY = 'key'
LABEL = 'label'
SEARCH = 'search'


class Span(NamedTuple):
    """One run of header text plus the role used to style it."""

    text: str
    role: str = PLAIN


class HeaderLine:
    """Builder for the explicit, unparsed header form.

    Each method appends one `Span` and returns `self`.  Roles come from the
    method, not punctuation: `key('x')` styles `x` as a key, while `text('[x]')`
    stays literal.  Empty strings add nothing.
    """

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def _add(self, text: str, role: str) -> HeaderLine:
        if text:
            self.spans.append(Span(text, role))
        return self

    def text(self, s: str) -> HeaderLine:
        """Append *s* as literal `PLAIN` text."""
        return self._add(s, PLAIN)

    def key(self, k: str, display: str | None = None) -> HeaderLine:
        """Append a `KEY` span, drawing *display* instead of *k* when given."""
        return self._add(display if display is not None else k, KEY)

    def bracket_key(self, k: str) -> HeaderLine:
        """Append `'['`, *k* as `KEY`, and `']'`; only `add_header_line` keeps them."""
        self._add('[', PLAIN)
        self._add(k, KEY)
        return self._add(']', PLAIN)

    def label(self, s: str) -> HeaderLine:
        """Append a `LABEL` span (the header's title)."""
        return self._add(s, LABEL)

    def search(self, pattern: str, prefix: str = '/') -> HeaderLine:
        """Append `prefix + pattern` as one `SEARCH` span."""
        return self._add(prefix + pattern, SEARCH)

    def extend(self, other: HeaderLine) -> HeaderLine:
        """Append every span of *other* to this line."""
        self.spans.extend(other.spans)
        return self

    def __iter__(self) -> Iterator[Span]:
        return iter(self.spans)

    def __len__(self) -> int:
        return len(self.spans)

    def __bool__(self) -> bool:
        return bool(self.spans)

    def __str__(self) -> str:
        """The line as text, including literal markup characters."""
        return ''.join(span.text for span in self.spans)


def strip_key_brackets(spans: Iterable[Span]) -> list[Span]:
    """Remove literal `[`/`]` delimiters around explicit `KEY` spans.

    The explicit-token API keeps the brackets; the fancy header path treats
    them as markup, matching the `[x]` rule while preserving span roles.
    """
    pending = list(spans)
    result: list[Span] = []
    i = 0
    while i < len(pending):
        span = pending[i]
        following = pending[i + 1] if i + 1 < len(pending) else None
        if (span.role == KEY and result
                and result[-1].role == PLAIN
                and result[-1].text.endswith('[')
                and following is not None
                and following.role == PLAIN
                and following.text.startswith(']')):
            previous = result.pop()
            prefix = previous.text[:-1]
            if prefix:
                result.append(Span(prefix, PLAIN))
            result.append(span)
            suffix = following.text[1:]
            if suffix:
                result.append(Span(suffix, PLAIN))
            i += 2
            continue
        result.append(span)
        i += 1
    return result


def _re_match_word(word: str) -> bool:
    return bool(re.match(r'^[\w-]+$', word))


def _re_match_key(s: str) -> str | None:
    match = re.match(r'([A-Z]{2,}|[A-Z]):', s)
    return match.group(1) if match else None


def _re_match_pattern(s: str) -> str | None:
    match = re.match(r'/(\S+)', s)
    return match.group(0) if match else None


def parse_fancy_header(line: str) -> list[Span]:
    """Scan *line* with the header markup grammar and return its spans.

    A leading `^[\\w-]+$` word becomes `LABEL`; `[x]` becomes a one-character
    `KEY`; `CAPS:` at a word start becomes `KEY` (case-sensitive); `/text` at a
    word start becomes `SEARCH` to the next whitespace; the rest is `PLAIN`.
    """
    result: list[Span] = []
    i = 0
    current_text = ''

    def flush() -> None:
        nonlocal current_text
        if current_text:
            result.append(Span(current_text, PLAIN))
            current_text = ''

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
