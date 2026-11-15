# Changelog

All notable changes to `console-window` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [3.0.0]

A major release: content and pick/scroll state move onto `Screen`, `draw()` is
removed, and the appearance and glyph layers are unified.  The README's
"3.0.0 Breakages" section lists each break with its replacement.

### Added

- `OptionSpinner` registers `quit` (`q`, `^C`) and `escape` (`ESC`, `^J`,
  `ENTER`) before the application registers anything; override the key sets with
  `quit_keys=` / `escape_keys=`.  They are shown once in the `NavKeys:` block,
  never in the option body.  `Screen` supplies the default `quit_ACTION()`
  (`SystemExit`) and `escape_ACTION()` (pop one screen, a no-op at home), both
  overridable.
- A `ScreenStack` owns at most one spinner: the spinner injects itself as
  `stack.spinner`, the stack assigns each screen its `num` and `stack` at
  construction, and `Screen.get_spinner()` reads the injection instead of
  scanning the application's attributes.  A second spinner raises `ValueError`.
  `OptionSpinner.options_for_screen(screen)` is the single definition of which
  options apply on a screen.
- A one-time minimum-size fit.  The default floor is `(20, 5)`; after the first
  screen is painted, the floor grows to `min(60, widest_header + 3)` columns and
  `header_rows + 4 + separator` rows, measured before header truncation.  Later
  screens and passes do not change it; `min_cols_rows=` remains the explicit
  override, and `ConsoleWindow.min_size` reports the effective floor.
- A curated catalog of 80 named one-cell glyphs, each with a plain-ASCII
  fallback and covered by DejaVu Sans Mono: `Glyphs.catalog()`,
  `catalog_rows(width)`, `catalog_entries()`, `group_of(name)`, `lookup(name)`
  and `register(..., group=...)`.  Re-registering a built-in keeps its family.
  The theme picker prints the catalog as a font check.
- `BUILTIN_MARKS` / `Glyphs.marks()` is a 39-entry two-cell mark family whose
  contract is width: one East-Asian-Width `W` code point, two cells with and
  without VS16, and a two-cell ASCII fallback.  `Glyphs.mark(name)` returns the
  active form, `validate_mark()` enforces the rules at import, and
  `Glyphs.find_issues(text)` reports VS16-promoted, ZWJ, Ambiguous and
  unapproved marks (also from the glyph audit).
- Every help page carries a **Fonts** section drawing the catalog, the marks and
  the two reference families.  `ConsoleWindowOpts(help_fonts=...)` is `'once'`
  (default), `'always'` or `'never'`; `BasicHelpScreen.font_section` overrides it
  per screen, and ASCII mode collapses it to a sentence.  `register()` and
  `register_mark()` record a missing font for an application symbol.
- `check_ans` on `OptionSpinner.add_key()` validates a `prompt` reply: a string
  or compiled pattern must match the whole reply, and a callable returns `None`
  to accept or a description of what was expected.  A rejected reply re-opens the
  dialog seeded with the text and shows the description through `answer(hint=)`;
  ESC still aborts.
- `line_attr` on `add_fancy_header()`/`add_header_line()` is OR'd into every
  span, so a whole fancy header can be dimmed while its per-span styling
  survives.
- `answer_hint` on `begin_prompt()`/`PromptLine.start()` replaces the default
  `[Press "y" or ESC]` suffix for single-key modes, with `{mode}` substituted for
  the live letter.  The template is plain text, so an application can bracket its
  own question without escaping braces.
- `add_prompt_header(align='center')` centres the prompt row in display cells, so
  wide glyphs and emoji selectors stay centred.  `prompt_separator_attr` styles
  the separator rule only while a prompt is live.
- `suspend_curses()`/`resume_curses()` leave curses mode with `endwin()` and
  reattach later without losing the pads, content model or pick state, the
  supported way to shell out and come back.  The pre-2.0
  `stop_curses(); ...; start_curses()` pair works again in singleton mode by
  suspending and resuming the shared screen; `stop_all()` remains the permanent
  teardown.
- `ConsoleWindow.theme` records the window's theme, `ConsoleWindowOpts(theme=...)`
  seeds it and `set_theme()` switches it, repainting that window's pads.
  `Theme.set()` remains the process-wide switch and now relabels every live
  window.
