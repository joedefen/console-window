#!/usr/bin/env python3
"""Bare-minimum console-window app: a static table and a help page.

One Screen, no ScreenStack and no OptionSpinner.  It rebuilds the page every
pass -- clear(), add_*(), render() -- then waits for a key.  ``?`` shows the
help page, ESC returns, and ``q`` (or Ctrl-C) exits.
"""

import curses as cs
import textwrap
from types import SimpleNamespace

from PrimeRows import PrimeRows

from console_window import ConsoleWindow, ConsoleWindowOpts, Screen
from console_window import help as help_text

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'


def row_line(row):
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {row["spelled"]}'


class PagerScreen(Screen):
    """The whole app: a table and a hand-written help page behind one flag."""

    help_mode = False

    def draw_screen(self):
        self.set_pick_mode(False)
        if self.help_mode:
            self._draw_table_help()
        else:
            self._draw_table()

    def _draw_table(self):
        # Fancy header: [q]uit and ?:help.
        self.add_fancy_header(
            'prime rows 100-200 | [q]uit [?]:help',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.app.rows:
            self.add_body(row_line(row))

    def _draw_table_help(self):
        self.add_body('HELP', attr=cs.A_BOLD | cs.A_UNDERLINE)
        self.add_body('')

        for line in self.win.nav_help_lines():
            self.add_body(line, attr=cs.A_DIM)
        self.add_body('')

        self.add_body('? - show this help')
        self.add_body('ESC - back to the table')
        self.add_body('q or Ctrl-C - quit')
        self.add_body('')

        width = max(self.win.cols - 8, 20)
        for line in textwrap.wrap(help_text.glyph_paragraph(self.win), width=width):
            self.add_body(line, attr=cs.A_DIM)


def main():
    # head_line=True draws the rule between the header rows and the body.
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_line=True))
    app = SimpleNamespace(win=win,
                          rows=list(PrimeRows().generate_rows(100, 200)))
    screen = PagerScreen(app)
    try:
        while True:
            screen.clear()          # content reset for the new pass
            screen.draw_screen()    # add_header()/add_body() only
            win.render()            # paints, doupdate() diffs

            key = win.prompt(seconds=0.5)
            if key in (ord('q'), ord('Q')):
                break
            if screen.help_mode:
                if key == 27:  # ESC returns to the table
                    screen.help_mode = False
            elif key == ord('?'):
                screen.help_mode = True
    except KeyboardInterrupt:
        pass
    finally:
        win.stop_curses()


if __name__ == '__main__':
    main()
