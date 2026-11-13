"""The bank and its closed vocabulary. Every check here fires at LOAD, before an interview."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, fields  # noqa: E402
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
    raw["competency_fields"]["deployment"] = "software"
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
    raw["competency_fields"]["deployment"] = "software"
    raw["questions"].append({"id": "gen.deploy.1", "text": "How do you deploy?",
                             "field": "software",
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


# --- seniority -------------------------------------------------------------------------------

def test_a_question_with_no_level_is_fair_at_every_level():
    """Defaulted, unlike `status`: an omitted level reproduces the behaviour before levels
    existed, so omission cannot make a plan worse than it was."""
    q = next(q for q in bank.load(BANK).questions if q.id == "bank.learn.1")
    assert q.min_level == "junior"
    assert all(q.fits(level) for level in bank.LEVELS)


def test_a_question_that_presumes_a_team_is_not_fair_to_a_junior():
    q = next(q for q in bank.load(BANK).questions if q.id == "bank.collab.2")
    assert q.min_level == "mid"
    assert not q.fits("junior")
    assert q.fits("mid") and q.fits("senior") and q.fits("staff")


def test_an_unknown_level_is_refused_at_load(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["questions"][0]["min_level"] = "intern"
    p = tmp_path / "bank.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="min_level"):
        bank.load(p)


def test_a_save_keeps_every_level(tmp_path):
    """`save` wrote its fields by name and `min_level` was not among them, so the first
    approval would have untagged the whole bank -- and `load` treats a missing level as junior,
    so nothing would have said so."""
    b = bank.load(BANK)
    out = tmp_path / "saved.json"
    bank.save(b, out)
    again = bank.load(out)
    assert {q.id: q.min_level for q in again.questions} == {q.id: q.min_level
                                                            for q in b.questions}


def test_a_save_does_not_write_the_default_onto_every_question(tmp_path):
    out = tmp_path / "saved.json"
    bank.save(bank.load(BANK), out)
    rows = json.loads(out.read_text(encoding="utf-8"))["questions"]
    assert all(r.get("min_level") != "junior" for r in rows)


def test_approving_a_question_keeps_its_level():
    """`approve` rebuilt the question field by field, which dropped anything added after it
    was written."""
    b = bank.load(BANK)
    pending = bank.Question(id="gen.test.1", text="Tell me about a team you led?",
                            competencies=("collaboration",), shape="star",
                            source="generated", status="proposed", min_level="senior")
    b = bank.approve(bank.with_question(b, pending), "gen.test.1")
    got = next(q for q in b.questions if q.id == "gen.test.1")
    assert got.askable and got.min_level == "senior"


def test_saving_an_untouched_bank_changes_nothing(tmp_path):
    """The general guard against the whole class. `save` wrote its fields by name and dropped
    `notes`, and would have dropped `min_level` the same way -- each found by accident. A field
    that `load` and `save` do not both carry now fails here instead."""
    out = tmp_path / "saved.json"
    bank.save(bank.load(BANK), out)
    assert out.read_bytes() == BANK.read_bytes()


def test_approving_a_proposal_keeps_the_files_notes(tmp_path):
    """The path that actually rewrites the file. The notes explain every rule the bank encodes,
    and one approval erased them."""
    b = bank.load(BANK)
    pending = bank.Question(id="gen.test.2", text="Tell me about a small thing you fixed?",
                            competencies=("learning",), shape="star",
                            source="generated", status="proposed")
    out = tmp_path / "saved.json"
    bank.save(bank.approve(bank.with_question(b, pending), "gen.test.2"), out)
    assert bank.load(out).notes == b.notes
    assert "min_level" in bank.load(out).notes


# --- format 2: fields, views, the local file (V1.2_PLAN P2) ----------------------------------

TEMPLATE = BANK.parent / "interview_swe_general.json"
SWE_TEN = ("incident_response", "performance", "data_modelling", "system_design",
           "testing_quality", "collaboration", "ownership", "learning", "technical_judgement",
           "mentoring")


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False).encode()).hexdigest()[:12]


# Software questions activation item 4 moved to shared (13/11): their text and tags are 1.1's.
MOVED = ("bank.own.3", "bank.mentor.1", "bank.collab.2")


def test_the_software_questions_and_descriptions_are_the_1_1_ones():
    """D5: sharing the bank changes what SWE plans may pick, never the 28 or their tags."""
    b = bank.load(BANK)
    sw = [[q.id, q.text, list(q.competencies), q.shape, q.min_level]
          for q in b.questions if q.field == "software" or q.id in MOVED]
    assert len(sw) == 28 and _sha(sw) == "9cba03a2d752"
    assert {q.field for q in b.questions if q.id in MOVED} == {"shared"}
    assert _sha(dict(sorted((c, b.competencies[c]) for c in SWE_TEN))) == "1f990cd508b2"


def _one_one() -> dict:
    """The shipped bank cut back to what 1.1 held: the ten competencies and the 28."""
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    for key in ("competencies", "competency_fields", "phase_affinity", "onet"):
        raw[key] = {c: v for c, v in raw[key].items() if c in SWE_TEN}
    raw["questions"] = [dict(q, field="software") for q in raw["questions"]
                        if q["field"] == "software" or q["id"] in MOVED]
    return raw


def _two_fields(tmp_path, *, case_shape="design"):
    """1.1's bank plus a data-analytics competency pair and a template for them."""
    raw = _one_one()
    raw["competencies"].update({"analysis": "turning data into a finding someone acted on",
                                "investigation": "working an open analytics problem through"})
    raw["competency_fields"].update({"analysis": "data_analytics",
                                     "investigation": "data_analytics"})
    raw["phase_affinity"].update({"analysis": "analytics_experience",
                                  "investigation": "analytics_case"})
    raw["questions"] += [
        {"id": "da.analysis.1", "text": "Tell me about an analysis that changed a decision.",
         "field": "data_analytics", "competencies": ["analysis"], "shape": "star",
         "source": "curated", "status": "approved"},
        {"id": "da.case.1", "text": "How would you find out why sign-ups fell last week?",
         "field": "data_analytics", "competencies": ["investigation"], "shape": case_shape,
         "source": "curated", "status": "approved"},
        {"id": "shared.collab.1", "text": "Tell me about a time you changed someone's mind.",
         "field": "shared", "competencies": ["collaboration"], "shape": "star",
         "source": "curated", "status": "approved"},
        {"id": "shared.own.1", "text": "Tell me about something you kept running after launch.",
         "field": "shared", "competencies": ["ownership", "learning", "mentoring"],
         "shape": "star", "source": "curated", "status": "approved"},
    ]
    p = tmp_path / "bank.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    plan = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for ph in plan["phases"]:
        ph["id"] = {"technical_experience": "analytics_experience",
                    "design": "analytics_case"}.get(ph["id"], ph["id"])
    t = tmp_path / "interview_data_analytics.json"
    t.write_text(json.dumps(plan), encoding="utf-8")
    return p, {"software": TEMPLATE, "data_analytics": t}


