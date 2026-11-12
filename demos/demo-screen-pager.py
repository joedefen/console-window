#!/usr/bin/env python3
"""The prime table on Screen and ScreenStack, without OptionSpinner.

Screens own the drawing; the app handles the few keys by hand.  The help
screen starts from BasicHelpScreen, with the navigation and app keys added
before its display notes.
"""

import curses as cs
import sys
from types import SimpleNamespace

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    HeaderLine,
    Screen,
    ScreenStack,
)
from PrimeRows import PrimeRows

MAIN_ST = 0
HELP_ST = 1
SCREEN_NAMES = ('MAIN', 'HELP')
HANDLED_KEYS = {0x3, ord('q'), ord('Q'), ord('?'), 27}

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'


def row_line(row):
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {row["spelled"]}'


class MainScreen(Screen):
    def draw_screen(self):
        win = self.app.win
        win.set_pick_mode(False)

        line = HeaderLine()
        line.text('prime rows 100-200  ')
        line.bracket_key('q').text('uit  ')
        line.bracket_key('?').text(':help')
        win.add_fancy_header(line, mode='Underline', line_attr=cs.A_DIM)

        win.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        for row in self.app.rows:
            win.add_body(row_line(row))


class HelpScreen(BasicHelpScreen):
    show_display_notes = True

    def draw_screen(self):
        win = self.app.win
        win.set_pick_mode(False)

        win.add_body('HELP', attr=cs.A_BOLD | cs.A_UNDERLINE)
        win.add_body('')
        for line in win.nav_help_lines():
            win.add_body(line, attr=cs.A_DIM)
        win.add_body('')
        win.add_body('ESC - back to the table')
        win.add_body('q or Ctrl-C - quit')
        win.add_body('')

        # With no spinner, this adds just the canned display notes.
        super().draw_screen()


class ScreenPagerApp:
    def __init__(self, backend=None, singleton=True):
        self.opts = SimpleNamespace()
        self.rows = list(PrimeRows().generate_rows(100, 200))

        win_opts = ConsoleWindowOpts(
            head_line=True,
            # Ctrl-C arrives as an ordinary key so it can be handled by hand.
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

        self.win.set_handled_keys(HANDLED_KEYS)

    def handle_key(self, key):
        if key in (0x3, ord('q'), ord('Q')):
            self.win.stop_curses()
            sys.exit(0)

        if key == 27 and self.stack.is_curr(HELP_ST):
            self.stack.pop()
        elif key == ord('?') and self.stack.is_curr(MAIN_ST):
            self.stack.push(HELP_ST, self.win.pick_pos)

    def main_loop(self):
        while True:
            screen = self.stack.get_curr_obj()
            screen.draw_screen()
            self.win.render()

            key = self.win.prompt(seconds=0.5)
            if key:
                self.handle_key(key)
            self.win.clear()


def main(backend=None, singleton=True):
    ScreenPagerApp(backend=backend, singleton=singleton).main_loop()


if __name__ == '__main__':
    main()
