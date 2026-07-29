"""
Day 3 acceptance tests — power management daemon and battery health.
Tests all four power states at boundary values (40%, 20%, 5% exactly) plus charging.
"""

import json
import pytest
from power.power_management_daemon import (
    PowerManagementDaemon,
    PowerState,
    SubsystemSeconds,
    voltage_to_percent,
    _state_for_percent,
)
from power.battery_health import BatteryHealthTracker, REPLACEMENT_CYCLE_THRESHOLD
from power.power_thermal_estimate import estimate_by_level, COMPONENT_PROFILES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_daemon(voltage: float, charging: bool = False):
    notifications = []
    logs = []

    def adc():
        return voltage

    def charging_fn():
        return charging

    daemon = PowerManagementDaemon(
        adc_read_fn=adc,
        charging_detected_fn=charging_fn,
        notify_phone_fn=notifications.append,
        log_fn=logs.append,
    )
    return daemon, notifications, logs


def _percent_to_voltage(pct: float) -> float:
    """Reverse-lookup voltage for a given percentage (approximate, for testing)."""
    from power.power_management_daemon import _DISCHARGE_CURVE
    if pct >= 100:
        return _DISCHARGE_CURVE[0][0]
    if pct <= 0:
        return _DISCHARGE_CURVE[-1][0]
    for i in range(len(_DISCHARGE_CURVE) - 1):
        v_hi, pct_hi = _DISCHARGE_CURVE[i]
        v_lo, pct_lo = _DISCHARGE_CURVE[i + 1]
        if pct_lo <= pct <= pct_hi:
            ratio = (pct - pct_lo) / (pct_hi - pct_lo)
            return v_lo + ratio * (v_hi - v_lo)
    return _DISCHARGE_CURVE[-1][0]


# ── Voltage → percent lookup ──────────────────────────────────────────────────

def test_full_charge_voltage_is_100_percent():
    assert voltage_to_percent(4.20) == 100.0

def test_depleted_voltage_is_0_percent():
    assert voltage_to_percent(3.00) == 0.0

def test_voltage_above_max_clamped_to_100():
    assert voltage_to_percent(5.0) == 100.0

def test_voltage_below_min_clamped_to_0():
    assert voltage_to_percent(2.0) == 0.0

def test_mid_voltage_interpolates():
    pct = voltage_to_percent(3.75)
    assert 45.0 <= pct <= 55.0


# ── Power state boundaries (spec: >40, 20-40, <20, <5) ───────────────────────

def test_above_40_is_full_active():
    assert _state_for_percent(41.0) == PowerState.FULL_ACTIVE

def test_exactly_40_is_conservation():
    assert _state_for_percent(40.0) == PowerState.CONSERVATION

def test_between_20_and_40_is_conservation():
    assert _state_for_percent(30.0) == PowerState.CONSERVATION

def test_exactly_20_is_conservation():
    # Spec: Conservation is "20–40%"; Critical is "below 20%" (< 20, not ≤ 20)
    assert _state_for_percent(20.0) == PowerState.CONSERVATION

def test_between_5_and_20_is_critical():
    assert _state_for_percent(10.0) == PowerState.CRITICAL

def test_exactly_5_is_critical():
    # Spec: Emergency is "below 5%" (< 5, not ≤ 5); 5% exactly is still Critical
    assert _state_for_percent(5.0) == PowerState.CRITICAL

def test_below_5_is_emergency():
    assert _state_for_percent(4.9) == PowerState.EMERGENCY
    assert _state_for_percent(0.0) == PowerState.EMERGENCY


# ── Daemon state enforcement per spec ────────────────────────────────────────

def test_full_active_no_camera_restriction():
    daemon, _, _ = _make_daemon(_percent_to_voltage(80.0))
    daemon.tick()
    assert daemon.get_restrictions().camera_max_level == 5

def test_conservation_camera_capped_at_4():
    daemon, _, _ = _make_daemon(_percent_to_voltage(30.0))
    daemon.tick()
    r = daemon.get_restrictions()
    assert r.camera_max_level == 4

