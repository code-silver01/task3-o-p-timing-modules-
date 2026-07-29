"""
Key hierarchy for Chronis device.

DIK  — Device Identity Key (Ed25519). Generated once. Private key never exposed publicly.
DSK  — Data Session Key (AES-256). Derived daily from DIK + date. Never stored.
UPK  — User Public Key (X25519). Provisioned at pairing. Safe to store in plaintext.
ServerTransportKey — Ephemeral X25519 per upload session. Never persisted.
"""

from datetime import date

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from mock_crypto.crypto_chip import MockCryptoChip


class DIK:
    """Device Identity Key. Raw private key bytes are never returned by any public method."""

    def __init__(self, chip: MockCryptoChip):
        self._private_key: Ed25519PrivateKey = chip.generate_ed25519_keypair()

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def _private_bytes_raw(self) -> bytes:
        """Internal use only — DSK derivation. Never call from outside this module."""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )


class DSK:
    """Data Session Key. Derived on demand; never stored anywhere."""

    @staticmethod
    def derive(dik: DIK, for_date: date) -> bytes:
        """Derive a 32-byte AES key for the given date. Deterministic per date, unique across dates."""
        ikm = dik._private_bytes_raw()
        date_salt = for_date.isoformat().encode()
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=date_salt,
            info=b"chronis-dsk-v1",
        )
        return hkdf.derive(ikm)


class UPK:
    """User Public Key (X25519). Provisioned at pairing; safe to store in plaintext."""

    def __init__(self, public_key: X25519PublicKey):
        self._public_key = public_key

    @classmethod
    def from_private(cls, private_key: X25519PrivateKey) -> "UPK":
        return cls(private_key.public_key())

    @classmethod
    def from_raw_bytes(cls, raw: bytes) -> "UPK":
        return cls(X25519PublicKey.from_public_bytes(raw))

    @property
    def public_key(self) -> X25519PublicKey:
        return self._public_key

    def public_bytes_raw(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )


class ServerTransportKey:
    """Ephemeral X25519 key pair per upload session. Never persisted."""

    def __init__(self, chip: MockCryptoChip):
        self._private_key: X25519PrivateKey = chip.generate_x25519_keypair()

    @property
    def public_key(self) -> X25519PublicKey:
        return self._private_key.public_key()

    def exchange(self, peer_public: X25519PublicKey) -> bytes:
        return self._private_key.exchange(peer_public)
