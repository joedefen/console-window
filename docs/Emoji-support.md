# Emoji and status marks: width-safe decoration

**Status:** design, not implemented. **Owner:** a new `marks` family in
`console_window/glyphs.py`, enforcing the rule that `console_window/textwidth.py`
already models.

This document replaces the crude symbol list that started this file. That list is
now Appendix A, filtered: every entry there passed the width rule in §4. The rest
of the document is the design of the support that makes the rule enforceable —
an approved mark table, a two-cell ASCII fallback, and a detector that tells you
during development that a mark is unsafe.

Decisions in this document:

1. A mark is approved on a **measurable** property (cell width), not on taste.
2. Approval is enforced at import, by name lookup, and by an audit — three
   different trust levels, because the three failure modes are different.
3. Emoji live in their own family, separate from the one-cell glyph catalog, so
   the existing promise ("no emoji, no patched fonts") stays true.
4. Prominence comes from the **attribute**, not the glyph (§6). That is the whole
   answer to "bold check marks that do not break the table".
5. Nothing about content is policed: a pager shows a file containing `⚙️` without
   complaint. Only decoration the application itself chooses is checked.

---

## 1. The problem

Three goals pull against each other:

* **Loud.** In a mono theme, or with color unused, a prompt or a status column
  needs a mark that is seen at a glance. Hairline `✓`, `△`, `·` are often too
  small or too dim to carry that weight.
* **Aligned.** The mark sits in a row with other columns. If its width changes —
  between terminals, between modes, between one frame and the next — every cell
  to its right moves.
* **Portable.** A terminal without an emoji font, a legacy console, an SSH
  session with a poor font. A mark that does not render is acceptable. A mark
  that renders *at a different width* is not.

The instinct that produced the bold-looking candidates in Appendix A is right:
the heavy variants are exactly the ones that read clearly. They are also exactly
the ones with an unstable cell count. That is the trap this document resolves.

## 2. Why the obvious bold marks are the unsafe ones

Measured with `textwidth.string_width()`, the everyday bold text symbols are all
one cell, and become two cells only when a variation selector is appended:

| mark | code point | width alone | width with U+FE0F | what the terminal does |
|---|---|---|---|---|
| `⚠` | U+26A0 | 1 | 2 | honors VS16 or not, at its own discretion |
| `✔` | U+2714 | 1 | 2 | same |
| `✖` | U+2716 | 1 | 2 | same |
| `⏱` | U+23F1 | 1 | 2 | same |
| `🖥` | U+1F5A5 | 1 | 2 | same |
| `🗄` | U+1F5C4 | 1 | 2 | same |
| `⛓` | U+26D3 | 1 | 2 | same, and East-Asian **Ambiguous** (see §4) |

Two consequences:

* `⚠️` is **2 cells in this library's model and 1 cell on a terminal that ignores
  VS16**. That is precisely the misalignment that two rounds of work on the
  widths demo chased: the column was measured for 2 and drawn in 1. It is not a
  bug in `_string_char_width()`; VS16 is a *request*, and whether it is granted is
  a property of the terminal, unobservable from inside the process.
* Writing the bare code point does not help: `⚠` alone may still be drawn as a
  color emoji, two cells wide, by a terminal configured to force emoji
  presentation.

There is no way to ask a terminal "will you make this two cells?". The only way
out is to use code points where **the answer cannot differ**: East-Asian Width
`W`, where the width table says 2, every common terminal agrees, and even a
missing glyph (tofu) occupies 2 cells. A box is the acceptable failure. A shift
is not.

## 3. What cannot be detected

Same conclusion as the glyph policy, and stricter: the encoding is observable,
the font is not, and for emoji the *cell count* is not either. So detection is
advisory only:

* a font check that prints the real marks, so the user can see them;
* an explicit switch (§5) that the user can throw when the guess is wrong;
* defaults that prefer the boring spelling (one-cell text marks) over the
  attractive one.

## 4. The width-safety rule

Four classes, derived from `unicodedata.east_asian_width()` plus
`textwidth.string_width()`. `w(ch)` is the model's width; `w(ch + VS16)` is the
width when a variation selector is appended.

