"""Ready-made help-screen paragraphs for the display features.

A help screen is where a user goes when the display looks wrong, so the two
things that most often look wrong -- the color theme and the symbol set --
deserve standard wording.  Keeping the wording here means every app that uses
this library says the same true thing, and an app that adds a theme picker
does not have to re-explain what ``t`` does.

Both builders are plain strings: an app returns them from
:meth:`Screen.extra_help_paragraphs`, and ``BasicHelpScreen`` adds the
``Instructions`` separator and renders them as bulleted instructions with a
hanging indent.

The symbol check itself is no longer a paragraph an app opts into: every help
page gets ``BasicHelpScreen.draw_fonts()``, and the ``FONT_*`` constants here
are the sentences it uses -- the unconditional install advice, the one-line
form for later pages, and the ASCII and narrow-terminal variants.
``glyph_paragraph()`` stays for an app that draws its own help body.
"""

from __future__ import annotations

from . import glyphs

__all__ = [
    'FONT_ADVICE',
    'FONT_ASCII',
    'FONT_BRIEF',
    'FONT_NARROW',
    'glyph_paragraph',
    'theme_paragraph',
]

#: Closing line of the built-in Fonts section.  It is unconditional on purpose:
#: the library cannot see a box, so it names the two families and lets the user
#: judge the symbols on the page.
FONT_ADVICE = (
    'If any symbol above is a box, a blank, or pushes the columns sideways, '
    'install DejaVu Sans Mono and Noto Color Emoji (fonts-dejavu-core and '
    'fonts-noto-color-emoji on Debian and Ubuntu).'
)

#: The one-line form shown on later help pages when ``help_fonts='once'``.
FONT_BRIEF = (
    'The full symbol check appears on the first help page this window shows; '
    'install DejaVu Sans Mono and Noto Color Emoji if any symbol is a box.'
)

#: What the section says in ASCII mode, where no font can fail to draw a symbol.
FONT_ASCII = (
    'Plain ASCII is in use, so every symbol is covered. Restart with '
    '--glyphs unicode to check the full set.'
)

#: What the section says when the body is too narrow for the sample rows: the
#: theme page prints the same catalog at any width, and the advice still holds.
FONT_NARROW = (
    'Widen the terminal (or open the theme page) to see the full symbol check; '
    'install DejaVu Sans Mono and Noto Color Emoji if any symbol is a box.'
)


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
    """Describe the symbol set in one line, including how to change it.

    For an application that draws its own help body; ``BasicHelpScreen`` uses
    its built-in Fonts section instead.  In Unicode mode this is the short font
    check -- the real glyphs, so the user can see for themselves whether the
    font has them.  In ASCII mode it says how to get the full set back, which is
    the only thing a user can act on once the fallback is already in use.
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
