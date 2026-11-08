"""What the person chose on the Settings page (V1.1_PLAN P2).

No file means 1.0's behaviour exactly: the local server, nothing sent anywhere. The file lives
in `data`, which an upgrade keeps, and never holds the API key (`app/secret.py` does).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "settings.json"

# The acknowledgement cloud mode asks for. Its version is stored with the answer, and any
# change to what is sent, or to this wording, bumps it so the person is asked again.
ACK_VERSION = 1
ACK_TEXT = ("In cloud mode the provider you choose receives the job description you paste, "
            "every interview question, and the text of every answer, to read them. Your "
            "recordings stay on this computer. The provider's own terms decide what it keeps.")

MODES = ("local", "cloud")
# setup_done: first run chose a mode (P3). hearing: answers are spoken, which in cloud mode on a
# computer without a capable GPU means LFM3 listening on the CPU. hearing_speed: what the
# first-run check measured there, or None where the voice runs on a GPU.
# voice: a `config/voices.json` id, or None for the default that suits the hardware (P4).
DEFAULTS: dict[str, Any] = {"version": 1, "mode": "local", "vendor": None, "model": None,
                            "ack_version": 0, "setup_done": False, "hearing": True,
                            "hearing_speed": None, "voice": None}


class SettingsError(ValueError):
    pass


def load() -> dict[str, Any]:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}


def _validate(s: dict[str, Any]) -> None:
    from app import provider  # late: provider reads settings, not the other way round
    if s["mode"] not in MODES:
        raise SettingsError("mode must be one of %s" % ", ".join(MODES))
    if s["mode"] == "cloud":
        if s["vendor"] not in provider.VENDORS:
            raise SettingsError("choose a provider: %s" % ", ".join(provider.VENDORS))
        if not isinstance(s["model"], str) or not s["model"].strip() or len(s["model"]) > 200:
            raise SettingsError("choose a model")
    if not isinstance(s["ack_version"], int) or not 0 <= s["ack_version"] <= ACK_VERSION:
        raise SettingsError("unknown acknowledgement version")
    if not isinstance(s["setup_done"], bool) or not isinstance(s["hearing"], bool):
        raise SettingsError("setup_done and hearing are true or false")
    if s["hearing_speed"] is not None and not isinstance(s["hearing_speed"], (int, float)):
        raise SettingsError("hearing_speed is a number")
    if s["voice"] is not None:
        from app import piper
        if piper.entry(s["voice"]) is None:
            raise SettingsError("unknown voice %r" % s["voice"])


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """Apply `changes` over the current settings, validate the result, and write it atomically,
    so a reader never sees half a file."""
    unknown = set(changes) - set(DEFAULTS) - {"version"}
    if unknown:
        raise SettingsError("unknown setting %s" % ", ".join(sorted(unknown)))
    s = {**load(), **changes}
    if isinstance(s.get("model"), str):
        s["model"] = s["model"].strip()
    _validate(s)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, PATH)
    return s


def acknowledged(s: dict[str, Any] | None = None) -> bool:
    return (s or load())["ack_version"] >= ACK_VERSION


def hearing_refused(s: dict[str, Any] | None = None) -> str | None:
    """Why spoken answers are off, or None. Only cloud mode can turn them off: locally the voice
    runs on the GPU and was measured there."""
    s = s or load()
    if s["mode"] != "cloud":
        return None
    if not s["hearing"]:
        return "answers are typed: speaking them was turned off at setup"
    from app import lfm3
    speed = s["hearing_speed"]
    if speed is not None and speed < lfm3.HEARING_MIN_SPEED:
        return ("this computer recognised speech at %.1fx real time, under the %.1fx a spoken "
                "answer needs, so answers are typed" % (speed, lfm3.HEARING_MIN_SPEED))
    return None
