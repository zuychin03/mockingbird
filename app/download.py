"""What Mockingbird downloads on first run, from where, and the checksum each file must match.

    python -m app.download                 fetch whatever is missing
    python -m app.download --from DIR ...  take matching files from DIR first

Nothing is trusted on arrival: every file is checked against the SHA-256 recorded here before it
is moved into place, and a mismatch is deleted. Every source is pinned to the exact file the
product was measured with, so a repository re-uploading a file cannot change the interviewer.
That has already happened once: LFM3-Audio's projector was replaced on 29/10/2026, after the
voice was measured, so it is pinned to the revision before.

`--from` is for machines that already hold the files: a match is hard-linked (copied across
volumes) after the same checksum, so it costs no disk.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 1 << 20
# Flushed, so progress reads in order beside pip's output when it is piped to a log.
print = partial(print, flush=True)  # noqa: A001

HF = "https://huggingface.co/%s/resolve/%s/%s"
GH_LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/%s/%s"
QWEN = ("lmstudio-community/Qwen3-4B-Instruct-2507-GGUF", "4edb920b6f14e3b9284d4502a6485103d72cde05")
LFM3 = ("LiquidAI/LFM3-Audio-2B-GGUF", "b0d3187e4ef8f4befd06e0a0af5c7a84ff51e42d")
MINILM = ("second-state/All-MiniLM-L6-v2-Embedding-GGUF", "544f204f2eaa2d71361ffc74d6df7170285b286a")
SILERO = "5cd7945676eb32225748052e2e6a0580e4686a08"     # tag v6.2.3
LLAMA_BUILD = "b11981"


@dataclass(frozen=True)
class Item:
    name: str
    dest: str           # under ROOT; for an archive, the directory it is extracted into
    url: str
    sha256: str
    size: int
    licence: str
    archive: bool = False

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[1]


def _hf(repo: tuple[str, str], name: str) -> str:
    return HF % (repo[0], repo[1], name)


ITEMS = (
    Item("language model", "models/qwen3-4b-instruct-2507/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
         _hf(QWEN, "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
         "8cdb57cbb880d313736a9bc4e3d3d2485f145b5e19cf33783746e753e82641fc", 2497280448,
         "Apache-2.0"),
    Item("voice model", "models/lfm3-audio/LFM3-Audio-2B-Q8_0.gguf",
         _hf(LFM3, "LFM3-Audio-2B-Q8_0.gguf"),
         "d4e36902ba8f0ee7b333596030a59d650f88ac76660b4d9ba5ff77c3c2258fc0", 1846236704,
         "LFM Open License v1.0"),
    Item("voice projector", "models/lfm3-audio/mmproj-LFM3-Audio-2B-BF16.gguf",
         _hf(LFM3, "mmproj-LFM3-Audio-2B-BF16.gguf"),
         "c20fced222c6b7e7bcd32eb0480fad5108f9ea26cadca4f106fac37747868ed9", 570846400,
         "LFM Open License v1.0"),
    Item("voice model licence", "models/lfm3-audio/LICENSE", _hf(LFM3, "LICENSE"),
         "4d28ca14dedc0b3d0fcc2b3339f0e79931faa33874f3d24f522183a8fc70068c", 10574,
         "LFM Open License v1.0"),
    Item("embedder", "models/all-minilm-l6-v2/all-MiniLM-L6-v2-Q8_0.gguf",
         _hf(MINILM, "all-MiniLM-L6-v2-Q8_0.gguf"),
         "263215c3cadd6e16740741a7624ab4cbb6c8e777688bd5331ecfbf5681c2f8ed", 25008064,
         "Apache-2.0"),
    Item("pause detector", "models/vad/silero_vad.onnx",
         "https://github.com/snakers4/silero-vad/raw/%s/src/silero_vad/data/silero_vad.onnx"
         % SILERO,
         "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3", 2327524, "MIT"),
    Item("llama.cpp %s" % LLAMA_BUILD, "runtime/llama.cpp",
         GH_LLAMA % (LLAMA_BUILD, "llama-%s-bin-win-cuda-12.4-x64.zip" % LLAMA_BUILD),
         "dcb0f6be103aec6c55a365be71a678c0cf620f9c85bf9a16de78090edd44ddbb", 279763823, "MIT",
         archive=True),
    Item("CUDA runtime", "runtime/llama.cpp",
         GH_LLAMA % (LLAMA_BUILD, "cudart-llama-bin-win-cuda-12.4-x64.zip"),
         "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6", 391443627,
         "NVIDIA CUDA runtime, redistributable", archive=True),
)

# GPL-3.0, so it is installed from PyPI on the user's machine rather than shipped.
PARSELMOUTH = ("praat-parselmouth==0.4.7 --hash=sha256:"
               "7cfd6941a4e8dd1d8398260f1269a831b84e9f230b03c569993e144a20704f99")


def _marker(item: Item) -> Path:
    return ROOT / item.dest / (".%s.sha256" % item.filename)


def present(item: Item) -> bool:
    if item.archive:
        m = _marker(item)
        return m.exists() and m.read_text(encoding="ascii").strip() == item.sha256
    p = ROOT / item.dest
    return p.exists() and p.stat().st_size == item.size


def missing() -> list[Item]:
    return [i for i in ITEMS if not present(i)]


def parselmouth_missing() -> bool:
    return importlib.util.find_spec("parselmouth") is None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def _human(n: float) -> str:
    if n < 1024:
        return "%d B" % n
    for unit in ("KB", "MB"):
        n /= 1024
        if n < 1024:
            return "%.1f %s" % (n, unit)
    return "%.1f GB" % (n / 1024)


def _fetch(url: str, to: Path, expect: str, size: int, say=print) -> None:
    """Download to `to`, checking the hash as it arrives. Raises on any failure, leaving no file."""
    h = hashlib.sha256()
    got = 0
    step = max(size // 20, CHUNK)
    shown = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mockingbird-setup"})
        with urllib.request.urlopen(req, timeout=60) as r, open(to, "wb") as f:
            while block := r.read(CHUNK):
                f.write(block)
                h.update(block)
                got += len(block)
                if got - shown >= step:
                    shown = got
                    say("  %3d%%  %s of %s" % (100 * got // size, _human(got), _human(size)))
    except (OSError, http.client.HTTPException, ValueError) as e:
        to.unlink(missing_ok=True)
        raise RuntimeError("download failed: %s (%s)" % (url, e)) from e
    if h.hexdigest() != expect:
        to.unlink(missing_ok=True)
        raise RuntimeError("checksum mismatch for %s: got %s, expected %s"
                           % (url, h.hexdigest(), expect))


def _local(item: Item, sources: list[Path]) -> Path | None:
    for src in sources:
        for cand in (src / item.dest, src / item.filename):
            if cand.is_file() and cand.stat().st_size == item.size and sha256(cand) == item.sha256:
                return cand
    return None


def _place(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    os.replace(tmp, dest)


def get(item: Item, found: Path | None = None, say=print) -> None:
    """Put one item in place, from `found` (a checked local copy) when given, else its URL."""
    if not item.archive:
        dest = ROOT / item.dest
        if found:
            say("%s: found at %s" % (item.name, found))
            _place(found, dest)
            return
        say("%s: downloading %s" % (item.name, _human(item.size)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        _fetch(item.url, part, item.sha256, item.size, say)
        os.replace(part, dest)
        return
    target = ROOT / item.dest
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target, prefix=".download-") as tmp:
        zpath = found
        if zpath:
            say("%s: found at %s" % (item.name, found))
        else:
            say("%s: downloading %s" % (item.name, _human(item.size)))
            zpath = Path(tmp) / item.filename
            _fetch(item.url, zpath, item.sha256, item.size, say)
        say("%s: unpacking" % item.name)
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                # Refuse anything that would land outside the target (zip slip).
                if not (target / member).resolve().is_relative_to(target.resolve()):
                    raise RuntimeError("unsafe path in %s: %s" % (item.filename, member))
            z.extractall(target)
    _marker(item).write_text(item.sha256 + "\n", encoding="ascii")


def install_parselmouth(say=print) -> bool:
    """Install the GPL delivery-measurement package from PyPI, hash-pinned. False on failure:
    the interview runs without delivery measurements rather than not at all."""
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "parselmouth.txt"
        req.write_text(PARSELMOUTH + "\n", encoding="ascii")
        say("delivery measurements: installing praat-parselmouth from PyPI")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                            "--only-binary", ":all:", "--require-hashes", "--disable-pip-version-check",
                            "-r", str(req)])
    return r.returncode == 0


def fetch_all(sources: list[Path] = (), say=print) -> list[str]:
    """Everything missing, in order. Returns the failures, empty when all is in place."""
    failures = []
    todo = missing()
    found = {i: _local(i, list(sources)) for i in todo}
    total = sum(i.size for i in todo if not found[i])
    if total:
        say("Mockingbird needs %s of models and runtime, downloaded once." % _human(total))
    if any(i.licence.startswith("LFM") for i in todo):
        say("The voice model is under the LFM Open License v1.0: free to use, but commercial "
            "use is not licensed for organisations with US$10M or more in annual revenue.")
    for item in todo:
        try:
            get(item, found[item], say)
        except (RuntimeError, OSError, zipfile.BadZipFile) as e:
            failures.append("%s: %s" % (item.name, e))
            say("%s: FAILED, %s" % (item.name, e))
    if parselmouth_missing() and not install_parselmouth(say):
        say("delivery measurements: not installed; interviews still run")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="sources", type=Path, nargs="*", default=[],
                    help="directories to take matching files from before downloading")
    a = ap.parse_args()
    failures = fetch_all(a.sources)
    if failures:
        print("\nNot everything arrived; running this again fetches only what is still missing.")
        return 1
    print("Everything is in place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
