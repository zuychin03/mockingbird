"""Feedback for the candidate. Plan section 6, log section 9.5.

The report is the product. Everything before it -- the turn loop, the guards, the budget -- is
in service of a person finding out how they did, and a coach that conducts a good interview and
says nothing is not a coach.

Four decisions about what this says, all of which constrain the code below:

  no grade          a number out of ten tells someone how they did and not what to change.
                    The criteria are reported, the arithmetic is visible, and nothing is
                    rolled into a single score that invites comparison to strangers.
  evidence first    every claim quotes the candidate. NFR-5 requires a score to name the
                    observation behind it; more importantly, feedback that cannot be checked
                    is feedback that has to be taken on trust, and this model has not earned
                    that (7.10).
  the near miss     the useful advice is on criteria they met SOMETIMES, not never -- those
                    are habits, and a habit is fixable. Something they never did may simply
                    not apply to them.
  their words       advice is phrased against what they actually said, not against a template,
                    so "you gave the figure and not the method" cites the figure.

`build` makes the report as sections of typed blocks, and every reader lays those out its own
way: `to_text` for a terminal, History and the exports as pages. A report cached before it had
the structure is read back from its text by `from_text`.
"""

from __future__ import annotations

import functools
import json
import re
import textwrap

from . import fields, guards
from .score import CRITERIA, Report, weak_order

# What to say when a criterion is weak, and what to ask them to do instead. Written as
# second-person coaching rather than as a rubric label, because the rubric label is what the
# candidate cannot act on.
ADVICE = {
    "sets_context": (
        "Several answers began with what you did rather than where you were.",
        "One sentence of setup first -- the system, its scale, the constraint you were under. "
        "It is what makes the rest of the answer mean anything."),
    "describes_action": (
        "Some answers described a situation without saying what was actually done about it.",
        "Say what you did, in the order you did it. The interviewer is trying to picture you "
        "working."),
    "states_outcome": (
        "Several answers stopped at what you did and never said what changed.",
        "Finish with the effect: what got faster, what stopped breaking, what the team did "
        "differently afterwards. An action with no outcome reads as an activity, not a result."),
    "first_person": (
        "In places you described work the team did without saying which part was yours.",
        "Say 'I' where it was you. Interviewers cannot give you credit for work you attribute "
        "to a group."),
    "specific_detail": (
        "Your answers were mostly qualitative -- big, slow, a lot, much faster.",
        "Put a number on it. 'Eight seconds to four hundred milliseconds' is checkable; "
        "'much faster' is not, and the difference is what separates an anecdote from evidence."),
    "measurement_stated": (
        "You gave figures without saying how you got them.",
        "Say how you know -- profiled it, timed it before and after, watched the dashboard. "
        "A number with a method behind it is worth several without."),
    # Design questions (log 9.6).
    "names_approach": (
        "The design answer stayed general and never landed on something to build.",
        "Name the mechanism early -- a token bucket, a queue, a cache -- even if you change it "
        "later. An interviewer cannot follow your reasoning until they know what you are "
        "reasoning about."),
    "considers_alternatives": (
        "You gave one design and did not say what else you considered.",
        "Name the option you rejected and why. A design with no discarded alternative reads "
        "as the first thing you thought of, whether or not it was."),
    "names_tradeoff": (
        "You described what your design does without saying what it costs.",
        "Every choice buys something and pays for it somewhere -- memory, accuracy, "
        "complexity, a burst at the window boundary. Saying the price is what shows you "
        "chose rather than guessed."),
    "anticipates_failure": (
        "The design did not say what happens when part of it breaks.",
        "Say what fails and what you would do about it -- what happens when the store is "
        "unavailable, when one key is enormous, when two servers write at once. That is "
        "usually the question behind the question."),
}

PRAISE = {
    "sets_context": "you set the scene before the story",
    "describes_action": "you said plainly what you did",
    "states_outcome": "you closed the loop on what changed",
    "first_person": "you were clear about your own part",
    "specific_detail": "you answered with figures",
    "measurement_stated": "you said how you knew, not just what you found",
    "names_approach": "you named something concrete to build",
    "considers_alternatives": "you weighed more than one approach",
    "names_tradeoff": "you said what your choice costs",
    "anticipates_failure": "you said what would break, and when",
}

