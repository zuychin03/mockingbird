"""The turn contract. Plan sections 6.1-6.3, as settled in 1c.4.

Every constant here was measured, not chosen. Changing one invalidates the Tier 1 result
that justified it, so each carries its log reference.

  6-action enum, LONG field names   short names looked free on Q4_K_M (+1 fixture) and cost
                                    3 severity on Q6_K -- deferred to phase 2 (log 7.19)
  `ask` required                    removing it saves 1.19x and DOUBLES severity; a populated
                                    `ask` is rationale-first scaffolding (log 7.20)
  prompt V5                         V2, plus the imperative `ask` copy instruction that took
                                    severity 6 -> 3 (log 7.16), plus V4's one-question and
                                    15-word rules (log 8.17). V4 also carried "start with a
                                    question word", which measured WORSE than no instruction
                                    at all -- 93% hedged openings against a 46% baseline --
                                    and is gone; guard 3c does that job deterministically.
                                    `say` on the closing actions is likewise not requested
                                    any more: asking for "at most 5 words, never a question"
                                    specifies a topic label, and 50 of 50 stored `advance`
                                    lines were labels or bare tokens (log 8.18).
"""

from __future__ import annotations

ACTIONS = ["advance", "probe", "reask", "clarify", "skip", "end"]

CONTINUE = frozenset({"advance", "probe", "reask", "clarify"})
HALT = frozenset({"skip", "end"})

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "act": {"type": "string", "enum": ACTIONS},
        "say": {"type": "string"},
        "ok": {"type": "boolean"},
        "ask": {"type": "string"},
    },
    "required": ["act", "say", "ok", "ask"],
    "additionalProperties": False,
}

# A wording repair must not be able to re-decide the turn. Keeping the action, score and
# candidate-question fields out of this schema makes that a structural property rather than
# another instruction the model may or may not follow.
SPEECH_SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
    },
    "required": ["say"],
    "additionalProperties": False,
}

# The word limit below matches `runner.MAX_SAY_WORDS`. They were 15 and 25, and the gap was
# measured before it was closed: raising the instruction to 25 moves the median one word and
# DOUBLES the compound rate, 5.2% to 10.3%, with classification flat at 87%, because the model
# spends the extra budget joining a second question with "and". Duy chose alignment knowing
# that. `compound-request-trimmed` absorbs the cost deterministically and without a model call.
SYSTEM = """You are conducting a software-engineering job interview. You ask the scripted question and judge the reply.

Choose exactly one action:

- advance  : the reply answers the question. Move to the next one.
- probe    : a real but incomplete answer. Ask one short follow-up about THIS question.
             A very short answer is still an answer -- probe it, do not re-ask it.
- reask    : no answer was produced. They drew a blank, could not recall one, or went
             off-topic. They are still willing. Put the question a different way.
- clarify  : they asked what the question means. Explain it briefly.
- skip     : they REFUSED this question. They could answer but choose not to. Move on.
- end      : they asked to STOP THE INTERVIEW -- not this question, the whole interview.

Three of these get confused. The test that separates them:

  "I can't think of one" / "nothing comes to mind"  -> CANNOT answer, still willing -> reask
  "I'd rather not answer that" / "pass on that"     -> WILL NOT answer THIS ONE     -> skip
  "I need to stop" / "I have to go"                 -> WILL NOT CONTINUE AT ALL     -> end

Ask yourself: can they not answer, will they not answer this one, or will they not continue?
Being unable to think of an example is NOT a refusal.

Rules:
- "say" is the literal words you speak next. Never stage directions.
- Speak like an interviewer, not a form. ONE question, at most 25 words.
- Probes that sound right: "Why?" / "What did you measure?" / "How did that land?" /
  "Who else was involved?" / "What would you do differently?" / "How long did that take?"
  Match that length. Anything longer is a form, not a conversation.
- On advance, skip and end, "say" is DISCARDED. Leave it empty.
- "ok" is true only when the reply fully answers the question asked. A single sentence is
  almost never a full answer to these questions. "We split a table while live" names the
  thing but says nothing about how -- that is ok=false, probe it. Set ok=true when they have
  given the situation, what they personally did, and how it turned out.
- "ask": if the candidate asked YOU a question, copy their question verbatim into "ask".
  Otherwise "ask" is an empty string. On clarify there is ALWAYS a question to copy."""


SPEECH_SYSTEM = """You are wording one follow-up in a software-engineering job interview.
The decision to probe is already final. Do not judge the answer or choose an action.

Return only the literal interviewer speech in "say".
- Ask exactly one direct question, with no preamble or acknowledgement.
- Stay on the current interview question and the required focus.
- Do not add an action, score, rationale, or any other field."""
# The repeat instruction was removed because it could not be followed. This call gets the same
# user turn as the decision it repairs, and the rendered history carries only the CANDIDATE's
# ground, so the model can see neither the line just rejected nor any question it asked
# earlier. Quoting them back is not the fix: doing so was measured and the model copied the
# rejected line on two retries. Repetition is caught deterministically after the fact instead,
# against `said_this_question` and `said_this_session`, which needs no cooperation.


def render(question: str, answer: str, history: str = "") -> str:
    """Assemble the user turn.

    History precedes the question: it wins or ties on accuracy at every depth (log 7.22),
    and it is the order a cache that grows by appending wants. An empty section is omitted
    entirely rather than rendered as a bare heading -- a heading with nothing under it cost
    2 of 24 fixtures.
    """
    head = ("INTERVIEW SO FAR:\n\n%s\n\n" % history.strip()) if history.strip() else ""
    return "%sCURRENT QUESTION: %s\n\nCANDIDATE: %s" % (head, question, answer)


def severity(predicted: str | None, gold: str) -> int:
    """Section 4.4's weighting. A family crossing is the error that ends interviews."""
    if predicted == gold:
        return 0
    if predicted is None:
        return 5
    return 5 if (predicted in HALT) != (gold in HALT) else 1
