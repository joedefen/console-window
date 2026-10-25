# `console-window` — Code & Design Audit

**Audited:** 2026-10-22 (working tree on `4f48396`).
**Scope:** the `console_window` package, its test suite, `SampleApp.py`, `runner`, packaging and CI. Competitive/ecosystem analysis is deliberately excluded (it is covered in [`README.md`](README.md:1)).
**Method:** full source read of all 14 package modules plus the example and tests; `ruff`, `pylint`, `mypy`, `pytest` and `coverage` run locally; API reachability established by repo-wide call-site search, not by inference.

| Metric | Value |
| --- | --- |
| Package size | 4,512 lines / 2,607 statements across 14 modules; stdlib-only, POSIX curses |
| Example | [`SampleApp.py`](SampleApp.py:1) 520 lines; [`runner`](runner:1) 13 lines |
| Tests | 302 tests, ~3,670 lines in 21 files — **all pass** (1.4 s) |
| Coverage (`--source=console_window`) | **90%** overall; engine [`window.py`](console_window/window.py:1) **89%**, [`spinner.py`](console_window/spinner.py:1) **92%**, [`widgets.py`](console_window/widgets.py:1) **86%**, [`screens.py`](console_window/screens.py:1) **83%** |
| `ruff check .` | clean (`E,F,W,I,B,C4,ANN,RUF,C901`) |
| `pylint` | **10.00/10** with `C,R` disabled (0 warnings) |
| Type checking | **mypy** configured for `console_window` and run in CI; clean (14 source files) |
| CI gates ([`.github/workflows/ci.yml`](.github/workflows/ci.yml:1)) | tests on 3.10-3.13 with `--cov-fail-under=80`; `ruff`, `mypy` and `pylint --disable=C,R` jobs; every tool pinned (`pytest 9.1.1`, `pytest-cov 7.1.0`, `ruff 0.17.0`, `mypy 2.4.0`, `pylint 3.3.4`) |
| Complexity (ruff `C901`, threshold 12) | worst is [`answer()`](console_window/window.py:1384) at **12**; next are [`parse_fancy_header()`](console_window/header.py:113) and [`perform_actions()`](console_window/screens.py:197) at **11** |

Section numbers in older [`CHANGELOG.md`](CHANGELOG.md:1) entries and in source comments refer to earlier revisions of this document.

## 1. Executive summary

The library is small, dependency-free, and unusually disciplined for a single-author project: a real module split, a headless render backend, 302 fast TTY-free tests, a green linter and type checker, changelog and release metadata, and a worked example that is itself smoke-tested.

There is no data-loss or security defect, and the interactive core is well covered. What is left is a small body of public surface with no consumer outside the test suite; the dialog retry policy is documented as an accepted limitation and every lint finding now states its reason. Highest-risk findings, in order:

1. **Some public API has no consumer.** `ConsoleWindow.set_pick_range()`, `ConsoleWindow.draw()` and the `OptionSpinner.add()` tombstone are reached only from tests (§3.1).
2. **The dialog retry policy is class-wide and discards input.** `answer()` spends the shared `render_retry_seconds` budget, and resize recovery drains every queued key. Both are now explicit, documented limitations rather than silent surprises (§3.2).

## 2. Architecture as implemented

| Module | Lines | Stmts | Cover | Role |
| --- | --- | --- | --- | --- |
| [`window.py`](console_window/window.py:1) | 2193 | 1271 | 89% | The engine: two pads + screen, add/draw/render/prompt/answer/alert/flash, navigation |
| [`widgets.py`](console_window/widgets.py:1) | 337 | 231 | 86% | `InlineConfirmation`, `IncrementalSearchBar` (pure, no curses drawing) |
| [`spinner.py`](console_window/spinner.py:1) | 339 | 215 | 92% | `OptionSpinner`: key → option registry, genre inference, scope subtraction, help body |
| [`screens.py`](console_window/screens.py:1) | 248 | 161 | 83% | `Screen` base, `ScreenStack` router, `HOME_ST`, `BasicHelpScreen` |
| [`theme.py`](console_window/theme.py:1) | 303 | 100 | 98% | 7 palettes, `set()`/`set_active()`, picker-screen factory |
| [`textwidth.py`](console_window/textwidth.py:1) | 236 | 167 | 95% | Display-cell arithmetic: width, truncate, justify, wrap, wrap positions |
| [`header.py`](console_window/header.py:1) | 162 | 110 | 97% | `Span`/`HeaderLine` token API + legacy `[x]`/`KEY:` string parser |
| [`backend.py`](console_window/backend.py:1) | 282 | 128 | 88% | `Surface`/`RenderBackend` protocols, `CursesBackend`, `HeadlessBackend` |
| [`geometry.py`](console_window/geometry.py:1) | 82 | 61 | 100% | Pure abut/indicator/pickable-row math |
| [`opts.py`](console_window/opts.py:1) | 88 | 63 | 100% | `ConsoleWindowOpts` (`__slots__` + kwargs) |
| [`context.py`](console_window/context.py:1) | 47 | 22 | 100% | Per-row `Context` (`genre`/`pickable`/`abut` + open kwargs) |
| [`signals.py`](console_window/signals.py:1) | 144 | 63 | 87% | SIGINT policy: captured host handler, per-window setup/teardown, reset |
| [`keys.py`](console_window/keys.py:1) | 18 | 3 | 100% | `NAVIGATION_KEYS` |
| [`__init__.py`](console_window/__init__.py:1) | 33 | 12 | 100% | Re-exports + `__all__` |

