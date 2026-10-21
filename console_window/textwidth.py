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

# Categories that occupy no display cell: non-spacing/ enclosing marks, format
# characters (ZWJ, variation selectors, BOM, …) and control characters.
_ZERO_WIDTH_CATEGORIES = frozenset({'Mn', 'Me', 'Cf', 'Cc'})

# Any character that is not printable ASCII needs per-character measurement.
# Everything else is exactly one cell wide, so measurement can skip whole
# ASCII runs in C and only visit the glyphs that actually differ.
_SPECIAL_CHAR = re.compile(r'[^\x20-\x7e]')


def _is_plain_ascii(text: str) -> bool:
    # Fast path for the overwhelmingly common terminal case.  Printable ASCII
    # occupies exactly one cell per code point, so the per-character
    # unicodedata scan in char_width() can be skipped entirely.  Control
    # characters are excluded because this module treats them as zero-width.
    # The checks themselves are C-level string scans, and keep add_body() on
    # the same cost profile as the pre-2.0 plain slicing it replaced.
    return text.isascii() and text.isprintable()


@lru_cache(maxsize=4096)
def _non_ascii_char_width(ch: str) -> int:
    # Only reached for non-printable-ASCII characters.  A terminal UI reuses a
    # small alphabet (box drawing, check marks, CJK, emoji), so caching turns
    # the three unicodedata lookups into one dict hit after the first sighting.
    if unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES:
        return 0
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1


def char_width(ch: str) -> int:
    if not ch:
        return 0
    # Printable ASCII is one cell.  This branch is what keeps mixed text (the
    # common case: ASCII rows with a ✔/─/◆ glyph) from paying unicodedata
    # costs for every ordinary character.
    if ' ' <= ch <= '~':
        return 1
    return _non_ascii_char_width(ch)


def string_width(text: str) -> int:
    if _is_plain_ascii(text):
        return len(text)
    # Count printable ASCII as one cell, then adjust only the glyphs that
    # differ (wide, combining, ZWJ, control).  This keeps mixed rows cheap
    # without needing a whole-string cache large enough for every body row.
    width = len(text)
    for match in _SPECIAL_CHAR.finditer(text):
        width += char_width(match.group()) - 1
    return width


# A redraw usually re-measures the same rows.  The cache must hold a whole
# frame, not just a terminal's worth: large package/app lists routinely exceed
# a few thousand rows, and a too-small cache evicts every entry before the next
# frame and then pays both the scan and the eviction cost.  The ASCII-run scan
# below still handles lists larger than this cap efficiently.
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
        w = char_width(match.group())
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
        w = char_width(match.group())
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
