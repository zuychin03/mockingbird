"""FR-1: JD -> role, seniority, ranked competencies, every one of them cited."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, planner  # noqa: E402
from app import session as sess  # noqa: E402
from app.provider import Completion  # noqa: E402

BANK = bank.load(Path(__file__).resolve().parent.parent / "config" / "question_bank.json")

JD = """Senior Backend Engineer, Payments

We run the ledger behind every transaction on the platform, and we are looking for an
engineer to own a service end to end. You will be on a shared on-call rotation and are
expected to lead the response when payments break in production. Much of the work is
schema and data-model change against tables that are written to continuously, so
experience running migrations on live data matters more to us than breadth. You will be
asked to justify technical decisions to people who will push back on them, and to review
the work of engineers earlier in their careers.

Nice to have: experience profiling and reducing latency in a high throughput system.
"""


class Model:
    """Returns whatever the test wants, so grounding is exercised in isolation."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.schema = None

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.calls += 1
        self.schema = schema
        return Completion(text=json.dumps(self.payload))


def run(coro):
    return asyncio.run(coro)


def spec(**payload):
    base = {"role": "Senior Backend Engineer", "seniority": "senior", "competencies": []}
    base.update(payload)
    return run(planner.read_jd(Model(base), BANK, JD))


def test_role_and_seniority_come_back():
    s = spec()
    assert s.role == "Senior Backend Engineer"
    assert s.seniority == "senior"


def test_the_competency_enum_is_built_from_the_bank():
    """The strongest form of the closed vocabulary: an unknown name is unrepresentable in the
    contract rather than rejected after the fact."""
    m = Model({"role": "R", "seniority": "mid", "competencies": []})
    run(planner.read_jd(m, BANK, JD))
    enum = m.schema["properties"]["competencies"]["items"]["properties"]["name"]["enum"]
    assert set(enum) == set(BANK.competencies)
    assert "communication" not in enum


def test_a_cited_competency_is_kept_and_ranking_is_the_order_given():
    s = spec(competencies=[
        {"name": "data_modelling",
         "evidence": "schema and data-model change against tables that are written to continuously"},
        {"name": "incident_response",
         "evidence": "expected to lead the response when payments break in production"},
    ])
    assert s.competencies == ("data_modelling", "incident_response")
    assert not s.dropped


def test_an_uncited_competency_is_dropped():
    """The phantom quote of 9.9 in a worse place. A phantom in the report misleads one reader;
    a phantom here silently shapes every question that follows."""
    s = spec(competencies=[
        {"name": "incident_response",
         "evidence": "expected to lead the response when payments break in production"},
        {"name": "mentoring",
         "evidence": "you will run a team of eight and own the hiring plan for the year"},
    ])
    assert s.competencies == ("incident_response",)
    assert [r.name for r in s.dropped] == ["mentoring"]


def test_a_dropped_requirement_keeps_its_text_for_review():
    """Showing what was dropped is the difference between "the JD did not ask for this" and
    "the planner missed it", and only the user can tell those apart."""
    s = spec(competencies=[{"name": "mentoring", "evidence": "no such words appear here at all"}])
    assert s.dropped[0].evidence == "no such words appear here at all"


def test_the_model_tidying_a_quote_does_not_lose_it():
    """8.23: the model quotes across a boundary and tidies as it copies, so grounding is
    coverage rather than an exact match. A real citation has to survive that."""
    s = spec(competencies=[
        {"name": "data_modelling",
         "evidence": "experience running migrations on live data matters more to us"},
    ])
    assert s.competencies == ("data_modelling",)


def test_a_repeated_competency_keeps_its_highest_ranked_mention():
    s = spec(competencies=[
        {"name": "incident_response",
         "evidence": "expected to lead the response when payments break in production"},
        {"name": "incident_response",
         "evidence": "You will be on a shared on-call rotation"},
    ])
    assert s.competencies == ("incident_response",)
    assert "lead the response" in s.requirements[0].evidence


def test_a_name_outside_the_vocabulary_is_dropped_not_trusted():
    """Only reachable if the server ignores the enum, which is exactly when trusting it is
    worst."""
    s = spec(competencies=[{"name": "communication", "evidence": "justify technical decisions"}])
    assert not s.competencies
    assert s.dropped[0].name == "communication"


