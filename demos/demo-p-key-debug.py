#!/usr/bin/env python3
"""P — Keys and widths.

Owns: demo-mode, textwidth, wide-characters
Base: c-options
Run:  ./demos/run-demo p-key-debug

``K`` cycles ``set_demo_mode()`` (uppercase because lowercase ``k`` is a
navigation key).  While it is on, the header shows the last key the terminal
sent at its right edge; the badge fades after two seconds while the mode stays
on, so a stale key never camps in the corner.

The body rows measure their labels with ``textwidth.string_width()`` and lay
them out with ``ljust()``/``truncate()``, so CJK (two cells), a Wide emoji and
combining marks line up in the same columns as ASCII.  The last column prefixes
five ``-`` cells to each sample and keeps six, so the cut is visible: a wide
glyph that would straddle the boundary is dropped whole instead of being split.

The emoji sample is East-Asian Width ``W`` on purpose.  A narrow base promoted
by VS16 (``⚠️``) is two cells only on terminals that honor emoji presentation,
so it is explained in the help page instead of breaking the table on terminals
that draw it as one cell.

``c`` cycles the column-header case (lower, Title, UPPER).  It is the key with a
lasting mark -- the badge fades, the chosen case does not -- which is how the
demo shows that a key was understood without leaving demo mode on.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import textwidth
from console_window.glyphs import get

SAMPLES = (
    ('ascii', 'plain ascii'),
    ('cjk', '漢字かな'),
    # A Wide (EAW=W) emoji: every width model agrees it is two cells.  A
    # VS16-promoted narrow glyph is not used here; see the help paragraph.
    ('emoji', '🌍 ✓'),
    ('combining', 'e\u0301'),
)
LABEL_WIDTH = 10
WIDTH_COLUMN = 5
SAMPLE_WIDTH = 13
TRUNC_WIDTH = 6
TRUNC_PREFIX = '-----'

#: The case styles ``c`` cycles, keyed by the value the spinner stores.  The
#: column-header row is rebuilt through one of these every pass, so the chosen
#: style is demo state, not a one-off rewording of the literal.
CASE_STYLES = {
    'lower': str.lower,
    'Title': str.title,
    'UPPER': str.upper,
}


class WidthScreen(DemoScreen):
    title = 'P-keys-and-widths'

    @property
    def case(self) -> str:
        return getattr(self.app.opts, 'case', 'lower')

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        keys_on = bool(getattr(self.app.opts, 'keys', False))
        # The spinner owns the setting; the window owns the badge.  Writing it
        # every pass keeps the two from drifting when the help page changes it.
        self.win.set_demo_mode(keys_on)
        self.add_fancy_header(
            f'P-keys-and-widths  [K]:keys={"ON" if keys_on else "off"}  '
            f'[c]:case={self.case}  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(self._column_header(), attr=cs.A_BOLD)
        for label, sample in SAMPLES:
            self.add_body(self._sample_line(label, sample))
        # The emoji group is the one family the library draws at two cells in
        # both modes, so it belongs in a width table: get() is the emoji here
        # and the two-cell ASCII fallback under --ascii.
        self.add_body(self._sample_line(
            'marks', f'{get("ok")} {get("attention")}'))

    def _column_header(self) -> str:
        """The table heading, styled by the current ``c`` value.

        The framing pipes are part of the header, so the heading labels start
        on the same cells as the body columns; leaving them out is what made
        the data look one column short.
        """
        style = CASE_STYLES.get(self.case, str.lower)
        return (
            f'{style("sample"):<{LABEL_WIDTH}} '
            f'{style("width"):>{WIDTH_COLUMN}}  '
            f'|{style("cell-accurate"):<{SAMPLE_WIDTH}}|  '
            f'|{style("trunc6"):<{TRUNC_WIDTH}}|'
        )

    @staticmethod
    def _sample_line(label: str, sample: str) -> str:
        """One measured row: width, the padded cells, and a visible truncation."""
        width = textwidth.string_width(sample)
        cells = textwidth.ljust(sample, SAMPLE_WIDTH)
        cut = textwidth.ljust(
            textwidth.truncate(TRUNC_PREFIX + sample, TRUNC_WIDTH), TRUNC_WIDTH)
        return (
            f'{textwidth.ljust(label, LABEL_WIDTH)} '
            f'{textwidth.rjust(str(width), WIDTH_COLUMN)}  '
            f'|{cells}|  |{cut}|'
        )


class WidthApp(DemoApp):
    title = 'P-keys-and-widths'
    screen_class = WidthScreen
    help_paragraphs = (
        'K turns the key indicator on and off.  While it is on, the header '
        'prints the last key the terminal sent at its right edge, which is the '
        'quickest way to find out what a key really sends.  The badge fades '
        'after two seconds; the mode stays on, so the next key appears there.',
        'The table measures every sample with textwidth.string_width() and lays '
        'the cells out with ljust()/truncate(), so CJK (two cells), a Wide '
        'emoji and combining marks line up in the same columns as ASCII.  The '
        'trunc6 column prefixes five "-" cells and keeps six, so the cut lands '
        'on the next glyph; a wide one is dropped whole rather than split '
        'across the boundary.',
        'A narrow glyph promoted by VS16 (U+26A0 WARNING SIGN, U+2714 HEAVY '
        'CHECK MARK) is deliberately not in the table: the selector doubles it '
        'on terminals that honor emoji presentation and is ignored on terminals '
        'that do not, so that row could not line up everywhere.  textwidth '
        'follows the emoji-presentation rule; a Wide emoji satisfies both '
        'rules.',
        'c cycles the column-header case through lower, Title and UPPER.  It is '
        'the lasting key: the badge fades, but the header keeps the case you '
        'chose, so the screen shows a key was handled while demo mode is off.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('keys', 'K - show the last key',
                     vals=[False, True], keys=[ord('K')],
                     comments='ON badges the last key the terminal sent at the '
                              "header's right edge for two seconds; off is the "
                              'default.')
        spin.add_key('case', 'c - column-header case',
                     vals=list(CASE_STYLES), keys=[ord('c')],
                     comments='Cycles the sample row heading from lower through '
                              'Title to UPPER.')
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> WidthApp:
    return WidthApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-p-key-debug')


if __name__ == '__main__':
    main()
