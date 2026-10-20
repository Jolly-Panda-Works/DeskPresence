"""End-to-end encryption between this PC and each paired phone (used through the relay).

  keys     P-256 (ECDH). The PC has one identity key (pc_identity.pem); each phone sends its
           public key when it pairs.
  derive   HKDF-SHA256(ECDH shared secret, salt = device id, info = INFO) -> 32-byte key
  seal     AES-256-GCM with a random 96-bit nonce; the device id is the associated data
  replay   every sealed request carries a timestamp and is accepted once, within 2 minutes

The relay only ever sees {"d": device id, "n": nonce, "c": ciphertext}.
The Android app implements the same steps (Crypto.kt).
"""
import base64
import hashlib
import json
import os
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import APP_DIR

IDENTITY_PATH = os.path.join(APP_DIR, "pc_identity.pem")
INFO = b"deskpresence pc-phone v1"
MAX_AGE = 120


def b64e(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text):
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_b64(key):
    """Public key as base64url(DER SubjectPublicKeyInfo) - Java's X509EncodedKeySpec format."""
    pub = key.public_key() if hasattr(key, "public_key") else key
    return b64e(pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))


def fingerprint(pub_b64):
    """Short fingerprint shown in QR codes / links so the phone can check the key it receives."""
    return hashlib.sha256(b64d(pub_b64)).hexdigest()[:16]


def load_public(pub_b64):
    key = serialization.load_der_public_key(b64d(pub_b64))
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise ValueError("not a P-256 key")
    return key


def identity(path=None):
    """This PC's long-term identity key (created on first use)."""
    path = path or IDENTITY_PATH
    if not os.path.exists(path):
        key = ec.generate_private_key(ec.SECP256R1())
        with open(path, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def derive(private_key, their_pub_b64, salt, info=INFO):
    shared = private_key.exchange(ec.ECDH(), load_public(their_pub_b64))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode() if isinstance(salt, str) else salt,
                info=info).derive(shared)


def seal(key, obj, aad):
    nonce = os.urandom(12)
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return {"n": b64e(nonce), "c": b64e(AESGCM(key).encrypt(nonce, data, aad.encode()))}


def open_sealed(key, envelope, aad):
    data = AESGCM(key).decrypt(b64d(envelope["n"]), b64d(envelope["c"]), aad.encode())
    return json.loads(data.decode("utf-8"))


def seal_bytes(key, data, aad):
    """Binary frames (webcam): nonce (12 bytes) + ciphertext."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad.encode())


class ReplayGuard:
    """Accepts each sealed request (by nonce) once, and only if its timestamp is recent."""

    def __init__(self, max_age=MAX_AGE):
        self.max_age = max_age
        self._seen = {}
        self._lock = threading.Lock()

    def check(self, nonce, timestamp):
        now = time.time()
        if abs(now - float(timestamp)) > self.max_age:
            return False
        with self._lock:
            for n, at in list(self._seen.items()):
                if now - at > self.max_age * 2:
                    del self._seen[n]
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
        return True
