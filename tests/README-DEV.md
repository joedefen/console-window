# console-window: working on the source tree

This is the developer companion to [`README.md`](../README.md), which documents
the library for its users. Here we document the things a maintainer needs and a
user does not: running the **lettered demos** from the working tree, the
**test gate**, and the **release gate** (`./bless`).

This file lives in `tests/`, so its links point one directory up. The commands
assume the repository root, which is where the gate has to be run.

## Running the demos from the working tree

The demos run directly against your working tree — no install or build step
required:

    ./runner                     # the lettered menu from demos/demos.ini
    ./demos/run-demo a-basic     # one demo, by short name

A, B and C are complete single-file programs; D–Q are short deltas on
`demos/demo_kit.py`. The demos are interactive and need a real terminal (any
POSIX box). They are repo-level scripts, **not** part of the installed package:
after `pip install console-window` you write your own `main()` — copy C, the
boilerplate (stack + spinner + help).

Every demo takes the same display switches:

    ./demos/run-demo a-basic --ascii
    ./demos/run-demo j-themes --theme nord
    NO_COLOR=1 ./demos/run-demo j-themes   # same as --theme mono

`mono` is a real theme, not a separate color flag. It uses the terminal's own
foreground and background plus a bold/reverse attribute hierarchy, so it follows
a light or dark terminal automatically. `NO_COLOR` selects it for a run when no
explicit `--theme` is given.

### The demo curriculum

The canonical examples are the demos in [`../demos/`](../demos). They form a
curriculum, not one app with every feature:

* **A — [`a-basic`](../demos/demo-a-basic.py)** is the degenerate showcase: one
  `Screen`, one table, and the four-call loop, with no stack, spinner or help.
  Navigation scrolls the body; live data changes one row each pass.
* **B — [`b-stack`](../demos/demo-b-stack.py)** is the second degenerate step: two
  pages on a `ScreenStack`, still with no spinner and no help. Each screen keeps
  its own content and scroll position.
* **C — [`c-options`](../demos/demo-c-options.py)** is the **boilerplate**: a
  `ScreenStack`, an `OptionSpinner` and a `BasicHelpScreen`, plus the smallest
  set of options that still shows every genre. Copy this file to start an app.

D through P each add one focused lesson on top of that shape, and they all keep
it -- every one has a help page, and its keys are spinner registrations, so the
help page lists them (a test enforces both): picking, search, in-place prompts,
dialogs, messages, headers, themes, glyphs, read-only text, navigation
ownership, suspend/resume, large bodies, and width/debug aids. Each demo's
`Owns:` docstring line records the learning objectives it demonstrates, and a
library feature change names its demo in the changelog.

## Layout and single sources of truth

| Path | Owns |
| --- | --- |
| [`console_window/__init__.py`](../console_window/__init__.py) | `__version__`, and the public re-exports. The build backend reads the version line, and `bless` reads it without importing the package. |
| [`pyproject.toml`](../pyproject.toml) | Name, description, `requires-python`, runtime dependencies, classifiers, the `test`/`dev` extras, the `[tool.bless]` branch model, and the pytest, coverage and ruff configuration. |
| [`bless`](../bless) | The release gate, emitted verbatim from [`../../blessd/bless`](../../blessd/bless) by that repo's `build.py`. It holds no copy of this project's identity, and it is never edited here. |
| [`blessd/docs/release-strategy.md`](../../blessd/docs/release-strategy.md) | The release strategy every project shares: the branch model, the stages, the rehearsal, the credentials. This file documents only what is particular to `console-window`. |
| [`tests/inspect_dist.py`](inspect_dist.py) | The distribution inspector. `bless` refuses to upload a wheel and sdist it has not inspected with this file. |
| [`runner`](../runner), [`demos/`](../demos) | The non-invasive way to run the demo family from the working tree (`./runner`, or `.venv/bin/python ./runner`): it shows the lettered menu from `demos/demos.ini`, and `./demos/run-demo a-basic` runs one demo against the tree. Neither is part of the installed package. |
| [`.gitignore`](../.gitignore) | Keeps gate artifacts (`build/`, `dist/`, `.coverage*`, caches, `*.whl`, `*.tar.gz`) out of `git status`, because the gate refuses a dirty tree. |

The version lives in exactly one place. `pyproject.toml` declares
`dynamic = ["version"]`, so flit reads `console_window/__init__.py`; an
`X.Y.Z.99.N` rehearsal rewrites that line only inside a throwaway copy.

