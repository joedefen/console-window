"""Decorative glyphs, and how to live without them.

Every symbol a TUI uses for *meaning* rather than words needs two spellings:
the one the design is built around, and one that a terminal which cannot draw
it (or a font that lacks it) can still show.  A symbol that fails to draw does
not fail loudly -- the terminal paints a box, or nothing -- and the row silently
loses its meaning.  Keeping the symbols in one table matters because the
failure is invisible.

The table an application draws from is :data:`BUILTIN_GLYPHS`: about eighty
symbols grouped by family, every one of them a single cell wide and covered by
the default monospace font on Debian, Ubuntu and Fedora.  :func:`catalog_items`
and :func:`catalog_rows` are how a screen lists the characters; the theme page
does.  :func:`catalog_entries` keeps each name and its family, which is what a
grouped table wants, and :func:`group_of` answers the same question for one
name.

What can and cannot be checked
------------------------------
Whether a terminal can *encode* UTF-8 is observable: the output stream's
encoding and ``TERM`` say so.  Whether the *font* has a glyph for a code point
is not observable from inside the process.  So detection is split three ways:

* :func:`terminal_report` reports what is detectable and sets
  ``ascii_required`` only when UTF-8 output is impossible;
* that report always carries a *font check* line containing the real glyphs, so
  the user can look at them and judge;
* :func:`set_ascii` forces the fallback for everything else, including a font
  the check cannot see.

Marks are the other family
--------------------------
Some symbols are worth two cells: a status badge, a coloured dot, a mark that is
seen at a glance in a mono theme.  :data:`BUILTIN_MARKS` is that family, and its
contract is different from the one-cell catalog's.  Every entry is an emoji whose
East-Asian Width is ``W``, so it measures two cells in this library's model *and*
in the terminal, and appending a variation selector cannot change that.  The
ASCII spelling is two cells as well, so ``--ascii`` (or a terminal with no emoji
font) never moves the columns around a mark.  :func:`mark` is the accessor and
:func:`find_issues` is the development-time check that reports VS16-promoted,
Ambiguous and unapproved marks in a string.  ``docs/Emoji-support.md`` is the
long form, including why the bold-looking text symbols are the unsafe ones.

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

from .textwidth import string_width

logger = logging.getLogger(__name__)

__all__ = [
    'AUDIT_ENV',
    'BUILTIN_GLYPHS',
    'BUILTIN_MARKS',
    'DEPRECATED_GLYPHS',
    'GLYPHS_ENV',
    'MARK_GROUP',
    'CatalogEntry',
    'Glyph',
    'Glyphs',
    'Issue',
    'SafeMark',
    'TerminalReport',
    'apply_policy',
    'catalog_entries',
    'catalog_items',
    'catalog_rows',
    'ensure_policy',
    'find_issues',
    'get',
    'group_of',
    'is_ascii',
    'lookup',
    'mark',
    'marks',
    'marks_probe_text',
    'probe',
    'probe_text',
    'register',
    'register_many',
    'register_mark',
    'reset',
    'set_ascii',
    'terminal_report',
    'transliterate',
    'unicode_of',
    'validate_mark',
]

#: Environment variable that pins the glyph mode for apps without argparse
#: (``auto``, ``ascii`` or ``unicode``).  Also the escape hatch for an app whose
#: terminal was detected wrongly.
GLYPHS_ENV = 'CONSOLE_WINDOW_GLYPHS'

#: Environment variable that turns on the decoration audit.  In both glyph
#: modes, VS16-promoted, joiner-sequenced, East-Asian Ambiguous and unapproved
#: marks get a verdict and a suggestion in the log, once per code point; symbols
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


@dataclass(frozen=True)
class Glyph:
    """One decorative symbol in both spellings, with its catalog family.

    ``ascii`` may be empty: that spells "delete the decoration", which is the
    right answer for a marker whose meaning is already carried by its column.

    ``group`` is the family the listing uses (``'math'``, ``'frames'``,
    ``'application'``, ...).  A catalog can therefore start a divider when the
    group changes, and a lockup can ask which family a name belongs to, without
    a second name-to-group table to keep in step.
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


