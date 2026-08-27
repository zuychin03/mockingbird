# Exaone Semantic Retention Design

**Date:** 26/08/2026

**Status:** Approved for implementation on 26/08/2026

**Branch:** `exaone-adaptation`

## Purpose

Improve Exaone 3.5 2.4B's product interview behaviour using the lessons from the Granite 4.2 adaptation, while preserving the controls that currently protect candidates from irrelevant, repeated, compound, and over-length questions.

The work is successful only if Exaone becomes measurably closer to Granite on the same laptop, model settings, candidate protocols, and product profile. Reducing template usage is not success by itself.

## Current Evidence

### Exaone baseline

The established Exaone Q4/Q5 replay baseline produced:

- 14 correct actions out of 22;
- severity-weighted loss 12;
- one family crossing;
- four of ten questions closed; and
- ten focus substitutions in the original Q4 run.

The committed Exaone profile uses `trust_ok=False` and `max_say_words=15`. A shortening retry previously produced one strong Q4 result: 15/22 actions, severity 7, zero family crossings, no over-length spoken probes, and 14 distinct lines out of 15. Because speech enters later model history, this result must be reproduced rather than treated as a permanent property of the profile.

### Unfinished focus-retry experiment

The branch contains uncommitted work in `app/runner.py` and `tests/test_runner.py` that retries any short or long question the focus classifier cannot recognise. Session `20260826-031120-a16d44` showed:

- the same 14/22 actions, severity 12, one family crossing, and four questions closed;
- 40 model calls across 22 turns;
- six retained retries and twelve rejected retries;
- eleven substitutions across fifteen spoken probe/reask turns; and
- decision latency p90 of approximately 3.06 seconds.

The experiment did not improve navigation or action quality and did not materially solve template dependence. Its main failure is architectural: it treats every classifier miss as a model wording failure, even when the question is relevant but uses vocabulary outside the current classifier.

### Granite 4.2 reference

The comparable Granite 4.2 live controls are:

- strong candidate, session `20260826-200541-27e1fd`: 14 questions completed in 17 turns, two probes, zero reasks, one focus substitution;
- junior-to-mid candidate, session `20260826-203719-90e74f`: 14 questions completed in 23 turns, seven probes, zero reasks, four focus substitutions; and
- no family crossings in either live control.

These sessions are product references, not immutable golden transcripts. The final comparison must rerun both models under matched conditions because model state, power, and speech history can change results.

## Problem Statement

Exaone's raw questions fail for three different reasons that the current decision record partially conflates:

1. **Semantic classifier miss:** a useful question asks a fresh dimension using wording such as “what led to your disagreement” or “how you communicated your concerns”, but `focus.classify` does not recognise it.
2. **Real speech defect:** the line is generic, repeated, compound, or longer than the Exaone speech cap.
3. **Action/speech contradiction:** the model chooses `advance` or `end` while also writing a question.

The existing `say_model` field records only a line replaced by the final focus template. It does not reliably record the initial line, a retry line, why a retry was rejected, or a question removed by an action guard. Without that provenance, a lower substitution rate can hide worse questions and a failed retry cannot be diagnosed.

## Goals

- Preserve every model-authored speech attempt before guards or substitutions change it.
- Retain short, relevant, single-focus Exaone questions when they ask a fresh answer dimension.
- Keep deterministic templates as the fallback for generic, repeated, compound, unclassifiable, or over-length questions.
- Determine empirically whether an off-focus retry or contradictory advance-question promotion helps Exaone.
- Keep Granite 4.1 and Granite 4.2 behaviour stable unless a shared semantic correction is independently valid for both.
- Compare Q4 and Q5 symmetrically under their resolved product profiles and matched live conditions.

## Non-goals

- Removing focus substitution globally.
- Moving per-turn focus instructions into the user prompt.
- Optimising for fixture action accuracy while ignoring live completion and speech quality.
- Making Exaone imitate Granite's exact wording or question sequence.
- Changing interview planning, scoring, observation extraction, TTS, or UI behaviour.
- Committing generated sessions, calibration outputs, transcripts, or the existing untracked architecture documents.

## Chosen Approach

Use an instrumentation-first, semantic-retention design. Correct shared candidate-language routing, make every speech transformation auditable, expand focus recognition only for bounded question-shaped semantics, and test permissive policies as disabled experimental arms before selecting a production profile.

This is preferred over two alternatives:

### Rejected: port Granite's creative policy wholesale

