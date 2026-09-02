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
