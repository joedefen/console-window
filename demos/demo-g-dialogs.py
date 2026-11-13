#!/usr/bin/env python3
"""G — Dialogs and the inline editor.

Owns: answer-dialog, alert-dialog, inline-confirmation, caret-editing
Base: c-options
Run:  ./demos/run-demo g-dialogs

``a`` opens the blocking ``answer()`` text dialog; the line editor behind it
handles Left/Right/Home/End/Backspace/Delete.  ``l`` opens ``alert()`` as a
modal, scrollable message box.  ``i`` starts an ``InlineConfirmation`` on the
screen itself, so the question is rendered by the demo and the widget only
classifies the keys.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import (
    COLUMN_HEADER,
    DemoApp,
    DemoScreen,
    row_line,
    run_main,
)

from console_window import Context, InlineConfirmation


class DialogScreen(DemoScreen):
    title = 'dialogs'
    pick_enabled = True

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        self.add_fancy_header(
            f'dialogs  pass {self.app.iteration}  '
            f'[a]answer  [l]alert  [i]inline  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.app.rows:
            self.add_body(row_line(row, self.app.iteration),
                          context=Context(genre='item', item=row))

        if self.app.inline.active:
            self.add_body(self.app.inline.get_display_string('Proceed? '),
                          attr=cs.A_BOLD)
            self.add_body(self.app.inline.get_hint(), attr=cs.A_DIM)

    def answer_ACTION(self) -> None:
        response = self.win.answer('Your name: ',
                                   hint='ENTER submits, ESC cancels')
        if response:
            self.win.status(f'Hello, {response}!', level='warn', timeout=2.0)
        else:
            self.win.status('Cancelled', timeout=1.0)

    def alert_ACTION(self) -> None:
        ctx = self.win.get_picked_context()
        if ctx:
            row = ctx.item
            message = (f'rank {row["rank"]}: {row["prime"]} '
                       f'({row["spelled"]})')
            self.win.alert(message, title='Prime info')
        else:
            self.win.alert('No row picked.', title='Pick a row')

    def inline_ACTION(self) -> None:
        self.app.inline.start(action_type='process', identity='rank',
                              mode='yes')
        self.win.status('Inline confirmation: y or ESC', timeout=2.0)


class DialogApp(DemoApp):
    title = 'dialogs'
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}

    def build_screens(self):
        return [DialogScreen(self)]

    def after_build(self) -> None:
        self.inline = InlineConfirmation()

    def handle_key(self, key: int) -> None:
        if self.inline.active:
            result = self.inline.handle_key(key)
            if result == 'confirmed':
                answer = self.inline.input_buffer
                self.inline.cancel()
                self.win.status(f'Confirmed: {answer}', timeout=1.5)
            elif result == 'cancelled':
                self.inline.cancel()
                self.win.status('Cancelled', timeout=1.0)
            return
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('a'):
            self.main.answer_ACTION()
        elif key == ord('l'):
            self.main.alert_ACTION()
        elif key == ord('i'):
            self.main.inline_ACTION()

    @property
    def main(self) -> DialogScreen:
        return self.stack.get_curr_obj()


def build_app(backend: object | None = None,
              singleton: bool = True) -> DialogApp:
    return DialogApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-g-dialogs')


if __name__ == '__main__':
    main()
