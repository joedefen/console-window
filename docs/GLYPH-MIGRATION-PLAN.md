# Plan: move crippled-terminal handling into `console-window`

Status: **implemented in 2.1.3** (phases 0-3).  Phase 4 (the grub-wiz
migration) is still open; see §5.

Goal: an application that upgrades `console-window` gets glyph degradation
**for free** (no code change), and an application that wants control needs at
most a one-line option and a two-line `argparse` call.

---

## 1. What we built in grub-wiz, and what is generic

| Piece | Where it lives now | Generic? |
| --- | --- | --- |
| Glyph table (`name -> (unicode, ascii)`) | [`grub_wiz/Glyphs.py`](../../grub-wiz/grub_wiz/Glyphs.py:38) | yes, the *mechanism*; the *names* are app vocabulary |
| ASCII switch (process state) | [`set_ascii()`](../../grub-wiz/grub_wiz/Glyphs.py:70) | yes |
| Detectability rules (encoding, `TERM=dumb`, `TERM=linux`) | [`terminal_report()`](../../grub-wiz/grub_wiz/Glyphs.py:176) | yes, entirely terminal-generic |
| Font-check line + wording | [`terminal_report()`](../../grub-wiz/grub_wiz/Glyphs.py:216) | yes |
| Startup policy (print notes, set mode) | [`apply_glyph_policy()`](../../grub-wiz/grub_wiz/main.py:2942) | yes |
| `--ascii`, `--theme` argparse options | [`main.py`](../../grub-wiz/grub_wiz/main.py:2980) | yes, boilerplate |
| Help-screen notes | [`extra_help_paragraphs()`](../../grub-wiz/grub_wiz/main.py:1410) | the *shape* is generic; the wording is app copy |
| Theme picker screen | [`ThemeScreen`](../../grub-wiz/grub_wiz/main.py:1392) | should be pure factory output |
| Theme persistence | [`UiPrefs`](../../grub-wiz/grub_wiz/UiPrefs.py:29) | the *store protocol* is generic; the file/location is app-owned |
| App decoration call sites (`✘`, `🟌`, `●`, …) | ~15 sites in `main.py` | app-specific, must stay app-side |

The only genuinely app-specific parts are the glyph *names* and the theme
config-file location. Everything else is terminal plumbing that every curses app
has to reinvent.

---

## 2. Target API (additive, `console-window` 2.1.3)

### 2.1 New module `console_window/glyphs.py`

Move grub-wiz's module almost verbatim, minus the app names, plus the two things
it does not have today:

```python
# console_window/glyphs.py
@dataclass(frozen=True)
class Glyph:
    unicode: str
    ascii: str

#: Glyphs the library itself draws.  An app that changes nothing gets these
#: downgraded automatically.
BUILTIN_GLYPHS: dict[str, Glyph] = {
    'cursor':       Glyph('│', '|'),      # widgets.py:282, 418
    'cursor_block': Glyph('█', '#'),      # widgets.py:546, 559
    'choice':       Glyph('⮞', '->'),     # widgets.py:444 (resolved choice)
    'scroll_prev':  Glyph('◀', '<'),      # window.py:2161 (dialog scroll)
    'scroll_next':  Glyph('▶', '>'),      # window.py:2165
    'alert_up':     Glyph('▲', '^'),      # window.py:2585
    'alert_down':   Glyph('▼', 'v'),      # window.py:2586
    'nav_prev':     Glyph('←', '<-'),     # window.py:53 (help labels)
    'nav_next':     Glyph('→', '->'),     # window.py:54
    'bullet':       Glyph('·', '.'),      # spinner.py:302
    'swatch':       Glyph('█', '#'),      # theme.py:459 (repeated by caller)
}

class Glyphs:
    @classmethod
    def register(cls, name, unicode_text, ascii_text, *, probe=False): ...
    @classmethod
    def register_many(cls, mapping, *, probe=()): ...
    @classmethod
    def get(cls, name) -> str: ...            # active set
    @classmethod
    def unicode_of(cls, name) -> str: ...     # always the Unicode form
    @classmethod
    def is_ascii(cls) -> bool: ...
    @classmethod
    def set_ascii(cls, enabled: bool) -> None: ...
    @classmethod
    def reset(cls) -> None: ...               # tests: drop app registrations
    @classmethod
    def probe_text(cls) -> str: ...
    @classmethod
    def transliterate(cls, text: str) -> str: ...
    @classmethod
    def terminal_report(cls, environ=None, stream=None) -> TerminalReport: ...
    @classmethod
    def apply_policy(cls, force_ascii: bool = False) -> TerminalReport: ...
```

