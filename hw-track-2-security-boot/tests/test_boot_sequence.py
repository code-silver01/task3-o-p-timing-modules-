"""
Day 2 acceptance tests — boot sequence and failure handling.
One test per row of the failure table (9 rows) + happy path + boot order verification.
"""

import pytest
from boot.boot_sequence import (
    BootSequenceManager,
    BootReport,
    ComponentStatus,
    DeviceState,
    BOOT_ORDER,
)
from boot.failure_handling import BootOutcome


def _hal_all_ok():
    return {c: (lambda: ComponentStatus.OK) for c in BOOT_ORDER}


def _hal_with_failure(component: str):
    hal = _hal_all_ok()
    hal[component] = lambda: ComponentStatus.FAIL
    return hal


# ── Happy path ────────────────────────────────────────────────────────────────

def test_happy_path_all_ok_reaches_ready():
    mgr = BootSequenceManager(_hal_all_ok())
    report = mgr.run()
    assert report.device_state == DeviceState.READY

def test_happy_path_no_halt_reason():
    mgr = BootSequenceManager(_hal_all_ok())
    report = mgr.run()
    assert report.halt_reason is None

def test_happy_path_no_failures():
    mgr = BootSequenceManager(_hal_all_ok())
    report = mgr.run()
    assert report.component_results == []

def test_boot_order_is_followed(monkeypatch):
    """Components must be checked in the canonical spec order."""
    visited = []
    hal = {}
    for c in BOOT_ORDER:
        name = c
        def make_fn(n):
            def fn():
                visited.append(n)
                return ComponentStatus.OK
            return fn
        hal[c] = make_fn(name)
    BootSequenceManager(hal).run()
    assert visited == BOOT_ORDER


# ── HALT rows ─────────────────────────────────────────────────────────────────

def test_security_chip_failure_halts():
    mgr = BootSequenceManager(_hal_with_failure("security_chip"))
    report = mgr.run()
    assert report.device_state == DeviceState.HALTED

def test_security_chip_failure_notifies_phone():
    mgr = BootSequenceManager(_hal_with_failure("security_chip"))
    report = mgr.run()
    assert len(report.phone_notifications) >= 1
    assert any("security" in n.lower() or "halt" in n.lower() for n in report.phone_notifications)

def test_security_chip_failure_stops_remaining_boot():
    """After HALT, no components after security_chip should be checked."""
    checked = []
    hal = _hal_with_failure("security_chip")
    storage_orig = hal["storage"]
    def tracking_storage():
        checked.append("storage")
        return ComponentStatus.OK
    hal["storage"] = tracking_storage
    BootSequenceManager(hal).run()
    assert "storage" not in checked

def test_storage_failure_halts():
    mgr = BootSequenceManager(_hal_with_failure("storage"))
    report = mgr.run()
    assert report.device_state == DeviceState.HALTED

def test_storage_failure_notifies_phone():
    mgr = BootSequenceManager(_hal_with_failure("storage"))
    report = mgr.run()
    assert len(report.phone_notifications) >= 1
    assert any("storage" in n.lower() or "halt" in n.lower() for n in report.phone_notifications)

def test_storage_failure_stops_remaining_boot():
    checked = []
    hal = _hal_with_failure("storage")
    def tracking_motion():
        checked.append("motion_sensor")
        return ComponentStatus.OK
    hal["motion_sensor"] = tracking_motion
    BootSequenceManager(hal).run()
    assert "motion_sensor" not in checked


# ── Degraded-continue rows ────────────────────────────────────────────────────

def test_motion_sensor_failure_degraded_boot():
    mgr = BootSequenceManager(_hal_with_failure("motion_sensor"))
    report = mgr.run()
    assert report.device_state == DeviceState.DEGRADED

def test_motion_sensor_failure_notifies_phone():
    mgr = BootSequenceManager(_hal_with_failure("motion_sensor"))
    report = mgr.run()
    assert any("motion" in n.lower() for n in report.phone_notifications)

def test_motion_sensor_failure_boot_continues():
    """Boot must continue past motion sensor failure — remaining components checked."""
    checked = []
    hal = _hal_with_failure("motion_sensor")
    def tracking_hr():
        checked.append("heart_rate_sensor")
        return ComponentStatus.OK
    hal["heart_rate_sensor"] = tracking_hr
    BootSequenceManager(hal).run()
    assert "heart_rate_sensor" in checked

