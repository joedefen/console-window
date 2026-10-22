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
    # Per-episode state, reset so one test cannot leak a captured handler or a
    # live-window count into the next.
    monkeypatch.setattr(signals, '_ctrl_c_users', 0)
    monkeypatch.setattr(signals, '_ctrl_c_previous', signals._UNSET)
    monkeypatch.setattr(signals, '_ctrl_c_installed', signals._UNSET)
    return calls


def test_non_terminating_window_installs_and_restores_handler(recorded):
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()
    assert recorded == [(_FAKE_SIGINT, signals._ctrl_c_handler)]

    signals.teardown_ctrl_c()
    assert recorded[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)
    # No terminating window has claimed the process, and the episode is over.
    assert signals._ctrl_c_terminates_locked is False
    assert signals._ctrl_c_users == 0


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

    # A later non-terminating window cannot take Ctrl-C back, and stopping one
    # of the three windows cannot uninstall the terminating policy (the
    # AUDIT.md §3.1 interleaving).
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


def test_handler_restored_only_when_the_last_window_stops(recorded):
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()  # window A
    signals.setup_ctrl_c()  # window B
    assert signals._ctrl_c_users == 2

    signals.teardown_ctrl_c()  # A stops; B still needs the handler
    assert signals._ctrl_c_users == 1
    assert recorded == [(_FAKE_SIGINT, signals._ctrl_c_handler)]

    signals.teardown_ctrl_c()  # B stops; now the host handler comes back
    assert recorded[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)
    assert signals._ctrl_c_users == 0


def test_latched_setup_still_pairs_with_its_teardown(recorded):
    # A window that joins after the latch is set does not install anything, but
    # it must still account for its own teardown or stopping it would drop the
    # count of a window that is still live.
    signals.set_ctrl_c_policy(True)
    signals.setup_ctrl_c()   # terminating window, sets the latch
    signals.setup_ctrl_c()   # latched window, no install
    signals.teardown_ctrl_c()
    assert signals._ctrl_c_users == 1
    assert len(recorded) == 1  # the terminating install only

    signals.teardown_ctrl_c()
    assert signals._ctrl_c_users == 0


def test_previous_host_handler_is_captured_and_restored(monkeypatch):
    # The handler installed before the first window is restored verbatim, not
    # replaced by Python's default_int_handler.
    calls = []
    host_handler = object()
    current = {'handler': host_handler}

    def fake_signal(sig, handler):
        calls.append((sig, handler))
        current['handler'] = handler

    monkeypatch.setattr(signals, 'signal', SimpleNamespace(
        SIGINT=_FAKE_SIGINT,
        default_int_handler=_FAKE_DEFAULT,
        signal=fake_signal,
        getsignal=lambda sig: current['handler'],
    ))
    monkeypatch.setattr(signals, '_ctrl_c_terminates', True)
    monkeypatch.setattr(signals, '_ctrl_c_terminates_locked', False)
    monkeypatch.setattr(signals, '_ctrl_c_users', 0)
    monkeypatch.setattr(signals, '_ctrl_c_previous', signals._UNSET)
    monkeypatch.setattr(signals, '_ctrl_c_installed', signals._UNSET)

    signals.setup_ctrl_c()
    assert calls[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)

    signals.teardown_ctrl_c()
    assert calls[-1] == (_FAKE_SIGINT, host_handler)
    assert signals._ctrl_c_terminates_locked is False


def test_reset_ctrl_c_clears_the_latch_for_a_later_window(recorded):
    signals.set_ctrl_c_policy(True)
    signals.setup_ctrl_c()
    assert signals._ctrl_c_terminates_locked is True

    signals.reset_ctrl_c()
    assert signals._ctrl_c_terminates_locked is False
    assert signals._ctrl_c_terminates is True

    # With the latch cleared, Ctrl-C can be an application key again.
    signals.set_ctrl_c_policy(False)
    assert signals._ctrl_c_terminates is False


def test_reset_ctrl_c_never_leaves_the_library_handler_installed(recorded):
    signals.set_ctrl_c_policy(False)
    signals.setup_ctrl_c()
    assert recorded[-1] == (_FAKE_SIGINT, signals._ctrl_c_handler)

    # Pretend the captured "previous" handler was our own flag setter (which
    # can happen if an application captured it); restoring it would make Ctrl-C
    # permanently non-terminating, so the default handler is restored instead.
    signals._ctrl_c_previous = signals._ctrl_c_handler
    signals.reset_ctrl_c()
    assert recorded[-1] == (_FAKE_SIGINT, _FAKE_DEFAULT)
