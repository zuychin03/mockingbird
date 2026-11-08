"""Piper voices through sherpa-onnx (V1.1_PLAN P4): the interviewer's voice where LFM3-Audio cannot
speak in time, and a choice anywhere.

sherpa-onnx is already a dependency (live mode's pause detector) and carries its own Apache-2.0
VITS implementation, so a voice is a downloaded model folder, not another runtime. It runs on the
processor, in-process, measured at a real-time factor near 0.05 on this laptop (log, 06/09).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "models" / "piper"
CATALOGUE = ROOT / "config" / "voices.json"
THREADS = 2       # one sentence at a time; more threads contend with the CPU recogniser


def catalogue() -> list[dict]:
    try:
        return json.loads(CATALOGUE.read_text(encoding="utf-8"))["voices"]
    except (OSError, ValueError, KeyError):
        return []


def entry(voice_id: str) -> dict | None:
    return next((v for v in catalogue() if v["id"] == voice_id), None)


def folder(voice_id: str) -> Path | None:
    e = entry(voice_id)
    return DIR / e["package"] if e and e.get("engine") == "piper" else None


def installed(voice_id: str) -> bool:
    f = folder(voice_id)
    return bool(f) and (f / "tokens.txt").exists() and any(f.glob("*.onnx"))


class Speaker:
    """The TTS port for one Piper voice. The model loads on first use, not at construction, so
    choosing a voice costs nothing until it speaks."""

    def __init__(self, voice_id: str) -> None:
        if not installed(voice_id):
            raise RuntimeError("the %s voice is not downloaded" % voice_id)
        self.voice = voice_id
        self.rate = 22050
        self._tts = None
        self._lock = threading.Lock()

    def _load(self):
        import sherpa_onnx
        f = folder(self.voice)
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(next(f.glob("*.onnx"))), tokens=str(f / "tokens.txt"),
                    data_dir=str(f / "espeak-ng-data")),
                num_threads=THREADS),
            max_num_sentences=1)
        tts = sherpa_onnx.OfflineTts(cfg)
        self.rate = tts.sample_rate
        return tts

    def say(self, text: str) -> np.ndarray:
        # The warm-up runs on its own thread beside the first line; one generate at a time.
        with self._lock:
            if self._tts is None:
                self._tts = self._load()
            audio = self._tts.generate(text, sid=0, speed=1.0)
        return np.asarray(audio.samples, dtype=np.float32)

    def warm(self) -> None:
        self.say("Ready.")


_LOADED: dict[str, Speaker] = {}
_LOADED_LOCK = threading.Lock()


def speaker(voice_id: str) -> Speaker:
    """One loaded voice per process. Each socket built its own and the first line on it waited
    for the model to load: 3.7 s to first audio against about 0.2 s once loaded (08/11/2026)."""
    with _LOADED_LOCK:
        if voice_id not in _LOADED:
            _LOADED[voice_id] = Speaker(voice_id)
        return _LOADED[voice_id]


def describe(voice_id: str) -> dict:
    e = entry(voice_id) or {}
    return {"engine": "piper/sherpa-onnx", "voice": voice_id, "package": e.get("package"),
            "licence": e.get("licence"), "noncommercial": bool(e.get("noncommercial"))}
