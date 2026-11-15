# Demo gaps: what the applications use and the demos never show

This is the reading of [`docs/API-USAGE.md`](API-USAGE.md) that asks the useful
question: **which public APIs have application users but no demo, and does that
mean the demos are missing a lesson?**

Verdict, before the evidence:

1. **One real gap** — the runtime color switch (`Appearance.set_colors_enabled()` /
   `colors_enabled()`), which four applications use and no demo ever flipped.
   Plugged at the source: the `C` key in
   [`demo-j-themes`](../demos/demo-j-themes.py), not a new demo.
2. **One orphaned export** — `reset_ctrl_c`, the only public name with no consumer
   anywhere. Plugged: [`demo-n-suspend`](../demos/demo-n-suspend.py) calls it across
   its external-program hand-back.
3. **Everything else is an artefact of version skew.** The application corpus is
   pre-3.0 code: 106 calls across all ten applications still use the
   window-direct drawing API that 3.0 removed. A name the applications use and the
   demos do not is therefore usually *migration debt*, not a missing demo.

The family stays at seventeen demos. Both plugs are one key (or one call) plus
prose, and both obey the change rule in [`docs/DEMO-APPS.md`](DEMO-APPS.md):
demo, `Owns:` line, [`demos/features.py`](../demos/features.py) and the changelog
move together.  The counts below are the post-plug report; the two plugged
families read `0` in the demo column before the change.

## Method

The candidate set is every name whose `demos` column is `0` and whose `apps`
column is not, in either table of [`docs/API-USAGE.md`](API-USAGE.md).  Each
candidate then faces three filters; it is a gap only if it passes all three.

1. **Spread.** At least two applications, and at least one call site that is not
   an import, a test, or a type annotation.  A single application with a dozen
   calls is that application's style, not a lesson.
2. **Shape.** The call site must use the 3.0 API.  [`README.md`](../README.md:348)
   records that `win.add_header()`, `win.add_body()`, `win.add_fancy_header()`,
   `win.add_header_line()`, `win.add_prompt_header()` and `win.add_prompt_lines()`
   are gone, and that a `Screen` is the object those calls belong on.  Call sites
   that pass a `ConsoleWindow` where a `Screen` is wanted are pre-3.0 code, so
   they cannot demonstrate a 3.0 gap.
3. **Replacement.** The sanctioned 3.0 path must not already be demonstrated.
   Counts are references, and a demo can exercise a name through a helper:
   every demo's `run_main()` calls `cli.apply_display_arguments()`, which calls
   `Appearance.resolve_appearance()` and `Theme.set_active()`; `begin_prompt()`
   drives `PromptLine`; `HeaderLine` builds `Span`s.

## The corpus is 2.x-shaped

Calls to the removed window-direct methods, by application (AST census, vendored
trees excluded):

| Application | `win.add_*` | `self.add_*` |
| --- | ---: | ---: |
| dwipe | 23 | 0 |
| grub-wiz | 20 | 3 |
| pypi-cleanup-tui | 18 | 0 |
| memfo | 17 | 0 |
| vappman | 9 | 0 |
| my-snaps | 7 | 0 |
| psistat | 7 | 0 |
| efibootdude | 3 | 0 |
| zram-advisor | 2 | 0 |
| pmemstat | 0 | 4 |
| **total** | **106** | **7** |

The demos are the mirror image: 29 `self.add_body()` calls and **zero**
`win.add_body()` calls.  Two consequences for reading the usage table:

- An application count for `Screen.add_body` is small (7) not because
  applications draw less, but because they draw through the window handle that
  3.0 no longer accepts.  The demos are ahead of the corpus, not behind it.
- A method listed as "no demo use, some application use" is frequently the 2.x
  spelling of something a demo already teaches in its 3.0 form.  The filters
  below name the replacement.

## The gap: the runtime color switch

