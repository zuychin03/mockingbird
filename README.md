# Mockingbird

A mock-interview coach for software-engineering roles that runs entirely on your own machine.
It conducts a structured interview, decides for itself when to probe and when to move on, and
produces feedback in which every claim quotes something you actually said.

Built against a 3B model on a 6GB laptop GPU, which is the constraint that shaped the whole
design.

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
lms load granite-4.1-3b --context-length 8192 --identifier mockingbird-llm -y
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
  --out data/calibration/granite42-junior-probes.json
```

The audit measures speech transformation, not interview quality or model accuracy. It rejects
sessions captured before raw model speech provenance was added rather than mixing incompatible
records.

## Layout

```
app/
  runner.py        the loop: one decision per turn, dispatch over pure functions
  contract.py      the turn schema and system prompt
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
tests/             224 tests
```

## A note on the comments

The source comments cite section numbers from a research log that is not part of this
repository — the project was built measurement-first, and most rules here exist because an
alternative was tried and measured worse. The citations are left in because the reasoning is
worth more than the tidiness, but the documents behind them are private.

## Status

The text interview, the rubric scoring and the report are built and tested. A job-description
planner and a voice mode are designed and not built.
