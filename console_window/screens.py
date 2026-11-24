"""Screen base classes and the screen stack."""

from __future__ import annotations

import curses
import textwrap
from collections.abc import Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

from . import glyphs
from . import help as help_text
from .context import Context
from .header import HeaderLine, Span
from .spinner import OptionSpinner
from .window import _ViewState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .window import ConsoleWindow


class _AppLike(Protocol):
    win: ConsoleWindow


# One body row: plain text, or text paired with a curses attribute.
_LineItem = str | tuple[str, int | None]
# One header entry, or a specification of one or more of them.
_HeadSpec = str | HeaderLine | Iterable[str | HeaderLine] | None


HOME_ST = 0


class Screen(_ViewState):
    """One screen: its content, its pick/scroll position, and its draw code.

    A screen *is* its view state (it inherits `_ViewState`), so the window paints
    the live values.  The supported loop is::

        screen.clear()
        screen.draw_screen()
        win.render()
        key = win.prompt(seconds=0.5)
    """

    # Navigation control (override in subclasses)
    come_from_whitelist = None  # None = any screen, else a list of screen numbers
    is_terminal = False         # True = cannot be pushed onto the stack
    cannot_stack_me = False     # True = cannot have screens pushed on top

    # True on a screen that documents another screen.
    is_help_screen = False

    num: int | None = None
    stack: ScreenStack | None = None

    def __init__(self, app: _AppLike) -> None:
        super().__init__()
        self.app = app

    @property
    def win(self) -> ConsoleWindow:
        """The window this screen draws on, resolved at call time."""
        return self.app.win

    # --- content writers ---------------------------------------------------
    #
    # The only supported writers; each delegates with this screen's namespace,
    # so they work even before the screen is adopted.

    def add_header(self, text: str, attr: int | None = None, resume: bool = False,
                   context: Context | None = None) -> None:
        """Append one header row, or resume the current row when *resume* is set."""
        self.win._add(self.head, text, attr, resume, context, is_body=False)

    def add_body(self, text: str, attr: int | None = None, resume: bool = False,
                 context: Context | None = None) -> None:
        """Append one body row, or resume the current row when *resume* is set."""
        self.win._add(self.body, text, attr, resume, context, is_body=True)

    def add_fancy_header(self, line: str | HeaderLine, mode: str = 'Underline',
                         search_pattern_attr: int | None = None,
                         line_attr: int | None = None) -> None:
        """Append a header row from a markup string or explicit spans.

        A `str` *line* is scanned: a leading `^[\\w-]+$` word becomes `LABEL`;
        `[x]` becomes `KEY` without the brackets; `CAPS:` at a word start
        becomes `KEY`; `/pattern` becomes `SEARCH`.  A `HeaderLine` keeps its
        declared role for every span.

        Args:
            mode: `'Underline'` (default), `'Reverse'`, or `'Off'` for no
                scanning and no role styling.
            search_pattern_attr: Attribute for `SEARCH` spans; defaults to
                bold+reverse.
            line_attr: OR'd into every span, e.g. to dim the whole row.

        Use `add_header_line` to keep the text and brackets literal.
        """
        self.win._add_fancy_header(self.head, line, mode, search_pattern_attr,
                                   line_attr)

    def add_header_line(self, header_line: HeaderLine | Iterable[Span],
                        mode: str = 'Underline',
                        search_pattern_attr: int | None = None,
                        line_attr: int | None = None) -> None:
        """Append a header row from explicit spans, with no parsing at all.

        Every span's text and role is emitted as given; `bracket_key()` keeps
        its literal brackets.  `mode`, `search_pattern_attr` and `line_attr`
        are as in `add_fancy_header`.
        """
        self.win._add_header_line(self.head, header_line, mode,
                                  search_pattern_attr, line_attr)

    def add_prompt_header(self, attr: int | None = None,
                          align: str | None = None) -> bool:
        """Draw the active in-place prompt as a header row; False if inactive.

        Args:
            attr: Row attribute; `None` uses the window's prompt default.
            align: `'center'` to center the composed line.
        """
        return self.win._add_prompt_header(self.head, attr, align)

    def add_prompt_lines(self, attr: int | None = None,
                         hint_attr: int | None = None) -> bool:
        """Draw the active in-place prompt and hint as transient body rows."""
        return self.win._add_prompt_lines(self.body, attr, hint_attr)

    def clear(self) -> None:
        """Start a new content pass, handing this screen to the window.

        Content is reset; pick/scroll position, pick mode and `free_scroll`
        survive because they describe where the user is.
        """
        self.win._adopt_view(self)
        self.reset()

    def draw_screen(self) -> None:
        """Draw this screen's content.  Override; the base draws nothing."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """Paragraphs appended to this screen's help output, if it draws any."""
        return ()

    def on_pause(self) -> bool:
        """Veto hook for being covered by a push; False refuses the push."""
        return not self.cannot_stack_me

    def on_resume(self) -> bool:
        """Veto hook for becoming current again on pop; False refuses the pop."""
        return True

    def on_pop(self) -> bool:
        """Notification that this screen is being removed; the return is ignored."""
        return True

    def get_spinner(self) -> OptionSpinner | None:
        """The spinner injected into this screen's stack, or None."""
        stack = self.stack
        return None if stack is None else getattr(stack, 'spinner', None)

    def handle_action(self, action_name: str) -> bool:
        """Call `<action_name>_ACTION` if it exists; False when there is none."""
        method_name = f'{action_name}_ACTION'
        method = getattr(self, method_name, None)
        if method and callable(method):
            method()  # getattr + callable() proof is opaque to pylint's inference
            return True
        return False

    def escape_ACTION(self) -> None:
        """Default back action: pop one screen; a no-op on the home screen."""
        if self.stack is not None:
            self.stack.pop()

    def quit_ACTION(self) -> None:
        """Default quit action: leave the process (curses teardown is on atexit)."""
        raise SystemExit