def test_too_short_to_be_a_job_description_is_refused():
    """FR-4 runs a stock plan without a JD. Silently planning from three words would produce
    an interview with nothing behind it."""
    with pytest.raises(ValueError, match="job description"):
        run(planner.read_jd(Model({}), BANK, "Backend engineer wanted."))


def test_a_careers_page_is_truncated_rather_than_sent_whole():
    long_jd = JD + ("\n\nBenefits: " + "we offer a competitive package. " * 2000)
    m = Model({"role": "R", "seniority": "mid", "competencies": []})
    run(planner.read_jd(m, BANK, long_jd))
    assert len(m.schema) and len(long_jd) > planner.MAX_JD_CHARS
    # The prompt the model saw is the truncated one.
    assert m.calls == 1


def test_every_extracted_competency_has_a_question_in_the_bank():
    """The point of taking the enum from the bank: an extraction the planner cannot act on is
    the silent gap the closed vocabulary exists to prevent."""
    s = spec(competencies=[
        {"name": "incident_response",
         "evidence": "expected to lead the response when payments break in production"},
        {"name": "data_modelling",
         "evidence": "experience running migrations on live data matters more to us"},
    ])
    for name in s.competencies:
        assert BANK.for_competency(name)


class Writer:
    def __init__(self, question):
        self.question = question

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.user = user
        return Completion(text=json.dumps({"question": self.question}))


def propose(text, **kw):
    return run(planner.propose_question(Writer(text), BANK, kw.pop("competency", "performance"),
                                        "profiling and reducing latency", **kw))


def test_a_generated_question_comes_back_proposed_not_askable():
    """FR-2 allows generation and FR-6 promises every scripted question is asked verbatim.
    Both hold only if a person reads the text before a candidate hears it."""
    q = propose("Tell me about a latency problem you traced to its cause?")
    assert q.source == "generated"
    assert q.status == "proposed"
    assert not q.askable
    assert q.generated


def test_nothing_in_this_path_can_produce_an_askable_question():
    """Belt and braces: the guarantee should not depend on a caller remembering it."""
    for text in ("Tell me about a slow endpoint you fixed?",
                 "Describe a time you profiled something in anger?"):
        assert not propose(text).askable


def test_a_proposal_that_is_not_a_question_is_refused():
    with pytest.raises(ValueError, match="not a question"):
        propose("Tell me about a latency problem.")


def test_an_overlong_proposal_is_refused():
    with pytest.raises(ValueError, match="word cap"):
        propose(" ".join(["word"] * 40) + "?")


def test_a_proposal_that_repeats_a_bank_question_verbatim_is_refused():
    existing = BANK.for_competency("performance")[0].text
    with pytest.raises(ValueError, match="verbatim"):
        propose(existing if existing.endswith("?") else existing.rstrip(".") + "?")


def test_a_near_duplicate_is_refused_when_similarity_is_available():
    """The embedding is optional everywhere else, so the check is skipped rather than assumed
    when it is absent -- quieter and weaker, never wrong."""
    banked = BANK.for_competency("performance")[0]
    hits = lambda a, b: 0.99 if b == banked.text else 0.0  # noqa: E731
    with pytest.raises(ValueError, match="restates"):
        propose("An entirely different sentence about speed?", similarity=hits)


def test_the_near_duplicate_check_is_skipped_without_an_embedding():
    q = propose("An entirely different sentence about speed?", similarity=None)
    assert q.text == "An entirely different sentence about speed?"


def test_the_employer_wording_reaches_the_model():
    """The reason to generate at all: a bank question is generic, and this one is not."""
    w = Writer("What did you profile when latency mattered most?")
    run(planner.propose_question(w, BANK, "performance", "reducing p99 latency in the ledger"))
    assert "reducing p99 latency in the ledger" in w.user


def test_an_unknown_competency_cannot_be_proposed_for():
    with pytest.raises(KeyError):
        propose("Anything at all?", competency="communication")


TEMPLATE = Path(__file__).resolve().parent.parent / "config" / "interview_swe_general.json"