# Re-exported so `report.WEAK` keeps resolving for the renderers. The definition lives with
# `Report.weakest`, which is the other thing that has to agree with it: the two used to be
# `< 0.5` here and `<= 0.6` there, and both were live, so the plain report and the rendered
# one could name different criteria as the candidate's worst.
from .score import STRONG, WEAK  # noqa: E402,F401


def _missed(report: Report, criterion: str, used: set[str] | None = None):
    """A question where this was missed, chosen to illustrate a HABIT.

    Two questions are poor illustrations and both were being picked:

    a question they could not answer -- "I've not really shipped anything big enough to go
    wrong yet" is not an example of failing to quantify, it is an example of having nothing to
    say, and citing it reads as a reprimand for inexperience;

    a question already used for an earlier point -- three pieces of advice all pointing at the
    same answer makes the report look like it found one bad moment rather than three habits.

    Falls back rather than returning nothing: a weaker example beats none (log 9.5).
    """
    used = used or set()
    misses = [q for q in report.scores if q.met.get(criterion) is False]
    # Richest first. A habit shows best in an answer they gave plenty of, and it keeps the
    # thin "I have not done that" answers out of the examples without needing to classify
    # them -- they sort to the bottom on their own.
    misses.sort(key=lambda q: -len(q.answer.split()))
    engaged = [q for q in misses if q.addresses_question != "no" and len(q.answer.split()) > 12]
    for pool in (
            [q for q in engaged if q.question_id not in used],  # engaged and not yet cited
            engaged,                                            # engaged, even if repeated
            [q for q in misses if q.question_id not in used],    # anything not yet cited
            misses):
        if pool:
            return pool[0]
    return None


def _shown(report: Report, criterion: str, used: set[str] | None = None):
    """A question where this WAS met, chosen the same way `_missed` chooses a miss.

    The strengths path used to take the first scored question with a quote over 20 characters,
    which put an answer that OPENS on a non-answer under a compliment. Observed live (9.16):
    "you set the scene before the story" was evidenced with "I can't really think of one to be
    honest. We don't really disagree much, there's only four of us" -- true about the second
    sentence, and it reads as praising someone for having nothing to say.

    Section 9.5 gave `_missed` richest-first ordering and a thin-answer filter for exactly this
    reason and never applied either here. The cannot-answer test is the addition: sorting alone
    does not stop a long answer that begins by declining.
    """
    used = used or set()
    hits = [q for q in report.scores
            if q.met.get(criterion) and len(_quote(q, criterion)) > 20]
    hits.sort(key=lambda q: -len(q.answer.split()))
    engaged = [q for q in hits
               if q.addresses_question != "no" and len(q.answer.split()) > 12
               and not guards.cannot_answer(q.answer)]
    for pool in (
            [q for q in engaged if q.question_id not in used],
            engaged,
            [q for q in hits if q.question_id not in used],
            hits):
        if pool:
            return pool[0]
    return None


def _quote(qs, criterion: str) -> str:
    """The candidate's words, or "" when the criterion has no quote behind it.

    Only quoted criteria have one. The deterministic three are detections, and rendering
    "found in the answer" inside quotation marks attributes our sentence to them.
    """
    return qs.evidence.get(criterion, "") if criterion in qs.quoted else ""


# What to say about a design answer. Descriptive: it reports which parts are present and
# does not decide whether the answer was good, because scoring these inverted the ranking of
# four measured candidates (log 9.6).
DESIGN_PARTS = (
    ("approach", "named what you would build"),
    ("alternative", "mentioned another approach"),
    ("tradeoff", "named a cost or limit"),
    ("failure_mode", "raised something that could go wrong"),
)


