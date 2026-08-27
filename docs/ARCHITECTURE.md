# Mockingbird architecture

> Current-state guide for the `exaone-adaptation` branch.
>
> Evidence snapshot: commit `5e21330c43ac69d121fbe129c6bd40097e275ba0`, inspected on
> 26/08/2026. The working tree also contained pre-existing changes in `app/runner.py` and
> `tests/test_runner.py`; the behaviour described here includes those changes. Re-check the
> snapshot block after substantial runtime changes.

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

- A 14-question, six-phase software-engineering interview plan.
- Terminal-based text interviews through `python -m app.cli`.
- LM Studio integration with structured output, enum posteriors, timing and health checks.
- Model-specific speech profiles for Granite, Yi and EXAONE.
- Deterministic consent, refusal, clarification, repetition, speech and budget controls.
- Candidate-question routing that keeps questions out of answer evidence.
- Per-answer background observation extraction for live pacing.
- Offline grounded extraction, deterministic scoring and plain-text reporting.
- Append-only decision records, transcript/session snapshots and provenance.
- Replay, calibration, transcript and report harnesses under `tools/`.

### What is not implemented

- Voice input, TTS integration, barge-in, acoustic metrics and browser audio.
- A job-description-to-interview-plan generator.
- A production web interface or remote service.
- Durable command serialization, idempotency or atomic event replay.
- A general agent framework. This is intentionally not planned as the next step.

## 2. Architectural principles

### 2.1 The model proposes; Python decides

The model returns a schema-constrained object with four required fields:

| Field | Meaning | Final authority |
|---|---|---|
| `act` | Proposed action: `advance`, `probe`, `reask`, `clarify`, `skip` or `end` | Python may preserve, downgrade, upgrade or replace it |
| `say` | Proposed next sentence | Guards may strip, shorten, regenerate or replace it |
| `ok` | Whether the current reply fully answers the question | Advisory; its influence is model-profile dependent |
| `ask` | Candidate question copied verbatim, otherwise empty | Grounded against the utterance before use |

Python alone owns the consequences of an action. It verifies stop and skip intent, constrains
follow-ups, decides when evidence is complete, records the transition and updates durable state.

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

### 2.4 Local-first and standard-library-only runtime

The runtime requires Python 3.12 but has no third-party runtime dependencies. It uses `asyncio`,
`urllib`, `json`, dataclasses and local files. Pytest and research/audio dependencies are optional.
LM Studio is the only live external process, reached on `http://127.0.0.1:1234`.

## 3. Runtime topology

