"""Observation extraction. Plan section 6, log sections 7.10, 7.33, 8.23.

Stage 2's job is to say how the candidate did. This module does the first half: turn a
question's answers into OBSERVATIONS. Nothing here judges anything -- `score.py` does that,
deterministically, from what this produces.

The split is not stylistic. Section 7.10 measured this model at 29/30 on concrete sub-facts
(has_situation / has_action / has_result) and 6/10 on the summary judgement built from them;
deriving the judgement from the model's own sub-facts scored 10/10 on both models tested. So
the rule for everything below: **ask for text the candidate actually said, never for an
opinion about it.**

Three of the six rubric criteria need no model at all -- `first_person`, `specific_detail`
and `measurement_stated` are regex over the answer (8.23). The model is asked only for the
three it is good at, and it answers by QUOTING rather than by deciding:

    situation   the sentence where they set the scene
    action      the sentence where they say what THEY did
    result      the sentence where they say how it turned out

One sentence may serve more than one field, and saying so is worth 43 points of `situation`
recall (19.8% to 65.3% over 101 first-answers). Candidates set the scene and say what they did
in a single sentence constantly -- "I added a status history table to a live support system
that previously stored only the current status" -- and while the fields were exclusive,
`action` took those and `situation` came back empty. Live that starved the `seen` set, so the
selector kept asking for context the candidate had already given (log: the repeated scale
question). Rewording `situation` itself was measured and did nothing; exclusivity was the
whole defect.

Each quote is then checked against the answer text and dropped if it is not there. Section
7.33's depth-probe contract failed on its own terms, but its verbatim-quote guard produced
**zero hallucinations**, and that is the part worth keeping.

The report path runs this after the session ends. 1c.5's pacing also runs it DURING the
session, one answer at a time, so the runner can tell whether an answer added a new part --
`Runner._settle` awaits it off the decision path and its result reaches the focus selector as
`seen`. Nothing it produces may reach the candidate mid-interview (12.6.1); only the decision
of what to ask next depends on it.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .depth_signals import FIRST_SG, MEASURED, NUMBER
from .provider import Provider

SYSTEM = """You are reading one answer from a job interview and quoting parts of it back.

You do NOT judge the answer. You only find and copy text.

Return three fields. Each is a VERBATIM quote from the candidate's answer, or an empty string
if that part is not there:

- "situation" : where they set the scene -- the system, the team, the problem, the constraint.
- "action"    : where they say what was DONE. Prefer a sentence where they say what THEY did.
- "result"    : where they say how it turned out -- what changed, what the effect was.

Rules:
- Copy the text exactly as they said it. Do not paraphrase, tidy or shorten.
- One sentence per field. The SAME sentence may supply more than one field -- if they set the
  scene and say what they did in one sentence, quote it for both.
- If a part is genuinely absent, return an empty string for it.
- An empty string is a correct answer. Do not invent a quote to fill a field."""

SCHEMA = {
    "type": "object",
    "properties": {"situation": {"type": "string"},
                   "action": {"type": "string"},
                   "result": {"type": "string"}},
    "required": ["situation", "action", "result"],
    "additionalProperties": False,
}

# A hypothetical design answer has no situation, action or result, and forcing one through
# that shape produced no observations at all -- the one question that asks how somebody THINKS
# generated no feedback. The config anticipated this: `design.scored_false_reason` said to
# revisit "when a concrete proxy for structure has been measured" (log 9.6).
#
# The parts below are the same KIND of thing as S/A/R -- text the candidate said, quoted, not
# judged. Section 7.10 warned that `mentions_tradeoff` asked as a judgement scores 7/10 and
# should be dropped; asked as a QUOTE it is a different question, and 9.6 measures it.
DESIGN_SYSTEM = """You are reading a candidate's answer to a hypothetical design question and
quoting parts of it back.

You do NOT judge the answer. You only find and copy text.

Return four fields. Each is a VERBATIM quote from the answer, or an empty string if that part
is not there:

- "approach"     : where they name what they would actually build -- the mechanism, the
                   component, the algorithm.
