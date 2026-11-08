"""The ASR port: a protocol and the one engine behind it, LFM3-Audio (`app/lfm3.py`).

Output is verbatim on purpose (11.4): the filled pauses and false starts are signal, because the
report reads fluency and confidence as well as content. Recognition still errs (`cutover` came
back as `queueover`), which is what 12.6 makes the transcript editable for.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app import lfm3


class AsrEngine(Protocol):
    def transcribe(self, samples: np.ndarray, rate: int) -> str:
        """One slice of speech as text. Verbatim, and never raises on a bad slice."""

    def available(self) -> str | None:
        """Why this cannot run, or None. Checked before a session rather than mid-answer."""


class Refused:
    """No recognition, and why: the voice socket then runs typed answers and says so."""

    def __init__(self, why: str) -> None:
        self.why = why

    def available(self) -> str | None:
        return self.why

    def transcribe(self, samples: np.ndarray, rate: int) -> str:
        return ""


def engine() -> AsrEngine:
    from app import settings
    why = settings.hearing_refused()
    return Refused(why) if why else lfm3.Listener()


def describe() -> dict:
    """What a session records about how its audio was read (FR-44)."""
    return lfm3.describe_asr()
