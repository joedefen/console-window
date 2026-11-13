#!/usr/bin/env python3
"""F — Ask in place.

Owns: begin-prompt, single-key-prompt, text-prompt, prompt-placement,
      prompt-callbacks
Base: d-pick
Run:  ./demos/run-demo f-prompts

``y`` asks a single-key question under the picked row (``mode='y'``); ``N``
opens a buffered text prompt in the header band (``mode='text'`` with a seed).
The prompt is drawn by ``add_prompt_lines()`` / ``add_prompt_header()``, and the
completion callbacks run after passthrough is restored, so they can report with
``status()`` safely.

A live prompt owns every key.  The app routes each one through
``handle_prompt_key()`` until the prompt reports that it is done.
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

from console_window import Context


class PromptScreen(DemoScreen):
    title = 'ask in place'
    pick_enabled = True

    def draw_screen(self) -> None:
        self.set_pick_mode(True)
        self.draw_header()
        self.add_header(COLUMN_HEADER, attr=cs.A_BOLD)

        for row in self.app.rows:
            rank = row['rank']
            marker = ' ✓ processed' if rank in self.app.processed else ''
            if rank in self.app.notes:
                marker += f'  note={self.app.notes[rank]!r}'
            self.add_body(
                row_line(row, self.app.iteration) + marker,
                context=Context(genre='item', item=row),
            )
            # The single-key question belongs to the row it asks about; the
            # window marks both prompt rows as transient/non-pickable.
            if self.app.win.prompt_active and self.app.prompt_rank == rank:
                self.add_prompt_lines(attr=cs.A_BOLD, hint_attr=cs.A_DIM)

    def draw_header(self) -> None:
        self.add_fancy_header(
            f'ask in place  pass {self.app.iteration}  '
            f'[y]confirm  [N]note  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        # A buffered note is a screen-wide question, so it lives in the header
        # band instead of under one row.
        if self.app.win.prompt_active and self.app.note_rank is not None:
            self.add_prompt_header()

    def confirm_ACTION(self) -> None:
        ctx = self.win.get_picked_context()
        if not ctx:
            return
        rank = ctx.item['rank']
        self.app.prompt_rank = rank

        def confirm(_answer: str) -> None:
            self.app.prompt_rank = None
            self.app.processed.add(rank)
            self.win.status(f'Processed rank {rank}', timeout=1.5)

        def cancel() -> None:
            self.app.prompt_rank = None
            self.win.status('Cancelled', timeout=1.0)

        self.win.begin_prompt(
            f'    Process rank {rank}?',
            mode='y',
            hint='Marks the row as processed',
            on_confirm=confirm,
            on_cancel=cancel,
        )

    def note_ACTION(self) -> None:
        ctx = self.win.get_picked_context()
        if not ctx:
            self.win.status('Pick a row first', level='warn', timeout=2.0)
            return
        rank = ctx.item['rank']
        self.app.note_rank = rank

        def save(answer: str) -> None:
            self.app.note_rank = None
            self.app.notes[rank] = answer
            self.win.status(f'Note saved for rank {rank}', level='warn',
                            timeout=2.0)

        def cancel() -> None:
            self.app.note_rank = None
            self.win.status('Note cancelled', timeout=1.5)

        self.win.begin_prompt(
            f'Note for rank {rank}',
            hint='ENTER to save, ESC to cancel',
            mode='text',
            seed=self.app.notes.get(rank, ''),
            on_confirm=save,
            on_cancel=cancel,
        )


class PromptApp(DemoApp):
    title = 'ask in place'
    win_options: ClassVar[dict[str, object]] = {'pick_attr': cs.A_REVERSE}

    def build_screens(self):
        return [PromptScreen(self)]

    def after_build(self) -> None:
        self.processed: set[int] = set()
        self.notes: dict[int, str] = {}
        self.prompt_rank: int | None = None
        self.note_rank: int | None = None

    def handle_key(self, key: int) -> None:
        # Contract: a live prompt owns every key until it is done.
        if self.win.prompt_active:
            self.win.handle_prompt_key(key)
            return
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('y'):
            self.main.confirm_ACTION()
        elif key == ord('N'):
            self.main.note_ACTION()

    @property
    def main(self) -> PromptScreen:
        return self.stack.get_curr_obj()


def build_app(backend: object | None = None,
              singleton: bool = True) -> PromptApp:
    return PromptApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-f-prompts')


if __name__ == '__main__':
    main()
