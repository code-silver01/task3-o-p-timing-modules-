"""
Day 1 acceptance tests — EncryptionDaemon, EncryptedRecord, storage boundary.
All eight spec requirements covered plus extras for Rule 1/2 completeness.
"""

import os
import tempfile
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from mock_crypto.crypto_chip import MockCryptoChip, CryptoChipError
from encryption.keys import DIK, DSK, UPK, ServerTransportKey
from encryption.daemon import EncryptedRecord, EncryptionDaemon
from storage.storage_writer import write_record, StorageError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def chip():
    return MockCryptoChip()

@pytest.fixture
def upk_private():
    return X25519PrivateKey.generate()

@pytest.fixture
def dik(chip):
    return DIK(chip)

@pytest.fixture
def upk(upk_private):
    return UPK.from_private(upk_private)

@pytest.fixture
def daemon(dik, upk):
    return EncryptionDaemon(dik, upk)


# ── Rule 1: write_record rejects non-EncryptedRecord types ────────────────────

def test_write_record_rejects_raw_bytes(tmp_path):
    with pytest.raises(TypeError):
        write_record(b"raw sensor data", str(tmp_path / "out.bin"))

def test_write_record_rejects_string(tmp_path):
    with pytest.raises(TypeError):
        write_record("plaintext string", str(tmp_path / "out.bin"))

def test_write_record_rejects_dict(tmp_path):
    with pytest.raises(TypeError):
        write_record({"data": b"bytes"}, str(tmp_path / "out.bin"))

def test_write_record_rejects_none(tmp_path):
    with pytest.raises(TypeError):
        write_record(None, str(tmp_path / "out.bin"))

def test_write_record_rejects_duck_typed_lookalike(tmp_path):
    class FakeRecord:
        def to_bytes(self):
            return b"i look like an EncryptedRecord"
    with pytest.raises(TypeError):
        write_record(FakeRecord(), str(tmp_path / "out.bin"))


# ── Rule 1: EncryptedRecord cannot be constructed directly ────────────────────

def test_encrypted_record_direct_construction_fails():
    with pytest.raises(RuntimeError, match="Rule 1"):
        EncryptedRecord(
            "not_the_token",
            ephemeral_pub_bytes=b"\x00" * 32,
            outer_nonce=b"\x00" * 12,
            outer_ciphertext=b"\x00" * 48,
            signature=b"\x00" * 64,
            record_date=date.today(),
        )

def test_encrypted_record_none_token_fails():
    with pytest.raises(RuntimeError):
        EncryptedRecord(
            None,
            ephemeral_pub_bytes=b"\x00" * 32,
            outer_nonce=b"\x00" * 12,
            outer_ciphertext=b"\x00" * 48,
            signature=b"\x00" * 64,
            record_date=date.today(),
        )


# ── Rule 2: write_record never overwrites ─────────────────────────────────────

def test_write_record_no_overwrite(daemon, tmp_path):
    record = daemon.encrypt(b"first write")
    path = str(tmp_path / "record.bin")
    write_record(record, path)
    with pytest.raises(StorageError, match="append-only"):
        write_record(daemon.encrypt(b"second write"), path)


# ── Round-trip: encrypt → decrypt recovers exact plaintext ───────────────────

def test_encrypt_decrypt_roundtrip(daemon, upk_private):
    plaintext = b"Hello, Chronis! \x00\xff\x7f sensitive payload"
    record = daemon.encrypt(plaintext)
    recovered = daemon.decrypt(record, upk_private)
    assert recovered == plaintext

def test_encrypt_decrypt_roundtrip_empty(daemon, upk_private):
    record = daemon.encrypt(b"")
    assert daemon.decrypt(record, upk_private) == b""

def test_encrypt_decrypt_roundtrip_large(daemon, upk_private):
    plaintext = os.urandom(64 * 1024)
    record = daemon.encrypt(plaintext)
    assert daemon.decrypt(record, upk_private) == plaintext


# ── Tampered ciphertext fails signature verification ─────────────────────────

def test_tampered_ciphertext_rejected(daemon, upk_private):
    record = daemon.encrypt(b"authentic data")
    serialized = bytearray(record.to_bytes())
    # Flip a byte deep in the outer ciphertext section
    serialized[-50] ^= 0xFF
    tampered = EncryptedRecord.from_bytes(bytes(serialized))
    with pytest.raises(ValueError, match="[Ss]ignature"):
        daemon.decrypt(tampered, upk_private)

def test_tampered_signature_rejected(daemon, upk_private):
    record = daemon.encrypt(b"authentic data")
    serialized = bytearray(record.to_bytes())
    # Flip a byte in the signature section (near the end, before date field)
    serialized[-(4 + 32 + 4 + 10 + 5)] ^= 0x01
    tampered = EncryptedRecord.from_bytes(bytes(serialized))
    with pytest.raises(ValueError):
        daemon.decrypt(tampered, upk_private)


# ── Wrong UPK private key cannot decrypt ─────────────────────────────────────

