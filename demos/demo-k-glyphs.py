#!/usr/bin/env python3
"""K — Glyphs and ASCII.

Owns: glyph-catalog, glyph-vocabulary, glyph-fallback, glyph-cli, glyph-help,
      emoji-group, emoji-fallback, emoji-detector
Base: c-options
Run:  ./demos/run-demo k-glyphs --ascii

Two pages share one registry.  The catalog page lists every registered one-cell
glyph with its fallback, its code point and its name, grouped by family with a
dim divider, so a missing glyph can be identified rather than merely noticed.
The emoji page lists the two-cell ``'emoji'`` group and runs ``find_issues()``
over five samples; ``e`` opens it and ESC returns.  ``a`` cycles the ASCII
fallbacks on either page -- both emoji spellings are two cells, so the table
keeps its columns.

The application vocabulary comes from ``ConsoleWindowOpts(glyphs=...)``.  Here
``tick`` falls back to ``OK`` in ASCII mode; the window registers it, so
``Glyphs.get('tick')`` is all the draw code needs.  The help page's built-in
Fonts section shows the whole one-cell catalog and every emoji, so the demo adds
no font check of its own.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import Glyphs
from console_window.glyphs import (
    CatalogEntry,
    find_issues,
    glyphs_in_group,
    set_ascii,
)
from console_window.textwidth import ljust, string_width

MAIN_ST = 0
NAME_WIDTH = 11
ASCII_WIDTH = 5
VERDICT_WIDTH = 9
CLEAN = 'clean'

DEMO_GLYPHS = {'tick': ('\u2713', 'OK')}
DEMO_PROBE = ('tick', 'cursor', 'choice', 'scroll_prev', 'scroll_next')

SAMPLES = (
    '\u2705 approved mark',
    '\u26a0\ufe0f VS16-promoted',
    '\u25cf East-Asian ambiguous',
    '\U0001f984 no fallback',
    '\u2713 one cell',
)


def _codepoint(character: str) -> str:
    """The Unicode column's payload, e.g. ``U+2502``."""
    return f'U+{ord(character):04X}'


class GlyphPage(DemoScreen):
    """Shared ASCII switch and divider for the two registry pages."""

    title = 'K-glyphs'

    def _sync_ascii(self) -> bool:
        ascii_on = bool(getattr(self.app.opts, 'ascii', False))
        # The switch is process state; writing it every pass keeps the `a` key,
        # `--ascii` and the tables from drifting apart.
        set_ascii(ascii_on)
        return ascii_on

    def _divider(self, label: str) -> str:
        """A rule that names what starts below it."""
        width = self.win.get_pad_width()
        rule = Glyphs.get('box_h')
        return f'{label} ' + rule * max(1, width - string_width(label) - 1)


class GlyphScreen(GlyphPage):
    title = 'K-glyphs'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        ascii_on = self._sync_ascii()
        self.add_fancy_header(
            f'K-glyphs  [e]:emoji  [a]:ascii={"ON" if ascii_on else "off"}  '
            '[?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )

        entries = Glyphs.catalog_entries()
        glyph_width, fallback_width, unicode_width = self._column_widths(entries)
        self.add_header(
            f'{"glyph":<{glyph_width}}  '
            f'{"fallback":<{fallback_width}}  '
            f'{"unicode":<{unicode_width}}  '
            'name',
            attr=cs.A_BOLD,
        )

        group = None
        for entry in entries:
            if entry.group != group:
                group = entry.group
                self.add_body(self._divider(group), attr=cs.A_DIM)
            self.add_body(self._table_row(
                entry, glyph_width, fallback_width, unicode_width))

    def emoji_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.emoji, self.pick_pos)

    @staticmethod
    def _column_widths(entries: list[CatalogEntry]) -> tuple[int, int, int]:
        """Widths wide enough for both the titles and every row."""
        glyph_width = max(
            len('glyph'), *(string_width(entry.active) for entry in entries))
        fallback_width = max(
            len('fallback'), *(string_width(entry.ascii) for entry in entries))
        unicode_width = max(
            len('unicode'), *(len(_codepoint(entry.unicode)) for entry in entries))
        return glyph_width, fallback_width, unicode_width

    @staticmethod
    def _table_row(entry: CatalogEntry, glyph_width: int,
                   fallback_width: int, unicode_width: int) -> str:
        return (
            f'{ljust(entry.active, glyph_width)}  '
            f'{ljust(entry.ascii, fallback_width)}  '
            f'{ljust(_codepoint(entry.unicode), unicode_width)}  '
            f'{entry.name}'
        )

