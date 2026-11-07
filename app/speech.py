"""The TTS port: a protocol and the one engine behind it, LFM3-Audio (`app/lfm3.py`).

Rule inherited from the LLM port: **the voice is chosen at session start and never mid-session.**
A session's audio has to be one voice or listening back to it is incoherent.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app import lfm3

VOICES = lfm3.VOICES
DEFAULT_VOICE = lfm3.DEFAULT_VOICE


class TtsEngine(Protocol):
    """What the rest of the codebase is allowed to know about speech."""

    rate: int

    def say(self, text: str) -> np.ndarray:
        """Float32 mono at `rate`."""


def engine(voice: str | None = None) -> TtsEngine:
    return lfm3.Speaker(voice or DEFAULT_VOICE)


def describe(voice: str | None = None) -> dict:
    """What a session records about the voice it used (FR-44). Without it, listening back to an
    old session tells you nothing about what produced it."""
    return lfm3.describe_voice(voice)
