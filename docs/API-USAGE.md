# Public API usage

How much of the public surface the demo suite and the sibling
applications actually touch.  Regenerate with
`python tests/api_usage_report.py --write docs/API-USAGE.md`.

A *reference* is an AST load of the name (or a `from console_window
import ...` alias).  Comments, docstrings and help text are not counted.
Build metadata, virtualenvs and `build/`-`dist/` sandboxes are excluded:
they hold installed copies of this library, and counting them would score
the library against itself.

## Entry points

| API | demos | apps |
| --- | ---: | ---: |
| `Theme` | 19 | 192 |
| `Glyphs` | 9 | 65 |
| `ConsoleWindow` | 12 | 53 |
| `semantic_attr` | 3 | 62 |
| `Context` | 8 | 48 |
| `ConsoleWindowOpts` | 9 | 46 |
| `HOME_ST` | 0 | 55 |
| `set_colors_enabled` | 1 | 54 |
| `colors_enabled` | 2 | 51 |
| `OptionSpinner` | 6 | 45 |
| `Appearance` | 8 | 33 |
| `Screen` | 12 | 21 |
| `ScreenStack` | 6 | 23 |
| `InlineConfirmation` | 2 | 20 |
| `HeaderLine` | 7 | 8 |
| `IncrementalSearchBar` | 2 | 11 |
| `BasicHelpScreen` | 4 | 8 |
| `resolve_appearance` | 0 | 9 |
| `BasicTextScreen` | 2 | 2 |
| `MONO_ROLES` | 0 | 4 |
| `NAVIGATION_KEYS` | 0 | 4 |
| `TerminalTooSmallError` | 2 | 2 |
| `ThemeStore` | 4 | 0 |
| `Glyph` | 0 | 3 |
| `reset_ctrl_c` | 2 | 0 |
| `PromptLine` | 0 | 0 |
| `Span` | 0 | 0 |

Entry points with no consumers at all: `PromptLine`, `Span`.

### No demo use, some application use

The coverage question, one row per entry point the demos never touch.
`apps` counts the applications that reference the name at all; `busiest`
is the largest count inside a single application, so `1` (an import)
reads differently from a name one application depends on.

| API | apps | busiest | application |
| --- | ---: | ---: | --- |
| `HOME_ST` | 3 | 29 | vappman |
| `NAVIGATION_KEYS` | 1 | 4 | grub-wiz |
| `Glyph` | 1 | 3 | pypi-cleanup-tui |
| `resolve_appearance` | 4 | 3 | my-snaps |
| `MONO_ROLES` | 3 | 2 | vappman |

## Methods

Only methods defined on exactly one exported class are listed, and a call
is counted only when the handle is known to hold that class: an annotated
parameter or attribute (`win: ConsoleWindow`), an exported constructor, or
a function whose return annotation names the class (`spin =
self.new_spinner()`).  An untyped handle falls back to the conventional
names (`win`, `screen`, `stack`, `spinner`, `spin`, `opts`, `theme`,
`header`, `line`, `prompt`, `editor`, `bar`, `menu`, `app`), and `self`
counts inside a class that descends from an exported class.  That keeps
`.pop()` on a list out of `ScreenStack.pop` and `.get()` on a dict out of
`Glyphs.get`, and it keeps a pre-3.0 `window.add_body()` out of
`Screen.add_body`.

