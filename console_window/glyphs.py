"""Decorative glyphs in one registry, in two width families.

Every symbol a TUI uses for *meaning* rather than words needs two spellings:
the one the design is built around, and one that a terminal which cannot draw it
(or a font that lacks it) can still show.  A symbol that fails to draw does not
fail loudly -- the terminal paints a box, or nothing -- and the row silently
loses its meaning.  Keeping the symbols in one table matters because the failure
is invisible.

:data:`BUILTIN_GLYPHS` is that table: about eighty one-cell symbols plus the
two-cell emoji family, each with its ASCII spelling and its catalog family.
:data:`GLYPH_GROUPS` fixes the family names, so a group is always one of a known
set.  :func:`catalog_items` and :func:`catalog_rows` are how a screen lists the
one-cell characters; :func:`font_check_rows` is the fixed-block form the help
page uses.  :func:`catalog_entries` keeps each name and its family, which is what
a grouped table wants, :func:`group_of` answers the same question for one name,
and :func:`glyphs_in_group` lists one family.

The two families differ in what they promise
--------------------------------------------
One-cell glyphs are text symbols from the default monospace font, one cell wide
in Unicode, with a plain-ASCII spelling that may be wider (``->``, ``[x]``).
The ``'emoji'`` group is the two-cell family: every entry is a single code point
whose East-Asian Width is ``W``, so it measures two cells in this library and in
the terminal, appending a variation selector cannot change that, and the ASCII
spelling is two cells as well.  Pick a family by the cell budget and the
emphasis the row needs, not by an abstract preference for text over emoji.

What can and cannot be checked
------------------------------
Whether a terminal can *encode* UTF-8 is observable: the output stream's
encoding and ``TERM`` say so.  Whether the *font* has a glyph for a code point
is not observable from inside the process.  So detection is split three ways:

* :func:`terminal_report` reports what is detectable and sets
  ``ascii_required`` only when UTF-8 output is impossible;
* the built-in Fonts section of every help page draws the real one-cell symbols
  and emoji, so the user can look at them and judge;
* :func:`set_ascii` switches to the fallback for everything else, including a
  font the check cannot see.  It is a compatibility mode, not the preferred
  look: when a chosen symbol cannot be drawn, the best answer is the spelling
  that keeps the intended width and presentation -- a two-cell text fallback
  for an emoji, or a one-cell symbol where the layout can spare only one cell.

Degrading for free
------------------
Registering a glyph feeds two consumers: :func:`get` (named lookup) and
:func:`transliterate` (a longest-match substitution applied to whatever text
the app passes to the window).  An app that upgrades this library and changes
nothing gets every *known* decorative code point downgraded as the window
draws; an app that registers its own vocabulary gets its own fallbacks.

Substitution only ever rewrites code points that are in the table: a pager
showing ``GRUB_CMDLINE_LINUX="Grüße"`` is byte-identical in both modes, because
``ü`` is not registered.  Set ``CONSOLE_WINDOW_GLYPH_AUDIT=1`` to log each unseen
decorative code point together with the :func:`register` call that would teach
the library about it.
"""

from __future__ import annotations

import locale
import logging
import os
import re
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from . import fonts
from .textwidth import string_width

logger = logging.getLogger(__name__)

__all__ = [
    'AUDIT_ENV',
    'BUILTIN_GLYPHS',
    'BUILTIN_PROBE',
    'DEPRECATED_GLYPHS',
    'EMOJI_GROUP',
    'GLYPHS_ENV',
    'GLYPH_GROUPS',
    'CatalogEntry',
    'Glyph',
    'Glyphs',
    'Issue',
    'TerminalReport',
    'apply_policy',
    'catalog_entries',
    'catalog_items',
    'catalog_rows',
    'ensure_policy',
    'find_issues',
    'font_check_rows',
    'font_missing',
    'get',
    'glyphs_in_group',
    'group_of',
    'is_ascii',
    'lookup',
    'probe',
    'probe_text',
    'register',
    'register_many',
    'reset',
    'set_ascii',
    'terminal_report',
    'transliterate',
    'unicode_of',
]

#: Environment variable that pins the glyph mode for apps without argparse
#: (``auto``, ``ascii`` or ``unicode``).  Also the escape hatch for an app whose
#: terminal was detected wrongly.
GLYPHS_ENV = 'CONSOLE_WINDOW_GLYPHS'

#: Environment variable that turns on the decoration audit.  In both glyph
#: modes, VS16-promoted, joiner-sequenced, East-Asian Ambiguous and unapproved
#: emoji get a verdict and a suggestion in the log, once per code point; symbols
#: registered nowhere keep the older "has no ASCII fallback" message.
AUDIT_ENV = 'CONSOLE_WINDOW_GLYPH_AUDIT'

#: Terminal types that cannot draw the Unicode set at all.
ASCII_TERMS = frozenset({'dumb'})

#: Terminals that encode UTF-8 but whose default font usually lacks the
#: emoji-style glyphs; the Linux console is the common case.
LIMITED_TERMS = frozenset({'linux', 'cons25'})

#: Unicode categories that are decoration rather than content.  Used only by
#: the audit, to keep prose ("Grüße") out of the report.
_DECORATIVE_CATEGORIES = frozenset({'So', 'Sk', 'Sm'})

_MODE_VALUES = ('auto', 'ascii', 'unicode')

_VARIATION_SELECTORS = ('\ufe0f', '\ufe0e')


#: The fixed catalog families, in catalog order.  A glyph's ``group`` is always
#: one of these; there is no application-defined family.  A new registration
#: joins ``'application'``, and ``'emoji'`` is the two-cell family.
GLYPH_GROUPS: tuple[str, ...] = (
    'ui', 'frames', 'arrows', 'triangles', 'shapes', 'blocks', 'status',
    'math', 'currency', 'typography', 'emoji', 'application',
)

#: The group whose members are two-cell emoji rather than one-cell text symbols.
EMOJI_GROUP = 'emoji'


def _validate_emoji(unicode_text: str, ascii_text: str) -> None:
    """Raise unless an ``'emoji'`` glyph keeps two cells in both spellings."""
    if len(unicode_text) != 1:
        raise ValueError(
            f'emoji glyph {unicode_text!r}: the visual must be one code point')
    if unicode_text in _VARIATION_SELECTORS or unicode_text == '\u200d':
        raise ValueError(
            f'emoji glyph {unicode_text!r}: a variation selector or joiner is '
            'not a mark; use the base code point')
    eaw = unicodedata.east_asian_width(unicode_text)
    if eaw != 'W':
        raise ValueError(
            f'emoji glyph {unicode_text!r}: East-Asian {eaw}, not W; its cell '
            'count is terminal-dependent')
    width = string_width(unicode_text)
    if width != 2:
        raise ValueError(
            f'emoji glyph {unicode_text!r} measures {width} cells, not 2')
    promoted = string_width(unicode_text + _VARIATION_SELECTORS[0])
    if promoted != width:
        raise ValueError(
            f'emoji glyph {unicode_text!r}: a variation selector changes it '
            f'from {width} to {promoted} cells')
    ascii_width = string_width(ascii_text)
    if ascii_width != width:
        raise ValueError(
            f'emoji glyph {unicode_text!r}: the fallback {ascii_text!r} '
            f'measures {ascii_width} cells, not {width}; it would shift the '
            'column it replaces')