def _clip(text: str, limit: int) -> str:
    """Shorten on a word boundary. A cut mid-word reads as a bug in a report made of quotes."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or t[:limit]) + "..."


# A reader finds a section by its id. The heading is what the candidate reads, and a field may
# word it differently.
HEADINGS = {
    "summary": "HOW THAT WENT",
    "change": "WHAT WOULD CHANGE THE MOST",
    "strengths": "WHAT YOU ALREADY DO WELL",
    "criteria": "EVERY CRITERION",
    "delivery": "DELIVERY",
    "cut_short": "SCORED, BUT CUT SHORT",
    "revisit": "QUESTIONS WORTH REVISITING ON YOUR OWN",
    "asked": "WHAT YOU ASKED",
    "design": "ON THE DESIGN QUESTION",
}

DESIGN_INTRO = ("Not scored -- a hypothetical has no outcome to check an answer against, and "
                "the parts below are reported rather than marked. Read them as a checklist of "
                "what a design answer usually covers.")
# The other fields' case question, in the slot where software asks its design question.
# General asks neither (V1.2_PLAN P4).
CASE_HEADING = "ON THE CASE QUESTION"
CASE_INTRO = ("Not scored -- a case question has no outcome to check an answer against, and the "
              "parts below are reported rather than marked. Read them as a checklist of what a "
              "case answer usually covers.")
CASE_PARTS = (
    ("approach", "said what you would do"),
    ("alternative", "mentioned another approach"),
    ("tradeoff", "named a cost or limit"),
    ("failure_mode", "raised something that could go wrong"),
)
DELIVERY_INTRO = ("Observations, not scores. These measures are the ones most affected by "
                  "recognition error and by accent, so they sit beside the result, not in it.")
CUT_SHORT_INTRO = ("These questions ended before the conversation was finished with them, so "
                   "read their scores as weaker evidence than the rest.")
ASKED_INTRO = ("These went unanswered on purpose. There is no employer behind this interview, "
               "and inventing an answer about a real workplace is the one thing a practice "
               "interviewer must not do. They are recorded here so you can put them to the "
               "real one.")
# "Nothing here is an impression" was not true, and it is the kind of untrue that 9.5 was
# written about. The quotes are the candidate's own words and the arithmetic is checkable, but
# a model chose which words counted as evidence, and saying otherwise claims a guarantee the
# pipeline does not have.
SIGNOFF = ("Every quote above is your own words, and the counting on top of them is "
           "arithmetic you can check.",
           "Which words counted as evidence was decided by a model, so that part is a "
           "reading, not a measurement.")


def _block(kind: str, text: str) -> dict:
    return {"kind": kind, "text": text}


def _section(sid: str, blocks: list[dict]) -> dict:
    return {"id": sid, "heading": HEADINGS[sid], "blocks": blocks}


def _design_section(observations, case: bool = False) -> dict | None:
    """A description of the design or case answer. No score, no contribution to any total."""
    d = next((o for o in observations if o.shape == "design" and o.text.strip()), None)
    if d is None:
        return None
    parts = CASE_PARTS if case else DESIGN_PARTS
    blocks = [_block("para", CASE_INTRO if case else DESIGN_INTRO)]
    # "covered" would be a verdict, and a verdict is the thing that inverted the ranking.
    # These say what was FOUND and let the candidate judge it -- which they can, since the
    # words are their own.
    for k, label in parts:
        if getattr(d, k):
            blocks += [_block("para", "You %s:" % label),
                       _block("quote", "\"%s\"" % _clip(getattr(d, k), 88))]
    blocks += [_block("item", "Nothing in the answer %s." % label)
               for k, label in parts if not getattr(d, k)]
    s = _section("design", blocks)
    if case:
        s["heading"] = CASE_HEADING
    return s


@functools.cache
def _template_advice(field_id: str) -> dict:
    try:
        raw = json.loads(fields.get(field_id).template.read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return {}
    return raw.get("advice") or {}


def advice_for(plan: dict | None) -> dict[str, tuple[str, str]]:
    """`ADVICE` with the field template's overrides, where software's examples do not fit.
    The plan's own copy wins; a plan recorded before templates carried advice uses its field's
    template as it is now."""
    plan = plan or {}
    over = (plan["advice"] if "advice" in plan
            else _template_advice(plan.get("field", fields.SOFTWARE)))
    out = dict(ADVICE)
    for name, words in (over or {}).items():
        problem, fix = ADVICE.get(name, (name, ""))
        out[name] = (words.get("problem") or problem, words.get("fix") or fix)
    return out


GENERATED_INTRO = ("The model wrote these questions from your job description, and they were on "
                   "the plan you approved before the interview. Each shows the duty it was "
                   "written from.")
JD_INTRO = "The description as you pasted it, kept with this interview."


def kind_of(info: dict) -> str:
    """The line the exports and History name the interview with, such as "Data analytics
    interview, planned from a job description"."""
    return "%s interview%s" % (info["field_label"], ", planned from a job description"
                               if info["job_description"] else "")


