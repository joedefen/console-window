import importlib.util

import pytest

PUBLIC_NAMES = [
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'OptionSpinner',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'PromptLine',
    'Theme',
    'Context',
    'Screen',
    'ScreenStack',
    'BasicHelpScreen',
    'BasicTextScreen',
    'HeaderLine',
    'Span',
    'HOME_ST',
    'NAVIGATION_KEYS',
    'TerminalTooSmallError',
    'reset_ctrl_c',
]


def test_package_root_exports_all_public_names():
    pkg = importlib.import_module('console_window')
    for name in PUBLIC_NAMES:
        assert hasattr(pkg, name), f'console_window.{name} missing'


def test_package_all_matches_names():
    pkg = importlib.import_module('console_window')
    assert set(PUBLIC_NAMES) == set(pkg.__all__)


def test_legacy_consolewindow_module_is_removed():
    # The module name shadowed the class and violated PEP 8 (ruff N999); it was
    # removed now that every consumer imports from the package root.
    assert importlib.util.find_spec('console_window.ConsoleWindow') is None
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('console_window.ConsoleWindow')


def test_consolewindow_attribute_is_the_class_not_a_module():
    import console_window
    # `console_window.ConsoleWindow` is the class re-exported from window.py.
    assert isinstance(console_window.ConsoleWindow, type)
    assert console_window.ConsoleWindow.__module__ == 'console_window.window'
    assert console_window.OptionSpinner.__module__ == 'console_window.spinner'
    assert console_window.Theme.__module__ == 'console_window.theme'


def test_new_submodules_exist():
    for mod in ('window', 'theme', 'context', 'opts', 'widgets', 'spinner',
                'screens', 'keys', 'signals', 'geometry', 'backend',
                'header', 'textwidth'):
        importlib.import_module(f'console_window.{mod}')


def test_theme_state_is_unified():
    # Regression guard for the old split between _current and CURRENT_THEME.
    from console_window import Theme
    original = Theme._current
    try:
        Theme._current = 'nord'
        assert Theme.get_current() == 'nord'
    finally:
        Theme._current = original


def test_theme_set_rejects_unknown_without_curses():
    from console_window import Theme
    assert Theme.set('does-not-exist') is False


def test_theme_lists_expected_themes():
    from console_window import Theme
    themes = Theme.list_all()
    for expected in ('default', 'nord', 'gruvbox', 'dark-mono', 'light-mono'):
        assert expected in themes


def test_opts_validates_dialog_abort():
    from console_window import ConsoleWindowOpts
    with pytest.raises(ValueError):
        ConsoleWindowOpts(dialog_abort='NOPE')


def test_opts_validates_dialog_return():
    from console_window import ConsoleWindowOpts
    with pytest.raises(ValueError):
        ConsoleWindowOpts(dialog_return='SPACE')


def test_opts_rejects_unknown_key():
    from console_window import ConsoleWindowOpts
    with pytest.raises(TypeError, match=r"unknown option\(s\): 'body_row'"):
        ConsoleWindowOpts(body_row=5000)


def test_opts_unknown_key_suggests_the_closest_name():
    from console_window import ConsoleWindowOpts
    with pytest.raises(TypeError, match="did you mean 'body_rows'"):
        ConsoleWindowOpts(body_row=5000)


def test_opts_rejects_every_unknown_key():
    from console_window import ConsoleWindowOpts
    with pytest.raises(TypeError) as excinfo:
        ConsoleWindowOpts(body_row=5000, head_row=8)
    message = str(excinfo.value)
    assert "'body_row'" in message
    assert "'head_row'" in message


def test_nav_help_lines_are_stored_without_dedent_magic():
    from console_window.window import NAV_KEY_LINES, ConsoleWindow
    assert NAV_KEY_LINES
    assert ConsoleWindow.get_nav_key_lines() is NAV_KEY_LINES
    assert ConsoleWindow.get_nav_keys_blurb() == '\n'.join(NAV_KEY_LINES)


def test_opts_defaults():
    from console_window import ConsoleWindowOpts
    opts = ConsoleWindowOpts()
    assert opts.head_line is True
    assert opts.dialog_return == 'ENTER'
    assert opts.min_cols_rows == (70, 20)