#: Glyphs this library draws itself, and the catalog an application draws from.
#:
#: The catalog is the answer to "what may I use?": every entry is one cell wide
#: in both spellings and has a plain ASCII fallback, and the set is confined to
#: characters that the default monospace font on Debian, Ubuntu and Fedora
#: (DejaVu Sans Mono) actually covers -- no emoji, nothing from a patched font.
#: A code point has exactly one fallback even when two names draw it
#: (``cursor_block`` and ``swatch`` are the same block); an application that
#: registers a code point itself takes it over (see :func:`_compile_tables`).
BUILTIN_GLYPHS: dict[str, Glyph] = {
    # --- the library's own UI marks -----------------------------------------
    'cursor': Glyph('\u2502', '|'),          # narrow text cursor in widgets
    'cursor_block': Glyph('\u2588', '#'),    # block cursor / caret
    # One cell in both spellings: the choice list indents the other rows by one
    # cell plus a space, so a two-character marker would knock the column out
    # of alignment exactly where the terminal is already struggling.
    # U+27A4, not the equilateral U+2B9E this used to be: DejaVu Sans Mono has
    # no glyph for U+2B9E, so the marker came from a fallback font that can be
    # wider than one cell.  Both spellings stay one cell wide.
    'choice': Glyph('\u27a4', '>'),          # "this choice is the current value"
    'scroll_prev': Glyph('\u25c0', '<'),     # dialog horizontal scroll, left
    'scroll_next': Glyph('\u25b6', '>'),     # dialog horizontal scroll, right
    'alert_up': Glyph('\u25b2', '^'),        # alert "more above"
    'alert_down': Glyph('\u25bc', 'v'),      # alert "more below"
    # The heavy (black) arrows: the light `←`/`→` look anaemic beside the solid
    # triangles the same UI uses, and these are in the same font.
    'nav_prev': Glyph('\u2b05', '<-'),       # help legend, "left arrow"
    'nav_next': Glyph('\u27a1', '->'),       # help legend, "right arrow"
    'bullet': Glyph('\u00b7', '.'),          # help-list bullet
    'swatch': Glyph('\u2588', '#'),          # theme color swatch

    # --- frames -------------------------------------------------------------
    # The message-box frame.  `curses.textpad.rectangle()` already draws with
    # ACS line art, but a message box painted by hand needs its own fallback;
    # registering the corners keeps the ASCII mode invariant ("every painted
    # cell is ASCII") true for dialogs too.
    'box_tl': Glyph('\u250c', '+'),
    'box_h': Glyph('\u2500', '-'),
    'box_tr': Glyph('\u2510', '+'),
    'box_v': Glyph('\u2502', '|'),           # also reused by widgets' cursor
    'box_bl': Glyph('\u2514', '+'),
    'box_br': Glyph('\u2518', '+'),
    'frame_rounded_tl': Glyph('\u256d', '+'),
    'frame_rounded_tr': Glyph('\u256e', '+'),
    'frame_rounded_bl': Glyph('\u2570', '+'),
    'frame_rounded_br': Glyph('\u256f', '+'),
    'frame_h_double': Glyph('\u2550', '='),
    'frame_v_double': Glyph('\u2551', '|'),

    # --- arrows -------------------------------------------------------------
    'arrow_up': Glyph('\u2b06', '^'),
    'arrow_down': Glyph('\u2b07', 'v'),
    'arrow_double_left': Glyph('\u21d0', '<='),
    'arrow_double_right': Glyph('\u21d2', '=>'),
    'arrow_double_up': Glyph('\u21d1', '^^'),
    'arrow_double_down': Glyph('\u21d3', 'vv'),

    # --- triangles: hollow and small, in both horizontal directions ---------
    'tri_right_hollow': Glyph('\u25b7', '>'),
    'tri_left_hollow': Glyph('\u25c1', '<'),
    'tri_up_hollow': Glyph('\u25b3', '^'),
    'tri_down_hollow': Glyph('\u25bd', 'v'),
    'tri_right_small': Glyph('\u25b8', '>'),
    'tri_left_small': Glyph('\u25c2', '<'),

    # --- shapes: filled and hollow pairs ------------------------------------
    'circle_filled': Glyph('\u25cf', '@'),
    'circle_hollow': Glyph('\u25ef', 'o'),   # large circle: reads heavier
    'diamond_filled': Glyph('\u25c6', '#'),
    'diamond_hollow': Glyph('\u25c7', '<>'),
    'square_filled': Glyph('\u25fc', '#'),   # medium pair: a matched weight
    'square_hollow': Glyph('\u25fb', '[]'),
    'star_filled': Glyph('\u2605', '*'),
    'star_hollow': Glyph('\u2606', '+'),

    # --- blocks and bars: textures, half blocks, sparkline columns ----------
    'block_light': Glyph('\u2591', '.'),
    'block_medium': Glyph('\u2592', ':'),
    'block_dark': Glyph('\u2593', '#'),
    'block_upper': Glyph('\u2580', '"'),
    'block_left': Glyph('\u258c', '['),
    'block_right': Glyph('\u2590', ']'),
    'block_quadrant': Glyph('\u259a', '%'),
    'bar_1': Glyph('\u2581', '1'),
    'bar_2': Glyph('\u2582', '2'),
    'bar_3': Glyph('\u2583', '3'),
    'bar_4': Glyph('\u2584', '4'),
    'bar_5': Glyph('\u2585', '5'),
    'bar_6': Glyph('\u2586', '6'),
    'bar_7': Glyph('\u2587', '7'),

    # --- marks and status symbols -------------------------------------------
    'check': Glyph('\u2713', 'v'),
    'check_heavy': Glyph('\u2714', 'v'),
    'cross': Glyph('\u2717', 'x'),
    'cross_heavy': Glyph('\u2718', 'x'),
    'ballot_box': Glyph('\u2610', '[ ]'),
    'ballot_check': Glyph('\u2611', '[v]'),
    'ballot_cross': Glyph('\u2612', '[x]'),
    'warn': Glyph('\u26a0', '!'),
    'sun': Glyph('\u2600', '*'),
    'cloud': Glyph('\u2601', '~'),

    # --- math ---------------------------------------------------------------
    'plus_minus': Glyph('\u00b1', '+-'),
    'times': Glyph('\u00d7', 'x'),
    'not_equal': Glyph('\u2260', '!='),
    'less_equal': Glyph('\u2264', '<='),
    'greater_equal': Glyph('\u2265', '>='),
    'approx': Glyph('\u2248', '~'),
    'infinity': Glyph('\u221e', 'inf'),

    # --- currency -----------------------------------------------------------
    'euro': Glyph('\u20ac', 'E'),
    'pound': Glyph('\u00a3', 'L'),
    'yen': Glyph('\u00a5', 'Y'),

    # --- typography ---------------------------------------------------------
    'en_dash': Glyph('\u2013', '-'),
    'em_dash': Glyph('\u2014', '--'),
    'ellipsis': Glyph('\u2026', '...'),
}