def test_a_version_1_bank_loads_as_software(tmp_path):
    raw = _one_one()
    raw["version"] = 1
    raw.pop("competency_fields")
    for q in raw["questions"]:
        q.pop("field")
    p = tmp_path / "v1.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    b = bank.load(p)
    assert {q.field for q in b.questions} == {"software"}
    assert set(b.competency_fields.values()) == {"software"}
    assert b.view("software").questions == b.questions


def test_a_version_2_question_must_name_its_field(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["questions"][0].pop("field")
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="declares field None"):
        bank.load(p)


def test_an_unknown_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match="format 3"):
        bank.load(_write(tmp_path, version=3))


def test_a_question_cannot_carry_another_fields_competency(tmp_path):
    p, templates = _two_fields(tmp_path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["questions"][0]["competencies"].append("analysis")
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="belong to another field"):
        bank.load(p, templates=templates)


def test_a_shared_question_carries_shared_competencies_only(tmp_path):
    p, templates = _two_fields(tmp_path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["questions"][-1]["competencies"].append("performance")
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="belong to another field"):
        bank.load(p, templates=templates)


def test_a_view_holds_its_field_and_the_shared_ones(tmp_path):
    p, templates = _two_fields(tmp_path)
    b = bank.load(p, templates=templates)
    da, sw = b.view("data_analytics"), b.view("software")
    assert set(da.competencies) == {"analysis", "investigation", "collaboration", "ownership",
                                    "learning", "mentoring"}
    assert {q.id for q in da.questions} == {"da.analysis.1", "da.case.1", "shared.collab.1",
                                            "shared.own.1"}
    assert "analysis" not in sw.competencies and "performance" in sw.competencies
    assert "shared.collab.1" in {q.id for q in sw.questions}
    assert da.view_of == "data_analytics" and b.view_of is None
    with pytest.raises(KeyError, match="unknown field"):
        b.view("nursing")


