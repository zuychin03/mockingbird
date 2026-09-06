"""The ASR port: nemotron through `transcribe.cpp`, one utterance slice at a time.

Mirrors the TTS port (11.6.1) deliberately -- a protocol, a config, one implementation -- so the
engine can change without anything downstream knowing. 11.2.1 already exercised that: whisper
was measured against this and dropped on cost, and nothing outside this file would have to
change if that decision were ever revisited.

**Measured on this laptop, on mains, and both numbers shape the design above it:**

* a fixed **~2.5 s per invocation**, independent of length -- there is no server mode and no
  shared library in the build, so every call reloads the model;
* **5.5x realtime**, about 182 ms per second of audio.

So a single pass over a 60 s answer costs ~13.5 s, which is why `api/voice.py` transcribes in
slices while the candidate is still talking rather than once when they stop.

**`--threads 6`, and this is not folklore.** The recorded trap was that 16 threads ran 3.5x
slower than 8 on this 8-core/16-thread part; sweeping it properly puts the optimum at **6**
(5.5x), flat across 5-7, with 4 at 4.3x and 8 at 5.0x. Never pass `os.cpu_count()`.

**The language argument must be a locale.** `-l en-US` works; `-l en` and `-l eng` are rejected
outright as an unsupported language.

Output is verbatim on purpose (11.4): the filled pauses and false starts are signal, because the
report reads fluency and confidence as well as content. Jargon errors are expected and accepted
(11.2.1) -- `PostgreSQL` comes back as `Postgre SQL` -- which is what 12.6 makes the transcript
editable for.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "nemotron-asr" / "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"
BINARY = Path(os.environ.get("MOCKINGBIRD_TRANSCRIBE",
                             r"C:\src\transcribe.cpp\build\bin\Release\transcribe-cli.exe"))
THREADS = 6
LOCALE = "en-US"
LOAD_SECONDS = 2.5      # measured; the slicing above this file is sized against it
RATE_REALTIME = 5.5


class AsrEngine(Protocol):
    def transcribe(self, samples: np.ndarray, rate: int) -> str:
        """One slice of speech as text. Verbatim, and never raises on a bad slice."""


@dataclass
class Nemotron:
    binary: Path = BINARY
    model: Path = MODEL
    threads: int = THREADS

    def available(self) -> str | None:
        """Why this cannot run, or None. Checked before a session rather than mid-answer."""
        if not self.binary.exists():
            return ("the transcribe.cpp binary is not at %s (set MOCKINGBIRD_TRANSCRIBE)"
                    % self.binary)
        if not self.model.exists():
            return "the ASR model is not at %s" % self.model
        return None

    def transcribe(self, samples: np.ndarray, rate: int) -> str:
        if len(samples) < rate // 10:      # under 100 ms carries no word
            return ""
        with tempfile.TemporaryDirectory(prefix="mockingbird-asr-") as tmp:
            d = Path(tmp)
            audio, text = d / "slice.wav", d / "slice.txt"
            with wave.open(str(audio), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            cmd = [str(self.binary), "-m", str(self.model), "-l", LOCALE,
                   "--threads", str(self.threads), "-q", "-o", str(text), str(audio)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=180, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired):
                return ""
            try:
                return text.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return ""


def engine() -> Nemotron:
    return Nemotron()


def describe() -> dict:
    """What a session records about how its audio was read (FR-44)."""
    return {"engine": "transcribe.cpp", "model": MODEL.name, "locale": LOCALE,
            "threads": THREADS, "verbatim": True}
