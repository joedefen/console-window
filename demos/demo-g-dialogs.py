#!/usr/bin/env python3
"""G — Dialogs and the inline editor.

Owns: answer-dialog, alert-dialog, inline-confirmation, caret-editing
Base: c-options
Run:  ./demos/run-demo g-dialogs

``a`` opens the blocking ``answer()`` text dialog; the line editor behind it
handles Left/Right/Home/End/Backspace/Delete, and the name it returns is shown
on the header's second line, where a table-wide value belongs.  ``l`` opens
``alert()`` as a modal, scrollable message box.  ``i`` starts an
``InlineConfirmation`` on the picked row: the demo draws the question under that
row, so typing is echoed where the answer is read, and the widget only
classifies the keys.  Confirming marks the row with a check in the untitled
left column, so the answer leaves a visible trace in the table itself.

The three keys are spinner actions like any other, so the help page lists them.
``handle_key()`` adds one thing the shared ladder cannot know: an inline
confirmation owns keys before the spinner does.
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
from PrimeRows import PrimeRows

from console_window import Context, InlineConfirmation

#: A dialog is a conversation: hold the table still between churn passes (one
#: every five seconds) so the row being discussed cannot change under the
#: reader while the question is open.
PrimeRows.thaw_secs = 5.0
#: The mark a confirmed row wears, in the untitled column on the left.  The
#: column header carries the same width blank, so the titles stay aligned.
CHECK_MARK = '\u2713'
CHECK_COL = 2


class DialogScreen(DemoScreen):
    title = 'G-dialogs'
    pick_enabled = True

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        self.add_fancy_header(
            'G-dialogs  [a]nswer  [l]ert  [i]nline  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        # The answer to "a" is about the whole table, so it rides on the
        # header's second line (the column header) instead of on one row.  The
        # check column has no title of its own, so the titles keep their
        # columns under the marks.
        column = ' ' * CHECK_COL + COLUMN_HEADER
        if self.app.name:
            column += f'  name={self.app.name!r}'
        self.add_header(column, attr=cs.A_BOLD)

        for row in self.app.rows:
            mark = CHECK_MARK if row['rank'] in self.app.confirmed else ' '
            self.add_body(f'{mark} ' + row_line(row, self.app.iteration),
                          context=Context(genre='item', item=row))
            # The inline question is about the row it was started on, so it is
            # drawn directly under it: the caret, the echo and a wrong answer
            # are all visible where the question is asked, not off the bottom
            # of the table.  The rank is remembered at start time because the
            # body contexts are empty until this loop has added them.
            if self.app.inline.active and row['rank'] == self.app.inline_rank:
                self.add_body(
                    self.app.inline.get_display_string(
                        f'    Confirm rank {row["rank"]}? '),
                    attr=cs.A_BOLD)
                hint = self.app.inline.get_hint()
                if hint:
                    self.add_body(f'    {hint}', attr=cs.A_DIM)

    def answer_ACTION(self) -> None:
        response = self.win.answer('Your name: ',
                                   hint='ENTER submits, ESC cancels')
        if response:
            self.app.name = response
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
        ctx = self.win.get_picked_context()
        if not ctx:
            self.win.status('Pick a row first', level='warn', timeout=2.0)
            return
        rank = ctx.item['rank']
        self.app.inline_rank = rank
        # 'identity' mode: the answer must be the thing being confirmed, so a
        # stray ENTER cannot confirm anything.
        self.app.inline.start(action_type='confirm', identity=str(rank),
                              mode='identity')
        self.win.status(f'Type {rank} + ENTER to confirm, or ESC',
                        timeout=2.0)


class DialogApp(DemoApp):
    title = 'G-dialogs'
    screen_class = DialogScreen
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}
    help_paragraphs = (
        'answer() and alert() are blocking: the window takes the screen, runs '
        'its own key loop, and returns the reply (or None when the dialog is '
        'aborted).  ESC is the abort key, so both dialogs leave the picked row '
        'and the listing alone.  The name you answer with belongs to the whole '
        'table, so it is shown on the header\'s second line.',
        'InlineConfirmation is the non-blocking alternative.  It is drawn under '
        'the picked row and owns every key while it is live, which is the one '
        'mode the shared key ladder cannot know about.  It asks you to type the '
        'rank, so a stray ENTER confirms nothing and a wrong answer says so; '
        'the row it confirms then wears a check in the left column.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('answer', 'a - answer dialog', keys=[ord('a')],
                     genre='action',
                     comments='Blocking text dialog; ENTER submits, ESC '
                              'cancels.  The reply is shown on the header\'s '
                              'second line.')
        spin.add_key('alert', 'l - alert dialog', keys=[ord('l')],
                     genre='action',
                     comments='Modal message box about the picked row.')
        spin.add_key('inline', 'i - inline confirmation', keys=[ord('i')],
                     genre='action',
                     comments='The question is drawn under the picked row; '
                              'type its rank + ENTER, or ESC.')
        return spin

    def after_build(self) -> None:
        self.inline = InlineConfirmation()
        self.inline_rank: int | None = None
        self.confirmed: set[int] = set()
        self.name = ''

    def handle_key(self, key: int) -> None:
        if self.inline.active:
            before = self.inline.input_buffer
            result = self.inline.handle_key(key)
            if result == 'confirmed':
                answer = self.inline.input_buffer
                rank = self.inline_rank
                self.inline.cancel()
                self.inline_rank = None
                if rank is not None:
                    self.confirmed.add(rank)
                self.win.status(f'Confirmed: {answer}', timeout=1.5)
            elif result == 'cancelled':
                self.inline.cancel()
                self.inline_rank = None
                self.win.status('Cancelled', timeout=1.0)
            elif key in (10, 13) and before:
                # The widget clears an answer it cannot match, silently; the
                # demo is the only part that knows what the answer should be.
                self.win.status(
                    f'Type {self.inline.identity} + ENTER to confirm',
                    level='warn', timeout=2.0)
            return
        super().handle_key(key)


def build_app(backend: object | None = None,
              singleton: bool = True) -> DialogApp:
    return DialogApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-g-dialogs')


if __name__ == '__main__':
    main()
