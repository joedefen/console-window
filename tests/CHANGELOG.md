# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [2.1.3]

### Added
- `console_window.glyphs`: one registry for every decorative symbol the UI
  draws, each with a plain-ASCII fallback (`Glyph`, `BUILTIN_GLYPHS`, `Glyphs`).
  `Glyphs.register()` / `register_many()` add application vocabulary,
  `Glyphs.get()` returns the form for the active mode, `Glyphs.unicode_of()` and
  `Glyphs.probe_text()` always return the real glyphs (for a font check), and
  `Glyphs.reset()` drops app registrations — the suite does it in an autouse
  fixture because the mode is process state.
  `Glyphs.apply_policy()` decides the mode from an explicit request, the
  `CONSOLE_WINDOW_GLYPHS` variable (`auto`/`ascii`/`unicode`), or detection, in
  that order; `Glyphs.ensure_policy()` runs detection at most once per process,
  so a window constructed later cannot undo an earlier decision.
  `Glyphs.transliterate()` rewrites registered decoration and nothing else, so
  real UTF-8 content is never altered.  `CONSOLE_WINDOW_GLYPH_AUDIT=1` logs
  unregistered decoration together with the `register()` call that would fix it.
- `ConsoleWindowOpts(ascii=None, glyphs=None, glyphs_probe=())`, plus
  `ConsoleWindow.ascii_mode` and `ConsoleWindow.glyph(name)`.  `ascii` seeds the
  process-wide mode, `glyphs` registers the app's vocabulary, and `glyphs_probe`
  chooses the font-check order.
- `console_window.cli`: `add_display_arguments(parser)` and
  `apply_display_arguments(args)`.  `--ascii` takes an optional boolean
  (`--ascii`, `--ascii=no`) and `--glyphs {auto,ascii,unicode}` is its symmetric
  counterpart (`--glyphs` wins when both are given).  `--theme` is added with
  the installed theme names as choices and seeds the first window's theme.
- `console_window.help`: `theme_paragraph()` and `glyph_paragraph()`, plus
  `Screen.extra_help_paragraphs()` and `BasicHelpScreen.draw_notes()` /
  `show_display_notes = True`, which wrap and dim the result.  The flag is off
  by default so an existing help screen keeps its exact output.
- `Theme.create_picker_screen(base, cycle_key=None, store=None, note=None)`: the
  hint line names the key actually bound to `spin_theme` (discovered from the
  spinner, default `t`), `store.save()` remembers the choice after each cycle
  (a failing store is logged, never raised), and `note` adds one dim line.
- `Theme.initial(cli_theme, store)` and the `ThemeStore` protocol
  (`load()`/`save()`).  The library never opens a file, so the app keeps owning
  the path, the format and the permissions.

### Changed
- Decorative literals the library used to hard-code now come from the registry:
  the widget cursors (`│`, `█`), the resolved-choice marker (`⮞`), the help-list
  bullet (`·`), the dialog scroll arrows (`◀`/`▶`), the alert scroll markers
  (`▲`/`▼`), the help-legend arrows (`←`/`→`), the theme swatch (`█`), and the
  `flash()` message box.  Unicode output is unchanged; in ASCII mode the same
  paths paint `|`, `#`, `>`, `.`, `<`, `>`, `^`, `v`, `<-`, `->` and a `+---+`
  box.
- `InlineConfirmation.get_display_string()`,
  `IncrementalSearchBar.get_display_string()` and
  `IncrementalSearchBar.as_header_line()` accept `cursor_char=None` to mean "the
  registered glyph".  An explicit character still wins.
- `Theme.create_picker_screen()`'s new parameters are keyword-only, so existing
  subclasses and call sites are unaffected.

### Notes
- Behaviour change worth knowing: on a terminal that cannot encode UTF-8 (or
  with `TERM=dumb`) a window now starts in ASCII mode by itself.  That is the
  point of the release; `CONSOLE_WINDOW_GLYPHS=unicode` and
  `ConsoleWindowOpts(ascii=False)` are the escape hatches.
- The message-box frame uses registered glyphs rather than `curses.ACS_*`, so it
  degrades on any backend (including the headless one) and stays assertable in
  tests.

## [2.1.0]

