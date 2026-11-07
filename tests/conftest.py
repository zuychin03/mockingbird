"""Keep the suite out of the real interview history.

`new_session` writes a session directory the moment it is called, so every test that built
one wrote into `data/sessions`, where real interviews live: 47 of them had accumulated
there. Autouse rather than opt-in, because the write is a side effect of construction and a
test need not look like it touches storage in order to pollute it.

The voice socket keeps its OWN paths and went the same way. `api/voice.py` resolves an
answer's directory through `data/live_session.json`, so tests that never mentioned storage
dropped 45 tone wavs into whichever interview was last run -- where a report would have
offered them back as the candidate's own answers. Same fix, one import further out.
"""

import pytest

from app import session as sess


@pytest.fixture(autouse=True)
def _sessions_in_tmp(tmp_path, monkeypatch):
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setattr(sess, "SESSIONS", d)

    # `api/` needs the web extra and `app/` must stay importable without it, so this is a
    # try rather than a top-level import.
    try:
        from api import voice
    except ImportError:
        return d
    monkeypatch.setattr(voice, "SESSIONS", d)
    monkeypatch.setattr(voice, "LIVE", tmp_path / "no-live-session.json")
    monkeypatch.setattr(voice, "LOOSE", tmp_path / "voice")
    monkeypatch.setattr(voice, "ROOT", tmp_path)
    return d


class FakeVad:
    """Silero as sherpa-onnx applies it -- speech only once it has lasted MIN_SPEECH, silence
    only once it has lasted MIN_SILENCE -- over energy instead of a model, so a tone is speech,
    zeros are silence, and the live-mode tests know every boundary exactly."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.at = 0
        self.triggered = False
        self.start = 0
        self.end = 0
        self.resets = getattr(self, "resets", 0) + 1

    def is_speech(self, window) -> bool:
        # Imported here: the text-only suite runs without numpy, and this file loads for it.
        import numpy as np

        from app import endpoint

        assert len(window) == endpoint.WINDOW
        loud = float(np.sqrt(np.mean(window ** 2))) > 0.05
        self.at += len(window)
        min_speech = int(endpoint.MIN_SPEECH * endpoint.MIC_RATE)
        min_silence = int(endpoint.MIN_SILENCE * endpoint.MIC_RATE)
        if not self.triggered:
            if not loud:
                self.start = 0
                return False
            if not self.start:
                self.start = self.at
            if self.at - self.start >= min_speech:
                self.triggered, self.end = True, 0
                return True
            return False
        if loud:
            self.end = 0
            return True
        if not self.end:
            self.end = self.at
        if self.at - self.end < min_silence:
            return True
        self.triggered, self.start, self.end = False, 0, 0
        return False


@pytest.fixture()
def fake_vad():
    return FakeVad
