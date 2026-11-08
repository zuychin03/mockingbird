"""The provider port. Plan section 9.4, amended by 1c.1-A and V1.1_PLAN P1.

Nothing else in the app talks to a model directly.

The default model runs in llama.cpp's `llama-server` on loopback, started by `app/servers.py`.
Turns go to /v1/chat/completions, which carries `logprobs`, so the enum posterior is logged
every turn, and `timings`, which the periodic canary reads.

`CloudClient` serves the same interface from an OpenAI-compatible vendor, for people who cannot
host the model. It is a separate class on purpose: `LlamaServer` is the measured path and stays
byte-for-byte what it was.

Stdlib HTTP inside a thread rather than httpx: the client really is this small, and the
async signature is what phase 2 needs. Swap the transport, not the interface.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# 127.0.0.1, never "localhost". `localhost` resolves to ::1 first, the server listens only on
# IPv4, and every request then waits ~2s for the IPv6 connection to fail before falling back.
# Measured: 2,109 ms per call against 66 ms. It is invisible in the server's own timings --
# ttft still reads 30 ms -- so only wall-clock timing catches it.
BASE = "http://127.0.0.1:8091"
# Mockingbird deliberately supports one measured model. The server is started with this alias
# and this file, and both are checked before an interview starts.
MODEL = "qwen3-4b-instruct-2507"
MODEL_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
# Every measurement behind the contract was taken under a 1.1 repeat penalty, the previous
# runtime's default; llama-server's is off. Without it 26 of 60 fixture turns came back worded
# differently, with it 10, all near-ties (07/11/2026).
REPEAT_PENALTY = 1.1
TOP_LOGPROBS = 20          # log 7.2
CANARY_WARN_MS = 150.0     # a warm TTFT above this means the GPU clock dropped (log 7.23)
# `clock_ok` watches TTFT, which is PREFILL, and 8.8 measured the turn as essentially all
# DECODE -- warm prefill is ~0 ms while decode runs at 8-16 tok/s throttled. So the check was
# looking at the half that does not matter: running on battery, TTFT stayed at 13 ms and
# reported healthy while throughput fell from 85.6 tok/s to 9.2 (log 9.19). Llama measured
# above 110 tok/s when plugged in, leaving a wide gap above this throttling threshold.
DECODE_FLOOR_TPS = 25.0
TRANSPORT_WARN_MS = 250.0  # wall clock minus what the server says it spent. A healthy
                           # loopback runs 20-40 ms; the IPv6 stall was 2,080 (log 8.6)
CANARY_TOKENS = 8          # not 1: one token is too short to time decode


START_HINT = "Start it with `python -m app.servers`."


class ProviderError(RuntimeError):
    pass


class SetupRequired(ProviderError):
    """Cloud mode is chosen but cannot run yet: no key, or no current acknowledgement. Fixed in
    Settings, not by restarting a server, so it is reported differently from an outage."""


@dataclass
class Completion:
    """One model call. `posterior` is empty unless an enum position was requested and the
    provider returns logprobs; `posterior_note` says why when it could not."""
    text: str
    prompt_tokens: int = 0
    decode_tokens: int = 0
    wall_ms: float = 0.0
    posterior: dict[str, float] = field(default_factory=dict)
    posterior_note: str = ""
    cost_usd: float | None = None
    reasoning_tokens: int = 0
    # Set instead of raising where a caller degrades: the provider's sentence, for the record.
    error: str = ""

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
        raise ProviderError("the model server %s: %s"
                            % (e.code, e.read()[:200].decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise ProviderError("cannot reach the model server at %s (%s). %s"
                            % (BASE, e.reason, START_HINT))
    except (OSError, http.client.HTTPException, ValueError) as e:
        # A read timeout is TimeoutError and a dropped connection a ConnectionError or an
        # http.client error; none is a URLError, and a timeout escaped as a 500 (07/11/2026).
        raise ProviderError("the model server at %s did not answer (%s: %s)"
                            % (BASE, type(e).__name__, e))


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


class LlamaServer:
    """Local provider. Default, and the point of the project."""

    name = "llama-server"
    vendor = None

    def __init__(self, model: str = MODEL, seed: int = 42, timeout: float = 120.0):
        self.model, self.seed, self.timeout = model, seed, timeout

    def describe(self) -> dict[str, Any]:
        return {"mode": "local", "vendor": None, "label": "llama-server", "host": BASE,
                "model": self.model, "measured": self.model == MODEL}

    def _call(self, system, user, schema, max_tokens, enum_field, enum_values) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.0, "seed": self.seed, "stream": False,
            "repeat_penalty": REPEAT_PENALTY,
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
        """Clock, decode and transport health, from the server's own `timings`.

        Sampled, not per turn. Two independent failures, each silent on its own:

        clock      a warm TTFT over CANARY_WARN_MS means the GPU memory clock dropped back
                   to its idle P-state, which quadruples every latency (log 7.23)
        transport  wall clock minus what the server says it spent. `timings` is reported BY
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
            _post("/v1/chat/completions", body, 30.0)
        t0 = time.perf_counter()
        d = _post("/v1/chat/completions", body, 30.0)
        wall = (time.perf_counter() - t0) * 1000
        timings = d.get("timings") or {}
        ttft = timings.get("prompt_ms") or 0
        served = ttft + (timings.get("predicted_ms") or 0)
        transport = wall - served
        tps = timings.get("predicted_per_second") or 0
        return {"ttft_ms": round(ttft, 1),
                "tokens_per_second": round(tps, 1),
                "wall_ms": round(wall, 1),
                "transport_ms": round(transport, 1),
                "clock_ok": ttft <= CANARY_WARN_MS,
                "decode_ok": tps >= DECODE_FLOOR_TPS,
                "transport_ok": transport <= TRANSPORT_WARN_MS}


