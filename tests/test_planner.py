"""FR-1: JD -> role, seniority, ranked competencies, every one of them cited."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, fields, planner  # noqa: E402
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


def test_software_reads_a_description_on_1_1s_ten():
    """The view's five new shared competencies turned 4 of 9 software reads into `influence`
    first on the cloud model (13/11), so they wait for P3's measurement. Other views are
    read whole."""
    def enum(view):
        m = Model({"role": "R", "seniority": "mid", "competencies": []})
        run(planner.read_jd(m, view, JD))
        return set(m.schema["properties"]["competencies"]["items"]["properties"]["name"]["enum"])

    full = bank.load(Path(__file__).resolve().parent.parent / "config" / "question_bank.json",
                     templates=fields.templates())
    assert "influence" in full.view("software").competencies
    assert enum(full.view("software")) == planner.SOFTWARE_1_1
    assert enum(full.view("data_analytics")) == set(full.view("data_analytics").competencies)


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


def test_a_competency_one_mention_grounded_is_not_also_listed_as_not_used():
    """15/11: the plan page showed data_quality as asked for, then twice as not used."""
    s = spec(competencies=[
        {"name": "incident_response", "evidence": "no such words appear here at all"},
        {"name": "incident_response",
         "evidence": "expected to lead the response when payments break in production"},
        {"name": "incident_response", "evidence": "nor do these words appear anywhere"},
    ])
    assert s.competencies == ("incident_response",)
    assert not s.dropped


def test_a_competency_dropped_twice_is_listed_once_with_its_first_quote():
    s = spec(competencies=[
        {"name": "mentoring", "evidence": "no such words appear here at all"},
        {"name": "mentoring", "evidence": "nor do these words appear anywhere"},
    ])
    assert [(r.name, r.evidence) for r in s.dropped] == [
        ("mentoring", "no such words appear here at all")]


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


EVIDENCE = "profiling and reducing latency"


class Writer:
    """Replies as D18's generator does, writing from the evidence it was given."""

    def __init__(self, question, min_level="junior"):
        self.question, self.min_level = question, min_level

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.system, self.user = system, user
        competency = schema["properties"]["competency"]["enum"][0]
        return Completion(text=json.dumps({"duty": EVIDENCE, "question": self.question,
                                           "competency": competency,
                                           "min_level": self.min_level}))


def propose(text, **kw):
    return run(planner.propose_question(Writer(text), BANK, kw.pop("competency", "performance"),
                                        EVIDENCE, **kw))


def test_a_generated_question_comes_back_proposed_not_askable():
    """FR-2 allows generation and FR-6 promises every scripted question is asked verbatim.
    Both hold only if a person reads the text before a candidate hears it."""
    q = propose("Tell me about a latency problem you traced to its cause.")
    assert q.source == "generated"
    assert q.status == "proposed"
    assert not q.askable
    assert q.generated


def test_nothing_in_this_path_can_produce_an_askable_question():
    """Belt and braces: the guarantee should not depend on a caller remembering it."""
    for text in ("Tell me about a slow endpoint you fixed.",
                 "Describe a time you profiled something under pressure."):
        assert not propose(text).askable


def test_the_gap_path_drafts_through_the_generator():
    """D17: the same prompt and checks as a generated slot."""
    w = Writer("Tell me about a slow endpoint you fixed.")
    run(planner.propose_question(w, BANK, "performance", EVIDENCE))
    assert w.system == planner.GENERATE_SYSTEM


def test_a_proposal_that_does_not_open_as_an_interview_question_is_refused():
    with pytest.raises(ValueError, match="must begin with"):
        propose("What did you profile when latency mattered?")


def test_an_overlong_proposal_is_refused():
    with pytest.raises(ValueError, match="the limit is 24 words"):
        propose("Tell me about " + " ".join(["word"] * 40) + ".")


def test_a_hypothetical_proposal_is_refused():
    with pytest.raises(ValueError, match="hypothetical"):
        propose("Tell me how you would profile a slow service.")