@dataclass(frozen=True)
class Glyph:
    """One decorative symbol in both spellings, with its catalog family.

    ``unicode`` is the visual spelling the design is built around.  ``ascii``
    may be empty: that spells "delete the decoration", which is the right answer
    for a marker whose meaning is already carried by its column.

    ``group`` is one of :data:`GLYPH_GROUPS`; a new registration joins
    ``'application'``.  A glyph in the :data:`EMOJI_GROUP` family is a *wide*
    mark and must keep its two-cell width in both spellings, which the
    constructor enforces so a column cannot shift when the mode changes.
    """

    unicode: str
    ascii: str
    group: str = 'application'

    def __post_init__(self) -> None:
        if not isinstance(self.unicode, str) or not self.unicode:
            raise TypeError(f'Glyph.unicode must be a non-empty str, got {self.unicode!r}')
        if not isinstance(self.ascii, str):
            raise TypeError(f'Glyph.ascii must be a str, got {self.ascii!r}')
        if not self.ascii.isascii():
            raise ValueError(
                f'Glyph.ascii must be plain ASCII (that is the point), got {self.ascii!r}'
            )
        if not isinstance(self.group, str) or not self.group:
            raise TypeError(f'Glyph.group must be a non-empty str, got {self.group!r}')
        if self.group not in GLYPH_GROUPS:
            raise ValueError(
                f'Glyph.group must be one of {", ".join(GLYPH_GROUPS)}, '
                f'got {self.group!r}'
            )
        if self.group == EMOJI_GROUP:
            _validate_emoji(self.unicode, self.ascii)