### Added
- `ConsoleWindow.status(text='', level='info', timeout=None, attr=None)`: a
  one-line message painted on the separator row (the row that owns the scroll
  indicator), so the listing stays visible.  `level` selects an attribute from
  the patchable `ConsoleWindow.STATUS_LEVELS` map (`info` dim, `warn` bold,
  `error` bold+reverse); an unknown level falls back to `info` rather than
  raising, and `attr` overrides the level for one message.  `timeout` is
  evaluated lazily at draw time.  The text starts at column 0 of
  `head.view_cnt` and leaves one blank cell before the scroll indicator; when
  no separator row exists the text is stored (the call returns `False`) and a
  later resize reveals it.  Also `clear_status()` and the `current_status`
  property.  `status()` never renders by itself; the message appears on the next
  `render()`/`prompt()`.
- `PromptLine`: a window-independent in-place prompt with a fixed display
  format (`f'{prompt}  [Press "{mode}" or ESC]'` for `Y`/`y`, otherwise
  `f'{prompt}: {buffer}{caret}{rest}'`), hint truncation and resolved-choice
  lines (`⮞ choice`).  `take()` returns the answer and callbacks without running
  them.  `InlineConfirmation.resolved_choice` is the public wrapper over the
  existing private resolution.
- `ConsoleWindow` prompt lifecycle: `prompt_active`, `begin_prompt()`,
  `end_prompt()`, `handle_prompt_key()`, `add_prompt_header()` and
  `add_prompt_lines()`.  While a prompt is active the application routes every
  key through `handle_prompt_key()`; completion callbacks run after the prompt
  is torn down and passthrough is restored, so a callback may begin the next
  prompt.
- `BasicTextScreen`: a read-only `Screen` for preformatted lines under optional
  headers.  It resolves `app.win` at draw time, disables pick mode, and adds
  body rows without `Context` so normal navigation scrolls them.

### Changed
- Demo-mode key labels no longer fall back to `???` for anything curses can
  name: `curses.KEY_*` codes are rendered from the curses constant names (so a
  taken `KEY_LEFT`/`KEY_RIGHT` shows `LEFT`/`RIGHT`, and F-keys, shift-arrows,
  `HOME`, `RESIZE`, etc. show their own names), control characters use caret
  notation (`^U`), and a code curses does not know is shown as `<code>`.
- `SampleApp.py` now exercises the new API: `SPACE` uses the window prompt
  lifecycle with a `PromptLine` single-key confirmation, `N` adds a buffered
  header note prompt, non-modal feedback uses `status()`, and the HISTORY
  screen is built from `BasicTextScreen` with `set_text()` on every draw.

### Notes
- `flash()` is documented as clearing the screen; that difference is why
  `status()` exists for messages that must leave the listing visible.

## [2.0.2]

### Added
- `ConsoleWindowOpts(taken_nav_keys=...)`: hand specific navigation keys to the
  application on a per-window basis. The value is a mapping of
  `{key_code: help_label}` (a bare iterable of key codes is also accepted and
  normalizes to empty labels), so the help screen can show what the app bound
  them to (`←: prev`). The normalized mapping is available as
  `opts.taken_nav_keys`, and the effective set as `opts.nav_keys` (a
  `frozenset` of `NAVIGATION_KEYS` minus the taken keys).
- `OptionSpinner(nav_keys=...)`: the spinner validates `add_key()` against the
  supplied set instead of the module global, so
  `OptionSpinner(nav_keys=opts.nav_keys)` accepts a key the window took.
- `ConsoleWindow.nav_help_lines()`: renders navigation help for the window's
  effective key set and appends a separate `App:` line for taken keys with
  their labels. `OptionSpinner.show_help_nav_keys(win)` now uses it.

### Changed
- Navigation help is generated from the structured `NAV_HELP_ROWS` table, so a
  key the app took disappears from the rendered help instead of being
  advertised and doing nothing. `NAV_KEY_LINES`, `get_nav_key_lines()` and
  `get_nav_keys_blurb()` remain the static default output, and the default
  rendering is unchanged.
- `_navigation_target()` refuses a taken key before consulting its movement
  table. Subtracting from `NAVIGATION_KEYS` alone was not enough: UP/DOWN,
  page and HOME/END movements are dispatched by that hardcoded table, so a
  taken key would still have scrolled.
- Demo-mode highlighting and passthrough classification treat taken keys as
  application keys, and `_handle_prompt_app_key()` no longer treats them as
  navigation.
- `NAVIGATION_KEYS` is still a `set` for 2.0 compatibility, but the library no
  longer mutates it. Applications should pass `taken_nav_keys` (and can delete
  their `NAVIGATION_KEYS.remove(...)` monkeypatches); two windows with
  different bindings no longer contaminate each other.

