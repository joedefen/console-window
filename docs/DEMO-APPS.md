# Demo apps: a lettered family

Status: **implemented** — the sixteen demos, `demo_kit.py` and `features.py`
exist, `demo-buffet.py` is gone, and `tests/test_demos.py` enforces the
manifest below.  This document remains the design and the index the family
keeps in sync with.

The goal is a small, bounded set of **focused** sample apps.  Each one is a
short program that teaches one increment.  `demo-buffet.py` is retired: it was
637 lines, its features were only discoverable through the help screen, and
adding one more feature to it made it worse.

## Why a family instead of one worked example

- A reader looking for "how do I make a picker?" should not have to read about
  themes, glyphs, prompts and stress rows first.
- Every demo is short enough to read in one sitting; A, B and C are also
  complete single-file starting points.
- A feature is taught once.  Later demos reuse it without re-explaining it.
- The set is bounded: **16 demos, A through P**, inside the 10–20 range.  A, B
  and C are the complete programs; every later demo is a short delta on the
  shared `demo_kit.py`, not a copy of a base.  If the family still feels large,
  the first candidates to fold are H (messages) into G (dialogs) and P (key
  debug/widths) into O (limits).

## Conventions

- **File name:** `demos/demo-<letter>-<name>.py`, e.g.
  `demos/demo-a-basic.py`.  The `run-demo` short name is `<letter>-<name>`,
  e.g. `./demos/run-demo a-basic`.
- **Complete examples and deltas:** A, B and C are complete, standalone programs
  and the only files that show the whole app.  D–P import `demos/demo_kit.py`,
  which carries the common app shape (window, loop, table, sample data) plus the
  stack and spinner glue; it contains none of the feature additions.  Each later
  demo adds only its row's features and stays short.  No demo imports another
  demo; `demo_kit.py` and `PrimeRows.py` are the only shared modules.
- **Why the kit, not copies:** a base change is made once in the kit.  Thirteen
  copies would drift silently, and "which copy is current?" is exactly the
  re-education problem this family is meant to solve.  If a single-file
  copy-paste starting point matters more, the alternative is a marked
  `# BEGIN BASE` block plus a test that every copy matches; the kit is the
  default because the drift is otherwise invisible.
- **First appearance only:** the "Adds" column lists the features a demo
  introduces.  Do not repeat a feature in a later row, even though the code
  still contains it.  A reader can infer that a later demo has the earlier
  features because it shares the kit and the earlier demos' features.
- **Size:** target 60–150 lines; 200 is a hard ceiling.  If a row needs more,
  the feature belongs in another demo.
- **No hidden features:** the header carries the key hints.  The help screen
  exists where help itself is the lesson; it is not a place to bury a demo
  feature.
- **Uniform smoke-test seam:** every demo exposes
  `build_app(backend=None, singleton=True) -> app`, and `q` quits.  The test
  suite uses that to construct each app against `HeadlessBackend`, draw one
  pass, queue `q`, and run the loop.  `main()` is a thin wrapper around
  `build_app(...).main_loop()`.
- **Standalone run:** every demo uses the same two-line `cli` prelude for
  `--ascii` / `--glyphs` / `--theme` where those switches are relevant, so a
  reader can run any demo with the same flags.

## Feature ownership and the change rule

The unit of ownership is a **learning objective**, not an API symbol.  The
picking model is one feature even though it uses `set_pick_mode()`, `Context`
and `abut`; `status-levels` and `flash` are two because they are separate
lessons.  This keeps the family at 16 demos instead of one per API call.

`demos/features.py` is the machine-readable owner map:

```python
FEATURES: dict[str, str] = {
    'app-loop': 'a-basic',
    'abut': 'd-pick',
    'begin-prompt': 'f-prompts',
    'glyph-catalog': 'k-glyphs',
    # ... one entry per key in the appendix below
}
```

`tests/test_demos.py` asserts that every key maps to an existing demo, no key is
owned twice, every demo owns at least one key, and the appendix below matches
`FEATURES` (the appendix is rendered from the same mapping).

### The change rule

When a feature is added or changed, the same change must:

1. update the owning demo and its `Owns:` docstring line, or add a new lettered
   demo when no current demo is the right home;
2. add or update the key in `demos/features.py`; and
3. name the demo in the changelog bullet, for example:

   ```markdown
   - **`status()` gains `timeout`** — see `demo: h-messages`.
   ```

A change that only updates library tests is incomplete for re-education: the
demo is the focused manual check and the test is the regression net.  They are
not substitutes.

### The docstring contract

Every demo starts with the same header, so opening the file answers "what does
this own and how do I run it?" without consulting this document:

```python
"""D — Pick a row.

Owns: pick-mode, context-metadata, decor-rows, pick-size, abut, pick-range
Base: c-options
Run:  ./demos/run-demo d-pick
"""
```

## The family

Base names the curriculum lineage a reader should have seen first.  A–C are
complete files; D–P import `demo_kit.py`, which carries the common app shape
plus the stack and spinner glue, but none of the feature additions.  The "Adds"
column is the ownership list; the appendix is the same list sorted for lookup.

| # | Demo | Base | Adds (first appearance only) |
| - | ---- | ---- | ---------------------------- |
| A | **Basic pager** — `a-basic` | — | One `Screen` whose `draw_screen()` rebuilds the page each pass. The four-call loop (`clear()` → `draw_screen()` → `render()` → `prompt()`). Static header band and separator rule (`head_line=True`). `add_header()` / `add_body()` and a title line above a column header. Built-in navigation keys (`j`/`k`, arrows, PgUp/PgDn, Home/End) scroll the body. Live data: one deterministic row changes each pass; `ConsoleWindow.timeout_ms` keeps keys responsive. |
| B | **Two pages** — `b-stack` | A | `ScreenStack.from_screens()` with more than one screen. `push()` / `pop()` / `is_curr()` driven by application keys. Per-screen content and scroll position restored on return. `ctrl_c_terminates=False`: Ctrl-C arrives as an ordinary key. `set_handled_keys()` to claim only the application's keys. |
| C | **Options** — `c-options` | B | `OptionSpinner.add_key(..., vals=...)` value cycles. `prompt=` plus `check_ans=` for validated free text that is re-asked on bad input. `scope=` per screen. Generated `BasicHelpScreen` body that lists only the options in scope (`options_for_screen()`) and a `NavKeys:` legend. `perform_actions()` and the `<name>_ACTION()` dispatch convention. Built-in `quit` / `escape` actions and `quit_keys=`. |
| D | **Pick a row** — `d-pick` | C | `set_pick_mode(True)` and the highlighted row. `Context(genre='item', item=...)` plus `get_picked_context()`. `Context(genre='DECOR')` rows that navigation skips. `pick_size=` for multi-row picks. `Context(abut=...)` keeps a detail block attached to its picked row. `set_pick_range()` for a column-range highlight. |
| E | **Filter as you type** — `e-search` | C | `IncrementalSearchBar` with `on_change` / `on_accept` / `on_cancel`. `passthrough_mode` while the bar is active. `temp_handled_keys()` for one temporary application key. Live filtering with a pick-position reset. A screen-local ESC that subtracts that screen from the global escape action. An explicit empty-result row. |
| F | **Ask in place** — `f-prompts` | D | `begin_prompt()` / `prompt_active` / `handle_prompt_key()`. Single-key confirmation (`mode='y'`) with `hint=`. Buffered text input (`mode='text'`, `seed=`). `add_prompt_lines()` drawn directly under the owning row. `add_prompt_header()` for a screen-wide question. `on_confirm` / `on_cancel` callbacks that run after passthrough is restored. |
| G | **Dialogs and the inline editor** — `g-dialogs` | C | `answer()` with `hint=` and its return/abort contract. `alert()` as a modal message. `InlineConfirmation` in yes/no, choices, identity and text modes. The line editor's caret keys (Left/Right/Home/End/Backspace/Delete). |
| H | **Messages** — `h-messages` | A | `status()` with `level='info' / 'warn' / 'error'` and `timeout=`. `status('')`, `clear_status()` and `current_status`. Separator-row placement, truncation before the scroll indicator, and deferred status when `head_line=False`. `flash()` as a timed modal message. The per-message `attr=` override. |
| I | **Header composition** — `i-headers` | A | `HeaderLine` tokens: `text()`, `bracket_key()`, `key()` and `extend()`. `add_header_line()` (tokens emitted verbatim) versus `add_fancy_header()` (the mode string is interpreted). `mode='Underline'` and `line_attr=curses.A_DIM`. `Span` styling and a multi-row header band. |
| J | **Themes and appearance** — `j-themes` | C | `Theme.create_picker_screen()` with `cycle_key=`. `ThemeStore` / `Theme.initial()` persistence. `win.set_theme()` as per-window state versus `Theme.set_active()` as process state. `mono`, `NO_COLOR` and `--theme`. `Appearance.semantic_attr()` for semantic body rows. `captions=` role renaming and the `swatch_attr()` / `swatch_rows()` overrides. |
| K | **Glyphs and ASCII** — `k-glyphs` | C | `Glyphs.catalog()` / `catalog_rows()` as a font-check page. Application vocabulary through `ConsoleWindowOpts(glyphs=..., glyphs_probe=...)`. `Glyphs.get()` in content and its ASCII fallback. `--ascii`, `--glyphs` and `CONSOLE_WINDOW_GLYPHS`. `help.glyph_paragraph()` with `show_display_notes`. This is also the home for the deferred "show the whole catalog" sample page. |
| L | **Read-only screens** — `l-text-screens` | C | `BasicTextScreen` and `set_text()` accepting `str` or `(text, attr)`. A `BasicHelpScreen` subclass with `extra_help_paragraphs()`. A read-only text screen with no spinner. The default `escape_ACTION()` pop. |
| M | **Own the navigation keys** — `m-own-keys` | C | `ConsoleWindowOpts(taken_nav_keys={key: label})`. `OptionSpinner(..., nav_keys=opts.nav_keys)`. LEFT/RIGHT as previous/next page, while dialogs still use them for the caret. The help legend showing the application's labels instead of the reserved arrows. |
| N | **Pause and run** — `n-suspend` | A | `suspend_curses()` / `resume_curses()`. Running an external program (`$EDITOR`, `less`, a subprocess) between them. Content and pick state surviving the hand-back, with the next `render()` repainting. |
| O | **Large bodies and limits** — `o-large-bodies` | A | A 2,000+ row body with viewport-sized pads. The scroll indicator on a long body. The `max_rows` safety ceiling, its one-time `UserWarning`, and `rows_dropped`. `min_cols_rows`, the one-time minimum-size fit, and `TerminalTooSmallError`. Resize recovery and `render(redraw=True)`. |
| P | **Keys and widths** — `p-key-debug` | A | `set_demo_mode()` and the last-key indicator. `textwidth.string_width()` and `truncate()` for cell-accurate layout. Wide CJK, emoji and combining marks aligned in columns. |

