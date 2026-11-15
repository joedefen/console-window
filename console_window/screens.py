from __future__ import annotations

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

    #: True on a screen that documents another screen.  The spinner then lists
    #: the pushed screen's value keys here and keeps them live, so a value can
    #: be changed without backing out.  ``BasicHelpScreen`` sets this; see
    #: ``OptionSpinner.help_subject()``.
    is_help_screen = False

    #: Assigned by the owning ScreenStack when the stack is constructed.  A
    #: screen built without a stack keeps ``None`` for both.
    num: int | None = None
    stack: ScreenStack | None = None

    def __init__(self, app: _AppLike) -> None:
        super().__init__()
        self.app = app  # Reference to main application instance

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
        """Append one header row (or resume the current one, on the same row).

        Args:
            text: Row text, written verbatim.
            attr: Row attribute, or ``None`` for the plain/role default.
            resume: Continue the current row instead of starting a new one.
            context: Pick metadata for the row, or ``None``.
        """
        self.win._add(self.head, text, attr, resume, context, is_body=False)

    def add_body(self, text: str, attr: int | None = None, resume: bool = False,
                 context: Context | None = None) -> None:
        """Append one body row (or resume the current one, on the same row).

        Args:
            text: Row text, written verbatim.
            attr: Row attribute, or ``None`` for the plain default.
            resume: Continue the current row instead of starting a new one.
            context: Pick metadata (genre, pickable, abut), or ``None``.
        """
        self.win._add(self.body, text, attr, resume, context, is_body=True)

    def add_fancy_header(self, line: str | HeaderLine, mode: str = 'Underline',
                         search_pattern_attr: int | None = None,
                         line_attr: int | None = None) -> None:
        """Append a header row, optionally scanning the legacy text markup.

        *line* is either of the two accepted header forms:

        ``str`` -- the legacy (or "simple") form.  Its text is scanned for the
        markup described below.  This is what older applications wrote, and it
        is still the shortest spelling for a one-off legend.

        :class:`HeaderLine` (or any iterable of :class:`Span`) -- the newer
        form.  Roles are declared by the builder (``text()``, ``key()``,
        ``bracket_key()``, ``label()``, ``search()``) and are never re-guessed
        from the text.  The one markup rule that still applies is
        ``bracket_key()``'s pair of literal ``[``/``]``: in every mode except
        ``'Off'`` those delimiters are removed and the enclosed key keeps its
        ``KEY`` styling.  Use :meth:`add_header_line` to keep them verbatim.

        *mode* selects how span roles are emphasized.  It is a case-sensitive
        string with three recognized values:

        ``'Underline'`` (default) -- ``KEY`` is underlined and bold, ``LABEL``
        is bold, and ``SEARCH`` uses *search_pattern_attr* (or bold+reverse).

        ``'Reverse'`` -- the same, except ``KEY`` is reverse video instead of
        underlined.  Because the renderer only special-cases ``'Off'`` and
        ``'Underline'``, any other spelling also lands here (``'reverse'``
        works); prefer the capitalized form.

        ``'Off'`` -- no role styling at all: ``LABEL``, ``KEY`` and ``SEARCH``
        are all plain.  For a ``str`` *line* the markup is not scanned either,
        so the text is emitted exactly as written; a ``HeaderLine`` keeps its
        span split and its ``bracket_key()`` delimiters.  Only *line_attr*
        still styles the line's own spans, so an "off" line can still be
        dimmed.

        Legacy string markup (``str`` input, and never in ``'Off'`` mode):

        * the first word, if it is a word of letters/digits/underscores and
          hyphens (``^[\\w-]+$``), is the title and is styled as ``LABEL``
          (bold) -- any case, not just capitals;
        * ``[x]`` anywhere in the text styles the single character ``x`` as
          ``KEY`` and removes the brackets;
        * a run of ASCII capitals followed by ``:``, at the start of the line
          or after a space, styles that run as ``KEY`` (case-sensitive, so
          ``q:`` stays plain);
        * ``/text`` at the start of the line or after a space is a ``SEARCH``
          span, slash included, ending at the next whitespace.

        *search_pattern_attr* overrides the attribute used for ``SEARCH``
        spans, which otherwise default to ``curses.A_BOLD | curses.A_REVERSE``.
        It is ignored in ``'Off'`` mode, where no role is styled.

        *line_attr* is OR'd into every span's attribute, including ``PLAIN``
        spans and the raw line emitted for ``mode='Off'``.  It therefore lets
        a caller dim a whole header (``line_attr=curses.A_DIM``) while keeping
        each span's own bold/underline/reverse styling.

        See also :meth:`add_header_line`, the variant that renders explicit
        spans with neither scanning nor bracket elision.
        """
        self.win._add_fancy_header(self.head, line, mode, search_pattern_attr,
                                   line_attr)

    def add_header_line(self, header_line: HeaderLine | Iterable[Span],
                        mode: str = 'Underline',
                        search_pattern_attr: int | None = None,
                        line_attr: int | None = None) -> None:
        """Append a header row from explicit spans, with no parsing at all.

        This is the newer, less parsed form: every span's ``text`` and ``role``
        is emitted exactly as given.  In particular, ``HeaderLine``'s
        ``bracket_key()`` keeps its literal ``[``/``]`` here, whereas
        :meth:`add_fancy_header` treats those delimiters as markup and removes
        them.  No role is ever inferred from the text, so a leading title word,
        a ``KEY:`` spelling or a ``/pattern`` is styled only if the caller
        declared the matching role.

        *mode* is one of the three values documented on
        :meth:`add_fancy_header`: ``'Underline'`` (default) underlines keys,
        ``'Reverse'`` reverses them, and ``'Off'`` applies no role styling at
        all.  In ``'Off'`` mode only *line_attr* still styles the spans.

        *search_pattern_attr* overrides the ``SEARCH`` span attribute (default
        ``curses.A_BOLD | curses.A_REVERSE``) and is ignored in ``'Off'`` mode.
        *line_attr* is OR'd into every span's attribute, including ``PLAIN``
        spans, so the whole row can be dimmed without losing the role styling.

        Use this method when the text must stay literal (paths, sample markup,
        or brackets a user should see) or when the roles are already known and
        re-parsing would be lossy.
        """
        self.win._add_header_line(self.head, header_line, mode,
                                  search_pattern_attr, line_attr)

    def add_prompt_header(self, attr: int | None = None,
                          align: str | None = None) -> bool:
        """Draw the active in-place prompt as a header row; False if inactive.

        Args:
            attr: Row attribute, or ``None`` for the window's prompt default.
            align: ``'center'`` centers the composed line; ``None`` left-aligns.
        """
        return self.win._add_prompt_header(self.head, attr, align)

    def add_prompt_lines(self, attr: int | None = None,
                         hint_attr: int | None = None) -> bool:
        """Draw the active in-place prompt and hint as transient body rows.

        Args:
            attr: Attribute for the prompt row, or ``None`` for the default.
            hint_attr: Attribute for the hint row, or ``None`` for its default.
        """
        return self.win._add_prompt_lines(self.body, attr, hint_attr)

    def clear(self) -> None:
        """Start a new content pass on this screen.

        This is the loop's first call, and its other job is to hand the screen
        to the window (``_adopt_view``): the window cannot discover a screen on
        its own, and every later ``add_*()``/``render()`` in the pass depends on
        the window already pointing at this screen.

        Content is reset; the pick/scroll position, the pick mode and
        ``free_scroll`` are not -- they describe where the user is in this
        screen and must survive a rebuild.
        """
        self.win._adopt_view(self)
        self.reset()

    def draw_screen(self) -> None:
        """Draw this screen's content.  Override; the base draws nothing."""

    def extra_help_paragraphs(self) -> Iterable[str]:
        """Paragraphs appended to this screen's help output, if it draws any.

        An app that owns a feature worth explaining returns its paragraphs here
        (``help.theme_paragraph()``, its own prose) and lets ``BasicHelpScreen``
        do the separator, the bullet and the hanging-indent wrapping.  The
        default is empty, so an app that says nothing keeps its exact output.
        """
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
        """The spinner injected into this screen's stack, or None.

        Injection (``stack.spinner``) replaces the old scan of the app's
        attributes: a screen built without a stack has no spinner, and a screen
        whose stack has none simply draws without the option body.
        """
        stack = self.stack
        return None if stack is None else getattr(stack, 'spinner', None)

    def handle_action(self, action_name: str) -> bool:
        """Call ``<action_name>_ACTION`` if it exists; False when there is none.

        Args:
            action_name: Bare action name, without the ``_ACTION`` suffix.
        """
        method_name = f'{action_name}_ACTION'
        method = getattr(self, method_name, None)
        if method and callable(method):
            # pylint: disable-next=not-callable
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

    Screens are numbered in declaration order, ``HOME_ST`` (0) first.  A move
    can be refused by the outgoing screen's ``on_pause()``, the incoming
    screen's ``come_from_whitelist``/``is_terminal``, or a repeat push.
    ``curr`` is the live frame, and every owned ``Screen`` points back here.
    """

    def __init__(self, win: ConsoleWindow, spins_obj: object, screens: tuple,
                 screen_objects: dict[int, Screen] | None = None) -> None:
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        # Dict of screen_num -> Screen instance
        self.screen_objects: dict[int, Screen] = screen_objects or {}
        # Number and link the screens this stack owns, so a Screen can find its
        # own number, its stack, and (through it) the injected spinner.
        for num, screen_obj in self.screen_objects.items():
            screen_obj.num = num
            screen_obj.stack = self
        self.spinner: OptionSpinner | None = None
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
        """Make *screen* current after the validation hooks.

        Args:
            screen: Screen number, screen name, or ``Screen`` object.
            prev_pos: Row the parent wants restored on pop; defaults to the
                window's current pick position.
            force: Skip the loop, whitelist and ``on_pause()`` checks.

        Returns:
            0 when the push happened, ``None`` when a hook refused it.
        """
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
        """The ``Screen`` for the current frame, or None for bare-number stacks."""
        if self.curr:
            return self.screen_objects.get(self.curr.num, None)
        return None

    def pop(self, force: bool = False) -> int | None:
        """Pop the current frame and report where the parent wants to be.

        Args:
            force: Skip ``on_pop()``/``on_resume()``, so no veto is honored.

        Returns:
            The restored frame's ``prev_pos``, or ``None`` on the home screen.
        """
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
        """True when the current screen is (one of) *screens*.

        Args:
            screens: A screen number, a screen name, or an iterable of either.
        """
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
        """Run the ``*_ACTION`` handlers whose flags are set, then clear them.

        Args:
            spinner: Supplies the action options; each option's ``obj`` holds
                its flag, and ``effective_scope`` (when present) restricts the
                action to the listed screens.

        Returns:
            How many handlers were called.
        """
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
    """Help page: navigation keys, the spinner's option body, notes, fonts.

    Content comes from the injected spinner
    (``show_help_nav_keys()``/``show_help_body()``), the app's
    ``extra_help_paragraphs()``, and the built-in font check.  Each section's
    separator, bullet and visibility are class attributes, so a subclass
    overrides them rather than the draw method; ``is_help_screen`` tells the
    window that this page describes the screen it was pushed from.
    """

    #: The help body describes the screen this one was pushed from, not itself.
    is_help_screen = True
    #: Per-screen override of ``ConsoleWindowOpts(help_fonts=...)``: ``None``
    #: follows the window's option, ``True`` always shows the full Fonts
    #: section, ``False`` never shows it.
    font_section: bool | None = None
    #: The rows of the Fonts section resolve once per screen instance: a redraw
    #: must not change the page under the user.
    _fonts_mode_cache: str | None = None
    #: Row that introduces the Fonts section.  Set it to '' to drop the
    #: separator and keep only the sample rows and the advice.
    fonts_separator = '---------- Fonts ----------'
    #: Narrowest body the sample rows are drawn in.  The rows are a fixed
    #: :data:`glyphs.FONT_CHECK_ROW_WIDTH` cells wide, so a narrower body would
    #: wrap them and destroy the alignment check; the section says so instead.
    fonts_min_width = glyphs.FONT_CHECK_ROW_WIDTH

    #: Row that introduces the extra help, separating it from the key list
    #: above.  Set it to '' to drop the separator and keep only the paragraphs.
    notes_separator = '---------- Instructions ----------'

    #: First-row prefix of an extra-help paragraph; the wrapped rows are
    #: indented to line up under it.  Three cells wide by design.  The plain
    #: ``\u25c6`` is downgraded to its ASCII spelling by the window when the
    #: terminal cannot draw it.
    notes_bullet = ' \u25c6 '

    def draw_screen(self) -> None:
        """Draw the whole page; pick mode is off because nothing here is pickable."""
        # The screen draws itself: pick mode is its own, and every writer below
        # targets this screen's content, so no window handle is resolved here.
        self.set_pick_mode(False)
        spinner = self.get_spinner()
        if spinner:
            spinner.show_help_nav_keys(self)
            spinner.show_help_body(self)
        self.draw_notes()
        self.draw_fonts()

    def draw_notes(self) -> None:
        """Append the app's paragraphs as bulleted prose.

        A method rather than inline code so a subclass can add its own notes
        and still get the separator, the bullet, the hanging indent and the
        wrapping from one place.  The prose is drawn in the normal attribute:
        these are instructions the user is meant to read, not dimmed fine print.
        """
        paragraphs = list(self.extra_help_paragraphs())
        if not paragraphs:
            return
        if self.notes_separator:
            self.add_body(self.notes_separator)
        indent = ' ' * len(self.notes_bullet)
        width = max(getattr(self.win, 'cols', 80) - 8 - len(indent), 20)
        for paragraph in paragraphs:
            for number, line in enumerate(textwrap.wrap(paragraph, width=width)):
                prefix = self.notes_bullet if number == 0 else indent
                self.add_body(prefix + line)

    def draw_fonts(self) -> None:
        """Append the built-in font check: every symbol, then what to install.

        The rows are the real Unicode symbols, which in ASCII mode would be
        pointless -- every cell is plain ASCII there -- so the section collapses
        to one sentence instead.  Nothing here queries fonts: the advice is
        unconditional, and a registration's font note is recorded by
        :mod:`console_window.fonts` before the page is ever drawn.

        With the default ``help_fonts='once'`` the section is drawn on the
        window's first help page only; later help pages do not mention it.
        """
        if self._fonts_mode() == 'none':
            return
        if self.fonts_separator:
            self.add_body(self.fonts_separator)
        width = max(getattr(self.win, 'cols', 80) - 8, 20)
        if getattr(self.win, 'ascii_mode', glyphs.is_ascii()):
            self._add_font_lines(help_text.FONT_ASCII, width)
            return
        if width < self.fonts_min_width:
            self._add_font_lines(help_text.FONT_NARROW, width)
            return
        for row in glyphs.font_check_rows():
            self.add_body(row)
        missing = glyphs.font_missing()
        if missing:
            names = ', '.join(entry.name for entry in missing)
            self._add_font_lines(
                f'Registered, but not in the reference fonts: {names}.', width)
        self._add_font_lines(help_text.FONT_ADVICE, width)

    def _add_font_lines(self, paragraph: str, width: int) -> None:
        for line in textwrap.wrap(paragraph, width=width):
            self.add_body(line)

    def on_pop(self) -> bool:
        """Forget the resolved Fonts mode so the next visit resolves it afresh.

        The demos (and many applications) reuse one help-screen instance for
        every ``?`` press.  Without this reset the first visit's cached
        ``'full'`` would be reused forever; clearing it lets the window's
        ``help_fonts='once'`` flag suppress the section on later visits while a
        redraw during the same visit still sees the same page.
        """
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
            self.win._help_fonts_shown = True  # pylint: disable=protected-access
        except AttributeError:
            return 'full'
        return 'full'


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
        """Replace the screen's content.  Safe before or after the first draw.

        Args:
            lines: ``str`` items, or ``(text, attr)`` pairs.
            head: A ``str``, a :class:`HeaderLine`, or an iterable of either.
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
            # No Context: these are plain, scrollable rows (the same shape
            # ViewScreen/CompareScreen produced before this helper existed).
            self.add_body(text, attr=attr)
