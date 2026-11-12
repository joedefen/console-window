# Help Screen: Decisions and Open Items

Status as of 2026-11-11. Decisions are cumulative: later entries build on
earlier ones, and nothing here is implemented unless it says so.

## Decisions

### 1. Navigation map is two compact lines (implemented)

```
NavKeys:    pos: H/M/L    half: ^u/^d    page: ^b/^f/PPAGE/NPAGE
 up: k/UP  down: j/DOWN  first: 0/HOME   last: $/END
```

- [`NAV_HELP_LINES`](../console_window/window.py:91) is a per-line tuple of
  `(action, keys, gap)` rows. One row per action, not per key, so the verb is
  stored once and every key that performs it hangs off it.
- The gap lives on the row, not on the line, so `last:` can be nudged into the
  same column as `page:`. A uniform per-line gap cannot do that: the rows carry
  three and four chunks respectively.
- Control keys use caret notation (`^u`, `^d`, `^b`, `^f`), the same spelling
  `_raw_key_label()` uses for unexpected control keys. It keeps the map well
  inside 80 columns.
- A key the application took via `taken_nav_keys` disappears from its chunk; a
  row whose keys are all taken disappears entirely. The label belongs to the
  block: if the top row is entirely taken, the bottom row prints with the
  `NavKeys:` prefix.
- `NAV_KEY_LINES`, `get_nav_key_lines()` and `get_nav_keys_blurb()` keep their
  tuple-of-lines shape.

### 2. The help body shows the keys that work on the help screen (decided: D)

Rule: the help body lists an option when its key is live while the help screen
is current. That means:

- options whose `effective_scope` contains the help screen's number, plus
- every `cycle` and `prompt` option ("spinner"), which is made available on
  help screens automatically even when registered with a narrower scope, and
  whose keys therefore work there.

Rationale: "shown" and "works" become the same set by construction.

- Dispatch is already strictly per-screen: [`do_key()`](../console_window/spinner.py:325)
  resolves `key_scopes[(key, stack.curr.num)]`, and
  [`perform_actions()`](../console_window/screens.py:219) skips actions whose
  `effective_scope` lacks the current screen. The help screen was the only
  place ignoring that: [`BasicHelpScreen.draw_screen()`](../console_window/screens.py:267)
  calls `show_help_body(win)` with no filter, so every option is dumped.
- The "one key, several purposes" mess is cross-screen, not intra-screen:
  [`_reject_key_conflicts()`](../console_window/spinner.py:153) guarantees one
  meaning per key per screen, and [`_subtract_scope()`](../console_window/spinner.py:145)
  narrows earlier registrations (ESC is "back" on HELP and "clear filter" on
  MAIN). Filtering removes the contradictions without new data.
- Because spinners are auto-scoped to help, the same key may carry different
  cycle/prompt options on different screens; help resolves it by screen.

### 3. Alternatives considered and rejected

- **Documentation-only parent section**: lists the *parent* screen's keys on
  the help screen. Rejected: those keys are deliberately not live there
  (`?`, `/`, SPACE, `a`, `l`, `N`), so the help would advertise dead keys and
  add rows to a screen we are trying to shrink.
- **Parent delegation**: show the parent's map and make its keys act on the
  parent while help is focused. Rejected: the help screen would become a
  remote control for a hidden screen, actions would mutate state the user
  cannot see, and `perform_actions()` would need a second resolution rule.

### 4. `OptionSpinner.add()` removed (implemented)

- It was a `NotImplementedError` tombstone since 2.0; the method and its
  regression test are now deleted. `add_key()` is the only registration path.
- Historical 2.x changelog entries and earlier audit notes remain as written;
  the removal is recorded in the 3.0.0 changelog section.

### 5. `add_key()` is documented in code (implemented)

- The method carries a full docstring covering every argument and the implicit
  rules: genre inference, key inference from `descr[0]`, scope resolution and
  subtraction, value normalization at registration, and the conflict errors.

### 6. A help screen is a screen with `is_help = True` (decided)

Detection is a class flag, not a class test:

```python
class Screen:
    is_help = False  # True = help screen: cycle/prompt keys auto-scope here


class BasicHelpScreen(Screen):
    is_help = True
```

and `OptionSpinner` asks `getattr(screen_obj, 'is_help', False)` of each screen
object it already has in `stack.screen_objects`, inside `add_key()`.