class EmojiScreen(GlyphPage):
    title = 'K-emoji'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        ascii_on = self._sync_ascii()
        self.add_fancy_header(
            f'K-emoji  [a]:ascii={"ON" if ascii_on else "off"}  '
            'ESC:glyphs  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        # The emoji an app would reach for, in the active spelling.  (Not a
        # font check: the window transliterates header text, so in ASCII mode
        # this line is the fallbacks, which is the point of the `a` key.)
        self.add_header('status: ' + '  '.join(
            Glyphs.get(name) for name in ('ok', 'fail', 'attention', 'siren')))
        self.add_header(
            f'{"mark":<4} {"name":<{NAME_WIDTH}}  {"ascii":<{ASCII_WIDTH}}  w',
            attr=cs.A_BOLD,
        )
        for name, spec in glyphs_in_group('emoji'):
            shown = Glyphs.get(name)
            self.add_body(
                f'{shown}   {name:<{NAME_WIDTH}}  '
                f'{ljust(spec.ascii, ASCII_WIDTH)}  {string_width(shown)}')
        self.add_body('')
        self.add_body(self._divider('find_issues()'), attr=cs.A_DIM)
        for sample in SAMPLES:
            issues = find_issues(sample)
            verdict = issues[0].kind if issues else CLEAN
            self.add_body(f'{ljust(sample, 26)}  {verdict:<{VERDICT_WIDTH}}')


class GlyphApp(DemoApp):
    title = 'K-glyphs'
    screen_class = GlyphScreen
    win_options: ClassVar[dict[str, object]] = {
        'glyphs': DEMO_GLYPHS,
        'glyphs_probe': DEMO_PROBE,
    }
    help_paragraphs = (
        'Application vocabulary: ConsoleWindowOpts(glyphs=...) registers '
        "'tick' with its ASCII fallback 'OK'; Glyphs.get('tick') returns the "
        'spelling for the active mode.',
        'Choosing a family is a layout decision, not a preference for text over '
        'emoji: use the emoji when the row needs emphasis and can spare two '
        'cells, and the one-cell status symbols when it cannot. The `a` key '
        'keeps either table aligned because every fallback has the same width '
        'as the symbol it replaces.',
        'Approval is a width test. Every emoji in the group is one code point '
        'with East-Asian Width W, so it measures two cells here and in the '
        'terminal, and a variation selector cannot change that. find_issues() '
        'names the four ways a two-cell mark is unsafe: VS16-promoted, a '
        'zero-width joiner, East-Asian Ambiguous, and an unapproved emoji with '
        'no fallback.',
        'A mark is decoration, never the only signal: pair it with A_BOLD or '
        'A_REVERSE, which every terminal draws. When the chosen emoji cannot be '
        'drawn, switch to the two-cell text fallback; if the row can spare only '
        'one cell, use a one-cell status symbol instead. Either choice keeps the '
        'presentation and the width the row was measured for.',
    )

    def build_screens(self):
        self.main = self.screen_class(self)
        self.emoji = EmojiScreen(self)
        self.help = self.help_class(self)
        return [self.main, self.emoji, self.help]

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('emoji_screen', 'e - emoji page', keys=[ord('e')],
                     genre='action', scope={MAIN_ST})
        spin.add_key('ascii', 'a - ASCII fallbacks',
                     vals=[False, True], keys=[ord('a')],
                     comments='Both emoji spellings are two cells, so the table '
                              'keeps its columns either way.')
        return spin

    def after_build(self) -> None:
        # Start from whatever --ascii or the environment decided; the key cycles
        # from there.
        self.opts.ascii = Glyphs.is_ascii()


def build_app(backend: object | None = None,
              singleton: bool = True) -> GlyphApp:
    return GlyphApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-k-glyphs')


if __name__ == '__main__':
    main()
