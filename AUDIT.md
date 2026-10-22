# `console-window` — Code & Design Audit

**Audited:** 2026-10-15 (`368304d`); **refreshed:** 2026-10-18 (`15125a8`) after removing every finding that has since been resolved. Section references inside older `CHANGELOG.md` entries point at the pre-refresh numbering.
**Scope:** the `console_window` package, its test suite, `SampleApp.py`, `runner`, packaging and CI. Competitive/ecosystem analysis is deliberately excluded (it is covered in [`README.md`](README.md:1)).
**Method:** full source read of all 14 package modules plus the example and tests; `ruff`, `pylint`, `mypy`, `pytest` and `coverage` run locally; API reachability established by repo-wide call-site search, not by inference.

| Metric | Value |
| --- | --- |
| Package size | 3,988 lines / 2,391 statements across 14 modules; stdlib-only, POSIX curses |
| Example | [`SampleApp.py`](SampleApp.py:1) 532 lines; [`runner`](runner:1) 13 lines |
| Tests | 268 tests, ~3,045 lines in 18 files — **all pass** (1.5 s) |
| Coverage (`--source=console_window`) | **87%** overall; engine [`window.py`](console_window/window.py:1) **88%**, [`theme.py`](console_window/theme.py:1) **69%**, [`screens.py`](console_window/screens.py:1) **67%** |
| `ruff check .` | clean (`E,F,W,I,B,C4,ANN,RUF,C901`) |
| `pylint` | 9.92/10 with `C,R` disabled |
| Type checking | **mypy** configured for `console_window` and run in CI; clean (14 source files) |
| Complexity (ruff `C901`, threshold 12) | `prompt()` decomposed from 43 to **5**; worst remaining is [`answer()`](console_window/window.py:1167) at **12** |

## 1. Executive summary

The library is small, dependency-free, and unusually disciplined for a single-author project: a real module split, a headless render backend, 268 fast TTY-free tests, a green linter and type checker, changelog and release metadata, and a worked example that is itself smoke-tested. Resolved findings from the 2026-10-15 audit have been removed from this document; [`CHANGELOG.md`](CHANGELOG.md:1) records them.

The remaining risks are narrower than the ones in the original audit. There is no data-loss or security defect, and the interactive core is no longer an untested hole. What is left is a body of unreachable or dead-but-broken public surface, residual process-global state, and CI that cannot reproduce its own inputs. Highest-risk findings, in order:

1. **A meaningful amount of public API is unreachable.** `ConsoleWindow.set_pick_range()` and `BasicHelpScreen` have no consumer outside the test suite (§3.3).
2. **The theme is per-window, but colour pairs are per-terminal.** `ConsoleWindowOpts(theme=...)`, `ConsoleWindow.theme` and `set_theme()` make the selection per window and install it through that window's backend; curses owns one pair table per terminal, so windows sharing one screen still show one palette at a time (§3.1).
3. **CI is green but shallow.** Tool versions are unpinned, and there is no coverage or `pylint` gate, so the current 87% coverage and 9.92/10 score are not protected (§3.4).

None of these is a data-loss or security defect, and the project's own bar remains high. The work left is concentrated in the list above rather than spread across the package.

## 2. Architecture as implemented

| Module | Lines | Stmts | Cover | Role |
| --- | --- | --- | --- | --- |
| [`window.py`](console_window/window.py:1) | 1983 | 1185 | 88% | The engine: two pads + screen, add/draw/render/prompt/answer/alert/flash, navigation |
| [`widgets.py`](console_window/widgets.py:1) | 337 | 231 | 86% | `InlineConfirmation`, `IncrementalSearchBar` (pure, no curses drawing) |
| [`spinner.py`](console_window/spinner.py:1) | 333 | 225 | 87% | `OptionSpinner`: key → option registry, genre inference, scope subtraction, help body |
| [`screens.py`](console_window/screens.py:1) | 234 | 159 | 67% | `Screen` base, `ScreenStack` router, `HOME_ST`, `BasicHelpScreen` |
| [`theme.py`](console_window/theme.py:1) | 231 | 71 | 69% | 7 palettes, `set()`/`set_active()`, picker-screen factory |
| [`textwidth.py`](console_window/textwidth.py:1) | 170 | 129 | 95% | Display-cell arithmetic: width, truncate, justify, wrap, wrap positions |
| [`header.py`](console_window/header.py:1) | 126 | 88 | 99% | `Span`/`HeaderLine` token API + legacy `[x]`/`KEY:` string parser |
| [`backend.py`](console_window/backend.py:1) | 279 | 128 | 88% | `Surface`/`RenderBackend` protocols, `CursesBackend`, `HeadlessBackend` |
| [`geometry.py`](console_window/geometry.py:1) | 82 | 61 | 100% | Pure abut/indicator/pickable-row math |
| [`opts.py`](console_window/opts.py:1) | 78 | 59 | 100% | `ConsoleWindowOpts` (`__slots__` + kwargs) |
| [`context.py`](console_window/context.py:1) | 37 | 17 | 100% | Per-row `Context` (`genre`/`pickable`/`abut` + open kwargs) |
| [`signals.py`](console_window/signals.py:1) | 49 | 24 | 96% | SIGINT policy globals |
| [`keys.py`](console_window/keys.py:1) | 18 | 3 | 100% | `NAVIGATION_KEYS` |
| [`__init__.py`](console_window/__init__.py:1) | 31 | 11 | 100% | Re-exports + `__all__` |

