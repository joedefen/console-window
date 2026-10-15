# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `[project.urls]` in `pyproject.toml` (Homepage / Repository / Issues /
  Changelog) so published package metadata carries project links.

### Removed
- `console_window/ConsoleWindow.py`, the compatibility facade. Its filename
  shadowed the `ConsoleWindow` class and violated PEP 8 (ruff `N999`). The
  public API is unchanged for package-root imports (`from console_window import
  ...`), which is the documented style; only the legacy
  `from console_window.ConsoleWindow import ...` path is gone. The interactive
  self-test moved to `python -m console_window._selftest`.

## [2.0.1]

Internal overhaul — modularization and tests. The public API is unchanged and
fully backward compatible (`from console_window import ...` and
`from console_window.ConsoleWindow import ...` both continue to work).

### Added
- Unit-test suite (`tests/`, TTY-free) covering scroll/pick geometry,
  `IncrementalSearchBar` / `InlineConfirmation`, `OptionSpinner` scope
  subtraction, public-API compatibility, the `answer()`/`alert()` dialog fixes,
  `set_demo_mode()` toggle/state handling, `render()`'s retry cap, and the
  non-destructive `flash()` behaviour (`tests/test_flash.py`).
- `ConsoleWindow.flash_repaint` (repaint the underlying screen when `flash()`
  ends) and `ConsoleWindow.flash_poll_ms` (flash key-poll interval).
- `console_window.textwidth` — a stdlib-only (`unicodedata`-based) display-cell
  width toolkit (`char_width`, `string_width`, `truncate`, `ljust`/`rjust`,
  `cell_to_index`, `wrap_ranges`/`wrap_position`/`index_at_cell`, `wrap`),
  plus `tests/test_textwidth.py` and `tests/test_widechars.py`.
- `console_window.geometry` — pure scroll/pick math extracted for testing:
  `cook_abut`, `compute_abut`, `calc_indicator`, `scroll_indicator_row`,
  `scroll_indicator_col`, `count_pickable_rows`, `find_pickable`.
- `console_window.backend` — a `RenderBackend` abstraction with `CursesBackend`
  (real terminal) and `HeadlessBackend` (in-memory), plus `tests/test_backend.py`.
- `console_window.__version__`.
- Explicit `__all__` in the package root and compatibility module.
- `[tool.pytest.ini_options]` in `pyproject.toml`.
- GitHub Actions CI (`.github/workflows/ci.yml`) running the TTY-free suite on
  Python 3.8–3.13, plus a Ruff lint job backed by a `[tool.ruff]` config in
  `pyproject.toml`.
- Type annotations across the public API (every package module now uses
  `from __future__ import annotations`), enforced for the package by Ruff's
  `ANN` rules.

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
- Removed the process-wide `ConsoleWindow.static_scr`/`static_win` singletons:
  live windows are tracked in a weak-reference registry, teardown is per-instance
  (`stop_curses()`), `stop_all()` is the single `atexit` hook, and `Theme.set()`
  broadcasts to every live window via `_apply_default_colors()`. Multiple windows
  may now coexist, and one may be constructed without a terminal by passing
  `backend=HeadlessBackend()` to the constructor.
- Every package module opts into PEP 563 (`from __future__ import annotations`)
  so the modern `X | None` annotations remain valid on Python 3.8.
- `add_fancy_header()` regex logic extracted into named helpers.

### Fixed
- `answer()` now records the screen read timeout in effect before the dialog and
  restores that value on every exit path (submit, TAB, ESC, ESC-ESC, too-small
  abort) instead of resetting to the class default `ConsoleWindow.timeout_ms`.
- `alert()` recomputes `self.rows`/`self.cols` from `getmaxyx()` before drawing,
  so a resize immediately before the call no longer causes a misdraw.
- `flash()` is now non-destructive and interruptible: it polls for a key
  (`flash_poll_ms`) instead of `time.sleep`ing, so it can be dismissed early —
  and any key pressed is preserved in `pending_keys` for the next `prompt()`
  rather than being swallowed. A resize while the message is up redraws it, and
  on exit the underlying screen is repainted from the pads (`flash_repaint`)
  instead of being left blank; the pre-flash read timeout is restored on every
  exit path.
- Width arithmetic is now **display-cell aware** (wide CJK/emoji = 2 cells,
  combining marks/ZWJ = 0) throughout the render pipeline: `_add`, `draw`,
  `highlight_picked`/`_draw_line_with_attrs` (highlight columns map to
  code-point indices), `add_fancy_header`, `flash`, `alert`, and the `answer()`
  display/editor (cell-accurate wrapping and cursor placement) — fixing
  misalignment for the wide characters the demo already uses.
- `render()` now bounds its transient-error retry loop by wall-clock time
  (`ConsoleWindow.render_retry_seconds`, default 2 s) instead of a fixed 128
  iterations, so a reproducible `curses.error` aborts quickly with the
  diagnostic dump rather than freezing the UI for ~20 s.
- Demo: the settings spinner keys (`v` view mode, `s` sort, `t` theme) now also
  work while the HELP screen is open — they are scoped to include `HELP_ST`.
  (Scoping logic itself was unchanged by the refactor; this was a demo-scope
  issue.)
- `ScreenStack.__init__(screen_objects=...)` annotated as `dict | None` (fixes the
  implicit-`Optional` finding, Ruff RUF013); removed redundant `int(round(...))`
  casts (RUF046) and trailing whitespace in `widgets.py` (W291); dropped an
  unused local in `tests/test_spinner.py` (F841).
- Removed retired `put_body()` references (docstring + `__main__` self-test now
  use `add_body()`).
- `Development Status` classifier aligned with the release; version bumped to
  `2.0.1`.

[2.0.1]: https://github.com/joedefen/console-window