| Name | demos | apps | spread |
| --- | ---: | ---: | --- |
| `Appearance.set_colors_enabled()` | 1 | 17 | 4 applications |
| `Appearance.colors_enabled()` | 2 | 15 | 4 applications |
| `set_colors_enabled` (entry point) | 1 | 54 | 7 applications |
| `colors_enabled` (entry point) | 2 | 51 | 6 applications |

What [`demo-j-themes`](../demos/demo-j-themes.py) already showed: `--theme`,
`mono`, `NO_COLOR`, `Theme.set_active()`, `win.set_theme()`, the picker screen,
`semantic_attr()`, `captions=`, and the swatch overrides.  What it did not show
was the switch moving **while the program runs**, and being read back to choose
an attribute.

That is not stale: [`console_window/_appearance.py`](../console_window/_appearance.py:45)
documents the switch as public "for embedding code that manages the switch
directly", and
[`console_window/_appearance.py`](../console_window/_appearance.py:135)
is the branch every semantic lookup takes.  Applications that parse their own
`--no-color` reach for it after their own argument handling, the same moment the
demos reach for `cli.apply_display_arguments()`; before the plug the demo showed
only the second route.

**Applied.**  In `demo-j-themes`:

- `C` is bound in the spinner (`cycle_color`, `genre='action'`, `scope` MAIN),
  described on the help page as "color on/off";
- `cycle_color_ACTION()` calls
  `Appearance.set_colors_enabled(not Appearance.colors_enabled())`;
- the header band prints `[C]olor=on|off`, and a second header row reads
  `Appearance.colors_enabled()` back through
  `Appearance.semantic_attr(Theme.EMPHASIS)`, so the flip shows as hue versus
  bold and the switch is visibly the input to the attribute choice;
- one help paragraph: `mono` is the *theme* that turns color off through
  `Theme.set_active()`, so the next `t` resynchronizes a switch flipped by hand
  — which is why the switch is the low-level entry point.

Bookkeeping: `'runtime-color-switch': 'j-themes'` in
[`demos/features.py`](../demos/features.py), the `Owns:` line,
[`docs/DEMO-APPS.md`](DEMO-APPS.md)'s J row and appendix, and the changelog.

A new demo was considered and rejected: the objective is one key and one
paragraph, and J already owns "appearance".  Creating an eighteenth demo for it
would violate the one-objective-per-demo rule in the other direction.

## The orphan: `reset_ctrl_c`

`reset_ctrl_c` is the only name in `console_window.__all__` with no consumer at
all — no demo, no application.  It restores the pre-library SIGINT handler and
clears the policy latch, which is the signal half of the same hand-back: run a
program that owns the terminal, then take the library's policy back.

[`demo-n-suspend`](../demos/demo-n-suspend.py) already runs an external program
between `suspend_curses()` and `resume_curses()`, so the lesson was one call
away and the demo's help page already said what survives the hand-back.

**Applied.**  `run_external()` calls `reset_ctrl_c()` between the external
program and `resume_curses()`, which installs the library's policy again; the
demo docstring and a help paragraph say that the signal goes with the screen.
A headless trace of the demo shows the nuance worth teaching: the suspend path
already calls `teardown_ctrl_c()`, which resets when the last window suspends, so
the demo's call is the explicit and idempotent form of a hand-back that would
otherwise only be implied — the same call an embedding application makes when it
wants to own Ctrl-C for the duration of a program it runs.
Bookkeeping: `'ctrl-c-reset': 'n-suspend'`, the N `Owns:` line, the N row, the
changelog.

## Deliberately not plugged

