"""FR-3: a plan is reviewed before anyone is interviewed with it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, planner, review  # noqa: E402
from app import session as sess  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANK = bank.load(ROOT / "config" / "question_bank.json")
TEMPLATE = ROOT / "config" / "interview_swe_general.json"


def draft(*names):
    names = names or ("data_modelling", "incident_response", "collaboration")
    spec = planner.JobSpec(role="Senior Backend Engineer", seniority="senior",
                           requirements=tuple(planner.Requirement(n, "x") for n in names))
    a = planner.assemble(spec, BANK, template=TEMPLATE)
    return review.from_assembled(a, BANK, spec)


def test_a_reviewed_plan_still_loads(tmp_path):
    d = draft()
    d = review.move(d, "behavioural_core", 0, 2)
    d = review.edit(d, "collaboration", 0, "Tell me about a disagreement you lost?")
    d = review.delete(d, "technical_experience", 0)
    out = tmp_path / "reviewed.json"
    review.save(d, out)
    assert sess.load_plan(out)


def test_every_operation_revalidates_immediately():
    """A draft the runner would refuse is refused when it is created. The alternative is
    discovering it at the start of an interview, which is the worst possible moment."""
    d = draft()
    with pytest.raises(ValueError, match="no questions"):
        # A scored phase with nothing in it gives the rubric a denominator of zero.
        single = review.delete(review.delete(d, "collaboration", 0), "collaboration", 0)
        assert single


def test_structural_phases_are_not_editable():
    """Warmup carries the AI disclosure and closing carries the sign-off. Changing those is a
    different decision from planning an interview."""
    d = draft()
    for phase in ("warmup", "closing"):
        with pytest.raises(ValueError, match="structural"):
            review.edit(d, phase, 0, "Something else entirely?")


def test_a_proposal_cannot_be_added_to_a_plan_by_hand():
    """The gate `assemble` applies must not be reachable past by a reviewer."""
    proposal = bank.Question(id="gen.perf.99", text="A proposed latency question?",
                             competencies=("performance",), shape="star",
                             source="generated", status="proposed")
    d = draft()
    d = review.propose_into_bank(d, proposal)
    with pytest.raises(ValueError, match="Approve it first"):
        review.add_from_bank(d, "technical_experience", "gen.perf.99")


def test_approving_makes_it_addable_but_does_not_change_the_plan():
    """Approval and inclusion are separate acts, so approving never silently rewrites the
    interview in front of you."""
    proposal = bank.Question(id="gen.perf.99", text="A proposed latency question?",
                             competencies=("performance",), shape="star",
                             source="generated", status="proposed")
    d = review.propose_into_bank(draft(), proposal)
    before = d.all_questions

    d = review.approve(d, "gen.perf.99")
    assert d.all_questions == before, "approval must not touch the plan"

    d = review.add_from_bank(d, "technical_experience", "gen.perf.99")
    assert proposal.text in d.all_questions


def test_an_edited_question_keeps_what_it_was():
    """The change should be visible rather than silent: a saved plan otherwise looks
    hand-written and nobody can tell what the planner actually produced."""
    d = draft()
    was = d.questions("collaboration")[0]
    d = review.edit(d, "collaboration", 0, "Tell me about a disagreement you lost?")
    assert d.edited_from["Tell me about a disagreement you lost?"] == was


def test_editing_twice_still_points_at_the_original():
    d = draft()
    was = d.questions("collaboration")[0]
    d = review.edit(d, "collaboration", 0, "First rewrite?")
    d = review.edit(d, "collaboration", 0, "Second rewrite?")
    assert d.edited_from["Second rewrite?"] == was
    assert "First rewrite?" not in d.edited_from


def test_a_duplicate_question_is_refused():
    d = draft()
    existing = d.questions("behavioural_core")[0]
    with pytest.raises(ValueError, match="already asks that"):
        review.add(d, "collaboration", existing)
    with pytest.raises(ValueError, match="already asks that"):
        review.edit(d, "collaboration", 0, existing)


def test_an_empty_or_unpunctuated_question_is_refused():
    d = draft()
    with pytest.raises(ValueError, match="cannot be empty"):
        review.edit(d, "collaboration", 0, "   ")
    with pytest.raises(ValueError, match="end with"):
        review.edit(d, "collaboration", 0, "Tell me about a disagreement")


def test_reordering_changes_the_order_and_nothing_else():
    d = draft()
    before = list(d.questions("behavioural_core"))
    d = review.move(d, "behavioural_core", 0, 2)
    after = list(d.questions("behavioural_core"))
    assert after != before
    assert sorted(after) == sorted(before)


def test_saving_writes_the_bank_only_when_asked(tmp_path):
    d = draft()
    plan_out, bank_out = tmp_path / "p.json", tmp_path / "b.json"
    review.save(d, plan_out)
    assert plan_out.exists() and not bank_out.exists()
    review.save(d, plan_out, bank_out)
    assert bank.load(bank_out).questions


def test_a_saved_plan_records_that_it_was_edited(tmp_path):
    d = review.edit(draft(), "collaboration", 0, "Tell me about a disagreement you lost?")
    out = tmp_path / "p.json"
    review.save(d, out)
    assert "edited" in json.loads(out.read_text(encoding="utf-8"))["notes"]


def test_the_gaps_survive_into_the_draft():
    """The most useful thing at review: what the description asked for and the plan misses."""
    d = draft("system_design", "system_design")
    assert "system_design" in d.gaps


def test_no_temp_file_is_left_behind(tmp_path):
    d = draft()
    review.save(d, tmp_path / "p.json")
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(ROOT.glob(".plan-check.tmp.json"))
