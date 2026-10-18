# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `mypy` type checking for the library: `[tool.mypy]` in `pyproject.toml`
  checks `console_window` (`files`, `ignore_missing_imports`,
  `warn_unused_ignores`, `disallow_untyped_defs = false`) and a new `types` job
  in CI runs it on every push/PR. Ruff's `ANN` rules were already enforcing
  annotation *presence*; this enforces that the annotations are true
  (AUDIT.md §3.4).
- `[project.urls]` in `pyproject.toml` (Homepage / Repository / Issues /
  Changelog) so published package metadata carries project links.
- `ConsoleWindow(..., singleton=True)` restores the historical process-wide
  window model for applications that relied on it: `static_scr`/`static_win`
  are populated, every window shares one process screen and backend, and the
  unbound `ConsoleWindow.stop_curses()` tears it down. The first successful
  construction latches the mode; constructing another window with a different
  `singleton` value raises `AssertionError`. Pass `singleton=False` for
  independent per-instance screens and teardown (the test suite does).
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
- The package version now has a single source of truth: `pyproject.toml`
  declares `dynamic = ["version"]` and flit reads `__version__` from
  `console_window/__init__.py` (AUDIT.md §3.14). The stale manual-build recipe
  at the top of `pyproject.toml` is gone.
- `OptionSpinner.get_value()` is now a pure read: its `coerce` parameter is
  gone and initialisation moved to the explicit `OptionSpinner.normalize(attr)`,
  which `_register()` calls. Apps that read option values through
  `get_value()` are unaffected because `add_key()` already normalizes the value
  during registration; code that passed `coerce=True` directly should call
  `normalize()` instead (AUDIT.md §3.12).
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
- Navigation keys are responsive again. 2.0.0 made every body row pass through
  wide-character-aware `textwidth.truncate()`, which ran three `unicodedata`
  lookups per character on every full redraw; a 2,000-row screen spent ~39 ms
  of a ~41 ms frame there. Printable ASCII now takes a direct one-cell path,
  repeated `string_width()`/`truncate()` calls are memoised (a TUI redraws the
  same rows on each keypress), and non-ASCII glyph widths are cached. The same
  headless redraw is now ~4 ms, including mixed `✔`/`─`/`◆` rows.
- Hygiene debt from AUDIT.md §3.14: removed blank lines inside the
  `index_at_cell()`/`answer()` signatures and the commented-out assignment in
  `fix_positions()`; replaced `render()`'s `print()`/`except Exception` failure
  path with `logging` and `curses.error`; made `_BACKSPACE_KEYS` a single
  module constant; moved `ScreenStack`'s `SimpleNamespace` import to module
  level; stored navigation help as `NAV_KEY_LINES` so indentation cannot alter
  it; bounded `_NoopSurface.calls` to `MAX_CALLS`; and restored the hardware
  cursor in `CursesBackend.stop()`.
- The window no longer uses identity or sentinel tricks to decide what it is
  drawing. `_add()` takes an explicit `is_body` keyword from
  `add_header()`/`add_body()` instead of comparing `id(ns)` with `id(self.body)`,
  and `_warn_rows_dropped()` receives the pad name. The undocumented
  `last_pick_pos == -2` "clear every row" sentinel is replaced by the one-shot
  `_pick_clear_pending` flag, which `set_pick_mode()`/`set_pick_range()` set and
  `highlight_picked()` consumes; `last_pick_pos` is now only a row index or `-1`.
  A range change still repaints the picked row when its position is unchanged
  (AUDIT.md §3.13).
- The help screen no longer relies on `assert` to guard option rendering.
  `OptionSpinner._write_option_body()` now renders a dim `<unset: 'attr'>`
  placeholder when an application has deleted or cleared a registered option,
  so the row shows the same thing under `python -O` instead of falling through
  to `None` (AUDIT.md §3.12).
- `ConsoleWindowOpts` now rejects unknown option names with a `TypeError`
  instead of silently ignoring them. A typo such as
  `ConsoleWindowOpts(body_row=5000)` used to leave `body_rows` at its default
  and surface only later as discarded pad rows; construction now fails, and a
  `difflib` suggestion points at the intended name (`body_rows`). Multiple
  unknown keys are all reported (AUDIT.md §3.11).
- `answer()` no longer loops forever on `curses.error`, and it no longer uses
  `None` for both "user aborted" and "terminal too small". The recovery loop is
  bounded by `render_retry_seconds` and then re-raises; both too-small paths
  raise `TerminalTooSmallError` (ESC on the mid-dialog too-small notice still
  returns `None`, since that is a real abort). The dialog timeout is now
  restored in a `finally`, so it is also restored when `answer()` raises.
- Annotations that `mypy` exposed: `fix_positions()` is declared `-> int`
  (it returns `indent` and the caller uses it), `_draw_line_with_attrs()` and
  `_draw_plain_line()` accept `attrs: list | None`, `pick_range` is typed as
  `list[int] | tuple[int, int] | None`, and `draw()` accepts `str | bytes` to
  match its decode path. `ConsoleWindowOpts` attributes now have explicit types
  instead of being `object` values from `**kwargs`, and the full screen/pad API
  is described by the new `CursesSurface` protocol rather than `object`.
- Ctrl-C termination is now a process-lifetime latch. The first `ConsoleWindow`
  created with `ctrl_c_terminates=True` sets SIGINT to the default handler and
  no later window can install the key-delivery handler, even after that window
  stops. Previously `teardown_ctrl_c()` decided from whichever policy happened to
  be current, so window A (`False`, handler installed) → window B (`True`) →
  stop A left A's handler installed and Ctrl-C could no longer terminate. The
  latch is deliberately one-way: `ctrl_c_terminates=False` applies only while no
  terminating window has existed in the process (AUDIT.md §3.6).
- Aborting a `prompt`-genre spinner option (ESC in the `answer()` dialog) no
  longer wipes the stored value. `OptionSpinner.do_key()` wrote whatever
  `answer()` returned straight onto the attribute, and an aborted dialog returns
  `None`, so cancelling blanked the setting and the next read coerced it back to
  `''`. The prompt branch now treats `None` as "no change" and returns without
  touching the attribute (AUDIT.md §3.7).
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
- `ConsoleWindow` startup and `Theme.set()` now (re)initialise the same semantic
  colour pairs from the single `Theme.SEMANTIC_PAIRS` constant. Startup previously
  omitted `OLD_SUCCESS`, so it rendered on an uninitialised pair (effectively pair
  0) until the user changed theme. The magic pair id `8` is now the named
  `Theme.DEFAULT_BG`. `tests/test_theme.py` pins the shared list, the historic id
  and that both init paths agree (AUDIT.md §3.9).

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