def test_every_view_is_checked_against_its_template(tmp_path):
    """Without its shared questions the data-analytics view has a hole the whole bank does
    not, and it fails at load rather than mid-interview."""
    p, templates = _two_fields(tmp_path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["questions"] = [q for q in raw["questions"] if q["field"] != "shared"]
    p.write_text(json.dumps(raw), encoding="utf-8")
    bank.load(p)
    with pytest.raises(ValueError, match="no question covers collaboration, learning, "
                                         "mentoring, ownership in the data_analytics view"):
        bank.load(p, templates=templates)


def test_a_phase_the_template_lacks_is_refused(tmp_path):
    p, _ = _two_fields(tmp_path)
    with pytest.raises(ValueError, match="phase, which the data_analytics template does not"):
        bank.load(p, templates={"software": TEMPLATE, "data_analytics": TEMPLATE})


def test_the_case_phase_shape_comes_from_the_template(tmp_path):
    """Learned from `observation_shape`, not from a phase called `design`."""
    p, templates = _two_fields(tmp_path)
    assert bank.template_shapes(templates["data_analytics"])["analytics_case"] == "design"
    bank.load(p, templates=templates)
    p, templates = _two_fields(tmp_path, case_shape="star")
    with pytest.raises(ValueError, match="can only hold design questions"):
        bank.load(p, templates=templates)


def test_a_view_cannot_be_saved_over_the_bank(tmp_path):
    with pytest.raises(ValueError, match="software view"):
        bank.save(bank.load(BANK).view("software"), tmp_path / "b.json")


def test_onet_round_trips_and_a_bad_id_is_refused(tmp_path):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["onet"] = {"performance": [{"id": "4.A.2.a.4",
                                    "title": "Analyzing Data or Information"}]}
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    out = tmp_path / "saved.json"
    bank.save(bank.load(p), out)
    assert bank.load(out).onet == {"performance": (("4.A.2.a.4",
                                                    "Analyzing Data or Information"),)}
    raw["onet"]["performance"][0]["id"] = "2.A.1"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="O\\*NET"):
        bank.load(p)


def _local(tmp_path, *rows, **extra):
    p = tmp_path / "local.json"
    p.write_text(json.dumps({"version": 2, "questions": list(rows), **extra}), encoding="utf-8")
    return p


GEN = {"id": "gen.performance.1", "text": "Tell me about a slow page you made fast?",
       "field": "software", "competencies": ["performance"], "shape": "star",
       "source": "generated", "status": "approved", "min_level": "mid"}


def test_local_questions_join_the_bank_and_never_its_file(tmp_path):
    b = bank.load(BANK, local=_local(tmp_path, GEN))
    assert b.for_competency("performance")[-1].id == "gen.performance.1"
    assert b.local_ids == {"gen.performance.1"}
    out = tmp_path / "saved.json"
    bank.save(b, out)
    assert out.read_bytes() == BANK.read_bytes()