**Frame cycle.** `main_loop` → `screen.draw_screen()` (`clear()` + `add_header*`/`add_body` into the two pads) → `win.render()` → `fix_positions()` (clamp/scroll/pick, returns `indent`) → gutter/separator/indicator → `pnoutrefresh` both pads → `doupdate()` → `win.prompt()` (key read + built-in navigation) → `handle_key()` → `stack.perform_actions(spin)` (convention dispatch of `<attr>_ACTION`) → `clear()`.

**Two data models, one window.** Layout/scroll/pick live in `SimpleNamespace`s (`self.head`, `self.body`) with parallel lists (`texts`, `text_attrs` run-length encoded, `contexts`, `row_cnt`); `Row Context` carries per-row semantics. `Screen` subclasses add routing and `*_ACTION` dispatch. `OptionSpinner` is the key/option registry, optionally scope-aware per screen with automatic scope subtraction ([`spinner.py:134`](console_window/spinner.py:134)).

**The seam covers the drawing, input and colour paths.** `RenderBackend` abstracts `start`/`newpad`/`doupdate`/`curs_set`/`update_lines_cols`/`is_term_resized`/`has_colors`/`start_color`/`use_default_colors`/`init_pair`/`color_pair`/`stop`, and the dialogs, flash, resize checks and colour init all go through it.

**Two window models over that seam.** `ConsoleWindow(singleton=True)` (the default) restores the historical process-wide screen: every instance shares one screen/backend, `static_scr`/`static_win` are populated, and `ConsoleWindow.stop_curses()` tears the process screen down. `singleton=False` keeps the per-instance model: each window owns its screen and teardown, and `stop_all()` is the multi-window hook. The first construction latches the mode process-wide; mixing values asserts.

**Current shape.** Docstrings have been replaced by comments, `_selftest.py` is folded into `SampleApp.py`, the pad-overflow contract is counted + warned + enforced in this project's suite, and the package version is single-sourced through `dynamic = ["version"]`.

## 3. Findings

### 3.1 🟢 Per-window theme and a reversible Ctrl-C policy (resolved)

The active theme is per-window. `ConsoleWindowOpts(theme=...)` seeds [`ConsoleWindow.theme`](console_window/window.py:242) ([`opts.py:40`](console_window/opts.py:40)); [`set_theme()`](console_window/window.py:397) installs the palette through that window's backend and repaints its pads; startup ([`_init_screen()`](console_window/window.py:583)) and pad reallocation ([`_apply_pad_theme()`](console_window/window.py:424)) read the window's own theme. [`Theme.set()`](console_window/theme.py:180) remains the process-wide switch and now relabels every live window. All three install paths share [`Theme.pair_specs()`](console_window/theme.py:156), so they cannot drift apart.

The Ctrl-C policy still latches terminating Ctrl-C while any window depends on it, so a non-terminating window cannot swallow Ctrl-C after a terminating one exists. What changed is the other end: [`setup_ctrl_c()`](console_window/signals.py:82) captures the handler that was installed *before* the first window ([`signals.py:33`](console_window/signals.py:33)), and [`teardown_ctrl_c()`](console_window/signals.py:107) restores it only when the last live window stops. Setups and teardowns are counted per window (including latched no-ops), so stopping one of several windows cannot disarm the others. The restore also clears the latch, so a later window can make Ctrl-C an application key again, and [`reset_ctrl_c()`](console_window/signals.py:116) — exported from the package root — is the deliberate reset for an embedding application that manages SIGINT itself.

**Limit (curses, not this library):** colour pairs belong to the terminal, so two windows drawing on one screen cannot show different palettes at the same time. What is per-window is the recorded choice and what is applied at startup, on pad reallocation, and by `set_theme()`.

### 3.2 🟢 `draw()` now shares the `_add()` overflow contract (resolved)

