"""Correcting what was heard before it is scored (FR-31; V1.1_PLAN P5), and the slice seam."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audio, corrections, session  # noqa: E402
from app.runner import Runner  # noqa: E402
from test_runner import PLAN, ScriptedProvider, d  # noqa: E402

_RAW = {"questions": [
    {"phase": "p1", "question_id": "p1.1", "question": "Tell me about a migration.",
     "answers": ["We moved to queueover on Friday.", "It took two hours."]},
    {"phase": "p1", "question_id": "p1.2", "question": "What did you measure?",
     "answers": ["Latency at p99."]}]}


def raw():
    return copy.deepcopy(_RAW)


# ------------------------------------------------------------------ the slice seam
@pytest.mark.parametrize("prev,nxt,want", [
    ("for a", "A friend of mine", "friend of mine"),
    ("it was the", "the cache, honestly", "cache, honestly"),
    ("we shipped it.", "It worked", "It worked"),
    ("I measured", "latency first", "latency first"),
    ("", "Hello there", "Hello there"),
    ("something", "", ""),
])
def test_a_word_repeated_across_a_cut_is_dropped_once_and_nothing_else(prev, nxt, want):
    assert audio.seam(prev, nxt) == want


def test_the_seam_never_reaches_past_the_first_word():
    assert audio.seam("that that", "that that was it") == "that was it"


# ------------------------------------------------------------------ what was heard, per turn
def test_a_spoken_answer_keeps_what_was_heard_beside_what_was_sent(tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("advance", "Thanks."), d("advance", "Thanks.")]), PLAN, state)
    asyncio.run(r.ask())
    asyncio.run(r.submit("We moved to cutover.", None, heard="We moved to queueover."))
    turn = state.turns[-1]
    assert turn.utterance == "We moved to cutover." and turn.heard == "We moved to queueover."
    asyncio.run(r.submit("typed"))
    assert state.turns[-1].heard is None, "a typed answer has nothing heard"


def test_a_1_0_transcript_without_heard_still_loads():
    t = session.Turn(index=0, phase="p", question_id="q", question="Q?", utterance="u",
                     act="advance", say="", ok=True, ask="")
    assert t.heard is None


# ------------------------------------------------------------------ the corrections file
def test_only_changes_are_kept_and_a_review_with_none_still_counts(tmp_path):
    rec = corrections.save(tmp_path, raw(), [
        {"question_id": "p1.1", "index": 0, "text": "We moved to cutover on Friday."},
        {"question_id": "p1.1", "index": 1, "text": "It took two hours."},
        {"question_id": "p1.2", "index": 0, "text": "  Latency at p99.  "}])
    assert rec["answers"] == {"p1.1": [{"index": 0, "original": "We moved to queueover on Friday.",
                                        "text": "We moved to cutover on Friday."}]}
    assert corrections.load(tmp_path)["answers"] == rec["answers"]
    assert corrections.save(tmp_path, raw(), [])["answers"] == {}
    assert corrections.load(tmp_path) is not None, "reviewed, even with nothing to change"


@pytest.mark.parametrize("edit,why", [
    ({"question_id": "p9.9", "index": 0, "text": "x"}, "no question"),
    ({"question_id": "p1.1", "index": 5, "text": "x"}, "no answer"),
    ({"question_id": "p1.1", "index": 0, "text": "   "}, "to nothing"),
])
def test_a_correction_that_does_not_fit_the_interview_is_refused(tmp_path, edit, why):
    with pytest.raises(corrections.CorrectionError, match=why):
        corrections.save(tmp_path, raw(), [edit])


def test_scoring_reads_the_corrected_text_and_keeps_the_original(tmp_path):
    corrections.save(tmp_path, raw(), [
        {"question_id": "p1.1", "index": 0, "text": "We moved to cutover on Friday."}])
    states = [session.QuestionState(**q) for q in _RAW["questions"]]
    changes = corrections.apply(states, corrections.load(tmp_path))
    assert states[0].answers[0] == "We moved to cutover on Friday."
    assert changes == [{"question_id": "p1.1", "question": "Tell me about a migration.",
                        "index": 0, "original": "We moved to queueover on Friday.",
                        "corrected": "We moved to cutover on Friday."}]
    assert _RAW["questions"][0]["answers"][0] == "We moved to queueover on Friday."


def test_a_correction_whose_original_moved_is_skipped_not_misapplied(tmp_path):
    corrections.save(tmp_path, raw(), [
        {"question_id": "p1.1", "index": 0, "text": "We moved to cutover on Friday."}])
    states = [session.QuestionState(**q) for q in raw()["questions"]]
    states[0].answers[0] = "Something else entirely."
    assert corrections.apply(states, corrections.load(tmp_path)) == []
    assert states[0].answers[0] == "Something else entirely."


def test_review_pairs_each_answer_with_its_recording_and_what_was_heard(tmp_path):
    turns = [{"question_id": "p1.1", "utterance": "We moved to queueover on Friday.",
              "audio": "data/sessions/s/audio/answer-1.wav", "heard": "We moved to queueover on Friday."},
             {"question_id": "p1.2", "utterance": "Latency at p99.", "audio": None, "heard": None}]
    rows = corrections.review(tmp_path, raw(), turns)
    first = rows[0]
    assert first["audio"] == "answer-1.wav" and first["spoken"] and not first["corrected"]
    assert rows[2]["spoken"] is False
    corrections.save(tmp_path, raw(), [{"question_id": "p1.2", "index": 0, "text": "Latency at P99."}])
    rows = corrections.review(tmp_path, raw(), turns)
    assert rows[2]["corrected"] and rows[2]["text"] == "Latency at P99."
    assert rows[2]["original"] == "Latency at p99."


# ------------------------------------------------------------------ the HTTP surface
@pytest.fixture()
def client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    root = tmp_path / "sessions"
    root.mkdir(exist_ok=True)
    s = root / "s1"
    s.mkdir()
    (s / "session.json").write_text(json.dumps({**raw(), "session_id": "s1",
                                                "plan_snapshot": {"phases": []}}))
    (s / "transcript.json").write_text(json.dumps({"turns": [
        {"question_id": "p1.1", "utterance": "We moved to queueover on Friday.",
         "heard": "We moved to queueover on Friday.", "audio": None}]}))
    monkeypatch.setattr(api, "SESSIONS", root)
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    return TestClient(api.app), api, s


def test_corrections_round_trip_and_make_the_cached_report_stale(client):
    c, api, s = client
    (s / "report.json").write_text("{}")
    old = time.time() - 60
    for f in s.iterdir():
        os.utime(f, (old, old))
    assert api._report_is_fresh(s) is not None
    view = c.get("/api/sessions/s1/corrections").json()
    assert view["spoken"] == 1 and not view["reviewed"] and view["editable"]
    got = c.put("/api/sessions/s1/corrections", json={"answers": [
        {"question_id": "p1.1", "index": 0, "text": "We moved to cutover on Friday."}]})
    assert got.status_code == 200 and got.json()["reviewed"]
    assert api._report_is_fresh(s) is None, "a correction must rebuild the report"


def test_the_interview_still_running_cannot_be_corrected(client):
    c, api, _ = client
    api.LIVE.write_text(json.dumps({"session_id": "s1", "status": "running"}))
    assert c.get("/api/sessions/s1/corrections").json()["editable"] is False
    got = c.put("/api/sessions/s1/corrections", json={"answers": []})
    assert got.status_code == 409


def test_a_correction_is_scored_and_shown_in_the_report(client, monkeypatch):
    c, api, s = client
    read = []

    async def fake_observe(provider, qid, question, answers):
        read.append(list(answers))
        from app import observe
        return observe.Observation(question_id=qid, question=question, answers=answers)

    monkeypatch.setattr(api.observe, "observe", fake_observe)
    c.put("/api/sessions/s1/corrections", json={"answers": [
        {"question_id": "p1.1", "index": 0, "text": "We moved to cutover on Friday."}]})
    rep = c.get("/api/sessions/s1/report").json()
    assert ["We moved to cutover on Friday.", "It took two hours."] in read
    assert rep["corrections"][0]["original"] == "We moved to queueover on Friday."
    raw = json.loads((s / "session.json").read_text())
    assert raw["questions"][0]["answers"][0] == "We moved to queueover on Friday."


def test_the_answer_endpoint_records_what_was_heard(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    from app import session as sess

    plan = json.loads(json.dumps(PLAN))
    state = sess.new_session(plan)
    r = Runner(ScriptedProvider([d("advance", "Thanks.")]), plan, state)
    asyncio.run(r.ask())
    monkeypatch.setattr(api, "_runner", lambda: r)
    monkeypatch.setattr(api.resume, "write", lambda *a, **k: None)
    got = TestClient(api.app).post("/api/session/answer", json={
        "text": "We moved to cutover.", "heard": "We moved to queueover."})
    assert got.status_code == 200
    assert state.turns[-1].heard == "We moved to queueover."
