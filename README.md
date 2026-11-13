
# console-window 

`console-window` is a **stdlib-only, single-dependency-free curses framework** that is *not* a general widget toolkit. It is best understood as a **keyboard-driven, full-screen "pager + selection engine + screen-stack router"** built on raw curses **pads**. The genuinely novel ideas are:

- a separate **head pad / body pad** split with a static header band;
- a **scroll position** and an independent **pick (cursor) position** that stay synchronized;
- a **`Context` metadata object per line** with an `abut` concept (keep N lines around the picked row visible — perfect for expandable/transient detail rows);
- **`OptionSpinner` scoped key bindings** with last-writer-wins **scope subtraction** per screen.


The package abstracts away the complexities of managing curses pads, dynamic screen resizing, custom scroll/pick synchronization, and keyboard handling. Its strengths include:

1. **Zero runtime dependencies.** The only requirements are the standard-library `curses` and `curses.textpad` modules — no third-party dependency tree and no associated supply-chain risk.
2. **Efficient rendering.** Uses accumulated refreshes on the screen and pads with a single terminal update per frame, rather than flicker-prone full refreshes. A redraw path can recover the display from terminal corruption.
3. **Two-axis scroll/pick model.** The scroll position and the pick (cursor) position are tracked independently and reconciled each frame. Most simple pagers conflate these; separating them is what enables kept-visible selection with context rows above and below.
4. **Per-line metadata plus an `abut` concept.** Because context is attached to each line rather than parsed from text, and transient child rows auto-abut to their parent, expandable/transient detail rows stay attached to the row that produced them. "After trumps before" is a thoughtful touch.
5. **Non-pickable rows are first-class.** Decorative separator and header lines are skipped by navigation and page movement, so they do not produce "dead" cursor stops; scrolling still reaches them, including a trailing block of them past the last pickable row.
6. **Scoped, self-subtracting key bindings.** A later, narrower binding (e.g. `ESC` to clear a filter on one screen only) subtracts that screen from an earlier global binding. This is a real router, not a flat key map, and it actively rejects collisions with navigation keys.
7. **Convention-based dispatch.** Actions map to matching handler methods on screen classes, keeping them free of central `if key == ...` towers.
8. **Resize resilience.** Rendering retries during terminal resizes, dialogs drain resize events, and the window enforces a minimum size instead of crashing.  The minimum starts at a small floor and is raised once, after the first screen is drawn, to fit that screen's header plus a few body rows.
9. **Inline confirmation is unusually complete.** Tiered matching (exact, then case-insensitive, then abbreviation), an auto-calculated minimum abbreviation length, and six modes including identity matching and free text.
10. **Real, dogfooded apps.** The API is validated by several downstream projects (listed below), not by theory.
11. **Headless, testable core.** The layout math and a headless render backend let the whole engine be exercised without a TTY.
12. **Display-cell correctness.** A small standard-library width engine accounts for wide CJK/emoji and zero-width combining marks, so layout and highlighting stay correct across the body, header, dialogs and the demos that exercise wide and combining text.


## Installation

Install the package via `pip`:

```bash
pip install console-window
```

## Running the Demos (from source)

For development, the demos run directly against your working tree — no install or build step required:

```bash
./runner                     # the lettered menu from demos/demos.ini
./demos/run-demo a-basic     # one demo, by short name
./demos/run-demo features    # the feature -> demo owner map
```

A, B and C are complete single-file programs; D–P are short deltas on `demos/demo_kit.py`. The full curriculum, feature ownership and change rule are in [`docs/DEMO-APPS.md`](docs/DEMO-APPS.md).

Every demo takes the same display switches:

```bash
./demos/run-demo a-basic --ascii
./demos/run-demo j-themes --theme nord
NO_COLOR=1 ./demos/run-demo j-themes   # same as --theme mono
```

`mono` is a real theme, not a separate color flag. It uses the terminal's own foreground and background plus a bold/reverse attribute hierarchy, so it follows a light or dark terminal automatically. `NO_COLOR` selects it for a run when no explicit `--theme` is given.

## Core Features (The "Secret Sauce")

