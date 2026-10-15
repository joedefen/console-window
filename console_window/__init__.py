"""console-window: a robust curses wrapper for building TUIs.

Public API, importable from the package root::

    from console_window import ConsoleWindow, ConsoleWindowOpts, OptionSpinner
"""

__version__ = "2.0.1"

from .context import Context
from .header import HeaderLine, Span
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .screens import HOME_ST, BasicHelpScreen, Screen, ScreenStack
from .spinner import OptionSpinner
from .theme import Theme
from .widgets import IncrementalSearchBar, InlineConfirmation
from .window import ConsoleWindow

__all__ = [
    'HOME_ST',
    'NAVIGATION_KEYS',
    'BasicHelpScreen',
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'Context',
    'HeaderLine',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'OptionSpinner',
    'Screen',
    'ScreenStack',
    'Span',
    'Theme',
]
