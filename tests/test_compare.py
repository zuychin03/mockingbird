"""Compare, the Markdown export and example answers (FR-25, FR-22, FR-21; V1.1_PLAN P6)."""

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

from app import compare, corrections, examples, export, score  # noqa: E402
from app.provider import Completion  # noqa: E402


def _ev(qid, question, met, quote=None):
    return {"question_id": qid, "question": question, "met": met, "quote": quote}


Q1, Q2, Q3 = "Tell me about a migration.", "What did you measure?", "How did it end?"

REPORT = {
    "session_id": "20260101-090000-aaaaaa", "label": "Backend round",
    "started_at": "2026-01-01T09:00:00", "asked": 3, "answered": 3, "scored": 3,
    "text": "HOW IT WENT\n===========\n\n  You named the system every time.\n\n  - Say how it ended.\n",
    "rubric": [
        {"name": "sets_context", "label": "Sets the scene", "description": "said where",
         "met": 3, "of": 3, "evidence": [_ev("p1.1", Q1, True, "on the billing service"),
                                         _ev("p1.2", Q2, True), _ev("p1.3", Q3, True)]},
        {"name": "states_outcome", "label": "Says how it ended",
         "description": "said how it turned out", "met": 1, "of": 3,
         "evidence": [_ev("p1.1", Q1, True), _ev("p1.2", Q2, False), _ev("p1.3", Q3, False)]},
        {"name": "specific_detail", "label": "Gives a figure",
         "description": "gave a concrete figure or quantity", "met": 1, "of": 3,
         "evidence": [_ev("p1.1", Q1, True), _ev("p1.2", Q2, False), _ev("p1.3", Q3, True)]},
    ],
    "delivery": {"answers": [{"question_id": "p1.1", "audio": "a.wav", "why": None,
                              "articulation_rate": 4.2, "wpm": 148.6, "pause_count": 2,
                              "mid_clause_pauses": 1}],
                 "spoken": 1, "articulation_rate": 4.2, "wpm": 148.6, "pause_count": 2,
                 "mid_clause_share": 0.5, "speaking_seconds": 30.0},
    "corrections": [],
}

SESSION = {
    "session_id": "20260101-090000-aaaaaa", "plan_id": "backend_v1",
    "started_at": "2026-01-01T09:00:00", "status": "complete",
    "provenance": {"model_id": "qwen3-4b-instruct-2507", "quantization": "Q4_K_M"},
    "plan_snapshot": {"label": "Backend round", "phases": []},
    "questions": [
        {"phase": "p1", "question_id": "p1.1", "question": Q1,
         "answers": ["We moved billing to Postgres in 2 weeks.", "Errors fell 40%."]},
        {"phase": "p1", "question_id": "p1.2", "question": Q2, "answers": ["Mostly *latency* | p99."]},
        {"phase": "p1", "question_id": "p1.3", "question": Q3, "answers": ["We shipped 3 services."]},
    ],
}


def rs(**over):
    r, s = copy.deepcopy(REPORT), copy.deepcopy(SESSION)
    r.update(over.pop("report", {}))
    s.update(over.pop("session", {}))
    return r, s


# ------------------------------------------------------------------ the Markdown export
def test_markdown_carries_the_report_the_rubric_and_every_answer():
    md = export.markdown_document(*rs())
    assert md.startswith("# Backend round\n")
    assert "## How it went" in md and "- Say how it ended." in md
    assert "| Says how it ended | 1/3 | said how it turned out |" in md
    assert md.index("Says how it ended") < md.index("| Sets the scene"), "weakest first"
    assert "### 1. Tell me about a migration." in md
    assert "> We moved billing to Postgres in 2 weeks." in md
    assert "Met: Sets the scene. Missed: Says how it ended, Gives a figure." in md
    assert "| p1.1 | 4.2 | 149 | 2 | 1 |" in md
    assert "- quantization: Q4_K_M" in md


def test_an_answer_cannot_become_markdown_structure():
    md = export.markdown_document(*rs())
    assert r"> Mostly \*latency\* \| p99." in md
    r, s = rs()
    s["questions"][0]["answers"] = ["# not a heading <script>x</script> [a](b)"]
    md = export.markdown_document(r, s)
    assert r"> \# not a heading \<script\>x\</script\> \[a\](b)" in md


def test_a_corrected_answer_reads_as_scored_with_what_was_heard_beside_it():
    r, s = rs(report={"corrections": [{"question_id": "p1.3", "index": 0,
                                       "original": "We shipped 3 services.",
                                       "corrected": "We shipped three services."}]})
    md = export.markdown_document(r, s)
    assert "> We shipped three services." in md
    assert "The recogniser heard:* We shipped 3 services." in md
    assert s["questions"][2]["answers"][0] == "We shipped 3 services."


