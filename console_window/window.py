"""ConsoleWindow: the curses pad/scroll/pick engine.

This module contains the high-level window class.  Related pieces live in
sibling modules: :mod:`console_window.theme`, :mod:`console_window.context`,
:mod:`console_window.opts`, :mod:`console_window.keys`,
:mod:`console_window.signals`, and :mod:`console_window.geometry`.
"""
# pylint: disable=too-many-instance-attributes,too-many-arguments
# pylint: disable=invalid-name,broad-except,too-many-branches,global-statement
# pylint: disable=line-too-long,too-many-statements,too-many-locals
# pylint: disable=too-many-return-statements,too-many-nested-blocks
# pylint: disable=multiple-statements,no-else-return

from __future__ import annotations

import atexit
import curses
import os
import re
import textwrap
import time
from curses.textpad import Textbox, rectangle
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable

from . import geometry, signals
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .theme import Theme

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import Context


class ConsoleWindow:
    """
    A high-level wrapper around the curses library that provides a structured
    interface for terminal applications.

    The screen is divided into a fixed-size **Header** area and a scrollable
    **Body** area, separated by an optional line. It manages screen
    initialization, cleanup, rendering, and user input including scrolling
    and an optional item selection (pick) mode.
    """
    timeout_ms: int = 2000
    static_scr: curses.window | None = None
    static_win: ConsoleWindow | None = None  # Reference to active ConsoleWindow instance for theme updates
    nav_keys: str = """
        Navigation:      H/M/L:      top/middle/end-of-page
          k, UP:  up one row             0, HOME:  first row
        j, DOWN:  down one row           $, END:  last row
          Ctrl-u:  half-page up     Ctrl-b, PPAGE:  page up
          Ctrl-d:  half-page down     Ctrl-f, NPAGE:  page down
    """
    def __init__(self, opts: ConsoleWindowOpts | None = None, head_line: bool | None = None,
                 head_rows: int | None = None, body_rows: int | None = None,
                 body_cols: int | None = None, keys: set | list | None = None,
                 pick_mode: bool | None = None, pick_size: int | None = None,
                 mod_pick: Callable | None = None, ctrl_c_terminates: bool | None = None) -> None:
        """
        Initializes the ConsoleWindow, sets up internal pads, and starts curses mode.

        :param opts: ConsoleWindowOpts instance with all options (recommended)
        :param head_line: DEPRECATED - use opts. If True, draws a horizontal line between header and body.
        :param head_rows: DEPRECATED - use opts. Maximum capacity of internal header pad.
        :param body_rows: DEPRECATED - use opts. Maximum capacity of internal body pad.
        :param body_cols: DEPRECATED - use opts. Maximum width for content pads.
        :param keys: DEPRECATED - use opts. Collection of key codes returned by prompt.
        :param pick_mode: DEPRECATED - use opts. If True, enables item highlighting/selection.
        :param pick_size: DEPRECATED - use opts. Number of rows highlighted as single pick unit.
        :param mod_pick: DEPRECATED - use opts. Optional callable to modify highlighted text.
        :param ctrl_c_terminates: DEPRECATED - use opts. If True, Ctrl-C terminates; if False, returns key 3.
        :type opts: ConsoleWindowOpts or None
        """
        # Enforce either opts OR deprecated parameters, not both
        has_opts = opts is not None
        has_deprecated = any(p is not None for p in [head_line, head_rows, body_rows, body_cols,
                                                       keys, pick_mode, pick_size, mod_pick, ctrl_c_terminates])

        if has_opts and has_deprecated:
            raise ValueError("Cannot use both 'opts' and deprecated parameters. Use opts only.")

        # Use opts or create default
        if has_opts:
            self.opts = opts
        elif has_deprecated:
            # Backward compatibility: create opts from deprecated parameters
            self.opts = ConsoleWindowOpts(
                head_line=head_line if head_line is not None else True,
                head_rows=head_rows if head_rows is not None else 50,
                body_rows=body_rows if body_rows is not None else 200,
                body_cols=body_cols if body_cols is not None else 200,
                keys=keys,
                pick_mode=pick_mode if pick_mode is not None else False,
                pick_size=pick_size if pick_size is not None else 1,
                mod_pick=mod_pick,
                ctrl_c_terminates=ctrl_c_terminates if ctrl_c_terminates is not None else True
            )
        else:
            # No parameters provided - use all defaults
            self.opts = ConsoleWindowOpts()

        # Configure SIGINT policy (Ctrl-C terminates, or is delivered as key 0x3).
        signals.set_ctrl_c_policy(self.opts.ctrl_c_terminates)
        self.ctrl_c_terminates = self.opts.ctrl_c_terminates

        self.scr = self._start_curses()
        # curses.window exposes no gettimeout(), so every place that sets a read
        # timeout records it here (via _set_scr_timeout).  This lets modal
        # dialogs such as answer() restore the timeout that was in effect before
        # they ran, instead of assuming the class default.
        self._scr_timeout_ms = ConsoleWindow.timeout_ms

        self.head = SimpleNamespace(
            pad=curses.newpad(self.opts.head_rows, self.opts.body_cols),
            rows=self.opts.head_rows,
            cols=self.opts.body_cols,
            row_cnt=0,  # no. head rows added
            texts = [],
            text_attrs = [],  # run-length encoded: [(attr, count), ...] per line
            contexts = [],  # Context object per line (or None)
            view_cnt=0,  # no. head rows viewable (NOT in body)
        )
        self.body = SimpleNamespace(
            pad = curses.newpad(self.opts.body_rows, self.opts.body_cols),
            rows= self.opts.body_rows,
            cols= self.opts.body_cols,
            row_cnt = 0,
            texts = [],
            text_attrs = [],  # run-length encoded: [(attr, count), ...] per line
            contexts = []  # Context object per line (or None)
        )

        # Apply theme background to pads
        if curses.has_colors():
            theme = Theme.THEMES.get(Theme.get_current(), Theme.THEMES['default'])
            if 'default_fg' in theme and 'default_bg' in theme:
                default_fg = theme['default_fg']
                default_bg = theme['default_bg']
                if default_fg != -1 or default_bg != -1:
                    self.head.pad.bkgd(' ', curses.color_pair(8))
                    self.body.pad.bkgd(' ', curses.color_pair(8))

        # Store reference for theme updates
        ConsoleWindow.static_win = self

        self.mod_pick = self.opts.mod_pick # call back to modify highlighted row
        self.hor_line_cnt = 1 if self.opts.head_line else 0 # no. h-lines in header
        self.scroll_pos = 0  # how far down into body are we?
        self.max_scroll_pos = 0
        self.pick_pos = 0 # in highlight mode, where are we?
        self.last_pick_pos = -1 # last highlighted position
        self.pick_mode = self.opts.pick_mode # whether in highlight mode
        self.pick_size = self.opts.pick_size # whether in highlight mode
        self.rows, self.cols = 0, 0
        self.body_cols, self.body_rows = self.opts.body_cols, self.opts.body_rows
        self.scroll_view_size = 0  # no. viewable lines of the body
        self.handled_keys = set(self.opts.keys) if isinstance(self.opts.keys, (set, list)) else set()
        self.pending_keys = set()
        self.last_demo_key = ''  # Last key pressed in demo mode
        self.max_header_len = 0  # Max visible header length from previous render
        self.passthrough_mode = False  # When True, all printable keys pass through
        self.relax_handled_keys = self.opts.relax_handled_keys  # When True, pass non-nav keys without checking handled_keys
        self._set_screen_dims()
        self.calc()

    def set_handled_keys(self, keys: object) -> None:
        """
        Set or update the keys that prompt() should return to the application.

        This allows keys to be set after initialization, breaking circular dependencies.

        :param keys: Collection of key codes (set, list, or OptionSpinner with .keys attribute)
        :type keys: set or list or OptionSpinner
        """
        if hasattr(keys, 'keys'):
            # It's an OptionSpinner or similar object
            self.handled_keys = set(keys.keys) if keys.keys else set()
        elif isinstance(keys, (set, list)):
            self.handled_keys = set(keys)
        else:
            self.handled_keys = set()

    def set_demo_mode(self, enabled: bool | None) -> bool:
        """
        Enable or disable demo mode. Passing None will toggle it.

        When demo mode is enabled, the last non-navigation key pressed is shown
        in reverse video at the end of the first header line.

        :param enabled: True to enable demo mode, False to disable
        :type enabled: bool
        """
        if enabled is None: # toggle if not explicit
            self.opts.demo_mode = not (self.opts.demo_mode)
        else:
            self.opts.demo_mode = bool(enabled)
        if not self.opts.demo_mode:
            self.last_demo_key = ''
        return self.opts.demo_mode

    def _format_key_for_demo(self, key: int) -> str:
        """
        Format a key code as a 3-character string for demo mode display.

        :param key: The key code to format
        :type key: int
        :returns: 3-character string representation of the key
        :rtype: str
        """
        # Special multi-character keys
        if key == 27:  # ESC
            return 'ESC'
        elif key == ord('\t'):
            return 'TAB'
        elif key == ord('\n') or key == curses.KEY_ENTER or key == 10 or key == 13:
            return 'ENT'
        elif key == ord(' '):
            return 'SPC'
        elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
            return 'BSP'
        elif key == curses.KEY_DC:
            return 'DEL'
        # Printable single character keys - center with spaces
        elif 32 < key < 127:
            return f' {chr(key)} '
        # Default for unrecognized keys
        else:
            return '???'

    def get_pad_width(self) -> int:
        """
        Returns the maximum usable column width for content drawing.

        :returns: The width in columns.
        :rtype: int
        """
        return min(self.cols-1, self.body_cols)

    def _is_pickable(self, row: int) -> bool:
        """
        Check if a body row is pickable.

        :param row: The row index to check
        :type row: int
        :returns: True if the row is pickable, False otherwise
        :rtype: bool
        """
        if row < 0 or row >= len(self.body.contexts):
            return True  # Default to pickable if no context
        ctx = self.body.contexts[row]
        if ctx is None:
            return True  # Default to pickable if no context
        return ctx.pickable

    def _count_pickable_rows(self, start_pos: int, count: int, direction: int = 1) -> int:
        """
        Move through count pickable rows from start_pos in the given direction.

        This skips non-pickable rows (DECOR, TRANSIENT) so that page-up/down
        moves through a consistent number of actual content rows.

        :param start_pos: Starting row position
        :param count: Number of pickable rows to count
        :param direction: 1 for forward, -1 for backward
        :type start_pos: int
        :type count: int
        :type direction: int
        :returns: The row position after counting pickable rows
        :rtype: int
        """
        return geometry.count_pickable_rows(
            self._is_pickable, self.body.row_cnt, start_pos, count, direction)

    def get_picked_context(self) -> Context | None:
        """
        Get the Context object for the currently picked line.

        :returns: The Context object for the current pick position, or None
        :rtype: Context or None
        """
        if not self.pick_mode:
            return None
        if self.pick_pos < 0 or self.pick_pos >= len(self.body.contexts):
            return None
        return self.body.contexts[self.pick_pos]

    def _cook_abut(self, abut_value: geometry.AbutSpec) -> tuple[int, int] | None:
        """
        Parse the abut attribute into [before, after] format.

        :param abut_value: Can be:
            - negative int: lines before (e.g., -3 -> [-3, 0])
            - positive int: lines after (e.g., 7 -> [0, 7])
            - list/tuple [before, after]: explicit range (e.g., [-5, 3])
        :returns: Tuple (before, after) where before <= 0 and after >= 0
        :rtype: tuple
        """
        return geometry.cook_abut(abut_value)

    def _get_effective_abut(self, row: int) -> geometry.AbutSpec:
        """
        Get the effective abut value for a row, either explicit or auto-calculated.

        For rows with TRANSIENT children, automatically calculates abut to show
        all consecutive TRANSIENT rows below.

        :param row: The row index to get abut for
        :type row: int
        :returns: Abut value (can be int, list, or None) suitable for _cook_abut()
        :rtype: int or list or None
        """
        if row < 0 or row >= len(self.body.contexts):
            return None

        ctx = self.body.contexts[row]
        if ctx is None:
            return None

        # Explicit abut takes precedence
        explicit = getattr(ctx, 'abut', None)

        # Auto-abut for TRANSIENT: count consecutive TRANSIENT rows below
        transient_count = 0
        for i in range(row + 1, self.body.row_cnt):
            next_ctx = self.body.contexts[i] if i < len(self.body.contexts) else None
            if next_ctx and next_ctx.genre == 'TRANSIENT':
                transient_count += 1
            else:
                break

        return geometry.compute_abut(explicit, transient_count)

    @staticmethod
    def get_nav_keys_blurb() -> str:
        """
        Returns a multiline string describing the default navigation key bindings
        for use in help screens.

        :returns: String of navigation keys.
        :rtype: str
        """
        return textwrap.dedent(ConsoleWindow.nav_keys)

    def _set_screen_dims(self) -> bool:
        """Recalculate dimensions based on current terminal size."""
        rows, cols = self.scr.getmaxyx()
        same = bool(rows == self.rows and cols == self.cols)
        self.rows, self.cols = rows, cols
        return same

    def _set_scr_timeout(self, ms: int) -> None:
        """Set the screen read timeout (milliseconds) and remember it.

        ``curses.window`` has no ``gettimeout()``, so the last value applied is
        tracked on the instance.  :meth:`answer` uses this to restore whatever
        timeout was in effect before the dialog ran, rather than resetting to
        the class default.

        :param ms: Read timeout in milliseconds (negative = block forever,
                   0 = non-blocking).
        :type ms: int
        """
        self._scr_timeout_ms = ms
        self.scr.timeout(ms)

    def _check_min_size(self) -> bool:
        """
        Checks if current terminal size meets minimum requirements.
        Blocks with a message if too small, waiting for resize or ESC.

        :returns: True if size is acceptable, False if user pressed ESC to abort
        :rtype: bool
        """
        min_cols, min_rows = self.opts.min_cols_rows

        while self.rows < min_rows or self.cols < min_cols:
            self.scr.clear()
            msg1 = f"Min size: {min_cols}x{min_rows}"
            msg2 = f"Current: {self.cols}x{self.rows}"
            try:
                self.scr.addstr(0, 0, msg1, curses.A_REVERSE)
                self.scr.addstr(1, 0, msg2, curses.A_REVERSE)
            except curses.error:
                pass  # Terminal too small even for message
            self.scr.refresh()

            # Wait for key
            key = self.scr.getch()
            if key == 27:  # ESC to abort
                return False
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
                self._set_screen_dims()

        return True

    @staticmethod
    def _start_curses() -> curses.window:
        """
        For compatibility only. Used to be private, but that was annoying.
        """
        return ConsoleWindow.start_curses()

    @staticmethod
    def start_curses() -> curses.window:
        """
        Performs the Curses initial setup: initscr, noecho, cbreak, curs_set(0),
        keypad(1), sets up the timeout, and initializes color pairs.

        :returns: The main screen object.
        :rtype: _curses.window
        """
        atexit.register(ConsoleWindow.stop_curses)
        signals.setup_ctrl_c()
        ConsoleWindow.static_scr = scr = curses.initscr()
        curses.set_escdelay(25)  # Reduce ESC key delay from 1000ms to 25ms
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        scr.keypad(1)
        scr.timeout(ConsoleWindow.timeout_ms)
        scr.clear()

        # Initialize color support with theme
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()  # Allow -1 for default terminal colors

            # Select theme from environment variable or default
            theme_name = os.environ.get('DWIPE_THEME', 'default')
            if theme_name not in Theme.THEMES:
                theme_name = 'default'
            Theme.set_active(theme_name)
            theme = Theme.THEMES[theme_name]

            # Set terminal background and foreground from theme
            if 'default_fg' in theme and 'default_bg' in theme:
                default_fg = theme['default_fg']
                default_bg = theme['default_bg']
                # Initialize pair 0 equivalent for default colors
                # Note: Can't change pair 0, so we set screen background directly
                if default_fg != -1 or default_bg != -1:
                    # Create a color pair for default colors and set screen background
                    curses.init_pair(8, default_fg, default_bg)
                    scr.bkgd(' ', curses.color_pair(8))

            # Initialize semantic color pairs based on selected theme
            for color_id in [Theme.DANGER, Theme.SUCCESS, Theme.WARNING,
                           Theme.INFO, Theme.EMPHASIS, Theme.ERROR, Theme.PROGRESS, Theme.HOTSWAP]:
                if color_id in theme:
                    fg, bg = theme[color_id]
                    curses.init_pair(color_id, fg, bg)

        return scr

    def set_pick_mode(self, on: bool = True, pick_size: int = 1) -> None:
        """
        Toggles the item highlighting/selection mode for the body area.

        If pick mode is enabled or the pick size changes, it forces a redraw
        of all body lines to clear any previous highlighting attributes.

        :param on: If True, enables pick mode.
        :param pick_size: The number of consecutive rows to highlight as one unit.
        :type on: bool
        :type pick_size: int
        """
        was_on, was_size = self.pick_mode, self.pick_size
        self.pick_mode = bool(on)
        self.pick_size = max(pick_size, 1)
        if self.pick_mode and (not was_on or was_size != self.pick_size):
            self.last_pick_pos = -2 # indicates need to clear them all

    def set_pick_range(self, start_col: int | None = None, end_col: int | None = None) -> None:
        """
        Set the column range for pick highlighting.

        :param start_col: Starting column (inclusive), None for full line
        :param end_col: Ending column (exclusive), None for full line
        :type start_col: int or None
        :type end_col: int or None
        """
        if start_col is None or end_col is None:
            self.opts.pick_range = None
        else:
            self.opts.pick_range = [start_col, end_col]
        # Force redraw of pick line
        if self.pick_mode:
            self.last_pick_pos = -2

    @staticmethod
    def stop_curses() -> None:
        """
        Curses shutdown (registered to be called on exit). Restores the terminal
        to its pre-curses state.
        """
        if ConsoleWindow.static_scr:
            curses.nocbreak()
            curses.echo()
            ConsoleWindow.static_scr.keypad(0)
            curses.endwin()
            ConsoleWindow.static_scr = None
            ConsoleWindow.static_win = None
            signals.teardown_ctrl_c()

    def calc(self) -> bool:
        """
        Recalculates the screen geometry, viewable areas, and maximum scroll position.

        :returns: True if the screen geometry has changed, False otherwise.
        :rtype: bool
        """
        same = self._set_screen_dims()
        self.head.view_cnt = min(self.rows - self.hor_line_cnt, self.head.row_cnt)
        self.scroll_view_size = self.rows - self.head.view_cnt - self.hor_line_cnt
        self.max_scroll_pos = max(self.body.row_cnt - self.scroll_view_size, 0)
        self.body_base = self.head.view_cnt + self.hor_line_cnt
        return not same

    def _add(self, ns: SimpleNamespace, text: str, attr: int | None = None,
             resume: bool = False, context: Context | None = None) -> None:
        """Internal method to add text to a pad using its namespace."""
        is_body = bool(id(ns) == id(self.body))
        if ns.row_cnt < ns.rows:
            row = max(ns.row_cnt - (1 if resume else 0), 0)
            if attr is None:
                attr = curses.A_NORMAL
            # Apply stripping logic if needed
            if is_body and self.pick_mode and self.opts.strip_attrs_in_pick_mode:
                attr = curses.A_NORMAL

            if resume:
                _, x = ns.pad.getyx()
                cols = self.get_pad_width() - x
                if cols > 0:
                    actual_text = text[0:cols]
                    ns.pad.addstr(actual_text, attr)
                    ns.texts[row] += actual_text
                    # Append to existing attrs list
                    if row < len(ns.text_attrs):
                        ns.text_attrs[row].append((attr, len(actual_text)))
                    # Note: context not updated on resume
            else:
                actual_text = text[0:self.cols]
                ns.pad.addstr(row, 0, actual_text, attr)
                ns.texts.append(actual_text)  # text only history
                ns.text_attrs.append([(attr, len(actual_text))])  # run-length encoded
                ns.contexts.append(context)  # Context metadata (or None)
                ns.row_cnt += 1

    def add_header(self, text: str, attr: int | None = None, resume: bool = False,
                   context: Context | None = None) -> None:
        """
        Adds a line of text to the header pad.

        :param text: The text to add.
        :param attr: Curses attribute (e.g., curses.A_BOLD).
        :param resume: If True, adds the text to the current, incomplete line.
        :param context: Optional Context object with metadata for this line.
        :type text: str
        :type attr: int or None
        :type resume: bool
        :type context: Context or None
        """
        self._add(self.head, text, attr, resume, context)

    def add_body(self, text: str, attr: int | None = None, resume: bool = False,
                 context: Context | None = None) -> None:
        """
        Adds a line of text to the body pad.

        :param text: The text to add.
        :param attr: Curses attribute (e.g., curses.A_BOLD).
        :param resume: If True, adds the text to the current, incomplete line.
        :param context: Optional Context object with metadata for this line.
        :type text: str
        :type attr: int or None
        :type resume: bool
        :type context: Context or None
        """
        self._add(self.body, text, attr, resume, context)

    def add_fancy_header(self, line: str, mode: str = 'Underline',
                         search_pattern_attr: int | None = None) -> None:
        """
        Parses header line and adds it with fancy formatting.

        Modes:
        - 'Off': Normal formatting (no special handling)
        - 'Underline': Underlined and bold keys
        - 'Reverse': Reverse video keys

        Converts [x]text to formatted x (brackets removed).
        Handles x:text patterns by formatting x.
        Handles /pattern by highlighting the entire pattern.
        Multi-character keys like ESC:, ENTER:, TAB: are supported.

        :param line: The header text to add with formatting
        :param mode: Formatting mode ('Off', 'Underline', or 'Reverse')
        :param search_pattern_attr: Optional custom attribute for /pattern highlighting
        :type line: str
        :type mode: str
        :type search_pattern_attr: int or None
        """
        if mode == 'Off':
            # Fancy mode off, just add the line normally
            self.add_header(line)
            return

        # Choose the attribute based on mode
        key_attr = (curses.A_UNDERLINE | curses.A_BOLD) if mode == 'Underline' else curses.A_REVERSE

        # List of (text, attr) tuples
        result_sections = []
        i = 0
        current_text = ""

        # Check if line starts with all-caps word and extract it
        stripped = line.lstrip()
        if stripped:
            first_word_match = stripped.split()[0] if stripped.split() else ''
            if first_word_match and re_match_word(first_word_match):
                # Add leading whitespace
                leading_space = line[:len(line) - len(stripped)]
                if leading_space:
                    result_sections.append((leading_space, None))
                # Add the all-caps word in BOLD
                result_sections.append((first_word_match, curses.A_BOLD))
                # Skip past it in our processing
                i = len(leading_space) + len(first_word_match)

        while i < len(line):
            # Check for [x]text pattern
            if line[i] == '[' and i + 2 < len(line) and line[i + 2] == ']':
                # Save any accumulated normal text
                if current_text:
                    result_sections.append((current_text, None))
                    current_text = ""

                # Extract the key letter and add it with chosen attribute
                key_char = line[i + 1]
                result_sections.append((key_char, key_attr))
                i += 3  # Skip past [x]

            # Check for multi-character key names like ESC:, ENTER:, TAB:
            elif (i == 0 or line[i - 1] == ' '):
                # Look ahead for uppercase word followed by colon
                match = re_match_key(line[i:])
                if match:
                    # Found a key name followed by colon
                    if current_text:
                        result_sections.append((current_text, None))
                        current_text = ""

                    key_name = match
                    result_sections.append((key_name, key_attr))
                    result_sections.append((':', None))  # Add the colon without formatting
                    i += len(key_name) + 1  # Skip past key and colon
                else:
                    match = re_match_pattern(line[i:])
                    if match:
                        # Found a search pattern
                        if current_text:
                            result_sections.append((current_text, None))
                            current_text = ""

                        full_pattern = match  # includes the /
                        # Use custom attr if provided, otherwise default bold+reverse
                        pattern_attr = search_pattern_attr if search_pattern_attr is not None else (curses.A_BOLD | curses.A_REVERSE)
                        result_sections.append((full_pattern, pattern_attr))
                        i += len(full_pattern)
                    else:
                        # Not a key pattern, just regular character
                        current_text += line[i]
                        i += 1

            else:
                # Regular character
                current_text += line[i]
                i += 1

        # Add any remaining text
        if current_text:
            result_sections.append((current_text, None))

        # Calculate visible length of this header line
        visible_length = sum(len(text) for text, attr in result_sections)

        # Check if this is the first header line
        is_first_header = (self.head.row_cnt == 0)

        # Add demo indicator to first header if demo mode is active
        if is_first_header and self.opts.demo_mode and self.last_demo_key:
            # Pad to max_header_len + 2 spaces
            padding_needed = max(0, self.max_header_len + 2 - visible_length)
            if padding_needed > 0:
                result_sections.append((' ' * padding_needed, None))
            # Add demo key in reverse video
            result_sections.append((self.last_demo_key, curses.A_REVERSE))

        # Now output the sections using add_header with resume
        for idx, (text, attr) in enumerate(result_sections):
            resume = bool(idx > 0)  # Resume for all but the first section
            self.add_header(text, attr=attr, resume=resume)

        # Track max header length for next render (excluding demo indicator)
        if visible_length > self.max_header_len:
            self.max_header_len = visible_length

    def draw(self, y: int, x: int, text: str, text_attr: int | None = None,
             width: int | None = None, leftpad: bool = False, header: bool = False) -> None:
        """
        Draws the given text at a specific position (row=y, col=x) on a pad.

        This method is useful for structured or overlay drawing, but is less
        efficient than the standard add/put methods.

        :param y: The row index on the pad.
        :param x: The column index on the pad.
        :param text: The text to draw (str or bytes).
        :param text_attr: Optional curses attribute.
        :param width: Optional fixed width for the drawn text (pads/truncates).
        :param leftpad: If True and ``width`` is used, left-pads with spaces.
        :param header: If True, draws to the header pad, otherwise to the body pad.
        :type y: int
        :type x: int
        :type text: str or bytes
        :type text_attr: int or None
        :type width: int or None
        :type leftpad: bool
        :type header: bool
        """
        ns = self.head if header else self.body
        text_attr = text_attr if text_attr else curses.A_NORMAL
        if y < 0 or y >= ns.rows or x < 0 or x >= ns.cols:
            return # nada if out of bounds
        ns.row_cnt = max(ns.row_cnt, y+1)

        uni = text if isinstance(text, str) else text.decode('utf-8')

        if width is not None:
            width = min(width, self.get_pad_width() - x)
            if width <= 0:
                return
            padlen = width - len(uni)
            if padlen > 0:
                if leftpad:
                    uni = padlen * ' ' + uni
                else:  # rightpad
                    uni += padlen * ' '
            text = uni[:width].encode('utf-8')
        else:
            text = uni.encode('utf-8')

        try:
            while y >= len(ns.texts):
                ns.texts.append('')
            ns.texts[y] = ns.texts[y][:x].ljust(x) + uni + ns.texts[y][x+len(uni):]
            ns.pad.addstr(y, x, text, text_attr)
        except curses.error:
            # curses errors on drawing the last character on the screen; ignore
            pass


    def highlight_picked(self) -> None:
        """
        Highlights the current selection and un-highlights the previous one.
        Called internally during :py:meth:`render_once` when in pick mode.
        """
        def get_text(pos: int) -> str:
            return self.body.texts[pos][0:self.cols] if pos < len(self.body.texts) else ''

        def get_attrs(pos: int) -> list:
            return self.body.text_attrs[pos] if pos < len(self.body.text_attrs) else None

        if not self.pick_mode:
            return
        pos0, pos1 = self.last_pick_pos, self.pick_pos
        if pos0 == -2: # special flag to clear all formatting
            for row in range(self.body.row_cnt):
                text = get_text(row).ljust(self.get_pad_width())
                attrs = get_attrs(row)
                self._draw_line_with_attrs(self.body.pad, row, 0, text, attrs, extra_attr=None)
        if pos0 != pos1:
            if 0 <= pos0 < self.body.row_cnt:
                for i in range(self.pick_size):
                    row_idx = pos0 + i
                    if row_idx < len(self.body.texts):
                        text = get_text(row_idx).ljust(self.get_pad_width())
                        attrs = get_attrs(row_idx)
                        self._draw_line_with_attrs(self.body.pad, row_idx, 0, text, attrs, extra_attr=None)
            if 0 <= pos1 < self.body.row_cnt:
                for i in range(self.pick_size):
                    row_idx = pos1 + i
                    if row_idx < len(self.body.texts):
                        text = get_text(row_idx)
                        if self.mod_pick:
                            text = self.mod_pick(text)
                        text = text.ljust(self.get_pad_width())
                        attrs = get_attrs(row_idx)

                        self._draw_line_with_attrs(self.body.pad, row_idx, 0, text, attrs,
                                                  extra_attr=self.opts.pick_attr,
                                                  extra_attr_range=self.opts.pick_range)
                self.last_pick_pos = pos1

    def _draw_line_with_attrs(self, pad: object, row: int, col_offset: int, text: str,
                              attrs: list, extra_attr: int | None = None,
                              extra_attr_range: tuple | None = None) -> None:
        """
        Draw a line using run-length encoded attributes.

        :param pad: The pad to draw on
        :param row: Row index in the pad
        :param col_offset: Starting column
        :param text: The text to draw
        :param attrs: Run-length encoded attributes [(attr, count), ...] or None
        :param extra_attr: Additional attribute to OR with each segment (e.g., A_REVERSE for highlighting)
        :param extra_attr_range: [start_col, end_col] range to apply extra_attr; None applies to entire line
        """
        if not attrs:
            # No stored attributes - draw with normal or extra_attr
            if extra_attr is not None and extra_attr_range:
                # Apply extra_attr only to the specified range
                start_col, end_col = extra_attr_range
                max_width = self.get_pad_width() - col_offset
                text = text[0:max_width]

                # Before range
                if start_col > 0:
                    pad.addstr(row, col_offset, text[0:start_col], curses.A_NORMAL)
                # Inside range
                range_text = text[start_col:end_col]
                if range_text:
                    pad.addstr(row, col_offset + start_col, range_text, extra_attr)
                # After range
                if end_col < len(text):
                    pad.addstr(row, col_offset + end_col, text[end_col:], curses.A_NORMAL)
            else:
                final_attr = extra_attr if extra_attr is not None else curses.A_NORMAL
                pad.addstr(row, col_offset, text[0:self.get_pad_width()-col_offset], final_attr)
            return

        # Handle run-length encoded attributes with optional range highlighting
        if extra_attr_range:
            range_start, range_end = extra_attr_range
        else:
            range_start, range_end = 0, len(text)

        col = col_offset
        pos = 0
        for attr, count in attrs:
            if pos >= len(text):
                break

            # Get the segment for this attribute run
            segment = text[pos:pos+count]
            segment_start = pos
            segment_end = pos + len(segment)

            # Split segment into parts: before range, in range, after range
            parts = []

            # Part before highlight range
            if segment_start < range_start and segment_end > segment_start:
                before_end = min(segment_end, range_start)
                before_text = text[segment_start:before_end]
                parts.append((before_text, attr, False))

            # Part inside highlight range
            in_range_start = max(segment_start, range_start)
            in_range_end = min(segment_end, range_end)
            if in_range_start < in_range_end:
                in_range_text = text[in_range_start:in_range_end]
                parts.append((in_range_text, attr, True))

            # Part after highlight range
            if segment_end > range_end and segment_start < segment_end:
                after_start = max(segment_start, range_end)
                after_text = text[after_start:segment_end]
                parts.append((after_text, attr, False))

            # Draw each part
            for part_text, part_attr, in_highlight in parts:
                if not part_text:
                    continue

                final_attr = part_attr
                if extra_attr is not None and in_highlight:
                    final_attr = part_attr | extra_attr

                # Ensure we don't exceed pad width
                max_len = self.get_pad_width() - col
                if max_len <= 0:
                    break
                part_text = part_text[0:max_len]

                pad.addstr(row, col, part_text, final_attr)
                col += len(part_text)

            pos += count

    def _scroll_indicator_row(self) -> int:
        """Internal helper to compute the scroll indicator row position."""
        return geometry.scroll_indicator_row(
            self.scroll_pos, self.max_scroll_pos, self.scroll_view_size,
            self.body_base, self.rows)

    def _scroll_indicator_col(self) -> int:
        """Internal helper to compute the scroll indicator column position."""
        return geometry.scroll_indicator_col(
            self.pick_mode, self.pick_pos, self.scroll_pos,
            self.max_scroll_pos, self.body.row_cnt, self.cols)

    def _calc_indicator(self, pos: int, pos0: int, pos9: int, ind0: int, ind9: int) -> int:
        """Internal helper to calculate indicator position based on content position."""
        return geometry.calc_indicator(pos, pos0, pos9, ind0, ind9, self.max_scroll_pos)

    def render(self, redraw: bool = False) -> None:
        """
        Draws the content of the pads to the visible screen.

        :param redraw: If True, forces a complete redraw of all pads and the screen
                    to clear terminal corruption.

        This method wraps :py:meth:`render_once` in a loop to handle spurious
        ``curses.error`` exceptions that can occur during screen resizing.
        """
        for _ in range(128):
            try:
                self.render_once(redraw)
                return
            except curses.error:
                time.sleep(0.16)
                self._set_screen_dims()
                continue
        try:
            self.render_once(redraw)
        except Exception:
            ConsoleWindow.stop_curses()
            print(f"""curses err:
    head.row_cnt={self.head.row_cnt}
    head.view_cnt={self.head.view_cnt}
    hor_line_cnt={self.hor_line_cnt}
    body.row_cnt={self.body.row_cnt}
    scroll_pos={self.scroll_pos}
    max_scroll_pos={self.max_scroll_pos}
    pick_pos={self.pick_pos}
    last_pick_pos={self.last_pick_pos}
    pick_mode={self.pick_mode}
    pick_size={self.pick_size}
    rows={self.rows}
    cols={self.cols}
""")
            raise


    def fix_positions(self, delta: int = 0) -> None:
        """
        Ensures the vertical scroll and pick positions are within valid boundaries,
        adjusting the scroll position to keep the pick cursor visible.

        :param delta: An optional change in position (e.g., from key presses).
        :type delta: int
        :returns: The indent amount for the body content (1 if pick mode is active, 0 otherwise).
        :rtype: int
        """
        self.calc()

        # Save old pick position to check for abut constraints before applying delta
        old_pick_pos = self.pick_pos if self.pick_mode else -1

        if self.pick_mode:
            self.pick_pos += delta
            # Also adjust scroll_pos in pick mode to allow showing DECOR lines
            # above/below the pick_pos when scrolling
            self.scroll_pos += delta
        else:
            self.scroll_pos += delta
            self.pick_pos += delta

        indent = 0
        if self.body_base < self.rows:
            ind_pos = 0 if self.pick_mode else self._scroll_indicator_row()
            if self.pick_mode:
                # First, get abut range from the PREVIOUS pick position (before delta was applied)
                abut_range = None
                if 0 <= old_pick_pos < len(self.body.contexts):
                    effective_abut = self._get_effective_abut(old_pick_pos)
                    if effective_abut is not None:
                        cooked = self._cook_abut(effective_abut)
                        if cooked:
                            before, after = cooked
                            # Calculate the valid line range based on old position
                            min_line = max(0, old_pick_pos + before)
                            max_line = min(self.body.row_cnt - 1, old_pick_pos + after)
                            abut_range = (min_line, max_line)

                # Clamp pick_pos to valid bounds
                self.pick_pos = max(self.pick_pos, 0)
                self.pick_pos = min(self.pick_pos, self.body.row_cnt-1)

                # If abut range exists, further constrain pick_pos within that range
                if abut_range:
                    min_line, max_line = abut_range
                    self.pick_pos = max(self.pick_pos, min_line)
                    self.pick_pos = min(self.pick_pos, max_line)

                if self.pick_pos >= 0:
                    self.pick_pos -= (self.pick_pos % self.pick_size)

                # Ensure pick_pos is on a pickable line (skip DECOR lines)
                if not self._is_pickable(self.pick_pos):
                    self.pick_pos = geometry.find_pickable(
                        self._is_pickable, self.body.row_cnt, self.pick_pos)

                # Re-check for abut in the CURRENT pick position for scroll adjustment
                abut_range = None
                effective_abut = self._get_effective_abut(self.pick_pos)
                if effective_abut is not None:
                    cooked = self._cook_abut(effective_abut)
                    if cooked:
                        before, after = cooked
                        # Calculate the valid line range: [min_line, max_line]
                        min_line = max(0, self.pick_pos + before)
                        max_line = min(self.body.row_cnt - 1, self.pick_pos + after)
                        abut_range = (min_line, max_line)

                if self.pick_pos < 0:
                    self.scroll_pos = 0
                elif abut_range:
                    # Apply abut constraints: "after trumps before"
                    min_line, max_line = abut_range
                    range_size = max_line - min_line + 1

                    if range_size <= self.scroll_view_size:
                        # Entire range fits: minimal scrolling to keep it visible
                        # Only scroll if the range would go off-screen
                        viewport_bottom = self.scroll_pos + self.scroll_view_size - 1

                        # Check if the range would go below viewport (prioritize "after" lines)
                        if max_line > viewport_bottom:
                            # Scroll down just enough to show max_line at the bottom
                            self.scroll_pos = max_line - self.scroll_view_size + 1
                        # Check if the range would go above viewport (but allow scrolling to show DECOR above)
                        elif min_line < self.scroll_pos and self.pick_pos < self.scroll_pos:
                            # Only enforce min_line constraint if pick_pos would go off top
                            # This allows scrolling up to show DECOR lines above the abut range
                            self.scroll_pos = min_line
                        # else: range is already fully visible, don't scroll
                    else:
                        # Range doesn't fit: minimal scrolling to keep picked line + abut lines visible
                        # Priority: keep "after" lines visible (they take precedence over "before" lines)

                        # Calculate the bottom of the current viewport
                        viewport_bottom = self.scroll_pos + self.scroll_view_size - 1

                        # Check if picked line + after lines would go below viewport
                        if max_line > viewport_bottom:
                            # Need to scroll down: position so max_line is at bottom of viewport
                            self.scroll_pos = max_line - self.scroll_view_size + 1
                        # Check if picked line + before lines would go above viewport
                        elif min_line < self.scroll_pos and self.pick_pos < self.scroll_pos:
                            # Need to scroll up: position so min_line is at top of viewport
                            # But allow scrolling further up to show DECOR lines
                            self.scroll_pos = min_line
                        # else: picked line + abut range is already fully visible, don't scroll

                        # Ensure we don't scroll too far down (beyond max_line)
                        # but allow scrolling above min_line to show DECOR headers
                        if self.pick_pos < self.scroll_pos:
                            # pick_pos would be off top - enforce min_line
                            self.scroll_pos = max(self.scroll_pos, min_line)
                        max_scroll = max_line - self.scroll_view_size + 1
                        self.scroll_pos = min(self.scroll_pos, max_scroll)
                elif self.scroll_pos > self.pick_pos:
                    # picked line would be above viewport - scroll up to show it
                    self.scroll_pos = self.pick_pos
                elif self.pick_pos >= self.scroll_pos + self.scroll_view_size:
                    # picked line would be below viewport bottom - scroll down to show it
                    self.scroll_pos = self.pick_pos - (self.scroll_view_size - self.pick_size)
                # Note: We allow scroll_pos < pick_pos to show DECOR lines above the picked item

                # Final clamping
                self.scroll_pos = max(self.scroll_pos, 0)
                self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)
                indent = 1
            else:
                self.scroll_pos = max(self.scroll_pos, 0)
                self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)
                self.pick_pos = self.scroll_pos + ind_pos - self.body_base
                # indent = 1 if self.body.row_cnt > self.scroll_view_size else 0
        return indent


    # Assuming this function is part of a class with attributes like self.scr, self.head, self.body, etc.

    def render_once(self, redraw: bool = False) -> None:
        """
        Performs the actual rendering of header, horizontal line, and body pads.
        Handles pick highlighting and scroll bar drawing.

        :param redraw: If True, forces a complete redraw of all pads and the screen
                    to clear terminal corruption.
        """

        # --- 1. Preparation and Conditional Redrawwin ---

        if redraw:
            # Mark the main screen and all pads as requiring a full repaint.
            self.scr.redrawwin()
            self.head.pad.redrawwin()
            self.body.pad.redrawwin()

        indent = self.fix_positions()

        # --- 2. Screen Drawing (Highlighting, Scrollbar, Separator) ---

        if indent > 0 and self.pick_mode:
            self.scr.vline(self.body_base, 0, ' ', self.scroll_view_size)
            if self.pick_pos >= 0:
                pos = self.pick_pos - self.scroll_pos + self.body_base
                self.scr.addstr(pos, 0, '>', curses.A_REVERSE)

        if self.head.view_cnt < self.rows:
            self.scr.hline(self.head.view_cnt, 0, curses.ACS_HLINE, self.cols)
            ind_pos = self._scroll_indicator_col()
            if ind_pos >= 0:
                bot, cnt = ind_pos, 1
                if not self.opts.single_cell_scroll_indicator and 0 < ind_pos < self.cols-1:
                    # Proportional range indicator
                    width = self.scroll_view_size/self.body.row_cnt*self.cols
                    bot = max(round(ind_pos-width/2), 1)
                    top = min(round(ind_pos+width/2), self.cols-1)
                    cnt = max(top - bot, 1)

                for idx in range(bot, bot+cnt):
                    self.scr.addch(self.head.view_cnt, idx, curses.ACS_HLINE, curses.A_REVERSE)

        # Instead of self.scr.refresh(), use pnoutrefresh/doupdate for efficiency.
        # The 'redrawwin' above handles the forced repaint, so we just call 'noutrefresh'.
        self.scr.noutrefresh()

        # --- 3. Pad Drawing (Body and Head) ---

        if self.body_base < self.rows:
            if self.pick_mode:
                self.highlight_picked()

            self.body.pad.noutrefresh(
                self.scroll_pos, 0,
                self.body_base, indent, self.rows-1, self.cols-1
            )

        if self.rows > 0:
            last_row = min(self.head.view_cnt, self.rows)-1
            if last_row >= 0:
                self.head.pad.noutrefresh(
                    0, 0,
                    0, indent, last_row, self.cols-1
                )

        # --- 4. Final Update (Only one physical screen update) ---
        curses.doupdate()


    def answer(self, prompt: str = 'Type string [then Enter]', seed: str = '', width: int = 80,
               height: int = 5, esc_abort: bool | None = None, prompt_attr: int | None = None) -> str | None:
        """
        Presents a modal dialog box with working horizontal scroll indicators.
        Uses opts.dialog_abort to determine ESC behavior and opts.dialog_return for submit key.

        :param esc_abort: DEPRECATED. Use opts.dialog_abort instead. If provided, overrides opts.dialog_abort.
        :param prompt_attr: Optional curses attribute for the prompt text (e.g., curses.color_pair(COLOR_RED))
        """
        # Handle deprecated esc_abort parameter for backward compatibility
        if esc_abort is not None:
            dialog_abort = 'ESC' if esc_abort else None
        else:
            dialog_abort = self.opts.dialog_abort

        # Remember the timeout in effect before the dialog so every exit path can
        # restore it; curses.window has no gettimeout(), so we track it ourselves.
        prev_timeout_ms = getattr(self, '_scr_timeout_ms', ConsoleWindow.timeout_ms)

        def draw_rectangle(scr: object, r1: int, c1: int, r2: int, c2: int) -> None:
            """Draws a box using standard curses characters."""
            scr.border(0)
            for r in range(r1, r2 + 1):
                if r == r1 or r == r2:
                    # Draw horizontal lines
                    for c in range(c1 + 1, c2):
                        scr.addch(r, c, curses.ACS_HLINE)
                if r > r1 and r < r2:
                    # Draw vertical lines
                    scr.addch(r, c1, curses.ACS_VLINE)
                    scr.addch(r, c2, curses.ACS_VLINE)
            # Draw corners
            scr.addch(r1, c1, curses.ACS_ULCORNER)
            scr.addch(r1, c2, curses.ACS_URCORNER)
            scr.addch(r2, c1, curses.ACS_LLCORNER)
            scr.addch(r2, c2, curses.ACS_LRCORNER)

        input_string = list(seed)
        cursor_pos = len(input_string)
        v_scroll_top = 0
        last_esc_time = None  # For ESC-ESC tracking

        def calculate_geometry(self: ConsoleWindow) -> None:
            # ... (Geometry calculation logic remains the same) ...
            self.rows, self.cols = self.scr.getmaxyx()
            min_cols, min_rows = self.opts.min_cols_rows
            min_height_needed = max(height + 4, min_rows)
            min_cols_needed = max(30, min_cols)
            if self.rows < min_height_needed or self.cols < min_cols_needed:
                return False, None, None, None, None

            max_display_width = self.cols - 6
            text_win_width = min(width, max_display_width)
            row0 = self.rows // 2 - (height // 2 + 1)
            row9 = row0 + height + 1
            col0 = (self.cols - (text_win_width + 2)) // 2

            return True, row0, row9, col0, text_win_width

        success, row0, row9, col0, text_win_width = calculate_geometry(self)
        if not success:
            # Terminal too small for dialog - return None to indicate failure
            # Returning seed here would be dangerous as it makes it appear the user accepted the default
            return None

        # Set longer timeout for dialog - redraw every 5s for screen recovery
        # This prevents flicker (was 200ms) while recovering from corruption
        self._set_scr_timeout(5000)  # 5 second timeout for auto-refresh

        # DEBUG: Set to True to show redraw indicator in upper-left corner
        debug_show_redraws = self.opts.answer_show_redraws
        debug_redraw_toggle = False

        while True:
            try:
                success, row0, row9, col0, text_win_width = calculate_geometry(self)

                # --- RESIZE/TOO SMALL CHECK ---
                if not success:
                    min_cols, min_rows = self.opts.min_cols_rows
                    min_height_needed = max(height + 4, min_rows)
                    min_cols_needed = max(30, min_cols)
                    self.scr.clear()
                    msg = f"Min size: {min_cols_needed}x{min_height_needed}"
                    try:
                        self.scr.addstr(0, 0, msg, curses.A_REVERSE)
                    except curses.error:
                        pass  # Terminal too small even for message
                    self.scr.noutrefresh()
                    curses.doupdate()
                    key = self.scr.getch()
                    if key in [27]:
                        self._set_scr_timeout(prev_timeout_ms)
                        return None
                    if key == curses.KEY_RESIZE: curses.update_lines_cols()
                    continue

                self.scr.clear()

                # Draw the box using the imported rectangle function
                draw_rectangle(self.scr, row0, col0, row9, col0 + text_win_width + 1)

                # DEBUG: Toggle indicator to visualize redraws
                if debug_show_redraws:
                    debug_redraw_toggle = not debug_redraw_toggle
                    indicator = '*' if debug_redraw_toggle else '+'
                    self.scr.addstr(row0, col0, indicator)

                if prompt_attr is not None:
                    self.scr.addstr(row0, col0 + 1, prompt[:text_win_width], prompt_attr | curses.A_BOLD)
                else:
                    self.scr.addstr(row0, col0 + 1, prompt[:text_win_width])

                # --- Core Display and Scroll Indicator Logic ---

                wrapped_line_idx = cursor_pos // text_win_width
                cursor_offset_on_wrapped_line = cursor_pos % text_win_width

                # Vertical scroll adjustment
                if wrapped_line_idx < v_scroll_top:
                    v_scroll_top = wrapped_line_idx
                elif wrapped_line_idx >= v_scroll_top + height:
                    v_scroll_top = wrapped_line_idx - height + 1

                # Horizontal scroll start calculation
                h_scroll_start = max(0, cursor_offset_on_wrapped_line - text_win_width + 1)

                # Calculate total wrapped lines for overflow detection
                total_wrapped_lines = (len(input_string) + text_win_width - 1) // text_win_width
                if len(input_string) == 0:
                    total_wrapped_lines = 1

                # Display the visible lines
                for r in range(height):
                    current_wrapped_line_idx = v_scroll_top + r

                    start_char_idx = current_wrapped_line_idx * text_win_width
                    end_char_idx = start_char_idx + text_win_width

                    if start_char_idx > len(input_string) and r > 0:
                        break

                    raw_wrapped_line = "".join(input_string[start_char_idx:end_char_idx])
                    line_to_display = raw_wrapped_line
                    current_h_scroll_start = 0

                    is_cursor_line = (current_wrapped_line_idx == wrapped_line_idx)

                    if is_cursor_line:
                        line_to_display = raw_wrapped_line[h_scroll_start:]
                        current_h_scroll_start = h_scroll_start

                    # 1. Clear the content area (important for redraw integrity)
                    self.scr.addstr(row0 + 1 + r, col0 + 1, ' ' * text_win_width)
                    # 2. Display the text
                    self.scr.addstr(row0 + 1 + r, col0 + 1, line_to_display[:text_win_width])

                    # --- SCROLL INDICATOR LOGIC ---
                    if is_cursor_line:
                        left_indicator = curses.ACS_VLINE
                        right_indicator = curses.ACS_VLINE

                        # Left Indicator Check
                        if current_h_scroll_start > 0:
                            # If content is scrolled right, show '<'
                            left_indicator = ord('<')

                        # Right Indicator Check
                        full_line_len = len(raw_wrapped_line)
                        if full_line_len > current_h_scroll_start + text_win_width:
                            # If there's more content to the right, show '>'
                            right_indicator = ord('>')

                        # Draw Indicators (overwrite the border's vertical line)
                        self.scr.addch(row0 + 1 + r, col0, left_indicator)
                        self.scr.addch(row0 + 1 + r, col0 + text_win_width + 1, right_indicator)

                        # Highlight the cursor position
                        display_cursor_pos = cursor_pos - start_char_idx - current_h_scroll_start
                        char_at_cursor = line_to_display[display_cursor_pos] if display_cursor_pos < len(line_to_display) else " "

                        self.scr.addstr(row0 + 1 + r, col0 + 1 + display_cursor_pos,
                                        char_at_cursor, curses.A_REVERSE)

                        # Set the actual hardware cursor
                        self.scr.move(row0 + 1 + r, col0 + 1 + display_cursor_pos)

                # --- CORNER OVERFLOW INDICATORS ---
                # Upper left (one line down): show if scrolled down or scrolled right
                has_content_above = v_scroll_top > 0
                has_content_left = h_scroll_start > 0
                if has_content_above or has_content_left:
                    self.scr.addch(row0 + 1, col0, '◀', curses.A_BOLD)

                # Lower right (one line up): show if there's content below or to the right
                has_content_below = (v_scroll_top + height) < total_wrapped_lines
                # Check if cursor line has content beyond the visible window
                cursor_line_start = wrapped_line_idx * text_win_width
                cursor_line_end = cursor_line_start + text_win_width
                cursor_line_full_len = min(len(input_string), cursor_line_end) - cursor_line_start
                has_content_right = cursor_line_full_len > (h_scroll_start + text_win_width)
                if has_content_below or has_content_right:
                    self.scr.addch(row9 - 1, col0 + text_win_width + 1, '▶', curses.A_BOLD)

                # Footer and refresh
                submit_key = self.opts.dialog_return
                abort = ''
                if dialog_abort == 'ESC':
                    abort = ' or ESC to abort'
                elif dialog_abort == 'ESC-ESC':
                    abort = ' or ESC-ESC to abort'
                ending = f'{submit_key} to submit{abort}'
                self.scr.addstr(row9, col0 + 1 + text_win_width - len(ending), ending[:text_win_width])
                self.scr.noutrefresh()
                curses.doupdate()
                curses.curs_set(0)  # Hide hardware cursor; reverse video shows position

                key = self.scr.getch()

                # --- Key Handling Logic ---
                # Handle dialog_return (submit)
                if self.opts.dialog_return == 'ENTER' and key in [10, 13]:
                    curses.curs_set(0)
                    self._set_scr_timeout(prev_timeout_ms)
                    return "".join(input_string)
                elif self.opts.dialog_return == 'TAB' and key == 9:
                    curses.curs_set(0)
                    self._set_scr_timeout(prev_timeout_ms)
                    return "".join(input_string)

                # Handle dialog_abort (ESC and ESC-ESC)
                if key == 27:
                    if dialog_abort == 'ESC':
                        self._set_scr_timeout(prev_timeout_ms)
                        return None
                    elif dialog_abort == 'ESC-ESC':
                        current_time = time.time()
                        if last_esc_time is not None and (current_time - last_esc_time) <= 1.0:
                            self._set_scr_timeout(prev_timeout_ms)
                            return None  # Double ESC within timeout
                        last_esc_time = current_time
                        # Single ESC - just update time and continue

                elif key == curses.KEY_UP:
                    target_pos = cursor_pos - text_win_width
                    cursor_pos = max(0, target_pos)

                elif key == curses.KEY_DOWN:
                    target_pos = cursor_pos + text_win_width
                    cursor_pos = min(len(input_string), target_pos)

                # ... [KEY_LEFT, KEY_RIGHT, HOME, END, edits, ASCII] ...
                elif key == curses.KEY_LEFT: cursor_pos = max(0, cursor_pos - 1)
                elif key == curses.KEY_RIGHT: cursor_pos = min(len(input_string), cursor_pos + 1)
                elif key == curses.KEY_HOME: cursor_pos = 0
                elif key == curses.KEY_END: cursor_pos = len(input_string)
                elif key in [curses.KEY_BACKSPACE, 127, 8]:
                    if cursor_pos > 0:
                        input_string.pop(cursor_pos - 1)
                        cursor_pos -= 1
                elif key == curses.KEY_DC:
                    if cursor_pos < len(input_string):
                        input_string.pop(cursor_pos)

                # Map special characters to space unless they're the dialog_return key
                elif key in [9, 10, 13]:
                    # Check if this is the dialog_return key
                    is_return_key = False
                    if self.opts.dialog_return == 'TAB' and key == 9:
                        is_return_key = True
                    elif self.opts.dialog_return == 'ENTER' and key in [10, 13]:
                        is_return_key = True

                    if not is_return_key:
                        # Convert to space
                        input_string.insert(cursor_pos, ' ')
                        cursor_pos += 1

                elif 32 <= key <= 126:
                    input_string.insert(cursor_pos, chr(key))
                    cursor_pos += 1

                # --- Explicit Resize Handler ---
                elif key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue

            except curses.error:
                # Catch exceptions from drawing outside bounds during resize
                self.scr.clear()
                curses.update_lines_cols()
                self.rows, self.cols = self.scr.getmaxyx()
                # Drain any pending resize events to prevent infinite loop
                self.scr.nodelay(True)  # Make getch() non-blocking
                while True:
                    key = self.scr.getch()
                    if key == -1:  # No more keys in queue
                        break
                self.scr.nodelay(False)  # Restore blocking mode
                continue


    def flash(self, message: str = '', duration: float = 2.0) -> None:
        """
        Displays a brief flash message in the center of the screen.
        Auto-dismisses after duration seconds without requiring user input.

        :param message: The message to display
        :param duration: How long to show the message in seconds (default 0.5)
        """

        if self.rows < 3 or self.cols < len(message) + 4:
            return

        # Calculate centered position
        msg_len = min(len(message), self.cols - 4)
        row = self.rows // 2
        col = (self.cols - msg_len - 2) // 2

        # Draw a simple box with the message
        self.scr.clear()
        try:
            # Top border
            self.scr.addstr(row - 1, col, '┌' + '─' * msg_len + '┐', curses.A_BOLD | curses.A_REVERSE)
            # Message
            self.scr.addstr(row, col, '│' + message[:msg_len] + '│', curses.A_BOLD | curses.A_REVERSE)
            # Bottom border
            self.scr.addstr(row + 1, col, '└' + '─' * msg_len + '┘', curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass  # Ignore if terminal too small

        self.scr.noutrefresh()
        curses.doupdate()
        time.sleep(duration)


    def alert(self, message: str = '', title: str = 'ALERT',
              _height: int | None = None, _width: int | None = None) -> None:
        """
        Displays a blocking, modal alert box with a title and message.
        Auto-sizes based on content and terminal size with 1-cell border.

        Waits for the user to press **ENTER** to acknowledge and dismiss the box.

        :param message: The message body content.
        :param title: The title text for the alert box (defaults to 'ALERT')
        :param height: DEPRECATED - ignored
        :param width: DEPRECATED - ignored
        :type title: str
        :type message: str
        """
        # Refresh the cached dimensions from the live screen first: a resize may
        # have happened since the last render, and everything below draws from
        # self.rows/self.cols (answer() recomputes for the same reason).
        self._set_screen_dims()

        # Auto-calculate dimensions with 1-cell border on all sides
        # Leave 1 cell on each side for reverse video border
        max_box_width = self.cols - 2  # 1 cell left, 1 cell right
        max_box_height = self.rows - 2  # 1 cell top, 1 cell bottom

        if max_box_width < 20 or max_box_height < 5:
            return  # Terminal too small

        # Calculate content width (box interior minus borders)
        content_width = max_box_width - 2  # Subtract box borders

        # Determine if title fits on box border, or needs to go inside
        footer_text = 'Press ENTER to ack'
        title_available_width = content_width - len(footer_text) - 2

        lines = []
        if len(title) > title_available_width:
            # Title too long - use "alert" as box title, put real title inside
            box_title = 'alert'
            # Wrap the actual title
            title_lines = textwrap.wrap(title, width=content_width)
            lines.extend(title_lines)
            lines.append('')  # Blank line separator
        else:
            # Title fits on box border
            box_title = title

        # Wrap message content
        if message:
            message_lines = textwrap.wrap(message, width=content_width)
            lines.extend(message_lines)

        # Calculate box dimensions - use full height with 1-cell border
        content_height = len(lines)
        box_height = max_box_height  # Use full available height

        # Calculate box position - 1 cell border on all sides
        row0 = 1  # 1 cell from top
        row9 = self.rows - 2  # 1 cell from bottom
        col0 = 1  # 1 cell from left
        col9 = self.cols - 2  # 1 cell from right

        # Clear screen normally (no reverse video)
        self.scr.clear()

        # Draw 1-cell reverse video border around the box area
        # Top and bottom borders (full width)
        self.scr.insstr(0, 0, ' '*self.cols, curses.A_REVERSE)
        self.scr.insstr(self.rows-1, 0, ' '*self.cols, curses.A_REVERSE)
        # Left and right borders
        for row in range(1, self.rows-1):
            self.scr.addch(row, 0, ' ', curses.A_REVERSE)
            self.scr.addch(row, self.cols-1, ' ', curses.A_REVERSE)

        # Draw box
        rectangle(self.scr, row0, col0, row9, col9)

        # Fill box interior with normal background (to override any reverse video)
        for row in range(row0+1, row9):
            self.scr.addstr(row, col0+1, ' '*(col9-col0-1))

        # Add title on top border
        self.scr.addstr(row0, col0+1, box_title[:content_width], curses.A_REVERSE)

        # Add footer on bottom border
        footer_pos = col0 + 1 + content_width - len(footer_text)
        self.scr.addstr(row9, footer_pos, footer_text[:content_width])

        # Create pad for scrollable content
        pad = curses.newpad(max(content_height, 1), content_width + 1)

        # Add lines to pad
        for idx, line in enumerate(lines):
            if idx < content_height:
                pad.addstr(idx, 0, line[:content_width])

        # Refresh screen
        self.scr.refresh()

        # Display content (scrollable if needed)
        visible_rows = box_height - 2  # Subtract top and bottom borders
        pad.refresh(0, 0, row0+1, col0+1, row0+visible_rows, col9-1)

        # Wait for ENTER using dummy Textbox.  Textbox.edit() only stops when
        # its validator returns the sentinel 7; _textbox_edit_on_enter maps the
        # ENTER key codes onto that sentinel so any ENTER acknowledges the alert.
        win = curses.newwin(1, 1, row9-1, col9-2)
        curses.curs_set(0)  # Ensure cursor is off
        Textbox(win).edit(_textbox_edit_on_enter).strip()
        return

    def clear(self) -> None:
        """
        Clears all content from both the header and body pads and resets internal
        counters in preparation for adding new screen content.
        """
        self.scr.clear()
        self.head.pad.clear()
        self.body.pad.clear()
        self.head.texts, self.body.texts, self.last_pick_pos = [], [], -1
        self.head.text_attrs, self.body.text_attrs = [], []
        self.head.contexts, self.body.contexts = [], []
        self.head.row_cnt = self.body.row_cnt = 0

    def prompt(self, seconds: float = 1.0) -> int | None:
        """
        Waits for user input for up to ``seconds``.

        Handles terminal resize events and built-in navigation keys, updating
        scroll/pick position as needed.

        :param seconds: The maximum time (float) to wait for input.
        :type seconds: float
        :returns: The key code if it is one of the application-defined ``keys``,
                  or None on timeout or if a navigation key was pressed.
        :rtype: int or None
        """
        ctl_b, ctl_d, ctl_f, ctl_u = 2, 4, 6, 21
        begin_mono = time.monotonic()
        while True:
            if time.monotonic() - begin_mono >= seconds:
                break
            while self.pending_keys:
                key = self.pending_keys.pop()
                if key in self.handled_keys:
                    return key

            key = self.scr.getch()
            if signals.ctrl_c_flag:
                if key in self.handled_keys:
                    self.pending_keys.add(key)
                signals.ctrl_c_flag = False # Reset flag
                if 0x3 in self.handled_keys:
                    return 0x3 # Return the ETX key code
                continue

            if key == curses.ERR:
                continue


            if key in (curses.KEY_RESIZE, ) or curses.is_term_resized(self.rows, self.cols):
                self._set_screen_dims()
                if not self._check_min_size():
                    # User pressed ESC to abort during size check
                    if 27 in self.handled_keys:
                        return 27
                break

            # App keys...
            # In passthrough mode, return all keys to the application (printable, editing, and navigation)
            # This allows InlineConfirmation and IncrementalSearchBar to decide which keys to handle
            if self.passthrough_mode:
                # Return all printable chars, editing keys, navigation keys, and handled_keys
                # Let the application decide what to do with each key
                editing_keys = {curses.KEY_BACKSPACE, 127, 8, 263,  # backspace variants
                              curses.KEY_LEFT, curses.KEY_RIGHT,
                              curses.KEY_HOME, curses.KEY_END,
                              1, 5}  # Ctrl-A, Ctrl-E
                if (32 <= key <= 126 or key in editing_keys or key in NAVIGATION_KEYS or key in self.handled_keys):
                    # Update demo mode tracking for non-navigation keys
                    if self.opts.demo_mode and key not in NAVIGATION_KEYS:
                        self.last_demo_key = self._format_key_for_demo(key)
                    return key

            # If relax_handled_keys is False, only pass keys explicitly in handled_keys
            # (Navigation keys will still be handled below)
            if not self.relax_handled_keys and key in self.handled_keys:
                # Update demo mode tracking for non-navigation keys
                if self.opts.demo_mode and key not in NAVIGATION_KEYS:
                    self.last_demo_key = self._format_key_for_demo(key)
                return key # return for handling

            # Navigation Keys...
            # Clear demo mode indicator when any navigation key is pressed
            if self.opts.demo_mode and key in NAVIGATION_KEYS:
                self.last_demo_key = ''

            pos = self.pick_pos if self.pick_mode else self.scroll_pos
            delta = self.pick_size if self.pick_mode else 1
            was_pos = pos
            if key in (ord('k'), curses.KEY_UP):
                pos -= delta
            elif key in (ord('j'), curses.KEY_DOWN):
                pos += delta
            elif key in (ctl_b, curses.KEY_PPAGE):
                pos -= self.scroll_view_size
            elif key in (ctl_u, ):
                pos -= self.scroll_view_size//2
            elif key in (ctl_f, curses.KEY_NPAGE):
                pos += self.scroll_view_size
            elif key in (ctl_d, ):
                pos += self.scroll_view_size//2
            elif key in (ord('0'), curses.KEY_HOME):
                pos = 0
            elif key in (ord('$'), curses.KEY_END):
                pos = self.body.row_cnt - 1
            elif key in (ord('H'), ):
                pos = self.scroll_pos
            elif key in (ord('M'), ):
                pos = self.scroll_pos + self.scroll_view_size//2
            elif key in (ord('L'), ):
                pos = self.scroll_pos + self.scroll_view_size-1

            # Skip non-pickable lines in pick mode
            scroll_adjustment = 0  # Track if we should adjust scroll even when pick doesn't move
            if self.pick_mode and pos != was_pos:
                # Determine direction of movement
                direction = 1 if pos > was_pos else -1

                # Find next pickable line in the direction of movement
                attempts = 0
                max_attempts = self.body.row_cnt + 1  # Prevent infinite loop

                while 0 <= pos < self.body.row_cnt and not self._is_pickable(pos) and attempts < max_attempts:
                    pos += direction
                    attempts += 1

                # If we went out of bounds or found no pickable line, stay at current position
                # BUT still allow scrolling to reveal DECOR lines
                if pos < 0 or pos >= self.body.row_cnt or attempts >= max_attempts:
                    # Check if there are non-pickable lines in the direction we're trying to go
                    # that could be revealed by scrolling
                    check_pos = was_pos + direction
                    if 0 <= check_pos < self.body.row_cnt and not self._is_pickable(check_pos):
                        # There's a DECOR/TRANSIENT line in that direction - allow scroll adjustment
                        scroll_adjustment = direction
                    pos = was_pos

            if self.pick_mode:
                self.pick_pos = pos
                # If pick_pos didn't move but there are DECOR lines to reveal, adjust scroll
                if scroll_adjustment != 0 and pos == was_pos:
                    self.scroll_pos += scroll_adjustment
            else:
                self.scroll_pos = pos
                self.pick_pos = pos

            self.fix_positions()

            # Render if position changed OR if we adjusted scroll to reveal DECOR lines
            if pos != was_pos or scroll_adjustment != 0:
                if self.opts.return_if_pos_change:
                    # Don't render with stale content; return immediately to allow full redraw
                    return None
                else:
                    # Only render here if we're not going to redraw immediately
                    self.render()
            else:
                # Navigation key didn't match - if relax_handled_keys is True, pass key to app
                if self.relax_handled_keys:
                    # Update demo mode tracking for non-navigation keys
                    if self.opts.demo_mode and key not in NAVIGATION_KEYS:
                        self.last_demo_key = self._format_key_for_demo(key)
                    return key
        return None


def _textbox_edit_on_enter(key: int) -> int:
    """Exit ``curses.textpad.Textbox.edit`` as soon as ENTER is pressed.

    ``Textbox.edit(validator)`` has no dedicated "stop" return value: it keeps
    reading keys until the *validator* returns the sentinel code ``7`` (Ctrl-G).
    To make a single ENTER press acknowledge :meth:`ConsoleWindow.alert`, map the
    Enter key codes (``10`` and ``curses.KEY_ENTER``) onto that sentinel and pass
    every other key through untouched so ``Textbox`` still performs editing.

    :param key: Key code delivered by ``Textbox`` to the validator.
    :type key: int
    :returns: ``7`` for ENTER (which stops editing), otherwise ``key`` unchanged.
    :rtype: int
    """
    # 7 is BEL / Ctrl-G, Textbox.do_command()'s "end edit" control code.
    return 7 if key in (10, curses.KEY_ENTER) else key


def re_match_word(word: str) -> bool:
    """Return True if ``word`` is a simple \\w/- token (used by add_fancy_header)."""
    return bool(re.match(r'^[\w-]+$', word))


def re_match_key(s: str) -> str | None:
    """Match a leading multi-character key name followed by ':' (e.g. 'ESC:')."""
    match = re.match(r'([A-Z]{2,}|[A-Z]):', s)
    return match.group(1) if match else None


def re_match_pattern(s: str) -> str | None:
    """Match a leading /search-pattern token (including the slash)."""
    match = re.match(r'/(\S+)', s)
    return match.group(0) if match else None
