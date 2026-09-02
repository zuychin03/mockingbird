# Mockingbird architecture

> Current-state guide for the `stage3-natural-probing` branch.
>
> Evidence snapshot: base commit `788ac3a`, plus the current uncommitted Stage 3 working-tree
> changes, inspected on 29/08/2026. The behaviour and test counts below describe that complete
> working state, not a published commit. Re-check this block after integration or further live
> tuning.

## 1. Purpose in one page

Mockingbird is a locally hosted mock-interview coach for software-engineering roles. It runs a
structured interview, asks bounded follow-up questions, records how each decision was reached, and
produces evidence-backed feedback from the candidate's own words.

The architecture is built around one deliberate constraint: the language model may propose and
phrase a conversational move, but deterministic Python owns consent, pacing, budgets, durable
state, evidence grounding and scoring.

```text
candidate
    |
    v
terminal CLI --> Runner --> deterministic policy and guards --> candidate-visible speech
                    |                    |
                    |                    +--> budgets, focus, intent, phase rules
                    |
                    +--> LM Studio: bounded turn proposal and quote extraction
                    |
                    +--> local session files --> observations --> arithmetic score --> report
```

This is not a general autonomous-agent loop. `Runner.submit()` is the explicit orchestrator, and
the model's six-action JSON object is advisory input to that orchestrator.

### What is implemented

- A 14-question, six-phase software-engineering interview plan, and a planner that produces one from a job description or from a stock template at a chosen length.
- Terminal-based text interviews through `python -m app.cli`.
- LM Studio integration with structured output, enum posteriors, timing and health checks.
- Exact-identity, Qwen3-4B-Instruct-2507 runtime with a measured 35-word speech cap.
- Deterministic consent, refusal, clarification, repetition, speech and budget controls.
- Focus-aware creative probing, hypothetical-design tense repair and one action-locked
  speech-only repair before template fallback.
- Candidate-question routing that keeps questions out of answer evidence.
- Per-answer background observation extraction for live pacing.
- Offline grounded extraction, deterministic scoring and plain-text reporting.
- Append-only decision records, transcript/session snapshots and provenance.
- A curated question bank over a closed competency vocabulary, model-generated questions
  that stay unaskable until a person approves them, and a plan review surface.
- Replay, calibration, transcript, planning and report harnesses under `tools/`.

### What is not implemented

- Voice input, TTS integration, barge-in, acoustic metrics and browser audio.
- A production web interface or remote service.
- A retrieval detour for answering the candidate's own questions mid-session.
- Durable command serialization, idempotency or atomic event replay.
- A general agent framework. This is intentionally not planned as the next step.

## 2. Architectural principles

### 2.1 The model proposes; Python decides

The normal turn model returns a schema-constrained object with four required fields:

| Field | Meaning | Final authority |
|---|---|---|
| `act` | Proposed action: `advance`, `probe`, `reask`, `clarify`, `skip` or `end` | Python may preserve, downgrade, upgrade or replace it |
| `say` | Proposed next sentence | Guards may strip, shorten, regenerate or replace it |
| `ok` | Whether the current reply fully answers the question | Advisory; Python resolves contradictions and pacing |
| `ask` | Candidate question copied verbatim, otherwise empty | Grounded against the utterance before use |

Python alone owns the consequences of an action. It verifies stop and skip intent, constrains
follow-ups, decides when evidence is complete, records the transition and updates durable state.

When a final probe is empty or misses the requested focus, a separate speech-repair schema exposes
only `say`. The second response therefore cannot re-decide `act`, `ok` or `ask`; Python retains the
already resolved action and accepts the wording only after deterministic length, focus, repetition
and single-question checks.

### 2.2 Extract facts, then score them

The model is not asked whether an answer was good. It is asked to quote concrete parts of the
answer. Behavioural and technical answers use `situation`, `action` and `result`. The design answer
uses `approach`, `alternative`, `tradeoff` and `failure_mode`.

Every returned quote is checked against the candidate's answer. Ungrounded or very short quotes
are dropped. Three further observations are deterministic text checks: first-person language,
specific figures and measurement language. `app/score.py` then converts those observations into
criterion booleans and totals using ordinary arithmetic.

The boundary is important:

```text
model-mediated reading                  deterministic calculation
----------------------                  -------------------------
find a situation quote     --------->   sets_context = bool(quote)
find an action quote        --------->   describes_action = bool(quote)
find a result quote         --------->   states_outcome = bool(quote)
                                             |
regex facts ------------------------------->|--> per-criterion totals
```

Design observations are described but intentionally not scored. Mentioning a topic is not reliable
evidence that the candidate reasoned about it well.

### 2.3 Live and assessment channels are separate

Only `runner.live_view()` is intended for the candidate-facing channel. It contains speech,
question progress and completion status. It excludes `ok`, posteriors, guard names, score fields and
other assessment signals that could change how a candidate answers.

### 2.4 A question is asked only if a person wrote or approved it

FR-2 allows the model to write questions and FR-6 requires every scripted question to be asked
verbatim. Both hold only while the text has been read by someone, so a question carries a
`source` -- where the text came from, which never changes -- and a `status`, which is whether
it may be asked at all. Generation produces `proposed`, only approval changes status, and both
selection and review refuse anything unapproved. Approving never rewrites `source`, so a
generated question stays marked as one for good.

The competency vocabulary is closed for the same reason `rubric_criteria` is validated at
load: a planner free to invent a name produces a tag nothing matches, and the failure is
silent -- a competency the description asked for simply never appears in the plan.

### 2.5 Local-first and standard-library-only runtime

The runtime requires Python 3.12 but has no third-party runtime dependencies. It uses `asyncio`,
`urllib`, `json`, dataclasses and local files. Pytest and research/audio dependencies are optional.
LM Studio is the only live external process, reached on `http://127.0.0.1:1234`.

## 3. Runtime topology

```text
Process A: terminal application                    Process B: LM Studio
-----------------------------------------------   -------------------------------
app.cli                                            exact runtime identifier
  preflight ------------------------------------> /api/v0/models
  canary ---------------------------------------> /api/v0/chat/completions
  warm prompt cache ----------------------------> /v1/chat/completions
  Runner.submit()
    decide structured turn ---------------------> /v1/chat/completions + logprobs
    background observation ---------------------> /v1/chat/completions
    refresh completed-question history --------> /v1/chat/completions
  local persistence
    data/sessions/<session-id>/
```

`127.0.0.1` is intentional. Using `localhost` previously attempted IPv6 before IPv4 and added a
large client-side stall that server timing could not see.

The provider port uses two endpoints because the API surfaces are complementary:

- `/v1/chat/completions` supplies structured completion output and token log probabilities.
- `/api/v0/chat/completions` supplies server timing data for the canary.
- `/api/v0/models` supplies the loaded catalogue used to verify the exact product identifier.

## 4. Component map

### 4.1 Runtime modules

| Module | Responsibility | Main inputs | Main outputs |
|---|---|---|---|
| [`app/cli.py`](../app/cli.py) | Terminal entry point, preflight, warm-up and interview loop | Plan path, stdin, LM Studio | Candidate speech and session paths |
| [`app/runner.py`](../app/runner.py) | Owns the turn loop, precedence, state transitions and dispatch | Candidate utterance, plan, provider, state | `TurnOutcome`, persisted turn |
| [`app/contract.py`](../app/contract.py) | Normal turn and speech-only repair schemas, prompts and severity utility | Current question, answer, summary | Structured model request |
| [`app/provider.py`](../app/provider.py) | LM Studio transport, metrics, posteriors and exact runtime identity | System/user prompts and schema | `Completion` or `ProviderError` |
| [`app/intent.py`](../app/intent.py) | Clause-aware control parsing | Candidate utterance | stop, continue, skip or unclear |
| [`app/direction.py`](../app/direction.py) | Separates candidate questions from answers | Candidate utterance | Role decision and optional answer prefix |
| [`app/guards.py`](../app/guards.py) | Validates model proposal and sanitises speech | Raw model JSON and utterance | `Guarded` effective proposal |
| [`app/focus.py`](../app/focus.py) | Chooses and classifies request types; supplies session-distinct and design-safe fallbacks | Answer, criteria, used focuses | Focus instruction, classification or fallback line |
| [`app/budget.py`](../app/budget.py) | Per-question allowance and shared overflow pool | Phase cap, pool and progress | `Allowance` |
| [`app/bank.py`](../app/bank.py) | Curated questions over a closed competency vocabulary; the approved/proposed gate | Bank file | `Bank`, or a load error naming what is wrong |
| [`app/planner.py`](../app/planner.py) | Reads a description into cited competencies; selects, generates and assembles a plan | Description text or a stock kind, and a `Bank` | `JobSpec`, a proposed `Question`, or an `Assembled` plan |
| [`app/review.py`](../app/review.py) | The operations a person performs on a plan before it runs | `Draft` and one edit | A revalidated `Draft` |
| [`app/history.py`](../app/history.py) | Maintains a short summary of completed questions | Closed questions and answers | Prompt history |
| [`app/result_check.py`](../app/result_check.py) | Conservative pacing-only result check | Extracted result quote | Whether text states change/completion |
| [`app/session.py`](../app/session.py) | Plan validation, state types and local persistence | Plan and `SessionState` | JSON/JSONL session files |
| [`app/provenance.py`](../app/provenance.py) | Best-effort reproducibility snapshot | Git, Python, model metadata | Revision, contract and environment fields |
| [`app/observe.py`](../app/observe.py) | Grounded quote extraction and observation cache | Completed answers and shape | `Observation` objects |
| [`app/embed.py`](../app/embed.py) | OPTIONAL local sentence similarity for probe de-duplication; returns None when the embedding model is absent | Two probe texts | Cosine similarity or None |
| [`app/score.py`](../app/score.py) | Deterministic criterion arithmetic | Observations and criteria map | `QuestionScore` and `Report` |
| [`app/report.py`](../app/report.py) | Evidence-led candidate feedback | Scores, observations, close reasons | Plain-text report |
| [`app/depth_signals.py`](../app/depth_signals.py) | Regex facts used by focus and observations | Answer text | Depth-signal booleans |