**Frame cycle.** `main_loop` → `screen.draw_screen()` (`clear()` + `add_header*`/`add_body` into the two pads) → `win.render()` → `fix_positions()` (clamp/scroll/pick, returns `indent`) → gutter/separator/indicator → `pnoutrefresh` both pads → `doupdate()` → `win.prompt()` (key read + built-in navigation) → `handle_key()` → `stack.perform_actions(spin)` (convention dispatch of `<attr>_ACTION`) → `clear()`.

**Two data models, one window.** Layout/scroll/pick live in `SimpleNamespace`s (`self.head`, `self.body`) with parallel lists (`texts`, `text_attrs` run-length encoded, `contexts`, `row_cnt`); `Row Context` carries per-row semantics. `Screen` subclasses add routing and `*_ACTION` dispatch. `OptionSpinner` is the key/option registry, optionally scope-aware per screen with automatic scope subtraction ([`spinner.py:134`](console_window/spinner.py:134)).

**The seam covers the drawing, input and colour paths.** `RenderBackend` abstracts `start`/`newpad`/`doupdate`/`curs_set`/`update_lines_cols`/`is_term_resized`/`has_colors`/`start_color`/`use_default_colors`/`init_pair`/`color_pair`/`stop`, and the dialogs, flash, resize checks and colour init all go through it.

**Two window models over that seam.** `ConsoleWindow(singleton=True)` (the default) restores the historical process-wide screen: every instance shares one screen/backend, `static_scr`/`static_win` are populated, and `ConsoleWindow.stop_curses()` tears the process screen down. `singleton=False` keeps the per-instance model: each window owns its screen and teardown, and `stop_all()` is the multi-window hook. The first construction latches the mode process-wide; mixing values asserts.

**Current shape.** Docstrings are reserved for public entry points whose call shape needs spelling out, while module- and algorithm-level explanation lives in comments; `_selftest.py` is folded into `SampleApp.py`; the pad-overflow contract is counted, warned about once per fill episode, and enforced in this project's suite; and the package version is single-sourced through `dynamic = ["version"]`.

## 3. Findings

### 3.1 🟡 Unreachable public surface

No consumer outside the test suite for:

| Symbol | Where | Note |
| --- | --- | --- |
| `ConsoleWindow.set_pick_range()` | [`window.py:609`](console_window/window.py:609) | The `pick_range` feature's only public entry point; called only by [`tests/test_interactive.py`](tests/test_interactive.py:434) |
| `OptionSpinner.add()` | [`spinner.py:163`](console_window/spinner.py:163) | Retired tombstone that raises `NotImplementedError` pointing at `add_key()`; only [`tests/test_spinner.py`](tests/test_spinner.py:259) calls it, to assert the raise |
| `ConsoleWindow.draw()` | [`window.py:863`](console_window/window.py:863) | Named as a model-writing entry point in [`README.md`](README.md:52), but no library or example code calls it; only tests do ([`tests/test_interactive.py`](tests/test_interactive.py:368), [`tests/test_overflow.py`](tests/test_overflow.py:152), [`tests/test_viewport_pad.py`](tests/test_viewport_pad.py:79), [`tests/test_widechars.py`](tests/test_widechars.py:129)) |

`OptionSpinner.add()` keeps its old signature so pre-2.0 call sites fail at the call rather than at import, and its `NotImplementedError` names the replacement call. It is otherwise inert, so the only thing keeping it alive is its own regression test.

`draw()` is the inverse case: the README presents it as part of the row-model API while every actual caller is a test, so the documentation promises a path the project never demonstrates.

