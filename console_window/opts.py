from __future__ import annotations

import curses
import difflib
from typing import Any, Callable


class ConsoleWindowOpts:
    __slots__ = ['answer_show_redraws', 'body_cols', 'body_rows', 'ctrl_c_terminates',
                 'demo_mode', 'dialog_abort', 'dialog_return', 'head_line', 'head_rows',
                 'keys', 'min_cols_rows', 'mod_pick', 'pick_attr', 'pick_mode', 'pick_range',
                 'pick_size', 'relax_handled_keys', 'return_if_pos_change',
                 'single_cell_scroll_indicator', 'strip_attrs_in_pick_mode']

    # Explicit attribute types: assignments below come from **kwargs, so without
    # these every option would be typed as ``object`` and every read would need a
    # cast (AUDIT.md §3.4).  ``Any`` for kwargs keeps the dynamic API while the
    # stored attributes are checked.
    answer_show_redraws: bool
    body_cols: int
    body_rows: int
    ctrl_c_terminates: bool
    demo_mode: bool
    dialog_abort: str | None
    dialog_return: str
    head_line: bool
    head_rows: int
    keys: set | list | None
    min_cols_rows: tuple[int, int]
    mod_pick: Callable[[str], str] | None
    pick_attr: int
    pick_mode: bool
    pick_range: list[int] | None
    pick_size: int
    relax_handled_keys: bool
    return_if_pos_change: bool
    single_cell_scroll_indicator: bool
    strip_attrs_in_pick_mode: bool

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401 - dynamic options bag
        unknown = set(kwargs) - set(self.__slots__)
        if unknown:
            details = []
            for name in sorted(unknown):
                match = difflib.get_close_matches(name, self.__slots__, n=1)
                hint = f' (did you mean {match[0]!r}?)' if match else ''
                details.append(f'{name!r}{hint}')
            raise TypeError(
                f'ConsoleWindowOpts() got unknown option(s): {", ".join(details)}.')

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
