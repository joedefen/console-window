"""console-window: a robust curses wrapper for building TUIs.

Public API (importable from the package root or from the
``console_window.ConsoleWindow`` compatibility module).
"""

__version__ = "2.0.1"

from .ConsoleWindow import (
    HOME_ST,
    NAVIGATION_KEYS,
    BasicHelpScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    IncrementalSearchBar,
    InlineConfirmation,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
)

__all__ = [
    'HOME_ST',
    'NAVIGATION_KEYS',
    'BasicHelpScreen',
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'Context',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'OptionSpinner',
    'Screen',
    'ScreenStack',
    'Theme',
]
