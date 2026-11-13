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
"""

from __future__ import annotations

import argparse
import curses as cs

from demo_kit import (
    DemoApp,
    DemoHelpScreen,
    DemoScreen,
    row_line,
)

from console_window import (
    Appearance,
    OptionSpinner,
    Theme,
    ThemeStore,
    cli,
)

MAIN_ST = 0
THEMES_ST = 1


class DemoThemeStore(ThemeStore):
    """An in-memory ThemeStore: the demo remembers within one process."""

    def __init__(self) -> None:
        self.saved: str | None = None

    def load(self) -> str | None:
        return self.saved

    def save(self, name: str) -> None:
        self.saved = name


class ThemeMainScreen(DemoScreen):
    title = 'themes'
    SEMANTIC_ROLES = (Theme.SUCCESS, Theme.INFO, Theme.WARNING, Theme.EMPHASIS)

    def draw_screen(self) -> None:
        self.set_pick_mode(False)
        self.add_fancy_header(
            f'themes  theme={Theme.theme_of(self.win)}  pass '
            f'{self.app.iteration}  [t]heme screen  [?]help  [q]uit',
            mode='Underline',
            line_attr=cs.A_DIM,
        )
        self.add_header('role rows use Appearance.semantic_attr()')
        for index, row in enumerate(self.app.rows[:40]):
            role = self.SEMANTIC_ROLES[index % len(self.SEMANTIC_ROLES)]
            self.add_body(row_line(row, self.app.iteration),
                          attr=Appearance.semantic_attr(role))

    def theme_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.themes, self.pick_pos)

    def help_screen_ACTION(self) -> None:
        self.app.stack.push(self.app.help, self.pick_pos)


class ThemeHelpScreen(DemoHelpScreen):
    def extra_help_paragraphs(self):
        return (
            'The theme list ends with mono.  It uses the terminal colors and a '
            'bold/reverse attribute hierarchy; a palette turns color back on.',
            'The picker remembers the last choice through its ThemeStore.',
        )


class ThemeApp(DemoApp):
    title = 'themes'

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
        self.help = ThemeHelpScreen(self)
        return [self.main, self.themes, self.help]

    def build_spinner(self):
        spin = OptionSpinner(stack=self.stack,
                             quit_keys=(ord('q'), ord('Q'), 0x3))
        # The factory's own action cycles the theme and calls store.save(), so
        # the choice is remembered without a second implementation here.
        spin.add_key('spin_theme', 't - cycle theme', keys=[ord('t')],
                     genre='action', scope={THEMES_ST})
        spin.add_key('theme_screen', 't - theme screen', keys=[ord('t')],
                     genre='action', scope={MAIN_ST})
        spin.add_key('help_screen', '? - help', keys=[ord('?')],
                     genre='action', scope={MAIN_ST})
        return spin

    def after_build(self) -> None:
        # Start on the theme the process actually chose (--theme, NO_COLOR,
        # or the window default).
        self.opts.theme = Theme.resolve(Theme.get_current())

    def apply_theme_choice(self, choice: str) -> None:
        """Make a cycle choice live on this window."""
        self.opts.theme = Theme.resolve(choice)
        self.win.set_theme(self.opts.theme)

    def handle_key(self, key: int) -> None:
        if self.win.prompt_active:
            self.win.handle_prompt_key(key)
            return
        if self.spin is not None and key in self.spin.keys:
            self.spin.do_key(key, self.win)
            return
        if key in (ord('q'), ord('Q'), 0x3):
            self.running = False


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
