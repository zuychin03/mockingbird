"""How the three model servers are started: the flags the product was measured under, loopback
and one slot for each, and what `python -m app.servers` does when one is already up or a file
is missing. Nothing here starts a real server."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import embed, lfm3, provider, servers  # noqa: E402


def _flag(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


def test_every_server_is_on_loopback_with_one_slot_at_its_clients_address():
    for s, client_base in ((servers.LLM, provider.BASE), (servers.VOICE, lfm3.BASE),
                           (servers.EMBEDDER, embed.BASE)):
        cmd = servers.command(s)
        assert _flag(cmd, "--host") == "127.0.0.1"
        assert _flag(cmd, "--parallel") == "1"
        assert client_base == "http://127.0.0.1:%s" % _flag(cmd, "--port")


def test_the_language_model_runs_under_the_product_alias_file_and_measured_flags():
    cmd = servers.command(servers.LLM)
    assert _flag(cmd, "--alias") == provider.MODEL
    assert Path(_flag(cmd, "-m")).name == provider.MODEL_FILE
    assert (_flag(cmd, "-c"), _flag(cmd, "-fa"), _flag(cmd, "-ctk"), _flag(cmd, "-ctv")) == (
        "8192", "on", "f16", "f16")
    assert servers.LLM.required and not servers.VOICE.required and not servers.EMBEDDER.required


def test_the_embedder_takes_no_gpu_memory():
    cmd = servers.command(servers.EMBEDDER)
    assert "--embedding" in cmd
    assert (_flag(cmd, "-ngl"), _flag(cmd, "--device")) == ("0", "none")


def test_servers_already_running_are_left_alone(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("nothing should be started")

    monkeypatch.setattr(servers, "healthy", lambda base: True)
    monkeypatch.setattr(servers.subprocess, "Popen", refuse)
    assert servers.main() == 0


def test_a_missing_language_model_stops_the_start(monkeypatch, capsys):
    monkeypatch.setattr(servers, "healthy", lambda base: False)
    monkeypatch.setattr(servers, "missing",
                        lambda s: [servers.LLM_FILE] if s is servers.LLM else [])
    monkeypatch.setattr(servers.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    assert servers.main() == 1
    assert "language model: not started, missing" in capsys.readouterr().out
