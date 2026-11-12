# Screen Overhaul: Plan, Decisions, Open Issues

Status: **implemented** (4.0.0). Phases 0-6 are in the tree; the two app ports that
live outside this repository (nanny, psistat) remain, see "Implementation notes".
This was the predecessor to the remaining items in
[`HELP-SCOPING-PLAN.md`](HELP-SCOPING-PLAN.md) because it changes the signatures those
items are written against.

One sentence: **content and pick/scroll state move out of `ConsoleWindow` into `Screen`,
`draw()` is deleted so there is exactly one drawing model, and the window becomes a
terminal/chrome/input engine.**

## Decisions

### D1. The Screen owns content

`add_header()`, `add_body()`, `add_header_line()`, `add_fancy_header()`,
`add_prompt_header()`, `add_prompt_lines()` become Screen API. The window keeps the
private implementation ([`_add()`](../console_window/window.py:1201),
[`_emit_header_spans()`](../console_window/window.py:1450),
[`_resolve_header_attr()`](../console_window/window.py:1429)) because the Screen delegates
to it, but the public writers are gone from the window.

State that moves with content: `texts`, `text_attrs`, `contexts`, `row_cnt`,
`rows_dropped`, `max_header_len` (head only for the last).

### D2. A Screen is mandatory; standalone window use is dropped

No screenless path is supported. Every app constructs at least one `Screen`. The
window keeps the content objects internally (the Screen delegates to it), but the
`add_*()` writers do not exist on a bare window at all. This retires the "psistat and
`demo-basic-pager` never build a Screen" caveat; both demos now build one.

### D3. Pick/scroll state is per screen (resolves O-B)

The state is a package-private class and `Screen` **inherits** it, so `screen.pick_pos`
*is* the state: no `screen.view.pick_pos` double naming, no forwarding properties on
`Screen`, and `win._view` can point at the current Screen itself.

```python
class _ViewState:                        # package-private; apps never name it
    __slots__ = ('pick_mode', 'pick_size', 'pick_pos', 'scroll_pos',
                 'free_scroll', 'pick_range', 'head', 'body', '_opts_seeded')

class Screen(_ViewState):
    ...
```

Fields: `pick_mode`, `pick_size`, `pick_pos`, `scroll_pos`, `free_scroll`, `pick_range`,
plus the two content namespaces (`head`, `body`, which are `_Content` objects holding
`texts`/`text_attrs`/`contexts`/`rows_dropped`/pads) and the one-shot `_opts_seeded`
latch. `last_pick_pos` disappears with D7. `prev_pos` is not view state: it is the row
the *parent* wants back, stored on the frame being pushed out
([screens.py:149](../console_window/screens.py:149)) and returned by
[`pop()`](../console_window/screens.py:188), so it stays in the stack's namespace.

`ConsoleWindow` keeps `self._view` plus assignable proxies, so every existing read/write of
`self.pick_pos`, `self.scroll_pos`, `self.pick_mode`, `self.free_scroll` inside
[`render()`](../console_window/window.py:1745), [`prompt()`](../console_window/window.py:2933),
[`fix_positions()`](../console_window/window.py:1771) and the navigation helpers is
untouched. App code targets the screen: nanny's `self.win.pick_pos = self.confirm_ctx.row`
becomes `self.pick_pos = ...` inside its Screen.

Three consequences to implement:

- **Adoption happens in `Screen.clear()`.** The window cannot find a Model A screen on its
  own, and `clear()` is the loop's first call, so `clear()` begins with
  `self.win._adopt_view(self)`. That is also why the D14 order is fixed: `clear()` first,
  or `render()` paints with the previous view.
- **A fallback view exists.** [`ScreenStack.__init__`](../console_window/screens.py:95)
  accepts `screen_objects=None`, so a stack of bare numbers has no Screen to hold state;
  `win._view` starts as a window-owned `_ViewState` for that case.
- **`opts` is a seed, not an owner.** Screens can be built before the window (D11), so the
  defaults are static and `_adopt_view()` applies `opts.pick_mode`, `opts.pick_size` and
  `opts.pick_range` once. That also closes a quiet global:
  [`set_pick_range()`](../console_window/window.py:1077) writes `opts.pick_range` today, so
  two screens cannot hold different ranges; it becomes a view field instead.

