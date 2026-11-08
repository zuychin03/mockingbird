"""What produced a session. Log section 9.14.

The exact runtime id, quantisation, context length, prompt and code revision are stored
with every session. An instance nickname alone is insufficient to reproduce a result.

Cheap and best-effort by construction. Nothing here may raise: provenance that can abort an
interview is worse than provenance that records "unknown".
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from . import contract

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "BUILD"     # written by installer/build.py: an install has no git to ask


def code_revision() -> str:
    if BUILD.is_file():
        return BUILD.read_text(encoding="utf-8").strip() or "unknown"
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        rev = out.stdout.strip()
    except Exception:
        return "unknown"
    if not rev:
        return "unknown"
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5)
        if dirty.stdout.strip():
            rev += "-dirty"
    except Exception:
        pass
    return rev


def contract_hash() -> str:
    """Every prompt and schema that can contribute model-written spoken output."""
    blob = "".join((
        contract.SYSTEM,
        json.dumps(contract.TURN_SCHEMA, sort_keys=True),
        contract.SPEECH_SYSTEM,
        json.dumps(contract.SPEECH_SCHEMA, sort_keys=True),
    ))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def snapshot(model: dict | None = None, provider: dict | None = None) -> dict:
    """`model` is what `provider.served_model()` returned, or None when it is unavailable or
    the interview runs on a cloud model; `provider` is `provider.describe()` of what served it."""
    m = model or {}
    return {
        "provider": provider,
        "code_revision": code_revision(),
        "contract_hash": contract_hash(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "model_id": m.get("id"),
        "model_path": m.get("path"),
        "quantization": m.get("quantization"),
        "context_length": m.get("loaded_context_length"),
        "model_runtime": m.get("runtime"),
    }
