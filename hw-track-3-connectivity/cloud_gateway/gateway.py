"""
Chronis HW-3 — Cloud Ingestion + Decryption Gateway + Canonical Record DB.

The server-side skeleton:
  1. accepts an uploaded encrypted payload (storage manager output)
  2. verifies it against the encryption scheme's signature
  3. decrypts via server-side transport-key logic
  4. hands a structured, decrypted event to the next pipeline stage
  5. appends to the canonical record database (append-only at the DB level)

For the simulated end-to-end loop, the gateway accepts a verifier/decryptor
pair through its constructor (Rule 4 seam) so HW-2's real daemon or HW-1's
stub can both plug in.
"""

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Optional, List


@dataclass
class StructuredEvent:
    record_id: str
    source_daemon: str
    captured_at: float
    payload: dict
    verified: bool


class GatewayRejection(Exception):
    pass


class CloudGateway:
    def __init__(self,
                 verify_fn: Callable[[bytes, bytes], bool],
                 decrypt_fn: Callable[[bytes], bytes],
                 db_path: str = ":memory:"):
        """
        verify_fn(ciphertext, signature) -> bool
        decrypt_fn(ciphertext) -> plaintext bytes
        """
        self._verify = verify_fn
        self._decrypt = decrypt_fn
        self.db = CanonicalRecordDB(db_path)
        self.rejected: List[str] = []

    def ingest(self, ciphertext: bytes, signature: bytes,
               source_daemon: str, captured_at: float) -> StructuredEvent:
        # 1. verify before anything else
        if not self._verify(ciphertext, signature):
            rid = hashlib.sha256(ciphertext).hexdigest()[:16]
            self.rejected.append(rid)
            raise GatewayRejection(f"signature verification failed for {rid}")

        # 2. decrypt (server-side transport key logic lives inside decrypt_fn)
        plaintext = self._decrypt(ciphertext)

        # 3. structure
        record_id = hashlib.sha256(ciphertext).hexdigest()
        try:
            payload = json.loads(plaintext.decode())
        except (ValueError, UnicodeDecodeError):
            payload = {"raw": plaintext.hex()}

        event = StructuredEvent(
            record_id=record_id,
            source_daemon=source_daemon,
            captured_at=captured_at,
            payload=payload,
            verified=True,
        )

        # 4. append to canonical record — Rule 2 at the DB level
        self.db.append(event)
        return event


class CanonicalRecordDB:
    """
    Append-only permanent record store (SQLite).
    Rule 2 enforced AT THE DATABASE LEVEL:
      - record_id is PRIMARY KEY: INSERT of a duplicate fails
      - a BEFORE UPDATE trigger raises, so UPDATE is impossible
      - a BEFORE DELETE trigger raises, so DELETE is impossible
    """

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS canonical_record (
                record_id     TEXT PRIMARY KEY,
                source_daemon TEXT NOT NULL,
                captured_at   REAL NOT NULL,
                ingested_at   REAL NOT NULL,
                payload_json  TEXT NOT NULL
            )""")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS no_update
            BEFORE UPDATE ON canonical_record
            BEGIN SELECT RAISE(ABORT, 'RULE 2: canonical record is append-only'); END
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS no_delete
            BEFORE DELETE ON canonical_record
            BEGIN SELECT RAISE(ABORT, 'RULE 2: canonical record is append-only'); END
        """)
        self.conn.commit()

    def append(self, event: StructuredEvent):
        self.conn.execute(
            "INSERT INTO canonical_record VALUES (?,?,?,?,?)",
            (event.record_id, event.source_daemon, event.captured_at,
             time.time(), json.dumps(event.payload)))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM canonical_record").fetchone()[0]

    def get(self, record_id: str) -> Optional[tuple]:
        return self.conn.execute(
            "SELECT * FROM canonical_record WHERE record_id=?",
            (record_id,)).fetchone()