- `reset_ctrl_c()` restores the SIGINT handler that was installed before the
  first window and clears the Ctrl-C policy latch.
- `ConsoleWindow(singleton=True)` restores the historical process-wide window
  model (`static_scr`/`static_win`, one shared screen and backend).  The first
  construction latches the mode; mixing values raises `AssertionError`.
  `singleton=False` gives independent per-instance screens and teardown.
- `rows_dropped` counts rows discarded past the content ceiling, and the first
  row of each fill episode emits a `UserWarning` naming the pad and the option to
  raise.  The ceiling is `ConsoleWindowOpts(max_rows=...)` (default `32767`,
  `None` for unlimited).
- `temp_handled_keys(*keys)` adds keys to `handled_keys` for one prompt and
  removes only the keys it added, so application keys can be forwarded
  reversibly and nested uses are safe.
- `InlineConfirmation` is a real line editor: `start(..., initial='')` seeds the
  buffer with the caret at the end, and LEFT/RIGHT, Home/End (Ctrl-A/Ctrl-E),
  Backspace and Delete edit at the caret.  `cursor_pos` and `cursor_cell` expose
  the string index and terminal column; movement and deletion use the
  `textwidth` helpers so wide characters and combining marks stay intact.
- `IncrementalSearchBar.reset(initial_text='')` leaves search mode with the given
  text and runs no callback, and `as_header_line(..., invalid=False)` emits the
  prefix as its own search-role span, so a caller can reverse-video just the `/`
  while the pattern does not compile.

### Changed

- **Breaking:** content and the pick/scroll state moved from `ConsoleWindow`
  onto `Screen`, and `draw()` is deleted, leaving one drawing model.  The
  `win.add_header()`, `win.add_body()`, `win.add_fancy_header()`,
  `win.add_header_line()`, `win.add_prompt_header()` and
  `win.add_prompt_lines()` writers are `Screen` methods now, called inside
  `draw_screen()`; the loop is `screen.clear(); screen.draw_screen();
  win.render(); win.prompt()`, where `clear()` both resets content and makes the
  screen current.  `win.pick_pos`/`scroll_pos`/`pick_mode`/`free_scroll`/
  `pick_range` read and write the current screen, so two screens keep independent
  positions, and `pick_range` left `ConsoleWindowOpts`.  `head_line=False` no
  longer paints a rule, a scroll indicator or status text onto the body's first
  row, and in scroll mode the pick tracks the top of the viewport.
- **Breaking:** the appearance layer's public name is now `Appearance`
  (`console_window.Appearance`), capitalized to match the other package-root
  names (`Theme`, `Glyphs`, `Context`, ...).  Its implementation module is now
  private (`console_window._appearance`), so `from console_window import
  appearance` and `console_window.appearance.*` no longer resolve.  Import
  `Appearance` and call `Appearance.semantic_attr()`,
  `Appearance.colors_enabled()`, `Appearance.set_colors_enabled()` or
  `Appearance.resolve_appearance()` instead.  The individual names
  (`MONO_ROLES`, `colors_enabled`, `resolve_appearance`, `semantic_attr`,
  `set_colors_enabled`) remain importable from the package root.
- **Breaking:** the library's own symbols moved to their heavier, font-covered
  forms.  The resolved-choice marker is `➤` (U+27A4) instead of `⮞` (U+2B9E),
  which DejaVu Sans Mono does not contain; `Glyphs.get('choice')`,
  `get_choice_lines()` and `InlineConfirmation` follow it, and the ASCII fallback
  stays `>`.  The help-legend arrows are `⬅`/`➡` and `⬆`/`⬇`, the hollow circle
  is `◯`, and the square pair is `◻`/`◼`.  Old spellings are upgraded in both
  modes, so text written against 2.x renders from the basic font without a source
  change, and registering an old code point keeps it.  Hollow triangles have no
  heavier outline form, so `△▽◁▷` stay as they are.
- The help screen is three bands: the `NavKeys:` legend, a body headed
  `Keys for '<screen>':` for the screen the help was pushed from, and an
  `---------- Instructions ----------` block whose paragraphs are drawn in the
  normal attribute as ` ◆ `-bulleted prose with a three-cell hanging indent.
