#!/usr/bin/env python3
"""Q — The two-cell emoji family.

Owns: emoji-glyphs, mark-fallback, mark-detector, mark-catalog
Base: k-glyphs
Run:  ./demos/run-demo q-marks --ascii

The ``'emoji'`` group exists for the places where a one-cell symbol is too
quiet: a status column, a prompt badge, a row that has to be seen.  Its contract
is width.  Every entry is a single ``EAW=W`` code point, so it is two cells here
and in the terminal, and a variation selector cannot change that; the ASCII
spelling is two cells as well, so ``a`` (or ``--ascii``) leaves the columns where
they were.

Choosing a family is a layout decision, not a preference for text over emoji:
use the emoji when the row needs emphasis and can spare two cells, and the
one-cell status symbols when it cannot.  The verdicts at the bottom are
``find_issues()`` over five samples: an approved emoji, a VS16-promoted base, an
East-Asian Ambiguous shape, an unapproved emoji and a plain one-cell check.
Only the first and the last are quiet.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import Glyphs
from console_window.glyphs import find_issues, glyphs_in_group, set_ascii
from console_window.textwidth import ljust, string_width

NAME_WIDTH = 11
ASCII_WIDTH = 5
VERDICT_WIDTH = 9
CLEAN = 'clean'

SAMPLES = (
    '\u2705 approved mark',
    '\u26a0\ufe0f VS16-promoted',
    '\u25cf East-Asian ambiguous',
    '\U0001f984 no fallback',
    '\u2713 one cell',
)


class MarkScreen(DemoScreen):
    title = 'Q-marks'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        ascii_on = bool(getattr(self.app.opts, 'ascii', False))
        # The switch is process state; writing it every pass keeps the `a` key,
        # `--ascii` and the table from drifting apart.
        set_ascii(ascii_on)
        self.add_fancy_header(
            f'Q-marks  [a]:ascii={"ON" if ascii_on else "off"}  [?]:help  [q]uit',
            mode='Underline', line_attr=cs.A_DIM)
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
        width = self.win.get_pad_width()
        self.add_body(self._divider('find_issues()', width), attr=cs.A_DIM)
        for sample in SAMPLES:
            issues = find_issues(sample)
            verdict = issues[0].kind if issues else CLEAN
            self.add_body(f'{ljust(sample, 26)}  {verdict:<{VERDICT_WIDTH}}')

    @staticmethod
    def _divider(label: str, width: int) -> str:
        """A rule that names what starts below it."""
        rule = Glyphs.get('box_h')
        return f'{label} ' + rule * max(1, width - string_width(label) - 1)


class MarkApp(DemoApp):
    title = 'Q-marks'
    screen_class = MarkScreen
    help_paragraphs = (
        'Approval is a width test, not a taste test. Every emoji in the group is '
        'one code point with East-Asian Width W, so it measures two cells in '
        'this library and in the terminal, and appending a variation selector '
        'cannot change that. The ASCII column is two cells too, which is why '
        '`a` (or --ascii) keeps the table aligned instead of moving it.',
        'find_issues() names the four ways a two-cell mark is unsafe: '
        'VS16-promoted (one or two cells depending on the terminal), a '
        'zero-width joiner, East-Asian Ambiguous (one cell here, two in a '
        'CJK-width terminal), and an unapproved two-cell emoji with no fallback. '
        'Running it over the strings an app draws is the quickest way to catch a '
        'mark before it shifts a row.',
        'A mark is decoration, never the only signal: pair it with A_BOLD or '
        'A_REVERSE, which every terminal draws. When the chosen emoji cannot be '
        'drawn, switch to the two-cell text fallback; if the row can spare only '
        'one cell, use a one-cell status symbol instead. Either choice keeps the '
        'presentation and the width the row was measured for.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('ascii', 'a - ASCII fallbacks',
                     vals=[False, True], keys=[ord('a')],
                     comments='Both spellings are two cells, so the table keeps '
                              'its columns either way.')
        return spin

    def after_build(self) -> None:
        # Start from whatever --ascii or the environment decided; the key cycles
        # from there.
        self.opts.ascii = Glyphs.is_ascii()


def build_app(backend: object | None = None,
              singleton: bool = True) -> MarkApp:
    return MarkApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-q-marks')


if __name__ == '__main__':
    main()
