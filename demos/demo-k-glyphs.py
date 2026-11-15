#!/usr/bin/env python3
"""K — Glyphs and ASCII.

Owns: glyph-catalog, glyph-vocabulary, glyph-fallback, glyph-cli, glyph-help
Base: c-options
Run:  ./demos/run-demo k-glyphs --ascii

The catalog page lists every registered glyph with its fallback, its code point
and its name, grouped by family with a dim divider, so a missing glyph can be
identified rather than merely noticed.

The application vocabulary comes from ``ConsoleWindowOpts(glyphs=...)``.  Here
``tick`` falls back to ``OK`` in ASCII mode; the window registers it, so
``Glyphs.get('tick')`` is all the draw code needs.  The help page's built-in
Fonts section shows the whole catalog and every mark, so the demo adds no font
check of its own.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import Glyphs
from console_window.glyphs import CatalogEntry
from console_window.textwidth import ljust, string_width

DEMO_GLYPHS = {'tick': ('\u2713', 'OK')}
DEMO_PROBE = ('tick', 'cursor', 'choice', 'scroll_prev', 'scroll_next')


def _codepoint(character: str) -> str:
    """The Unicode column's payload, e.g. ``U+2502``."""
    return f'U+{ord(character):04X}'


class GlyphScreen(DemoScreen):
    title = 'K-glyphs'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header('K-glyphs  [?]:help  [q]uit', mode='Underline')

        entries = Glyphs.catalog_entries()
        glyph_width, fallback_width, unicode_width = self._column_widths(entries)
        self.add_header(
            f'{"glyph":<{glyph_width}}  '
            f'{"fallback":<{fallback_width}}  '
            f'{"unicode":<{unicode_width}}  '
            'name',
            attr=cs.A_BOLD,
        )

        width = self.win.get_pad_width()
        group = None
        for entry in entries:
            if entry.group != group:
                group = entry.group
                self.add_body(self._group_divider(group, width), attr=cs.A_DIM)
            self.add_body(self._table_row(
                entry, glyph_width, fallback_width, unicode_width))

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

    @staticmethod
    def _group_divider(group: str, width: int) -> str:
        """A rule that names the family it starts."""
        label = f'{group} '
        rule = Glyphs.get('box_h')
        return label + rule * max(1, width - string_width(label))


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
    )


def build_app(backend: object | None = None,
              singleton: bool = True) -> GlyphApp:
    return GlyphApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-k-glyphs')


if __name__ == '__main__':
    main()
