"""Pure scroll/pick geometry helpers.

These functions contain no curses or instance state so they can be unit-tested
without a terminal.  ``ConsoleWindow`` delegates its geometry math here.
"""

from __future__ import annotations

from typing import Callable, Sequence, Union

# Accepted forms for a row's ``abut`` attribute (see :func:`cook_abut`).
AbutSpec = Union[int, Sequence[int], None]


def cook_abut(abut_value: AbutSpec) -> tuple[int, int] | None:
    """
    Parse an ``abut`` attribute into a ``(before, after)`` tuple.

    :param abut_value: Can be:
        - ``None``: no constraint (returns None)
        - negative int: lines before (e.g., -3 -> (-3, 0))
        - positive int: lines after (e.g., 7 -> (0, 7))
        - list/tuple: min negative and max positive are used
          (e.g., [-8, 3, -2, 12] -> (-8, 12))
    :returns: Tuple ``(before, after)`` where ``before <= 0`` and ``after >= 0``,
              or ``None`` if unparseable.
    :rtype: tuple or None
    """
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
    """
    Determine the effective abut value for a row.

    Explicit abut takes precedence; otherwise, if there are consecutive
    ``TRANSIENT`` rows below, auto-abut to keep them visible (0 before, N after).

    :param explicit_abut: The row's explicit abut attribute (or None)
    :param transient_count: Number of consecutive TRANSIENT rows below the row
    :returns: An abut value suitable for :func:`cook_abut`, or None
    """
    if explicit_abut is not None:
        return explicit_abut
    if transient_count > 0:
        return [0, transient_count]
    return None


def calc_indicator(pos: int, pos0: int, pos9: int, ind0: int, ind9: int, max_scroll_pos: int) -> int:
    """
    Map a content position to an indicator coordinate.

    :returns: Indicator coordinate, or -1 if the content is not scrollable.
    :rtype: int
    """
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
    """Compute the row position of the vertical scroll indicator."""
    if max_scroll_pos <= 1:
        return body_base
    y2, y1 = scroll_view_size - 1, 1
    x2, x1 = max_scroll_pos, 1
    x = scroll_pos
    pos = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return min(body_base + int(max(pos, 0)), rows - 1)


def scroll_indicator_col(pick_mode: bool, pick_pos: int, scroll_pos: int, max_scroll_pos: int, body_row_cnt: int, cols: int) -> int:
    """Compute the column position of the horizontal scroll indicator."""
    if pick_mode:
        return calc_indicator(pick_pos, 0, body_row_cnt - 1, 0, cols - 1, max_scroll_pos)
    return calc_indicator(scroll_pos, 0, max_scroll_pos, 0, cols - 1, max_scroll_pos)


def count_pickable_rows(is_pickable: Callable[[int], bool], row_cnt: int, start_pos: int, count: int, direction: int = 1) -> int:
    """
    Move through ``count`` pickable rows from ``start_pos`` in ``direction``.

    Skips non-pickable rows so page-up/down moves through a consistent number
    of actual content rows.

    :param is_pickable: Callable ``row -> bool``
    :param row_cnt: Total number of body rows
    :param start_pos: Starting row position
    :param count: Number of pickable rows to count
    :param direction: 1 for forward, -1 for backward
    :returns: The row position after counting pickable rows
    :rtype: int
    """
    pos = start_pos
    pickable_count = 0
    while 0 <= pos < row_cnt and pickable_count < count:
        pos += direction
        if 0 <= pos < row_cnt and is_pickable(pos):
            pickable_count += 1
    return pos


def find_pickable(is_pickable: Callable[[int], bool], row_cnt: int, pick_pos: int) -> int:
    """
    Find the nearest pickable row to ``pick_pos`` (searching downward first).

    :param is_pickable: Callable ``row -> bool``
    :param row_cnt: Total number of body rows
    :param pick_pos: Current pick position
    :returns: A pickable row index, or -1 if none exists
    :rtype: int
    """
    if 0 <= pick_pos < row_cnt and is_pickable(pick_pos):
        return pick_pos
    for offset in range(1, row_cnt):
        if pick_pos + offset < row_cnt and is_pickable(pick_pos + offset):
            return pick_pos + offset
        if pick_pos - offset >= 0 and is_pickable(pick_pos - offset):
            return pick_pos - offset
    return -1