#: The catalog family of each built-in symbol, in catalog order.  The table
#: above groups its entries with comments; this is the same grouping as data,
#: because a screen cannot read a comment.  Names not listed here are
#: application registrations and land in the ``'application'`` group.
BUILTIN_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('ui', (
        'cursor', 'cursor_block', 'choice', 'scroll_prev', 'scroll_next',
        'alert_up', 'alert_down', 'nav_prev', 'nav_next', 'bullet', 'swatch',
    )),
    ('frames', (
        'box_tl', 'box_h', 'box_tr', 'box_v', 'box_bl', 'box_br',
        'frame_rounded_tl', 'frame_rounded_tr', 'frame_rounded_bl',
        'frame_rounded_br', 'frame_h_double', 'frame_v_double',
    )),
    ('arrows', (
        'arrow_up', 'arrow_down', 'arrow_double_left', 'arrow_double_right',
        'arrow_double_up', 'arrow_double_down',
    )),
    ('triangles', (
        'tri_right_hollow', 'tri_left_hollow', 'tri_up_hollow',
        'tri_down_hollow', 'tri_right_small', 'tri_left_small',
    )),
    ('shapes', (
        'circle_filled', 'circle_hollow', 'diamond_filled', 'diamond_hollow',
        'square_filled', 'square_hollow', 'star_filled', 'star_hollow',
    )),
    ('blocks', (
        'block_light', 'block_medium', 'block_dark', 'block_upper',
        'block_left', 'block_right', 'block_quadrant', 'bar_1', 'bar_2',
        'bar_3', 'bar_4', 'bar_5', 'bar_6', 'bar_7',
    )),
    ('marks', (
        'check', 'check_heavy', 'cross', 'cross_heavy', 'ballot_box',
        'ballot_check', 'ballot_cross', 'warn', 'sun', 'cloud',
    )),
    ('math', (
        'plus_minus', 'times', 'not_equal', 'less_equal', 'greater_equal',
        'approx', 'infinity',
    )),
    ('currency', ('euro', 'pound', 'yen')),
    ('typography', ('en_dash', 'em_dash', 'ellipsis')),
)

