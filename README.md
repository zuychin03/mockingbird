# Mockingbird

A mock-interview coach for software-engineering roles that runs entirely on your own machine.
It conducts a structured interview, decides for itself when to probe and when to move on, and
produces feedback in which every claim quotes something you actually said.

Built and validated against Qwen3-4B-Instruct-2507 on a 6GB laptop GPU, which is the
constraint that shaped the whole design. Mockingbird intentionally supports that model only:
accepting an unknown loaded model would bypass the controls measured for the product.

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
repair when it is a direct question within the word cap, asks about a focus this question has not
already spent, and does not repeat the rejected line, the current question or earlier session
speech. Otherwise a reviewed focus template is used.

The repair asks for a focus but does not insist on it, because the decision path it serves does
not either: a question that arrives on a different unspent focus is a good turn, and demanding
the exact one discarded usable questions in favour of canned lines. The repair also runs under a
deadline; past it the turn stops waiting and speaks the template, which bounds what a candidate
can be left waiting for on a slow machine.

Two more controls compare meaning rather than spelling, and both are skipped when the optional
embedding model is absent:

- a probe that re-asks the previous one in different words is dropped and the question advances,
  because focus rotation compares LABELS and cannot see "how did you know X" and "what made you
  decide X" as one question
- a line the repetition guard flags is kept anyway when the embedding disagrees, because that
  guard compares characters and short interview questions are mostly shared scaffolding

Compound questions are kept rather than trimmed. A two-part question is ordinary interviewer
behaviour, one of the scripted questions is itself double-barrelled, and trimming to the first
clause discarded the better half often enough to notice while halving the text the focus
classifier had to read.

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
lms load qwen3-4b-instruct-2507 --context-length 8192 --identifier qwen3-4b-instruct-2507 -y
```

One small embedding model is optional and worth loading. Two of the speech controls compare
what a probe MEANS rather than how it is spelled, and without it they fall back to comparing
words, which is quieter and weaker rather than an error:

```bash
lms get -y https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF
lms load text-embedding-all-minilm-l6-v2-embedding -y
```

`lms get` needs the full Hugging Face URL; a bare model name searches LM Studio's own catalogue
and fails. The model was chosen by measuring six candidates on labelled probe pairs from real
sessions rather than by leaderboard: all-MiniLM-L6-v2 at 22M parameters beat nomic-embed-v1.5,
mxbai-embed-large and embeddinggemma-300m, because those are tuned for matching a short query to
a long document while this compares two questions of the same shape. It costs 25MB on disk and
about 164MiB of VRAM.

Then plan an interview. There are three ways in.

From a job description, which is read for the competencies it actually asks for and turned
into a plan you review before anyone is interviewed with it:

```bash
python tools/plan_review.py --jd path/to/description.txt
```

Without one, from a stock plan at a length you choose:

```bash
python tools/plan_review.py --stock technical --minutes 40
```

Or skip planning and run the hand-written plan, which is the one every measurement in this
repo was taken against:

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

## Planning, and what the agent is allowed to ask

A job description is read for the competencies it asks for, each one cited from the
description's own words. A competency whose citation is not actually in the text is dropped
and kept separately, because "the description did not ask for this" and "the planner missed
it" are different facts and only a person can tell them apart. The vocabulary is closed and
the extraction schema takes its list from the question bank, so the planner cannot name a
competency it has no question for.

Questions come from a curated bank. The model may also write one, and when it does the
question is marked `generated` and lands at `proposed`, which means it cannot be asked. There
are exactly three ways a question reaches a candidate:

- it was written by hand and reviewed, or
- it was generated and a person approved it, or
- a person typed it during review.

Approving changes a question's status and never its source, so a generated question stays
marked as one after it is approved. Assembly reads askable questions only, and review refuses
to add a proposal by hand, so the gate cannot be reached past from either side. That is what
makes asking every scripted question verbatim worth anything.

Assembly chooses questions and nothing else. Every other field of a phase -- the probe
budgets, the focus ladders, whether the phase is scored -- is a measured decision, so the
phase configuration is the reviewed template and a test asserts it comes through unchanged.

Two limits worth knowing. Extraction found four of six competencies on a hand-labelled
description and missed one the text names outright; asking per competency instead measured
worse, so review is the mitigation rather than a better prompt. And the near-duplicate check
on a generated question catches 12 of 28 real rephrasings at the threshold that produces no
false positives -- a cheap filter on the obvious cases, not a guarantee.

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
  embed.py         OPTIONAL local sentence similarity; returns None when absent
  score.py         the rubric, as arithmetic
  report.py        the feedback, and the rules about how it is worded
  session.py       plan validation and persistence
  bank.py          the curated question bank and its closed competency vocabulary
  planner.py       description -> competencies -> plan; generation, and stock plans
  review.py        the operations a person performs on a plan before it is run
config/            interview plans, and the question bank
tests/             deterministic unit and integration coverage
```

## Why Qwen3-4B-Instruct

Mockingbird was built measurement-first, and the runtime changed once the measurements said to.
Llama 3.2 3B was the sole model until September 2026, when a symmetric screen and a paired live
control replaced it.

On 60 fixtures scored through the real guards, Qwen reads 49/49 with severity 0 against Llama's
47/49 and severity 2, and it never contradicts itself on `advance`: it chooses that action ten
times for ten, where Llama chooses it twelve times for the same ten. On a live junior interview
answered turn by turn, Qwen closed all fourteen questions in 29 turns against Llama's 42, needed
no speech repair where Llama's failed three times and fell back to four canned lines, and drew
twice on the shared question pool where Llama drew five times.

Qwen decodes about 24% slower per token, which is the one axis it loses and the one that matters
least: it writes less per decision, so a single turn is faster in wall time (840 ms median against
897 ms, and 1438 ms at its worst against 1682 ms), and Llama is the one that breaches the 1500 ms
per-turn budget.

The private development log `internal_docs/MODEL_EXPERIMENTING_LOG.md` records the screens,
controls, speech audits and rejected alternatives behind that change. It remains local and
intentionally ignored by Git.

## Status

The text interview, rubric scoring, report, the natural-probing wave and the planner are
implemented, with 468 automated tests passing. An interview can be planned from a job
description or from a stock plan, reviewed and edited, saved, and then conducted.

The paired acceptance control passes on a fresh run of each profile: a junior-to-mid interview
closed all 14 questions in 25 turns and a strong one in 16, with no reask, family crossing,
invalid output, repeated focus or unknowable question in either, and no pool draws. Creative
retention across the pair was 90.9% among the questions that reached the candidate, with
byte-for-byte retention reported separately at 61.5% because the two measure different things.

Two cautions on those numbers, both learned by getting them wrong first. A single session cannot
resolve a retention difference smaller than roughly fifteen points, because extraction is
non-deterministic on this GPU path — two runs of one build measured 50.0% and 65.2%. And timing
comparisons between sessions are worthless unless the arms are interleaved: the same build has
measured 20% apart depending on how warm the GPU was.

A web interface and voice mode are designed and not built.
