"""The three local model servers, each a llama.cpp `llama-server` on loopback with one slot.

    python -m app.servers

starts whichever is not already answering, in order, and stays up until it is closed or
stopped, which stops what it started.

  language model  qwen3-4b-instruct-2507  127.0.0.1:8091  required
  voice           LFM3-Audio-2B           127.0.0.1:8092  speech both ways, `app/lfm3.py`
  embedder        all-MiniLM-L6-v2        127.0.0.1:8093  optional, CPU only

All three fit a 6 GB card: 5,856 MiB with the language model and the voice resident, and the
embedder takes no GPU memory at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app import embed, lfm3, provider

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
# Where `python -m app.download` puts the llama.cpp release; the variable points elsewhere.
BINARY = Path(os.environ.get("MOCKINGBIRD_LLAMA_SERVER",
                             ROOT / "runtime" / "llama.cpp" / "llama-server.exe"))
LLM_FILE = MODELS / "qwen3-4b-instruct-2507" / provider.MODEL_FILE
EMBED_FILE = MODELS / "all-minilm-l6-v2" / "all-MiniLM-L6-v2-Q8_0.gguf"
READY_SECONDS = 120


@dataclass(frozen=True)
class Server:
    name: str
    base: str
    files: tuple[Path, ...]
    args: tuple[str, ...]
    required: bool = False


# The flags the product's measurements were taken under: flash attention, f16 KV cache,
# 2048/512 batches, six threads. Decisions matched on 176 of 178 fixtures and real answers.
LLM = Server("language model", provider.BASE, (LLM_FILE,), (
    "-m", str(LLM_FILE), "--alias", provider.MODEL, "-c", "8192", "-ngl", "99",
    "-b", "2048", "-ub", "512", "-t", "6", "-ctk", "f16", "-ctv", "f16", "-fa", "on", "-kvu",
    "--jinja"), required=True)
VOICE = Server("voice", lfm3.BASE, (lfm3.MODEL, lfm3.MMPROJ), (
    "-m", str(lfm3.MODEL), "--mmproj", str(lfm3.MMPROJ), "-c", str(lfm3.CONTEXT), "-ngl", "99",
    "--jinja"))
# Scores matched the GPU-served copy to within 0.006 over 60 probe pairs, at 11 ms a pair.
EMBEDDER = Server("embedder", embed.BASE, (EMBED_FILE,), (
    "-m", str(EMBED_FILE), "--embedding", "-c", "512", "-ngl", "0", "--device", "none"))
ALL = (LLM, VOICE, EMBEDDER)


def command(s: Server) -> list[str]:
    # --parallel 1: more slots split the context between them.
    port = s.base.rsplit(":", 1)[1]
    return [str(BINARY), *s.args, "--host", "127.0.0.1", "--port", port, "--parallel", "1",
            "--no-webui"]


def healthy(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/health", timeout=2) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def missing(s: Server) -> list[Path]:
    return [f for f in (BINARY, *s.files) if not f.exists()]


def _wait(s: Server, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if healthy(s.base):
            return True
        time.sleep(1)
    return False


Started = list[tuple[Server, subprocess.Popen]]


def start(log=None) -> tuple[Started, str | None]:
    """Start whichever servers are not already answering, one at a time. Returns what was
    started, and why the required one could not be when it could not. `log` takes the servers'
    output instead of the console."""
    started: Started = []
    for s in ALL:
        if healthy(s.base):
            print("%s: already running on %s" % (s.name, s.base), flush=True)
            continue
        if gone := missing(s):
            why = "%s: not started, missing %s" % (s.name, ", ".join(map(str, gone)))
            print(why, flush=True)
            if s.required:
                return started, why
            continue
        print("%s: starting on %s" % (s.name, s.base), flush=True)
        proc = subprocess.Popen(command(s), stdout=log, stderr=subprocess.STDOUT if log else None)
        started.append((s, proc))
        # One at a time, so a load failure is this server's and not a contended allocation.
        if not _wait(s, proc):
            why = "%s: did not become ready" % s.name
            print(why, flush=True)
            if s.required:
                return started, why
            continue
        print("%s: ready" % s.name, flush=True)
    return started, None


def stop(started: Started) -> None:
    for _, p in started:
        if p.poll() is None:
            p.terminate()


def main() -> int:
    started: Started = []
    try:
        started, why = start()
        if why or not started:
            return 1 if why else 0
        while any(p.poll() is None for _, p in started):
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        stop(started)


if __name__ == "__main__":
    sys.exit(main())