# Attach the family to each built-in without disturbing the readable table
# above.  A missing name is a table/grouping bug, so the lookup is deliberately
# unguarded and fails at import.
for _group_name, _group_members in BUILTIN_GROUPS:
    for _member in _group_members:
        BUILTIN_GLYPHS[_member] = replace(
            BUILTIN_GLYPHS[_member], group=_group_name)
del _group_name, _group_members, _member

#: The catalog family of the two-cell marks.  A glyph in this family is listed by
#: :func:`marks`, not by :func:`catalog_items`, because the one-cell catalog
#: promises something these cannot ("no emoji, one cell, DejaVu Sans Mono").
#: Not ``'marks'``: that family already exists in :data:`BUILTIN_GROUPS` for the
#: one-cell check, cross and ballot symbols, and the two must not be confused.
MARK_GROUP = 'badges'


def validate_mark(spec: SafeMark) -> None:
    """Raise unless *spec* is a width-safe mark.

    The rules are the ones in ``docs/Emoji-support.md``: a single ``EAW=W`` code
    point, two cells in this model, two cells with a variation selector appended,
    and a plain-ASCII fallback that is also two cells.  They are checked because
    a violation is invisible -- the terminal draws something, at a width the row
    was not measured for.
    """
    for field, value in (('name', spec.name), ('emoji', spec.emoji),
                         ('ascii', spec.ascii), ('group', spec.group)):
        if not isinstance(value, str) or not value:
            raise TypeError(
                f'SafeMark.{field} must be a non-empty str, got {value!r}')
    if len(spec.emoji) != 1:
        raise ValueError(
            f'mark {spec.name!r}: the emoji must be one code point, '
            f'got {spec.emoji!r}')
    if spec.emoji in _VARIATION_SELECTORS or spec.emoji == '\u200d':
        raise ValueError(
            f'mark {spec.name!r}: a variation selector or joiner is not a mark; '
            'use the base code point')
    eaw = unicodedata.east_asian_width(spec.emoji)
    if eaw != 'W':
        raise ValueError(
            f'mark {spec.name!r}: {spec.emoji!r} is East-Asian {eaw}, not W; its '
            'cell count is terminal-dependent')
    width = string_width(spec.emoji)
    if width != 2:
        raise ValueError(
            f'mark {spec.name!r}: {spec.emoji!r} measures {width} cells, not 2')
    promoted = string_width(spec.emoji + _VARIATION_SELECTORS[0])
    if promoted != width:
        raise ValueError(
            f'mark {spec.name!r}: a variation selector changes {spec.emoji!r} '
            f'from {width} to {promoted} cells')
    if not spec.ascii.isascii():
        raise ValueError(
            f'mark {spec.name!r}: the fallback must be plain ASCII, '
            f'got {spec.ascii!r}')
    ascii_width = string_width(spec.ascii)
    if ascii_width != width:
        raise ValueError(
            f'mark {spec.name!r}: the fallback {spec.ascii!r} measures '
            f'{ascii_width} cells, not {width}; it would shift the column it '
            'replaces')


