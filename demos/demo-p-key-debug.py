#!/usr/bin/env python3
"""P — Keys and widths.

Owns: demo-mode, textwidth, wide-characters
Base: a-basic
Run:  ./demos/run-demo p-key-debug

``d`` toggles ``set_demo_mode()``: while it is on, the window shows the last key
it received in the corner, which is the fastest way to discover what a
terminal actually sends.

The body rows measure their labels with ``textwidth.string_width()`` and lay
them out with ``ljust()``/``truncate()``, so CJK (two cells), emoji with a
variation selector, and combining marks line up in the same columns as ASCII.
"""

from __future__ import annotations

import curses as cs

from demo_kit import DemoApp, DemoScreen, run_main

from console_window import textwidth

SAMPLES = (
    ('ascii', 'plain ascii'),
    ('cjk', '漢字かな'),
    ('emoji', '⚠️ ✓'),
    ('combining', 'e\u0301'),
)
LABEL_WIDTH = 12
SAMPLE_WIDTH = 12


class WidthScreen(DemoScreen):
    title = 'keys and widths'

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'keys and widths  demo_mode={self.win.opts.demo_mode}  '
            f'pass {self.app.iteration}  [d]toggle keys  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header(
            f'{"sample":<10} {"width":>5}  {"cell-accurate":<{SAMPLE_WIDTH}}'
        )
        for label, sample in SAMPLES:
            width = textwidth.string_width(sample)
            cell = textwidth.ljust(sample, SAMPLE_WIDTH)
            clipped = textwidth.truncate(sample, 6)
            self.add_body(
                f'{label:<10} {width:>5}  |{cell}|  trunc6=|{clipped}|'
            )


class WidthApp(DemoApp):
    title = 'keys and widths'

    def build_screens(self):
        return [WidthScreen(self)]

    def handle_key(self, key: int) -> None:
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False
        elif key == ord('d'):
            enabled = self.win.set_demo_mode(None)
            self.win.status(f'demo mode {"on" if enabled else "off"}',
                            timeout=1.0)


def build_app(backend: object | None = None,
              singleton: bool = True) -> WidthApp:
    return WidthApp(backend=backend, singleton=singleton)


def main() -> None:
    run_main(build_app, 'demo-p-key-debug')


if __name__ == '__main__':
    main()
