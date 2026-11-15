"""The two font families the blessed symbols are promised from, and the checks.

The terminal decides which face paints a code point, so nothing here can promise
that a cell was drawn.  What it can answer is the question a user's font install
fixes: does the family that should carry this character actually have it?

Three rules keep the check cheap and quiet:

* the blessed tables are covered by a test, not by a runtime check;
* an application registration is checked once, at registration time, and only
  when the family is installed -- a machine without DejaVu Sans Mono or Noto
  Color Emoji is not a bug, so the answer is "unknown" and nothing is recorded;
* fontconfig is the only source of truth, so a missing ``fc-list`` degrades to
  "unknown" instead of an exception.

The one-cell catalog and the two-cell marks share this module because they share
the shape of the question: ``kind`` picks the expected family, nothing else
differs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

#: The family the one-cell catalog is promised from.  Every blessed glyph is in
#: it at the font's single advance width (see the test suite).
TEXT_FONT = 'DejaVu Sans Mono'

#: The family the two-cell marks are promised from.  Emoji 12 or later draws all
#: of them; older versions box the newest three (see docs/Emoji-support.md).
EMOJI_FONT = 'Noto Color Emoji'

#: Seconds to wait for fontconfig.  A local query is fast; a hung one must not
#: hold up a window's construction.
_FC_TIMEOUT = 5.0

#: family -> code-point ranges, or None when fontconfig could not be asked.
#: An installed family with no matching face is an empty list, which is a fact
#: ("not installed"), not a failure.
_charsets: dict[str, list[tuple[int, int]] | None] = {}

_missing: list[Missing] = []


@dataclass(frozen=True)
class Missing:
    """One registered symbol the family that should carry it does not have."""

    kind: str    # 'glyph' (one cell) or 'mark' (two cells)
    name: str
    text: str
    family: str


def _parse_charset(text: str) -> list[tuple[int, int]]:
    """Parse fontconfig's charset format (``20-7e a0-377 ...``) into ranges."""
    ranges: list[tuple[int, int]] = []
    for token in text.split():
        first, _, last = token.partition('-')
        low = int(first, 16)
        ranges.append((low, int(last, 16) if last else low))
    return ranges


def _run_fc_list(family: str) -> str | None:
    """Ask fontconfig for the charsets of every face in *family*."""
    try:
        result = subprocess.run(
            ['fc-list', f':family={family}', '--format=%{charset}\n'],
            capture_output=True, text=True, timeout=_FC_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def charset(family: str) -> list[tuple[int, int]] | None:
    """The code-point ranges the installed faces of *family* cover.

    ``None`` means "cannot tell": fontconfig is missing or answered with an
    error.  An empty list means "fontconfig works and this family is not
    installed", which is a different answer and is never reported as a fault.
    """
    if family in _charsets:
        return _charsets[family]
    output = _run_fc_list(family)
    ranges = None if output is None else _parse_charset(output)
    _charsets[family] = ranges
    return ranges


def installed(family: str) -> bool | None:
    """True if the family is installed, False if not, None if unknown."""
    ranges = charset(family)
    return None if ranges is None else bool(ranges)


def has_char(family: str, char: str) -> bool | None:
    """Does an installed face of *family* cover the single character *char*?

    A multi-code-point string is not testable as a unit and answers "unknown";
    every blessed glyph and mark is one code point.
    """
    if len(char) != 1:
        return None
    ranges = charset(family)
    if not ranges:
        return None
    point = ord(char)
    return any(low <= point <= high for low, high in ranges)


def check_registration(kind: str, name: str, text: str) -> bool | None:
    """Record a registered symbol the expected font family cannot draw.

    *kind* is ``'glyph'`` (one cell, expected from :data:`TEXT_FONT`) or
    ``'mark'`` (two cells, expected from :data:`EMOJI_FONT`).  The answer is
    True when the family has the character, False when the family is installed
    but does not, and None when the question could not be asked (no
    ``fc-list``, or the family is not installed).  Only False is recorded.
    """
    family = EMOJI_FONT if kind == 'mark' else TEXT_FONT
    answer = has_char(family, text)
    if answer is False and not any(
            entry.kind == kind and entry.name == name for entry in _missing):
        _missing.append(Missing(kind, name, text, family))
    return answer


def registered_missing() -> tuple[Missing, ...]:
    """Every registration the expected font family cannot draw, in order."""
    return tuple(_missing)


def reset() -> None:
    """Forget cached font answers and recorded registrations (test hook)."""
    _charsets.clear()
    _missing.clear()
