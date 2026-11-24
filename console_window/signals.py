"""SIGINT handling shared by the windows."""

from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType
from typing import Any, cast

SigHandler = Callable[[int, FrameType | None], object]

ctrl_c_flag: bool = False

_ctrl_c_terminates: bool = True

_ctrl_c_terminates_locked: bool = False

# Sentinel meaning "this library has not installed a SIGINT handler right now".
_UNSET: object = object()

_ctrl_c_previous: object = _UNSET

_ctrl_c_installed: object = _UNSET

_ctrl_c_users: int = 0


def _ctrl_c_handler(sig: int, frame: FrameType | None) -> None:
    global ctrl_c_flag
    ctrl_c_flag = True


def _current_handler() -> object:
    """Return the handler currently installed for SIGINT (best effort).

    Tests and exotic platforms may supply a partial `signal` module,
    so fall back to `default_int_handler` when the query is unavailable.
    """
    get = getattr(signal, 'getsignal', None)
    if get is None:
        return signal.default_int_handler
    try:
        return get(signal.SIGINT)
    except (ValueError, OSError):
        return signal.default_int_handler


def _install(handler: object) -> bool:
    # signal.signal() only works on the main thread;
    # a window created elsewhere simply runs with the
    # host's handler rather than failing construction.
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
    # Every setup pairs with one teardown.
    _ctrl_c_users += 1
    if _ctrl_c_terminates_locked:
        return
    if _ctrl_c_previous is _UNSET:
        _ctrl_c_previous = _current_handler()
    handler: SigHandler
    if _ctrl_c_terminates:
        # The first terminating window wins for as long as any window is live.
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

    `teardown_ctrl_c()` calls this when the last window stops. Embedding
    applications that manage SIGINT themselves may also call it directly.
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