| class | rule | example | verdict for a column |
|---|---|---|---|
| **S1** safe, one cell | `EAW=N`, `w(ch) == 1`, `w(ch + VS16) == 1` | `✓` `✗` `·` `—` `…` `⊗` | allowed, in one-cell fields |
| **S2** safe, two cells | one code point, `EAW=W`, `w(ch) == 2`, `w(ch + VS16) == 2` | `✅` `❌` `❗` `🚨` `💥` `🟢` | allowed, in two-cell fields |
| **U1** ambiguous | `EAW=A` | `●` `■` `◆` `★` `▲` `⛓` | **banned** in columns |
| **U2** VS16-promoted | `EAW=N` or `A`, `w(ch) != w(ch + VS16)` | `⚠` `✔` `✖` `⏱` `🖥` `🗄` | **banned** everywhere |
| **U3** sequence | more than one code point, or a ZWJ | `👨‍👩‍👧` `🇺🇸` | **banned** everywhere |

Notes:

* U1 is a hazard this library already carries: `textwidth` counts the Ambiguous
  class as one cell, which is right for a Latin-locale terminal and wrong for a
  CJK-width one. The one-cell glyph catalog uses `● ■ ◆ ★ ▲` as shapes, and that
  is fine in prose and help legends; it is not fine next to a two-cell mark in a
  column whose width matters.
* The S2 test is deliberately "**VS16 cannot change the answer**". An approved
  mark is immune to a stray `\ufe0f` that a copy-paste or a code generator adds:
  `✅` and `✅\ufe0f` are both two cells. U2 marks flip; that is the whole point.
* Every rule is a couple of lines of Python, so an entry can be checked before it
  is added:

  ```python
  import unicodedata
  from console_window.textwidth import string_width

  def classify(ch: str) -> str:
      w, wv = string_width(ch), string_width(ch + '\ufe0f')
      if len(ch) != 1:
          return 'U3 sequence'
      eaw = unicodedata.east_asian_width(ch)
      if eaw == 'W' and w == wv == 2:
          return 'S2 safe, two cells'
      if eaw == 'N' and w == wv == 1:
          return 'S1 safe, one cell'
      if eaw == 'A':
          return 'U1 ambiguous'
      return 'U2 VS16-promoted'
  ```

Appendix A was produced by running that rule over the source list; the 15 entries
that failed it are listed, with their reasons, in Appendix B.

## 5. The approved mark set

### 5.1 What belongs in it

A small, garden-variety vocabulary: status, dots, shapes, data, comms, waiting.
About forty entries, not three hundred. The list is data, not policy, so an
application can add to it — under the same validation.

```python
# console_window/glyphs.py, next to BUILTIN_GLYPHS
@dataclass(frozen=True)
class SafeMark:
    name: str          # 'ok', 'dot_red'
    emoji: str         # one code point, EAW=W, width 2
    ascii: str         # plain ASCII, width 2
    group: str = 'badges'   # not 'marks': that family is check/cross/warn
```

Validation, raised at import time as `ValueError` (never `assert`: `python -O`
removes asserts, and a library must not lose its invariants under an optimiser):

1. `emoji` is exactly one code point;
2. `unicodedata.east_asian_width(emoji) == 'W'`;
3. `string_width(emoji) == 2`;
4. `string_width(emoji + '\ufe0f') == 2` — VS16 immunity;
5. no `U+200D` (ZWJ) and no other variation selector;
6. `ascii.isascii()` and `string_width(ascii) == 2`;
7. `name` and `emoji` are unique across the table.

Rule 6 is the one that is easy to miss: the ASCII fallback must be **two cells**
as well, or `--ascii` moves every column the emoji did not.

### 5.2 The initial table

Fallbacks use the house style already set by the one-cell catalog (`check` → `v`,
`cross` → `x`, `warn` → `!`): one ASCII character plus a trailing space, so the
token is two cells and reads as a single mark. Names avoid the one-cell catalog's
names, because both tables share one registry (`warn` is already `⚠`). A code
point appears once in the table, so a longer wish list cannot fork it: the bell
(🔔) and the speech balloon (💬) are `bell` and `chat` already.