## Groups at a glance

1. **Foundations (A–C).** The pager, the stack, the spinner.  These are the only
   files that need to be read from top to bottom.
2. **Rows and input (D–G).** Selecting, filtering, asking in place, and modal
   questions.  D, E and G start from C; F starts from D.
3. **Presentation (H–L).** Messages, headers, themes, glyphs and read-only text.
   H, I start from A; J, K, L start from C.
4. **Application plumbing (M–P).** Navigation ownership, pausing, scale/safety,
   and debugging aids.  M starts from C; N, O, P start from A.

## Where the `demo-buffet` features go

| Buffet feature | New home |
| -------------- | -------- |
| `ScreenStack` plus MAIN/HELP/HISTORY/THEMES | B; screens reassembled in J, K and L |
| Scoped, self-subtracting spinner keys | C (the `t` on MAIN versus THEMES case) |
| `Context(genre='item')` and `get_picked_context()` | D |
| `Context(genre='DECOR')` skipped rows | D |
| Multi-row picking (`p`) | D |
| `IncrementalSearchBar` and `passthrough_mode` | E |
| In-place `y` / text prompts and `add_prompt_*` | F |
| `answer()` and `alert()` | G |
| `status()` and `flash()` | H |
| `HeaderLine` / `add_header_line()` / three strategies | I |
| Theme picker, `set_theme()`, `mono`, `NO_COLOR` | J |
| One app glyph, `probe_text()`, font-check help note | K |
| `BasicTextScreen` for HISTORY | L |
| `show_keys` demo mode | P |
| `taken_nav_keys` | M |
| `suspend_curses()` / `resume_curses()` | N (new; not in buffet) |
| Large-body `z` stress and the scroll indicator | O |
| Full-repaint `r` recovery | O |
| `ctrl_c_terminates=False` | B |
| `InlineConfirmation` (public widget, not used by buffet) | G |