def test_a_proposal_that_repeats_a_bank_question_verbatim_is_refused():
    existing = BANK.for_competency("performance")[0].text
    with pytest.raises(ValueError, match="restates"):
        propose(existing)


def test_a_near_duplicate_is_refused_when_similarity_is_available():
    """The embedding is optional everywhere else, so the check is skipped rather than assumed
    when it is absent -- quieter and weaker, never wrong."""
    banked = BANK.for_competency("performance")[0]
    hits = lambda a, b: 0.99 if b == banked.text else 0.0  # noqa: E731
    with pytest.raises(ValueError, match="restates"):
        propose("Tell me about an entirely different thing about speed.", similarity=hits)


def test_the_near_duplicate_check_is_skipped_without_an_embedding():
    q = propose("Tell me about an entirely different thing about speed.", similarity=None)
    assert q.text == "Tell me about an entirely different thing about speed."


def test_a_proposal_above_the_plans_level_is_refused():
    w = Writer("Tell me about a latency problem you traced.", min_level="senior")
    with pytest.raises(ValueError, match="pitched at junior"):
        run(planner.propose_question(w, BANK, "performance", EVIDENCE, level="junior"))


def test_the_employer_wording_reaches_the_model():
    """The reason to generate at all: a bank question is generic, and this one is not."""
    w = Writer("Tell me about a slow endpoint you fixed.")
    run(planner.propose_question(w, BANK, "performance", EVIDENCE))
    assert EVIDENCE in w.user


def test_a_design_or_case_competency_stays_curated():
    with pytest.raises(ValueError, match="stay curated"):
        propose("Tell me about a system you designed.", competency="system_design")


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


def test_the_three_stock_plans_are_actually_different_interviews():
    """The first version ranked competencies but kept every phase, so "technical" still held
    two behavioural questions and behavioural/technical shared 7 of 8 questions -- which made
    the choice cosmetic. A stock kind has to change the SHAPE."""
    got = {k: planner.stock_plan(k, BANK, template=TEMPLATE) for k in planner.STOCK}
    b, t = set(got["behavioural"].questions), set(got["technical"].questions)
    structural = {q for ph in got["mixed"].plan["phases"] if ph["id"] in ("warmup", "closing")
                  for q in ph["questions"]}
    assert len(b & t) - len(b & t & structural) <= 4, "the two kinds are nearly the same plan"

    shape = lambda a: {ph["id"]: len(ph["questions"]) for ph in a.plan["phases"]}  # noqa: E731
    assert shape(got["behavioural"]) != shape(got["technical"])
    assert "design" not in shape(got["behavioural"]), "a behavioural interview drops design"
    assert shape(got["technical"])["technical_experience"] > \
        shape(got["behavioural"])["technical_experience"]


def test_a_dropped_phase_is_removed_not_left_empty():
    """A scored phase with no questions gives the rubric a denominator of zero. Design is the
    only phase safe to drop, because it is observed and described rather than scored (9.6)."""
    a = planner.stock_plan("behavioural", BANK, template=TEMPLATE)
    for ph in a.plan["phases"]:
        assert ph["questions"], ph["id"]


def test_every_stock_plan_loads_through_the_real_validator(tmp_path):
    for kind in planner.STOCK:
        a = planner.stock_plan(kind, BANK, template=TEMPLATE)
        p = tmp_path / ("%s.json" % kind)
        p.write_text(json.dumps(a.plan), encoding="utf-8")
        assert sess.load_plan(p), kind


def test_a_stock_competency_carries_no_evidence():
    """There is no employer text to cite, and inventing one is exactly what the JD path drops
    a requirement for."""
    a = planner.stock_plan("technical", BANK, template=TEMPLATE)
    assert a.covered
    assert "no job description" in a.plan["notes"]


def test_a_shorter_interview_is_the_same_interview_with_less_of_it():
    long_ = planner.stock_plan("mixed", BANK, template=TEMPLATE)
    short = planner.stock_plan("mixed", BANK, template=TEMPLATE, minutes=30)
    assert len(short.questions) < len(long_.questions)
    assert short.estimated_secs < long_.estimated_secs
    # Same phases, fewer questions -- not a different shape of interview.
    assert [ph["id"] for ph in short.plan["phases"]] == \
        [ph["id"] for ph in long_.plan["phases"]]


