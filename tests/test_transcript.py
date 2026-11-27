"""The interview line by line (V1.2_PLAN P4 step 5): `transcript.lines`, its route, and the
HTML export's "what was said", which reads the same lines."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import export, transcript  # noqa: E402

SID = "20261126-222221-531904"
Q1 = "Tell me about a time you decided which insight to share first."
Q2 = "What did you check before you sent it?"
DUTY = "turn our sales data into answers the commercial team can act on"


def _turn(i, qid, question, said, say, act="advance", audio=None):
    return {"index": i, "phase": qid.split(".")[0], "question_id": qid, "question": question,
            "utterance": said, "act": act, "say": say, "ok": False, "ask": "Is that ok?",
            "guards": ["hedge-stripped"], "at": "2026-11-26T11:22:%02d+00:00" % i,
            "audio": audio, "heard": None}


TURNS = [
    _turn(0, "behavioural_core.1", Q1, "We had three findings.", "What did you pick?", "probe",
          audio="data/sessions/%s/audio/b1-0.wav" % SID),
    _turn(1, "behavioural_core.1", Q1, "The churn one, because it cost most.", "Thank you."),
    _turn(2, "collaboration.1", Q2, "I reconciled it to finance.", "Thanks for that."),
]

SESSION = {
    "session_id": SID,
    "plan_snapshot": {"field": "data_analytics",
                      "generated": [{"text": Q1, "duty": DUTY, "phase": "behavioural_core"}]},
    "questions": [
        {"phase": "behavioural_core", "question_id": "behavioural_core.1", "question": Q1,
         "answers": ["We had three findings.", "The churn one, because it cost most."]},
        {"phase": "collaboration", "question_id": "collaboration.1", "question": Q2,
         "answers": ["I reconciled it to finance."]},
    ],
}


def test_every_line_in_order_with_each_question_once_before_its_answers():
    got = transcript.lines(SESSION, TURNS)
    assert [(x["who"], x["kind"], x["text"]) for x in got] == [
        ("interviewer", "question", Q1),
        ("candidate", "answer", "We had three findings."),
        ("interviewer", "reply", "What did you pick?"),
        ("candidate", "answer", "The churn one, because it cost most."),
        ("interviewer", "reply", "Thank you."),
        ("interviewer", "question", Q2),
        ("candidate", "answer", "I reconciled it to finance."),
        ("interviewer", "reply", "Thanks for that."),
    ]
    assert [x["turn"] for x in got if x["kind"] == "answer"] == [0, 1, 2]
    assert got[1]["at"] == "2026-11-26T11:22:00+00:00" and got[1]["phase"] == "behavioural_core"


def test_only_the_dialogue_leaves_the_decision_record():
    keys = {k for x in transcript.lines(SESSION, TURNS) for k in x}
    assert not keys & {"act", "ok", "guards", "ask", "heard"}


def test_a_written_question_carries_its_duty():
    got = transcript.lines(SESSION, TURNS)
    assert got[0]["duty"] == DUTY and got[5]["duty"] is None


def test_a_correction_rides_beside_what_was_heard_while_it_still_matches():
    record = {"answers": {"behavioural_core.1": [
        {"index": 1, "original": "The churn one, because it cost most.",
         "text": "The churn one, because it cost the most."}],
        "collaboration.1": [{"index": 0, "original": "an answer since replaced", "text": "x"}]}}
    got = [x for x in transcript.lines(SESSION, TURNS, record) if x["kind"] == "answer"]
    assert got[1]["text"] == "The churn one, because it cost most."
    assert got[1]["corrected"] == "The churn one, because it cost the most."
    assert got[0]["corrected"] is None and got[2]["corrected"] is None


def test_a_recording_is_offered_only_where_it_is_kept(tmp_path):
    (tmp_path / "audio").mkdir()
    assert transcript.lines(SESSION, TURNS, None, tmp_path)[1]["audio"] is None
    (tmp_path / "audio" / "b1-0.wav").write_bytes(b"RIFF")
    got = transcript.lines(SESSION, TURNS, None, tmp_path)
    assert got[1]["audio"] == "b1-0.wav" and got[3]["audio"] is None
    assert transcript.lines(SESSION, TURNS)[1]["audio"] is None


def test_an_empty_answer_or_reply_is_not_a_line():
    quiet = [_turn(0, "warmup.1", "Tell me about yourself.", "  ", "")]
    assert [x["kind"] for x in transcript.lines({}, quiet)] == ["question"]


def test_the_export_says_the_same_lines(tmp_path):
    page = export.html_document({"session_id": SID, "rubric": [], "text": ""}, SESSION, TURNS,
                                tmp_path, embed_audio=False)
    said = page[page.index("<h2>what was said</h2>"):]
    assert said.count('class="turn them q"') == 2
    assert said.index(Q1) < said.index("We had three findings.") < said.index(Q2)
    assert "Interviewer, written from the description</span>%s" % Q1 in said


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    d = tmp_path / "sessions" / SID
    (d / "audio").mkdir(parents=True)
    (d / "audio" / "b1-0.wav").write_bytes(b"RIFF")
    (d / "session.json").write_text(json.dumps(SESSION), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps({"session_id": SID, "turns": TURNS}),
                                       encoding="utf-8")
    monkeypatch.setattr(main, "SESSIONS", tmp_path / "sessions")
    return TestClient(main.app)


def test_the_route_serves_every_line_without_a_model(api):
    got = api.get("/api/sessions/%s/transcript" % SID)
    assert got.status_code == 200
    body = got.json()
    assert body["turns"] == 3 and len(body["lines"]) == 8
    assert body["lines"][1]["audio"] == "b1-0.wav"
    assert api.get("/api/sessions/nope/transcript").status_code == 404
    assert api.get("/api/sessions/..%2Fsessions/transcript").status_code == 404