### 4.2 Configuration and tools

| Area | Role |
|---|---|
| [`config/interview_swe_general.json`](../config/interview_swe_general.json) | Current plan, phases, question text, caps, focus ladders and rubric metadata. Also the template every generated plan takes its phase configuration from |
| [`config/question_bank.json`](../config/question_bank.json) | Curated questions, the closed competency vocabulary and the phase each competency belongs to |
| [`tools/plan_review.py`](../tools/plan_review.py) | Terminal surface for planning and review; a command per action with disk state, so each step is its own process |
| [`tools/live_candidate.py`](../tools/live_candidate.py) | Turn-at-a-time human-driven harness with disk state; least scripted drift |
| [`tools/stage2_report.py`](../tools/stage2_report.py) | Offline extraction, scoring and report generation |
| [`tools/render_transcript.py`](../tools/render_transcript.py) | Human-readable transcript page |
| [`tools/render_report.py`](../tools/render_report.py) | Rendered report output |
| [`tools/probe_audit.py`](../tools/probe_audit.py) | Audits session decision records as retained, repaired or substituted speech with transformation diagnostics |
| Private ignored harnesses | Historical `stage1_*`, `tier1_*` and `tier2_*` experiments kept locally for development evidence |

## 5. Session start, end to end

`app.cli.run()` establishes the runtime in this order:

1. Create an `LMStudio` provider for the exact identifier `qwen3-4b-instruct-2507`.
2. Query loaded models and refuse to start unless that exact product model is loaded.
3. Run the canary unless disabled. It checks prefill time, decode throughput and transport
   overhead separately.
4. Load and validate the interview plan.
5. Warm the real turn system prompt so the first candidate turn is not a cold-cache measurement.
6. Capture provenance and create the session directory.
7. Construct `Runner` with the 35-word cap and an injected per-answer observation function.
8. Ask the current scripted question.
9. Repeatedly read one non-empty utterance and call `Runner.submit()`.
10. Print only candidate-safe `Spoken` fields.
11. On completion, print status and file locations. Ctrl+C records an abandoned checkpoint.

## 6. One live turn, systematically

The important architecture is the ordering inside `Runner.submit()`. Later rules can only see the
result of earlier ones, so the sequence is policy, not incidental control flow.

### 6.1 Settle background evidence

The previous answer's pending observation task is awaited first. Extraction failure is caught and
ignored so optional enrichment cannot end the interview. For STAR-paced phases, newly found
`situation`, `action` and `result` parts update `seen`; a pacing-only check rejects result text that
does not state a change or completion.

### 6.2 Resolve pending control states

Two runner-owned mini-states outrank a normal model turn:

