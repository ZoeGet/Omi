import hashlib
import hmac


DOMAIN = b"OmiPet LAN authentication v1"
KEY_BYTES = 32
NONCE_BYTES = 32
CERT_PIN_BYTES = 32
PROOF_BYTES = 32
DAILY_KEY_INFO = b"OmiPet daily authentication key v1"


def _require_bytes(value: bytes, size: int, name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != size:
        raise ValueError(f"{name} must contain exactly {size} bytes")
    return value


def make_proof(
    key: bytes,
    role: str,
    device_nonce: bytes,
    host_nonce: bytes,
    cert_pin: bytes,
) -> bytes:
    _require_bytes(key, KEY_BYTES, "key")
    if not any(key):
        raise ValueError("key must not be zero")
    if role not in ("host", "device"):
        raise ValueError("invalid role")
    _require_bytes(device_nonce, NONCE_BYTES, "device_nonce")
    _require_bytes(host_nonce, NONCE_BYTES, "host_nonce")
    _require_bytes(cert_pin, CERT_PIN_BYTES, "cert_pin")
    if not any(cert_pin):
        raise ValueError("cert_pin must not be zero")
    role_byte = b"H" if role == "host" else b"D"
    return hmac.new(
        key, DOMAIN + role_byte + device_nonce + host_nonce + cert_pin,
        hashlib.sha256,
    ).digest()


def verify_proof(
    key: bytes,
    role: str,
    device_nonce: bytes,
    host_nonce: bytes,
    cert_pin: bytes,
    received: bytes,
) -> bool:
    if not isinstance(received, bytes) or len(received) != PROOF_BYTES:
        return False
    expected = make_proof(key, role, device_nonce, host_nonce, cert_pin)
    return hmac.compare_digest(expected, received)


def verify_certificate_pin(cert_der: bytes, expected_pin: bytes) -> bool:
    """Check the TLS peer's DER certificate before sending application data."""
    _require_bytes(expected_pin, CERT_PIN_BYTES, "expected_pin")
    if not any(expected_pin) or not isinstance(cert_der, bytes) or not cert_der:
        return False
    return hmac.compare_digest(hashlib.sha256(cert_der).digest(), expected_pin)


def derive_daily_key(shared_secret: bytes, transcript_sha256: bytes,
                     cert_pin: bytes) -> bytes:
    """Derive a credential only after PAKE and pin confirmation succeeds."""
    if not isinstance(shared_secret, bytes) or len(shared_secret) < KEY_BYTES or not any(shared_secret):
        raise ValueError("shared_secret must contain at least 32 nonzero bytes")
    _require_bytes(transcript_sha256, KEY_BYTES, "transcript_sha256")
    _require_bytes(cert_pin, CERT_PIN_BYTES, "cert_pin")
    if not any(transcript_sha256) or not any(cert_pin):
        raise ValueError("transcript digest and certificate pin must not be zero")
    extracted = hmac.new(transcript_sha256, shared_secret, hashlib.sha256).digest()
    return hmac.new(extracted, DAILY_KEY_INFO + cert_pin + b"\x01", hashlib.sha256).digest()
