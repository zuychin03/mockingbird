"""The HTTP surface. What matters here is that it enforces nothing of its own: every rule is
the domain's, so the web and the terminal cannot disagree about what may be asked."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi", reason="the web extra is optional; app/ never imports it")
from fastapi.testclient import TestClient  # noqa: E402

from api import main as api  # noqa: E402
from app import bank, planner, review  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DRAFT", tmp_path / "draft.json")
    return TestClient(api.app)


@pytest.fixture()
def started(client):
    r = client.post("/api/plan/from-stock", json={"kind": "mixed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_stock_plan_can_be_started_without_a_model(started):
    """FR-4 makes no model call: there is no description to read, so the whole path is
    selection over reviewed text. The API should not need LM Studio for it either."""
    assert started["phases"]
    assert started["label"]
    assert started["stock_kinds"] == ["behavioural", "mixed", "technical"]


def test_the_ui_is_told_which_phases_it_may_edit(started):
    ids = {ph["id"]: ph["editable"] for ph in started["phases"]}
    assert ids["warmup"] is False and ids["closing"] is False
    assert ids["behavioural_core"] is True


def test_editing_goes_through_the_same_rules_as_the_terminal(client, started):
    r = client.put("/api/plan/collaboration/questions/0",
                   json={"text": "Tell me about a disagreement you lost?"})
    assert r.status_code == 200
    q = r.json()["phases"]
    edited = [x for ph in q for x in ph["questions"] if x["edited_from"]]
    assert edited and edited[0]["text"] == "Tell me about a disagreement you lost?"


def test_a_domain_refusal_keeps_the_domain_sentence(client, started):
    """Those sentences were written to be read by a person. Rewriting them into API prose
    would lose the reason, which is the only useful part."""
    r = client.put("/api/plan/warmup/questions/0", json={"text": "Something else?"})
    assert r.status_code == 400
    assert "structural" in r.json()["detail"]

    r = client.put("/api/plan/collaboration/questions/0", json={"text": "no punctuation"})
    assert r.status_code == 400
    assert "end with" in r.json()["detail"]


def test_a_proposal_cannot_be_added_through_the_api_either(client, started, tmp_path):
    """The gate has to be the same object both surfaces use, or one will eventually let
    through what the other refuses."""
    d = review.read_draft(api.DRAFT, bank.load(api.BANK))
    proposal = bank.Question(id="gen.perf.99", text="A proposed latency question?",
                             competencies=("performance",), shape="star",
                             source="generated", status="proposed")
    review.write_draft(review.propose_into_bank(d, proposal), api.DRAFT)

    r = client.post("/api/plan/technical_experience/from-bank",
                    json={"question_id": "gen.perf.99"})
    assert r.status_code == 400
    assert "Approve it first" in r.json()["detail"]

    assert client.post("/api/proposals/gen.perf.99/approve").status_code == 200
    r = client.post("/api/plan/technical_experience/from-bank",
                    json={"question_id": "gen.perf.99"})
    assert r.status_code == 200
    assert proposal.text in [q["text"] for ph in r.json()["phases"] for q in ph["questions"]]


def test_approving_does_not_change_the_plan(client, started, tmp_path):
    d = review.read_draft(api.DRAFT, bank.load(api.BANK))
    proposal = bank.Question(id="gen.own.98", text="A proposed ownership question?",
                             competencies=("ownership",), shape="star",
                             source="generated", status="proposed")
    review.write_draft(review.propose_into_bank(d, proposal), api.DRAFT)
    before = client.get("/api/plan").json()["phases"]

    after = client.post("/api/proposals/gen.own.98/approve").json()["phases"]
    assert after == before


def test_deleting_the_last_question_of_a_phase_is_refused(client, started):
    r = client.delete("/api/plan/design/questions/0")
    assert r.status_code == 400
    assert "no questions" in r.json()["detail"]


def test_moving_reorders_without_losing_anything(client, started):
    before = [q["text"] for ph in started["phases"]
              if ph["id"] == "behavioural_core" for q in ph["questions"]]
    r = client.post("/api/plan/behavioural_core/questions/0/move", json={"to": 2})
    after = [q["text"] for ph in r.json()["phases"]
             if ph["id"] == "behavioural_core" for q in ph["questions"]]
    assert after != before and sorted(after) == sorted(before)


def test_saving_writes_a_plan_the_runner_accepts(client, started, tmp_path):
    from app import session as sess
    r = client.post("/api/plan/save", json={"path": "data/api_test_plan.json"})
    assert r.status_code == 200, r.text
    out = api.ROOT / r.json()["saved"]
    try:
        assert sess.load_plan(out)
    finally:
        out.unlink(missing_ok=True)


def test_a_plan_cannot_be_saved_outside_the_project(client, started):
    r = client.post("/api/plan/save", json={"path": "../../escaped.json"})
    assert r.status_code == 400


def test_no_draft_is_a_404_not_a_crash(client):
    assert client.get("/api/plan").status_code == 404


def test_an_unknown_stock_kind_is_refused(client):
    r = client.post("/api/plan/from-stock", json={"kind": "vibes"})
    assert r.status_code == 404
    assert "behavioural" in r.json()["detail"]


def test_the_api_layer_is_not_imported_by_the_runtime():
    """`app/` must run on the standard library alone. If it ever imports the web extra, an
    interview stops working wherever the extra is not installed."""
    for module in (Path(api.ROOT) / "app").glob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "fastapi" not in text, module.name
        assert "import api" not in text, module.name


# --- session, history and report -------------------------------------------------------------

def test_no_session_in_progress_is_a_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    assert client.get("/api/session").status_code == 404


def test_starting_a_session_needs_the_exact_model_loaded(client, monkeypatch, tmp_path):
    """The exact-identity gate is the product's, not the API's. A wrong model must not be
    able to receive an interview's controls just because the request came over HTTP."""
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    monkeypatch.setattr(api.prov, "loaded_models", lambda: [{"id": "something-else"}])
    r = client.post("/api/session/start",
                    json={"plan_path": "config/interview_swe_general.json"})
    assert r.status_code == 503
    assert api.prov.MODEL in r.json()["detail"]


