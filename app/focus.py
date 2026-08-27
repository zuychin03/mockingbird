"""Which KIND of follow-up to ask next. Log section 8.18.

Measured over 2,442 turns: a question gets ~2.2 follow-ups but only ~1.6 distinct requests,
and the collapse is at probe 2 with no cliff after it. The model uses 11.4 distinct request
types across a session and re-uses one already spent on the current question 64% of the time.
The variety is there; nothing asks for it.

So this module asks. It is the same move as section 7.10 -- derive it, never ask the model
for it -- applied one level up, from the WORDING of a probe to its INTENT. The model still
writes the sentence; it no longer chooses what the sentence is for.

Three sources, in order, all deterministic:

  signals   what the last answer is missing, from app/depth_signals.py. A figure with no
            account of how it was established asks for MEASURE; credit to "we" with the
            candidate's own part unstated asks for ROLE.
  criteria  the phase's own `rubric_criteria`, which is what the session will be scored on.
            Asking about what is scored is the whole point of the interview.
  ladder    a fixed fallback order, so there is always an unused type to reach for.

Nothing here calls a model, so it costs no latency and is decidable in a test.
"""

from __future__ import annotations

import re

from .depth_signals import signals

# The closed set. Each is a distinct thing an interviewer wants, phrased as the instruction
# that goes into the prompt.
FOCUS = {
    "STEPS": "what they actually did, step by step",
    "REASON": "why they chose that, and what they weighed against it",
    "MEASURE": "how they know -- the numbers, and how they were established",
    "OUTCOME": "what happened in the end, and how they knew it worked",
    "ROLE": "which parts were theirs personally, as opposed to the team's",
    "CHALLENGE": "the hardest part, or what went wrong along the way",
    "ALTERNATIVE": "what else they considered, or would do differently now",
    "LESSON": "what they took from it that changed how they work",
    "CONTEXT": "the situation around it -- scale, constraints, who was involved",
    "DURATION": "how long it took, and how much of that was which part",
}

# Signals map to the request that answers them. Ordered: the first firing signal wins.
FROM_SIGNAL = [
    ("unverified", "MEASURE"),
    ("attribution", "ROLE"),
    ("asserted", "OUTCOME"),
    ("vague", "MEASURE"),
    ("skipped", "STEPS"),
]

# `rubric_criteria` names what the answer is scored on, so an unmet criterion is a question
# worth asking. Criteria with no natural probe (first_person is covered by ROLE) are mapped.
FROM_CRITERION = {
    "sets_context": "CONTEXT",
    "describes_action": "STEPS",
    "states_outcome": "OUTCOME",
    "first_person": "ROLE",
    "specific_detail": "MEASURE",
    "measurement_stated": "MEASURE",
}

# Reached only when signals and criteria are exhausted. Ordered by what an interviewer
# usually wants next rather than alphabetically.
LADDER = ["STEPS", "REASON", "OUTCOME", "MEASURE", "CHALLENGE", "ROLE",
          "ALTERNATIVE", "LESSON", "CONTEXT", "DURATION"]

# Detection lexicon for validating what came back. Stem-based, but NOT on single common words
# that appear incidentally: bare "instead" and "process" made "Why did you choose to approach
# this colleague ... instead of through a formal review process?" classify as ALTERNATIVE and
# STEPS, so a REASON question already asked on that question was accepted as a fresh request
# and spoken twice (log 9.7). Generosity was the right trade when substituting meant one canned
# sentence per focus; with variants it is not.
_PATTERNS = {
    "MEASURE": r"measur|metric|number|how (much|many|fast|long)|quantif|benchmark|profil|"
               r"how do you know|how did you know (?:that|whether|if)|what data|p9\d|"
               r"percentile|baseline",
    "ROLE": r"\byou personally\b|your (own )?(part|role|contribution)|which parts were you|"
            r"what did you do|were you the",
    "OUTCOME": r"outcome|what happened|end (up|result)|how did (it|that) (go|land|turn out)|"
               r"result|in the end|was it successful|what (?:was|is) the impact",
    "STEPS": r"step|walk (me )?through|how did you (do|approach|go about|handle)|"
             r"what did you do (?:first|next)|what specific changes (?:did|would) you make|"
             r"sequence",
    "REASON": r"\bwhy\b|reason|what made you|rationale|weigh|trade.?off|instead of|"
              r"what led you",
    "CHALLENGE": r"hard(est)?|difficult|challeng|went wrong|problem|obstacle|struggl|"
                 r"tricky|blocker|what (?:happens|would happen) (?:if|when)|"
                 r"how (?:would|do) you handle .*(?:unavailable|down|outage)|"
                 r"what breaks first|how (?:does|would) .* behave (?:if|when)|failure mode",
    "ALTERNATIVE": r"alternativ|what else|other option|differently|considered|"
                   r"would you change",
    "LESSON": r"learn|lesson|take(away)?|changed how|since then|next time|do differently now",
    "CONTEXT": r"context|situation|scale|how (big|large|many people)|who else|team size|"
               r"background|constraint",
    "DURATION": r"how long|duration|timeline|how much time|weeks|months|took you",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in _PATTERNS.items()}