def test_wrong_upk_private_key_rejected(daemon):
    record = daemon.encrypt(b"secret")
    wrong_private = X25519PrivateKey.generate()
    with pytest.raises(ValueError, match="[Uu][Pp][Kk]|decryption|tampered"):
        daemon.decrypt(record, wrong_private)


# ── DSK: different across dates, identical for same date ─────────────────────

def test_dsk_deterministic_same_date(dik):
    d = date(2024, 6, 15)
    assert DSK.derive(dik, d) == DSK.derive(dik, d)

def test_dsk_different_across_dates(dik):
    d1 = date(2024, 6, 15)
    d2 = date(2024, 6, 16)
    assert DSK.derive(dik, d1) != DSK.derive(dik, d2)

def test_dsk_length_is_32_bytes(dik):
    assert len(DSK.derive(dik, date(2024, 1, 1))) == 32

def test_dsk_different_for_midnight_boundary(dik):
    assert DSK.derive(dik, date(2024, 12, 31)) != DSK.derive(dik, date(2025, 1, 1))


# ── DIK: no public method/attribute exposes raw private key material ──────────

def test_dik_no_public_private_key_exposure(chip):
    dik = DIK(chip)
    public_attrs = [a for a in dir(dik) if not a.startswith("_")]
    for attr_name in public_attrs:
        attr = getattr(dik, attr_name)
        assert not isinstance(attr, Ed25519PrivateKey), (
            f"Public attribute '{attr_name}' exposes an Ed25519PrivateKey — Rule 1 violation."
        )

def test_dik_has_no_private_key_named_attribute(chip):
    dik = DIK(chip)
    for forbidden in ("private_key", "private_bytes", "raw_private", "secret_key"):
        assert not hasattr(dik, forbidden), (
            f"DIK exposes public attribute '{forbidden}' which could leak private key."
        )

def test_dik_public_key_is_public_not_private(chip):
    dik = DIK(chip)
    assert isinstance(dik.public_key, Ed25519PublicKey)
    assert not isinstance(dik.public_key, Ed25519PrivateKey)

def test_dik_sign_returns_bytes_not_key(chip):
    dik = DIK(chip)
    sig = dik.sign(b"message")
    assert isinstance(sig, bytes)
    assert not isinstance(sig, Ed25519PrivateKey)


# ── Serialization round-trip (for HW-3 interop) ──────────────────────────────

def test_to_bytes_from_bytes_roundtrip(daemon, upk_private):
    plaintext = b"HW-3 storage test payload"
    record = daemon.encrypt(plaintext)
    serialized = record.to_bytes()
    restored = EncryptedRecord.from_bytes(serialized)
    recovered = daemon.decrypt(restored, upk_private)
    assert recovered == plaintext

def test_from_bytes_bad_magic_rejected():
    with pytest.raises(ValueError, match="magic"):
        EncryptedRecord.from_bytes(b"INVALID_HEADER" + b"\x00" * 100)


# ── write_record happy path ───────────────────────────────────────────────────

def test_write_record_creates_file(daemon, tmp_path):
    record = daemon.encrypt(b"valid payload")
    path = str(tmp_path / "vault" / "2024-06-15" / "record.bin")
    write_record(record, path)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0

def test_write_record_content_is_valid_encrypted_record(daemon, upk_private, tmp_path):
    plaintext = b"file content check"
    record = daemon.encrypt(plaintext)
    path = str(tmp_path / "record.bin")
    write_record(record, path)
    with open(path, "rb") as f:
        restored = EncryptedRecord.from_bytes(f.read())
    assert daemon.decrypt(restored, upk_private) == plaintext


# ── Mock chip unavailable state (Rule 3) ─────────────────────────────────────

def test_unavailable_chip_raises_explicit_error():
    chip = MockCryptoChip(available=False)
    with pytest.raises(CryptoChipError, match="UNAVAILABLE"):
        DIK(chip)

def test_chip_state_toggle():
    chip = MockCryptoChip(available=False)
    assert not chip.is_available
    chip.set_state(True)
    assert chip.is_available
    dik = DIK(chip)
    assert isinstance(dik.public_key, Ed25519PublicKey)


# ── ServerTransportKey sanity ─────────────────────────────────────────────────

def test_server_transport_key_ephemeral(chip):
    stk1 = ServerTransportKey(chip)
    stk2 = ServerTransportKey(chip)
    pub1 = stk1.public_key.public_bytes_raw() if hasattr(stk1.public_key, 'public_bytes_raw') else \
           stk1.public_key.public_bytes(
               encoding=__import__('cryptography.hazmat.primitives.serialization', fromlist=['Encoding']).Encoding.Raw,
               format=__import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.Raw,
           )
    pub2 = stk2.public_key.public_bytes_raw() if hasattr(stk2.public_key, 'public_bytes_raw') else \
           stk2.public_key.public_bytes(
               encoding=__import__('cryptography.hazmat.primitives.serialization', fromlist=['Encoding']).Encoding.Raw,
               format=__import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.Raw,
           )
    assert pub1 != pub2, "ServerTransportKey must be fresh (ephemeral) each time"