def served_model() -> dict:
    """What the server is running, from `/props`. Every failure here is a ProviderError too."""
    try:
        with urllib.request.urlopen(BASE + "/props", timeout=20) as r:
            props = json.loads(r.read())
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise ProviderError("cannot reach the model server at %s (%s). %s"
                            % (BASE, getattr(e, "reason", e), START_HINT))
    return {"id": props.get("model_alias"), "path": props.get("model_path"),
            "quantization": props.get("model_ftype"),
            "loaded_context_length": (props.get("default_generation_settings") or {}).get("n_ctx"),
            "runtime": props.get("build_info")}


def product_model(model: dict | None = None) -> dict | None:
    """The served model when it is exactly the supported one, never an alias or a fallback.

    Earlier multi-model runs tried to infer the weights behind an alias from model metadata.
    That became ambiguous when two installed revisions shared the same metadata. The product
    instead requires both its alias and its file to match; a wrong model is rejected before an
    interview starts rather than silently receiving another's controls.
    """
    m = served_model() if model is None else model
    if m.get("id") == MODEL and Path(m.get("path") or "").name == MODEL_FILE:
        return m
    return None


# ---------------------------------------------------------------- cloud (V1.1_PLAN P1)

ROOT = Path(__file__).resolve().parent.parent
CLOUD_MODELS = ROOT / "config" / "cloud_models.json"
CLOUD_TIMEOUT = 30.0
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class Vendor:
    name: str
    label: str
    url: str            # the chat completions endpoint itself
    token_field: str    # OpenAI's reasoning models reject `max_tokens`


VENDORS = {
    "openai": Vendor("openai", "OpenAI", "https://api.openai.com/v1/chat/completions",
                     "max_completion_tokens"),
    "openrouter": Vendor("openrouter", "OpenRouter",
                         "https://openrouter.ai/api/v1/chat/completions", "max_tokens"),
    "gemini": Vendor("gemini", "Google Gemini",
                     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                     "max_tokens"),
    "groq": Vendor("groq", "Groq", "https://api.groq.com/openai/v1/chat/completions",
                   "max_completion_tokens"),
}


