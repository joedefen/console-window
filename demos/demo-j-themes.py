#!/usr/bin/env python3
"""J — Themes and appearance.

Owns: theme-picker, theme-store, per-window-theme, mono-theme, semantic-attrs,
      theme-captions
Base: c-options
Run:  ./demos/run-demo j-themes

``Theme.create_picker_screen()`` builds the THEMES screen, including its
swatch rows and the glyph catalog.  ``win.set_theme()`` changes this window's
theme; ``Theme.set_active()`` is the process default.  ``mono`` is a real
theme: selecting it turns semantic color off and the swatches switch to the
bold/reverse attribute hierarchy.

The host's ``captions=`` mapping renames one role, and ``store=`` remembers the
last choice for the next start.  Body rows use ``Appearance.semantic_attr()``,
so the same rows degrade correctly under ``mono``.

``t`` cycles the window's theme without leaving the table; the header names the
theme it lands on and the choice is saved.  ``T`` opens the picker, where ``t``
cycles too.  The table churns once every five seconds
(``PrimeRows.thaw_secs``), so the color change is the only motion on screen.
"""

from __future__ import annotations

import argparse
import curses as cs

from demo_kit import DemoApp, DemoScreen, row_line
from PrimeRows import PrimeRows

from console_window import Appearance, Theme, ThemeStore, cli

MAIN_ST = 0
THEMES_ST = 1

#: One churn pass every five seconds: the theme is the subject here, and a table
#: restyling under it would compete with the color change.
PrimeRows.thaw_secs = 5.0


class DemoThemeStore(ThemeStore):
    """An in-memory ThemeStore: the demo remembers within one process."""

    def __init__(self) -> None:
        self.saved: str | None = None

    def load(self) -> str | None:
        return self.saved

    def save(self, name: str) -> None:
        self.saved = name


class ThemeMainScreen(DemoScreen):
    title = 'J-themes'
    SEMANTIC_ROLES = (Theme.SUCCESS, Theme.INFO, Theme.WARNING, Theme.EMPHASIS)

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'J-themes  [t]heme={Theme.theme_of(self.win)}  '
            f'[T]hemeScreen  [?]:help  [q]uit',
            mode='Underline',
            line_attr=cs.A_NORMAL,
        )
        self.add_header('Note: role rows use Appearance.semantic_attr()', attr=cs.A_DIM)
        for index, row in enumerate(self.app.rows[:40]):
            role = self.SEMANTIC_ROLES[index % len(self.SEMANTIC_ROLES)]
            self.add_body(row_line(row, self.app.iteration),
                          attr=Appearance.semantic_attr(role))

    def theme_screen_ACTION(self) -> None:
        """``T``: open the theme picker."""
        self.app.stack.push(self.app.themes, self.pick_pos)

    def cycle_theme_ACTION(self) -> None:
        """``t``: advance this window's theme without opening the picker."""
        self.app.cycle_theme()


class ThemeApp(DemoApp):
    title = 'J-themes'
    help_paragraphs = (
        't cycles this window through every theme, including mono, and saves '
        'the choice.  T opens the picker, where t does the same and the '
        'swatches show what each semantic role looks like.',
        'The theme list ends with mono.  It uses the terminal colors and a '
        'bold/reverse attribute hierarchy; a palette turns color back on.',
        'The picker remembers the last choice through its ThemeStore.  The '
        'table churns once every five seconds, so the color change is the only '
        'motion on screen.',
    )

    def __init__(self, backend: object | None = None,
                 singleton: bool = True,
                 store: ThemeStore | None = None) -> None:
        self.store = store
        super().__init__(backend=backend, singleton=singleton)

    def build_screens(self):
        self.main = ThemeMainScreen(self)
        picker_class = Theme.create_picker_screen(
            DemoScreen,
            cycle_key='t',
            store=self.store,
            captions={Theme.SUCCESS: ('DONE', 'Rows already processed')},
        )
        self.themes = picker_class(self)
        self.help = self.help_class(self)
        return [self.main, self.themes, self.help]

    def build_spinner(self):
        spin = self.new_spinner()
        # t is bound on two screens: on the picker it is the factory's own
        # spin_theme action (which also calls store.save()), and on the table it
        # is this demo's cycle_theme action.  T enters the picker.
        spin.add_key('spin_theme', 't - cycle theme', keys=[ord('t')],
                     genre='action', scope={THEMES_ST})
        spin.add_key('cycle_theme', 't - cycle theme', keys=[ord('t')],
                     genre='action', scope={MAIN_ST},
                     comments='Applies to this window and remembers the choice.')
        spin.add_key('theme_screen', 'T - theme screen', keys=[ord('T')],
                     genre='action', scope={MAIN_ST},
                     comments='The picker shows every semantic role as a swatch.')
        return spin

    def after_build(self) -> None:
        # Start on the theme the process actually chose (--theme, NO_COLOR,
        # or the window default).
        self.opts.theme = Theme.resolve(Theme.get_current())

    def apply_theme_choice(self, choice: str) -> None:
        """Make a cycle choice live on this window."""
        self.opts.theme = Theme.resolve(choice)
        self.win.set_theme(self.opts.theme)

    def cycle_theme(self) -> str:
        """Advance this window's theme, saving the choice like the picker."""
        names = Theme.list_all()
        current = self.opts.theme or Theme.theme_of(self.win)
        index = names.index(current) if current in names else -1
        choice = names[(index + 1) % len(names)]
        self.apply_theme_choice(choice)
        if self.store is not None:
            self.store.save(self.opts.theme)
        return self.opts.theme


def build_app(backend: object | None = None,
              singleton: bool = True,
              store: ThemeStore | None = None) -> ThemeApp:
    return ThemeApp(backend=backend, singleton=singleton, store=store)


def main() -> None:
    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='demo-j-themes'))
    args = parser.parse_args()
    cli.apply_display_arguments(args, prog='demo-j-themes')

    store = DemoThemeStore()
    if Theme.get_current() is None:
        # No --theme and no NO_COLOR: use the remembered choice, if any.
        Theme.set_active(Theme.initial(None, store))
    build_app(store=store).main_loop()


if __name__ == '__main__':
    main()