#: Glyphs this library draws itself, and the catalog an application draws from.
#:
#: Each row is the visual, its plain-ASCII spelling, and the family it belongs
#: to.  The codepoint comment is the searchable name of the character; the glyph
#: itself is written literally so the table reads as the UI it describes.  The
#: one-cell families promise a single cell in Unicode; their fallback may be
#: wider (``->``, ``[x]``).  The ``'emoji'`` rows are the two-cell family and
#: keep two cells in both spellings.  A code point has exactly one fallback even
#: when two names draw it (``cursor_block`` and ``swatch`` are the same block);
#: an application that registers a code point itself takes it over (see
#: :func:`_compile_tables`).
BUILTIN_GLYPHS: dict[str, Glyph] = {
    # --- ui: the library's own marks ----------------------------------------
    'cursor': Glyph('│', '|', group='ui'),          # U+2502 narrow text cursor
    'cursor_block': Glyph('█', '#', group='ui'),    # U+2588 block cursor
    # One cell in both spellings: the choice list indents the other rows by one
    # cell plus a space, so a two-character marker would knock the column out
    # of alignment exactly where the terminal is already struggling.
    # U+27A4, not the equilateral U+2B9E this used to be: DejaVu Sans Mono has
    # no glyph for U+2B9E, so the marker came from a fallback font that can be
    # wider than one cell.  Both spellings stay one cell wide.
    'choice': Glyph('➤', '>', group='ui'),          # U+27A4 resolved choice
    'scroll_prev': Glyph('◀', '<', group='ui'),     # U+25C0 scroll left
    'scroll_next': Glyph('▶', '>', group='ui'),     # U+25B6 scroll right
    'alert_up': Glyph('▲', '^', group='ui'),        # U+25B2 "more above"
    'alert_down': Glyph('▼', 'v', group='ui'),      # U+25BC "more below"
    # The heavy (black) arrows: the light `←`/`→` look anaemic beside the solid
    # triangles the same UI uses, and these are in the same font.
    'nav_prev': Glyph('⬅', '<-', group='ui'),       # U+2B05 help legend, left
    'nav_next': Glyph('➡', '->', group='ui'),       # U+27A1 help legend, right
    'bullet': Glyph('·', '.', group='ui'),          # U+00B7 help-list bullet
    'swatch': Glyph('█', '#', group='ui'),          # U+2588 theme color swatch

    # --- frames -------------------------------------------------------------
    # The message-box frame.  `curses.textpad.rectangle()` already draws with
    # ACS line art, but a message box painted by hand needs its own fallback;
    # registering the corners keeps the ASCII mode invariant ("every painted
    # cell is ASCII") true for dialogs too.
    'box_tl': Glyph('┌', '+', group='frames'),      # U+250C
    'box_h': Glyph('─', '-', group='frames'),       # U+2500
    'box_tr': Glyph('┐', '+', group='frames'),      # U+2510
    'box_v': Glyph('│', '|', group='frames'),       # U+2502 also a cursor
    'box_bl': Glyph('└', '+', group='frames'),      # U+2514
    'box_br': Glyph('┘', '+', group='frames'),      # U+2518
    'frame_rounded_tl': Glyph('╭', '+', group='frames'),  # U+256D
    'frame_rounded_tr': Glyph('╮', '+', group='frames'),  # U+256E
    'frame_rounded_bl': Glyph('╰', '+', group='frames'),  # U+2570
    'frame_rounded_br': Glyph('╯', '+', group='frames'),  # U+256F
    'frame_h_double': Glyph('═', '=', group='frames'),    # U+2550
    'frame_v_double': Glyph('║', '|', group='frames'),    # U+2551

    # --- arrows -------------------------------------------------------------
    'arrow_up': Glyph('⬆', '^', group='arrows'),            # U+2B06
    'arrow_down': Glyph('⬇', 'v', group='arrows'),          # U+2B07
    'arrow_double_left': Glyph('⇐', '<=', group='arrows'),  # U+21D0
    'arrow_double_right': Glyph('⇒', '=>', group='arrows'),  # U+21D2
    'arrow_double_up': Glyph('⇑', '^^', group='arrows'),    # U+21D1
    'arrow_double_down': Glyph('⇓', 'vv', group='arrows'),  # U+21D3

    # --- triangles: hollow and small, in both horizontal directions ---------
    'tri_right_hollow': Glyph('▷', '>', group='triangles'),  # U+25B7
    'tri_left_hollow': Glyph('◁', '<', group='triangles'),   # U+25C1
    'tri_up_hollow': Glyph('△', '^', group='triangles'),     # U+25B3
    'tri_down_hollow': Glyph('▽', 'v', group='triangles'),   # U+25BD
    'tri_right_small': Glyph('▸', '>', group='triangles'),   # U+25B8
    'tri_left_small': Glyph('◂', '<', group='triangles'),    # U+25C2

    # --- shapes: filled and hollow pairs ------------------------------------
    'circle_filled': Glyph('●', '@', group='shapes'),        # U+25CF
    'circle_hollow': Glyph('◯', 'o', group='shapes'),        # U+25EF heavier
    'diamond_filled': Glyph('◆', '#', group='shapes'),       # U+25C6
    'diamond_hollow': Glyph('◇', '<>', group='shapes'),      # U+25C7
    'square_filled': Glyph('◼', '#', group='shapes'),        # U+25FC
    'square_hollow': Glyph('◻', '[]', group='shapes'),       # U+25FB
    'star_filled': Glyph('★', '*', group='shapes'),          # U+2605
    'star_hollow': Glyph('☆', '+', group='shapes'),          # U+2606
    'asterisk_heavy': Glyph('✱', '*', group='shapes'),       # U+2731
    'asterisk_eight_spoked': Glyph('✳', '*', group='shapes'),  # U+2733

    # --- blocks and bars: textures, half blocks, sparkline columns ----------
    'block_light': Glyph('░', '.', group='blocks'),          # U+2591
    'block_medium': Glyph('▒', ':', group='blocks'),         # U+2592
    'block_dark': Glyph('▓', '#', group='blocks'),           # U+2593
    'block_upper': Glyph('▀', '"', group='blocks'),          # U+2580
    'block_left': Glyph('▌', '[', group='blocks'),           # U+258C
    'block_right': Glyph('▐', ']', group='blocks'),          # U+2590
    'block_quadrant': Glyph('▚', '%', group='blocks'),       # U+259A
    'bar_1': Glyph('▁', '1', group='blocks'),                # U+2581
    'bar_2': Glyph('▂', '2', group='blocks'),                # U+2582
    'bar_3': Glyph('▃', '3', group='blocks'),                # U+2583
    'bar_4': Glyph('▄', '4', group='blocks'),                # U+2584
    'bar_5': Glyph('▅', '5', group='blocks'),                # U+2585
    'bar_6': Glyph('▆', '6', group='blocks'),                # U+2586
    'bar_7': Glyph('▇', '7', group='blocks'),                # U+2587

    # --- status: one-cell check, cross and ballot symbols -------------------
    'check': Glyph('✓', 'v', group='status'),                # U+2713
    'check_heavy': Glyph('✔', 'v', group='status'),          # U+2714
    'cross': Glyph('✗', 'x', group='status'),                # U+2717
    'cross_heavy': Glyph('✘', 'x', group='status'),          # U+2718
    'ballot_box': Glyph('☐', '[ ]', group='status'),         # U+2610
    'ballot_check': Glyph('☑', '[v]', group='status'),       # U+2611
    'ballot_cross': Glyph('☒', '[x]', group='status'),       # U+2612
    'warn': Glyph('⚠', '!', group='status'),                 # U+26A0
    'sun': Glyph('☀', '*', group='status'),                  # U+2600
    'cloud': Glyph('☁', '~', group='status'),                # U+2601

    # --- math ---------------------------------------------------------------
    'plus_minus': Glyph('±', '+-', group='math'),            # U+00B1
    'times': Glyph('×', 'x', group='math'),  # U+00D7  # noqa: RUF001
    'not_equal': Glyph('≠', '!=', group='math'),             # U+2260
    'less_equal': Glyph('≤', '<=', group='math'),            # U+2264
    'greater_equal': Glyph('≥', '>=', group='math'),         # U+2265
    'approx': Glyph('≈', '~', group='math'),                 # U+2248
    'infinity': Glyph('∞', 'inf', group='math'),             # U+221E

    # --- currency -----------------------------------------------------------
    'euro': Glyph('€', 'E', group='currency'),               # U+20AC
    'pound': Glyph('£', 'L', group='currency'),              # U+00A3
    'yen': Glyph('¥', 'Y', group='currency'),                # U+00A5

    # --- typography ---------------------------------------------------------
    'en_dash': Glyph('–', '-', group='typography'),  # U+2013  # noqa: RUF001
    'em_dash': Glyph('—', '--', group='typography'),         # U+2014
    'ellipsis': Glyph('…', '...', group='typography'),       # U+2026

    # --- emoji: the two-cell family -----------------------------------------
    # Every entry is one EAW=W code point and both spellings are exactly two
    # cells, so a column never moves when the mode changes.  Pick this family
    # when the row needs to be seen; the one-cell families above stay quieter.
    'ok': Glyph('✅', 'v ', group='emoji'),                  # U+2705
    'fail': Glyph('❌', 'x ', group='emoji'),                # U+274C
    'attention': Glyph('❗', '! ', group='emoji'),           # U+2757
    'ask': Glyph('❓', '? ', group='emoji'),                 # U+2753
    'stop': Glyph('🛑', '- ', group='emoji'),                # U+1F6D1
    'ban': Glyph('⛔', '# ', group='emoji'),                 # U+26D4
    'denied': Glyph('🚫', 'X ', group='emoji'),              # U+1F6AB
    'siren': Glyph('🚨', '!!', group='emoji'),               # U+1F6A8
    'boom': Glyph('💥', '* ', group='emoji'),                # U+1F4A5
    'idea': Glyph('💡', 'i ', group='emoji'),                # U+1F4A1
    'build': Glyph('🚧', 'C ', group='emoji'),               # U+1F6A7
    'dot_green': Glyph('🟢', 'G ', group='emoji'),           # U+1F7E2
    'dot_yellow': Glyph('🟡', 'Y ', group='emoji'),          # U+1F7E1
    'dot_red': Glyph('🔴', 'R ', group='emoji'),             # U+1F534
    'dot_blue': Glyph('🔵', 'B ', group='emoji'),            # U+1F535
    'dot_black': Glyph('⚫', 'K ', group='emoji'),           # U+26AB
    'dot_white': Glyph('⚪', 'W ', group='emoji'),           # U+26AA
    'radio': Glyph('🔘', 'r ', group='emoji'),               # U+1F518
    'star': Glyph('⭐', 's ', group='emoji'),                # U+2B50
    'star_glow': Glyph('🌟', 'S ', group='emoji'),           # U+1F31F
    'circle_heavy': Glyph('⭕', '0 ', group='emoji'),        # U+2B55
    'diamond_orange': Glyph('🔶', 'O ', group='emoji'),      # U+1F536
    'diamond_blue': Glyph('🔷', 'D ', group='emoji'),        # U+1F537
    'diamond_dot': Glyph('💠', '. ', group='emoji'),         # U+1F4A0
    'folder': Glyph('📁', '[ ', group='emoji'),              # U+1F4C1
    'file': Glyph('📄', 'f ', group='emoji'),                # U+1F4C4
    'chart': Glyph('📊', '| ', group='emoji'),               # U+1F4CA
    'find': Glyph('🔍', 'o ', group='emoji'),                # U+1F50D
    'lock': Glyph('🔒', 'L ', group='emoji'),                # U+1F512
    'key': Glyph('🔑', 'k ', group='emoji'),                 # U+1F511
    'link': Glyph('🔗', '> ', group='emoji'),                # U+1F517
    'magnet': Glyph('🧲', 'M ', group='emoji'),              # U+1F9F2
    'mail': Glyph('📧', '@ ', group='emoji'),                # U+1F4E7
    'bell': Glyph('🔔', 'n ', group='emoji'),                # U+1F514
    'chat': Glyph('💬', 'm ', group='emoji'),                # U+1F4AC
    'globe': Glyph('🌍', 'g ', group='emoji'),               # U+1F30D
    'net': Glyph('🌐', 'N ', group='emoji'),                 # U+1F310
    'package': Glyph('📦', 'p ', group='emoji'),             # U+1F4E6
    'wait': Glyph('⏳', 'w ', group='emoji'),                # U+23F3
}



