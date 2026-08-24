"""The provider port. Plan section 9.4, amended by 1c.1-A.

Nothing else in the app talks to a model directly.

Two LM Studio endpoints, because neither is sufficient alone (log 7.1):
  /v1        carries `logprobs`, and nothing else does
  /api/v0    carries `stats.time_to_first_token`, and nothing else does

Turns go to /v1 so the enum posterior can be logged every turn. The prefix-cache canary
is a periodic /api/v0 health check instead of riding along on each turn.

Stdlib HTTP inside a thread rather than httpx: the client really is this small, and the
async signature is what phase 2 needs. Swap the transport, not the interface.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

# 127.0.0.1, never "localhost". `localhost` resolves to ::1 first, LM Studio listens only
# on IPv4, and every request then waits ~2s for the IPv6 connection to fail before falling
# back. Measured: 2,109 ms per call against 66 ms. It is invisible in LM Studio's own
# `stats` -- ttft still reads 30 ms -- so only wall-clock timing catches it.
BASE = "http://127.0.0.1:1234"
MODEL = "mockingbird-llm"
TOP_LOGPROBS = 20          # server rejects anything higher (log 7.2)
CANARY_WARN_MS = 150.0     # a warm TTFT above this means the GPU clock dropped (log 7.23)
TRANSPORT_WARN_MS = 250.0  # wall clock minus what the server says it spent. A healthy
                           # loopback runs 20-40 ms; the IPv6 stall was 2,080 (log 8.6)
CANARY_TOKENS = 8          # not 1: at one token `generation_time` rounds to zero and the
                           # server reports `tokens_per_second` as 1e6


class ProviderError(RuntimeError):
    pass


@dataclass
class Completion:
    """One model call. `posterior` is empty unless an enum position was requested."""
    text: str
    prompt_tokens: int = 0
    decode_tokens: int = 0
    wall_ms: float = 0.0
    posterior: dict[str, float] = field(default_factory=dict)

    def json(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.text)
        except (json.JSONDecodeError, TypeError):
            return None


class Provider(Protocol):
    async def complete(self, system: str, user: str, schema: dict | None = None,
                       max_tokens: int = 400, enum_field: str | None = None,
                       enum_values: list[str] | None = None) -> Completion: ...


def _post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        BASE + path, method="POST", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ProviderError("LM Studio %s: %s" % (e.code, e.read()[:200].decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise ProviderError("cannot reach LM Studio at %s (%s)" % (BASE, e.reason))


def _posterior(entries: list[dict], field_name: str, values: list[str]) -> dict[str, float]:
    """Renormalised mass per enum value at `field_name`'s value position.

    Reported logprobs are PRE-grammar-mask and one value can be reached by several token
    paths -- `probe` arrives as 'probe'/'pro'/'prob' (log 7.2). So: locate the position,
    aggregate by value, renormalise. A value absent from the capped top-k is ~0, not an error.
    """
    acc, idx = "", -1
    needle = '"%s":"' % field_name
    for i, e in enumerate(entries):
        if acc.replace(" ", "").endswith(needle):
            idx = i
            break
        acc += e.get("token", "")
    if idx < 0:
        return {}

    agg: dict[str, float] = {}
    for alt in entries[idx].get("top_logprobs") or []:
        tok = alt.get("token", "").strip().strip('"')
        if not tok:
            continue
        for v in values:
            if v.startswith(tok):
                agg[v] = agg.get(v, 0.0) + math.exp(alt["logprob"])
                break
    total = sum(agg.values())
    return {k: v / total for k, v in agg.items()} if total > 0 else {}


class LMStudio:
    """Local provider. Default, and the point of the project."""

    name = "lmstudio"

    def __init__(self, model: str = MODEL, seed: int = 42, timeout: float = 120.0):
        self.model, self.seed, self.timeout = model, seed, timeout

    def _call(self, system, user, schema, max_tokens, enum_field, enum_values) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.0, "seed": self.seed, "stream": False,
        }
        if schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "turn", "strict": True,
                                                       "schema": schema}}
        if enum_field:
            body["logprobs"] = True
            body["top_logprobs"] = TOP_LOGPROBS

        t0 = time.perf_counter()
        d = _post("/v1/chat/completions", body, self.timeout)
        wall = (time.perf_counter() - t0) * 1000

        choice = d["choices"][0]
        usage = d.get("usage") or {}
        post = {}
        if enum_field and enum_values:
            entries = (choice.get("logprobs") or {}).get("content") or []
            post = _posterior(entries, enum_field, enum_values)
        return Completion(
            text=choice["message"].get("content") or "",
            prompt_tokens=usage.get("prompt_tokens") or 0,
            decode_tokens=usage.get("completion_tokens") or 0,
            wall_ms=round(wall, 1),
            posterior=post,
        )

    async def complete(self, system: str, user: str, schema: dict | None = None,
                       max_tokens: int = 400, enum_field: str | None = None,
                       enum_values: list[str] | None = None) -> Completion:
        return await asyncio.to_thread(self._call, system, user, schema, max_tokens,
                                       enum_field, enum_values)

    async def warmup(self, system: str, user: str) -> float:
        """Put the real system prompt in llama.cpp's prefix cache before the session starts.

        The canary's tiny "ready" call wakes the weights and the GPU clocks, and cannot touch
        this: the cache is keyed on the prompt, so only a request carrying OUR ~430-token
        system prompt prefills it. Measured cost of not doing this is ~1,277 ms on turn 0 --
        the first thing a candidate ever waits for (log 8.14).

        One token out, because the decode is not what is being warmed.
        """
        t0 = time.perf_counter()
        await self.complete(system, user, max_tokens=1)
        return round((time.perf_counter() - t0) * 1000, 1)

    def canary(self, warm: bool = True) -> dict[str, Any]:
        """Clock and transport health, on /api/v0 because /v1 omits `stats`.

        Sampled, not per turn. Two independent failures, each silent on its own:

        clock      a warm TTFT over CANARY_WARN_MS means the GPU memory clock dropped back
                   to its idle P-state, which quadruples every latency (log 7.23)
        transport  wall clock minus what the server says it spent. `stats` is reported BY
                   the server ABOUT the server, so it reads healthy through anything that
                   goes wrong before the request lands -- DNS, connection setup, a proxy.
                   The `localhost` IPv6 stall put 2,080 ms here while TTFT read 30 ms, and
                   no server-side metric could see it (log 8.6).

        CANARY_WARN_MS is a WARM threshold, and preflight runs at the coldest moment there
        is. Measured on an idle model: first call 150 ms, settling to 34-59 ms. So the first
        call is spent and discarded, or a healthy machine gets told to check its GPU.
        """
        body = {"model": self.model, "messages": [{"role": "user", "content": "ready"}],
                "max_tokens": CANARY_TOKENS, "temperature": 0.0, "seed": self.seed,
                "stream": False}
        if warm:
            _post("/api/v0/chat/completions", body, 30.0)
        t0 = time.perf_counter()
        d = _post("/api/v0/chat/completions", body, 30.0)
        wall = (time.perf_counter() - t0) * 1000
        stats = d.get("stats") or {}
        ttft = (stats.get("time_to_first_token") or 0) * 1000
        served = max(ttft, (stats.get("generation_time") or 0) * 1000)
        transport = wall - served
        return {"ttft_ms": round(ttft, 1),
                "tokens_per_second": round(stats.get("tokens_per_second") or 0, 1),
                "wall_ms": round(wall, 1),
                "transport_ms": round(transport, 1),
                "clock_ok": ttft <= CANARY_WARN_MS,
                "transport_ok": transport <= TRANSPORT_WARN_MS}


def loaded_models() -> list[dict]:
    """Every failure in this module surfaces as ProviderError, including this one."""
    try:
        with urllib.request.urlopen(BASE + "/api/v0/models", timeout=20) as r:
            return [m for m in json.loads(r.read())["data"] if m.get("state") == "loaded"]
    except urllib.error.URLError as e:
        raise ProviderError("cannot reach LM Studio at %s (%s). Is `lms server start` running?"
                            % (BASE, getattr(e, "reason", e)))
