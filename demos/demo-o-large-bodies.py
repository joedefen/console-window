#!/usr/bin/env python3
"""O — Large bodies and limits.

Owns: large-body, scroll-indicator, max-rows, min-size,
redraw-recovery Base: c-options Run: ./demos/run-demo o-large-bodies

The whole table is rebuilt every pass,
but the pads stay viewport-sized: the rows live in the model,
so memory and the cost of `clear()` do not grow with the row count.
The scroll indicator appears because the body is longer than the viewport.

`+` and `-` grow and shrink the table while it runs (509 rows added, 251 removed),
and each row shows every `PrimeRows` field except the palindrome flag -- rank, prime,
digits, digit sum, binary, mod 10, gap and spelled
-- so the body is a record, not just a number list.

`max_rows` is the only ceiling (10,000 here; `None` disables it),
and a dropped row is counted in `rows_dropped` instead of crashing the app.
The library's drop warning goes to stderr, which would corrupt the curses screen,
so this demo captures it and shows one alert per run instead;
the alert waits for ENTER before the table is painted again.

`min_cols_rows` is the hard floor, but the one-time fit raises it after the first frame
to fit the widest header (capped at 60 columns).
The second header line prints the floor actually in force,
which is why it settles at 60 rather than the configured 40.
`r` calls `render(redraw=True)`, the full-repaint recovery path.

`PrimeRows.thaw_secs` holds the spelled column still for ten seconds between churn passes,
so the table is readable while rows are added and removed.
"""

from __future__ import annotations

import argparse
import curses as cs
import warnings
from typing import ClassVar

from demo_kit import DemoApp, DemoScreen
from PrimeRows import PrimeRows

from console_window import TerminalTooSmallError, cli

# One churn pass every ten seconds: the table is being grown and shrunk here,
# so the restyling should not compete with the row count.
PrimeRows.thaw_secs = 10.0

# Where the body starts; + and - move it while the demo runs.
START_ROWS = 2_000
# The ceiling each content namespace (header and body separately) enforces.
MAX_ROWS = 10_000
ADD_ROWS = 509
REMOVE_ROWS = 251

COLUMN_HEADER = (
    f'{"rank":>6}  {"prime":>8}  {"digits":>6}  {"digit_sum":>9}  '
    f'{"binary":>18}  {"mod_10":>6}  {"gap":>3}  spelled'
)


def table_line(row: dict, iteration: int) -> str:
    """One row with every `PrimeRows` field but `is_palindrome`."""
    gap = '-' if row['gap_from_previous'] is None else str(row['gap_from_previous'])
    spelled = PrimeRows.altered_spelled(row['spelled'], row['rank'], iteration)
    return (
        f'{row["rank"]:>6}  {row["prime"]:>8}  {row["digits"]:>6}  '
        f'{row["digit_sum"]:>9}  {row["binary"]:>18}  {row["mod_10"]:>6}  '
        f'{gap:>3}  {spelled}'
    )


class LargeScreen(DemoScreen):
    title = 'O-large-bodies'

    def __init__(self, app: LargeApp) -> None:
        super().__init__(app)
        # True once this run's single drop alert has been acknowledged.
        self._drop_alerted = False

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        # Body first: header and body are separate namespaces,
        # so the painted bands still come out header-over-body,
        # but the dropped= count below has already seen this pass's overflow.
        with warnings.catch_warnings():
            # The library's drop warning is a UserWarning on stderr;
            # printing it would write straight into the middle of the curses screen.
            # The one-time alert below carries the same message without the damage.
            warnings.filterwarnings(
                'ignore',
                message=r'console-window: the .* content limit is full',
                category=UserWarning,
            )
            for row in self.app.rows:
                self.add_body(table_line(row, self.app.iteration))
        dropped = self.win.rows_dropped
        min_cols, min_rows = self.win.min_size
        self.add_fancy_header(
            f'O-large-bodies  [+]{ADD_ROWS}rows  [-]{REMOVE_ROWS}rows  '
            f'[r]edraw  [?]:help  [q]uit',
            mode='Underline',
        )
        self.add_header(
            f'NOTE: test resize [MinSize={min_cols}x{min_rows}]'
            f'{" " * 8}rows={len(self.app.rows)}/{self.win.opts.max_rows}'
            f' dropped={dropped}'
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)
        self._alert_if_rows_dropped(dropped)

    def _alert_if_rows_dropped(self, dropped: int) -> None:
        """Say once per run that rows are being discarded."""
        if not dropped or self._drop_alerted:
            return
        self._drop_alerted = True
        self.win.alert(
            f'{len(self.app.rows)} rows do not fit: '
            f'max_rows={self.win.opts.max_rows}.  {dropped} body rows were '
            f'dropped this pass.\nPress - to remove {REMOVE_ROWS} rows, or '
            'raise max_rows.',
            title='ROWS DROPPED',
        )

    def redraw_ACTION(self) -> None:
        self.win.render(redraw=True)
        self.win.status('full repaint complete', timeout=1.5)

    def add_rows_ACTION(self) -> None:
        self.app.add_rows()

    def remove_rows_ACTION(self) -> None:
        self.app.remove_rows()


class LargeApp(DemoApp):
    title = 'O-large-bodies'
    row_range = (1, START_ROWS)
    screen_class = LargeScreen
    win_options: ClassVar[dict[str, object]] = {
        'max_rows': MAX_ROWS,
        'min_cols_rows': (40, 8),
    }
    help_paragraphs = (
        'Every pass rebuilds the whole table, yet the pads stay sized to the '
        'viewport: the rows live in the model and the pads are blit buffers, so '
        'neither memory nor clear() grows with the row count.  The scroll '
        'indicator appears because the body is taller than the viewport.',
        f'+ adds {ADD_ROWS} rows and - removes {REMOVE_ROWS}, so the table can '
        'be resized by content as well as by terminal.  max_rows is the one '
        f'ceiling ({MAX_ROWS:,} here); a row added past it is dropped and '
        'counted in rows_dropped instead of raising.',
        'min_cols_rows is the configured floor, but after the first frame the '
        'one-time fit raises it to fit the widest header, capped at 60 columns. '
        'The second header line prints the floor in force, which is why it says '
        '60 rather than the configured 40.  r forces a full repaint, the '
        'recovery path for a corrupted display.',
    )

    def add_rows(self, count: int = ADD_ROWS) -> None:
        """Append up to *count* more ranks, as far as the sieve reaches."""
        start = len(self.rows) + 1
        available = len(PrimeRows().make_primes())
        if start > available:
            return
        end = min(start + count - 1, available)
        self.rows.extend(PrimeRows().generate_rows(start, end))

    def remove_rows(self, count: int = REMOVE_ROWS) -> None:
        """Drop the last *count* ranks, keeping at least one row."""
        del self.rows[max(1, len(self.rows) - count):]

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('redraw', 'r - full repaint', keys=[ord('r')],
                     genre='action',
                     comments='render(redraw=True): the normal pass repaints '
                              'only the viewport.')
        spin.add_key('add_rows', f'+ - add {ADD_ROWS} rows', keys=[ord('+')],
                     genre='action',
                     comments=f'Append {ADD_ROWS} prime ranks; rows past '
                              'max_rows raise the run\'s one alert and are '
                              'counted.')
        spin.add_key('remove_rows', f'- - remove {REMOVE_ROWS} rows',
                     keys=[ord('-')], genre='action',
                     comments=f'Drop the last {REMOVE_ROWS} ranks, never the '
                              'whole table.')
        return spin


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
