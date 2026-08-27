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


def test_product_model_accepts_only_the_exact_llama_runtime():
    llama = {"id": "llama-3.2-3b-instruct", "state": "loaded"}
    other = {"id": "unsupported-model", "state": "loaded"}

    assert provider.product_model([other, llama]) is llama
    assert provider.product_model([other]) is None


def test_preflight_rejects_a_loaded_non_product_model(monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(provider, "loaded_models", lambda: [
        {"id": "unsupported-model", "state": "loaded"},
    ])

    assert cli._preflight(provider.LMStudio(), skip=True) is None
    assert "llama-3.2-3b-instruct" in capsys.readouterr().out