def about(session: dict) -> dict:
    """What the interview was made from, read from its own snapshot whenever a report or an
    export is made, so one cached before this existed still carries it. `generated` lists the
    asked questions the model wrote from the description, each with its duty."""
    plan = session.get("plan_snapshot") or {}
    f = fields.FIELDS.get(plan.get("field") or fields.SOFTWARE) or fields.get(fields.SOFTWARE)
    duty = {r.get("text"): r.get("duty") or "" for r in plan.get("generated") or []}
    return {
        "field": f.id,
        "field_label": f.label,
        "measured": f.measured_note,
        "job_description": bool((plan.get("job_description") or {}).get("text")),
        "generated": [{"question_id": q.get("question_id"), "question": q.get("question"),
                       "duty": duty[q.get("question")]}
                      for q in session.get("questions") or [] if q.get("question") in duty],
    }


def design_note(observations) -> list[str]:
    """The design section as text, or nothing when no design question was answered."""
    s = _design_section(observations)
    return _lay_design(s) if s else []


# Why a question ended, in words a candidate can act on. Only the reasons that mean the
# conversation stopped moving appear here: `evidence_complete` and `model_advanced` are the
# question working as intended and need no explanation.
#
# It matters because a score carries different weight depending on which of these it came
# from. A criterion missed on a question that ran out of follow-ups is weaker evidence about
# the candidate than the same miss on one they finished, and the report used to present both
# identically -- `closed_by` recorded only `advance` or `skip`.
CUT_SHORT = {
    "budget_exhausted": "we ran out of follow-ups",
    "no_new_evidence": "the answer stopped developing",
    "wording_exhausted": "I ran out of ways to ask it",
    "clarification_exhausted": "the question never landed",
    "detour_budget_spent": "we ran out of time for questions",
    "skip_consented": "you asked to skip it",
    "refused": "you chose not to answer",
    "ended_early": "the session ended here",
    "left": "you left the interview here",
}


def _figures(d: dict) -> dict:
    """The session's delivery measures. The per-answer rows stay in the payload's own copy."""
    return {k: v for k, v in d.items() if k != "answers"}


PAUSE_NOTE = ("Pausing between clauses reads as normal; pausing inside one reads as hunting "
              "for the word.")


def _figure_rows(d: dict) -> list[dict]:
    """The delivery measures in words, so the text and every page say them the same way."""
    rows = []
    if d.get("articulation_rate"):
        rows.append({"label": "Speaking rate", "text": "%.1f syllables per second while "
                     "actually speaking" % d["articulation_rate"]})
    if d.get("wpm"):
        # 11.5's band, given as context rather than a verdict: it is coaching guidance, not a
        # measurement of anything about this candidate.
        rows.append({"label": "Words per minute",
                     "text": "%.0f   (coaching guidance is usually 120-150)" % d["wpm"]})
    if d.get("pause_count"):
        rows.append({"label": "Pauses", "text": "%d of 200ms or longer" % d["pause_count"]})
        if d.get("mid_clause_share") is not None:
            rows.append({"label": "Where they fell", "note": PAUSE_NOTE,
                         "text": "%d of %d were mid-clause"
                                 % (d["mid_clause_pauses"], d["pause_count"])})
    elif d.get("spoken"):
        rows.append({"label": "Pauses", "text": "none of 200ms or longer"})
    return rows


def _delivery_block(d: dict) -> dict:
    return {"kind": "delivery", "figures": _figures(d), "rows": _figure_rows(d)}


def _delivery_section(d: dict) -> dict | None:
    """How the answers were said. Plain numbers in -- this module is on the text path and may
    not import what measured them.

    FR-36 is stated in the section rather than assumed: delivery is the measurement most
    contaminated by recognition error and most biased against non-native speakers, so a reader
    is told it sits beside the score instead of inside it.
    """
    if not d or not d.get("spoken"):
        return None
    measured = ("Measured on %d spoken answer%s, %.0fs of speech."
                % (d["spoken"], "" if d["spoken"] == 1 else "s", d.get("speaking_seconds") or 0))
    return _section("delivery", [_block("para", DELIVERY_INTRO), _block("para", measured),
                                 _delivery_block(d)])


def _delivery_lines(d: dict) -> list[str]:
    s = _delivery_section(d)
    return _lay_delivery(s) if s else []


