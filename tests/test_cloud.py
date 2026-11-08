"""The cloud client (V1.1_PLAN P1): what it sends each vendor, what it reads back, and that the
key never leaves through an error. The local server's request is pinned here too, because the
promise of P1 is that adding a cloud path changed nothing on the measured one."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import contract, provider  # noqa: E402
from app.provider import CloudClient, Profile, ProviderError  # noqa: E402

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


def test_the_local_request_is_byte_for_byte_what_1_0_sent(monkeypatch):
    sent = []
    monkeypatch.setattr(provider, "_post", lambda path, body, timeout: sent.append(
        (path, json.dumps(body))) or {"choices": [{"message": {"content": "{}"}}]})
    asyncio.run(provider.LlamaServer().complete(
        "sys", "user", schema=contract.TURN_SCHEMA, max_tokens=400,
        enum_field="act", enum_values=contract.ACTIONS))
    expected = {
        "model": "qwen3-4b-instruct-2507",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        "max_tokens": 400, "temperature": 0.0, "seed": 42, "stream": False,
        "repeat_penalty": 1.1,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "turn", "strict": True,
                                            "schema": contract.TURN_SCHEMA}},
        "logprobs": True, "top_logprobs": 20,
    }
    assert sent == [("/v1/chat/completions", json.dumps(expected))]


def _body(vendor, enum=True, **caps):
    c = CloudClient(Profile(vendor, "m", **caps), KEY)
    return c.body("sys", "user", contract.TURN_SCHEMA, 400, "act" if enum else None)


def test_no_cloud_request_carries_llama_cpp_parameters():
    for vendor in provider.VENDORS:
        b = _body(vendor, logprobs=True, seed=True, reasoning="none")
        assert "repeat_penalty" not in b
        assert b["response_format"]["json_schema"]["strict"] is True
        assert b["temperature"] == 0.0 and b["stream"] is False


def test_openai_gets_its_own_token_field_and_reasoning_switch():
    b = _body("openai", reasoning="none")
    assert b["max_completion_tokens"] == 400 and "max_tokens" not in b
    assert b["reasoning_effort"] == "none"


def test_openrouter_routes_only_to_hosts_that_honour_every_parameter_and_keep_nothing():
    b = _body("openrouter", reasoning="none")
    assert b["reasoning"] == {"effort": "none"} and "reasoning_effort" not in b
    assert b["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert b["max_tokens"] == 400


def test_logprobs_and_seed_are_sent_only_where_the_model_takes_them():
    plain = _body("groq")
    assert "logprobs" not in plain and "top_logprobs" not in plain and "seed" not in plain
    full = _body("openrouter", logprobs=True, seed=True)
    assert full["logprobs"] is True and full["top_logprobs"] == 20 and full["seed"] == 42
    assert "logprobs" not in _body("openrouter", enum=False, logprobs=True)


def test_groq_hides_reasoning_beside_a_schema_in_the_way_each_model_accepts():
    qwen = CloudClient(provider.profile_for("groq", "qwen/qwen3.8-27b"), KEY).body(
        "s", "u", contract.TURN_SCHEMA, 400, "act")
    assert qwen["reasoning_effort"] == "none" and qwen["reasoning_format"] == "hidden"
    assert "logprobs" not in qwen and qwen["max_completion_tokens"] == 400
    oss = CloudClient(provider.profile_for("groq", "openai/gpt-oss-20b"), KEY).body(
        "s", "u", contract.TURN_SCHEMA, 400, "act")
    assert oss["reasoning_effort"] == "low" and oss["include_reasoning"] is False
    assert "reasoning_format" not in oss


def test_no_reasoning_field_when_the_model_has_no_reasoning_control():
    b = _body("openai")
    assert "reasoning_effort" not in b and "reasoning" not in b


def _client(monkeypatch, reply, **caps):
    monkeypatch.setattr(provider, "_send", lambda vendor, body, key, timeout: reply)
    return CloudClient(Profile("openrouter", "m", **caps), KEY)


def _turn(c):
    return asyncio.run(c.complete("s", "u", schema=contract.TURN_SCHEMA,
                                  enum_field="act", enum_values=contract.ACTIONS))


def test_cost_comes_from_the_vendor_when_it_reports_one(monkeypatch):
    c = _client(monkeypatch, {"choices": [{"message": {"content": "{}"}}],
                              "usage": {"prompt_tokens": 1000, "completion_tokens": 50,
                                        "cost": 0.000123}}, price_in=9.0, price_out=9.0)
    out = _turn(c)
    assert out.cost_usd == 0.000123 and out.prompt_tokens == 1000 and out.decode_tokens == 50


def test_cost_is_estimated_from_list_prices_otherwise(monkeypatch):
    c = _client(monkeypatch, {"choices": [{"message": {"content": "{}"}}],
                              "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 200_000}},
                price_in=0.10, price_out=0.50)
    assert _turn(c).cost_usd == pytest.approx(0.20)


def test_no_cost_is_invented_without_a_price(monkeypatch):
    c = _client(monkeypatch, {"choices": [{"message": {"content": "{}"}}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    assert _turn(c).cost_usd is None


def test_a_model_without_logprobs_says_so_instead_of_an_empty_posterior(monkeypatch):
    out = _turn(_client(monkeypatch, {"choices": [{"message": {"content": "{}"}}]}))
    assert out.posterior == {} and "does not return logprobs" in out.posterior_note


def test_the_posterior_is_read_where_logprobs_come_back(monkeypatch):
    content = [{"token": t, "top_logprobs": []} for t in ['{"', 'act', '":"']]
    content.append({"token": "probe", "top_logprobs": [
        {"token": "probe", "logprob": -0.1}, {"token": "advance", "logprob": -2.5}]})
    reply = {"choices": [{"message": {"content": "{}"}, "logprobs": {"content": content}}]}
    out = _turn(_client(monkeypatch, reply, logprobs=True))
    assert set(out.posterior) == {"probe", "advance"} and out.posterior_note == ""
    assert out.posterior["probe"] > out.posterior["advance"]


def test_reasoning_tokens_are_counted_so_thinking_left_on_shows(monkeypatch):
    reply = {"choices": [{"message": {"content": "{}"}}],
             "usage": {"completion_tokens": 300,
                       "completion_tokens_details": {"reasoning_tokens": 240}}}
    assert _turn(_client(monkeypatch, reply)).reasoning_tokens == 240


def test_a_reply_without_choices_is_a_provider_error(monkeypatch):
    with pytest.raises(ProviderError, match="no choices"):
        _turn(_client(monkeypatch, {"error": "busy"}))


# --------------------------------------------------------------- the key never leaks
def _http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


@pytest.mark.parametrize("code,words", [(401, "refused the API key"),
                                        (402, "out of credit"),
                                        (404, "has no model 'm'"),
                                        (429, "rate limiting"),
                                        (400, "rejected the request (HTTP 400)")])
def test_vendor_refusals_say_what_to_do_and_never_echo_the_key(monkeypatch, code, words):
    def boom(req, timeout=None):
        raise _http_error(code, '{"error": "Incorrect API key provided: %s"}' % KEY)

    monkeypatch.setattr(provider.urllib.request, "urlopen", boom)
    monkeypatch.setattr(provider, "_sleep", lambda s: None)
    with pytest.raises(ProviderError) as e:
        _turn(CloudClient(Profile("openrouter", "m"), KEY))
    assert words in str(e.value) and KEY not in str(e.value)
    assert "OpenRouter" in str(e.value)


def _limited(wait):
    return urllib.error.HTTPError("https://x", 429, "slow down", {"retry-after": wait},
                                  io.BytesIO(b'{"error": "rate limit"}'))


def test_a_rate_limit_is_waited_out_for_as_long_as_the_vendor_asks(monkeypatch):
    calls, waits = [], []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "{}"}}]}'

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _limited("3.5")
        return Reply()

    monkeypatch.setattr(provider.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(provider, "_sleep", waits.append)
    _turn(CloudClient(Profile("groq", "m"), KEY))
    assert len(calls) == 2 and waits == [3.5]


def test_a_long_wait_is_capped_and_a_persistent_limit_becomes_a_provider_error(monkeypatch):
    waits = []

    def always(req, timeout=None):
        raise _limited("1m26.4s")

    monkeypatch.setattr(provider.urllib.request, "urlopen", always)
    monkeypatch.setattr(provider, "_sleep", waits.append)
    with pytest.raises(ProviderError, match="rate limiting"):
        _turn(CloudClient(Profile("groq", "m"), KEY))
    assert waits == [provider.RETRY_WAIT_CAP_S] * provider.RATE_RETRIES


def test_groq_style_reset_headers_are_read():
    assert provider._retry_after({"x-ratelimit-reset-tokens": "8.452s"}) == 8.452
    assert provider._retry_after({"x-ratelimit-reset-requests": "1m26.4s"}) == pytest.approx(86.4)
    assert provider._retry_after({}) == 5.0


def test_a_partly_masked_key_echoed_back_is_redacted_too(monkeypatch):
    def boom(req, timeout=None):
        raise _http_error(401, "bad key sk-proj-abcdefghijklmnopqrstuvwxyz1234")

    monkeypatch.setattr(provider.urllib.request, "urlopen", boom)
    with pytest.raises(ProviderError) as e:
        _turn(CloudClient(Profile("openai", "m"), "sk-proj-something-else-entirely"))
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz1234" not in str(e.value)


@pytest.mark.parametrize("exc", [urllib.error.URLError("unreachable " + KEY),
                                 TimeoutError("timed out " + KEY),
                                 ConnectionResetError("reset " + KEY)])
def test_transport_failures_are_provider_errors_without_the_key(monkeypatch, exc):
    def boom(req, timeout=None):
        raise exc

    monkeypatch.setattr(provider.urllib.request, "urlopen", boom)
    with pytest.raises(ProviderError) as e:
        _turn(CloudClient(Profile("gemini", "m"), KEY))
    assert KEY not in str(e.value)


def test_the_key_is_sent_as_a_bearer_header_and_nowhere_in_the_body(monkeypatch):
    seen = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "{}"}}]}'

    def capture(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = req.data.decode()
        return Reply()

    monkeypatch.setattr(provider.urllib.request, "urlopen", capture)
    c = CloudClient(Profile("openai", "m"), KEY)
    _turn(c)
    assert seen["auth"] == "Bearer " + KEY and KEY not in seen["body"]
    assert KEY not in repr(c) and KEY not in json.dumps(c.describe())


# --------------------------------------------------------------- choosing a profile
def _catalogue(monkeypatch, **models):
    monkeypatch.setattr(provider, "_OR_CACHE", dict(models))


def test_openrouter_capabilities_come_from_its_model_list(monkeypatch):
    _catalogue(monkeypatch, **{
        "a/off": {"supported_parameters": ["structured_outputs", "logprobs", "seed",
                                           "temperature"],
                  "reasoning": {"supported_efforts": ["high", "low", "none"]},
                  "pricing": {"prompt": "0.0000001", "completion": "0.0000005"}},
        "a/floor": {"supported_parameters": ["structured_outputs"],
                    "reasoning": {"mandatory": True, "supported_efforts": ["low", "minimal"]}},
        "a/plain": {"supported_parameters": ["structured_outputs"]},
        "a/loose": {"supported_parameters": ["response_format"]},
    })
    off = provider.openrouter_profile("a/off")
    assert (off.reasoning, off.logprobs, off.seed, off.temperature) == ("none", True, True, True)
    assert (off.price_in, off.price_out) == (0.1, 0.5)
    floor = provider.openrouter_profile("a/floor")
    assert floor.reasoning == "minimal" and not floor.temperature and not floor.seed
    assert "temperature" not in CloudClient(floor, KEY).body("s", "u", None, 10, None)
    assert provider.openrouter_profile("a/plain").reasoning is None
    with pytest.raises(ProviderError, match="strict structured output"):
        provider.openrouter_profile("a/loose")
    with pytest.raises(ProviderError, match="no model"):
        provider.openrouter_profile("a/missing")


def test_a_measured_model_uses_its_recorded_profile(tmp_path, monkeypatch):
    f = tmp_path / "cloud_models.json"
    f.write_text(json.dumps({"models": [{"vendor": "openai", "model": "gpt-x",
                                         "reasoning": "none", "price_in": 0.1,
                                         "price_out": 0.5, "gate": {"product": "49/49"}}]}))
    monkeypatch.setattr(provider, "CLOUD_MODELS", f)
    p = provider.profile_for("openai", "gpt-x")
    assert p.measured and p.reasoning == "none" and p.price_out == 0.5
    assert not provider.profile_for("openai", "gpt-y").measured


def test_the_shipped_measured_list_loads_with_the_settings_it_was_gated_under():
    listed = provider.measured_models()
    assert listed, "config/cloud_models.json ships at least one measured model"
    for m in listed:
        assert m["vendor"] in provider.VENDORS and m["gate"]["fixtures"]
        p = provider.profile_for(m["vendor"], m["model"])
        assert p.measured and p.reasoning == m["reasoning"] and p.logprobs == m["logprobs"]
    qwen = provider.profile_for("groq", "qwen/qwen3.8-27b")
    assert qwen.measured and qwen.reasoning == "none" and qwen.price_in == 0.0
    known = provider.KNOWN[("groq", "qwen/qwen3.8-27b")]
    assert (qwen.seed, qwen.temperature, qwen.logprobs) == (known.seed, known.temperature,
                                                           known.logprobs)


def test_the_environment_chooses_a_cloud_model_until_settings_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "CLOUD_MODELS", tmp_path / "none.json")
    monkeypatch.setenv("MOCKINGBIRD_PROVIDER", "openai")
    monkeypatch.delenv("MOCKINGBIRD_MODEL", raising=False)
    with pytest.raises(ProviderError, match="needs MOCKINGBIRD_MODEL"):
        provider.current()
    monkeypatch.setenv("MOCKINGBIRD_MODEL", "gpt-x")
    monkeypatch.setenv("MOCKINGBIRD_API_KEY", KEY)
    c = provider.current()
    assert isinstance(c, CloudClient) and not provider.is_local(c)
    assert c.describe() == {"mode": "cloud", "vendor": "openai", "label": "OpenAI",
                            "host": "api.openai.com", "model": "gpt-x", "measured": False}


def test_an_unknown_vendor_is_refused():
    with pytest.raises(ValueError, match="unknown vendor"):
        CloudClient(Profile("acme", "m"), KEY)


def test_a_cloud_model_has_no_prefix_cache_to_warm():
    assert asyncio.run(CloudClient(Profile("openai", "m"), KEY).warmup("s", "u")) == 0.0
