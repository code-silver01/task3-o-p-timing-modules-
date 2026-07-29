"""
Power & Thermal Estimate (Day 3).

LABEL: UNVERIFIED PLANNING ESTIMATE — datasheet-based, not measured.
       Do not treat these numbers as validated specs. Real measurements on hardware
       will differ. This document is for pre-hardware planning only.

Components (locked list from spec):
  ICM-42688-P  — motion sensor (IMU)
  MAX30102     — heart-rate/PPG sensor
  IMX219       — camera sensor
  ATECC608B    — security/crypto chip
  Radxa Zero 3W — main compute (RK3566, includes BT/WiFi via AP6256)
  DS3231-class — RTC backup

Capture intensity levels L0–L5 from HW-1 spec (stubbed here until HW-1 publishes):
  L0: idle/standby   L1: minimal   L2: low   L3: medium   L4: high   L5: maximum
"""

from dataclasses import dataclass
from typing import Dict, List


# ── Component current draw (mA) at each capture-intensity level ───────────────
# Sources: ICM-42688-P DS Rev1.0, MAX30102 DS Rev2, IMX219 DS,
#          ATECC608B DS, Radxa Zero 3W spec sheet, AP6256 DS.
# All figures are ESTIMATES from datasheet typical values — NOT measured.

@dataclass
class ComponentCurrentProfile:
    name: str
    datasheet_source: str
    current_mA_by_level: Dict[str, float]   # key = "L0".."L5"


COMPONENT_PROFILES: List[ComponentCurrentProfile] = [
    ComponentCurrentProfile(
        name="ICM-42688-P (IMU)",
        datasheet_source="ICM-42688-P Product Specification Rev 1.0",
        current_mA_by_level={
            "L0": 0.017,   # duty-cycled low-power mode
            "L1": 0.5,
            "L2": 0.77,
            "L3": 0.77,
            "L4": 0.77,
            "L5": 0.77,
        },
    ),
    ComponentCurrentProfile(
        name="MAX30102 (HR/PPG)",
        datasheet_source="MAX30102 Datasheet Rev 3",
        current_mA_by_level={
            "L0": 0.0007,  # shutdown
            "L1": 0.6,     # low LED current
            "L2": 1.2,
            "L3": 1.8,
            "L4": 6.0,
            "L5": 10.0,    # max LED current
        },
    ),
    ComponentCurrentProfile(
        name="IMX219 (Camera)",
        datasheet_source="IMX219 Product Brief / CSI spec",
        current_mA_by_level={
            "L0": 0.0,     # off / standby
            "L1": 50.0,    # preview low res
            "L2": 100.0,
            "L3": 150.0,
            "L4": 200.0,
            "L5": 250.0,   # full res continuous
        },
    ),
    ComponentCurrentProfile(
        name="ATECC608B (Crypto)",
        datasheet_source="ATECC608B Datasheet",
        current_mA_by_level={
            "L0": 0.001,   # sleep
            "L1": 1.0,
            "L2": 1.0,
            "L3": 1.5,
            "L4": 1.5,
            "L5": 2.0,     # active crypto ops
        },
    ),
    ComponentCurrentProfile(
        name="Radxa Zero 3W SoC (RK3566)",
        datasheet_source="Radxa Zero 3W Hardware Design v1.2",
        current_mA_by_level={
            "L0": 200.0,   # idle, single core
            "L1": 400.0,
            "L2": 600.0,
            "L3": 800.0,
            "L4": 1000.0,
            "L5": 1200.0,  # all cores active
        },
    ),
    ComponentCurrentProfile(
        name="AP6256 BT/WiFi (on Radxa Zero 3W)",
        datasheet_source="AP6256 Datasheet",
        current_mA_by_level={
            "L0": 0.5,    # BLE beacon only
            "L1": 10.0,
            "L2": 50.0,
            "L3": 100.0,
            "L4": 150.0,
            "L5": 200.0,  # WiFi full throughput
        },
    ),
    ComponentCurrentProfile(
        name="DS3231 RTC",
        datasheet_source="DS3231 Datasheet",
        current_mA_by_level={
            "L0": 0.17,
            "L1": 0.17,
            "L2": 0.17,
            "L3": 0.17,
            "L4": 0.17,
            "L5": 0.17,  # constant — RTC always on
        },
    ),
]


BATTERY_CAPACITY_MAH = 3000.0    # assumed — no hardware yet
SUPPLY_VOLTAGE = 3.7             # nominal LiPo
THERMAL_WARNING_THRESHOLD_MW = 3000.0  # >3W sustained likely needs heat management


@dataclass
class LevelEstimate:
    level: str
    total_current_mA: float
    total_power_mW: float
    estimated_runtime_hours: float
    thermal_warning: bool


def estimate_by_level() -> Dict[str, LevelEstimate]:
    """
    Sum current draw per component at each capture level.
    UNVERIFIED PLANNING ESTIMATE — datasheet typical values only.
    """
    estimates = {}
    for level in ["L0", "L1", "L2", "L3", "L4", "L5"]:
        total_mA = sum(
            p.current_mA_by_level[level]
            for p in COMPONENT_PROFILES
        )
        total_mW = total_mA * SUPPLY_VOLTAGE
        runtime_h = BATTERY_CAPACITY_MAH / total_mA if total_mA > 0 else float("inf")
        estimates[level] = LevelEstimate(
            level=level,
            total_current_mA=round(total_mA, 2),
            total_power_mW=round(total_mW, 2),
            estimated_runtime_hours=round(runtime_h, 2),
            thermal_warning=total_mW > THERMAL_WARNING_THRESHOLD_MW,
        )
    return estimates


def print_estimate_table() -> None:
    print("\n=== POWER/THERMAL ESTIMATE (UNVERIFIED PLANNING ESTIMATE) ===")
    print(f"Battery: {BATTERY_CAPACITY_MAH} mAh @ {SUPPLY_VOLTAGE}V nominal")
    print(f"Thermal warning threshold: {THERMAL_WARNING_THRESHOLD_MW} mW\n")
    print(f"{'Level':<6} {'Total mA':>10} {'Total mW':>10} {'Runtime (h)':>12} {'Thermal Warn':>13}")
    print("-" * 56)
    for level, est in estimate_by_level().items():
        warn = "⚠ YES" if est.thermal_warning else "no"
        print(
            f"{level:<6} {est.total_current_mA:>10.1f} {est.total_power_mW:>10.1f} "
            f"{est.estimated_runtime_hours:>12.2f} {warn:>13}"
        )
    print("\nNOTE: All values are datasheet-derived estimates. Validate on real hardware.")
