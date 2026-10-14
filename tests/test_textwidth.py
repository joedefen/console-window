"""Unit tests for the stdlib-only display-cell width helpers.

These are pure functions (no curses), covering wide CJK, combining marks,
zero-width joiners, truncation, padding, wrapping and the index mapping used by
the modal ``answer()`` editor.
"""

from console_window import textwidth as tw

CJK = '世'          # U+4E16, East-Asian Wide -> 2 cells
COMBINING = '\u0301'  # combining acute accent -> 0 cells
ZWJ = '\u200d'     # zero-width joiner (Cf) -> 0 cells


# --- char_width / string_width ----------------------------------------------

def test_char_width_narrow():
    assert tw.char_width('a') == 1
    assert tw.char_width(' ') == 1


def test_char_width_wide():
    assert tw.char_width(CJK) == 2


def test_char_width_zero_width():
    assert tw.char_width(COMBINING) == 0
    assert tw.char_width(ZWJ) == 0


def test_char_width_empty():
    assert tw.char_width('') == 0


def test_string_width_mixed():
    assert tw.string_width(f'a{CJK}b') == 4
    assert tw.string_width('') == 0


def test_string_width_ignores_combining_and_zwj():
    assert tw.string_width(f'e{COMBINING}') == 1  # é as e + combining accent
    assert tw.string_width(f'{CJK}{ZWJ}{CJK}') == 4


# --- truncate / ljust / rjust -----------------------------------------------

def test_truncate_narrow():
    assert tw.truncate('abcdef', 3) == 'abc'
    assert tw.truncate('abc', 0) == ''
    assert tw.truncate('abc', 10) == 'abc'


def test_truncate_never_splits_wide_char():
    # 3 cells can hold one wide (2) char but not two (4).
    assert tw.truncate(CJK * 2, 3) == CJK
    assert tw.truncate(CJK * 2, 2) == CJK
    assert tw.truncate(CJK * 2, 1) == ''


def test_ljust_pads_to_cells():
    padded = tw.ljust(CJK, 4)
    assert tw.string_width(padded) == 4
    assert padded == CJK + '  '


def test_ljust_truncates_when_too_wide():
    assert tw.ljust('abcdef', 2) == 'ab'
    # Only one wide char fits in 3 cells; the spare cell is space-padded.
    assert tw.ljust(CJK * 3, 3) == CJK + ' '


def test_rjust_pads_to_cells():
    padded = tw.rjust(CJK, 4)
    assert tw.string_width(padded) == 4
    assert padded == '  ' + CJK


# --- cell_to_index ----------------------------------------------------------

def test_cell_to_index_ascii():
    assert tw.cell_to_index('abcd', 2) == 2


def test_cell_to_index_inside_wide_char_rounds_down():
    text = f'a{CJK}b'  # columns: a=0, 世=1..2, b=3
    assert tw.cell_to_index(text, 1) == 1
    assert tw.cell_to_index(text, 2) == 1  # middle of the wide char
    assert tw.cell_to_index(text, 3) == 2


def test_cell_to_index_clamps():
    assert tw.cell_to_index('abc', 0) == 0
    assert tw.cell_to_index('abc', 99) == 3


# --- wrap_ranges / wrap_position / index_at_cell ----------------------------

def test_wrap_ranges_ascii():
    assert tw.wrap_ranges('abcdef', 3) == [(0, 3), (3, 6)]


def test_wrap_ranges_wide():
    # width 4 holds two 2-cell chars per line.
    assert tw.wrap_ranges(CJK * 3, 4) == [(0, 2), (2, 3)]


def test_wrap_ranges_empty():
    assert tw.wrap_ranges('', 5) == [(0, 0)]


def test_wrap_ranges_over_wide_char_owns_a_line():
    # width 1 cannot hold a 2-cell char; it gets its own (over-wide) line.
    assert tw.wrap_ranges(CJK * 2, 1) == [(0, 1), (1, 2)]


def test_wrap_position_end_of_text():
    assert tw.wrap_position('abcdef', 6, 3) == (1, 3)


def test_wrap_position_at_line_boundary():
    # Index 3 is the start of the second line.
    assert tw.wrap_position('abcdef', 3, 3) == (1, 0)


def test_wrap_position_matches_wrap_ranges_count():
    text = CJK * 5
    ranges = tw.wrap_ranges(text, 4)
    line, _ = tw.wrap_position(text, len(text), 4)
    assert line == len(ranges) - 1


def test_index_at_cell_inverse():
    ranges = tw.wrap_ranges('abcdef', 3)
    assert tw.index_at_cell('abcdef', ranges, 1, 1) == 4


def test_index_at_cell_out_of_range():
    ranges = tw.wrap_ranges('abc', 3)
    assert tw.index_at_cell('abc', ranges, -1, 0) is None
    assert tw.index_at_cell('abc', ranges, 5, 0) is None


# --- wrap (word wrapping) ---------------------------------------------------

def test_wrap_words():
    assert tw.wrap('hello world', 5) == ['hello', 'world']
    assert tw.wrap('a bb ccc', 3) == ['a', 'bb', 'ccc']


def test_wrap_hard_breaks_over_wide_words():
    assert tw.wrap(CJK * 4, 4) == [CJK * 2, CJK * 2]


def test_wrap_empty():
    assert tw.wrap('', 5) == ['']