@dataclass(frozen=True)
class SafeMark:
    """One approved two-cell mark, in both spellings.

    The contract is width, not beauty: the emoji is a single code point whose
    East-Asian Width is ``W``, so it is two cells here and in the terminal, and a
    variation selector cannot change that.  The ASCII spelling is two cells too,
    so switching to ``--ascii`` leaves the columns where they were.
    """

    name: str
    emoji: str
    ascii: str
    group: str = MARK_GROUP

    def __post_init__(self) -> None:
        validate_mark(self)


#: The approved two-cell marks.  Small on purpose: status, dots, data, comms and
#: waiting cover an ordinary application, and every entry costs two cells wherever
#: it is drawn.  Names do not reuse the one-cell catalog's names (both families
#: share one registry, so `warn` is already U+26A0).
BUILTIN_MARKS: dict[str, SafeMark] = {
    # --- status: the marks that have to be seen ------------------------------
    'ok': SafeMark('ok', '\u2705', 'v '),               # white heavy check mark
    'fail': SafeMark('fail', '\u274c', 'x '),           # cross mark
    'attention': SafeMark('attention', '\u2757', '! '),  # heavy exclamation
    'ask': SafeMark('ask', '\u2753', '? '),             # question ornament
    'stop': SafeMark('stop', '\U0001f6d1', '- '),       # octagonal sign
    'ban': SafeMark('ban', '\u26d4', '# '),             # no entry
    'siren': SafeMark('siren', '\U0001f6a8', '!!'),     # revolving light
    'boom': SafeMark('boom', '\U0001f4a5', '* '),       # collision symbol
    # --- dots: two cells of status colour ------------------------------------
    'dot_green': SafeMark('dot_green', '\U0001f7e2', 'G '),
    'dot_yellow': SafeMark('dot_yellow', '\U0001f7e1', 'Y '),
    'dot_red': SafeMark('dot_red', '\U0001f534', 'R '),
    'dot_blue': SafeMark('dot_blue', '\U0001f535', 'B '),
    'dot_black': SafeMark('dot_black', '\u26ab', 'K '),
    'dot_white': SafeMark('dot_white', '\u26aa', 'W '),
    # --- data: the objects an app lists --------------------------------------
    'folder': SafeMark('folder', '\U0001f4c1', '[ '),
    'file': SafeMark('file', '\U0001f4c4', 'f '),
    'chart': SafeMark('chart', '\U0001f4ca', '| '),
    'find': SafeMark('find', '\U0001f50d', 'o '),
    'lock': SafeMark('lock', '\U0001f512', 'L '),
    'key': SafeMark('key', '\U0001f511', 'k '),
    # --- comms: the events an app reports ------------------------------------
    'mail': SafeMark('mail', '\U0001f4e7', '@ '),
    'bell': SafeMark('bell', '\U0001f514', 'n '),
    'chat': SafeMark('chat', '\U0001f4ac', 'm '),
    'globe': SafeMark('globe', '\U0001f30d', 'g '),
    'package': SafeMark('package', '\U0001f4e6', 'p '),
    # --- waiting -------------------------------------------------------------
    'wait': SafeMark('wait', '\u23f3', 'w '),           # hourglass with sand
}