def test_heart_rate_sensor_failure_degraded_boot():
    mgr = BootSequenceManager(_hal_with_failure("heart_rate_sensor"))
    report = mgr.run()
    assert report.device_state == DeviceState.DEGRADED

def test_heart_rate_sensor_failure_notifies_phone():
    mgr = BootSequenceManager(_hal_with_failure("heart_rate_sensor"))
    report = mgr.run()
    assert any("heart" in n.lower() or "hr" in n.lower() for n in report.phone_notifications)

def test_camera_failure_degraded_boot():
    mgr = BootSequenceManager(_hal_with_failure("camera"))
    report = mgr.run()
    assert report.device_state == DeviceState.DEGRADED

def test_camera_failure_notifies_phone():
    mgr = BootSequenceManager(_hal_with_failure("camera"))
    report = mgr.run()
    assert any("camera" in n.lower() or "audio" in n.lower() for n in report.phone_notifications)


# ── Normal-continue rows ──────────────────────────────────────────────────────

def test_display_failure_continues_normally():
    mgr = BootSequenceManager(_hal_with_failure("display"))
    report = mgr.run()
    assert report.device_state == DeviceState.READY

def test_display_failure_no_phone_notification():
    mgr = BootSequenceManager(_hal_with_failure("display"))
    report = mgr.run()
    # display failure → no phone notification per spec
    assert len(report.phone_notifications) == 0

def test_display_failure_logs():
    mgr = BootSequenceManager(_hal_with_failure("display"))
    report = mgr.run()
    result = next(r for r in report.component_results if r.component == "display")
    assert result.log is True

def test_status_led_failure_continues_normally():
    mgr = BootSequenceManager(_hal_with_failure("status_led"))
    report = mgr.run()
    assert report.device_state == DeviceState.READY

def test_status_led_failure_log_only():
    mgr = BootSequenceManager(_hal_with_failure("status_led"))
    report = mgr.run()
    assert len(report.phone_notifications) == 0
    result = next(r for r in report.component_results if r.component == "status_led")
    assert result.log is True

def test_bluetooth_failure_continues_normally():
    mgr = BootSequenceManager(_hal_with_failure("bluetooth"))
    report = mgr.run()
    assert report.device_state == DeviceState.READY

def test_bluetooth_failure_shows_display_icon():
    mgr = BootSequenceManager(_hal_with_failure("bluetooth"))
    report = mgr.run()
    assert any("BT" in e or "bt" in e.lower() for e in report.display_events)

def test_bluetooth_failure_no_phone_notification():
    mgr = BootSequenceManager(_hal_with_failure("bluetooth"))
    report = mgr.run()
    assert len(report.phone_notifications) == 0

def test_wifi_failure_continues_normally():
    mgr = BootSequenceManager(_hal_with_failure("wifi"))
    report = mgr.run()
    assert report.device_state == DeviceState.READY

def test_wifi_failure_no_phone_notification():
    mgr = BootSequenceManager(_hal_with_failure("wifi"))
    report = mgr.run()
    assert len(report.phone_notifications) == 0

def test_wifi_failure_logs():
    mgr = BootSequenceManager(_hal_with_failure("wifi"))
    report = mgr.run()
    result = next(r for r in report.component_results if r.component == "wifi")
    assert result.log is True


# ── HALT vs degraded asymmetry — must not share code path ────────────────────

def test_halt_and_degraded_outcomes_are_distinct():
    halt_report = BootSequenceManager(_hal_with_failure("security_chip")).run()
    degraded_report = BootSequenceManager(_hal_with_failure("motion_sensor")).run()
    assert halt_report.device_state == DeviceState.HALTED
    assert degraded_report.device_state == DeviceState.DEGRADED
    assert halt_report.device_state != degraded_report.device_state

def test_multiple_degraded_failures_still_degraded_not_halt():
    hal = _hal_all_ok()
    hal["motion_sensor"] = lambda: ComponentStatus.FAIL
    hal["camera"] = lambda: ComponentStatus.FAIL
    report = BootSequenceManager(hal).run()
    assert report.device_state == DeviceState.DEGRADED
    assert report.halt_reason is None


# ── UNAVAILABLE state (Rule 3) ────────────────────────────────────────────────

def test_unavailable_component_treated_as_failure():
    hal = _hal_all_ok()
    hal["security_chip"] = lambda: ComponentStatus.UNAVAILABLE
    report = BootSequenceManager(hal).run()
    assert report.device_state == DeviceState.HALTED