class ScreenStack:
    """Screen numbers plus the objects behind them, with push/pop validation.

    Screens are numbered in declaration order, `HOME_ST` (0) first.
    A move can be refused by the outgoing screen's `on_pause()`,
    the incoming screen's `come_from_whitelist`/`is_terminal`, or a repeat push.
    `curr` is the live frame, and every owned `Screen` points back here.
    """

    def __init__(self, win: ConsoleWindow, spins_obj: object, screens: tuple,
                 screen_objects: dict[int, Screen] | None = None) -> None:
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        self.screen_objects: dict[int, Screen] = screen_objects or {}
        # Link each screen to its number and stack so it can find its spinner.
        for num, screen_obj in self.screen_objects.items():
            screen_obj.num = num
            screen_obj.stack = self
        self.spinner: OptionSpinner | None = None
        self.stack: list[SimpleNamespace] = []
        self.curr: SimpleNamespace | None = None
        self.push(HOME_ST, 0)

    @classmethod
    def from_screens(cls, win: ConsoleWindow, spins_obj: object,
                     screens: Iterable[Screen]) -> ScreenStack:
        """Build a stack from Screen objects, numbered in order.

        The first object is `HOME_ST` (0).  Names come from each object's
        `name` attribute, or its class name when it has none.
        """
        objects = list(screens)
        names = tuple(getattr(obj, 'name', None) or type(obj).__name__
                      for obj in objects)
        return cls(win, spins_obj, names, dict(enumerate(objects)))

    def _screen_index(self, screen: int | str | Screen) -> int:
        """Resolve a number, a screen name, or a Screen object to its number."""
        if isinstance(screen, int):
            return screen
        if isinstance(screen, str):
            try:
                return self.screens.index(screen)
            except ValueError:
                raise ValueError(f'no screen named {screen!r}') from None
        for num, obj in self.screen_objects.items():
            if obj is screen:
                return num
        raise ValueError(f'screen {screen!r} is not registered with this stack')

    def push(self, screen: int | str | Screen, prev_pos: int | None = None,
             force: bool = False) -> int | None:
        """Make *screen* current after the validation hooks.

        Args:
            screen: Screen number, screen name, or `Screen` object.
            prev_pos: Row the parent wants restored on pop; defaults to the
                window's current pick position.
            force: Skip the loop, whitelist and `on_pause()` checks.

        Returns 0 when the push happened, `None` when a hook refused it.
        """
        screen = self._screen_index(screen)
        if prev_pos is None:
            prev_pos = self.win.pick_pos

        if not force:
            if self._would_loop(screen) or not self._navigation_allowed(screen):
                return None
            if not self._pause_current():
                return None

        self._activate(screen, prev_pos)
        return 0

    def _would_loop(self, screen: int) -> bool:
        if self.curr and screen == self.curr.num:
            return True
        return any(stacked_screen.num == screen for stacked_screen in self.stack)

    def _navigation_allowed(self, screen: int) -> bool:
        new_screen_obj = self.screen_objects.get(screen) if self.screen_objects else None
        if not new_screen_obj:
            return True
        if new_screen_obj.is_terminal:
            return False
        if new_screen_obj.come_from_whitelist is None:
            return True
        from_screen_num = self.curr.num if self.curr else None
        return from_screen_num in new_screen_obj.come_from_whitelist

    def _pause_current(self) -> bool:
        if not (self.curr and self.screen_objects):
            return True
        current_screen_obj = self.screen_objects.get(self.curr.num)
        return current_screen_obj.on_pause() if current_screen_obj else True

    def _activate(self, screen: int, prev_pos: int) -> None:
        if self.curr:
            # The outgoing screen owns its position; the frame remembers prev_pos.
            self.curr.prev_pos = prev_pos
            self.stack.append(self.curr)
        self.curr = SimpleNamespace(num=screen, name=self.screens[screen],
                                    prev_pos=-1)
        self.win._adopt_view(self._view_for(screen))

    def _view_for(self, screen: int) -> _ViewState:
        """The view state for *screen*: its Screen, or the window fallback.

        The fallback is reset on activation, so entering a bare-number screen
        starts at the top; a real Screen keeps its own position.
        """
        obj = self.screen_objects.get(screen) if self.screen_objects else None
        if obj is not None:
            return obj
        view = self.win._fallback_view
        view.pick_pos = view.scroll_pos = 0
        view.free_scroll = False
        return view

    def get_curr_obj(self) -> Screen | None:
        """The `Screen` for the current frame, or None for bare-number stacks."""
        if self.curr:
            return self.screen_objects.get(self.curr.num, None)
        return None

    def pop(self, force: bool = False) -> int | None:
        """Pop the current frame and report where the parent wants to be.

        Returns the restored frame's `prev_pos`, or `None` on the home screen.

        Args:
            force: Skip `on_pop()`/`on_resume()`, so no veto is honored.
        """
        if not self.stack:
            return None

        to_screen_num = self.stack[-1].num

        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(self.curr.num)
            if current_screen_obj:
                current_screen_obj.on_pop()

        if not force and self.screen_objects:
            prev_screen_obj = self.screen_objects.get(to_screen_num)
            if prev_screen_obj:
                if not prev_screen_obj.on_resume():
                    # Previous screen rejected resuming (rare, but allowed)
                    return None

        self.curr = self.stack.pop()
        self.win._adopt_view(self._view_for(self.curr.num))
        return self.curr.prev_pos

    def is_curr(self, screens: int | str | list | tuple | set) -> bool:
        """True when the current screen is (one of) *screens*."""
        curr = self.curr
        if curr is None:
            return False

        def test_one(screen: int | str) -> bool:
            if isinstance(screen, int):
                return screen == curr.num
            return str(screen) == curr.name
        if isinstance(screens, (tuple, list, set)):
            return any(test_one(screen) for screen in screens)
        return test_one(screen=screens)

    def act_in(self, action: str, screens: int | str | list | tuple | set | None = None) -> bool:
        """Consume one boolean action flag from `self.obj`.

        The flag is cleared even when *screens* does not match, preserving the
        one-shot semantics; an unset flag reads as `False`.
        """
        if not hasattr(self.obj, action):
            return False
        val = getattr(self.obj, action)
        setattr(self.obj, action, False)
        return bool(val) and (screens is None or self.is_curr(screens))

    def perform_actions(self, spinner: OptionSpinner) -> int:
        """Run the `*_ACTION` handlers whose flags are set, then clear them.

        Args:
            spinner: Supplies the action options; `effective_scope`, when
                present, restricts an action to the listed screens.
        """
        if self.curr is None:
            return 0
        current_screen = self.screen_objects.get(self.curr.num)
        if not current_screen:
            return 0

        actions_performed = 0

        for option_ns in spinner.options:
            if option_ns.genre == 'action':
                action_name = option_ns.attr

                if hasattr(option_ns, 'effective_scope'):
                    if self.curr.num not in option_ns.effective_scope:
                        if hasattr(option_ns.obj, action_name):
                            setattr(option_ns.obj, action_name, False)
                        continue

                if hasattr(option_ns.obj, action_name):
                    action_value = getattr(option_ns.obj, action_name, False)

                    # Clear even an unset flag so a delayed read cannot fire it.
                    setattr(option_ns.obj, action_name, False)

                    if action_value:
                        method_name = f'{action_name}_ACTION'
                        method = getattr(current_screen, method_name, None)
                        if method and callable(method):
                            method()
                            actions_performed += 1

        return actions_performed