# ------------------------------------------------------------------ compare
def test_compare_pairs_questions_by_wording_and_puts_the_earlier_interview_first():
    later = rs(report={"session_id": "b", "started_at": "2026-02-01T09:00:00"},
               session={"session_id": "b"})
    later[0]["rubric"][1].update(met=3, evidence=[_ev("p1.1", Q1, True), _ev("p1.2", Q2, True),
                                                  _ev("p1.3", Q3, True)])
    out = compare.compare(later, rs())
    assert out["a"]["started_at"] < out["b"]["started_at"]
    assert out["same_plan"] and out["note"] is None
    row = next(c for c in out["criteria"] if c["name"] == "states_outcome")
    assert row["a"] == {"met": 1, "of": 3} and row["b"] == {"met": 3, "of": 3}
    q2 = next(q for q in out["questions"] if q["question"] == Q2)
    assert q2["a"]["met"]["states_outcome"] is False and q2["b"]["met"]["states_outcome"] is True
    assert out["delivery"]["a"]["wpm"] == 148.6


def test_different_plans_are_compared_with_a_note_and_unshared_questions_stay_apart():
    other = rs(report={"session_id": "b", "started_at": "2026-02-01T09:00:00"},
               session={"session_id": "b", "plan_id": "frontend_v1"})
    other[1]["questions"][0]["question"] = "Tell me about a redesign."
    out = compare.compare(rs(), other)
    assert not out["same_plan"] and "different plans" in out["note"]
    alone = [q for q in out["questions"] if q["a"] is None or q["b"] is None]
    assert {q["question"] for q in alone} == {Q1, "Tell me about a redesign."}


def test_a_criterion_only_one_interview_scored_is_shown_against_nothing():
    other = rs(report={"session_id": "b", "started_at": "2026-02-01T09:00:00"})
    other[0]["rubric"] = other[0]["rubric"][:1]
    row = next(c for c in compare.compare(rs(), other)["criteria"] if c["name"] == "states_outcome")
    assert row["a"] and row["b"] is None


# ------------------------------------------------------------------ example answers
def test_the_weakest_answers_are_the_ones_that_met_the_smallest_share():
    picked = examples.weakest(*rs())
    assert [p["question_id"] for p in picked] == ["p1.2", "p1.3"], "p1.1 met everything"
    assert [m["label"] for m in picked[0]["missing"]] == ["Says how it ended", "Gives a figure"]
    assert picked[0]["answer"] == "Mostly *latency* | p99."
    assert len(examples.weakest(*rs(), most=1)) == 1


def test_the_prompt_names_what_was_missing_and_asks_for_placeholders_not_facts():
    item = examples.weakest(*rs())[0]
    p = examples.prompt(item)
    assert Q2 in p and item["answer"] in p and "- said how it turned out" in p
    assert "square brackets" in examples.SYSTEM


class Writer:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    async def complete(self, system, user, schema=None, max_tokens=400, **kw):
        self.calls.append((system, user, schema))
        return Completion(text=json.dumps({"sentences": [self.texts.pop(0)]}), prompt_tokens=50,
                          decode_tokens=80, cost_usd=0.0)

    def describe(self):
        return {"mode": "cloud", "vendor": "groq", "label": "Groq", "host": "api.groq.com",
                "model": "qwen/qwen3.8-27b", "measured": True}


def test_an_empty_example_is_an_error_not_a_blank_card():
    with pytest.raises(examples.ExampleError):
        asyncio.run(examples.write(Writer([" "]), examples.weakest(*rs())[:1]))


def test_the_sentences_are_joined_into_one_answer():
    class Split(Writer):
        async def complete(self, *a, **k):
            return Completion(text=json.dumps({"sentences": ["I led it. ", "", " It shipped."]}))

    got = asyncio.run(examples.write(Split([]), examples.weakest(*rs())[:1]))
    assert got[0]["example"] == "I led it. It shipped."


def test_an_example_goes_stale_when_its_answer_is_corrected(tmp_path):
    r, s = rs()
    items = asyncio.run(examples.write(Writer(["one", "two"]), examples.weakest(r, s)))
    rec = examples.save(tmp_path, items, Writer([]).describe(), {"calls": 2})
    assert not any(e["stale"] for e in examples.view(rec, s, [])["examples"])
    changed = [{"question_id": "p1.2", "index": 0, "original": "Mostly *latency* | p99.",
                "corrected": "Latency at p99."}]
    stale = {e["question_id"]: e["stale"] for e in examples.view(rec, s, changed)["examples"]}
    assert stale == {"p1.2": True, "p1.3": False}