def _spec(*names):
    return planner.JobSpec(role="Senior Backend Engineer", seniority="senior",
                           requirements=tuple(planner.Requirement(n, "x") for n in names))


def _assembled(*names):
    return planner.assemble(_spec(*names), BANK, template=TEMPLATE)


def test_a_generated_plan_loads_through_the_real_validator(tmp_path):
    """The only acceptance test that means anything: a plan the runner would refuse is a JSON
    file, not an interview."""
    a = _assembled("data_modelling", "incident_response", "collaboration")
    p = tmp_path / "generated.json"
    p.write_text(json.dumps(a.plan), encoding="utf-8")
    assert sess.load_plan(p)


def test_no_question_is_asked_twice():
    """The bank was seeded from the template, so the same sentence exists in both. Selecting
    it for one phase and back-filling it into another asked it twice."""
    a = _assembled("data_modelling", "incident_response", "collaboration", "performance",
                   "system_design", "mentoring")
    qs = list(a.questions)
    assert len(qs) == len(set(qs)), [q for q in qs if qs.count(q) > 1]


def test_every_phase_keeps_the_template_capacity():
    """A phase can lose a question to another phase and find nothing to replace it with. The
    shortfall is otherwise silent: fewer questions than the reviewed plan it was built from."""
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    want = {ph["id"]: len(ph.get("questions", [])) for ph in template["phases"]}
    a = _assembled("data_modelling", "incident_response", "collaboration", "performance",
                   "system_design", "mentoring")
    for ph in a.plan["phases"]:
        assert len(ph["questions"]) == want[ph["id"]], ph["id"]


def test_assembly_changes_questions_and_nothing_else():
    """Every other field is a measured decision -- the design phase's `scored: false` and the
    paragraph explaining why scoring it inverts the ranking (9.6), each probe budget (9.10),
    each focus ladder. A planner that re-derived those would be re-litigating measurements."""
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    a = _assembled("data_modelling", "collaboration")
    for before, after in zip(template["phases"], a.plan["phases"]):
        assert set(before) == set(after)
        for key in before:
            if key == "questions":
                continue
            assert before[key] == after[key], "%s.%s was rewritten" % (before["id"], key)


def test_the_ranking_decides_who_gets_a_question_first():
    high = _assembled("performance", "data_modelling")
    low = _assembled("data_modelling", "performance")
    tech = lambda a: [ph for ph in a.plan["phases"]  # noqa: E731
                      if ph["id"] == "technical_experience"][0]["questions"][0]
    assert "performance" in tech(high).lower() or "scalability" in tech(high).lower()
    assert tech(high) != tech(low)


def test_a_proposed_question_never_reaches_a_plan():
    """The guarantee, at the last place it could fail. Selection reads askable questions only,
    so approval is the single gate between generated text and a candidate hearing it."""
    proposal = bank.Question(id="gen.perf.99", text="A proposed question about latency?",
                             competencies=("performance",), shape="star",
                             source="generated", status="proposed")
    b = bank.with_question(BANK, proposal)
    a = planner.assemble(_spec("performance"), b, template=TEMPLATE)
    assert proposal.text not in a.questions

    # Approval makes it SELECTABLE, which is not the same as selected: curated questions for
    # the same competency still rank ahead of it, and that ordering is deliberate.
    approved = bank.approve(b, "gen.perf.99")
    assert proposal.text not in {q.text for q in b.for_competency("performance")}
    assert proposal.text in {q.text for q in approved.for_competency("performance")}


def test_a_competency_with_no_usable_question_is_reported_as_a_gap():
    """Recall is imperfect and the bank may not stretch. A user can only fix what they see."""
    a = _assembled("system_design", "system_design")
    assert a.covered.count("system_design") == 1
    assert "system_design" in a.gaps, "the design phase holds one question, not two"


def test_the_notes_record_what_was_and_was_not_covered():
    a = _assembled("system_design", "system_design")
    assert "Covered" in a.plan["notes"] and "Not covered" in a.plan["notes"]


def test_the_duration_estimate_is_reported_as_an_estimate():
    a = _assembled("data_modelling", "collaboration")
    assert 20 * 60 < a.estimated_secs < 120 * 60
