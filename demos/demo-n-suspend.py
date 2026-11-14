#!/usr/bin/env python3
"""N — Pause and run.

Owns: suspend-resume, external-program
Base: c-options
Run:  ./demos/run-demo n-suspend

``suspend_curses()`` leaves curses mode without destroying the window;
``resume_curses()`` brings it back.  Everything between them is an ordinary
terminal program: an editor, a pager, or any subprocess that needs the real
screen.  The screen's content and scroll position survive, and the next
``render()`` repaints the page.

``e`` clears the screen and hands the terminal to a small shell program.  It
prints the command it is about to run (``+ ls -l /bin/*sh | head -n 8``), runs
it, then asks ``===>  Return to screen?`` and waits for ENTER.  That pause is
the lesson: the hand-back takes milliseconds, so without it ``e`` looks like it
did nothing.  The help page says what the keys do and what survives.
"""

from __future__ import annotations

import curses as cs
import subprocess

from demo_kit import DemoApp, DemoScreen, run_main

# The external program owns the terminal completely, prompt included.  Clearing
# the screen makes it obvious what belongs to this run, the "+ ..." line shows
# the command, and the listing is a bounded glob that always matches (/bin/sh
# exists on every POSIX system).  The answer is read from the terminal rather
# than stdin, so the hold works even if curses left fd 0 in an unexpected state;
# the second read is the no-tty fallback, where nobody is there to wait.
EXTERNAL_SCRIPT = """\
clear 2>/dev/null || true
printf 'You are in an ordinary terminal now, not in curses.\\n\\n'
printf '+ ls -l /bin/*sh | head -n 8\\n\\n'
ls -l /bin/*sh | head -n 8
printf '\\n===>  Return to screen? '
read _ 2>/dev/null < /dev/tty || read _
"""


class SuspendScreen(DemoScreen):
    title = 'pause-and-run'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        # The fancy header bolds its first word as the title.  "pause-and-run"
        # is one hyphenated word, so the whole title is bold; the colon keeps a
        # key from abutting the word it introduces (e:run, ?:help), while
        # [q]uit stays bracketed because the key is part of that word.
        self.add_fancy_header(
            'pause-and-run  [e]:run  [?]:help  [q]uit',
            mode='Underline',
        )
        self.add_header('NOTE: content and scroll position survive the hand-back',
                        attr=cs.A_BOLD)
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))

    def run_external_ACTION(self) -> None:
        """``e``: hand the terminal over, then come back to the same page."""
        self.app.run_external()


class SuspendApp(DemoApp):
    title = 'pause-and-run'
    screen_class = SuspendScreen
    help_paragraphs = (
        'e suspends curses and gives the whole terminal to an ordinary shell '
        'program.  It clears the screen, echoes the command it runs '
        '(+ ls -l /bin/*sh | head -n 8), then asks "===>  Return to screen?" '
        'and waits for ENTER.  The wait is the demo: without it the hand-back is '
        'too fast to see.',
        'When the program exits, curses comes back and the next render repaints '
        'the page: the content, the pick position and the scroll position are '
        'the same as before the hand-back.  A real editor or pager is the same '
        'shape -- it owns the terminal until it exits.',
    )

    def build_spinner(self):
        spin = self.new_spinner()
        spin.add_key('run_external', 'e - run an external program',
                     keys=[ord('e')], genre='action',
                     comments='Prints, asks "Return to screen?", waits for '
                              'ENTER, then repaints.')
        return spin

    def run_external(self) -> None:
        """Run a real terminal program between suspend and resume."""
        self.win.suspend_curses()
        try:
            subprocess.run(['sh', '-c', EXTERNAL_SCRIPT], check=False)
        finally:
            self.win.resume_curses()


def build_app(backend: object | None = None,
              singleton: bool = True) -> SuspendApp:
    return SuspendApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-n-suspend')


if __name__ == '__main__':
    main()
