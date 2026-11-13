"""Transliteration: registered decoration degrades, content never changes."""

import logging

from console_window import glyphs
from console_window.glyphs import (
    AUDIT_ENV,
    register,
    set_ascii,
    transliterate,
)


def test_unicode_mode_is_the_identity_function():
    text = 'a\u2502b \u27a4'
    assert transliterate(text) is text


def test_ascii_input_is_returned_unchanged_without_work():
    set_ascii(True)
    text = 'plain ascii'
    # Same object: the fast path must not copy or rebuild the string.
    assert transliterate(text) is text


def test_registered_glyphs_are_replaced():
    set_ascii(True)
    assert transliterate('a\u2502b') == 'a|b'


def test_content_is_left_alone():
    set_ascii(True)
    # A pager showing real UTF-8 must not be rewritten: only decoration is
    # registered, so German prose survives byte for byte.
    assert transliterate('Gr\u00fc\u00dfe aus K\u00f6ln') == 'Gr\u00fc\u00dfe aus K\u00f6ln'


def test_the_longest_registered_form_wins():
    register('legend', '\u2b9c\u2013\u2b9e', '<->')
    set_ascii(True)
    assert transliterate('\u2b9c\u2013\u2b9e') == '<->'


def test_a_variation_selector_spelling_matches_both_ways():
    register('alert', '\u26a0\ufe0f', '(!)')
    set_ascii(True)
    assert transliterate('a \u26a0\ufe0f b') == 'a (!) b'
    # The selector is consumed, so no orphan zero-width mark is left behind.
    assert transliterate('a \u26a0 b') == 'a (!) b'


def test_registering_the_bare_codepoint_also_consumes_a_selector():
    register('alert', '\u26a0', '(!)')
    set_ascii(True)
    assert transliterate('a \u26a0\ufe0f b') == 'a (!) b'


def test_an_unregistered_decorative_codepoint_is_untouched():
    set_ascii(True)
    assert transliterate('\u2691 flag') == '\u2691 flag'


def test_the_audit_logs_unregistered_decoration_once(monkeypatch, caplog):
    monkeypatch.setenv(AUDIT_ENV, '1')
    set_ascii(True)
    with caplog.at_level(logging.WARNING):
        transliterate('\u2691')
        transliterate('\u2691')
    audits = [record for record in caplog.records if 'glyph audit' in record.message]
    assert len(audits) == 1
    assert 'Glyphs.register' in audits[0].message


def test_the_audit_ignores_plain_text(monkeypatch, caplog):
    monkeypatch.setenv(AUDIT_ENV, '1')
    set_ascii(True)
    with caplog.at_level(logging.WARNING):
        transliterate('Gr\u00fc\u00dfe')
    assert not [record for record in caplog.records if 'glyph audit' in record.message]


def test_the_audit_is_off_by_default(caplog):
    set_ascii(True)
    with caplog.at_level(logging.WARNING):
        transliterate('\u2691')
    assert not caplog.records


def test_a_registration_invalidates_the_cached_table():
    set_ascii(True)
    assert transliterate('\u2691') == '\u2691'
    register('flag', '\u2691', '!')
    assert transliterate('\u2691') == '!'


def test_an_empty_fallback_deletes_the_decoration():
    register('bullet_mark', '\u25cf', '')
    set_ascii(True)
    assert transliterate('[\u25cf]') == '[]'


def test_glyph_widths_follow_the_substitution():
    # The ASCII fallback of a two-cell emoji is one cell, so the *rendered*
    # width shrinks; callers measure after transliterating, never before.
    register('stop_sign', '\U0001f6d1', 'STOP')
    set_ascii(True)
    assert glyphs.transliterate('a\U0001f6d1') == 'aSTOP'


def test_a_deprecated_spelling_is_upgraded_in_unicode_mode():
    # Text written against an older release keeps the shape, from the font that
    # actually has it.
    assert transliterate('\u2b9e') == '\u27a4'
    assert transliterate('\u2192 and \u25a1') == '\u27a1 and \u25fb'


def test_a_deprecated_spelling_still_degrades_in_ascii_mode():
    set_ascii(True)
    assert transliterate('\u2192 \u25a1') == '-> []'


def test_a_deprecated_variation_selector_spelling_is_upgraded():
    assert transliterate('\u2192\ufe0f') == '\u27a1'


def test_an_app_registration_keeps_a_deprecated_spelling():
    # Render once first: the compiled table must be rebuilt, not reused, when
    # the app claims the old code point.
    assert transliterate('\u2b9e') == '\u27a4'
    register('choice', '\u2b9e', '>')
    assert transliterate('\u2b9e') == '\u2b9e'
    set_ascii(True)
    assert transliterate('\u2b9e') == '>'