Almost nothing needs a `[tool.bless]` table: `NAME = console-window`,
`MODULE = console_window` and the inspector are all derived from what is already
there. The one setting written out is `branches`, which names the branches
`publish` releases from -- see [the branch model](#the-branch-model-is-a-setting-not-a-convention)
below. There is no `[project.scripts]` entry: this is a library, so the smoke
stage imports the installed package and prints `__version__` instead of running
a console script.

## The environment and the test gate

`bt penv` rebuilds `.venv` around this tree. It installs the project
**editably** (`-e '.[dev]'`, or `-e .` when a project has no `dev` extra)
together with the release toolchain, so pytest, `./bless` and a debugger all
run under one interpreter and breakpoints land in `console_window/` rather
than in a copied install:

    bt penv

The equivalent by hand:

    python3 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev]'

Select `<project>/.venv/bin/python` as the VS Code interpreter. `bless` runs
every stage with `sys.executable`, so the gate has to be started with that
same interpreter -- the one holding ruff, pytest-cov, build, `twine>=7` and
`packaging>=26`:

    .venv/bin/python ./bless

This project declares no `[project.scripts]`, so `bt status` reports
`Entry point: none`: there is no `~/.local/bin/<app>` link for `bt edit` to
manage. Releases are still rehearsed and published through `./bless`; when a
released artifact is installed with `bt test`/`bt prod`, pipx keeps it in its
own per-app venv and `bt status` reports that record.

Then the commands `bless` runs, in the same order, on the same interpreter:

    python -m ruff check .
    python -m compileall -q console_window tests
    python -m pytest -q --cov=console_window --cov-report=term-missing

### Leaving the old `--user` model

The previous `bt` installed the package into the system Python's user site
(`pip install --user`), so `.venv` held only the tools. `bt status` reports any
such leftover as `Legacy --user install`; a one-time `bt clean` removes it, and
no current subcommand uses `pip install --user`. With that gone, `.venv` is
the only editable copy and a debugger started under it steps through the tree.

The coverage floor (90%) is enforced through `[tool.coverage.report]
fail_under`. It was set just below the measured 90.69% when the release gate
was adopted; raise it when the number rises, never lower it.

`demos/` is outside the measurement (`[tool.coverage.run] omit`) and outside the
suite's behaviour assertions.  `tests/test_demo_syntax.py` only compiles and
imports each demo script against the public API, so a demo can be reworked
without touching the project.

The ruff selection is committed rather than inherited, so that no user or global
configuration can change what the gate enforces. `requires-python` still allows
3.10, which is why the `test` and `dev` extras carry `tomli` for the interpreter
that has no `tomllib`.

## The release gate: `./bless`

`./bless` takes no arguments and has no flag that skips a stage. It always runs
everything, then prints what it has in hand and asks one question:

    ====> Enter test or publish or quit:

Only `test` and `publish` are accepted, spelled in full; anything else is asked
again. Enter, `quit` or Ctrl-C stops with nothing tagged, uploaded or pushed.

**Stages, in order**

1. **preflight** -- clean tree, the `vX.Y.Z` tag absent, `twine>=7` and
   `packaging>=26` present.
2. **index check** -- refuses if `__version__` is already on PyPI, printing
   every published version, before anything is built or uploaded.
3. **gates** -- the three commands above.
4. **build** -- into `build/bless-<version>/`, wiped first, so no older
   artifact can be sent by mistake.
5. **inspect** -- `tests/inspect_dist.py` against the wheel and the sdist.
6. **check** -- `twine check --strict` on both files.
7. **smoke** -- installs the built wheel into a throwaway venv, imports
   `console_window` and prints `__version__`, which must match the release.
8. **branch plan** -- refuses a detached HEAD, a branch that is not one of the
   release branches, a release branch missing locally or on origin, two
   branches that have diverged, or a push that would not fast-forward.

**`test`** is the rehearsal and never spends the working version. It copies the
tree to `build/bless-test-<version>/src`, rewrites `__version__` to
`X.Y.Z.99.N` (99 keeps it clear of real releases; `N` is one past the highest
suffix TestPyPI already holds for that base), builds, inspects and smoke-tests
the copy, and uploads only to `test.pypi.org`. No tag, no branch, no push. It
prints the install line, which needs `python -m pip cache purge` first and
`--extra-index-url https://pypi.org/simple/`, because TestPyPI carries no
dependencies.

