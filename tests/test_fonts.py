"""The two reference font families: parsing, coverage answers, and recording."""

import pytest

from console_window import ConsoleWindowOpts, fonts, glyphs
from console_window.fonts import (
    EMOJI_FONT,
    TEXT_FONT,
    _parse_charset,
    check_registration,
    has_char,
    installed,
    registered_missing,
    reset,
)
from console_window.glyphs import BUILTIN_GLYPHS, EMOJI_GROUP


def test_charset_ranges_are_parsed():
    assert _parse_charset('20-7e a0 1f9f2-1f9ff') == [
        (0x20, 0x7E), (0xA0, 0xA0), (0x1F9F2, 0x1F9FF)]


def test_a_symbol_is_found_inside_a_range(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x2B00, 0x2BFF)])
    assert has_char(TEXT_FONT, '\u2b50') is True
    assert has_char(TEXT_FONT, '\u2705') is False


def test_an_absent_family_is_unknown_not_missing(monkeypatch):
    # A machine without the font is not a bug: the answer is "cannot check",
    # which is also what keeps nothing recorded.
    monkeypatch.setattr(fonts, 'charset', lambda family: [])
    assert has_char(TEXT_FONT, '\u2705') is None
    assert installed(TEXT_FONT) is False


def test_no_fontconfig_is_unknown(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: None)
    assert has_char(TEXT_FONT, '\u2705') is None
    assert installed(TEXT_FONT) is None


def test_a_sequence_is_not_testable_as_a_unit(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x20, 0x7E)])
    assert has_char(TEXT_FONT, '\u2705\ufe0f') is None


def test_a_covered_registration_records_nothing(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x20, 0x7E)])
    assert check_registration('glyph', 'tilde', '~') is True
    assert registered_missing() == ()


def test_a_missing_registration_is_recorded_once(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x20, 0x7E)])
    assert check_registration('glyph', 'pua', '\ue000') is False
    check_registration('glyph', 'pua', '\ue000')
    assert [entry.name for entry in registered_missing()] == ['pua']


def test_a_mark_is_checked_against_the_emoji_family(monkeypatch):
    seen = []

    def fake_charset(family):
        seen.append(family)
        return [(0x20, 0x7E)]

    monkeypatch.setattr(fonts, 'charset', fake_charset)
    check_registration('mark', 'dot_purple', '\U0001f7e3')
    assert seen == [EMOJI_FONT]


def test_reset_forgets_the_records(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x20, 0x7E)])
    check_registration('glyph', 'pua', '\ue000')
    reset()
    assert registered_missing() == ()


def test_help_fonts_defaults_to_once_and_accepts_bools():
    assert ConsoleWindowOpts().help_fonts == 'once'
    assert ConsoleWindowOpts(help_fonts=True).help_fonts == 'always'
    assert ConsoleWindowOpts(help_fonts=False).help_fonts == 'never'
    assert ConsoleWindowOpts(help_fonts=' ALWAYS ').help_fonts == 'always'


def test_help_fonts_rejects_an_unknown_value():
    with pytest.raises(ValueError, match='help_fonts'):
        ConsoleWindowOpts(help_fonts='sometimes')


def test_a_registered_glyph_missing_from_the_text_font_is_recorded(monkeypatch):
    monkeypatch.setattr(fonts, 'charset', lambda family: [(0x20, 0x7E)])
    glyphs.register('pua', '\ue000', '? ')
    assert [entry.name for entry in glyphs.font_missing()] == ['pua']


@pytest.mark.skipif(
    installed(TEXT_FONT) is not True or installed(EMOJI_FONT) is not True,
    reason='the two reference font families are not installed')
def test_every_blessed_symbol_is_covered_by_its_family():
    for name, spec in BUILTIN_GLYPHS.items():
        family = EMOJI_FONT if spec.group == EMOJI_GROUP else TEXT_FONT
        assert has_char(family, spec.unicode) is True, name
