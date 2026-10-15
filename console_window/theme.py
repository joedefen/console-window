from __future__ import annotations

import curses
from typing import ClassVar


class Theme:
    # Semantic color-pair IDs.  The pairs themselves are (re)initialized per theme
    # by Theme.set() and, at startup, by ConsoleWindow.start_curses().
    DEFAULT = 0      # Default terminal colors
    DANGER = 1       # For destructive operations (wipe prompts)
    SUCCESS = 2      # For completed operations
    WARNING = 3      # For caution/stopped states
    INFO = 4         # For informational states
    EMPHASIS = 5     # For emphasized text
    ERROR = 6        # For errors
    PROGRESS = 7     # For progress indicators
    HOTSWAP = 9      # For newly inserted devices (hot-swapped)
    OLD_SUCCESS = 10 # For completed operations (dimmer)

    # Current theme name — single source of truth, written by Theme.set() and by
    # Theme.set_active() (called from ConsoleWindow.start_curses()).
    _current: ClassVar[str | None] = None

    # Available themes
    THEMES: ClassVar[dict] = {
        'dark-mono': {
            'name': 'Dark Mono',
            'default_fg': 253,
            'default_bg': 232,
            1: (196, 232),  # DANGER
            2: (46, 232),   # SUCCESS - Bright green
            10: (28, 232),  # OLD_SUCCESS - Medium green, darker than SUCCESS but not too dark
            3: (226, 232),  # WARNING
            4: (51, 232),   # INFO
            5: (255, 232),  # EMPHASIS
            6: (196, 232),  # ERROR
            7: (39, 232),   # PROGRESS
            9: (208, 232),  # HOTSWAP
        },
        'light-mono': {
            'name': 'Light Mono',
            'default_fg': 233,
            'default_bg': 253,
            1: (196, 253),  # DANGER
            2: (34, 253),   # SUCCESS - Bright visible green on light background
            10: (22, 253),  # OLD_SUCCESS - Darker muted green, clearly darker than SUCCESS
            3: (208, 253),  # WARNING
            4: (25, 253),   # INFO
            5: (232, 253),  # EMPHASIS
            6: (196, 253),  # ERROR
            7: (27, 253),   # PROGRESS
            9: (166, 253),  # HOTSWAP
        },
        'default': {
            'name': 'Terminal Default',
            'default_fg': -1,
            'default_bg': -1,
            1: (1, -1),   # DANGER
            2: (2, -1),   # SUCCESS - Standard green
            10: (28, -1), # OLD_SUCCESS - Medium green, dimmer than bright SUCCESS
            3: (3, -1),   # WARNING
            4: (6, -1),   # INFO
            5: (7, -1),   # EMPHASIS
            6: (9, -1),   # ERROR
            7: (4, -1),   # PROGRESS
            9: (208, -1), # HOTSWAP
        },
        'solarized-dark': {
            'name': 'Solarized Dark',
            'default_fg': 244,
            'default_bg': 234,
            1: (160, 234),  # DANGER
            2: (70, 234),   # SUCCESS - Brighter solarized green, clearly bright
            10: (28, 234),  # OLD_SUCCESS - Darker muted green, clearly dimmer than SUCCESS
            3: (136, 234),  # WARNING
            4: (37, 234),   # INFO
            5: (230, 234),  # EMPHASIS
            6: (196, 234),  # ERROR
            7: (33, 234),   # PROGRESS
            9: (166, 234),  # HOTSWAP
        },
        'solarized-light': {
            'name': 'Solarized Light',
            'default_fg': 240,
            'default_bg': 230,
            1: (160, 230),  # DANGER
            2: (70, 230),   # SUCCESS - Brighter solarized green, clearly bright
            10: (28, 230),  # OLD_SUCCESS - Darker muted green, clearly dimmer than SUCCESS
            3: (166, 230),  # WARNING
            4: (37, 230),   # INFO
            5: (235, 230),  # EMPHASIS
            6: (196, 230),  # ERROR
            7: (33, 230),   # PROGRESS
            9: (208, 230),  # HOTSWAP
        },
        'gruvbox': {
            'name': 'Gruvbox Dark',
            'default_fg': 223,
            'default_bg': 235,
            1: (167, 235),  # DANGER
            2: (142, 235),  # SUCCESS - Gruvbox green
            10: (106, 235), # OLD_SUCCESS - Gruvbox medium green (dimmer)
            3: (214, 235),  # WARNING
            4: (109, 235),  # INFO
            5: (229, 235),  # EMPHASIS
            6: (203, 235),  # ERROR
            7: (109, 235),  # PROGRESS
            9: (208, 235),  # HOTSWAP
        },
        'nord': {
            'name': 'Nord',
            'default_fg': 252,
            'default_bg': 236,
            1: (203, 236),  # DANGER
            2: (150, 236),  # SUCCESS - Nord aurora green, bright
            10: (114, 236), # OLD_SUCCESS - Nord frost green (dimmer), darker but not too dark
            3: (220, 236),  # WARNING
            4: (116, 236),  # INFO
            5: (231, 236),  # EMPHASIS
            6: (203, 236),  # ERROR
            7: (136, 236),  # PROGRESS
            9: (208, 236),  # HOTSWAP
        },
    }

    @classmethod
    def get_current(cls) -> str | None:
        return cls._current

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls.THEMES.keys())

    @classmethod
    def set(cls, theme_name: str) -> bool:
        if theme_name not in cls.THEMES:
            return False

        if not curses.has_colors():
            return False

        cls._current = theme_name
        theme = cls.THEMES[theme_name]

        # Late import to avoid a circular import at module load time.
        from .window import ConsoleWindow

        # Set terminal background and foreground from theme
        if 'default_fg' in theme and 'default_bg' in theme:
            default_fg = theme['default_fg']
            default_bg = theme['default_bg']
            # Always update the default color pair and screen background
            # (even when -1, -1 to reset to terminal defaults)
            curses.init_pair(8, default_fg, default_bg)
            # Broadcast to *every* live window — there is no longer a single
            # process-wide "static" window to update.
            ConsoleWindow._apply_default_colors(curses.color_pair(8))

        # Reinitialize color pairs with new theme
        for color_id in [cls.DANGER, cls.SUCCESS, cls.OLD_SUCCESS, cls.WARNING,
                       cls.INFO, cls.EMPHASIS, cls.ERROR, cls.PROGRESS, cls.HOTSWAP]:
            if color_id in theme:
                fg, bg = theme[color_id]
                curses.init_pair(color_id, fg, bg)

        return True

    @classmethod
    def set_active(cls, theme_name: str) -> str:
        cls._current = theme_name
        return theme_name

    @classmethod
    def create_picker_screen(cls, base_class: type) -> type:
        class ThemePickerScreen(base_class):
            def draw_screen(self) -> None:
                app = self.app
                win = app.win

                win.set_pick_mode(False)

                # Get current theme name (may be empty string for default)
                current_theme = cls.get_current()
                display_theme = current_theme if current_theme else '(default)'

                # Add header showing current theme
                win.add_header(f'COLOR THEME:  {display_theme:^18}', attr=curses.A_BOLD)
                win.add_header('   Press [t] to cycle themes, ESC to return', resume=True)

                # Color purpose labels
                color_labels = [
                    (cls.DANGER, 'DANGER', 'Destructive operations'),
                    (cls.SUCCESS, 'SUCCESS', 'Completed operations'),
                    (cls.OLD_SUCCESS, 'OLD_SUCCESS', 'Older completed operations'),
                    (cls.WARNING, 'WARNING', 'Caution/stopped states'),
                    (cls.INFO, 'INFO', 'Informational states'),
                    (cls.EMPHASIS, 'EMPHASIS', 'Emphasized text'),
                    (cls.ERROR, 'ERROR', 'Errors'),
                    (cls.PROGRESS, 'PROGRESS', 'Progress indicators'),
                    (cls.HOTSWAP, 'HOTSWAP', 'Recently added items'),
                ]

                # Show color examples for this theme
                for color_id, label, description in color_labels:
                    # Create line with colored block and description
                    line = f'{label:12} ████████  {description}'
                    attr = curses.color_pair(color_id)
                    win.add_body(line, attr=attr)

            def spin_theme_ACTION(self) -> None:
                vals = cls.list_all()
                value = cls.get_current()
                idx = vals.index(value) if value in vals else -1
                value = vals[(idx+1) % len(vals)]  # choose next
                cls.set(value)
                self.app.opts.theme = value

        return ThemePickerScreen
