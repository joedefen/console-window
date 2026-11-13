#!/usr/bin/env python3
"""L — Read-only screens.

Owns: basic-text-screen, help-paragraphs, read-only-screen, escape-action
Base: c-options
Run:  ./demos/run-demo l-text-screens

``BasicTextScreen`` is for content that does not need a spinner, a pick model
or per-row actions: give it lines (plain strings or ``(text, attr)`` pairs) and
optional headers, and ``set_text()`` replaces them at any time.  The screen is
read-only; its default ``escape_ACTION`` pops back.

The help screen is a ``BasicHelpScreen`` subclass that adds its own paragraph
through ``extra_help_paragraphs()``; the base class supplies the wrapping,
indent and the dim attribute.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import (
    Appearance,
    BasicHelpScreen,
    BasicTextScreen,
    OptionSpinner,
    Theme,
)

MAIN_ST = 0
INFO_ST = 1
HELP_ST = 2


class InfoScreen(BasicTextScreen):
    """A read-only report; set_text() replaces the whole body."""

    def quit_ACTION(self) -> None:
        self.app.running = False


class HelpTextScreen(BasicHelpScreen):
    def extra_help_paragraphs(self):
        return (
            'This screen is a BasicHelpScreen subclass.  Its own paragraph is '
            'wrapped and dimmed by the base class, and ESC pops back.',
        )

    def quit_ACTION(self) -> None:
        self.app.running = False


class TextMainScreen(DemoScreen):
    title = 'read-only screens'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'read-only screens  pass {self.app.iteration}  '
            f'[i]nfo  [?]help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header('the info screen is a BasicTextScreen')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def info_screen_ACTION(self) -> None:
        self.app.show_info()
        self.app.stack.push(self.app.info, self.pick_pos)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class TextApp(DemoApp):
    title = 'read-only screens'

    def build_screens(self):
        self.main = TextMainScreen(self)
        self.info = InfoScreen(self)
        self.help = HelpTextScreen(self)
        return [self.main, self.info, self.help]

    def build_spinner(self):
        spin = OptionSpinner(stack=self.stack,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        spin.add_key('info_screen', 'i - info', keys=[ord('i')],
                     genre='action', scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin

    def show_info(self) -> None:
        """Rebuild the read-only body with set_text()."""
        lines = [
            ('  Prime rows, first and last in this page', cs.A_DIM),
            '',
            '  rank   prime   spelled',
        ]
        for row in (self.rows[0], self.rows[-1]):
            lines.append(
                f'  {row["rank"]:>4}  {row["prime"]:>6}   {row["spelled"]}'
            )
        lines.extend([
            '',
            ('  Processed rows are marked by the application.',
             Appearance.semantic_attr(Theme.SUCCESS)),
            ('  ESC pops back to the table.', cs.A_DIM),
        ])
        self.info.set_text(lines=lines, head='READ-ONLY DETAIL')


def build_app(backend: object | None = None,
              singleton: bool = True) -> TextApp:
    return TextApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-l-text-screens')


if __name__ == '__main__':
    main()