- Deriving from `BasicHelpScreen` stays the documented default path: the flag is
  inherited, so "a help screen is a `BasicHelpScreen`" still reads true for the
  ordinary case. A hand-written help screen that calls
  [`show_help_body()`](../console_window/spinner.py:326) opts in with one line;
  a `BasicHelpScreen` subclass that overrides `draw_screen()` and never shows
  the body opts out with one line (`is_help = False`).
- Rejected: `isinstance(screen_obj, BasicHelpScreen)`. It needs a function-local
  import around the runtime edge [`screens.py`](../console_window/screens.py:11)
  -> `spinner` ([`spinner.py`](../console_window/spinner.py:12) imports
  `ScreenStack` only under `TYPE_CHECKING`), and it tests inheritance where the
  real question is "does this screen render the option list?". A custom help
  screen would be missed and a body-less subclass would be caught, both wrongly.
- Rejected: an `OptionSpinner(..., help_screens=(...))` argument as the primary
  rule: it duplicates the screen number, and every new help screen has to be
  added in two places. It stays available as an escape hatch for stacks built
  without screen objects (see the caveat below), not as the rule.
- Consistent with the capability flags already on [`Screen`](../console_window/screens.py:34)
  (`come_from_whitelist`, `is_terminal`, `cannot_stack_me`) and on
  [`BasicHelpScreen.show_display_notes`](../console_window/screens.py:265): the
  library already answers "what kind of screen is this?" with class attributes.
- Testable without curses: the spinner tests' fake screen needs only
  `is_help = True`.

**Caveat (ordering).** Detection runs inside `add_key()`, exactly like the action
detection in [`_resolve_scope()`](../console_window/spinner.py:119), so
`ScreenStack.screen_objects` must be complete before the first registration.
A stack built as `ScreenStack(win, obj, names)` without the fourth argument has
`{}` there: action detection falls back to `all_screens` (permissive), but help
detection finds no help screen at all, so auto-scoping is silently off. The
sample app satisfies the ordering (screens are built, then the stack, then
`add_key()`); the requirement must be documented, and `help_screens=` is the
escape hatch if an app cannot meet it.

### 7. `quit` and `escape` are built-in options (decided)

`OptionSpinner.__init__` registers two actions before the application registers
anything:

| attr | genre | default keys | shown in |
| --- | --- | --- | --- |
| `quit` | action | `q`, `^C` | third `NavKeys:` line |
| `escape` | action | `ESC`, `^J`, `ENTER` | third `NavKeys:` line |

- Keys are overridden in the constructor (`quit_keys=`, `escape_keys=`), so an
  app never spells these two bindings again.
- They are registered first and their keys are **reserved**: a later `add_key()`
  whose scope overlaps a reserved key raises from
  [`_subtract_scope()`](../console_window/spinner.py:145) with a message naming
  the constructor argument, instead of quietly taking the screen. This is the
  "make it an error to force fixing" option, and it dissolves the one bad case
  of the collision policy: ESC and ^C can no longer be displaced on the help
  screen.
- They are shown once, in a third line of the NavKeys block, and skipped by
  [`show_help_body()`](../console_window/spinner.py:326). The mark that hides
  them from the body also keeps them out of the `align` maximum in
  [`_register()`](../console_window/spinner.py:116), or two long built-in
  descriptions would skew the body's description column.
- [`show_help_nav_keys()`](../console_window/spinner.py:320) becomes an instance
  method so it can append the row from its own built-ins; the window keeps
  knowing nothing about the spinner.
- Layout: `quit: q/^C   back: ESC/^J/ENTER` (29 columns). Spelling the three
  back codes honestly is deliberate: the sample app binds `[27, 10, KEY_ENTER]`
  and describes it as "ESC,ENTER".
- Sample-app consequences: delete the two registrations at
  [`SampleApp.py:121`](../SampleApp.py:121), delete `DemoScreen.escape_ACTION`
  (the default now does it), and the ENTER branch in `handle_key()`
  ([`SampleApp.py:240`](../SampleApp.py:240)) becomes redundant once ENTER is a
  bound back key. `quit_ACTION` stays as an override.
- [`test_every_action_option_has_a_handler_on_some_screen`](../tests/test_sample_app.py:89)
  starts passing by inheritance, so it must be narrowed to non-builtin actions.