| Candidate | Evidence | Why it is not a demo gap |
| --- | --- | --- |
| `HOME_ST` | 3 applications (vappman 29, grub-wiz 19, my-snaps 7) | A convenience constant for screen 0. [`console_window/screens.py`](../console_window/screens.py:30) says applications should define their own, and the demos do (`MAIN_ST = 0`). This is a decision about the export, not about a demo: keep it as the 2.x spelling or mark it legacy in the 3.0 breakage notes. |
| `resolve_appearance` | 4 applications | Covered transitively: every demo's `run_main()` calls `cli.apply_display_arguments()`, which calls it. The demos teach the two-line prelude, which is the sanctioned path. |
| `.show_help_body()`, `.show_help_nav_keys()` | 7 and 6 applications | Six of the seven sites pass a window (`spinner.show_help_nav_keys(app.win)`) and then call `window.add_body(...)`: pre-3.0. `pmemstat` passes a `Screen` for its help-as-a-mode, which [`docs/SCREEN-OVERHAUL-PLAN.md`](SCREEN-OVERHAUL-PLAN.md:230) already lists for migration. `BasicHelpScreen` (C, L) is the 3.0 replacement. |
| `.calc()`, `.fix_positions()`, `.render_once()`, `.start_curses()` | 3, 2, 1, 2 applications | `pmemstat` and `psistat` call `calc()` in the same pass as `window.add_*` (2.x); `vappman`'s calls are in its test harness; `pypi-cleanup-tui` has one `fix_positions()` site. `render()` calls `calc()` internally and O already teaches resize recovery. Revisit only if a 3.0-shaped application needs a hand-driven frame. |
| `.set_ascii()` | 1 application (grub-wiz, 14 calls) | One application's runtime toggle. K teaches `--ascii`, `--glyphs`, `glyphs_probe` and `Glyphs.get()`. |
| `.get_value()` | 1 application (pypi-cleanup-tui, 9 calls) | Reading a spun value; C, D and E exercise `vals=` and the written value. |
| `.set()`, `.apply_to()`, `.is_mono()` | 2, 2, 1 applications | Process-wide theme install. No application is multi-window: `active_windows()` and `primary_window()` have zero application users, so the entry point exists for a case the corpus does not have. J covers the user-visible behaviour (`t`, `T`, the picker). |
| `.draw_notes()`, `.escape_ACTION()`, `.get_spinner()`, `.set_text()`, `.extra_help_paragraphs()`, `.glyph()`, `.search()`, `.stop_all()` | 1–2 applications each | Either one application, or already demonstrated in L (text screens, extra paragraphs, the default escape pop) and H (messages). `stop_all()` is atexit-shaped teardown; the demo-visible exit is `stop_curses()` (154 calls). |
| `NAVIGATION_KEYS` | 1 application, in a test | Test-only reference. |
| `MONO_ROLES` | 3 applications, two references each | An import and a stub. The API is `Appearance.semantic_attr()`, which J shows. |
| `Glyph` | 1 application, 3 references | A type annotation in one file. K covers the glyph vocabulary. |

## Two measurement caveats

- **Demo counts are attributed call sites**, not references.  A call through a
  chained receiver (`Something().method()`) is not attributed unless it is
  `super()`, which is why `.set_text()` read `0` until derived-class
  constructors were resolved.  Read the entry-point table for presence and the
  methods table for volume.
- **Applications pin older releases.**  Their virtualenvs hold installed copies
  of this library, so the counting script excludes `.venv`, `build/` and `dist/`
  trees; a name they use may not exist in this tree at all, and a signature they
  use may differ from the current one.

## What to do

1. ~~`demo-j-themes`: bind `C`, flip `Appearance.set_colors_enabled()`, read it
   back, add the paragraph.  Owns `runtime-color-switch`.~~ Done.
2. ~~`demo-n-suspend`: call `reset_ctrl_c()` after the external program.  Owns
   `ctrl-c-reset`.~~ Done.
3. Leave the rest.  The next real gap is not a demo at all — it is the
   applications' migration from window-direct drawing to `Screen`, which the
   demos already document in their 3.0 form.
4. Decide the fate of `HOME_ST`, `NAVIGATION_KEYS` and `MONO_ROLES` as *exports*
   in the 3.0 breakage notes; none of them needs demo coverage.
5. Re-run `tests/api_usage_report.py --write docs/API-USAGE.md` after the next
   round of demo changes; the zero rows in the report are the input to this
   document, and both plugged families now read non-zero.