@dataclass(frozen=True)
class Profile:
    """What one vendor's model accepts. Capabilities default to the conservative reading: a
    parameter a provider does not take is either rejected (Groq 400s on `logprobs`) or silently
    ignored, and neither may decide a turn."""
    vendor: str
    model: str
    logprobs: bool = False
    seed: bool = False
    temperature: bool = True
    # "none" turns thinking off, "minimal" is the floor where it cannot be (Gemini 3), None
    # sends nothing. A small model that thinks by default cannot meet NFR-1's 1.5 s.
    reasoning: str | None = None
    price_in: float | None = None     # USD per million tokens
    price_out: float | None = None
    measured: bool = False


def host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def _redact(text: str, key: str | None) -> str:
    if key:
        text = text.replace(key, "[key]")
    # Vendors echo part of a rejected key back; never let anything key-shaped through.
    return re.sub(r"\b(sk|gsk|AIza|or)[-_A-Za-z0-9]{12,}", "[key]", text)


USER_AGENT = "Mockingbird (+https://github.com/zuychin03/mockingbird)"
# Free tiers cap tokens per minute (Groq's: 8,000), which background extraction can spend in a
# burst. A wait the vendor names is honoured up to this cap, twice, before the turn degrades.
RETRY_WAIT_CAP_S = 20.0
RATE_RETRIES = 2
_sleep = time.sleep


def _retry_after(headers) -> float:
    """Seconds the vendor asks us to wait: `retry-after`, or Groq's `x-ratelimit-reset-*`
    ("8.45s", "1m26.4s")."""
    for name in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        v = (headers.get(name) if headers else None) or ""
        m = re.fullmatch(r"(?:(\d+)m)?([\d.]+)s?", v.strip())
        if m:
            return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 5.0


def _send(vendor: Vendor, body: dict, key: str | None, timeout: float) -> dict:
    for attempt in range(RATE_RETRIES + 1):
        try:
            return _send_once(vendor, body, key, timeout)
        except _RateLimited as e:
            if attempt == RATE_RETRIES:
                raise ProviderError(str(e)) from None
            _sleep(min(e.wait_s, RETRY_WAIT_CAP_S))
    raise AssertionError("unreachable")


class _RateLimited(Exception):
    def __init__(self, message: str, wait_s: float):
        super().__init__(message)
        self.wait_s = wait_s


