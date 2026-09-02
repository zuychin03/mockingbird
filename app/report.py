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

Plain text by design. It is read in a terminal today and rendered elsewhere later, and the
structure has to survive both.
"""

from __future__ import annotations

import textwrap

from . import guards
from .score import CRITERIA, Report

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


def design_note(observations) -> list[str]:
    """A description of the design answer. No score, no contribution to any total."""
    d = next((o for o in observations if o.shape == "design" and o.text.strip()), None)
    if d is None:
        return []
    have = [(k, label) for k, label in DESIGN_PARTS if getattr(d, k)]
    missing = [label for k, label in DESIGN_PARTS if not getattr(d, k)]
    out = ["ON THE DESIGN QUESTION", "-" * 60, ""]
    out.append("Not scored -- a hypothetical has no outcome to check an answer against, and")
    out.append("the parts below are reported rather than marked. Read them as a checklist of")
    out.append("what a design answer usually covers.")
    out.append("")
    # "covered" would be a verdict, and a verdict is the thing that inverted the ranking.
    # These lines say what was FOUND and let the candidate judge it -- which they can, since
    # the words are their own.
    for k, label in have:
        out.append("  You %s:" % label)
        out.append("      \"%s\"" % _clip(getattr(d, k), 88))
    for label in missing:
        out.append("  Nothing in the answer %s." % label)
    out.append("")
    return out


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
}


def render(report: Report, questions_asked: int, questions_answered: int,
           observations=None, question_states=None) -> str:
    totals = report.totals
    if not totals:
        return "No scored questions in this session.\n"

    rate = {k: v[0] / v[1] for k, v in totals.items() if v[1]}
    weak = sorted((k for k, r in rate.items() if r <= WEAK), key=lambda k: rate[k])
    strong = sorted((k for k, r in rate.items() if r >= STRONG), key=lambda k: -rate[k])

    out: list[str] = []
    out.append("HOW THAT WENT")
    out.append("=" * 60)
    out.append("")
    out.append("%d questions, %d answered. Scored on %d of them; the opening and closing "
               "questions are not scored." % (questions_asked, questions_answered,
                                              len(report.scores)))
    out.append("")

    if weak:
        out.append("WHAT WOULD CHANGE THE MOST")
        out.append("-" * 60)
        cited: set[str] = set()
        for i, name in enumerate(weak[:3], 1):
            problem, fix = ADVICE.get(name, (name, ""))
            got, n = totals[name]
            out.append("")
            out.append("%d. %s  (%d of %d answers)" % (i, problem, got, n))
            out.append("   %s" % fix)
            miss = _missed(report, name, cited)
            if miss:
                cited.add(miss.question_id)
            if miss:
                out.append("")
                out.append("   Where it showed -- %s" % _clip(miss.question, 66))
                if miss.answer:
                    out.append("   You said: \"%s\"" % _clip(miss.answer, 110))
        out.append("")

    if strong:
        out.append("WHAT YOU ALREADY DO WELL")
        out.append("-" * 60)
        praised: set[str] = set()
        for name in strong[:3]:
            got, n = totals[name]
            out.append("  - On %d of %d answers, %s." % (got, n, PRAISE.get(name, name)))
            q = _shown(report, name, praised)
            if q:
                praised.add(q.question_id)
                out.append("      \"%s\"" % _clip(_quote(q, name), 96))
        out.append("")

    out.append("EVERY CRITERION")
    out.append("-" * 60)
    for name in sorted(totals):
        got, n = totals[name]
        out.append("  %-22s %2d/%-2d   %s" % (name, got, n, CRITERIA[name][1]))
    out.append("")

    scored_ids = {q.question_id for q in report.scores}
    cut = [(q, CUT_SHORT[q.closed_because]) for q in (question_states or [])
           if q.closed_because in CUT_SHORT and q.question_id in scored_ids]
    if cut:
        out.append("SCORED, BUT CUT SHORT")
        out.append("-" * 60)
        out.append("  These questions ended before the conversation was finished with them,")
        out.append("  so read their scores as weaker evidence than the rest.")
        for q, why in cut[:5]:
            out.append("  - [%s] %s" % (why, _clip(q.question, 60)))
        out.append("")

    thin = [q for q in report.scores if q.addresses_question != "yes"]
    if thin:
        out.append("QUESTIONS WORTH REVISITING ON YOUR OWN")
        out.append("-" * 60)
        for q in thin[:5]:
            out.append("  [%s] %s" % (q.addresses_question, _clip(q.question, 70)))
        out.append("")

    # The candidate's own questions. `asked_back` was persisted from the first version of the
    # closing handler and read by nobody, while the interviewer told them to their face it had
    # gone "in your report" -- a reviewed line promising what the runner did not do, which is
    # the SKIP_ACK defect. They are verbatim: these are the only words in the report that were
    # never scored, never extracted and never judged, so paraphrasing them would be the one
    # edit with nothing to gain.
    asked = [line for q in (question_states or []) for line in q.asked_back if line.strip()]
    if asked:
        out.append("WHAT YOU ASKED")
        out.append("-" * 60)
        out.append("  These went unanswered on purpose. There is no employer behind this")
        out.append("  interview, and inventing an answer about a real workplace is the one")
        out.append("  thing a practice interviewer must not do. They are recorded here so")
        out.append("  you can put them to the real one.")
        out.append("")
        # Wrapped, never clipped. A candidate often asks two things in one breath, and
        # truncating dropped the second one silently -- which is the same loss the section
        # was added to undo.
        for line in asked[:6]:
            # `break_on_hyphens` off: the default split "per-region?" across two lines, and
            # a hyphenation break in the one section that exists to reproduce the candidate's
            # words exactly is the same defect as clipping, just quieter.
            wrapped = textwrap.wrap(" ".join(line.split()), width=64,
                                    break_on_hyphens=False, break_long_words=False)
            out.append("  - %s" % (wrapped[0] if wrapped else ""))
            out.extend("    %s" % w for w in wrapped[1:])
        if len(asked) > 6:
            out.append("  ... and %d more in the session record." % (len(asked) - 6))
        out.append("")

    out.extend(design_note(observations or []))

    # "Nothing here is an impression" was not true, and it is the kind of untrue that 9.5
    # was written about. The quotes are the candidate's own words and the arithmetic is
    # checkable, but a model chose which words counted as evidence, and saying otherwise
    # claims a guarantee the pipeline does not have.
    out.append("Every quote above is your own words, and the counting on top of them is "
               "arithmetic you can check.")
    out.append("Which words counted as evidence was decided by a model, so that part is a "
               "reading, not a measurement.")
    return "\n".join(out) + "\n"