- The help body describes the pushed screen: it lists that screen's options --
  global or scoped to it -- and its `cycle`/`prompt` keys stay live there, so a
  value can be changed without leaving the help.  Actions are listed but
  inactive, and the built-in `quit`/`escape` stay in the nav block.  The heading
  is omitted when nothing applies; with nothing pushed the body shows the
  complete option list under `All keys:`.  `show_help_body()` takes just the
  screen; its `screen_filter=` argument is gone.
- The help body is laid out for the width the window has when it draws, so
  nothing is left for the window to truncate silently.  The value column is
  measured per draw from the options that screen lists; a row that would overflow
  wraps, a single value too long for a row is ellipsized, and comments wrap under
  the same column (or two cells in, when the column leaves too little room for
  prose).  Below eight cells of value column the body degrades to the four-cell
  dot gap and then to a flat layout.  `OptionSpinner.align` and `.margin` are
  gone; a resize re-flows on the next draw.
- Registering an option on a built-in key now requires an explicit `scope=`; an
  implicit registration raises and names the built-in action.  A deliberate
  per-screen override, such as `ESC` clearing a filter on `MAIN`, still works.
- The minimum size is enforced at the start of every `prompt()`, not only when
  `KEY_RESIZE` arrives, and the notice polls the terminal dimensions so growing
  back above the minimum is noticed without a resize key.  `answer()` uses the
  same effective minimum and refreshes its geometry on each retry;
  `min_cols_rows` is validated as a pair of positive integers.
- An application's registration now wins over a built-in for the same code
  point, whether it re-registers the built-in's name or claims the character
  under a new one.
- Passthrough mode now forwards ESC (`27`) and Delete (`curses.KEY_DC`) as
  editing keys, so an `InlineConfirmation` caller no longer has to add `27` to
  `win.handled_keys` by hand.
- Body and header pads are viewport-sized blit buffers rather than content
  stores: `add_body()`, `add_header()` and `draw()` write the model only, and
  `render()` paints the visible page, so memory and per-frame cost track the
  terminal instead of the highest row count.  `opts.body_rows`/`opts.head_rows`
  are advisory hints only; the single ceiling is `opts.max_rows`.
- The help screen's navigation map is now two aligned rows of `action: keys`
  chunks under a `NavKeys:` label --
  `pos: H/M/L    half: ^u/^d    page: ^b/^f/PPAGE/NPAGE` above
  `up: k/UP  down: j/DOWN  first: 0/HOME   last: $/END`.  Control keys use caret
  notation, `NAV_HELP_ROWS` is replaced by `NAV_HELP_LINES` (a per-line tuple of
  `(action, keys, gap)` rows), and `NAV_KEY_LINES`, `get_nav_key_lines()` and
  `get_nav_keys_blurb()` keep their tuple-of-lines shape.  A key the application
  took still disappears from its chunk.
- The startup report no longer carries a `font check:` line, and
  `BasicHelpScreen.show_display_notes` is gone: the built-in Fonts section
  replaces both, so an application needs no display notes to get a symbol check.
  `help.glyph_paragraph()` remains for a custom help body.
- `OptionSpinner.get_value()` is a pure read.  Its `coerce` parameter is gone;
  initialization moved to the explicit `normalize(attr)`, which `add_key()`
  already calls.
- The minimum supported Python is now **3.10** (`requires-python = ">=3.10"`).
  The 3.8 floor was never real: `curses.set_escdelay()` is new in 3.9.

### Fixed

- A pick's block is the picked row plus the rows attached to it by `abut` (a
  detail row's `abut=-1`, a transient parent's children) instead of a fixed
  `pick_size`; a separator or the next group's header ends the block, which
  scrolling keeps visible together.  Only the picked row is highlighted, and the
  pick is never rounded to a block boundary.
- `0`/HOME and `$`/END select the first and last *pickable* row in pick mode, and
  `H`/`M`/`L` snap to the nearest pickable row, instead of targeting row 0 or the
  last body row.
- The separator rule and scroll indicator never write the terminal's
  bottom-right cell; both reserve the last column as the pads already do.
- In pick mode the head and body pads are shifted right by the gutter's one
  cell, so the whole left column is blanked from the top row down on every frame
  instead of leaving a stale character in the header band.
- Plain `Screen.add_header()` rows contribute to the widest-header measurement
  used for the one-time minimum and for indicator padding.