#: Glyph names the font check prints, in reading order, when an app registers
#: none of its own.  These are the built-ins a user is most likely to notice.
#: The help page shows the whole catalog, so this line stays short.
BUILTIN_PROBE: tuple[str, ...] = (
    'nav_prev', 'nav_next', 'choice', 'cursor', 'cursor_block', 'bullet',
)

#: Symbols per sample row for the generic catalog packing.  Superseded on the
#: help page by the fixed block layout below, but kept for callers that just
#: want a compact list.
CATALOG_PER_ROW = 27

#: Cells in one block of the help page's font check.  One-cell symbols pack ten
#: to a block; the two-cell emoji pack five, which is why both end up ten cells
#: wide.  Every block ends with a ``|`` so a font that shifts a column is
#: immediately visible.
FONT_CHECK_BLOCK_CELLS = 10

#: Blocks on one font-check row.  Five blocks plus five ``|`` separators make
#: every row exactly :data:`FONT_CHECK_ROW_WIDTH` cells wide.
FONT_CHECK_BLOCKS = 5

#: Width of a complete font-check row.  The help page will not draw the sample
#: rows in a narrower body: a wrapped row would defeat the visual alignment
#: check, so the section falls back to a sentence instead.
FONT_CHECK_ROW_WIDTH = FONT_CHECK_BLOCK_CELLS * FONT_CHECK_BLOCKS + FONT_CHECK_BLOCKS

#: Spellings this library used to draw, mapped to the code point that replaced
#: them.  Text written against an older release is upgraded in *both* modes, so
#: it renders from the same font instead of a fallback.  An application that
#: registers one of these code points itself keeps it (see
#: :func:`_compile_tables`), which is the escape hatch for an app that liked the
#: old shape.
DEPRECATED_GLYPHS: dict[str, str] = {
    '⮞': '➤',   # choice: U+2B9E is not in DejaVu Sans Mono
    '←': '⬅',   # nav_prev
    '→': '➡',   # nav_next
    '↑': '⬆',   # arrow_up
    '↓': '⬇',   # arrow_down
    '○': '◯',   # circle_hollow
    '□': '◻',   # square_hollow
    '■': '◼',   # square_filled
}

_registry: dict[str, Glyph] = {}
_probe: list[str] = []
_ascii_mode = False
#: True once anything (an app option, the CLI helper, or auto-detection) has
#: chosen a mode.  Later auto-detection must not undo that choice, otherwise
#: every new window would re-run the environment probe and silently revert a
#: ``--ascii`` the user asked for.
_decided = False
_table: re.Pattern[str] | None = None
_upgrade_table: re.Pattern[str] | None = None
_compiled = False
_map: dict[str, str] = {}
_upgrade: dict[str, str] = {}
_audited: set[str] = set()


def _invalidate() -> None:
    """Forget the compiled patterns; the registry changed under them."""
    global _compiled  # pylint: disable=global-statement
    _compiled = False


def _reset_state() -> None:
    """Restore the built-in tables and the Unicode mode (used by :func:`reset`)."""
    global _ascii_mode, _decided, _table, _upgrade_table  # pylint: disable=global-statement
    _registry.clear()
    _registry.update(BUILTIN_GLYPHS)
    _probe.clear()
    _probe.extend(BUILTIN_PROBE)
    _ascii_mode = False
    _decided = False
    _table = None
    _upgrade_table = None
    _map.clear()
    _upgrade.clear()
    _audited.clear()
    _invalidate()
    fonts.reset()


def register(
    name: str,
    unicode_text: str,
    ascii_text: str,
    *,
    probe: bool = False,  # pylint: disable=redefined-outer-name
    group: str | None = None,
) -> None:
    """Teach the library one decorative glyph.

    *ascii_text* must be plain ASCII (it may be empty).  ``probe=True`` adds the
    glyph to the font check, where the user sees the real Unicode form.

    *group* is one of :data:`GLYPH_GROUPS`.  ``None`` keeps the family of an
    already-registered name, so overriding a built-in's spelling does not
    silently move it into the application group; a new name with no group joins
    ``'application'``.  ``group='emoji'`` applies the two-cell width contract.
    """
    if not isinstance(name, str) or not name:
        raise TypeError(f'glyph name must be a non-empty str, got {name!r}')
    existing = _registry.get(name)
    resolved_group = group
    if resolved_group is None:
        resolved_group = existing.group if existing is not None else 'application'
    if resolved_group == EMOJI_GROUP:
        for other_name, other in _registry.items():
            if (other_name != name and other.group == EMOJI_GROUP
                    and other.unicode == unicode_text):
                raise ValueError(
                    f'emoji glyph {other_name!r} already draws '
                    f'{unicode_text!r}')
    _registry[name] = Glyph(unicode_text, ascii_text, group=resolved_group)
    if probe:
        _add_probe(name)
    # Advisory only.  The blessed table is covered by a test, and a machine
    # without the reference font is not a bug: console_window.fonts answers
    # None then and records nothing.
    kind = 'mark' if resolved_group == EMOJI_GROUP else 'glyph'
    fonts.check_registration(kind, name, unicode_text)
    _invalidate()


