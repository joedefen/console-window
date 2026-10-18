
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
8. **Resize resilience.** Rendering retries during terminal resizes, dialogs drain resize events, and the window degrades gracefully below its minimum size instead of crashing.
9. **Inline confirmation is unusually complete.** Tiered matching (exact, then case-insensitive, then abbreviation), an auto-calculated minimum abbreviation length, and six modes including identity matching and free text.
10. **Real, dogfooded apps.** The API is validated by several downstream projects (listed below), not by theory.
11. **Headless, testable core.** The layout math and a headless render backend let the whole engine be exercised without a TTY.
12. **Display-cell correctness.** A small standard-library width engine accounts for wide CJK/emoji and zero-width combining marks, so layout and highlighting stay correct across the body, header, dialogs and the emoji-heavy sample app.


## Installation

Install the package via `pip`:

```bash
pip install console-window
```

## Running the Sample App (from source)

For development, run the bundled sample app directly against your working tree —
no install or build step required:

```bash
./runner
```

(`runner` executes `SampleApp` as `__main__`, so live edits are picked
up immediately. The equivalent one-off is `python3 SampleApp.py`.)

## Core Features (The "Secret Sauce")

The wrapper handles several advanced terminal interaction patterns automatically:

  * **Padded Content Management:** Uses separate `head` and `body` pads, allowing for a static header area while the main content area can be scrolled independently.
  * **Loud Pad Limits:** The pads are fixed-size (`opts.head_rows` / `opts.body_rows`). Rows added past capacity are still discarded, but no longer quietly: the first discarded row of each fill episode emits a `UserWarning` naming the pad and the option to raise, and every discarded row is counted in `ConsoleWindow.rows_dropped`. It stays non-fatal — run `python -W error::UserWarning` if you would rather it killed the app.
  * **Seamless Resizing:** Automatically detects terminal size changes (`KEY_RESIZE`) and recalculates layout dimensions, with robust error handling to prevent common `curses.error` crashes during resizing.
  * **Scroll & Pick Synchronization:** The `Window` class manages **scroll position** and a separate **pick position** (highlighted row) simultaneously.
    * When using pick mode, scrolling automatically tracks the highlighted element to keep it visible in `.pick_pos`.
    * To use that value, you must separately be able to associate `.pick_pos` to its value by, say, keeping an array of values for every added line to the `body`. 
  * **Intuitive Navigation:** Provides built-in handling for common navigation keys (`j`/`k`, `UP`/`DOWN`, Page Up/Down, `H`/`M`/`L` for home/middle/last viewable line, etc.).
  * **Dynamic Options Management (`OptionSpinner`):** The companion class simplifies creation of application settings, allowing users to **toggle options** or input strings using single keypresses (e.g., `p` to toggle pick mode).
  * **Blocking Popups:** Includes fully implemented, blocking pop-up methods for user input (`.answer()`) and alerts (`.alert()`), handling the necessary temporary screen takeover and cursor management.

## Worked Example: `SampleApp.py`

The canonical example is the bundled sample app:

**<https://github.com/joedefen/console-window/blob/main/SampleApp.py>**

It is a read-only `/etc/passwd` browser, and it is deliberately more than a list:
it exercises the whole `Screen` paradigm the library is built around — one
window, a `ScreenStack` of screens, and key bindings scoped per screen. What it
demonstrates:

* **`ScreenStack` + four screens** (`MAIN`, `HELP`, `HISTORY`, `THEMES`) pushed
  and popped with `?`, `h`, `t` and `ESC`/`ENTER`, dispatched through
  `ScreenStack.perform_actions()`.
* **Convention-based actions** — each key maps to an `<attr>_ACTION` method on the
  current screen (`filter_ACTION`, `select_ACTION`, `help_screen_ACTION`, …), so
  there is no central `if key == ...` tower.
* **Scoped, self-subtracting keys** — `t` opens the theme screen on `MAIN` but
  cycles themes on `THEMES`/`HELP`; the narrower binding subtracts its screen
  from the wider one automatically.
* **Per-line `Context` metadata** — rows carry `Context(genre='item')`, read back
  with `get_picked_context()`, and decorative rows (`Context(genre='DECOR')`) are
  skipped by navigation.
* **`IncrementalSearchBar`** — `/` filters the list as you type, using
  `passthrough_mode` to hand keys to the bar.
* **`InlineConfirmation`** — `SPACE` asks you to confirm with `y` before
  "processing" the picked row.
* **Themes** — a `THEMES` screen of colour samples backed by
  `Theme.list_all()` / `get_current()` / `set()`.
* **Dialogs** — `a` calls `answer()` for text input, `l` calls `alert()`, and `n`
  drives `answer()` from an `OptionSpinner` option (`add_key(..., prompt=...)`).
  `answer()` returns `None` only when the user aborts; if the terminal cannot
  fit the dialog it raises `TerminalTooSmallError` with the required and actual
  sizes.
* **`flash()`** — transient, non-destructive status messages.
* **Token-based headers** — `HeaderLine` (`text`, `bracket_key`, `key`, `extend`)
  rendered with `add_header_line()`, rather than string markup.
* **`Ctrl-C` as an application key** — `ctrl_c_terminates=False` and
  `keys={0x3, ord('q')}` on the quit action. This works only while no window in
  the process has requested terminating Ctrl-C: once any window uses the default
  (`ctrl_c_terminates=True`), terminating Ctrl-C is latched for the process
  lifetime and cannot be undone.
* **Full-repaint recovery** — `r` toggles `render(redraw=True)`, the path that
  repaints after terminal corruption.
* **Multi-row picking** — `p` sets `pick_size` (1–3) via
  `set_pick_mode(True, size)`.
* **Large-body stress** — `z` appends 2000 non-pickable filler rows to exercise
  big pads and the scroll indicator. The sample raises `body_rows` to 4000 so
  that nothing is discarded: `row_cnt` is capped at the pad size and any excess
  is counted in `ConsoleWindow.rows_dropped`.

### Running it

See [Running the Sample App (from source)](#running-the-sample-app-from-source)
above. The sample app is interactive, so it needs a real terminal (any POSIX
box). It is a repo-level script and is **not** part of the installed package:
after `pip install console-window` you write your own `main()` — start from the
sample app above, or from the shape below.

### The shape of every app

```python
from console_window import ConsoleWindow, ConsoleWindowOpts


def main() -> None:
    # ConsoleWindow.__init__ performs the curses setup (no curses.wrapper needed).
    win = ConsoleWindow(opts=ConsoleWindowOpts(head_line=True, body_rows=200))
    try:
        while True:
            win.clear()
            win.add_header('hello - q or ESC to quit')
            for i in range(100):
                win.add_body(f'row {i}')
            win.render()
            key = win.prompt(seconds=0.5)   # key code, or None on timeout
            if key in (ord('q'), 27):
                break
    finally:
        win.stop_curses()


if __name__ == '__main__':
    main()
```

For anything beyond a single list, subclass `Screen` and drive it with
`ScreenStack` — that is what the sample app does, and it is the paradigm the
library is designed around.

## Versioning and Deprecation

`console-window` follows semantic versioning: patch releases fix behaviour
without changing the public API, minor releases add functionality, and major
releases may make incompatible changes.

Deprecated APIs remain supported **indefinitely**. A deprecation is a request to
migrate, not a scheduled removal: deprecated functions and parameters keep
working, and one is removed only when there is significant value in doing so
(for example, the API is actively harmful or blocks a necessary redesign).
Deprecated paths emit a `DeprecationWarning` where practical, and every removal
is recorded in [`CHANGELOG.md`](CHANGELOG.md:1).

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
