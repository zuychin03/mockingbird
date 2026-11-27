"""Report integrity: one threshold, one artifact, no network.

Both defects here were live at once and neither had a test, which is how two candidate-facing
outputs came to disagree about what the candidate was worst at.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import report as rep  # noqa: E402
from app import score  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _report(rates: dict[str, list[bool]]) -> score.Report:
    """One QuestionScore per index across the given per-criterion outcomes."""
    n = len(next(iter(rates.values())))
    r = score.Report(session_id="t")
    for i in range(n):
        qs = score.QuestionScore(question_id="q.%d" % i, question="Q?", answer="A")
        qs.met = {k: v[i] for k, v in rates.items()}
        r.scores.append(qs)
    return r


def test_both_report_paths_name_the_same_weakest_criteria():
    """`Report.weakest` ranked `< 0.5` while `render()` ranked `<= 0.6`, and both were live:
    the plain Stage 2 report reads the first, the rendered HTML recomputes the second. A
    criterion met exactly 3 times in 5 was the candidate's weakest in one and absent from
    the other."""
    r = _report({
        "sets_context": [True, True, True, False, False],      # 0.6, weak at <=0.6 only
        "describes_action": [True, True, True, True, True],    # 1.0, never weak
        "states_outcome": [False, False, False, False, False],  # 0.0, weak either way
    })
    rate = {k: v[0] / v[1] for k, v in r.totals.items() if v[1]}
    rendered = {k for k, v in rate.items() if v <= rep.WEAK}
    assert set(r.weakest) == rendered
    assert "sets_context" in rendered, "the case that used to disagree"


def test_praise_is_not_evidenced_with_an_answer_that_declines():
    """Observed live (9.16): "you set the scene before the story" was evidenced with "I can't
    really think of one to be honest..." -- true of its second sentence, and it reads as
    praising someone for having nothing to say. Section 9.5 gave the WEAKNESS path
    richest-first ordering and a thin-answer filter and never applied either here."""
    declines = ("I can't really think of one to be honest. We don't really disagree much, "
                "there's only four of us and my manager usually decides.")
    substantial = ("When I took over the booking tool it was two of us on a Node and Postgres "
                   "service, about eight thousand lines, and the client wanted it done in "
                   "six weeks which is where most of the pressure came from.")
    r = score.Report(session_id="t")
    for qid, answer in (("q.0", declines), ("q.1", substantial)):
        qs = score.QuestionScore(question_id=qid, question="Q?", answer=answer,
                                 addresses_question="partial")
        qs.met = {"sets_context": True}
        qs.evidence["sets_context"] = answer
        qs.quoted.add("sets_context")
        r.scores.append(qs)

    text = rep.render(r, questions_asked=2, questions_answered=2)
    block = text.split("WHAT YOU ALREADY DO WELL")[1].split("\n\n")[0]
    assert "When I took over the booking tool" in block, "the one that sets the scene"
    assert "can't really think of one" not in block


def test_praise_falls_back_rather_than_going_silent():
    """A weaker example beats none -- the same rule `_missed` follows (9.5)."""
    only = "I can't think of one, I'm quite junior and haven't had that come up yet really."
    r = score.Report(session_id="t")
    qs = score.QuestionScore(question_id="q.0", question="Q?", answer=only,
                             addresses_question="partial")
    qs.met = {"sets_context": True}
    qs.evidence["sets_context"] = only
    qs.quoted.add("sets_context")
    r.scores.append(qs)
    assert rep._shown(r, "sets_context") is not None


def test_two_strengths_do_not_cite_the_same_answer():
    """Three points on one answer makes the report look like it found one good moment
    rather than three habits -- the reason `_missed` tracks what it has cited."""
    r = _report({"sets_context": [True, True], "describes_action": [True, True]})
    for i, qs in enumerate(r.scores):
        qs.answer = "Answer number %d, long enough to count as engaged with the question " \
                    "and carrying a bit of detail about the system involved." % i
        qs.question = "Question %d?" % i
        for name in ("sets_context", "describes_action"):
            qs.evidence[name] = qs.answer
            qs.quoted.add(name)
    a = rep._shown(r, "sets_context")
    b = rep._shown(r, "describes_action", {a.question_id})
    assert a.question_id != b.question_id


def test_the_report_renders_what_the_candidate_asked():
    """`asked_back` was persisted from the first closing handler and read by nobody, while the
    interviewer said to the candidate's face that it had gone "in your report". The line was
    corrected first; this is the half that makes the original claim true."""
    from types import SimpleNamespace
    r = _report({"sets_context": [True, False]})
    mine = ("When you moved off the monolithic ledger, did one service end up owning "
            "settlement across all currencies, or did it split per-region?")
    states = [
        SimpleNamespace(question_id="q.0", question=r.scores[0].question,
                        closed_because=None, asked_back=[mine]),
        SimpleNamespace(question_id="q.1", question=r.scores[1].question,
                        closed_because=None, asked_back=[]),
    ]
    text = rep.render(r, questions_asked=2, questions_answered=2, question_states=states)

    assert "WHAT YOU ASKED" in text
    # Verbatim, compared against the flattened text because the line is wrapped to the report
    # width. These are the only words in the report that were never scored, extracted or
    # judged, so a paraphrase would be the one edit with nothing to gain.
    assert " ".join(mine.split()) in " ".join(text.split())
    block = text.split("WHAT YOU ASKED")[1]
    assert "no employer behind this" in block


def test_a_report_with_no_candidate_questions_omits_the_section():
    """An empty section is worse than no section: it invites the reader to wonder what they
    were supposed to have asked."""
    from types import SimpleNamespace
    r = _report({"sets_context": [True, False]})
    states = [SimpleNamespace(question_id="q.0", question=r.scores[0].question,
                              closed_because=None, asked_back=[])]
    text = rep.render(r, questions_asked=2, questions_answered=2, question_states=states)
    assert "WHAT YOU ASKED" not in text


def test_a_question_cut_short_is_flagged_in_the_report():
    """`closed_by` put an answer the model was satisfied with and one that ran out of turns
    in the same bucket, so the report presented their scores identically."""
    from types import SimpleNamespace
    r = _report({"sets_context": [True, False]})
    r.scores[0].question = "Tell me about a disagreement."
    r.scores[1].question = "Tell me about a failure."
    states = [
        SimpleNamespace(question_id="q.0", question=r.scores[0].question,
                        closed_because="evidence_complete", asked_back=[]),
        SimpleNamespace(question_id="q.1", question=r.scores[1].question,
                        closed_because="budget_exhausted", asked_back=[]),
    ]
    text = rep.render(r, questions_asked=2, questions_answered=2, question_states=states)
    assert "SCORED, BUT CUT SHORT" in text
    block = text.split("SCORED, BUT CUT SHORT")[1].split("\n\n")[0]
    assert "ran out of follow-ups" in block
    assert "Tell me about a failure" in block
    assert "Tell me about a disagreement" not in block, "a question that finished properly"


def test_a_report_without_close_reasons_still_renders():
    """Every session stored before the field existed has none."""
    r = _report({"sets_context": [True, False]})
    assert "SCORED, BUT CUT SHORT" not in rep.render(r, 2, 2)


def test_the_threshold_has_one_definition():
    assert rep.WEAK is score.WEAK
    assert rep.STRONG is score.STRONG


def test_a_rendered_report_reaches_no_network_host():
    """The product requirement is a self-contained local artifact. The HTML linked Google
    Fonts, so offline it lost its typography with nothing to say about why."""
    for tool in ("render_report.py", "render_transcript.py"):
        src = (ROOT / "tools" / tool).read_text(encoding="utf-8")
        template = "".join(re.findall(r'"""(.*?)"""', src, re.S))
        for host in ("http://", "https://", "//fonts.", "cdn."):
            assert host not in template, "%s embeds %s" % (tool, host)


def test_a_candidate_question_is_never_truncated():
    """The first version clipped at 200 characters, which silently dropped the second half of
    "Two things. First ... Second ..." -- the same loss the section exists to undo."""
    from types import SimpleNamespace
    r = _report({"sets_context": [True, False]})
    both = ("Two things. First, when you moved off the monolithic ledger, did one service own "
            "settlement across every currency or did it split per-region? Second, who gets "
            "paged when settlement breaks at three in the morning, the owning team or a "
            "central SRE group?")
    states = [SimpleNamespace(question_id="q.0", question=r.scores[0].question,
                              closed_because=None, asked_back=[both])]
    text = rep.render(r, questions_asked=1, questions_answered=1, question_states=states)
    flat = " ".join(text.split())
    assert "Second, who gets paged" in flat, "the second question was dropped"
    assert "..." not in text.split("WHAT YOU ASKED")[1].split("\n\n")[1]


# ------------------------------------------------ the report as structure (P4)
ASKED = ("Two questions. Who owns the release train now the ledger moved? 2. Is \"on call\" "
         "shared across both teams?")


def _full():
    """A report that reaches every section, asking a question that wraps onto "2."."""
    from types import SimpleNamespace
    r = _report({"sets_context": [True, True, True], "states_outcome": [False, False, True],
                 "first_person": [True, False, True]})
    for i, qs in enumerate(r.scores):
        qs.question = "Tell me about a time number %d that a plan changed late?" % i
        qs.answer = ("We moved the ledger to a new service over three weekends and I wrote the "
                     "cut-over plan myself, then ran it with the on-call team %d." % i)
        qs.addresses_question = "yes" if i else "partly"
        qs.evidence["sets_context"] = "the ledger ran on one box in Sydney"
        qs.quoted.add("sets_context")
    states = [SimpleNamespace(question_id=q.question_id, question=q.question,
                              closed_because="budget_exhausted" if i == 1 else None,
                              asked_back=[ASKED] if i == 2 else [])
              for i, q in enumerate(r.scores)]
    design = SimpleNamespace(shape="design", text="a queue", approach="a queue in front",
                             alternative="", tradeoff="it adds a hop", failure_mode="")
    delivery = {"answers": [{"question_id": "q.0"}], "spoken": 3, "articulation_rate": 4.2,
                "wpm": 131.0, "pause_count": 7, "mid_clause_pauses": 2,
                "mid_clause_share": 0.29, "speaking_seconds": 95.0}
    return r, states, [design], delivery


def _rubric(r):
    """The payload's rubric rows, as `api._rubric` writes them."""
    return [{"name": n, "label": n, "description": score.CRITERIA[n][1], "met": m, "of": o,
             "evidence": []} for n, (m, o) in sorted(r.totals.items())]