def register_many(
    mapping: Mapping[str, Glyph | tuple[str, str] | list[str]],
    *,
    probe: Iterable[str] = (),  # pylint: disable=redefined-outer-name
    group: str | None = None,
) -> None:
    """Register a whole table at once.

    Values may be :class:`Glyph` instances or two-item ``(unicode, ascii)``
    sequences.  *probe* names the entries the font check should print, in order.
    *group* applies to the pair values and to a ``Glyph`` left at the default
    ``'application'`` family; it must be one of :data:`GLYPH_GROUPS`.  A
    ``Glyph`` with an explicit family keeps it, and overriding a built-in's
    spelling keeps the family it is cataloged under.
    """
    for name, spec in mapping.items():
        if isinstance(spec, Glyph):
            spec_group = group
            if spec_group is None and spec.group != 'application':
                spec_group = spec.group
            register(name, spec.unicode, spec.ascii, group=spec_group)
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            register(name, spec[0], spec[1], group=group)
        else:
            raise TypeError(
                f'glyph {name!r} must be a Glyph or a (unicode, ascii) pair, '
                f'got {spec!r}'
            )
    for name in probe:
        _add_probe(name)


def _add_probe(name: str) -> None:
    if name not in _registry:
        raise KeyError(f'cannot probe unregistered glyph {name!r}')
    if name not in _probe:
        _probe.append(name)


def probe(*names: str) -> None:
    """Add already-registered glyphs to the font check, in the given order."""
    for name in names:
        _add_probe(name)


def reset() -> None:
    """Drop every app registration and return to the Unicode built-ins.

    This is a test hook: the glyph mode is process state, so a suite must be
    able to start each case from a known state.
    """
    _reset_state()


def _active(glyph: Glyph) -> str:
    """The spelling to draw for the current glyph mode."""
    return glyph.ascii if _ascii_mode else glyph.unicode


def _resolve_name(key: str) -> str:
    """Return the registered name for a name or a registered Unicode visual."""
    if not isinstance(key, str):
        raise TypeError(f'glyph key must be a str, got {type(key).__name__}')
    if key in _registry:
        return key
    for name, glyph in _registry.items():
        if glyph.unicode == key:
            return name
    raise KeyError(f'unknown glyph {key!r}')


def get(key: str) -> str:
    """Return glyph *key* in the active set.

    *key* may be a registered name or the glyph's Unicode visual, so an
    application can write ``Glyphs.get('│')`` without looking up the name.  When
    several names draw the same character, the first registered wins.
    """
    return _active(_registry[_resolve_name(key)])


def unicode_of(key: str) -> str:
    """Return glyph *key* in its Unicode form, whatever the active mode is."""
    return _registry[_resolve_name(key)].unicode


def lookup(key: str) -> Glyph:
    """Return the :class:`Glyph` registered as *key* (a name or a visual).

    Unlike :func:`get`, this exposes both spellings and the group, which is what
    a catalog listing or a lookup table needs.
    """
    return _registry[_resolve_name(key)]


def group_of(key: str) -> str:
    """Return the catalog family (``'math'``, ``'ui'``, ...) of *key*."""
    return lookup(key).group


def glyphs_in_group(group: str) -> list[tuple[str, Glyph]]:
    """Every registered glyph in *group*, in registration order.

    Returns ``(name, glyph)`` pairs.  *group* must be one of
    :data:`GLYPH_GROUPS`; an unknown group raises ``ValueError``.
    """
    if group not in GLYPH_GROUPS:
        raise ValueError(
            f'unknown glyph group {group!r}; choose from '
            f'{", ".join(GLYPH_GROUPS)}')
    return [
        (name, glyph)
        for name, glyph in _registry.items()
        if glyph.group == group
    ]


def font_missing() -> tuple[fonts.Missing, ...]:
    """Registrations the reference font family cannot draw, in order.

    Populated only when an application registers a glyph and the expected family
    is installed (see :mod:`console_window.fonts`).  A help page reads it;
    nothing on a draw path queries fonts.
    """
    return fonts.registered_missing()


@dataclass(frozen=True)
class Issue:
    """One piece of decoration whose cell count is not guaranteed."""

    kind: str      # 'vs16', 'zwj', 'ambiguous' or 'unapproved'
    text: str      # the offending code point, or base+selector for a VS16 mark
    offset: int    # index of that text in the string that was examined
    hint: str      # what to use instead


#: Code point ranges a mark can come from.  Outside them a character is content
#: (``Grüße``, ``—``, ``±``) and is never reported, which is what lets an app run
#: :func:`find_issues` over every string it draws.
_MARK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2190, 0x21FF),    # arrows
    (0x2300, 0x23FF),    # hourglass, stopwatch, alarm clock
    (0x25A0, 0x25FF),    # geometric shapes
    (0x2600, 0x27BF),    # miscellaneous symbols and dingbats
    (0x2B00, 0x2BFF),    # stars, squares, arrows
    (0xFE00, 0xFE0F),    # variation selectors
    (0x1F000, 0x1FAFF),  # emoji, flags, skin tones
)


def _in_mark_ranges(ch: str) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in _MARK_RANGES)


#: What to say about a mark that is one cell when it was meant to be two.
_SINGLE_CELL_HINT = (
    'use an emoji glyph for two cells, or a one-cell EAW=N symbol like \u2713'
)


def _sequence_offsets(text: str) -> set[int]:
    """Offsets of the code points a zero-width joiner joins to a neighbour."""
    offsets: set[int] = set()
    for index, ch in enumerate(text):
        if ch != '\u200d':
            continue
        for near in (index - 1, index, index + 1):
            if 0 <= near < len(text):
                offsets.add(near)
    return offsets