### 8. The library supplies the default handlers (decided)

- `Screen.escape_ACTION()` pops the stack and is a no-op at home
  ([`pop()`](../console_window/screens.py:164) already returns `None` with an
  empty stack).
- `Screen.quit_ACTION()` exits with `SystemExit`. Curses teardown is already
  covered by [`_register_atexit()`](../console_window/window.py:310), so the
  library does not call `stop_curses()` first.
- Both are ordinary overridable methods, so an app keeps a farewell flash by
  overriding `quit_ACTION`; nothing about dispatch changes, because
  [`perform_actions()`](../console_window/screens.py:219) finds the method by
  `getattr` on the current screen object and inheritance is enough.
- To let a `Screen` reach the stack without the `app.stack` convention, the
  stack injects itself into each screen it activates (`screen.stack = self`).
- Public surface grows by two documented methods on `Screen`.

### 9. Help-screen collisions are settled by subtraction (decided)

As read from "unless a help screen, scoping to the help screen is simply
subtracted if given as a scope":

- Adding the help screens to a cycle/prompt option's `effective_scope` reuses
  [`_subtract_scope()`](../console_window/spinner.py:145), which is already last
  writer wins and already pops the earlier option's `key_scopes` entries. The
  table [`do_key()`](../console_window/spinner.py:379) reads and the
  `effective_scope` a help filter would read are therefore corrected in the same
  step: shown and works cannot drift.
- The case that resolved badly — a spinner silently un-binding ESC/^C on the
  help screen — is gone because those keys are reserved (decision 7). What is
  left is spinner against spinner, where "the newest registration owns help" is
  the same rule the scope machinery already applies everywhere else.
- An option that names a help screen in `scope=` keeps it: that is a claim like
  any other, and only a later claim on the same key and screen subtracts it.
- `ns.scope` (as declared) is kept beside `ns.effective_scope`, so the rule can
  be tightened later to "explicit beats implicit" without new state if an app
  ever needs it.

### 10. `OptionSpinner` requires the full stack model (decided)

`OptionSpinner` requires a stack, and a stack requires its screen objects. There
is no stackless spinner and no screenless stack.

- `OptionSpinner.__init__(stack, ...)`: `stack` is required; `None` raises
  `ValueError` naming `ScreenStack(win, obj, names, screens)` rather than a
  `TypeError`, so the message teaches the construction.
- `ScreenStack` requires screen objects too. `screen_objects={}` is the same
  incoherence one level down: [`perform_actions()`](../console_window/screens.py:219)
  returns 0 and no `_ACTION` ever fires; [`get_curr_obj()`](../console_window/screens.py:159)
  and decision 8's `screen.stack` injection have nothing to attach to.
- Deletions that follow: `OptionSpinner.key_to_option`, the `if not self.stack:`
  branch in [`_store_key_scope()`](../console_window/spinner.py:162), the global
  fallback in [`do_key()`](../console_window/spinner.py:387), and the three
  defensive guards — `if ns.genre == 'action' and self.stack and
  self.stack.screen_objects` in [`_resolve_scope()`](../console_window/spinner.py:123),
  `hasattr(option_ns, 'effective_scope')` in
  [`perform_actions()`](../console_window/screens.py:234), and the same pattern in
  [`_skipped_by_filter()`](../console_window/spinner.py:347).
- `_resolve_scope()` always returns a real set of screen numbers, so decision 9's
  subtraction always has a domain and decision 6's `is_help` detection always has
  objects to inspect. O3's "no stack, show everything" fallback stops existing.
- `scope=` can be validated against the screen range at registration, so
  `scope={7}` in a four-screen app becomes an error instead of an option that can
  never fire.
- `ConsoleWindow` is **not** the enforcement point and should not become one: it
  never sees the stack or the spinner. Its only coupling is
  [`set_handled_keys()`](../console_window/window.py:620) duck-typing an object
  with a `.keys` set, which is how `prompt()` learns which keys to return. The
  paradigm is enforced where the knowledge lives: the spinner constructor and the
  stack constructor.
- What this does *not* enforce: that the app loop ever calls the dispatcher. See
  O8.
