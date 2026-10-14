"""Guards for the public API and import compatibility after the module split."""

import importlib

import pytest

PUBLIC_NAMES = [
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'OptionSpinner',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'Theme',
    'Context',
    'Screen',
    'ScreenStack',
    'BasicHelpScreen',
    'HOME_ST',
    'NAVIGATION_KEYS',
]


def test_package_root_exports_all_public_names():
    pkg = importlib.import_module('console_window')
    for name in PUBLIC_NAMES:
        assert hasattr(pkg, name), f'console_window.{name} missing'


def test_package_all_matches_names():
    pkg = importlib.import_module('console_window')
    assert set(PUBLIC_NAMES) == set(pkg.__all__)


def test_compatibility_module_exports_all_public_names():
    # The historical import path must keep working.
    shim = importlib.import_module('console_window.ConsoleWindow')
    for name in PUBLIC_NAMES:
        assert hasattr(shim, name), f'console_window.ConsoleWindow.{name} missing'


def test_root_and_shim_reference_same_objects():
    pkg = importlib.import_module('console_window')
    shim = importlib.import_module('console_window.ConsoleWindow')
    assert pkg.ConsoleWindow is shim.ConsoleWindow
    assert pkg.OptionSpinner is shim.OptionSpinner
    assert pkg.Theme is shim.Theme


def test_new_submodules_exist():
    for mod in ('window', 'theme', 'context', 'opts', 'widgets',
                'spinner', 'screens', 'keys', 'signals', 'geometry', 'backend'):
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


def test_opts_defaults():
    from console_window import ConsoleWindowOpts
    opts = ConsoleWindowOpts()
    assert opts.head_line is True
    assert opts.dialog_return == 'ENTER'
    assert opts.min_cols_rows == (70, 20)