def build(report: Report, questions_asked: int, questions_answered: int,
          observations=None, question_states=None, delivery=None,
          plan: dict | None = None) -> dict:
    """The report as sections of typed blocks, for each reader to lay out its own way.

    A block is a `para` of our prose, a numbered `lead`, an `item`, a `quote` of the
    candidate's words (marks included), the `rubric` counts or the `delivery` figures. Text is
    whole: wrapping belongs to whatever lays it out. `plan` is the session's snapshot: its
    field, `advice_priority` and advice.
    """
    plan = plan or {}
    totals = report.totals
    if not totals:
        # Delivery is explicitly not a score (FR-36), so it does not belong behind
        # this gate: an interview that was spoken aloud and scored nothing still has
        # something measured and true to say about how it was spoken.
        sections = [{"id": "summary", "heading": None,
                     "blocks": [_block("para", "No scored questions in this session.")]}]
        spoken = _delivery_section(delivery or {})
        return {"version": 1, "sections": sections + ([spoken] if spoken else []),
                "signoff": []}

    rate = {k: v[0] / v[1] for k, v in totals.items() if v[1]}
    weak = weak_order(totals, plan.get("advice_priority"))
    strong = sorted((k for k, r in rate.items() if r >= STRONG), key=lambda k: -rate[k])
    advice = advice_for(plan)

    sections = [_section("summary", [_block(
        "para", "%d questions, %d answered. Scored on %d of them; the opening and closing "
                "questions are not scored." % (questions_asked, questions_answered,
                                               len(report.scores)))])]

    if weak:
        blocks = []
        cited: set[str] = set()
        for i, name in enumerate(weak[:3], 1):
            problem, fix = advice.get(name, (name, ""))
            got, n = totals[name]
            blocks += [_block("lead", "%d. %s  (%d of %d answers)" % (i, problem, got, n)),
                       _block("para", fix)]
            miss = _missed(report, name, cited)
            if miss:
                cited.add(miss.question_id)
                blocks.append(_block("para", "Where it showed -- %s" % _clip(miss.question, 66)))
                if miss.answer:
                    blocks.append(_block("quote", "You said: \"%s\"" % _clip(miss.answer, 110)))
        sections.append(_section("change", blocks))

    if strong:
        blocks = []
        praised: set[str] = set()
        for name in strong[:3]:
            got, n = totals[name]
            blocks.append(_block("item", "On %d of %d answers, %s."
                                 % (got, n, PRAISE.get(name, name))))
            q = _shown(report, name, praised)
            if q:
                praised.add(q.question_id)
                blocks.append(_block("quote", "\"%s\"" % _clip(_quote(q, name), 96)))
        sections.append(_section("strengths", blocks))

    sections.append(_section("criteria", [{"kind": "rubric", "rows": [
        {"name": name, "met": got, "of": n, "description": CRITERIA[name][1]}
        for name, (got, n) in sorted(totals.items())]}]))

    spoken = _delivery_section(delivery or {})
    if spoken:
        sections.append(spoken)

    scored_ids = {q.question_id for q in report.scores}
    cut = [(q, CUT_SHORT[q.closed_because]) for q in (question_states or [])
           if q.closed_because in CUT_SHORT and q.question_id in scored_ids]
    if cut:
        sections.append(_section("cut_short", [_block("para", CUT_SHORT_INTRO)] + [
            _block("item", "[%s] %s" % (why, _clip(q.question, 60))) for q, why in cut[:5]]))

    thin = [q for q in report.scores if q.addresses_question != "yes"]
    if thin:
        sections.append(_section("revisit", [
            _block("item", "[%s] %s" % (q.addresses_question, _clip(q.question, 70)))
            for q in thin[:5]]))

    # The candidate's own questions. `asked_back` was persisted from the first version of the
    # closing handler and read by nobody, while the interviewer told them to their face it had
    # gone "in your report" -- a reviewed line promising what the runner did not do, which is
    # the SKIP_ACK defect. They are verbatim: these are the only words in the report that were
    # never scored, never extracted and never judged, so paraphrasing them would be the one
    # edit with nothing to gain.
    asked = [line for q in (question_states or []) for line in q.asked_back if line.strip()]
    if asked:
        # Whole, never clipped. A candidate often asks two things in one breath, and
        # truncating dropped the second one silently -- which is the same loss the section
        # was added to undo.
        blocks = [_block("para", ASKED_INTRO)]
        blocks += [_block("item", " ".join(line.split())) for line in asked[:6]]
        if len(asked) > 6:
            blocks.append(_block("para", "... and %d more in the session record."
                                 % (len(asked) - 6)))
        sections.append(_section("asked", blocks))

    design = _design_section(observations or [],
                             case=plan.get("field", fields.SOFTWARE) != fields.SOFTWARE)
    if design:
        sections.append(design)
    return {"version": 1, "sections": sections, "signoff": list(SIGNOFF)}