`free_scroll` is per screen and persists. Activation no longer resets it (today
[screens.py:157](../console_window/screens.py:157) does) and `clear()` leaves it alone: it
describes the user's viewport, not the pass.

### D4. Stack activation is a pointer swap

[`_activate()`](../console_window/screens.py:145) stops copying pick/scroll into a
`SimpleNamespace` and zeroing the window; it saves the outgoing screen's frame in
`self.stack` and points `win._view` at the incoming Screen (itself a `_ViewState`).
[`pop()`](../console_window/screens.py:164) restores by pointing back. The `curr`
namespace keeps only `num`, `name`, `prev_pos`.

### D5. `clear()` is content; surfaces are lifecycle

- `Screen.clear()` resets content (`texts`, `text_attrs`, `contexts`, `row_cnt`,
  `rows_dropped`, `max_header_len`) and transient view bookkeeping. The app calls it
  once per pass.
- `ConsoleWindow.clear()` stops calling [`self.scr.clear()`](../console_window/window.py:2705).
  The pads erase themselves: [`_paint_body()`](../console_window/window.py:1979) and
  [`_paint_head()`](../console_window/window.py:2000) both call `pad.erase()` every
  frame, and head + separator + body cover the full terminal, so a shrinking document
  is already handled.
- The surface wipe moves to the lifecycle paths only (`resize`, `suspend`, `resume`,
  `stop_curses`), behind `_clear_surface()`, which is a no-op while suspended.
- Consequence: the app loop never calls a private method. The earlier
  `screen.clear()` + `win._clear_surface()` split collapses into `screen.clear()`.

### D6. Content contract: `render()` never clears

`render()` paints what the content model holds and does nothing else. Content persists
until `Screen.clear()`. Rebuild-per-frame is the sanctioned app style; persistence
across frames is neither required nor forbidden. This is what makes
`clear(); add_*(); render()` a correct loop and a mid-loop `render()` harmless.

### D7. One drawing model: `add_*` only; `draw()` is deleted

Deletion set, all reachable only from tests or from each other:

| Symbol | Location | Note |
| --- | --- | --- |
| `draw()` | [window.py:1484](../console_window/window.py:1484) | the only absolute-placement writer |
| `ns.drawn` / `drawn` | [window.py:2717](../console_window/window.py:2717) | overlay span store |
| `_overlay_spans()` | [window.py:1563](../console_window/window.py:1563) | replays `drawn`; never fires without `draw()` |
| `highlight_picked()` | [window.py:1527](../console_window/window.py:1527) | no production caller |
| `_redraw_rows()`, `_draw_picked_rows()` | [window.py:1597](../console_window/window.py:1597) | only `highlight_picked()` calls them |
| `last_pick_pos` | [window.py:575](../console_window/window.py:575) | incremental-paint bookkeeping |
| `_pick_clear_pending` | [window.py:578](../console_window/window.py:578) | idem; paint is stateless |

Follow-on simplifications:

- `row_cnt` becomes `len(texts)` (a property), which removes the "row count is max-y"
  oddity and simplifies [`calc()`](../console_window/window.py:1192).
- [`set_pick_mode()`](../console_window/window.py:1070) loses its pending-repaint branch.
- The render debug line ([window.py:1761](../console_window/window.py:1761)) loses three fields.

Multi-attribute rows survive: `add_body(segment, attr, resume=True)` appends a segment
with its own attribute and computes the resume column from display width
([window.py:1223](../console_window/window.py:1223)). Column placement moves to the app,
composed with `textwidth.string_width`/`ljust`/`truncate` — not `len()`/`str.ljust`,
because `_add()` transliterates glyphs before the width math
([window.py:1215](../console_window/window.py:1215)).

The no-mixing rule in decision 11 of the help plan becomes moot and is replaced by
"add_* only".

### D8. Navigation and key routing stay on the window

`prompt()`, `_navigation_target()`, `_skip_to_pickable()`, `_finish_prompt_move()` keep
their logic and read the same proxy properties. `handled_keys`, `nav_keys`,
`taken_nav_keys`, `_record_demo_key()` are key-routing concerns and stay window-global.
`OptionSpinner.do_key(key, win)` is unchanged.

### D9. Help draw helpers take the Screen

