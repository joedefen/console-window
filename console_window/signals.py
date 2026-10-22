from __future__ import annotations

import signal
from types import FrameType
from typing import Any, Callable, cast

# A SIGINT handler as ``signal.signal`` understands it.  ``object`` as the
# return type keeps this compatible with both default_int_handler (which never
# returns) and ordinary handlers.
SigHandler = Callable[[int, FrameType | None], object]

# The SIGINT policy is deliberately module-level state: the signal itself is
# process-global, there is exactly one policy per process, and module scope is
# what lets a harness (and this project's tests) swap the fields wholesale.
# pylint: disable=global-statement

# Set to True by the SIGINT handler when Ctrl-C is pressed.
ctrl_c_flag: bool = False

# Whether Ctrl-C should terminate (True) or be delivered as a key (False).
_ctrl_c_terminates: bool = True

# Once any *live* window has asked for terminating Ctrl-C, that policy is
# latched: SIGINT never goes back to being an application key while a window
# still depends on it.  SIGINT is process-global, so a non-terminating window
# must not be able to swallow Ctrl-C after a terminating one exists
# (AUDIT.md §3.1).  The latch is cleared by reset_ctrl_c(), which teardown calls
# once the last window has stopped.
_ctrl_c_terminates_locked: bool = False

# Sentinel meaning "this library has not installed a SIGINT handler right now".
_UNSET: object = object()

# The handler that was installed before the library first took SIGINT over.
# Captured once per installation episode and restored verbatim, so an embedding
# application that manages SIGINT itself gets its own handler back instead of
# Python's default_int_handler (AUDIT.md §3.1).
_ctrl_c_previous: object = _UNSET

# The handler this library last installed in the current episode; installing the
# same one twice (a second window with the same policy) is a no-op.
_ctrl_c_installed: object = _UNSET

# Number of live windows that called setup_ctrl_c() and have not yet called
# teardown_ctrl_c().  The host handler is only restored when this reaches zero,
# so stopping one of several windows cannot disarm the others.
_ctrl_c_users: int = 0


def _ctrl_c_handler(sig: int, frame: FrameType | None) -> None:
    # pylint: disable=unused-argument  # signature fixed by signal.signal()
    global ctrl_c_flag
    ctrl_c_flag = True


def _current_handler() -> object:
    """Return the handler currently installed for SIGINT (best effort).

    Tests and exotic platforms may supply a partial ``signal`` module, so fall
    back to ``default_int_handler`` when the query is unavailable.
    """
    get = getattr(signal, 'getsignal', None)
    if get is None:
        return signal.default_int_handler
    try:
        return get(signal.SIGINT)
    except (ValueError, OSError):
        return signal.default_int_handler


def _install(handler: object) -> bool:
    # signal.signal() only works on the main thread; a window created elsewhere
    # simply runs with the host's handler rather than failing construction.
    try:
        signal.signal(signal.SIGINT, cast(Any, handler))
    except ValueError:
        return False
    return True


def set_ctrl_c_policy(ctrl_c_terminates: bool) -> None:
    global _ctrl_c_terminates
    if _ctrl_c_terminates_locked:
        return
    _ctrl_c_terminates = bool(ctrl_c_terminates)


def setup_ctrl_c() -> None:
    global _ctrl_c_terminates_locked, _ctrl_c_previous, _ctrl_c_users
    global _ctrl_c_installed
    # Every setup pairs with one teardown, including the latched no-op case:
    # otherwise stopping a window that found the latch set would decrement the
    # count of a window that is still running.
    _ctrl_c_users += 1
    if _ctrl_c_terminates_locked:
        return
    if _ctrl_c_previous is _UNSET:
        _ctrl_c_previous = _current_handler()
    handler: SigHandler
    if _ctrl_c_terminates:
        # First terminating window wins for as long as any window is live.
        # Restore the default handler in case a non-terminating window already
        # installed ours, then never let a later window replace it.
        _ctrl_c_terminates_locked = True
        handler = signal.default_int_handler
    else:
        handler = _ctrl_c_handler
    if handler is not _ctrl_c_installed and _install(handler):
        _ctrl_c_installed = handler


def teardown_ctrl_c() -> None:
    """Stop relying on this library's SIGINT policy for one window."""
    global _ctrl_c_users
    if _ctrl_c_users > 0:
        _ctrl_c_users -= 1
    if _ctrl_c_users == 0:
        reset_ctrl_c()


def reset_ctrl_c() -> None:
    """Restore the pre-library SIGINT handler and clear the policy latch.

    ``teardown_ctrl_c()`` calls this when the last window stops, so a process
    that creates and destroys windows in sequence does not stay latched onto
    terminating Ctrl-C.  Embedding applications that manage SIGINT themselves
    can also call it directly to hand the signal back mid-life.
    """
    global _ctrl_c_previous, _ctrl_c_terminates_locked, _ctrl_c_terminates
    global _ctrl_c_users, _ctrl_c_installed
    previous, _ctrl_c_previous = _ctrl_c_previous, _UNSET
    _ctrl_c_installed = _UNSET
    _ctrl_c_users = 0
    _ctrl_c_terminates_locked = False
    _ctrl_c_terminates = True
    if previous is _UNSET or previous is None:
        return
    if previous is _ctrl_c_handler:
        # Never leave the host holding our own flag-setting handler.
        previous = signal.default_int_handler
    try:
        signal.signal(signal.SIGINT, cast(Any, previous))
    except (ValueError, OSError, TypeError):
        pass
