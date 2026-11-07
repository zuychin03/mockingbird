"""LFM3-Audio-2B through llama.cpp's `llama-server`: one resident process that both hears and speaks.

The engine behind both voice ports. Nothing above `app/listen.py` and `app/speech.py` knows it.

The model can also run the whole conversation itself over `/v1/realtime`. That is deliberately
not wired in: its speech would reach the candidate without passing `guards.apply()` or the
runner's policy.

Started before the app with the other model servers (`python -m app.servers`). It fits beside
the language model on a 6 GB card in either load order: 5965 of 6144 MiB at peak.
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "models" / "lfm3-audio"
MODEL = DIR / "LFM3-Audio-2B-Q8_0.gguf"
MMPROJ = DIR / "mmproj-LFM3-Audio-2B-BF16.gguf"
PORT = 8092
BASE = "http://127.0.0.1:%d" % PORT
CONTEXT = 8192             # covers a capped answer

# Model card contracts: the ASR system prompt, and the TTS voices and locales llama.cpp maps.
ASR_PROMPT = "Perform ASR in English."
VOICES = ("female", "male")
DEFAULT_VOICE = "female"
LANG = "en"
# Fixed so a line renders the same way twice; the server's default (-1) re-rolls every call.
SEED = 7
TIMEOUT = 300

THINK = re.compile(r"<think>.*?</think>", re.S)


def _post(base: str, path: str, body: dict, timeout: float = TIMEOUT):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def health(base: str = BASE) -> str | None:
    """Why the server cannot be used, or None."""
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            if r.status == 200:
                return None
            return "llama-server answered %d on %s/health" % (r.status, base)
    except urllib.error.HTTPError as e:
        # 503 while the model is still loading.
        return "llama-server is not ready on %s (%d)" % (base, e.code)
    except (OSError, ValueError):
        return ("llama-server is not running on %s (start it with `python -m app.servers`)"
                % base)


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class Listener:
    """The ASR port over `/v1/chat/completions` with an `input_audio` part."""

    def __init__(self, base: str = BASE) -> None:
        self.base = base

    def available(self) -> str | None:
        return health(self.base)

    def transcribe(self, samples: np.ndarray, rate: int) -> str:
        if len(samples) < rate // 10:
            return ""
        audio = base64.b64encode(wav_bytes(samples, rate)).decode("ascii")
        body = {"messages": [
                    {"role": "system", "content": ASR_PROMPT},
                    {"role": "user", "content": [
                        {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}]}],
                "temperature": 0, "max_tokens": 1024}
        try:
            with _post(self.base, "/v1/chat/completions", body) as r:
                reply = json.loads(r.read())
            text = reply["choices"][0]["message"].get("content") or ""
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return ""
        return THINK.sub("", text).strip()


class Speaker:
    """The TTS port over llama-server's `/tts`."""

    def __init__(self, voice: str = DEFAULT_VOICE, base: str = BASE) -> None:
        if voice not in VOICES:
            raise ValueError("unknown voice %r; have %s" % (voice, ", ".join(VOICES)))
        self.voice = voice
        self.base = base
        self.rate = 24000

    def warm(self) -> None:
        why = health(self.base)
        if why:
            raise RuntimeError(why)
        self.say("Ready.")

    def say(self, text: str) -> np.ndarray:
        body = {"input": text, "voice": self.voice, "lang": LANG, "seed": SEED,
                "response_format": "pcm"}
        try:
            with _post(self.base, "/tts", body) as r:
                kind = r.headers.get("Content-Type", "")
                data = r.read()
        except (OSError, ValueError) as e:
            raise RuntimeError("LFM3 speech failed: %s" % (health(self.base) or e)) from e
        m = re.search(r"rate=(\d+)", kind)
        if m:
            self.rate = int(m.group(1))
        return np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4").copy()


def describe_voice(voice: str | None = None) -> dict:
    return {"engine": "lfm3-audio/llama.cpp", "voice": voice or DEFAULT_VOICE, "lang": LANG,
            "seed": SEED, "model": MODEL.name, "mmproj": MMPROJ.name,
            "python": sys.version.split()[0]}


def describe_asr() -> dict:
    return {"engine": "lfm3-audio/llama.cpp", "model": MODEL.name, "mmproj": MMPROJ.name,
            "prompt": ASR_PROMPT, "verbatim": True}
