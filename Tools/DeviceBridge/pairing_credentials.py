import hashlib
import hmac
import os
from pathlib import Path
import tempfile
from enum import Enum


HEADER = b"OMIC\x01"
KEY_BYTES = 32
PIN_BYTES = 32
RECORD_BYTES = len(HEADER) + KEY_BYTES + PIN_BYTES + 32


class CredentialState(Enum):
    ABSENT = "absent"
    PRESENT = "present"
    UNKNOWN = "unknown"


def encode_record(daily_key: bytes, cert_pin: bytes) -> bytes:
    if not isinstance(daily_key, bytes) or len(daily_key) != KEY_BYTES or not any(daily_key):
        raise ValueError("daily_key must be 32 nonzero bytes")
    if not isinstance(cert_pin, bytes) or len(cert_pin) != PIN_BYTES or not any(cert_pin):
        raise ValueError("cert_pin must be 32 nonzero bytes")
    payload = HEADER + daily_key + cert_pin
    return payload + hashlib.sha256(payload).digest()


def decode_record(record: bytes) -> tuple[bytes, bytes]:
    if not isinstance(record, bytes) or len(record) != RECORD_BYTES or record[:len(HEADER)] != HEADER:
        raise ValueError("invalid credential record")
    payload = record[:-32]
    if not hmac.compare_digest(hashlib.sha256(payload).digest(), record[-32:]):
        raise ValueError("credential record checksum mismatch")
    key = payload[len(HEADER):len(HEADER) + KEY_BYTES]
    pin = payload[len(HEADER) + KEY_BYTES:]
    if not any(key) or not any(pin):
        raise ValueError("credential record contains zero material")
    return key, pin


def load_file(path: Path) -> tuple[CredentialState, tuple[bytes, bytes] | None]:
    path = Path(path)
    try:
        with path.open("rb") as file:
            record = file.read(RECORD_BYTES + 1)
    except FileNotFoundError:
        return CredentialState.ABSENT, None
    except OSError:
        return CredentialState.UNKNOWN, None
    try:
        return CredentialState.PRESENT, decode_record(record)
    except ValueError:
        return CredentialState.UNKNOWN, None


def save_file_once(path: Path, daily_key: bytes, cert_pin: bytes) -> None:
    """Publish a complete record without replacing an existing credential."""
    path = Path(path)
    record = encode_record(daily_key, cert_pin)
    descriptor, temporary = tempfile.mkstemp(prefix=".omipet-pair-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), 0o600)
            file.write(record)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
