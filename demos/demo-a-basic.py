#!/usr/bin/env python3
"""A — Basic pager.

Owns: app-loop, header-band, navigation, live-data
Base: —
Run:  ./demos/run-demo a-basic

One Screen, no ScreenStack, no OptionSpinner and no help screen.  It rebuilds
the page every pass -- clear(), add_*(), render() -- then waits for a key.
Navigation keys scroll the body; ``q`` (or Ctrl-C) exits.

One row in ALTER_INTERVAL gets a new quote/case style for its spelled value
each cycle, so successive passes are visibly different.  The style is derived
from a hash, so it persists between passes without any app state.
"""

from __future__ import annotations

import argparse
import curses as cs

from PrimeRows import PrimeRows

from console_window import ConsoleWindow, ConsoleWindowOpts, Screen, cli

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
ALTER_INTERVAL = 10
QUIT_KEYS = (ord('q'), ord('Q'), 0x3)


def row_line(row: dict, iteration: int, interval: int) -> str:
    spelled = PrimeRows.altered_spelled(
        row["spelled"], row["rank"], iteration, interval)
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {spelled}'


class PagerScreen(Screen):
    """The whole app: one table, no help page, no spinner."""

    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        # The header band: a title line, then the column header.  head_line=True
        # draws the rule between the header rows and the body.
        self.add_fancy_header(
            f'prime rows 100-200 | q: quit | pass {self.app.iteration}',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.app.rows:
            self.add_body(row_line(row, self.app.iteration, ALTER_INTERVAL))


class BasicApp:
    def __init__(self, backend: object | None = None,
                 singleton: bool = True) -> None:
        self.rows = list(PrimeRows().generate_rows(100, 200))
        self.iteration = 0
        self.running = True
        self.win = ConsoleWindow(
            opts=ConsoleWindowOpts(head_line=True, ctrl_c_terminates=False),
            backend=backend,
            singleton=singleton,
        )
        self.screen = PagerScreen(self)
        self.win.set_handled_keys(QUIT_KEYS)

    def draw_once(self) -> PagerScreen:
        self.screen.clear()
        self.screen.draw_screen()
        return self.screen

    def handle_key(self, key: int) -> None:
        if key in QUIT_KEYS:
            self.running = False

    def main_loop(self) -> None:
        try:
            while self.running:
                self.screen.clear()          # content reset for the new pass
                self.screen.draw_screen()    # add_header()/add_body() only
                self.win.render()            # paints, doupdate() diffs

                key = self.win.prompt(seconds=0.5)
                if key:
                    self.handle_key(key)
                self.iteration += 1
        finally:
            self.win.stop_curses()


def build_app(backend: object | None = None,
              singleton: bool = True) -> BasicApp:
    return BasicApp(backend=backend, singleton=singleton)


def main() -> None:
    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='demo-a-basic'))
    args = parser.parse_args()
    cli.apply_display_arguments(args, prog='demo-a-basic')
    build_app().main_loop()


if __name__ == '__main__':
    main()