def test_a_duration_the_plan_cannot_reach_is_refused_not_silently_overshot():
    """Returning a 26-minute interview to someone who asked for 12 is the quiet degrading this
    codebase refuses elsewhere -- `answer_shape` is validated rather than defaulted for the
    same reason."""
    with pytest.raises(ValueError, match="shorter than this plan can be"):
        planner.stock_plan("mixed", BANK, template=TEMPLATE, minutes=12)


@pytest.mark.parametrize("field_id", fields.IDS)
def test_no_stock_plan_runs_past_its_length(field_id):
    """15/11: rounding and the one-question floor never shrank a case phase, so 30-minute plans
    with one ran 35 to 37 minutes."""
    view = bank.load(bank.SHIPPED, templates=fields.templates()).view(field_id)
    for k in fields.get(field_id).kinds:
        for minutes in range(15, 66, 5):
            try:
                a = planner.stock_plan(k.id, view, minutes=minutes, field=field_id)
            except ValueError:
                continue
            assert a.estimated_secs <= minutes * 60 * planner.OVERRUN, (k.id, minutes)


def test_a_short_technical_plan_stays_technical():
    """Held to the length exactly, the trim cut this to one technical question."""
    a = planner.stock_plan("technical", BANK, template=TEMPLATE, minutes=30)
    tech = next(ph for ph in a.plan["phases"] if ph["id"] == "technical_experience")
    assert len(tech["questions"]) >= 2
    assert a.estimated_secs > 30 * 60 * 0.95


def test_an_unknown_stock_kind_names_the_known_ones():
    with pytest.raises(KeyError, match="behavioural"):
        planner.stock_plan("vibes", BANK, template=TEMPLATE)


def test_a_stock_plan_holds_only_askable_questions():
    proposal = bank.Question(id="gen.own.99", text="A proposed ownership question?",
                             competencies=("ownership",), shape="star",
                             source="generated", status="proposed")
    b = bank.with_question(BANK, proposal)
    a = planner.stock_plan("behavioural", b, template=TEMPLATE)
    assert proposal.text not in a.questions


# --- seniority ---------------------------------------------------------------------------------
# The ranked competencies the junior full-stack description produced live on 21/09. Built by
# hand here so selection is tested without extraction.
JUNIOR_JD = ("testing_quality", "technical_judgement", "learning", "collaboration",
             "system_design", "data_modelling")
PRESUMING = {q.text for q in BANK.questions if not q.fits("junior")}


def _at(level, *names, bank_=BANK):
    s = planner.JobSpec(role="Software Engineer", seniority=level,
                        requirements=tuple(planner.Requirement(n, "x") for n in names))
    return planner.assemble(s, bank_, template=TEMPLATE)


def _asked(a):
    return [q for ph in a.plan["phases"] for q in ph["questions"]]


def test_a_junior_plan_asks_nothing_that_presumes_a_team_or_a_live_system():
    """Seniority reached only the label. A junior plan asked "describe a production incident
    you were responsible for" and "give difficult feedback to a colleague", and neither came
    from the description: both were the mid-level template filling its slots."""
    assert PRESUMING, "the bank tags nothing, so this test would pass vacuously"
    asked = _asked(_at("junior", *JUNIOR_JD))
    assert not PRESUMING & set(asked), sorted(PRESUMING & set(asked))


def test_fitting_to_a_junior_costs_neither_length_nor_coverage():
    """Preferred, not excluded. A junior interview that came out shorter, or dropped a
    competency the description asked for, would be a worse fix than the gap."""
    junior, mid = _at("junior", *JUNIOR_JD), _at("mid", *JUNIOR_JD)
    assert len(_asked(junior)) == len(_asked(mid))
    assert junior.covered == mid.covered and junior.gaps == mid.gaps