| use | name | mark | ascii | meaning |
|---|---|---|---|---|
| status | `ok` | ✅ | `v ` | success |
| status | `fail` | ❌ | `x ` | failure |
| status | `attention` | ❗ | `! ` | needs attention |
| status | `ask` | ❓ | `? ` | unknown, question |
| status | `stop` | 🛑 | `- ` | stop, do not proceed |
| status | `ban` | ⛔ | `# ` | forbidden |
| status | `denied` | 🚫 | `X ` | blocked, refused |
| status | `siren` | 🚨 | `!!` | alarm, incident |
| status | `boom` | 💥 | `* ` | crash, collision |
| status | `idea` | 💡 | `i ` | idea, note |
| status | `build` | 🚧 | `C ` | work in progress |
| dots | `dot_green` | 🟢 | `G ` | healthy |
| dots | `dot_yellow` | 🟡 | `Y ` | degraded |
| dots | `dot_red` | 🔴 | `R ` | failing |
| dots | `dot_blue` | 🔵 | `B ` | informational |
| dots | `dot_black` | ⚫ | `K ` | off, absent |
| dots | `dot_white` | ⚪ | `W ` | empty, unknown |
| dots | `radio` | 🔘 | `r ` | selected, one of |
| shapes | `star` | ⭐ | `s ` | starred, favourite |
| shapes | `star_glow` | 🌟 | `S ` | highlighted |
| shapes | `circle_heavy` | ⭕ | `0 ` | open, ring |
| shapes | `diamond_orange` | 🔶 | `O ` | bullet, orange |
| shapes | `diamond_blue` | 🔷 | `D ` | bullet, blue |
| shapes | `diamond_dot` | 💠 | `. ` | bullet, detail |
| data | `folder` | 📁 | `[ ` | directory |
| data | `file` | 📄 | `f ` | file |
| data | `chart` | 📊 | `\| ` | metrics |
| data | `find` | 🔍 | `o ` | search |
| data | `lock` | 🔒 | `L ` | locked |
| data | `key` | 🔑 | `k ` | credential |
| data | `link` | 🔗 | `> ` | reference, link |
| data | `magnet` | 🧲 | `M ` | pinned, attached |
| comms | `mail` | 📧 | `@ ` | mail |
| comms | `bell` | 🔔 | `n ` | notification |
| comms | `chat` | 💬 | `m ` | message |
| comms | `globe` | 🌍 | `g ` | network, world |
| comms | `net` | 🌐 | `N ` | internet, web |
| comms | `package` | 📦 | `p ` | package, release |
| time | `wait` | ⏳ | `w ` | pending |

### 5.3 API

```python
mark('ok')            # '✅'   (two cells)
set_ascii(True)
mark('ok')            # 'v '   (still two cells)
mark('tick')          # KeyError: not an approved mark
```

* `mark(name)` is the accessor. `KeyError` is the development-time "assert" —
  it fires in the application's own tests, where it is cheap to fix.
* Registration reuses the existing machinery: a mark is a `Glyph` whose `ascii`
  is two cells wide, so `transliterate()` already rewrites `✅` to `v ` under
  `set_ascii(True)` with no second pass and no second switch. There is **no new
  mode**: `--ascii` / `CONSOLE_WINDOW_GLYPHS` keep meaning what they mean.
* `Glyphs.marks()` lists the family for a catalog page, and
  `catalog_items(include_marks=True)` is the opt-in for a page that wants both
  families. `catalog_items()` itself keeps returning the one-cell family only, so
  the README's "no emoji" sentence about the glyph catalog stays true and the
  theme page does not silently grow a second kind of cell.
* `Glyphs.marks_probe_text()` returns the status marks for a font check. Note
  that the window transliterates header text, so a *page* that prints it shows
  the fallbacks in ASCII mode; the demo labels that line `status:`, not
  `font check:`, rather than implying it checks the emoji font.
* `demo-q-marks` (next free letter) owns the catalog, the fallback switch and the
  detector page. `demo-p-key-debug` keeps one mark row in its width table, which
  is where the two-cell claim is easiest to see.

### 5.4 The font budget

A mark is a single code point with `Emoji_Presentation=Yes`, so the mark table
costs **one** font, not one per group: a colour emoji font. Nothing here wants a
text-symbol font on the side, and nothing wants a per-entry fallback font. The
code point either has its emoji glyph in that font or it is a box.

Measured with `fc-list :charset=…` over all 39 marks: exactly one installed family
covers every entry, **Noto Color Emoji**. The near misses are instructive —
Symbola covers 36 of the 39 (it lacks 🟢 🟡 🧲), and Noto Sans Symbols2 has the
punctuation-like marks (❗ ❓ ⛔ ⭕) but not the pictures (✅ 🔑 📁).