- Test cost: 17 stackless constructions, nine of them in
  [`tests/test_spinner.py`](../tests/test_spinner.py:24) beside an existing
  `make_stack()`, plus [`tests/test_screens.py:54`](../tests/test_screens.py:54)
  (a `BasicHelpScreen` with no stack) and three in
  [`tests/test_taken_nav_keys.py`](../tests/test_taken_nav_keys.py:157).
- This decision does not forbid a bare `Screen` used without a stack or spinner
  (Model A in decision 11); it forbids an `OptionSpinner` without a stack. Read
  "Screen paradigm is the only model" as "Screen is the only content/drawing
  model", not "every app must use the stack and spinner".

### 11. Two app models and one Screen-owned drawing surface (decided)

There are exactly two sanctioned app shapes. Both draw through `Screen`; they
differ in how much of the stack/spinner/help machinery they take.

| Model | Use when | Composition | Help |
| --- | --- | --- | --- |
| A. Bare Screen | Small, single-view tool that does not advertise nav keys or help | one `Screen` object + `ConsoleWindow` + a hand-written loop | none |
| B. Full Screen | App advertises navigation or needs a help screen | `ScreenStack` + `OptionSpinner` + `BasicHelpScreen` (or an `is_help=True` screen) | supplied by the spinner and `BasicHelpScreen` |

- There is no third "Screen + stack with hand-written help" model. If an app
  needs help, promote it to Model B. The spinner makes the help body; the
  built-in `quit`/`escape` actions (decision 7) and the auto-scoping rules
  (decisions 6 and 9) are the app's help implementation. Hand-writing a help
  page is the signal that the app is in the wrong model.
- Model A is not the retired screenless API. It still has a `Screen`; it simply
  does not create a `ScreenStack` or an `OptionSpinner`. Decision 10's "no
  stackless mode" means no stackless `OptionSpinner`, not no stackless `Screen`.
- If a Model A app wants navigation keys, it takes on the help obligation and
  becomes Model B. Not advertising nav keys is what lets the smallest apps omit
  help without pretending the help screen is optional everywhere.
- Content drawing belongs to `Screen`: `draw()`, `add_header()`, `add_body()`,
  `add_fancy_header()` and `add_header_line()` are Screen API, not
  `ConsoleWindow` API. `ConsoleWindow` keeps terminal/input/chrome concerns
  (`clear()`, `render()`, `prompt()`, `status()`, `flash()`, dialogs).
- Within one screen's draw pass, use either `draw()` or
  `add_header()`/`add_body()` (and the fancy/token header variants), never both.
  They are alternative placement models: absolute row/column drawing versus
  flow-ordered rows. Mixing them makes overflow, scrolling and paint order
  ambiguous. The rule is the same for Model A and Model B.
- Enforcement of the no-mixing rule is still a choice (documentation, warning,
  or assertion); the rule itself is not optional.
- Moving the drawing methods from `ConsoleWindow` to `Screen` is a deliberate
  one-time break. The project maintains all consumers and most already use
  `Screen`, so a compatibility shim is optional; if one exists, it is temporary.
- Sample-app mapping: the sample set should demonstrate exactly these two
  models. A Screen-only pager is Model A; the spinner pager is Model B. The
  intermediate stack-plus-hand-written-help pager is not a durable third sample.

## Open items

O1 (help-screen collision policy) is settled by decisions 7 and 9; O7 (the
stackless mode) is settled by decision 10. Decision 11 then defines the two
sanctioned app models and does not reopen O7: a bare `Screen` has no spinner,
so there is still no stackless `OptionSpinner`. It does narrow the remaining
items: O8 is Model B-only, and O9's `get_spinner() -> None` is a legitimate
Model A state. The remaining items are below.

### O3. A screen knowing its own number

The body filter is keyed by the **help screen's own** number, not the parent's:
filtering by the parent would list MAIN's `filter`, `select`, `note`, `a`, `l`,
`N`, which do not dispatch on help (the dead-key list decision 3 rejected).