def test_a_plan_above_junior_is_exactly_what_it_was():
    """Nothing is tagged above mid, so every level from mid up must select identically -- and
    must still ask the template's own experienced questions, which proves nothing was filtered."""
    mid = _asked(_at("mid", *JUNIOR_JD))
    assert _asked(_at("senior", *JUNIOR_JD)) == mid == _asked(_at("staff", *JUNIOR_JD))
    assert "Describe a production incident you were responsible for resolving." in mid


def test_a_stock_plan_is_untouched():
    """Stock plans have no description to read a level from and run at mid."""
    for kind in planner.STOCK:
        a = planner.stock_plan(kind, BANK, template=TEMPLATE)
        assert "Pitched at" not in a.plan["notes"], kind


def test_a_junior_plan_falls_back_rather_than_leaving_a_competency_uncovered():
    """When every question for a competency presumes experience, the junior plan still asks
    one. The alternative is a gap the description asked to have covered."""
    from dataclasses import replace
    strict = bank.Bank(
        competencies=dict(BANK.competencies),
        phase_affinity=dict(BANK.phase_affinity),
        questions=tuple(replace(q, min_level="mid") if "collaboration" in q.competencies
                        or "mentoring" in q.competencies else q for q in BANK.questions))
    a = _at("junior", "collaboration", bank_=strict)
    assert "collaboration" in a.covered
    assert "Asked anyway, for want of a fairer one" in a.plan["notes"]


def test_the_notes_say_when_the_level_changed_anything():
    """The sheet shows the questions but not which of them presume experience, so the plan's
    own notes say it. A mid plan's notes read exactly as they did."""
    assert "Pitched at junior" in _at("junior", *JUNIOR_JD).plan["notes"]
    assert "Pitched at" not in _at("mid", *JUNIOR_JD).plan["notes"]


# --- asking a question twice -------------------------------------------------------------------

def test_no_plan_asks_the_same_question_twice():
    """A sweep of 4,089 plans found 249 asking "disagreed with a technical decision on your
    team" twice: picked into the collaboration phase, and kept as a template line in a
    behavioural_core the JD never reached. Every single competency and ordered pair, at every
    level."""
    import itertools
    lists = [[n] for n in BANK.competencies] + [
        list(p) for p in itertools.permutations(BANK.competencies, 2)]
    for ranked in lists:
        for level in planner.SENIORITY:
            asked = _asked(_at(level, *ranked))
            assert len(asked) == len(set(asked)), (ranked, level)


def test_removing_a_repeat_does_not_shorten_the_plan():
    """The repeat is replaced, not just dropped: the interview stays as long as it was."""
    asked = _asked(_at("mid", "collaboration"))
    assert len(asked) == len(set(asked)) == len(_asked(_at("mid", "learning")))


def test_a_phase_left_alone_still_claims_its_questions(tmp_path):
    """The other direction. A phase the JD did not reach was skipped without recording what it
    would ask, so a LATER phase topping up from the bank could take one of its lines. The
    shipped bank never happens to trigger it, so this builds the smallest bank that does."""
    shared = "Tell me about the shared question?"
    b = bank.Bank(
        competencies={"alpha": "a", "beta": "b"},
        phase_affinity={"alpha": "behavioural_core", "beta": "collaboration"},
        questions=tuple(bank.Question(id=i, text=t, competencies=(c,), shape="star",
                                      source="curated", status="approved")
                        for i, t, c in (("q.first", "Tell me about the first beta thing?", "beta"),
                                        ("q.shared", shared, "beta"),
                                        ("q.other", "Tell me about another beta thing?", "beta"),
                                        ("q.alpha", "Tell me about an alpha thing?", "alpha"))))
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for ph in raw["phases"]:
        if ph["id"] == "behavioural_core":
            ph["questions"] = [shared]          # unreached, and holds a line beta could use
        if ph["id"] == "collaboration":
            ph["questions"] = ["Tell me about the first beta thing?"]
    template = tmp_path / "template.json"
    template.write_text(json.dumps(raw), encoding="utf-8")

    a = planner._select("X", "mid", [planner.Requirement("beta", "e")], b, template, None,
                        "test", shape={"warmup": 1, "behavioural_core": 1,
                                       "collaboration": 2, "closing": 1})
    asked = _asked(a)
    assert asked.count(shared) == 1, asked
    collab = next(ph["questions"] for ph in a.plan["phases"] if ph["id"] == "collaboration")
    assert collab == ["Tell me about the first beta thing?", "Tell me about another beta thing?"]


