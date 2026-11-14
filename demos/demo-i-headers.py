#!/usr/bin/env python3
"""I — Header composition.

Owns: header-tokens, header-modes, span-styling
Base: c-options
Run:  ./demos/run-demo i-headers

A header can be written in three ways.  ``add_header_line()`` emits explicit
``Span`` roles verbatim, so a ``bracket_key()`` keeps its literal brackets.
``add_fancy_header()`` interprets the mode string and treats ``[x]`` / ``KEY:``
as markup.  A raw list of ``Span`` values gives every role to the renderer
without any parsing at all.

The three header rows here are one multi-row band over the same table.  The
demo has no keys of its own beyond the shared ``?`` and ``q``; the band is the
whole lesson, so the help page carries the prose instead of adding keys.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import HeaderLine, Span


class HeaderScreen(DemoScreen):
    title = 'I-headers'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        # Row 1: an explicit label token plus tokens emitted verbatim (brackets
        # are literal).
        tokens = HeaderLine()
        tokens.label('I-headers').text('  ')
        tokens.bracket_key('q').text('uit  ')
        tokens.bracket_key('j').text('/').bracket_key('k').text(':move  ')
        tokens.bracket_key('?').text(':help')
        self.add_header_line(tokens, mode='Underline')

        # Row 2: the same spelling through the fancy path: brackets are markup,
        # and the mode controls how the roles are emphasized.
        self.add_fancy_header(
            '  [q]uit  [j]/[k]:move  [?]:help',
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
    title = 'I-headers'
    screen_class = HeaderScreen
    help_paragraphs = (
        'Row 1 is a HeaderLine: the brackets are literal text, and the key role '
        'is attached to the token that follows.  Row 2 is the same line through '
        'add_fancy_header(), where "[x]" and "KEY:" are markup parsed by the '
        'window.  Row 3 is a list of Span values: the roles are declared, so '
        'there is no parsing at all.',
        'The three rows are one band over one body.  A header row is written by '
        'the screen on every pass, so the band can change with the data without '
        'any window-side state.',
    )


def build_app(backend: object | None = None,
              singleton: bool = True) -> HeaderApp:
    return HeaderApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-i-headers')


if __name__ == '__main__':
    main()