`OptionSpinner.show_help_nav_keys(win)` and `show_help_body(win, ...)` become
`(screen)`; `BasicHelpScreen.draw_screen()` and `BasicTextScreen.draw_screen()` call
`self.add_header(...)`, `self.add_body(...)`, `self.set_pick_mode(False)` and
`self.draw_notes()`. This deletes the double window resolution at
[screens.py:271](../console_window/screens.py:271) and
[screens.py:342](../console_window/screens.py:342).

### D10. `head_line=False` has no side effects (decided; bug fix)

nanny is not hiding chrome it has no use for; it is working around a layout/paint
mismatch. `head_line=False` only zeroes the reserved row
([`hor_line_cnt`](../console_window/window.py:571)), so
[`calc()`](../console_window/window.py:1198) puts `body_base` at `head.view_cnt` and the
body starts immediately under the header. But
[`render_once()`](../console_window/window.py:1894) gates the paint on
`head.view_cnt < self.rows`, not on `hor_line_cnt`, so
[`_draw_separator_and_indicator()`](../console_window/window.py:1923) still runs and its
`hline(head.view_cnt, ...)` lands on the body's first row. Because that rule spans from
column 0, it also paints over the `>` that
[`_draw_pick_gutter()`](../console_window/window.py:1891) drew a few lines earlier.

The scroll indicator is collateral damage, not a separate concern: it is painted by the
same method on the same row ([window.py:1936](../console_window/window.py:1936)), and
[`calc_indicator()`](../console_window/geometry.py:35) returns `-1` when nothing
scrolls, so nanny's short body never had an indicator to suppress in the first place.
One call removed both.

Decided: no `scroll_indicator` option, and `head_line=False` is fixed to have no side
effects. Three implementation points:

1. Gate the paint on the flag, not on a row count: `render_once()` calls
   `_draw_separator_and_indicator()` only when
   `self.hor_line_cnt and self.head.view_cnt < self.rows`.
2. The indicator row is also the scroll-to-pick anchor.
   [`fix_positions()`](../console_window/window.py:1788) derives a row from
   `_scroll_indicator_row()` in scroll mode, so with no rule row
   [`_scroll_indicator_row()`](../console_window/window.py:1729) returns `self.body_base`
   and the anchor becomes the top of the viewport (`pick_pos == scroll_pos`). That is the
   one behavioral change, and it is the honest one: with no indicator there is no
   indicator position to derive a row from.
3. `status()` has nowhere to draw, so
   [`_draw_status_line()`](../console_window/window.py:1940) warns once per episode (the
   `_warn_rows_dropped()` pattern) instead of silently writing over body row 0. Drawing it
   on the last header row stays a possible later addition if an app asks for it.

`single_cell_scroll_indicator` remains the only indicator knob: an app that keeps the rule
cannot drop the indicator, which nothing needs today.

### D11. Construction seam

`Screen.win` becomes a property over `self.app.win`, resolved at call time. Screens may
be constructed before the `ConsoleWindow`; `ScreenStack` still requires the window
(it pushes HOME in `__init__` at [screens.py:105](../console_window/screens.py:105)),
so the stack is built after the window, as today.

### D12. Compatibility and version

- Read-only `win.body` / `win.head` properties survive (tests and
  [`nav_help_lines()`](../console_window/window.py:827) read them).
- Settable `win.pick_*` / `win.scroll_pos` / `win.free_scroll` proxies survive, because
  apps legitimately assign them mid-frame (nanny selects a confirm row that way).
- `win.add_*` writers are removed with no deprecation shim; every consumer is in this
  repo.
- The version notes in [`README.md`](../README.md:290) gate "upward compatible across 3.x",
  so this is a **4.0.0** with a "4.0.0 Breakages" section beside the 3.0.0 one.

### D13. App ports