- `awaiting_confirm`: read stop, skip, continue or unclear without a model call. An unclear
  three-way answer is narrowed once to a yes/no stop question.
- `awaiting_skip_offer`: accept the skip, escalate a stop response to confirmation, or grant one
  more clarification attempt.

These states cost no model call and cannot silently convert a bare affirmative into an unsafe end.

### 6.3 Apply phase-specific routing

- A `user_questions` phase uses a deterministic handler and never calls the turn model.
- Outside that phase, a candidate question about the role is deferred and separated from answer
  evidence. A sufficiently long answer before a trailing question is retained as answer text.

### 6.4 Choose follow-up intent

`focus.next_focus()` chooses what a probe should ask about. Its precedence is:

1. Missing signals in the current answer.
2. The phase's declared rubric criteria, still outstanding, asked in the ladder's order.
3. The phase-specific focus ladder.
4. A global fallback ladder.

Used focuses are excluded, preventing the same request type from consuming multiple turns. If the
candidate explicitly has no example, focus steering is disabled and rephrasing is left to `reask`.

Two orderings exist and step 2 follows the second. `rubric_criteria` is the order an answer is
SCORED in and leads with `sets_context` in every scored phase; `focus_ladder` is the order an
interviewer ASKS in and ranks `CONTEXT` low or omits it. Selecting in scoring order made the
ladder unreachable whenever a criterion was unmet, so `CONTEXT` won nearly every fallback turn.

A criterion is outstanding only if its focus is unused AND the observation part that satisfies it
is not in `seen` (`SATISFIED_BY` in `app/focus.py`): `sets_context` by `situation`,
`describes_action` by `action`, `states_outcome` by `result`. This is what stops the interviewer
asking for evidence an earlier answer already supplied. Criteria with no extracted part, such as
`first_person`, are never skipped by it. Parts are extracted off the live path, so `seen` reflects
the answers before the current one; the current utterance is covered by step 1, which runs first.

### 6.5 Ask the model for one constrained proposal

The request combines the system contract, optional focus instruction, completed-question summary,
current scripted question and candidate utterance. The provider requests strict JSON and records an
action posterior from the enum token position.

### 6.6 Run proposal guards

`guards.apply()` performs the following effective pipeline:

1. Invalid or missing JSON becomes a regenerating `probe` fallback.
2. Invented questions on closing actions are removed; an `advance`/`ok=false` contradiction becomes
   `probe` for the measured turn contract.
3. Ungrounded `end`, `clarify` and `skip` actions are downgraded.
4. Candidate-grounded refusal and cannot-answer language upgrades eligible actions to `skip` and
   `reask` respectively.
5. A repeated probe/reask requests one regeneration.
6. Candidate-text echoes and prompt labels are removed.
7. Hedged openings are rewritten more directly.
8. Closing-action speech is discarded.
9. Multi-sentence speech keeps the actual question where possible, then applies a hard character
   cap.

### 6.7 Bound retries and speech adaptation

There are at most two model calls for a turn.

- A repeated or malformed first turn response gets one full-turn regeneration. A second semantic
  repetition advances rather than looping; malformed output keeps the safe probe fallback.
- A first line past the 35-word cap gets one full-turn shortening retry. It is accepted only
  when the action is unchanged, speech is present and the result fits the cap. Compound
  questions are NOT trimmed: a two-part question is ordinary interviewer behaviour.
- After consent, clarification, budget and pacing decisions are final, a hypothetical design probe
  with a recognised past premise is rewritten through a finite deterministic transform. An unsafe
  or repeated transform uses a future-conditional design template and costs no model call.
- An off-focus line is not automatically discarded. The focus check is empty for two different
  reasons, and only one of them is a fault: a line that classifies to a request type already
  spent on this question is the model repeating itself and is refused, while a line the
  classifier cannot NAME is kept when it is a single question, within the cap, at least ten
  words and not already spoken. The requested focus is charged either way, so the ladder still
  advances and no turn can silently ask the same kind of thing twice.
- A final `probe` whose speech is empty, or off-focus and too terse to keep, gets one
  speech-only completion through `SPEECH_SCHEMA`. It is accepted only when the line is one
  direct question within the cap, asks about a focus this question has not already spent, and
  repeats neither the current/rejected line nor prior session speech. It runs under a deadline;
  past it the turn stops waiting. A failed attempt falls through to the next unspoken reviewed
  focus template.

