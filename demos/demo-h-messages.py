#!/usr/bin/env python3
"""H — Messages.

Owns: status-levels, status-lifecycle, status-placement,
flash Base: c-options Run: ./demos/run-demo h-messages

`status()` writes one line on the separator row, next to the scroll indicator.
Its `level` chooses the attribute (info, warn,
error) and `timeout` makes it expire lazily at draw time.  `status('')`,
`clear_status()` and `current_status` are the lifecycle;
the header's second line repeats the payload so the
effect is visible even when the separator is narrow,
and the payload is decorated per level -- plain, bold, bold and reversed
-- instead of being dimmed with the rest of the band.

`flash()` is the modal alternative: it clears the screen and waits,
so it is right for a short acknowledgement and wrong
for a message that must leave the listing visible.

The table churns once every five seconds (`PrimeRows.thaw_secs`):
the listing is a backdrop for the message, not a reason to repaint continuously.

Every key here is a spinner action,
so the help page lists all five and says what each one is expected to do.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import DemoApp, DemoScreen, run_main
from PrimeRows import PrimeRows

# One churn pass every five seconds: the status message is the subject here,
# and a table restyling under it would pull the eye away from the separator row.
PrimeRows.thaw_secs = 5.0

# How the demo repeats the payload on the header's second line.
# `status()` stores `A_DIM` for `info`,
# which is right on the separator row -- the message is an aside there
# -- but would leave the demo's own line looking untouched,
# so `info` is plain here and the three levels stay distinct.
HEADER_LEVEL_ATTRS: dict[str, int] = {
    'info': cs.A_NORMAL,
    'warn': cs.A_BOLD,
    'error': cs.A_BOLD | cs.A_REVERSE,
}


class MessageScreen(DemoScreen):
    title = 'H-messages'

    def draw_header(self) -> None:
        self.add_fancy_header(
            'H-messages  [i]nfo [w]arn [e]rror [c]lear [f]lash [?]:help [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        # The caption stays dim with the band;
        # the payload resumes the same row in the level's decoration,
        # so a message never disappears into the dim header
        # and the three categories look different at a glance.
        status, _attr = self.win.current_status
        self.add_header('current status: ', attr=cs.A_DIM)
        if status:
            self.add_header(status, attr=HEADER_LEVEL_ATTRS[self.app.status_level],
                            resume=True)
        else:
            self.add_header('(none)', attr=cs.A_DIM, resume=True)

    def draw_body(self) -> None:
        self.add_header('body rows stay put between churn passes; '
                        'the separator row changes at once')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def info_ACTION(self) -> None:
        self.app.status_level = 'info'
        self.win.status('Saved successfully', level='info', timeout=2.0)

    def warn_ACTION(self) -> None:
        self.app.status_level = 'warn'
        self.win.status('Careful: the disk is almost full', level='warn',
                        timeout=3.0)

    def error_ACTION(self) -> None:
        self.app.status_level = 'error'
        self.win.status('Failed to write the row', level='error',
                        timeout=None)

    def clear_ACTION(self) -> None:
        self.app.status_level = 'info'
        self.win.clear_status()

    def flash_ACTION(self) -> None:
        self.win.flash('All changes applied', duration=1.0)


class MessageApp(DemoApp):
    title = 'H-messages'
    screen_class = MessageScreen
    # The level of the message currently declared;
    # the header's second line decorates itself from this,
    # since `current_status` carries text and attribute
    # but not the name of the level that chose the attribute.
    status_level: ClassVar[str] = 'info'
    help_paragraphs = (
        'A status message declares itself and is painted on the next render, on '
        'the separator row beside the scroll indicator.  It never takes over '
        "the display, so the listing stays readable while it is up.  The header's "
        "second line repeats the payload in the level's decoration (plain, bold, "
        'bold and reversed), which keeps it readable in a narrow window where '
        'the separator has little room.',
        'The timeout expires lazily at draw time; the error message has no '
        'timeout and stays until it is cleared or replaced.  flash() is the '
        'modal alternative: it clears the screen and waits, which suits a short '
        'acknowledgement and not a reference message.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('info', 'i - info status', keys=[ord('i')],
                     genre='action',
                     comments='Looks like success; expires after two seconds.')
        spin.add_key('warn', 'w - warn status', keys=[ord('w')],
                     genre='action',
                     comments='Bold, for something the user should notice.')
        spin.add_key('error', 'e - error status', keys=[ord('e')],
                     genre='action',
                     comments='Bold and reversed; no timeout, so it persists.')
        spin.add_key('clear', 'c - clear status', keys=[ord('c')],
                     genre='action',
                     comments='The same as status(""): removes the line.')
        spin.add_key('flash', 'f - flash a message', keys=[ord('f')],
                     genre='action',
                     comments='Modal: clears the screen for one second.')
        return spin


def build_app(backend: object | None = None,
              singleton: bool = True) -> MessageApp:
    return MessageApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-h-messages')


if __name__ == '__main__':
    main()
