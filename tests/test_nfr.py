"""NFR-4 and NFR-6, both of which the plan states as testable and neither of which was tested.

NFR-4 says "Zero [egress]. Verified by test, not assumed" -- so assuming it is the one thing
the requirement rules out. It is checked from two directions, because either alone is weak:
statically, that no module names a host we did not choose; dynamically, that a whole session
reaches nothing off this machine and never resolves a name.

NFR-6 says a malformed model reply is "retried once, then degrades to a scripted question,
never to a crash". The retry existed and the degrade worked; nothing pinned either, so a
refactor could turn a degrade into an exception with every test still green.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import provider, session  # noqa: E402
from app.provider import Completion  # noqa: E402
from app.runner import Runner  # noqa: E402
from test_runner import PLAN, ScriptedProvider, d  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app"
ALLOWED_HOSTS = {"127.0.0.1"}
HOST_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")


# --------------------------------------------------------------- NFR-4: egress
def test_no_module_on_the_live_path_names_a_foreign_host():
    """Catches a telemetry call, a CDN font, or a cloud fallback added by hand."""
    offenders = []
    for f in sorted(APP.glob("*.py")):
        for host in HOST_RE.findall(f.read_text(encoding="utf-8")):
            if host not in ALLOWED_HOSTS:
                offenders.append("%s -> %s" % (f.name, host))
    assert not offenders, "foreign hosts on the live path: %s" % offenders


def test_provider_is_pinned_to_loopback():
    """`localhost` is banned outright: it resolves to ::1 first and costs 2 s a call (log 8.6)."""
    assert provider.BASE == "http://127.0.0.1:1234"
    assert "localhost" not in provider.BASE


def test_a_whole_session_leaves_the_machine_alone(tmp_path, monkeypatch):
    """Everything except the provider must run with the network unplugged.

    Loopback is permitted and cannot be denied outright: asyncio's event loop builds its
    self-pipe from a 127.0.0.1 socket pair on Windows, so a blanket ban fails inside
    `asyncio.run` before any of our code executes. Loopback is not egress, which is what
    NFR-4 is actually about -- so the assertion is that nothing NON-loopback is contacted
    and no name is ever resolved.
    """
    seen = []
    real_connect = socket.socket.connect

    def watch(self, address, *a, **kw):
        seen.append(address)
        host = address[0] if isinstance(address, tuple) else address
        assert host in ("127.0.0.1", "::1", "localhost"), "egress to %r" % (address,)
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", watch)
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("live path resolved a name: %r" % (a,))))

    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("probe"), d("advance"), d("advance")]), PLAN, state)

    async def go():
        await r.ask()
        await r.submit("a short answer")
        await r.submit("a fuller answer")
        await r.ask()
        await r.submit("the second answer")

    asyncio.run(go())
    assert len(state.turns) == 3
    assert all(a[0] in ("127.0.0.1", "::1") for a in seen if isinstance(a, tuple))


# ------------------------------------------------------- NFR-6: no failed turns
class Malformed:
    """Returns unparseable text. `replies` counts only schema-constrained calls."""

    def __init__(self, then=None):
        self.replies = 0
        self.then = then

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        if schema is None:
            return Completion(text="a summary line")
        self.replies += 1
        if self.then and self.replies > 1:
            return Completion(text=json.dumps(self.then))
        return Completion(text="{not json at all")


def _session(prov, tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    return Runner(prov, PLAN, state), state


def test_a_malformed_reply_is_retried_exactly_once(tmp_path):
    p = Malformed()
    r, _ = _session(p, tmp_path)
    asyncio.run(r.ask())
    asyncio.run(r.submit("an answer"))
    assert p.replies == 2, "one retry, not none and not a loop"


def test_a_valid_retry_is_the_decision_that_stands(tmp_path):
    p = Malformed(then=d("advance", "Thanks."))
    r, state = _session(p, tmp_path)
    asyncio.run(r.ask())
    out = asyncio.run(r.submit("an answer"))
    assert out.act == "advance" and out.closed_question
    assert "regenerated" in state.turns[-1].guards


def test_a_model_that_never_recovers_degrades_and_never_crashes(tmp_path):
    """The whole point of NFR-6: a broken model costs answer quality, not the session.

    It must also still TERMINATE. A degraded run that never closes a question is a hang,
    which is a worse failure than a crash because nothing reports it.
    """
    p = Malformed()
    r, state = _session(p, tmp_path)
    asyncio.run(r.ask())
    decided = 0
    for _ in range(12):
        out = asyncio.run(r.submit("an answer"))
        if out.end_session:
            break
        decided += 1
        assert out.act in ("probe", "advance", "reask")
        assert "invalid->probe" in state.turns[-1].guards
        if out.closed_question:
            asyncio.run(r.ask())
    assert decided == len(state.turns), "every turn produced a decision -- zero failed turns"
    assert len(state.questions) == 2, "a broken model still worked through the whole plan"
    assert state.status == "complete"


def test_the_degraded_line_is_scripted_speech_not_an_empty_string(tmp_path):
    """A blank line is dead air in voice and an empty bubble in text."""
    p = Malformed()
    r, _ = _session(p, tmp_path)
    asyncio.run(r.ask())
    out = asyncio.run(r.submit("an answer"))
    assert out.act == "probe"
    assert out.spoken.text.strip(), "degraded probe must still say something"