def _send_once(vendor: Vendor, body: dict, key: str | None, timeout: float) -> dict:
    # Groq's Cloudflare front rejects urllib's default agent outright (403, error 1010).
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = "Bearer " + key
    if vendor.name == "openrouter":
        # OpenRouter's optional attribution headers; they identify the app, not the user.
        headers["HTTP-Referer"] = "https://github.com/zuychin03/mockingbird"
        headers["X-Title"] = "Mockingbird"
    req = urllib.request.Request(vendor.url, method="POST", data=json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = _redact(e.read()[:400].decode("utf-8", "replace"), key)
        if e.code in (401, 403):
            why = "refused the API key"
        elif e.code == 402:
            why = "says the account is out of credit"
        elif e.code == 404:
            why = "has no model %r, or no endpoint for it with these settings" % body.get("model")
        elif e.code == 429:
            raise _RateLimited("%s is rate limiting this key: %s" % (vendor.label, detail),
                               _retry_after(e.headers))
        else:
            why = "rejected the request (HTTP %d)" % e.code
        raise ProviderError("%s %s: %s" % (vendor.label, why, detail))
    except urllib.error.URLError as e:
        raise ProviderError("cannot reach %s at %s (%s)"
                            % (vendor.label, host(vendor.url), _redact(str(e.reason), key)))
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise ProviderError("%s did not answer (%s: %s)"
                            % (vendor.label, type(e).__name__, _redact(str(e), key)))


class CloudClient:
    """A cloud model behind the same `complete` the runner calls."""

    name = "cloud"

    def __init__(self, profile: Profile, key: str | None, seed: int = 42,
                 timeout: float = CLOUD_TIMEOUT):
        if profile.vendor not in VENDORS:
            raise ValueError("unknown vendor %r; have %s" % (profile.vendor, ", ".join(VENDORS)))
        self.profile, self.vendor = profile, VENDORS[profile.vendor]
        self.model, self.seed, self.timeout = profile.model, seed, timeout
        self._key = key

    def __repr__(self) -> str:
        return "CloudClient(%s, %s)" % (self.vendor.name, self.model)

    def describe(self) -> dict[str, Any]:
        return {"mode": "cloud", "vendor": self.vendor.name, "label": self.vendor.label,
                "host": host(self.vendor.url), "model": self.model,
                "measured": self.profile.measured}

    def body(self, system: str, user: str, schema: dict | None, max_tokens: int,
             enum_field: str | None) -> dict[str, Any]:
        p = self.profile
        b: dict[str, Any] = {
            "model": p.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            self.vendor.token_field: max_tokens, "stream": False,
        }
        if p.temperature:
            b["temperature"] = 0.0
        if p.seed:
            b["seed"] = self.seed
        if schema:
            b["response_format"] = {"type": "json_schema",
                                    "json_schema": {"name": "turn", "strict": True,
                                                    "schema": schema}}
        if enum_field and p.logprobs:
            b["logprobs"] = True
            b["top_logprobs"] = TOP_LOGPROBS
        if self.vendor.name == "openrouter":
            if p.reasoning:
                b["reasoning"] = {"effort": p.reasoning}
            # Skip hosts that would ignore a parameter (the schema above all) rather than
            # route to them, and hosts that may keep or train on what the candidate said.
            b["provider"] = {"require_parameters": True, "data_collection": "deny"}
        elif p.reasoning:
            b["reasoning_effort"] = p.reasoning
        if self.vendor.name == "groq" and p.reasoning:
            # Groq 400s on `raw` reasoning beside a JSON schema, and gpt-oss takes no
            # `reasoning_format` at all, only `include_reasoning` (docs, 08/11/2026).
            if p.model.startswith("openai/gpt-oss"):
                b["include_reasoning"] = False
            else:
                b["reasoning_format"] = "hidden"
        return b

    def _call(self, system, user, schema, max_tokens, enum_field, enum_values) -> Completion:
        t0 = time.perf_counter()
        d = _send(self.vendor, self.body(system, user, schema, max_tokens, enum_field),
                  self._key, self.timeout)
        wall = (time.perf_counter() - t0) * 1000
        try:
            choice = d["choices"][0]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("%s returned no choices: %s"
                                % (self.vendor.label, _redact(json.dumps(d)[:300], self._key)))
        usage = d.get("usage") or {}
        prompt, decode = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
        post, note = {}, ""
        if enum_field and enum_values:
            if not self.profile.logprobs:
                note = "%s does not return logprobs for %s" % (self.vendor.label, self.model)
            else:
                entries = (choice.get("logprobs") or {}).get("content") or []
                post = _posterior(entries, enum_field, enum_values)
                note = "" if post else "no logprobs at the %s position" % enum_field
        cost = usage.get("cost")
        if cost is None and self.profile.price_in is not None:
            cost = (prompt * self.profile.price_in
                    + decode * (self.profile.price_out or 0)) / 1e6
        return Completion(
            text=(choice.get("message") or {}).get("content") or "",
            prompt_tokens=prompt, decode_tokens=decode, wall_ms=round(wall, 1),
            posterior=post, posterior_note=note,
            cost_usd=None if cost is None else round(float(cost), 8),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens") or 0)

    async def complete(self, system: str, user: str, schema: dict | None = None,
                       max_tokens: int = 400, enum_field: str | None = None,
                       enum_values: list[str] | None = None) -> Completion:
        return await asyncio.to_thread(self._call, system, user, schema, max_tokens,
                                       enum_field, enum_values)

    async def warmup(self, system: str, user: str) -> float:
        """Nothing to warm: no prefix cache we control, and a call here would cost money."""
        return 0.0

    def ping(self) -> dict[str, Any]:
        """One short call: does the key work, does the model exist, how long is a round trip."""
        c = self._call("Reply with the word ready.", "ready", None, 16, None, None)
        return {"ok": True, "wall_ms": c.wall_ms, "model": self.model,
                "vendor": self.vendor.label}


def measured_models() -> list[dict]:
    """The models that passed the gate (`config/cloud_models.json`), or none yet."""
    try:
        return json.loads(CLOUD_MODELS.read_text(encoding="utf-8")).get("models") or []
    except (OSError, ValueError):
        return []


_OR_CACHE: dict[str, dict] = {}


def openrouter_profile(model: str) -> Profile:
    """A typed-in OpenRouter model's capabilities, from OpenRouter's public model list. Without
    it a model that cannot turn thinking off, or cannot do a strict schema, would only show up
    as slow or invalid turns mid-interview."""
    if not _OR_CACHE:
        try:
            with urllib.request.urlopen(OPENROUTER_MODELS, timeout=20) as r:
                for m in json.loads(r.read()).get("data") or []:
                    _OR_CACHE[m.get("id", "")] = m
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise ProviderError("cannot read OpenRouter's model list (%s)" % e)
    m = _OR_CACHE.get(model)
    if m is None:
        raise ProviderError("OpenRouter has no model %r" % model)
    params = set(m.get("supported_parameters") or [])
    if "structured_outputs" not in params:
        raise ProviderError("%s does not support strict structured output on OpenRouter, "
                            "which every turn needs" % model)
    r = m.get("reasoning") or {}
    efforts = r.get("supported_efforts")
    if not r:
        reasoning = None
    elif not r.get("mandatory") and (efforts is None or "none" in efforts):
        reasoning = "none"
    else:
        reasoning = "minimal" if "minimal" in (efforts or []) else None
    pricing = m.get("pricing") or {}

    def per_million(v: Any) -> float | None:
        try:
            return round(float(v) * 1e6, 6)
        except (TypeError, ValueError):
            return None

    # `require_parameters` drops every host for a model that does not list a parameter we send,
    # so anything optional is sent only where listed. Reasoning models list no temperature.
    return Profile("openrouter", model, logprobs="logprobs" in params, seed="seed" in params,
                   temperature="temperature" in params, reasoning=reasoning,
                   price_in=per_million(pricing.get("prompt")),
                   price_out=per_million(pricing.get("completion")))


# Models whose settings are known from the vendor's docs but which have no public capability
# list to read them from. Groq's strict-schema models (docs, 08/11/2026): gpt-oss cannot turn
# thinking off, `low` is its floor; qwen3.8 takes `none`. Neither returns logprobs.
KNOWN = {
    ("groq", "qwen/qwen3.8-27b"): Profile("groq", "qwen/qwen3.8-27b", seed=True,
                                          reasoning="none"),
    ("groq", "openai/gpt-oss-20b"): Profile("groq", "openai/gpt-oss-20b", seed=True,
                                            reasoning="low"),
    ("groq", "openai/gpt-oss-120b"): Profile("groq", "openai/gpt-oss-120b", seed=True,
                                             reasoning="low"),
}


def profile_for(vendor: str, model: str) -> Profile:
    for m in measured_models():
        if m.get("vendor") == vendor and m.get("model") == model:
            fields = {k: m[k] for k in Profile.__dataclass_fields__ if k in m}
            return Profile(**{**fields, "measured": True})
    if (vendor, model) in KNOWN:
        return KNOWN[(vendor, model)]
    if vendor == "openrouter":
        return openrouter_profile(model)
    return Profile(vendor, model)


def describe(p) -> dict[str, Any]:
    """What a session records about the provider that served it (FR-42)."""
    p = getattr(p, "inner", p)
    d = getattr(p, "describe", None)
    return d() if d else {"mode": "local", "vendor": None, "label": type(p).__name__,
                          "host": BASE, "model": getattr(p, "model", MODEL), "measured": False}


def is_local(p) -> bool:
    return getattr(getattr(p, "inner", p), "vendor", None) is None


def _cloud(vendor: str, model: str) -> CloudClient:
    from app import secret
    key = secret.load()
    if not key:
        label = VENDORS[vendor].label if vendor in VENDORS else vendor
        raise SetupRequired("cloud mode needs an API key for %s; add one in Settings" % label)
    return CloudClient(profile_for(vendor, model), key)


def current():
    """The provider for the next interview, from Settings. The environment overrides them
    (`MOCKINGBIRD_PROVIDER`, `MOCKINGBIRD_MODEL`, `MOCKINGBIRD_API_KEY`) for source runs and the
    gate. A cloud choice from Settings is refused until its acknowledgement is current: the
    first thing it would send is a job description."""
    from app import settings
    env = (os.environ.get("MOCKINGBIRD_PROVIDER") or "").strip().lower()
    if env:
        if env == "local":
            return LlamaServer()
        model = (os.environ.get("MOCKINGBIRD_MODEL") or "").strip()
        if not model:
            raise ProviderError("MOCKINGBIRD_PROVIDER=%s needs MOCKINGBIRD_MODEL" % env)
        return CloudClient(profile_for(env, model), os.environ.get("MOCKINGBIRD_API_KEY"))
    s = settings.load()
    if s["mode"] != "cloud":
        return LlamaServer()
    if not settings.acknowledged(s):
        raise SetupRequired("cloud mode is chosen but not yet acknowledged; confirm what it "
                            "sends in Settings first")
    return _cloud(s["vendor"], s["model"])


def for_session(recorded: dict | None):
    """The provider an interview was recorded with (V1.1_PLAN D4, D5). An interview never moves
    to another provider because the settings changed after it started; 1.0's sessions recorded
    none and were all local."""
    if not recorded or recorded.get("mode") != "cloud":
        return LlamaServer()
    return _cloud(recorded["vendor"], recorded["model"])


def configured() -> dict[str, Any]:
    """What Settings point at, described without building a client or reading the key."""
    from app import settings
    env = (os.environ.get("MOCKINGBIRD_PROVIDER") or "").strip().lower()
    s = settings.load()
    vendor, model = ((env, os.environ.get("MOCKINGBIRD_MODEL") or "") if env
                     else (s["vendor"], s["model"]) if s["mode"] == "cloud" else ("local", ""))
    if vendor == "local" or vendor not in VENDORS:
        return LlamaServer().describe()
    measured = any(m.get("vendor") == vendor and m.get("model") == model
                   for m in measured_models())
    return {"mode": "cloud", "vendor": vendor, "label": VENDORS[vendor].label,
            "host": host(VENDORS[vendor].url), "model": model, "measured": measured}


def empty_usage() -> dict[str, Any]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": None}


class Metered:
    """Counts every call a session makes, whichever part of the app makes it, into the dict
    the session record carries (FR-41). Everything else passes through to the provider."""

    def __init__(self, inner, usage: dict[str, Any] | None = None):
        self.inner = inner
        self.usage = usage if usage is not None else empty_usage()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def complete(self, *args, **kwargs) -> Completion:
        out = await self.inner.complete(*args, **kwargs)
        u = self.usage
        u["calls"] = u.get("calls", 0) + 1
        u["prompt_tokens"] = u.get("prompt_tokens", 0) + (out.prompt_tokens or 0)
        u["completion_tokens"] = u.get("completion_tokens", 0) + (out.decode_tokens or 0)
        if out.cost_usd is not None:
            u["cost_usd"] = round((u.get("cost_usd") or 0.0) + out.cost_usd, 8)
        return out
