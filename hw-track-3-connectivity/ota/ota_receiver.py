"""
Chronis HW-3 — OTA (Over-The-Air) Update Receiver.

Flow: download to temp partition -> verify SHA-256 -> verify RSA-2048
signature -> mark pending -> boot new firmware -> 3 consecutive failed boots
triggers automatic rollback to the previous working version.

Failure paths tested explicitly:
  - Bad signature  -> update rejected, phone alerted
  - 3 failed boots -> automatic revert
"""

import hashlib
from dataclasses import dataclass, field
from typing import Optional, List, Callable

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature


@dataclass
class FirmwareImage:
    version: str
    data: bytes
    sha256: str
    signature: bytes


class OTAError(Exception):
    pass


def generate_test_keypair():
    """RSA-2048 test key pair (the real signing key lives on the build
    server, never on-device)."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def sign_firmware(private_key, data: bytes) -> bytes:
    return private_key.sign(
        data,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )


class OTAReceiver:
    """
    Manages firmware slots:
      active   — currently running version
      previous — last known-good (rollback target)
      pending  — downloaded to temp partition, not yet active
    """

    MAX_FAILED_BOOTS = 3

    def __init__(self, public_key, phone_alert: Optional[Callable[[str], None]] = None):
        self._pub = public_key
        self._alert = phone_alert or (lambda msg: None)
        self.active: Optional[FirmwareImage] = None
        self.previous: Optional[FirmwareImage] = None
        self.pending: Optional[FirmwareImage] = None       # temp partition
        self.failed_boot_count = 0
        self.event_log: List[str] = []

    def _log(self, msg: str):
        self.event_log.append(msg)

    # ---------------- download + verification ----------------

    def receive_update(self, version: str, data: bytes,
                       claimed_sha256: str, signature: bytes) -> bool:
        """Download into the temp partition and verify. Never touches active."""
        # 1. Integrity: SHA-256
        actual = hashlib.sha256(data).hexdigest()
        if actual != claimed_sha256:
            self._log(f"REJECTED {version}: SHA-256 mismatch")
            self._alert(f"OTA update {version} rejected: integrity check failed")
            return False

        # 2. Authenticity: RSA-2048 signature over the image bytes
        try:
            self._pub.verify(
                signature, data,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
        except InvalidSignature:
            self._log(f"REJECTED {version}: bad signature")
            self._alert(f"OTA update {version} rejected: signature invalid")
            return False

        self.pending = FirmwareImage(version=version, data=data,
                                     sha256=actual, signature=signature)
        self._log(f"STAGED {version} in temp partition")
        return True

    # ---------------- activation + rollback ----------------

    def activate_pending(self):
        """Swap pending into active; keep the old active as rollback target."""
        if self.pending is None:
            raise OTAError("no pending firmware to activate")
        self.previous = self.active
        self.active = self.pending
        self.pending = None
        self.failed_boot_count = 0
        self._log(f"ACTIVATED {self.active.version} "
                  f"(rollback target: {self.previous.version if self.previous else 'none'})")

    def report_boot(self, success: bool) -> Optional[str]:
        """
        Called by the boot manager after each boot attempt on the active image.
        Returns the version rolled back to, if a rollback occurred.
        """
        if success:
            self.failed_boot_count = 0
            return None

        self.failed_boot_count += 1
        self._log(f"boot failure {self.failed_boot_count}/{self.MAX_FAILED_BOOTS} "
                  f"on {self.active.version if self.active else '?'}")

        if self.failed_boot_count >= self.MAX_FAILED_BOOTS:
            if self.previous is None:
                self._log("ROLLBACK IMPOSSIBLE: no previous firmware")
                self._alert("CRITICAL: firmware failing and no rollback target")
                return None
            bad = self.active
            self.active = self.previous
            self.previous = None       # a rollback target is single-use
            self.failed_boot_count = 0
            self._log(f"ROLLED BACK from {bad.version} to {self.active.version}")
            self._alert(f"Device auto-reverted to firmware {self.active.version}")
            return self.active.version
        return None