def test_a_plan_outside_the_project_cannot_be_loaded(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    r = client.post("/api/session/start", json={"plan_path": "../../elsewhere.json"})
    assert r.status_code == 400


def test_the_session_payload_carries_no_judgement(client, monkeypatch, tmp_path):
    """Section 12 treats showing an assessment mid-session as a correctness bug. `ok`, the
    guard names and the posterior belong to the decision record; the person being interviewed
    sees the dialogue and nothing else."""
    from app import resume, session as sess

    plan = sess.load_plan(api.ROOT / "config" / "interview_swe_general.json")
    state = sess.new_session(plan, {"model_id": "test"})
    state.turns.append(sess.Turn(
        index=0, phase="warmup", question_id="warmup.1", question="Q?",
        utterance="An answer.", act="probe", say="A follow-up?", ok=False, ask="",
        guards=["invented-question-dropped"]))

    class R:
        pass
    r = R()
    r.state = state
    r.done = False
    r.index = 0
    r.questions = list(sess.iter_questions(plan))
    r.said_this_question = ["A follow-up?"]
    r.current = r.questions[0]

    monkeypatch.setattr(resume, "write", lambda *a, **k: None)
    monkeypatch.setattr(api.resume, "write", lambda *a, **k: None)
    payload = api._session_state(r)

    blob = json.dumps(payload)
    assert "invented-question-dropped" not in blob
    assert '"ok"' not in blob
    assert '"guards"' not in blob
    assert [t["who"] for t in payload["turns"]] == ["candidate", "interviewer"]


def test_history_lists_what_is_on_disk(client, monkeypatch, tmp_path):
    """Read from the records themselves rather than an index: a session on disk is always
    listed, and a deleted one always disappears."""
    monkeypatch.setattr(api, "SESSIONS", tmp_path)
    (tmp_path / "20260101-000000-aaaaaa").mkdir()
    (tmp_path / "20260101-000000-aaaaaa" / "session.json").write_text(json.dumps({
        "session_id": "20260101-000000-aaaaaa", "started_at": "2026-01-01T00:00:00",
        "status": "complete", "plan_id": "p", "questions": [{}, {}], "turn_count": 7,
    }), encoding="utf-8")
    got = client.get("/api/sessions").json()
    assert len(got) == 1
    assert got[0]["session_id"] == "20260101-000000-aaaaaa"
    assert got[0]["turns"] == 7


def test_a_corrupt_session_record_does_not_break_history(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "SESSIONS", tmp_path)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "session.json").write_text("{not json", encoding="utf-8")
    assert client.get("/api/sessions").json() == []


