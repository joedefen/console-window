#!/usr/bin/env python3
"""Bare-minimum console-window app: a static table and a help screen.

No Screen, ScreenStack or OptionSpinner.  It draws the same page every frame,
then waits for a key.  ``?`` shows the help page, ESC returns, and ``q`` (or
Ctrl-C) exits.
"""

import curses as cs
import textwrap

from console_window import ConsoleWindow, ConsoleWindowOpts
from console_window import help as help_text
from PrimeRows import PrimeRows

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'


def row_line(row):
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {row["spelled"]}'


def draw_table(win, rows):
    win.set_pick_mode(False)

    # Fancy header: [q]uit and ?:help.
    win.add_fancy_header(
        'prime rows 100-200 | [q]uit [?]:help',
        mode='Underline',
        line_attr=cs.A_DIM,
    )
    win.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

    for row in rows:
        win.add_body(row_line(row))


def draw_help(win):
    win.set_pick_mode(False)
    win.add_body('HELP', attr=cs.A_BOLD | cs.A_UNDERLINE)
    win.add_body('')

    for line in win.nav_help_lines():
        win.add_body(line, attr=cs.A_DIM)
    win.add_body('')

    win.add_body('? - show this help')
    win.add_body('ESC - back to the table')
    win.add_body('q or Ctrl-C - quit')
    win.add_body('')

    width = max(win.cols - 8, 20)
    for line in textwrap.wrap(help_text.glyph_paragraph(win), width=width):
        win.add_body(line, attr=cs.A_DIM)


def main():
    rows = list(PrimeRows().generate_rows(100, 200))
    help_mode = False

    # head_line=True draws the rule between the header rows and the body.
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_line=True))
    try:
        while True:
            win.clear()

            if help_mode:
                draw_help(win)
            else:
                draw_table(win, rows)

            win.render()

            key = win.prompt(seconds=0.5)
            if key in (ord('q'), ord('Q')):
                break
            if help_mode:
                if key == 27:  # ESC returns to the table
                    help_mode = False
            elif key == ord('?'):
                help_mode = True
    except KeyboardInterrupt:
        pass
    finally:
        win.stop_curses()


if __name__ == '__main__':
    main()
