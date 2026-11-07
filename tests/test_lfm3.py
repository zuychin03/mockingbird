"""The LFM3-Audio adapters, against a stand-in llama-server on loopback.

What is under test is the contract with the server and with the two ports: the request each
adapter sends, what it makes of the reply, and how it fails. Recognition and voice quality need
the real model and are measured against it, not here.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import lfm3, listen, speech  # noqa: E402


class Stub:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.status = 200
        self.content = "Hello there."
        self.pcm = np.linspace(-0.5, 0.5, 2400, dtype="<f4")


@pytest.fixture()
def stub():
    s = Stub()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(s.status)
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            s.requests.append((self.path, body))
            if s.status != 200:
                self.send_response(s.status)
                self.end_headers()
                return
            if self.path == "/tts":
                data = s.pcm.tobytes()
                kind = "audio/pcm;rate=24000;encoding=float;bits=32"
            else:
                data = json.dumps({"choices": [{"message": {"content": s.content}}]}).encode()
                kind = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s.base = "http://127.0.0.1:%d" % server.server_address[1]
    yield s
    server.shutdown()


def tone(seconds: float, rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# --- choosing the engine -----------------------------------------------------------------

def test_both_ports_are_served_by_lfm3():
    assert isinstance(listen.engine(), lfm3.Listener)
    assert isinstance(speech.engine(), lfm3.Speaker)
    assert speech.engine("male").voice == "male"
    assert speech.DEFAULT_VOICE in speech.VOICES


def test_a_session_records_which_engine_it_used():
    assert listen.describe()["engine"] == "lfm3-audio/llama.cpp"
    voice = speech.describe()
    assert (voice["engine"], voice["voice"], voice["seed"]) == (
        "lfm3-audio/llama.cpp", "female", lfm3.SEED)


def test_the_server_is_reached_by_loopback_address():
    assert lfm3.BASE.startswith("http://127.0.0.1:")
    assert "--parallel" in lfm3.command() and "127.0.0.1" in lfm3.command()


# --- hearing -----------------------------------------------------------------------------

def test_a_slice_is_sent_as_a_wav_at_its_own_rate(stub):
    text = lfm3.Listener(stub.base).transcribe(tone(1.0), 16000)
    assert text == "Hello there."
    path, body = stub.requests[0]
    assert path == "/v1/chat/completions"
    assert body["messages"][0] == {"role": "system", "content": lfm3.ASR_PROMPT}
    assert body["temperature"] == 0
    part = body["messages"][1]["content"][0]
    with wave.open(io.BytesIO(base64.b64decode(part["input_audio"]["data"]))) as w:
        assert (w.getframerate(), w.getnframes(), w.getnchannels()) == (16000, 16000, 1)


def test_a_slice_too_short_to_hold_a_word_never_reaches_the_server(stub):
    assert lfm3.Listener(stub.base).transcribe(tone(0.05), 16000) == ""
    assert stub.requests == []


def test_a_reasoning_block_is_not_part_of_the_transcript(stub):
    stub.content = "<think>\nshort\n</think>\n\nWe split the table by region."
    assert lfm3.Listener(stub.base).transcribe(tone(1.0), 16000) == "We split the table by region."


@pytest.mark.parametrize("status", [500, 503])
def test_a_failed_read_is_an_empty_slice_not_an_exception(stub, status):
    stub.status = status
    assert lfm3.Listener(stub.base).transcribe(tone(1.0), 16000) == ""


def test_a_server_that_is_not_there_is_reported_before_the_session():
    why = lfm3.Listener("http://127.0.0.1:9").available()
    assert why and "python -m app.lfm3" in why
    assert lfm3.Listener("http://127.0.0.1:9").transcribe(tone(1.0), 16000) == ""


def test_a_running_server_is_available(stub):
    assert lfm3.Listener(stub.base).available() is None


# --- speaking ----------------------------------------------------------------------------

def test_a_line_comes_back_as_float_samples_at_the_declared_rate(stub):
    s = lfm3.Speaker("male", stub.base)
    samples = s.say("Tell me about a time you disagreed.")
    assert s.rate == 24000
    assert samples.dtype == np.float32 and len(samples) == 2400
    assert np.allclose(samples, stub.pcm)
    path, body = stub.requests[0]
    assert path == "/tts"
    assert body == {"input": "Tell me about a time you disagreed.", "voice": "male",
                    "lang": lfm3.LANG, "seed": lfm3.SEED, "response_format": "pcm"}


def test_a_voice_the_model_does_not_have_is_refused_at_construction():
    with pytest.raises(ValueError):
        lfm3.Speaker("narrator")


def test_speech_that_cannot_be_rendered_says_why():
    with pytest.raises(RuntimeError, match="not running"):
        lfm3.Speaker(base="http://127.0.0.1:9").say("Hello.")
    with pytest.raises(RuntimeError, match="not running"):
        lfm3.Speaker(base="http://127.0.0.1:9").warm()


def test_warming_renders_once_so_the_first_line_does_not_pay_for_it(stub):
    lfm3.Speaker("female", stub.base).warm()
    assert [p for p, _ in stub.requests] == ["/tts"]