`register()` automatically feeds `transliterate()`: the ASCII form of every
registered glyph becomes the fallback for its Unicode code point(s). One table,
two consumers.

### 2.2 Transliteration — the "do nothing" story

`Glyphs.transliterate(text)` replaces registered Unicode glyphs with their ASCII
forms and **leaves every other non-ASCII code point alone**:

```python
def transliterate(text: str) -> str:
    if text.isascii() or not _ascii_mode:
        return text                      # fast path, same idiom as textwidth
    return _TABLE.sub(lambda m: _MAP[m.group(0)], text)
```

where `_TABLE` is an alternation of the registered Unicode forms sorted
longest-first (so `⚠️` = U+26A0 U+FE0F wins over a bare `⚠`), and `_MAP`
includes a VS16-stripped spelling for every entry.

This is what makes an untouched app *mostly* correct: an app that writes `⚠️` or
`✔` in its own strings gets `(!)` / `✔`'s fallback without registering anything,
because the library already knows those code points. An app that wants a
different fallback (`stop -> STOP` instead of `!`) registers its own entry and
wins.

**Why it is safe.** It only rewrites codepoints that are registered as
*decoration*. A pager showing `GRUB_CMDLINE_LINUX="Grüße"` is untouched, because
`ü` is not in the table. To keep developers honest, an opt-in audit mode
(`CONSOLE_WINDOW_GLYPH_AUDIT=1`) logs once per unseen decorative codepoint and
prints the exact `register()` call to add.

### 2.3 Where transliteration hooks in

One choke point per draw path, always **before** width math:

| Seam | File | Why |
| --- | --- | --- |
| `_add()` top | [`window.py:1110`](../../console-window/console_window/window.py:1110) | both `add_header()` and `add_body()` funnel here; `textwidth.truncate()` runs at 1134/1144 **after** substitution, so widths and the run-length `text_attrs` stay correct |
| `draw()` | [`window.py:1388`](../../console-window/console_window/window.py:1388) | direct writes that bypass `_add` |
| `status()` | [`window.py:2317`](../../console-window/console_window/window.py:2317) | separator-row text |
| `_paint_alert()` / `alert()` | [`window.py:2585`](../../console-window/console_window/window.py:2585) | `addch` arrows |
| widget defaults | [`widgets.py:282`](../../console-window/console_window/widgets.py:282), [418](../../console-window/console_window/widgets.py:418), [546](../../console-window/console_window/widgets.py:546), [559](../../console-window/console_window/widgets.py:559) | change `cursor_char: str = '│'` to `cursor_char: str \| None = None` and resolve through `Glyphs.get('cursor')` |

Width accounting needs no change in `textwidth.py`: ASCII is one cell per code
point by definition.

### 2.4 Box drawing: registry glyphs, not `ACS_*`

The plan proposed switching the `flash()` frame (`┌ ─ ┐ │ └ ┘`,
`window.py:2392-2398`) to `curses.ACS_*`, which is alt-charset graphics and
works where UTF-8 does not.  Implementation chose registered glyphs instead:

* `box_tl`, `box_h`, `box_tr`, `box_v`, `box_bl`, `box_br` are built-ins with
  `+`, `-`, `+`, `|`, `+`, `+` as fallbacks, and `flash()` builds its frame from
  them.  A `TERM=dumb` terminal gets a readable `+---+` box, which is what the
  ACS version was for.
* It keeps one mechanism instead of two, keeps the ASCII-mode invariant
  ("every painted cell is ASCII") true for dialogs, and needs no ACS→character
  table in `HeadlessBackend`.  `curses.textpad.rectangle()` — already used by
  `_draw_alert_frame()` — still draws with ACS; both paths are safe.

