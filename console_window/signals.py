"""SIGINT (Ctrl-C) handling policy for console_window.

Historically the policy was implemented by rebinding module-level functions at
``ConsoleWindow`` construction time (action-at-a-distance).  This module makes
the policy explicit:

* When ``ctrl_c_terminates`` is True (default), the default SIGINT handler is
  left in place, so Ctrl-C terminates the process as usual.
* When False, a handler is installed that sets :data:`ctrl_c_flag`; the main
  input loop polls that flag and can return the ETX key code (0x3) instead.
"""

import signal

# Set to True by the SIGINT handler when Ctrl-C is pressed.
ctrl_c_flag = False

# Whether Ctrl-C should terminate (True) or be delivered as a key (False).
_ctrl_c_terminates = True


def _ctrl_c_handler(sig, frame):
    """SIGINT handler: record that Ctrl-C was pressed."""
    global ctrl_c_flag
    ctrl_c_flag = True


def set_ctrl_c_policy(ctrl_c_terminates):
    """Configure how Ctrl-C is handled for the next :func:`setup_ctrl_c`."""
    global _ctrl_c_terminates
    _ctrl_c_terminates = bool(ctrl_c_terminates)


def setup_ctrl_c():
    """Install the SIGINT handler when Ctrl-C should be delivered as a key."""
    if not _ctrl_c_terminates:
        signal.signal(signal.SIGINT, _ctrl_c_handler)


def teardown_ctrl_c():
    """Restore the default SIGINT handler on curses shutdown."""
    if not _ctrl_c_terminates:
        signal.signal(signal.SIGINT, signal.default_int_handler)
