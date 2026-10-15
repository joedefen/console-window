from __future__ import annotations

from typing import Callable, Sequence, Union

# Accepted forms for a row's ``abut`` attribute (see :func:`cook_abut`).
AbutSpec = Union[int, Sequence[int], None]


def cook_abut(abut_value: AbutSpec) -> tuple[int, int] | None:
    if abut_value is None:
        return None

    if isinstance(abut_value, (list, tuple)):
        # Extract min negative and max positive
        before = min((x for x in abut_value if x < 0), default=0)
        after = max((x for x in abut_value if x >= 0), default=0)
        return (before, after)

    if isinstance(abut_value, int):
        if abut_value < 0:
            return (abut_value, 0)
        return (0, abut_value)

    return None


def compute_abut(explicit_abut: AbutSpec, transient_count: int) -> AbutSpec:
    if explicit_abut is not None:
        return explicit_abut
    if transient_count > 0:
        return [0, transient_count]
    return None


def calc_indicator(pos: int, pos0: int, pos9: int, ind0: int, ind9: int, max_scroll_pos: int) -> int:
    if max_scroll_pos <= 0:
        return -1  # not scrollable
    if pos9 - pos0 <= 0:
        return -1  # not scrollable
    if pos <= pos0:
        return ind0
    if pos >= pos9:
        return ind9
    ind = round(ind0 + (ind9 - ind0 + 1) * (pos - pos0) / (pos9 - pos0 + 1))
    return min(max(ind, ind0 + 1), ind9 - 1)


def scroll_indicator_row(scroll_pos: int, max_scroll_pos: int, scroll_view_size: int, body_base: int, rows: int) -> int:
    if max_scroll_pos <= 1:
        return body_base
    y2, y1 = scroll_view_size - 1, 1
    x2, x1 = max_scroll_pos, 1
    x = scroll_pos
    pos = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return min(body_base + int(max(pos, 0)), rows - 1)


def scroll_indicator_col(pick_mode: bool, pick_pos: int, scroll_pos: int, max_scroll_pos: int, body_row_cnt: int, cols: int) -> int:
    if pick_mode:
        return calc_indicator(pick_pos, 0, body_row_cnt - 1, 0, cols - 1, max_scroll_pos)
    return calc_indicator(scroll_pos, 0, max_scroll_pos, 0, cols - 1, max_scroll_pos)


def count_pickable_rows(is_pickable: Callable[[int], bool], row_cnt: int, start_pos: int, count: int, direction: int = 1) -> int:
    pos = start_pos
    pickable_count = 0
    while 0 <= pos < row_cnt and pickable_count < count:
        pos += direction
        if 0 <= pos < row_cnt and is_pickable(pos):
            pickable_count += 1
    return pos


def find_pickable(is_pickable: Callable[[int], bool], row_cnt: int, pick_pos: int) -> int:
    if 0 <= pick_pos < row_cnt and is_pickable(pick_pos):
        return pick_pos
    for offset in range(1, row_cnt):
        if pick_pos + offset < row_cnt and is_pickable(pick_pos + offset):
            return pick_pos + offset
        if pick_pos - offset >= 0 and is_pickable(pick_pos - offset):
            return pick_pos - offset
    return -1
