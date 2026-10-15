from __future__ import annotations

import curses
from types import SimpleNamespace
from typing import TYPE_CHECKING

from .keys import NAVIGATION_KEYS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .screens import ScreenStack
    from .window import ConsoleWindow


class OptionSpinner:
    def __init__(self, stack: ScreenStack | None = None) -> None:
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
        return self._default_obj

    @default_obj.setter
    def default_obj(self, value: object) -> None:
        self._default_obj = value
        if self.stack:
            self.stack.obj = value  # Keep in sync!

    @staticmethod
    def _make_option_ns() -> SimpleNamespace:
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
            self._subtract_scope(key, effective_scope)
            self._reject_key_conflicts(key, effective_scope)
            self._store_key_scope(key, ns, effective_scope)

        self.options.append(ns)
        self.align = max(self.align, self.margin+len(ns.descr))
        self.get_value(ns.attr, coerce=True)

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

    @staticmethod
    def _key_label(key: int) -> str:
        return chr(key) if 32 <= key < 127 else f'<{key}>'

    def _reject_navigation_key(self, key: int) -> None:
        if key in NAVIGATION_KEYS:
            raise ValueError(
                f'Key {self._key_label(key)} ({key}) conflicts with a navigation key. '
                f'Navigation keys are reserved for cursor movement and scrolling.'
            )

    def _subtract_scope(self, key: int, effective_scope: set) -> None:
        for existing_ns in self.options:
            if key in existing_ns.keys and hasattr(existing_ns, 'effective_scope'):
                overlap = existing_ns.effective_scope & effective_scope
                for screen_num in overlap:
                    self.key_scopes.pop((key, screen_num), None)
                existing_ns.effective_scope -= effective_scope

    def _reject_key_conflicts(self, key: int, effective_scope: set) -> None:
        for screen_num in effective_scope:
            if (key, screen_num) in self.key_scopes:
                existing_ns = self.key_scopes[(key, screen_num)]
                raise ValueError(
                    f'Key {self._key_label(key)} ({key}) already defined for screen {screen_num} '
                    f'in option "{existing_ns.descr}". Cannot define same key twice for same screen.'
                )

    def _store_key_scope(self, key: int, ns: SimpleNamespace, effective_scope: set) -> None:
        for screen_num in effective_scope:
            self.key_scopes[(key, screen_num)] = ns

        # Update global key tracking (if not using scopes, keep old behavior)
        if not self.stack:
            if key in self.key_to_option:
                raise ValueError(f'key ({chr(key)}, {key}) already used')
            self.key_to_option[key] = ns

        self.keys.add(key)

    def add(self, obj: object, specs: list) -> None:
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

        ns.scope = self._parse_scope(scope)
        self._register(ns)

    @staticmethod
    def _parse_keys(keys: int | str | list | tuple | set | None, descr: str) -> list[int]:
        if not keys:
            return [ord(descr[0])]

        raw = list(keys) if isinstance(keys, (list, tuple, set)) else [keys]
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

    @staticmethod
    def show_help_nav_keys(win: ConsoleWindow) -> None:
        # Late import to avoid a circular import at module load time.
        from .window import ConsoleWindow
        for line in ConsoleWindow.get_nav_keys_blurb().splitlines():
            if line:
                win.add_header(line)

    def show_help_body(self, win: ConsoleWindow, screen_filter: int | list | set | None = None) -> None:
        win.add_body('Type keys to alter choice:', curses.A_UNDERLINE)

        filter_screens = self._filter_screens(screen_filter)
        for ns in self.options:
            if self._skipped_by_filter(ns, filter_screens):
                continue
            self._write_option_body(win, ns)

    @staticmethod
    def _filter_screens(screen_filter: int | list | set | None) -> set | None:
        if screen_filter is None:
            return None
        if isinstance(screen_filter, int):
            return {screen_filter}
        if isinstance(screen_filter, (list, tuple, set)):
            return set(screen_filter)
        return None

    @staticmethod
    def _skipped_by_filter(ns: SimpleNamespace, filter_screens: set | None) -> bool:
        if filter_screens is None or not hasattr(ns, 'effective_scope'):
            return False
        return not (ns.effective_scope & filter_screens)

    def _write_option_body(self, win: ConsoleWindow, ns: SimpleNamespace) -> None:
        # get / coerce the current value
        value = self.get_value(ns.attr)
        assert value is not None, f'cannot get value of {ns.attr!r}'

        dot = ' ' if ns.genre == 'action' else '·'
        win.add_body(f'{ns.descr:{dot}<{self.align}} ')

        if ns.genre in ('cycle', 'prompt'):
            choices = ns.vals if ns.vals else [value]
            for choice in choices:
                win.add_body(' ', resume=True)
                win.add_body(self._format_choice(choice), resume=True,
                    attr=curses.A_REVERSE if choice == value else None)

        for comment in ns.comments:
            win.add_body(f'{"":>{self.align}}:  {comment}')

    @staticmethod
    def _format_choice(choice: object) -> str:
        if isinstance(choice, bool):
            return "ON" if choice else "off"
        return f'{choice}'

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
            value = win.answer(prompt=ns.prompt, seed=str(value))
        elif ns.genre == 'action':
            value = True

        setattr(ns.obj, ns.attr, value)
        return value