### Notes
- A taken key is withdrawn from *navigation dispatch* only. Text editing
  (`_DIALOG_SIMPLE_MOVES`, widget carets, dialogs) still uses
  LEFT/RIGHT/HOME/END normally.
- Return behaviour follows the existing `handled_keys`/`relax_handled_keys`
  rules: a taken key bound through the spinner is returned; with
  `relax_handled_keys=False` and no binding it may still be swallowed.
- Invalid entries (non-integer key codes) raise `ValueError`; duplicate codes
  collapse to one binding. Codes that are not navigation keys are kept but
  logged as having no effect, and taking every vertical key logs a
  "reduced navigation" warning instead of failing.

## [Unreleased]

### Added
- `line_attr` on `add_fancy_header()`/`add_header_line()`: an attribute OR'd
  into every span of the header (including plain spans and the raw line emitted
  for `mode='Off'`), so a caller can dim a whole fancy header while keeping the
  per-span bold/underline/reverse styling.
- `answer_hint` on `begin_prompt()`/`PromptLine.start()`: replaces the default
  trailing `[Press "y" or ESC]` text for the `Y`/`y` modes, with `{mode}`
  substituted for the live mode letter.  The template is plain text (`.replace`,
  not `.format`), so an application can bracket its own question, e.g.
  `'["{mode}" or ESC] ⚠️'`, without escaping braces.
- `add_prompt_header(align='center')`: pads the prompt row so it sits in the
  middle of the pad width.  The offset is measured in display cells from the
  composed line, so wide glyphs and emoji presentation selectors stay centred.
- `ConsoleWindow.prompt_separator_attr`: an attribute applied to the separator
  rule only while an in-place prompt is live (`None`, the default, keeps the
  rule plain).  Lets the chrome recede behind the one line keys can reach.
- `suspend_curses()`/`resume_curses()` on `ConsoleWindow`: leave curses mode
  with `endwin()` while keeping the window (pads, content model, pick state)
  alive, then reattach a screen and repaint.  This is the supported way for an
  app to shell out to a command or an editor and come back.  The pads survive
  because `endwin()` restores the terminal without destroying the curses
  SCREEN; `resume_curses()` refreshes the screen handle, backend, dimensions,
  pad backgrounds and redraw bookkeeping.
- Singleton-mode compatibility for the pre-2.0 start/stop pair:
  `stop_curses()` now *suspends* the shared screen and `start_curses()`
  resumes it, so `stop_curses(); ...; start_curses()` works again (this is what
  efibootdude's write/reboot paths needed).  `ConsoleWindow.stop_all()` remains
  the permanent teardown and is the atexit hook; per-instance windows keep
  `stop_curses()` as a one-way teardown and use suspend/resume explicitly.
- Per-window themes. `ConsoleWindow.theme` records the theme a window is on,
  `ConsoleWindowOpts(theme=...)` seeds it, and `ConsoleWindow.set_theme()`
  switches it: colours are reinstalled through the window's own backend (curses
  keeps one pair table per terminal, so installing a palette still affects the
  shared screen) and that window's pads are repainted. `Theme.set()` remains the
  process-wide switch and now relabels every live window. Startup, `Theme.set()`
  and `set_theme()` install colours from the single `Theme.pair_specs()` list,
  so the three paths cannot drift apart (AUDIT.md §3.1).
- `reset_ctrl_c()` (also exported from the package root) restores the SIGINT
  handler that was installed before the first window and clears the Ctrl-C
  policy latch, for embedding applications that manage SIGINT themselves
  (AUDIT.md §3.1).
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
- `InlineConfirmation` is now a real line editor, matching the
  `IncrementalSearchBar` beside it: `start(..., initial='')` seeds the buffer
  with the caret at the end, and `LEFT`/`RIGHT`/`HOME`/`END` (also Ctrl-A/
  Ctrl-E), `KEY_DC` and Backspace edit at the caret instead of only appending.
  `cursor_pos` exposes the string index, `cursor_cell` the terminal column
  (measured with `textwidth`), and `get_display_string(prompt='',
  cursor_char='│')` renders the prompt plus the caret for a body row.
  Movement, insertion and deletion use the `textwidth` helpers so wide
  characters and combining marks cannot split a grapheme.
- `ConsoleWindow.temp_handled_keys(*keys)`: a context manager that adds keys to
  `handled_keys` for one prompt and removes only the keys it actually added, so
  an application key can be forwarded reversibly and nested uses leave existing
  bindings intact.

