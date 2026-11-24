#!/usr/bin/env python3
"""I — Header modes.

Owns: header-tokens, header-modes,
span-styling Base: c-options Run: ./demos/run-demo i-headers

`add_fancy_header()` renders the declared header roles,
and its `mode` decides how they are emphasized: `Off` styles
nothing (the bracket delimiters of `bracket_key()` stay literal),
`Underline` underlines the keys, and `Reverse` reverses them.
`m` cycles the three modes; the header is rebuilt every pass,
so the change is visible immediately.

The table churns once every five seconds
(`PrimeRows.thaw_secs`): the header is the subject here,
and a table restyling under it would pull the eye away from the mode change.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main
from PrimeRows import PrimeRows

from console_window import HeaderLine

# One churn pass every five seconds,
# so the listing holds still while the header is compared across modes.
PrimeRows.thaw_secs = 5.0

# The values `add_fancy_header()` accepts for *mode*, in cycle order.
HEADER_MODES = ('Off', 'Underline', 'Reverse')


class HeaderScreen(DemoScreen):
    title = 'I-headers'
    header_mode = 'Underline'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        # One header line carries every role: the LABEL title,
        # the KEY spans, and plain text.
        # The fancy path strips bracket_key()'s delimiters in every mode but 'Off',
        # where they stay literal.
        line = HeaderLine()
        line.label('I-headers').text('  ')
        line.bracket_key('m').text(f'ode={self.header_mode}  ')
        line.bracket_key('?').text(':help  ')
        line.bracket_key('q').text('uit')
        self.add_fancy_header(line, mode=self.header_mode)

        self.add_header(f'{"rank":>6}  {"prime":>8}  spelled', attr=cs.A_BOLD)
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def cycle_mode_ACTION(self) -> None:
        """`m`: move to the next header mode."""
        index = HEADER_MODES.index(self.header_mode)
        self.header_mode = HEADER_MODES[(index + 1) % len(HEADER_MODES)]


class HeaderApp(DemoApp):
    title = 'I-headers'
    screen_class = HeaderScreen
    help_paragraphs = (
        'The single header row declares every role at once: the title is a '
        'LABEL, the bracketed letters are KEY spans, and the rest is plain '
        'text.  add_fancy_header() keeps those roles and applies the mode.',
        'm cycles the mode through Off, Underline and Reverse.  Off styles '
        'nothing and leaves bracket_key() delimiters literal; Underline and '
        'Reverse differ in how the keys are emphasized.  The table churns '
        'once every five seconds so the header is easy to compare.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('cycle_mode', 'm - cycle the header mode',
                     keys=[ord('m')], genre='action',
                     comments='Off, Underline and Reverse; the header line '
                              'redraws with the chosen style.')
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> HeaderApp:
    return HeaderApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-i-headers')


if __name__ == '__main__':
    main()