The version floor comes from the newest additions:

| entry | code point | emoji version |
|---|---|---|
| `dot_green`, `dot_yellow` | U+1F7E2, U+1F7E1 | 12.0 (2019) |
| `magnet` | U+1F9F2 | 11.0 (2018) |

Everything else dates from Emoji 1.0–3.0 (2015–2016), so "an emoji font" means one
from mid-2019 or later: Noto Color Emoji on Linux and Android, Apple Color Emoji on
macOS and iOS, Segoe UI Emoji on Windows 10+. An older font boxes those three
entries and nothing else.

The one-cell catalog is the cheaper side of the bill, and the README's "no patched
font" promise is measured rather than hoped for: all 80 names (78 distinct
characters) are in **DejaVu Sans Mono**, each at exactly the font's cell advance
(1233 of 2048 units), so the default face on Debian and Ubuntu needs no fallback
at all. **FreeMono** carries all 78 as well (600 of 1000 units). Other monospace
faces are partial — Noto Sans Mono 63 of the 80 names, JetBrains Mono 64, Hack 68,
Liberation Mono 35 — each missing mostly arrows, stars and ballot boxes. Terminals
fall back per code point (fontconfig picks a face that has the character), so this
is usually invisible; where fallback is disabled it is a box, not a shifted row.

No single font covers both tables. Over the 117 distinct code points of the two
families, the closest installed face is Symbola at 114 (every glyph, 36 of the
marks), and it is not a terminal font; DejaVu Sans Mono has all the glyphs and none
of the marks, Noto Color Emoji the mirror image (all 39 marks, 13 of the glyphs).
So the budget is two fonts, each already implied by a different promise: the
monospace you have, plus one emoji font you install once. Installing several emoji
fonts buys nothing (first match wins, so two fonts can disagree about a mark), and
the library cannot see which fonts exist (§3) — which is why the answer is one
switch (`--ascii`) and one probe line, not a font database.

The check itself is built in, not per application. Every help page carries a
**Fonts** section: three rows of one-cell glyphs, two rows of marks, and the
advice above word for word. The section is purely visual, so it runs no font
query and cannot stall a redraw; the option only decides how often it appears —
`ConsoleWindowOpts(help_fonts='once' | 'always' | 'never')`, default `'once'`,
which is the full section on the first help page a window shows and one line
afterwards, with `BasicHelpScreen.font_section` overriding it per screen. In
ASCII mode the section collapses to a sentence, because every cell is plain
ASCII there.

The one machine check is narrower, and runs only when an application registers
something. `register()` and `register_mark()` ask fontconfig, once, whether the
family that should carry the new symbol (`DejaVu Sans Mono` for a glyph, `Noto
Color Emoji` for a mark) has it, and record a miss that the help page then names.
If the family is not installed the answer is "cannot check" and nothing is
recorded: a machine without the font is not a bug. The blessed tables skip the
check entirely — the test suite asserts that the two families cover them, which
is the contract from the start of this section.

## 6. Loud check marks without the gamble

The goal "an OK that stands out" does not need an unstable glyph. There are three
rungs, in decreasing order of safety; pick the highest one that fits the layout.

**Rung 1 — attribute, always safe.** Prominence is a property of the cell, not of
the glyph. Reverse video on a padded word is the loudest thing a mono terminal
can draw, and its width is the length of the word:

```python
win.status('saved', level='warn')      # STATUS_LEVELS: warn -> A_BOLD
win.status('failed', level='error')    # error -> A_BOLD | A_REVERSE
```

`STATUS_LEVELS` (`console_window/window.py:522`) is already this design: `info`
dim, `warn` bold, `error` bold-and-reversed. A prompt's hint is the same idea —
the existing hint text `["{mode}" or ESC]` padded and inverted is louder than any
symbol, and costs no cells beyond its own length.

**Rung 2 — approved two-cell mark.** `mark('ok')` / `mark('fail')` / `mark('attention')`.
Colour where available, tofu where not, two cells either way. Use it where the
column is two cells and the extra visual weight is wanted.

