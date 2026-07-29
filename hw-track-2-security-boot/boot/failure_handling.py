"""
Per-component failure behavior table (Day 2 spec, exact rows implemented verbatim).
HALT rows and degraded-continue rows share NO code path — kept structurally separate.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class BootOutcome(Enum):
    HALT = "HALT"
    DEGRADED = "DEGRADED"
    NORMAL = "NORMAL"


@dataclass
class FailureResult:
    outcome: BootOutcome
    component: str
    message: str
    notify_phone: bool
    log: bool


# ── HALT handlers (security chip, storage) ───────────────────────────────────
# These must NEVER share a code path with the continue rows below.

def handle_security_chip_failure(notify_fn: Callable[[str], None]) -> FailureResult:
    """SYSTEM HALT. Never boot without encryption available."""
    msg = "SYSTEM HALT: security chip failed — encryption unavailable, cannot boot."
    notify_fn(msg)
    return FailureResult(
        outcome=BootOutcome.HALT,
        component="security_chip",
        message=msg,
        notify_phone=True,
        log=True,
    )


def handle_storage_failure(notify_fn: Callable[[str], None]) -> FailureResult:
    """SYSTEM HALT. No data capture allowed without storage."""
    msg = "SYSTEM HALT: storage failed — no data capture possible, cannot boot."
    notify_fn(msg)
    return FailureResult(
        outcome=BootOutcome.HALT,
        component="storage",
        message=msg,
        notify_phone=True,
        log=True,
    )


# ── Degraded-continue handlers ────────────────────────────────────────────────

def handle_motion_sensor_failure(notify_fn: Callable[[str], None]) -> FailureResult:
    """Degraded boot — audio-only inputs for decision-making."""
    msg = "Degraded boot: motion sensor failed — audio-only inputs active."
    notify_fn(msg)
    return FailureResult(
        outcome=BootOutcome.DEGRADED,
        component="motion_sensor",
        message=msg,
        notify_phone=True,
        log=True,
    )


def handle_heart_rate_sensor_failure(notify_fn: Callable[[str], None]) -> FailureResult:
    """Degraded boot — heart-rate-based features disabled."""
    msg = "Degraded boot: heart-rate sensor failed — HR features disabled."
    notify_fn(msg)
    return FailureResult(
        outcome=BootOutcome.DEGRADED,
        component="heart_rate_sensor",
        message=msg,
        notify_phone=True,
        log=True,
    )


def handle_camera_failure(notify_fn: Callable[[str], None]) -> FailureResult:
    """Audio-only boot — continue without video."""
    msg = "Degraded boot: camera failed — audio-only mode active."
    notify_fn(msg)
    return FailureResult(
        outcome=BootOutcome.DEGRADED,
        component="camera",
        message=msg,
        notify_phone=True,
        log=True,
    )


# ── Normal-continue handlers ──────────────────────────────────────────────────

def handle_display_failure(log_fn: Callable[[str], None]) -> FailureResult:
    """Continue normally. Status LED takes over. No phone notification."""
    msg = "Display failed — status LED is now primary indicator."
    log_fn(msg)
    return FailureResult(
        outcome=BootOutcome.NORMAL,
        component="display",
        message=msg,
        notify_phone=False,
        log=True,
    )


def handle_status_led_failure(log_fn: Callable[[str], None]) -> FailureResult:
    """Continue normally. Log the failure only."""
    msg = "Status LED failed — logged, no further action."
    log_fn(msg)
    return FailureResult(
        outcome=BootOutcome.NORMAL,
        component="status_led",
        message=msg,
        notify_phone=False,
        log=True,
    )


def handle_bluetooth_failure(log_fn: Callable[[str], None], display_fn: Callable[[str], None]) -> FailureResult:
    """Continue normally. Fall back to WiFi. Log it. Display shows an icon."""
    msg = "Bluetooth failed — falling back to WiFi. Display icon shown."
    log_fn(msg)
    display_fn("BT_FAIL_ICON")
    return FailureResult(
        outcome=BootOutcome.NORMAL,
        component="bluetooth",
        message=msg,
        notify_phone=False,
        log=True,
    )


def handle_wifi_failure(log_fn: Callable[[str], None]) -> FailureResult:
    """Continue normally. Store data locally until connectivity returns."""
    msg = "WiFi failed — storing data locally until connectivity returns."
    log_fn(msg)
    return FailureResult(
        outcome=BootOutcome.NORMAL,
        component="wifi",
        message=msg,
        notify_phone=False,
        log=True,
    )
