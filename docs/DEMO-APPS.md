# Demo apps: a lettered family

Status: **implemented** — the seventeen demos, `demo_kit.py` and `features.py`
exist and `demo-buffet.py` is gone.  The demos are showcase programs, not
library code: the test suite does not assert their screens, keys or manifest,
and `demos/` is outside the coverage measurement.  This document remains the
design and the index, maintained by hand.

The goal is a small, bounded set of **focused** sample apps.  Each one is a
short program that teaches one increment.  `demo-buffet.py` is retired: it was
637 lines, its features were only discoverable through the help screen, and
adding one more feature to it made it worse.

## Why a family instead of one worked example

- A reader looking for "how do I make a picker?" should not have to read about
  themes, glyphs, prompts and stress rows first.
- Every demo is short enough to read in one sitting.  A and B are complete
  single-file starting points for the degenerate cases; C is the complete
  full-shape file to copy.
- A feature is taught once.  Later demos reuse it without re-explaining it.
- The set is bounded: **17 demos, A through Q**, inside the 10–20 range.  A, B
  and C are the complete programs; every later demo is a short delta on the
  shared `demo_kit.py`, not a copy of a base.  If the family still feels large,
  the first candidates to fold are H (messages) into G (dialogs) and P (key
  debug/widths) into O (limits).

## The full shape (the boilerplate)

A and B are the **degenerate showcases**: A is one `Screen` and the four-call
loop with no stack, no spinner and no help page; B adds the `ScreenStack`.
Everything from C on has the full shape, and that shape is the boilerplate:

1. `ScreenStack` -- even a one-screen demo has one, so pushing a help page is
   never a special case.
2. `OptionSpinner` -- the single registry of application keys, with `quit` and
   `escape` built in and `? - help` already bound.
3. `BasicHelpScreen` -- the `NavKeys:` legend, the key list for the screen the
   help was pushed from, and the `Instructions` prose.

`demo_kit.DemoApp` supplies all three by default: `build_screens()` returns the
main screen and its help page, `new_spinner()` returns the spinner with help
bound, and `DemoHelpScreen` reads the app's `help_paragraphs`.  The help page's
Fonts section is the base class's, so no demo supplies one.  A demo adds a key with
`add_key(..., genre='action', comments=...)`; that one registration is its
dispatch (`perform_actions()`), its help row (`descr`) and its prose
(`comments`).  A key that is not in the spinner is a key the help page cannot
list, so a hand-written `handle_key()` is reserved for a mode that must own keys
first (a search bar, an inline confirmation).  C is the same shape written out
in full, with no kit, as the file to copy.

The consequence -- every key the spinner reports for a screen appears on that
screen's help page, and every `[x]` in the drawn header is a key the demo really
binds -- is a convention, checked by eye when the demo is run; the suite does
not police it.

## Conventions

- **File name:** `demos/demo-<letter>-<name>.py`, e.g.
  `demos/demo-a-basic.py`.  The `run-demo` short name is `<letter>-<name>`,
  e.g. `./demos/run-demo a-basic`.
- **Complete examples and deltas:** A and B are complete, standalone programs
  and the degenerate showcases.  C is the complete full-shape program and the
  file to copy.  D–Q import `demos/demo_kit.py`, which carries the full shape
  (window, stack, spinner with `? - help`, help page, loop, table, sample data)
  and none of the feature additions.  Each later demo adds only its row's
  features and stays short.  No demo imports another demo; `demo_kit.py` and
  `PrimeRows.py` are the only shared modules.
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
- **Live tables, calmly:** a demo whose table mutates sets
  `PrimeRows.thaw_secs` (E, F, G, H, I and J all use `5.0`), which puts the
  churn's pass count on the wall clock: one churn pass at most
  every thaw, so only one `interval`-th of the rows restyles.  The call sites do
  not change; `PrimeRows.pass_count` is the count if an app wants to show it.
  Without the thaw the churn follows the loop's `iteration`, which is right for
  a short table and a shimmer for a 2000-row one.
- **No hidden features:** the header carries the key hints.  The help screen
  exists where help itself is the lesson; it is not a place to bury a demo
  feature.
- **Header line:** `add_fancy_header()` bolds its first word as the title, so
  the title is one hyphenated token that starts with the demo's uppercase letter
  (`M-own-the-navigation-keys`, `N-pause-and-run`), and the whole title is bold.
  A key that is its hint's first letter is written once, inside the word, so
  `[q]uit` draws "quit" and `[c]heck` draws "check"; any other key is divided
  from its hint by a colon (`[y]:confirm`, `[e]:run`, `[?]:help`).
