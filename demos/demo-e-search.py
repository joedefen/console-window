#!/usr/bin/env python3
"""E — Filter as you type.

Owns: incremental-search, passthrough-mode, regex-filter, scoped-escape
Base: c-options
Run:  ./demos/run-demo e-search

``/`` starts the IncrementalSearchBar and turns on ``passthrough_mode``: while
the bar is live, printable keys and the caret keys belong to the bar instead of
the application.  The listing is filtered on every keystroke, and accepting a
filter resets the pick position to the top.

The pattern is a regular expression, decided the way vappman's filter does: a
pattern made only of words, dashes and spaces is split into words and matched
in order (so ``five hun`` finds "five hundred ..."), while anything else is
compiled as written (``^19\\d``).  A regex is often invalid while it is still
being typed, so a pattern that does not compile yet leaves the last valid
pattern filtering the table and turns only the ``/`` reverse-video; ENTER is
ignored until the pattern compiles again.

The pattern is drawn at the right end of the title line, after the ``/``, so
the title and the keys to its left never shift as it grows.  ``c`` -- an
ordinary OptionSpinner action -- clears the pattern and the table together.

ESC is deliberately screen-local here: the main screen binds it to "clear the
filter", which subtracts MAIN from the spinner's built-in escape action, so ESC
still pops the help screen.  While the bar is composing, ESC cancels back to the
pattern the bar started with.
"""

from __future__ import annotations

import re
from typing import ClassVar

from demo_kit import (
    COLUMN_HEADER,
    DemoApp,
    DemoHelpScreen,
    DemoScreen,
    row_line,
    run_main,
)

from console_window import HeaderLine, IncrementalSearchBar

MAIN_ST = 0
#: A pattern of only words, dashes and spaces is matched as words in order;
#: anything else is taken as a regex.  ``fullmatch``: the whole pattern decides.
_WORD_PATTERN = re.compile(r'[-\w\s]*')


class SearchScreen(DemoScreen):
    title = 'filter-as-you-type'

    def draw_header(self) -> None:
        line = HeaderLine()
        # One hyphenated word, so the whole title is the header's bold label.
        line.label('filter-as-you-type').text('  ')
        # A key that is part of its hint needs no separator; one that is not
        # (the '?') is divided from it with a colon.
        line.bracket_key('c').text('lear  ')
        line.bracket_key('?').text(':help  ')
        line.bracket_key('q').text('uit  ')
        # The pattern sits at the right end of the line, after the '/', so the
        # title and the keys never shift as it grows -- including while the
        # bar is composing, when the caret block is shown too.  A pattern that
        # does not compile yet reverses only the '/'; the table keeps the last
        # valid filter, so this is the one cue that it needs finishing.
        bar = self.app.filter_bar
        if bar.is_active:
            line.extend(bar.as_header_line(
                prefix='/', invalid=not self.app.filter_valid))
        else:
            # An accepted pattern (and an empty one, which is valid) is plain
            # text, so reverse video means exactly one thing on this line: the
            # pattern being typed does not compile yet.
            line.text(f'/{bar.text}' if bar.text else '/')
        self.add_fancy_header(line, mode='Underline')

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
        """``c``/ESC: drop the pattern and the filtered table together."""
        self.app.clear_filter()


