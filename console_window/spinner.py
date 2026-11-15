from __future__ import annotations

import curses
import re
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar

from . import glyphs, textwidth
from .keys import NAVIGATION_KEYS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .screens import Screen, ScreenStack
    from .window import ConsoleWindow

#: One ``(text, attr)`` piece of an option's value run.
_Fragments = list[tuple[str, int | None]]
#: One help-body row: its text, its attribute, and whether it continues the
#: row before it (the window appends a resuming fragment to the last row).
_Row = tuple[str, int | None, bool]
#: An option paired with the values shown beside it on the help screen.
_HelpRows = list[tuple[SimpleNamespace, _Fragments]]


class OptionSpinner:
    """Keys and values for a Screen application.

    A spinner may be used without a stack (no screen scoping) or with one.  A
    stack may own at most one spinner, which the spinner injects as
    ``stack.spinner`` so screens find it without scanning the app.  Two actions
    are registered before the application registers anything: ``quit`` (``q``,
    ``^C``) and ``escape`` (``ESC``, ``^J``, ``ENTER``).  They are shown in the
    help navigation block, never in the option body, and an implicit
    registration that would claim their keys raises; name the screens with
    ``scope=`` to override one deliberately.
    """

    #: Default key sets for the two built-in actions.  Override them with the
    #: ``quit_keys=`` / ``escape_keys=`` constructor arguments.
    _DEFAULT_QUIT_KEYS: tuple[int, ...] = (ord('q'), 0x3)
    _DEFAULT_ESCAPE_KEYS: tuple[int, ...] = (27, 10, curses.KEY_ENTER)
    _BUILTIN_NAV_LABELS: ClassVar[dict[str, str]] = {
        'quit': 'quit', 'escape': 'back'}

    #: Genres a help screen keeps live for the screen it describes, so a value
    #: can be changed without backing out of the help.  Actions are excluded:
    #: they act on their own screen and do nothing while the help is up.
    _HELP_GENRES: ClassVar[tuple[str, ...]] = ('cycle', 'prompt')

    #: Help-body layout.  The value column starts ``_COLUMN_MARGIN`` cells past
    #: the longest description it lists (so the dotted gap never closes), with
    #: ``_VALUE_GAP`` spaces before the first value.  A wrapped value row needs
    #: ``_MIN_VALUE_CELLS`` cells to be worth aligning; below that the option is
    #: laid out flat -- description on its own row, values beneath it, indented
    #: ``_FLAT_INDENT`` cells.
    _COLUMN_MARGIN: ClassVar[int] = 4
    _VALUE_GAP: ClassVar[int] = 2
    _MIN_VALUE_CELLS: ClassVar[int] = 8
    _FLAT_INDENT: ClassVar[int] = 2
    #: A comment is prose, not a list, so it needs more room than a value row
    #: before hanging under the column is worth it; below this it wraps at the
    #: flat indent instead, where two or three words still fit per row.
    _MIN_PROSE_CELLS: ClassVar[int] = 16

    def __init__(self, stack: ScreenStack | None = None,
                 nav_keys: Iterable[int] | None = None,
                 quit_keys: int | str | list | tuple | set | None = None,
                 escape_keys: int | str | list | tuple | set | None = None) -> None:
        self.options: list[SimpleNamespace] = []
        self.keys: set[int] = set()
        # The navigation set this spinner validates against.  Pass the owning
        # window's ``opts.nav_keys`` when the window takes navigation keys for
        # the app; otherwise the process default applies.  Keeping this
        # per-spinner (rather than reading/mutating the module global) lets two
        # windows with different bindings coexist.
        self.nav_keys: frozenset[int] = frozenset(
            NAVIGATION_KEYS if nav_keys is None else nav_keys
        )
        self._default_obj: object = SimpleNamespace() # if not given one (private)
        self.attr_to_option: dict[str, SimpleNamespace] = {} # attr -> option ns
        self.key_to_option: dict[int, SimpleNamespace] = {} # key -> option ns
        self.stack = stack  # Optional ScreenStack for scope-aware bindings
        # Maps (key, screen) -> option_ns for scope tracking
        self.key_scopes: dict[tuple[int, int], SimpleNamespace] = {}

        # Sync with stack.obj: use stack's obj if available, otherwise provide ours
        if self.stack:
            existing = getattr(self.stack, 'spinner', None)
            if existing is not None:
                raise ValueError(
                    'A ScreenStack may own only one OptionSpinner; '
                    'construct a second spinner with its own stack.'
                )
            self.stack.spinner = self
            if self.stack.obj is not None:
                # Stack already has an obj - use it as our default_obj
                self._default_obj = self.stack.obj
            else:
                # Stack has no obj - give it ours
                self.stack.obj = self._default_obj

        self._register_builtins(quit_keys, escape_keys)

    @property
    def default_obj(self) -> object:
        """The object option values are read from and written to."""
        return self._default_obj

    @default_obj.setter
    def default_obj(self, value: object) -> None:
        self._default_obj = value
        if self.stack:
            self.stack.obj = value  # Keep in sync!

    def _register_builtins(
            self,
            quit_keys: int | str | list | tuple | set | None,
            escape_keys: int | str | list | tuple | set | None,
    ) -> None:
        """Register ``quit`` and ``escape`` before the app registers anything."""
        specs = (
            ('quit', self._DEFAULT_QUIT_KEYS if quit_keys is None else quit_keys),
            ('escape', self._DEFAULT_ESCAPE_KEYS if escape_keys is None else escape_keys),
        )
        for attr, keys in specs:
            # The built-ins are advertised in the navigation block, never in
            # the body, so their descriptions never set the body's column.
            self.add_key(attr, f'{attr} (built in)', genre='action', keys=keys)
            ns = self.attr_to_option[attr]
            ns.builtin = True
            ns.reserved = True

    @staticmethod
    def _make_option_ns() -> SimpleNamespace:
        return SimpleNamespace(
            keys=[],
            descr='',
            obj=None,
            attr='',
            vals=None,
            prompt=None,
            check_ans=None,  # compiled regex or callable; prompt genre only
            comments=[],
            genre=None,
            scope=None,  # None = all screens, or set of screen numbers
            builtin=False,  # registered by OptionSpinner, not by the app
            reserved=False,  # its keys may only be taken with an explicit scope
        )

    def get_value(self, attr: str) -> object:
        """Return the current value without mutating the application object.

        Args:
            attr: Option name, as registered.
        """
        ns = self.attr_to_option.get(attr, None)
        if ns is None or ns.obj is None:
            return None
        return getattr(ns.obj, ns.attr, None)

    def normalize(self, attr: str) -> object:
        """Initialize a missing option to its first value (or '' for a prompt).

        Args:
            attr: Option name, as registered.

        This is the only path that writes while an option is being registered;
        ordinary reads (help rendering, key handling) use get_value() and stay
        side-effect free.  An existing non-None value is left alone.
        """
        value = self.get_value(attr)
        if value is not None:
            return value
        ns = self.attr_to_option.get(attr, None)
        if ns is None or ns.obj is None:
            return None
        value = ns.vals[0] if ns.vals else ''
        setattr(ns.obj, ns.attr, value)
        return value

    def _register(self, ns: SimpleNamespace) -> None:
        if ns.attr in self.attr_to_option:
            existing = self.attr_to_option[ns.attr]
            raise ValueError(
                f"Attribute '{ns.attr}' already registered with description '{existing.descr}'. "
                f"Each add_key() must have a unique attr name. "
                f"If you want the same key on different screens, use different attr names with scope parameter."
            )
        self.attr_to_option[ns.attr] = ns

        all_screens = set(range(len(self.stack.screens))) if self.stack else set()
        effective_scope = self._resolve_scope(ns, all_screens)
        ns.effective_scope = effective_scope  # Store for later subtraction

        for key in ns.keys:
            self._reject_navigation_key(key)
            self._subtract_scope(key, effective_scope,
                                 explicit=ns.scope is not None)
            self._store_key_scope(key, ns, effective_scope)

        self.options.append(ns)
        self.normalize(ns.attr)

    def _resolve_scope(self, ns: SimpleNamespace, all_screens: set) -> set:
        if ns.scope is not None:
            return ns.scope.copy()

        if ns.genre == 'action' and self.stack and self.stack.screen_objects:
            implemented = {
                screen_num
                for screen_num, screen_obj in self.stack.screen_objects.items()
                if hasattr(screen_obj, f'{ns.attr}_ACTION')
            }
            if implemented:
                return implemented

        return all_screens

    #: Names for the keys whose caret spelling would be unreadable in help.
    _KEY_LABELS: ClassVar[dict[int, str]] = {
        27: 'ESC', 10: '^J', curses.KEY_ENTER: 'ENTER'}

    @classmethod
    def _key_label(cls, key: int) -> str:
        label = cls._KEY_LABELS.get(key)
        if label is not None:
            return label
        if 0 <= key < 32:
            return f'^{chr(key + 64)}'
        if 32 <= key < 127:
            return chr(key)
        return f'<{key}>'

    def _reject_navigation_key(self, key: int) -> None:
        if key in self.nav_keys:
            raise ValueError(
                f'Key {self._key_label(key)} ({key}) conflicts with a navigation key. '
                f'Navigation keys are reserved for cursor movement and scrolling.'
            )

    def _subtract_scope(self, key: int, effective_scope: set, *,
                        explicit: bool = False) -> None:
        for existing_ns in self.options:
            if key in existing_ns.keys and hasattr(existing_ns, 'effective_scope'):
                overlap = existing_ns.effective_scope & effective_scope
                if overlap and not explicit and getattr(existing_ns, 'reserved', False):
                    raise ValueError(
                        f'Key {self._key_label(key)} is reserved by the built-in '
                        f"'{existing_ns.attr}' action; pass an explicit scope= to "
                        f'override it on named screens, or change '
                        f'{existing_ns.attr}_keys=.'
                    )
                for screen_num in overlap:
                    self.key_scopes.pop((key, screen_num), None)
                existing_ns.effective_scope -= effective_scope

    def _store_key_scope(self, key: int, ns: SimpleNamespace, effective_scope: set) -> None:
        for screen_num in effective_scope:
            self.key_scopes[(key, screen_num)] = ns

        # Update global key tracking (if not using scopes, keep old behavior)
        if not self.stack:
            if key in self.key_to_option:
                raise ValueError(f'key ({chr(key)}, {key}) already used')
            self.key_to_option[key] = ns

        self.keys.add(key)

    def add_key(self, attr: str, descr: str, obj: object | None = None,
                vals: list | None = None, prompt: str | None = None,
                keys: int | str | list | tuple | set | None = None,
                comments: str | list[str] | tuple[str, ...] | None = None,
                genre: str | None = None,
                scope: int | list | set | None = None,
                check_ans: str | re.Pattern[str]
                | Callable[[str], str | None] | None = None) -> None:
        """Register one option: a setting to cycle, a prompt, or an action.

        This is the only registration path; the pre-2.0 ``add()`` shim has been
        removed.  ``quit`` and ``escape`` are already registered by the
        constructor (see the class docstring).

        ``attr``
            Attribute name on the target object, and the option's unique id.
            Two options may not share it (``ValueError``).  For an action it is
            also the method name: ``perform_actions()`` calls
            ``f'{attr}_ACTION'`` on the current screen.  To reuse a key on two
            screens, register two options with different ``attr`` values, the
            same ``keys`` and different ``scope`` values; scope subtraction
            keeps the bindings apart.

        ``descr``
            Text shown on the help screen.  Its first character is the key when
            ``keys`` is omitted, so ``'v - view mode'`` binds ``v`` and then
            repeats the binding in the text.  The help body prints the whole
            string, so keep the key visible in it.

        ``obj``
            Object the value lives on.  Defaults to ``default_obj``, which is
            the ``ScreenStack`` object when the spinner was given a stack.  The
            value is initialized at registration: the first entry of ``vals``
            for a cycle, the empty string otherwise.  An action's flag is
            therefore falsy until its key sets it.

        ``vals``
            Allowed values in cycle order.  Supplying it makes the option a
            ``cycle``: each key press advances to the next value, wrapping at
            the end, and writes it to ``obj``.  The current value is shown on
            the help screen with the matching entry reversed.

        ``prompt``
            Question for a ``prompt`` option.  Each key press runs
            ``win.answer(prompt=..., seed=<current value>)`` and writes the
            reply.  An aborted dialog returns ``None`` and leaves the previous
            value untouched.

        ``check_ans``
            Validation for a ``prompt`` option; ``None`` (the default) accepts
            any reply.  A string is a regular expression the whole reply must
            match (``re.fullmatch``); a compiled pattern is accepted too.  A
            callable is handed the reply and returns ``None`` to accept it, or
            a string describing the expectation.  A rejected reply re-opens the
            dialog with the rejected text as the seed and the description on
            the dialog's footer, so it can be edited; ESC still aborts and
            leaves the value untouched.  ``check_ans`` is only meaningful for
            a prompt option: passing it with ``vals`` or for an action raises
            ``ValueError``.

        ``keys``
            Key code, character, or iterable of either (a string is expanded
            per character), that drives the option.  Defaults to
            ``ord(descr[0])``.  Navigation keys are rejected with
            ``ValueError`` unless the window released them through
            ``taken_nav_keys``, so a binding can never shadow scrolling.

        ``comments``
            Extra explanatory lines printed under the option on the help
            screen, one body row each.

        ``genre``
            ``'action'``, ``'cycle'`` or ``'prompt'``.  Normally inferred
            (``vals`` means cycle, ``prompt`` means prompt, neither means
            action).  Passing a genre that contradicts the arguments raises
            ``ValueError`` rather than mis-registering the option.

        ``scope``
            Screen number, or iterable of them, the key is live on.  ``None``
            means every screen for a setting, and every screen implementing the
            ``_ACTION`` method for an action.  Later registrations that claim
            the same key subtract their screens from earlier options, so the
            last writer wins and the earlier option keeps the screens nobody
            else took.  The built-in ``quit``/``escape`` keys are reserved:
            taking one requires an explicit ``scope=``; an implicit
            registration on it raises ``ValueError``.

        Raises ``ValueError`` for a duplicate ``attr``, a navigation key, a
        genre that contradicts the arguments, ``check_ans`` on a non-prompt
        option, a ``check_ans`` string that is not a valid regular expression,
        or an implicit registration on a reserved built-in key.

        ``effective_scope`` is computed once at registration and recorded per
        screen in ``key_scopes``; that table is what ``do_key()`` and
        ``perform_actions()`` consult, so a key registered for a screen is
        dispatchable only there.
        """
        ns = self._make_option_ns()
        ns.keys = self._parse_keys(keys, descr)
        ns.comments = self._parse_comments(comments)
        ns.descr = descr
        ns.attr = attr
        ns.obj = obj if obj else self.default_obj

        ns.genre = self._resolve_genre(genre, vals, prompt)
        if vals:
            ns.vals = vals
        elif prompt:
            ns.prompt = prompt
        if check_ans is not None:
            if ns.genre != 'prompt':
                raise ValueError(
                    f"check_ans is only meaningful for a prompt option, but "
                    f"'{attr}' is a {ns.genre} option."
                )
            ns.check_ans = self._compile_check_ans(attr, check_ans)

        ns.scope = self._parse_scope(scope)
        self._register(ns)

    @staticmethod
    def _compile_check_ans(
            attr: str,
            check_ans: str | re.Pattern[str] | Callable[[str], str | None],
    ) -> re.Pattern[str] | Callable[[str], str | None]:
        """Compile a pattern string; pass a compiled pattern or callable through."""
        if isinstance(check_ans, str):
            try:
                return re.compile(check_ans)
            except re.error as exc:
                raise ValueError(
                    f"check_ans for '{attr}' is not a valid regular expression: {exc}"
                ) from None
        return check_ans

    @staticmethod
    def _check_answer(
            check_ans: re.Pattern[str] | Callable[[str], str | None],
            answer: str,
    ) -> str | None:
        """Return None when *answer* is acceptable, else what was expected."""
        if isinstance(check_ans, re.Pattern):
            if check_ans.fullmatch(answer):
                return None
            return f'must match {check_ans.pattern!r}'
        problem = check_ans(answer)
        return None if problem is None else str(problem)

    @staticmethod
    def _parse_keys(keys: int | str | list | tuple | set | None, descr: str) -> list[int]:
        if not keys:
            return [ord(descr[0])]

        # A set is unordered; sort it so the help block reads the same on every
        # run.  List and tuple order is the caller's reading order.
        raw = (sorted(keys) if isinstance(keys, set)
               else list(keys) if isinstance(keys, (list, tuple)) else [keys])
        codes: list[int] = []
        for key in raw:
            if isinstance(key, str):
                codes.extend(ord(stroke) for stroke in key)
            else:
                codes.append(key)
        return codes

    @staticmethod
    def _parse_comments(comments: str | list[str] | tuple[str, ...] | None) -> list[str]:
        if comments is None:
            return []
        return list(comments) if isinstance(comments, (list, tuple)) else [comments]

    @staticmethod
    def _resolve_genre(genre: str | None, vals: list | None, prompt: str | None) -> str:
        if genre is not None and genre not in ('action', 'cycle', 'prompt'):
            raise ValueError(
                f"genre must be 'action', 'cycle' or 'prompt' (got {genre!r})"
            )

        inferred_genre = 'cycle' if vals else 'prompt' if prompt else 'action'
        if genre is None:
            return inferred_genre
        if genre != inferred_genre:
            supplied = 'vals' if vals else 'prompt' if prompt else 'neither vals nor prompt'
            raise ValueError(
                f"genre={genre!r} conflicts with the supplied arguments "
                f"({supplied}); expected genre={inferred_genre!r}. "
                f"Drop the conflicting argument or pass the matching genre."
            )
        return genre

    @staticmethod
    def _parse_scope(scope: int | list | set | None) -> set | None:
        if scope is None:
            return None  # All screens (or all screens with action)
        if isinstance(scope, int):
            return {scope}
        if isinstance(scope, (list, tuple, set)):
            return set(scope)
        raise ValueError(f"scope must be None, int, or list/set, got {type(scope)}")

    def show_help_nav_keys(self, screen: Screen) -> None:
        """Draw the navigation block for *screen* from the live window.

        Args:
            screen: Help screen being built; its window supplies the key lines,
                so ``opts.taken_nav_keys`` is honored.
        """
        # Render from the live window so its own opts.taken_nav_keys are
        # honored: keys the app owns are not advertised as navigation.
        for line in screen.win.nav_help_lines():
            screen.add_header(line)
        builtin = self._builtin_nav_line()
        if builtin:
            screen.add_header(builtin)

    def _builtin_nav_line(self) -> str:
        """The ``quit: ... back: ...`` row, or '' when the built-ins are gone."""
        chunks = []
        for attr, label in self._BUILTIN_NAV_LABELS.items():
            ns = self.attr_to_option.get(attr)
            if ns is None or not ns.builtin:
                continue
            keys = '/'.join(self._key_label(key) for key in ns.keys)
            chunks.append(f'{label}: {keys}')
        return '   '.join(chunks)

    def options_for_screen(self, screen: object) -> list[SimpleNamespace]:
        """The options that apply on *screen*, built-ins excluded.

        Without a stack -- or on a screen the stack did not number -- there is
        no scope to filter by, so every application option applies.  The help
        body applies this to the screen it describes (``help_subject()``), so
        global options and those scoped to that screen are the ones listed.
        """
        shown = [ns for ns in self.options if not ns.builtin]
        num = getattr(screen, 'num', None)
        if self.stack is None or num is None:
            return shown
        return [ns for ns in shown
                if num in getattr(ns, 'effective_scope', set())]

    def show_help_body(self, screen: Screen) -> None:
        """Draw the option body for the screen this help page describes.

        Args:
            screen: Help screen being built; its ``help_subject()`` picks the
                rows, so global and screen-scoped options are the ones listed.
        """
        subject = self.help_subject(screen)
        if subject is None:
            # Nothing was pushed under the help: fall back to every option, so
            # a stackless or entry help screen still documents something.
            options = [ns for ns in self.options if not ns.builtin]
        else:
            options = self.options_for_screen(subject)
        if not options:
            return
        width = self._body_width(screen)
        for line in self._wrap(self._keys_heading(subject), width,
                               self._FLAT_INDENT):
            screen.add_body(line, curses.A_UNDERLINE)
        self._write_options(screen, options, width)

    def help_subject(self, screen: object) -> SimpleNamespace | None:
        """The paused frame this help screen describes, or ``None``.

        A help screen is pushed onto the screen it documents, so the frame the
        stack paused is the subject: its name titles the keys band, its scope
        selects the rows, and its value keys stay live on the help screen.  The
        subject is ``None`` when nothing was pushed -- a stackless spinner, a
        help screen that is the entry screen, or a screen drawn while it is not
        the current one -- and the body then shows the complete option list.
        """
        stack = getattr(screen, 'stack', None) or self.stack
        if stack is None:
            return None
        num = getattr(screen, 'num', None)
        curr = getattr(stack, 'curr', None)
        frames = getattr(stack, 'stack', None) or []
        if num is None or curr is None or getattr(curr, 'num', None) != num:
            return None
        return frames[-1] if frames else None

    def _keys_heading(self, subject: SimpleNamespace | None) -> str:
        """``Keys for 'MAIN':``, naming the screen the help was opened from.

        With no subject there is no screen to name -- the body is the complete
        option list -- so the heading says what it is instead.
        """
        name = getattr(subject, 'name', None)
        return f"Keys for '{name}':" if name else 'All keys:'

    def _help_value_key(self, key: int, curr_num: int) -> SimpleNamespace | None:
        """The subject's cycle/prompt option for *key*, on a help screen only.

        ``do_key()`` resolves a key against the current screen, which on a help
        screen would hide the value keys of the screen it describes.  Those are
        exactly the keys a reader may want to adjust without backing out, so the
        lookup falls through to the subject's scope.  Actions are deliberately
        not inherited: they act on their own screen, not on the help.
        """
        screen_objects = getattr(self.stack, 'screen_objects', None) or {}
        screen_obj = screen_objects.get(curr_num)
        if not getattr(screen_obj, 'is_help_screen', False):
            return None
        subject = self.help_subject(screen_obj)
        if subject is None:
            return None
        ns = self.key_scopes.get((key, subject.num))
        if ns is not None and ns.genre in self._HELP_GENRES:
            return ns
        return None

    def _write_options(self, screen: Screen, options: list[SimpleNamespace],
                       width: int) -> None:
        """Lay out *options* in *width* cells: the pad's width when it draws.

        The column is chosen per draw from the rows actually listed -- a long
        description on another screen must not widen this one -- so a resize
        re-flows on the next draw.  No row may be wider than that pad: the
        window truncates silently otherwise, and the cells it drops can be the
        highlighted value.
        """
        rows: _HelpRows = [(ns, self._value_fragments(ns)) for ns in options]
        column = self._help_column(rows, width)
        for ns, fragments in rows:
            for text, attr, resume in self._option_rows(
                    ns, fragments, column, width):
                screen.add_body(text, attr, resume=resume)

    @staticmethod
    def _body_width(screen: Screen) -> int:
        """The cells one body row may occupy, or 80 for a sink that cannot say."""
        getter = getattr(getattr(screen, 'win', None), 'get_pad_width', None)
        return max(1, getter() if callable(getter) else 80)

    def _value_fragments(self, ns: SimpleNamespace) -> _Fragments:
        """What follows the description: one ``(text, attr)`` per visible value.

        An action has none.  A cycle lists every value in order with the current
        one reversed; a prompt shows its single current value.  A value the
        application deleted after registration renders the same dimmed
        placeholder as before -- registration normalizes every option, so the
        only way to see ``None`` here is a caller clearing the attribute, and
        printing "None" as the current value would hide that.
        """
        value = self.get_value(ns.attr)
        if value is None:
            return [(f'<unset: {ns.attr!r}>', curses.A_DIM)]
        if ns.genre == 'action':
            return []
        if ns.genre == 'cycle' and ns.vals:
            return [(self._format_choice(choice),
                     curses.A_REVERSE if choice == value else None)
                    for choice in ns.vals]
        return [(self._format_choice(value), curses.A_REVERSE)]

    def _help_column(self, rows: _HelpRows, width: int) -> int:
        """The description column for *rows* on a *width*-cell-wide body.

        Two candidates, widest first: the longest description listed, then the
        longest description that carries values (an action's description is
        followed by nothing, so it sets no column).  The first whose rows all
        fit wins; when neither fits, the narrow one wins and the rows that
        overflow are wrapped.
        """
        descrs = [self._cells(ns.descr) for ns, _fragments in rows]
        valued = [self._cells(ns.descr) for ns, fragments in rows if fragments]
        candidates = [self._COLUMN_MARGIN + max(descrs, default=0)]
        if valued:
            candidates.append(self._COLUMN_MARGIN + max(valued))
        for column in candidates:
            if all(self._fits(ns, fragments, column, width)
                   for ns, fragments in rows):
                return column
        return candidates[-1]

    def _fits(self, ns: SimpleNamespace, fragments: _Fragments,
              column: int, width: int) -> bool:
        """True when this option's row needs no wrapping at *column*."""
        descr = self._cells(ns.descr)
        if not fragments:
            return descr <= width
        return (self._value_start(descr, column) + self._value_cells(fragments)
                <= width)

    def _value_start(self, descr: int, column: int) -> int:
        """The cell where the first value begins, never inside the dot margin."""
        return max(column, descr + self._COLUMN_MARGIN) + self._VALUE_GAP

    def _value_cells(self, fragments: _Fragments) -> int:
        """Display cells of the whole value run, its separator spaces included."""
        return (sum(self._cells(text) for text, _attr in fragments)
                + len(fragments) - 1)

    def _option_rows(self, ns: SimpleNamespace, fragments: _Fragments,
                     column: int, width: int) -> list[_Row]:
        """The body rows for one option, wrapped to *width* cells.

        Aligned under the chosen column while that leaves room to wrap beneath
        it, at the four-cell dot margin when it does not, and flat -- the
        description on its own row, the values beneath it -- when even that
        leaves too little.  Values break between entries, never inside one, so
        the current value's reversal is always emitted as a single run; an
        entry too long for any line is truncated with an ellipsis instead.
        """
        descr = self._cells(ns.descr)
        start: int | None = self._value_start(descr, column)
        if not fragments:
            rows = self._descr_rows(ns.descr, width)
        else:
            for start in (self._value_start(descr, column),
                          self._value_start(
                              descr, descr + self._COLUMN_MARGIN)):
                if width - start >= self._MIN_VALUE_CELLS:
                    rows = self._rows_with_values(
                        ns.descr, fragments, start, width)
                    break
            else:
                # Flat: there is no column for a comment marker to point at.
                rows = self._flat_rows(ns.descr, fragments, width)
                start = None
        for comment in ns.comments:
            rows += self._comment_rows(comment, start, width)
        return rows

    def _rows_with_values(self, descr: str, fragments: _Fragments,
                          start: int, width: int) -> list[_Row]:
        """The description row, with the values starting at *start*.

        Dots fill the gap to *start*, so the value column stays visible even
        beside a short description; the values break between entries, one space
        apart, and every continuation row is indented to the same column.
        """
        dots = max(start - self._VALUE_GAP - self._cells(descr), 0)
        rows: list[list[tuple[str, int | None]]] = [
            [(descr + glyphs.get('bullet') * dots + ' ' * self._VALUE_GAP, None)]
        ]
        used = start
        for text, attr in fragments:
            piece = self._cells(text)
            if used > start and used + 1 + piece > width:
                rows.append([(' ' * start, None)])
                used = start
            if used > start:
                rows[-1].append((' ', None))
                used += 1
            if used + piece > width:
                text = self._clip(text, width - start)
                piece = self._cells(text)
            rows[-1].append((text, attr))
            used += piece
        return self._flush(rows)

    def _flat_rows(self, descr: str, fragments: _Fragments,
                   width: int) -> list[_Row]:
        """Description, then its values beneath it, both on their own rows."""
        return (self._descr_rows(descr, width)
                + self._rows_with_values('', fragments, self._FLAT_INDENT, width))

    def _descr_rows(self, descr: str, width: int) -> list[_Row]:
        """The description alone, word-wrapped under a two-cell hanging indent."""
        if self._cells(descr) <= width:
            return [(descr, None, False)]
        return [(text, None, False)
                for text in self._wrap(descr, width, self._FLAT_INDENT)]

    def _comment_rows(self, comment: str, start: int | None,
                      width: int) -> list[_Row]:
        """One comment, wrapped under the value column it annotates.

        Under a column the ``:`` marker stays where it always was; in the flat
        layout there is no column to point at, so the text simply hangs two
        cells in from the option it belongs to.
        """
        if start is None or width - (start + 1) < self._MIN_PROSE_CELLS:
            lines = self._wrap(comment, width, self._FLAT_INDENT)
            lines[0] = ' ' * self._FLAT_INDENT + lines[0]
            return [(text, None, False) for text in lines]
        hang = start + 1
        lines = self._wrap(comment, width, hang)
        lines[0] = ' ' * (hang - 3) + ':  ' + lines[0]
        return [(text, None, False) for text in lines]

    @staticmethod
    def _wrap(text: str, width: int, indent: int) -> list[str]:
        """*text* word-wrapped to *width*, continuation rows indented *indent*."""
        lines = textwidth.wrap(text, max(width - indent, 1))
        pad = ' ' * indent
        return [lines[0]] + [pad + line for line in lines[1:]]

    def _clip(self, text: str, avail: int) -> str:
        """*text* cut to *avail* cells, ellipsis-marked when it lost any."""
        if avail <= 0 or self._cells(text) <= avail:
            return text
        mark = glyphs.get('ellipsis')
        room = avail - self._cells(mark)
        if room <= 0:
            return textwidth.truncate(text, avail)
        return textwidth.truncate(text, room) + mark

    @staticmethod
    def _flush(rows: list[list[tuple[str, int | None]]]) -> list[_Row]:
        """One ``(text, attr, resume)`` triple per fragment.

        The first fragment of each row starts it; every later fragment resumes,
        which is how the window keeps one logical row while the value run is
        drawn in pieces with its own attributes.
        """
        return [(text, attr, index > 0)
                for row in rows
                for index, (text, attr) in enumerate(row)]

    @staticmethod
    def _cells(text: str) -> int:
        """Display cells *text* occupies, so a wide glyph is not miscounted."""
        return textwidth.string_width(text)

    @staticmethod
    def _format_choice(choice: object) -> str:
        if isinstance(choice, bool):
            return "ON" if choice else "off"
        return f'{choice}'

    def _prompt_value(self, ns: SimpleNamespace, win: ConsoleWindow,
                      value: object) -> object | None:
        """Run the prompt dialog until its answer passes ``check_ans``.

        Returns the accepted text, or ``None`` when the user aborts.  A
        rejected answer re-opens the dialog seeded with that text and the
        expectation on the footer, so a typo is an edit rather than a restart.
        """
        hint = ''
        while True:
            # Only pass ``hint`` when there is one: a window-like object with
            # the pre-hint answer() signature keeps working for the plain path.
            if hint:
                answer = win.answer(prompt=ns.prompt, seed=str(value), hint=hint)
            else:
                answer = win.answer(prompt=ns.prompt, seed=str(value))
            if answer is None or ns.check_ans is None:
                return answer
            problem = self._check_answer(ns.check_ans, answer)
            if problem is None:
                return answer
            value, hint = answer, problem

    def do_key(self, key: int, win: ConsoleWindow) -> object | None:
        """Resolve *key* to its option and produce the option's new value.

        Args:
            key: ``curses`` key code.
            win: Window used by ``prompt`` options (``win.answer``).

        Returns:
            The new value; ``None`` when the key matches nothing or a prompt
            dialog was aborted (the previous value is then left untouched).
        """
        # Try scoped lookup first (if stack is available)
        ns = None
        current_screen = None
        if self.stack and hasattr(self.stack, 'curr') and self.stack.curr:
            current_screen = self.stack.curr.num
            ns = self.key_scopes.get((key, current_screen), None)

        # On a help screen the described screen's value keys still apply.
        if ns is None and current_screen is not None:
            ns = self._help_value_key(key, current_screen)

        # Fall back to global lookup (for backward compatibility without scopes)
        if ns is None:
            ns = self.key_to_option.get(key, None)

        if ns is None:
            return None
        value = self.get_value(ns.attr)
        if ns.genre == 'cycle':
            idx = ns.vals.index(value) if value in ns.vals else -1
            value = ns.vals[(idx+1) % len(ns.vals)] # choose next
        elif ns.genre == 'prompt':
            value = self._prompt_value(ns, win, value)
            if value is None:
                return None  # aborted dialog: leave the previous value untouched
        elif ns.genre == 'action':
            value = True

        setattr(ns.obj, ns.attr, value)
        return value