# ------------------------------------------------------------------ the HTTP surface
@pytest.fixture()
def api_env(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    root = tmp_path / "sessions"
    for sid, started in (("20260101-090000-aaaaaa", "2026-01-01T09:00:00"),
                         ("20260201-090000-bbbbbb", "2026-02-01T09:00:00")):
        d = root / sid
        d.mkdir(parents=True)
        r, s = rs(report={"session_id": sid, "started_at": started},
                  session={"session_id": sid, "started_at": started})
        (d / "session.json").write_text(json.dumps(s))
        (d / "transcript.json").write_text(json.dumps({"turns": []}))
        old = time.time() - 60
        for f in d.iterdir():
            os.utime(f, (old, old))
        (d / "report.json").write_text(json.dumps(r))
    monkeypatch.setattr(api, "SESSIONS", root)
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    return TestClient(api.app), api, root


def test_the_markdown_route_downloads_a_file(api_env):
    c, _, _ = api_env
    got = c.get("/api/sessions/20260101-090000-aaaaaa/export.md")
    assert got.status_code == 200 and got.headers["content-type"].startswith("text/markdown")
    assert got.headers["content-disposition"].endswith('.md"')
    assert got.text.startswith("# Backend round")


def test_the_compare_route(api_env):
    c, _, _ = api_env
    got = c.get("/api/compare", params={"a": "20260201-090000-bbbbbb", "b": "20260101-090000-aaaaaa"})
    assert got.status_code == 200
    assert got.json()["a"]["session_id"] == "20260101-090000-aaaaaa"
    assert c.get("/api/compare", params={"a": "x", "b": "x"}).status_code == 400
    assert c.get("/api/compare", params={"a": "../sessions/20260101-090000-aaaaaa",
                                         "b": "20260201-090000-bbbbbb"}).status_code == 404


def cloud(monkeypatch, api, writer):
    conf = {**writer.describe()}
    monkeypatch.setattr(api.prov, "configured", lambda: conf)
    monkeypatch.setattr(api.prov, "current", lambda: writer)


def test_examples_are_not_offered_or_written_in_local_mode(api_env):
    c, _, _ = api_env
    sid = "20260101-090000-aaaaaa"
    assert c.get("/api/sessions/%s/examples" % sid).json()["offer"] is None
    assert c.post("/api/sessions/%s/examples" % sid).status_code == 409


def test_examples_for_a_local_interview_ask_first_then_are_written_and_kept(api_env, monkeypatch):
    c, api, root = api_env
    sid = "20260101-090000-aaaaaa"
    w = Writer(["I measured [the p99 you saw].", "We shipped three and [the outcome]."])
    cloud(monkeypatch, api, w)
    view = c.get("/api/sessions/%s/examples" % sid).json()
    assert view["offer"]["switching"] and view["examples"] is None
    refused = c.post("/api/sessions/%s/examples" % sid)
    assert refused.status_code == 409 and "Groq" in refused.json()["detail"] and not w.calls
    got = c.post("/api/sessions/%s/examples?ack=true" % sid).json()
    rec = got["examples"]
    assert [e["question_id"] for e in rec["examples"]] == ["p1.2", "p1.3"]
    assert rec["provider"]["model"] == "qwen/qwen3.8-27b" and rec["usage"]["calls"] == 2
    assert w.calls[0][2] == examples.SCHEMA
    assert api._report_is_fresh(root / sid) is not None, "writing examples must not rebuild"


def test_examples_for_an_interview_held_on_that_model_need_no_second_ask(api_env, monkeypatch):
    c, api, root = api_env
    sid = "20260101-090000-aaaaaa"
    w = Writer(["a", "b"])
    cloud(monkeypatch, api, w)
    raw = json.loads((root / sid / "session.json").read_text())
    raw["provenance"]["provider"] = w.describe()
    (root / sid / "session.json").write_text(json.dumps(raw))
    (root / sid / "report.json").touch()
    assert c.post("/api/sessions/%s/examples" % sid).status_code == 200


def test_corrections_still_rebuild_the_report(api_env):
    c, api, root = api_env
    sid = "20260101-090000-aaaaaa"
    c.put("/api/sessions/%s/corrections" % sid, json={"answers": [
        {"question_id": "p1.2", "index": 0, "text": "Latency at p99."}]})
    assert api._report_is_fresh(root / sid) is None
    assert corrections.load(root / sid)["answers"]["p1.2"][0]["text"] == "Latency at p99."


def test_met_by_question_reads_the_rubric_back():
    assert score.met_by_question(REPORT["rubric"])["p1.2"] == {
        "sets_context": True, "states_outcome": False, "specific_detail": False}
    assert score.met_by_question([{"name": "x", "met": 1, "of": 1}]) == {}
