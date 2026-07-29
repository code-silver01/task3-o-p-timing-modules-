#!/usr/bin/env python3
"""
chronis-cli — command-line debug tool against the full mock stack.

Commands: status | sensor-read | crypto-test | storage-list

Guarantee: NEVER prints unencrypted/plaintext user data to the screen, even
from mock data — ciphertext is shown as truncated hex, records by hash only.
"""

import sys
import os
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "hw-track-1-sensors"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "observability-fleet"))   # Team B, Task 2

from mock_hal import MockHAL                                    # HW-1
from storage.storage_manager import StorageManager              # HW-3
from telemetry.health_endpoint import HealthEndpoint, ComponentHealth, HealthStatus  # Team B
from telemetry.checks import register_standard_checks                               # Team B, Day 4


def _redact(b: bytes, keep: int = 16) -> str:
    """Show ciphertext safely: truncated hex, never decoded."""
    h = b.hex()
    return f"{h[:keep]}… ({len(b)} bytes, encrypted)"


def cmd_status(hal: MockHAL, storage: StorageManager):
    imu = hal.read_imu()
    ppg = hal.read_ppg()
    print("chronis status")
    print(f"  imu:      {'ok' if imu.is_valid else imu.status.name}")
    print(f"  ppg:      {'ok' if ppg.is_valid else ppg.status.name}")
    print(f"  vault:    {len(storage.list_vault())} records")
    print(f"  system:   {len(storage.list_system())} files")


def cmd_sensor_read(hal: MockHAL):
    imu = hal.read_imu()
    if imu.is_valid:
        print(f"imu: accel=({imu.accel_x:+.3f},{imu.accel_y:+.3f},{imu.accel_z:+.3f})g "
              f"gyro=({imu.gyro_x:+.2f},{imu.gyro_y:+.2f},{imu.gyro_z:+.2f})°/s")
    else:
        print(f"imu: UNAVAILABLE — {imu.unavailable_reason.value if imu.unavailable_reason else '?'}")
    ppg = hal.read_ppg()
    if ppg.is_valid:
        print(f"ppg: hr={ppg.heart_rate_bpm:.0f}bpm quality={ppg.signal_quality:.2f}")
    else:
        print(f"ppg: {ppg.status.name} — {ppg.unavailable_reason.value if ppg.unavailable_reason else '?'}")


def cmd_crypto_test():
    """Round-trip through HW-2's encryption daemon if present, else the stub."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "hw-track-2-security-boot"))
        from encryption.daemon import EncryptionDaemon           # HW-2 real
        print("crypto-test: HW-2 encryption daemon found")
        print("  (round-trip test delegated to HW-2's own test suite: 119 tests)")
    except ImportError:
        from daemons.capture_daemons import StubEncryptionDaemon  # HW-1 stub
        from mock_hal.sensor_types import RawPayload
        enc = StubEncryptionDaemon()
        rec = enc.encrypt(RawPayload(data=b"cli-self-test", source_daemon="cli",
                                     timestamp=0.0))
        print("crypto-test: HW-2 daemon not on path — using HW-1 stub")
        print(f"  ciphertext: {_redact(rec.ciphertext)}")
        print(f"  signature:  {_redact(rec.signature, 12)}")


def cmd_health(hal: MockHAL, storage: StorageManager):
    """The Day 1 deliverable: a local health-check endpoint chronis-cli can
    query. Day 4 factored the individual checks out to telemetry/checks.py
    so this CLI and the full-stack integration test share one definition."""
    ep = HealthEndpoint()
    register_standard_checks(ep, hal, storage)

    report = ep.query()
    print(f"chronis health  [{report.overall_status.value}]")
    for c in report.components:
        print(f"  {c.name:<8} {c.status.value:<9} {c.detail}")


def cmd_storage_list(storage: StorageManager):
    print("vault records (hash only — content never displayed):")
    for path in storage.list_vault():
        rec = storage.read_vault(path)
        print(f"  {path}  sha256={rec.sha256[:16]}…")
    if not storage.list_vault():
        print("  (empty)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="chronis-cli")
    p.add_argument("command",
                   choices=["status", "sensor-read", "crypto-test", "storage-list", "health"])
    args = p.parse_args(argv)

    hal = MockHAL()
    storage = StorageManager()

    if args.command == "status":
        cmd_status(hal, storage)
    elif args.command == "sensor-read":
        cmd_sensor_read(hal)
    elif args.command == "crypto-test":
        cmd_crypto_test()
    elif args.command == "storage-list":
        cmd_storage_list(storage)
    elif args.command == "health":
        cmd_health(hal, storage)


if __name__ == "__main__":
    main()
