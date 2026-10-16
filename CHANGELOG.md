# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `[project.urls]` in `pyproject.toml` (Homepage / Repository / Issues /
  Changelog) so published package metadata carries project links.
- `ConsoleWindow.rows_dropped`, counting the rows `add_body()`/`add_header()`
  discard once that pad has reached `opts.body_rows` / `opts.head_rows`. The
  first discarded row of each fill episode also emits a `UserWarning` naming the
  pad and the option to raise. Overflow previously left no trace, so an
  under-sized pad showed up only as missing content. The behaviour is
  deliberately non-fatal: the excess is still discarded and the app keeps
  running, `-W error::UserWarning` turns it into a hard failure for anyone who
  wants that, and `clear()` re-arms the warning for the next fill.
- A headless harness for the interactive core: `HeadlessBackend.queue_keys()`
  feeds ordered key codes to the screen's `getch()`, and the new
  `tests/test_interactive.py` (43 tests) drives `prompt()` and its navigation,
  `render()`/`draw()`, the `answer()` dialog and the resize-recovery path
  without a TTY. Coverage of `window.py` rises from 55% to 84% (missing
  statements 444 → 161), so the half of the engine users actually feel is now
  smoke-tested in CI (AUDIT.md §3.2).

### Changed
- Raised the minimum supported Python to **3.10** (was 3.8): `requires-python =
  ">=3.10"`, the Ruff `target-version` is now `py310`, and the CI matrix drops
  the 3.8/3.9 legs. The 3.8 floor was never real — [`backend.py`](console_window/backend.py:35)
  calls `curses.set_escdelay()`, which is new in 3.9, so every
  `ConsoleWindow()` raised `AttributeError` on 3.8. 3.10 is a deliberate floor
  rather than the bare 3.9 that `set_escdelay` would have permitted.
- Renamed `ConsoleWindowDemo.py` to `SampleApp.py`: the old name collided with
  the library's own `set_demo_mode()` feature. Updated [`runner`](runner:1), the
  README, the ruff per-file-ignores and the headless smoke tests
  (`tests/test_sample_app.py`) to match. The classes inside are still named
  `DemoApp`/`DemoScreen`.

### Fixed
- `ConsoleWindow.alert()` now actually scrolls. It used to build a pad sized to
  the whole message but always refresh it at offset 0, so content taller than the
  box was silently unreachable despite the "scrollable if needed" comment. The
  content is now reachable with `j`/`k`, the arrow keys, PageUp/PageDown (and
  Ctrl-B/Ctrl-F/Space) and Home/End, and the box's left border shows `▲`/`▼`
  markers when content extends past the fold. The `_height`/`_width` parameters,
  previously accepted and ignored, now cap the (centred) box; passing `None`
  keeps the previous full-box, 1-cell-margin geometry.
- `alert()` no longer reaches around the backend seam: it builds its content pad
  through `RenderBackend.newpad()` and drives its own key loop rather than calling
  module-level `curses.newpad()`/`curses.newwin()`/`Textbox`. It therefore runs
  under `HeadlessBackend` and is covered by the new `alert()` tests in
  `tests/test_interactive.py`; the `Textbox` monkeypatch in `tests/test_dialogs.py`
  is gone, along with the now-unused `_textbox_edit_on_enter()` helper (AUDIT.md
  §3.3).
- `answer()`, `flash()` and the shared render/dialog helpers no longer call the
  process-global `curses.doupdate()`/`curs_set()`/`update_lines_cols()`/
  `is_term_resized()` directly. Four matching methods were added to
  `RenderBackend`, implemented by `CursesBackend` (delegating to curses) and
  `HeadlessBackend` (recording no-ops), so the dialogs are backend-driven end to
  end and the `curs_set`/`doupdate` monkeypatches are gone from `tests/test_dialogs.py`
  (AUDIT.md §3.3).

### Removed
- `console_window/_selftest.py`, the TTY-only dev self-test. The old
  `python -m console_window._selftest` entry point is gone; the features it
  demonstrated — multi-row picking, a prompt-style option, forced
  `render(redraw=True)`, `Ctrl-C` as an application key, large-body stress and
  `ConsoleWindow.primary_window()` recovery — were folded into `SampleApp.py`,
  which is now covered by headless smoke tests (`tests/test_sample_app.py`).
- All docstrings from the package, the test suite, the demo and the `runner`
  script (305 in total, across 29 files). Nothing consumed them via `__doc__`,
  `inspect.getdoc()` or `help()` (verified by grep), so runtime behaviour and the
  public API are unchanged; statement order, bodies and the blank-line layout
  around definitions were preserved.
- The `DWIPE_THEME` environment variable. `Theme.set()` no longer exports it and
  the startup path reads `Theme.get_current()` instead of `os.environ`, making
  `Theme` state the single source of truth. The library no longer namespaces its
  config under a downstream app's name (`dwipe` never read the variable) and no
  longer leaks the theme value into child processes via the inherited
  environment.
- `console_window/ConsoleWindow.py`, the compatibility facade. Its filename
  shadowed the `ConsoleWindow` class and violated PEP 8 (ruff `N999`). The
  public API is unchanged for package-root imports (`from console_window import
  ...`), which is the documented style; only the legacy
  `from console_window.ConsoleWindow import ...` path is gone. The interactive
  self-test moved to `python -m console_window._selftest`.

### Fixed
- Scrolling could not reach non-pickable `DECOR` rows that sit past the last
  pickable row (or before the first one).  In pick mode the frame's
  pick-visibility clamp in [`_adjust_scroll_for_abut()`](console_window/window.py:862)
  reset `scroll_pos` back to `pick_pos` every frame, so the SampleApp's `z`
  "stress" mode created 2000 filler rows that were unreachable — the view showed
  the last pickable row plus one screen of filler and the scroll indicator sat
  near the start.  Movement is now allowed to scroll past the pick (a new
  `free_scroll` state) while the pick can find no pickable row in the requested
  direction; the clamp is skipped in that state and restored as soon as a real
  pick move resynchronises the view.  The blocked-move scroll amount is now the
  *requested* delta rather than a single row, so page keys and `HOME`/`END`
  traverse a `DECOR` block too, and the scroll indicator follows the viewport
  while free-scrolling instead of the parked pick.
- `SampleApp.py` asked for `head_rows=4`, but the help screen's nav-key block is
  five header rows, so the last line was being clipped in silence. Raised to 8,
  and the pad-sizing comment now records what each pad has to hold. The bug was
  found by the overflow signal above, which this project's own suite now
  enforces (`filterwarnings = ["error::UserWarning"]` in `pyproject.toml`) so
  that neither the sample app nor the library's own helpers can quietly regress
  that way again.

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