The wrapper handles several advanced terminal interaction patterns automatically:

  * **Viewport-Sized Pads:** Separate `head` and `body` pads give the static header band and the independently scrolling body, but the pads are blit buffers sized to the terminal rather than content stores. `add_body()`/`add_header()`/`draw()` write the model, and `render()` paints the visible page into pad row 0, so pad memory and per-frame `clear()` cost stay constant no matter how many rows an app adds. Row counts need no configuration at all: `opts.body_rows` / `opts.head_rows` are advisory hints only, and `opts.max_rows` (default `32767`, `None` for unlimited) is the single content ceiling.
  * **Loud Content Limits:** A row added past `opts.max_rows` is discarded, but no longer quietly: the first discarded row of each fill episode emits a `UserWarning` naming the namespace and the option to change, and every discarded row is counted in `ConsoleWindow.rows_dropped`. It stays non-fatal — run `python -W error::UserWarning` if you would rather it killed the app.
  * **Seamless Resizing:** Automatically detects terminal size changes (`KEY_RESIZE`) and recalculates layout dimensions, with robust error handling to prevent common `curses.error` crashes during resizing.
  * **Graceful Color Degradation:** Themes are written against the 256-color xterm palette, but installation asks the backend how many colors the terminal actually exposes. A 256-color terminal gets the theme's literal specs; 16-, 88- and 8-color terminals get the nearest available palette entry, with a contrast guard so a pair never collapses to `fg == bg`; below 8 colors (or with no color support) the theme falls back to attributes. `-1` is only emitted when `use_default_colors()` succeeds, and `COLOR_PAIRS` is respected. Stock tmux (`TERM=screen`, 8 colors) therefore works instead of raising `ValueError: Color number is greater than COLORS-1`.
  * **Scroll & Pick Synchronization:** The `Window` class manages **scroll position** and a separate **pick position** (highlighted row) simultaneously.
    * When using pick mode, scrolling automatically tracks the highlighted element to keep it visible in `.pick_pos`.
    * To use that value, you must separately be able to associate `.pick_pos` to its value by, say, keeping an array of values for every added line to the `body`. 
  * **Intuitive Navigation:** Provides built-in handling for common navigation keys (`j`/`k`, `UP`/`DOWN`, Page Up/Down, `H`/`M`/`L` for home/middle/last viewable line, etc.).
  * **Dynamic Options Management (`OptionSpinner`):** The companion class simplifies creation of application settings, allowing users to **toggle options** or input strings using single keypresses (e.g., `p` to toggle pick mode).
  * **Blocking Popups:** Includes fully implemented, blocking pop-up methods for user input (`.answer()`) and alerts (`.alert()`), handling the necessary temporary screen takeover and cursor management.

## Worked Example: the lettered demos

The canonical examples are the demos in [`demos/`](demos). They form a
curriculum, not one app with every feature:

* **A — [`a-basic`](demos/demo-a-basic.py)** is one `Screen`, one table, and
  the four-call loop. Navigation scrolls the body; live data changes one row
  each pass.
* **B — [`b-stack`](demos/demo-b-stack.py)** adds a second page and a
  `ScreenStack`; each screen keeps its own content and scroll position.
* **C — [`c-options`](demos/demo-c-options.py)** adds an `OptionSpinner`, a
  validated prompt, scoped keys and a generated help screen.

D through P each add one focused lesson on the shared kit: picking, search,
in-place prompts, dialogs, messages, headers, themes, glyphs, read-only text,
navigation ownership, suspend/resume, large bodies, and width/debug aids.
[`docs/DEMO-APPS.md`](docs/DEMO-APPS.md) lists all sixteen, the feature each
one owns, and the rule that a library feature change names its demo in the
changelog.

### Running it

```bash
./runner                 # menu
./demos/run-demo a-basic # one demo
```

The demos are interactive and need a real terminal (any POSIX box). They are
repo-level scripts, **not** part of the installed package: after
`pip install console-window` you write your own `main()` — start from A, B or C,
or from the shape below.

### The shape of every app

A `Screen` owns its content and its pick/scroll position; the window owns the terminal, the pads and key routing.  The loop is four calls, and rebuilding the whole page every pass is the sanctioned style:

