"""
Chronis HW-1 — Mock Storage Layer.

Rule 1 enforced: write() ONLY accepts EncryptedPayload. Passing RawPayload
or raw bytes raises TypeError — structurally impossible to bypass encryption.

Rule 2 enforced: append-only. Once a record is written, it can never be
overwritten, edited, or deleted.
"""

from typing import Dict, List
from .sensor_types import EncryptedPayload, RawPayload


class AppendOnlyViolation(Exception):
    """Raised when code attempts to overwrite or delete an existing record."""
    pass


class EncryptionBypassAttempt(Exception):
    """Raised when code attempts to write unencrypted data to storage."""
    pass


class MockStorage:
    """
    Mock filesystem enforcing Rules 1 and 2.
    
    In production, this maps to:
      /vault/YYYY-MM-DD/audio/
      /vault/YYYY-MM-DD/camera/
      /vault/YYYY-MM-DD/sensors/imu/
      /vault/YYYY-MM-DD/sensors/ppg/
      /vault/YYYY-MM-DD/metadata.json
    """

    def __init__(self):
        self._records: Dict[str, EncryptedPayload] = {}
        self._write_log: List[dict] = []

    def write(self, path: str, payload) -> bool:
        """
        Write encrypted data to storage.

        RULE 1: Only EncryptedPayload is accepted.
        Anything else raises EncryptionBypassAttempt.

        RULE 2: If path already exists, raises AppendOnlyViolation.
        """
        # Rule 1: structural enforcement — type check
        if isinstance(payload, RawPayload):
            raise EncryptionBypassAttempt(
                f"RULE 1 VIOLATION: daemon '{payload.source_daemon}' attempted to "
                f"write raw unencrypted data to '{path}'. "
                f"All data must pass through the encryption daemon first."
            )

        if not isinstance(payload, EncryptedPayload):
            raise EncryptionBypassAttempt(
                f"RULE 1 VIOLATION: write() received {type(payload).__name__} "
                f"instead of EncryptedPayload. Only encrypted data can be stored."
            )

        # Rule 2: append-only — no overwrites
        if path in self._records:
            raise AppendOnlyViolation(
                f"RULE 2 VIOLATION: attempted to overwrite existing record at '{path}'. "
                f"The canonical record is append-only — no edits, no overwrites."
            )

        self._records[path] = payload
        self._write_log.append({
            'path': path,
            'timestamp': payload.timestamp,
            'source': payload.source_daemon,
            'key_id': payload.key_id,
        })
        return True

    def read(self, path: str):
        """Read an encrypted record."""
        if path not in self._records:
            return None
        return self._records[path]

    def exists(self, path: str) -> bool:
        return path in self._records

    def list_records(self) -> List[str]:
        return list(self._records.keys())

    def delete(self, path: str):
        """
        ALWAYS FAILS. Rule 2: no deletion allowed in this sprint.
        """
        raise AppendOnlyViolation(
            f"RULE 2 VIOLATION: attempted to delete record at '{path}'. "
            f"Deletion is not permitted in this sprint's scope."
        )

    @property
    def write_count(self) -> int:
        return len(self._records)

    @property
    def log(self) -> List[dict]:
        return list(self._write_log)
