"""V1.2_PLAN D10, D16, D18: duties read from a description, and questions generated from them."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, fields, planner  # noqa: E402
from app.provider import Completion  # noqa: E402

VIEW = bank.load(bank.SHIPPED, templates=fields.templates()).view("software")

JD = """Backend Engineer, Payments

You will own a service end to end and join a shared on-call rotation, leading the response when
payments break in production. Much of the work is schema change against tables written to
continuously, so experience running migrations on live data matters. You will work with product
managers to break features into pieces we can ship, and you will review the work of engineers
earlier in their careers. We offer a learning budget of $1000 a year and flexible hours."""

DUTIES = [
    ("own a service end to end and join a shared on-call rotation", "duty"),
    ("leading the response when payments break in production", "duty"),
    ("experience running migrations on live data matters", "duty"),
    ("work with product managers to break features into pieces we can ship", "duty"),
    ("review the work of engineers earlier in their careers", "duty"),
    ("We offer a learning budget of $1000 a year and flexible hours", "offer"),
]

SPEC = planner.JobSpec(role="Backend Engineer", seniority="mid", requirements=(
    planner.Requirement("incident_response",
                        "leading the response when payments break in production"),
    planner.Requirement("data_modelling", "experience running migrations on live data matters"),
))


def run(coro):
    return asyncio.run(coro)


class Model:
    """Reads duties from a fixed list and writes questions with `write(user, schema)`."""

    def __init__(self, write=None, duties=DUTIES):
        self.write = write or good
        self.duties = duties
        self.calls: list[tuple[str, str]] = []
        self.sent: list[dict] = []

    async def complete(self, system, user, schema=None, max_tokens=400, **kw):
        self.calls.append((system, user))
        if system == planner.GENERATE_SYSTEM:
            self.sent.append({"enum": schema["properties"]["competency"]["enum"],
                              "temperature": kw.get("temperature", 0.0), "user": user})
        if system == planner.DUTIES_SYSTEM:
            return Completion(text=json.dumps(
                {"items": [{"quote": q, "kind": k} for q, k in self.duties]}))
        if system == planner.GENERATE_SYSTEM:
            return Completion(text=json.dumps(self.write(user, schema)))
        raise AssertionError("unexpected prompt")


def first_duty(user: str) -> str:
    return re.search(r"^1\. (.+)$", user, re.M).group(1)


def phase_of(user: str) -> str:
    return re.search(r"^PHASE: (.+)$", user, re.M).group(1)


COUNTER = {"n": 0}


def good(user, schema):
    COUNTER["n"] += 1
    return {"duty": first_duty(user),
            "question": "Tell me about piece of work number %d that you led recently."
                        % COUNTER["n"],
            "competency": schema["properties"]["competency"]["enum"][0], "min_level": "junior"}


def bad(user, schema):
    return {"duty": first_duty(user), "question": "How would you handle an outage?",
            "competency": schema["properties"]["competency"]["enum"][0], "min_level": "junior"}


def _duties():
    return run(planner.read_duties(Model(), JD))


def _fill(model):
    a = planner.assemble(SPEC, VIEW)
    plan, rows = run(planner.fill_generated(model, a, SPEC, _duties(), VIEW,
                                            field_id="software", jd=JD))
    return a, plan, rows


def _changed(a, plan):
    out = {}
    for before, after in zip(a.plan["phases"], plan["phases"]):
        diff = [q for q in after["questions"] if q not in before["questions"]]
        if diff:
            out[after["id"]] = diff
    return out


# --- D16 ---------------------------------------------------------------------------------------

def test_duties_are_kept_only_when_the_description_says_them():
    invented = ("lead a team of twelve platform engineers across three time zones", "duty")
    d = run(planner.read_duties(Model(duties=DUTIES + [invented, DUTIES[0]]), JD))
    assert [x.quote for x in d.items] == [q for q, _ in DUTIES]
    assert [x.quote for x in d.dropped] == [invented[0]]
    assert "learning budget" not in " ".join(x.quote for x in d.duties)


def test_no_more_than_twelve_duties_are_read():
    many = [(DUTIES[0][0], "duty")] + [("x" * i, "duty") for i in range(1, 20)]
    d = run(planner.read_duties(Model(duties=many), JD))
    assert len(d.items) + len(d.dropped) <= planner.MAX_DUTIES


def test_unanswered_duties_come_first():
    order = [d.quote for d in planner.duty_order(_duties(), SPEC, ("incident_response",))]
    assert order[-1] == "leading the response when payments break in production"
    assert order[0] == DUTIES[0][0]


# --- D18 ---------------------------------------------------------------------------------------

def _check(text, *, competency="ownership", min_level="junior", level="mid",
           duty=DUTIES[0][0], existing=()):
    checks = planner.check_generated(text, competency, min_level, duty, level=level, jd=JD,
                                     duties=_duties(), competencies=["ownership"],
                                     existing=list(existing))
    return {c.name for c in checks if not c.ok}


GOOD = "Tell me about a service you owned after it went live, and what you changed."


def test_a_good_question_passes_every_check():
    assert _check(GOOD) == set()


@pytest.mark.parametrize("text,kw,failed", [
    ("How do you approach owning a service end to end?", {}, "opener"),
    ("Tell me about " + "a very " * 12 + "long service.", {}, "shape"),
    ("Tell me about a service. Describe it. Describe more.", {}, "shape"),
    ("Tell me about a service you owned", {}, "shape"),
    ("Tell me about how you would own a service end to end.", {}, "past"),
    ("Describe what you'd do if you were on call for the first time.", {}, "past"),
    (GOOD, {"existing": [GOOD.upper()]}, "distinct"),
    (GOOD, {"competency": "performance"}, "competency"),
    (GOOD, {"min_level": "senior"}, "level"),
    (GOOD, {"duty": "lead a team of twelve platform engineers across time zones"}, "duty"),
    (GOOD, {"duty": "We offer a learning budget of $1000 a year and flexible hours"}, "duty"),
])
def test_each_check_rejects_its_case(text, kw, failed):
    assert failed in _check(text, **kw)


def test_every_star_question_in_the_bank_passes_the_text_checks():
    for q in bank.load(bank.SHIPPED).questions:
        if q.shape == "star":
            assert not _check(q.text, existing=()) & {"opener", "shape", "past"}, q.text


def test_a_near_duplicate_is_caught_by_similarity():
    checks = planner.check_generated(GOOD, "ownership", "junior", DUTIES[0][0], level="mid",
                                     jd=JD, duties=_duties(), competencies=["ownership"],
                                     existing=["Something else entirely."],
                                     similarity=lambda a, b: 0.8)
    assert not next(c for c in checks if c.name == "distinct").ok


# --- D10 ---------------------------------------------------------------------------------------

def test_at_most_one_generated_question_per_scored_phase_and_none_in_design():
    a, plan, rows = _fill(Model())
    changed = _changed(a, plan)
    assert changed and all(len(v) == 1 for v in changed.values())
    assert "design" not in changed and all(g.phase != "design" for g in rows)
    assert {g.phase for g in rows} <= {"behavioural_core", "technical_experience",
                                       "collaboration"}


def test_a_requirements_question_is_never_replaced():
    a, plan, _ = _fill(Model())
    asked = [q for ph in plan["phases"] for q in ph["questions"]]
    assert all(q in asked for qs in a.picked.values() for q in qs)
    assert any(a.picked.values())


def test_the_plan_keeps_its_shape():
    a, plan, _ = _fill(Model())
    assert [(ph["id"], len(ph["questions"])) for ph in plan["phases"]] == \
        [(ph["id"], len(ph["questions"])) for ph in a.plan["phases"]]


def test_every_failure_falls_back_to_exactly_the_bank_only_plan():
    m = Model(write=bad)
    a, plan, rows = _fill(m)
    assert plan == a.plan
    assert rows and not any(g.kept for g in rows)
    for g in rows:
        assert len(g.attempts) == 2
        assert g.fallback in [q for ph in a.plan["phases"] if ph["id"] == g.phase
                              for q in ph["questions"]]
    retries = [u for s, u in m.calls if s == planner.GENERATE_SYSTEM and "IT FAILED" in u]
    assert retries and all("hypothetical" in u for u in retries)


def test_offers_never_feed_a_slot():
    _, _, rows = _fill(Model())
    assert all("learning budget" not in g.duty for g in rows)
    offers_only = [d for d in DUTIES if d[1] == "offer"]
    a = planner.assemble(SPEC, VIEW)
    plan, rows = run(planner.fill_generated(
        Model(duties=offers_only), a, SPEC, run(planner.read_duties(Model(duties=offers_only),
                                                                    JD)),
        VIEW, field_id="software", jd=JD))
    assert rows == () and plan == a.plan


def test_no_duty_is_used_twice():
    _, _, rows = _fill(Model())
    kept = [g.duty for g in rows if g.kept]
    assert len(kept) == len(set(kept)) > 1


def test_collaboration_chooses_its_duty_first():
    m = Model()
    _fill(m)
    first = next(u for s, u in m.calls if s == planner.GENERATE_SYSTEM)
    assert phase_of(first) == planner.PHASE_BRIEF["collaboration"]


def test_a_failed_slot_leaves_its_duty_for_another_phase():
    def collab_fails(user, schema):
        if phase_of(user) == planner.PHASE_BRIEF["collaboration"]:
            return bad(user, schema)
        return good(user, schema)

    _, _, rows = _fill(Model(write=collab_fails))
    collab = next(g for g in rows if g.phase == "collaboration")
    assert not collab.kept
    assert collab.duty in [g.duty for g in rows if g.kept]


def test_a_stock_plan_has_no_generated_slots_to_fill():
    """Stock plans never call fill_generated; their picked phases hold nothing to protect."""
    a = planner.stock_plan("mixed", VIEW)
    assert set(a.picked) <= set(bank.template_shapes(fields.get("software").template))


# --- D21 ---------------------------------------------------------------------------------------

def _phase_competencies(phase):
    return sorted(c for c, p in VIEW.phase_affinity.items() if p == phase)


def test_a_slot_offers_unused_competencies_at_temperature_zero():
    m = Model()
    a, _, rows = _fill(m)
    by_text = {q.text: q for q in VIEW.questions}
    assert rows and all(g.kept for g in rows)
    for g in rows:
        assert g.competency in g.allowed
        own = [c for c in by_text[g.fallback].competencies
               if VIEW.phase_affinity.get(c) == g.phase]
        others = {c for ph in a.plan["phases"] for q in ph["questions"]
                  if q != g.fallback and q in by_text for c in by_text[q].competencies}
        if own and own[0] not in others:
            assert g.allowed[0] == own[0]
    assert all(len(g.allowed) > 1 for g in rows if g.phase == "behavioural_core")
    assert all(s["temperature"] == 0.0 for s in m.sent)
    assert all("the plan does not ask about yet" in s["user"] for s in m.sent)


def test_a_generated_competency_is_not_offered_again():
    _, _, rows = _fill(Model())
    done = sorted(rows, key=lambda g: planner.FILL_ORDER.get(g.phase, 1))
    for i, later in enumerate(done):
        for earlier in done[:i]:
            assert earlier.competency not in later.allowed


def test_a_slot_with_nothing_to_offer_keeps_its_bank_question_unasked(monkeypatch):
    monkeypatch.setattr(planner, "open_competencies", lambda *a: ())
    m = Model()
    a, plan, rows = _fill(m)
    assert rows == () and plan == a.plan
    assert not any(s == planner.GENERATE_SYSTEM for s, _ in m.calls)


def test_a_competency_the_slot_was_not_offered_is_refused():
    checks = planner.check_generated(GOOD, "ownership", "junior", DUTIES[0][0], level="mid",
                                     jd=JD, duties=_duties(), competencies=["ownership"],
                                     existing=[], allowed=("learning",))
    c = next(c for c in checks if c.name == "competency")
    assert not c.ok and "this slot may use: learning" in c.reason

    def wrong(user, schema):
        out = good(user, schema)
        out["competency"] = "not_this_slots"
        return out

    m = Model(write=wrong)
    a, plan, rows = _fill(m)
    assert plan == a.plan and not any(g.kept for g in rows)
    assert all("this slot may use" in u for s, u in m.calls if "IT FAILED" in u)


B = _phase_competencies("behavioural_core")
C = _phase_competencies("collaboration")


def _open(known, replaced="Q1", phase="behavioural_core"):
    plan = {"phases": [{"id": phase, "questions": list(known)}]}
    return planner.open_competencies(VIEW, plan, phase, replaced, known)


def test_the_slots_own_competency_comes_first_and_taken_ones_go():
    got = _open({"Q1": (B[1],), "Q2": (B[0],)})
    assert got[0] == B[1]
    assert B[0] not in got
    assert set(got) == set(B) - {B[0]}


def test_a_behavioural_slot_left_with_one_option_is_not_filled():
    assert _open({"Q1": (B[1],), "Q2": tuple(c for c in B if c != B[1])}) == ()
    assert _open({"Q1": (B[1],), "Q2": tuple(B)}) == ()


def test_a_round_slot_left_with_one_option_keeps_it():
    tech = "technical_experience"
    T = _phase_competencies(tech)
    assert _open({"Q1": (T[0],), "Q2": tuple(T[1:])}, phase=tech) == (T[0],)
    assert _open({"Q1": (T[0],), "Q2": tuple(T)}, phase=tech) == (T[0],)


def test_a_two_competency_question_offers_its_phases_share_first():
    got = _open({"Q1": (C[0], B[2])})
    assert got[0] == B[2] and C[0] not in got


def test_a_question_with_no_competency_in_the_phase_offers_its_own():
    got = _open({"Q1": (C[0],)})
    assert got[0] == C[0] and set(got[1:]) == set(B)


def test_a_question_outside_the_view_offers_nothing():
    assert _open({"Q2": (B[0],)}, replaced="unknown") == ()


ALL_VIEWS = bank.load(bank.SHIPPED, templates=fields.templates())
FIELD_KINDS = [(f.id, k.id) for f in fields.FIELDS.values() for k in f.kinds]


@pytest.mark.parametrize("field,kind", FIELD_KINDS)
def test_every_scored_slot_has_a_competency_to_start_from(field, kind):
    """A slot whose question is not in the view is left unfilled; none should be, or a plan
    would quietly lose its generated question."""
    view = ALL_VIEWS.view(field)
    by_text = {q.text: q for q in view.questions}
    a = planner.stock_plan(kind, view, field=field)
    for ph in a.plan["phases"]:
        if not ph.get("scored") or ph.get("observation_shape") == "design":
            continue
        for q in ph["questions"]:
            assert q in by_text and by_text[q].competencies, (field, kind, ph["id"], q)
