from __future__ import annotations

import curses
import textwrap
from collections.abc import Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

from . import help as help_text
from .context import Context
from .header import HeaderLine, Span
from .spinner import OptionSpinner
from .window import _ViewState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .window import ConsoleWindow


class _AppLike(Protocol):
    # The only part of the host application a Screen touches at construction.
    win: ConsoleWindow


#: One body row: plain text, or text paired with a curses attribute.
_LineItem = str | tuple[str, int | None]
#: One header entry, or a specification of one or more of them.
_HeadSpec = str | HeaderLine | Iterable[str | HeaderLine] | None


# Default home screen constant (applications should define their own)
HOME_ST = 0


class Screen(_ViewState):
    """One screen: its content, its pick/scroll position, and its draw code.

    A screen *is* its view state: it inherits the package-private ``_ViewState``,
    so ``screen.pick_pos`` and ``screen.free_scroll`` are the live values the
    window paints from and no copy happens when the stack activates it.

    Content is written with ``add_header()``/``add_body()`` and friends.  The
    supported loop is::

        screen.clear()        # content reset for the new pass
        screen.draw_screen()  # add_header()/add_body() only
        win.render()          # paint + doupdate()
        key = win.prompt(seconds=0.5)
    """

    # Navigation control (class attributes - override in subclasses)
    come_from_whitelist = None  # None = can come from any screen, else list of screen numbers
    is_terminal = False         # True = cannot be pushed onto stack
    cannot_stack_me = False     # True = cannot have other screens pushed on top

    def __init__(self, app: _AppLike) -> None:
        super().__init__()
        self.app = app  # Reference to main application instance
        self._cached_spinner: OptionSpinner | None = None  # Lazy-loaded spinner reference

    @property
    def win(self) -> ConsoleWindow:
        """The window this screen draws on, resolved at call time.

        Applications may construct their Screen objects before the
        ConsoleWindow exists, so this cannot be cached in ``__init__``.
        """
        return self.app.win

    # --- content writers ---------------------------------------------------
    #
    # These are the only supported writers.  They delegate to the window's
    # private implementation with *this screen's* namespace, so they are
    # correct even before the screen is adopted (the loop's clear() adopts it).

    def add_header(self, text: str, attr: int | None = None, resume: bool = False,
                   context: Context | None = None) -> None:
        """Append one header row (or resume the current one, on the same row)."""
        self.win._add(self.head, text, attr, resume, context, is_body=False)

    def add_body(self, text: str, attr: int | None = None, resume: bool = False,
                 context: Context | None = None) -> None:
        """Append one body row (or resume the current one, on the same row)."""
        self.win._add(self.body, text, attr, resume, context, is_body=True)

    def add_fancy_header(self, line: str | HeaderLine, mode: str = 'Underline',
                         search_pattern_attr: int | None = None,
                         line_attr: int | None = None) -> None:
        """Add a header line with legacy ``[x]``/``KEY:``/``/pattern`` markup."""
        self.win._add_fancy_header(self.head, line, mode, search_pattern_attr,
                                   line_attr)

    def add_header_line(self, header_line: HeaderLine | Iterable[Span],
                        mode: str = 'Underline',
                        search_pattern_attr: int | None = None,
                        line_attr: int | None = None) -> None:
        """Render explicit header spans; see :meth:`add_fancy_header`."""
        self.win._add_header_line(self.head, header_line, mode,
                                  search_pattern_attr, line_attr)

    def add_prompt_header(self, attr: int | None = None,
                          align: str | None = None) -> bool:
        """Draw the active in-place prompt as a header row; False if inactive."""
        return self.win._add_prompt_header(self.head, attr, align)

    def add_prompt_lines(self, attr: int | None = None,
                         hint_attr: int | None = None) -> bool:
        """Draw the active in-place prompt and hint as transient body rows."""
        return self.win._add_prompt_lines(self.body, attr, hint_attr)

    def clear(self) -> None:
        """Start a new content pass on this screen.

        This is the loop's first call, and its other job is to hand the screen
        to the window (``_adopt_view``): the window cannot discover a Model A
        screen on its own, and every later ``add_*()``/``render()`` in the pass
        depends on the window already pointing at this screen.

        Content is reset; the pick/scroll position, the pick mode and
        ``free_scroll`` are not -- they describe where the user is in this
        screen and must survive a rebuild.
        """
        self.win._adopt_view(self)
        self.reset()

    def draw_screen(self) -> None:
        pass

    def extra_help_paragraphs(self) -> Iterable[str]:
        """Paragraphs appended to this screen's help output, if it draws any.

        An app that owns a feature worth explaining returns its paragraphs here
        (``help.theme_paragraph()``, its own prose) and lets ``BasicHelpScreen``
        do the wrapping and dimming.  The default is empty, so an app that says
        nothing keeps its exact output.
        """
        return ()

    def on_pause(self) -> bool:
        return not self.cannot_stack_me

    def on_resume(self) -> bool:
        return True

    def on_pop(self) -> bool:
        return True

    def get_spinner(self) -> OptionSpinner | None:
        # Return cached spinner if already found
        if self._cached_spinner is not None:
            return self._cached_spinner

        # Search through app's attributes for an OptionSpinner instance
        for attr_name in dir(self.app):
            if not attr_name.startswith('_'):  # Skip private attributes
                try:
                    attr_value = getattr(self.app, attr_name)
                    if isinstance(attr_value, OptionSpinner):
                        self._cached_spinner = attr_value
                        return attr_value
                except (AttributeError, TypeError):
                    continue

        # Not found - return None (don't cache to allow retry)
        return None

    def handle_action(self, action_name: str) -> bool:
        method_name = f'{action_name}_ACTION'
        method = getattr(self, method_name, None)
        if method and callable(method):
            # pylint: disable-next=not-callable
            method()  # getattr + callable() proof is opaque to pylint's inference
            return True
        return False