def test_conservation_led_capped_at_50():
    daemon, _, _ = _make_daemon(_percent_to_voltage(30.0))
    daemon.tick()
    assert daemon.get_restrictions().led_max_brightness_pct == 50

def test_conservation_audio_capped_at_4():
    daemon, _, _ = _make_daemon(_percent_to_voltage(30.0))
    daemon.tick()
    assert daemon.get_restrictions().audio_max_level == 4

def test_critical_camera_capped_at_3():
    daemon, _, _ = _make_daemon(_percent_to_voltage(15.0))
    daemon.tick()
    assert daemon.get_restrictions().camera_max_level == 3

def test_critical_led_capped_at_20():
    daemon, _, _ = _make_daemon(_percent_to_voltage(15.0))
    daemon.tick()
    assert daemon.get_restrictions().led_max_brightness_pct == 20

def test_critical_audio_capped_at_3():
    daemon, _, _ = _make_daemon(_percent_to_voltage(15.0))
    daemon.tick()
    assert daemon.get_restrictions().audio_max_level == 3

def test_critical_sync_disabled():
    daemon, _, _ = _make_daemon(_percent_to_voltage(15.0))
    daemon.tick()
    assert daemon.get_restrictions().sync_enabled is False

def test_emergency_camera_off():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().camera_max_level is None

def test_emergency_wifi_off():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().wifi_enabled is False

def test_emergency_ble_beacon_only():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().ble_beacon_only is True

def test_emergency_motion_hr_minimum_sampling():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().motion_hr_minimum_sampling is True

def test_emergency_audio_ring_buffer_only():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().audio_max_level is None

def test_emergency_sync_disabled():
    daemon, _, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert daemon.get_restrictions().sync_enabled is False


# ── Boundary values exactly at 40%, 20%, 5% ──────────────────────────────────

def test_boundary_40_percent_is_conservation():
    daemon, _, _ = _make_daemon(_percent_to_voltage(40.0))
    state = daemon.tick()
    assert state == PowerState.CONSERVATION

def test_boundary_20_percent_is_conservation():
    # "Below 20%" is < 20; 20% itself is still Conservation
    daemon, _, _ = _make_daemon(_percent_to_voltage(20.0))
    state = daemon.tick()
    assert state == PowerState.CONSERVATION

def test_boundary_5_percent_is_critical():
    # "Below 5%" is < 5; 5% itself is still Critical
    daemon, _, _ = _make_daemon(_percent_to_voltage(5.0))
    state = daemon.tick()
    assert state == PowerState.CRITICAL


# ── Notifications ──────────────────────────────────────────────────────────────

def test_conservation_entry_notifies_phone_once():
    notifications = []
    logs = []
    voltage_holder = [_percent_to_voltage(80.0)]

    daemon = PowerManagementDaemon(
        adc_read_fn=lambda: voltage_holder[0],
        charging_detected_fn=lambda: False,
        notify_phone_fn=notifications.append,
        log_fn=logs.append,
    )
    daemon.tick()  # full active
    voltage_holder[0] = _percent_to_voltage(30.0)
    daemon.tick()  # → conservation (notify)
    daemon.tick()  # still conservation (no second notify)
    assert len([n for n in notifications if "conservation" in n.lower()]) == 1

def test_critical_notifies_phone():
    daemon, notifications, _ = _make_daemon(_percent_to_voltage(10.0))
    daemon.tick()
    assert any("critical" in n.lower() or "20%" in n for n in notifications)

def test_emergency_notifies_phone():
    daemon, notifications, _ = _make_daemon(_percent_to_voltage(3.0))
    daemon.tick()
    assert any("emergency" in n.lower() or "5%" in n or "urgent" in n.lower() for n in notifications)


# ── Charging detection ────────────────────────────────────────────────────────

def test_charging_triggers_charging_state():
    daemon, _, _ = _make_daemon(3.5, charging=True)
    state = daemon.tick()
    assert state == PowerState.CHARGING

