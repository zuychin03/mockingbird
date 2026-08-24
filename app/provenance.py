"""What produced a session. Log section 9.14.

A session recorded the model's ALIAS and nothing else, which is not enough to reproduce or
even to interpret it: `mockingbird-llm` says nothing about the quantization, the context
length, or which revision of the prompt and schema the numbers were measured against. Every
figure in the research log is paired with a model and a prompt, and until now that pairing
lived in the log's prose rather than in the session it describes.

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


def code_revision() -> str:
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
    """The prompt and schema the turn was decided against. Changing either invalidates a
    comparison across sessions, and neither is visible in the transcript."""
    blob = contract.SYSTEM + json.dumps(contract.TURN_SCHEMA, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def snapshot(model: dict | None = None) -> dict:
    """`model` is one entry from `provider.loaded_models()`, or None when it is unavailable."""
    m = model or {}
    return {
        "code_revision": code_revision(),
        "contract_hash": contract_hash(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "model_id": m.get("id"),
        "model_path": m.get("path"),
        "quantization": m.get("quantization"),
        "context_length": m.get("loaded_context_length"),
        "model_arch": m.get("arch"),
    }
