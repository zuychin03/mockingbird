"""V1.2_PLAN P3: a plan from a description in any field, its generated slots on the plan page,
variety from History, and the description kept out of the interview itself."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, contract, detour, fields, planner, review  # noqa: E402
from app import session as sess  # noqa: E402
from app.provider import Completion, ProviderError  # noqa: E402
from app.runner import Runner  # noqa: E402

BANK = bank.load(bank.SHIPPED, templates=fields.templates())
VIEW = BANK.view(fields.SOFTWARE)

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
REQUIREMENTS = [
    {"name": "incident_response",
     "evidence": "leading the response when payments break in production"},
    {"name": "data_modelling", "evidence": "experience running migrations on live data matters"},
]
EVIDENCE = "You will own a service end to end and join a shared on-call rotation"


def run(coro):
    return asyncio.run(coro)


def first_duty(user: str) -> str:
    return re.search(r"^1\. (.+)$", user, re.M).group(1)


def good(user, schema):
    n = good.n = getattr(good, "n", 0) + 1
    return {"duty": first_duty(user),
            "question": "Tell me about piece of work number %d that you led recently." % n,
            "competency": schema["properties"]["competency"]["enum"][0], "min_level": "junior"}


def hypothetical(user, schema):
    return {"duty": first_duty(user), "question": "Tell me how you would handle an outage.",
            "competency": schema["properties"]["competency"]["enum"][0], "min_level": "junior"}


class Model:
    """Plays every planning call: detection, the read, the duties and the generator."""

    def __init__(self, write=good, field="software", evidence=EVIDENCE, duties_down=False):
        self.write, self.field, self.evidence = write, field, evidence
        self.duties_down = duties_down
        self.systems: list[str] = []

    async def complete(self, system, user, schema=None, max_tokens=400, **kw):
        self.systems.append(system)
        if system == planner.FIELD_SYSTEM:
            out = {"evidence": self.evidence, "field": self.field}
        elif system == planner.SYSTEM:
            out = {"role": "Backend Engineer", "seniority": "mid", "competencies": REQUIREMENTS}
        elif system == planner.DUTIES_SYSTEM:
            if self.duties_down:
                raise ProviderError("the model server did not answer")
            out = {"items": [{"quote": q, "kind": k} for q, k in DUTIES]}
        elif system == planner.GENERATE_SYSTEM:
            out = self.write(user, schema)
        else:
            raise AssertionError("unexpected prompt")
        return Completion(text=json.dumps(out))


def planned(model=None, **kw) -> planner.Planned:
    return run(planner.plan_description(model or Model(), BANK, JD, **kw))


def _questions(plan: dict) -> list[str]:
    return [q for ph in plan["phases"] for q in ph.get("questions", [])]


# --- planning from a description ---------------------------------------------------------------

def test_a_description_is_planned_in_the_field_detection_reads():
    done = planned()
    plan = done.assembled.plan
    assert done.field == plan["field"] == "software"
    jd = plan["job_description"]
    assert jd["text"] == JD.strip() and jd["field"] == "software"
    assert jd["field_evidence"] == EVIDENCE
    assert [d["quote"] for d in jd["duties"]] == [q for q, _ in DUTIES]
    answered = {d["quote"]: d["answered"] for d in jd["duties"]}
    assert answered["leading the response when payments break in production"]
    assert not answered["review the work of engineers earlier in their careers"]
    assert plan["generated"], "the fake writes a passing question for every slot"
    for row in plan["generated"]:
        phase = next(ph for ph in plan["phases"] if ph["id"] == row["phase"])
        assert row["text"] in phase["questions"]
        assert row["fallback"] not in phase["questions"]
        assert row["prompt_hash"] == planner.PROMPT_HASH and row["kept"] is False
    assert "%d written from the description." % len(plan["generated"]) in plan["notes"]
    assert sess.load_plan  # the plan is a plan: see test_a_generated_plan_loads


def test_a_generated_plan_loads(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(planned().assembled.plan), encoding="utf-8")
    assert sess.load_plan(path)["field"] == "software"


def test_a_reading_detection_cannot_ground_is_planned_as_general():
    done = planned(Model(evidence="a sentence the description never says"))
    assert done.detection.field is None
    assert done.field == done.assembled.plan["field"] == fields.GENERAL
    assert done.assembled.plan["job_description"]["field_evidence"] == ""


def test_the_switch_skips_detection_and_keeps_what_it_read():
    m = Model()
    first = planner.Detection("software", EVIDENCE, named="software")
    done = planned(m, field_id="data_analytics", detection=first)
    assert planner.FIELD_SYSTEM not in m.systems
    assert done.field == done.assembled.plan["field"] == "data_analytics"
    assert done.detection is first
    assert done.assembled.plan["job_description"]["field_evidence"] == ""


def test_without_duties_the_plan_is_the_bank_plan():
    done = planned(Model(duties_down=True))
    spec = done.spec
    bank_only = planner.assemble(spec, VIEW, field="software")
    assert done.assembled.plan["phases"] == bank_only.plan["phases"]
    assert done.assembled.plan["generated"] == []
    assert done.assembled.plan["notes"].endswith(planner.NO_DUTIES)


def test_a_slot_that_falls_back_says_why():
    done = planned(Model(write=hypothetical))
    plan = done.assembled.plan
    assert plan["generated"] == []
    assert "0 written from the description; %d fell back: it asked what you would do" \
        % len(done.generated) in plan["notes"]


# --- D20, variety from History -----------------------------------------------------------------

SPEC = planner.JobSpec(role="Backend Engineer", seniority="mid", requirements=(
    planner.Requirement("incident_response", "leading the response"),))


def _equal_candidates() -> list[str]:
    return [q.text for q in VIEW.for_competency("incident_response")
            if q.shape == "star" and q.fits("mid")]


def test_with_no_history_the_plan_is_byte_identical():
    before = planner.assemble(SPEC, VIEW)
    for recent in (None, {}):
        after = planner.assemble(SPEC, VIEW, recent=recent)
        assert json.dumps(after.plan) == json.dumps(before.plan)
    stock = planner.stock_plan("mixed", VIEW)
    assert json.dumps(planner.stock_plan("mixed", VIEW, recent={}).plan) == json.dumps(stock.plan)


def test_the_least_recently_asked_of_equal_candidates_wins():
    options = _equal_candidates()
    assert len(options) >= 2, "the test needs two equal candidates"
    first = planner.assemble(SPEC, VIEW).picked[VIEW.phase_for("incident_response")][0]
    assert first == options[0]
    recent = {options[0].lower(): "2026-11-14T10:00:00+00:00",
              options[1].lower(): "2026-11-01T10:00:00+00:00"}
    later = {o.lower(): "2026-11-13T10:00:00+00:00" for o in options[2:]}
    got = planner.assemble(SPEC, VIEW, recent={**recent, **later})
    assert got.picked[VIEW.phase_for("incident_response")][0] == options[1]


def test_never_asked_beats_asked_long_ago():
    options = _equal_candidates()
    recent = {options[0].lower(): "2020-01-01T00:00:00+00:00"}
    got = planner.assemble(SPEC, VIEW, recent=recent)
    assert got.picked[VIEW.phase_for("incident_response")][0] == options[1]


def test_history_is_read_from_the_interviews_on_disk(tmp_path):
    for sid, at, q in (("a", "2026-11-01T00:00:00+00:00", "Old question?"),
                       ("b", "2026-11-10T00:00:00+00:00", "Old question?"),
                       ("c", "2026-11-05T00:00:00+00:00", "Other question?")):
        (tmp_path / sid).mkdir()
        (tmp_path / sid / "session.json").write_text(json.dumps(
            {"started_at": at, "questions": [{"question": q}]}), encoding="utf-8")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "session.json").write_text("{", encoding="utf-8")
    assert sess.recently_asked(tmp_path) == {"old question?": "2026-11-10T00:00:00+00:00",
                                             "other question?": "2026-11-05T00:00:00+00:00"}


# --- the draft: generated slots and their three actions (D17) ----------------------------------

def _draft() -> review.Draft:
    done = planned()
    d = done.detection
    return review.from_assembled(done.assembled, VIEW, done.spec,
                                 {"field": d.field, "evidence": d.evidence, "reason": d.reason})


def test_use_a_bank_question_puts_the_fallback_back():
    d = _draft()
    row = d.plan["generated"][0]
    after = review.use_bank(d, 0)
    phase = next(ph for ph in after.plan["phases"] if ph["id"] == row["phase"])
    assert row["fallback"] in phase["questions"] and row["text"] not in phase["questions"]
    assert len(after.plan["generated"]) == len(d.plan["generated"]) - 1


def test_replace_keeps_the_old_text_when_the_new_one_fails():
    d = _draft()
    row = d.plan["generated"][0]
    failed = run(planner.regenerate(Model(write=hypothetical), VIEW, d.plan, row))
    with pytest.raises(ValueError, match="keeps its question"):
        review.replace_generated(d, 0, failed, "m")
    assert d.plan["generated"][0] == row


def test_replace_writes_another_question_for_the_same_duty():
    d = _draft()
    row = d.plan["generated"][0]
    g = run(planner.regenerate(Model(), VIEW, d.plan, row))
    after = review.replace_generated(d, 0, g, "m")
    new = after.plan["generated"][0]
    assert new["text"] != row["text"] and new["duty"] == row["duty"]
    assert new["fallback"] == row["fallback"] and new["competency"] == row["competency"]
    assert new["text"] in _questions(after.plan) and row["text"] not in _questions(after.plan)


def test_keep_is_idempotent_and_writes_only_the_local_bank(tmp_path):
    shipped = hashlib.sha256(bank.SHIPPED.read_bytes()).hexdigest()
    local = tmp_path / "bank_local.json"
    d = _draft()
    row = d.plan["generated"][0]
    once = review.keep_generated(d, 0, local)
    twice = review.keep_generated(once, 0, local)
    assert twice.plan["generated"][0]["kept"]
    rows = json.loads(local.read_text(encoding="utf-8"))["questions"]
    assert len(rows) == 1
    assert rows[0]["text"] == row["text"] and rows[0]["duty"] == row["duty"]
    assert rows[0]["status"] == "approved" and rows[0]["source"] == "generated"
    assert hashlib.sha256(bank.SHIPPED.read_bytes()).hexdigest() == shipped
    loaded = bank.load(bank.SHIPPED, local=local)
    assert any(q.text == row["text"] and q.askable and q.duty == row["duty"]
               for q in loaded.questions)


def test_a_slot_changed_by_hand_is_no_longer_generated():
    d = _draft()
    row = d.plan["generated"][0]
    phase = next(ph for ph in d.plan["phases"] if ph["id"] == row["phase"])
    i = phase["questions"].index(row["text"])
    edited = review.edit(d, row["phase"], i, "Tell me about a schema you designed by hand.")
    assert row["text"] not in [r["text"] for r in edited.plan["generated"]]
    deleted = review.delete(d, row["phase"], i)
    assert row["text"] not in [r["text"] for r in deleted.plan["generated"]]


def test_a_draft_keeps_its_description_detection_and_slots(tmp_path):
    d = _draft()
    path = tmp_path / "draft.json"
    review.write_draft(d, path)
    back = review.read_draft(path, lambda f: BANK.view(f))
    assert back.plan["job_description"] == d.plan["job_description"]
    assert back.plan["generated"] == d.plan["generated"]
    assert back.detected == d.detected and back.bank.view_of == "software"


def test_a_draft_from_before_1_2_is_software(tmp_path):
    raw = review.to_json(review.from_assembled(planner.stock_plan("mixed", VIEW), VIEW))
    raw["plan"].pop("field")
    raw.pop("detected")
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    seen = []
    d = review.read_draft(path, lambda f: seen.append(f) or BANK.view(f))
    assert seen == ["software"] and d.detected is None and "generated" not in d.plan
    assert review.editable(d.plan) == ("behavioural_core", "technical_experience", "design",
                                       "collaboration")


def test_editable_phases_follow_the_field():
    plan = planner.stock_plan("analytics", BANK.view("data_analytics"),
                              field="data_analytics").plan
    assert set(review.editable(plan)) == {"behavioural_core", "analytics_experience",
                                          "analytics_case", "collaboration"} & \
        {ph["id"] for ph in plan["phases"]}


def test_a_stock_plan_names_its_field_and_no_gaps():
    a = planner.stock_plan("technical", VIEW)
    assert a.plan["field"] == "software"
    assert "Not covered" not in a.plan["notes"] and "Covered" not in a.plan["notes"]


# --- the interview never sees the description ---------------------------------------------------

class Turns:
    def __init__(self):
        self.calls: list[str] = []

    async def complete(self, system, user, schema=None, max_tokens=400, **kw):
        self.calls.append(system + "\n" + user)
        if schema is None:
            return Completion(text="Covered one question so far.")
        if schema == contract.SPEECH_SCHEMA:
            return Completion(text=json.dumps({"say": ""}))
        return Completion(text=json.dumps({"act": "advance", "say": "Thanks.", "ok": True,
                                           "ask": ""}))


def test_the_description_never_reaches_the_interview(tmp_path, monkeypatch):
    """Only the plan's questions are spoken: the description, its offers and its duties stay
    on the plan page."""
    plan = planned().assembled.plan
    private = ["learning budget", "tables written to continuously", "Backend Engineer, Payments"]
    text = " ".join(p.text for p in detour.corpus(plan))
    assert not any(s.lower() in text.lower() for s in private)

    monkeypatch.setattr(sess, "SESSIONS", tmp_path / "sessions")
    p = Turns()
    r = Runner(p, plan, sess.new_session(plan))
    run(r.ask())
    for answer in ("I led the migration.", "We shipped it.", "It went well."):
        run(r.submit(answer))
    assert p.calls
    assert not any(s.lower() in c.lower() for c in p.calls for s in private)


def test_the_turn_prompt_is_the_plan_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "SESSIONS", tmp_path / "sessions")
    da = fields.get("data_analytics")
    monkeypatch.setitem(fields.FIELDS, "data_analytics", replace(da, prompt_arm="B"))
    plan = planner.stock_plan("mixed", BANK.view("data_analytics"), field="data_analytics").plan
    r = Runner(Turns(), plan, sess.new_session(plan))
    assert r.system == contract.system_for("data_analytics", "B") != contract.SYSTEM
    assert r.speech_system == contract.speech_for("data_analytics", "B")
    old = dict(plan)
    old.pop("field")
    assert Runner(Turns(), old, sess.new_session(old)).system == contract.SYSTEM


def test_replace_names_the_question_it_replaces_and_samples():
    """At temperature 0 the same prompt wrote the slot's question again (14/11)."""
    d = _draft()
    row = d.plan["generated"][0]
    seen = []

    class Recording(Model):
        async def complete(self, system, user, schema=None, max_tokens=400, **kw):
            seen.append((user, kw.get("temperature", 0.0)))
            return await super().complete(system, user, schema, max_tokens, **kw)

    run(planner.regenerate(Recording(), VIEW, d.plan, row))
    user, temperature = seen[0]
    assert "THE QUESTION BEING REPLACED: %s" % row["text"] in user
    assert temperature == planner.REPLACE_TEMPERATURE > 0
    first = []

    class First(Model):
        async def complete(self, system, user, schema=None, max_tokens=400, **kw):
            if system == planner.GENERATE_SYSTEM:
                first.append(kw.get("temperature", 0.0))
            return await super().complete(system, user, schema, max_tokens, **kw)

    planned(First())
    assert first and set(first) == {0.0}