### Changed
- Passthrough mode now forwards ESC (`27`) and Delete (`curses.KEY_DC`) as
  editing keys, in addition to printable characters, Backspace, the arrow keys
  and Home/End. This closes the gap that forced every `InlineConfirmation`
  caller to discover `win.handled_keys.add(27)` to receive the cancel key; the
  resize-abort path already treated `27` as an application key when bound, so
  the behaviour is consistent rather than a silent widening.
- Every `pylint` warning now states why it is deliberate (AUDIT.md §3.3), taking
  `pylint --disable=C,R` from 9.94/10 to **10.00/10**. Protected-access and
  protocol-signature findings carry scoped disables with an adjacent reason,
  `_paint_alert()`'s genuinely unused `row9` parameter was removed, and the
  `getattr` + `callable()` call site uses `disable-next`. No runtime behaviour
  changed.
- The example's application class is now `SampleApp` (was `DemoApp`), matching
  the module filename and the package name. The screen base class keeps its
  `DemoScreen` name; only the app class and its construction site changed.
- `answer()`'s recovery policy is now documented rather than implicit
  (AUDIT.md §3.2): the retry loop deliberately shares the class-level
  `render_retry_seconds`/`render_retry_interval` budget with `render()`, and
  `_recover_from_resize()` deliberately discards every queued key. The budget
  is read on the class, so tuning it on one instance has no effect, and keys
  typed during the bounded recovery window are lost because curses offers no
  push-back API. Both points are stated on the attributes, on `answer()` and on
  the recovery method; no behaviour changed.
- The SIGINT policy captures the handler that was installed before the library
  first took the signal over instead of assuming `signal.default_int_handler`,
  and restores it when the last live window stops rather than on the first
  teardown, so one of several windows stopping cannot disarm the others.
  Stopping every window ends the latch, so a later window can make Ctrl-C an
  application key again; the latch still prevents a non-terminating window from
  swallowing Ctrl-C while a terminating one is live (AUDIT.md §3.1).
- The sample app's `THEMES` screen is now generated by
  `Theme.create_picker_screen()` instead of duplicating the factory's header and
  colour swatches. The generated screen applies the host's `opts.theme` before
  drawing (so an ordinary `OptionSpinner` cycle binding keeps working) and
  `spin_theme_ACTION()` starts from that option when present. The factory now has
  direct tests in `tests/test_theme.py` (AUDIT.md §3.3).
- Body and header pads are now viewport-sized blit buffers rather than content
  stores. `add_body()`, `add_header()` and `draw()` write the model only, and
  `render()` paints the visible page into pad row 0, so pad memory and the
  per-frame `clear()` cost track the terminal instead of the highest row count
  an app ever reached. `opts.body_rows`/`opts.head_rows` are retained for
  compatibility but are now **advisory hints only**: no row is discarded for
  exceeding them. The single ceiling is the new `opts.max_rows` (default
  `32767`, `None` for unlimited), which is what `rows_dropped` and its warning
  report. Apps no longer have to pre-size storage for the largest list they
  might show. `draw()` keeps its content-row coordinates (a row written
  off-screen appears when scrolled to) and records its span so the attribute it
  was given survives the deferred paint. Pick highlighting is applied while
  painting, so it follows the viewport when scrolling without moving the pick.
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

- `OptionSpinner.add()` is now a retired tombstone. Its comment handling sliced
  the truncated value list with the pre-truncation index, so `comments` was
  always empty; rather than register a half-configured option it raises
  `NotImplementedError` naming `add_key()` and showing the replacement call.
  No in-repo code used it.

### Fixed
- `textwidth` now counts an emoji presentation selector (`U+FE0F`) as a cell
  when it follows a narrow, non-ASCII base, so `⚠️` measures two cells as
  terminals draw it instead of one.  Every measurement that follows the glyph
  (`string_width()`, `truncate()`, `ljust()`/`rjust()`, `cell_to_index()`) was
  one cell short, which shifted following text left and padded rows short --
  visible as a crammed space after the glyph.  A base that is already two cells
  wide (`⌚`, `⌛`) and ASCII bases are left alone, and `char_width()` stays per
  code point so the cursor can never land between a base and its selector.
- `win._start_curses()` once again *reattaches* the window.  The 1.4.x
  compatibility hook is still called in the wild (psistat's "dump event log"
  path uses `self.window._start_curses()` to return from shell mode), but the
  2.0 implementation only created and returned a screen, leaving `win.scr` as
  `None`; the next `clear()`/`render()` then raised
  `AttributeError: 'NoneType' object has no attribute 'clear'`.  It now resumes
  a suspended window through `resume_curses()` (singleton mode reattaches every
  window sharing the screen), so the pads and the content model survive, and
  `clear()` while suspended resets the content model without dereferencing the
  missing screen.