# Spoken when the model returns a line that is not the focus that was asked for. Plain and
# short by design -- these exist so a mis-targeted turn still asks something useful.
#
# Several per focus, because one fixed string per focus is spoken verbatim every time that
# focus fires, and CONTEXT fired four times in one session: "What was the scale of that?" was
# asked about a codebase, a queue, and a one-on-one conversation, where the candidate answered
# "I'm not sure scale applies to a coffee chat" (log 9.7). The repetition guard never saw any
# of it -- substitution happens after the guards run. `template()` below is what stops it.
TEMPLATE = {
    "STEPS": ("What did you actually do, step by step?",
              "Walk me through what you did.",
              "What was the first thing you did?"),
    "REASON": ("Why that one?",
               "What made you go that way?",
               "What was the thinking behind that?"),
    "MEASURE": ("How did you measure that?",
                "How did you know it worked?",
                "What were you looking at to tell?"),
    "OUTCOME": ("What happened in the end?",
                "How did that land?",
                "Where did it end up?"),
    "ROLE": ("Which parts of that were yours?",
             "What was your own part in it?",
             "What did you do yourself there?"),
    "CHALLENGE": ("What was the hardest part?",
                  "What gave you the most trouble?",
                  "Where did that get difficult?"),
    "ALTERNATIVE": ("What else did you consider?",
                    "What did you rule out?",
                    "Was there another way to do it?"),
    "LESSON": ("What did you take from it?",
               "What would you do differently?",
               "What stayed with you from that?"),
    "CONTEXT": ("What was the scale of that?",
                "What was the setup around it?",
                "Who else was involved?"),
    "DURATION": ("How long did that take?",
                 "Over what sort of timeframe?",
                 "How long were you on it?"),
}


def template(focus: str, spoken: set[str] | None = None) -> str:
    """A line for this focus that has not been spoken in this SESSION yet.

    Scoped to the session, not the question: all four repeats measured in 9.7 were on
    different questions, so a per-question check could not have caught any of them. Falls back
    to the first variant once they are exhausted, which is honest -- three usable phrasings is
    what exists, and inventing a fourth here would put an unreviewed line in the interviewer's
    mouth.
    """
    variants = TEMPLATE[focus]
    spoken = spoken or set()
    return next((v for v in variants if v not in spoken), variants[0])


# A candidate saying they have nothing to say. There is no gap in an answer that is not
# there, so asking a well-chosen question about it is worse than not asking: measured live,
# "I've not really shipped anything big enough to go wrong yet" was answered with "How did
# you measure that?" (log 8.22).
_NO_CONTENT = re.compile(
    r"\b(?:"
    r"nothing (?:comes to mind|springs to mind|really)"
    r"|(?:can'?t|cannot|could not|couldn'?t) (?:really )?(?:think of|recall|remember)"
    r"|(?:i )?(?:have ?n'?t|had ?n'?t|has ?n'?t|have not|had not|never|not really|don'?t think"
    r" i(?:'ve| have)?) ?(?:\w+ ){0,3}?(?:done|had|got|shipped|built|worked|been|encountered|"
    r"come across|dealt with|run into|hit)"
    r"|no experience"
    r"|(?:that|it)'?s not (?:been )?(?:my|our) (?:work|area|job)"
    r"|not (?:my|our) (?:area|job|work)"
    r")\b", re.I)


