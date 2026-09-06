"""The TTS port: a protocol, a dict of voices, and one implementation (11.6.1).

11.6.1 planned three engines behind this and then withdrew the plan: both shipped voices came
out of the same bench as Piper/VITS, so the port needs exactly one adapter and the voice choice
is a model path. It is kept anyway because it is nearly free and it is what let the engine
change three times during evaluation without touching anything downstream.

Note 11.6.1 still reads "Kokoro stays the default"; 11.6 supersedes it -- the default is
`hfc_female` and the alternate is `ryan`, at 0.88 pace, which is the operator's own call after
listening to both on ten real bank questions.

Rule inherited from the LLM port: **the voice is chosen at session start and never mid-session.**
A session's audio has to be one voice or listening back to it is incoherent.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
PACE = 0.88     # 11.6: the operator's pace, chosen by ear against real questions


@dataclass(frozen=True)
class Voice:
    key: str
    directory: str
    label: str


VOICES: dict[str, Voice] = {
    "hfc_female": Voice("hfc_female", "vits-piper-en_US-hfc_female-medium",
                        "Fiona - US, default"),
    "ryan": Voice("ryan", "vits-piper-en_US-ryan-medium", "Ryan - US, alternate"),
}
DEFAULT_VOICE = "hfc_female"


class TtsEngine(Protocol):
    """What the rest of the codebase is allowed to know about speech."""

    rate: int

    def say(self, text: str) -> np.ndarray:
        """Float32 mono at `rate`."""


class Piper:
    """Piper voices through sherpa-onnx.

    sherpa-onnx rather than `piper1-gpl` is the load-bearing choice and not only a licence one
    (11.6.1): it made benching 14 voices a download instead of an integration each time. It also
    embeds espeak-ng in the wheel, so there is no separate install and no environment variables.
    """

    def __init__(self, voice: str = DEFAULT_VOICE, threads: int = 4) -> None:
        if voice not in VOICES:
            raise ValueError("unknown voice %r; have %s" % (voice, ", ".join(VOICES)))
        self.voice = VOICES[voice]
        self._threads = threads
        self._tts = None
        self._lock = threading.Lock()
        self.rate = 0

    def _engine(self):
        # Built on first use, not in __init__: importing sherpa_onnx and loading the model costs
        # real time, and nothing should pay it just by constructing a session object.
        with self._lock:
            if self._tts is not None:
                return self._tts
            import sherpa_onnx

            d = MODELS / self.voice.directory
            if not d.exists():
                raise FileNotFoundError("voice %r is not installed at %s" % (self.voice.key, d))
            self._tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(next(d.glob("*.onnx"))), tokens=str(d / "tokens.txt"),
                        data_dir=str(d / "espeak-ng-data")),
                    provider="cpu", num_threads=self._threads),
                max_num_sentences=1))
            self.rate = self._tts.sample_rate
            return self._tts

    def warm(self) -> None:
        """Load and run once. The first generate carries the model load and ONNX's own lazy
        setup; paying it at session start keeps it out of the first turn."""
        self._engine().generate("warm up", sid=0, speed=PACE)

    def say(self, text: str) -> np.ndarray:
        a = self._engine().generate(text, sid=0, speed=PACE)
        self.rate = a.sample_rate
        return np.asarray(a.samples, dtype=np.float32)


def engine(voice: str | None = None) -> TtsEngine:
    return Piper(voice or DEFAULT_VOICE)


def describe(voice: str | None = None) -> dict:
    """What a session records about the voice it used (FR-44). Without it, listening back to an
    old session tells you nothing about what produced it."""
    v = VOICES[voice or DEFAULT_VOICE]
    return {"engine": "piper/sherpa-onnx", "voice": v.key, "label": v.label,
            "model": v.directory, "pace": PACE, "python": sys.version.split()[0]}