```python
from types import SimpleNamespace

from console_window import ConsoleWindow, ConsoleWindowOpts, Screen


class Pager(Screen):
    def draw_screen(self) -> None:
        self.add_header('hello - q or ESC to quit')
        for i in range(100):
            self.add_body(f'row {i}')


def main() -> None:
    # ConsoleWindow.__init__ performs the curses setup (no curses.wrapper needed).
    # No row sizing is required; max_rows is only a safety ceiling.
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_line=True))
    app = SimpleNamespace(win=win)
    screen = Pager(app)
    try:
        while True:
            screen.clear()          # content reset for the new pass
            screen.draw_screen()    # add_header()/add_body() only
            win.render()            # pads repaint, doupdate() diffs
            key = win.prompt(seconds=0.5)   # key code, or None on timeout
            if key in (ord('q'), 27):
                break
    finally:
        win.stop_curses()


if __name__ == '__main__':
    main()
```

`clear()` is also what hands the screen to the window, which is why it comes
first.  The pick/scroll position, pick mode and free-scroll latch live on the
screen and survive each pass, so a rebuild never loses the user's place.  For
more than one screen, subclass `Screen` and drive the screens with
`ScreenStack` — activation is a pointer swap, so returning to a screen restores
its position with no copying in the application.

### Inline editing and key forwarding

`InlineConfirmation` is a curses-free line editor. `start(..., initial='x')` seeds the buffer with the caret at the end; `LEFT`/`RIGHT`, Home/End (and Ctrl-A/Ctrl-E), Backspace and Delete edit at the caret. The `get_display_string(prompt='…')` method returns the prompt plus the buffer and caret glyph, so wording and layout stay in the application, while `cursor_pos` (string index) and `cursor_cell` (terminal column, measured with `textwidth`) are available to callers that need them.

Passthrough widgets receive printable ASCII, navigation keys, Backspace, Delete, Home/End, ESC and the keys in `handled_keys` while `passthrough_mode` is `True`. For any additional application key, use the reversible context manager rather than mutating `handled_keys` by hand:
```python
win.passthrough_mode = True
try:
    with win.temp_handled_keys(27):
        key = win.prompt(seconds=0.5)
finally:
    win.passthrough_mode = False
```

Only keys the context actually added are removed on exit, so a pre-existing binding is left in place and nested uses are safe.

### Transient status on the separator row

`status()` declares a one-line message that is painted on the separator row — the row that also owns the scroll indicator — so the listing stays visible.  Unlike `flash()`, which clears the whole screen, `status()` never takes over the display:

```python
win.status('Backup tag failed', level='error', timeout=5.0)
```

The message appears on the next `render()`/`prompt()`; `status()` never renders by itself. Levels `'info'`, `'warn'` and `'error'` select an attribute from `ConsoleWindow.STATUS_LEVELS` (`info` dim, `warn` bold, `error` bold+reverse); an unknown level falls back to `'info'` instead of raising, and `attr=` overrides the level for that message only. `timeout=None` keeps the message until it is replaced or cleared; any number expires it lazily at draw time. `status('')` and `clear_status()` remove it, and `current_status` returns `(text, attr)`.

The exact rendering rule is: the text starts at column 0 of the separator row and is truncated to leave **one blank cell between it and the scroll indicator**.  If the window currently has no separator row, the text is still stored and `status()` returns `False` (the message is deferred, not lost); a later resize reveals it.  With `head_line=False` there is no separator row at all, so `status()` also warns once per episode instead of painting over the first body row.

### In-place prompts

`PromptLine` is the window-independent state machine: text, an editable buffer, an optional hint and completion callbacks. It never runs the callbacks itself; `take()` returns `(answer, on_confirm, on_cancel)` after cancelling the widget.  The window wraps it with a lifecycle that keeps key routing and passthrough consistent:

```python
win.begin_prompt('Overwrite the tag?', mode='y',
                 on_confirm=lambda answer: apply(answer))
while win.prompt_active:
    key = win.prompt(seconds=0.5)
    if win.handle_prompt_key(key) == 'continue':
        continue          # swallow every key while a prompt is live
    break
win.render()
```

While `prompt_active` is true, route **every** key through `handle_prompt_key()` and swallow a `'continue'` result, so no action key can fire underneath a live prompt. `begin_prompt()` turns `passthrough_mode` on and `end_prompt()` restores its previous value; completion callbacks run *after* the prompt is gone and passthrough is restored, so a callback may safely begin the next prompt (the "re-edit, then ENTER or ESC" re-ask path).

The display formats are fixed so applications do not have to reproduce them:

