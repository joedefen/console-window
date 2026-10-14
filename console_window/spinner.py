"""Key-driven option management (spinners, prompts, actions)."""

from __future__ import annotations

import curses
from types import SimpleNamespace
from typing import TYPE_CHECKING

from .keys import NAVIGATION_KEYS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .screens import ScreenStack
    from .window import ConsoleWindow


class OptionSpinner:
    """
    Manages a set of application options where the value can be rotated through
    a fixed set of values (spinner) or requested via a dialog box (prompt) by
    pressing a single key.

    It also generates a formatted help screen based on the registered options.
    """
    def __init__(self, stack: ScreenStack | None = None) -> None:
        """
        Initializes the OptionSpinner, setting up internal mappings for options
        and keys.

        :param stack: Optional ScreenStack reference for scope-aware key bindings.
                      If stack.obj is None, it will be set to this spinner's default_obj.
        :type stack: ScreenStack or None

        .. warning::
            If you plan to set a custom default_obj, either:

            1. Pass it via ScreenStack: ``ScreenStack(win, my_opts, ...)`` then
               ``OptionSpinner(stack=stack)`` (recommended)
            2. Set it immediately after creation before calling add_key():
               ``spin = OptionSpinner(stack=stack); spin.default_obj = my_opts``

            The default_obj property automatically syncs with stack.obj when set.
        """
        self.options, self.keys = [], []
        self.margin = 4 # + actual width (1st column right pos)
        self.align = self.margin # + actual width (1st column right pos)
        self._default_obj = SimpleNamespace() # if not given one (private)
        self.attr_to_option = {} # given an attribute, find its option ns
        self.key_to_option = {} # given key, options namespace
        self.keys = set()
        self.stack = stack  # Optional ScreenStack for scope-aware bindings
        self.key_scopes = {}  # Maps (key, screen) -> option_ns for scope tracking

        # Sync with stack.obj: use stack's obj if available, otherwise provide ours
        if self.stack:
            if self.stack.obj is not None:
                # Stack already has an obj - use it as our default_obj
                self._default_obj = self.stack.obj
            else:
                # Stack has no obj - give it ours
                self.stack.obj = self._default_obj

    @property
    def default_obj(self) -> object:
        """
        The default object for storing option values.

        When set, automatically synchronizes with stack.obj to prevent
        object reference fragmentation.
        """
        return self._default_obj

    @default_obj.setter
    def default_obj(self, value: object) -> None:
        """Set default_obj and keep stack.obj synchronized."""
        self._default_obj = value
        if self.stack:
            self.stack.obj = value  # Keep in sync!

    @staticmethod
    def _make_option_ns() -> SimpleNamespace:
        """Internal helper to create a default namespace for an option."""
        return SimpleNamespace(
            keys=[],
            descr='',
            obj=None,
            attr='',
            vals=None,
            prompt=None,
            comments=[],
            genre=None,
            scope=None,  # None = all screens, or set of screen numbers
        )

    def get_value(self, attr: str, coerce: bool = False) -> object:
        """
        Get the current value of the given attribute.

        :param attr: The name of the attribute (e.g., 'help_mode').
        :param coerce: If True, ensures the value is one of the valid 'vals'
                       or an empty string for prompted options.
        :type attr: str
        :type coerce: bool
        :returns: The current value of the option attribute.
        :rtype: Any
        """
        ns = self.attr_to_option.get(attr, None)
        obj = ns.obj if ns else None
        value = getattr(obj, attr, None) if obj else None
        if value is None and obj and coerce:
            if ns.vals:
                if value not in ns.vals:
                    value = ns.vals[0]
                    setattr(obj, attr, value)
            else:
                if value is None:
                    value = ''
                    setattr(ns.obj, ns.attr, '')
        return value

    def _register(self, ns: SimpleNamespace) -> None:
        """
        Create the internal mappings needed for a new option namespace.
        Handles scope subtraction for overlapping keys.
        """
        if ns.attr in self.attr_to_option:
            existing = self.attr_to_option[ns.attr]
            raise ValueError(
                f"Attribute '{ns.attr}' already registered with description '{existing.descr}'. "
                f"Each add_key() must have a unique attr name. "
                f"If you want the same key on different screens, use different attr names with scope parameter."
            )
        self.attr_to_option[ns.attr] = ns

        # Get all screen numbers for scope calculations
        all_screens = set(range(len(self.stack.screens))) if self.stack else set()

        # Calculate effective scope for this new key
        # If scope is None and it's an action, need to determine which screens have this action
        if ns.scope is None:
            if ns.genre == 'action' and self.stack and self.stack.screen_objects:
                # Find all screens that implement this action (have method with name = attr)
                effective_scope = set()
                for screen_num, screen_obj in self.stack.screen_objects.items():
                    if hasattr(screen_obj, f'{ns.attr}_ACTION'):
                        effective_scope.add(screen_num)
                # If no screens found, default to all screens
                if not effective_scope:
                    effective_scope = all_screens
            else:
                # Not an action, or no stack available: all screens
                effective_scope = all_screens
        else:
            effective_scope = ns.scope.copy()

        # Store the effective scope in the namespace
        ns.effective_scope = effective_scope

        # Process each key for scope subtraction
        for key in ns.keys:
            # Check for conflicts with navigation keys
            if key in NAVIGATION_KEYS:
                key_char = chr(key) if 32 <= key < 127 else f'<{key}>'
                raise ValueError(
                    f'Key {key_char} ({key}) conflicts with a navigation key. '
                    f'Navigation keys are reserved for cursor movement and scrolling.'
                )

            # Perform subtraction FIRST: remove new scope from existing options with same key
            for existing_ns in self.options:
                if key in existing_ns.keys and hasattr(existing_ns, 'effective_scope'):
                    # Subtract the new scope from existing option's scope
                    # Also remove from key_scopes for screens that are being taken over
                    overlap = existing_ns.effective_scope & effective_scope
                    for screen_num in overlap:
                        if (key, screen_num) in self.key_scopes:
                            del self.key_scopes[(key, screen_num)]
                    existing_ns.effective_scope -= effective_scope

            # NOW check for conflicts: same key defined twice for the same screen
            # (After subtraction, there should be no conflicts if subtraction worked)
            for screen_num in effective_scope:
                if (key, screen_num) in self.key_scopes:
                    # This should not happen after subtraction
                    existing_ns = self.key_scopes[(key, screen_num)]
                    key_char = chr(key) if 32 <= key < 127 else f'<{key}>'
                    raise ValueError(
                        f'Key {key_char} ({key}) already defined for screen {screen_num} '
                        f'in option "{existing_ns.descr}". Cannot define same key twice for same screen.'
                    )

            # Store in key_scopes for each screen in the effective scope
            for screen_num in effective_scope:
                self.key_scopes[(key, screen_num)] = ns

            # Update global key tracking (if not using scopes, keep old behavior)
            if not self.stack:
                if key in self.key_to_option:
                    raise ValueError(f'key ({chr(key)}, {key}) already used')
                self.key_to_option[key] = ns

            self.keys.add(key)

        self.options.append(ns)
        self.align = max(self.align, self.margin+len(ns.descr))
        self.get_value(ns.attr, coerce=True)

    def add(self, obj: object, specs: list) -> None:
        """
        **Compatibility Method.** Adds options using an older array-of-specs format.

        A spec is a list or tuple like::

            ['a - allow auto suggestions', 'allow_auto', True, False],
            ['/ - filter pattern', 'filter_str', self.filter_str],

        The key is derived from the first character of the description string.
        It is recommended to use :py:meth:`add_key` for new code.

        :param obj: The object holding the option attributes (e.g., an argparse namespace).
        :param specs: An iterable of option specifications.
        :type obj: Any
        :type specs: list
        """
        for spec in specs:
            ns = self._make_option_ns()
            ns.descr = spec[0]
            ns.obj = obj
            ns.attr = spec[1]
            ns.vals=spec[2:]
            if None in ns.vals:
                idx = ns.vals.index(None)
                ns.vals = ns.vals[:idx]
                ns.comments = ns.vals[idx+1:]
            ns.keys = [ord(ns.descr[0])]
            self._register(ns)

    def add_key(self, attr: str, descr: str, obj: object | None = None,
                vals: list | None = None, prompt: str | None = None,
                keys: int | str | list | tuple | set | None = None,
                comments: str | list[str] | tuple[str, ...] | None = None,
                genre: str | None = None,
                scope: int | list | set | None = None) -> None:
        """
        Adds an option that is toggled by a key press.

        The option can be a **spinner** (rotates through a list of ``vals``) or
        a **prompt** (requests string input via a dialog).

        :param attr: The name of the attribute for the value; referenced as ``obj.attr``.
        :param descr: The description of the key (for help screen).
        :param obj: The object holding the value. If None, uses ``self.default_obj``.
        :param vals: A list of values. If provided, the option is a spinner.
        :param prompt: A prompt string. If provided instead of ``vals``, the key press
                       will call :py:meth:`ConsoleWindow.answer`.
        :param keys: A single key code or string or a list of such that triggers
                     the action. If a string, ord(each-character) is assumed.
                     If None, uses the first letter of ``descr``.
        :param comments: Additional line(s) for the help screen item (string or list of strings).
        :param genre: (action, cycle, prompt)
        :param scope: Screen number(s) where this key is active. Can be:
                      - None (default): all screens, or all screens with action if genre='action'
                      - int: single screen number
                      - list/set: multiple screen numbers
                      Later add_key() calls for the same key subtract from earlier scopes.
        :type attr: str
        :type descr: str
        :type obj: Any
        :type vals: list or None
        :type prompt: str or None
        :type keys: int or list or tuple or None
        :type comments: str or list or tuple or None
        :type genre: str or None
        :type scope: int or list or set or None
        """

        ns = self._make_option_ns()
        if keys:
            keys = list(keys) if isinstance(keys, (list, tuple, set)) else [keys]
            ns.keys = []
            for key in keys:
                if isinstance(key, str):
                    for stroke in key:
                        ns.keys.append(ord(stroke))
                else:
                    ns.keys.append(key)
        else:
            ns.keys = [ord(descr[0])]
        if comments is None:
            ns.comments = []
        else:
            ns.comments = list(comments) if isinstance(comments, (list, tuple)) else [comments]
        ns.descr = descr
        ns.attr = attr
        ns.obj = obj if obj else self.default_obj
        if vals:
            ns.vals, ns.genre = vals, 'cycle'
        elif prompt:
            ns.prompt, ns.genre = prompt, 'prompt'
        else:
            ns.genre = 'action'

        # Process scope parameter
        if scope is None:
            ns.scope = None  # All screens (or all screens with action)
        elif isinstance(scope, int):
            ns.scope = {scope}
        elif isinstance(scope, (list, tuple, set)):
            ns.scope = set(scope)
        else:
            raise ValueError(f"scope must be None, int, or list/set, got {type(scope)}")

        self._register(ns)

    @staticmethod
    def show_help_nav_keys(win: ConsoleWindow) -> None:
        """
        Displays the standard navigation keys blurb in the provided ConsoleWindow.

        :param win: The :py:class:`ConsoleWindow` instance to write to.
        :type win: ConsoleWindow
        """
        # Late import to avoid a circular import at module load time.
        from .window import ConsoleWindow
        for line in ConsoleWindow.get_nav_keys_blurb().splitlines():
            if line:
                win.add_header(line)

    def show_help_body(self, win: ConsoleWindow, screen_filter: int | list | set | None = None) -> None:
        """
        Writes the formatted list of all registered options and their current
        values to the body of the provided :py:class:`ConsoleWindow`.

        When using ScreenStack with scoped keys, only shows options applicable
        to the specified screens.

        :param win: The :py:class:`ConsoleWindow` instance to write to.
        :param screen_filter: Screen number(s) to filter options for. Can be:
                              - None: show all options (default)
                              - int: single screen number
                              - list/set: multiple screen numbers (typically [prev_screen, help_screen])
        :type win: ConsoleWindow
        :type screen_filter: int or list or set or None
        """
        win.add_body('Type keys to alter choice:', curses.A_UNDERLINE)

        # Convert screen_filter to a set for easy comparison
        if screen_filter is None:
            filter_screens = None
        elif isinstance(screen_filter, int):
            filter_screens = {screen_filter}
        elif isinstance(screen_filter, (list, tuple, set)):
            filter_screens = set(screen_filter)
        else:
            filter_screens = None

        for ns in self.options:
            # Skip options not applicable to the filtered screens
            if filter_screens is not None and hasattr(ns, 'effective_scope'):
                # Check if this option applies to any of the filter screens
                if not (ns.effective_scope & filter_screens):
                    continue

            # get / coerce the current value
            value = self.get_value(ns.attr)
            assert value is not None, f'cannot get value of {ns.attr!r}'

            dot = ' ' if ns.genre == 'action' else '·'
            win.add_body(f'{ns.descr:{dot}<{self.align}} ')

            if ns.genre in ('cycle', 'prompt'):
                choices = ns.vals if ns.vals else [value]
                for choice in choices:
                    shown = f'{choice}'
                    if isinstance(choice, bool):
                        shown = "ON" if choice else "off"
                    win.add_body(' ', resume=True)
                    win.add_body(shown, resume=True,
                        attr=curses.A_REVERSE if choice == value else None)

            for comment in ns.comments:
                win.add_body(f'{"":>{self.align}}:  {comment}')

    def do_key(self, key: int, win: ConsoleWindow) -> object | None:
        """
        Processes a registered key press.

        If the option is a spinner, it rotates to the next value. If it
        requires a prompt, it calls ``win.answer()`` to get user input.

        :param key: The key code received from :py:meth:`ConsoleWindow.prompt`.
        :param win: The :py:class:`ConsoleWindow` instance for dialogs.
        :type key: int
        :type win: ConsoleWindow
        :returns: The new value of the option, or None if the key is unhandled.
        :rtype: Any or None
        """
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
            value = win.answer(prompt=ns.prompt, seed=str(value))
        elif ns.genre == 'action':
            value = True

        setattr(ns.obj, ns.attr, value)
        return value
