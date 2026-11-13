"""The glyph registry: registration, lookup, probe text, and reset."""

import pytest

from console_window.glyphs import (
    BUILTIN_GLYPHS,
    DEPRECATED_GLYPHS,
    Glyph,
    Glyphs,
    catalog_items,
    catalog_rows,
    get,
    is_ascii,
    probe_text,
    register,
    register_many,
    reset,
    set_ascii,
    transliterate,
    unicode_of,
)
from console_window.textwidth import string_width


def test_every_builtin_has_a_unicode_form_and_a_plain_ascii_fallback():
    assert BUILTIN_GLYPHS
    for name, glyph in BUILTIN_GLYPHS.items():
        assert glyph.unicode, name
        assert glyph.ascii.isascii(), name


def test_get_follows_the_mode_while_unicode_of_never_does():
    assert get('cursor') == '\u2502'
    set_ascii(True)
    assert get('cursor') == '|'
    # The font check must always show the real glyph, or it checks nothing.
    assert unicode_of('cursor') == '\u2502'


def test_unknown_names_raise_keyerror_with_the_name():
    with pytest.raises(KeyError, match='unknown glyph'):
        get('no-such-glyph')
    with pytest.raises(KeyError, match='no-such-glyph'):
        unicode_of('no-such-glyph')


def test_register_overrides_a_builtin_and_reset_restores_it():
    register('cursor', '\u258f', '|')
    assert get('cursor') == '\u258f'
    reset()
    assert get('cursor') == BUILTIN_GLYPHS['cursor'].unicode


def test_ascii_fallback_must_be_ascii():
    with pytest.raises(ValueError, match='plain ASCII'):
        Glyph('\u2718', '\u2717')


def test_glyph_requires_a_non_empty_unicode_form():
    with pytest.raises(TypeError):
        Glyph('', 'x')


def test_an_empty_ascii_form_is_allowed():
    # "delete the decoration" is a real fallback for a marker whose meaning is
    # already carried by its column.
    assert Glyph('\u25cf', '').ascii == ''


def test_register_many_accepts_glyphs_and_pairs():
    register_many({'tick': Glyph('\u2713', 'OK'), 'nix': ('\u2717', 'X')})
    assert get('tick') == '\u2713'
    assert get('nix') == '\u2717'
    set_ascii(True)
    assert get('tick') == 'OK'
    assert get('nix') == 'X'


def test_register_many_rejects_a_bad_spec():
    with pytest.raises(TypeError, match='Glyph'):
        register_many({'bad': 'x'})
    with pytest.raises(TypeError, match='non-empty str'):
        register_many({1: ('x', 'x')})


def test_probe_text_is_already_unicode_in_ascii_mode():
    set_ascii(True)
    text = probe_text()
    assert text
    assert not text.isascii()


def test_probe_order_is_the_registration_order():
    register_many({'alpha': ('\u03b1', 'a'), 'beta': ('\u03b2', 'b')},
                  probe=('beta', 'alpha'))
    assert probe_text().endswith('\u03b2 \u03b1')


def test_probe_rejects_names_that_are_not_registered():
    with pytest.raises(KeyError):
        Glyphs.probe('no-such-glyph')


def test_probe_does_not_repeat_a_duplicate_unicode_form():
    # Both names draw the same block; the check has no reason to show it twice.
    register_many({'block_a': ('\u2588', '#'), 'block_b': ('\u2588', '#')},
                  probe=('block_a', 'block_b'))
    assert probe_text().split().count('\u2588') == 1


def test_reset_returns_to_unicode_mode_and_drops_app_vocabulary():
    register('app_thing', '\u2691', '!')
    set_ascii(True)
    reset()
    assert is_ascii() is False
    with pytest.raises(KeyError):
        get('app_thing')


def test_facade_delegates_to_the_module_functions():
    set_ascii(True)
    assert Glyphs.is_ascii() is True
    assert Glyphs.get('bullet') == '.'
    assert Glyphs.unicode_of('bullet') == '\u00b7'
    assert Glyphs.catalog() == catalog_items()
    assert Glyphs.catalog_rows(79) == catalog_rows(79)
    Glyphs.set_ascii(False)
    assert Glyphs.get('bullet') == '\u00b7'


def test_the_builtin_catalog_is_eighty_glyphs():
    assert len(BUILTIN_GLYPHS) == 80


def test_every_builtin_is_one_cell_wide():
    # A two-cell symbol would push the rest of its row out of alignment on the
    # very terminal that is already struggling to draw it.
    for name, glyph in BUILTIN_GLYPHS.items():
        assert string_width(glyph.unicode) == 1, name


def test_one_codepoint_has_one_fallback():
    # The catalog lists a character once, so two names for it must agree;
    # otherwise which fallback wins would depend on registration order.
    fallbacks = {}
    for name, glyph in BUILTIN_GLYPHS.items():
        assert fallbacks.setdefault(glyph.unicode, glyph.ascii) == glyph.ascii, name


def test_the_catalog_lists_each_character_once():
    items = catalog_items()
    assert len(items) == 78
    assert len(set(items)) == 78


def test_the_catalog_follows_the_active_spelling():
    assert catalog_items()[0] == BUILTIN_GLYPHS['cursor'].unicode
    set_ascii(True)
    assert catalog_items()[0] == BUILTIN_GLYPHS['cursor'].ascii


def test_catalog_rows_are_three_measured_rows_at_eighty_columns():
    rows = catalog_rows(79)
    assert len(rows) == 3
    assert all(string_width(row) <= 79 for row in rows)


def test_catalog_rows_wrap_rather_than_overflow_a_narrow_terminal():
    rows = catalog_rows(20)
    assert len(rows) > 3
    assert all(string_width(row) <= 20 for row in rows)


def test_an_app_registration_takes_over_a_builtin_code_point():
    # The application is allowed to say what its own use of a symbol means, so
    # claiming a built-in character under a new name wins.
    register('alert', '\u26a0', '(!)')
    set_ascii(True)
    assert transliterate('\u26a0') == '(!)'


def test_re_registering_a_builtin_takes_effect_after_the_table_is_built():
    set_ascii(True)
    assert transliterate('\u2713') == 'v'
    register('check', '\u2713', 'OK')
    assert transliterate('\u2713') == 'OK'


def test_every_deprecated_spelling_maps_to_a_registered_replacement():
    registered = {glyph.unicode for glyph in BUILTIN_GLYPHS.values()}
    for old, new in DEPRECATED_GLYPHS.items():
        assert string_width(old) == 1, old
        assert new in registered, new
        # A deprecated form still present as a built-in would never upgrade,
        # and the app-wins rule would never fire, so the table would be dead.
        assert old not in registered, old
