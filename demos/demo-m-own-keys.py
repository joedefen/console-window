#!/usr/bin/env python3
"""M — Own the navigation keys.

Owns: taken-nav-keys, spinner-nav-keys, paged-navigation, help-labels
Base: c-options
Run:  ./demos/run-demo m-own-keys

LEFT and RIGHT are navigation keys by default, so the spinner would normally
reject them.  ``ConsoleWindowOpts(taken_nav_keys={...})`` withdraws them from
this window's navigation dispatch and gives them labels; the window's
``opts.nav_keys`` (the reduced set) is what the spinner validates against.

The help legend is generated from the same bindings: it shows the
application's labels for LEFT/RIGHT instead of the reserved arrow names.
Dialogs still edit with the arrow keys, because their key loop is separate from
the paged navigation.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import (
    COLUMN_HEADER,
    DemoApp,
    DemoHelpScreen,
    DemoScreen,
    row_line,
    run_main,
)

from console_window import OptionSpinner

MAIN_ST = 0
PAGE_SIZE = 25


class OwnKeysScreen(DemoScreen):
    title = 'own the navigation keys'

    def __init__(self, app: OwnKeysApp) -> None:
        super().__init__(app)
        self.page = 0

    @property
    def page_count(self) -> int:
        return max(1, (len(self.app.rows) + PAGE_SIZE - 1) // PAGE_SIZE)

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'own the navigation keys  page {self.page + 1}/{self.page_count}  '
            f'pass {self.app.iteration}  '
            f'LEFT:prev RIGHT:next [?]help [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header('LEFT and RIGHT are application keys in this window')
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        start = self.page * PAGE_SIZE
        for row in self.app.rows[start:start + PAGE_SIZE]:
            self.add_body(row_line(row, self.app.iteration))

    def prev_page_ACTION(self) -> None:
        self.page = max(0, self.page - 1)
        self.win.status(f'page {self.page + 1}/{self.page_count}',
                        timeout=1.0)

    def next_page_ACTION(self) -> None:
        self.page = min(self.page_count - 1, self.page + 1)
        self.win.status(f'page {self.page + 1}/{self.page_count}',
                        timeout=1.0)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class OwnKeysApp(DemoApp):
    title = 'own the navigation keys'
    win_options: ClassVar[dict[str, object]] = {
        'taken_nav_keys': {
            cs.KEY_LEFT: 'prev page',
            cs.KEY_RIGHT: 'next page',
        },
    }

    def build_screens(self):
        self.main = OwnKeysScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        # The spinner validates against the window's effective navigation set,
        # which no longer contains LEFT/RIGHT.
        spin = OptionSpinner(stack=self.stack,
                             nav_keys=self.win.opts.nav_keys,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        spin.add_key('prev_page', 'LEFT - previous page',
                     keys=[cs.KEY_LEFT], genre='action', scope={MAIN_ST})
        spin.add_key('next_page', 'RIGHT - next page',
                     keys=[cs.KEY_RIGHT], genre='action', scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> OwnKeysApp:
    return OwnKeysApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-m-own-keys')


if __name__ == '__main__':
    main()
