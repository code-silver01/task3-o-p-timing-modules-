"""
Chronis HW-3 — Storage Manager.

Implements the exact encrypted directory tree from the sprint doc:
    /vault/YYYY-MM-DD/audio/
    /vault/YYYY-MM-DD/camera/
    /vault/YYYY-MM-DD/sensors/imu/
    /vault/YYYY-MM-DD/sensors/ppg/
    /vault/YYYY-MM-DD/metadata.json
    /vault/YYYY-MM-DD/manifest.sha
    /system/logs/      <- plaintext only, never user data
    /system/config/    <- device config, public key, sync state
    /system/firmware/  <- current + previous version (for rollback)

Rules enforced:
  - Rule 1: vault writes only accept EncryptedRecord-shaped payloads
  - Rule 2: append-only — overwrite of any vault record fails
  - Double-confirmation deletion: device-confirmed upload AND server hash
    match required before anything is removed. No exceptions.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, List


class StorageViolation(Exception):
    pass


class AppendOnlyViolation(StorageViolation):
    pass


class UnencryptedWriteAttempt(StorageViolation):
    pass


class DeletionRefused(StorageViolation):
    pass


@dataclass
class StoredRecord:
    path: str
    ciphertext: bytes
    signature: bytes
    sha256: str
    uploaded_device_confirmed: bool = False
    uploaded_server_confirmed: bool = False


VAULT_RE = re.compile(
    r"^/vault/\d{4}-\d{2}-\d{2}/(audio|camera|sensors/imu|sensors/ppg)/[\w\-.]+$"
)
VAULT_META_RE = re.compile(r"^/vault/\d{4}-\d{2}-\d{2}/(metadata\.json|manifest\.sha)$")
SYSTEM_RE = re.compile(r"^/system/(logs|config|firmware)/[\w\-./]+$")


def _looks_encrypted(payload) -> bool:
    """
    Rule 1 gate: payload must expose ciphertext + signature bytes.
    Accepts HW-2's EncryptedRecord or HW-1's EncryptedPayload (duck-typed
    across track boundaries — Rule 4: interface, not internals).
    """
    return (hasattr(payload, "ciphertext") and isinstance(payload.ciphertext, bytes)
            and hasattr(payload, "signature") and isinstance(payload.signature, bytes))


class StorageManager:
    """Mock filesystem implementing the vault contract."""

    def __init__(self):
        self._vault: Dict[str, StoredRecord] = {}
        self._system: Dict[str, bytes] = {}
        self._deletion_log: List[dict] = []

    # ---------------- vault (user data — encrypted only) ----------------

    def write_vault(self, path: str, payload) -> StoredRecord:
        if not (VAULT_RE.match(path) or VAULT_META_RE.match(path)):
            raise StorageViolation(f"invalid vault path: {path}")
        if not _looks_encrypted(payload):
            raise UnencryptedWriteAttempt(
                f"RULE 1: vault write at '{path}' requires an encrypted record "
                f"(got {type(payload).__name__})")
        if path in self._vault:
            raise AppendOnlyViolation(
                f"RULE 2: '{path}' already exists — records are append-only")

        rec = StoredRecord(
            path=path,
            ciphertext=payload.ciphertext,
            signature=payload.signature,
            sha256=hashlib.sha256(payload.ciphertext).hexdigest(),
        )
        self._vault[path] = rec
        return rec

    def read_vault(self, path: str) -> Optional[StoredRecord]:
        return self._vault.get(path)

    def list_vault(self, prefix: str = "/vault/") -> List[str]:
        return sorted(p for p in self._vault if p.startswith(prefix))

    # ------------- double-confirmation deletion flow -------------

    def confirm_device_upload(self, path: str):
        rec = self._vault.get(path)
        if rec is None:
            raise StorageViolation(f"no such record: {path}")
        rec.uploaded_device_confirmed = True

    def confirm_server_receipt(self, path: str, server_sha256: str) -> bool:
        """Server independently confirms via cryptographic hash match."""
        rec = self._vault.get(path)
        if rec is None:
            raise StorageViolation(f"no such record: {path}")
        if server_sha256 != rec.sha256:
            rec.uploaded_server_confirmed = False
            return False
        rec.uploaded_server_confirmed = True
        return True

    def delete_vault(self, path: str):
        """
        Deletion succeeds ONLY when BOTH confirmations are present.
        Never silently delete unconfirmed data — no exceptions.
        """
        rec = self._vault.get(path)
        if rec is None:
            raise StorageViolation(f"no such record: {path}")
        if not rec.uploaded_device_confirmed:
            raise DeletionRefused(
                f"refusing to delete '{path}': device has not confirmed upload")
        if not rec.uploaded_server_confirmed:
            raise DeletionRefused(
                f"refusing to delete '{path}': server has not confirmed matching copy")
        del self._vault[path]
        self._deletion_log.append({"path": path, "sha256": rec.sha256})

    # ---------------- system area (plaintext allowed, never user data) ----------------

    def write_system(self, path: str, data: bytes):
        if not SYSTEM_RE.match(path):
            raise StorageViolation(f"invalid system path: {path}")
        # firmware keeps current + previous only
        self._system[path] = data

    def read_system(self, path: str) -> Optional[bytes]:
        return self._system.get(path)

    def list_system(self) -> List[str]:
        return sorted(self._system)

    @property
    def deletion_log(self) -> List[dict]:
        return list(self._deletion_log)