```text
Process A: terminal application                    Process B: LM Studio
-----------------------------------------------   -------------------------------
app.cli                                            local model alias
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
- `/api/v0/models` supplies the loaded model and model catalogue used to resolve aliases.

## 4. Component map

### 4.1 Runtime modules

| Module | Responsibility | Main inputs | Main outputs |
|---|---|---|---|
| [`app/cli.py`](../app/cli.py) | Terminal entry point, preflight, warm-up and interview loop | Plan path, stdin, LM Studio | Candidate speech and session paths |
| [`app/runner.py`](../app/runner.py) | Owns the turn loop, precedence, state transitions and dispatch | Candidate utterance, plan, provider, state | `TurnOutcome`, persisted turn |
| [`app/contract.py`](../app/contract.py) | Six-action schema, prompt and severity utility | Current question, answer, summary | Structured model request |
| [`app/provider.py`](../app/provider.py) | LM Studio transport, metrics, posteriors and alias resolution | System/user prompts and schema | `Completion` or `ProviderError` |
| [`app/intent.py`](../app/intent.py) | Clause-aware control parsing | Candidate utterance | stop, continue, skip or unclear |
| [`app/direction.py`](../app/direction.py) | Separates candidate questions from answers | Candidate utterance | Role decision and optional answer prefix |
| [`app/guards.py`](../app/guards.py) | Validates model proposal and sanitises speech | Raw model JSON and utterance | `Guarded` effective proposal |
| [`app/focus.py`](../app/focus.py) | Chooses a missing evidence/request type | Answer, criteria, used focuses | Focus instruction or fallback line |
| [`app/budget.py`](../app/budget.py) | Per-question allowance and shared overflow pool | Phase cap, pool and progress | `Allowance` |
| [`app/history.py`](../app/history.py) | Maintains a short summary of completed questions | Closed questions and answers | Prompt history |
| [`app/result_check.py`](../app/result_check.py) | Conservative pacing-only result check | Extracted result quote | Whether text states change/completion |
| [`app/session.py`](../app/session.py) | Plan validation, state types and local persistence | Plan and `SessionState` | JSON/JSONL session files |
| [`app/provenance.py`](../app/provenance.py) | Best-effort reproducibility snapshot | Git, Python, model metadata | Revision, contract and environment fields |
| [`app/observe.py`](../app/observe.py) | Grounded quote extraction and observation cache | Completed answers and shape | `Observation` objects |
| [`app/score.py`](../app/score.py) | Deterministic criterion arithmetic | Observations and criteria map | `QuestionScore` and `Report` |
| [`app/report.py`](../app/report.py) | Evidence-led candidate feedback | Scores, observations, close reasons | Plain-text report |
| [`app/depth_signals.py`](../app/depth_signals.py) | Regex facts used by focus and observations | Answer text | Depth-signal booleans |

### 4.2 Configuration and tools

| Area | Role |
|---|---|
| [`config/interview_swe_general.json`](../config/interview_swe_general.json) | Current plan, phases, question text, caps, focus ladders and rubric metadata |
| [`tools/live_candidate.py`](../tools/live_candidate.py) | Turn-at-a-time human-driven harness with disk state; least scripted drift |
| [`tools/stage1_long.py`](../tools/stage1_long.py) | Scripted 14-question session; use `--pin` when fixed navigation is required |
| [`tools/stage1_replay.py`](../tools/stage1_replay.py) | Recorded-session replay used to isolate navigation drift |
| [`tools/stage2_report.py`](../tools/stage2_report.py) | Offline extraction, scoring and report generation |
| [`tools/render_transcript.py`](../tools/render_transcript.py) | Human-readable transcript page |
| [`tools/render_report.py`](../tools/render_report.py) | Rendered report output |
| `tools/tier1_*`, `tools/tier2_*` | Experimental and calibration harnesses; consult [`tools/README.md`](../tools/README.md) before use |

## 5. Session start, end to end

`app.cli.run()` establishes the runtime in this order:

1. Create an `LMStudio` provider using the stable model alias.
2. Query loaded models and resolve the alias to the underlying model key where possible.
3. Run the canary unless disabled. It checks prefill time, decode throughput and transport
   overhead separately.
4. Load and validate the interview plan.
5. Select the model-specific `Speech` profile.
6. Warm the real turn system prompt so the first candidate turn is not a cold-cache measurement.
7. Capture provenance and create the session directory.
8. Construct `Runner` with an injected per-answer observation function.
9. Ask the current scripted question.
10. Repeatedly read one non-empty utterance and call `Runner.submit()`.
11. Print only candidate-safe `Spoken` fields.
12. On completion, print status and file locations. Ctrl+C records an abandoned checkpoint.

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
2. The phase's declared rubric criteria.
3. The phase-specific focus ladder.
4. A global fallback ladder.

Used focuses are excluded, preventing the same request type from consuming multiple turns. If the
candidate explicitly has no example, focus steering is disabled and rephrasing is left to `reask`.

### 6.5 Ask the model for one constrained proposal

The request combines the system contract, optional focus instruction, completed-question summary,
current scripted question and candidate utterance. The provider requests strict JSON and records an
action posterior from the enum token position.

### 6.6 Run proposal guards

`guards.apply()` performs the following effective pipeline:

1. Invalid or missing JSON becomes a regenerating `probe` fallback.
2. Invented questions on closing actions are removed; an `advance`/`ok=false` contradiction may
   become `probe` depending on the speech profile.
3. Ungrounded `end`, `clarify` and `skip` actions are downgraded.
4. Candidate-grounded refusal and cannot-answer language upgrades eligible actions to `skip` and
   `reask` respectively.
5. A repeated probe/reask requests one regeneration.
6. Candidate-text echoes and prompt labels are removed.
7. Hedged openings are rewritten more directly.
8. Closing-action speech is discarded.
9. Multi-sentence speech keeps the actual question where possible, then applies a hard character
   cap.

### 6.7 Bound retry and speech adaptation

There are at most two model calls for a turn.

- A repetition or malformed first response gets one regeneration.
- For a configured word cap, an overlong or off-focus line gets one targeted retry. The retry is
  accepted only if it keeps the same action, meets the word cap and fixes the focus miss.
- A failed retry falls through to deterministic focus substitution or handler fallback.

The active profiles are:

| Model family | Exemplars | Substitute focus | Repeated line closes | Trust `ok` | Word cap |
|---|---:|---:|---:|---:|---:|
| Default/unknown | yes | yes | yes | yes | none |
| Granite | yes | yes | yes | no | none |
| Yi | no | yes | yes | yes | none |
| EXAONE | yes | yes | yes | no | 15 words |

These are speech/advisory adaptations only. Consent and policy rules do not vary by model.

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
7. Off-focus model speech is either retained, retried or replaced according to the model profile.

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
| Gives a partial answer | focus -> model -> guards -> budget | `probe` with a bounded question |
| Gives no example but remains willing | cannot-answer vocabulary -> guard upgrade | `reask` |
| Refuses only this question | refusal vocabulary -> guard upgrade | `skip` |
| Asks what the question means | clarification detector -> runner upgrade | `clarify` without spending probe budget |
| Asks about the role mid-answer | direction routing; answer prefix may be kept | defer the question and keep assessment channels separate |
| Requests to stop | stop detector -> confirmation state | `end` only after grounded confirmation |
| Gives an ambiguous confirmation | narrow once, then preserve session | `clarify`/continue, never guessed end |
| Model repeats itself | regeneration once, then profile fallback/close | bounded liveness |
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
- model-specific speech profile.

`SessionState` owns durable-domain state: session identity, status, turns and closed questions.

### 9.2 On-disk layout

```text
data/sessions/<session-id>/
  session.json       session metadata, plan snapshot, provenance and closed-question state
  transcript.json    every committed turn in candidate/interviewer order
  decisions.jsonl    append-only effective decision and diagnostic record per turn
