"""Display-width measurement for terminal text."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

__all__ = [
    'cell_to_index',
    'char_width',
    'index_at_cell',
    'ljust',
    'rjust',
    'string_width',
    'truncate',
    'wrap',
    'wrap_position',
    'wrap_ranges',
]

# Categories that occupy no display cell: marks, format characters, controls.
_ZERO_WIDTH_CATEGORIES = frozenset({'Mn', 'Me', 'Cf', 'Cc'})

# VS16 asks for emoji presentation, which terminals draw two cells wide even
# when the base is East-Asian Narrow/Ambiguous.  VS15 needs no adjustment.
_VS16 = '\ufe0f'
_VS15 = '\ufe0e'

# Non-printable-ASCII characters need per-character measurement; ASCII runs
# can be counted in C.
_SPECIAL_CHAR = re.compile(r'[^\x20-\x7e]')


def _is_plain_ascii(text: str) -> bool:
    # Printable ASCII is one cell per code point, so the unicodedata scan is skipped.
    return text.isascii() and text.isprintable()


@lru_cache(maxsize=4096)
def _non_ascii_char_width(ch: str) -> int:
    # A terminal UI reuses a small alphabet, so caching pays off quickly.
    if unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES:
        return 0
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1


def _string_char_width(text: str, index: int) -> int:
    """Width of `text[index]`, folding a VS16 into a narrow base.

    `char_width()` stays per code point so cursor helpers cannot land between a
    base and its selector.
    """
    ch = text[index]
    if ch != _VS16 or index == 0:
        return char_width(ch)
    base = text[index - 1]
    if base.isascii() or char_width(base) != 1:
        return 0
    return 1


def char_width(ch: str) -> int:
    if not ch:
        return 0
    if ' ' <= ch <= '~':
        return 1
    return _non_ascii_char_width(ch)


def string_width(text: str) -> int:
    if _is_plain_ascii(text):
        return len(text)
    # Count ASCII as one, then adjust only the glyphs that differ.
    width = len(text)
    for match in _SPECIAL_CHAR.finditer(text):
        width += _string_char_width(text, match.start()) - 1
    return width


# A redraw re-measures the same rows, and lists routinely exceed a few thousand
# rows; the ASCII-run scan below handles anything beyond the cache.
@lru_cache(maxsize=32768)
def truncate(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ''
    if _is_plain_ascii(text):
        return text if len(text) <= max_width else text[:max_width]
    total = 0
    ascii_start = 0
    for match in _SPECIAL_CHAR.finditer(text):
        run = match.start() - ascii_start
        if total + run > max_width:
            return text[:ascii_start + max_width - total]
        total += run
        w = _string_char_width(text, match.start())
        if total + w > max_width:
            return text[:match.start()]
        total += w
        ascii_start = match.end()
    run = len(text) - ascii_start
    if total + run > max_width:
        return text[:ascii_start + max_width - total]
    return text


def ljust(text: str, width: int) -> str:
    clipped = truncate(text, width)
    return clipped + ' ' * max(0, width - string_width(clipped))


def rjust(text: str, width: int) -> str:
    clipped = truncate(text, width)
    return ' ' * max(0, width - string_width(clipped)) + clipped


def cell_to_index(text: str, col: int) -> int:
    if col <= 0:
        return 0
    if _is_plain_ascii(text):
        return min(col, len(text))
    total = 0
    ascii_start = 0
    for match in _SPECIAL_CHAR.finditer(text):
        run = match.start() - ascii_start
        if total + run > col:
            return ascii_start + col - total
        total += run
        w = _string_char_width(text, match.start())
        if total + w > col:
            return match.start()
        total += w
        ascii_start = match.end()
    run = len(text) - ascii_start
    if total + run > col:
        return ascii_start + col - total
    return len(text)


def wrap_ranges(text: str, width: int) -> list[tuple[int, int]]:
    if width <= 0:
        return [(0, len(text))]
    ranges: list[tuple[int, int]] = []
    start = 0
    cell = 0
    i = 0
    n = len(text)
    while i < n:
        w = char_width(text[i])
        if cell + w > width and cell > 0:
            ranges.append((start, i))
            start = i
            cell = 0
            continue
        cell += w
        i += 1
        if cell > width:  # a single character owns an over-wide line
            ranges.append((start, i))
            start = i
            cell = 0
    if start < n or not ranges:
        ranges.append((start, n))
    return ranges


def wrap_position(text: str, index: int, width: int) -> tuple[int, int]:
    if width <= 0:
        return (0, 0)
    index = max(0, min(index, len(text)))
    line = 0
    cell = 0
    for i in range(index):
        w = char_width(text[i])
        if cell + w > width and cell > 0:
            line += 1
            cell = 0
        cell += w
        if cell > width:
            line += 1
            cell = 0
    # A cursor sitting exactly at a full line's end belongs to the next line.
    if index < len(text) and cell > 0 and cell + char_width(text[index]) > width:
        line += 1
        cell = 0
    return (line, cell)


def index_at_cell(text: str, ranges: list[tuple[int, int]], line_no: int,
                  cell: int) -> int | None:
    if line_no < 0 or line_no >= len(ranges):
        return None
    start, end = ranges[line_no]
    i = start
    acc = 0
    while i < end:
        w = char_width(text[i])
        if acc + w > cell:
            break
        acc += w
        i += 1
    return i


def _hard_break(word: str, width: int) -> list[str]:
    pieces: list[str] = []
    current = ''
    current_w = 0
    for ch in word:
        w = char_width(ch)
        if current and current_w + w > width:
            pieces.append(current)
            current = ''
            current_w = 0
        current += ch
        current_w += w
    if current:
        pieces.append(current)
    return pieces


def wrap(text: str, width: int) -> list[str]:
    if width <= 0:
        return [text]
    lines: list[str] = []
    current = ''
    for word in text.split():
        for piece in _hard_break(word, width):
            if not current:
                current = piece
            elif string_width(current) + 1 + string_width(piece) <= width:
                current += ' ' + piece
            else:
                lines.append(current)
                current = piece
    if current or not lines:
        lines.append(current)
    return lines
