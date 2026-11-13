#!/usr/bin/env python3
"""D — Pick a row.

Owns: pick-mode, context-metadata, decor-rows, pick-size, abut, pick-range
Base: c-options
Run:  ./demos/run-demo d-pick

Navigation always moved the viewport; pick mode moves a highlight instead and
leaves the viewport tracking it.  Each prime row carries a ``Context`` so the
application can read the picked value back with ``get_picked_context()``.

The detail row under each item has ``abut=-1``: it is part of the item's block,
so the pick jumps over it and the pair scrolls together.  The DECOR separators
are skipped by navigation for the same reason.  ``p`` cycles the number of
rows a single pick covers, and the column-range highlight shows the picked
columns rather than the whole row.
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

from console_window import Context, OptionSpinner

MAIN_ST = 0
PICK_COLUMNS = (0, 22)


class PickScreen(DemoScreen):
    title = 'pick a row'
    pick_enabled = True

    def draw_screen(self) -> None:
        # The pick size is one of the option values, so the spinner's cycle
        # changes both the highlight and what the next j/k moves.
        self.set_pick_mode(True, self.app.opts.pick_size)
        # A column-range highlight: only the rank/prime columns are marked.
        self.set_pick_range(*PICK_COLUMNS)

        self.add_fancy_header(
            f'pick a row  size={self.app.opts.pick_size}  '
            f'pass {self.app.iteration}  [p]size  [?]help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for index, row in enumerate(self.app.rows):
            if index and index % 5 == 0:
                # DECOR is non-pickable: j/k/arrows step over the separator.
                self.add_body('  --- group ---', attr=cs.A_DIM,
                              context=Context(genre='DECOR'))
            # The pickable row and its value, readable on return.
            self.add_body(row_line(row, self.app.iteration),
                          context=Context(genre='item', item=row))
            # abut=-1 makes this a non-pickable detail row attached to the
            # item above it; the two move as one block.
            self.add_body(
                f'      digits={row["digits"]} sum={row["digit_sum"]} '
                f'binary={row["binary"]}',
                attr=cs.A_DIM,
                context=Context(genre='DECOR', abut=-1),
            )

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class PickApp(DemoApp):
    title = 'pick a row'
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}

    def build_screens(self):
        self.main = PickScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        spin = OptionSpinner(stack=self.stack,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        spin.add_key('pick_size', 'p - rows per pick', vals=[1, 2, 3],
                     keys=[ord('p')], scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> PickApp:
    return PickApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-d-pick')


if __name__ == '__main__':
    main()
