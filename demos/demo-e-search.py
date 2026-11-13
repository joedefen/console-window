#!/usr/bin/env python3
"""E — Filter as you type.

Owns: incremental-search, passthrough-mode, temp-handled-keys, scoped-escape
Base: c-options
Run:  ./demos/run-demo e-search

``/`` starts the IncrementalSearchBar and turns on ``passthrough_mode``: while
the bar is live, printable keys and the caret keys belong to the bar instead of
the application.  The listing is filtered on every keystroke, and accepting a
filter resets the pick position to the top.

ESC is deliberately screen-local here: the main screen binds it to "clear the
filter", which subtracts MAIN from the spinner's built-in escape action, so ESC
still pops the help screen.  ``\\`` is forwarded for one prompt only with
``temp_handled_keys()`` -- the window's handled-key set is not changed for the
rest of the session.
"""

from __future__ import annotations

from typing import ClassVar

from demo_kit import (
    COLUMN_HEADER,
    DemoApp,
    DemoHelpScreen,
    DemoScreen,
    row_line,
    run_main,
)

from console_window import (
    HeaderLine,
    IncrementalSearchBar,
    OptionSpinner,
)

MAIN_ST = 0
TEMP_CLEAR_KEY = ord('\\')


class SearchScreen(DemoScreen):
    title = 'filter as you type'

    def draw_header(self) -> None:
        line = HeaderLine()
        line.text(f'filter as you type  pass {self.app.iteration}  ')
        bar_line = self.app.filter_bar.as_header_line(prefix='/')
        if bar_line:
            line.extend(bar_line)
        else:
            line.text('/')
        line.text('  [/]filter  [\\]clear  [?]help  [q]uit')
        self.add_fancy_header(line, mode='Underline', line_attr=None)

    def draw_body(self) -> None:
        self.add_header(COLUMN_HEADER, attr=0)
        rows = self.app.visible_rows()
        if not rows:
            self.add_body('  (no matches)', attr=0)
            return
        for row in rows:
            self.add_body(row_line(row, self.app.iteration))

    def filter_ACTION(self) -> None:
        self.app.filter_bar.start(self.app.filter_text)
        self.app.win.passthrough_mode = True

    def clear_filter_ACTION(self) -> None:
        self.app.filter_bar.start(self.app.filter_text)
        self.app.filter_bar.handle_key(27)
        self.app.win.pick_pos = 0

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class SearchApp(DemoApp):
    title = 'filter as you type'
    win_options: ClassVar[dict[str, object]] = {'relax_handled_keys': False}

    def build_screens(self):
        self.main = SearchScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        spin = OptionSpinner(stack=self.stack,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        spin.add_key('filter', '/ - filter', keys=[ord('/')],
                     genre='action', scope={MAIN_ST})
        # Explicit scope on ESC subtracts MAIN from the built-in escape action;
        # on HELP the built-in still pops the screen.
        spin.add_key('clear_filter', 'ESC - clear filter', keys=[27],
                     genre='action', scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin

    def after_build(self) -> None:
        self.filter_text = ''
        self.filter_bar = IncrementalSearchBar(
            on_change=self._on_filter_change,
            on_accept=self._on_filter_accept,
            on_cancel=self._on_filter_cancel,
        )

    # --- filter callbacks --------------------------------------------------

    def _on_filter_change(self, text: str) -> None:
        self.filter_text = text.lower()
        self.win.pick_pos = 0

    def _on_filter_accept(self, text: str) -> None:
        self.filter_text = text.lower()
        self.win.passthrough_mode = False
        self.win.pick_pos = 0

    def _on_filter_cancel(self, _original: str) -> None:
        self.filter_text = ''
        self.win.passthrough_mode = False
        self.win.pick_pos = 0

    def visible_rows(self) -> list[dict]:
        if not self.filter_text:
            return self.rows
        return [row for row in self.rows
                if self.filter_text in str(row['prime'])
                or self.filter_text in row['spelled'].lower()]

    # --- actions -----------------------------------------------------------

    def read_key(self) -> int | None:
        # Forward the one-off clear key without changing the window's permanent
        # binding set.  The prompt is called inside the context manager.
        with self.win.temp_handled_keys(TEMP_CLEAR_KEY):
            return self.win.prompt(seconds=0.5)

    def handle_key(self, key: int) -> None:
        if self.win.prompt_active:
            self.win.handle_prompt_key(key)
            return
        if self.filter_bar.is_active:
            self.filter_bar.handle_key(key)
            return
        if key == TEMP_CLEAR_KEY:
            self.main.clear_filter_ACTION()
            return
        if self.spin is not None and key in self.spin.keys:
            self.spin.do_key(key, self.win)
            return
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False


def build_app(backend: object | None = None,
              singleton: bool = True) -> SearchApp:
    return SearchApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-e-search')


if __name__ == '__main__':
    main()
