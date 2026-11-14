#!/usr/bin/env python3
"""H — Messages.

Owns: status-levels, status-lifecycle, status-placement, flash
Base: c-options
Run:  ./demos/run-demo h-messages

``status()`` writes one line on the separator row, next to the scroll
indicator.  Its ``level`` chooses the attribute (info, warn, error) and
``timeout`` makes it expire lazily at draw time.  ``status('')``,
``clear_status()`` and ``current_status`` are the lifecycle; the header shows
the current value so the effect is visible even when the separator is narrow.

``flash()`` is the modal alternative: it clears the screen and waits, so it is
right for a short acknowledgement and wrong for a message that must leave the
listing visible.

Every key here is a spinner action, so the help page lists all five and says
what each one is expected to do.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main


class MessageScreen(DemoScreen):
    title = 'messages'

    def draw_header(self) -> None:
        status, _attr = self.win.current_status
        self.add_fancy_header(
            f'messages  pass {self.app.iteration}  '
            f'[i]nfo [w]arn [e]rror [c]lear [f]lash [?]help [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(f'current status: {status or "(none)"}', attr=cs.A_DIM)

    def draw_body(self) -> None:
        self.add_header('body rows stay put; only the separator row changes')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def info_ACTION(self) -> None:
        self.win.status('Saved successfully', level='info', timeout=2.0)

    def warn_ACTION(self) -> None:
        self.win.status('Careful: the disk is almost full', level='warn',
                        timeout=3.0)

    def error_ACTION(self) -> None:
        self.win.status('Failed to write the row', level='error',
                        timeout=None)

    def clear_ACTION(self) -> None:
        self.win.clear_status()

    def flash_ACTION(self) -> None:
        self.win.flash('All changes applied', duration=1.0)


class MessageApp(DemoApp):
    title = 'messages'
    screen_class = MessageScreen
    help_paragraphs = (
        'A status message declares itself and is painted on the next render, on '
        'the separator row beside the scroll indicator.  It never takes over '
        'the display, so the listing stays readable while it is up.',
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
