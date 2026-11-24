"""Semantic color roles, and one resolver for the color switch."""

from __future__ import annotations

import curses
import os
from collections.abc import Mapping
from typing import ClassVar

from .theme import Theme

__all__ = [
    'MONO_ROLES',
    'Appearance',
    'colors_enabled',
    'resolve_appearance',
    'semantic_attr',
    'set_colors_enabled',
]


class Appearance:
    """Semantic color roles, and one resolver for the color switch.

    Role ids are `Theme`'s semantic pairs, installed at startup and whenever a
    theme is applied, so a theme change recolors every draw path.  `mono` is a
    theme, not a mode layered on a palette.
    """

    MONO_ROLES: ClassVar[dict[int, int]] = {
        Theme.DANGER: curses.A_BOLD | curses.A_REVERSE,
        Theme.ERROR: curses.A_BOLD | curses.A_REVERSE,
        Theme.WARNING: curses.A_BOLD,
        Theme.SUCCESS: curses.A_BOLD,
        Theme.EMPHASIS: curses.A_BOLD,
        Theme.INFO: curses.A_NORMAL,
        Theme.PROGRESS: curses.A_NORMAL,
        Theme.OLD_SUCCESS: curses.A_NORMAL,
        Theme.HOTSWAP: curses.A_NORMAL,
    }

    # One terminal, so one process-wide decision.
    _COLORS_ENABLED: ClassVar[bool] = True

    @classmethod
    def set_colors_enabled(cls, enabled: bool) -> None:
        """Turn semantic color on or off for the whole process.

        Args:
            enabled: Whether roles resolve to color pairs rather than `MONO_ROLES`.
        """
        cls._COLORS_ENABLED = bool(enabled)

    @classmethod
    def colors_enabled(cls) -> bool:
        """True while semantic roles resolve to color pairs rather than attributes."""
        return cls._COLORS_ENABLED

    @staticmethod
    def resolve_appearance(
        cli_theme: str | None = None,
        saved_theme: str | None = '',
        environ: Mapping[str, str] | None = None,
    ) -> str:
        """Starting theme from the switches, environment and memory.

        Precedence, highest first: an explicit `--theme` (honored even when
        `NO_COLOR` is set), the `NO_COLOR` convention (any non-empty value
        selects `Theme.MONO`), then the remembered choice.  Names resolve
        through `Theme.resolve`; `''` means no explicit theme.

        The result is a decision, not an action: pass it to `Theme.set_active`.
        """
        env = os.environ if environ is None else environ

        if cli_theme:
            return Theme.resolve(cli_theme)
        if env.get('NO_COLOR'):
            return Theme.MONO
        if saved_theme:
            return Theme.resolve(saved_theme)
        return ''

    @classmethod
    def semantic_attr(cls, pair_id: int) -> int:
        """Attribute for a `Theme` role, or its monochrome fallback.

        Args:
            pair_id: A semantic pair id, e.g. `Theme.DANGER`; unknown ids
                degrade to plain text.
        """
        if not cls._COLORS_ENABLED:
            return cls.MONO_ROLES.get(pair_id, curses.A_NORMAL)
        try:
            if not curses.has_colors():
                return cls.MONO_ROLES.get(pair_id, curses.A_NORMAL)
            return curses.color_pair(pair_id)
        except Exception:
            # The terminal is not initialized yet; never abort a redraw.
            return 0


def _startup_theme(chosen: str | None,
                   environ: Mapping[str, str] | None = None) -> str | None:
    """The theme to start on, honoring `NO_COLOR` only when nothing decided."""
    if chosen or Theme.get_current() is not None:
        return chosen
    return Appearance.resolve_appearance(environ=environ) or None


# Module-level aliases for the class methods.
MONO_ROLES = Appearance.MONO_ROLES
colors_enabled = Appearance.colors_enabled
resolve_appearance = Appearance.resolve_appearance
semantic_attr = Appearance.semantic_attr
set_colors_enabled = Appearance.set_colors_enabled