The former fourth row of this table, `SampleApp.do_key()`, has been **removed**: it had no caller at all because `main_loop` dispatches through `handle_key()`, which already forwards spinner keys itself.

**Fix:** delete what no consumer needs, or promote it deliberately: give each survivor an exercising caller (the example or a documented snippet) alongside its test. For `OptionSpinner.add()`, either set a removal release or keep it explicitly documented as deprecated.

### 3.2 ✅ `answer()` residual: documented limitations

[`answer()`](console_window/window.py:1384) has one unambiguous meaning per outcome (`str` = submitted, `None` = user abort, `TerminalTooSmallError` = environment), and its recovery loop is bounded. Two narrow characteristics remain, and both are now stated where a maintainer will meet them rather than fixed:

* **The retry budget is class-wide.** `answer()` spends the shared `render_retry_seconds` budget ([`window.py:1421`](console_window/window.py:1421), declared at [`window.py:160`](console_window/window.py:160)). The budget is read as `ConsoleWindow.render_retry_seconds`, so it applies to `render()` and `answer()` alike and must be tuned on the class; an instance assignment has no effect. This is accepted because the knob already exists, no consumer has asked for a different dialog budget, and a second option would add public surface for a ~2 s recovery policy. The attribute comment in [`window.py`](console_window/window.py:153) spells this out.
* **Recovery discards queued keys.** [`_recover_from_resize()`](console_window/window.py:1750) drains **every** queued key, not only `KEY_RESIZE` ([`window.py:1767`](console_window/window.py:1767)). This is accepted because curses exposes no push-back API: preserving keys would mean replaying raw codes read after a failed redraw, where duplicates and partial escape sequences are indistinguishable from real input. The loss is bounded by `render_retry_seconds` (keys typed after recovery are read normally), and both the method docstring and [`answer()`](console_window/window.py:1384)'s docstring state the loss explicitly.

**Resolution:** documented as accepted limitations; no behaviour change. Revisit only if an app needs an independent dialog budget or faithful key replay, which would justify the extra API and input-buffer plumbing.

### 3.3 ✅ Lint findings now carry rationale

`pylint` is **10.00/10** with `C,R` disabled. Each former warning now either states why it is deliberate or has been removed:

* **protected access** — the registry helpers explain that the module owns `_registry_key` ([`window.py:97`](console_window/window.py:97), [`window.py:105`](console_window/window.py:105)); the `stop_curses` descriptor explains why it reaches the private implementations ([`window.py:147`](console_window/window.py:147), [`window.py:149`](console_window/window.py:149)); `Theme.set()` owns the internal default-colour step ([`theme.py:204`](console_window/theme.py:204)); the sample resets `filter_bar._text` because `IncrementalSearchBar` exposes only a read-only `text` property ([`SampleApp.py:402`](SampleApp.py:402)).
* **unused arguments** — `_paint_alert()`'s dead `row9` parameter was removed (both call sites updated). The headless backend's protocol arguments ([`backend.py:255`](console_window/backend.py:255), [`backend.py:283`](console_window/backend.py:283)) and `DemoScreen.__init__`'s protocol `name` ([`SampleApp.py:244`](SampleApp.py:244)) are kept for signature compatibility and say so inline.
* **not-callable** — [`screens.py:68`](console_window/screens.py:68) carries a `disable-next` noting that pylint cannot see through `getattr` + `callable()`.
* **broad exceptions** — [`SampleApp.py:149`](SampleApp.py:149) explains the sample-data fallback; [`SampleApp.py:518`](SampleApp.py:518) explains the top-level demo guard that leaves the terminal usable.

**Resolution:** resolved; no suppression is unexplained, and `pylint --disable=C,R` is clean.

## 4. Prioritized recommendations

**P1 — surface**

1. Delete or promote the unreachable API and the `draw()` documentation mismatch (§3.1). (`SampleApp.do_key()` has already been deleted.)

**P2 — hygiene**

The §3.2 dialog residuals are closed as documented limitations and the §3.3 lint findings are annotated; reopen either only against a concrete consumer requirement.

## 5. Reproduction

```bash
python3 -m ruff check .
python3 -m pytest -q
python3 -m pytest -q --cov=console_window --cov-fail-under=80   # the CI coverage gate
python3 -m coverage run --source=console_window -m pytest -q && python3 -m coverage report -m
python3 -m pylint console_window SampleApp.py runner --disable=C,R
python3 -m mypy
python3 -m ruff check --select C901 console_window SampleApp.py   # uses the ratchet in pyproject.toml
python3 -W error::UserWarning -c "import SampleApp"   # exit path for the pad-overflow policy
```