| App | Work |
| --- | --- |
| `demos/demo-screen-pager.py`, `demo-spinner-pager.py`, `demo-buffet.py` | mechanical: drop `win.` prefixes, `win` onto `self` |
| `demos/demo-basic-pager.py` | two hand-written functions become Screen subclasses; `help_mode` becomes a screen or a draw branch |
| nanny (`/tmp/nanny.py`, outside this repo) | delete the `_draw_separator_and_indicator` monkey-patch (D10 ships first); `draw(y, x, ...)` lines become composed `add_body()` segments; `_set_body_context()` dies (`context=` exists); `body.drawn[row] = []` resets die; `_draw_kill_confirm()` becomes an ordinary row in the loop; state file read on mtime change, not per frame; `max_rows` left at the default so a rebuild cannot warn every frame |
| psistat (outside this repo) | already `add_body`-shaped; wrap in one Screen (`self.add_body`, `self.clear()` at the top of the pass); help-as-mode stays or becomes a second screen |

### D14. The loop is four explicit calls (decided)

```python
while True:
    screen.clear()          # content reset for the new pass
    screen.draw_screen()    # add_header()/add_body() only
    win.render()            # pads repaint, doupdate() diffs
    key = win.prompt(seconds=0.5)
```

No `render_pass()`, no `run()`, no library-owned pass. In Model B the first three act on
the screen the stack makes current. The four calls are permanent public API: if help-plan
O8 later adds a `dispatch()` or `run()` seam it may only wrap them, never replace or
rename them. That is what lets this overhaul land before O8 is decided.

## Phases

0. **Nothing to settle** — the loop is D14 and the state shape is D3. D10 ships
   separately and first: it is a bug fix in 3.x shape, and its only visible consumer is
   nanny, which then deletes three lines. *(done)*
