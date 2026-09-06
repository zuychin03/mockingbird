"""The voice transport: framing, and the socket that carries it.

The engine is faked throughout. What is under test is the plumbing -- that audio survives the
round trip intact, that a turn's audio is bracketed rather than always-on, and that a barge-in
reports what was heard rather than what was sent -- none of which needs a real voice, and all of
which would be untestable if it did.
"""

from __future__ import annotations

import asyncio
import io
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audio  # noqa: E402

pytest.importorskip("fastapi", reason="the web extra is optional; app/ never imports it")
from fastapi.testclient import TestClient  # noqa: E402

from api import main as api  # noqa: E402
from api import voice as voice_mod  # noqa: E402


def tone(seconds: float, rate: int, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakeEngine:
    """Loud, short, and instant. A real voice would make these tests slow and no truer."""

    rate = 22050

    def __init__(self) -> None:
        self.said: list[str] = []

    def warm(self) -> None:
        pass

    def say(self, text: str) -> np.ndarray:
        self.said.append(text)
        return tone(0.4, self.rate)


@pytest.fixture()
def engine(monkeypatch):
    e = FakeEngine()
    monkeypatch.setattr(voice_mod.speech, "engine", lambda *a, **k: e)
    return e


@pytest.fixture()
def client(tmp_path, monkeypatch, engine):
    monkeypatch.setattr(voice_mod, "LOOSE", tmp_path / "voice")
    monkeypatch.setattr(voice_mod, "LIVE", tmp_path / "nothing.json")
    monkeypatch.setattr(voice_mod, "ROOT", tmp_path)
    return TestClient(api.app)


# --- framing ------------------------------------------------------------------------------

def test_pcm_survives_the_round_trip():
    x = tone(0.05, audio.MIC_RATE)
    back = audio.from_int16(audio.to_int16(x))
    assert np.abs(back - x).max() < 1e-4


def test_samples_over_one_are_clipped_not_wrapped():
    # int16 wraps a value past full scale to the opposite sign, and one wrapped sample is an
    # audible click, so this is the difference between loud and broken.
    loud = np.array([2.0, -2.0], dtype=np.float32)
    assert list(audio.from_int16(audio.to_int16(loud)) > 0) == [True, False]


def test_a_partial_frame_is_left_for_next_time():
    x = np.zeros(audio.FRAME_SAMPLES * 2 + 7, dtype=np.float32)
    assert len(audio.frames(x, audio.FRAME_SAMPLES)) == 2


def test_control_frames_never_raise_on_rubbish():
    for junk in ("", "{", "[]", '"hello"', '{"no":"type"}', "null"):
        assert audio.decode(junk)["t"] == "bad"
    assert audio.decode('{"t":"say","text":"hi"}')["t"] == "say"


def test_an_utterance_reports_its_own_length_and_peak():
    u = audio.Utterance()
    u.add(audio.to_int16(tone(0.5, audio.MIC_RATE)))
    u.add(audio.to_int16(tone(0.5, audio.MIC_RATE)))
    assert u.seconds == pytest.approx(1.0, abs=0.01)
    assert u.peak == pytest.approx(0.5, abs=0.01)


def test_the_wav_is_a_real_wav_at_the_declared_rate():
    u = audio.Utterance()
    u.add(audio.to_int16(tone(0.25, audio.MIC_RATE)))
    with wave.open(io.BytesIO(u.wav())) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, audio.MIC_RATE)
        assert w.getnframes() == audio.MIC_RATE // 4


def test_speech_chunks_lose_no_samples():
    sp = audio.Speech(id=1, text="hello", rate=22050, samples=tone(1.0, 22050))
    assert sum(len(c) for c in sp.chunks()) // 2 == len(sp.samples)


# --- what the candidate actually heard --------------------------------------------------

def test_an_uninterrupted_line_was_heard_whole():
    sp = audio.Speech(id=1, text="one two three four", rate=22050, samples=tone(1.0, 22050))
    sp.heard_seconds = 1.0
    assert sp.spoken_text() == ("one two three four", "")


def test_a_cut_line_splits_where_it_was_cut():
    sp = audio.Speech(id=1, text="one two three four", rate=22050, samples=tone(1.0, 22050))
    sp.heard_seconds = 0.5
    heard, unheard = sp.spoken_text()
    assert (heard, unheard) == ("one two", "three four")


def test_a_line_cut_before_it_started_was_heard_not_at_all():
    sp = audio.Speech(id=1, text="one two three four", rate=22050, samples=tone(1.0, 22050))
    sp.heard_seconds = 0.0
    assert sp.spoken_text() == ("", "one two three four")


