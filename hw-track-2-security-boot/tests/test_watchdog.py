"""
Day 3 acceptance tests — watchdog daemon.
encryption_daemon failure → HALT
any other daemon failure → isolated restart, rest of system unaffected
"""

import pytest
from watchdog.watchdog_daemon import WatchdogDaemon, DaemonStatus, WatchdogAction


def _make_watchdog():
    halts = []
    restarts = []
    logs = []

    def halt_fn(msg):
        halts.append(msg)

    def restart_fn(name):
        restarts.append(name)

    def log_fn(msg):
        logs.append(msg)

    wd = WatchdogDaemon(halt_fn=halt_fn, restart_fn=restart_fn, log_fn=log_fn)
    return wd, halts, restarts, logs


def _alive():
    return DaemonStatus.ALIVE

def _dead():
    return DaemonStatus.DEAD

def _unavailable():
    return DaemonStatus.UNAVAILABLE


# ── Encryption daemon failure → HALT ─────────────────────────────────────────

def test_encryption_daemon_failure_triggers_halt():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _dead)
    events = wd.check_all()
    assert len(events) == 1
    assert events[0].action == WatchdogAction.HALT

def test_encryption_daemon_failure_calls_halt_fn():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _dead)
    wd.check_all()
    assert len(halts) == 1
    assert "encryption" in halts[0].lower() or "halt" in halts[0].lower()

def test_encryption_daemon_failure_sets_system_halted():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _dead)
    wd.check_all()
    assert wd.system_halted is True

def test_encryption_daemon_failure_does_not_trigger_restart():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _dead)
    wd.check_all()
    assert len(restarts) == 0

def test_encryption_daemon_unavailable_also_halts():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _unavailable)
    events = wd.check_all()
    assert events[0].action == WatchdogAction.HALT
    assert wd.system_halted is True

def test_encryption_daemon_failure_stops_sweep():
    """After encryption_daemon halts, no further daemons should be checked."""
    checked = []

    def tracking_check():
        checked.append("camera_daemon")
        return DaemonStatus.ALIVE

    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _dead)
    wd.register("camera_daemon", tracking_check)
    wd.check_all()
    assert "camera_daemon" not in checked


# ── Other daemon failure → isolated restart ───────────────────────────────────

def test_other_daemon_failure_triggers_restart():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("camera_daemon", _dead)
    events = wd.check_all()
    assert events[0].action == WatchdogAction.RESTART

def test_other_daemon_failure_calls_restart_fn():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("audio_daemon", _dead)
    wd.check_all()
    assert "audio_daemon" in restarts

def test_other_daemon_failure_does_not_halt():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("motion_daemon", _dead)
    wd.check_all()
    assert len(halts) == 0
    assert wd.system_halted is False

def test_other_daemon_failure_system_not_halted():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("ble_daemon", _dead)
    wd.check_all()
    assert wd.system_halted is False


# ── Other daemon failure leaves rest of system unaffected ─────────────────────

def test_other_daemon_failure_other_daemons_still_checked():
    checked = []

    def tracking_check():
        checked.append("wifi_daemon")
        return DaemonStatus.ALIVE

    wd, halts, restarts, logs = _make_watchdog()
    wd.register("audio_daemon", _dead)
    wd.register("wifi_daemon", tracking_check)
    wd.check_all()
    assert "wifi_daemon" in checked

def test_multiple_non_encryption_failures_all_restarted():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("audio_daemon", _dead)
    wd.register("motion_daemon", _dead)
    wd.register("ble_daemon", _dead)
    wd.check_all()
    assert set(restarts) == {"audio_daemon", "motion_daemon", "ble_daemon"}
    assert wd.system_halted is False

def test_alive_daemons_not_restarted():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _alive)
    wd.register("camera_daemon", _alive)
    wd.register("audio_daemon", _alive)
    events = wd.check_all()
    assert events == []
    assert restarts == []
    assert halts == []

def test_mixed_alive_and_dead_daemons():
    wd, halts, restarts, logs = _make_watchdog()
    wd.register("encryption_daemon", _alive)
    wd.register("camera_daemon", _dead)
    wd.register("audio_daemon", _alive)
    wd.register("motion_daemon", _dead)
    events = wd.check_all()
    assert len(events) == 2
    assert all(e.action == WatchdogAction.RESTART for e in events)
    assert wd.system_halted is False