```

Important decision fields include candidate utterance, effective action and speech, guard names,
semantic close reason, requested/actual focus, replaced model line, budgets, posterior, usage,
latency, model-call count, exact rendered prompt and timestamp.

### 9.3 Provenance

Each session snapshot attempts to record:

- Git revision and dirty suffix;
- hash of the system prompt and turn schema;
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
| Invalid model JSON | Convert to probe and allow one regeneration | Safe fallback, possible generic wording |
| Model proposes ungrounded end/skip | Deterministic grounding downgrades action | Session/question remains open |
| Ambiguous stop reply | Narrow once; do not guess | One extra control turn |
| Repeated speech | One regeneration, then bounded fallback/close | No infinite wording loop |
| Overlong/off-focus EXAONE speech | One targeted retry, then template | Bounded latency and sentence length |
| Background live observation failure | Swallowed by `_settle()` | Adaptive pacing loses one evidence update |
| Corrupt observation cache | Ignore and re-extract | Extra offline model work |
| LM Studio unavailable at preflight | CLI refuses to start | No session begins |
| Provider failure during a normal turn | Propagates to CLI's provider handler | Current process exits; recovery is limited to saved files |
| Ctrl+C/EOF | Mark abandoned and checkpoint | Transcript retained |

## 12. Testing and evaluation architecture

At this snapshot, pytest collects 262 tests:

| Module | Collected tests | Main concern |
|---|---:|---|
| `test_guards.py` | 58 | Decision grounding and speech hygiene |
| `test_intent.py` | 26 | Clause-aware stop/skip/continue parsing |
| `test_nfr.py` | 7 | Architectural and non-functional constraints |
| `test_observe.py` | 31 | Extraction grounding, cache and observation shapes |
| `test_persistence.py` | 11 | Plan validation, files and provenance |
| `test_provider.py` | 9 | Transport, posterior and model identity |
| `test_report.py` | 8 | Feedback selection, thresholds and rendering |
| `test_runner.py` | 112 | Turn precedence, pacing, routing and state |

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

## 13. Current limitations and architecture risks

These are current-code observations, not claims that planned future work has shipped.

### High: replay and recovery are incomplete

The decision log records the effective turn and exact rendered user prompt, but it does not retain a
complete immutable envelope for every raw model attempt. Two-call turns aggregate to a call count and
final completion. There is no session restore function that rebuilds runner state by replaying events.

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

### Low: documentation can drift faster than the measured code

The root README still reports 224 tests while the current suite collects 262. Some persistence comments
describe question-boundary checkpoints while the runner calls the snapshot after each turn.

Improvement: update counts from commands, not memory, and keep architecture claims tied to a revision.

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
lms load granite-4.1-3b --context-length 8192 --identifier mockingbird-llm -y
```

The documented alias is stable, while the provider resolves and records the underlying model key.

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
3. `decisions.jsonl` for effective policy, guards, focus, model telemetry and prompt.
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
| Speech profile | Model-specific wording/advisory settings; never consent policy |
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
5. `tools/README.md` for harness suitability.
6. Tests for intended invariants.
7. The research log and plan for why a choice exists, not as proof that it is still implemented.

The companion [`architecture-explorer.html`](architecture-explorer.html) presents the same system as
interactive component, turn-path, phase and data-lineage views.
