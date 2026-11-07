"""Live mode's endpointer: an answer ends on a long enough pause after speech, and never before.

The VAD is `conftest.FakeVad`: Silero's hysteresis over energy, so a tone is speech, zeros are
silence, and every boundary is known exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import endpoint  # noqa: E402
from app.audio import MIC_RATE  # noqa: E402

RATE = MIC_RATE


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def feed(ep: endpoint.Endpointer, x: np.ndarray, frame: int = 320) -> float | None:
    """Frames as the socket delivers them. Returns when the answer ended, in seconds."""
    for i in range(0, len(x), frame):
        if ep.add(x[i:i + frame]):
            return (i + min(frame, len(x) - i)) / RATE
    return None


def test_thinking_before_speaking_never_ends_the_answer(fake_vad):
    ep = endpoint.Endpointer(fake_vad(), pause=1.0)
    assert feed(ep, quiet(20.0)) is None
    assert not ep.heard


def test_a_pause_shorter_than_the_setting_is_part_of_the_answer(fake_vad):
    ep = endpoint.Endpointer(fake_vad(), pause=2.5)
    assert feed(ep, np.concatenate([tone(2.0), quiet(2.0), tone(1.0)])) is None
    assert len(ep.spans) == 2


def test_the_setting_is_measured_from_the_last_word(fake_vad):
    ep = endpoint.Endpointer(fake_vad(), pause=2.5)
    ended = feed(ep, np.concatenate([tone(3.0), quiet(4.0)]))
    assert ended == pytest.approx(3.0 + 2.5, abs=0.1)


def test_speech_is_located_where_it_was_said(fake_vad):
    ep = endpoint.Endpointer(fake_vad(), pause=5.0)
    feed(ep, np.concatenate([quiet(1.0), tone(2.0), quiet(1.5), tone(1.0), quiet(1.0)]))
    got = [(s / RATE, e / RATE) for s, e in ep.spans]
    want = [(1.0, 3.0), (4.5, 5.5)]
    for (s, e), (ws, we) in zip(got, want):
        assert s == pytest.approx(ws, abs=0.1) and e == pytest.approx(we, abs=0.1)
    assert ep.speech_between(int(2.0 * RATE), int(2.1 * RATE))
    assert not ep.speech_between(int(3.2 * RATE), int(4.3 * RATE))


def test_a_pause_is_reported_only_once_it_has_lasted(fake_vad):
    ep = endpoint.Endpointer(fake_vad(), pause=5.0)
    feed(ep, np.concatenate([tone(2.0), quiet(0.5)]))
    assert ep.pause_onset(0.8) is None
    feed(ep, quiet(0.5))
    assert ep.pause_onset(0.8) == pytest.approx(2.0 * RATE, abs=0.1 * RATE)
    feed(ep, tone(0.5))
    assert ep.pause_onset(0.0) is None, "speaking again is not a pause"


def test_frames_that_do_not_fill_a_window_are_carried_not_lost(fake_vad):
    """20 ms frames are 320 samples and a window is 512, so most frames straddle two."""
    whole = endpoint.Endpointer(fake_vad(), pause=1.0)
    feed(whole, np.concatenate([tone(1.0), quiet(1.5)]), frame=len(tone(1.0)) + len(quiet(1.5)))
    framed = endpoint.Endpointer(fake_vad(), pause=1.0)
    feed(framed, np.concatenate([tone(1.0), quiet(1.5)]), frame=320)
    assert whole.spans == framed.spans


def test_each_answer_starts_the_model_afresh(fake_vad):
    vad = fake_vad()
    before = vad.resets
    endpoint.Endpointer(vad)
    assert vad.resets == before + 1


@pytest.mark.parametrize("given, want", [
    (2.5, 2.5), ("4", 4.0), (0.2, endpoint.PAUSE_MIN), (60, endpoint.PAUSE_MAX),
    (None, endpoint.PAUSE_DEFAULT), ("soon", endpoint.PAUSE_DEFAULT),
    (float("nan"), endpoint.PAUSE_DEFAULT),
])
def test_the_pause_setting_is_bounded(given, want):
    assert endpoint.clamp_pause(given) == want


@pytest.mark.parametrize("text, answer", [
    ("", False), ("Um.", False), ("Uh, hmm...", False), ("Mm-hmm.", False),
    ("No.", True), ("Yes, twice.", True), ("Um, I think so.", True),
])
def test_noise_alone_is_not_an_answer(text, answer):
    """Live mode sends without a press, so a cough the recogniser heard as "Hmm." must not
    reach the interviewer as the candidate's answer. "No." is an answer."""
    assert endpoint.is_answer(text) is answer


class FakeModel:
    def __init__(self, size: int) -> None:
        self.size = size
        self.seen: list[np.ndarray] = []

    def window_size(self) -> int:
        return self.size

    def is_speech(self, x) -> bool:
        self.seen.append(np.array(x))
        return False

    def reset(self) -> None:
        pass


def test_newer_silero_gets_the_previous_windows_tail_in_front():
    model = FakeModel(576)
    stream = endpoint._Stream(model)
    a = np.full(512, 0.1, dtype=np.float32)
    b = np.full(512, 0.2, dtype=np.float32)
    stream.is_speech(a)
    stream.is_speech(b)
    assert [len(x) for x in model.seen] == [576, 576]
    assert np.all(model.seen[1][:64] == pytest.approx(0.1))
    assert np.all(model.seen[1][64:] == pytest.approx(0.2))


def test_an_unknown_window_size_is_refused_at_load_not_mid_answer():
    """sherpa-onnx aborts the process on a wrong length rather than raising."""
    with pytest.raises(ValueError):
        endpoint._Stream(FakeModel(700))


def test_a_missing_model_is_explained_not_crashed_on(tmp_path):
    why = endpoint.Silero(model=tmp_path / "absent.onnx").available()
    assert why and "absent.onnx" in why