# --- the socket ---------------------------------------------------------------------------

def test_it_announces_the_frame_size_and_voice_it_expects(client):
    with client.websocket_connect("/api/voice") as ws:
        ready = ws.receive_json()
    assert ready["t"] == "ready"
    assert (ready["frame_ms"], ready["rate"]) == (audio.FRAME_MS, audio.MIC_RATE)
    assert ready["voice"]["engine"] == "piper/sherpa-onnx"


def test_a_turn_is_captured_between_open_and_close(client, tmp_path):
    pcm = audio.to_int16(tone(0.2, audio.MIC_RATE))
    with client.websocket_connect("/api/voice") as ws:
        ws.receive_json()
        ws.send_json({"t": "mic_open"})
        ws.send_bytes(pcm)
        ws.send_bytes(pcm)
        ws.send_json({"t": "mic_close"})
        done = ws.receive_json()
    assert done["t"] == "utterance"
    assert done["seconds"] == pytest.approx(0.4, abs=0.02)
    assert (tmp_path / done["path"]).exists()


def test_audio_outside_a_turn_is_dropped_not_banked(client, tmp_path):
    """Recording between turns would be a local-only product quietly holding the room open."""
    with client.websocket_connect("/api/voice") as ws:
        ws.receive_json()
        ws.send_bytes(audio.to_int16(tone(0.5, audio.MIC_RATE)))
        ws.send_json({"t": "mic_open"})
        ws.send_json({"t": "mic_close"})
        done = ws.receive_json()
    assert done["seconds"] == 0
    assert done["path"] == ""
    assert list((tmp_path / "voice").glob("*.wav")) == []


def test_a_line_is_rendered_and_streamed_as_pcm(client, engine):
    with client.websocket_connect("/api/voice") as ws:
        ws.receive_json()
        ws.send_json({"t": "say", "text": "Tell me about a time you disagreed."})
        head = ws.receive_json()
        got = 0
        while True:
            m = ws.receive()
            if "bytes" in m and m["bytes"] is not None:
                got += len(m["bytes"])
            else:
                tail = audio.decode(m["text"])
                break
    assert head["t"] == "speech" and head["rate"] == engine.rate
    assert head["text"] == "Tell me about a time you disagreed."
    assert tail["t"] == "speech_end" and tail["id"] == head["id"]
    assert got // 2 == int(0.4 * engine.rate)
    assert engine.said == ["Tell me about a time you disagreed."]


def test_an_empty_line_is_not_sent_to_the_engine(client, engine):
    with client.websocket_connect("/api/voice") as ws:
        ws.receive_json()
        ws.send_json({"t": "say", "text": "   "})
        ws.send_json({"t": "mic_open"})
        ws.send_json({"t": "mic_close"})
        assert ws.receive_json()["t"] == "utterance"
    assert engine.said == []


class FakeWS:
    """Enough WebSocket to drive `Link` without a server."""

    def __init__(self) -> None:
        self.sent: list = []

    async def send_text(self, s: str) -> None:
        self.sent.append(audio.decode(s))

    async def send_bytes(self, b: bytes) -> None:
        self.sent.append(b)


@pytest.fixture()
def link(engine):
    return voice_mod.Link(FakeWS(), engine)


def test_a_barge_in_records_where_playback_actually_got_to(link):
    async def go():
        await link.say("one two three four")
        await link.task
        assert link.speech.heard_seconds is None

        await link.on_control({"t": "cut", "id": link.speech.id, "heard_ms": 100})

        # 100 ms of a 400 ms line. The remainder is not deleted -- 12.4 requires it struck
        # through, and the context truncated to what was heard, not to what was sent.
        assert link.speech.heard_seconds == pytest.approx(0.1)
        assert link.speech.spoken_text() == ("one", "two three four")

        # And the split is sent, so the browser renders the server's apportioning rather than
        # working out its own: two implementations would eventually disagree about a
        # transcript that is the artefact of the whole product.
        told = [m for m in link.ws.sent if isinstance(m, dict) and m.get("t") == "interrupted"]
        assert told == [{"t": "interrupted", "id": link.speech.id,
                         "heard": "one", "unheard": "two three four"}]

    asyncio.run(go())


def test_playing_a_line_to_the_end_leaves_nothing_struck_through(link):
    async def go():
        await link.say("one two three four")
        await link.task
        await link.on_control({"t": "played", "id": link.speech.id, "heard_ms": 400})
        assert link.speech.spoken_text() == ("one two three four", "")
        # Nothing was cut, so nothing is struck through and no interruption is announced.
        assert not [m for m in link.ws.sent
                    if isinstance(m, dict) and m.get("t") == "interrupted"]

    asyncio.run(go())


