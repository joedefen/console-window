# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [2.0.1]

Internal overhaul — modularization and tests. The public API is unchanged and
fully backward compatible (`from console_window import ...` and
`from console_window.ConsoleWindow import ...` both continue to work).

### Added
- Unit-test suite (`tests/`, 77 tests, TTY-free) covering scroll/pick geometry,
  `IncrementalSearchBar` / `InlineConfirmation`, `OptionSpinner` scope
  subtraction, public-API compatibility, the `answer()`/`alert()` dialog fixes,
  and `set_demo_mode()` toggle/state handling.
- `console_window.geometry` — pure scroll/pick math extracted for testing:
  `cook_abut`, `compute_abut`, `calc_indicator`, `scroll_indicator_row`,
  `scroll_indicator_col`, `count_pickable_rows`, `find_pickable`.
- `console_window.__version__`.
- Explicit `__all__` in the package root and compatibility module.
- `[tool.pytest.ini_options]` in `pyproject.toml`.

### Changed
- Split the 3,815-line `console_window/ConsoleWindow.py` into focused modules:
  `window.py`, `theme.py`, `context.py`, `opts.py`, `widgets.py`, `spinner.py`,
  `screens.py`, `keys.py`, `signals.py`, `geometry.py`; `ConsoleWindow.py` is now
  a thin compatibility facade.
- Theme state unified into `Theme._current` (via `Theme.set_active()`); removed
  the split between `_current` and `CURRENT_THEME` that made
  `Theme.get_current()` return `None` after startup.
- SIGINT handling moved to an explicit `console_window.signals` policy API;
  removed the action-at-a-distance rebinding of module-level functions.
- `set_demo_mode()` now tests the resulting state rather than the argument.
- `add_fancy_header()` regex logic extracted into named helpers.

### Fixed
- `answer()` now records the screen read timeout in effect before the dialog and
  restores that value on every exit path (submit, TAB, ESC, ESC-ESC, too-small
  abort) instead of resetting to the class default `ConsoleWindow.timeout_ms`.
- `alert()` recomputes `self.rows`/`self.cols` from `getmaxyx()` before drawing,
  so a resize immediately before the call no longer causes a misdraw.
- Demo: the settings spinner keys (`v` view mode, `s` sort, `t` theme) now also
  work while the HELP screen is open — they are scoped to include `HELP_ST`.
  (Scoping logic itself was unchanged by the refactor; this was a demo-scope
  issue.)
- Removed retired `put_body()` references (docstring + `__main__` self-test now
  use `add_body()`).
- `Development Status` classifier aligned with the release; version bumped to
  `2.0.1`.

[2.0.1]: https://github.com/joedefen/console-window
