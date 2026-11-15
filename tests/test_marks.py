"""Approved two-cell marks: validation, spelling, and the width detector."""

import logging

import pytest

from console_window.glyphs import (
    AUDIT_ENV,
    BUILTIN_MARKS,
    Glyphs,
    SafeMark,
    catalog_items,
    find_issues,
    mark,
    marks,
    marks_probe_text,
    register_mark,
    reset,
    set_ascii,
    transliterate,
)
from console_window.textwidth import ljust, string_width

VS16 = '\ufe0f'
OK = '\u2705'
WARN = '\u26a0'          # 1 cell, 2 with VS16: the classic trap
DOT = '\u25cf'           # East-Asian Ambiguous
UNICORN = '\U0001f984'
FAMILY = '\U0001f468\u200d\U0001f469\u200d\U0001f467'

#: The vocabulary added after the first table.  Same rule as the entries above:
#: one code point, two cells, a two-cell fallback.
EXPANDED_MARKS = (
    ('denied', '\U0001f6ab', 'X '),       # no entry sign
    ('idea', '\U0001f4a1', 'i '),         # electric light bulb
    ('build', '\U0001f6a7', 'C '),        # construction sign
    ('radio', '\U0001f518', 'r '),        # radio button
    ('star', '\u2b50', 's '),             # white medium star
    ('star_glow', '\U0001f31f', 'S '),    # glowing star
    ('circle_heavy', '\u2b55', '0 '),     # heavy large circle
    ('diamond_orange', '\U0001f536', 'O '),
    ('diamond_blue', '\U0001f537', 'D '),
    ('diamond_dot', '\U0001f4a0', '. '),
    ('link', '\U0001f517', '> '),         # link symbol
    ('magnet', '\U0001f9f2', 'M '),       # magnet
    ('net', '\U0001f310', 'N '),          # globe with meridians
)


def test_every_mark_is_two_cells_in_both_spellings():
    for spec in marks():
        assert string_width(spec.emoji) == 2, spec.name
        assert string_width(spec.ascii) == 2, spec.name
        # A variation selector cannot change the answer, which is what makes the
        # mark safe to paste, re-export or generate.
        assert string_width(spec.emoji + VS16) == 2, spec.name


def test_the_table_is_unambiguous():
    specs = marks()
    assert len(specs) == len(BUILTIN_MARKS)
    assert len({spec.name for spec in specs}) == len(specs)
    assert len({spec.emoji for spec in specs}) == len(specs)
    assert len({spec.ascii for spec in specs}) == len(specs)


@pytest.mark.parametrize(('name', 'emoji', 'ascii_text'), EXPANDED_MARKS)
def test_every_expanded_mark_is_available_in_both_spellings(name, emoji, ascii_text):
    assert mark(name) == emoji
    assert string_width(mark(name)) == 2
    set_ascii(True)
    assert mark(name) == ascii_text
    assert string_width(mark(name)) == 2


def test_a_mark_asked_for_twice_does_not_enter_the_table_twice():
    # The bell and the speech balloon were already approved under the names the
    # table uses, so each code point is still drawn by exactly one mark.
    assert mark('bell') == '\U0001f514'
    assert mark('chat') == '\U0001f4ac'
    drawn = [spec.name for spec in marks() if spec.emoji in ('\U0001f514', '\U0001f4ac')]
    assert drawn == ['bell', 'chat']


@pytest.mark.parametrize(('emoji', 'ascii_text', 'reason'), [
    ('ab', 'ab', 'two code points'),
    (VS16, 'xx', 'a bare variation selector'),
    ('\u200d', 'xx', 'a bare joiner'),
    ('\u2713', 'v ', 'East-Asian N, one cell'),
    (OK, 'v', 'a one-cell fallback'),
    (OK, '\u2713 ', 'a non-ASCII fallback'),
])
def test_validation_rejects_a_mark_that_cannot_keep_its_width(emoji, ascii_text, reason):
    with pytest.raises(ValueError):
        SafeMark('bad', emoji, ascii_text)


def test_validation_rejects_a_non_string_field():
    with pytest.raises(TypeError):
        SafeMark('bad', OK, 2)


def test_mark_follows_the_mode_and_never_changes_width():
    assert mark('ok') == OK
    set_ascii(True)
    assert mark('ok') == 'v '
    assert string_width(mark('ok')) == 2


def test_a_one_cell_glyph_is_not_a_mark():
    with pytest.raises(KeyError):
        mark('cursor')
    with pytest.raises(KeyError):
        mark('no_such_mark')