def test_charging_state_no_restrictions():
    daemon, _, _ = _make_daemon(3.5, charging=True)
    daemon.tick()
    r = daemon.get_restrictions()
    assert r.camera_max_level == 5
    assert r.wifi_enabled is True

def test_charging_logs_animation():
    daemon, notifications, logs = _make_daemon(3.5, charging=True)
    daemon.tick()
    assert any("charg" in l.lower() for l in logs)


# ── Battery health — charge cycle counter ─────────────────────────────────────

def test_no_replacement_before_500_cycles():
    tracker = BatteryHealthTracker()
    tracker.record_discharge(49_900.0)   # 499 cycles
    report = tracker.report()
    assert report.replacement_needed is False

def test_replacement_flagged_at_exactly_500_cycles():
    tracker = BatteryHealthTracker()
    tracker.record_discharge(50_000.0)   # exactly 500 cycles
    report = tracker.report()
    assert report.replacement_needed is True

def test_replacement_flagged_above_500_cycles():
    tracker = BatteryHealthTracker()
    tracker.record_discharge(60_000.0)
    assert tracker.report().replacement_needed is True

def test_cycle_count_accumulates_correctly():
    tracker = BatteryHealthTracker()
    tracker.record_discharge(25.0)
    tracker.record_discharge(25.0)
    tracker.record_discharge(50.0)
    assert tracker.cycle_count == 1.0

def test_partial_cycles_counted():
    tracker = BatteryHealthTracker()
    tracker.record_discharge(50.0)
    assert tracker.cycle_count == 0.5


# ── Daily power report JSON schema ───────────────────────────────────────────

def test_daily_report_json_schema():
    daemon, _, _ = _make_daemon(_percent_to_voltage(80.0))
    daemon.tick()
    active = SubsystemSeconds(camera=3600, audio=1800, motion=7200, heart_rate=7200, ble=86400, wifi=1200)
    report = daemon.generate_daily_report(
        date_str="2024-06-15",
        active_seconds=active,
        partial_cycles=0.3,
        power_consumed_mwh=1500.0,
        time_at_state={"full_active": 50000, "conservation": 36400},
    )
    blob = json.loads(report.to_json())
    assert "date" in blob
    assert "active_seconds" in blob
    assert "partial_charge_cycles" in blob
    assert "estimated_power_consumed_mwh" in blob
    assert "time_at_state_seconds" in blob
    assert blob["date"] == "2024-06-15"

def test_daily_report_active_seconds_fields():
    daemon, _, _ = _make_daemon(_percent_to_voltage(80.0))
    daemon.tick()
    active = SubsystemSeconds(camera=100, audio=200, motion=300, heart_rate=400, ble=500, wifi=600)
    report = daemon.generate_daily_report("2024-06-15", active, 0.5, 1000.0, {})
    blob = json.loads(report.to_json())
    assert blob["active_seconds"]["camera"] == 100
    assert blob["active_seconds"]["audio"] == 200
    assert blob["active_seconds"]["wifi"] == 600


# ── Power thermal estimate sanity ─────────────────────────────────────────────

def test_estimate_covers_all_levels():
    estimates = estimate_by_level()
    for level in ["L0", "L1", "L2", "L3", "L4", "L5"]:
        assert level in estimates

def test_higher_level_draws_more_current():
    estimates = estimate_by_level()
    for lvl_a, lvl_b in [("L0", "L3"), ("L1", "L4"), ("L2", "L5")]:
        assert estimates[lvl_b].total_current_mA > estimates[lvl_a].total_current_mA

def test_all_components_present():
    names = {p.name for p in COMPONENT_PROFILES}
    assert any("ICM" in n for n in names)
    assert any("MAX30102" in n for n in names)
    assert any("IMX219" in n for n in names)
    assert any("ATECC608B" in n for n in names)
    assert any("RK3566" in n or "Radxa" in n for n in names)