Nothing in the buffet is left without a home.  The buffet file itself is
deleted after the tests that drive it are retargeted.

## Test plan

The old `tests/test_sample_app.py` imported `demos/demo-buffet.py` and made
393 lines of assertions about its screens.  It was replaced by
`tests/test_demos.py`, which:

1. **`tests/test_demos.py`** discovers every `demos/demo-*.py`, imports it
   with `importlib`, calls `build_app(backend=HeadlessBackend(...),
   singleton=False)`, queues `ord('q')`, and runs `main_loop()`.  It asserts the
   loop drew at least one header/body row and stopped cleanly.  This gives every
   demo a headless smoke test without teaching the test suite each app's shape.
2. **The buffet's specific assertions were ported to the demo that now owns
   each feature**:
   - scoped key subtraction and every action having a handler → C;
   - the router pushing/popping screens → B;
   - confirm prompt row placement and callbacks → F;
   - theme choice, mono attribute and picker header → J;
   - read-only screen content → L;
   - large-body size and no dropped rows → O.
3. **Manifest tests** in `tests/test_demos.py`: every key in `FEATURES` names an
   existing `demo-*.py`; no key has two owners; every demo owns at least one
   key; and every demo's `Owns:` docstring line matches its keys.  This is the
   guard that keeps "one feature, one demo" true.
4. **A rendered appendix test:** `demos/features.py` can render the
   feature-to-demo table, and the test compares it with the appendix in this
   document.  The index cannot drift from the code.  The same renderer backs
   `./demos/run-demo features` for quick lookup at the terminal.

## Implementation checklist

- [x] Add `demo-a-basic.py` (rename `demo-basic-pager.py`), `demo-b-stack.py`
      (rename `demo-screen-pager.py`), and `demo-c-options.py` (rename
      `demo-spinner-pager.py`); add `build_app()` and the `q` quit rule.
- [x] Add `demos/demo_kit.py`: the common app shape (window options, the
      four-call loop, the table screen and the sample rows) plus the stack and
      spinner glue that D–P share, with none of the feature additions.
- [x] Add D–P in letter order as short deltas on `demo_kit.py`, each adding only
      its row's features.
- [x] Keep `PrimeRows.py` as the data module.  A–C stay complete files; D–P do
      not copy the loop.
- [x] Add `demos/features.py` with the `FEATURES` owner map, the demo docstring
      contract and the renderer used by the appendix and `run-demo features`.
- [x] Add the manifest checks to `tests/test_demos.py` (existence, one owner
      per key, every demo owned, docstring agreement, rendered appendix
      agreement).
- [x] Rewrite `demos/demos.ini` as the lettered menu, one `run-demo` line per
      demo, with group comments and no buffet entry.
- [x] Update the `run-demo` docstring (it still names `buffet` as the example).
- [x] Rename and retarget the buffet-oriented `tests/test_sample_app.py` as
      `tests/test_demos.py`: keep the generic smoke harness and port the
      feature-specific assertions listed above.
- [x] Delete `demos/demo-buffet.py`.
- [x] Update `README.md`: the "Running the Sample App" section becomes the demo
      menu; the 20-bullet buffet walkthrough becomes a three-demo progression
      (A → B → C) plus this document; fix the dead `SampleApp.py` links.
- [x] Add a `tests/CHANGELOG.md` entry under `[3.0.0]`: the demo family replaces
      `demo-buffet`; list the renamed demos; and make every feature bullet name
      its owning `demo: <name>` from then on.
