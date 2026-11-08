"""Whether this computer can run the interviewer itself (V1.1_PLAN P3).

The local model and the voice together need a 6 GB NVIDIA card: 5,965 of 6,144 MiB at peak. The
NVIDIA driver installs `nvidia-smi` beside itself, so asking it is both the check for a card and
the check for a working driver; anything that goes wrong reads as "no capable GPU".

`MOCKINGBIRD_FORCE_CPU=1` answers "none" on a machine that has one, to try the no-GPU path here.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

# A "6 GB" card reports 6,144 MiB; the margin admits one that reserves a little for the display.
LOCAL_MIN_MIB = 5900
# The voice model alone needs about 2.2 GB of video memory (5,965 MiB at peak beside the 4B,
# which held ~3,740 by itself); this leaves headroom for the display. An estimate.
VOICE_GPU_MIN_MIB = 3000


def parse(output: str) -> dict | None:
    """The first card from `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,
    nounits`, e.g. "NVIDIA GeForce RTX 3060 Laptop GPU, 6144"."""
    for line in output.splitlines():
        name, _, mib = line.rpartition(",")
        try:
            return {"name": name.strip(), "memory_mib": int(mib.strip())}
        except ValueError:
            continue
    return None


@lru_cache(maxsize=1)
def nvidia() -> dict | None:
    if os.environ.get("MOCKINGBIRD_FORCE_CPU"):
        return None
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return parse(r.stdout) if r.returncode == 0 else None


_ASK = object()


def can_run_local(gpu=_ASK) -> bool:
    gpu = nvidia() if gpu is _ASK else gpu
    return bool(gpu) and gpu["memory_mib"] >= LOCAL_MIN_MIB


def voice_on_gpu(gpu=_ASK) -> bool:
    """Whether the voice model can run on the card, and so speak as well as hear."""
    gpu = nvidia() if gpu is _ASK else gpu
    return bool(gpu) and gpu["memory_mib"] >= VOICE_GPU_MIN_MIB


def describe() -> dict:
    gpu = nvidia()
    return {"gpu": gpu, "can_run_local": can_run_local(gpu),
            "forced_cpu": bool(os.environ.get("MOCKINGBIRD_FORCE_CPU"))}