1. **Content to Screen** — introduce `Content` on `Screen`, keep `win.body`/`win.head` as
   read-only proxies, route `add_*` through the Screen, leave `draw()` in place for now.
   *(done; done together with step 4, since `draw()`'s span store had no other home)*
2. **View state to Screen** — `_ViewState` as a `Screen` base, `win._view` plus the
   fallback instance, `_adopt_view()` in `Screen.clear()`, proxy properties, pointer-swap
   activation, and dropping the `free_scroll` reset at
   [screens.py:157](../console_window/screens.py:157). *(done)*
3. **Clear split** — `Screen.clear()`, drop `scr.clear()` from `ConsoleWindow.clear()`,
   move the wipe to lifecycle paths, verify no stale-cell case on shrink/resize. *(done:
   `_clear_surface()` on resume/resize)*
4. **Delete `draw()` and the incremental-paint layer** — the D7 table, in one commit,
   with its tests. *(done)*
5. **Call sites** — spinner help helpers, `BasicHelpScreen`, `BasicTextScreen`, the
   `head_line` paint guard, `__init__` exports. *(done)*
6. **Tests and docs** — retarget the ~130 window-content references; update README's
   "shape of every app", worked example and version section; amend help-plan decision 11.
   *(done; new coverage in `tests/test_screen_state.py`)*
7. **App ports** — the D13 table, each app on its own commit. *(in-repo demos done;
   nanny and psistat live outside this repository — see Implementation notes)*

## Open issues: answers

O-A, O-B, O-C, O-D and O-H were settled in conversation before implementation. The last
three were answered while implementing:

| # | Answer |
| --- | --- |
| O-E | **No.** Per-screen state is the whole point: `BasicHelpScreen` disabling pick must not change the parent. `ESC` now restores the parent's mode and position, which is the behavior the demo wants and `tests/test_screen_state.py` pins. |
| O-F | **Yes.** `win.rows_dropped` stays, as a property summing the active view's `head` and `body` counters; the warning text points at `max_rows` as before. |
| O-G | **They move to the Screen.** They write content, so `Screen.add_prompt_header()` / `Screen.add_prompt_lines()` are the public spelling and the window keeps private `_add_prompt_*` implementations. One supported content-writer type remains. |

## Relationship to HELP-SCOPING-PLAN

Yes, this goes first, and it moves that document rather than competing with it:

- **Amends decision 11.** "Content drawing belongs to `Screen`: `draw()`, `add_header()`,
  ..." loses `draw()`, and the no-mixing paragraph collapses to "add_* only".
- **Closes part of O6.** Its last bullet ("a draw pass that mixes `draw()` with
  `add_header()`/`add_body()` trips the no-mixing policy") becomes untestable and is
  deleted; the Model A / Model B bullets stay and get the D14 loop.
- **Touches every remaining item's call sites.** O3 (`self.num` + `screen_filter=`),
  O4 (`options_for_screen()`, `show_help_body()` wording) and O9 (`get_spinner()`
  injection) all rewrite `show_help_body()`'s signature or `BasicHelpScreen.draw_screen()`.
  Doing them first means editing those signatures twice.
- **O8 no longer constrains the order.** D14 fixes the loop as four permanent public
  calls, so O8 can add a `dispatch()`/`run()` wrapper later without touching any app a
  second time. It stays open, and it stays additive.
- **O3, O4, O5, O9 remain open and unsolved by this plan.** O5 (incremental search) is
  untouched; O3/O4/O9 are help/spinner concerns whose signatures this plan changes.
- **New doc inconsistency to resolve in the help plan, not here:** decision 11 says a
  Model A app has no help, but `demo-basic-pager.py` is Model A with hand-written help.
  Either Model A gains hand-written help or that demo promotes to Model B.

## Verification to add to the gate

- Every sample app's loop is exactly the four calls in D14, and none of them is renamed.
- Model A loop with a bare `Screen`, no stack and no spinner, exits normally.
- Model B help screen draws only current-screen options plus spinners.
- ESC on the help screen pops to the parent with the parent's pick mode and scroll
  position intact (the D3/D4 payoff).
- Switching A → B → A restores A's `pick_pos`/`scroll_pos` without any copy in the app.
- `render()` twice in a row with no content change produces no terminal traffic
  (`doupdate()` diff), and a mid-loop `render()` does not erase content.
- A shrinking document leaves no stale row anywhere on the screen.
- `head_line=False` paints no rule, no indicator and no status text onto the body's first
  row, with pick mode on and off; `status()` warns once instead.
- In scroll mode with `head_line=False`, `pick_pos` tracks the top of the viewport.
- `add_body(seg, attr, resume=True)` keeps the first segment's `Context`.
- Tests retargeted: `test_viewport_pad.py`, `test_overflow.py`, `test_interactive.py`,
  `test_widechars.py`, `test_glyph_rendering.py` (delete `draw()` cases),
  `test_render_retry.py` (drop `last_pick_pos`), `test_sample_app.py` (`draw_screen()`
  after `clear()`).

## Implementation notes

Deviations from the text above, all deliberate:

- **The pads live on the content object, not on the window.** Keeping `pad`/`pad_rows`/
  `pad_cols` beside `texts` is what lets `win.body.pad` (read by several tests) keep
  working; `_adopt_view()` sizes a newly adopted view's pads once, so a screen that has
  never rendered cannot hit `redrawwin()` on `None`. The pads are still viewport-sized
  buffers that are erased and repainted every frame, so sharing them across screens was
  never needed.
- **`status()` carries the no-row warning, not `_draw_status_line()`.** The paint is
  gated on `_separator_available()`, so `_draw_status_line()` is unreachable without a
  row; the caller-visible warning therefore belongs to `status()`, once per episode.
- **`Screen.draw_notes()` lost its optional `win` parameter.** It writes through
  `self.add_body()`; `BasicHelpScreen.draw_screen()` is the only caller.
- **`tests/support.py`** provides `screen_of(win)`, a test-only helper that creates and
  adopts a Screen for tests that only need to fill content.
- **`tests/test_sample_app.py` was retargeted, not deleted.** The worked example moved
  from the repo-level `SampleApp.py` to [`demos/demo-buffet.py`](../demos/demo-buffet.py);
  the module is now loaded from that path with `importlib`, and each test drives a screen
  through the four-call loop (`screen.clear(); screen.draw_screen()`), so `win.body` and
  `win.head` are the screen that was just drawn. The history-screen test follows the new
  shape (the screen writes its own content instead of delegating to a nested
  `BasicTextScreen`). All 20 pass; the gate is 657 passed, 0 failed.
- **External app ports remain.** nanny (`/tmp/nanny.py` in this analysis) and psistat
  live outside this repository. Their required changes are exactly the D13 rows: drop
  the `_draw_separator_and_indicator` monkey-patch (D10 makes it unnecessary), replace
  `draw(y, x, ...)` with composed `add_body()` segments (column padding via
  `textwidth`), drop `_set_body_context()` in favour of `add_body(..., context=ctx)`,
  drop the `body.drawn[row] = []` resets, and start each pass with `screen.clear()`.
