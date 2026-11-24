"""Ready-made help-screen paragraphs for the display features."""

from __future__ import annotations

__all__ = [
    'FONT_ADVICE',
    'FONT_ASCII',
    'theme_paragraph',
]

# Two lines each, sized for the 55-cell Font Check section.
FONT_ADVICE = (
    'If symbols are fillers or blanks or columns shift,',
    'install DejaVu Sans Mono and Noto Color Emoji fonts.',
)

FONT_ASCII = (
    'Plain ASCII spellings cover every symbol.',
    'Restart with --glyphs unicode to check the real fonts.',
)


def theme_paragraph(
    open_key: str = 'T',
    cycle_key: str = 't',
    remembered: bool = False,
) -> str:
    """Describe the theme picker: how to open it, cycle it, and leave it.

    Args:
        remembered: Promise that the choice survives a restart; pass True only
            when the app supplies a `ThemeStore`.
    """
    text = (
        f'Color theme: press {open_key} for the theme picker, then {cycle_key} '
        'to cycle the themes (ESC returns).'
    )
    if remembered:
        text += ' The choice is remembered for the next start.'
    return text
