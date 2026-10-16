import hashlib
import hmac


HEADER = b"OMIC\x01"
KEY_BYTES = 32
PIN_BYTES = 32
RECORD_BYTES = len(HEADER) + KEY_BYTES + PIN_BYTES + 32


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