# Marks share the registry with the one-cell glyphs, so transliterate() rewrites
# them in ASCII mode with no second pass.  Check the two table-level invariants
# here: a name that collides with a one-cell glyph, and two names drawing the
# same character (a catalog cannot tell them apart).
for _mark_name, _mark_spec in BUILTIN_MARKS.items():
    if _mark_name in BUILTIN_GLYPHS:
        raise ValueError(
            f'mark {_mark_name!r} reuses the name of a one-cell glyph')
_mark_drawn: dict[str, str] = {}
for _mark_name, _mark_spec in BUILTIN_MARKS.items():
    if _mark_spec.emoji in _mark_drawn:
        raise ValueError(
            f'marks {_mark_drawn[_mark_spec.emoji]!r} and {_mark_name!r} draw '
            f'the same character {_mark_spec.emoji!r}')
    _mark_drawn[_mark_spec.emoji] = _mark_name
del _mark_name, _mark_spec, _mark_drawn

#: Marks the font check prints, in reading order.  One per status, because a
#: missing emoji font is most visible on the marks an app uses for status.
MARKS_PROBE: tuple[str, ...] = ('ok', 'fail', 'attention', 'siren')

#: Glyph names the font check prints, in reading order, when an app registers
#: none of its own.  These are the built-ins a user is most likely to notice.
#: The theme page shows the whole catalog, so this line stays short.
BUILTIN_PROBE: tuple[str, ...] = (
    'nav_prev', 'nav_next', 'choice', 'cursor', 'cursor_block', 'bullet',
)

#: Symbols per sample row on the theme page.  The full catalog is three rows at
#: this width; a narrower terminal wraps into more rows rather than truncating.
CATALOG_PER_ROW = 27