class BasicHelpScreen(Screen):
    """Help page: navigation keys, the spinner's option body, notes, fonts.

    Each section's heading, bullet and visibility are class attributes, so a
    subclass overrides them rather than the draw method.
    """

    is_help_screen = True
    # None follows the window option; True/False forces the Font Check section.
    font_section: bool | None = None
    # Resolved once per visit so a redraw cannot change the page.
    _fonts_mode_cache: str | None = None
    # '' drops the centered heading and keeps the advice and sample rows.
    fonts_title = '- Font Check -'

    # '' drops the underlined heading and keeps only the paragraphs.
    notes_title = 'Notes:'

    # Three cells wide; wrapped rows align under it.
    notes_bullet = ' \u25c6 '

    def draw_screen(self) -> None:
        """Draw the whole page; nothing here is pickable."""
        self.set_pick_mode(False)
        spinner = self.get_spinner()
        if spinner:
            spinner.show_help_nav_keys(self)
            spinner.show_help_body(self)
        self.draw_notes()
        self.draw_fonts()

    def draw_notes(self) -> None:
        """Append the app's paragraphs as bulleted prose in the normal attribute."""
        paragraphs = list(self.extra_help_paragraphs())
        if not paragraphs:
            return
        if self.notes_title:
            self.add_body(self.notes_title, curses.A_UNDERLINE)
        indent = ' ' * len(self.notes_bullet)
        width = max(getattr(self.win, 'cols', 80) - 8 - len(indent), 20)
        for paragraph in paragraphs:
            for number, line in enumerate(textwrap.wrap(paragraph, width=width)):
                prefix = self.notes_bullet if number == 0 else indent
                self.add_body(prefix + line)

    def draw_fonts(self) -> None:
        """Append the built-in font check: what to install, then the sample rows.

        The section is `FONT_CHECK_ROW_WIDTH` cells wide and centered when the
        terminal is wider, so the alignment means the same thing everywhere.
        Lines are never folded: on a narrower terminal they run past the edge.
        """
        if self._fonts_mode() == 'none':
            return
        width = glyphs.FONT_CHECK_ROW_WIDTH
        pad_width = self.win.get_pad_width()
        indent = ' ' * max((pad_width - width) // 2, 0)
        self.add_body('')
        if self.fonts_title:
            self.add_body(indent + self.fonts_title.center(
                min(width, pad_width)).rstrip())
        if getattr(self.win, 'ascii_mode', glyphs.is_ascii()):
            self._add_font_lines(help_text.FONT_ASCII, indent)
            return
        self._add_font_lines(help_text.FONT_ADVICE, indent)
        for row in glyphs.font_check_rows():
            self.add_body(indent + row)
        missing = glyphs.font_missing()
        if missing:
            names = ', '.join(entry.name for entry in missing)
            message = f'Registered, but not in the reference fonts: {names}.'
            room = max(pad_width - len(indent), 20)
            self._add_font_lines(textwrap.wrap(message, width=room), indent)

    def _add_font_lines(self, lines: Iterable[str], indent: str) -> None:
        for line in lines:
            self.add_body(indent + line)

    def on_pop(self) -> bool:
        """Forget the resolved Fonts mode so the next visit resolves it afresh."""
        self._fonts_mode_cache = None
        return super().on_pop()

    def _fonts_mode(self) -> str:
        """Return 'full' or 'none' for this help page (once per visit)."""
        if self._fonts_mode_cache is None:
            self._fonts_mode_cache = self._resolve_fonts_mode()
        return self._fonts_mode_cache

    def _resolve_fonts_mode(self) -> str:
        if self.font_section is not None:
            return 'full' if self.font_section else 'none'
        opts = getattr(self.win, 'opts', None)
        mode = getattr(opts, 'help_fonts', 'once')
        if mode == 'never':
            return 'none'
        if mode == 'always':
            return 'full'
        if getattr(self.win, '_help_fonts_shown', False):
            return 'none'
        try:
            self.win._help_fonts_shown = True
        except AttributeError:
            return 'full'
        return 'full'


class BasicTextScreen(Screen):
    """Read-only screen showing preformatted lines under optional headers.

    There is no pick mode, no action handling and no spinner; ESC/back stays
    the application's `escape_ACTION`.
    """

    come_from_whitelist = None

    def __init__(self, app: _AppLike, lines: Iterable[_LineItem] = (),
                 head: _HeadSpec = ()) -> None:
        super().__init__(app)
        self._lines: list[tuple[str, int | None]] = []
        self._heads: list[str | HeaderLine] = []
        self.set_text(lines, head)

    def set_text(self, lines: Iterable[_LineItem] = (),
                 head: _HeadSpec = ()) -> None:
        """Replace the screen's content.  Safe before or after the first draw.

        Args:
            lines: `str` items, or `(text, attr)` pairs.
            head: A `str`, a `HeaderLine`, or an iterable of either.
        """
        self._lines = [self._normalize_line(item) for item in (lines or ())]
        self._heads = self._normalize_heads(head)

    @staticmethod
    def _normalize_line(item: _LineItem) -> tuple[str, int | None]:
        if isinstance(item, str):
            return item, None
        text, attr = item
        return str(text), attr

    @staticmethod
    def _normalize_heads(head: _HeadSpec) -> list[str | HeaderLine]:
        if head is None:
            return []
        if isinstance(head, (str, HeaderLine)):
            return [head]
        return list(head)

    def draw_screen(self) -> None:
        """Draw the heads first, then the content rows in order."""
        self.set_pick_mode(False)
        for head_item in self._heads:
            if isinstance(head_item, HeaderLine):
                # Keep the declared span roles; add_header() takes plain text.
                self.add_header_line(head_item)
            else:
                self.add_header(head_item)
        for text, attr in self._lines:
            self.add_body(text, attr=attr)
