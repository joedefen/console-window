#!/usr/bin/env python3
"""Two Screens and a ScreenStack, without OptionSpinner.

ONE shows prime ranks 100-200; TWO shows 300-400.  ``2`` pushes TWO and ESC
pops back to ONE.  Each Screen owns its content and its scroll position, so
returning to ONE lands exactly where you left it.

The data is live, like the basic pager: one row in ALTER_INTERVAL gets a new
quote/case style for its spelled value each cycle, so every pass differs a
little while each screen keeps its own place.

Pitch: one page needs no stack.  The second page does -- and the stack is what
keeps the first page's place without the app copying any state around.
"""

from __future__ import annotations

import curses as cs
from types import SimpleNamespace

from PrimeRows import PrimeRows

from console_window import (
    ConsoleWindow,
    ConsoleWindowOpts,
    Screen,
    ScreenStack,
)

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
ALTER_INTERVAL = 10


def row_line(row: dict, iteration: int, interval: int) -> str:
    spelled = PrimeRows.altered_spelled(
        row["spelled"], row["rank"], iteration, interval)
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {spelled}'


class PrimeTableScreen(Screen):
    """One page of the table; subclasses only choose a name and a range."""

    name = 'TABLE'
    start_rank = 1
    end_rank = 10
    hint = ''

    def __init__(self, app: ScreenPagerApp) -> None:
        super().__init__(app)
        self.rows = list(PrimeRows().generate_rows(self.start_rank,
                                                   self.end_rank))

    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        self.add_fancy_header(
            f'{self.name}  prime ranks {self.start_rank}-{self.end_rank}  '
            f'pass {self.app.iteration}  {self.hint}[q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.rows:
            self.add_body(row_line(row, self.app.iteration, ALTER_INTERVAL))


class OneScreen(PrimeTableScreen):
    name = 'ONE'
    start_rank = 100
    end_rank = 200
    hint = '[2]:TWO  '


class TwoScreen(PrimeTableScreen):
    name = 'TWO'
    start_rank = 300
    end_rank = 400
    hint = 'ESC:ONE  '


class ScreenPagerApp:
    def __init__(self, backend: object | None = None,
                 singleton: bool = True) -> None:
        self.opts = SimpleNamespace()
        self.iteration = 0
        win_opts = ConsoleWindowOpts(
            head_line=True,
            # Ctrl-C arrives as an ordinary key so it can be handled by hand.
            ctrl_c_terminates=False,
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend,
                                 singleton=singleton)

        self.one = OneScreen(self)
        self.two = TwoScreen(self)
        # Screen objects in order: ONE is home (0), TWO is 1.  Names come from
        # the screens, so there is no parallel names tuple to keep in sync.
        self.stack = ScreenStack.from_screens(self.win, self.opts,
                                              [self.one, self.two])

        self.win.set_handled_keys({0x3, ord('q'), ord('Q'), ord('2'), 27})
        self.running = True

    def handle_key(self, key: int) -> None:
        if key in (0x3, ord('q'), ord('Q')):
            self.running = False
        elif key == ord('2') and self.stack.is_curr('ONE'):
            # push() takes the Screen itself, so the app never handles numbers.
            self.stack.push(self.two, self.win.pick_pos)
        elif key == 27 and self.stack.is_curr('TWO'):
            self.stack.pop()

    def main_loop(self) -> None:
        try:
            while self.running:
                screen = self.stack.get_curr_obj()
                screen.clear()          # content reset for the new pass
                screen.draw_screen()    # add_header()/add_body() only
                self.win.render()       # paints, doupdate() diffs

                key = self.win.prompt(seconds=0.5)
                if key:
                    self.handle_key(key)
                self.iteration += 1
        finally:
            self.win.stop_curses()


def main(backend: object | None = None, singleton: bool = True) -> None:
    ScreenPagerApp(backend=backend, singleton=singleton).main_loop()


if __name__ == '__main__':
    main()