Overflow through `_add()` is counted (`ns.rows_dropped`, exposed as [`ConsoleWindow.rows_dropped`](console_window/window.py:413)), warned about once per fill episode with a caller-facing `stacklevel`, reset by [`clear()`](console_window/window.py:1926), non-fatal by design, and enforced in this project's own suite via `filterwarnings = ["error::UserWarning"]` ([`pyproject.toml:49`](pyproject.toml:49)).

The earlier gap no longer describes the implementation. Under the viewport-sized-pad model, [`draw()`](console_window/window.py:823) writes the row model, bounds `y` against `ns.rows` (the same `max_rows` ceiling `_add()` enforces, not the pad height), fills any gap in `texts`/`text_attrs`/`contexts`, and records the span in `ns.drawn` for replay by `_paint_row()`/`_overlay_spans()` on a full repaint. [`highlight_picked()`](console_window/window.py:865) goes through `_pad_row()`, which skips rows outside the viewport and rows beyond `texts`, so there are no phantom rows to walk.

One real gap remained: `draw()` returned silently when `y >= ns.rows`. That path now calls [`_warn_rows_dropped()`](console_window/window.py:716) with `stacklevel=3`, so an over-ceiling draw is counted in `rows_dropped`, warned about once per fill episode, and attributed to the caller's line — the same policy as `_add()`. [`tests/test_overflow.py`](tests/test_overflow.py:148) pins the body and header cases; [`tests/test_interactive.py`](tests/test_interactive.py:377) keeps negative/out-of-width coordinates as silent no-ops.

### 3.3 🟡 Unreachable public surface (and dead code in the example)

No consumer outside the test suite for:

| Symbol | Where | Note |
| --- | --- | --- |
| `ConsoleWindow.set_pick_range()` | [`window.py:518`](console_window/window.py:518) | The `pick_range` feature's only public entry point; called only by [`tests/test_interactive.py`](tests/test_interactive.py:1) |
| `BasicHelpScreen` | [`screens.py:227`](console_window/screens.py:227) | Exported in `__all__`, unused; the sample app writes its own help screen |
| `OptionSpinner.add()` | [`spinner.py:163`](console_window/spinner.py:163) | Retired shim; raises `NotImplementedError` pointing to `add_key()` (see below) |
| `draw()` | [`window.py:749`](console_window/window.py:749) | Used only by [`tests/test_interactive.py`](tests/test_interactive.py:365) and [`tests/test_widechars.py`](tests/test_widechars.py:1) |
| `add_fancy_header()` string path | [`window.py:685`](console_window/window.py:685) | The sample uses `add_header_line()`; only tests exercise the string path |
| `demo_mode` / `set_demo_mode()` | [`window.py:325`](console_window/window.py:325) | Only tests toggle it; internal prompt/render code reads `opts.demo_mode` |

`OptionSpinner.add()` was a pre-2.0 compatibility shim that truncated `ns.vals` and *then* sliced it with the pre-truncation index, so `ns.comments` was always empty — the parameter it existed for was silently dropped. Since no in-repo consumer uses it, it is kept only as a tombstone: the signature remains (so old callers fail at the call rather than at import) and it raises `NotImplementedError` naming `add_key()` and showing the replacement call.

`ScreenStack.act_in()` and `is_curr()` were promoted rather than removed: the README now documents them, [`tests/test_screens.py`](tests/test_screens.py:1) covers one-shot flag consumption, screen filtering and the missing-flag case, and `act_in()` returns `False` for a flag that was never set instead of raising `AttributeError`.

The same is true of one example method: `DemoApp.do_key()` ([`SampleApp.py:219`](SampleApp.py:219)) is never called (`main_loop` calls [`handle_key()`](SampleApp.py:184), which calls `spin.do_key` directly). The sample's `THEMES` screen is now generated by [`Theme.create_picker_screen()`](console_window/theme.py:186) and covered by [`tests/test_theme.py`](tests/test_theme.py:1), so its hand-written draw/cycle pair is gone.

**Fix:** delete what no consumer needs (these are pre-2.0 leftovers), or promote it deliberately: give each survivor a test and a README mention. `OptionSpinner.add()` is done: it now fails loudly instead of registering a broken option.

### 3.4 🟡 CI is green but shallow, and its inputs are unpinned

[`.github/workflows/ci.yml`](.github/workflows/ci.yml:1) runs `pytest -q` on 3.10-3.13, `ruff check .` and `mypy`, installing `pytest`, `ruff` and `mypy` **unpinned** ([`ci.yml:22`](.github/workflows/ci.yml:22), [`ci.yml:36`](.github/workflows/ci.yml:36), [`ci.yml:50`](.github/workflows/ci.yml:50)) — a new tool release can break the build with no code change, and the same build cannot reproduce yesterday's result. There is no coverage gate and no `pylint` (so the 87% coverage and 9.92/10 figures in this audit are not protected by CI).

