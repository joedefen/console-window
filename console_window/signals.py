from __future__ import annotations

import signal
from types import FrameType

# Set to True by the SIGINT handler when Ctrl-C is pressed.
ctrl_c_flag: bool = False

# Whether Ctrl-C should terminate (True) or be delivered as a key (False).
_ctrl_c_terminates: bool = True

# Once any window has asked for terminating Ctrl-C, that policy is latched for
# the rest of the process: SIGINT never goes back to being an application key.
# SIGINT is process-global, so a non-terminating window must not be able to
# swallow Ctrl-C after a terminating one exists (AUDIT.md §3.1).
_ctrl_c_terminates_locked: bool = False


def _ctrl_c_handler(sig: int, frame: FrameType | None) -> None:
    global ctrl_c_flag
    ctrl_c_flag = True


def set_ctrl_c_policy(ctrl_c_terminates: bool) -> None:
    global _ctrl_c_terminates
    if _ctrl_c_terminates_locked:
        return
    _ctrl_c_terminates = bool(ctrl_c_terminates)


def setup_ctrl_c() -> None:
    global _ctrl_c_terminates_locked
    if _ctrl_c_terminates_locked:
        return
    if _ctrl_c_terminates:
        # First terminating window wins for the process lifetime.  Restore the
        # default handler in case a non-terminating window already installed
        # ours, then never let a later window replace it.
        _ctrl_c_terminates_locked = True
        signal.signal(signal.SIGINT, signal.default_int_handler)
    else:
        signal.signal(signal.SIGINT, _ctrl_c_handler)


def teardown_ctrl_c() -> None:
    if _ctrl_c_terminates_locked:
        return
    if not _ctrl_c_terminates:
        signal.signal(signal.SIGINT, signal.default_int_handler)
