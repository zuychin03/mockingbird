"""Live mode's endpointer: when has the candidate finished answering?

FR-26 makes open microphone an opt-in beside tap-to-talk, with the pause that ends an answer a
user setting. This decides that end from the audio alone: speech has been heard, then silence
has lasted the chosen pause.

**Silence length, not a semantic turn detector, and that reverses 11.7.** Smart Turn v3.2 was
replayed over the recorded answers on 22/09/2026 and could not tell a pause between sentences
from the end of an answer: after 0.5 s of silence it called 7 of 10 mid-answer pauses finished
while catching 9 of 12 real ends, and after 1.0 s all 4 mid-answer pauses. It was trained on
conversational turns, where a finished sentence followed by a pause usually is the end, and an
interview answer is several finished sentences. Pause length did separate them: no pause inside
any answer reached 2 s. A false cut truncates the answer being scored (12.6.3), so the one signal
that measured clean is the only one used.

Silero VAD through sherpa-onnx, already a voice dependency, so live mode adds a 2 MB model and
no package. `VadModel.is_speech` applies Silero's own hysteresis per 512-sample window and
buffers nothing, which is all an endpointer needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from app.audio import MIC_RATE

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "vad" / "silero_vad.onnx"
WINDOW = 512            # Silero's hard constraint at 16 kHz
THRESHOLD = 0.5
MIN_SPEECH = 0.25       # shorter is a click or a breath, not a word
# Silero holds "speech" this long after the probability drops. Short, because the pause itself
# is timed here rather than inside the model.
MIN_SILENCE = 0.25

PAUSE_DEFAULT = 2.5
PAUSE_MIN, PAUSE_MAX = 1.0, 10.0


class Vad(Protocol):
    def is_speech(self, window: np.ndarray) -> bool:
        """One WINDOW of 16 kHz samples, with the model's hysteresis applied."""

    def reset(self) -> None: ...


@dataclass
class Silero:
    model: Path = MODEL

    def available(self) -> str | None:
        """Why live mode cannot run, or None. Checked at connect, not mid-answer."""
        if not self.model.exists():
            return "the voice activity model is not at %s" % self.model
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return "sherpa-onnx is not installed"
        return None

    def load(self) -> Vad:
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(self.model)
        cfg.silero_vad.threshold = THRESHOLD
        cfg.silero_vad.min_speech_duration = MIN_SPEECH
        cfg.silero_vad.min_silence_duration = MIN_SILENCE
        # Never split a long answer: a forced split flips the state to silence mid-speech.
        cfg.silero_vad.max_speech_duration = 3600.0
        cfg.silero_vad.window_size = WINDOW
        cfg.sample_rate = MIC_RATE
        cfg.num_threads = 1
        return _Stream(sherpa_onnx.VadModel.create(cfg))


class _Stream:
    """Silero v5 and later read each window with the previous 64 samples in front of it, so
    `window_size()` is 576 while the hop is 512. sherpa-onnx aborts the whole process on a
    wrong length rather than raising, so the size is checked once here and never guessed."""

    def __init__(self, model) -> None:
        self.model = model
        self.context = model.window_size() - WINDOW
        if self.context not in (0, 64):
            raise ValueError("unexpected VAD window of %d samples" % model.window_size())
        self.tail = np.zeros(self.context, dtype=np.float32)

    def is_speech(self, window: np.ndarray) -> bool:
        if not self.context:
            return self.model.is_speech(window)
        x = np.concatenate([self.tail, window])
        self.tail = window[-self.context:].copy()
        return self.model.is_speech(x)

    def reset(self) -> None:
        self.model.reset()
        self.tail[:] = 0.0


def engine() -> Silero:
    return Silero()


def clamp_pause(value: object) -> float:
    try:
        pause = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return PAUSE_DEFAULT
    if pause != pause:  # NaN
        return PAUSE_DEFAULT
    return min(PAUSE_MAX, max(PAUSE_MIN, pause))


class Endpointer:
    """Fed the same frames as the utterance, so every index here is an utterance sample index.

    Silence before the first word never ends an answer: thinking before speaking is not having
    finished, and the candidate may take as long over it as they like.
    """

    def __init__(self, vad: Vad, pause: float = PAUSE_DEFAULT, rate: int = MIC_RATE) -> None:
        self.vad = vad
        self.pause = pause
        self.rate = rate
        self.at = 0
        self.speaking = False
        self.spans: list[list[int]] = []
        self.quiet_from: int | None = None
        self._rest = np.zeros(0, dtype=np.float32)
        vad.reset()

    @property
    def heard(self) -> bool:
        return bool(self.spans)

    def add(self, x: np.ndarray) -> bool:
        """True when the answer has ended. Frames of any length; windows are cut here."""
        buf = np.concatenate([self._rest, x]) if len(self._rest) else x
        whole = len(buf) - len(buf) % WINDOW
        for i in range(0, whole, WINDOW):
            speech = self.vad.is_speech(buf[i:i + WINDOW])
            self.at += WINDOW
            if speech and not self.speaking:
                # The model only reports speech once it has lasted MIN_SPEECH, so it began then.
                start = max(0, self.at - int(MIN_SPEECH * self.rate) - WINDOW)
                self.spans.append([start, self.at])
                self.speaking, self.quiet_from = True, None
            elif speech:
                self.spans[-1][1] = self.at
            elif self.speaking:
                # And it only reports silence once that has lasted MIN_SILENCE.
                end = max(self.spans[-1][0], self.at - int(MIN_SILENCE * self.rate) - WINDOW)
                self.spans[-1][1] = end
                self.speaking, self.quiet_from = False, end
        self._rest = buf[whole:].copy()
        return self.ended

    @property
    def ended(self) -> bool:
        # A pause only has a start once speech has ended, so silence before the first word
        # can never satisfy this.
        return (not self.speaking and self.quiet_from is not None
                and self.at - self.quiet_from >= self.pause * self.rate)

    def pause_onset(self, least: float) -> int | None:
        """Where the current silence began, once it has lasted `least` seconds."""
        if self.speaking or self.quiet_from is None:
            return None
        return self.quiet_from if self.at - self.quiet_from >= least * self.rate else None

    def speech_between(self, a: int, b: int) -> bool:
        return any(s < b and e > a for s, e in self.spans)


# What a recogniser returns for a cough or a hum. An answer that is only these is not an answer,
# and live mode sends answers without a person pressing anything, so it has to be able to tell.
# Narrower than guards._FILLER on purpose: "yes", "no" and "sure" are real answers.
_NOISE = frozenset({"um", "umm", "uhm", "uh", "uhh", "er", "erm", "ah", "hm", "hmm", "hmmm",
                    "mm", "mmm", "mhm", "mhmm", "mm-hmm", "uh-huh"})


def is_answer(text: str) -> bool:
    words = [w.strip(".,!?;:'\"-").lower() for w in (text or "").split()]
    return any(w and w not in _NOISE for w in words)
