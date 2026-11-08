"""PCM plumbing and the voice wire protocol.

Deliberately knows nothing about FastAPI, sockets or sherpa-onnx: the same framing has to be
exercised by tests that start no server and no engine, and `app/` never imports the web extra.

The wire is two channels over one socket. **Control is JSON text; audio is raw binary**, which
is why the protocol carries no length prefixes or type bytes -- the frame type already says
which it is. Audio is always 16-bit signed little-endian mono, and its sample rate is whatever
the last control message declared for that direction: `MIC_RATE` going up, whatever the engine
emits coming down. Nothing resamples silently.

Rates are the recurring trap here (12.7). The browser captures at the device default, almost
always 48 kHz on Windows; ASR wants 16 kHz; the voice emits 24 kHz. Three rates, none of them
negotiable, so each one is declared rather than assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

MIC_RATE = 16000       # what the ASR wants; the worklet downsamples to it before sending
FRAME_MS = 20          # 12.7 allows 20-250 ms; the low end costs nothing on a local socket
FRAME_SAMPLES = MIC_RATE * FRAME_MS // 1000
SPEECH_CHUNK_MS = 100  # coarser downlink: playback is scheduled ahead, so latency is the buffer


def to_int16(x: np.ndarray) -> bytes:
    """Float32 in [-1, 1] to the wire format. Clipped, because a sample over 1.0 wraps to the
    opposite sign in int16 and one wrapped sample is an audible click."""
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def from_int16(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0


def frames(x: np.ndarray, n: int) -> list[np.ndarray]:
    """Whole frames only. A trailing partial frame is dropped by design: the caller keeps the
    remainder and prepends it next time, so nothing is padded with silence mid-utterance."""
    return [x[i:i + n] for i in range(0, len(x) - n + 1, n)]


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def _bare(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum() or c == "'")


def seam(previous: str, nxt: str) -> str:
    """The next slice of an answer, minus a word it repeats across the cut. A cut at a pause can
    land inside the recogniser's context for one word, which then comes back in both slices:
    "for a" then "A friend" was heard as "for a A friend" (V1.1_PLAN P5). Only the one word at
    the seam is dropped, compared without case or punctuation; a repeat anywhere else is the
    candidate's own."""
    prev_words, next_words = previous.split(), nxt.split()
    if not (prev_words and next_words and _bare(prev_words[-1])):
        return nxt
    # "...we shipped it. It worked" is a new sentence, not an echo.
    if prev_words[-1][-1] in ".?!":
        return nxt
    if _bare(prev_words[-1]) == _bare(next_words[0]):
        return " ".join(next_words[1:])
    return nxt


def encode(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def decode(raw: str) -> dict:
    """A control frame, or a rejection. Never raises: this parses input from a browser, and a
    socket that dies on malformed JSON is a socket that drops a whole interview."""
    try:
        msg = json.loads(raw)
    except ValueError:
        return {"t": "bad", "why": "not json"}
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        return {"t": "bad", "why": "no type"}
    return msg


def split_at_pause(x: np.ndarray, rate: int, earliest: float, latest: float,
                   window: float = 0.12) -> int | None:
    """Where to cut a growing answer so the slice ends in a pause rather than mid-word.

    Transcription happens in slices while the candidate is still talking, so the answer fills in
    as it is given and only the tail is left to read when they stop. Slices are recognised
    independently, so a cut through a word loses it from both sides -- hence cutting where the
    audio is quietest.

    Energy on the raw PCM, not the transcript: word timestamps would be a better boundary and
    would mean parsing them back out of a second recognition pass, which is a lot of machinery
    to place a cut that a silence already marks.

    Returns None when the region is too short to choose within, and the caller waits.
    """
    a, b = int(earliest * rate), min(int(latest * rate), len(x))
    n = max(1, int(window * rate))
    if b - a < n:
        return None
    hop = max(1, n // 2)
    best, best_energy = None, None
    for i in range(a, b - n + 1, hop):
        e = float(np.mean(x[i:i + n] ** 2))
        if best_energy is None or e < best_energy:
            best, best_energy = i, e
    return None if best is None else best + n // 2


@dataclass
class Utterance:
    """One press-to-talk turn, accumulating as frames arrive.

    Holds float32 rather than bytes because everything downstream -- level metering, the wav
    written for the report, ASR -- wants samples, and converting once at the edge beats
    converting at each of them.
    """

    rate: int = MIC_RATE
    chunks: list[np.ndarray] = field(default_factory=list)
    peak: float = 0.0
    # Running count rather than a sum over `chunks`: the length cap reads it once per 20 ms
    # frame against a list that grows for the whole answer.
    length: int = 0

    def add(self, pcm: bytes) -> float:
        x = from_int16(pcm)
        self.chunks.append(x)
        self.length += len(x)
        level = rms(x)
        self.peak = max(self.peak, float(np.abs(x).max()) if len(x) else 0.0)
        return level

    @property
    def samples(self) -> np.ndarray:
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype=np.float32)

    @property
    def seconds(self) -> float:
        return self.length / self.rate

    def wav(self) -> bytes:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(to_int16(self.samples))
        return buf.getvalue()


@dataclass
class Speech:
    """One thing the interviewer says, sliced for the downlink.

    `heard_seconds` is the point of tracking this at all. 12.4 requires that a barge-in cuts
    the audio without deleting it, and that the context is truncated to *what the candidate
    actually heard* -- so the transport has to report how far playback got, not how much was
    sent. Everything after that is struck through, not dropped.
    """

    id: int
    text: str
    rate: int
    samples: np.ndarray
    sent: int = 0
    heard_seconds: float | None = None

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate

    def chunks(self) -> list[bytes]:
        n = max(1, self.rate * SPEECH_CHUNK_MS // 1000)
        return [to_int16(self.samples[i:i + n]) for i in range(0, len(self.samples), n)]

    def spoken_text(self) -> tuple[str, str]:
        """The line split into what was heard and what was cut, by time.

        Words are apportioned by position because there is no alignment here and inventing one
        would be worse than the approximation: an unaligned guess that is visibly approximate
        beats a precise-looking number that is wrong. The report shows the remainder struck
        through, so this only has to be close.
        """
        if self.heard_seconds is None or self.heard_seconds >= self.seconds:
            return self.text, ""
        words = self.text.split()
        if not words:
            return "", ""
        share = max(0.0, self.heard_seconds) / self.seconds
        cut = round(len(words) * share)
        return " ".join(words[:cut]), " ".join(words[cut:])