- Starting a window on a terminal with fewer than 256 colours (including tmux's
  stock `TERM=screen`, whose terminfo entry has 8 colours) no longer crashes with
  `ValueError: Color number is greater than COLORS-1`. Theme installation now
  asks the backend for its capabilities through the new
  `RenderBackend.colors()` / `color_pairs()` seam (captured after
  `start_color()`), so `theme.py` and `window.py` never read the `curses`
  globals directly. On 256-colour terminals the theme's literal specs are used
  unchanged; on 16/88/8-colour terminals each index is mapped to the nearest
  entry of the standard xterm palette (base colours 0..15, the 6x6x6 cube and
  the grayscale ramp are modelled), with a contrast guard that moves the
  foreground if mapping would collapse a pair to `fg == bg`. Below 8 colours, or
  when colours are unavailable, installation falls back to attributes instead
  of raising. `use_default_colors()` is now guarded by `except curses.error` and
  its result is remembered, so `-1` becomes a concrete default (fg 7, bg 0) on
  terminals that reject it; pair ids at or past `COLOR_PAIRS` are skipped.
  Startup, `ConsoleWindow.set_theme()` and `Theme.set()` all install through the
  new `Theme.install()`, and `Theme.set()` no longer calls `curses.init_pair()`
  directly, so the built-in theme picker gets the same degradation.
  `HeadlessBackend(colors=...)` now accepts a colour count (plus optional
  `color_pairs=` and `default_colors=`) so the low-colour paths are covered by
  `tests/test_low_colour.py`.
- `draw()` now routes rows at or past the `max_rows` content ceiling through the
  same `rows_dropped` counter and once-per-fill warning as `add_body()` /
  `add_header()`, with the warning attributed to the caller's line. Previously
  an over-ceiling `draw()` returned silently while the rest of the overflow
  contract reported nothing. The stale half of the audit finding (phantom rows,
  missing contexts, lost attributes) had already been fixed by the
  viewport-sized-pad model and is now documented in AUDIT.md §3.2.
- `ScreenStack.act_in()` no longer raises `AttributeError` when the requested
  action flag is absent; it returns `False` and leaves the options object
  untouched. Its one-shot, current-screen semantics are now covered by
  `tests/test_screens.py` and documented in the README (AUDIT.md §3.3).
- `BasicHelpScreen.draw_screen()` resolves the window from `self.app.win` at
  draw time instead of using the `app.win` value cached by `Screen.__init__`.
  Applications that build their `Screen` objects before their `ConsoleWindow`
  (including `SampleApp`) then get a working help screen instead of
  `AttributeError: 'NoneType' object has no attribute 'set_pick_mode'` when
  mixing `BasicHelpScreen` into an existing screen class.
- `add_fancy_header()` now treats `HeaderLine.bracket_key()` delimiters as
  markup in every mode except `'Off'`: the brackets are removed and the
  enclosed span keeps its `KEY` styling. Previously a `HeaderLine` was emitted
  verbatim, so it rendered identically to `add_header_line()`. The explicit
  path still shows literal brackets, and declared span roles are preserved
  rather than re-parsed from the rendered text.
- Navigation keys are responsive again. Two 2.0.0 hot paths made a full
  redraw of a large list far slower than 1.4.3. `textwidth.truncate()` ran
  three `unicodedata` lookups per character on every row, and
  `Context.__init__()` ran `difflib.get_close_matches()` for every custom
  keyword on every row (a 9,000-row screen constructs 9,000 Contexts per
  frame). Printable ASCII now takes a direct one-cell path, mixed text skips
  whole ASCII runs and visits only the glyphs that differ, `truncate()` uses a
  frame-sized cache, non-ASCII glyph widths are cached, and the Context typo
  suggestion is cached per attribute name. On vappman's 9,035-row screen,
  `draw_screen()` fell from ~225 ms to ~74 ms (1.4.3 measured ~58 ms).
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
- `SampleApp.do_key()`, a dead method with no caller: `main_loop` dispatches
  through `handle_key()`, which already forwards spinner keys to
  `spin.do_key()`. No behaviour changed (AUDIT.md §3.1).
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

[2.0.2]: https://github.com/joedefen/console-window
[2.0.1]: https://github.com/joedefen/console-window
