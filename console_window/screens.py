"""Screen base class and stack-based navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .spinner import OptionSpinner

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .window import ConsoleWindow


# Default home screen constant (applications should define their own)
HOME_ST = 0


class Screen:
    """
    Base class for all screen types in a screen stack navigation system.

    Screen objects represent individual UI screens/views that can be stacked
    on top of each other, providing a navigation history similar to a web
    browser.

    Class Attributes (override in subclasses):
        come_from_whitelist (list[int] | None): Restricts which screens can navigate
            to this screen. None = any screen can navigate here, otherwise only screens
            in the list can navigate to this screen.
        is_terminal (bool): If True, this screen cannot be pushed onto the stack
            (i.e., it must replace the current screen entirely).
        cannot_stack_me (bool): If True, no other screens can be pushed on top
            of this screen. Useful for modal screens or final destinations.

    Instance Attributes:
        app: Reference to the main application instance
        win (ConsoleWindow): Reference to the console window for drawing
    """
    # Navigation control (class attributes - override in subclasses)
    come_from_whitelist = None  # None = can come from any screen, else list of screen numbers
    is_terminal = False         # True = cannot be pushed onto stack
    cannot_stack_me = False     # True = cannot have other screens pushed on top

    def __init__(self, app):
        """
        Initialize the screen with references to the application and window.
        Called once when screen is first created.

        Args:
            app: Main application instance (should have a 'win' attribute)
        """
        self.app = app  # Reference to main application instance
        self.win = app.win
        self._cached_spinner = None  # Lazy-loaded spinner reference

    def draw_screen(self):
        """
        Draw screen-specific content (header and body).

        Override this method in subclasses to implement the screen's UI.
        Use self.win.add_header() and self.win.add_body() to populate content.

        Example:
            def draw_screen(self):
                self.win.add_header("My Screen Title")
                self.win.add_body("Screen content goes here")
        """
        pass

    def on_pause(self):
        """
        Called when another screen is about to be pushed on top of this one.

        Returns:
            True to allow being paused/covered, False to reject
        """
        return not self.cannot_stack_me

    def on_resume(self):
        """
        Called when this screen becomes the top screen again
        (after a screen that was on top of it was popped).

        Returns:
            True to allow resuming (typically always True)
        """
        return True

    def on_pop(self):
        """
        Called when this screen is being permanently removed from the stack.
        Must always succeed - use for cleanup only.

        Returns:
            Always returns True (cleanup cannot be rejected)
        """
        return True

    def get_spinner(self):
        """
        Find and return the OptionSpinner instance from the app.

        Searches through the app's attributes to find an OptionSpinner instance.
        Caches the result for performance.

        Returns:
            OptionSpinner: The spinner instance, or None if not found

        Example:
            spinner = self.get_spinner()
            if spinner:
                spinner.show_help_nav_keys(self.win)
        """
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

    def handle_action(self, action_name):
        """
        Dispatch action to screen-specific handler method.

        Looks for a method named '{action_name}_ACTION' (uppercase) and calls it
        if it exists. This provides a convention-based way to handle actions.

        Args:
            action_name (str): The action name to dispatch (e.g., 'quit', 'save')

        Returns:
            bool: True if action was handled (method exists), False otherwise

        Example:
            # In your Screen subclass:
            def quit_ACTION(self):
                sys.exit(0)

            # Then call:
            screen.handle_action('quit')  # Calls quit_ACTION()
        """
        method_name = f'{action_name}_ACTION'
        method = getattr(self, method_name, None)
        if method and callable(method):
            method()
            return True
        return False


class ScreenStack:
    """
    A stack-based screen navigation system for terminal applications.

    Manages a stack of screens (like a browser history), allowing screens to be
    pushed onto and popped from the stack. Each screen can maintain its own state
    (scroll position, pick position, etc.) which is restored when returning to it.

    The ScreenStack integrates with Screen objects and ConsoleWindow to provide:
    - Navigation validation (come_from whitelist, terminal screens, etc.)
    - Lifecycle hooks (on_pause, on_resume, on_pop)
    - State preservation (scroll/pick positions)
    - Loop prevention (can't push same screen twice)

    Example usage:
        # 1. Define screen constants
        HOME_ST, SETTINGS_ST, HELP_ST = 0, 1, 2
        SCREENS = ['HOME', 'SETTINGS', 'HELP']

        # 2. Create Screen subclasses
        class HomeScreen(Screen):
            def draw_screen(self):
                self.win.add_header("Home Screen")
                self.win.add_body("Welcome to the app")

        class SettingsScreen(Screen):
            def draw_screen(self):
                self.win.add_header("Settings")
                self.win.add_body("Configure your settings here")

        # 3. Initialize screen objects
        screens = {
            HOME_ST: HomeScreen(app),
            SETTINGS_ST: SettingsScreen(app),
            HELP_ST: HelpScreen(app),
        }

        # 4. Create ScreenStack
        ss = ScreenStack(win, app, SCREENS, screens)

        # 5. Navigate between screens
        ss.push(SETTINGS_ST, 0)  # Go to settings
        ss.pop()                  # Go back to home
    """

    def __init__(self, win: ConsoleWindow, spins_obj: object, screens: tuple, screen_objects: dict = None):
        """
        Initialize the ScreenStack with a home screen.

        Args:
            win (ConsoleWindow): The console window instance
            spins_obj: Application object (typically holds OptionSpinner and state)
                      IMPORTANT: If using OptionSpinner, pass your options namespace here
                      to ensure proper object linking. See warning below.
            screens (tuple): Tuple of screen names (e.g., ['HOME', 'SETTINGS', 'HELP'])
            screen_objects (dict): Dict mapping screen numbers to Screen instances

        .. warning::
            **Initialization Order Matters!**

            When using ScreenStack with OptionSpinner, follow this pattern:

            .. code-block:: python

                # CORRECT - Pass opts to ScreenStack
                opts = SimpleNamespace()
                stack = ScreenStack(win, opts, SCREENS, screen_objects)
                spinner = OptionSpinner(stack=stack)
                # spinner.default_obj now points to opts via stack.obj

                # INCORRECT - Don't pass None then reassign
                stack = ScreenStack(win, None, SCREENS, screen_objects)
                spinner = OptionSpinner(stack=stack)
                spinner.default_obj = opts  # Creates object fragmentation!

            The OptionSpinner syncs with stack.obj, so they must use the same object
            from the start to avoid different parts of the code using different namespaces.
        """
        from types import SimpleNamespace
        self.win = win
        self.obj = spins_obj
        self.screens = screens
        self.screen_objects = screen_objects or {}  # Dict of screen_num -> Screen instance
        self.stack = []
        self.curr = None
        self._SimpleNamespace = SimpleNamespace
        # Push home screen (HOME_ST=0) as the initial screen
        self.push(HOME_ST, 0)

    def push(self, screen, prev_pos=None, force=False):
        """
        Push a new screen onto the stack with validation and loop prevention.

        Args:
            screen: Screen number to push
            prev_pos: Previous cursor position
            force: Skip validation hooks if True

        Returns:
            Previous position if successful, None if blocked by validation
        """
        if prev_pos is None:
            prev_pos = self.win.pick_pos
        # Loop prevention: Check if screen is already on the stack
        if not force and self.curr and screen == self.curr.num:
            # Trying to push the current screen again - ignore
            return None

        # Check if screen is already in the stack (deeper loop)
        if not force:
            for stacked_screen in self.stack:
                if stacked_screen.num == screen:
                    # Would create a loop - block it
                    return None

        from_screen_num = self.curr.num if self.curr else None
        new_screen_obj = self.screen_objects.get(screen) if self.screen_objects else None

        # Check navigation constraints
        if not force and new_screen_obj:
            # Check if screen is terminal (cannot be pushed)
            if new_screen_obj.is_terminal:
                return None

            # Check come_from whitelist
            if new_screen_obj.come_from_whitelist is not None:
                if from_screen_num not in new_screen_obj.come_from_whitelist:
                    # Navigation from this screen not allowed
                    return None

        # Call on_pause() on current screen (it's being covered)
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
            if current_screen_obj:
                if not current_screen_obj.on_pause():
                    # Current screen rejected being paused
                    return None

        # Navigation approved - proceed
        if self.curr:
            self.curr.pick_pos = self.win.pick_pos
            self.curr.scroll_pos = self.win.scroll_pos
            self.curr.prev_pos = prev_pos
            self.stack.append(self.curr)
        self.curr = self._SimpleNamespace(num=screen,
                  name=self.screens[screen], pick_pos=-1,
                                scroll_pos=-1, prev_pos=-1)
        self.win.pick_pos = self.win.scroll_pos = 0
        return 0

    def get_curr_obj(self):
        """ get the current screen object """
        if self.curr:
            return self.screen_objects.get(self.curr.num, None)
        return None

    def pop(self, force=False):
        """
        Pop the top screen from the stack.
        on_pop() is always called for cleanup (cannot be rejected).
        on_resume() is called on the screen being returned to (typically always succeeds).

        Args:
            force: Skip validation hooks if True

        Returns:
            Previous position if successful, None if stack is empty
        """
        if not self.stack:
            return None

        to_screen_num = self.stack[-1].num
        from_screen_num = self.curr.num if self.curr else None

        # Call on_pop() on current screen (it's being removed - always succeeds)
        if not force and self.curr and self.screen_objects:
            current_screen_obj = self.screen_objects.get(from_screen_num)
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

    def is_curr(self, screens):
        """
        Check if the current screen matches any of the given screen(s).

        Args:
            screens: A single screen (int or str) or a list/tuple of screens.
                    Int values are compared against screen numbers.
                    String values are compared against screen names.

        Returns:
            bool: True if current screen matches any of the provided screens

        Example:
            if ss.is_curr(HOME_ST):
                print("On home screen")
            if ss.is_curr([HOME_ST, SETTINGS_ST]):
                print("On home or settings")
            if ss.is_curr('HOME'):
                print("On home screen (by name)")
        """
        def test_one(screen):
            if isinstance(screen, int):
                return screen == self.curr.num
            return str(screen) == self.curr.name
        if isinstance(screens, (tuple, list)):
            return any(test_one(screen) for screen in screens)
        return test_one(screen=screens)

    def act_in(self, action, screens=None):
        """
        Check if an action flag is set and optionally if we're on specific screen(s).

        This is a convenience method that:
        1. Gets the value of self.obj.{action}
        2. Resets self.obj.{action} to False
        3. Returns True only if the action was True AND (screens is None OR current screen matches)

        Useful for handling action flags from OptionSpinner with genre='action'.

        Args:
            action (str): Name of the action attribute to check (e.g., 'quit', 'save')
            screens: Optional screen filter (int, str, or list). If provided, action
                    only returns True if we're on one of these screens.

        Returns:
            bool: True if action was set and screen matches (if specified)

        Example:
            # In your main loop:
            if ss.act_in('quit'):
                sys.exit(0)
            if ss.act_in('save', HOME_ST):
                # Only save if we're on home screen
                save_data()
        """
        val = getattr(self.obj, action)
        setattr(self.obj, action, False)
        return val and (screens is None or self.is_curr(screens))

    def perform_actions(self, spinner):
        """
        Automatically handle all pending actions for the current screen.

        This method iterates through ALL action options from the OptionSpinner,
        clears any set flags, and calls the corresponding *_ACTION method if it
        exists on the current screen.

        IMPORTANT: This clears ALL action flags, even if the current screen doesn't
        have a handler. This prevents actions from having delayed/unexpected effects
        when navigating between screens.

        Args:
            spinner (OptionSpinner): The OptionSpinner instance containing action definitions

        Returns:
            int: Number of actions that were performed (called handlers)

        Example:
            # In your main loop (replaces manual action checking):
            while True:
                self.screens[screen_num].draw_screen()
                self.win.render()
                key = self.win.prompt()
                if key:
                    self.spinner.do_key(key, self.win)
                    self.ss.perform_actions(self.spinner)  # Handles all actions automatically

            # Old way (what this replaces):
            for action in ['quit', 'help', 'save', 'load']:
                if self.ss.act_in(action):
                    current_screen.handle_action(action)
        """
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
    """
    Example help screen implementation.

    Displays navigation keys and help information from an OptionSpinner.
    Assumes the app object has a 'spinner' attribute (OptionSpinner instance).

    This is a reference implementation that can be used as-is or customized
    for your application's specific help screen needs.
    """
    def draw_screen(self):
        """
        Draw the help screen content.

        Displays:
        1. Navigation keys blurb (from OptionSpinner.show_help_nav_keys)
        2. Application options help (from OptionSpinner.show_help_body)
        """
        win = self.win
        self.win.set_pick_mode(False)
        spinner = self.get_spinner()
        if spinner:
            spinner.show_help_nav_keys(win)
            spinner.show_help_body(win)