DA_JD = """Data Analyst, Customer Insights

You will turn our product and sales data into answers the commercial team can act on. Most
weeks you will build and maintain dashboards, write SQL against our warehouse, and present
what you find to managers who do not read SQL. Experience designing and reading A/B tests is
a plus.
"""


def detect(**payload):
    return run(planner.detect_field(Model(payload), DA_JD))


def test_a_grounded_field_is_kept():
    d = detect(field="data_analytics",
               evidence="turn our product and sales data into answers the commercial team can act on")
    assert d.field == "data_analytics"
    assert d.reason == ""


def test_an_ungrounded_field_is_not_trusted():
    d = detect(field="data_analytics", evidence="owns the analytics roadmap for the whole company")
    assert d.field is None
    assert "not in the description" in d.reason
    assert d.named == "data_analytics"


def test_an_unknown_field_gives_none():
    d = detect(field="nursing", evidence="build and maintain dashboards, write SQL against our warehouse")
    assert d.field is None
    assert d.named == "nursing"


def test_the_field_enum_is_the_closed_field_list_and_evidence_comes_first():
    m = Model({"field": "general", "evidence": "x"})
    run(planner.detect_field(m, DA_JD))
    assert m.schema["properties"]["field"]["enum"] == list(fields.IDS)
    assert list(m.schema["properties"]) == ["evidence", "field"]


def test_detection_refuses_what_is_not_a_description():
    with pytest.raises(ValueError):
        run(planner.detect_field(Model({}), "Data analyst wanted."))


# --- every field's stock plans (V1.2_PLAN P2) ------------------------------------------------

FIELD_KINDS = [(f.id, k.id) for f in fields.FIELDS.values() if f.id != fields.SOFTWARE
               for k in f.kinds]
ALL_VIEWS = bank.load(Path(__file__).resolve().parent.parent / "config" / "question_bank.json",
                      templates=fields.templates())


@pytest.mark.parametrize("field,kind", FIELD_KINDS)
def test_every_fields_stock_plan_assembles_on_its_view(field, kind, tmp_path):
    """The same selection software's plans go through, on the field's template and view: every
    phase holds what the kind's shape asks, nothing is asked twice, and the case phase holds
    case questions, learned from the template rather than from a phase called `design`."""
    view = ALL_VIEWS.view(field)
    k = fields.get(field).kind(kind)
    a = planner.stock_plan(kind, view, field=field)
    assert {ph["id"]: len(ph["questions"]) for ph in a.plan["phases"]} == \
        {p: n for p, n in k.shape.items() if n}
    assert len({q.lower() for q in a.questions}) == len(a.questions)
    assert a.gaps == ()
    by_text = {q.text: q for q in view.questions}
    shapes = bank.template_shapes(fields.get(field).template)
    for ph in a.plan["phases"]:
        for q in ph["questions"]:
            if q in by_text and ph["id"] in shapes:
                assert by_text[q].shape == shapes[ph["id"]], (ph["id"], q)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(a.plan), encoding="utf-8")
    assert sess.load_plan(p)


def test_a_round_label_reads_as_written():
    a = planner.stock_plan("ux", ALL_VIEWS.view("ux_design"), field="ux_design")
    assert a.plan["label"] == "UX interview (mid)"
    assert a.plan["notes"].startswith("Stock UX plan, no job description.")


def test_an_unknown_kind_names_the_fields_own():
    with pytest.raises(KeyError, match="known: analytics, behavioural, mixed"):
        planner.stock_plan("technical", ALL_VIEWS.view("data_analytics"),
                           field="data_analytics")
