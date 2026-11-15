"""Ready-made help-screen paragraphs for the display features.

A help screen is where a user goes when the display looks wrong, so the color
theme deserves standard wording.  :func:`theme_paragraph` means every app that
offers a picker says the same true thing and does not have to re-explain what
``t`` does.

The builder is a plain string: an app returns it from
:meth:`Screen.extra_help_paragraphs`, and ``BasicHelpScreen`` adds the
``Instructions`` separator and renders it as a bulleted instruction with a
hanging indent.

The symbol check is not a paragraph at all: ``BasicHelpScreen.draw_fonts()``
draws it once per app run, and the ``FONT_*`` constants here are the sentences
that section uses -- the unconditional install advice and the ASCII and
narrow-terminal variants.
"""

from __future__ import annotations

__all__ = [
    'FONT_ADVICE',
    'FONT_ASCII',
    'FONT_NARROW',
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

#: What the section says in ASCII mode, where no font can fail to draw a symbol.
FONT_ASCII = (
    'Plain ASCII is in use, so every symbol is covered. Restart with '
    '--glyphs unicode to check the full set.'
)

#: What the section says when the body is too narrow for the sample rows.
FONT_NARROW = (
    'Widen the terminal to see the full symbol check; install DejaVu Sans Mono '
    'and Noto Color Emoji if any symbol is a box.'
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