def test_a_report_for_an_unknown_session_is_a_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "SESSIONS", tmp_path)
    assert client.get("/api/sessions/nope/report").status_code == 404


def test_the_runtime_being_down_is_a_503_with_the_provider_sentence(client, monkeypatch,
                                                                    tmp_path):
    """It already names the host it tried and suggests `lms server start`, which is the whole
    answer. Unhandled it was an opaque 500 and the page said "Internal Server Error"."""
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")

    def down():
        raise api.prov.ProviderError("cannot reach LM Studio at http://127.0.0.1:1234. "
                                     "Is `lms server start` running?")
    monkeypatch.setattr(api.prov, "loaded_models", down)
    r = client.post("/api/session/start",
                    json={"plan_path": "config/interview_swe_general.json"})
    assert r.status_code == 503
    assert "lms server start" in r.json()["detail"]


def _one_turn_runner(act, say, said_this_question):
    from app import session as sess

    plan = sess.load_plan(api.ROOT / "config" / "interview_swe_general.json")
    state = sess.new_session(plan, {"model_id": "test"})
    state.turns.append(sess.Turn(
        index=0, phase="warmup", question_id="warmup.1", question="Q?",
        utterance="An answer.", act=act, say=say, ok=True, ask="", guards=[]))

    class R:
        pass
    r = R()
    r.state, r.done = state, False
    r.questions = list(sess.iter_questions(plan))
    r.index = 1 if act == "advance" else 0
    r.said_this_question = list(said_this_question)
    r.current = r.questions[r.index]
    return r


def _interviewer_lines(r, monkeypatch):
    monkeypatch.setattr(api.resume, "write", lambda *a, **k: None)
    return [t["text"] for t in api._session_state(r)["turns"] if t["who"] == "interviewer"]


def test_after_an_advance_the_next_question_is_shown_and_the_thanks_only_once(monkeypatch):
    """The acknowledgement is already on the turn `submit` wrote. Appending what was just
    spoken on top of that showed it twice, once alone and once glued to the next question."""
    ack = "Thank you for walking me through that."
    r = _one_turn_runner("advance", ack, [])
    said = _interviewer_lines(r, monkeypatch)
    assert sum(line.count(ack) for line in said) == 1, said
    assert said[-1] == r.questions[1]["question"], said


def test_after_a_probe_the_probe_is_not_repeated(monkeypatch):
    """A probe is both the last turn's `say` and the line awaiting an answer. Showing the
    pending line unconditionally would print it twice."""
    probe = "What did you do first?"
    r = _one_turn_runner("probe", probe, [probe])
    said = _interviewer_lines(r, monkeypatch)
    assert sum(line.count(probe) for line in said) == 1, said
    # The failure that matters is not a second copy of the probe but the question after it
    # appearing early: the candidate would be shown a question they were never asked.
    assert said[-1] == probe, said


def test_a_resumed_session_still_shows_the_question_it_is_waiting_on(monkeypatch):
    """The regression this derivation exists for: nothing spoken after the last answer is
    in `state.turns`, so a reload used to leave the candidate with no question to answer."""
    r = _one_turn_runner("advance", "Thanks.", [])
    said = _interviewer_lines(r, monkeypatch)
    assert said[-1] == r.questions[1]["question"], said


