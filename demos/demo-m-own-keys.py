#!/usr/bin/env python3
"""M — Own the navigation keys.

Owns: taken-nav-keys, spinner-nav-keys, paged-navigation,
nav-help-pruning Base: c-options Run: ./demos/run-demo m-own-keys

LEFT and RIGHT are navigation keys by default, so the spinner would normally reject them.
`ConsoleWindowOpts(taken_nav_keys=[...])` withdraws
them from this window's navigation dispatch;
the window's `opts.nav_keys` (the reduced set) is what the spinner validates against.

The help legend is generated from the same bindings: a taken key is
removed from the navigation map instead of being documented a second time.
LEFT/RIGHT are only reserved (never printed), so this window's legend is unchanged.
Dialogs still edit with the arrow keys,
because their key loop is separate from the paged navigation.
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
from PrimeRows import PrimeRows

# One churn pass every five seconds.  Paging and the header are the lesson here,
# so the table should stay calm while the page is being read.
PrimeRows.thaw_secs = 5.0

MAIN_ST = 0
PAGE_SIZE = 100


class OwnKeysScreen(DemoScreen):
    title = 'M-own-the-navigation-keys'

    def __init__(self, app: OwnKeysApp) -> None:
        super().__init__(app)
        self.page = 0

    @property
    def page_count(self) -> int:
        return max(1, (len(self.app.rows) + PAGE_SIZE - 1) // PAGE_SIZE)

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            'M-own-the-navigation-keys  LEFT:prev RIGHT:next [?]:help [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header('NOTE: LEFT and RIGHT are application keys in this window')
        start = self.page * PAGE_SIZE
        page_rows = self.app.rows[start:start + PAGE_SIZE]
        self.add_header(
            f'{COLUMN_HEADER}{" " * 12}'
            f'Page: {self.page + 1}/{self.page_count} '
            f'[{page_rows[0]["rank"]}-{page_rows[-1]["rank"]}]',
            attr=cs.A_BOLD,
        )
        for row in page_rows:
            self.add_body(row_line(row, self.app.iteration))

    def _go_top(self) -> None:
        """Put the body at its first row when the page under it changes."""
        self.pick_pos = 0
        self.scroll_pos = 0
        self.free_scroll = False

    def prev_page_ACTION(self) -> None:
        page = max(0, self.page - 1)
        if page != self.page:
            self.page = page
            self._go_top()

    def next_page_ACTION(self) -> None:
        page = min(self.page_count - 1, self.page + 1)
        if page != self.page:
            self.page = page
            self._go_top()

class OwnKeysApp(DemoApp):
    title = 'M-own-the-navigation-keys'
    # Five pages of one hundred ranks, so LEFT/RIGHT have somewhere to go.
    row_range = (1, 500)
    win_options: ClassVar[dict[str, object]] = {
        'taken_nav_keys': [cs.KEY_LEFT, cs.KEY_RIGHT],
    }

    def build_screens(self):
        self.main = OwnKeysScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        # The spinner validates against the window's effective navigation set,
        # which omits LEFT/RIGHT because the app has taken them.
        spin = self.new_spinner(nav_keys=self.win.opts.nav_keys)
        spin.add_key('prev_page', 'LEFT - previous page',
                     keys=[cs.KEY_LEFT], genre='action', scope={MAIN_ST})
        spin.add_key('next_page', 'RIGHT - next page',
                     keys=[cs.KEY_RIGHT], genre='action', scope={MAIN_ST})
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> OwnKeysApp:
    return OwnKeysApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-m-own-keys')


if __name__ == '__main__':
    main()
