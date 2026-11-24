#!/usr/bin/env python3
"""L — Read-only screens.

Owns: basic-text-screen, help-paragraphs, read-only-screen,
escape-action Base: c-options Run: ./demos/run-demo l-text-screens

`BasicTextScreen` is for content that does not need a spinner,
a pick model or per-row actions: give it lines (plain
strings or `(text, attr)` pairs) and optional headers,
and `set_text()` replaces them at any time.
The screen is read-only; its default `escape_ACTION` pops back.

The help screen is a `BasicHelpScreen` subclass that
adds its own paragraph through `extra_help_paragraphs()`;
the base class supplies the `Instructions` separator,
the bullet and the hanging-indent wrapping.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoHelpScreen, DemoScreen, run_main

from console_window import Appearance, BasicTextScreen, Theme

MAIN_ST = 0
INFO_ST = 1
HELP_ST = 2


class InfoScreen(BasicTextScreen):
    """A read-only report; set_text() replaces the whole body."""

    def quit_ACTION(self) -> None:
        self.app.running = False


class HelpTextScreen(DemoHelpScreen):
    """The app's own prose, added to the shared help page's paragraphs."""

    def extra_help_paragraphs(self):
        return (*super().extra_help_paragraphs(),
                'This screen is a DemoHelpScreen subclass.  Its own paragraph is '
                'wrapped and bulleted by the base class, and ESC pops back.')


class TextMainScreen(DemoScreen):
    title = 'L-read-only-screens'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            'L-read-only-screens  [i]nfo  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header('the info screen is a BasicTextScreen')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def info_screen_ACTION(self) -> None:
        self.app.show_info()
        self.app.stack.push(self.app.info, self.pick_pos)


class TextApp(DemoApp):
    title = 'L-read-only-screens'

    def build_screens(self):
        self.main = TextMainScreen(self)
        self.info = InfoScreen(self)
        self.help = HelpTextScreen(self)
        return [self.main, self.info, self.help]

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('info_screen', 'i - info', keys=[ord('i')],
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
