#!/usr/bin/env python3
"""The same static prime table, driven through Screen and ScreenStack.

This is the Screen-paradigm counterpart to demo-basic-pager.py.  It still
draws only one table, but navigation, the help screen and quit are handled by
ScreenStack and OptionSpinner rather than by a hand-written key loop.
"""

import curses as cs
import sys
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

MAIN_ST = 0
HELP_ST = 1
SCREEN_NAMES = ('MAIN', 'HELP')

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'


def row_line(row):
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {row["spelled"]}'


def quit_app(app):
    app.win.stop_curses()
    sys.exit(0)


class MainScreen(Screen):
    def draw_screen(self):
        self.set_pick_mode(False)

        line = HeaderLine()
        line.text('prime rows 100-200  ')
        line.bracket_key('q').text('uit  ')
        line.bracket_key('?').text(':help')
        self.add_fancy_header(line, mode='Underline', line_attr=cs.A_DIM)

        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        for row in self.app.rows:
            self.add_body(row_line(row))

    def quit_ACTION(self):
        quit_app(self.app)

    def help_screen_ACTION(self):
        # The parent's own pick position: per-screen state, no window copy.
        self.app.stack.push(HELP_ST, self.pick_pos)


class HelpScreen(BasicHelpScreen):

    def quit_ACTION(self):
        quit_app(self.app)

    def escape_ACTION(self):
        self.app.stack.pop()


class ScreenPagerApp:
    def __init__(self, backend=None, singleton=True):
        self.opts = SimpleNamespace()
        self.rows = list(PrimeRows().generate_rows(100, 200))

        win_opts = ConsoleWindowOpts(
            head_line=True,
            # Ctrl-C arrives as an ordinary key so it can be bound to quit.
            ctrl_c_terminates=False,
        )
        self.win = ConsoleWindow(opts=win_opts, backend=backend,
                                 singleton=singleton)

        self.screens = {
            MAIN_ST: MainScreen(self),
            HELP_ST: HelpScreen(self),
        }
        self.stack = ScreenStack(self.win, self.opts, SCREEN_NAMES,
                                 self.screens)

        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.add_key('quit', 'q,CTRL-C - quit',
                     keys={0x3, ord('q'), ord('Q')}, genre='action')
        spin.add_key('escape', 'ESC - back', keys=[27], genre='action',
                     scope={HELP_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})

        self.win.set_handled_keys(spin.keys)

    def handle_key(self, key):
        if key in self.spin.keys:
            self.spin.do_key(key, self.win)

    def main_loop(self):
        while True:
            screen = self.stack.get_curr_obj()
            screen.clear()          # content reset for the new pass
            screen.draw_screen()    # add_header()/add_body() only
            self.win.render()       # paints, doupdate() diffs

            key = self.win.prompt(seconds=0.5)
            if key:
                self.handle_key(key)
            self.stack.perform_actions(self.spin)


def main(backend=None, singleton=True):
    ScreenPagerApp(backend=backend, singleton=singleton).main_loop()


if __name__ == '__main__':
    main()