The speech-repair prompt deliberately does not quote rejected or previously spoken lines. The first
live implementation showed the model copied negative examples; repetition is now described only as
a validator rule. `reask` retains its existing deterministic fallback to the scripted question.

### 6.8 Apply runner-owned policy

After the guards and retry, the runner may still override the proposal:

1. A stop request that the model missed starts confirmation.
2. A clarification request that the model missed becomes `clarify`.
3. Repeated clarification offers a consensual skip, then eventually auto-skips after the additional
   attempt is exhausted.
4. Per-question follow-up cap and shared pool prevent unbounded `probe`/`reask` turns.
5. Complete STAR evidence or two consecutive no-gain answers may advance an adaptive phase.
6. A design answer about to advance without failure language receives one fixed design probe if its
   own cap still has room.
7. A design probe is made future-conditional when needed; empty or off-focus probe speech is then
   repaired through the action-locked schema or replaced with a reviewed template.

### 6.9 Dispatch, record and continue

The effective action maps to one handler. The handler produces speech and says whether the question
or session closed. The runner then:

1. Appends a `Turn` to in-memory transcript state.
2. Appends a decision record to `decisions.jsonl`.
3. Closes and rolls question state when required.
4. Updates terminal session status.
5. Writes transcript and session snapshots.
6. Returns a candidate-safe `TurnOutcome`.
7. Starts per-answer observation in the background when the question remains open and is STAR-paced.

Although `session.checkpoint()` is documented as question-boundary persistence, the current runner
calls it after every dispatched turn. That is safer than the docstring implies, but it is still a
direct rewrite rather than an atomic projection.

## 7. Common scenario paths

| Candidate input | Deterministic path | Typical effective outcome |
|---|---|---|
| Gives a partial answer | focus -> model -> guards -> pacing -> speech validation | `probe` with a retained, repaired or reviewed bounded question |
| Gives no example but remains willing | cannot-answer vocabulary -> guard upgrade | `reask` |
| Refuses only this question | refusal vocabulary -> guard upgrade | `skip` |
| Asks what the question means | clarification detector -> runner upgrade | `clarify` without spending probe budget |
| Asks about the role mid-answer | direction routing; answer prefix may be kept | defer the question and keep assessment channels separate |
| Requests to stop | stop detector -> confirmation state | `end` only after grounded confirmation |
| Gives an ambiguous confirmation | narrow once, then preserve session | `clarify`/continue, never guessed end |
| Model repeats itself | regeneration once, then safe fallback/close | bounded liveness |
| Probe speech cannot be named by the classifier | kept when it is a single in-cap question of ten words or more | the model's own wording survives a regex that cannot label it |
| Probe speech repeats a spent request type, or is empty | action-locked speech repair, then template | useful wording without re-deciding the turn |
| Design probe assumes past experience | finite future-tense rewrite or design template | hypothetical assessment stays hypothetical |
| LM output is malformed | invalid guard -> one regeneration/fallback | continue with safe probe wording |
| Background extraction fails | exception swallowed in `_settle()` | live interview continues |

## 8. Interview plan and pacing

The current plan contains 14 questions:

| Phase | Type | Questions | Probe cap | Scored | Observation shape |
|---|---|---:|---:|---:|---|
| `warmup` | `fixed_sequence` | 2 | 1 | no | STAR-shaped but not adaptively paced |
| `behavioural_core` | `adaptive_discussion` | 4 | 3 | yes | STAR |
| `technical_experience` | `adaptive_discussion` | 4 | 2 | yes | STAR |
| `design` | `long_turn` | 1 | 2 | no | design |
| `collaboration` | `adaptive_discussion` | 2 | 2 | yes | STAR |
| `closing` | `user_questions` | 1 | 0 | no | none |

The shared overflow pool is `round(question_count * 1.0)`, currently 14 turns. A question with a
positive phase cap receives an integer fair share of the remaining pool. A zero cap is hard and
cannot draw from the pool.

Clarification is excluded from probe budget because it repairs interviewer/candidate understanding,
but a separate liveness limit prevents an infinite clarification loop.

Plan loading validates:

- every phase has `answer_shape`;
- every phase declares a supported type;
- every rubric criterion has an implementation;
- every scored phase declares at least one criterion.

`session.iter_questions()` then flattens phase data into the runner's ordered question records.

## 9. State and persistence

### 9.1 In-memory state

