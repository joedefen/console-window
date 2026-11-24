"""Font families the blessed symbols are promised from, and the checks.

The terminal decides which face paints a code point, so this module answers
the question a font install fixes: does the expected family have the character?
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

TEXT_FONT = 'DejaVu Sans Mono'
EMOJI_FONT = 'Noto Color Emoji'

_FC_TIMEOUT = 5.0

# family -> code-point ranges, or None when fontconfig could not be asked.
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
    """Parse fontconfig's charset format (`20-7e a0-377 ...`) into ranges."""
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

    `None` means fontconfig is missing or failed; an empty list means it works
    and the family is not installed.
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

    *kind* is `'glyph'` (one cell, from `TEXT_FONT`) or `'mark'` (two cells,
    from `EMOJI_FONT`).  True means covered, False means the family is
    installed without it, None means the question could not be asked.  Only
    False is recorded.
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
