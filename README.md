# Mockingbird

A mock-interview coach for software-engineering roles that runs entirely on your own machine.
It conducts a structured interview, decides for itself when to probe and when to move on, and
produces feedback in which every claim quotes something you actually said.

Built and validated against Llama 3.2 3B on a 6GB laptop GPU, which is the constraint that
shaped the whole design. Mockingbird intentionally supports that model only: accepting an
unknown loaded model would bypass the controls measured for the product.

## The idea it is testing

An interview is latency-sensitive and consent-sensitive, so it is a bad fit for an
unconstrained agent loop. Mockingbird gives the model a narrow job and keeps everything else
in Python:

| | |
|---|---|
| **The model** | writes the next sentence, and extracts verbatim quotes from an answer |
| **Python** | decides when to probe, when to stop, what to score, and when to end |

The model never has authority over consent, pacing, budgets, durable state, or a score. Its
proposed action is recorded and usually overridden, which is deliberate: keeping it visible is
what makes the override measurable.

## Extract, then score

The model is never asked "was this a good answer". It is asked what an answer *contains* —
quote the situation, quote the action, quote the result — and deterministic Python computes
the rubric from those quotes.

Two properties follow. Every criterion names the observation behind it, so a score can be
argued with by pointing at the quote it rests on. And the arithmetic is reproducible: the same
observations always score the same way.

The boundary is real and the code is explicit about where it sits. A criterion that is a fact
about text works well. A criterion that smuggles in a judgement does not, and the design
questions are deliberately **observed and not scored** for that reason — the report describes
what a design answer covered rather than putting a number on it.

## Guards

Five guards run on every model decision before a handler sees it. Each exists because
something went wrong, not because it seemed prudent:

- an action that ends or skips a question needs the candidate's own words behind it
- a question the model invented for itself never reaches the candidate
- a repeated line is regenerated once, and a second repeat is treated as the model's position
- closing actions do not speak the model's line
- prompt fragments are stripped out of speech

Natural probing adds two bounded speech controls after those guards. Hypothetical design
questions are kept in future tense, and an empty or off-focus probe gets one speech-only repair
attempt. That second contract exposes only `say`, so it cannot change the chosen action, the
model's completeness judgement, candidate-question routing, pacing or budget. Python accepts the
repair only when it is one direct question, no more than 25 words, asks for the requested focus and
does not repeat the rejected line, the current question or earlier session speech. Otherwise a
reviewed focus template is used.

Control replies — stop, skip, carry on — are parsed by `app/intent.py`, which matches whole
tokens, scopes negation to its clause, and answers `UNCLEAR` when it genuinely cannot tell.
Ambiguity never ends a session.

## Live and report are separate channels

What the candidate sees comes only from `live_view()`. Judgement fields — the model's
completeness verdict, action posteriors, guard names, rubric results — go to storage and the
report and never cross the live channel. Someone who can watch the agent deciding their answer
is weak will change their answer, and the assessment stops measuring what it claims to.

## Running it

Needs Python 3.12 and [LM Studio](https://lmstudio.ai/) with a local model loaded.

```bash
lms server start
lms load llama-3.2-3b-instruct --context-length 8192 --identifier llama-3.2-3b-instruct -y
```

Then, for an interview in the terminal:

```bash
python -m app.cli
```

The runtime is standard library only. Tests need pytest:

```bash
pip install -e ".[test]"
python -m pytest
```

`tools/` holds a turn-at-a-time harness (`live_candidate.py`) for driving a session
programmatically, plus renderers for the report and the transcript.

To audit how model-written questions were retained or transformed in a recent session:

```powershell
python tools/probe_audit.py --session SESSION_ID `
  --out data/calibration/probe-audit.json
```

The audit measures speech transformation, not interview quality or model accuracy. It rejects
sessions captured before raw model speech provenance was added rather than mixing incompatible
records. It reports retained, repaired and template-substituted questions separately. Each repair
also persists its trigger, raw attempt, accepted line, detected focus and rejection reason in
`speech_attempt`.

## Layout

```
app/
  runner.py        the loop: one decision per turn, dispatch over pure functions
  contract.py      the normal turn and speech-only repair schemas and prompts
  guards.py        the five guards
  intent.py        stop / skip / carry-on parsing
  direction.py     is this an answer, or a question aimed at the interviewer
  focus.py         picks what to ask ABOUT; the model only words it
  budget.py        per-question cap plus a shared session pool
  observe.py       quote extraction, with grounding
  score.py         the rubric, as arithmetic
  report.py        the feedback, and the rules about how it is worded
  session.py       plan validation and persistence
config/            interview plans
tests/             deterministic unit and integration coverage
```

## Why Llama

Mockingbird was built measurement-first. The private development log
`internal_docs/MODEL_EXPERIMENTING_LOG.md` records the symmetric fixture screens, full interview
controls, speech audits and rejected alternatives that led to selecting Llama as the sole runtime.
It remains local and intentionally ignored by Git.

## Status

The text interview, rubric scoring, report and Stage 3 natural-probing controls are implemented.
The current automated suite passes 319 tests. A full 14-question junior run produced 23 of 31
follow-ups from model speech (20 retained byte for byte and three safely trimmed to one request),
used seven templates and one deterministic design-gap probe, with no generic, compound or
over-25-word spoken question. A later targeted replay proved the final speech-repair path can
retain a corrected Llama question without changing its action. One fresh paired full-interview run
is still required to measure the final aggregate substitution rate after that last classifier
correction. A job-description planner and voice mode are designed and not built.
