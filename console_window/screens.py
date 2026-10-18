from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .spinner import OptionSpinner

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .window import ConsoleWindow


class _AppLike(Protocol):
    # The only part of the host application a Screen touches at construction.
    win: ConsoleWindow


# Default home screen constant (applications should define their own)
HOME_ST = 0


class Screen:
    # Navigation control (class attributes - override in subclasses)
    come_from_whitelist = None  # None = can come from any screen, else list of screen numbers
    is_terminal = False         # True = cannot be pushed onto stack
    cannot_stack_me = False     # True = cannot have other screens pushed on top

    def __init__(self, app: _AppLike) -> None:
        self.app = app  # Reference to main application instance
        self.win = app.win
        self._cached_spinner: OptionSpinner | None = None  # Lazy-loaded spinner reference

    def draw_screen(self) -> None:
        pass

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
            method()
            return True
        return False


class ScreenStack:
    def __init__(self, win: ConsoleWindow, spins_obj: object, screens: tuple,
                 screen_objects: dict[int, Screen] | None = None) -> None:
        from types import SimpleNamespace
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        # Dict of screen_num -> Screen instance
        self.screen_objects: dict[int, Screen] = screen_objects or {}
        self.stack: list[SimpleNamespace] = []
        self.curr: SimpleNamespace | None = None
        self._SimpleNamespace = SimpleNamespace
        # Push home screen (HOME_ST=0) as the initial screen
        self.push(HOME_ST, 0)

    def push(self, screen: int, prev_pos: int | None = None, force: bool = False) -> int | None:
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
            self.curr.pick_pos = self.win.pick_pos
            self.curr.scroll_pos = self.win.scroll_pos
            self.curr.prev_pos = prev_pos
            self.stack.append(self.curr)
        self.curr = self._SimpleNamespace(num=screen,
                  name=self.screens[screen], pick_pos=-1,
                                scroll_pos=-1, prev_pos=-1)
        self.win.pick_pos = self.win.scroll_pos = 0
        # Entering a screen starts a fresh pick/scroll pairing; drop any
        # free-scroll state left over from the screen we came from.
        self.win.free_scroll = False

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

        # Navigation approved - proceed
        self.curr = self.stack.pop()
        self.win.pick_pos = self.curr.pick_pos
        self.win.scroll_pos = self.curr.scroll_pos
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
        val = getattr(self.obj, action)
        setattr(self.obj, action, False)
        return val and (screens is None or self.is_curr(screens))

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
    def draw_screen(self) -> None:
        win = self.win
        self.win.set_pick_mode(False)
        spinner = self.get_spinner()
        if spinner:
            spinner.show_help_nav_keys(win)
            spinner.show_help_body(win)
