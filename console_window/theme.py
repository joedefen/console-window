"""Theme and color-pair management for console_window.

The active theme name is stored in the single attribute :attr:`Theme._current`
and queried with :meth:`Theme.get_current`.  (Previously the startup path wrote a
separate ``CURRENT_THEME`` attribute, leaving ``get_current()`` returning None
after boot — that split has been removed.)
"""

import curses
import os


class Theme:
    """Theme and color management for ConsoleWindow"""

    # Semantic color pair constants (initialized in start_curses based on theme)
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

    # Current theme name (set in start_curses / Theme.set)
    _current = None

    # Available themes
    THEMES = {
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
    def get_current(cls):
        """Get the name of the currently active color theme."""
        return cls._current

    @classmethod
    def list_all(cls):
        """List all available color themes."""
        return list(cls.THEMES.keys())

    @classmethod
    def set(cls, theme_name):
        """Change the current theme and reinitialize color pairs.

        Args:
            theme_name: Name of theme from THEMES dict

        Returns:
            bool: True if theme was set, False if invalid theme or colors not supported
        """
        if theme_name not in cls.THEMES:
            return False

        if not curses.has_colors():
            return False

        cls._current = theme_name
        # Update environment variable so it persists for session
        os.environ['DWIPE_THEME'] = theme_name
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
            if ConsoleWindow.static_scr:
                ConsoleWindow.static_scr.bkgd(' ', curses.color_pair(8))
            # Also update pads if window exists
            if ConsoleWindow.static_win:
                ConsoleWindow.static_win.head.pad.bkgd(' ', curses.color_pair(8))
                ConsoleWindow.static_win.body.pad.bkgd(' ', curses.color_pair(8))

        # Reinitialize color pairs with new theme
        for color_id in [cls.DANGER, cls.SUCCESS, cls.OLD_SUCCESS, cls.WARNING,
                       cls.INFO, cls.EMPHASIS, cls.ERROR, cls.PROGRESS, cls.HOTSWAP]:
            if color_id in theme:
                fg, bg = theme[color_id]
                curses.init_pair(color_id, fg, bg)

        return True

    @classmethod
    def set_active(cls, theme_name):
        """Record the active theme name without reinitializing color pairs.

        Used by :meth:`ConsoleWindow.start_curses` once it has already applied
        the theme's color pairs.

        :param theme_name: Name of the theme to record as active
        :returns: The recorded theme name
        :rtype: str
        """
        cls._current = theme_name
        return theme_name

    @classmethod
    def create_picker_screen(cls, base_class):
        """
        Create a theme picker screen class dynamically.

        Args:
            base_class: The Screen base class to inherit from

        Returns:
            A new class that displays all themes and allows cycling through them

        Usage:
            ThemeScreen = Theme.create_picker_screen(Screen)
            screens[THEME_ST] = ThemeScreen(app)
        """
        class ThemePickerScreen(base_class):
            """Theme preview screen showing all available themes with color examples"""

            def draw_screen(self):
                """Draw the theme screen with color examples for all themes"""
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

            def spin_theme_ACTION(self):
                """Handle 't' key - cycle through themes"""
                vals = cls.list_all()
                value = cls.get_current()
                idx = vals.index(value) if value in vals else -1
                value = vals[(idx+1) % len(vals)]  # choose next
                cls.set(value)
                self.app.opts.theme = value

        return ThemePickerScreen