def _write_session(root, sid, label="A plan"):
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps({
        "session_id": sid, "plan_id": "p", "started_at": "2026-01-01T00:00:00",
        "status": "complete", "plan_snapshot": {"label": label},
    }), encoding="utf-8")
    return d


def test_the_history_is_capped_and_newest_first(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    for i in range(60):
        _write_session(root, "202601%02d-000000-aaaaaa" % (i + 1))
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/sessions").json()
    assert len(got) == api.SESSIONS_SHOWN
    assert got[0]["session_id"] > got[-1]["session_id"], "newest first"
    assert got[0]["session_id"] == "20260160-000000-aaaaaa"
    assert len(client.get("/api/sessions?limit=3").json()) == 3


def test_an_unreadable_record_does_not_spend_a_slot(client, monkeypatch, tmp_path):
    """The cap counts what is shown. Counting what is read would silently shorten the table
    by one row for every corrupt file on disk."""
    root = tmp_path / "s"
    for i in range(4):
        _write_session(root, "2026010%d-000000-aaaaaa" % (i + 1))
    bad = root / "20260105-000000-bbbbbb"
    bad.mkdir(parents=True)
    (bad / "session.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/sessions?limit=4").json()
    assert len(got) == 4
    assert all(s["session_id"] != "20260105-000000-bbbbbb" for s in got)


def _session_with_report(root, sid="20260101-000000-cache1"):
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps({
        "session_id": sid, "plan_id": "p", "started_at": "2026-01-01T00:00:00",
        "status": "complete", "plan_snapshot": {"label": "A plan"}, "questions": [],
    }), encoding="utf-8")
    return d


