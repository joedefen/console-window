import signal
from types import SimpleNamespace

import pytest

from console_window import signals

_FAKE_SIGINT = signal.SIGINT
_FAKE_DEFAULT = object()


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    monkeypatch.setattr(
        signals,
        'signal',
        SimpleNamespace(
            SIGINT=_FAKE_SIGINT,
            default_int_handler=_FAKE_DEFAULT,
            signal=fake_signal,
        ),
    )
    monkeypatch.setattr(signals, '_ctrl_c_terminates', True)
    monkeypatch.setattr(signals, '_ctrl_c_terminates_locked', False)
    return calls


def test_non_terminating_window_installs_and_restores_handler(recorded):
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()
    assert recorded == [(_FAKE_SIGINT, signals._ctrl_c_handler)]

    signals.teardown_ctrl_c()
    assert recorded[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)
    # No terminating window has claimed the process yet.
    assert signals._ctrl_c_terminates_locked is False


def test_terminating_window_latches_and_replaces_handler(recorded):
    # Window A: Ctrl-C as an application key.
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()
    assert recorded == [(_FAKE_SIGINT, signals._ctrl_c_handler)]

    # Window B: terminating Ctrl-C wins and replaces A's handler.
    signals.set_ctrl_c_policy(True)
    signals.setup_ctrl_c()
    assert recorded[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)
    assert signals._ctrl_c_terminates_locked is True

    # A later non-terminating window cannot take Ctrl-C back, and stopping it
    # cannot uninstall the terminating policy (the AUDIT.md §3.1 interleaving).
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()
    signals.teardown_ctrl_c()
    assert len(recorded) == 2
    assert signals._ctrl_c_terminates_locked is True


def test_latched_policy_ignores_new_policy_values(recorded):
    signals.set_ctrl_c_policy(True)
    signals.setup_ctrl_c()
    assert signals._ctrl_c_terminates_locked is True

    signals.set_ctrl_c_policy(False)
    assert signals._ctrl_c_terminates is True