* single-key modes `Y`/`y`: `f'{prompt}  [Press "{mode}" or ESC]'`, e.g.  `Really quit?  [Press "y" or ESC]`;
* every other mode: `f'{prompt}: {buffer}{caret}{rest}'`, e.g. `Value: 5│`.

`get_hint_string(width)` returns the hint (truncated when a width is given), and `get_choice_lines()` returns one row per choice, marking the currently resolved one: `➤ alpha` versus `  beta`. Drawing is the application's choice: `Screen.add_prompt_header()` puts a screen-wide question in the header band, while `Screen.add_prompt_lines()` appends a bold prompt row and a dim hint row as `Context(genre='TRANSIENT', pickable=False)` from the application's own row loop. The window never learns which item the prompt belongs to.

### Read-only text screens

`BasicTextScreen` is the small `Screen` for preformatted, scrollable text. It resolves `app.win` at call time, disables pick mode, adds each header before the body, and adds each line with `add_body()` and no `Context` (so normal navigation scrolls it). Content is normalized by `set_text()`, which is safe before or after the first draw; the loop still calls `screen.clear()` before `draw_screen()`:

```python
screen = BasicTextScreen(app, head='COMPARE',
                         lines=[('first difference', curses.A_BOLD),
                                'second difference'])
screen.set_text(lines=['replacement'])
```

`lines` items are `str` or `(str, attr)`; `head` may be a `str`, a `HeaderLine`, or an iterable of either. There is no pick mode, no action handler and no spinner: ESC/back uses the default `Screen.escape_ACTION` (pop), which the application may override.

### Taking navigation keys for the application

Navigation keys are reserved by default, but an app may take specific ones for itself without monkeypatching the module global. Declare them on the window's options; the mapping value is the label the help screen shows:

```python
import curses
from console_window import ConsoleWindowOpts, OptionSpinner

opts = ConsoleWindowOpts(
    taken_nav_keys={
        curses.KEY_LEFT: 'prev page',
        curses.KEY_RIGHT: 'next page',
    },
)
win = ConsoleWindow(opts=opts)
spin = OptionSpinner(stack=stack, nav_keys=opts.nav_keys)  # accept them in add_key()
spin.add_key('prev', '⬅ - previous', genre='action', keys=[curses.KEY_LEFT])
```

A taken key is withdrawn from navigation dispatch for that window only: it no longer scrolls, it is no longer advertised as navigation, and it takes the normal `handled_keys`/`relax_handled_keys` path on return. Text editing is unchanged — dialogs and widgets still use LEFT/RIGHT/HOME/END for the caret.  Because ownership lives in `ConsoleWindowOpts`, two windows in one process can have different bindings; `NAVIGATION_KEYS` itself is never mutated. Taking every vertical key is allowed (and logged as "reduced navigation"), since the application is then responsible for its own scrolling.

`ScreenStack.perform_actions()` is the normal router: it walks the spinner options, honors their scopes, and calls the matching `<attr>_ACTION` method.  For apps that dispatch an action themselves, `ScreenStack.act_in(action, screens=None)` is the low-level single-flag variant: it clears that flag from `stack.obj` and returns whether it was set and the current screen matched.  `ScreenStack.is_curr()` answers the screen test on its own. A missing flag reads as `False`, so an options object need not pre-seed every action.

### Help body, built-in actions and the spinner

A spinner registers two actions before the application registers anything: `quit` (`q`, `^C`) and `escape` (`ESC`, `^J`, `ENTER`). They are printed once in the `NavKeys:` block, never in the option body. `Screen` supplies the default handlers — `quit_ACTION()` exits and `escape_ACTION()` pops one screen (a no-op at home) — and an app overrides either method as usual. The key sets are constructor arguments:

```python
spin = OptionSpinner(stack=stack, quit_keys=(ord('q'), ord('Q'), 0x3))
```

A `ScreenStack` owns at most one spinner: the spinner injects itself as `stack.spinner`, and the stack assigns each screen its `num` and `stack`, so a help screen finds the spinner without scanning the application. Constructing a second spinner on the same stack raises `ValueError`.

The help body lists only the options whose scope includes the help screen, so "shown" and "works" are the same set; an option meant to work on help names it in `scope=`. The built-in actions are excluded, and when nothing applies the `Type keys to alter choice:` heading is omitted. `OptionSpinner.options_for_screen(screen)` is the same definition an application can use when drawing its own help. A registration that would take a built-in key must name its screens explicitly (`scope=...`); an implicit registration raises, so a global option can no longer silently unbind `q`/`^C`/`ESC`.

