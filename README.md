# console-window

`console-window` is a stdlib-only curses framework, not a widget toolkit: a keyboard-driven, full-screen **pager + selection engine + screen-stack router** built on raw curses **pads**. The ideas that shape it:

- a separate **head pad / body pad** split, so the header band stays put while the body scrolls;
- an independent **scroll position** and **pick position**, reconciled each frame;
- **`Context` metadata per row**, with an `abut` rule that keeps N transient detail rows beside the picked row;
- **`OptionSpinner` bindings** whose narrower scopes subtract themselves from wider ones.

## Installation & License

* `pip install console-window` — Python 3.10 or newer, no runtime dependencies.
* License: MIT

## Strengths

1. **Zero runtime dependencies** — standard-library `curses` only.
2. **Cheap frames** — pad refreshes accumulate into one update per frame, and a redraw path recovers from terminal corruption.
3. **Two-axis model** — scroll and pick are separate, which is what keeps a selection visible with context rows around it.
4. **Rows carry their own metadata** — transient detail stays attached to the row that produced it.
5. **No dead cursor stops** — decorative rows are skipped by navigation yet still reachable by scrolling.
6. **Real key routing** — scoped bindings subtract themselves, and navigation collisions are refused.
7. **Resize resilience** — rendering retries during a resize and the window enforces a minimum size instead of crashing.
8. **Testable core** — layout math is pure, and a headless backend renders without a TTY.

## Features, in demo order

Each feature below is introduced or emphasized by one demo. From a checkout, `./runner` opens the demo menu and `demos/run-demo <name>` runs one directly.

- **Pager and drawing loop** — a `Screen` owns its rows and its position; the loop is `clear()`, `draw_screen()`, `render()`, `prompt()`. Pads are viewport-sized blit buffers, so memory and per-frame clear cost stay flat however many rows an app adds. See [demo-a-basic.py](demos/demo-a-basic.py).
- **Screens and the stack** — `ScreenStack` pushes and pops by name, number or object. Each screen keeps its own content and pick/scroll position, and activation is a pointer swap, so returning restores the user's place with no copying in the app. See [demo-b-stack.py](demos/demo-b-stack.py).
- **Options and scoped help** — `OptionSpinner` cycles values or prompts on one keypress, applies options per screen, and builds the help body under a `Keys for '<screen>':` heading. A narrower binding subtracts its screen from a wider one, and collisions with navigation keys are rejected. See [demo-c-options.py](demos/demo-c-options.py).
- **Pick mode, context and abut** — scroll and pick are separate. `Context` marks a row decorative or transient; such rows are skipped by navigation but still reachable by scrolling, and transient rows abut their parent. `pick_range` narrows the pickable columns. See [demo-d-pick.py](demos/demo-d-pick.py).
- **Filter as you type** — `IncrementalSearchBar` holds the pattern and caret; the app owns the matching and the row rebuild, and passthrough routing feeds it the keys while it is active. See [demo-e-search.py](demos/demo-e-search.py).
- **In-place prompts** — `PromptLine` holds the text, buffer, hint and callbacks; the window adds the lifecycle that keeps key routing and passthrough consistent, and can draw the prompt as a header row or as transient body rows. See [demo-f-prompts.py](demos/demo-f-prompts.py).
- **Dialogs and inline confirmation** — `answer()` and `alert()` block and manage their own screen takeover. `InlineConfirmation` matches exactly, then case-insensitively, then by abbreviation, with an auto-computed minimum abbreviation length. See [demo-g-dialogs.py](demos/demo-g-dialogs.py).
- **Status and flash** — `status()` paints a level-styled message on the separator row beside the scroll indicator without taking over the display; `flash()` shows a short modal box. See [demo-h-messages.py](demos/demo-h-messages.py).
- **Header modes** — header rows take `Off`, `Underline` or `Reverse`. A markup string marks a label, `[keys]` and `/searches`; a `HeaderLine` keeps every character literal. See [demo-i-headers.py](demos/demo-i-headers.py).
- **Themes and appearance** — themes are written for the 256-color palette and installed at the nearest entry the terminal reports, with a contrast guard and attribute fallbacks below 8 colors. `Theme.create_picker_screen()` builds the picker; `mono` is an ordinary theme, and a non-empty `NO_COLOR` selects it. See [demo-j-themes.py](demos/demo-j-themes.py).
- **Glyphs and ASCII** — every decorative symbol lives in one registry with a Unicode and an ASCII spelling. Text is transliterated before it is measured, so widths and attributes stay correct when the terminal cannot draw the non-ASCII form; the `emoji` family is entirely two cells. The `cli` helpers add `--ascii`, `--glyphs` and `--theme`, and the help page's Font Check section shows the whole catalog. See [demo-k-glyphs.py](demos/demo-k-glyphs.py).
- **Read-only screens** — `BasicTextScreen` shows preformatted lines under optional headers, with no pick mode and no spinner, and `extra_help_paragraphs()` adds app prose to the help page's `Notes:` block. See [demo-l-text-screens.py](demos/demo-l-text-screens.py).
- **App-owned navigation keys** — `ConsoleWindowOpts(taken_nav_keys=[...])` withdraws keys from navigation for that window only, and the generated help drops them from its `action: keys` chunks. See [demo-m-own-keys.py](demos/demo-m-own-keys.py).
- **Suspend and resume** — `suspend_curses()` calls `endwin()` so the terminal can run another program; `resume_curses()` reattaches the screen, and pads, content and pick state survive. `singleton=False` gives each window its own screen. See [demo-n-suspend.py](demos/demo-n-suspend.py).
- **Large bodies and limits** — row counts need no configuration; `max_rows` is the one content ceiling, and the first discarded row of a fill episode warns once and every one is counted in `rows_dropped`. See [demo-o-large-bodies.py](demos/demo-o-large-bodies.py).
- **Widths and key debugging** — `textwidth` measures display cells, including wide CJK/emoji and zero-width combining marks, and demo mode shows each key as it arrives. See [demo-p-key-debug.py](demos/demo-p-key-debug.py).


