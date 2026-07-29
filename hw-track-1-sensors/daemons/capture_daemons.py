"""
Chronis HW-1 — Camera & Audio Capture Daemons.

Both daemons capture data, timestamp it, and hand it to the encryption daemon
BEFORE anything reaches storage. Rule 1 is enforced structurally: the storage
write path only accepts EncryptedPayload.

The encryption daemon here is a MOCK/STUB — Track HW-2 owns the real one. We
depend only on its interface: encrypt(raw) -> EncryptedPayload. When HW-2's
daemon is ready, we swap the stub for theirs with zero changes to this file.
"""

import time
import hashlib
from dataclasses import dataclass
from typing import Optional, Protocol

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mock_hal.sensor_types import (
    CameraReading, AudioReading, EncryptedPayload, RawPayload, SensorStatus,
)
from mock_hal.mock_storage import MockStorage


class EncryptionInterface(Protocol):
    """The contract we need from Track HW-2's encryption daemon."""
    def encrypt(self, raw: RawPayload) -> EncryptedPayload: ...


class StubEncryptionDaemon:
    """
    Minimal stand-in for HW-2's encryption daemon.
    Real one uses ATECC608B-backed keys; this just wraps + hashes so the
    interface and data flow can be tested today.
    """
    def __init__(self, key_id: str = "DSK-STUB"):
        self.key_id = key_id

    def encrypt(self, raw: RawPayload) -> EncryptedPayload:
        # NOT real crypto — placeholder so the pipeline shape is correct
        ct = bytes(b ^ 0x5A for b in raw.data)  # trivial reversible xor
        sig = hashlib.sha256(raw.data).digest()
        return EncryptedPayload(
            ciphertext=ct,
            signature=sig,
            key_id=self.key_id,
            timestamp=raw.timestamp,
            source_daemon=raw.source_daemon,
        )


class CameraDaemon:
    """Captures frames and routes them through encryption to storage."""

    def __init__(self, encryptor: EncryptionInterface, storage: MockStorage):
        self._encryptor = encryptor
        self._storage = storage
        self.frames_captured = 0
        self.frames_stored = 0

    def capture_and_store(self, reading: CameraReading, date: str = "2026-07-12") -> bool:
        # Rule 3: don't store an unavailable frame as if it were real
        if not reading.is_valid:
            return False

        self.frames_captured += 1

        # serialize frame metadata to bytes (stand-in for pixel payload)
        raw_bytes = (
            f"frame:{reading.frame_id}:{reading.width}x{reading.height}"
            f":{reading.compression_level}:{reading.timestamp}"
        ).encode()

        raw = RawPayload(
            data=raw_bytes,
            source_daemon="camera",
            timestamp=reading.timestamp,
        )

        # Rule 1: MUST encrypt before storage. We physically cannot call
        # storage.write with raw — it would raise. So we encrypt first.
        encrypted = self._encryptor.encrypt(raw)
        path = f"/vault/{date}/camera/frame_{reading.frame_id:06d}"
        self._storage.write(path, encrypted)  # only accepts EncryptedPayload
        self.frames_stored += 1
        return True


class AudioDaemon:
    """
    Captures audio chunks and routes them through encryption to storage.
    Supports the different capture modes the state machine will request.
    """

    # sample rates by capture level
    MODE_RATES = {
        "L0": 8000,    # buffer only, not saved
        "L1": 8000,    # saved
        "L2": 16000,   # continuous
        "L3": 16000,   # full quality
        "L4": 16000,   # dual-boosted
        "L5": 48000,   # lossless
    }

    def __init__(self, encryptor: EncryptionInterface, storage: MockStorage):
        self._encryptor = encryptor
        self._storage = storage
        self.chunks_captured = 0
        self.chunks_stored = 0
        self.chunks_buffered_only = 0  # L0: buffer, never saved
        self._chunk_counter = 0

    def capture_and_store(self, reading: AudioReading, level: str = "L2",
                          date: str = "2026-07-12") -> bool:
        if not reading.is_valid:
            return False

        self.chunks_captured += 1
        self._chunk_counter += 1

        # L0 = ring-buffer only, never written to disk
        if level == "L0":
            self.chunks_buffered_only += 1
            return True  # intentionally NOT stored

        raw_bytes = (
            f"audio:{self._chunk_counter}:{reading.sample_rate_hz}"
            f":{reading.energy_rms}:{reading.timestamp}"
        ).encode()

        raw = RawPayload(
            data=raw_bytes,
            source_daemon="audio",
            timestamp=reading.timestamp,
        )
        encrypted = self._encryptor.encrypt(raw)
        path = f"/vault/{date}/audio/chunk_{self._chunk_counter:06d}"
        self._storage.write(path, encrypted)
        self.chunks_stored += 1
        return True
