"""The HTTP surface. What matters here is that it enforces nothing of its own: every rule is
the domain's, so the web and the terminal cannot disagree about what may be asked."""

from __future__ import annotations

import json
import sys
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