### Singleton vs. per-instance windows

`ConsoleWindow` supports two process-wide models, selected by the constructor's `singleton` argument:

* **`singleton=True` (default)** — the historical process-wide model. Every window draws through one shared screen, `ConsoleWindow.static_scr` and `ConsoleWindow.static_win` are populated, and a second window reuses the first window's screen and backend. `stop_curses()` here *suspends* the shared screen and `start_curses()` resumes it (the pre-2.0 pair, kept working); `ConsoleWindow.stop_all()` is the permanent teardown and the `atexit` hook.
* **`singleton=False`** — per-instance windows. Each window owns its screen, pads and teardown; `win.stop_curses()` stops only that window for good, `ConsoleWindow.stop_all()` stops every live window, and the unbound `ConsoleWindow.stop_curses()` is an error.

### Pausing to run another program

To shell out (an editor, a package manager, `efibootmgr`, a confirmation prompt) and then come back, suspend instead of stopping:

```python
win.suspend_curses()          # endwin(): the terminal is yours again
try:
    ... prints, input(), subprocess.run(...) ...
finally:
    win.resume_curses()       # reattaches a screen; the next render() repaints
```

`endwin()` restores the terminal without destroying the curses SCREEN, so the pads, the content model and the pick state all survive; resume refreshes the screen handle, backend, dimensions, pad backgrounds and redraw bookkeeping.  In singleton mode `suspend_curses()` suspends every window that shares the screen, and `resume_curses()` reattaches all of them. The legacy pair works the same way there: `ConsoleWindow.stop_curses(); ...; ConsoleWindow.start_curses()`.  The pre-2.0 instance hook `win._start_curses()` is also supported: it reattaches that window (resuming a suspended screen) and returns the live screen, so the old `win.stop_curses(); ...; win._start_curses()` sequence keeps working.  Only `stop_all()` is a permanent teardown.

The first successful construction latches the mode for the whole process.  Mixing the two values raises `AssertionError` rather than silently changing what teardown means. Use `singleton=False` in tests and in applications that create independent windows (for example, one real window plus a headless one).

### Symbols on terminals that cannot draw them

The UI is built around non-ASCII symbols (`│`, `➤`, `█`, `⬅`, `➡`, `·`, box drawing). A terminal that cannot encode them does not fail loudly: it paints a box, or nothing, and the row quietly loses its meaning. `console-window` therefore keeps every symbol in one registry, in two spellings, and degrades by itself:

* **No code change.** A window detects the terminal when it is constructed — a non-UTF-8 output encoding or `TERM=dumb` selects the ASCII spellings — and text handed to `add_header()` / `add_body()` / `draw()` / `status()` / `flash()` is transliterated before it is measured, so widths and the run-length attribute counts stay correct.
* **Only registered symbols are rewritten.** `Grüße` stays `Grüße`: the substitution table contains the catalog's characters, never arbitrary text, so letters, digits and unregistered code points pass through byte for byte. A registered typographic mark does follow the mode, which is the point of it — an em dash inside file content becomes `--` on an ASCII terminal rather than a box. The eight spellings this library used to draw (`⮞`, `←`, `→`, `↑`, `↓`, `○`, `□`, `■`) are upgraded to their replacements (`➤`, `⬅`, `➡`, `⬆`, `⬇`, `◯`, `◻`, `◼`) in **both** modes, so text written against an older release renders from the font that has it — inside content as well. Registering an old code point yourself keeps it. Set `CONSOLE_WINDOW_GLYPH_AUDIT=1` to log each decorative code point you use but
  did not register, with the exact `register()` call to add.