def find_issues(text: str) -> list[Issue]:
    """Report decoration in *text* whose width the row was not measured for.

    Four verdicts, one per failure mode:

    * ``vs16`` -- a code point whose width depends on whether the terminal
      honors a variation selector (``⚠`` becomes two cells with ``U+FE0F``);
    * ``zwj`` -- a zero-width joiner, so the sequence's width is anyone's guess;
    * ``ambiguous`` -- East-Asian *Ambiguous*: one cell here, two in a CJK-width
      terminal;
    * ``unapproved`` -- a two-cell emoji with no approved fallback.

    One issue per offending code point: a base that is followed by a selector is
    reported once, at the selector (which carries the base in its text), and the
    code points of a joiner sequence are not also reported individually.
    Approved emoji and ordinary text produce nothing: ``Grüße``, ``—`` and ``±``
    are content, not decoration, and are outside the ranges the check looks at.
    A bare one-cell symbol is not a hazard either -- ``✓`` is rung 3 of the
    ladder, and whether a terminal forces emoji presentation for it cannot be
    observed anyway -- so it is reported only if a selector is attached.
    """
    if not text or text.isascii():
        return []
    approved = {
        glyph.unicode for glyph in _registry.values()
        if glyph.group == EMOJI_GROUP
    }
    joined = _sequence_offsets(text)
    issues: list[Issue] = []
    for offset, ch in enumerate(text):
        if ch in _VARIATION_SELECTORS:
            base = text[offset - 1] if offset else ''
            if base in approved:
                # An emoji glyph is VS16-immune by construction (Glyph checks
                # it), so a stray selector next to one is harmless.
                continue
            issues.append(Issue(
                'vs16', base + ch, offset - 1 if base else offset,
                f'{base}{ch} is VS16-promoted: 1 or 2 cells depending on the '
                f'terminal; {_SINGLE_CELL_HINT}'))
            continue
        if ch == '\u200d':
            issues.append(Issue(
                'zwj', ch, offset,
                'a zero-width joiner makes the width terminal-dependent; use a '
                'single code point'))
            continue
        if offset in joined or not _in_mark_ranges(ch) or ch in approved:
            continue
        following = text[offset + 1] if offset + 1 < len(text) else ''
        if following in _VARIATION_SELECTORS:
            # The selector reports the pair; one verdict per mark.
            continue
        width = string_width(ch)
        eaw = unicodedata.east_asian_width(ch)
        code = f'U+{ord(ch):04X}'
        if eaw == 'A':
            issues.append(Issue(
                'ambiguous', ch, offset,
                f'{ch} ({code}) is East-Asian Ambiguous: {width} cell(s) here, '
                '2 in a CJK-width terminal; use an emoji glyph for two cells, '
                'or a one-cell EAW=N symbol'))
            continue
        if eaw == 'W':
            issues.append(Issue(
                'unapproved', ch, offset,
                f'{ch} ({code}) is a two-cell mark with no approved fallback; '
                "add it with Glyphs.register(..., group='emoji') or use an "
                'approved emoji glyph'))
    return issues


def is_ascii() -> bool:
    """True when the plain-ASCII fallback is in use."""
    return _ascii_mode


def set_ascii(enabled: bool) -> None:
    """Select the plain-ASCII glyph set (True) or the Unicode one (False).

    This is an explicit decision: later auto-detection leaves it alone.
    """
    global _ascii_mode, _decided  # pylint: disable=global-statement
    _ascii_mode = bool(enabled)
    _decided = True


def probe_text() -> str:
    """The real Unicode glyphs a user should look at (never the ASCII set).

    The font check has to print the glyph that might be missing; printing the
    fallback would check nothing.
    """
    shown: list[str] = []
    for name in _probe:
        glyph = _registry.get(name)
        if glyph is None or glyph.unicode in shown:
            continue
        shown.append(glyph.unicode)
    return ' '.join(shown)


@dataclass(frozen=True)
class CatalogEntry:
    """One named glyph exactly as a catalog listing consumes it.

    A listing needs more than the active spelling: the name, both spellings
    side by side, and the family that decides where a group divider belongs.
    ``active`` is the spelling for the process-wide mode at the time it is read,
    so one entry list can be built before the mode is known.
    """

    group: str
    name: str
    unicode: str
    ascii: str

    @property
    def active(self) -> str:
        """The spelling to draw for the current glyph mode."""
        return self.ascii if _ascii_mode else self.unicode


def catalog_entries(unique: bool = False,
                    include_emoji: bool = False) -> list[CatalogEntry]:
    """Every registered glyph with its name and family, in catalog order.

    The built-ins come first, grouped by family, and the application's own
    registrations follow.  Every name is listed by default, so a table with a
    Name column can show ``cursor_block`` and ``swatch`` separately even though
    they draw the same character.  ``unique=True`` keeps only the first name for
    each character, which is the flat sample list :func:`catalog_items` returns.

    The two-cell ``'emoji'`` family is left out unless ``include_emoji=True``:
    the one-cell catalog promises a single cell in the default monospace font,
    and an emoji entry cannot keep that promise.  A page that wants both families
    passes ``include_emoji=True`` and splits on ``group``.
    """
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for name, glyph in _registry.items():
        if glyph.group == EMOJI_GROUP and not include_emoji:
            continue
        if unique:
            if glyph.unicode in seen:
                continue
            seen.add(glyph.unicode)
        entries.append(CatalogEntry(glyph.group, name, glyph.unicode, glyph.ascii))
    return entries


def catalog_items(include_emoji: bool = False) -> list[str]:
    """Every registered glyph, once, in registration order, in the active set.

    This is the list an application consults when it needs a symbol: the
    built-ins come first and the application's own registrations follow.  Two
    names may draw the same character (``cursor_block`` and ``swatch``); the
    character is listed once.  Use :func:`catalog_entries` when the names or
    groups matter.
    """
    return [
        entry.active
        for entry in catalog_entries(unique=True, include_emoji=include_emoji)
    ]


def catalog_rows(width: int, per_row: int = CATALOG_PER_ROW,
                 include_emoji: bool = False) -> list[str]:
    """Pack the catalog into space-separated rows no wider than *width* cells.

    A fallback can be more than one cell (``->``, ``[x]``, ``...``), so rows are
    measured rather than counted: a narrow terminal wraps into more rows instead
    of overflowing or truncating the set.  The rows are display text; the
    caller adds them to a screen.
    """
    rows: list[str] = []
    row: list[str] = []
    used = 0
    for item in catalog_items(include_emoji=include_emoji):
        item_width = string_width(item)
        needed = item_width if not row else item_width + 1
        if row and (len(row) >= per_row or used + needed > width):
            rows.append(' '.join(row))
            row, used, needed = [], 0, item_width
        row.append(item)
        used += needed
    if row:
        rows.append(' '.join(row))
    return rows


def _check_block(parts: list[str]) -> str:
    """Finish one ten-cell block with ``.`` padding and a trailing ``|``."""
    text = ''.join(parts)
    missing = FONT_CHECK_BLOCK_CELLS - string_width(text)
    if missing > 0:
        text += '.' * missing
    return text + '|'


def _check_blocks(items: Iterable[str]) -> list[str]:
    """Pack *items* into ten-cell blocks, each ending with ``|``.

    One-cell symbols therefore fill ten to a block; two-cell emoji fill five.
    A block that runs out of items is completed with ``.`` so the ``|`` stays in
    the same column on every row.
    """
    blocks: list[str] = []
    parts: list[str] = []
    used = 0
    for item in items:
        item_width = string_width(item)
        if used + item_width > FONT_CHECK_BLOCK_CELLS:
            blocks.append(_check_block(parts))
            parts, used = [], 0
        parts.append(item)
        used += item_width
    if parts:
        blocks.append(_check_block(parts))
    return blocks


