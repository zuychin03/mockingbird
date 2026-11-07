"""The provider: its canary, the exact-model gate, and how its failures surface.

The server's `timings` are reported by the server about the server. They read TTFT 30 ms and
51.6 tok/s for the whole of Tier 1 while every request actually took 2.1 s, because the time
went on an IPv6 connection timing out before the request ever landed (log 8.6). A health check
built only on them is green through that. The canary tests pin the wall-clock term that
catches it.
"""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import provider  # noqa: E402

HEALTHY = {"timings": {"prompt_ms": 30.0, "predicted_ms": 5.0,
                       "predicted_per_second": 51.6}}


def _canary(monkeypatch, stall_s=0.0, timings=None):
    def fake_post(path, body, timeout):
        if stall_s:
            time.sleep(stall_s)
        return {"timings": timings} if timings is not None else HEALTHY

    monkeypatch.setattr(provider, "_post", fake_post)
    return provider.LlamaServer().canary(warm=False)


def test_healthy_call_passes_both_checks(monkeypatch):
    c = _canary(monkeypatch)
    assert c["clock_ok"] and c["transport_ok"]
    assert c["transport_ms"] < provider.TRANSPORT_WARN_MS


def test_ipv6_stall_is_caught_although_timings_look_perfect(monkeypatch):
    """The regression test for log 8.6: server metrics healthy, wall clock is not."""
    c = _canary(monkeypatch, stall_s=0.4)
    assert c["ttft_ms"] == 30.0 and c["tokens_per_second"] == 51.6
    assert c["clock_ok"], "the clock check cannot see a transport fault, by construction"
    assert not c["transport_ok"]
    assert c["transport_ms"] > 300


def test_idle_gpu_clock_is_caught(monkeypatch):
    c = _canary(monkeypatch, timings={"prompt_ms": 194.0, "predicted_ms": 6.0,
                                      "predicted_per_second": 12.4})
    assert not c["clock_ok"]
    assert c["transport_ok"], "a slow server is not a transport fault"


def test_missing_timings_block_does_not_raise(monkeypatch):
    c = _canary(monkeypatch, timings={})
    assert c["ttft_ms"] == 0.0 and c["clock_ok"]


def test_warm_up_call_is_spent_before_measuring(monkeypatch):
    """Without it, preflight on a cold model reads 150 ms and cries GPU throttle."""
    calls = []

    def fake_post(path, body, timeout):
        calls.append(body["max_tokens"])
        return HEALTHY

    monkeypatch.setattr(provider, "_post", fake_post)
    provider.LlamaServer().canary()
    assert calls == [provider.CANARY_TOKENS, provider.CANARY_TOKENS]


def test_every_turn_carries_the_repeat_penalty_the_contract_was_measured_under(monkeypatch):
    """The server's default is no penalty; without it 26 of 60 fixture turns changed wording."""
    sent = []

    def fake_post(path, body, timeout):
        sent.append(body)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(provider, "_post", fake_post)
    provider.LlamaServer()._call("s", "u", None, 10, None, None)
    assert sent[0]["repeat_penalty"] == provider.REPEAT_PENALTY == 1.1


# --- the exact-model gate ----------------------------------------------------------------

PROPS = {"model_alias": provider.MODEL, "model_ftype": "Q4_K - Medium",
         "model_path": "C:/somewhere/models/qwen3-4b-instruct-2507/" + provider.MODEL_FILE,
         "build_info": "b11981-da6c30ade", "default_generation_settings": {"n_ctx": 8192}}


def test_the_served_model_is_read_from_props(monkeypatch):
    monkeypatch.setattr(provider.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(json.dumps(PROPS).encode()))
    m = provider.served_model()
    assert m == {"id": provider.MODEL, "path": PROPS["model_path"],
                 "quantization": "Q4_K - Medium", "loaded_context_length": 8192,
                 "runtime": "b11981-da6c30ade"}
    assert provider.product_model(m) is m


def test_product_model_needs_both_the_alias_and_the_file():
    """The alias alone can be put on any file, and the file alone under any name."""
    good = {"id": provider.MODEL, "path": "models/x/" + provider.MODEL_FILE}
    assert provider.product_model(good) is good
    assert provider.product_model(dict(good, id="unsupported-model")) is None
    assert provider.product_model(dict(good, path="models/x/Other-Q8_0.gguf")) is None
    assert provider.product_model({"id": provider.MODEL, "path": None}) is None


def test_preflight_rejects_a_server_running_another_model(monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(provider, "served_model",
                        lambda: {"id": "unsupported-model", "path": "models/other.gguf"})

    assert cli._preflight(provider.LlamaServer(), skip=True) is None
    out = capsys.readouterr().out
    assert provider.MODEL in out and "python -m app.servers" in out


def test_a_server_that_is_not_there_says_how_to_start_it(monkeypatch):
    monkeypatch.setattr(provider, "BASE", "http://127.0.0.1:9")
    with pytest.raises(provider.ProviderError, match="python -m app.servers"):
        provider.served_model()


# --- failures surface as ProviderError ---------------------------------------------------

@pytest.fixture()
def model_server(monkeypatch):
    """A listening socket standing in for the model server, pointed at by provider.BASE."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    monkeypatch.setattr(provider, "BASE", "http://127.0.0.1:%d" % srv.getsockname()[1])
    yield srv
    srv.close()


def test_a_server_that_never_answers_is_a_provider_error(model_server):
    """A read timeout is TimeoutError, not URLError, so it escaped `_post` and the HTTP app
    answered 500 when the laptop slept mid-request (07/11/2026)."""
    with pytest.raises(provider.ProviderError, match="did not answer"):
        provider._post("/v1/chat/completions", {}, 0.3)


def test_a_server_that_hangs_up_mid_request_is_a_provider_error(model_server):
    def hang_up():
        conn, _ = model_server.accept()
        conn.recv(65536)
        conn.close()

    threading.Thread(target=hang_up, daemon=True).start()
    with pytest.raises(provider.ProviderError, match="did not answer"):
        provider._post("/v1/chat/completions", {}, 5.0)
