from __future__ import annotations

import curses
import re
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar

from . import glyphs
from .keys import NAVIGATION_KEYS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .screens import Screen, ScreenStack
    from .window import ConsoleWindow


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
        self.margin = 4 # + actual width (1st column right pos)
        self.align = self.margin # + actual width (1st column right pos)
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
            # Keep the built-in descriptions out of the body's column width.
            align = self.align
            self.add_key(attr, f'{attr} (built in)', genre='action', keys=keys)
            ns = self.attr_to_option[attr]
            ns.builtin = True
            ns.reserved = True
            self.align = align

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
        """Return the current value without mutating the application object."""
        ns = self.attr_to_option.get(attr, None)
        if ns is None or ns.obj is None:
            return None
        return getattr(ns.obj, ns.attr, None)

    def normalize(self, attr: str) -> object:
        """Initialize a missing option to its first value (or '' for a prompt).

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
        self.align = max(self.align, self.margin+len(ns.descr))
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

    def options_for_screen(self, screen: Screen) -> list[SimpleNamespace]:
        """The body options that apply on *screen*, built-ins excluded.

        Without a stack -- or on a screen the stack did not number -- there is
        no scope to filter by, so every application option applies.  This is the
        one definition of "applies here" used by the help body and by an app
        drawing its own help.
        """
        shown = [ns for ns in self.options if not ns.builtin]
        num = getattr(screen, 'num', None)
        if self.stack is None or num is None:
            return shown
        return [ns for ns in shown
                if num in getattr(ns, 'effective_scope', set())]

    def show_help_body(self, screen: Screen) -> None:
        options = self.options_for_screen(screen)
        if options:
            screen.add_body('Type keys to alter choice:', curses.A_UNDERLINE)
        for ns in options:
            self._write_option_body(screen, ns)

    def _write_option_body(self, screen: Screen, ns: SimpleNamespace) -> None:
        # Registration normalizes every option, so a missing value here means
        # the application deleted or cleared the attribute afterwards.  Render
        # an explicit placeholder instead of relying on an assert (which would
        # vanish under ``python -O`` and print "None" as the current value).
        value = self.get_value(ns.attr)
        dot = ' ' if ns.genre == 'action' else glyphs.get('bullet')
        screen.add_body(f'{ns.descr:{dot}<{self.align}} ')
        if value is None:
            screen.add_body(f'<unset: {ns.attr!r}>', resume=True, attr=curses.A_DIM)
            return

        if ns.genre in ('cycle', 'prompt'):
            choices = ns.vals if ns.vals else [value]
            for choice in choices:
                screen.add_body(' ', resume=True)
                screen.add_body(self._format_choice(choice), resume=True,
                    attr=curses.A_REVERSE if choice == value else None)

        for comment in ns.comments:
            screen.add_body(f'{"":>{self.align}}:  {comment}')

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
        # Try scoped lookup first (if stack is available)
        ns = None
        if self.stack and hasattr(self.stack, 'curr') and self.stack.curr:
            current_screen = self.stack.curr.num
            ns = self.key_scopes.get((key, current_screen), None)

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