def test_a_cut_for_a_line_that_is_no_longer_playing_is_ignored(link):
    """Two lines in quick succession must not let the first one's cut truncate the second."""
    async def go():
        await link.say("first line")
        await link.task
        first = link.speech.id
        await link.say("second line")
        await link.task
        await link.on_control({"t": "cut", "id": first, "heard_ms": 10})
        assert link.speech.heard_seconds is None

    asyncio.run(go())


def test_rubbish_control_frames_are_answered_not_fatal(client):
    with client.websocket_connect("/api/voice") as ws:
        ws.receive_json()
        ws.send_text("{not json")
        assert ws.receive_json()["t"] == "error"
        ws.send_json({"t": "mic_open"})
        ws.send_json({"t": "mic_close"})
        assert ws.receive_json()["t"] == "utterance"


# --- reading the answer while it is still being given ------------------------------------

def test_the_cut_lands_in_the_quiet_part():
    rate = audio.MIC_RATE
    x = np.concatenate([tone(5.0, rate), np.zeros(int(1.5 * rate), dtype=np.float32),
                        tone(5.0, rate)])
    cut = audio.split_at_pause(x, rate, 3.0, 9.0)
    assert cut is not None
    assert 5.0 * rate < cut < 6.5 * rate, "the boundary should be inside the silence"


def test_a_region_too_short_to_choose_in_says_so():
    assert audio.split_at_pause(tone(0.05, audio.MIC_RATE), audio.MIC_RATE, 0.0, 0.05) is None


class FakeAsr:
    """Instant, and it says which slice it was, so stitching is visible in the result."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def available(self) -> None:
        return None

    def transcribe(self, samples, rate) -> str:
        self.calls.append(len(samples) / rate)
        return "slice%d" % len(self.calls)


@pytest.fixture()
def asr():
    return FakeAsr()


@pytest.fixture()
def hearing_link(engine, asr):
    return voice_mod.Link(FakeWS(), engine, asr)


def sent(link, kind):
    return [m for m in link.ws.sent if isinstance(m, dict) and m.get("t") == kind]


def test_a_short_answer_is_read_in_one_pass_at_the_end(hearing_link, asr):
    async def go():
        await hearing_link.on_control({"t": "mic_open"})
        await hearing_link.on_audio(audio.to_int16(tone(2.0, audio.MIC_RATE)))
        await hearing_link.on_control({"t": "mic_close"})
        assert sent(hearing_link, "partial") == [], "nothing to commit before the end"
        assert [m["text"] for m in sent(hearing_link, "transcript")] == ["slice1"]
        assert asr.calls == [pytest.approx(2.0, abs=0.01)]

    asyncio.run(go())


def test_a_long_answer_is_read_in_slices_while_it_is_still_running(hearing_link, asr):
    rate = audio.MIC_RATE

    async def go():
        await hearing_link.on_control({"t": "mic_open"})
        # loud, a clear pause, loud again: the boundary has somewhere obvious to land
        await hearing_link.on_audio(audio.to_int16(tone(5.0, rate)))
        await hearing_link.on_audio(audio.to_int16(np.zeros(int(1.5 * rate), dtype=np.float32)))
        await hearing_link.on_audio(audio.to_int16(tone(4.0, rate)))
        for _ in range(40):                       # let the reader take its slice
            await asyncio.sleep(0.05)
            if sent(hearing_link, "partial"):
                break
        assert sent(hearing_link, "partial"), "a slice should have been committed mid-answer"
        assert 5.0 < asr.calls[0] < 6.5, "the first slice ended in the pause, not mid-word"
        await hearing_link.on_control({"t": "mic_close"})
        final = sent(hearing_link, "transcript")[-1]["text"]
        assert final.split() == ["slice%d" % (i + 1) for i in range(len(asr.calls))]
        assert sum(asr.calls) == pytest.approx(10.5, abs=0.05), "every second read exactly once"

    asyncio.run(go())


def test_without_a_recogniser_the_turn_still_completes():
    """Recognition is optional; a missing binary must not take the interview with it."""
    async def go():
        link = voice_mod.Link(FakeWS(), FakeEngine(), None)
        await link.on_control({"t": "mic_open"})
        await link.on_audio(audio.to_int16(tone(1.0, audio.MIC_RATE)))
        await link.on_control({"t": "mic_close"})
        assert sent(link, "utterance"), "the recording still happened"
        assert sent(link, "transcript") == [], "and nothing pretended to transcribe it"

    asyncio.run(go())
