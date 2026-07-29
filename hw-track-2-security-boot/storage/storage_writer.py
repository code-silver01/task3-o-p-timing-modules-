"""
Rule 1 storage boundary.
write_record() is the only function that writes to disk and it accepts ONLY EncryptedRecord.
Rule 2 spot-check: refuses to overwrite any existing path.
"""

import os

from encryption.daemon import EncryptedRecord


class StorageError(Exception):
    pass


def write_record(record: EncryptedRecord, path: str) -> None:
    """
    Write an EncryptedRecord to disk.

    Rule 1: Rejects raw bytes, strings, dicts, and any non-EncryptedRecord type.
    Rule 2: Refuses to overwrite an existing file — append-only first-line-of-defense.
    """
    if not isinstance(record, EncryptedRecord):
        raise TypeError(
            f"write_record requires an EncryptedRecord instance, got {type(record).__name__}. "
            "Rule 1: no unencrypted data may reach storage."
        )

    if os.path.exists(path):
        raise StorageError(
            f"Record already exists at '{path}'. "
            "Rule 2: records are append-only — overwriting is not permitted."
        )

    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with open(path, "wb") as f:
        f.write(record.to_bytes())