def _pad_to_rows(blocks: list[str]) -> list[str]:
    """Complete *blocks* with ``.`` blocks so a section ends on a full row."""
    remaining = len(blocks) % FONT_CHECK_BLOCKS
    if remaining:
        blocks = blocks + [_check_block([])] * (FONT_CHECK_BLOCKS - remaining)
    return blocks


def font_check_rows() -> list[str]:
    """Return the fixed-width symbol and emoji rows for the help page.

    Each row is exactly :data:`FONT_CHECK_ROW_WIDTH` cells: five ten-cell blocks,
    each followed by ``|``.  One-cell catalog symbols come first, ten per block;
    the two-cell emoji follow, five per block and on a fresh row.  A block with
    more room than items is padded with ``.``, and the last row of each section
    is completed with ``.`` blocks, so every ``|`` must line up when the font and
    terminal are set up correctly.  A box, a blank or a shifted column breaks
    that alignment and makes the problem obvious.

    The emoji are always the Unicode ones, because the section exists to show
    what the emoji font will have to draw.
    """
    symbol_blocks = _pad_to_rows(_check_blocks(catalog_items()))
    emoji_blocks = _pad_to_rows(_check_blocks(
        glyph.unicode for _name, glyph in glyphs_in_group(EMOJI_GROUP)))
    blocks = symbol_blocks + emoji_blocks
    if not blocks:
        return []
    return [
        ''.join(blocks[start:start + FONT_CHECK_BLOCKS])
        for start in range(0, len(blocks), FONT_CHECK_BLOCKS)
    ]


def _spellings(text: str) -> list[str]:
    """Every form of *text* an app might have typed, most specific first.

    A glyph is often written with a variation selector (``⚠️``) and just as
    often without (``⚠``); both must map to the same fallback, and both must
    consume the selector so no orphan zero-width mark is left behind.
    """
    forms = [text]
    for selector in _VARIATION_SELECTORS:
        if selector in text:
            forms.append(text.replace(selector, ''))
        else:
            forms.append(text + selector)
    return forms


def _compile(mapping: Mapping[str, str]) -> re.Pattern[str] | None:
    """Compile one longest-match substitution pattern, or None when empty."""
    if not mapping:
        return None
    # Alternation is leftmost-first, so sorting longest-first is what lets a
    # multi-character glyph win over the single characters it contains.
    alternation = '|'.join(
        re.escape(form) for form in sorted(mapping, key=len, reverse=True)
    )
    return re.compile(alternation)


def _compile_tables() -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    """Build (and cache) the substitution patterns for both modes.

    Returns ``(ascii_table, upgrade_table)``.  The first replaces every
    registered glyph with its ASCII spelling.  The second rewrites the spellings
    this library used to draw to the code points that replaced them, so text
    written against an older release renders from the same font in Unicode mode
    too.  Both are built together because one registration can invalidate
    either.
    """
    global _compiled, _table, _upgrade_table  # pylint: disable=global-statement
    if _compiled:
        return _table, _upgrade_table
    # Rebuild from scratch.  A registration invalidates the cache, and an app
    # that claims a built-in's code point (under the same name or a new one)
    # must get its own fallback; keeping the old entry would silently ignore
    # the override for the rest of the process.
    _map.clear()
    _upgrade.clear()
    for glyph in _registry.values():
        if glyph.unicode.isascii():
            continue
        for form in _spellings(glyph.unicode):
            if form.isascii():
                continue
            _map[form] = glyph.ascii
    by_unicode = {glyph.unicode: glyph for glyph in _registry.values()}
    for old, new in DEPRECATED_GLYPHS.items():
        target = by_unicode.get(new)
        # Skip when the replacement is gone, or when the app registered the old
        # code point itself -- `register('choice', '\u2b9e', '>')` is the
        # documented way to keep the old marker.
        if target is None or old in by_unicode:
            continue
        for form in _spellings(old):
            if form.isascii():
                continue
            _upgrade[form] = target.unicode
            _map.setdefault(form, target.ascii)
    _table = _compile(_map)
    _upgrade_table = _compile(_upgrade)
    _compiled = True
    return _table, _upgrade_table


def _audit_enabled() -> bool:
    raw = os.environ.get(AUDIT_ENV, '')
    return raw.strip().lower() not in ('', '0', 'no', 'false', 'off')


def _suggest_name(ch: str) -> str:
    name = unicodedata.name(ch, 'glyph').lower()
    cleaned = re.sub(r'[^a-z0-9]+', '_', name).strip('_')
    return cleaned[:32] or 'glyph'


def _audit(text: str) -> None:
    """Log unsafe or unregistered decoration, once per code point.

    The first pass reports what :func:`find_issues` classifies -- a VS16-promoted
    base, a zero-width joiner, an East-Asian Ambiguous shape, an unapproved
    two-cell emoji -- and says what to use instead.  The second pass keeps the
    original behaviour for one-cell symbols that are registered nowhere, which is
    how an application learns the :func:`register` call for its own vocabulary.
    """
    for issue in find_issues(text):
        if issue.text in _audited:
            continue
        _audited.add(issue.text)
        logger.warning('glyph audit: %s', issue.hint)
    registered = {glyph.unicode for glyph in _registry.values()}
    for ch in text:
        if ch.isascii() or ch in _VARIATION_SELECTORS or ch in _audited:
            continue
        if ch in registered:
            continue
        code = ord(ch)
        decorative = unicodedata.category(ch) in _DECORATIVE_CATEGORIES
        if not (decorative or 0x2500 <= code <= 0x2BFF or 0x1F000 <= code <= 0x1FAFF):
            continue
        _audited.add(ch)
        logger.warning(
            'glyph audit: %r (U+%04X) has no ASCII fallback; teach it with '
            'Glyphs.register(%r, %r, <%r>)',
            ch, code, _suggest_name(ch), ch, 'ascii form',
        )


def transliterate(text: str) -> str:
    """Rewrite symbols the terminal cannot draw, and deprecated spellings.

    In ASCII mode every registered glyph becomes its ASCII spelling.  In *both*
    modes a spelling this library used to draw is upgraded to the code point
    that replaced it, so application text written against an older release
    renders from the same font instead of a fallback.  Those eight spellings are
    therefore rewritten even inside content; every other code point -- letters,
    digits, unregistered symbols -- passes through untouched, which is what
    keeps a pager showing ``Grüße`` byte-identical in both modes.
    """
    if not text or text.isascii():
        return text
    # Audit the text as written, in both modes: an approved mark is safe, but a
    # VS16-promoted or unapproved one is worth a line while the app is being
    # developed -- and in ASCII mode the substitution below would already have
    # hidden it.
    if _audit_enabled():
        _audit(text)
    ascii_table, upgrade_table = _compile_tables()
    if _ascii_mode:
        if ascii_table is None:
            return text
        return ascii_table.sub(lambda match: _map[match.group(0)], text)
    if upgrade_table is None:
        return text
    return upgrade_table.sub(lambda match: _upgrade[match.group(0)], text)