- "alternative"  : where they mention a DIFFERENT approach they considered or rejected.
- "tradeoff"     : where they name a cost, limit or downside of an approach.
- "failure_mode" : where they say what would go wrong, break, or happen under failure.

Rules:
- Copy the text exactly as they said it. Do not paraphrase, tidy or shorten.
- One sentence per field. If a part is genuinely absent, return an empty string for it.
- An empty string is a correct answer. "I don't know how you'd stop that" names a failure mode
  and no fix -- quote it under "failure_mode" anyway; deciding whether it is a good answer is
  not your job."""

DESIGN_SCHEMA = {
    "type": "object",
    "properties": {"approach": {"type": "string"},
                   "alternative": {"type": "string"},
                   "tradeoff": {"type": "string"},
                   "failure_mode": {"type": "string"}},
    "required": ["approach", "alternative", "tradeoff", "failure_mode"],
    "additionalProperties": False,
}

STAR_PARTS = ("situation", "action", "result")
DESIGN_PARTS = ("approach", "alternative", "tradeoff", "failure_mode")

# Share of the quote that must be found in the answer. Not 1.0: the model re-punctuates and
# tidies as it copies, and rejecting a quote for that discards real evidence -- which makes
# the report understate the candidate, the worst direction for a coach to be wrong in.
QUOTE_MATCH = 0.85
# Below this a quote is a fragment, not evidence, and coverage stops discriminating.
MIN_QUOTE_WORDS = 4


@dataclass
class Observation:
    """What one question's answers contain. Every field is text or a fact about text."""

    question_id: str
    question: str
    answers: list[str] = field(default_factory=list)
    situation: str = ""
    action: str = ""
    result: str = ""
    approach: str = ""
    alternative: str = ""
    tradeoff: str = ""
    failure_mode: str = ""
    shape: str = "star"
    first_person: bool = False
    specific_detail: bool = False
    measurement_stated: bool = False
    dropped_quotes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.answers)

    @property
    def addresses_question(self) -> str:
        """Derived, never asked. Section 7.10: asked directly 6/10, derived 10/10.

        A design answer is complete when it names something to build and something that could
        go wrong with it; the middle two parts are what separate a good answer from a
        sufficient one, so they raise it to "yes" rather than gating it.
        """
        if self.shape == "design":
            core = bool(self.approach) and bool(self.failure_mode)
            extra = bool(self.alternative) or bool(self.tradeoff)
            if core and extra:
                return "yes"
            return "no" if not (self.approach or self.failure_mode) else "partial"
        have = sum(bool(x) for x in (self.situation, self.action, self.result))
        return {3: "yes", 0: "no"}.get(have, "partial")


def _grounded(quote: str, answer: str) -> bool:
    """Is this quote actually in what they said?

    Section 7.33's verbatim-quote guard: measured zero hallucinations. Cheap, and it makes an
    invented quote impossible rather than unlikely.

    Matched as COVERAGE of the quote by the answer, not as similarity to any one sentence.
    The first version compared against individual sentences and dropped 4 of 5 quotes it
    should have kept: the model quotes across a sentence boundary, and it tidies as it copies
    -- "self-serve" for "self-service", "claim_ lines" for "claim_lines". Coverage survives
    both, and a fabricated quote still fails it, because invented text has no long matching
    blocks anywhere in the answer (log 8.23).
    """
    q = " ".join((quote or "").lower().split())
    # A very short string passes coverage trivially -- every answer contains "x" somewhere --
    # and a three-word fragment is not evidence a criterion was met either way.
    if len(q.split()) < MIN_QUOTE_WORDS:
        return False
    a = " ".join(answer.lower().split())
    if q in a:
        return True
    m = difflib.SequenceMatcher(None, q, a, autojunk=False)
    return sum(b.size for b in m.get_matching_blocks()) / len(q) >= QUOTE_MATCH


def deterministic(text: str) -> dict[str, bool]:
    """The three criteria that need no model. Regex over what they said."""
    return {"first_person": bool(FIRST_SG.search(text)),
            "specific_detail": bool(NUMBER.search(text)),
            "measurement_stated": bool(MEASURED.search(text))}