Granite 4.2 produced concise, specific invented questions often enough to justify an audit. Exaone more often produces generic or compound elaboration requests and averaged substantially longer raw substituted lines. Enabling the same policy without Exaone-specific evidence would lower template usage while potentially lowering interview quality.

### Rejected: stronger prompt forcing

Moving focus steering into the user prompt increased apparent focus compliance but collapsed Exaone's `advance` behaviour. Prompt changes are also session-wide changes because altered speech enters history. This avenue remains closed unless a future isolated experiment supplies contrary evidence.

## Architecture

### 1. Shared candidate-language corrections

Apply the model-independent candidate-language fixes already validated on `granite-4.2-adaptation` commit `64027e3`:

- segmented clarification choices such as “Quickly meaning what, a few days? A sprint?”;
- trailing uncertainty such as “it is hard to say” when no concrete recovery follows; and
- missing-process answers such as “we did not really have formal on-call” without a subsequent action.

These corrections change the interpretation of candidate speech, not model speech. They must pass Exaone, Granite 4.1, and Granite 4.2 guard fixtures before being treated as shared.

### 2. Speech provenance

Every model-backed decision record gains two fields:

```json
{
  "say_raw": "the model line that fed the final guarded turn",
  "speech_attempts": [
    {
      "kind": "initial",
      "act": "probe",
      "say": "Could you elaborate on how you communicated the concern?",
      "accepted": false,
      "reason": "off_focus"
    },
    {
      "kind": "focus_retry",
      "act": "probe",
      "say": "How did you communicate the concern to the team?",
      "accepted": true,
      "reason": "fresh_focus"
    }
  ]
}
```

`say_raw` is the exact line from the model decision that feeds the final guarded turn. If a retry is accepted, it is the accepted retry line. If a retry is rejected and the original decision remains active, it remains the original line. Deterministic turns store `null`.

`speech_attempts` records every model speech attempt in call order. Its allowed `kind` values are `initial`, `regeneration`, `shortening_retry`, and `focus_retry`. Its allowed `reason` values are `selected`, `invalid`, `repeated`, `over_length`, `off_focus`, `compound`, `action_changed`, and `fresh_focus`.

The existing `say_model` field remains backward compatible and continues to mean “the effective model line replaced by a focus template”. It is not repurposed.

### 3. Raw-versus-spoken audit

A standard-library audit reads `decisions.jsonl` and reports:

- raw question count;
- retained model-authored question count and rate;
- template substitution count and rate;
- action-conflict removals and promotions;
- accepted and rejected retries by reason;
- raw and spoken multi-question counts;
- raw and spoken over-15-word counts;
- repeated focus and repeated wording counts;
- focus-classifier misses; and
- a per-turn raw/attempted/spoken trace.

The audit rejects mixed old/new sessions when a model-backed row lacks the required provenance. It measures speech transformation, not interview quality; relevance remains a separately adjudicated metric.

### 4. Bounded semantic retention

The first product candidate expands focus recognition for question-shaped Exaone language rather than disabling substitution. Candidate pattern families include:

- `REASON`: “what led to…”, “what concerns led…”, and “what influenced…”;
- `STEPS`: “how you communicated…”, “how you handled…”, “how you identified…”, and “how you ensured…”;
- `CHALLENGE`: “what issues arose…”, “what challenges did you face…”, “what breaks…”, and bounded outage/unavailability forms; and
- `ROLE`: explicit ownership forms only, such as “which part did you own” or “what was your contribution”.

Bare words such as `issue`, `down`, `handled`, `team`, or `specific` are insufficient. A new pattern must:

1. classify a question-shaped request rather than candidate answer vocabulary;
2. identify exactly one focus, unless the line genuinely asks two dimensions and is therefore rejected as compound;
3. pass contextual-negation and declarative adversarial cases; and
4. leave the recorded Granite reference turns unchanged, or be separately justified as a shared correction.

The existing runner rule remains authoritative: any fresh unused focus may keep the model's wording, even when it differs from the requested focus. A line is substituted when it has no fresh recognised focus, repeats an already used focus, exceeds the model's word cap after its allowed shortening attempt, or violates the one-question contract.

### 5. Experimental off-focus retry

The unfinished eager focus retry becomes a disabled `Speech` capability rather than production behaviour. It may be tested only after provenance and semantic classification are in place.

The retry is eligible only when all of these are true:

- the action is `probe` or `reask`;
- the line contains exactly one question;
- the line is within the profile's word cap;
- no fresh focus is recognised;
- the line is not a repeat; and
- no other retry has already occurred on the turn.

