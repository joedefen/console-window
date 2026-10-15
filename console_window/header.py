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
    text: str
    role: str = PLAIN


class HeaderLine:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    def _add(self, text: str, role: str) -> HeaderLine:
        if text:
            self.spans.append(Span(text, role))
        return self

    def text(self, s: str) -> HeaderLine:
        return self._add(s, PLAIN)

    def key(self, k: str, display: str | None = None) -> HeaderLine:
        return self._add(display if display is not None else k, KEY)

    def bracket_key(self, k: str) -> HeaderLine:
        self._add('[', PLAIN)
        self._add(k, KEY)
        return self._add(']', PLAIN)

    def label(self, s: str) -> HeaderLine:
        return self._add(s, LABEL)

    def search(self, pattern: str, prefix: str = '/') -> HeaderLine:
        return self._add(prefix + pattern, SEARCH)

    def extend(self, other: HeaderLine) -> HeaderLine:
        self.spans.extend(other.spans)
        return self

    def __iter__(self) -> Iterator[Span]:
        return iter(self.spans)

    def __len__(self) -> int:
        return len(self.spans)

    def __bool__(self) -> bool:
        return bool(self.spans)

    def __str__(self) -> str:
        return ''.join(span.text for span in self.spans)


def _re_match_word(word: str) -> bool:
    return bool(re.match(r'^[\w-]+$', word))


def _re_match_key(s: str) -> str | None:
    match = re.match(r'([A-Z]{2,}|[A-Z]):', s)
    return match.group(1) if match else None


def _re_match_pattern(s: str) -> str | None:
    match = re.match(r'/(\S+)', s)
    return match.group(0) if match else None


def parse_fancy_header(line: str) -> list[Span]:
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
