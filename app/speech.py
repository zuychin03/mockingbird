"""The TTS port: a protocol and the engines behind it, LFM3-Audio (`app/lfm3.py`) and Piper
(`app/piper.py`), chosen from `config/voices.json` (V1.1_PLAN P4).

Rule inherited from the LLM port: **the voice is chosen at session start and never mid-session.**
A session's audio has to be one voice or listening back to it is incoherent. Settings are locked
while an interview runs, so the voice a socket picks up is the one the session recorded.

LFM3-Audio speaks only where its model runs on a GPU: on a processor it renders at a real-time
factor of 1.4 (08/11/2026), so a three-sentence question would wait about 11 s. There a chosen
LFM3 voice gives way to Piper's kristin, and the record says so.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app import lfm3, piper

LEGACY = {"female": "lfm3:female", "male": "lfm3:male"}   # 1.0 sessions and settings
DEFAULT_VOICE = "lfm3:female"
CPU_DEFAULT = "piper:kristin"


class TtsEngine(Protocol):
    """What the rest of the codebase is allowed to know about speech."""

    rate: int

    def say(self, text: str) -> np.ndarray:
        """Float32 mono at `rate`."""

    def warm(self) -> None:
        """Spend the first, slow render before anyone is waiting for it."""


class Silent:
    """No voice that can speak here: questions are shown, not spoken, and the record says why."""

    rate = 16000

    def __init__(self, why: str) -> None:
        self.why = why

    def say(self, text: str) -> np.ndarray:
        return np.zeros(0, dtype=np.float32)

    def warm(self) -> None:
        pass


def voices() -> list[dict]:
    return piper.catalogue()


def lfm3_speaks() -> bool:
    """Locally the voice runs on the 6 GB card; in cloud mode only if a card can hold it."""
    from app import hardware, settings
    return settings.load()["mode"] == "local" or hardware.voice_on_gpu()


def default_voice() -> str:
    return DEFAULT_VOICE if lfm3_speaks() else CPU_DEFAULT


def resolve(voice: str | None = None) -> tuple[str | None, str | None]:
    """The voice that will actually speak, and why it differs from the one asked for, if it does.
    None when nothing can speak here."""
    from app import settings
    asked = voice or settings.load().get("voice") or default_voice()
    asked = LEGACY.get(asked, asked)
    e = piper.entry(asked)
    if e is None:
        return resolve(default_voice()) if asked != default_voice() else (None, "no voice")
    if e["engine"] == "lfm3":
        if lfm3_speaks():
            return asked, None
        if piper.installed(CPU_DEFAULT):
            return CPU_DEFAULT, "LFM3 cannot speak in time on this computer's processor"
        return None, "LFM3 cannot speak in time here and no Piper voice is downloaded"
    if piper.installed(asked):
        return asked, None
    if lfm3_speaks():
        return DEFAULT_VOICE, "the %s voice is not downloaded yet" % e["label"]
    if asked != CPU_DEFAULT and piper.installed(CPU_DEFAULT):
        return CPU_DEFAULT, "the %s voice is not downloaded yet" % e["label"]
    return None, "the %s voice is not downloaded yet" % e["label"]


def engine(voice: str | None = None) -> TtsEngine:
    chosen, why = resolve(voice)
    if chosen is None:
        return Silent(why or "no voice")
    if chosen.startswith("lfm3:"):
        return lfm3.Speaker(piper.entry(chosen)["voice"])
    return piper.speaker(chosen)


def describe(voice: str | None = None) -> dict:
    """What a session records about the voice it used (FR-44). Without it, listening back to an
    old session tells you nothing about what produced it."""
    from app import settings
    asked = LEGACY.get(voice, voice) if voice else (settings.load().get("voice")
                                                     or default_voice())
    chosen, why = resolve(voice)
    e = piper.entry(chosen) if chosen else None
    out = {"id": chosen, "label": e["label"] if e else None, "asked": asked, "fallback": why,
           "licence": e["licence"] if e else None,
           "noncommercial": bool(e and e.get("noncommercial"))}
    if chosen and chosen.startswith("lfm3:"):
        out.update(lfm3.describe_voice(e["voice"]))
    elif chosen:
        out.update(piper.describe(chosen))
    else:
        out["engine"] = None
    return out
