"""
EncryptionDaemon — the sole producer of EncryptedRecord objects (Rule 1).

Encryption scheme (two-layer):
  Layer 1: AES-256-GCM with daily DSK
  Layer 2: ECIES wrap with UPK (ephemeral X25519 + AES-256-GCM)
  Signature: Ed25519 with DIK over the outer envelope

EncryptedRecord construction is gated by a module-private factory token.
Any attempt to construct one directly raises RuntimeError before any field is set.
"""

import os
import struct
from datetime import date
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature, InvalidTag

from encryption.keys import DIK, DSK, UPK

# Module-private sentinel — only encrypt() receives this reference.
# Direct EncryptedRecord construction without it raises immediately.
_FACTORY_TOKEN = object()

_MAGIC = b"CHRONIS_ENC_V1\x00"


class EncryptedRecord:
    """
    Sealed encrypted record. Rule 1: only EncryptionDaemon.encrypt() can produce one.
    Attempting direct construction raises RuntimeError at __init__ before any data is stored.
    """

    def __init__(
        self,
        _token,
        *,
        ephemeral_pub_bytes: bytes,
        outer_nonce: bytes,
        outer_ciphertext: bytes,
        signature: bytes,
        record_date: date,
    ):
        if _token is not _FACTORY_TOKEN:
            raise RuntimeError(
                "EncryptedRecord cannot be constructed directly. "
                "Use EncryptionDaemon.encrypt() — Rule 1 structural enforcement."
            )
        self._ephemeral_pub_bytes = ephemeral_pub_bytes
        self._outer_nonce = outer_nonce
        self._outer_ciphertext = outer_ciphertext
        self._signature = signature
        self._record_date = record_date

    @property
    def record_date(self) -> date:
        return self._record_date

    @property
    def ephemeral_pub_bytes(self) -> bytes:
        return self._ephemeral_pub_bytes

    @property
    def outer_nonce(self) -> bytes:
        return self._outer_nonce

    @property
    def outer_ciphertext(self) -> bytes:
        return self._outer_ciphertext

    @property
    def signature(self) -> bytes:
        return self._signature

    def to_bytes(self) -> bytes:
        """Serialized wire format for HW-3 storage manager to write as-is."""
        date_bytes = self._record_date.isoformat().encode()
        return _MAGIC + b"".join([
            _pack(self._ephemeral_pub_bytes),
            _pack(self._outer_nonce),
            _pack(self._outer_ciphertext),
            _pack(self._signature),
            _pack(date_bytes),
        ])

    @classmethod
    def from_bytes(cls, data: bytes) -> "EncryptedRecord":
        """Deserialize a record previously written by to_bytes(). Used by HW-3 and for testing."""
        if not data.startswith(_MAGIC):
            raise ValueError("Invalid EncryptedRecord magic header.")
        pos = len(_MAGIC)
        ephemeral_pub_bytes, pos = _unpack(data, pos)
        outer_nonce, pos = _unpack(data, pos)
        outer_ciphertext, pos = _unpack(data, pos)
        signature, pos = _unpack(data, pos)
        date_bytes, pos = _unpack(data, pos)
        record_date = date.fromisoformat(date_bytes.decode())
        return cls(
            _FACTORY_TOKEN,
            ephemeral_pub_bytes=ephemeral_pub_bytes,
            outer_nonce=outer_nonce,
            outer_ciphertext=outer_ciphertext,
            signature=signature,
            record_date=record_date,
        )


def _pack(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _unpack(data: bytes, pos: int) -> tuple[bytes, int]:
    length = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4
    return data[pos:pos + length], pos + length


class EncryptionDaemon:
    """
    The only entity that produces EncryptedRecords.
    Holds DIK for signing and DSK derivation; holds UPK for outer wrap.
    """

    def __init__(self, dik: DIK, upk: UPK):
        self._dik = dik
        self._upk = upk

    def encrypt(self, plaintext: bytes, for_date: Optional[date] = None) -> EncryptedRecord:
        """Encrypt plaintext bytes. This is the only path that produces an EncryptedRecord."""
        if not isinstance(plaintext, bytes):
            raise TypeError(f"plaintext must be bytes, got {type(plaintext).__name__}")

        record_date = for_date or date.today()

        # Layer 1: AES-256-GCM with daily DSK
        dsk = DSK.derive(self._dik, record_date)
        inner_nonce = os.urandom(12)
        inner_ciphertext = AESGCM(dsk).encrypt(inner_nonce, plaintext, None)
        inner_payload = inner_nonce + inner_ciphertext

        # Layer 2: ECIES wrap with UPK
        ephemeral_private = X25519PrivateKey.generate()
        ephemeral_pub_bytes = ephemeral_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        shared_secret = ephemeral_private.exchange(self._upk.public_key)
        wrap_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=ephemeral_pub_bytes,
            info=b"chronis-upk-wrap-v1",
        ).derive(shared_secret)

        outer_nonce = os.urandom(12)
        outer_ciphertext = AESGCM(wrap_key).encrypt(outer_nonce, inner_payload, None)

        # Sign outer envelope with DIK for tamper-evidence
        signing_body = ephemeral_pub_bytes + outer_nonce + outer_ciphertext
        signature = self._dik.sign(signing_body)

        return EncryptedRecord(
            _FACTORY_TOKEN,
            ephemeral_pub_bytes=ephemeral_pub_bytes,
            outer_nonce=outer_nonce,
            outer_ciphertext=outer_ciphertext,
            signature=signature,
            record_date=record_date,
        )

    def decrypt(self, record: EncryptedRecord, upk_private_key: X25519PrivateKey) -> bytes:
        """
        Decrypt an EncryptedRecord. Requires UPK private key (off-device holder).
        Verifies DIK signature first — tampered records are rejected before decryption.
        """
        if not isinstance(record, EncryptedRecord):
            raise TypeError(f"Expected EncryptedRecord, got {type(record).__name__}")

        signing_body = record.ephemeral_pub_bytes + record.outer_nonce + record.outer_ciphertext
        try:
            self._dik.public_key.verify(record.signature, signing_body)
        except InvalidSignature:
            raise ValueError("Signature verification failed — record may be tampered.")

        ephemeral_pub = X25519PublicKey.from_public_bytes(record.ephemeral_pub_bytes)
        shared_secret = upk_private_key.exchange(ephemeral_pub)
        wrap_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=record.ephemeral_pub_bytes,
            info=b"chronis-upk-wrap-v1",
        ).derive(shared_secret)

        try:
            inner_payload = AESGCM(wrap_key).decrypt(record.outer_nonce, record.outer_ciphertext, None)
        except InvalidTag:
            raise ValueError("UPK decryption failed — wrong private key or tampered ciphertext.")

        inner_nonce = inner_payload[:12]
        inner_ciphertext = inner_payload[12:]
        dsk = DSK.derive(self._dik, record.record_date)

        try:
            plaintext = AESGCM(dsk).decrypt(inner_nonce, inner_ciphertext, None)
        except InvalidTag:
            raise ValueError("DSK decryption failed — data integrity check failed.")

        return plaintext
