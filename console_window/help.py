"""Ready-made help-screen paragraphs for the display features.

A help screen is where a user goes when the display looks wrong, so the two
things that most often look wrong -- the colour theme and the symbol set --
deserve standard wording.  Keeping the wording here means every app that uses
this library says the same true thing, and an app that adds a theme picker
does not have to re-explain what ``t`` does.

Both builders are plain strings: an app returns them from
:meth:`Screen.extra_help_paragraphs`, and ``BasicHelpScreen`` wraps and dims
them.
"""

from __future__ import annotations

from . import glyphs

__all__ = ['glyph_paragraph', 'theme_paragraph']


def theme_paragraph(
    open_key: str = 'T',
    cycle_key: str = 't',
    remembered: bool = False,
) -> str:
    """Describe the theme picker: how to open it, cycle it, and leave it.

    *remembered* adds the promise that the choice survives a restart; only pass
    True when the app actually supplies a ``ThemeStore``.
    """
    text = (
        f'Color theme: press {open_key} for the theme picker, then {cycle_key} '
        'to cycle the themes (ESC returns).'
    )
    if remembered:
        text += ' The choice is remembered for the next start.'
    return text


def glyph_paragraph(window: object = None) -> str:
    """Describe the symbol set, including how to change it.

    In Unicode mode this is the font check: the real glyphs, so the user can
    see for themselves whether the font has them.  In ASCII mode it says how to
    get the full set back, which is the only thing a user can act on once the
    fallback is already in use.
    """
    ascii_mode = getattr(window, 'ascii_mode', None)
    if ascii_mode is None:
        ascii_mode = glyphs.is_ascii()
    if ascii_mode:
        return (
            'Symbols: this terminal used the plain-ASCII symbol set, because the '
            'terminal cannot show the full one (or --ascii was given). Restart '
            'without --ascii to try the full symbol set.'
        )
    probe = glyphs.probe_text()
    if not probe:
        return (
            'Symbols: if any symbol appears as a box or a blank, restart with '
            '--ascii to use plain-ASCII symbols instead.'
        )
    return (
        f'Symbols: {probe} -- if any of these appears as a box or a blank, '
        'restart with --ascii to use plain-ASCII symbols instead.'
    )