* **A catalog to choose from.** The registry carries about eighty named symbols, grouped as UI marks, frames, arrows, triangles, filled/hollow shape pairs, blocks and bars, marks, math, currency and typography. Every one is a single cell wide and is covered by the default monospace font on Debian, Ubuntu and Fedora (DejaVu Sans Mono), so it is safe to use without a patched font: no emoji, no icon fonts. `Glyphs.catalog()` returns the set in the active spelling and `Glyphs.catalog_rows(width)` packs it into display rows; the theme picker page prints all of them, so that page doubles as the font check. A character has exactly one fallback even when two names draw it (`cursor_block` and `swatch` are the same block).
* **App vocabulary.** Register what only your app draws:

  ```python
  Glyphs.register_many({'tick': ('✓', 'OK')}, probe=('tick',))
  ```

  or pass it with the window: `ConsoleWindowOpts(glyphs={'tick': ('✓', 'OK')}, glyphs_probe=('tick',))`. Once registered, the glyph both degrades with `Glyphs.get('tick')` and appears in the font check via `Glyphs.probe_text()`.
* **The switches, with no argparse boilerplate.** The bundled helper adds them:

  ```python
  parser = cli.add_display_arguments(argparse.ArgumentParser())
  opts = parser.parse_args()
  cli.apply_display_arguments(opts, prog='myapp')
  ```

  `--ascii` forces the fallback (`--ascii=no` forces the full set) and `--glyphs {auto,ascii,unicode}` is its symmetric spelling; `--glyphs` wins if both are given. `--theme` seeds the first window's color theme, and `--theme mono` draws the semantic roles with bold/reverse attributes instead of color. A non-empty `NO_COLOR` selects `mono` when no explicit theme is given. Apps without argparse can use `CONSOLE_WINDOW_GLYPHS=auto|ascii|unicode`, which outranks detection.
* **The mode is process-wide**, like the color-pair table, because there is one terminal. `ConsoleWindowOpts(ascii=...)` seeds it and `win.ascii_mode` reads it; a window constructed later never reverts an explicit choice.
* **Help screens can explain it for you.** Return `help.theme_paragraph()` from `Screen.extra_help_paragraphs()` and set `show_display_notes = True` on a `BasicHelpScreen` subclass to append the font check (Unicode mode) or the way back to the full set (ASCII mode). Both are off by default, so an upgrading app's help output is unchanged.

Themes work the same way: `Theme.create_picker_screen(base, cycle_key=None, store=None, note=None, captions=None, include_defaults=True)` discovers the key you bound to `spin_theme` for its hint line, remembers the choice through any object with `load()`/`save()`, and `Theme.initial(cli_theme, store)` returns the theme a new process should start on. The library never opens a file. `Theme.list_all()` includes `mono`, so the picker cycles it like any other theme; its swatches follow the same switch, so a picker opened on `mono` previews the monochrome hierarchy rather than a previous theme's colors.

`captions` renames or re-describes the semantic roles the picker shows, which is useful when the application's vocabulary differs from the library's. The mapping is `role -> (label, usage)`, where a role can be a `Theme` constant or a stable name such as `'danger'`; `None` or `''` keeps the library text. With the default `include_defaults=True`, overrides replace captions in place and the library rows remain; with `include_defaults=False` the mapping is the whole list, in mapping order. Unknown or duplicate roles raise `ValueError` when the factory runs.

```python
ThemeScreen = Theme.create_picker_screen(
    DemoScreen,
    cycle_key='t',
    captions={
        'danger':  ('FAILED',   'Boot or initramfs failed'),
        'warning': ('DEGRADED', ''),  # keep the library usage text
    },
)
```

Override `swatch_attr()` on a subclass to style swatches differently, `swatch_rows()` for dynamic captions (translation, for example), and `theme_label()` only if an application adds its own pseudo-theme.

The appearance layer is shared too. `Appearance.semantic_attr(role)` returns the installed color pair for a semantic role, or the matching attribute from `Appearance.MONO_ROLES` when color is off or the terminal reports no color support; a lookup that fails before `initscr()` degrades to plain text, so a redraw is never aborted by a color. `Appearance.resolve_appearance(cli_theme=None, saved_theme='', environ=None)` returns the theme to start with: an explicit `--theme` first, then the `NO_COLOR` convention (`mono`), then the remembered choice. Pass the result to `Theme.set_active()`, which records it and synchronizes `Appearance.colors_enabled()` / `Appearance.set_colors_enabled()`; applications select `mono` rather than flipping the switch themselves. Apps keep their preference file and any additional pseudo-themes; the library gives them the policy, not the storage.

## Versioning and Deprecation

`console-window` follows semantic versioning: patch releases fix behavior without changing the public API, minor releases add functionality, and major releases may make incompatible changes.

