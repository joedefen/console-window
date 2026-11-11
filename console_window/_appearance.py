"""Semantic color roles, and one resolver for the color switch.

The public surface is :class:`Appearance`; this module is its private
implementation.  The name is capitalized to match the other package-root
namespaces (``Theme``, ``Glyphs``) and is the only form documented and
supported from 3.0 onward.
"""

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

    Color here is decoration, never information.  Every role degrades to an
    attribute when color is off, so the same hierarchy survives on a monochrome
    terminal or under the ``mono`` theme.  Applications kept writing this layer
    twice: the role-to-attribute mapping, the process-wide switch, and a lookup
    that must never abort a redraw.  It now lives here.

    The role ids are :class:`Theme`'s semantic pairs rather than literal color
    numbers.  The library installs those pairs at startup and re-installs them
    whenever a theme is applied, so changing the active theme recolors the
    whole UI without an edit to any draw code.

    ``mono`` is a theme, not a mode layered on a palette.  Selecting it sets the
    switch off; selecting a palette sets it back on.  :meth:`Theme.set_active`
    owns that synchronization, so an application never needs to call
    :meth:`set_colors_enabled` itself.  The low-level methods remain public for
    embedding code that manages the switch directly.
    """

    # Role -> attribute used when color is off.  The hierarchy is kept with
    # emphasis instead of hue: the destructive roles are bold+reverse, warnings,
    # successes and emphasis are bold, and the informational roles carry
    # nothing (their surrounding structure already distinguishes them).
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

    # Process-wide switch, kept in step with the active theme by
    # Theme.set_active().  One terminal, so one decision.
    _COLORS_ENABLED: ClassVar[bool] = True

    @classmethod
    def set_colors_enabled(cls, enabled: bool) -> None:
        """Turn semantic color on or off for the whole process."""
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

        Precedence, highest first: an explicit ``--theme`` (a statement of
        intent, so it is honored even when ``NO_COLOR`` is set), the
        ``NO_COLOR`` convention (any non-empty value selects :attr:`Theme.MONO`,
        per no-color.org), then the remembered choice.

        ``cli_theme``/``saved_theme`` are returned resolved to a canonical
        library theme; ``''`` means "no explicit theme, keep the library
        default".  An unknown name resolves to ``'default'``, exactly like
        :meth:`Theme.resolve`, and a legacy ``dark-mono``/``light-mono`` name
        resolves to its canonical replacement.

        The result is a decision, not an action: pass it to
        :meth:`Theme.set_active`, which records the theme and synchronizes the
        appearance switch.  ``mono`` is a real theme, so there is no second
        "colors" value to apply.
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
        """Attribute for a :class:`Theme` role, or its monochrome fallback.

        With color off, or on a terminal that reports no color support, the
        role becomes an attribute from :attr:`MONO_ROLES`.  Otherwise both
        ``curses.has_colors()`` and ``curses.color_pair()`` can raise before
        ``initscr()`` (``color_pair()`` refuses to run until then), and a failed
        lookup must never abort a redraw, so that failure degrades to plain
        text.  The ``except`` is deliberately broad for that reason: a guarded
        redraw is worth more than a precise exception list, and the fallback is
        always the same.
        """
        if not cls._COLORS_ENABLED:
            return cls.MONO_ROLES.get(pair_id, curses.A_NORMAL)
        try:
            if not curses.has_colors():
                return cls.MONO_ROLES.get(pair_id, curses.A_NORMAL)
            return curses.color_pair(pair_id)
        except Exception:  # pylint: disable=broad-exception-caught
            # The terminal is not initialized yet; never abort a redraw.
            return 0


# The individual names remain part of the package root's public surface, as
# they have been since 2.2.0; they are the same functions the class exposes.
MONO_ROLES = Appearance.MONO_ROLES
colors_enabled = Appearance.colors_enabled
resolve_appearance = Appearance.resolve_appearance
semantic_attr = Appearance.semantic_attr
set_colors_enabled = Appearance.set_colors_enabled
