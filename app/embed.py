"""Sentence similarity for probe de-duplication. Local, optional, and never load-bearing.

`focus.rewords` catches a probe that re-asks the previous one when the two share a content
word. It cannot catch the same question asked in different words -- "which parts of the
codebase were most relevant" and "those paths" are one question with no token in common -- and
every deterministic proxy for that was measured and rejected (causal markers carry no signal
against their own base rate; focus adjacency alone is 42% false positives).

This is the semantic test those needed. It runs against the LM Studio instance already on
127.0.0.1, so nothing leaves the machine and no package is added.

**It is optional by construction.** Every entry point returns None when the model is not
loaded, and `rewords` falls back to the word-overlap test. An interview must not fail, or
behave differently in kind, because a second model is absent.

Model choice was measured rather than taken from a leaderboard, on 22 labelled probe pairs
from the stored sessions:

    all-MiniLM-L6-v2   22M    AUC 0.893   <- selected
    nomic-embed-v1.5   137M   AUC 0.848
    mxbai-embed-large  335M   AUC 0.830
    bge-small-en-v1.5  33M    AUC 0.812
    embeddinggemma     300M   AUC 0.670

Size is ANTI-correlated with performance here, and the reason is the task: the larger models
are tuned for asymmetric retrieval, where a short query is matched to a long document, while
this compares two questions of the same shape and length. MiniLM's training objective is that
symmetric comparison. Task prefixes, which those models want for retrieval, measured WORSE for
the same reason and are not used.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .provider import BASE

MODEL = "text-embedding-all-minilm-l6-v2-embedding"

# Above this, two probes on confusable focuses are the same question. Chosen from 17 stored
# pairs the confusable gate admits: the redundant ones score 0.267-0.794 and the rest
# 0.078-0.323, so this clears every non-redundant pair and recovers the two the word-overlap
# test cannot see. The margin over the highest non-redundant pair is 0.007, which is thin and
# fitted to one rater's labels -- treat it as provisional and re-measure it against T2.5's
# calibration set rather than trusting it to generalise.
SIMILAR = 0.33

_CACHE: dict[str, list[float] | None] = {}
_AVAILABLE: bool | None = None


def _vector(text: str) -> list[float] | None:
    key = " ".join((text or "").split())
    if not key:
        return None
    if key in _CACHE:
        return _CACHE[key]
    body = json.dumps({"model": MODEL, "input": key}).encode()
    req = urllib.request.Request(BASE + "/v1/embeddings", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            vec = json.loads(r.read())["data"][0]["embedding"]
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError):
        # Absent, unloadable or malformed all mean the same thing to the caller.
        vec = None
    _CACHE[key] = vec
    return vec


def available() -> bool:
    """Whether the embedding model answers. Probed once, then remembered -- a per-turn check
    would put a network round trip on the decision path to learn something that does not
    change during a session."""
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = _vector("ready") is not None
    return _AVAILABLE


def similarity(first: str, second: str) -> float | None:
    """Cosine similarity, or None if the model is unavailable.

    The availability check is here rather than at the call site so that constructing a Runner
    costs no network round trip, and so a caller can hold a reference to this function without
    having decided yet whether it will work."""
    if not available():
        return None
    a, b = _vector(first), _vector(second)
    if not a or not b:
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else None


def reset() -> None:
    """Drop the cache and the availability verdict. For tests."""
    _CACHE.clear()
    global _AVAILABLE
    _AVAILABLE = None
