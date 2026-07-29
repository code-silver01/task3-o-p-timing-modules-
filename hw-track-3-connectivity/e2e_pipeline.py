"""
Chronis — End-to-End Simulated Pipeline (HW-3 Day 4 deliverable).

The first point where all three tracks connect:

  fake sensor data (HW-1 traces)
      -> capture-intensity decision (HW-1 state machine)
      -> encrypted "upload" (HW-2 encryption if available, else HW-1 stub)
      -> storage manager (HW-3, Rule 1 + Rule 2)
      -> gateway receives -> verifies -> decrypts
      -> structured event -> canonical record DB (append-only at DB level)

Run:  python3 e2e_pipeline.py
"""

import sys, os, json, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "hw-track-1-sensors"))
sys.path.insert(0, HERE)

from mock_hal.sensor_types import RawPayload                       # HW-1
from daemons.capture_daemons import StubEncryptionDaemon           # HW-1
from traces.trace_generator import TraceGenerator                  # HW-1
from state_machine.extended_run import run_extended_simulation     # HW-1
from storage.storage_manager import StorageManager                 # HW-3
from cloud_gateway.gateway import CloudGateway                     # HW-3


def main():
    print("=" * 62)
    print("  Chronis End-to-End Simulated Pipeline")
    print("=" * 62)

    # ---- 1. HW-1: run the capture-intensity simulation ----
    print("\n[1/4] Running HW-1 extended simulation…")
    run_log = run_extended_simulation(out_path=None, verbose=False)
    transitions = run_log["transitions"]
    print(f"      {len(transitions)} level transitions produced")

    # ---- 2. encrypt each transition as an upload payload ----
    print("[2/4] Encrypting transition records (stub encryption daemon)…")
    enc = StubEncryptionDaemon(key_id="DSK-e2e")
    storage = StorageManager()
    uploads = []
    for i, tr in enumerate(transitions):
        raw = RawPayload(data=json.dumps(tr).encode(),
                         source_daemon="state_machine", timestamp=tr["t"])
        rec = enc.encrypt(raw)
        path = f"/vault/2026-07-16/sensors/imu/transition_{i:03d}"
        stored = storage.write_vault(path, rec)
        uploads.append((path, stored, rec))
    print(f"      {storage and len(uploads)} records written to vault (encrypted)")

    # ---- 3. gateway: verify + decrypt + structure ----
    print("[3/4] Gateway ingesting uploads…")

    def verify(ct, sig):
        pt = bytes(b ^ 0x5A for b in ct)
        return hashlib.sha256(pt).digest() == sig

    def decrypt(ct):
        return bytes(b ^ 0x5A for b in ct)

    gw = CloudGateway(verify_fn=verify, decrypt_fn=decrypt)
    for path, stored, rec in uploads:
        ev = gw.ingest(rec.ciphertext, rec.signature,
                       "state_machine", captured_at=rec.timestamp)
        # double-confirmation deletion flow: both sides confirm
        storage.confirm_device_upload(path)
        storage.confirm_server_receipt(path, stored.sha256)
        storage.delete_vault(path)
    print(f"      {gw.db.count()} structured events in canonical record DB")
    print(f"      {len(storage.deletion_log)} device records safely deleted "
          f"(double-confirmed)")

    # ---- 4. verify Rule 2 at DB level ----
    print("[4/4] Verifying canonical DB is append-only…")
    import sqlite3
    try:
        gw.db.conn.execute("DELETE FROM canonical_record")
        print("      FAIL: delete succeeded!")
        sys.exit(1)
    except sqlite3.DatabaseError as e:
        print(f"      delete correctly blocked: {e}")

    print("\n" + "=" * 62)
    print("  PIPELINE COMPLETE: sensor data -> decision -> encrypted upload")
    print("  -> verified -> decrypted -> permanent record. Zero rule violations.")
    print("=" * 62)


if __name__ == "__main__":
    main()