Mechanism in Model B (the full stack of decision 10):
`ScreenStack.__init__` assigns `obj.num = num` for each entry in
`screen_objects` (with `Screen.num = None` documented as "assigned by the
stack"), and `BasicHelpScreen.draw_screen()` calls
`spinner.show_help_body(win, screen_filter=self.num)`. No hook and no fallback:
with a stack always present, `self.num` is always an int, and
`show_help_body()` keeps its narrow `int | list | set | None` signature instead
of importing `Screen` (which [`spinner.py`](../console_window/spinner.py:11) only
imports under `TYPE_CHECKING`).

Decision 11 scopes this to Model B. A Model A screen has no stack, so `num`
stays `None` and it never calls the help-body filter; that is not a missing
number, just a screen for which the full-model help machinery does not exist.

`ScreenStack.get_parent_screen()` is worth adding beside
[`get_curr_obj()`](../console_window/screens.py:159) — four lines, `None` at the
bottom of the stack or when `screen_objects` lacks the frame — but for prose and
headings, not for this filter.

### O4. Seam and heading

- Add `OptionSpinner.options_for_screen(screen)` returning the filtered list;
  `show_help_body()` should use it so apps rendering their own help share one
  definition of "applies here".
- `show_help_body()` currently prints "Type keys to alter choice:" even when
  nothing matches. Wording and suppression rule are undecided.

### O5. Incremental search and other modal layers (deferred)

`IncrementalSearchBar` consumes printable keys while active inside
`handle_key()` and takes priority over the spinner. It is a layer, not a
screen, so it has no `effective_scope` and does not overlap per screen. Help is
unreachable while it is active. Deferred choices: list layer keys in a separate
"while typing" block, or make the bar take its keys from the current screen's
spinner set so the two cannot diverge.

### O6. Verification for decisions 2 and 7-11

When implemented, cover: the same key as a cycle option on two screens; help
draws only current-screen options plus spinners; pressing a spinner key while
help is current changes the value; a MAIN-only action is absent from help;
`quit` and `escape` appear in the third NavKeys line and not in the body; ESC on
the help screen pops to the parent; `quit` raises `SystemExit` through the
`atexit` teardown; an app registering its own key on ESC raises from
`add_key()` with a message naming `escape_keys=`.

- Model A draws through a bare `Screen` with no stack or spinner and exits
  normally.
- Model B supplies its help screen without a hand-written help body.
- Once enforcement is chosen, a draw pass that mixes `draw()` with
  `add_header()`/`add_body()` trips the no-mixing policy.

### O8. Nothing enforces the loop

For Model B, decision 10 makes the objects mandatory, but the paradigm is also
a five-call loop: `draw_screen()`, `render()`, `prompt()`, `handle_key()` and
`perform_actions()` ([`SampleApp.py:264`](../SampleApp.py:264)). An app can build
the stack and the spinner correctly and still never call the dispatcher, and
nothing complains — which is the same "apps decide too much" failure with a
different shape.

Decision 11 makes this a Model B-only concern: a Model A app has no dispatcher
to forget. The five-call loop and the options below are otherwise unchanged, so
O8 remains open for Model B.

Options: leave it documented; provide one seam the loop must use
(`ScreenStack.dispatch(key)` that resolves with `do_key()`, runs
`perform_actions()`, and returns what happened); or provide a `run()` that owns
all five calls, with `draw_screen()` and the key handler as the only app hooks.
Not decided.

Sub-question for `show_help_nav_keys()`: with decision 10 it is always an
instance method on a spinner that has a stack, so the stackless call at
[`tests/test_taken_nav_keys.py:264`](../tests/test_taken_nav_keys.py:264) grows a
stack like the rest.

### O9. `Screen.get_spinner()` discovery and its `None`

[`Screen.get_spinner()`](../console_window/screens.py:65) caches the result of
scanning `vars(self.app)` for an `OptionSpinner`, silently returns `None` when
there is none (or when the app has not built it yet), and takes the first match
when an app exposes two. Three call sites tolerate the `None`:
[`BasicHelpScreen.draw_screen()`](../console_window/screens.py:274),
[`theme._discover_cycle_key()`](../console_window/theme.py:38) and the cache.

Decision 11 changes the premise: every Model B app has exactly one spinner, but
a Model A app has none by design. Therefore `get_spinner() -> None` is a
legitimate permanent state, not only a construction-order tolerance, and the
"no `None`" direction is rejected. For Model B, the scan can still be replaced
by injection: the spinner sets `stack.spinner = self` in its constructor, the
way `screen.stack` and `screen.num` are set, and `get_spinner()` becomes
`self.stack.spinner` for Model B screens. Whether to keep scanning, whether
injection is per-screen or stack-wide, and whether two spinners should raise
remain open.