### 3.5 🟢 `answer()` residual: class-wide retry budget and key draining

[`answer()`](console_window/window.py:1167) now has one unambiguous meaning per outcome (`str` = submitted, `None` = user abort, `TerminalTooSmallError` = environment), and its recovery loop is bounded. Two narrow issues remain:

* the budget is the class-wide `render_retry_seconds` ([`window.py:1193`](console_window/window.py:1193)) rather than a dialog-specific option;
* [`_recover_from_resize()`](console_window/window.py:1522) still drains and **discards** every queued key ([`window.py:1528`](console_window/window.py:1528)).

**Fix:** make the dialog retry budget configurable and preserve (or explicitly document the loss of) keys typed during recovery.

### 3.6 🟢 Lint findings lack rationale

`pylint` remains in the high 9s only because its warnings are few, not because they are annotated. Current examples: protected-member access ([`window.py:78`](console_window/window.py:78), [`window.py:84`](console_window/window.py:84), [`theme.py:201`](console_window/theme.py:201)), unused arguments ([`window.py:1742`](console_window/window.py:1742), [`backend.py:252`](console_window/backend.py:252), [`backend.py:278`](console_window/backend.py:278)), a not-callable method ([`screens.py:67`](console_window/screens.py:67)), and broad exceptions in the example ([`SampleApp.py:150`](SampleApp.py:150), [`SampleApp.py:523`](SampleApp.py:523)). Each is plausibly deliberate, but none says why. The `signals.py` findings are now annotated (module-level rationale for the process-global policy, a scoped disable on the signal handler's fixed signature).

**Fix:** add a short rationale comment or a scoped `# pylint: disable=...` at each site, so a future reader can distinguish intent from accident.

## 4. Prioritized recommendations

**P1 — robustness and surface**

1. Delete or promote the unreachable API (§3.3) and delete `DemoApp.do_key()`.
2. Pin CI tool versions and add a coverage floor (even a low one, e.g. `--cov-fail-under=80`) so the suite cannot silently shrink (§3.4).

**P2 — honesty and hygiene**

4. ~~Make the active theme per-window (or document one-theme-per-process), and capture/restore the host SIGINT handler or expose a reset (§3.1).~~ Done: `ConsoleWindowOpts(theme=...)` / `ConsoleWindow.set_theme()`, captured-and-restored SIGINT handler, and the exported `reset_ctrl_c()`.
5. Make the dialog retry budget configurable and stop discarding keys during resize recovery (§3.5).
6. Add rationale comments or scoped disables for the remaining `pylint` findings (§3.6).

## 5. What is genuinely good (protect it)

* **The test suite is fast and genuinely TTY-free** (290 tests in 1.5 s) and includes headless smoke tests for the example ([`tests/test_sample_app.py`](tests/test_sample_app.py:1)), the interactive core ([`tests/test_interactive.py`](tests/test_interactive.py:1)) and the overflow contract ([`tests/test_overflow.py`](tests/test_overflow.py:1)).
* **The overflow contract for `_add()` is a model of restraint** — counted, warned once, non-fatal for users, fatal in the project's own suite ([`pyproject.toml:49`](pyproject.toml:49)), and it paid for itself in the same commit by finding the sample app's clipped help screen.
* **The `prompt()` loop is decomposed and guarded** — the one 160-line, complexity-43 function is now a 12-line intake loop over small helpers (worst `prompt`-family helper: 4), and `C901` at a ratcheted threshold of 12 prevents a new monolith ([`pyproject.toml:62`](pyproject.toml:62)).
* **`textwidth` and `geometry` are pure and near-fully covered** (95%/100%) — the right place for the fiddly math.
* **`Context`'s near-miss warning** ([`context.py:30`](console_window/context.py:30)) and **`OptionSpinner`'s conflict detection** ([`spinner.py:127`](console_window/spinner.py:127), [`spinner.py:142`](console_window/spinner.py:142)) turn silent misconfiguration into loud `ValueError`/warning at the exact point of the mistake.
* **Packaging is correct**: flit module config, static metadata, `__all__` matching the re-exports, and a `runner` that executes the example as `__main__` without an installed package.

## 6. Reproduction

```bash
python3 -m ruff check .
python3 -m pytest -q
python3 -m coverage run --source=console_window -m pytest -q && python3 -m coverage report -m
python3 -m pylint console_window SampleApp.py runner --disable=C,R
python3 -m mypy
python3 -m ruff check --select C901 console_window SampleApp.py   # uses the ratchet in pyproject.toml
python3 -W error::UserWarning -c "import SampleApp"   # exit path for the pad-overflow policy
```