`theme.py`'s `'████████'` swatch became `Glyphs.get('swatch') * 8`, as planned.

### 2.5 Options and window surface

```python
ConsoleWindowOpts(
    ascii=None,        # None = auto-detect, True = force ASCII, False = force Unicode
    glyphs=None,       # {'name': (unicode, ascii)} or {'name': Glyph(...)}
    glyphs_probe=(),   # names to show in the font check, in order
)
```

Added to `opts.py` `__slots__` (the strict unknown-kwarg check means the addition
is backwards compatible for callers, and is a deliberate, tested surface).

`ConsoleWindow` gains read-only `ascii_mode` and `glyph(name)`.

**Scope decision: the glyph mode is process-wide, not per-window.** There is one
terminal, so a per-window flag would be a lie; this mirrors the existing
`Theme._current` precedent ("applying a theme is terminal-global, but a window
records which one it is on"). `opts.ascii` *seeds* the process mode when it is
not `None`, which is exactly how `opts.theme` seeds a window today.

### 2.6 CLI boilerplate `console_window/cli.py`

```python
def add_display_arguments(parser, *, theme_store=None, prog=None):
    """Add --ascii, --theme (and --no-color later if wanted)."""

def apply_display_arguments(args, *, printer=print, prog=''):
    """Set the glyph mode, print the report notes, seed the theme.

    Returns the TerminalReport so a caller can react to ascii_required.
    """
```

That collapses grub-wiz's `--ascii` option, `--theme` option, `apply_glyph_policy()`
and the `Theme.initial(...)` call into two lines in `main()`.

Env override for apps without argparse (and for `sudo` re-exec wrappers):
`CONSOLE_WINDOW_GLYPHS=auto|ascii|unicode`.

Precedence, highest first:

1. `ConsoleWindowOpts(ascii=True/False)` / `--ascii`
2. `CONSOLE_WINDOW_GLYPHS`
3. auto-detect: `ascii_required` when the stream encoding is not UTF-8 or
   `TERM=dumb`; advisory notes for `TERM=linux`/`cons25`
4. Unicode

### 2.7 Theme: factory does the wiring, not the app

```python
Theme.create_picker_screen(
    base_class,
    cycle_key=None,   # None -> discover from the spinner's spin_theme binding, else 't'
    store=None,       # ThemeStore: load() -> str | None, save(name) -> None
    note=None,        # dim line under the swatches ("remembered for next start")
)
```

* `draw_screen()` stops hard-coding `Press [t] to cycle themes` — it uses
  `cycle_key`, discovered from the spinner when the app bound `spin_theme`
  (the current text is simply wrong for SampleApp, which binds `t` to the
  `theme` value and `t` to the action on another screen only).
* `spin_theme_ACTION()` calls `store.save(name)` inside `try/except OSError`, so
  persistence failures never break the cycle.
* New `Theme.initial(cli_theme, store)` = `resolve(cli_theme or store.load() if store else None)`,
  which is grub-wiz's `_initial_theme()` ([`main.py:1668`](../../grub-wiz/grub_wiz/main.py:1668)).

`ThemeStore` is a `typing.Protocol` in `theme.py`. The library never opens a
file: `grub-wiz`'s `UiPrefs` (already atomic, owner-fixing, warning-ridden)
becomes the adapter and keeps owning the path.

### 2.8 Help surface

Two small additions so no app has to re-word the disclaimer:

```python
# screens.py
class Screen:
    def extra_help_paragraphs(self) -> Iterable[str]:
        return ()

class BasicHelpScreen(Screen):
    def draw_screen(self):
        ...  # existing nav + body help
        for para in (*self.extra_help_paragraphs(), *self.window_help_notes()):
            for line in textwrap.wrap(para, width=max(win.cols - 8, 20)):
                win.add_body(line, attr=curses.A_DIM)
```

```python
# console_window/help.py
def theme_paragraph(open_key='T', cycle_key='t', remembered=True) -> str
def glyph_paragraph(window=None) -> str    # "draws … if any is a box, use --ascii"
```

`glyph_paragraph()` reads the probe text from the registry, and in ASCII mode
returns the "ASCII symbols are in use; restart without `--ascii` to try" variant
— the exact two branches grub-wiz hand-writes at
[`main.py:1424-1433`](../../grub-wiz/grub_wiz/main.py:1424).

`BasicHelpScreen` adds these by default only when the window has a theme store or
explicitly opted in, so existing apps' help output is unchanged.

---

## 3. Exact edit list in `console-window`

| File | Change |
| --- | --- |
| `console_window/glyphs.py` | **new** — table, registry, transliteration, `TerminalReport`, `terminal_report()`, `apply_policy()` |
| `console_window/cli.py` | **new** — `add_display_arguments()`, `apply_display_arguments()` |
| `console_window/help.py` | **new** — paragraph builders |
| `console_window/opts.py` | three new slots + validation (`ascii` must be `None`/bool, `glyphs` mapping shape) |
| `console_window/window.py` | transliterate at `_add`/`draw`/`status`; `glyph()`/`ascii_mode`; ACS frames; `nav_prev`/`nav_next` labels |
| `console_window/widgets.py` | `cursor_char=None` sentinels, `choice` glyph |
| `console_window/spinner.py` | `dot` glyph; `show_help_glyph_note(win)` |
| `console_window/theme.py` | `ThemeStore`, `Theme.initial()`, factory `cycle_key`/`store`/`note`, swatch glyph |
| `console_window/screens.py` | `Screen.extra_help_paragraphs()`, help composition |
| `console_window/backend.py` | ACS→char table for `HeadlessBackend` |
| `console_window/__init__.py` | export `Glyphs`, `Glyph`, `ThemeStore` |
| `SampleApp.py` | register one custom glyph, pass `store=` to the picker, show `--ascii` |
| `README.md`, `tests/CHANGELOG.md` | new "Glyphs and terminals that cannot draw them" section |

---

## 4. Test plan (library side)

1. `tests/test_glyphs.py` — registration, `get()`/`unicode_of()`, key errors,
   `reset()`, probe text always Unicode, ASCII forms are pure ASCII.
2. `tests/test_glyph_transliteration.py` — longest-match clusters, VS16 pairs
   (`⚠️`), bare base (`⚠`), unknown non-ASCII untouched (a `Grüße` row stays
   byte-identical), fast path returns the same object for ASCII input.
3. `tests/test_glyph_policy.py` — encoding/`TERM` matrix, precedence
   opts > env > auto, note wording, `apply_policy` return value.
4. `tests/test_glyph_rendering.py` — headless render of prompt, confirmation,
   alert frame, status line and picker swatches in both modes; **invariant
   assertion**: in ASCII mode every painted cell `.isascii()` (catches any future
   literal that forgets the registry).
5. `tests/test_cli_display_args.py` — argparse integration, `choices`, invalid
   theme, printed notes.
6. `tests/test_theme_picker.py` additions — `cycle_key` discovery, `store.save()`
   called on cycle, `OSError` tolerated, `note=` drawn.
7. Width regression: a row containing emoji (2 cells) renders one cell narrower
   in ASCII mode and still fills the pad exactly.

---

## 5. grub-wiz migration once the library ships

Ordered, each step independently shippable:

1. Bump the `console-window` pin to `>=2.2`.
2. [`grub_wiz/Glyphs.py`](../../grub-wiz/grub_wiz/Glyphs.py) shrinks to a
   registration shim: `Glyphs.register_many({...the same 12 names...}, probe=(...))`,
   and the module-level `nav()/warn()/...` accessors become thin aliases so the
   ~15 call sites in `main.py` do not change at all in this step.
3. Delete `apply_glyph_policy()` ([`main.py:2942`](../../grub-wiz/grub_wiz/main.py:2942));
   replace `--ascii`/`--theme` with `cli.add_display_arguments(parser)` +
   `cli.apply_display_arguments(opts)`.
4. Replace `_initial_theme()` ([`main.py:1668`](../../grub-wiz/grub_wiz/main.py:1668))
   and `remember_theme()` ([`main.py:1678`](../../grub-wiz/grub_wiz/main.py:1678)) with
   `Theme.initial(opts.theme, self.prefs)` and a `ThemeStore` adapter on `UiPrefs`
   (`load()` → `get('theme')`, `save(name)` → `set('theme', name)`).
5. Delete `ThemeScreen` ([`main.py:1392`](../../grub-wiz/grub_wiz/main.py:1392)) and
   use `Theme.create_picker_screen(GrubWizScreen, store=prefs, note='The choice is remembered for the next start.')`.
6. `HelpScreen.extra_help_paragraphs()` returns
   `[help.theme_paragraph('T', 't'), help.glyph_paragraph()]`; delete the bespoke
   wording and `draw_notes()` (the base class wraps and dims).
7. Tests: move `tests/test_glyphs.py` coverage upstream; keep in grub-wiz a single
   smoke test that renders every screen in ASCII mode and asserts no non-ASCII
   row.
8. README: replace the "COLOR THEMES AND SYMBOLS" how-to with a pointer to the
   `console-window` section plus the two flags grub-wiz still owns.

Net effect in grub-wiz: `Glyphs.py` goes from ~245 lines to ~20,
`UiPrefs` stays, `main.py` loses ~75 lines, and the `ThemeScreen` subclass
disappears.

---

## 6. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Transliteration mangles *content* (a pager showing UTF-8 text) | Only registered codepoints are rewritten; audit mode reports unseen decoration; documented as "register what you decorate with" |
| Substitution changing widths breaks alignment | Substitution happens before `textwidth.truncate()` / `string_width()` in `_add()` and friends; emoji 2→1 cell is covered by a width test |
| `TERM=dumb` apps suddenly change appearance | That is the point, but it is a behaviour change: call it out under "Changed" in the CHANGELOG and keep `CONSOLE_WINDOW_GLYPHS=unicode` as the escape hatch |
| `ACS_*` unavailable on a custom backend | Keep the current literal frame as the fallback branch when the backend has no ACS table |
| Process-global mode leaking across pytest cases | `Glyphs.reset()` in the suite's autouse fixture (same pattern as grub-wiz's `isolated_user_config_dir`) |
| Apps that never call `apply_policy()` get no font check line | Auto-detection runs at `ConsoleWindow.__init__` regardless; the *printed* check requires an explicit `announce=True` (grub-wiz prints it in its own `main()` before curses) |

