#!/usr/bin/env python3
"""N — Pause and run.

Owns: suspend-resume, external-program
Base: a-basic
Run:  ./demos/run-demo n-suspend

``suspend_curses()`` leaves curses mode without destroying the window;
``resume_curses()`` brings it back.  Everything between them is an ordinary
terminal program: an editor, a pager, or any subprocess that needs the real
screen.  The screen's content and scroll position survive, and the next
``render()`` repaints the page.

``e`` runs ``$PAGER`` (or ``less``) as the external program.  If the pager is
missing, the fallback is a tiny shell program, so the demo works on any host.
"""

from __future__ import annotations

import os
import shlex
import subprocess

from demo_kit import DemoApp, DemoScreen, run_main


class SuspendScreen(DemoScreen):
    title = 'pause and run'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'pause and run  pass {self.app.iteration}  [e]run pager  [q]uit',
            mode='Underline',
        )
        self.add_header('content and scroll position survive the hand-back')
        for row in self.app.rows:
            self.add_body(self.app.body_line(row))


class SuspendApp(DemoApp):
    title = 'pause and run'

    def build_screens(self):
        return [SuspendScreen(self)]

    def handle_key(self, key: int) -> None:
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('e'):
            self.run_external()

    def run_external(self) -> None:
        command = os.environ.get('PAGER') or 'less'
        argv = shlex.split(command)
        self.win.suspend_curses()
        try:
            try:
                subprocess.run(argv, check=False)
            except FileNotFoundError:
                subprocess.run(
                    ['sh', '-c',
                     'printf "External program.\\nPress ENTER to return."; '
                     'read _'],
                    check=False,
                )
        finally:
            self.win.resume_curses()
        self.win.status(f'returned from {command}', timeout=2.0)


def build_app(backend: object | None = None,
              singleton: bool = True) -> SuspendApp:
    return SuspendApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-n-suspend')


if __name__ == '__main__':
    main()
