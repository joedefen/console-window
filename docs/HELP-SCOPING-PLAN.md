# Help Screen: Decisions and Open Items

Status as of 2026-11-12.  The Screen overhaul is implemented and assumed here;
[`SCREEN-OVERHAUL-PLAN.md`](SCREEN-OVERHAUL-PLAN.md) records it.  The decisions
below are implemented too; only the modal-layer item remains open.

## Assumed (not revisited)

- **A `Screen` is mandatory.**  The content writers (`add_header()`,
  `add_body()`, `add_fancy_header()`, `add_header_line()`,
  `add_prompt_header()`, `add_prompt_lines()`) exist only on `Screen`, and
  `draw()` is gone.  There is one drawing model: flow-ordered `add_*()` rows.
- **`ConsoleWindow` is the terminal, chrome and input engine** (`clear()`,
  `render()`, `prompt()`, `status()`, `flash()`, dialogs).  It knows nothing
  about screens, stacks or spinners.
- **The pieces are independent.**  `Screen` is the only mandatory piece;
  `ScreenStack`, `OptionSpinner` and `BasicHelpScreen` are each optional.
  `OptionSpinner.stack` is optional, and a spinner without a stack has no screen
  scoping: every key is live on every screen.  `BasicHelpScreen` draws the
  spinner's body only when `get_spinner()` finds one; otherwise it shows just
  its own notes.
- **`OptionSpinner.add_key()` is the only registration path**; the 2.x `add()`
  tombstone is gone.
- **The loop is four calls**: `screen.clear()`, `screen.draw_screen()`,
  `win.render()`, `win.prompt()`.  `clear()` adopts the screen, so it comes
  first.

## Decisions (implemented)

### 1. The help body lists what is live on the help screen

An option is drawn when its `effective_scope` contains the help screen's number,
so "shown" and "works" are the same set; before this change every option was
dumped and dead keys were advertised.  An option that must work on the help
screen names it in
`scope=` (as the buffet demo does).  There is no implicit auto-scoping, so the
spinner never needs to know which screens are help screens.  With no stack there
are no scopes to filter by, and the body lists everything -- which is exactly
what a stackless spinner has.  Rejected: listing the parent screen's keys, or
letting help act on the parent; both advertise keys that do not work where they
are shown.

### 2. `quit` and `escape` are spinner-supplied actions

An app that uses the spinner should not have to spell these two bindings again.
The spinner registers `quit` (`q`, `^C`) and `escape` (`ESC`, `^J`, `ENTER`)
before the app registers anything and reserves their keys: an implicit
(scope-less) later `add_key()` on one of them raises with a message naming
`quit_keys=` / `escape_keys=`, while an explicit `scope=` is a deliberate
per-screen override (ESC clearing a filter on MAIN is the demo case).  They are
shown once in the `NavKeys:` block, not in the body.  `Screen` supplies
`escape_ACTION()` (pop; no-op at home) and `quit_ACTION()` (`SystemExit`; the
atexit hook already tears curses down), both ordinary overridable methods.  A
screen reaches the stack through the injected handle described in decision 4.
The defaults are reached through the stack's action dispatch, so a stackless app
gets the bindings but supplies its own handling.

### 3. The loop stays explicit and documented

An app can build the pieces correctly and still never call `draw_screen()` or
the action dispatcher; nothing complains.  That is accepted rather than fixed:
the four calls stay visible in every app instead of being hidden behind a
`dispatch()` or `run()` seam.  Less magic, and the samples already show the
shape.

### 4. The spinner is injected, not discovered

`OptionSpinner.__init__` sets `stack.spinner = self` when it is given a stack,
and constructing a second spinner on the same stack raises.  A screen reaches
the stack through the stack's own injection: at construction it assigns
`obj.num` and `obj.stack` to the screens it owns (the number is decision 6's
job), so [`Screen.get_spinner()`](../console_window/screens.py:151) becomes
`self.stack.spinner`, or `None` when the screen has no stack.  The
`dir()`/`getattr` scan and its cache went away.  The scan only existed because a
screen could be drawn before the app had built its spinner; with the
construction order fixed and documented -- screens, window, stack, spinner --
injection has no chicken-and-egg gap.

### 5. Help-screen collisions need no special rule

The help screen is just another number in `scope=`.  The rule, already
implemented, is last registration wins within an overlapping scope: a later
option subtracts the overlap from the earlier one
([`_subtract_scope()`](../console_window/spinner.py:209)), so within a screen
the newest registration owns the key.  One key may carry different options on
different screens -- a MAIN-only key and a HELP-only key with the same code are
not a conflict, and dispatch resolves by the current screen.  Without a stack
there is one global namespace, so a duplicate key is an error there and only
there.  The case that used to resolve badly, a spinner silently unbinding ESC/^C
on the help screen, is gone because decision 2 reserves those keys.  Consequence:
the old key-conflict guard could not fire, because subtraction always removes
the overlap first; it is deleted rather than kept as a rule that never fires.

### 6. The help body asks the spinner what applies

- **The number.**  `Screen.num = None` on the class, documented "assigned by
  the stack"; `ScreenStack.__init__` sets `obj.num = num` for every entry in
  `screen_objects` (sharing the loop that injects `obj.stack`, decision 4).
  [`BasicHelpScreen.draw_screen()`](../console_window/screens.py:403) passes
  itself to `show_help_body()`, so that method reads `screen.num` directly and
  its `screen_filter=` argument is gone.
- **One definition.**  `OptionSpinner.options_for_screen(screen)` is the body-
  options lookup: all options (minus the built-in `quit`/`escape`, decision 2)
  when the spinner has no stack or the screen has no number, otherwise those
  whose `effective_scope` contains `screen.num`.  Both `show_help_body()` and an
  app drawing its own help call it, so "applies here" has one definition.
  `_filter_screens()` and `_skipped_by_filter()` are deleted, and the built-in
  options are marked so the method never returns them.
- **The empty body.**  When nothing applies, omit the "Type keys to alter
  choice:" heading and draw no placeholder; the `NavKeys:` block and the app's
  notes remain.  A heading with nothing under it is worse than silence.
- `ScreenStack.get_parent_screen()` is not needed for any of this; do not add
  it.

## Reversed or dropped

- **`OptionSpinner` requires the full stack model** (was decision 10).
  Reversed: `stack=None` is supported, `ScreenStack(..., screen_objects=None)`
  is supported, and the stackless fallbacks and guards stay.
- **Two app models** (was decision 11).  Reversed: there is no "Model A" /
  "Model B" taxonomy; the composition levels under "Assumed" replace it.  The
  demos still cover a bare `Screen`, a stack-only pager and a spinner-plus-help
  pager.
- **`is_help` and help-screen auto-scoping** (were decisions 6 and 9).  Moot:
  with explicit `scope=`, the spinner never has to detect help screens, so the
  flag, the ordering caveat and the subtraction special case all go.

## Open item

O1 and O3 are decisions 5 and 6; the earlier items are settled or no longer
apply.  Only O5 remains.

### O5. Modal layers (deferred)

`IncrementalSearchBar` consumes printable keys inside `handle_key()` and
outranks the spinner while it is active.  It is a layer, not a screen, so it has
no `effective_scope`, and help is unreachable underneath it.  Deferred: list its
keys in a separate "while typing" block, or have it take its keys from the
current screen's spinner set so the two cannot diverge.