**Rung 3 — one-cell text mark.** `✓` `✗` and the catalog's `check`/`cross`
entries, in a one-cell field. Cheap and font-independent; thin, which is why it
was the problem in the first place. Never append VS16 to make it bolder — that is
how U2 marks appear in code.

Banned: anything from §4's U1/U2/U3 rows, in any column whose width matters.

And the rule that outranks the ladder: **the mark is never the only signal.** If
the emoji does not render, the attribute and the word still say "this failed". An
inverted `FAIL` is a failure; a lone box is a puzzle.

## 7. The detector

The goal is to *know quickly*, while writing the app, that a mark is unsafe.

```python
find_issues(text) -> list[Issue]   # Issue(kind, text, offset, hint)
```

`kind` is one of `vs16`, `zwj`, `ambiguous`, `unapproved`
(nothing is reported for S1/S2 code points, and nothing for ordinary non-ASCII
text: `Grüße` is content, not decoration).

Two places it runs:

1. **In the application's tests**, over its own literals — the fastest loop:
   `assert not find_issues(prompt_text)`.
2. **In the audit**, when `CONSOLE_WINDOW_GLYPH_AUDIT=1`. The audit runs on the
   text *as written*, in both modes (in ASCII mode the substitution would
   otherwise have hidden the problem), once per code point:

   ```
   glyph audit: ⚠️ is VS16-promoted: 1 or 2 cells depending on the terminal;
   use mark() for two cells, or a one-cell EAW=N mark like ✓
   glyph audit: ● (U+25CF) is East-Asian Ambiguous: 1 cell(s) here, 2 in a
   CJK-width terminal; use mark() or a one-cell EAW=N mark
   glyph audit: 🦄 (U+1F984) is a two-cell mark with no approved fallback;
   add it with Glyphs.register_mark() or use mark()
   ```

A bare one-cell mark is not reported — `✓` is rung 3, and a terminal that forces
emoji presentation for it cannot be observed from here. A code point that is
registered nowhere keeps the older "has no ASCII fallback" message, which is how
an application learns the `register()` call for its own vocabulary.

Concrete finding from the current tree: the copyable prompt example in
`tests/test_prompt_window.py` read `["{mode}" or ESC] ⚠️` — the exact U2 mark, in
the line a reader is most likely to copy. It now reads `❗`. The tests that
*measure* VS16 (`tests/test_textwidth.py`, `tests/test_prompt_window.py`) keep
their `⚠️`: they are the fixtures that prove the rule.

## 8. Out of scope