def test_a_built_report_is_cached_beside_its_session(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    d = _session_with_report(root)
    monkeypatch.setattr(api, "SESSIONS", root)

    first = client.get("/api/sessions/20260101-000000-cache1/report")
    assert first.status_code == 200
    assert (d / "report.json").exists(), "the built report was not kept"

    # Second read must not rebuild. Make rebuilding impossible and require a 200 anyway.
    def boom(*a, **k):
        raise AssertionError("rebuilt a report that was already cached")
    monkeypatch.setattr(api.observe, "observe", boom)
    monkeypatch.setattr(api.score_mod, "build", boom)
    again = client.get("/api/sessions/20260101-000000-cache1/report")
    assert again.status_code == 200
    assert again.json() == first.json()


def test_the_cache_is_dropped_when_the_session_changes(client, monkeypatch, tmp_path):
    """A cache that never invalidates is worse than none: a report built from four answers
    must not be served once the session holds six."""
    root = tmp_path / "s"
    d = _session_with_report(root, "20260101-000000-cache2")
    monkeypatch.setattr(api, "SESSIONS", root)
    client.get("/api/sessions/20260101-000000-cache2/report")
    cached = d / "report.json"
    assert cached.exists()

    assert api._report_is_fresh(d) is not None
    # The session gains a turn after the report was written.
    os.utime(d / "session.json", (time.time() + 10, time.time() + 10))
    assert api._report_is_fresh(d) is None, "a changed session still served its old report"


def test_refresh_forces_a_rebuild(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    _session_with_report(root, "20260101-000000-cache3")
    monkeypatch.setattr(api, "SESSIONS", root)
    client.get("/api/sessions/20260101-000000-cache3/report")

    calls = []
    real = api.score_mod.build
    monkeypatch.setattr(api.score_mod, "build",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    client.get("/api/sessions/20260101-000000-cache3/report")
    assert not calls, "served from cache without refresh"
    client.get("/api/sessions/20260101-000000-cache3/report?refresh=true")
    assert calls, "refresh=true did not rebuild"


# ------------------------------------------------- the answer's recording
class _AtSession:
    """Just enough runner for `_recording`: it only ever asks where the session lives."""

    def __init__(self, directory):
        self.state = type("S", (), {"dir": directory})()


@pytest.fixture()
def recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "ROOT", tmp_path)
    room = tmp_path / "data" / "sessions" / "s1" / "audio"
    room.mkdir(parents=True)
    (room / "answer-1.wav").write_bytes(b"RIFF")
    return _AtSession(tmp_path / "data" / "sessions" / "s1")


def test_an_answer_carries_the_recording_it_was_spoken_from(recorded):
    got = api._recording(recorded, "data/sessions/s1/audio/answer-1.wav")
    assert got == "data/sessions/s1/audio/answer-1.wav"


def test_a_typed_answer_carries_no_recording(recorded):
    assert api._recording(recorded, None) is None
    assert api._recording(recorded, "") is None


def test_a_recording_from_outside_this_session_is_not_linked(recorded, tmp_path):
    """The path comes from the browser. A session that could name any file on disk would let
    one interview's report play another's audio, and the check is cheaper than the argument
    about whether that matters."""
    other = tmp_path / "data" / "sessions" / "s2" / "audio"
    other.mkdir(parents=True)
    (other / "answer-1.wav").write_bytes(b"RIFF")
    assert api._recording(recorded, "data/sessions/s2/audio/answer-1.wav") is None
    assert api._recording(recorded, "../../../../windows/win.ini") is None


def test_a_recording_that_is_not_on_disk_is_not_linked(recorded):
    assert api._recording(recorded, "data/sessions/s1/audio/never-written.wav") is None


def test_an_unreachable_model_says_so_when_building_a_report(client, monkeypatch, tmp_path):
    """The same failure `/api/session/start` was already fixed for, missed on this path. The
    provider's own sentence names the host it tried and how to start it, and unguarded the
    whole thing arrived as an opaque 500 with "Internal Server Error" on the page."""
    root = tmp_path / "s"
    sid = "20260101-000000-down01"
    d = root / sid
    d.mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({
        "session_id": sid, "plan_id": "p", "started_at": "2026-01-01T00:00:00",
        "status": "complete", "plan_snapshot": {"label": "A plan"},
        "questions": [{"phase": "p1", "question_id": "p1.1", "question": "Why?",
                       "answers": ["because"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(api, "SESSIONS", root)

    async def down(*a, **k):
        raise api.prov.ProviderError("cannot reach LM Studio at http://127.0.0.1:1234. "
                                     "Is `lms server start` running?")
    monkeypatch.setattr(api.observe, "observe", down)

    r = client.get("/api/sessions/%s/report" % sid)
    assert r.status_code == 503, r.text
    assert "lms server start" in r.json()["detail"]


def test_an_answers_recording_is_served_for_playback(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    room = root / "20260101-000000-audio1" / "audio"
    room.mkdir(parents=True)
    (room / "answer-1.wav").write_bytes(b"RIFF....WAVE")
    monkeypatch.setattr(api, "SESSIONS", root)

    r = client.get("/api/sessions/20260101-000000-audio1/audio/answer-1.wav")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == b"RIFF....WAVE"


def test_playback_refuses_a_name_that_climbs_out_of_the_session(monkeypatch, tmp_path):
    """Called directly rather than over HTTP: every client normalises `..` out of a path before
    the request is sent, so an HTTP test of this asserts the client's behaviour and not the
    server's. What matters is that the handler itself refuses a name that resolves outside the
    audio folder, whatever route it arrives by.

    Sessions are not isolated from each other and should not be -- they are all one person's on
    one machine. The line being defended is the sessions tree, not the session.
    """
    root = tmp_path / "s"
    (root / "20260101-000000-audio1" / "audio").mkdir(parents=True)
    (tmp_path / "secrets.txt").write_bytes(b"not audio")
    monkeypatch.setattr(api, "SESSIONS", root)

    for name in ("../../../secrets.txt", "../../secrets.txt", "missing.wav", "."):
        with pytest.raises(api.HTTPException) as raised:
            api.session_audio("20260101-000000-audio1", name)
        assert raised.value.status_code == 404, name


def test_playback_serves_no_file_for_an_encoded_climb(client, monkeypatch, tmp_path):
    """The one traversal shape that survives a client: percent-encoded separators.

    Asserted on the bytes rather than the status. A decoded name containing slashes matches no
    path parameter, so the request falls through to the SPA catch-all and comes back as the app
    shell with a 200 -- but only when `ui/build` exists, which made an earlier version of this
    test pass or fail depending on whether the UI had been built. What must hold either way is
    that the file itself never leaves the machine.
    """
    root = tmp_path / "s"
    (root / "20260101-000000-audio1" / "audio").mkdir(parents=True)
    (tmp_path / "secrets.txt").write_bytes(b"not audio")
    monkeypatch.setattr(api, "SESSIONS", root)

    r = client.get("/api/sessions/20260101-000000-audio1/audio/..%2F..%2F..%2Fsecrets.txt")
    assert b"not audio" not in r.content
    assert r.headers.get("content-type") != "audio/wav"


# ------------------------------------------- where the interviews are, and removing them
def _recorded_session(root, sid="20260101-000000-stored1"):
    d = root / sid
    (d / "audio").mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({
        "session_id": sid, "plan_id": "p", "started_at": "2026-01-01T00:00:00",
        "status": "complete", "plan_snapshot": {"label": "A plan"}, "questions": [],
    }), encoding="utf-8")
    (d / "transcript.json").write_text('{"turns": []}', encoding="utf-8")
    (d / "audio" / "answer-1.wav").write_bytes(b"RIFF" * 64)
    return d


def test_the_interface_can_say_where_the_interviews_are(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    _recorded_session(root)
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/storage").json()
    assert got["path"] == str(root), "the real path, not a description of it"
    assert got["sessions"] == 1 and got["recordings"] == 1
    assert got["bytes"] > 0


def test_the_claim_is_derived_from_the_provider_not_asserted(client, monkeypatch, tmp_path):
    """12.9 makes "this never leaves your machine" the product's central claim and says it
    counts only while it is true. A hardcoded reassurance becomes a lie the day 9.5's cloud
    port lands and nobody remembers to edit the string."""
    monkeypatch.setattr(api, "SESSIONS", tmp_path / "s")
    (tmp_path / "s").mkdir()

    assert client.get("/api/storage").json()["leaves_machine"] is False

    monkeypatch.setattr(api.prov, "BASE", "https://api.example-vendor.com")
    got = client.get("/api/storage").json()
    assert got["leaves_machine"] is True
    assert got["provider"]["host"] == "https://api.example-vendor.com"


def test_deleting_an_interview_takes_the_recordings_with_it(client, monkeypatch, tmp_path):
    """A product that records someone's voice and cannot remove it has not earned the claim."""
    root = tmp_path / "s"
    d = _recorded_session(root)
    monkeypatch.setattr(api, "SESSIONS", root)
    monkeypatch.setattr(api, "LIVE", tmp_path / "nothing.json")

    got = client.delete("/api/sessions/20260101-000000-stored1")
    assert got.status_code == 200
    assert got.json()["recordings"] == 1 and got.json()["files"] == 3
    assert not d.exists(), "the directory must go, not just its record"
    assert client.get("/api/sessions").json() == []


def test_the_running_interview_cannot_be_deleted(client, monkeypatch, tmp_path):
    """It would leave the runner writing turns into a directory that is not there, and
    "I meant the other one" is the likelier click."""
    root = tmp_path / "s"
    d = _recorded_session(root)
    monkeypatch.setattr(api, "SESSIONS", root)
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"session_id": "20260101-000000-stored1"}), encoding="utf-8")
    monkeypatch.setattr(api, "LIVE", live)

    r = client.delete("/api/sessions/20260101-000000-stored1")
    assert r.status_code == 409
    assert "still running" in r.json()["detail"]
    assert d.exists()


def test_deleting_refuses_a_name_that_is_not_a_session(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    root.mkdir()
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setattr(api, "SESSIONS", root)
    monkeypatch.setattr(api, "LIVE", tmp_path / "nothing.json")

    for name in ("../elsewhere", "missing", "."):
        assert client.delete("/api/sessions/%s" % name).status_code in (404, 405, 307), name
    assert (tmp_path / "elsewhere").exists()


class _Caller:
    """Just enough Request for `_served_remotely`: who asked, and through what."""

    def __init__(self, host="127.0.0.1", headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def test_a_hosted_copy_cannot_claim_to_be_private(client, monkeypatch, tmp_path):
    """The interview module runs on one machine; the IELTS module is meant to be served. The
    same build has to be able to say either, and the hosted one keeps the recordings on
    somebody else's disk even when a local model is doing the reading."""
    monkeypatch.setattr(api, "SESSIONS", tmp_path / "s")
    (tmp_path / "s").mkdir()
    monkeypatch.setenv("MOCKINGBIRD_HOSTED", "1")

    got = client.get("/api/storage").json()
    assert got["served_remotely"] is True
    assert got["leaves_machine"] is True
    # The two exposures stay separate: a local model still reads the answers locally.
    assert got["answers_leave"] is False
    assert "hosted service" in got["why_hosted"]


def test_being_served_is_noticed_without_being_configured(monkeypatch):
    """The signal that matters must not be forgettable. A deploy that never sets the variable
    still gives itself away, by the caller not being on this machine or by the proxy in front
    of it announcing itself."""
    monkeypatch.delenv("MOCKINGBIRD_HOSTED", raising=False)

    assert api._served_remotely(_Caller()) is None
    assert "over the network" in api._served_remotely(_Caller(host="203.0.113.7"))
    assert "proxy" in api._served_remotely(_Caller(headers={"x-forwarded-for": "203.0.113.7"}))
    assert "proxy" in api._served_remotely(_Caller(headers={"forwarded": "for=203.0.113.7"}))


def test_running_it_yourself_still_reads_as_private(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "SESSIONS", tmp_path / "s")
    (tmp_path / "s").mkdir()
    monkeypatch.delenv("MOCKINGBIRD_HOSTED", raising=False)

    got = client.get("/api/storage").json()
    assert got == {**got, "served_remotely": False, "answers_leave": False,
                   "leaves_machine": False, "why_hosted": None}


# ------------------------------------------------ the same criteria across interviews
def _read_session(root, sid, started, rubric, answered=14, scored=10):
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps({
        "session_id": sid, "plan_id": "p", "started_at": started, "status": "complete",
        "plan_snapshot": {"label": "A plan"},
        "questions": [{"phase": "p1", "question_id": "p1.1", "question": "Why?",
                       "answers": ["because"]}],
    }), encoding="utf-8")
    (d / "report.json").write_text(json.dumps({
        "session_id": sid, "started_at": started, "label": "A plan", "text": "",
        "answered": answered, "scored": scored,
        "rubric": [{"name": k, "label": k, "description": "", "met": m, "of": o}
                   for k, (m, o) in rubric.items()],
    }), encoding="utf-8")
    return d


def test_progress_lines_up_the_same_criterion_across_interviews(client, monkeypatch, tmp_path):
    root = tmp_path / "s"
    _read_session(root, "20260101-000000-aaaaaa", "2026-01-01T09:00:00",
                  {"first_person": (3, 6), "describes_action": (9, 10)})
    _read_session(root, "20260202-000000-bbbbbb", "2026-02-02T09:00:00",
                  {"first_person": (5, 6), "describes_action": (9, 10)})
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/progress").json()
    assert got["read"] == 2
    assert [s["session_id"] for s in got["sessions"]] == [
        "20260101-000000-aaaaaa", "20260202-000000-bbbbbb"], "oldest first, so a line reads left to right"

    # The one that moved leads: a criterion sitting still is not what to look at.
    assert got["criteria"][0]["name"] == "first_person"
    assert [p["met"] for p in got["criteria"][0]["points"]] == [3, 5]
    assert [p["of"] for p in got["criteria"][0]["points"]] == [6, 6]


def test_progress_keeps_the_denominator_on_every_point(client, monkeypatch, tmp_path):
    """The rubric table already learned this: a rate without its denominator makes a criterion
    judged on four answers look exactly as settled as one judged on ten."""
    root = tmp_path / "s"
    _read_session(root, "20260101-000000-aaaaaa", "2026-01-01T09:00:00", {"c": (1, 1)})
    _read_session(root, "20260202-000000-bbbbbb", "2026-02-02T09:00:00", {"c": (10, 10)})
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/progress").json()
    points = got["criteria"][0]["points"]
    assert [(p["met"], p["of"], p["rate"]) for p in points] == [(1, 1, 1.0), (10, 10, 1.0)]
    # A point names its column and nothing else: the session it belongs to is `sessions[at]`,
    # so the id and the date are carried once rather than on all sixty points.
    assert sorted(points[0]) == ["at", "met", "of", "rate"]
    assert got["sessions"][points[1]["at"]]["session_id"] == "20260202-000000-bbbbbb"


def test_progress_claims_no_improvement_anywhere(client, monkeypatch, tmp_path):
    """Scores come from model extraction, so two readings of one interview need not agree and
    nothing has measured by how much. A number claiming improvement would be unsupported."""
    root = tmp_path / "s"
    _read_session(root, "20260101-000000-aaaaaa", "2026-01-01T09:00:00", {"c": (2, 10)})
    _read_session(root, "20260202-000000-bbbbbb", "2026-02-02T09:00:00", {"c": (9, 10)})
    monkeypatch.setattr(api, "SESSIONS", root)

    blob = json.dumps(client.get("/api/progress").json())
    assert not [w for w in ("trend", "improve", "better", "worse", "delta", "change")
                if w in blob.lower()]


def test_progress_says_how_many_interviews_have_not_been_read(client, monkeypatch, tmp_path):
    """The gap is the actionable part: this is only as long as the reports that exist, and
    building one is a minutes-long model pass rather than something a page can do."""
    root = tmp_path / "s"
    _read_session(root, "20260101-000000-aaaaaa", "2026-01-01T09:00:00", {"c": (1, 2)})
    for i in range(3):
        d = root / ("20260303-00000%d-cccccc" % i)
        d.mkdir(parents=True)
        (d / "session.json").write_text(json.dumps({
            "session_id": d.name, "plan_id": "p", "started_at": "2026-03-03T09:00:00",
            "status": "complete", "plan_snapshot": {"label": "A plan"},
            "questions": [{"phase": "p1", "question_id": "p1.1", "question": "Why?",
                           "answers": ["because"]}],
        }), encoding="utf-8")
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/progress").json()
    assert got["read"] == 1 and got["readable"] == 4


def test_progress_survives_a_report_written_before_a_field_existed(client, monkeypatch, tmp_path):
    """The one cached report on this machine predates delivery entirely, and carries no label or
    description on its criteria. A reader that assumed today's shape would fail on exactly the
    history it exists to show."""
    root = tmp_path / "s"
    d = root / "20260101-000000-aaaaaa"
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({
        "session_id": d.name, "started_at": "2026-01-01T09:00:00",
        "rubric": [{"name": "c", "met": 1, "of": 2}],
    }), encoding="utf-8")
    (d / "session.json").write_text('{"status": "complete", "questions": []}', encoding="utf-8")
    monkeypatch.setattr(api, "SESSIONS", root)

    got = client.get("/api/progress").json()
    assert got["read"] == 1
    assert got["criteria"][0]["name"] == "c"
    assert got["criteria"][0]["description"] == ""
    assert got["criteria"][0]["points"] == [{"at": 0, "met": 1, "of": 2, "rate": 0.5}]