#: Spellings this library used to draw, mapped to the code point that replaced
#: them.  Text written against an older release is upgraded in *both* modes, so
#: it renders from the same font instead of a fallback.  An application that
#: registers one of these code points itself keeps it (see
#: :func:`_compile_tables`), which is the escape hatch for an app that liked the
#: old shape.
DEPRECATED_GLYPHS: dict[str, str] = {
    '\u2b9e': '\u27a4',   # choice: U+2B9E is not in DejaVu Sans Mono
    '\u2190': '\u2b05',   # nav_prev
    '\u2192': '\u27a1',   # nav_next
    '\u2191': '\u2b06',   # arrow_up
    '\u2193': '\u2b07',   # arrow_down
    '\u25cb': '\u25ef',   # circle_hollow
    '\u25a1': '\u25fb',   # square_hollow
    '\u25a0': '\u25fc',   # square_filled
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
    # The marks are Glyphs too -- one registry, one substitution pass -- but they
    # stay out of the one-cell catalog (see catalog_entries()).
    _registry.update({
        name: Glyph(spec.emoji, spec.ascii, group=MARK_GROUP)
        for name, spec in BUILTIN_MARKS.items()
    })
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

    *group* is the catalog family (``'math'``, ``'widgets'``, ...).  ``None``
    keeps the family of an already-registered name, so overriding a built-in's
    spelling does not silently move it into the application group; a new name
    with no group joins ``'application'``.
    """
    if not isinstance(name, str) or not name:
        raise TypeError(f'glyph name must be a non-empty str, got {name!r}')
    existing = _registry.get(name)
    resolved_group = group
    if resolved_group is None:
        resolved_group = existing.group if existing is not None else 'application'
    _registry[name] = Glyph(unicode_text, ascii_text, group=resolved_group)
    if probe:
        _add_probe(name)
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
    *group* applies to the pair values, and overrides a ``Glyph``'s declared
    family when given.  A ``Glyph`` left at the default ``'application'`` family
    keeps an existing name's family, so overriding a built-in's spelling does
    not move it out of the family it is cataloged under.
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


def get(name: str) -> str:
    """Return glyph *name* in the active set."""
    try:
        glyph = _registry[name]
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc
    return glyph.ascii if _ascii_mode else glyph.unicode


def unicode_of(name: str) -> str:
    """Return glyph *name* in its Unicode form, whatever the active mode is."""
    try:
        return _registry[name].unicode
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc


def lookup(name: str) -> Glyph:
    """Return the :class:`Glyph` registered as *name*.

    Unlike :func:`get`, this exposes both spellings and the group, which is what
    a catalog listing or a lookup table needs.
    """
    try:
        return _registry[name]
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc


def group_of(name: str) -> str:
    """Return the catalog family (``'math'``, ``'ui'``, ...) of *name*."""
    return lookup(name).group


def register_mark(name: str, emoji: str, ascii_text: str) -> None:
    """Teach the library one approved two-cell mark.

    Validation is the built-in table's (:func:`validate_mark`): a single
    ``EAW=W`` code point, two cells in both spellings, and a variation selector
    that changes neither.  Registration puts the mark in the same substitution
    table as the one-cell glyphs, so ``transliterate()`` rewrites it in ASCII
    mode and the audit knows the fallback exists.
    """
    spec = SafeMark(name, emoji, ascii_text)
    for existing in marks():
        if existing.emoji == spec.emoji and existing.name != name:
            raise ValueError(f'mark {existing.name!r} already draws {spec.emoji!r}')
    register(name, spec.emoji, spec.ascii, group=MARK_GROUP)


def mark(name: str) -> str:
    """Return approved mark *name* in the active spelling.

    Always two cells: the emoji in Unicode mode, the plain-ASCII fallback in
    ASCII mode.  A name that is not an approved mark raises ``KeyError``, which
    is the development-time check -- it fires in an application's tests rather
    than halfway through a draw.
    """
    glyph = lookup(name)
    if glyph.group != MARK_GROUP:
        raise KeyError(f'{name!r} is not an approved mark')
    return glyph.ascii if _ascii_mode else glyph.unicode


def marks() -> list[SafeMark]:
    """Every approved mark, in registration order, as :class:`SafeMark` records."""
    return [
        SafeMark(name, glyph.unicode, glyph.ascii)
        for name, glyph in _registry.items()
        if glyph.group == MARK_GROUP
    ]


def marks_probe_text() -> str:
    """The real Unicode marks a user should look at (never the ASCII set).

    The font check has to print the mark that might be missing; printing the
    fallback would check nothing.
    """
    shown: list[str] = []
    for name in MARKS_PROBE:
        glyph = _registry.get(name)
        if glyph is None or glyph.unicode in shown:
            continue
        shown.append(glyph.unicode)
    return ' '.join(shown)


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
_SINGLE_CELL_HINT = 'use mark() for two cells, or a one-cell EAW=N mark like \u2713'


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

    Four verdicts, one per failure mode in ``docs/Emoji-support.md``:

    * ``vs16`` -- a code point whose width depends on whether the terminal
      honors a variation selector (``⚠`` becomes two cells with ``U+FE0F``);
    * ``zwj`` -- a zero-width joiner, so the sequence's width is anyone's guess;
    * ``ambiguous`` -- East-Asian *Ambiguous*: one cell here, two in a CJK-width
      terminal;
    * ``unapproved`` -- a two-cell emoji with no approved fallback.

    One issue per offending code point: a base that is followed by a selector is
    reported once, at the selector (which carries the base in its text), and the
    code points of a joiner sequence are not also reported individually.
    Approved marks and ordinary text produce nothing: ``Grüße``, ``—`` and ``±``
    are content, not decoration, and are outside the ranges the check looks at.
    A bare one-cell symbol is not a hazard either -- ``✓`` is rung 3 of the
    ladder, and whether a terminal forces emoji presentation for it cannot be
    observed anyway -- so it is reported only if a selector is attached.
    """
    if not text or text.isascii():
        return []
    approved = {
        glyph.unicode for glyph in _registry.values() if glyph.group == MARK_GROUP
    }
    joined = _sequence_offsets(text)
    issues: list[Issue] = []
    for offset, ch in enumerate(text):
        if ch in _VARIATION_SELECTORS:
            base = text[offset - 1] if offset else ''
            if base in approved:
                # An approved mark is VS16-immune by construction (validate_mark
                # checks it), so a stray selector next to one is harmless.
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
                '2 in a CJK-width terminal; use mark() or a one-cell EAW=N mark'))
            continue
        if eaw == 'W':
            issues.append(Issue(
                'unapproved', ch, offset,
                f'{ch} ({code}) is a two-cell mark with no approved fallback; '
                'add it with Glyphs.register_mark() or use mark()'))
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
                    include_marks: bool = False) -> list[CatalogEntry]:
    """Every registered glyph with its name and family, in catalog order.

    The built-ins come first, grouped by family, and the application's own
    registrations follow.  Every name is listed by default, so a table with a
    Name column can show ``cursor_block`` and ``swatch`` separately even though
    they draw the same character.  ``unique=True`` keeps only the first name for
    each character, which is the flat sample list :func:`catalog_items` returns.

    The two-cell marks are left out unless ``include_marks=True``: the one-cell
    catalog promises "no emoji, one cell, in the default monospace font", and a
    :data:`BUILTIN_MARKS` entry cannot keep that promise.  A page that wants both
    families passes ``include_marks=True`` and splits on ``group``.
    """
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for name, glyph in _registry.items():
        if glyph.group == MARK_GROUP and not include_marks:
            continue
        if unique:
            if glyph.unicode in seen:
                continue
            seen.add(glyph.unicode)
        entries.append(CatalogEntry(glyph.group, name, glyph.unicode, glyph.ascii))
    return entries


