#!/usr/bin/env python3
"""Bare-minimum console-window app: one scrollable table that changes a little.

One Screen, no ScreenStack, no OptionSpinner and no help screen.  It rebuilds
the page every pass -- clear(), add_*(), render() -- then waits for a key.
Navigation keys scroll the body; ``q`` (or Ctrl-C) exits.

One row in ALTER_INTERVAL gets a new quote/case style for its spelled value
each cycle, so successive passes are visibly different.  The style is derived
from a hash, so it persists between passes without any app state.
"""

import curses as cs
from types import SimpleNamespace

from PrimeRows import PrimeRows

from console_window import ConsoleWindow, ConsoleWindowOpts, Screen

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
ALTER_INTERVAL = 10


def row_line(row: dict, iteration: int, interval: int) -> str:
    spelled = PrimeRows.altered_spelled(
        row["spelled"], row["rank"], iteration, interval)
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {spelled}'


class PagerScreen(Screen):
    """The whole app: one table, no help page, no spinner."""

    iteration = 0

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self._draw_table()

    def _draw_table(self) -> None:
        # Fancy header.  Navigation keys scroll the body rows.
        self.add_fancy_header(
            f'prime rows 100-200 | q: quit | pass {self.iteration}',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.app.rows:
            self.add_body(row_line(row, self.iteration, ALTER_INTERVAL))


def main() -> None:
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
            screen.iteration += 1
    except KeyboardInterrupt:
        pass
    finally:
        win.stop_curses()


if __name__ == '__main__':
    main()
