#!/usr/bin/env python3
"""C — Options.

Owns: spinner-options, validated-prompt, option-scope, help-screen,
      action-dispatch
Base: b-stack
Run:  ./demos/run-demo c-options

One Screen plus an OptionSpinner: a live rank range and sort order.  The
spinner owns the two things that change while the app runs, and its help screen
shows the values that are in scope there.  The range prompt carries
``check_ans``, so a malformed range never reaches the screen: the dialog
re-opens on the rejected text and says what it expects.

Pitch: a fixed page needs no options.  As soon as the page depends on values
the user edits, reach for OptionSpinner: it binds the keys, runs the prompt,
and renders the current values in one place.
"""

from __future__ import annotations

import argparse
import curses as cs
import re
from types import SimpleNamespace

from PrimeRows import PrimeRows

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    HeaderLine,
    OptionSpinner,
    Screen,
    ScreenStack,
    cli,
)

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
DEFAULT_RANGE = '100-200'
MAX_RANK = 10_000
ALTER_INTERVAL = 10
RANGE_RE = re.compile(r'^\s*(\d+)\s*-\s*(\d+)\s*$')

MAIN_ST = 0
HELP_ST = 1


def row_line(row: dict, iteration: int, interval: int) -> str:
    spelled = PrimeRows.altered_spelled(
        row["spelled"], row["rank"], iteration, interval)
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {spelled}'


def parse_range(text: str) -> tuple[int, int] | None:
    """Return ``(start_rank, end_rank)``, or None when *text* is bad input.

    The accepted form is ``{min}-{max}`` with ``0 <= min < max <= MAX_RANK``.
    Rank 0 does not exist, so a minimum of 0 starts at rank 1.
    """
    match = RANGE_RE.match(str(text))
    if not match:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    if not 0 <= low < high <= MAX_RANK:
        return None
    return max(low, 1), high


def check_range(text: str) -> str | None:
    """``check_ans`` for the range prompt: None when it parses, else the rule."""
    if parse_range(text) is not None:
        return None
    return f'want {{min}}-{{max}}, 0 <= min < max <= {MAX_RANK}'


class MainScreen(Screen):
    def draw_screen(self) -> None:
        self.set_pick_mode(False)

        line = HeaderLine()
        line.text(f'{self.app.opts.range} {self.app.opts.order}  '
                  f'pass {self.app.iteration}  ')
        line.bracket_key('r').text('ange  ')
        line.bracket_key('o').text('rder  ')
        line.bracket_key('?').text(':help  ')
        line.bracket_key('q').text('uit')
        self.add_fancy_header(line, mode='Underline', line_attr=cs.A_DIM)

        parsed = parse_range(self.app.opts.range)
        if parsed is None:
            self.add_body(f'bad range: {self.app.opts.range!r}',
                          attr=cs.A_BOLD)
            return
        start, end = parsed
        rows = list(PrimeRows().generate_rows(start, end))
        if self.app.opts.order == 'down':
            rows.reverse()

        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        for row in rows:
            self.add_body(row_line(row, self.app.iteration, ALTER_INTERVAL))

    def quit_ACTION(self) -> None:
        self.app.running = False

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class HelpScreen(BasicHelpScreen):
    def quit_ACTION(self) -> None:
        self.app.running = False

    def escape_ACTION(self) -> None:
        self.app.stack.pop()


class SpinnerPagerApp:
    def __init__(self, backend: object | None = None,
                 singleton: bool = True) -> None:
        self.opts = SimpleNamespace(range=DEFAULT_RANGE, order='up')
        self.iteration = 0
        self.running = True

        win_opts = ConsoleWindowOpts(head_line=True, ctrl_c_terminates=False)
        self.win = ConsoleWindow(opts=win_opts, backend=backend,
                                 singleton=singleton)

        self.main = MainScreen(self)
        self.help = HelpScreen(self)
        self.stack = ScreenStack.from_screens(self.win, self.opts,
                                              [self.main, self.help])

        spin = self.spin = OptionSpinner(
            stack=self.stack, quit_keys=(ord('q'), ord('Q'), 0x3))

        # ``range`` is global, so HELP lists it.  ``order`` is scoped to MAIN,
        # so HELP deliberately does not; that is the scope lesson.
        spin.add_key('range', 'r - rank range',
                     prompt='Prime ranks (min-max):',
                     check_ans=check_range, keys=[ord('r')])
        spin.add_key('order', 'o - sort order', vals=['up', 'down'],
                     keys=[ord('o')], scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})

        self.win.set_handled_keys(spin.keys)

    def draw_once(self) -> Screen:
        screen = self.stack.get_curr_obj()
        screen.clear()
        screen.draw_screen()
        return screen

    def handle_key(self, key: int) -> None:
        if key in self.spin.keys:
            self.spin.do_key(key, self.win)

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
                self.stack.perform_actions(self.spin)
                self.iteration += 1
        finally:
            self.win.stop_curses()


def build_app(backend: object | None = None,
              singleton: bool = True) -> SpinnerPagerApp:
    return SpinnerPagerApp(backend=backend, singleton=singleton)


def main() -> None:
    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='demo-c-options'))
    args = parser.parse_args()
    cli.apply_display_arguments(args, prog='demo-c-options')
    build_app().main_loop()


if __name__ == '__main__':
    main()