class SearchApp(DemoApp):
    title = 'filter-as-you-type'
    win_options: ClassVar[dict[str, object]] = {'relax_handled_keys': False}
    help_paragraphs = (
        'The pattern is a regex.  Words, dashes and spaces are matched as '
        'words in order, so "five hun" finds "five hundred ...".  Anything '
        'else is compiled as written: try ^19\\d or 7$ .  A regex is often '
        'invalid while it is still being typed, so a pattern that does not '
        'compile yet leaves the last valid filter on the table and turns only '
        'the "/" reverse-video; ENTER is ignored until it compiles again.',
        'The pattern is drawn at the right end of the title line, after "/", '
        'so the keys to its left never move as it grows.  While the bar is '
        'composing, LEFT/RIGHT and Home/End move the caret, Backspace edits, '
        'ENTER accepts a valid pattern and ESC cancels back to the one it '
        'started with.',
        'c clears the pattern and the table together.  ESC on this screen '
        'clears the filter too, because the screen subtracts itself from the '
        'built-in escape action; on the help screen ESC still pops back.',
    )

    def build_screens(self):
        self.main = SearchScreen(self)
        self.help = DemoHelpScreen(self)
        return [self.main, self.help]

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('filter', '/ - filter by regex', keys=[ord('/')],
                     genre='action', scope={MAIN_ST},
                     comments='The table narrows on every keystroke; the '
                              'pattern is drawn at the right end of the title '
                              'line.')
        # Explicit scope on ESC subtracts MAIN from the built-in escape action;
        # on HELP the built-in still pops the screen.  One option owns both
        # keys, so the help page names them together.
        spin.add_key('clear_filter', 'c/ESC - clear the filter',
                     keys=[ord('c'), 27], genre='action', scope={MAIN_ST},
                     comments='Clears the pattern and restores every row.')
        return spin

    def after_build(self) -> None:
        self.filter_text = ''
        self.filter_re: re.Pattern[str] | None = None
        self.filter_valid = True
        self.filter_bar = IncrementalSearchBar(
            on_change=self._on_filter_change,
            on_accept=self._on_filter_accept,
            on_cancel=self._on_filter_cancel,
        )

    # --- the filter --------------------------------------------------------

    def apply_filter(self, text: str) -> bool:
        """Apply *text*, or keep the last valid pattern when it does not compile.

        Returns whether the text compiled.  ``filter_text``/``filter_re`` always
        describe the last pattern that did, so the table never blanks out while
        a regex is being typed; ``filter_valid`` describes the text at hand.
        """
        text = text.strip()
        if not text:
            self.filter_text = ''
            self.filter_re = None
            self.filter_valid = True
            return True
        try:
            if _WORD_PATTERN.fullmatch(text):
                # Words, dashes and spaces: match the words in order, so a
                # plain "five hun" behaves like a substring search even with
                # gaps between the words.
                words = text.split()
                pattern = re.compile(
                    r'\b' + r'(|.*\b)'.join(map(re.escape, words)),
                    re.IGNORECASE)
            else:
                # Anything else is the pattern the reader wrote.
                pattern = re.compile(text, re.IGNORECASE)
        except re.error:
            self.filter_valid = False
            return False
        self.filter_text = text
        self.filter_re = pattern
        self.filter_valid = True
        return True

    def clear_filter(self) -> None:
        """Drop the pattern, the bar's text and the table's filtering together."""
        self.filter_bar.reset()
        self.apply_filter('')
        self.win.passthrough_mode = False
        self.win.pick_pos = 0

    @staticmethod
    def filter_line(row: dict) -> str:
        """The text a pattern is matched against: the row as the table shows it."""
        return f'{row["rank"]} {row["prime"]} {row["spelled"]}'

    def visible_rows(self) -> list[dict]:
        if self.filter_re is None:
            return self.rows
        pattern = self.filter_re
        return [row for row in self.rows if pattern.search(self.filter_line(row))]

    # --- filter callbacks --------------------------------------------------

    def _on_filter_change(self, text: str) -> None:
        # Only a pattern that compiles moves the pick: an invalid one leaves
        # both the filter and the position alone.
        if self.apply_filter(text):
            self.win.pick_pos = 0

    def _on_filter_accept(self, text: str) -> None:
        self.apply_filter(text)
        self.win.passthrough_mode = False
        self.win.pick_pos = 0

    def _on_filter_cancel(self, original: str) -> None:
        # The bar has already put its starting text back; re-apply that pattern.
        self.apply_filter(original)
        self.win.passthrough_mode = False
        self.win.pick_pos = 0

    # --- the loop ----------------------------------------------------------

    def handle_key(self, key: int) -> None:
        # A live bar owns every key, so a printable key is a pattern character
        # rather than a spinner key; everything else takes the shared ladder.
        if self.filter_bar.is_active:
            if key in (10, 13) and not self.filter_valid:
                # A regex is invalid while it is being typed.  Ignore ENTER
                # until the bar's text compiles, so the last valid pattern
                # stays the filter and the reader can finish the pattern; the
                # reversed '/' in the header is the cue, and ESC still cancels.
                return
            self.filter_bar.handle_key(key)
            return
        super().handle_key(key)


def build_app(backend: object | None = None,
              singleton: bool = True) -> SearchApp:
    return SearchApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-e-search')


if __name__ == '__main__':
    main()
