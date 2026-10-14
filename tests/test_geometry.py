"""Unit tests for the pure scroll/pick geometry helpers (no TTY required)."""

from console_window import geometry

# --- cook_abut -------------------------------------------------------------

def test_cook_abut_none():
    assert geometry.cook_abut(None) is None


def test_cook_abut_negative_int():
    assert geometry.cook_abut(-3) == (-3, 0)


def test_cook_abut_positive_int():
    assert geometry.cook_abut(7) == (0, 7)


def test_cook_abut_pair():
    assert geometry.cook_abut([-5, 3]) == (-5, 3)


def test_cook_abut_mixed_list_uses_extremes():
    assert geometry.cook_abut([-8, 3, -2, 12]) == (-8, 12)


def test_cook_abut_unparseable():
    assert geometry.cook_abut("nope") is None


# --- compute_abut ----------------------------------------------------------

def test_compute_abut_explicit_wins():
    assert geometry.compute_abut([-5, 3], transient_count=9) == [-5, 3]


def test_compute_abut_auto_for_transient():
    assert geometry.compute_abut(None, transient_count=4) == [0, 4]


def test_compute_abut_none_when_no_transient():
    assert geometry.compute_abut(None, 0) is None


# --- calc_indicator --------------------------------------------------------

def test_calc_indicator_not_scrollable():
    assert geometry.calc_indicator(0, 0, 10, 0, 80, max_scroll_pos=0) == -1


def test_calc_indicator_not_scrollable_when_range_empty():
    assert geometry.calc_indicator(0, 5, 5, 0, 80, max_scroll_pos=10) == -1


def test_calc_indicator_clamps_at_start_and_end():
    assert geometry.calc_indicator(0, 0, 100, 0, 80, max_scroll_pos=100) == 0
    assert geometry.calc_indicator(100, 0, 100, 0, 80, max_scroll_pos=100) == 80


def test_calc_indicator_interior_is_bounded():
    ind = geometry.calc_indicator(50, 0, 100, 0, 80, max_scroll_pos=100)
    assert 1 <= ind <= 79


# --- scroll indicator row/col ---------------------------------------------

def test_scroll_indicator_row_non_scrollable_returns_body_base():
    assert geometry.scroll_indicator_row(
        scroll_pos=0, max_scroll_pos=1, scroll_view_size=10,
        body_base=3, rows=20) == 3


def test_scroll_indicator_row_clamped_to_rows():
    row = geometry.scroll_indicator_row(
        scroll_pos=1000, max_scroll_pos=1000, scroll_view_size=10,
        body_base=0, rows=5)
    assert 0 <= row <= 4


def test_scroll_indicator_col_not_scrollable():
    assert geometry.scroll_indicator_col(
        pick_mode=False, pick_pos=0, scroll_pos=0, max_scroll_pos=0,
        body_row_cnt=10, cols=80) == -1


# --- count_pickable_rows ---------------------------------------------------

def test_count_pickable_rows_skips_non_pickable():
    # rows 2 and 3 are DECOR (not pickable)
    pickable = {0, 1, 4, 5, 6}
    is_pickable = lambda r: r in pickable
    # From row 1, move 2 pickable rows down -> row 1 -> 4 -> 5
    assert geometry.count_pickable_rows(is_pickable, 7, 1, 2) == 5


def test_count_pickable_rows_backwards():
    pickable = {0, 1, 4, 5, 6}
    is_pickable = lambda r: r in pickable
    assert geometry.count_pickable_rows(is_pickable, 7, 5, 2, direction=-1) == 1


# --- find_pickable ---------------------------------------------------------

def test_find_pickable_returns_self_when_pickable():
    is_pickable = lambda r: r in {0, 3, 5}
    assert geometry.find_pickable(is_pickable, 6, 3) == 3


def test_find_pickable_prefers_down_on_tie():
    # At equal distance, downward is checked before upward.
    is_pickable = lambda r: r in {0, 2}
    assert geometry.find_pickable(is_pickable, 6, 1) == 2


def test_find_pickable_finds_nearest_up():
    # Nearest pickable to row 1 is row 0 (distance 1) vs row 4 (distance 3).
    is_pickable = lambda r: r in {0, 4}
    assert geometry.find_pickable(is_pickable, 6, 1) == 0


def test_find_pickable_returns_minus_one_when_none():
    is_pickable = lambda r: False
    assert geometry.find_pickable(is_pickable, 6, 3) == -1