- **Uniform entry point:** every demo exposes
  `build_app(backend=None, singleton=True) -> app`, and `q` quits, so a demo can
  be exercised by hand or against `HeadlessBackend` without knowing its shape.
  `main()` is a thin wrapper around `build_app(...).main_loop()`.
- **Standalone run:** every demo uses the same two-line `cli` prelude for
  `--ascii` / `--glyphs` / `--theme` where those switches are relevant, so a
  reader can run any demo with the same flags.

## Feature ownership and the change rule

The unit of ownership is a **learning objective**, not an API symbol.  The
picking model is one feature even though it uses `set_pick_mode()`, `Context`
and `abut`; `status-levels` and `flash` are two because they are separate
lessons.  This keeps the family at 17 demos instead of one per API call.

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

The invariants -- every key maps to an existing demo, no key is owned twice,
every demo owns at least one key, and the appendix below matches `FEATURES` --
are maintained by hand when the map changes.  The suite does not check them.

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

Owns: abut, context-metadata, decor-rows, pick-mode, pick-range
Base: c-options
Run:  ./demos/run-demo d-pick
"""
```

## The family

Base names the curriculum lineage a reader should have seen first.  A and B are
the degenerate showcases; C is the full shape and the file to copy.  D–Q import
`demo_kit.py`, which carries the full shape but none of the feature additions.
The "Adds" column is the ownership list; the appendix is the same list sorted
for lookup.

| # | Demo | Base | Adds (first appearance only) |
| - | ---- | ---- | ---------------------------- |
| A | **Basic pager** — `a-basic` | — | One `Screen` whose `draw_screen()` rebuilds the page each pass. The four-call loop (`clear()` → `draw_screen()` → `render()` → `prompt()`). Static header band and separator rule (`head_line=True`). `add_header()` / `add_body()` and a title line above a column header. Built-in navigation keys (`j`/`k`, arrows, PgUp/PgDn, Home/End) scroll the body. Live data: one deterministic row changes each pass; `ConsoleWindow.timeout_ms` keeps keys responsive. |
| B | **Two pages** — `b-stack` | A | `ScreenStack.from_screens()` with more than one screen. `push()` / `pop()` / `is_curr()` driven by application keys. Per-screen content and scroll position restored on return. `ctrl_c_terminates=False`: Ctrl-C arrives as an ordinary key. `set_handled_keys()` to claim only the application's keys. |
| C | **Options** — `c-options` | B | `OptionSpinner.add_key(..., vals=...)` value cycles. `prompt=` plus `check_ans=` for validated free text that is re-asked on bad input. `scope=` per screen. Generated `BasicHelpScreen` body that lists the pushed screen's options under a `Keys for '<screen>':` heading and keeps its `cycle` / `prompt` keys live on the help screen (`help_subject()`, `options_for_screen()`), plus a `NavKeys:` legend. The body is laid out for the width the window has when it draws: the value column is measured from the listed rows, values wrap between entries under it, and a narrow terminal degrades to the dot-gap then to a flat, stacked layout. `perform_actions()` and the `<name>_ACTION()` dispatch convention. Built-in `quit` / `escape` actions and `quit_keys=`. |
| D | **Pick a row** — `d-pick` | C | `set_pick_mode(True)` and the highlighted row. `Context(genre='item', item=...)` plus `get_picked_context()`. `Context(genre='DECOR')` rows that navigation skips. `rank % 3` gives each prime 0–2 `Context(abut=-1)` detail rows, so blocks differ in height: scrolling keeps a block on screen and navigation still visits only the primary row, while the highlight is the primary row alone. Detail rows start under the `spelled` column. `rank // 5` opens a `DECOR` group header (including one at the top of the body); headers end both navigation runs and blocks. An untitled left column plus the `c` action shows what the picked context is for: it toggles a `✓` on the picked row. `set_pick_range()` for a column-range highlight. |
| E | **Filter as you type** — `e-search` | C | `IncrementalSearchBar` with `on_change` / `on_accept` / `on_cancel`. `passthrough_mode` while the bar is active. The pattern is a regex: words, dashes and spaces are matched as words in order (vappman's rule), anything else is compiled as written. A regex is invalid while it is being typed, so a pattern that does not compile yet leaves the last valid filter on the table and reverses only the `/` (`as_header_line(invalid=True)`); ENTER is ignored until the pattern compiles, and the help page says so. The table is the first 2000 prime ranks, and the spelled column is written in Sentence Case and restyled by `PrimeRows`' thaw clock (`thaw_secs = 5.0`: one churn pass every five seconds, so a tenth of the rows restyle at a time), so the table stays live and rows enter and leave the match while the `Matched:` count moves; `four` finds only the rows currently showing a lower-case "four" (about 180 at first) and all 399 once `i` ignores case. Matching is case sensitive by default and `i` (another `OptionSpinner` action) flips it, the header showing `i:[Aa]` while case matters and `i:[aa]` while it does not. The pattern is drawn at the right end of the title line, after `/`, so the keys never shift as it grows. A second header row counts what the body shows (`Matched: 1234/2000`), its `M` under the `/`. `c` (an `OptionSpinner` action) clears the pattern and the table together, and `IncrementalSearchBar.reset()` backs it. A screen-local ESC that subtracts that screen from the global escape action, and that cancels composition back to the starting pattern. An explicit empty-result row. |
| F | **Ask in place** — `f-prompts` | D | `begin_prompt()` / `prompt_active` / `handle_prompt_key()`. Single-key confirmation (`mode='y'`) with `hint=`. Buffered text input (`mode='text'`, `seed=`). `add_prompt_lines()` drawn directly under the owning row (`y` confirms that row, which then wears a `✓ confirmed` marker). `add_prompt_header()` for a screen-wide question (`t` renames the spelled column from the header band). `on_confirm` / `on_cancel` callbacks that run after passthrough is restored. |
| G | **Dialogs and the inline editor** — `g-dialogs` | C | `answer()` with `hint=` and its return/abort contract; the reply is table-wide, so it rides on the header's second line. `alert()` as a modal message. `InlineConfirmation` in `mode='identity'`, drawn under the picked row where its buffer echo and a wrong answer are visible; the row it confirms then wears a `✓` in an untitled left column, so the answer leaves a trace in the table. The line editor's caret keys (Left/Right/Home/End/Backspace/Delete). |
| H | **Messages** — `h-messages` | C | `status()` with `level='info' / 'warn' / 'error'` and `timeout=`. `status('')`, `clear_status()` and `current_status`. Separator-row placement, truncation before the scroll indicator, and deferred status when `head_line=False`. `flash()` as a timed modal message. The per-message `attr=` override. The header's second line repeats the payload decorated per level (plain, bold, bold and reversed; `info` is plain there rather than the separator row's dim), so a status never vanishes into the dim band; `PrimeRows.thaw_secs = 5.0` keeps the table still behind the message. |
| I | **Header modes** — `i-headers` | C | `HeaderLine` tokens (`label()`, `text()`, `bracket_key()`) passed to `add_fancy_header()`, so the declared roles survive while the fancy path treats the bracket delimiters as markup. The single header line carries a LABEL title, KEY spans and plain text at once, and `m` cycles `mode='Off' / 'Underline' / 'Reverse'` (Off styles nothing and keeps the brackets literal) to show how each role is emphasized. `PrimeRows.thaw_secs = 5.0` keeps the table calm while the header is compared. |
| J | **Themes and appearance** — `j-themes` | C | `Theme.create_picker_screen()` with `cycle_key=`. `ThemeStore` / `Theme.initial()` persistence. `win.set_theme()` as per-window state versus `Theme.set_active()` as process state. `mono`, `NO_COLOR` and `--theme`. `Appearance.semantic_attr()` for semantic body rows. `captions=` role renaming and the `swatch_attr()` / `swatch_rows()` overrides. `t` cycles the window's theme from the table and saves the choice through the same store, while `T` opens the picker (`t` cycles there too), so one key is bound on two screens with different scopes. `PrimeRows.thaw_secs = 5.0` keeps the table calm while the colors change. |
| K | **Glyphs and ASCII** — `k-glyphs` | C | `Glyphs.catalog_entries()` as a grouped font-check table: glyph, fallback, code point and name, with a dim divider when the family changes. `Glyphs.group_of()` / `Glyphs.lookup()` expose the family for a lookup or an iteration, while `catalog_rows()` remains the flat sample list. Application vocabulary through `ConsoleWindowOpts(glyphs=..., glyphs_probe=...)`. `Glyphs.get()` in content and its ASCII fallback. `--ascii`, `--glyphs` and `CONSOLE_WINDOW_GLYPHS`. `help.glyph_paragraph()` with `show_display_notes`. |
| L | **Read-only screens** — `l-text-screens` | C | `BasicTextScreen` and `set_text()` accepting `str` or `(text, attr)`. A `BasicHelpScreen` subclass with `extra_help_paragraphs()`, drawn under an `Instructions` separator as bulleted prose with a hanging indent. A read-only text screen with no spinner. The default `escape_ACTION()` pop. |
| M | **Own the navigation keys** — `m-own-keys` | C | `ConsoleWindowOpts(taken_nav_keys={key: label})`. `OptionSpinner(..., nav_keys=opts.nav_keys)`. LEFT/RIGHT as previous/next page, while dialogs still use them for the caret. The help legend showing the application's labels instead of the reserved arrows. |
| N | **Pause and run** — `n-suspend` | C | `suspend_curses()` / `resume_curses()`. Running an external program between them: a small shell script that clears the screen, echoes the command it runs (`+ ls -l /bin/*sh | head -n 8`), lists those real files, then holds the terminal at `===>  Return to screen?` until ENTER, so the hand-back is visible instead of instantaneous. Content and pick state surviving the hand-back, with the next `render()` repainting. The help page states what `e` is expected to do and what survives. |
| O | **Large bodies and limits** — `o-large-bodies` | C | A body that starts at 2,000 ranks and grows by 509 per `+` / shrinks by 251 per `-`, showing every `PrimeRows` field except the palindrome flag (rank, prime, digits, digit sum, binary, mod 10, gap, spelled), with viewport-sized pads. The scroll indicator on a long body. The `max_rows` safety ceiling (10,000) and `rows_dropped`; the demo captures the library's stderr `UserWarning` (which would corrupt the curses display) and replaces it with one `alert()` per run that waits for ENTER — enough of a slap in the face to deal with or ignore. `min_cols_rows`, the one-time minimum-size fit, and `TerminalTooSmallError`; the second header line prints `ConsoleWindow.min_size` and the `rows=/dropped=` pair, so the configured 40-column floor can be seen rising to the 60-column cap. Resize recovery and `render(redraw=True)`; `PrimeRows.thaw_secs = 10.0` keeps the spelled column calm while the row count moves. |
| P | **Keys and widths** — `p-key-debug` | C | `set_demo_mode()` bound as a cycling bool (`[K]:keys=off/ON`) and the last-key badge, drawn at the right edge of the first header line and faded two seconds after the key arrives while the mode stays on. `textwidth.string_width()`, `truncate()` and `ljust()`/`rjust()` for a cell-accurate table whose heading carries the same framing pipes as the body, so the columns start on the same cells. Wide CJK, a Wide emoji and combining marks aligned in columns; a `trunc6` column prefixes five `-` cells so the cut is visible, and a wide glyph that would straddle the boundary is dropped whole. The table uses an East-Asian-Width `W` emoji rather than a VS16-promoted narrow glyph, because terminals disagree on whether the selector doubles it (the disagreement is explained in the help page). `c` cycles the column-header case through lower/Title/UPPER -- a lasting mark for a key whose badge fades. |

| Q | **Marks that stay two cells** — `q-marks` | C | `Glyphs.marks()` as the approved two-cell family: 39 emoji, each a single East-Asian-Width `W` code point, so the mark is two cells in the model and in the terminal and a variation selector cannot change that. `Glyphs.mark(name)` returns the emoji or the two-cell ASCII fallback, so `a` (a cycling bool) and `--ascii` leave every column where it was; a name outside the family raises `KeyError`. `Glyphs.find_issues()` over five samples shows the four unsafe cases -- VS16-promoted, zero-width joiner, East-Asian Ambiguous, unapproved -- beside the approved marks and a plain one-cell check, which is the row to read before copying a mark out of a document. `validate_mark()` and the glyph audit speak in the same verdicts. |

## Groups at a glance

1. **Foundations (A–C).** The pager, the stack, the spinner.  These are the only
   files that need to be read from top to bottom.
2. **Rows and input (D–G).** Selecting, filtering, asking in place, and modal
   questions.  D, E and G start from C; F starts from D.
3. **Presentation (H–L).** Messages, headers, themes, glyphs and read-only text.
   H through L all start from C.
4. **Application plumbing (M–Q).** Navigation ownership, pausing, scale/safety,
   debugging aids and the width-safe mark family.  M through Q all start from C.

## Where the `demo-buffet` features go

| Buffet feature | New home |
| -------------- | -------- |
| `ScreenStack` plus MAIN/HELP/HISTORY/THEMES | B; screens reassembled in J, K and L |
| Scoped, self-subtracting spinner keys | C (the `t` on MAIN versus THEMES case) |
| `Context(genre='item')` and `get_picked_context()` | D |
| `Context(genre='DECOR')` skipped rows | D |
| Multi-row picks from `abut` (one `DECOR` header per group) | D |
| `IncrementalSearchBar` and `passthrough_mode` | E |
| In-place `y` / text prompts and `add_prompt_*` | F |
| `answer()` and `alert()` | G |
| `status()` and `flash()` | H |
| `HeaderLine` tokens / `add_fancy_header()` modes | I |
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

The demos are not covered by the library suite.  They exist to be read and run,
not to be regression-tested, and changing one must not require changing a test.

The only gate is `tests/test_demo_syntax.py`: it imports every `demos/*.py` in a
subprocess, which checks the syntax and that every public API name the script
uses at import time still exists.  It makes no assertion about screens, keys,
help pages, output or the feature map, and `[tool.coverage.run]` omits `demos/`
from the measurement.

Behaviour is checked the way a reader checks it: `./runner` or
`./demos/run-demo <name>`, plus `./demos/run-demo features` for the map.  The
change rule above is a documentation convention, not an enforced invariant;
that is deliberate, so a demo can be reworked without touching `tests/`.

The old `tests/test_sample_app.py` imported `demos/demo-buffet.py` and made
393 lines of assertions about its screens.  Its replacement,
`tests/test_demos.py`, drove every demo headlessly and enforced the manifest,
headers and help pages; both were removed for the reason above.

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
      agreement); later removed with the rest of the demo tests (see Test
      plan).
- [x] Rewrite `demos/demos.ini` as the lettered menu, one `run-demo` line per
      demo, with group comments and no buffet entry.
- [x] Update the `run-demo` docstring (it still names `buffet` as the example).
- [x] Rename and retarget the buffet-oriented `tests/test_sample_app.py` as
      `tests/test_demos.py`: keep the generic smoke harness and port the
      feature-specific assertions listed above; later replaced by the
      syntax/import gate.
- [x] Delete `demos/demo-buffet.py`.
- [x] Update `README.md`: the "Running the Sample App" section becomes the demo
      menu; the 20-bullet buffet walkthrough becomes a three-demo progression
      (A → B → C) plus this document; fix the dead `SampleApp.py` links.
- [x] Add a `tests/CHANGELOG.md` entry under `[3.0.0]`: the demo family replaces
      `demo-buffet`; list the renamed demos; and make every feature bullet name
      its owning `demo: <name>` from then on.
- [x] Make the full shape the kit's default: `build_screens()` returns the main
      screen and a `DemoHelpScreen`, `new_spinner()` binds `? - help`, and a
      demo's prose is `help_paragraphs` / `help_display_notes` rather than a
      help-screen subclass.  H, I, N, O and P register their keys as spinner
      actions (with `comments=` prose), so "no help" is no longer a demo style.
- [x] Guard the result in `tests/test_demos.py`: every key the spinner reports
      for a screen must appear on its help page, and every `[x]` in the drawn
      header must be a key the demo really binds; later removed with the rest of
      the demo tests.
- [x] Run the gate: `.venv/bin/ruff check .` and `.venv/bin/python -m pytest -q`.

## Definition of done

- Seventeen demos, A through Q.  A–C are complete files; D–Q are deltas on
  `demo_kit.py`, each within the size ceiling.
- Every feature key in `FEATURES` appears exactly once, in the demo that owns
  it, and every demo's `Owns:` docstring matches its keys (maintained by hand).
- The appendix in this document is rendered from `FEATURES` and matches it.
- Every feature add/change in the changelog names its owning demo.
- Every demo after B has a help page that lists every key it binds, and no
  header advertises a key the demo does not bind (a review convention).
- Every `demos/*.py` compiles and imports against the public API.  Behaviour
  needs no TTY and is checked by running the demo, not by the test suite.
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
| `mark-catalog` | `q-marks` |
| `mark-detector` | `q-marks` |
| `mark-fallback` | `q-marks` |
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
| `prompt-callbacks` | `f-prompts` |
| `prompt-placement` | `f-prompts` |
| `read-only-screen` | `l-text-screens` |
| `redraw-recovery` | `o-large-bodies` |
| `regex-filter` | `e-search` |
| `safe-marks` | `q-marks` |
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
| `text-prompt` | `f-prompts` |
| `textwidth` | `p-key-debug` |
| `theme-captions` | `j-themes` |
| `theme-picker` | `j-themes` |
| `theme-store` | `j-themes` |
| `validated-prompt` | `c-options` |
| `wide-characters` | `p-key-debug` |