def test_the_local_file_holds_generated_questions_only(tmp_path):
    with pytest.raises(ValueError, match="only generated questions"):
        bank.load(BANK, local=_local(tmp_path, {**GEN, "source": "curated"}))
    with pytest.raises(ValueError, match="repeats question id"):
        bank.load(BANK, local=_local(tmp_path, {**GEN, "id": "bank.perf.1"}))


def test_saving_one_views_approvals_keeps_the_others(tmp_path):
    other = {**GEN, "id": "gen.analysis.1", "field": "data_analytics"}
    p = _local(tmp_path, other, imported_1_1={"imported": []})
    q = bank.Question(id="gen.learning.7", text="Tell me about a tool you learned fast?",
                      competencies=("learning",), shape="star", source="generated",
                      status="proposed")
    b = bank.approve(bank.with_question(bank.load(BANK), q), "gen.learning.7")
    bank.save_local(b.view("software"), p)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert [r["id"] for r in saved["questions"]] == ["gen.analysis.1", "gen.learning.7"]
    assert saved["questions"][1]["status"] == "approved"
    assert saved["imported_1_1"] == {"imported": []}


def _legacy(tmp_path, *extra):
    raw = json.loads(BANK.read_text(encoding="utf-8"))
    raw["version"] = 1
    raw.pop("competency_fields")
    for q in raw["questions"]:
        q.pop("field")
    raw["questions"] += [{k: v for k, v in GEN.items() if k != "field"}, *extra]
    p = tmp_path / "bank_1.1.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_a_1_1_banks_generated_questions_are_imported_once(tmp_path):
    """D12: every upgrade since 1.0 replaced config/question_bank.json and lost them."""
    dup = {**GEN, "id": "gen.performance.2"}
    bad = {**GEN, "id": "gen.performance.3", "text": "Something else?", "competencies": ["x"]}
    legacy, local = _legacy(tmp_path, dup, bad), tmp_path / "local.json"
    shipped = bank.load(BANK)
    assert bank.import_legacy(shipped, legacy, local) == ["gen.performance.1"]
    record = json.loads(local.read_text(encoding="utf-8"))["imported_1_1"]
    assert record["imported"] == ["gen.performance.1"]
    assert record["skipped"] == ["gen.performance.2", "gen.performance.3"]
    assert bank.import_legacy(shipped, legacy, local) == []
    got = bank.load(BANK, local=local).for_competency("performance")[-1]
    assert (got.id, got.field, got.status, got.min_level) == ("gen.performance.1", "software",
                                                              "approved", "mid")


def test_an_unreadable_1_1_bank_does_not_stop_the_app(tmp_path):
    legacy = tmp_path / "bank_1.1.json"
    legacy.write_text("{not json", encoding="utf-8")
    local = tmp_path / "local.json"
    assert bank.import_legacy(bank.load(BANK), legacy, local) == []
    assert json.loads(local.read_text(encoding="utf-8"))["imported_1_1"]["imported"] == []


def test_the_installed_bank_carries_the_import(tmp_path, monkeypatch):
    shipped = BANK.read_bytes()
    monkeypatch.setattr(bank, "LEGACY", _legacy(tmp_path))
    assert "gen.performance.1" in bank.installed(BANK).local_ids
    assert BANK.read_bytes() == shipped


def test_every_shipped_view_validates_against_its_template():
    """Activation item 4's bank: each field's view covers every competency with a question of
    the shape its phase holds, on that field's own template."""
    b = bank.load(BANK, templates=fields.templates())
    for fid in fields.IDS:
        v = b.view(fid)
        assert v.questions and v.competencies, fid


def test_the_installed_bank_can_be_narrowed_to_a_field():
    b = bank.installed(BANK, field="software")
    assert b.view_of == "software"
    assert "analysis" not in b.competencies and "performance" in b.competencies
    assert bank.installed(BANK).view_of is None