async def observe(provider: Provider, question_id: str, question: str,
                  answers: list[str], shape: str = "star") -> Observation:
    """One question in, one Observation out. No judgement, no scores.

    `shape` comes from the phase (`observation_shape` in the plan). It selects which parts are
    worth looking for, not how hard to look: both shapes quote, and both are grounded the same
    way.
    """
    obs = Observation(question_id=question_id, question=question, answers=list(answers),
                      shape=shape)
    joined = obs.text
    for k, v in deterministic(joined).items():
        setattr(obs, k, v)
    if not joined.strip():
        return obs

    design = shape == "design"
    out = await provider.complete(
        DESIGN_SYSTEM if design else SYSTEM,
        "QUESTION: %s\n\nCANDIDATE: %s" % (question, joined),
        schema=DESIGN_SCHEMA if design else SCHEMA, max_tokens=400)
    raw = out.json() or {}
    for part in (DESIGN_PARTS if design else STAR_PARTS):
        quote = (raw.get(part) or "").strip()
        if not quote:
            continue
        if _grounded(quote, joined):
            setattr(obs, part, quote)
        else:
            obs.dropped_quotes.append("%s: %s" % (part, quote))
    return obs


# ------------------------------------------------------------------ caching (log 9.7)
# The scoring is arithmetic and deterministic; the extraction feeding it is a model call and
# is not. Re-scoring ONE transcript five times gave states_outcome 7,7,8,8,9 of 10 at
# temperature 0.0 with a fixed seed -- the llama.cpp/GPU path, which no prompt change reaches.
# The candidate-visible effect was worse than a moving number: QUESTIONS WORTH REVISITING is
# derived from `addresses_question`, so the list of questions changed between two runs of the
# same interview.
#
# Extracting once and keeping the result makes a re-score repeatable, which is what
# `stage2_report.py` was built to do and could not. The fingerprint is the whole point: it
# covers the prompts and the grounding thresholds, so changing the extractor invalidates the
# cache rather than silently serving results from the old one -- a stale cache would turn a
# real improvement into a no-op and look exactly like the change not working.
CACHE_VERSION = 1


def fingerprint(items: list[tuple]) -> str:
    """What the observations depend on. Any change to it must invalidate the cache."""
    h = hashlib.sha256()
    h.update(repr((CACHE_VERSION, QUOTE_MATCH, MIN_QUOTE_WORDS)).encode())
    h.update(SYSTEM.encode())
    h.update(DESIGN_SYSTEM.encode())
    for qid, question, answers, shape in items:
        h.update(repr((qid, question, list(answers), shape)).encode())
    return h.hexdigest()[:16]


_FIELDS = ("question_id", "question", "answers", "situation", "action", "result",
           "approach", "alternative", "tradeoff", "failure_mode", "shape",
           "first_person", "specific_detail", "measurement_stated", "dropped_quotes")


async def observe_all(provider: Provider, items: list[tuple], cache: Path | None = None,
                      re_extract: bool = False) -> tuple[list[Observation], bool]:
    """Observe every question, reusing a cached extraction when the inputs are unchanged.

    Returns the observations and whether they came from cache, because a caller reporting
    scores should be able to say which -- a number from a fresh extraction carries the
    run-to-run band, and one from cache does not.
    """
    key = fingerprint(items)
    if cache and cache.exists() and not re_extract:
        try:
            blob = json.loads(cache.read_text(encoding="utf-8"))
            if blob.get("fingerprint") == key:
                return [Observation(**o) for o in blob["observations"]], True
        except (json.JSONDecodeError, KeyError, TypeError):
            pass    # A corrupt or outdated cache is a reason to re-extract, not to fail.

    out = [await observe(provider, qid, q, answers, shape=shape)
           for qid, q, answers, shape in items]
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(
            {"fingerprint": key,
             "observations": [{f: getattr(o, f) for f in _FIELDS} for o in out]},
            indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return out, False