- The glyph substitution table is rebuilt when a registration invalidates it, so
  a fallback changed at runtime is the one actually used.
- `textwidth` counts an emoji presentation selector (`U+FE0F`) as a cell after a
  narrow non-ASCII base, so `⚠️` measures two cells as terminals draw it.  Every
  measurement that follows the glyph was one cell short.
- `win._start_curses()` reattaches the window again (through `resume_curses()`)
  instead of only creating a screen, so the 1.4.x compatibility hook keeps
  working.
- Low-color terminals no longer crash with `ValueError: Color number is greater
  than COLORS-1`.  Theme installation asks the backend for its color count and
  pair count and maps a 256-color theme onto the nearest 16/88/8-color entry,
  with a contrast guard; below 8 colors, or with no color support, it falls back
  to attributes.
- `draw()` reports rows past `max_rows` through the same `rows_dropped` counter
  and once-per-fill warning as `add_body()`/`add_header()`.
- `ScreenStack.act_in()` returns `False` for an absent action flag instead of
  raising `AttributeError`.
- `BasicHelpScreen.draw_screen()` resolves `app.win` at draw time, so screens
  built before their window work.
- `add_fancy_header()` treats `HeaderLine.bracket_key()` delimiters as markup in
  every mode except `'Off'`, removing the brackets while keeping the `KEY`
  styling.
- Navigation over large lists is responsive again: printable ASCII takes a
  one-cell fast path, `truncate()` caches by width, glyph widths are cached, and
  the `Context` typo suggestion is cached per attribute name.
- `ConsoleWindowOpts` rejects unknown option names with a `TypeError` and a
  `difflib` suggestion instead of silently ignoring a typo.
- `answer()` has a bounded recovery loop and raises `TerminalTooSmallError`
  instead of looping forever or using `None` for both "aborted" and "too small".
- Ctrl-C termination is a process-lifetime latch: once a window with
  `ctrl_c_terminates=True` exists, a later window cannot replace SIGINT with the
  key-delivery handler, and the original handler is restored when the last live
  window stops.
- Aborting a `prompt`-genre spinner option with ESC no longer wipes the stored
  value; `None` from `answer()` means "no change".
- `alert()` now scrolls with `j`/`k`, the arrow keys, PageUp/PageDown and
  Home/End, and shows `▲`/`▼` markers when content extends past the fold.  Its
  `_height`/`_width` parameters now cap the centered box.
- Startup and `Theme.set()` initialize the same semantic color pairs from one
  list, so `OLD_SUCCESS` is no longer left on an uninitialized pair.
- Free-scrolling can reach non-pickable `DECOR` rows past the last (or before
  the first) pickable row; the pick stays parked while the viewport moves and
  resynchronises on the next real pick move.

### Removed

- `pick_size` is gone from `ConsoleWindow`, `ConsoleWindowOpts` and
  `set_pick_mode()`: a multi-row pick is the group of rows attached by `abut`, so
  there is no size to configure.  `set_pick_mode(on)` takes only the on/off flag.
- `_filter_screens()` and `_skipped_by_filter()` are replaced by
  `options_for_screen()`, and the unreachable `_reject_key_conflicts()` is
  deleted: a later registration always subtracts its overlap from an earlier one,
  so the newest option owns the key on a screen.
- `OptionSpinner.add()`, the pre-2.0 registration shim that had raised
  `NotImplementedError` since 2.0, is deleted together with its regression test.
  `add_key()` is the only registration path.
- The `DWIPE_THEME` environment variable.  `Theme` state is the single source of
  truth, so a theme no longer leaks into child processes through the environment.
- `console_window/ConsoleWindow.py`, the compatibility facade.  Package-root
  imports (`from console_window import ...`) are unchanged; only the legacy
  `from console_window.ConsoleWindow import ...` path is gone.

## [2.2.2]

### Fixed
- `Theme.create_picker_screen()`: the color swatches are painted through
  `console_window.appearance.semantic_attr()` rather than `curses.color_pair()`,
  so a picker open while color is off (`--no-color`, `NO_COLOR`, or
  `set_colors_enabled(False)`) shows each role's monochrome attribute
  (bold+reverse, bold, plain) instead of re-painting the previous theme's
  colors. The generated screen exposes an overridable `swatch_attr()` hook for
  hosts that want a different swatch style and a `theme_label()` hook so an app
  with a pseudo-theme can name it in the header. Color output is unchanged.

