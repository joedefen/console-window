"""Shared machinery for the lettered demo family.

A, B and C are complete standalone programs.  Every later demo (D-P) imports
this module so its file contains only the feature it teaches; the common app
shape lives here instead of being copied thirteen times.

The kit deliberately contains none of the later features: no pick model, no
search bar, no prompts, no dialogs, no theme picker.  It carries the window and
its options, the four-call loop, the sample table, and the small amount of
stack/spinner glue the later demos share.
"""

from __future__ import annotations

import argparse
import curses as cs
from types import SimpleNamespace
from typing import ClassVar

from PrimeRows import PrimeRows

from console_window import (
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Screen,
    ScreenStack,
    cli,
)

# prompt() only checks the clock between getch() calls, and getch() blocks for
# ConsoleWindow.timeout_ms.  A short timeout keeps the keys responsive.
ConsoleWindow.timeout_ms = 100

COLUMN_HEADER = f'{"rank":>6}  {"prime":>8}  spelled'
ALTER_INTERVAL = 10
HOME_ROWS = (100, 200)


def row_line(row: dict, iteration: int, interval: int = ALTER_INTERVAL) -> str:
    """One table row with its live spelled-value style for this pass."""
    spelled = PrimeRows.altered_spelled(
        row["spelled"], row["rank"], iteration, interval)
    return f'{row["rank"]:>6}  {row["prime"]:>8}  {spelled}'


def make_window_opts(**overrides: object) -> ConsoleWindowOpts:
    """The common window options, with per-demo overrides merged in."""
    options: dict[str, object] = {
        'head_line': True,
        # Ctrl-C arrives as an ordinary key so demos can bind it to quit.
        'ctrl_c_terminates': False,
    }
    options.update(overrides)
    return ConsoleWindowOpts(**options)


class DemoScreen(Screen):
    """The common one-table screen every later demo starts from."""

    title: str | None = None
    hint = ''
    column_header = COLUMN_HEADER
    pick_enabled = False

    def draw_screen(self) -> None:
        self.set_pick_mode(self.pick_enabled)
        self.draw_header()
        self.draw_body()

    def draw_header(self) -> None:
        title = self.title or self.app.title
        self.add_fancy_header(
            f'{title}  pass {self.app.iteration}  {self.hint}[q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )

    def draw_body(self) -> None:
        self.add_header(self.column_header, attr=cs.A_BOLD)
        for row in self.app.visible_rows():
            self.add_body(self.app.body_line(row), context=self.body_context(row))

    def body_context(self, row: dict) -> object | None:
        return None

    def quit_ACTION(self) -> None:
        self.app.running = False


class DemoHelpScreen(BasicHelpScreen):
    """A help screen that keeps the demo's quit action.

    ``BasicHelpScreen`` supplies the body; this subclass only has to keep the
    spinner's built-in ``quit`` action working on a screen that is not a table.
    """

    title = 'HELP'

    def quit_ACTION(self) -> None:
        self.app.running = False


class DemoApp:
    """Common demo app: window, stack, four-call loop, and ``q`` quits."""

    title = 'prime rows'
    row_range = HOME_ROWS
    win_options: ClassVar[dict[str, object]] = {}
    screen_class: type[DemoScreen] = DemoScreen

    def __init__(self, backend: object | None = None,
                 singleton: bool = True) -> None:
        # The spinner's default object: prompt and cycle values are written
        # here, and draw_screen() reads them back on every pass.
        self.opts = SimpleNamespace()
        self.iteration = 0
        self.running = True
        self.rows = list(PrimeRows().generate_rows(*self.row_range))

        self.win = ConsoleWindow(opts=make_window_opts(**self.win_options),
                                 backend=backend, singleton=singleton)
        self.stack = ScreenStack.from_screens(
            self.win, self.opts, self.build_screens())
        self.spin = self.build_spinner()  # pylint: disable=assignment-from-none
        self.win.set_handled_keys(self.handled_keys())
        self.after_build()

    # --- hooks -------------------------------------------------------------

    def build_screens(self) -> list[Screen]:
        return [self.screen_class(self)]

    def build_spinner(self):
        """Return an OptionSpinner, or None for a demo with no options."""
        return None

    def handled_keys(self) -> set[int]:
        keys = {ord('q'), ord('Q'), 0x3}
        if self.spin is not None:
            keys |= set(self.spin.keys)
        return keys

    def after_build(self) -> None:
        """Last constructor step, after the window, stack and spinner exist."""

    # --- data --------------------------------------------------------------

    def visible_rows(self) -> list[dict]:
        return self.rows

    def body_line(self, row: dict) -> str:
        return row_line(row, self.iteration)

    # --- loop --------------------------------------------------------------

    def draw_once(self) -> Screen:
        """Run one documented pass without waiting for a key (used by tests)."""
        screen = self.stack.get_curr_obj()
        screen.clear()
        screen.draw_screen()
        return screen

    def read_key(self) -> int | None:
        """Wait for one key.  A demo may wrap this to forward a temporary key."""
        return self.win.prompt(seconds=0.5)

    def handle_key(self, key: int) -> None:
        # A live in-place prompt owns every key until it is dealt with.
        if self.win.prompt_active:
            self.win.handle_prompt_key(key)
            return
        if self.spin is not None and key in self.spin.keys:
            self.spin.do_key(key, self.win)
            return
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False

    def main_loop(self) -> None:
        try:
            while self.running:
                screen = self.stack.get_curr_obj()
                screen.clear()          # content reset for the new pass
                screen.draw_screen()    # add_header()/add_body() only
                self.win.render()       # paints, doupdate() diffs

                key = self.read_key()
                if key:
                    self.handle_key(key)
                if self.spin is not None:
                    self.stack.perform_actions(self.spin)
                self.iteration += 1
        finally:
            self.win.stop_curses()


def run_main(build_app, prog: str) -> None:
    """The two-line display-argument prelude every demo shares."""
    parser = cli.add_display_arguments(argparse.ArgumentParser(prog=prog))
    args = parser.parse_args()
    cli.apply_display_arguments(args, prog=prog)
    build_app().main_loop()
