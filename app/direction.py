"""Which way is this utterance pointing? Log section 9.15.

The runner has no notion of an utterance's ROLE, so a candidate's questions were extracted as
STAR evidence for a scored question, consumed its follow-up budget, and then reappeared in
the closing phase where they were captured into `ask` and advanced past unanswered. One
defect, three consequences: wrong evidence, a wasted budget, and a candidate whose questions
went nowhere.

The obvious test -- "does it contain a question mark" -- does not work, and the corpus says
so plainly. Of 21 distinct non-closing utterances containing one, most are answers:

    "Um, I guess maybe when we picked React over Vue?"        hedged answer
    "Of the codebase? Around eighty thousand lines of Go"     self-addressed, then answers
    "Maybe you'd keep a couple of smaller windows?"           design answer, generic "you"
    "Sorry, do you mean something that failed technically"    clarification, already handled

and the one that did the damage has no question mark at all:

    "Two. First, what the on-call rota actually looks like here - not the policy, the
     reality of how often someone gets woken. And second, the ledger work"

So the signal is not interrogative form. What separates the real ones is that they ask about
the HIRING CONTEXT -- this team, this role, what the first months look like, who would review
my code -- rather than about the candidate's own past or the design task in front of them.

That is a narrower and more concrete test than "is this a question", which is what section
7.36 asks for. Whether it actually separates is measured by `tools/tier2_direction.py`, and
section 9.6's rule applies: if it fires on both classes it does not ship, however reasonable
it sounds.
"""

from __future__ import annotations

import re

from . import intent

_SENTENCE = re.compile(r"[^.!?]+[.!?]?")

# Asking about the place they would be working. Present or future, and about the interviewer's
# side of the table rather than the candidate's history.
HIRING_CONTEXT = re.compile(
    r"\b(?:"
    # `here` only in a work collocation. Bare, it collides with "stop here" (9.16).
    r"(?:work|working|works|look|looks|looked|like|regularly|do it|done|things) here|"
    r"this team|your team|the team|your company|the company|"
    r"the role|this role|the job|joining|join|onboard\w*|"
    r"first (?:three|3|six|6|few) months|first month|day one|"
    r"would i be|will i be|i'd be|id be|i would be|am i going to be|"
    r"someone at my level|my code|my work|"
    r"who else|anyone i|someone i'd|someone id"
    r")\b", re.I)

# The candidate flagging that they are about to ask, which is how the un-punctuated ones
# announce themselves: "Two. First, ..." / "One -- who else could ...".
ENUMERATED = re.compile(
    r"^\s*(?:i have\s+)?(?:a couple|one|two|three|1|2|3)\b[\s.,:;)–—-]*"
    r"(?:questions?|things?)?[\s.,:;)–—-]*", re.I)

# Their own past, or the hypothetical they were handed. Both are answers however they are
# punctuated, and both are common carriers of a stray question mark. The auxiliary group is
# not optional detail: without it "I've spent four years on systems where correctness
# matters" read as narrative-free and was flagged as an enquiry.
NARRATIVE = re.compile(
    r"\b(?:i|we)\s*(?:'|’)?\s*(?:ve|d|m|have|had|was|were|am|are)?\s*"
    r"(?:did|was|were|had|built|wrote|ran|used|shipped|chose|picked|"
    r"decided|made|took|found|got|spent|started|moved|added|fixed|worked|been|"
    r"haven'?t|hadn'?t|didn'?t|don'?t have)\b", re.I)

# An ordinal opening the enumerated form: "Two. FIRST, what the on-call rota ...".
ORDINAL = re.compile(r"^\s*(?:first|second|third|1st|2nd|3rd|one|two)\b[\s.,:;)–—-]*",
                     re.I)
# An actual interrogative. Required when nothing in the utterance is punctuated as a
# question, because the enumerated opener alone also fits "Two things. I've spent four
# years ...", which is an answer to what drew them to the role.
WH_ASK = re.compile(r"^(?:what|who|whose|how|why|when|where|which|whether|"
                    r"is there|are there|would|will|do you|does|can you|could you)\b", re.I)

# Asking what the QUESTION means. A different role with its own handler already.
CLARIFYING = re.compile(
    r"\b(?:do you mean|what do you mean|which do you mean|as in|what counts as|"
    r"say that again|could you repeat|do you want me to|shall i|should i|"
    r"can we move on|keep going on)\b", re.I)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text or "") if s.strip()]


def answer_part(utterance: str) -> str:
    """The answer that comes BEFORE a trailing question, if there is one.

    A candidate answers and then asks, in one breath. Found live: "I've probably picked up
    some bad habits and I wouldn't know. Nobody's ever told me my code is wrong, they just
    merge it. And is there someone who'd be reviewing my code regularly here?" -- routed
    whole to the question handler, so the two sentences of real evidence were discarded.

    Empty when the utterance opens on a question, and empty when nothing is punctuated as
    one: an announced question ("Two. First, what the on-call rota ...") has no answer in
    front of it, and returning the whole utterance there would score a question as an answer.
    """
    parts = sentences(utterance)
    if not any(s.rstrip().endswith("?") for s in parts):
        return ""
    kept: list[str] = []
    for s in parts:
        if s.rstrip().endswith("?"):
            break
        kept.append(s)
    return " ".join(kept)


def is_candidate_question(utterance: str) -> bool:
    """Is this the candidate asking the INTERVIEWER about the role, rather than answering?

    Deliberately conservative. A false positive deflects a genuine answer with "let me come
    back to that", which is the worse error: it discards evidence and confuses the candidate,
    where a false negative only reproduces today's behaviour.
    """
    text = utterance or ""
    if CLARIFYING.search(text):
        return False
    # A request to stop is a control utterance, not an enquiry about the job, and it outranks
    # this check. Found live: "do we have to stop here?" matched on the bare `here` in
    # HIRING_CONTEXT and was answered "Good question. Let's finish this one first." -- the
    # candidate was not wrongly stopped, but they were talked over, which is its own harm.
    if intent.asked_to_stop(text):
        return False

    parts = sentences(text)
    if not parts:
        return False

    asking = [s for s in parts if s.rstrip().endswith("?")]
    if asking:
        # The hiring-context marker has to sit in the ASKING part, not anywhere in the
        # utterance. An answer that mentions the team in passing and ends on a hedged
        # question mark is still an answer.
        scope = " ".join(asking)
    else:
        # Nothing is punctuated as a question. The only way in is the announced form, and it
        # has to be followed by a real interrogative -- "Two. First, what the on-call rota
        # actually looks like here" is one, "Two things. I've spent four years" is not.
        m = ENUMERATED.match(text)
        if not m:
            return False
        scope = ORDINAL.sub("", text[m.end():], count=1).lstrip()
        if not WH_ASK.match(scope):
            return False

    if not HIRING_CONTEXT.search(scope):
        return False

    # Narrative in the asking part means they are recounting, not enquiring.
    return not NARRATIVE.search(scope)
