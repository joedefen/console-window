#!/usr/bin/env python3
"""I — Header composition.

Owns: header-tokens, header-modes, span-styling
Base: a-basic
Run:  ./demos/run-demo i-headers

A header can be written in three ways.  ``add_header_line()`` emits explicit
``Span`` roles verbatim, so a ``bracket_key()`` keeps its literal brackets.
``add_fancy_header()`` interprets the mode string and treats ``[x]`` / ``KEY:``
as markup.  A raw list of ``Span`` values gives every role to the renderer
without any parsing at all.

The three header rows here are one multi-row band over the same table.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import HeaderLine, Span


class HeaderScreen(DemoScreen):
    title = 'headers'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        # Row 1: explicit tokens, emitted verbatim (brackets are literal).
        tokens = HeaderLine()
        tokens.text('  ').bracket_key('q').text('uit  ')
        tokens.bracket_key('j').text('/').bracket_key('k').text(' move')
        self.add_header_line(tokens, mode='Underline')

        # Row 2: the same spelling through the fancy path: brackets are markup,
        # and the mode controls how the roles are emphasized.
        self.add_fancy_header(
            '  [q]uit  [j]/[k] move  SPC:mark',
            mode='Underline',
            line_attr=cs.A_DIM,
        )

        # Row 3: explicit Span roles, no parsing and no markup rules.
        spans = [
            Span('  LABEL', 'label'),
            Span('  '),
            Span('KEY', 'key'),
            Span('  plain text', 'plain'),
        ]
        self.add_header_line(spans, mode='Underline')

        self.add_header(f'{"rank":>6}  {"prime":>8}  spelled', attr=cs.A_BOLD)
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))


class HeaderApp(DemoApp):
    title = 'headers'

    def build_screens(self):
        return [HeaderScreen(self)]


def build_app(backend: object | None = None,
              singleton: bool = True) -> HeaderApp:
    return HeaderApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-i-headers')


if __name__ == '__main__':
    main()