---

## 7. Phasing

| Phase | Scope | Size |
| --- | --- | --- |
| 0 | `glyphs.py` + opts + transliteration seams + tests 1-3, 4 | ~600 lines lib, ~400 lines tests |
| 1 | `cli.py`, `help.py`, theme `store`/`cycle_key`/`note`, picker tests | ~200 lines lib, ~200 tests |
| 2 | ACS frames + `HeadlessBackend` ACS table, swatch/dot/cursor cleanup | ~80 lines |
| 3 | `SampleApp` + README + CHANGELOG (2.1.3) | ~120 lines docs |
| 4 | grub-wiz migration (§5) | deletes ~150 lines there |

Phases 0-3 are additive; nothing in 2.1.3 requires an app change.

---

## 8. Decisions (resolved)

1. **Transliteration is on by default** (best effort).  Registering a glyph
   feeds both `get()` and `transliterate()`; unregistered decoration is left
   alone and reported by the opt-in audit.
2. **The glyph mode is process-wide**, mirroring `Theme._current`.  A window
   seeds it through `opts.ascii` (or auto-detects), and
   `glyphs.ensure_policy()` guarantees detection runs at most once, so a window
   constructed later cannot revert an explicit choice.
3. **`ThemeStore` lives in `theme.py`** as a `typing.Protocol` with
   `load()`/`save()`.  No `prefs.py`: the library never opens a file, and a
   YAML helper would have added a dependency for a two-method interface.
4. **The switches are symmetric**: `--ascii` takes an optional boolean
   (`--ascii`, `--ascii=no`) and `--glyphs {auto,ascii,unicode}` is its
   counterpart; `--glyphs` wins when both are given.  `CONSOLE_WINDOW_GLYPHS`
   remains the no-argparse escape hatch.

One deviation from §2.8 as written: help notes are **opt-in**
(`BasicHelpScreen.show_display_notes = True`) rather than automatic when a store
is configured.  An automatic note changed the output of existing help screens,
which the additive release could not justify; the sample app shows the opt-in.