* Colour and presentation control (a mark renders in whatever colour the terminal
  chooses; `--theme mono` is the app's answer, and rung 1 is its tool).
* ZWJ sequences and flag pairs (U3): variable width, no safe fallback, not worth
  the machinery.
* Per-terminal emoji probing: cannot be observed, so it is not attempted. The
  font check plus the switch is the whole story.
* Rewriting content: `transliterate()` already only touches registered code
  points, and this family does not change that.

## 9. Implementation checklist

Done, as the record of what changed:

1. `console_window/glyphs.py`
   * `SafeMark`, `validate_mark()`, `BUILTIN_MARKS`, registered at import under
     the `badges` group (so `transliterate()` and the audit handle marks for
     free).
   * `mark(name)`, `marks()`, `marks_probe_text()`, `register_mark()`,
     `Issue`/`find_issues(text)`; `MARK_GROUP` is exported for callers that
     filter on it.
   * `catalog_entries()`/`catalog_items()`/`catalog_rows()` take
     `include_marks=False`.
   * `_audit()` classifies with `find_issues()` first and keeps the old
     unregistered-symbol message second; `transliterate()` audits the input in
     both modes.
2. `tests/test_marks.py`
   * one case per validation rule, each expecting `ValueError` (plus `TypeError`
     for a non-string field);
   * every built-in mark: `string_width(emoji) == string_width(emoji + VS16) == 2`
     and `string_width(ascii) == 2`, with unique names, drawings and fallbacks;
   * `mark()` returns a two-cell token in both modes, `KeyError` for a one-cell
     glyph name and for an unknown name;
   * `find_issues()` kinds and offsets for `⚠️`, `●`, `🦄` and a ZWJ family, and
     nothing for `✅`, `✅\ufe0f`, `✓`, `Grüße` and `—`/`±` prose;
   * a row padded to a fixed width keeps that width when every mark is swapped
     for its ASCII spelling;
   * the audit logs one verdict in Unicode mode and stays quiet for an approved
     mark.
3. Existing tests: **no changes needed.** `catalog_entries()` still counts the
   one-cell family, so `tests/test_glyphs.py` and `tests/test_theme_picker.py`
   pass untouched; the only edit was the copyable prompt hint in
   `tests/test_prompt_window.py`, which now uses `❗`.
4. Docs and demos
   * `README.md` — a "two-cell marks" bullet under the symbols section, keeping
     the "no emoji" property of the glyph catalog intact.
   * `docs/DEMO-APPS.md` — row Q for `q-marks`, the four feature keys, the group
     note and the appendix; `demo-p-key-debug` gained one mark row.
   * `tests/CHANGELOG.md` — Added: approved marks and the detector; Changed: the
     copyable prompt hint no longer uses a VS16 mark.
   * `demos/demo-q-marks.py`, `demos/demos.ini`, `demos/features.py`.

---

## Appendix A: the source list, filtered

Every entry below is a single code point with East-Asian Width `W`, width 2, and
width 2 with a VS16 appended. Duplicates and the 15 entries that failed the rule
were removed (Appendix B); the grouping is the original author's.

**Status, Alerts & Badges**

* Pass / Fail / Warn: ✅ ❌ ❎ 🚨 🛑 🚫 ⭕ ❗ ❓ ❕ ❔
* Color Dots & Squares: 🟢 🟡 🟠 🔴 🔵 🟣 🟤 ⚫ ⚪ 🟩 🟨 🟧 🟥 🟦 🟪 ⬛ ⬜
* Diamonds & Shapes: 🔶 🔷 🔸 🔹 🔺 🔻 💠 🔘

**System, Hardware & Storage**

* Disks & Memory: 💾 💿 📀 💽 📼 📦 📥 📤 🧹 🧺
* Hardware & Devices: 💻 📱 📲 🔋 🪫 🔌 📡 📶 📻 📺 📷 🎥 🔦 💡
* Security & Keys: 🔒 🔓 🔏 🔐 🔑 🪪 🧱 🚧 🪝

**Files, Logs & Data**

* Documents & Folders: 📁 📂 📇 📄 📃 📑 📜 📰 📋 📝 📓 📔 📒 📕 📗 📘 📙 📚 📖
* Charts, Metrics & Search: 📊 📈 📉 🔍 🔎 🔬 🔭 🧭 📍 📌 📎 📏 📐 🧮

**Actions, Tools & Process**

* Execution & Speed: 🚀 🔥 ⚡ 💥 💫 ✨ 🌟 ⭐ 🎯 🏁 🎉 🎊 🏆 🥇 🥈 🥉
* Time & Waiting: ⏳ ⌛ ⏰ 🕛 🕒 🕕 🕘 📅 📆
* Tools, Build & Config: 🔧 🔨 🪓 🪚 🪛 🔩 🔗 🧲 🧪 🧫 🧬 🧰 🪜 🧯

**Network, Web & World**

* Globes & Maps: 🌍 🌎 🌏 🌐 🏠 🏢 🏭 🏦 🏥
* Mail & Comms: 📧 📨 📩 📬 📭 📮 📯 📢 📣 🔔 🔕 💬 💭

## Appendix B: what the filter removed, and why

The source list annotated most of these "skip" already; the rule agrees with the
annotation, so the annotation is now enforced rather than advised.

| entry | why it is not usable |
|---|---|
| `🗄` | `EAW=N`, 1 cell: it is a *text* presentation of a file cabinet, not a two-cell mark |
| `🗄️` `🗑️` `🖥️` `🛡️` `🗂️` `🗒️` `⏱️` `⏲️` `🗺️` `🏔️` `🏝️` `🗨️` `🗯️` | 2 cells only through VS16 (U2): 1 or 2 depending on the terminal |
| `⛓️` | U2 **and** `EAW=A` (U1): two independent ways to be wrong |
| `🔬` (second occurrence) | duplicate: already listed under Charts, Metrics & Search |
| `🧭` (second occurrence) | duplicate: already listed under Charts, Metrics & Search |

Removed: 15 failing entries and 2 duplicates out of 178 distinct tokens; 161
entries remain in Appendix A.
