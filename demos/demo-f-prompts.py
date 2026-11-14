#!/usr/bin/env python3
"""F — Ask in place.

Owns: begin-prompt, single-key-prompt, text-prompt, prompt-placement,
      prompt-callbacks
Base: d-pick
Run:  ./demos/run-demo f-prompts

``y`` asks a single-key question under the picked row (``mode='y'``) and marks
that row confirmed, as if its arithmetic had been checked by hand; ``t`` asks a
buffered text question in the header band (``mode='text'`` with a seed) and
renames the spelled column.  The placement follows the question: a row's answer
is read under that row, and a column title is read above the table.  The
prompts are drawn by ``add_prompt_lines()`` / ``add_prompt_header()``, and the
completion callbacks run after passthrough is restored, so they can report with
``status()`` safely.

A live prompt owns every key.  The shared ladder in ``demo_kit.DemoApp`` routes
each one through ``handle_prompt_key()`` until the prompt reports that it is
done, so this demo registers its two actions and nothing else.
"""

from __future__ import annotations

import curses as cs
from typing import ClassVar

from demo_kit import (
    DemoApp,
    DemoScreen,
    row_line,
    run_main,
)
from PrimeRows import PrimeRows

from console_window import Context

#: The kit's pager restyles a sliver of rows on every pass; one pass every five
#: seconds keeps the table calm while a prompt is open.
PrimeRows.thaw_secs = 5.0


class PromptScreen(DemoScreen):
    title = 'F-ask-in-place'
    pick_enabled = True

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        self.draw_header()
        # The spelled column's title is the app's, so the header has to be
        # rebuilt each pass rather than taken from the kit's constant.
        self.add_header(
            f'{"rank":>6}  {"prime":>8}  {self.app.column_title}',
            attr=cs.A_BOLD,
        )

        for row in self.app.rows:
            rank = row['rank']
            marker = ' ✓ confirmed' if rank in self.app.confirmed else ''
            self.add_body(
                row_line(row, self.app.iteration) + marker,
                context=Context(genre='item', item=row),
            )
            # The single-key question belongs to the row it asks about; the
            # window marks both prompt rows as transient/non-pickable.
            if self.app.win.prompt_active and self.app.confirm_rank == rank:
                self.add_prompt_lines(attr=cs.A_BOLD, hint_attr=cs.A_DIM)

    def draw_header(self) -> None:
        # A key that is its hint's first letter is written once, inside the
        # word ([t]itle draws "title"); one that is not is divided from its
        # hint by a colon ([y]:confirm, [?]:help).
        self.add_fancy_header(
            'F-ask-in-place  [y]:confirm  [t]itle  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        # A column title is a question about the whole table, so its prompt
        # lives in the header band instead of under one row.
        if self.app.win.prompt_active and self.app.title_prompt:
            self.add_prompt_header()

    def confirm_ACTION(self) -> None:
        ctx = self.win.get_picked_context()
        if not ctx:
            return
        rank = ctx.item['rank']
        self.app.confirm_rank = rank

        def confirm(_answer: str) -> None:
            self.app.confirm_rank = None
            self.app.confirmed.add(rank)
            self.win.status(f'Confirmed rank {rank}', timeout=1.5)

        def cancel() -> None:
            self.app.confirm_rank = None
            self.win.status('Not confirmed', timeout=1.0)

        self.win.begin_prompt(
            f'    Confirm rank {rank}?',
            mode='y',
            hint='Marks the row as checked by hand',
            on_confirm=confirm,
            on_cancel=cancel,
        )

    def title_ACTION(self) -> None:
        """``t``: rename the spelled column from the header band."""
        self.app.title_prompt = True

        def save(answer: str) -> None:
            self.app.title_prompt = False
            self.app.column_title = answer.strip() or 'spelled'
            self.win.status(f'Column title: {self.app.column_title}',
                            timeout=1.5)

        def cancel() -> None:
            self.app.title_prompt = False
            self.win.status('Title unchanged', timeout=1.0)

        self.win.begin_prompt(
            'Spelled column title',
            hint='ENTER to apply, ESC to cancel',
            mode='text',
            seed=self.app.column_title,
            on_confirm=save,
            on_cancel=cancel,
        )


class PromptApp(DemoApp):
    title = 'F-ask-in-place'
    screen_class = PromptScreen
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}
    help_paragraphs = (
        'y asks a single-key question directly under the picked row, so the '
        'answer is read next to the thing it is about; it marks that row '
        'confirmed, as if its arithmetic had been checked by hand.  The prompt '
        'rows are transient: the window marks them non-pickable and j/k skips '
        'them.',
        't asks a buffered text question in the header band, because the column '
        'title is about the whole table rather than one row; ENTER applies it '
        'and ESC cancels.  The callbacks run after passthrough is restored, so '
        'they can write a status line safely.  While a prompt is live it owns '
        'every key; the shared ladder routes them to handle_prompt_key() until '
        'it is done.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('confirm', 'y - confirm the picked row', keys=[ord('y')],
                     genre='action',
                     comments='Asks y/ESC under the row; marks it confirmed.')
        spin.add_key('title', 't - retitle the spelled column',
                     keys=[ord('t')], genre='action',
                     comments='A text prompt in the header band; ENTER '
                              'applies it, ESC cancels.')
        return spin

    def after_build(self) -> None:
        self.confirmed: set[int] = set()
        self.column_title = 'spelled'
        self.confirm_rank: int | None = None
        self.title_prompt = False


def build_app(backend: object | None = None,
              singleton: bool = True) -> PromptApp:
    return PromptApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-f-prompts')


if __name__ == '__main__':
    main()