def test_registering_an_application_mark_teaches_the_fallback():
    register_mark('rocket', '\U0001f680', 'R ')
    assert mark('rocket') == '\U0001f680'
    set_ascii(True)
    assert mark('rocket') == 'R '
    assert transliterate('go \U0001f680') == 'go R '
    with pytest.raises(ValueError):
        register_mark('rocket2', '\U0001f680', 'Q ')


def test_transliterate_rewrites_an_approved_mark_in_ascii_mode():
    set_ascii(True)
    assert transliterate('a' + OK + 'b') == 'av b'
    # The selector form is consumed with it, leaving no orphan mark.
    assert transliterate(OK + VS16) == 'v '


def test_the_one_cell_catalog_stays_one_cell():
    assert OK not in catalog_items()
    assert OK in catalog_items(include_marks=True)
    assert (len(catalog_items(include_marks=True))
            == len(catalog_items()) + len(BUILTIN_MARKS))


def test_probe_text_shows_the_real_marks_whatever_the_mode():
    set_ascii(True)
    shown = marks_probe_text()
    assert OK in shown
    assert 'v ' not in shown


def test_a_mixed_row_keeps_its_width_in_both_modes():
    # The point of the two-cell fallback: a row padded to a fixed width stays
    # that width when every mark is swapped for its ASCII spelling.
    def rows():
        return [
            ljust(f'{mark("ok")} plain', 16),
            ljust(f'{mark("dot_red")} \u6f22\u5b57\u304b\u306a', 16),
            ljust(f'{mark("wait")} combining e\u0301', 16),
        ]

    widths = [string_width(row) for row in rows()]
    assert widths == [16, 16, 16]
    set_ascii(True)
    assert [string_width(row) for row in rows()] == widths


def test_an_approved_mark_is_never_reported():
    assert find_issues(OK) == []
    # VS16 immunity is the point: a selector next to an approved mark is noise.
    assert find_issues(OK + VS16) == []


def test_a_vs16_promoted_base_is_one_issue_at_the_base():
    issues = find_issues(WARN + VS16 + ' bad')
    assert [(issue.kind, issue.text, issue.offset) for issue in issues] == [
        ('vs16', WARN + VS16, 0),
    ]


def test_a_vs16_promoted_base_reports_what_to_use():
    hint = find_issues(WARN + VS16)[0].hint
    assert 'mark()' in hint


def test_an_ambiguous_shape_is_reported():
    issues = find_issues('a ' + DOT)
    assert [(issue.kind, issue.offset) for issue in issues] == [('ambiguous', 2)]


def test_an_unapproved_two_cell_mark_is_reported():
    issues = find_issues(UNICORN)
    assert [(issue.kind, issue.text) for issue in issues] == [('unapproved', UNICORN)]


def test_a_joiner_sequence_is_reported_once_per_joiner():
    kinds = [(issue.kind, issue.offset) for issue in find_issues(FAMILY)]
    assert kinds == [('zwj', 1), ('zwj', 3)]


def test_ordinary_text_and_one_cell_marks_are_left_alone():
    assert find_issues('Gr\u00fc\u00dfe aus K\u00f6ln') == []
    # Rung 3: a bare one-cell mark is not a hazard, and a terminal that forces
    # emoji presentation for it cannot be observed from here.
    assert find_issues('\u2713 done') == []
    assert find_issues('a \u2014 b \u00b1 c') == []


def test_the_audit_names_the_problem(monkeypatch, caplog):
    monkeypatch.setenv(AUDIT_ENV, '1')
    with caplog.at_level(logging.WARNING):
        transliterate(WARN + VS16)
        transliterate(OK)
    audits = [record.getMessage() for record in caplog.records
              if 'glyph audit' in record.getMessage()]
    assert len(audits) == 1
    assert 'VS16' in audits[0]
    # The approved mark is not a warning: it has a two-cell fallback already.
    assert OK not in audits[0]


def test_the_audit_runs_in_unicode_mode_too(monkeypatch, caplog):
    monkeypatch.setenv(AUDIT_ENV, '1')
    with caplog.at_level(logging.WARNING):
        transliterate('\u25cf')
    assert any('Ambiguous' in record.getMessage() for record in caplog.records)


def test_reset_restores_the_builtin_marks():
    register_mark('rocket', '\U0001f680', 'R ')
    reset()
    with pytest.raises(KeyError):
        mark('rocket')
    assert len(marks()) == len(BUILTIN_MARKS)


def test_the_facade_exposes_the_marks_api():
    assert Glyphs.mark('ok') == OK
    assert len(Glyphs.marks()) == len(BUILTIN_MARKS)
    assert Glyphs.find_issues(OK) == []