# The widths the intros were hand-wrapped at before the report had a structure, so a cached
# report and a new one print the same text.
_WIDE, _NARROW = 76, 72


def _wrap(text: str, indent: str, width: int) -> list[str]:
    return textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent,
                         break_on_hyphens=False, break_long_words=False)


def _lay_summary(s: dict) -> list[str]:
    head = [s["heading"], "=" * 60, ""] if s["heading"] else []
    return head + [b["text"] for b in s["blocks"]] + [""]


def _lay_change(s: dict) -> list[str]:
    out = [s["heading"], "-" * 60]
    prev = None
    for b in s["blocks"]:
        if b["kind"] == "lead":
            out += ["", b["text"]]
        elif b["kind"] == "para" and prev != "lead":
            out += ["", "   " + b["text"]]
        else:
            out.append("   " + b["text"])
        prev = b["kind"]
    return out + [""]


def _lay_list(s: dict) -> list[str]:
    out = [s["heading"], "-" * 60]
    for b in s["blocks"]:
        if b["kind"] == "para":
            out += _wrap(b["text"], "  ", _NARROW)
        elif b["kind"] == "item":
            out.append("  - " + b["text"])
        else:
            out.append("      " + b["text"])
    return out + [""]


def _lay_criteria(s: dict) -> list[str]:
    return ([s["heading"], "-" * 60]
            + ["  %-22s %2d/%-2d   %s" % (r["name"], r["met"], r["of"], r["description"])
               for b in s["blocks"] for r in b["rows"]]
            + [""])


def _figure_lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        out.append("  %-19s%s" % (r["label"], r["text"]))
        # One clause a line, as the note always printed.
        note = r.get("note", "").replace("; ", ";\n")
        out += ["  %19s%s" % ("", part) for part in note.split("\n") if part]
    return out


def _lay_delivery(s: dict) -> list[str]:
    out = [s["heading"], "-" * 60, ""]
    for b in s["blocks"]:
        out += (_wrap(b["text"], "  ", _WIDE) if b["kind"] == "para"
                else _figure_lines(b["rows"])) + [""]
    return out


def _lay_asked(s: dict) -> list[str]:
    out = [s["heading"], "-" * 60]
    for i, b in enumerate(s["blocks"]):
        if b["kind"] == "item":
            # `break_on_hyphens` off: the default split "per-region?" across two lines, and a
            # hyphenation break in the one section that exists to reproduce the candidate's
            # words exactly is the same defect as clipping, just quieter.
            wrapped = textwrap.wrap(b["text"], width=64, break_on_hyphens=False,
                                    break_long_words=False)
            out.append("  - %s" % (wrapped[0] if wrapped else ""))
            out.extend("    %s" % w for w in wrapped[1:])
        elif i == 0:
            out += _wrap(b["text"], "  ", _NARROW) + [""]
        else:
            out += [""] + _wrap(b["text"], "  ", _NARROW)
    return out + [""]


def _lay_design(s: dict) -> list[str]:
    out = [s["heading"], "-" * 60, ""]
    for i, b in enumerate(s["blocks"]):
        if i == 0:
            out += _wrap(b["text"], "", _WIDE) + [""]
        elif b["kind"] == "quote":
            out.append("      " + b["text"])
        elif b["kind"] == "item":
            out.append("  - " + b["text"])
        else:
            out.append("  " + b["text"])
    return out + [""]


_LAYOUT = {"summary": _lay_summary, "change": _lay_change, "strengths": _lay_list,
           "criteria": _lay_criteria, "delivery": _lay_delivery, "cut_short": _lay_list,
           "revisit": _lay_list, "asked": _lay_asked, "design": _lay_design}


def to_text(doc: dict) -> str:
    """The report as plain text for a terminal: a 60-column rule under every heading."""
    out = [line for s in doc["sections"] for line in _LAYOUT[s["id"]](s)]
    if not doc["signoff"]:
        return "\n".join(out).rstrip() + "\n"
    return "\n".join(out + list(doc["signoff"])) + "\n"