class ScreenStack:
    def __init__(self, win: ConsoleWindow, spins_obj: object, screens: tuple,
                 screen_objects: dict[int, Screen] | None = None) -> None:
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        # Dict of screen_num -> Screen instance
        self.screen_objects: dict[int, Screen] = screen_objects or {}
        self.stack: list[SimpleNamespace] = []
        self.curr: SimpleNamespace | None = None
        # Push home screen (HOME_ST=0) as the initial screen
        self.push(HOME_ST, 0)

    @classmethod
    def from_screens(cls, win: ConsoleWindow, spins_obj: object,
                     screens: Iterable[Screen]) -> ScreenStack:
        """Build a stack from Screen objects, numbered in order.

        The first object is ``HOME_ST`` (0) and becomes active immediately.
        Names come from each object's ``name`` attribute, or its class name
        when it has none, so ``is_curr('ONE')`` works without also maintaining
        a parallel names tuple.  This is the short form of the original
        ``ScreenStack(win, obj, names, {num: screen})`` construction.
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
        screen = self._screen_index(screen)
        if prev_pos is None:
            prev_pos = self.win.pick_pos

        # Validation hooks are skipped entirely when forced.
        if not force:
            if self._would_loop(screen) or not self._navigation_allowed(screen):
                return None
            # Current screen gets a veto via on_pause() (it's being covered)
            if not self._pause_current():
                return None

        # Navigation approved - proceed
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
            # The outgoing screen owns its pick/scroll state, so the frame only
            # remembers the row the *parent* asked us to return to.
            self.curr.prev_pos = prev_pos
            self.stack.append(self.curr)
        self.curr = SimpleNamespace(num=screen, name=self.screens[screen],
                                    prev_pos=-1)
        self.win._adopt_view(self._view_for(screen))

    def _view_for(self, screen: int) -> _ViewState:
        """The view state for *screen*: its Screen, or the window fallback.

        A ``ScreenStack`` built from bare numbers has no Screen objects, so
        the window-owned fallback view carries the state instead.  It is reset
        on activation to reproduce the old "entering a screen starts at the
        top" behavior; a real Screen keeps its own position.
        """
        obj = self.screen_objects.get(screen) if self.screen_objects else None
        if obj is not None:
            return obj
        view = self.win._fallback_view  # pylint: disable=protected-access
        view.pick_pos = view.scroll_pos = 0
        view.free_scroll = False
        return view

    def get_curr_obj(self) -> Screen | None:
        if self.curr:
            return self.screen_objects.get(self.curr.num, None)
        return None

    def pop(self, force: bool = False) -> int | None:
        if not self.stack:
            return None

        to_screen_num = self.stack[-1].num

        # Call on_pop() on current screen (it's being removed - always succeeds)
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(self.curr.num)
            if current_screen_obj:
                current_screen_obj.on_pop()  # Always called, cannot reject

        # Call on_resume() on the screen we're returning to
        if not force and self.screen_objects:
            prev_screen_obj = self.screen_objects.get(to_screen_num)
            if prev_screen_obj:
                if not prev_screen_obj.on_resume():
                    # Previous screen rejected resuming (rare, but allowed)
                    return None

        # Navigation approved - proceed: the restored screen already holds its
        # own pick/scroll state, so activation is just a pointer swap.
        self.curr = self.stack.pop()
        self.win._adopt_view(self._view_for(self.curr.num))
        return self.curr.prev_pos

    def is_curr(self, screens: int | str | list | tuple | set) -> bool:
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
        """Consume one boolean action flag from ``self.obj``.

        This is the single-action, caller-dispatched companion to
        ``perform_actions()``: it clears the flag and reports whether it fired
        while *screens* was current.  A flag that was never set reads as
        ``False`` instead of raising ``AttributeError``, so an options object
        need not pre-seed every action.  The flag is consumed even when the
        screen does not match, preserving the one-shot semantics.
        """
        if not hasattr(self.obj, action):
            return False
        val = getattr(self.obj, action)
        setattr(self.obj, action, False)
        return bool(val) and (screens is None or self.is_curr(screens))

    def perform_actions(self, spinner: OptionSpinner) -> int:
        if self.curr is None:
            return 0
        current_screen = self.screen_objects.get(self.curr.num)
        if not current_screen:
            return 0  # No screen object to handle actions

        actions_performed = 0

        # Loop through ALL action options from the spinner
        for option_ns in spinner.options:
            if option_ns.genre == 'action':
                action_name = option_ns.attr

                # Check if this action is scoped to the current screen
                if hasattr(option_ns, 'effective_scope'):
                    if self.curr.num not in option_ns.effective_scope:
                        # This action is not valid for the current screen - skip it
                        # But still clear the flag if it was set
                        if hasattr(option_ns.obj, action_name):
                            setattr(option_ns.obj, action_name, False)
                        continue

                # Check if this action flag is set
                if hasattr(option_ns.obj, action_name):
                    action_value = getattr(option_ns.obj, action_name, False)

                    # ALWAYS clear the flag (prevents delayed/unexpected effects)
                    setattr(option_ns.obj, action_name, False)

                    # Only call the handler if the flag was set AND the method exists
                    if action_value:
                        method_name = f'{action_name}_ACTION'
                        method = getattr(current_screen, method_name, None)
                        if method and callable(method):
                            method()
                            actions_performed += 1

        return actions_performed


class BasicHelpScreen(Screen):
    #: Append the built-in display notes -- a font check in Unicode mode, and
    #: how to get the full set back in ASCII mode -- after the app's paragraphs.
    #: Off by default: an existing help screen must not gain a line merely by
    #: upgrading the library.  Turn it on with ``show_display_notes = True``.
    show_display_notes = False

    def draw_screen(self) -> None:
        # The screen draws itself: pick mode is its own, and every writer below
        # targets this screen's content, so no window handle is resolved here.
        self.set_pick_mode(False)
        spinner = self.get_spinner()
        if spinner:
            spinner.show_help_nav_keys(self)
            spinner.show_help_body(self)
        self.draw_notes()

    def draw_notes(self) -> None:
        """Append the app's paragraphs and the display notes, dim and wrapped.

        A method rather than inline code so a subclass can add its own notes
        and still get the wrapping, the indent, and the ``A_DIM`` attribute
        from one place.
        """
        paragraphs = list(self.extra_help_paragraphs())
        if self.show_display_notes:
            # The window answers ``ascii_mode``; that is a terminal property,
            # not a screen one.
            paragraphs.append(help_text.glyph_paragraph(self.win))
        width = max(getattr(self.win, 'cols', 80) - 8, 20)
        for paragraph in paragraphs:
            for line in textwrap.wrap(paragraph, width=width):
                self.add_body(line, attr=curses.A_DIM)


class BasicTextScreen(Screen):
    """Read-only screen showing preformatted lines under optional headers.

    The window is resolved at draw time: applications may build their Screen
    objects before the ConsoleWindow exists (BasicHelpScreen relies on the same
    rule).  ``lines`` items are ``str`` or ``(str, attr)``; ``head`` is a
    ``str``, a :class:`HeaderLine`, or an iterable of either.  Content is
    normalized by :meth:`set_text`, so ``draw_screen()`` is a flat loop and
    nothing is cached across draws.

    There is no pick mode, no action handling and no spinner.  ESC/back stays
    the application's ``escape_ACTION``, and ``come_from_whitelist`` stays
    permissive by default.
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
        """Replace the screen's content.  Safe before or after the first draw."""
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
        self.set_pick_mode(False)
        for head_item in self._heads:
            if isinstance(head_item, HeaderLine):
                # Keep the declared span roles; add_header() takes plain text.
                self.add_header_line(head_item)
            else:
                self.add_header(head_item)
        for text, attr in self._lines:
            # No Context: these are plain, scrollable rows (the same shape
            # ViewScreen/CompareScreen produced before this helper existed).
            self.add_body(text, attr=attr)