| Method | Owner | demos | apps |
| --- | --- | ---: | ---: |
| `.add_key()` | `OptionSpinner` | 33 | 195 |
| `.stop_curses()` | `ConsoleWindow` | 4 | 154 |
| `.set_pick_mode()` | `ConsoleWindow` | 16 | 32 |
| `.add_body()` | `Screen` | 29 | 7 |
| `.push()` | `ScreenStack` | 5 | 26 |
| `.get_picked_context()` | `ConsoleWindow` | 4 | 24 |
| `.add_header()` | `Screen` | 26 | 1 |
| `.bracket_key()` | `HeaderLine` | 11 | 16 |
| `.semantic_attr()` | `Appearance` | 3 | 24 |
| `.list_all()` | `Theme` | 1 | 25 |
| `.handle_prompt_key()` | `ConsoleWindow` | 1 | 24 |
| `.render()` | `ConsoleWindow` | 5 | 18 |
| `.alert()` | `ConsoleWindow` | 3 | 18 |
| `.perform_actions()` | `ScreenStack` | 2 | 19 |
| `.add_fancy_header()` | `Screen` | 18 | 0 |
| `.prompt()` | `ConsoleWindow` | 4 | 14 |
| `.set_colors_enabled()` | `Appearance` | 1 | 17 |
| `.status()` | `ConsoleWindow` | 15 | 3 |
| `.colors_enabled()` | `Appearance` | 2 | 15 |
| `.resolve()` | `Theme` | 2 | 15 |
| `.pop()` | `ScreenStack` | 1 | 14 |
| `.set_ascii()` | `Glyphs` | 0 | 14 |
| `.flash()` | `ConsoleWindow` | 1 | 12 |
| `.is_curr()` | `ScreenStack` | 2 | 10 |
| `.set_handled_keys()` | `ConsoleWindow` | 4 | 8 |
| `.do_key()` | `OptionSpinner` | 2 | 9 |
| `.get_value()` | `OptionSpinner` | 0 | 9 |
| `.get_current()` | `Theme` | 2 | 6 |
| `.show_help_body()` | `OptionSpinner` | 0 | 8 |
| `.answer()` | `ConsoleWindow` | 1 | 6 |
| `.create_picker_screen()` | `Theme` | 1 | 6 |
| `.fix_positions()` | `ConsoleWindow` | 0 | 7 |
| `.get()` | `Glyphs` | 2 | 5 |
| `.get_curr_obj()` | `ScreenStack` | 6 | 1 |
| `.initial()` | `Theme` | 1 | 6 |
| `.set_theme()` | `ConsoleWindow` | 1 | 6 |
| `.calc()` | `ConsoleWindow` | 0 | 6 |
| `.get_pad_width()` | `ConsoleWindow` | 2 | 4 |
| `.is_ascii()` | `Glyphs` | 1 | 5 |
| `.set_active()` | `Theme` | 1 | 5 |
| `.show_help_nav_keys()` | `OptionSpinner` | 0 | 6 |
| `.label()` | `HeaderLine` | 3 | 2 |
| `.set_demo_mode()` | `ConsoleWindow` | 1 | 4 |
| `.extend()` | `HeaderLine` | 1 | 3 |
| `.get_hint()` | `InlineConfirmation` | 1 | 3 |
| `.resume_curses()` | `ConsoleWindow` | 1 | 3 |
| `.suspend_curses()` | `ConsoleWindow` | 1 | 3 |
| `.apply_to()` | `Theme` | 0 | 3 |
| `.begin_prompt()` | `ConsoleWindow` | 2 | 1 |
| `.draw_notes()` | `BasicHelpScreen` | 0 | 3 |
| `.extra_help_paragraphs()` | `Screen` | 1 | 2 |
| `.from_screens()` | `ScreenStack` | 3 | 0 |
| `.probe_text()` | `Glyphs` | 1 | 2 |
| `.set()` | `Theme` | 0 | 3 |
| `.set_pick_range()` | `ConsoleWindow` | 1 | 2 |
| `.theme_of()` | `Theme` | 2 | 1 |
| `.as_header_line()` | `IncrementalSearchBar` | 1 | 1 |
| `.escape_ACTION()` | `Screen` | 0 | 2 |
| `.get_spinner()` | `Screen` | 0 | 2 |
| `.is_mono()` | `Theme` | 0 | 2 |
| `.mark()` | `Glyphs` | 2 | 0 |
| `.render_once()` | `ConsoleWindow` | 0 | 2 |
| `.set_text()` | `BasicTextScreen` | 1 | 1 |
| `.start_curses()` | `ConsoleWindow` | 0 | 2 |
| `.stop_all()` | `ConsoleWindow` | 0 | 2 |
| `.add_header_line()` | `Screen` | 1 | 0 |
| `.add_prompt_header()` | `Screen` | 1 | 0 |
| `.add_prompt_lines()` | `Screen` | 1 | 0 |
| `.catalog_entries()` | `Glyphs` | 1 | 0 |
| `.clear_status()` | `ConsoleWindow` | 1 | 0 |
| `.glyph()` | `ConsoleWindow` | 0 | 1 |
| `.resolve_appearance()` | `Appearance` | 0 | 1 |
| `.save()` | `ThemeStore` | 1 | 0 |
| `.search()` | `HeaderLine` | 0 | 1 |

### No demo use, some application use

Same reading as above, for method calls.  A name here is an integration
shape the demo family never exercises.

| Method | Owner | apps | busiest | application |
| --- | --- | ---: | ---: | --- |
| `.set_ascii()` | `Glyphs` | 1 | 14 | grub-wiz |
| `.get_value()` | `OptionSpinner` | 1 | 9 | pypi-cleanup-tui |
| `.fix_positions()` | `ConsoleWindow` | 2 | 6 | vappman |
| `.calc()` | `ConsoleWindow` | 3 | 3 | vappman |
| `.draw_notes()` | `BasicHelpScreen` | 1 | 3 | grub-wiz |
| `.apply_to()` | `Theme` | 2 | 2 | grub-wiz |
| `.escape_ACTION()` | `Screen` | 1 | 2 | grub-wiz |
| `.is_mono()` | `Theme` | 1 | 2 | pmemstat |
| `.render_once()` | `ConsoleWindow` | 1 | 2 | vappman |
| `.set()` | `Theme` | 2 | 2 | efibootdude |
| `.show_help_body()` | `OptionSpinner` | 7 | 2 | vappman |
| `.stop_all()` | `ConsoleWindow` | 1 | 2 | efibootdude |
| `.get_spinner()` | `Screen` | 2 | 1 | dwipe |
| `.glyph()` | `ConsoleWindow` | 1 | 1 | efibootdude |
| `.resolve_appearance()` | `Appearance` | 1 | 1 | dwipe |
| `.search()` | `HeaderLine` | 1 | 1 | pypi-cleanup-tui |
| `.show_help_nav_keys()` | `OptionSpinner` | 6 | 1 | dwipe |
| `.start_curses()` | `ConsoleWindow` | 2 | 1 | dwipe |

## Per application

10 sibling directories import the library; the rest do not.

| Application | references |
| --- | ---: |
| grub-wiz | 439 |
| vappman | 331 |
| pypi-cleanup-tui | 296 |
| pmemstat | 185 |
| dwipe | 165 |
| my-snaps | 124 |
| efibootdude | 68 |
| psistat | 33 |
| memfo | 23 |
| zram-advisor | 7 |

## Notes

- 20 demo modules and 213 application modules were scanned.
- Sibling applications pin older releases in their virtualenvs, so a name
  they use may have been renamed or removed since; the counts reflect the
  names as they exist in this tree.
- A count of one is usually an import; a count of many is real use.  The
  ratio between the two columns is the signal worth reading.
- A demo zero with an application count is not automatically a gap.  The
  applications pin older releases, and several still call the pre-3.0
  window-direct API (`win.add_body()`, a window passed where a `Screen` is
  wanted); those call sites are why `docs/DEMO-GAPS.md` checks the site,
  the spread and the replacement path before calling anything missing.