- [x] Run the gate: `.venv/bin/ruff check console_window tests`, `.venv/bin/ruff
      check demos --ignore ANN`, and `.venv/bin/python -m pytest -q`.

## Definition of done

- Sixteen demos, A through P.  A–C are complete files; D–P are deltas on
  `demo_kit.py`, each within the size ceiling.
- Every feature key in `FEATURES` appears exactly once, in the demo that owns
  it, and every demo's `Owns:` docstring matches its keys.
- The appendix in this document is rendered from `FEATURES` and matches it.
- Every feature add/change in the changelog names its owning demo.
- Every demo builds and draws headless, quits on `q`, and needs no TTY.
- `demo-buffet.py` is gone and every feature it demonstrated has a new home.
- The README, this document, `demos.ini` and the files on disk agree.
- The full ruff + pytest gate passes.

## Appendix: feature key → demo

This is the reverse index, sorted by feature key.  It is rendered from
`FEATURES`; do not hand-edit it independently of the manifest.
`./demos/run-demo features` prints the same mapping at the terminal.

| Feature key | Demo |
| ----------- | ---- |
| `abut` | `d-pick` |
| `action-dispatch` | `c-options` |
| `alert-dialog` | `g-dialogs` |
| `answer-dialog` | `g-dialogs` |
| `app-loop` | `a-basic` |
| `basic-text-screen` | `l-text-screens` |
| `begin-prompt` | `f-prompts` |
| `caret-editing` | `g-dialogs` |
| `context-metadata` | `d-pick` |
| `ctrl-c-key` | `b-stack` |
| `decor-rows` | `d-pick` |
| `demo-mode` | `p-key-debug` |
| `escape-action` | `l-text-screens` |
| `external-program` | `n-suspend` |
| `flash` | `h-messages` |
| `glyph-catalog` | `k-glyphs` |
| `glyph-cli` | `k-glyphs` |
| `glyph-fallback` | `k-glyphs` |
| `glyph-help` | `k-glyphs` |
| `glyph-vocabulary` | `k-glyphs` |
| `header-band` | `a-basic` |
| `header-modes` | `i-headers` |
| `header-tokens` | `i-headers` |
| `help-labels` | `m-own-keys` |
| `help-paragraphs` | `l-text-screens` |
| `help-screen` | `c-options` |
| `incremental-search` | `e-search` |
| `inline-confirmation` | `g-dialogs` |
| `large-body` | `o-large-bodies` |
| `live-data` | `a-basic` |
| `max-rows` | `o-large-bodies` |
| `min-size` | `o-large-bodies` |
| `mono-theme` | `j-themes` |
| `navigation` | `a-basic` |
| `option-scope` | `c-options` |
| `paged-navigation` | `m-own-keys` |
| `passthrough-mode` | `e-search` |
| `per-screen-state` | `b-stack` |
| `per-window-theme` | `j-themes` |
| `pick-mode` | `d-pick` |
| `pick-range` | `d-pick` |
| `pick-size` | `d-pick` |
| `prompt-callbacks` | `f-prompts` |
| `prompt-placement` | `f-prompts` |
| `read-only-screen` | `l-text-screens` |
| `redraw-recovery` | `o-large-bodies` |
| `scoped-escape` | `e-search` |
| `screen-stack` | `b-stack` |
| `scroll-indicator` | `o-large-bodies` |
| `semantic-attrs` | `j-themes` |
| `single-key-prompt` | `f-prompts` |
| `span-styling` | `i-headers` |
| `spinner-nav-keys` | `m-own-keys` |
| `spinner-options` | `c-options` |
| `status-levels` | `h-messages` |
| `status-lifecycle` | `h-messages` |
| `status-placement` | `h-messages` |
| `suspend-resume` | `n-suspend` |
| `taken-nav-keys` | `m-own-keys` |
| `temp-handled-keys` | `e-search` |
| `text-prompt` | `f-prompts` |
| `textwidth` | `p-key-debug` |
| `theme-captions` | `j-themes` |
| `theme-picker` | `j-themes` |
| `theme-store` | `j-themes` |
| `validated-prompt` | `c-options` |
| `wide-characters` | `p-key-debug` |
