"""Test-only helpers, imported directly by the suite (not installed).

pytest prepends this directory to ``sys.path`` for the test modules, so
``import support`` works without making ``tests`` a package.
"""

from types import SimpleNamespace

from console_window.screens import Screen


def screen_of(win):
    """Return a Screen attached to *win*, creating and adopting it once.

    Content belongs to a Screen: the window has no public ``add_*()`` writers.
    A test that only needs to fill content uses this instead of building a real
    app object.  Every ``win.body``/``win.head`` read keeps working because the
    adopted screen *is* the window's current view.

    The screen is cached on the window so repeated calls in one test share one
    content model (as an app's own Screen would).
    """
    screen = getattr(win, '_test_screen', None)
    if screen is None:
        app = SimpleNamespace(win=win)
        screen = Screen(app)
        win._test_screen = screen
    win._adopt_view(screen)
    return screen
