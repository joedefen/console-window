#!/usr/bin/env python3
"""O — Large bodies and limits.

Owns: large-body, scroll-indicator, max-rows, min-size, redraw-recovery
Base: a-basic
Run:  ./demos/run-demo o-large-bodies

Two thousand rows are added every pass, but the pads stay viewport-sized: the
rows live in the model, so memory and the cost of ``clear()`` do not grow with
the row count.  The scroll indicator appears because the body is longer than
the viewport.

``max_rows`` is the only ceiling (``None`` disables it), and a dropped row is
counted in ``rows_dropped`` instead of crashing the app.  ``min_cols_rows`` is
the hard floor: a terminal smaller than it is reported with
``TerminalTooSmallError`` from a dialog.  ``r`` calls ``render(redraw=True)``,
the full-repaint recovery path.
"""

from __future__ import annotations

import argparse
from typing import ClassVar

from demo_kit import DemoApp, DemoScreen

from console_window import TerminalTooSmallError, cli

LARGE_BODY_ROWS = 2000


class LargeScreen(DemoScreen):
    title = 'large bodies'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'large bodies  rows={len(self.app.rows)}  '
            f'max_rows={self.win.opts.max_rows}  '
            f'dropped={self.win.rows_dropped}  [r]edraw  [q]uit',
            mode='Underline',
        )
        self.add_header(
            f'min size: cols>={self.win.opts.min_cols_rows[0]} '
            f'rows>={self.win.opts.min_cols_rows[1]}'
        )
        self.add_header(f'{"rank":>6}  {"prime":>8}  spelled')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))


class LargeApp(DemoApp):
    title = 'large bodies'
    row_range = (1, LARGE_BODY_ROWS)
    win_options: ClassVar[dict[str, object]] = {
        'max_rows': LARGE_BODY_ROWS + 500,
        'min_cols_rows': (40, 8),
    }

    def build_screens(self):
        return [LargeScreen(self)]

    def handle_key(self, key: int) -> None:
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('r'):
            self.win.render(redraw=True)
            self.win.status('full repaint complete', timeout=1.5)


def build_app(backend: object | None = None,
              singleton: bool = True) -> LargeApp:
    return LargeApp(backend=backend, singleton=singleton)


def main() -> None:
    parser = cli.add_display_arguments(
        argparse.ArgumentParser(prog='demo-o-large-bodies'))
    args = parser.parse_args()
    cli.apply_display_arguments(args, prog='demo-o-large-bodies')
    try:
        build_app().main_loop()
    except TerminalTooSmallError as exc:
        # The app-level answer to a terminal smaller than the dialog floor:
        # report what was required instead of leaving the screen half painted.
        print(f'terminal too small: need at least {exc.required_cols} cols x '
              f'{exc.required_rows} rows')


if __name__ == '__main__':
    main()
