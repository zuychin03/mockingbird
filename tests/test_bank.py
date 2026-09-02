"""The bank and its closed vocabulary. Every check here fires at LOAD, before an interview."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank  # noqa: E402
from app import session as sess  # noqa: E402

BANK = Path(__file__).resolve().parent.parent / "config" / "question_bank.json"


def _write(tmp_path, **overrides):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw.update(overrides)
    p = tmp_path / "bank.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_the_shipped_bank_loads():
    b = bank.load(BANK)
    assert b.questions
    assert b.competencies


def test_every_competency_has_at_least_one_question():
    """A competency nothing covers is a hole the planner cannot fill from reviewed text, and
    the JD that asks for it would silently get no coverage."""
    b = bank.load(BANK)
    for name in b.competencies:
        assert b.for_competency(name), name


def test_every_shipped_question_is_curated_not_generated():
    """FR-6 asks every scripted question verbatim, which is only a guarantee while the text
    is reviewed. Generation is allowed, but nothing arrives in the file pre-marked as it."""
    for q in bank.load(BANK).questions:
        assert q.source == "curated", q.id
        assert not q.generated


def test_a_question_tagged_with_an_unknown_competency_is_refused(tmp_path):
    """The `rubric_criteria` failure in another costume: an unmatched tag means the question
    is never selected, with no error and no warning."""
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["questions"][0]["competencies"] = ["communication"]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown competencies"):
        bank.load(p)


def test_communication_is_not_in_the_vocabulary():
    """7.36 removed it from the rubric as unobservable, and it is the first word a model
    reaches for when asked to name a competency."""
    assert "communication" not in bank.load(BANK).competencies


def test_a_duplicate_id_is_refused(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["questions"].append(dict(raw["questions"][0]))
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        bank.load(p)


def test_an_untagged_question_is_refused(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["questions"][0]["competencies"] = []
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no competency"):
        bank.load(p)


def test_an_unknown_shape_or_source_is_refused(tmp_path):
    for field, value, match in (("shape", "chat", "shape"), ("source", "invented", "source")):
        raw = json.loads(BANK.read_text(encoding="utf-8"))
        raw["questions"][0][field] = value
        p = tmp_path / ("b_%s.json" % field)
        p.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            bank.load(p)


def test_an_uncovered_competency_is_refused(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["competencies"]["deployment"] = "shipping to production"
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no question covers"):
        bank.load(p)


def test_for_competency_refuses_a_name_outside_the_vocabulary():
    with pytest.raises(KeyError):
        bank.load(BANK).for_competency("communication")


def test_the_bank_carries_the_questions_the_hand_written_plan_already_uses():
    """The shipped plan is the only interview proven end to end. A bank that could not
    reproduce it would be starting from weaker text than the product already has."""
    plan = sess.load_plan(Path(__file__).resolve().parent.parent / "config"
                          / "interview_swe_general.json")
    scripted = {q for p in plan["phases"] for q in p.get("questions", [])
                if p.get("scored") or p.get("observation_shape") == "design"}
    banked = {q.text for q in bank.load(BANK).questions}
    missing = scripted - banked
    assert not missing, "the bank cannot reproduce: %s" % missing


def test_the_bank_offers_a_choice_for_every_competency():
    """Selection is only meaningful where there is more than one candidate; with one question
    per competency the planner is a lookup table and every generated plan is identical."""
    b = bank.load(BANK)
    thin = [n for n in b.competencies if len(b.for_competency(n)) < 2]
    assert not thin, "only one question for: %s" % ", ".join(thin)


def test_status_is_required_never_defaulted(tmp_path):
    """The `answer_shape` lesson. A missing status defaulting to approved would make an
    unreviewed question askable by omission, which is the one way this fails quietly."""
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    del raw["questions"][0]["status"]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="status"):
        bank.load(p)


def test_a_proposed_question_is_not_offered_for_selection(tmp_path):
    """The guarantee the whole design rests on: the agent draws only from what a person wrote
    or a person approved."""
    b = bank.load(BANK)
    proposal = bank.Question(id="gen.mentoring.99", text="Tell me about coaching someone?",
                             competencies=("mentoring",), shape="star",
                             source="generated", status="proposed")
    b2 = bank.with_question(b, proposal)

    assert proposal not in b2.for_competency("mentoring")
    assert proposal in b2.for_competency("mentoring", askable_only=False)
    assert proposal in b2.proposed
    assert not proposal.askable


def test_approval_flips_status_and_never_source():
    """FR-2 requires a generated question to stay marked as generated after approval, so a
    reader can always tell where the text came from."""
    b = bank.load(BANK)
    proposal = bank.Question(id="gen.learning.99", text="Tell me about learning something?",
                             competencies=("learning",), shape="star",
                             source="generated", status="proposed")
    b2 = bank.approve(bank.with_question(b, proposal), "gen.learning.99")
    approved = [q for q in b2.questions if q.id == "gen.learning.99"][0]

    assert approved.askable
    assert approved.source == "generated", "provenance must survive approval"
    assert approved.generated
    assert approved in b2.for_competency("learning")


def test_approving_twice_is_refused():
    b = bank.load(BANK)
    with pytest.raises(ValueError, match="already approved"):
        bank.approve(b, b.questions[0].id)


def test_a_competency_covered_only_by_proposals_is_still_uncovered(tmp_path):
    """Coverage is about what can be ASKED. A proposal is not coverage until someone reads
    it, or the planner reports a hole as filled while the interview still has one."""
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["competencies"]["deployment"] = "shipping to production"
    raw["questions"].append({"id": "gen.deploy.1", "text": "How do you deploy?",
                             "competencies": ["deployment"], "shape": "star",
                             "source": "generated", "status": "proposed"})
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="no question covers"):
        bank.load(p)


def test_saving_round_trips_through_the_validator(tmp_path):
    b = bank.load(BANK)
    out = tmp_path / "saved.json"
    bank.save(b, out)
    again = bank.load(out)
    assert [q.id for q in again.questions] == [q.id for q in b.questions]
    assert all(q.status == "approved" for q in again.questions)
    assert not (tmp_path / "saved.tmp").exists(), "the temp file is not left behind"