def is_contentless(utterance: str) -> bool:
    """Did the candidate say they have nothing to offer here?

    Deliberately narrow: it looks for the candidate SAYING SO, not for a short answer. A
    two-word answer can be a real one, and treating brevity as emptiness would suppress
    probing exactly where probing is most useful.
    """
    return bool(_NO_CONTENT.search(utterance or ""))


def classify(say: str) -> set[str]:
    """Which requests does this line make? A line may legitimately make more than one."""
    return {k for k, rx in _COMPILED.items() if rx.search(say or "")}


# Warmup and closing declare no `rubric_criteria`: nothing about them is scored, so there are
# no gaps for the signals to find. Running them anyway made the agent answer "I'm a platform
# engineer, seven years" with "How do you know? What did you measure?" -- the figure is real,
# the claim is not (log 8.19). These phases get a plain conversational ladder instead.
UNSCORED_LADDER = ["CONTEXT", "ROLE", "REASON", "STEPS", "OUTCOME"]


def next_focus(utterance: str, used: set[str], criteria: list[str] | None = None,
               ladder: list[str] | None = None) -> str | None:
    """The request type to ask for next. Never returns one already used on this question.

    `ladder` comes from the phase (`focus_ladder` in the plan), because a generic order does
    not fit every kind of question: a motivation question has no scale and a hypothetical
    design has no team, so CONTEXT and ROLE are nonsense on both (log 8.20). It falls through
    to the global ladder rather than returning None -- there are ten types and no question can
    spend them all, so there is always one left.
    """
    # None means "do not steer this turn": there is nothing in the answer to ask about, and
    # the right move is to put the question a different way, which is `reask`'s job.
    if is_contentless(utterance):
        return None
    criteria = criteria or []
    ladder = ladder or (UNSCORED_LADDER if not criteria else [])
    if criteria:
        for name, focus in FROM_SIGNAL:
            if signals(utterance).get(name) and focus not in used:
                return focus
        for c in criteria:
            focus = FROM_CRITERION.get(c)
            if focus and focus not in used:
                return focus
    for focus in list(ladder) + LADDER:
        if focus not in used:
            return focus
    return "STEPS"


# A design question is a hypothetical, so it has no outcome, no team and no duration, and the
# ladder above mostly does not apply. What it does have is a part that is missing more often
# than any other: measured live, a fluent design answer named an approach, an alternative and
# a tradeoff, named nothing that could go wrong, and drew ZERO probes out of a budget of three
# (log 9.7). `ok` asks whether the reply answers the question, not whether the answer has a
# hole in it, and a long fluent answer reads as complete either way.
#
# Vocabulary, not judgement: this asks whether the candidate USED failure language, which is a
# fact about text. Whether the failure they named is the right one is exactly the judgement
# 9.6 measured as unscoreable, and nothing here attempts it.
_FAILURE = re.compile(
    r"\b(?:fail(?:s|ed|ing|ure)?|break(?:s|ing)?|broke|broken|crash(?:es|ed)?"
    r"|outage|unavailable|goes? down|went down|down(?:time)?|degrade[sd]?"
    r"|drift(?:s|ed|ing)?|race|contention|deadlock|starv(?:e|es|ed|ation)"
    r"|stale|inconsistent|partition(?:ed|s)?|split.brain|timeout|times? out"
    r"|overload(?:ed)?|thundering herd|hot ?key|lose|loses|lost|drop(?:s|ped)?"
    r"|retry storm|back ?pressure|cascad(?:e|es|ing)|corrupt(?:ed|ion)?)\b", re.I)


def design_gap(answers: list[str]) -> str | None:
    """Which design part is missing and worth one deterministic follow-up? None if none is.

    Only failure. The other three parts (approach, alternative, tradeoff) are either
    volunteered or are a matter of how much the candidate chose to say; a missing failure
    mode is the one gap where an interviewer would reliably ask, and where the answer
    changes what the candidate learns about their own design.

    Returning None when the language is already there is the point, not a safeguard: asking
    what breaks after they have said what breaks is the redundancy that 9.7 measured on five
    of twenty-three lines.
    """
    return None if _FAILURE.search(" ".join(answers)) else "FAILURE"


DESIGN_FOLLOW_UP = "What breaks first when this is under real load?"


def instruction(focus: str) -> str:
    """The one line appended to the system prompt for this turn."""
    return ("\n\nFor THIS turn, if you probe or reask, ask about %s. Ask only that, in one "
            "short question." % FOCUS[focus])
