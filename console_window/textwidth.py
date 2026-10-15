from __future__ import annotations

import unicodedata

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

# Categories that occupy no display cell: non-spacing/ enclosing marks, format
# characters (ZWJ, variation selectors, BOM, …) and control characters.
_ZERO_WIDTH_CATEGORIES = frozenset({'Mn', 'Me', 'Cf', 'Cc'})


def char_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES:
        return 0
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1


def string_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def truncate(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ''
    total = 0
    for i, ch in enumerate(text):
        w = char_width(ch)
        if total + w > max_width:
            return text[:i]
        total += w
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
    total = 0
    for i, ch in enumerate(text):
        w = char_width(ch)
        if total + w > col:
            return i
        total += w
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