Deprecated APIs remain supported **indefinitely**. A deprecation is a request to migrate, not a scheduled removal: deprecated functions and parameters keep working, and one is removed only when there is significant value in doing so (for example, the API is actively harmful or blocks a necessary redesign).  Deprecated paths emit a `DeprecationWarning` where practical.

---

### 3.0.0 Breakages

`3.0.0` is the first release after the 2.x line, so every deliberate break from 2.x is collected here, each with its replacement.  Later 3.x releases are intended to remain upward compatible with this one.

**The Screen owns content.** Content and the pick/scroll state moved from `ConsoleWindow` onto `Screen`, which removes one of the two drawing models:

- **`win.add_header()`, `win.add_body()`, `win.add_fancy_header()`, `win.add_header_line()`, `win.add_prompt_header()` and `win.add_prompt_lines()` are gone.** Call them on the current `Screen` instead (`self.add_body(...)` inside `draw_screen()`).  The window keeps `head`/`body` as read-only views.
- **`win.draw(y, x, text, ...)` is gone**, with `highlight_picked()` and the deferred `drawn` span store.  There is one drawing model: append rows with `add_*()`; a row's column placement is composed by the application with `textwidth.string_width`/`ljust`/`truncate`.
- **Content and pick/scroll state are per screen.** `win.pick_pos`, `win.scroll_pos`, `win.pick_mode`, `win.free_scroll` and `win.pick_range` read and write the *current* screen; `pick_range` is no longer stored in `ConsoleWindowOpts`, so two screens can hold different ranges.  `last_pick_pos` and `_pick_clear_pending` are gone with the incremental painter.
- **The loop is `screen.clear(); screen.draw_screen(); win.render(); win.prompt()`.** `Screen.clear()` is what makes the screen current, so it must be the first call.  `ConsoleWindow.clear()` still works and resets the current screen's content, but it no longer wipes the physical screen (the pads repaint themselves every frame).
- **`head_line=False` now has no side effects.** It no longer paints a rule, a scroll indicator or a status line onto the body's first row, and in scroll mode the pick tracks the top of the viewport (`pick_pos == scroll_pos`).

**Appearance and themes.** There are renames for consistency and some simplifications:

- **`appearance` is now `Appearance`.** This matches the rest of the package root (`Theme`, `Glyphs`, `Context`, …).
- **`--no-color` is gone.** Select the real `mono` theme instead (`--theme mono`), or rely on the `NO_COLOR` environment convention. `cli.resolve_no_color()` and the `no_color=` / `saved_colors=` parameters of `Appearance.resolve_appearance()` were removed with it.
- **`Appearance.resolve_appearance()` returns one theme name**, not `(theme, colors)`. Apply it with `Theme.set_active()`; `mono` is the color-off state.
- **`dark-mono` / `light-mono` are now `dark` / `light`.** The old names are still accepted as aliases by `--theme`, remembered preferences and `Theme.resolve()`, but `Theme.list_all()` lists only the canonical names.
- **`mono` is a theme.** It installs only the terminal-default background and uses `Appearance.MONO_ROLES` for the semantic roles. It is terminal-global like any other theme install, because curses owns one color-pair table per terminal.

**The built-in symbols are the heavier, font-safe forms.** The library moved the symbols it draws itself to the heavier variant wherever one exists in the default monospace font:

- **The resolved-choice marker is `➤` (U+27A4), not `⮞` (U+2B9E).** U+2B9E is absent from DejaVu Sans Mono — the default on Debian, Ubuntu and Fedora — so the marker was drawn by whichever fallback font had it, which can be wider than one cell. `Glyphs.get('choice')`, `get_choice_lines()` and `InlineConfirmation` follow the new form; the ASCII fallback is still `>`. An application that hardcoded `⮞` should use `➤`, or register `⮞` itself to keep the old look.
- **The arrows are the black forms.** `⬅`/`➡` replace `←`/`→` (including the help legend's labels for taken keys) and `⬆`/`⬇` replace `↑`/`↓`. The light code points are no longer registered, so text containing them is not transliterated; `CONSOLE_WINDOW_GLYPH_AUDIT=1` reports them.
- **The hollow shapes are the heavier pair.** `◯` replaces `○`, and `◻`/`◼` replace `□`/`■`. The hollow triangles `△▽◁▷` keep their light form: Unicode has no heavy outline triangle.
- **Old spellings are upgraded in both modes.** `⮞`, `←`, `→`, `↑`, `↓`, `○`, `□` and `■` are rewritten to `➤`, `⬅`, `➡`, `⬆`, `⬇`, `◯`, `◻` and `◼` before the text is measured, in Unicode mode as well as ASCII. An unmodified application therefore picks up the font-safe shapes; registering one of the old code points (`register('choice', '⮞', '>')`) keeps it instead.

---

## License
MIT

## Comparable and Competing Projects

`console-window` is a niche tool. **For almost everyone, one of the projects below is the better choice** — reach for `console-window` specifically when you want a dependency-free, keyboard-driven list/detail viewer in the "pager meets selection engine" style and you are comfortable building your own widgets on top of it.

| Framework | Model | Widgets | Dependencies | Async/threads | Wide chars | Testing | Learning curve | Best for |
|---|---|---|---|---|---|---|---|---|
| **console-window** | head/body **pads** + scroll/pick + screen stack | you build views from your own classes; options, search bar, inline confirmation, dialogs | **none (stdlib)** | sync polling | yes (stdlib cell width) | `pytest`, TTY-free, render via a fake backend | low | keyboard list/detail viewers, "less-like" browsers |
| **urwid** | canvas + widget tree, event loop | rich (ListBox, Tree, Edit, Overlay, Columns/Pile) | `wcwidth` | event loops | yes (via wcwidth) | good (examples, docs) | medium | general full-screen apps |
| **Textual** | DOM + CSS, async, reactive | very rich; mouse, animations, web target | `rich`, `markdown-it`, `typing-extensions`, … | asyncio-first | yes | strong (pytest harness) | medium–high | modern, styled, ambitious TUIs |
| **prompt_toolkit** | input-centric full-screen | editing, completion, dialogs; limited layout widgets | `wcwidth` | yes | yes | strong | medium | REPLs, shells, rich input |
| **npyscreen** | forms/fields | form widgets (menus, multisets) | stdlib curses | no | partial | sparse | low | classic form-style admin TUIs |
| **py_cui** | widget grid | menus, scroll, forms | stdlib curses | no | partial | some | low | quick dashboards |
| **asciimatics** | screens + effects | widgets + animation engine | `pyfiglet`, `pillow` | no | partial | some | low–medium | animated/demo screens |
| **blessed** | raw terminfo control | none (primitives) | `jinxed` (Windows) | no | partial | some | low | custom low-level drawing |
| **Rich** | text/print styling (+Live/Layout) | none (not a TUI toolkit) | `markdown-it-py`, `pygments` | partial | yes | strong | low | pretty output/logs, not navigation |

**Where `console-window` wins:** zero dependencies; a tiny conceptual surface; excellent selection/paging semantics (`abut`, pick vs. scroll, decorative-row skipping); a scoped key router; efficient pad blitting; and a model already proven across several real apps.

**Where it loses to the big two (urwid / Textual):** no widget library, no mouse, no CSS/layout language, no async, no documentation site, single-window only. Textual in particular offers a testing framework and a modern developer experience a solo project cannot match — at the cost of a dependency tree and a very different paradigm.

**Closest functional peers:** `npyscreen` (form/list admin TUIs) and `py_cui` (dashboard grids) — both stdlib-curses, both simpler and less maintained than Textual/urwid. `console-window` is differentiated by its pager-centric selection model, which those two lack.

## Projects Using console-window
For more extensive examples, you can look at some projects using `console-window`:

* [efibootdude](https://github.com/joedefen/efibootdude)
  * simple wrapper for `efibootmgr`
  * one of the smaller projects
  * demonstrates a context sensitive available keys lines (i.e., first line) where the actions depend on current line.
* [dwipe](https://github.com/joedefen/dwipe)
  * disk cleaner with parallel jobs and stamps wiped partitions
* [pmemstat](https://github.com/joedefen/pmemstat)
  * system/process memory monitor with rollups and hooks for zRAM
* [memfo](https://github.com/joedefen/memfo)
  * viewer of /proc/meminfo that shows historical values
* [vappman](https://github.com/joedefen/vappman)
  * convenince wrapper to mostly hide CLI of [AppMan](https://github.com/ivan-hc/AppMan), a life-cycle manager for 2000+ AppImages
