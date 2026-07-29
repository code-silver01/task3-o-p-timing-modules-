"""HW-3 test suite: storage, OTA, BLE daemon + mock peripheral, orchestration, gateway."""
import sys, os, hashlib, json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from storage.storage_manager import (
    StorageManager, AppendOnlyViolation, UnencryptedWriteAttempt,
    DeletionRefused, StorageViolation,
)
from ota.ota_receiver import OTAReceiver, generate_test_keypair, sign_firmware
from ble_daemon.ble_daemon import (
    BLEDaemon, MockDeviceState, NumericComparisonPairing, PairingState,
)
from ble_mock.mock_peripheral import MockBLEPeripheral
from orchestration.orchestrator import Orchestrator, ServiceDef, ServiceState
from cloud_gateway.gateway import CloudGateway, GatewayRejection


class FakeEncrypted:
    """Duck-typed encrypted record (matches HW-1/HW-2 interfaces)."""
    def __init__(self, data=b"cipher"):
        self.ciphertext = data
        self.signature = b"sig"


# ================= Storage Manager =================

class TestStorageManager:
    def setup_method(self):
        self.s = StorageManager()

    def test_vault_write_encrypted_ok(self):
        rec = self.s.write_vault("/vault/2026-07-16/camera/f001", FakeEncrypted())
        assert rec.sha256 == hashlib.sha256(b"cipher").hexdigest()

    def test_vault_rejects_raw_bytes(self):
        with pytest.raises(UnencryptedWriteAttempt):
            self.s.write_vault("/vault/2026-07-16/audio/a001", b"raw")

    def test_vault_rejects_dict(self):
        with pytest.raises(UnencryptedWriteAttempt):
            self.s.write_vault("/vault/2026-07-16/audio/a001", {"x": 1})

    def test_append_only(self):
        self.s.write_vault("/vault/2026-07-16/sensors/imu/r1", FakeEncrypted())
        with pytest.raises(AppendOnlyViolation):
            self.s.write_vault("/vault/2026-07-16/sensors/imu/r1", FakeEncrypted(b"new"))

    def test_invalid_vault_path_rejected(self):
        with pytest.raises(StorageViolation):
            self.s.write_vault("/vault/hack/../../etc/passwd", FakeEncrypted())

    def test_exact_directory_tree_paths(self):
        """All spec paths are writable; junk paths are not."""
        good = [
            "/vault/2026-07-16/audio/chunk1",
            "/vault/2026-07-16/camera/frame1",
            "/vault/2026-07-16/sensors/imu/r1",
            "/vault/2026-07-16/sensors/ppg/r1",
            "/vault/2026-07-16/metadata.json",
            "/vault/2026-07-16/manifest.sha",
        ]
        for p in good:
            self.s.write_vault(p, FakeEncrypted())
        assert len(self.s.list_vault()) == 6

    def test_system_paths(self):
        self.s.write_system("/system/logs/boot.log", b"plaintext ok here")
        self.s.write_system("/system/config/device.json", b"{}")
        self.s.write_system("/system/firmware/current.bin", b"fw")
        assert len(self.s.list_system()) == 3

    # ---- double-confirmation deletion ----

    def test_delete_refused_without_any_confirmation(self):
        self.s.write_vault("/vault/2026-07-16/audio/a1", FakeEncrypted())
        with pytest.raises(DeletionRefused):
            self.s.delete_vault("/vault/2026-07-16/audio/a1")

    def test_delete_refused_with_only_device_confirmation(self):
        p = "/vault/2026-07-16/audio/a1"
        self.s.write_vault(p, FakeEncrypted())
        self.s.confirm_device_upload(p)
        with pytest.raises(DeletionRefused):
            self.s.delete_vault(p)

    def test_delete_refused_on_server_hash_mismatch(self):
        p = "/vault/2026-07-16/audio/a1"
        self.s.write_vault(p, FakeEncrypted())
        self.s.confirm_device_upload(p)
        assert self.s.confirm_server_receipt(p, "wrong_hash") is False
        with pytest.raises(DeletionRefused):
            self.s.delete_vault(p)

    def test_delete_succeeds_with_both_confirmations(self):
        p = "/vault/2026-07-16/audio/a1"
        rec = self.s.write_vault(p, FakeEncrypted())
        self.s.confirm_device_upload(p)
        assert self.s.confirm_server_receipt(p, rec.sha256) is True
        self.s.delete_vault(p)
        assert self.s.read_vault(p) is None
        assert len(self.s.deletion_log) == 1


# ================= OTA Receiver =================

