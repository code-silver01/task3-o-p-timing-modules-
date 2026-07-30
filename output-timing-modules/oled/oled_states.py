"""
Chronis Task 3, Team B, Day 2 — Display States & Priority Order.

Fact-check / assumption flag, stated honestly: the spec's sentence about
priority order is oddly worded ("highest real-world priority first in
testing even though it's last in the spec's enumerated list"). The plain
reading I'm going with: the enumerated list itself IS already highest-to-
lowest priority — tamper alert (listed first) is the most urgent thing
this device can show, idle face (listed last) is the default fallback
when nothing else needs attention. If that reading is wrong, the fix is
a one-line reorder of PRIORITY_ORDER below, nothing structural changes.
"""

from enum import Enum


class DisplayState(Enum):
    TAMPER_ALERT = "tamper_alert"
    BLE_PAIRING_QR = "ble_pairing_qr"
    CAMERA_KILLED_ICON = "camera_killed_icon"
    CHARGING_FILL = "charging_fill"
    LOW_BATTERY_ICON = "low_battery_icon"
    INSIGHT_NOTIFICATION = "insight_notification"
    CAPTURE_ACTIVE_INDICATOR = "capture_active_indicator"
    IDLE_FACE = "idle_face"


# Index 0 = highest priority. Whatever's the first ACTIVE state found
# walking this list top to bottom is what gets shown.
PRIORITY_ORDER = [
    DisplayState.TAMPER_ALERT,
    DisplayState.BLE_PAIRING_QR,
    DisplayState.CAMERA_KILLED_ICON,
    DisplayState.CHARGING_FILL,
    DisplayState.LOW_BATTERY_ICON,
    DisplayState.INSIGHT_NOTIFICATION,
    DisplayState.CAPTURE_ACTIVE_INDICATOR,
    DisplayState.IDLE_FACE,
]

# These three need to be visible at full brightness even if the device is
# currently in low-power ambient mode: a "full-screen warning" can't be a
# tiny ambient dot, a QR code needs real brightness to be scannable by a
# phone camera, and the camera-killed icon exists specifically to be
# noticed. This isn't stated word-for-word in the spec — it's the logical
# consequence of what these three states ARE — flagged here rather than
# silently assumed.
FORCE_FULL_BRIGHTNESS = {
    DisplayState.TAMPER_ALERT,
    DisplayState.BLE_PAIRING_QR,
    DisplayState.CAMERA_KILLED_ICON,
}

INSIGHT_MAX_CHARS = 60
INSIGHT_AUTO_DISMISS_SECONDS = 10
TAP_TO_WAKE_SECONDS = 15
AMBIENT_BRIGHTNESS_CDM2 = 5.0
AMBIENT_DOT_CYCLE_SECONDS = 5
AMBIENT_DOT_STATES = ["battery", "sync", "capture"]