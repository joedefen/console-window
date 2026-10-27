"""Shared fixtures for the console-window suite."""

import pytest

from console_window import glyphs


@pytest.fixture(autouse=True)
def isolated_glyph_state(monkeypatch):
    """Start every test from the built-in glyphs and Unicode mode.

    The glyph mode is process state on purpose (one terminal per process), so
    without this reset a test that forces ASCII would leak into every test that
    runs after it.  ``TERM`` is pinned for the same reason: auto-detection runs
    on window construction, and a ``dumb`` terminal in CI would flip the mode
    for tests that are not about detection.
    """
    monkeypatch.setenv('TERM', 'xterm-256color')
    monkeypatch.delenv(glyphs.GLYPHS_ENV, raising=False)
    monkeypatch.delenv(glyphs.AUDIT_ENV, raising=False)
    glyphs.reset()
    yield
    glyphs.reset()
