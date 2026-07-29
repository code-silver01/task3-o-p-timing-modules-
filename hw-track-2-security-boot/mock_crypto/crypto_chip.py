"""
Mock ATECC608B crypto chip API surface.
TEMPORARY STAND-IN: When hardware arrives, swap this file for a real I2C driver.
Nothing above this layer should need to change — only this file.
"""

import os
from enum import Enum

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.exceptions import InvalidSignature


class ChipState(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"  # Rule 3: explicit failure, never a silent zero


class CryptoChipError(Exception):
    pass


class MockCryptoChip:
    """Mock of ATECC608B. Same API surface the real I2C driver will expose."""

    def __init__(self, available: bool = True):
        self._state = ChipState.AVAILABLE if available else ChipState.UNAVAILABLE

    def _require_available(self):
        if self._state == ChipState.UNAVAILABLE:
            raise CryptoChipError(
                "Crypto chip UNAVAILABLE — Rule 3: explicit failure, not a zero substitute."
            )

    def set_state(self, available: bool) -> None:
        self._state = ChipState.AVAILABLE if available else ChipState.UNAVAILABLE

    @property
    def is_available(self) -> bool:
        return self._state == ChipState.AVAILABLE

    def generate_ed25519_keypair(self) -> Ed25519PrivateKey:
        self._require_available()
        return Ed25519PrivateKey.generate()

    def generate_x25519_keypair(self) -> X25519PrivateKey:
        self._require_available()
        return X25519PrivateKey.generate()

    def sign(self, private_key: Ed25519PrivateKey, message: bytes) -> bytes:
        self._require_available()
        return private_key.sign(message)

    def verify(self, public_key: Ed25519PublicKey, signature: bytes, message: bytes) -> bool:
        """Returns False on bad signature. Raises CryptoChipError if unavailable."""
        self._require_available()
        try:
            public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    def x25519_exchange(self, private_key: X25519PrivateKey, peer_public: X25519PublicKey) -> bytes:
        self._require_available()
        return private_key.exchange(peer_public)

    def get_random_bytes(self, n: int) -> bytes:
        """Random bytes from chip RNG. Unavailable is explicit, never a zero substitute."""
        self._require_available()
        return os.urandom(n)
