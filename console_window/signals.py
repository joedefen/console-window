from __future__ import annotations

import signal
from types import FrameType

# Set to True by the SIGINT handler when Ctrl-C is pressed.
ctrl_c_flag: bool = False

# Whether Ctrl-C should terminate (True) or be delivered as a key (False).
_ctrl_c_terminates: bool = True


def _ctrl_c_handler(sig: int, frame: FrameType | None) -> None:
    global ctrl_c_flag
    ctrl_c_flag = True


def set_ctrl_c_policy(ctrl_c_terminates: bool) -> None:
    global _ctrl_c_terminates
    _ctrl_c_terminates = bool(ctrl_c_terminates)


def setup_ctrl_c() -> None:
    if not _ctrl_c_terminates:
        signal.signal(signal.SIGINT, _ctrl_c_handler)


def teardown_ctrl_c() -> None:
    if not _ctrl_c_terminates:
        signal.signal(signal.SIGINT, signal.default_int_handler)
