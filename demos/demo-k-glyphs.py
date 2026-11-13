#!/usr/bin/env python3
"""K — Glyphs and ASCII.

Owns: glyph-catalog, glyph-vocabulary, glyph-fallback, glyph-cli, glyph-help
Base: c-options
Run:  ./demos/run-demo k-glyphs --ascii

The catalog page is the font check: if a symbol is a box or a blank, restart
with ``--ascii``.  ``Glyphs.catalog_rows()`` packs the whole registered set into
measured rows, so the page also doubles as the sample of every symbol.

The application vocabulary comes from ``ConsoleWindowOpts(glyphs=...)``.  Here
``tick`` falls back to ``OK`` in ASCII mode; the window registers it, so
``Glyphs.get('tick')`` is all the draw code needs.  The help screen turns on
``show_display_notes``, which appends ``help.glyph_paragraph()``.
"""

from __future__ import annotations

from typing import ClassVar

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import BasicHelpScreen, Glyphs, OptionSpinner

MAIN_ST = 0
HELP_ST = 1

DEMO_GLYPHS = {'tick': ('\u2713', 'OK')}
DEMO_PROBE = ('tick', 'cursor', 'choice', 'scroll_prev', 'scroll_next')


class GlyphScreen(DemoScreen):
    title = 'glyphs'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        mode = 'ASCII' if self.win.ascii_mode else 'Unicode'
        self.add_fancy_header(
            f'glyphs  mode={mode}  pass {self.app.iteration}  '
            f'[?]help  [q]uit',
            mode='Underline',
        )
        self.add_header(f'font check: {Glyphs.probe_text()}')
        self.add_header(f'application glyph: {Glyphs.get("tick")} (tick)')
        self.add_header('catalog:')
        for line in Glyphs.catalog_rows(self.win.get_pad_width()):
            self.add_body(line)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class GlyphHelpScreen(BasicHelpScreen):
    show_display_notes = True

    def extra_help_paragraphs(self):
        return (
            'Application vocabulary: ConsoleWindowOpts(glyphs=...) registers '
            "'tick' with its ASCII fallback 'OK'; Glyphs.get('tick') returns "
            'the spelling for the active mode.',
        )

    def quit_ACTION(self) -> None:
        self.app.running = False


class GlyphApp(DemoApp):
    title = 'glyphs'
    win_options: ClassVar[dict[str, object]] = {
        'glyphs': DEMO_GLYPHS,
        'glyphs_probe': DEMO_PROBE,
    }

    def build_screens(self):
        self.main = GlyphScreen(self)
        self.help = GlyphHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        spin = OptionSpinner(stack=self.stack,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> GlyphApp:
    return GlyphApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-k-glyphs')


if __name__ == '__main__':
    main()