def test_the_text_is_laid_out_from_the_structure():
    r, states, obs, d = _full()
    doc = rep.build(r, 3, 3, obs, states, d)
    assert rep.to_text(doc) == rep.render(r, 3, 3, observations=obs, question_states=states,
                                          delivery=d)
    assert [s["id"] for s in doc["sections"]] == [
        "summary", "change", "strengths", "criteria", "delivery", "cut_short", "revisit",
        "asked", "design"]
    assert {b["kind"] for s in doc["sections"] for b in s["blocks"]} == {
        "para", "lead", "item", "quote", "rubric", "delivery"}
    # Whole sentences: the wrapping belongs to whatever lays the blocks out.
    assert not any("\n" in b.get("text", "") for s in doc["sections"] for b in s["blocks"])
    assert {"kind": "item", "text": ASKED} in doc["sections"][7]["blocks"]
    assert "answers" not in doc["sections"][4]["blocks"][-1]["figures"]
    assert doc["signoff"] == list(rep.SIGNOFF)


def test_a_report_reads_back_to_the_structure_it_was_printed_from():
    """How a report cached before the structure gets one. If text this renderer printed read
    back as anything else, History would lay out an old report differently from a new one."""
    r, states, obs, d = _full()
    doc = rep.build(r, 3, 3, obs, states, d)
    text = rep.to_text(doc)
    assert "\n    2. Is" in text, "the fixture no longer wraps a question onto a number"
    back = rep.from_text(text, _rubric(r), d)
    assert back.pop("from_text") is True
    assert back == doc