**`publish`** fast-forwards the release branches to one commit, tags `vX.Y.Z`,
uploads the two inspected files to PyPI, verifies the index, and pushes those
branches and the tag.

**Credentials** are resolved per index -- `TWINE_PASSWORD` for PyPI,
`TWINE_TESTPYPI_PASSWORD` for TestPyPI, each overruling the `~/.pypirc` section
whose `repository` matches that index's upload URL -- so a PyPI token is never
spent on a rehearsal. A missing credential is a refusal before `twine` starts.

**Verification** reads the index back after an upload. The read is cache-busted
and patient (up to a quarter of an hour), because both indexes list new releases
through a CDN that lags; a release that is not listed yet is reported as lag
with the project page to check, never as a failed upload, since an accepted
upload cannot be withdrawn.

There is no CI publish job, on purpose: the upload is irreversible and is run by
the owner from the development tree, so the safety lives in one inspectable
command. CI stays a gate.

## The branch model is a setting, not a convention

`bless` publishes only from a branch it was told about, and pushes every branch
it was told about. Which ones those are is `[tool.bless] branches` in
[`pyproject.toml`](../pyproject.toml), and there are two shapes:

* `branches = ["main"]` -- one release branch. Nothing is aligned, and `publish`
  pushes `main` and the tag. This is what this project uses, so a small change
  can be published straight from the trunk.
* `branches = ["main", "dev"]` -- the default when the setting is absent. While
  you are on `main`, `dev` does not have to exist yet: the trunk alone satisfies
  the model, so `publish` releases from `main` and pushes only what exists. Once
  `dev` has been created it also has to exist as `origin/dev`, and whichever of
  the two lags is fast-forwarded onto the other before the tag, so a release
  always leaves them at one commit.

Either way the gate refuses a branch it was not told about, a branch it has to
push that is missing on origin, two branches that have diverged, and a push that
would not fast-forward. What a single branch cannot do is notice that a
development branch was left behind: merging `dev` into `main` stays your job,
and the pair exists to make it the gate's job instead.

Switching to the pair is one line in `pyproject.toml` plus the branch itself:

    git branch dev
    git push -u origin dev

## What the inspector asserts

[`tests/inspect_dist.py`](inspect_dist.py) is the one implementation, used by
`bless` and, once CI is wired up, by CI; expectations are read from
`pyproject.toml` and the package, never from the artifact under test.

* **wheel** -- `Name`, `Version`, `Summary` and `Requires-Python` match
  `pyproject.toml`; the *runtime* `Requires-Dist` names match (the `test` and
  `dev` extras are filtered out by their `extra ==` markers); every
  `console_window/*.py` is present; a `LICENSE` is carried; no `tests/`, no
  `.venv`, no `__pycache__`, no `.pyc`. If the metadata ever moves to a PEP 639
  `license` expression, `License-Expression` is asserted too, and every declared
  `license-files` entry must be listed.
* **sdist** -- carries `pyproject.toml`, `README.md`, `LICENSE` and every
  `console_window/*.py`; the `__version__` inside the sdist equals the artifact
  version; no venv or bytecode. The sdist is deliberately lean: flit's default
  payload is enough and `tests/` need not ride along.

Run it by hand on any built pair:

    python tests/inspect_dist.py dist/console_window-2.1.3-py3-none-any.whl \
                                dist/console_window-2.1.3.tar.gz

## Releasing, in three steps

1. Bump `__version__` in [`console_window/__init__.py`](../console_window/__init__.py)
   and add the notes to [`tests/CHANGELOG.md`](CHANGELOG.md), then commit.
2. Run `./bless`. The gate runs in full.
3. Answer `test` to rehearse on TestPyPI, then run `./bless` again and answer
   `publish` -- or go straight to `publish`.

`[tool.bless] branches` names what `publish` pushes. The trunk in that list must
exist and track origin; a development branch joins the release once it exists,
and from then on it has to exist on origin too. `publish` leaves every branch it
pushes at the tagged commit: one branch with `["main"]`, the pair with
`["main", "dev"]`. Everything else about the release is one of the stages above,
and the shared half lives in
[`blessd/docs/release-strategy.md`](../../blessd/docs/release-strategy.md).

## Future features and considerations

Deferred or out-of-repo work, recorded here so no separate plan document is
needed:

* **Modal layers and help.** `IncrementalSearchBar` consumes printable keys
  inside `handle_key()` and outranks the spinner while it is active. It is a
  layer, not a screen, so it has no `effective_scope`, and the help screen is
  unreachable underneath it. Two options were identified: list the bar's keys in
  a separate "while typing" block on the help page, or have the bar take its
  keys from the current screen's spinner set so the two cannot diverge.
