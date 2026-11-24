"""A robust curses wrapper for building terminal user interfaces."""

__version__ = "3.1.1"

from ._appearance import (
    MONO_ROLES,
    Appearance,
    colors_enabled,
    resolve_appearance,
    semantic_attr,
    set_colors_enabled,
)
from .context import Context
from .glyphs import Glyph, Glyphs
from .header import HeaderLine, Span
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .screens import (
    HOME_ST,
    BasicHelpScreen,
    BasicTextScreen,
    Screen,
    ScreenStack,
)
from .signals import reset_ctrl_c
from .spinner import OptionSpinner
from .theme import Theme, ThemeStore
from .widgets import IncrementalSearchBar, InlineConfirmation, PromptLine
from .window import ConsoleWindow, TerminalTooSmallError

__all__ = [
    'HOME_ST',
    'MONO_ROLES',
    'NAVIGATION_KEYS',
    'Appearance',
    'BasicHelpScreen',
    'BasicTextScreen',
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'Context',
    'Glyph',
    'Glyphs',
    'HeaderLine',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'OptionSpinner',
    'PromptLine',
    'Screen',
    'ScreenStack',
    'Span',
    'TerminalTooSmallError',
    'Theme',
    'ThemeStore',
    'colors_enabled',
    'reset_ctrl_c',
    'resolve_appearance',
    'semantic_attr',
    'set_colors_enabled',
]
