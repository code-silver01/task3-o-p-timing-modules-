"""
Chronis HW-3 — BLE Daemon (the real on-device logic).

Implements:
  - Handlers for all 8 GATT services reading REAL (mocked) device state
  - Numeric Comparison pairing (6-digit code, both sides must confirm match)
  - Auto-reconnect: bonded phone reconnects within 10 seconds of a drop
  - Beacon mode: name + battery %, once per second, NEVER user data
  - Range monitoring: disconnect >30 min while worn -> flagged event,
    surfaced to phone on next reconnect

Rule 4: device state is read through a DeviceStateProvider interface — this
daemon never reaches into other daemons' internals.
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Callable, Protocol


# ---------------- Rule 4 seam: state comes through an interface ----------------

class DeviceStateProvider(Protocol):
    """What the BLE daemon is allowed to know about the rest of the device."""
    def battery_percent(self) -> int: ...
    def power_state(self) -> str: ...
    def firmware_version(self) -> str: ...
    def sync_status(self) -> str: ...
    def storage_used_mb(self) -> int: ...
    def storage_total_mb(self) -> int: ...
    def capture_level(self) -> int: ...
    def operating_mode(self) -> str: ...
    def camera_killswitch(self) -> bool: ...
    def audio_paused(self) -> bool: ...
    def camera_fps(self) -> float: ...
    def is_worn(self) -> bool: ...


@dataclass
class MockDeviceState:
    """Test stand-in wired to HW-1/HW-2 values during integration."""
    _battery: int = 87
    _power: str = "Full Active"
    _fw: str = "0.4.1"
    _sync: str = "idle"
    _used: int = 1210
    _total: int = 512000
    _level: int = 1
    _mode: str = "normal"
    _kill: bool = False
    _paused: bool = False
    _fps: float = 0.5
    _worn: bool = True

    def battery_percent(self): return self._battery
    def power_state(self): return self._power
    def firmware_version(self): return self._fw
    def sync_status(self): return self._sync
    def storage_used_mb(self): return self._used
    def storage_total_mb(self): return self._total
    def capture_level(self): return self._level
    def operating_mode(self): return self._mode
    def camera_killswitch(self): return self._kill
    def audio_paused(self): return self._paused
    def camera_fps(self): return self._fps
    def is_worn(self): return self._worn


# ---------------- pairing ----------------

class PairingState(Enum):
    IDLE = "idle"
    AWAITING_CONFIRM = "awaiting_confirm"
    PAIRED = "paired"
    FAILED = "failed"


class NumericComparisonPairing:
    """
    Numeric Comparison (not 'Just Works'): both the device and phone display
    the same 6-digit code; pairing completes only on an explicit confirmed
    match. A mismatch fails safely — this defeats passive eavesdropping.
    """

    def __init__(self):
        self.state = PairingState.IDLE
        self.device_code: Optional[str] = None
        self.bonded_phone: Optional[str] = None

    def begin(self, phone_id: str) -> str:
        self.device_code = f"{random.SystemRandom().randint(0, 999999):06d}"
        self._phone_candidate = phone_id
        self.state = PairingState.AWAITING_CONFIRM
        return self.device_code   # displayed on device screen AND phone

    def confirm(self, phone_displayed_code: str, user_confirms: bool) -> bool:
        if self.state != PairingState.AWAITING_CONFIRM:
            return False
        if not user_confirms or phone_displayed_code != self.device_code:
            self.state = PairingState.FAILED
            self.device_code = None
            return False
        self.state = PairingState.PAIRED
        self.bonded_phone = self._phone_candidate
        self.device_code = None
        return True


# ---------------- the daemon ----------------

@dataclass
class Alert:
    kind: str
    detail: str
    timestamp: float


class BLEDaemon:
    RECONNECT_WINDOW_S = 10.0
    RANGE_FLAG_AFTER_S = 30 * 60.0
    BEACON_INTERVAL_S = 1.0

    ALERT_KINDS = {
        "sync_complete", "low_battery", "storage_warning", "sensor_disconnect",
        "tamper_detected", "new_insight_ready", "double_tap_moment_marked",
        "mode_change_confirmed", "boot_complete",
    }

    def __init__(self, state: DeviceStateProvider):
        self._state = state
        self.pairing = NumericComparisonPairing()
        self.connected = False
        self._disconnect_at: Optional[float] = None
        self._pending_alerts: List[Alert] = []
        self._flagged_events: List[dict] = []
        self._annotations: List[dict] = []
        self._config: Dict[str, str] = {}
        self._led = {"color": "auto", "pattern": "static", "brightness": 100}
        self._display_message: Optional[str] = None
        self._audio_pause_until: Optional[float] = None
        self.beacon_frames: List[dict] = []

    # ---------- GATT service 1: Device Info ----------
    def svc_device_info(self) -> dict:
        s = self._state
        return {
            "battery_percent": s.battery_percent(),
            "power_state": s.power_state(),
            "firmware_version": s.firmware_version(),
            "sync_status": s.sync_status(),
            "storage_used_mb": s.storage_used_mb(),
            "storage_available_mb": s.storage_total_mb() - s.storage_used_mb(),
            "capture_level": s.capture_level(),
            "operating_mode": s.operating_mode(),
            "camera_killswitch": s.camera_killswitch(),
            "audio_paused": s.audio_paused(),
        }

    # ---------- GATT service 2: LED Control ----------
    def svc_led_control(self, color=None, pattern=None, brightness=None) -> dict:
        if pattern is not None:
            if pattern not in ("static", "pulse", "chase", "flash", "custom"):
                raise ValueError(f"bad pattern: {pattern}")
            self._led["pattern"] = pattern
        if color is not None:
            self._led["color"] = color
        if brightness is not None:
            self._led["brightness"] = max(0, min(100, int(brightness)))
        return dict(self._led)

    # ---------- GATT service 3: Display Control ----------
    def svc_display_message(self, message: str) -> bool:
        self._display_message = message[:64]   # short message only
        return True

    # ---------- GATT service 4: Camera Control (kill-switch read-only) ----------
    def svc_camera_control(self) -> dict:
        return {
            "killswitch": self._state.camera_killswitch(),   # READ-ONLY over BLE
            "current_fps": self._state.camera_fps(),
        }

    # ---------- GATT service 5: Audio Control ----------
    def svc_audio_pause(self, now: float, duration_s: float) -> dict:
        self._audio_pause_until = now + duration_s
        return {"paused": True, "until": self._audio_pause_until}

    def svc_audio_resume(self) -> dict:
        self._audio_pause_until = None
        return {"paused": False}

    # ---------- GATT service 6: Config (WiFi write-only) ----------
    def svc_config_write(self, key: str, value: str):
        self._config[key] = value

    def svc_config_read(self, key: str) -> Optional[str]:
        if key == "wifi_credentials":
            return None   # WRITE-ONLY — never readable back over BLE
        return self._config.get(key)

    # ---------- GATT service 7: Alerts (device -> phone only) ----------
    def push_alert(self, kind: str, detail: str, timestamp: float):
        if kind not in self.ALERT_KINDS:
            raise ValueError(f"unknown alert kind: {kind}")
        self._pending_alerts.append(Alert(kind, detail, timestamp))

    def drain_alerts(self) -> List[Alert]:
        out, self._pending_alerts = self._pending_alerts, []
        return out

    # ---------- GATT service 8: Annotation ----------
    def svc_annotation(self, note: str, tap_timestamp: float) -> dict:
        entry = {"note": note, "anchored_to": tap_timestamp}
        self._annotations.append(entry)
        return entry

    # ---------- connection lifecycle ----------
    def on_connect(self, now: float, phone_id: str) -> List[Alert]:
        if self.pairing.bonded_phone != phone_id:
            raise PermissionError("phone not bonded — pair first")
        self.connected = True
        self._disconnect_at = None
        # surface any flagged events accumulated while disconnected
        for ev in self._flagged_events:
            self.push_alert("sensor_disconnect", f"range event: {ev}", now)
        self._flagged_events.clear()
        return self.drain_alerts()

    def on_disconnect(self, now: float):
        self.connected = False
        self._disconnect_at = now

    def tick(self, now: float) -> Optional[dict]:
        """Call periodically. Handles reconnect window, range flag, beacon."""
        if self.connected:
            return None

        # auto-reconnect within 10 s of a drop (simulated as success signal)
        if (self._disconnect_at is not None
                and now - self._disconnect_at <= self.RECONNECT_WINDOW_S
                and self.pairing.bonded_phone):
            self.connected = True
            self._disconnect_at = None
            return {"event": "auto_reconnected"}

        # range monitoring: >30 min disconnected while worn -> flag once
        if (self._disconnect_at is not None
                and now - self._disconnect_at > self.RANGE_FLAG_AFTER_S
                and self._state.is_worn()
                and not self._flagged_events):
            self._flagged_events.append(
                {"disconnected_at": self._disconnect_at, "flagged_at": now})

        # beacon: name + battery only — NEVER user data
        frame = {"name": "Chronis", "battery": self._state.battery_percent()}
        self.beacon_frames.append(frame)
        return {"event": "beacon", "frame": frame}