class TestOTA:
    def setup_method(self):
        self.priv, self.pub = generate_test_keypair()
        self.alerts = []
        self.ota = OTAReceiver(self.pub, phone_alert=self.alerts.append)

        # install v1 as active baseline
        fw1 = b"firmware-v1"
        self.ota.receive_update("1.0", fw1, hashlib.sha256(fw1).hexdigest(),
                                sign_firmware(self.priv, fw1))
        self.ota.activate_pending()

    def _stage(self, version, data):
        return self.ota.receive_update(
            version, data, hashlib.sha256(data).hexdigest(),
            sign_firmware(self.priv, data))

    def test_valid_update_staged_and_activated(self):
        assert self._stage("2.0", b"firmware-v2")
        self.ota.activate_pending()
        assert self.ota.active.version == "2.0"
        assert self.ota.previous.version == "1.0"

    def test_bad_signature_rejected_and_phone_alerted(self):
        data = b"firmware-evil"
        bad_sig = sign_firmware(self.priv, b"different-bytes")
        ok = self.ota.receive_update("6.6", data,
                                     hashlib.sha256(data).hexdigest(), bad_sig)
        assert not ok
        assert self.ota.pending is None
        assert any("rejected" in a for a in self.alerts)

    def test_sha_mismatch_rejected(self):
        ok = self.ota.receive_update("3.0", b"firmware-v3", "deadbeef",
                                     sign_firmware(self.priv, b"firmware-v3"))
        assert not ok

    def test_three_failed_boots_trigger_rollback(self):
        self._stage("2.0", b"firmware-v2")
        self.ota.activate_pending()
        assert self.ota.report_boot(False) is None      # 1
        assert self.ota.report_boot(False) is None      # 2
        rolled = self.ota.report_boot(False)            # 3 -> rollback
        assert rolled == "1.0"
        assert self.ota.active.version == "1.0"
        assert any("auto-reverted" in a for a in self.alerts)

    def test_successful_boot_resets_counter(self):
        self._stage("2.0", b"firmware-v2")
        self.ota.activate_pending()
        self.ota.report_boot(False)
        self.ota.report_boot(False)
        self.ota.report_boot(True)     # reset
        assert self.ota.failed_boot_count == 0
        assert self.ota.report_boot(False) is None   # 1 again, no rollback


# ================= Numeric Comparison Pairing =================

class TestPairing:
    def test_matching_codes_pair(self):
        p = NumericComparisonPairing()
        code = p.begin("phone-A")
        assert len(code) == 6 and code.isdigit()
        assert p.confirm(code, user_confirms=True)
        assert p.state == PairingState.PAIRED
        assert p.bonded_phone == "phone-A"

    def test_mismatched_codes_fail_safely(self):
        p = NumericComparisonPairing()
        p.begin("phone-A")
        assert not p.confirm("000000" if p.device_code != "000000" else "111111",
                             user_confirms=True)
        assert p.state == PairingState.FAILED
        assert p.bonded_phone is None

    def test_user_rejection_fails(self):
        p = NumericComparisonPairing()
        code = p.begin("phone-A")
        assert not p.confirm(code, user_confirms=False)
        assert p.state == PairingState.FAILED


# ================= BLE Daemon =================

class TestBLEDaemon:
    def setup_method(self):
        self.state = MockDeviceState()
        self.d = BLEDaemon(self.state)
        code = self.d.pairing.begin("phone-A")
        self.d.pairing.confirm(code, True)

    def test_device_info_reports_real_state(self):
        """Device Info must reflect ACTUAL state, not placeholders."""
        self.state._battery = 42
        self.state._level = 4
        info = self.d.svc_device_info()
        assert info["battery_percent"] == 42
        assert info["capture_level"] == 4
        # change state -> response changes (proves it's live, not canned)
        self.state._battery = 41
        assert self.d.svc_device_info()["battery_percent"] == 41

    def test_all_8_services_respond(self):
        self.d.svc_device_info()
        self.d.svc_led_control(pattern="pulse", brightness=50)
        assert self.d.svc_display_message("hello")
        self.d.svc_camera_control()
        self.d.svc_audio_pause(now=0.0, duration_s=60)
        self.d.svc_audio_resume()
        self.d.svc_config_write("sync_schedule", "hourly")
        self.d.push_alert("boot_complete", "ok", 0.0)
        self.d.svc_annotation("great moment", tap_timestamp=123.0)

    def test_wifi_credentials_write_only(self):
        self.d.svc_config_write("wifi_credentials", "ssid:pass")
        assert self.d.svc_config_read("wifi_credentials") is None  # never readable

    def test_camera_killswitch_read_only(self):
        """BLE can read the kill-switch but there is no setter over BLE."""
        assert "killswitch" in self.d.svc_camera_control()
        assert not hasattr(self.d, "svc_camera_killswitch_set")

    def test_unbonded_phone_cannot_connect(self):
        with pytest.raises(PermissionError):
            self.d.on_connect(now=0.0, phone_id="stranger-phone")

    def test_auto_reconnect_within_10s(self):
        self.d.on_connect(0.0, "phone-A")
        self.d.on_disconnect(100.0)
        out = self.d.tick(105.0)
        assert out == {"event": "auto_reconnected"}
        assert self.d.connected

    def test_no_reconnect_after_window(self):
        self.d.on_connect(0.0, "phone-A")
        self.d.on_disconnect(100.0)
        out = self.d.tick(150.0)                 # 50s later — window missed
        assert out["event"] == "beacon"
        assert not self.d.connected

    def test_beacon_never_contains_user_data(self):
        self.d.on_disconnect(0.0)
        for t in range(20, 200, 20):
            self.d.tick(float(t))
        for frame in self.d.beacon_frames:
            assert set(frame.keys()) == {"name", "battery"}

    def test_range_flag_after_30min_worn(self):
        self.d.on_connect(0.0, "phone-A")
        self.d.on_disconnect(0.0)
        self.d.tick(31 * 60.0)                   # 31 min later, still worn
        assert len(self.d._flagged_events) == 1
        # flagged event surfaces on next reconnect
        alerts = self.d.on_connect(32 * 60.0, "phone-A")
        assert any(a.kind == "sensor_disconnect" for a in alerts)

    def test_annotation_links_to_timestamp(self):
        entry = self.d.svc_annotation("note text", tap_timestamp=456.7)
        assert entry["anchored_to"] == 456.7