@dataclass(frozen=True)
class TerminalReport:
    """What could be learned about this terminal's glyph support."""

    encoding: str
    utf8: bool
    term: str
    ascii_required: bool
    notes: tuple[str, ...] = ()
    ascii_mode: bool = False
    source: str = 'auto'


def _normalized(encoding: str | None) -> str:
    return (encoding or '').strip().lower().replace('-', '').replace('_', '')


def _is_utf8(encoding: str | None) -> bool:
    """True for the UTF-8 family (``utf-8``, ``UTF8``, ``utf_8``, ...)."""
    name = _normalized(encoding)
    return name.startswith('utf8') or name == 'utf'


def terminal_report(
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Describe this terminal's ability to draw the UI's symbols.

    *environ* and *stream* exist so tests can supply a fake terminal.  The
    result is advisory except for ``ascii_required``, which is True only when
    the terminal provably cannot carry the glyphs (non-UTF-8 output encoding, or
    ``TERM=dumb``).  A font's coverage cannot be observed, so the report does not
    guess: every help page carries a built-in Fonts section with the real
    symbols, and the user judges them there.
    """
    env = os.environ if environ is None else environ
    out = sys.stdout if stream is None else stream
    encoding = getattr(out, 'encoding', None) or locale.getpreferredencoding(False) or ''
    term = str(env.get('TERM', '')).strip().lower()
    notes: list[str] = []

    utf8 = _is_utf8(encoding)
    if not utf8:
        notes.append(
            f'output encoding is {encoding or "unknown"}, which cannot show the '
            'symbols this program draws; using ASCII symbols instead'
        )
    if term in ASCII_TERMS:
        notes.append(f'TERM={term} cannot draw the symbols; using ASCII symbols instead')
    if not utf8 or term in ASCII_TERMS:
        notes.append(
            'for the full symbol set, run in a UTF-8 locale inside a '
            'Unicode-capable terminal'
        )
        return TerminalReport(
            encoding=encoding, utf8=utf8, term=term,
            ascii_required=True, notes=tuple(notes),
        )

    if term in LIMITED_TERMS:
        notes.append(
            f'TERM={term} uses a console font that often lacks some of these '
            'symbols; restart with --ascii if any line shows boxes'
        )
    return TerminalReport(
        encoding=encoding, utf8=utf8, term=term,
        ascii_required=False, notes=tuple(notes),
    )


def _env_mode(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Return ``(mode, note)`` for the environment override, if any."""
    raw = str(env.get(GLYPHS_ENV, '')).strip().lower()
    if not raw:
        return None, None
    if raw in _MODE_VALUES:
        return raw, f'glyph mode {raw} from {GLYPHS_ENV}={raw}'
    return None, (
        f'ignoring {GLYPHS_ENV}={raw!r}: expected one of {", ".join(_MODE_VALUES)}'
    )


def _resolve_mode(
    force_ascii: bool | None,
    report: TerminalReport,
    env: Mapping[str, str],
) -> tuple[bool, str, list[str]]:
    """Decide the mode: ``(ascii_mode, source, extra_notes)``."""
    if force_ascii is not None:
        if force_ascii:
            return True, 'request', ['using ASCII symbols (requested)']
        notes = []
        if report.ascii_required:
            notes.append(
                'Unicode symbols requested, but this terminal reports it cannot '
                'show them'
            )
        return False, 'request', notes

    mode, note = _env_mode(env)
    if mode is not None:
        notes = [note] if note else []
        return mode == 'ascii', 'env', notes
    if note is not None:
        notes = [note]
    else:
        notes = []

    auto_ascii = report.ascii_required
    return auto_ascii, 'auto', notes


def apply_policy(
    force_ascii: bool | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Set the process glyph mode and return what was learned.

    Precedence, highest first: *force_ascii* (an app option or ``--ascii``),
    ``CONSOLE_WINDOW_GLYPHS``, then auto-detection.  The returned report's
    ``notes`` are ready to print and its ``ascii_mode``/``source`` say what was
    decided (``'request'``, ``'env'`` or ``'auto'``).
    """
    env = os.environ if environ is None else environ
    report = terminal_report(environ=env, stream=stream)
    ascii_mode, source, extra = _resolve_mode(force_ascii, report, env)
    set_ascii(ascii_mode)
    return replace(
        report,
        notes=tuple(report.notes) + tuple(extra),
        ascii_mode=ascii_mode,
        source=source,
    )


def ensure_policy(
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Run auto-detection once, unless a mode has already been chosen.

    A window calls this on construction, which is how an app that never thinks
    about glyphs still gets the right mode.  It is deliberately *not* a reset:
    an explicit ``set_ascii()`` (or an earlier ``apply_policy()``) wins for the
    rest of the process, because a terminal does not change under a running
    program.
    """
    env = os.environ if environ is None else environ
    if not _decided:
        return apply_policy(None, environ=env, stream=stream)
    report = terminal_report(environ=env, stream=stream)
    return replace(report, ascii_mode=_ascii_mode, source='previous')


_reset_state()


class Glyphs:
    """Namespace facade over the module's single piece of state.

    The implementation is module-level functions (the switch is process state,
    not per-instance state, because there is one terminal); this class gives
    call sites a readable ``Glyphs.get('cursor')`` spelling without inventing an
    object to pass around.
    """

    register = staticmethod(register)
    register_many = staticmethod(register_many)
    probe = staticmethod(probe)
    reset = staticmethod(reset)
    get = staticmethod(get)
    unicode_of = staticmethod(unicode_of)
    lookup = staticmethod(lookup)
    group_of = staticmethod(group_of)
    glyphs_in_group = staticmethod(glyphs_in_group)
    font_missing = staticmethod(font_missing)
    find_issues = staticmethod(find_issues)
    is_ascii = staticmethod(is_ascii)
    set_ascii = staticmethod(set_ascii)
    probe_text = staticmethod(probe_text)
    catalog = staticmethod(catalog_items)
    catalog_entries = staticmethod(catalog_entries)
    catalog_rows = staticmethod(catalog_rows)
    font_check_rows = staticmethod(font_check_rows)
    transliterate = staticmethod(transliterate)
    terminal_report = staticmethod(terminal_report)
    apply_policy = staticmethod(apply_policy)
