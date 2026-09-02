"""Report integrity: one threshold, one artifact, no network.

Both defects here were live at once and neither had a test, which is how two candidate-facing
outputs came to disagree about what the candidate was worst at.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

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