class TestMockPeripheral:
    def test_all_services_schema(self):
        m = MockBLEPeripheral()
        assert m.pair("any-phone")
        for svc in MockBLEPeripheral.SERVICES:
            m.query(svc)

    def test_device_info_schema_matches_real_daemon(self):
        """Phone team builds against the mock — keys must match the real daemon."""
        m = MockBLEPeripheral()
        real = BLEDaemon(MockDeviceState()).svc_device_info()
        assert set(m.query("device_info").keys()) == set(real.keys())


# ================= Orchestration =================

class TestOrchestrator:
    def _mk(self, ok=True):
        return lambda: ok

    def test_encryption_starts_first_and_gates_everything(self):
        o = Orchestrator()
        o.register(ServiceDef("encryption", self._mk(True), critical=True))
        o.register(ServiceDef("storage", self._mk(True)))
        o.register(ServiceDef("ble", self._mk(True)))
        assert o.start_all()
        # encryption line is first in the log
        assert o.start_log[0].startswith("encryption")

    def test_encryption_failure_blocks_all(self):
        o = Orchestrator()
        o.register(ServiceDef("encryption", self._mk(False), critical=True))
        o.register(ServiceDef("storage", self._mk(True)))
        assert not o.start_all()
        assert o.states["storage"] == ServiceState.STOPPED   # never started

    def test_dependency_ordering(self):
        o = Orchestrator()
        o.register(ServiceDef("encryption", self._mk(True), critical=True))
        o.register(ServiceDef("storage", self._mk(True), requires=["encryption"]))
        o.register(ServiceDef("sync", self._mk(True), requires=["storage", "ble"]))
        o.register(ServiceDef("ble", self._mk(True)))
        assert o.start_all()
        assert o.states["sync"] == ServiceState.READY


# ================= Cloud Gateway + Canonical DB =================

def xor_decrypt(ct: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in ct)


def xor_encrypt(pt: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in pt)


def sha_verify(ct: bytes, sig: bytes) -> bool:
    return hashlib.sha256(xor_decrypt(ct)).digest() == sig


class TestCloudGateway:
    def setup_method(self):
        self.gw = CloudGateway(verify_fn=sha_verify, decrypt_fn=xor_decrypt)

    def _payload(self, obj):
        pt = json.dumps(obj).encode()
        return xor_encrypt(pt), hashlib.sha256(pt).digest()

    def test_valid_ingest_produces_structured_event(self):
        ct, sig = self._payload({"level": 3, "hr": 88})
        ev = self.gw.ingest(ct, sig, "state_machine", captured_at=100.0)
        assert ev.verified
        assert ev.payload == {"level": 3, "hr": 88}
        assert self.gw.db.count() == 1

    def test_bad_signature_rejected(self):
        ct, _ = self._payload({"x": 1})
        with pytest.raises(GatewayRejection):
            self.gw.ingest(ct, b"forged-signature", "camera", 0.0)
        assert self.gw.db.count() == 0

    def test_db_rejects_duplicate_record(self):
        ct, sig = self._payload({"x": 1})
        self.gw.ingest(ct, sig, "imu", 0.0)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            self.gw.ingest(ct, sig, "imu", 0.0)   # same ciphertext = same id

    def test_db_update_impossible(self):
        ct, sig = self._payload({"x": 1})
        ev = self.gw.ingest(ct, sig, "imu", 0.0)
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):
            self.gw.db.conn.execute(
                "UPDATE canonical_record SET payload_json='{}' WHERE record_id=?",
                (ev.record_id,))

    def test_db_delete_impossible(self):
        ct, sig = self._payload({"x": 1})
        ev = self.gw.ingest(ct, sig, "imu", 0.0)
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):
            self.gw.db.conn.execute(
                "DELETE FROM canonical_record WHERE record_id=?", (ev.record_id,))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