## Comparable and Competing Projects

`console-window` is a niche tool: for most projects one of the following is the better choice. Reach for it when you want a dependency-free, keyboard-driven list/detail viewer and are content to build your own widgets.

- **urwid** — the closest peer for full-screen apps: lists, trees, scrolling and events. It gives you a canvas and widget tree with an event loop (and a `wcwidth` dependency); `console-window` gives you rows and a selection model.
- **Textual** — same audience, far more machinery: a DOM with CSS, asyncio, mouse, animation and a web target, at the cost of a dependency tree.
- **prompt_toolkit** — overlaps on full-screen editing, completion and dialogs, but is input-centric with few layout widgets.
- **npyscreen** — overlaps on stdlib-curses admin screens, but is form-and-field driven where `console-window` is pager-and-pick driven.
- **py_cui** — overlaps on stdlib-curses dashboards, but arranges widgets in a grid rather than rows in a viewport.
- **asciimatics** — overlaps on curses screens with widgets, and adds an animation engine plus `pyfiglet`/`pillow` dependencies.
- **blessed** — overlaps only at the bottom: terminal control primitives, with no widgets and no navigation model.
- **Rich** — overlaps on styled terminal text, but is an output library, not a TUI toolkit.

## Projects Using console-window

- [efibootdude](https://github.com/joedefen/efibootdude) — a thin `efibootmgr` wrapper that varies its top key line with the current row.
- [dwipe](https://github.com/joedefen/dwipe) — disk cleaner with parallel jobs and stamped partitions.
- [pmemstat](https://github.com/joedefen/pmemstat) — memory monitor with rollups and zRAM hooks.
- [memfo](https://github.com/joedefen/memfo) — `/proc/meminfo` viewer with history.
- [vappman](https://github.com/joedefen/vappman) — shell over [AppMan](https://github.com/ivan-hc/AppMan) for AppImage life-cycle work.