`Runner` owns volatile loop state, including:

- current question index and follow-up counters;
- shared pool balance;
- pending observation task;
- accumulated STAR evidence and stall count;
- focus types and speech already used;
- answers and candidate questions for the current question;
- stop-confirmation and skip-offer flags;
- the 35-word speech cap and whether the design-gap follow-up has fired.

`SessionState` owns durable-domain state: session identity, status, turns and closed questions.

### 9.2 On-disk layout

```text
data/sessions/<session-id>/
  session.json       session metadata, plan snapshot, provenance and closed-question state
  transcript.json    every committed turn in candidate/interviewer order
  decisions.jsonl    append-only effective decision and diagnostic record per turn
```

Important decision fields include candidate utterance, effective action and speech, guard names,
semantic close reason, requested/actual focus, `say_raw`, replaced `say_model`, `speech_attempt`,
budgets, posterior, usage, total latency, model-call count, exact rendered normal-turn prompt and
timestamp. `speech_attempt` retains the repair trigger, its raw and guarded wording, detected focus,
acceptance or rejection reason, repair guards, usage and repair-call latency.

### 9.3 Provenance

Each session snapshot attempts to record:

- Git revision and dirty suffix;
- one hash covering both system prompts and both turn/speech schemas;
- Python and platform versions;
- resolved model key, path, architecture, quantisation and loaded context length.

Provenance is best-effort and cannot block interview start.

## 10. Offline assessment pipeline

The intended post-session sequence is:

```text
closed QuestionState answers
        |
        v
observe.observe_all()
  - select STAR or design extractor
  - run deterministic text checks
  - request verbatim model quotes
  - drop ungrounded quotes
  - cache by extractor/input fingerprint
        |
        v
score.build()
  - select phase-declared criteria
  - convert observation fields to booleans
  - aggregate per criterion
        |
        v
report.render()
  - lead with weak habits
  - cite representative answers/quotes
  - recognise strong habits
  - show all arithmetic
  - mark scored questions cut short
  - describe, but do not score, the design answer
```

`WEAK` is `<= 0.6` and `STRONG` is `>= 0.8`, defined once in `app/score.py` and shared by report
paths. No overall grade is produced.

The report's final disclaimer is architecturally important: the quotes are the candidate's words
and the counting is checkable, but a model still selected which words counted as evidence.

## 11. Failure containment

| Failure | Current containment | Candidate impact |
|---|---|---|
| Invalid model JSON | Convert to probe and allow one regeneration | Safe fallback, possible reviewed template |
| Model proposes ungrounded end/skip | Deterministic grounding downgrades action | Session/question remains open |
| Ambiguous stop reply | Narrow once; do not guess | One extra control turn |
| Repeated speech | One regeneration, then bounded fallback/close | No infinite wording loop |
| Overlong speech | One action-preserving full-turn shortening retry, then focus validation | Bounded latency and speech within the cap |
| Unnameable but substantive probe speech | Kept, with the requested focus charged | Fewer templates without losing focus rotation |
| Empty or terse off-focus probe speech | One `say`-only repair, then a reviewed focus template | Action and pacing remain fixed |
| Past-premised design speech | Finite tense rewrite, then a future-conditional design template | No false claim of prior implementation |
| Background live observation failure | Swallowed by `_settle()` | Adaptive pacing loses one evidence update |
| Corrupt observation cache | Ignore and re-extract | Extra offline model work |
| LM Studio unavailable at preflight | CLI refuses to start | No session begins |
| Provider failure during a normal turn | Propagates to CLI's provider handler | Current process exits; recovery is limited to saved files |
| Ctrl+C/EOF | Mark abandoned and checkpoint | Transcript retained |

## 12. Testing and evaluation architecture

At this snapshot, pytest collects and passes 319 tests:

| Module | Collected tests | Main concern |
|---|---:|---|
| `test_guards.py` | 61 | Decision grounding and speech hygiene |
| `test_intent.py` | 26 | Clause-aware stop/skip/continue parsing |
| `test_nfr.py` | 7 | Architectural and non-functional constraints |
| `test_observe.py` | 31 | Extraction grounding, cache and observation shapes |
| `test_persistence.py` | 11 | Plan validation, files and provenance |
| `test_probe_audit.py` | 4 | Raw, repaired and substituted speech provenance |
| `test_provider.py` | 7 | Transport, posterior and exact runtime identity |
| `test_report.py` | 8 | Feedback selection, thresholds and rendering |
| `test_runner.py` | 164 | Turn precedence, pacing, routing, repair and state |