def catalog_items(include_marks: bool = False) -> list[str]:
    """Every registered glyph, once, in registration order, in the active set.

    This is the list an application consults when it needs a symbol: the
    built-ins come first and the application's own registrations follow.  Two
    names may draw the same character (``cursor_block`` and ``swatch``); the
    character is listed once.  Use :func:`catalog_entries` when the names or
    groups matter.
    """
    return [
        entry.active
        for entry in catalog_entries(unique=True, include_marks=include_marks)
    ]


def catalog_rows(width: int, per_row: int = CATALOG_PER_ROW,
                 include_marks: bool = False) -> list[str]:
    """Pack the catalog into space-separated rows no wider than *width* cells.

    A fallback can be more than one cell (``->``, ``[x]``, ``...``), so rows are
    measured rather than counted: a narrow terminal wraps into more rows instead
    of overflowing or truncating the set.  The rows are display text; the
    caller adds them to a screen.
    """
    rows: list[str] = []
    row: list[str] = []
    used = 0
    for item in catalog_items(include_marks=include_marks):
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
    two-cell mark -- and says what to use instead.  The second pass keeps the
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
    ``TERM=dumb``).  A font's coverage cannot be observed, so the font-check
    note asks the user to look instead.
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
    notes.append(
        f'font check: {probe_text()}  (if any symbol is a box or blank, use --ascii)'
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
    register_mark = staticmethod(register_mark)
    probe = staticmethod(probe)
    reset = staticmethod(reset)
    get = staticmethod(get)
    unicode_of = staticmethod(unicode_of)
    lookup = staticmethod(lookup)
    group_of = staticmethod(group_of)
    mark = staticmethod(mark)
    marks = staticmethod(marks)
    marks_probe_text = staticmethod(marks_probe_text)
    find_issues = staticmethod(find_issues)
    is_ascii = staticmethod(is_ascii)
    set_ascii = staticmethod(set_ascii)
    probe_text = staticmethod(probe_text)
    catalog = staticmethod(catalog_items)
    catalog_entries = staticmethod(catalog_entries)
    catalog_rows = staticmethod(catalog_rows)
    transliterate = staticmethod(transliterate)
    terminal_report = staticmethod(terminal_report)
    apply_policy = staticmethod(apply_policy)