### Notes
- `SampleApp` demonstrates `--no-color` end to end: its own rows are painted
  with `appearance.semantic_attr()` instead of `curses.color_pair()`, its theme
  option offers the demo's `mono` pseudo-theme (a color mode, not a palette),
  and `main()` settles both halves of the decision with `resolve_appearance()`,
  so `NO_COLOR` works as well as the switch. The picker previews the
  monochrome hierarchy when `mono` is chosen and names that choice in its
  header (`COLOR THEME: mono`) instead of naming the palette left installed
  underneath it.
- Documentation, comments and test names now use American English spelling
  (`color`, `behavior`, `initialize`, `honor`, `centered`, `normalize`,
  `optimize`, `labeled`). There is no runtime or public-API change.
  The module `tests/test_low_colour.py` is now `tests/test_low_color.py`.

## [2.2.1]

### Notes
- No runtime change. This release only silences the warnings the strict pylint
  job fails on: the deliberate broad catches and the process-wide color switch
  in `console_window.appearance`, and `Theme`'s store seam, carry an inline
  `pylint: disable` with the reason; the public `probe` keyword parameters are
  marked as shadowing the module-level `probe()` helper rather than renamed.
  2.2.0 is functionally identical.

## [2.2.0]

### Added
- `console_window.appearance`: the appearance policy applications used to copy
  into their own modules. `MONO_ROLES` maps every semantic `Theme` role to the
  attribute used when color is off (destructive roles bold+reverse, warnings,
  successes and emphasis bold, informational roles plain), and
  `set_colors_enabled()` / `colors_enabled()` own the process-wide switch.
  `semantic_attr(role)` returns the installed color pair or the monochrome
  attribute, and degrades to plain text when the terminal has no color or
  curses is not initialized yet, so a failed lookup never aborts a redraw.
  `resolve_appearance(cli_theme=None, no_color=False, saved_theme='',
  saved_colors=True, environ=None)` returns the `(theme, colors)` a process
  should start with. Precedence is `--no-color`, an explicit `--theme`, the
  `NO_COLOR` convention (any non-empty value), then the remembered choice.
  Preference files, application vocabulary and application pseudo-themes stay
  with the application, so the resolver is storage-free and knows no `mono`
  pseudo-theme of its own.
- `console_window.cli`: `--no-color` in `add_display_arguments()` and
  `resolve_no_color(args)` beside `resolve_force_ascii(args)`.
  `apply_display_arguments()` acts on an explicit `--no-color` and otherwise
  leaves the switch alone, so an application with a remembered color
  preference can still decide for itself.

### Notes
- `MONO_ROLES`, `colors_enabled`, `resolve_appearance`, `semantic_attr` and
  `set_colors_enabled` are re-exported from the package root.
- The color-theme picker still lists only installed library themes; an
  application's `mono` pseudo-theme remains that application's own entry.

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
  `show_display_notes = True`, which add the `Instructions` separator and
  render the result as bulleted prose.  The flag is off by default so an
  existing help screen keeps its exact output.
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
- Behavior change worth knowing: on a terminal that cannot encode UTF-8 (or
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
- Return behavior follows the existing `handled_keys`/`relax_handled_keys`
  rules: a taken key bound through the spinner is returned; with
  `relax_handled_keys=False` and no binding it may still be swallowed.
- Invalid entries (non-integer key codes) raise `ValueError`; duplicate codes
  collapse to one binding. Codes that are not navigation keys are kept but
  logged as having no effect, and taking every vertical key logs a
  "reduced navigation" warning instead of failing.

## [2.0.1]

Internal overhaul — modularization and tests. The public API is unchanged and
fully backward compatible (`from console_window import ...` and
`from console_window.ConsoleWindow import ...` both continue to work).

### Added
- Unit-test suite (`tests/`, TTY-free) covering scroll/pick geometry,
  `IncrementalSearchBar` / `InlineConfirmation`, `OptionSpinner` scope
  subtraction, public-API compatibility, the `answer()`/`alert()` dialog fixes,
  `set_demo_mode()` toggle/state handling, `render()`'s retry cap, and the
  non-destructive `flash()` behavior (`tests/test_flash.py`).
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