def test_one_criterion_still_reads_back_as_the_rubric():
    r = _report({"first_person": [True, False]})
    doc = rep.build(r, 2, 2)
    back = rep.from_text(rep.to_text(doc), _rubric(r))
    back.pop("from_text")
    assert back == doc


def test_a_session_with_nothing_scored_still_has_a_structure():
    d = {"answers": [], "spoken": 1, "articulation_rate": None, "wpm": None, "pause_count": 0,
         "mid_clause_pauses": 0, "mid_clause_share": None, "speaking_seconds": 12.6}
    doc = rep.build(score.Report(session_id="t"), 2, 0, delivery=d)
    assert [s["id"] for s in doc["sections"]] == ["summary", "delivery"]
    assert doc["sections"][0]["heading"] is None and doc["signoff"] == []
    text = rep.to_text(doc)
    assert text.startswith("No scored questions in this session.\n\nDELIVERY\n")
    back = rep.from_text(text, None, d)
    back.pop("from_text")
    assert back == doc


def test_an_older_report_reads_the_way_history_read_it():
    """Headings this version does not print still make sections, and the rubric is found by
    the criteria it names."""
    old = ("HOW IT WENT\n==========\n\n"
           "  You gave four figures and said how\n  you measured two of them.\n\n"
           "1. Say what changed  (2 of 6 answers)\n   Finish with the effect.\n"
           "   You said: \"it went fine\"\n\n"
           "THE CRITERIA\n============\n\n  sets_context        6/6\n  specific_detail     2/6\n\n"
           "Every quote above is your own words.\n")
    rows = [{"name": "sets_context", "met": 6, "of": 6, "description": "said where"},
            {"name": "specific_detail", "met": 2, "of": 6, "description": "gave a figure"}]
    assert rep.from_text(old, rows) == {
        "version": 1, "from_text": True,
        "sections": [
            {"id": None, "heading": "HOW IT WENT", "blocks": [
                {"kind": "para",
                 "text": "You gave four figures and said how you measured two of them."},
                {"kind": "lead", "text": "1. Say what changed  (2 of 6 answers)"},
                {"kind": "para", "text": "Finish with the effect."},
                {"kind": "quote", "text": "You said: \"it went fine\""}]},
            {"id": None, "heading": "THE CRITERIA", "blocks": [{"kind": "rubric", "rows": rows}]}],
        "signoff": ["Every quote above is your own words."]}


