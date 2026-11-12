#!/usr/bin/env python3
"""One Screen plus an OptionSpinner: a live rank range and sort order.

The spinner owns the two things that change while the app runs -- the
``min-max`` rank range and the up/down sort order -- and its help screen shows
both current values.  Each pass rebuilds the table from those options, so an
edited range is visible on the very next frame.

The range prompt carries ``check_ans``, so a malformed range never reaches the
screen: the dialog re-opens on the rejected text and says what it expects.

The data is live, like the basic pager: one row in ALTER_INTERVAL gets a new
quote/case style for its spelled value each cycle, so a still page still moves.

Pitch: a fixed page needs no options.  As soon as the page depends on values
the user edits, reach for OptionSpinner: it binds the keys, runs the prompt,
and renders the current values in one place.
"""

from __future__ import annotations

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
)

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
DEFAULT_RANGE = '100-200'
MAX_RANK = 10_000
ALTER_INTERVAL = 10
RANGE_RE = re.compile(r'^\s*(\d+)\s*-\s*(\d+)\s*$')


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
    def __init__(self, app: SpinnerPagerApp) -> None:
        super().__init__(app)
        self._key = None
        self._rows = []
        self._error = ''

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

        self._load_rows()
        if self._error:
            self.add_body(self._error, attr=cs.A_BOLD)
            self.add_body('range format: {min}-{max}', attr=cs.A_DIM)
            self.add_body(f'0 <= min < max <= {MAX_RANK}', attr=cs.A_DIM)
            return

        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        for row in self._rows:
            self.add_body(row_line(row, self.app.iteration, ALTER_INTERVAL))

    def _load_rows(self) -> None:
        """Rebuild the page only when an option changed (or on the first pass)."""
        key = (str(self.app.opts.range), str(self.app.opts.order))
        if key == self._key:
            return
        self._key = key
        self._rows = []

        parsed = parse_range(self.app.opts.range)
        if parsed is None:
            # The prompt's check_ans rejects bad text, so this only guards a
            # value written behind the spinner's back.
            self._error = f'bad range: {self.app.opts.range!r}'
            return

        self._error = ''
        start, end = parsed
        rows = list(PrimeRows().generate_rows(start, end))
        if self.app.opts.order == 'down':
            rows.reverse()
        self._rows = rows

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
        # The spinner's default object: its prompt and cycle write here, and
        # draw_screen() reads these values back on every pass.
        self.opts = SimpleNamespace(range=DEFAULT_RANGE, order='up')
        self.iteration = 0

        win_opts = ConsoleWindowOpts(
            head_line=True,
            # Ctrl-C arrives as an ordinary key so it can be bound to quit.
            ctrl_c_terminates=False,
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend,
                                 singleton=singleton)

        self.main = MainScreen(self)
        self.help = HelpScreen(self)
        self.stack = ScreenStack.from_screens(self.win, self.opts,
                                              [self.main, self.help])

        self.running = True
        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.add_key('range', 'r - rank range',
                     prompt='Prime ranks (min-max):',
                     check_ans=check_range, keys=[ord('r')])
        spin.add_key('order', 'o - sort order', vals=['up', 'down'],
                     keys=[ord('o')])
        spin.add_key('quit', 'q,CTRL-C - quit',
                     keys={0x3, ord('q'), ord('Q')}, genre='action')
        # Actions infer their screens from which objects define *_ACTION.
        spin.add_key('escape', 'ESC - back', keys=[27], genre='action')
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action')

        self.win.set_handled_keys(spin.keys)

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


def main(backend: object | None = None, singleton: bool = True) -> None:
    SpinnerPagerApp(backend=backend, singleton=singleton).main_loop()


if __name__ == '__main__':
    main()
