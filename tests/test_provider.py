"""The canary, and specifically the failure it could not see before.

`stats` is reported by the server about the server. It read TTFT 30 ms and 51.6 tok/s for the
whole of Tier 1 while every request actually took 2.1 s, because the time went on an IPv6
connection timing out before the request ever landed (log 8.6). A health check built only on
`stats` is green through that. These pin the wall-clock term that catches it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import provider  # noqa: E402

HEALTHY = {"stats": {"time_to_first_token": 0.030, "tokens_per_second": 51.6,
                     "generation_time": 0.035}}


def _canary(monkeypatch, stall_s=0.0, stats=None):
    def fake_post(path, body, timeout):
        if stall_s:
            time.sleep(stall_s)
        return {"stats": stats} if stats is not None else HEALTHY

    monkeypatch.setattr(provider, "_post", fake_post)
    return provider.LMStudio().canary(warm=False)


def test_healthy_call_passes_both_checks(monkeypatch):
    c = _canary(monkeypatch)
    assert c["clock_ok"] and c["transport_ok"]
    assert c["transport_ms"] < provider.TRANSPORT_WARN_MS


def test_ipv6_stall_is_caught_although_stats_look_perfect(monkeypatch):
    """The regression test for log 8.6: server metrics healthy, wall clock is not."""
    c = _canary(monkeypatch, stall_s=0.4)
    assert c["ttft_ms"] == 30.0 and c["tokens_per_second"] == 51.6
    assert c["clock_ok"], "the clock check cannot see a transport fault, by construction"
    assert not c["transport_ok"]
    assert c["transport_ms"] > 300


def test_idle_gpu_clock_is_caught(monkeypatch):
    c = _canary(monkeypatch, stats={"time_to_first_token": 0.194, "tokens_per_second": 12.4,
                                    "generation_time": 0.200})
    assert not c["clock_ok"]
    assert c["transport_ok"], "a slow server is not a transport fault"


def test_missing_stats_block_does_not_raise(monkeypatch):
    c = _canary(monkeypatch, stats={})
    assert c["ttft_ms"] == 0.0 and c["clock_ok"]


def test_warm_up_call_is_spent_before_measuring(monkeypatch):
    """Without it, preflight on a cold model reads 150 ms and cries GPU throttle."""
    calls = []

    def fake_post(path, body, timeout):
        calls.append(body["max_tokens"])
        return HEALTHY

    monkeypatch.setattr(provider, "_post", fake_post)
    provider.LMStudio().canary()
    assert calls == [provider.CANARY_TOKENS, provider.CANARY_TOKENS]


# ------------------------------------- the instance alias (log 9.24)
CATALOGUE = [
    {"id": "live-llm", "publisher": "MaziyarPanahi", "arch": "llama",
     "quantization": "Q4_K_S", "max_context_length": 4096, "state": "loaded"},
    {"id": "yi-1.5-6b-chat", "publisher": "MaziyarPanahi", "arch": "llama",
     "quantization": "Q4_K_S", "max_context_length": 4096, "state": "not-loaded"},
    # Same publisher, arch and quant as Yi on the real disk. This is why the context ceiling
    # is part of the key rather than a fourth field that looked nice.
    {"id": "mistral-7b-instruct-v0.3", "publisher": "MaziyarPanahi", "arch": "llama",
     "quantization": "Q4_K_S", "max_context_length": 32768, "state": "not-loaded"},
    {"id": "granite-4.1-3b", "publisher": "ibm-granite", "arch": "granitemoe",
     "quantization": "Q4_K_M", "max_context_length": 131072, "state": "not-loaded"},
]


def test_the_alias_resolves_to_the_model_that_is_actually_loaded():
    """`--identifier live-llm` made every model look unknown, so a Yi session silently ran
    granite's speech profile and provenance stored an id nothing can be reproduced from."""
    assert provider.model_key(CATALOGUE[0], CATALOGUE) == "yi-1.5-6b-chat"


def test_an_unaliased_model_resolves_to_itself():
    loaded = dict(CATALOGUE[3], state="loaded")
    assert provider.model_key(loaded, [loaded]) == "granite-4.1-3b"


def test_an_ambiguous_match_keeps_the_alias_rather_than_guessing():
    """Two catalogue entries agreeing on publisher, arch and quant cannot be told apart. The
    identifier is wrong but visible; a coin-flip between two models is wrong and silent."""
    twin = dict(CATALOGUE[1], id="yi-1.5-6b-chat-copy")
    assert provider.model_key(CATALOGUE[0], CATALOGUE + [twin]) == "live-llm"


def test_a_model_absent_from_the_catalogue_keeps_the_alias():
    assert provider.model_key(CATALOGUE[0], [CATALOGUE[0]]) == "live-llm"