# ------------------------------------------------ a report for every field (P4 step 3)
def _template(field):
    import json
    from app import fields
    return json.loads(fields.get(field).template.read_text(encoding="utf-8"))


def test_advice_priority_orders_the_weak_criteria_and_never_changes_which():
    totals = {"sets_context": (1, 5), "states_outcome": (2, 5), "first_person": (3, 5),
              "describes_action": (5, 5)}
    assert score.weak_order(totals) == ["sets_context", "states_outcome", "first_person"]
    assert score.weak_order(totals, ["first_person", "describes_action", "states_outcome"]) == [
        "first_person", "states_outcome", "sets_context"], "unlisted last, still by rate"


def test_a_software_plan_reports_exactly_as_before():
    r, states, obs, d = _full()
    plan = _template("software")
    assert "advice" not in plan and "advice_priority" not in plan
    assert rep.render(r, 3, 3, obs, states, d, plan) == rep.render(r, 3, 3, obs, states, d)


def test_a_field_report_takes_its_template_advice_order_and_case_wording():
    r, states, obs, d = _full()
    plan = {"field": "product_management",
            "advice_priority": _template("product_management")["advice_priority"]}
    doc = rep.build(r, 3, 3, obs, states, d, plan)
    change = next(s for s in doc["sections"] if s["id"] == "change")["blocks"]
    assert change[0]["text"].startswith("1. Several answers stopped at what you did")
    fix = _template("product_management")["advice"]["states_outcome"]["fix"]
    assert change[1] == {"kind": "para", "text": fix}
    case = next(s for s in doc["sections"] if s["id"] == "design")
    assert case["heading"] == "ON THE CASE QUESTION"
    assert case["blocks"][0]["text"].startswith("Not scored -- a case question")
    assert {"kind": "para", "text": "You said what you would do:"} in case["blocks"]
    back = rep.from_text(rep.to_text(doc), _rubric(r), d)
    back.pop("from_text")
    assert back == doc


def test_the_plan_s_own_advice_wins_and_keeps_the_rest():
    r, states, obs, d = _full()
    plan = {"field": "product_management", "advice": {"states_outcome": {"fix": "Say it."}}}
    change = next(s for s in rep.build(r, 3, 3, obs, states, d, plan)["sections"]
                  if s["id"] == "change")["blocks"]
    assert change[1]["text"] == "Say it."
    assert change[0]["text"].startswith("1. %s" % rep.ADVICE["states_outcome"][0])
    assert rep.advice_for(plan)["sets_context"] == rep.ADVICE["sets_context"]


@pytest.mark.parametrize("field", ["data_analytics", "general", "product_management",
                                   "project_management", "ux_design"])
def test_a_template_advises_only_on_what_it_scores(field):
    t = _template(field)
    scored = {c for ph in t["phases"] for c in ph.get("rubric_criteria") or []}
    assert set(t["advice"]) <= scored
    for words in t["advice"].values():
        assert set(words) <= {"problem", "fix"} and all(w.strip() for w in words.values())
        assert not any("—" in w for w in words.values())
