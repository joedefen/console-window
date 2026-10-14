"""Configuration object for :class:`~console_window.window.ConsoleWindow`."""

import curses


class ConsoleWindowOpts:
    """
    Options class for ConsoleWindow with enforced valid members using __slots__.
    All options have sensible defaults.
    """
    __slots__ = ['head_line', 'head_rows', 'body_rows', 'body_cols', 'keys',
                 'pick_mode', 'pick_size', 'mod_pick', 'pick_attr', 'pick_range', 'ctrl_c_terminates',
                 'return_if_pos_change', 'min_cols_rows', 'dialog_abort', 'dialog_return',
                 'single_cell_scroll_indicator', 'answer_show_redraws', 'strip_attrs_in_pick_mode',
                 'demo_mode', 'relax_handled_keys']

    def __init__(self, **kwargs):
        """
        Initialize ConsoleWindowOpts with defaults. All parameters are optional.

        :param head_line: If True, draws a horizontal line between header and body (default: True)
        :param head_rows: Maximum capacity of internal header pad (default: 50)
        :param body_rows: Maximum capacity of internal body pad (default: 200)
        :param body_cols: Maximum width for content pads (default: 200)
        :param keys: Collection of key codes explicitly returned by prompt (default: None)
        :param pick_mode: If True, enables item highlighting/selection (default: False)
        :param pick_size: Number of rows highlighted as single 'pick' unit (default: 1)
        :param mod_pick: Optional callable to modify highlighted text (default: None)
        :param pick_attr: Curses attribute for highlighting picked items (default: curses.A_REVERSE)
        :param pick_range: Column range [start, end] for pick highlighting; None highlights entire line (default: None)
        :param ctrl_c_terminates: If True, Ctrl-C terminates; if False, returns key 3 (default: True)
        :param return_if_pos_change: If True, prompt returns when pick position changes for immediate redraw (default: True)
        :param min_cols_rows: Minimum terminal size as (cols, rows) tuple (default: (70, 20))
        :param dialog_abort: How ESC aborts dialogs: None, "ESC", "ESC-ESC" (default: "ESC")
        :param dialog_return: Which key submits dialogs: "ENTER", "TAB" (default: "ENTER")
        :param single_cell_scroll_indicator: If True, shows single-cell position dot; if False, shows proportional range (default: False)
        :param strip_attrs_in_pick_mode: If True, strips attributes in pick mode (old behavior); if False, preserves them (default: False)
        :param relax_handled_keys: If True, passes all non-navigation keys to app without checking handled_keys list (default: True)
        """
        self.head_line = kwargs.get('head_line', True)
        self.head_rows = kwargs.get('head_rows', 50)
        self.body_rows = kwargs.get('body_rows', 200)
        self.body_cols = kwargs.get('body_cols', 200)
        self.keys = kwargs.get('keys')
        self.pick_mode = kwargs.get('pick_mode', False)
        self.pick_size = kwargs.get('pick_size', 1)
        self.mod_pick = kwargs.get('mod_pick')
        self.pick_attr = kwargs.get('pick_attr', curses.A_REVERSE)
        self.pick_range = kwargs.get('pick_range')  # [start_col, end_col] or None
        self.ctrl_c_terminates = kwargs.get('ctrl_c_terminates', True)
        self.return_if_pos_change = kwargs.get('return_if_pos_change', True)
        self.min_cols_rows = kwargs.get('min_cols_rows', (70, 20))
        self.dialog_abort = kwargs.get('dialog_abort', 'ESC')
        self.dialog_return = kwargs.get('dialog_return', 'ENTER')
        self.single_cell_scroll_indicator = kwargs.get('single_cell_scroll_indicator', False)
        self.answer_show_redraws = kwargs.get('answer_show_redraws', False)
        self.strip_attrs_in_pick_mode = kwargs.get('strip_attrs_in_pick_mode', False)
        self.demo_mode = kwargs.get('demo_mode', False)
        self.relax_handled_keys = kwargs.get('relax_handled_keys', True)

        # Validate dialog_abort
        if self.dialog_abort not in [None, 'ESC', 'ESC-ESC']:
            raise ValueError(f"dialog_abort must be None, 'ESC', or 'ESC-ESC', got {self.dialog_abort!r}")

        # Validate dialog_return
        if self.dialog_return not in ['ENTER', 'TAB']:
            raise ValueError(f"dialog_return must be 'ENTER' or 'TAB', got {self.dialog_return!r}")