The retry is accepted only when it preserves the action, asks exactly one short question, and introduces a fresh recognised focus. Otherwise the original line proceeds to the existing template fallback. The turn remains capped at two model calls.

The capability is rejected for production unless it reduces substitutions by at least 20 percentage points on model-authored probe/reask turns, retains at least 60% of its retries, adds no family crossing, and keeps decision p90 within one second of the classifier-only candidate.

### 6. Experimental action-question promotion

Exaone's `trust_ok=False` profile currently drops questions attached to `advance`. No promotion is implemented until a provenance-enabled run supplies at least five eligible examples.

An eligible example is `advance + ok=false + exactly one raw question` where the final guard recorded `invented-question-dropped`. A question is usable only when it is relevant, fresh, no more than 15 words, not compound, and does not ask for unknowable information.

Promotion may be implemented behind a disabled model-profile flag only when at least 60% of eligible examples are usable, no more than 20% repeat an existing focus, and none crosses question families. It remains disabled for Granite 4.1, Granite 4.2, Yi, Llama, Hermes, and unknown models unless separately validated.

### 7. Model-specific profile selection

Q4 is the primary Exaone candidate because it is lighter and previously matched Q5's navigation at lower cost. Q5 remains a required comparison arm.

Every harness must resolve `Speech.for_model(model_id)`. Tests must pin:

- Exaone Q4 and Q5 to `trust_ok=False` and `max_say_words=15`;
- experimental flags off by default;
- Granite 4.1 and Granite 4.2 to their existing production values; and
- unknown models to the current default profile.

No result produced under a default-only profile is admissible in the final model comparison.

## Data Flow

For each model-backed candidate answer:

1. The runner selects the desired next focus from candidate evidence and unused focus history.
2. The model returns a structured action and speech line.
3. The runner records the initial speech attempt before transformation.
4. Deterministic action and safety guards run.
5. At most one eligible speech retry may run; every attempt and disposition is recorded.
6. The focus classifier determines whether the effective line asks a fresh dimension.
7. The effective line is retained or replaced with an unused deterministic template.
8. The final spoken line, raw effective line, all attempts, focus metadata, guards, latency, and model-call count are appended to `decisions.jsonl`.
9. Offline audit derives speech metrics without calling a model.
10. Replay and live harnesses measure action, navigation, completion, speech quality, and latency separately.

## Experiment Sequence

One variable changes per arm:

1. **Committed Exaone baseline:** current `EXAONE` profile at commit `5e21330`.
2. **Shared guards:** baseline plus the candidate-language corrections from `64027e3`.
3. **Instrumented control:** shared guards plus provenance and audit, with no speech-policy change.
4. **Classifier-only candidate:** instrumented control plus bounded semantic patterns.
5. **Focus-retry candidate:** classifier-only plus the opt-in off-focus retry.
6. **Promotion candidate:** created only if the action-question evidence gate passes.

An arm that violates a safety gate is eliminated and is not used as the base for later product selection. Experimental code may remain only when disabled, tested, and needed to reproduce a documented arm; otherwise it is removed before the final product commit.

## Evaluation Protocol

### Fixed controls

- Run the 60 action fixtures against Q4 and Q5 under every product-relevant profile.
- Run both recorded 22-turn replay scripts pinned and unpinned.
- Record raw action, guarded action, product action, severity, family crossings, question drift, speech disposition, focus, latency, and model calls.

### Live controls

Run the same two 14-question candidate protocols used for Granite 4.2:

- a strong candidate who usually supplies complete evidence without prompting; and
- a junior-to-mid candidate who gives plausible 25–60 word answers with naturally incomplete metrics, ownership, or failure analysis.

The candidate answers the interviewer that actually appears. Fixed answers must not be replayed after navigation diverges.

### Matched environment

- Laptop plugged into power.
- LM Studio thinking disabled.
- Context length 8,192.
- Parallelism 1.
- Temperature 0.
- Seed 11.
- One tested chat model loaded at a time.
- Same harness revision, plan, and candidate protocol.
- Canary decode speed recorded before each model run.

## Metrics and Gates

### Non-negotiable safety gates

- Zero family crossings.
- Zero invalid outputs escaping deterministic fallback.
- Zero unguarded `advance` or `end` questions.
- Zero spoken lines containing two independent questions.
- Zero repeated focus within one interview question.
- Candidate stop, skip, clarify, and cannot-answer controls retain their established behaviour.

### Strong-candidate control

