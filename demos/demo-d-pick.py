#!/usr/bin/env python3
"""D — Pick a row.

Owns: abut, context-metadata, decor-rows, pick-mode, pick-range
Base: c-options
Run:  ./demos/run-demo d-pick

Navigation always moved the viewport; pick mode moves a highlight instead and
leaves the viewport tracking it.  Each prime row carries a ``Context`` so the
application can read the picked value back with ``get_picked_context()``.

Rows are kept together by ``abut``: a prime's secondary rows are
``Context(genre='DECOR', abut=-1)``, so scrolling keeps the block on screen
while navigation still stops only on the primary row.  The highlight is always
just the picked row.  ``rank % 3`` decides how many detail rows a prime has
(0, 1 or 2), so the blocks differ in height.  Every five ranks a ``DECOR``
group header shows the group number (``rank // 5``); the headers open the body
and end both navigation runs and the blocks, which is what makes them
boundaries.  Detail rows start under the ``spelled`` column, so they read as
fields of the row above rather than a second, misaligned block.

``c`` toggles a check mark in the left column -- the smallest useful thing to
do with a picked context.  The mark has a column of its own and no title, so
the column header stays aligned with the rows.  The pick range marks the
rank/prime fields of the picked row, not the whole row.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import (
    COLUMN_HEADER,
    DemoApp,
    DemoHelpScreen,
    DemoScreen,
    run_main,
)

from console_window import Context

MAIN_ST = 0
GROUP_SIZE = 5
#: The mark the ``c`` action toggles, in the untitled column on the left.
CHECK_MARK = '\u2713'
#: Width of that column (the mark plus one space), and the rank/prime columns
#: it shifts right -- the pick range is those columns only.
CHECK_COL = 2
PICK_COLUMNS = (CHECK_COL, CHECK_COL + 16)
#: Detail rows start under the ``spelled`` column, so their fields line up with
#: the primary row's third column instead of drifting past the highlight.
DETAIL_INDENT = ' ' * (CHECK_COL + COLUMN_HEADER.index('spelled'))


class PickScreen(DemoScreen):
    title = 'pick-a-row'

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        # A column-range highlight: only the rank/prime columns are marked
        # (the check column stays in the normal attribute, so the mark reads).
        self.set_pick_range(*PICK_COLUMNS)

        # One hyphenated word, so the whole title is the fancy header's bold
        # label; a colon keeps a key from abutting the word it introduces.
        self.add_fancy_header('pick-a-row  [c]heck  [?]:help  [q]uit',
                              mode='Underline')
        # The check column is blank in the header: every row's mark sits under
        # a cell of its own, so the titles keep their columns.
        self.add_header(' ' * CHECK_COL + COLUMN_HEADER, attr=cs.A_BOLD)

        for index, row in enumerate(self.app.rows):
            if index % GROUP_SIZE == 0:
                # DECOR is non-pickable: j/k/arrows step over the header, and
                # it ends the previous group's pick block.
                self.add_body(self.app.group_line(row), attr=cs.A_DIM,
                              context=Context(genre='DECOR'))
            # The pickable row and its value, readable on return.
            self.add_body(self.app.item_line(row),
                          context=Context(genre='item', item=row))
            # abut=-1 keeps each detail attached to the primary row above it:
            # navigation stops only on the primary row, and scrolling keeps the
            # block visible, while only the primary row is highlighted.
            for line in self.app.detail_lines(row):
                self.add_body(line, attr=cs.A_DIM,
                              context=Context(genre='DECOR', abut=-1))

    def check_ACTION(self) -> None:
        """``c``: toggle the mark on the row the pick is on."""
        ctx = self.win.get_picked_context()
        if ctx is not None and ctx.genre == 'item':
            self.app.toggle_check(ctx.item['rank'])


class PickApp(DemoApp):
    title = 'pick-a-row'
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}
    help_paragraphs = (
        'rank % 3 decides how many secondary rows a prime has (0, 1 or 2), so '
        'the blocks differ in height.  The secondary rows abut the primary '
        'row: scrolling keeps the block on screen and j/k still visits only '
        'the primary row, while the highlight is just the picked row.  Detail '
        'rows start under the spelled column.',
        'A DECOR group header shows rank // 5 and opens the body and every '
        'group of five.  Headers are not pickable, so navigation steps over '
        'them; 0 and $ select the first and last pickable row rather than the '
        'first and last line.',
        'c toggles a check mark on the picked row.  The mark has its own left '
        'column with no title, so the column header still lines up with the '
        'rows; the set of checked ranks belongs to the app, not to the '
        'window, and survives every repaint.',
    )

    def __init__(self, backend: object | None = None,
                 singleton: bool = True) -> None:
        # Checked ranks outlive the per-pass rebuild, like the pick position.
        self.checked: set[int] = set()
        super().__init__(backend=backend, singleton=singleton)

    def build_screens(self):
        self.main = PickScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('check', 'c - check the picked row', keys=[ord('c')],
                     genre='action', scope={MAIN_ST},
                     comments='Toggles a check mark in the left column.')
        return spin

    def group_line(self, row: dict) -> str:
        return f'  --- group {row["rank"] // GROUP_SIZE} ---'

    def item_line(self, row: dict) -> str:
        mark = CHECK_MARK if row['rank'] in self.checked else ' '
        return f'{mark} ' + self.body_line(row)

    @staticmethod
    def detail_lines(row: dict) -> tuple[str, ...]:
        """The ``rank % 3`` secondary rows shown under a prime row."""
        lines = (
            f'{DETAIL_INDENT}digits={row["digits"]}  sum={row["digit_sum"]}',
            f'{DETAIL_INDENT}binary={row["binary"]}  '
            f'palindrome={"yes" if row["is_palindrome"] else "no"}',
        )
        return lines[:row['rank'] % 3]

    def toggle_check(self, rank: int) -> None:
        self.checked.symmetric_difference_update({rank})


def build_app(backend: object | None = None,
              singleton: bool = True) -> PickApp:
    return PickApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-d-pick')


if __name__ == '__main__':
    main()
