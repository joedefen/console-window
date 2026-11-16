from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Iterator, NamedTuple

# Span roles.  The renderer (:meth:`ConsoleWindow._resolve_header_attr`) maps a
# role + format mode to a curses attribute; keeping roles abstract here keeps
# this module curses-free and the mapping in exactly one place.
PLAIN = 'plain'
KEY = 'key'
LABEL = 'label'
SEARCH = 'search'


class Span(NamedTuple):
    """One run of header text plus the role used to style it.

    Args:
        text: Literal text of the run.
        role: One of the module-level role constants (``PLAIN``, ``KEY``,
            ``LABEL``, ``SEARCH``); mapped to an attribute at draw time.
    """

    text: str
    role: str = PLAIN


class HeaderLine:
    """Builder for the explicit, unparsed header form.

    Each method appends one :class:`Span` and returns ``self``, so calls
    chain.  Declare roles with the method, not with punctuation: ``key('x')``
    styles ``x`` as a key however it is spelled, while ``text('[x]')`` stays
    literal.  Empty strings add nothing.

    Emit the line with ``Screen.add_header_line()`` to render it verbatim
    (brackets included), or with ``Screen.add_fancy_header()`` to keep the
    declared roles but treat ``bracket_key()``'s delimiters as markup.  The
    header *mode* (``'Underline'``, ``'Reverse'`` or ``'Off'``) decides how
    the roles are emphasized; see ``Screen.add_fancy_header()``.
    """

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def _add(self, text: str, role: str) -> HeaderLine:
        if text:
            self.spans.append(Span(text, role))
        return self

    def text(self, s: str) -> HeaderLine:
        """Append *s* as literal ``PLAIN`` text."""
        return self._add(s, PLAIN)

    def key(self, k: str, display: str | None = None) -> HeaderLine:
        """Append a ``KEY`` span.

        Args:
            k: Key name; also the text drawn when *display* is omitted.
            display: Text to draw instead of *k*.
        """
        return self._add(display if display is not None else k, KEY)

    def bracket_key(self, k: str) -> HeaderLine:
        """Append ``'['``, *k* as ``KEY``, and ``']'`` as literal spans.

        ``add_header_line()`` keeps the brackets; ``add_fancy_header()``
        treats them as markup and removes them.
        """
        self._add('[', PLAIN)
        self._add(k, KEY)
        return self._add(']', PLAIN)

    def label(self, s: str) -> HeaderLine:
        """Append a ``LABEL`` span (the header's title)."""
        return self._add(s, LABEL)

    def search(self, pattern: str, prefix: str = '/') -> HeaderLine:
        """Append ``prefix + pattern`` as one ``SEARCH`` span.

        Args:
            pattern: The search text.
            prefix: Marker placed before *pattern*, usually ``'/'``.
        """
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
    """Remove literal ``[``/``]`` delimiters around explicit ``KEY`` spans.

    :meth:`HeaderLine.bracket_key` emits ``'[', Span(key, KEY), ']'`` so that
    the explicit-token API can show the brackets verbatim.  The fancy header
    path treats those delimiters as markup instead, matching the markup form's
    ``[x]`` rule while preserving the caller's declared span roles.
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

    The grammar is deliberately small:

    * the first word, if it matches ``^[\\w-]+$``, becomes ``LABEL`` (bold)
      whatever its case -- a historical quirk;
    * ``[x]`` anywhere in the text becomes a one-character ``KEY`` span with
      the brackets removed;
    * a run of ASCII capitals followed by ``:``, at the start of the line or
      after a space, becomes ``KEY`` (case-sensitive, so ``q:`` does not
      match);
    * ``/text`` at the start of the line or after a space becomes ``SEARCH``
      up to the next whitespace;
    * everything else is ``PLAIN`` text.

    This is pure lexing: no attributes and no mode.  ``mode='Off'`` skips
    this function entirely, which is how the markup string form keeps its
    literal brackets.
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