Use the project's virtual environment and a writable explicit base temp on Windows:

```powershell
$testTemp = Join-Path $env:TEMP 'mockingbird-pytest'
python -m pytest -q -p no:cacheprovider --basetemp $testTemp
```

The harness taxonomy matters:

- App-driving harnesses validate the current interfaces.
- Tier experiments preserve measurement history but may not be maintained against current app
  interfaces.
- Scripted candidates can drift out of sync with an adaptive interviewer. Use `stage1_long --pin`
  or a recorded replay when navigation itself is not under test.
- `live_candidate.py` is the best fit for human-in-the-loop behavioural validation.

Unit counts are evidence of deterministic coverage, not evidence that a local model, GPU state or
full live interview works end to end. The canary and a human-driven smoke session cover different
failure classes.

### 12.1 Latest behavioural evidence

The full junior probe-stress session `20260829-190818-ec1710` completed all 14 questions in 46
turns and produced 31 follow-ups: 23 model-derived lines (20 retained byte for byte plus three
compound-request trims, 74.2%), seven templates (22.6%) and one deterministic design-gap probe
(3.2%). It spoke no generic “Could you say a bit more about that?”, compound question or
question past the cap, and had no action conflict.

That run also exposed a defect in the first speech-repair prompt: all seven attempts were rejected,
including copies of negative examples. The prompt and classifier were corrected afterwards. The
targeted replay `20260829-193251-d8cd97` then retained two of three raw questions and accepted one
speech-only repair: the off-focus line “How did you know it was worth taking more time to discuss?”
became the focused measurement question “How did you know the optimal timeframe for completing the
demo?” The effective `probe` action stayed fixed, the turn used two model calls, and the repair call
took 602.6 ms.

Two junior controls were then run each side of the speech-recovery changes, with a strong control
for pacing. Pooled over 47 raw questions before and 54 after, byte-for-byte retention barely moved
(59.6% to 61.1%) while template substitution fell from 12.8% to 1.9% and speech-repair acceptance
rose from 20% to 67%. The change did not make the model write better questions; it stopped the
harness discarding the ones it already wrote.

The design-tense path is covered by a runner-level regression test rather than by a live run:
neither post-change control drew a follow-up on the design question, so that branch was never
exercised in a session.

## 13. Current limitations and architecture risks

These are current-code observations, not claims that planned future work has shipped.

### High: replay and recovery are incomplete

The decision log records the effective turn, exact normal-turn user prompt and raw-versus-spoken
speech. Speech-only repair attempts now have structured diagnostics, but full-turn regeneration and
shortening attempts still do not retain a complete immutable request/response envelope. There is no
session restore function that rebuilds runner state by replaying events.

Improvement: define immutable `ModelAttempt` and `TurnEvent` records, make the event stream the source
of truth, and rebuild projections from it.

### High: persistence is not atomic or serialized

JSON snapshots are written directly to their destination, JSONL appends are not explicitly flushed,
and there is no command sequence, idempotency key or expected state version. A browser or voice
frontend could submit concurrent commands into mutable runner state.

Improvement: serialize commands, append and flush the event before acknowledging it, use atomic
temporary-file replacement for projections, and test crash points.

### Medium-high: policy precedence is encoded by statement order

`Runner.submit()` is readable but large and owns control states, phase routing, model calls, retries,
budgets, evidence pacing, speech substitution and dispatch. A new override can accidentally reverse an
earlier decision if its eligible action set is too broad.

Improvement: first pin the current precedence pairs as tests, then extract a pure typed reducer one
rule family at a time. Do not replace the runner with a general graph framework.

### Medium: live provider failure recovery is limited

Background observation is fail-open, but the normal turn call and history refresh can raise out of the
runner. The CLI reports a provider error and exits; it does not offer a deterministic recoverable turn
or resume protocol.

Improvement: record the failed attempt, preserve an unambiguous state and provide a bounded retry or
safe pause/resume path.

### Medium: design feedback remains model-mediated

Design answers are correctly excluded from scoring, but the descriptive checklist still depends on
model-selected quotes. Project experiments record inversions where weak and strong answers received
misleading presence/absence descriptions.

