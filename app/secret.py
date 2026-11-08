"""The cloud provider's API key, encrypted with Windows DPAPI (V1.1_PLAN D8).

DPAPI ties the ciphertext to this Windows login, the same protection Credential Manager gives,
without a dependency in a hash-locked installer. Nothing here returns the key to a caller that
renders anything: the API sees `status()` only.

Where it lives: beside the app in `secrets`, which uninstalling removes and upgrading keeps.
A checkout inside OneDrive would upload that folder, so a source run there keeps the key under
%LOCALAPPDATA% instead. `MOCKINGBIRD_API_KEY` overrides the stored key for source runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "provider.key"
# Not a secret: it only keeps this blob from being decrypted as some other app's DPAPI data.
ENTROPY = b"mockingbird-provider-key-v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretError(RuntimeError):
    pass


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def path() -> Path:
    override = os.environ.get("MOCKINGBIRD_KEY_FILE")
    if override:
        return Path(override)
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        folder = os.environ.get(var)
        if folder and _inside(ROOT, Path(folder)):
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
            return Path(base) / "Mockingbird" / NAME
    return ROOT / "secrets" / NAME


def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise SecretError("storing a key needs Windows; set MOCKINGBIRD_API_KEY instead")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    data_in, keep_in = blob(data)
    entropy, keep_entropy = blob(ENTROPY)
    out = Blob()
    if not fn(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise SecretError("Windows could not %s the key (error %d)"
                          % ("encrypt" if protect else "decrypt", ctypes.GetLastError()))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def save(key: str) -> None:
    key = (key or "").strip()
    if not key or len(key) > 512 or any(c.isspace() for c in key):
        raise SecretError("that does not look like an API key")
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(_dpapi(key.encode("utf-8"), protect=True))
    os.replace(tmp, p)


def load() -> str | None:
    env = os.environ.get("MOCKINGBIRD_API_KEY")
    if env:
        return env.strip()
    p = path()
    if not p.exists():
        return None
    try:
        return _dpapi(p.read_bytes(), protect=False).decode("utf-8")
    except (OSError, SecretError, UnicodeDecodeError):
        return None


def clear() -> None:
    try:
        path().unlink()
    except FileNotFoundError:
        pass


def status() -> dict:
    """What the interface may show about the key: whether one is set, and its last four."""
    source = "environment" if os.environ.get("MOCKINGBIRD_API_KEY") else "stored"
    key = load()
    return {"set": bool(key), "last4": key[-4:] if key and len(key) >= 12 else None,
            "source": source if key else None}
