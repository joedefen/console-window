"""The emoji group: validation, spelling, and the width detector."""

import logging

import pytest

from console_window.glyphs import (
    AUDIT_ENV,
    EMOJI_GROUP,
    Glyph,
    Glyphs,
    catalog_items,
    find_issues,
    get,
    glyphs_in_group,
    register,
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


def emoji_specs() -> list[Glyph]:
    return [glyph for _name, glyph in glyphs_in_group(EMOJI_GROUP)]


def test_every_emoji_is_two_cells_in_both_spellings():
    for spec in emoji_specs():
        assert string_width(spec.unicode) == 2
        assert string_width(spec.ascii) == 2
        # A variation selector cannot change the answer, which is what makes the
        # emoji safe to paste, re-export or generate.
        assert string_width(spec.unicode + VS16) == 2


def test_the_emoji_group_is_unambiguous():
    specs = emoji_specs()
    assert len(specs) == 39
    assert len({spec.unicode for spec in specs}) == len(specs)
    assert len({spec.ascii for spec in specs}) == len(specs)


@pytest.mark.parametrize(('name', 'emoji', 'ascii_text'), EXPANDED_MARKS)
def test_every_expanded_emoji_is_available_in_both_spellings(
        name, emoji, ascii_text):
    assert get(name) == emoji
    assert string_width(get(name)) == 2
    set_ascii(True)
    assert get(name) == ascii_text
    assert string_width(get(name)) == 2


def test_an_emoji_asked_for_twice_does_not_enter_the_registry_twice():
    # The bell and the speech balloon are approved once each, so the group still
    # has one entry per character.
    assert get('bell') == '\U0001f514'
    assert get('chat') == '\U0001f4ac'
    drawn = [name for name, spec in glyphs_in_group(EMOJI_GROUP)
             if spec.unicode in ('\U0001f514', '\U0001f4ac')]
    assert drawn == ['bell', 'chat']


@pytest.mark.parametrize(('emoji', 'ascii_text', 'reason'), [
    ('ab', 'ab', 'two code points'),
    (VS16, 'xx', 'a bare variation selector'),
    ('\u200d', 'xx', 'a bare joiner'),
    ('\u2713', 'v ', 'East-Asian N, one cell'),
    (OK, 'v', 'a one-cell fallback'),
    (OK, '\u2713 ', 'a non-ASCII fallback'),
])
def test_validation_rejects_an_emoji_that_cannot_keep_its_width(
        emoji, ascii_text, reason):
    with pytest.raises(ValueError):
        Glyph(emoji, ascii_text, group=EMOJI_GROUP)


def test_validation_rejects_a_non_string_field():
    with pytest.raises(TypeError):
        Glyph(OK, 2, group=EMOJI_GROUP)


def test_an_emoji_follows_the_mode_and_never_changes_width():
    assert get('ok') == OK
    set_ascii(True)
    assert get('ok') == 'v '
    assert string_width(get('ok')) == 2


def test_a_one_cell_glyph_is_not_in_the_emoji_group():
    assert get('cursor') == '\u2502'
    names = [name for name, _spec in glyphs_in_group(EMOJI_GROUP)]
    assert 'cursor' not in names


def test_registering_an_application_emoji_teaches_the_fallback():
    register('rocket', '\U0001f680', 'R ', group=EMOJI_GROUP)
    assert get('rocket') == '\U0001f680'
    set_ascii(True)
    assert get('rocket') == 'R '
    assert transliterate('go \U0001f680') == 'go R '
    with pytest.raises(ValueError):
        register('rocket2', '\U0001f680', 'Q ', group=EMOJI_GROUP)


def test_transliterate_rewrites_an_approved_emoji_in_ascii_mode():
    set_ascii(True)
    assert transliterate('a' + OK + 'b') == 'av b'
    # The selector form is consumed with it, leaving no orphan mark.
    assert transliterate(OK + VS16) == 'v '


def test_the_one_cell_catalog_stays_one_cell():
    assert OK not in catalog_items()
    assert OK in catalog_items(include_emoji=True)
    assert (len(catalog_items(include_emoji=True))
            == len(catalog_items()) + len(glyphs_in_group(EMOJI_GROUP)))


def test_the_emoji_group_keeps_its_unicode_visual_in_ascii_mode():
    set_ascii(True)
    assert all(string_width(spec.unicode) == 2
               for spec in emoji_specs())
    assert get('ok') == 'v '


def test_a_mixed_row_keeps_its_width_in_both_modes():
    # The point of the two-cell fallback: a row padded to a fixed width stays
    # that width when every emoji is swapped for its ASCII spelling.
    def rows():
        return [
            ljust(f'{get("ok")} plain', 16),
            ljust(f'{get("dot_red")} \u6f22\u5b57\u304b\u306a', 16),
            ljust(f'{get("wait")} combining e\u0301', 16),
        ]

    widths = [string_width(row) for row in rows()]
    assert widths == [16, 16, 16]
    set_ascii(True)
    assert [string_width(row) for row in rows()] == widths


def test_an_approved_emoji_is_never_reported():
    assert find_issues(OK) == []
    # VS16 immunity is the point: a selector next to an approved emoji is noise.
    assert find_issues(OK + VS16) == []


def test_a_vs16_promoted_base_is_one_issue_at_the_base():
    issues = find_issues(WARN + VS16 + ' bad')
    assert [(issue.kind, issue.text, issue.offset) for issue in issues] == [
        ('vs16', WARN + VS16, 0),
    ]


def test_a_vs16_promoted_base_reports_what_to_use():
    hint = find_issues(WARN + VS16)[0].hint
    assert 'emoji glyph' in hint
    assert 'EAW=N' in hint


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
    # The approved emoji is not a warning: it has a two-cell fallback already.
    assert OK not in audits[0]


def test_the_audit_runs_in_unicode_mode_too(monkeypatch, caplog):
    monkeypatch.setenv(AUDIT_ENV, '1')
    with caplog.at_level(logging.WARNING):
        transliterate('\u25cf')
    assert any('Ambiguous' in record.getMessage() for record in caplog.records)


def test_reset_restores_the_builtin_emoji():
    register('rocket', '\U0001f680', 'R ', group=EMOJI_GROUP)
    reset()
    with pytest.raises(KeyError):
        get('rocket')
    assert len(glyphs_in_group(EMOJI_GROUP)) == 39


def test_the_facade_exposes_the_emoji_group():
    assert Glyphs.get('ok') == OK
    assert len(Glyphs.glyphs_in_group(EMOJI_GROUP)) == 39
    assert Glyphs.find_issues(OK) == []
