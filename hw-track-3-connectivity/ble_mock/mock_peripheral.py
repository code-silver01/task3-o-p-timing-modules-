"""
Chronis HW-3 — Mock Bluetooth Peripheral.

A fixed-response stand-in for the device, exposing the same 8 services so the
companion phone-app team can build the "connect to my Chronis" flow with no
hardware. This is NOT the device's BLE daemon (that's ble_daemon/ — real
logic, real state); this returns canned but schema-correct responses.
"""

FIXED_RESPONSES = {
    "device_info": {
        "battery_percent": 76, "power_state": "Full Active",
        "firmware_version": "0.4.1", "sync_status": "idle",
        "storage_used_mb": 1210, "storage_available_mb": 510790,
        "capture_level": 2, "operating_mode": "normal",
        "camera_killswitch": False, "audio_paused": False,
    },
    "led_control": {"color": "auto", "pattern": "static", "brightness": 100},
    "display_control": {"accepted": True},
    "camera_control": {"killswitch": False, "current_fps": 1.0},
    "audio_control": {"paused": False},
    "config": {"accepted": True},
    "alerts": [],
    "annotation": {"accepted": True},
}


class MockBLEPeripheral:
    """Pairs with anything, answers every service with canned data."""

    SERVICES = list(FIXED_RESPONSES.keys())

    def __init__(self):
        self.paired_phones = []

    def pair(self, phone_id: str) -> bool:
        self.paired_phones.append(phone_id)
        return True

    def query(self, service: str, payload=None) -> dict:
        if service not in FIXED_RESPONSES:
            raise KeyError(f"unknown service: {service}")
        resp = FIXED_RESPONSES[service]
        return dict(resp) if isinstance(resp, dict) else list(resp)