def render(report: Report, questions_asked: int, questions_answered: int,
           observations=None, question_states=None, delivery=None,
           plan: dict | None = None) -> str:
    return to_text(build(report, questions_asked, questions_answered,
                         observations, question_states, delivery, plan))


_RULE = re.compile(r"^[=-]{10,}$")
_QUOTED = re.compile(r"^(You said:\s*)?[“\"]")
_NUMBERED = re.compile(r"^\d+\.")
_IDS = {heading: sid for sid, heading in HEADINGS.items()} | {CASE_HEADING: "design"}


def _text_blocks(lines: list[str]) -> list[dict]:
    """Paragraphs back out of the 60-column wrapping. A blank line ends a block, a bullet or a
    number starts one, and a line opening on a quotation mark is the candidate's words."""
    out: list[dict] = []
    cur = None
    col = 0
    for raw in lines:
        line = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if not line:
            cur = None
        elif cur and cur["kind"] == "item" and indent == col:
            # A wrapped bullet's next line, whatever it opens with. History split a
            # candidate's question that wrapped onto "2." or a quotation mark.
            cur["text"] += " " + line
        elif _QUOTED.match(line):
            out.append(_block("quote", line))
            cur = None
        elif line.startswith("- "):
            cur = _block("item", line[2:])
            col = indent + 2
            out.append(cur)
        elif _NUMBERED.match(line):
            out.append(_block("lead", line))
            cur = None
        elif line.startswith("["):
            out.append(_block("item", line))
            cur = None
        elif cur:
            cur["text"] += " " + line
        else:
            cur = _block("para", line)
            out.append(cur)
    return out


def from_text(text: str, rubric: list[dict] | None = None,
              delivery: dict | None = None) -> dict:
    """The structure of a report cached before it had one, read back from its text.

    Read the way History and the exports read the text until now, so an old report looks the
    same once they read the structure. Nothing is rebuilt: the scoring behind a cached report
    took a model minutes, and the candidate has already read it. `rubric` and `delivery` are
    the same payload's data, which stand in for the lines that printed them.
    """
    lines = (text or "").split("\n")
    raw = [{"heading": None, "lines": []}]
    i = 0
    while i < len(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if lines[i].strip() and _RULE.match(nxt.strip()):
            raw.append({"heading": lines[i].strip(), "lines": []})
            i += 2
            continue
        raw[-1]["lines"].append(lines[i])
        i += 1

    # The sign-off is the run of unindented lines closing the last section.
    last = raw[-1]["lines"]
    end = len(last)
    while end and not last[end - 1].strip():
        end -= 1
    start = end
    while start and last[start - 1].strip() and not last[start - 1].startswith((" ", "\t")):
        start -= 1
    signoff: list[str] = []
    if start < end and (raw[-1]["heading"] or start):
        signoff = [line.strip() for line in last[start:end]]
        raw[-1]["lines"] = last[:start]

    rows = [{k: c.get(k) for k in ("name", "met", "of", "description")} for c in rubric or []]
    sections = []
    for s in raw:
        body = "\n".join(s["lines"])
        if not (s["heading"] or body.strip()):
            continue
        sid = _IDS.get(s["heading"]) if s["heading"] else "summary"
        # By heading, or by naming two criteria for a heading this does not know.
        if rows and (sid == "criteria"
                     or sum(1 for r in rows if r["name"] and r["name"] in body) >= 2):
            blocks = [{"kind": "rubric", "rows": rows}]
        else:
            blocks = _text_blocks(s["lines"])
        if sid == "delivery" and (delivery or {}).get("spoken"):
            at = next((n for n, b in enumerate(blocks)
                       if b["kind"] == "para" and b["text"].startswith("Measured on")), None)
            if at is not None:
                blocks = blocks[:at + 1] + [_delivery_block(delivery)]
        sections.append({"id": sid, "heading": s["heading"], "blocks": blocks})
    return {"version": 1, "sections": sections, "signoff": signoff, "from_text": True}


def structure_of(payload: dict) -> dict:
    """A report payload's structure, read from its text if it was cached without one."""
    return payload.get("structure") or from_text(
        payload.get("text") or "", payload.get("rubric"), payload.get("delivery"))
