"""
Boot sequence manager (Day 2).
Exact order from spec — do not reorder:
  power_rails → security_chip → clock_sync → storage → motion_sensor →
  heart_rate_sensor → camera → display → status_led → bluetooth → wifi
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from boot.failure_handling import (
    BootOutcome,
    FailureResult,
    handle_security_chip_failure,
    handle_storage_failure,
    handle_motion_sensor_failure,
    handle_heart_rate_sensor_failure,
    handle_camera_failure,
    handle_display_failure,
    handle_status_led_failure,
    handle_bluetooth_failure,
    handle_wifi_failure,
)


class ComponentStatus(Enum):
    OK = "OK"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"  # Rule 3: explicit, never a silent zero


class DeviceState(Enum):
    BOOTING = "BOOTING"
    READY = "READY"
    HALTED = "HALTED"
    DEGRADED = "DEGRADED"


@dataclass
class BootReport:
    device_state: DeviceState
    component_results: List[FailureResult] = field(default_factory=list)
    halt_reason: Optional[str] = None
    phone_notifications: List[str] = field(default_factory=list)
    log_entries: List[str] = field(default_factory=list)
    display_events: List[str] = field(default_factory=list)


# Canonical boot order — do not change without updating spec
BOOT_ORDER = [
    "power_rails",
    "security_chip",
    "clock_sync",
    "storage",
    "motion_sensor",
    "heart_rate_sensor",
    "camera",
    "display",
    "status_led",
    "bluetooth",
    "wifi",
]


class BootSequenceManager:
    """
    Runs the boot sequence in spec order.
    Queries each component via the mock HAL; delegates failures to failure_handling.py.
    """

    def __init__(self, hal: Dict[str, Callable[[], ComponentStatus]]):
        """
        hal: mapping of component_name → callable that returns ComponentStatus.
        Components not in the map default to OK (for power_rails, clock_sync
        which have no independent failure mode in the spec table).
        """
        self._hal = hal

    def run(self) -> BootReport:
        report = BootReport(device_state=DeviceState.BOOTING)
        has_degraded = False

        def notify(msg: str):
            report.phone_notifications.append(msg)

        def log(msg: str):
            report.log_entries.append(msg)

        def display(event: str):
            report.display_events.append(event)

        for component in BOOT_ORDER:
            status = self._hal.get(component, lambda: ComponentStatus.OK)()

            if status == ComponentStatus.OK:
                log(f"{component}: OK")
                continue

            # status is FAIL or UNAVAILABLE — route to the correct handler
            result = self._dispatch_failure(component, notify, log, display)
            report.component_results.append(result)

            if result.outcome == BootOutcome.HALT:
                report.device_state = DeviceState.HALTED
                report.halt_reason = result.message
                return report  # Stop immediately — never continue after HALT

            if result.outcome == BootOutcome.DEGRADED:
                has_degraded = True

        if report.device_state == DeviceState.BOOTING:
            report.device_state = DeviceState.DEGRADED if has_degraded else DeviceState.READY

        return report

    def _dispatch_failure(
        self,
        component: str,
        notify_fn: Callable,
        log_fn: Callable,
        display_fn: Callable,
    ) -> FailureResult:
        dispatch = {
            "security_chip": lambda: handle_security_chip_failure(notify_fn),
            "storage": lambda: handle_storage_failure(notify_fn),
            "motion_sensor": lambda: handle_motion_sensor_failure(notify_fn),
            "heart_rate_sensor": lambda: handle_heart_rate_sensor_failure(notify_fn),
            "camera": lambda: handle_camera_failure(notify_fn),
            "display": lambda: handle_display_failure(log_fn),
            "status_led": lambda: handle_status_led_failure(log_fn),
            "bluetooth": lambda: handle_bluetooth_failure(log_fn, display_fn),
            "wifi": lambda: handle_wifi_failure(log_fn),
        }
        handler = dispatch.get(component)
        if handler is None:
            # power_rails / clock_sync failures not in the spec table — treat as HALT
            msg = f"SYSTEM HALT: critical pre-boot component '{component}' failed."
            notify_fn(msg)
            return FailureResult(
                outcome=BootOutcome.HALT,
                component=component,
                message=msg,
                notify_phone=True,
                log=True,
            )
        return handler()