- All 14 questions close.
- At most 18 total candidate turns.
- At most three probes.
- Zero reasks.
- No new answer dimension is requested after the answer already supplies it.

### Junior-to-mid control

To be **close to Granite 4.2**:

- all 14 questions close in at most 25 turns;
- at most nine probes and one reask;
- at least 50% of relevant model-authored probe/reask questions are retained;
- at most 50% of model-authored probe/reask questions use templates; and
- manually adjudicated spoken-probe relevance is at least 80%.

To **match Granite 4.2**:

- all 14 questions close in at most 23 turns;
- at most seven probes and zero reasks;
- at least 60% relevant model-authored-question retention;
- at most 40% template substitution; and
- all non-negotiable gates pass.

### Performance gate

On the matched plugged-in run, Exaone's decision p90 must be no more than one second slower than Granite 4.2. Canary speed is diagnostic rather than a winner by itself, but a run with material thermal or power drift must be repeated.

## Selection Rule

Select the final Exaone profile in this order:

1. Reject any arm that fails a non-negotiable safety or completion gate.
2. Prefer the lowest severity-weighted loss on fixed controls.
3. Prefer higher live completion and relevant model-authored-question retention.
4. Break quality ties with fewer repeated or generic questions.
5. Break remaining ties with fewer total turns, fewer model calls, and lower p90 latency.
6. Prefer Q4 when Q4 and Q5 are within one severity point, one live turn, and five percentage points of relevant retention.

If Exaone does not reach the “close” gate, retain its best safe model-specific profile and report the remaining gap. Do not force a claim that it matches Granite.

## Error Handling and Evidence Integrity

- Abort a harness when the loaded model ID differs from the requested model.
- Reject audit input that mixes rows with and without speech provenance.
- Persist the resolved speech profile and experimental flags with live-session state so separate `--answer` processes cannot change policy mid-interview.
- Keep raw and spoken fields distinct; never overwrite diagnostic evidence with a template.
- Treat Windows pytest temporary-directory `PermissionError` as an environment failure only after confirming the traceback is confined to pytest or `tempfile`; rerun outside the managed sandbox.
- Record session IDs immediately and write comparison summaries from persisted decisions rather than terminal-only output.

## Testing Strategy

Implementation follows red-green-refactor cycles:

- provenance tests for initial, accepted-retry, rejected-retry, guard-dropped, and deterministic turns;
- classifier tests for positive question forms plus declarative, contextual-negation, answer-vocabulary, compound, and repeat adversaries;
- runner tests proving fresh questions survive and generic/repeated questions still substitute;
- profile tests proving experimental flags remain Exaone-specific and off by default;
- audit tests covering every speech disposition and rejecting incomplete provenance;
- harness persistence tests for resolved model/profile/flags; and
- the complete project suite after every independently committable behaviour change.

Live sessions validate product behaviour but do not replace automated regression tests.

## Repository and Commit Boundaries

- Work only on `exaone-adaptation`.
- The current uncommitted focus-retry diff is experimental evidence. It must be converted into a disabled, tested arm or removed through an explicit reviewed patch; it must not be accidentally included as production behaviour.
- Do not stage `docs/ARCHITECTURE.md` or `docs/architecture-explorer.html`.
- Do not stage generated `data/` content, live-session state, transcripts, calibration JSON, or private Tier-1 harnesses.
- Keep commits small and independently verifiable: shared guards, provenance/audit, semantic classification, each optional policy arm, and final profile selection are separate commits.

## Deliverables

- Shared candidate-language corrections validated across Exaone and Granite fixtures.
- Complete raw speech-attempt provenance in decision records.
- Raw-versus-spoken audit tool and tests.
- Bounded semantic classifier improvements.
- Evidence-backed decision on the off-focus retry.
- Evidence-backed decision on action-question promotion.
- Matched Q4, Q5, Granite 4.1, and Granite 4.2 comparison report with exact session IDs.
- Strong and junior-to-mid Exaone live transcripts.
- Final calibrated recommendation stating whether Exaone is behind, close to, or matches Granite.

## Acceptance Criteria

The adaptation is complete when:

- every model-backed turn records the effective raw line and all model speech attempts;
- templates remain the fallback for unsafe or low-quality questions;
- selected classifier patterns retain useful Exaone-authored questions without changing established candidate-control behaviour;
- every enabled Exaone policy passes fixed, replay, strong-live, and junior-live gates;
- the full automated suite passes under Python 3.12;
- generated artefacts remain uncommitted; and
- the final comparison makes only claims supported by persisted metrics and transcripts.