Improvement: keep it unscored, present uncertainty plainly, and expand independent held-out evaluation
before promoting any design observation to a scored criterion.

### Medium: evaluation independence is still limited

The unit suite is extensive, but a frozen, independently authored, stratified evaluation corpus and
human agreement record are not part of the runtime gate. Live sessions have repeatedly found paths
that fixtures and corpus sweeps missed.

Improvement: maintain a held-out set with multiple authors, preserve model/config provenance and run
both deterministic tests and human-driven live sessions before expanding to voice or planning.

### Low: final aggregate speech-repair evidence is pending

The final prompt and focus classifier pass the exact failure replay, but the most recent full junior
session predates those corrections. Its 74.2% raw retention and seven rejected repair attempts must
not be presented as the final configuration's aggregate rate.

Improvement: run a fresh paired junior and strong control, audit every raw/repaired/substituted line,
and record both byte-for-byte retention and accepted repair rates.

## 14. Safe extension sequence

1. Preserve current behaviour with precedence and adversarial control tests.
2. Introduce explicit utterance-role, policy-result, model-attempt and event types.
3. Make append-only events authoritative and recovery atomic.
4. Serialize commands and make repeated submissions idempotent.
5. Build an independent held-out evaluation gate.
6. Add a job-description planner only after generated plans are validated against executable phase
   contracts.
7. Add a text web interface using only `live_view()` for candidate-visible state.
8. Treat voice as a separate architecture wave covering endpointing, echo cancellation, transport
   cancellation, interruption and audio provenance.

## 15. Operational runbook

### Start LM Studio and load a model

```powershell
lms server start
lms load qwen3-4b-instruct-2507 --context-length 8192 --identifier qwen3-4b-instruct-2507 -y
```

The identifier is a product contract, not an interchangeable alias. Preflight rejects any other
loaded model rather than applying unmeasured model-specific behaviour.

### Run a terminal interview

```powershell
python -m app.cli
```

Optional flags:

```powershell
python -m app.cli --plan config/interview_swe_general.json
python -m app.cli --no-canary
```

Use `--no-canary` only when the health measurement is intentionally being bypassed; it does not make a
slow or misconfigured runtime healthy.

### Generate offline feedback

Consult the current command contract first:

```powershell
python tools/stage2_report.py --help
```

### Investigate a live session

Read in this order:

1. `session.json` for plan, provenance, status and semantic close reasons.
2. `transcript.json` for the candidate/interviewer conversation.
3. `decisions.jsonl` for effective policy, guards, focus, `say_raw`, `say_model`, any
   `speech_attempt`, model telemetry and prompt.
4. Cached observations and report output for the offline assessment path.

Never use only the model's proposed action to explain what happened. The effective action, guards and
close reason are the state transition.

## 16. Glossary

| Term | Meaning in Mockingbird |
|---|---|
| Advisory action | The model's proposed `act`; not necessarily the state transition |
| Effective action | The action after guards and runner policy |
| Focus | Deterministically chosen purpose of the next follow-up |
| Guard | Deterministic validation or speech rewrite applied to a model proposal |
| Observation | Grounded quote or fact about candidate text |
| Close reason | Semantic explanation of why a question/session ended |
| Speech repair | One action-locked `say`-only attempt to replace empty or off-focus probe wording |
| Live view | The only data structure intended for candidate-visible state |
| Overflow pool | Shared reserve used after a question's own positive cap |
| Script drift | A fixed replay answer no longer matching an adaptive runner's current question |
| Provenance | Code, contract, runtime and model identity stored with a session |

## 17. Source-of-truth checklist

When this guide and the code disagree, inspect in this order:

1. `app/runner.py` for live sequencing and effective policy.
2. `app/guards.py` and `app/intent.py` for control grounding.
3. `app/session.py` and the current plan for executable configuration and persistence.
4. `app/observe.py`, `app/score.py` and `app/report.py` for assessment.
5. `tools/live_candidate.py` and `tools/probe_audit.py` for current live and speech-audit contracts.
6. Tests for intended invariants.
7. The private `internal_docs/MODEL_EXPERIMENTING_LOG.md` and Stage 3 plan for why a choice exists,
   not as proof that it is still implemented.

The companion [`architecture-explorer.html`](architecture-explorer.html) presents the same system as
interactive component, turn-path, phase and data-lineage views.