* **External app ports to the 3.0 `Screen` shape.** `nanny` and `psistat` live
  outside this repository. Their required changes are the same: drop the
  `_draw_separator_and_indicator` monkey-patch (`head_line=False` now has no
  side effects), replace `draw(y, x, ...)` with composed `add_body()` segments
  (column padding via `textwidth`), replace `_set_body_context()` with
  `add_body(..., context=ctx)`, drop the `body.drawn[row] = []` resets, and
  start each pass with `screen.clear()`.
* **Status with no separator row.** With `head_line=False` there is no separator
  row, so `status()` stores the message and warns once per episode instead of
  painting it. Drawing it on the last header row remains a possible later
  addition if an application asks for it.
* **Dropping the scroll indicator while keeping the rule.** `head_line=True`
  paints the separator row and the scroll indicator together, so an application
  that keeps the rule cannot turn the indicator off. Nothing needs that today; a
  `scroll_indicator` option would be the way to add it.
* **Two-cell emoji marks: deliberate limits.** The approved `mark()` family is
  width-safe but stops short of: colour/presentation control (a mark renders in
  whatever colour the terminal chooses; `--theme mono` and attributes are the
  answer), ZWJ sequences and flag pairs (variable width, no safe fallback), and
  per-terminal emoji probing (not observable, so the font check and `--ascii`
  are the whole story). Content is never rewritten: `transliterate()` touches
  only registered code points, and the marks family does not change that. The
  two-cell table needs one colour emoji font from mid-2019 or later, and no
  single font covers both the one-cell catalog and the marks, which is why the
  fallback is one switch.

## Notes on this adoption

* This section is one run of
  [`../../blessd/docs/adopting.md`](../../blessd/docs/adopting.md), which is the
  procedure written for whoever converts the next project. If the two ever
  disagree, that document is the procedure and this is the record of one run.
* [`bless`](../bless) is emitted, byte for byte, from
  [`../../blessd/bless`](../../blessd/bless) -- SHA-256
  `3ef60e9e806ca58a3d900dd6622bb8be0052210da1ef26f9918bf0a1deb1e3b2` when this
  was written. It is not edited here: a change is made in `blessd` and re-emitted
  with `python3 ../../blessd/build.py --into .`, which replaces the file and
  prints the new hash. `python3 ../../blessd/build.py --sha` prints the hash the
  tree should be carrying, and `cmp ../../blessd/bless bless` is silent when it
  is.
* That build also gives the gate a read-only query mode,
  `./bless --branch-plan`, which prints this tree's branch plan as JSON without
  running a single gate. `bt` asks with it, and keeps its own copy of the policy
  for projects whose `bless` is older than the flag, so the branch note `bt`
  prints and the plan `publish` obeys are the same answer from the same code.
* `console-window` needed four things to satisfy the gate: an inspector, the
  `test` and `dev` extras (pytest-cov, ruff, build, `twine>=7`,
  `packaging>=26`, and `tomli` on 3.10), a coverage floor (90, from the measured
  90.69%), and a branch model -- here `branches = ["main"]`. The version was
  already in one place (`dynamic = ["version"]` reading
  `console_window/__init__.py`). No console script was added: this is a library,
  and the smoke stage's fallback imports the package and prints `__version__`.
* The environment was migrated to the per-project model in the postscript of
  [`../../blessd/docs/adopting.md`](../../blessd/docs/adopting.md): `bt penv`
  now installs the editable package and its `dev` extra into `.venv` (it no
  longer removes the package), so the interpreter VS Code selects is the one
  that debugs the tree. Because no `[project.scripts]` is declared, `bt status`
  reports `Entry point: none` and no `~/.local/bin` link is created; the legacy
  `pip install --user` copy was removed with `bt clean`, and `runner` remains the
  non-invasive way to run the sample app without touching `~/.local/bin`.
* The ruff rule set predates the gate and is unchanged; the whole tree was
  already clean under it. [`tests/test_bless.py`](test_bless.py) pins the
  identity this tree derives and the inspector it uploads behind; what the gate
  itself does -- branch plan, refusals, prompt, index check, emitter -- is
  tested once, in [`../../blessd/tests/test_bless.py`](../../blessd/tests/test_bless.py).
* CI is not wired up yet. When it is, it must run the same three gate commands
  and the same inspector, never an equivalent.
