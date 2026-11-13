#!/usr/bin/env python3
"""H — Messages.

Owns: status-levels, status-lifecycle, status-placement, flash
Base: a-basic
Run:  ./demos/run-demo h-messages

``status()`` writes one line on the separator row, next to the scroll
indicator.  Its ``level`` chooses the attribute (info, warn, error) and
``timeout`` makes it expire lazily at draw time.  ``status('')``,
``clear_status()`` and ``current_status`` are the lifecycle; the header shows
the current value so the effect is visible even when the separator is narrow.

``flash()`` is the modal alternative: it clears the screen and waits, so it is
right for a short acknowledgement and wrong for a message that must leave the
listing visible.
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
            f'[i]info [w]warn [e]error [c]lear [f]flash [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(f'current status: {status or "(none)"}', attr=cs.A_DIM)

    def draw_body(self) -> None:
        self.add_header('body rows stay put; only the separator row changes')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))


class MessageApp(DemoApp):
    title = 'messages'

    def build_screens(self):
        return [MessageScreen(self)]

    def handle_key(self, key: int) -> None:
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('i'):
            self.win.status('Saved successfully', level='info', timeout=2.0)
        elif key == ord('w'):
            self.win.status('Careful: the disk is almost full',
                            level='warn', timeout=3.0)
        elif key == ord('e'):
            self.win.status('Failed to write the row', level='error',
                            timeout=None)
        elif key == ord('c'):
            self.win.clear_status()
        elif key == ord('f'):
            self.win.flash('All changes applied', duration=1.0)


def build_app(backend: object | None = None,
              singleton: bool = True) -> MessageApp:
    return MessageApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-h-messages')


if __name__ == '__main__':
    main()
