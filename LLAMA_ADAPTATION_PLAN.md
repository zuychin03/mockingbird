# Llama 3.2 Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Llama 3.2 3B a measured, model-specific 20-word speech profile and retain more useful model-authored probes without weakening Mockingbird's action, consent, pacing, or focus safeguards.

**Architecture:** Fast-forward the historical `llama-adaptation` branch to the committed Granite 4.2 harness, then diverge through an explicit `LLAMA` `Speech` profile. Establish Llama's behaviour before and after the cap, audit raw-versus-spoken questions, and allow broader semantic retention or contradictory-question promotion only when fresh fixed-turn and live evidence clears the gates below. Compare the selected Llama candidate with Granite 4.2 under identical model, power, context, seed, and candidate protocols.

**Tech Stack:** Python 3.12 standard library, pytest 9.x, LM Studio OpenAI-compatible local API, existing `Runner`/`Speech`/`focus`/`guards` modules, ignored Tier 1 and Stage 1 research harnesses.

**Spec:** User-approved Llama adaptation design from 27/08/2026. Historical evidence is in `RESEARCH_AND_EXPERIMENTS_LOG.md` sections 9.42, 9.43, and 9.48; the inherited Granite design is `GRANITE4.2_CREATIVE_PROBING_PLAN.md` in the Granite adaptation worktree.

## Global Constraints

- Work only in `.worktrees/llama-adaptation` on branch `llama-adaptation`.
- Use exact model key `llama-3.2-3b-instruct`; do not let the Llama profile match `hermes-3-llama-3.2-3b`.
- Preserve Llama's measured `trust_ok=True`; Granite remains `trust_ok=False`.
- Raise Llama's hard speech limit to 20 words while preserving act-neutral shortening: a retry that changes action is rejected.
- Preserve `substitute_focus`; deterministic templates remain fallbacks for irrelevant, repeated, compound, over-length, or unclassifiable questions.
- Preserve `invented-question-dropped` unless the Llama-only promotion gate passes.
- Preserve `say_raw` and `say_model` so every substitution or dropped model question remains diagnosable.
- Do not fix the separately deferred compound-request or deterministic design-gap focus-accounting defects in this wave.
- Use thinking disabled, context length 8,192, parallelism 1, temperature 0, seed 11, and plugged-in power for every paired model run.
- Do not commit generated sessions, calibration JSON, rendered transcripts, or ignored Tier 1/Stage 1 harnesses.
- Do not commit or add attribution trailers unless the user explicitly requests a commit.
- A faster Llama is not "better" unless it also matches Granite's accuracy, safety, and interview completion gates.

## Evidence Baselines and Selection Rules

Historical Llama evidence is useful for hypotheses, not the product decision: its own profile scored 45/49 with severity 4 in the older screen, completed 7/10 questions in one 22-turn replay, produced zero family crossings, and tended to ask short single questions while advancing sooner than Granite. The modern control to beat is Granite 4.2 on the inherited harness.

Llama reaches parity only when all of these hold on fresh evidence:

- fixed PRODUCT score 49/49, severity 0, zero family crossings, and zero invalid outputs;
- strong live interview closes all 14 questions in at most 18 turns with at most three probes;
- junior-to-mid live interview closes all 14 questions in at most 23 turns;
- zero reasks, family crossings, invalid outputs, repeated focus, or compound spoken requests in the selected live controls;
- manually adjudicated spoken-probe relevance at least 80%;
- canary decode at least 50 tokens/second and decision p90 no more than one second slower than the paired Granite 4.2 run.

Call Llama better only if it clears every parity gate and improves at least two of: decision p90, relevant raw-question retention, template-substitution rate, or live turn efficiency. Otherwise report a tie or the exact trade-off.

---

### Task 1: Restore local research instruments and capture the uncapped Llama baseline

**Files:**
- Copy locally, ignored: `tools/tier1_model_screen.py`
- Copy locally, ignored: `tools/fixtures_v2.py`
- Copy locally, ignored: `tools/stage1_replay.py`
- Copy locally, ignored: `tools/session_script.py`
- Copy locally, ignored: `tools/experiment_profile.py`
- Generate locally, ignored: `data/calibration/llama32-baseline-fixed60.json`
- Generate locally, ignored: `data/sessions/<SESSION_ID>/`

**Interfaces:**
- Consumes: the adjacent main checkout's private research harnesses and the worktree's committed application code.
- Produces: a 60-fixture screen, one 22-turn replay, and raw-versus-spoken evidence under `Speech.for_model("llama-3.2-3b-instruct")` before an explicit Llama cap exists.

- [ ] **Step 1: Copy only the required ignored instruments**

From the Llama worktree, resolve the main checkout from the common Git directory and copy the five named files. Do not copy application code, session data, calibration output, or Exaone experiment settings.

```powershell
$common = git rev-parse --git-common-dir
$repo = Split-Path -Parent $common
$names = @(
  "tier1_model_screen.py", "fixtures_v2.py", "stage1_replay.py",
  "session_script.py", "experiment_profile.py"
)
foreach ($name in $names) {
  Copy-Item -LiteralPath (Join-Path $repo "tools/$name") -Destination "tools/$name"
}
git status --short
```

Expected: the copied harnesses remain absent from `git status` because they are deliberately ignored.

- [ ] **Step 2: Make the replay harness compatible with a profile lacking experimental fields**

Change only the ignored `tools/stage1_replay.py`. Replace its unconditional `dataclasses.replace` call with:

```python
speech = Speech.for_model(key)
overrides = {}
if a.semantic_retention:
    if not hasattr(speech, "semantic_retention"):
        raise RuntimeError("this baseline does not support semantic retention")
    overrides["semantic_retention"] = True
if a.retry_off_focus:
    if not hasattr(speech, "retry_off_focus"):
        raise RuntimeError("this baseline does not support off-focus retry")
    overrides["retry_off_focus"] = True
speech = replace(speech, **overrides) if overrides else speech
```

This is instrument compatibility only and remains ignored.

- [ ] **Step 3: Run the fixed-turn baseline**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/tier1_model_screen.py llama-3.2-3b-instruct `
  --arm llama-uncapped-baseline `
  --out data/calibration/llama32-baseline-fixed60.json
```

Record context, resident memory, TTFT, decode speed, raw/guarded/PRODUCT score, severity, invalid outputs, family crossings, p90 latency, and the resolved speech profile.

- [ ] **Step 4: Run the 22-turn uncapped replay**

The fixed screen leaves Llama loaded. Run:

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/stage1_replay.py --session 1 --expected-model llama-3.2-3b-instruct
```

Record the printed session ID and retain `replay_summary.json`.

- [ ] **Step 5: Audit baseline speech**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/probe_audit.py --session BASELINE_SESSION_ID `
  --out data/calibration/llama32-baseline-probes.json
```

Report retained, substituted, action-conflict, compound, and over-length raw questions separately. Do not infer quality from retention alone.

---

### Task 2: Add the explicit Llama 20-word product profile

**Files:**
- Modify: `tests/test_guards.py:539-545`
- Modify: `app/runner.py:128-167`

**Interfaces:**
- Consumes: `Speech.for_model(model_id: str) -> Speech`.
- Produces: `LLAMA = Speech(trust_ok=True, max_say_words=20)` for the exact Llama 3.2 Instruct family while leaving Hermes and unknown models uncapped.

- [ ] **Step 1: Write the failing behavioural profile test**

Add to `tests/test_guards.py`:

```python
def test_llama_gets_its_measured_resolution_and_twenty_word_cap():
    llama = Speech.for_model("llama-3.2-3b-instruct")
    hermes = Speech.for_model("hermes-3-llama-3.2-3b")

    assert llama.trust_ok is True
    assert llama.max_say_words == 20
    assert hermes.trust_ok is True
    assert hermes.max_say_words is None
```

The production mutation this catches is either losing Llama's `trust_ok=True`, failing to enforce the 20-word hard cap, or accidentally assigning the Llama profile to Hermes.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m pytest tests/test_guards.py::test_llama_gets_its_measured_resolution_and_twenty_word_cap -q
```

Expected: FAIL because Llama currently resolves to `Speech()` with `max_say_words is None`.

- [ ] **Step 3: Implement the minimal exact profile**

In `Speech.for_model`, resolve Llama before returning the default without matching Hermes:

```python
if "llama-3.2-3b-instruct" in m and "hermes" not in m:
    return LLAMA
```

Define beside the other measured profiles:

```python
LLAMA = Speech(trust_ok=True, max_say_words=20)
```

Document that `trust_ok=True` scored better for Llama in the symmetric 9.43 experiment and that 20 is a hard speech guard, not permission to change action.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Run profile and shortening regressions**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m pytest tests/test_guards.py tests/test_runner.py -q
```

Expected: all collected guard and runner tests pass. Any Windows `%TEMP%` ACL-only failure must be rerun outside the sandbox without changing code.

- [ ] **Step 6: Leave the change uncommitted for user review**

```powershell
git diff --check
git status --short
```

Expected tracked changes: `app/runner.py`, `tests/test_guards.py`, and this plan only.

---

### Task 3: Measure the 20-word profile against the uncapped baseline

**Files:**
- Generate locally, ignored: `data/calibration/llama32-cap20-fixed60.json`
- Generate locally, ignored: `data/calibration/llama32-cap20-probes.json`
- Generate locally, ignored: `data/sessions/<SESSION_ID>/`

**Interfaces:**
- Consumes: the explicit Llama profile from Task 2.
- Produces: paired fixed-turn and 22-turn evidence showing whether the hard limit changes decisions, substitutions, retries, latency, or navigation.

- [ ] **Step 1: Repeat the fixed screen under the product profile**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/tier1_model_screen.py llama-3.2-3b-instruct `
  --arm llama-cap20 `
  --out data/calibration/llama32-cap20-fixed60.json
```

- [ ] **Step 2: Repeat the same 22-turn replay**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/stage1_replay.py --session 1 --expected-model llama-3.2-3b-instruct
```

- [ ] **Step 3: Audit the capped replay**

Run `tools/probe_audit.py` as in Task 1 with the new session ID and write `data/calibration/llama32-cap20-probes.json`.

- [ ] **Step 4: Apply the cap acceptance gate**

Keep the 20-word Llama profile only when it introduces:

- no new family crossing or invalid output;
- no PRODUCT score or severity regression;
- no action-changing accepted shortening retry;
- no more than one additional second of decision p90; and
- no increase in compound spoken questions.

Because the user explicitly requested the 20-word limit, a run with zero over-length questions is neutral evidence and keeps the profile; a safety or accuracy regression rejects it.

---

### Task 4: Capture a full junior-to-mid Llama interview and adjudicate creative retention

**Files:**
- Generate locally, ignored: `data/sessions/<LLAMA_JUNIOR_SESSION_ID>/`
- Generate locally, ignored: `data/calibration/llama32-junior-probes.json`
- Modify only if Gate R passes: `app/focus.py:76-98`
- Modify only if Gate R passes: `app/runner.py:118-167, 674-705`
- Test only if Gate R passes: `tests/test_runner.py:880-960, 1401-1425`

**Interfaces:**
- Consumes: raw `say_raw`, final `say`, guard names, `focus_asked`, and `focus_got` from a provenance-enabled live session.
- Produces: either a classifier-only verdict or an opt-in Llama semantic-retention profile justified by actual rejected Llama questions.

- [ ] **Step 1: Load Llama with the matched runtime controls**

```powershell
& "C:\Users\kduy1\.lmstudio\bin\lms.exe" unload --all
& "C:\Users\kduy1\.lmstudio\bin\lms.exe" load llama-3.2-3b-instruct `
  --context-length 8192 --parallel 1 --identifier live-llm -y
```

Confirm `lms ps --json` reports the exact model key, context 8,192, and parallelism 1.

- [ ] **Step 2: Run one adaptive junior-to-mid interview**

Start with:

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/live_candidate.py --start
```

Answer the question actually asked. Initial answers should be 25-60 words, reasonably competent but omit one natural dimension such as metrics, ownership, trade-offs, or failure handling. Follow-up answers should be direct and concise. Do not fabricate refusals or deliberately trigger safety paths.

Continue with `--answer` until all 14 questions close. Record the session ID and render its transcript with `tools/render_transcript.py --live --session SESSION_ID --out data/sessions/SESSION_ID/transcript.html`.

- [ ] **Step 3: Audit raw versus spoken probing**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/probe_audit.py --session LLAMA_JUNIOR_SESSION_ID `
  --out data/calibration/llama32-junior-probes.json
```

For every `off-focus->*` substitution, manually label the raw line as relevant or irrelevant to the current answer, single or compound, fresh or repeated, and classifiable or genuinely generic.

- [ ] **Step 4: Apply semantic-retention Gate R**

Gate R passes only when:

- at least five substituted raw questions are single questions of at most 20 words;
- at least 60% of those are relevant and fresh;
- one bounded phrase family accounts for at least three useful rejected lines;
- none of the useful lines asks for unknowable information; and
- retaining them would not repeat a focus already used on that question.

If fewer than five eligible lines appear, or no bounded phrase family accounts for three, stop without adding semantic-retention code. This is a measured rejection, not an incomplete task.

- [ ] **Step 5: Write failing retention tests only if Gate R passes**

For each accepted phrase family, add one positive runner test using an exact captured Llama line and one adversarial negative using the same keyword in a different request. The positive test must assert the raw line is spoken and added to `focus_used`; the negative must assert substitution remains. Derive the expected focus by hand rather than through `focus.classify`.

- [ ] **Step 6: Verify RED before implementation**

Run only the new tests. Expected: positive cases fail because current classification does not recognise the captured phrase; negative cases already pass.

- [ ] **Step 7: Implement the smallest bounded semantic extension**

Add patterns only for the captured question-shaped phrases. Do not add bare topical nouns, globally disable substitution, or allow more than one focus dimension. If the patterns are valid for every model, extend the shared classifier; otherwise add a default-off `Speech.semantic_retention` flag and enable it only in `LLAMA`.

- [ ] **Step 8: Verify GREEN and the full runner suite**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m pytest tests/test_runner.py tests/test_guards.py -q
```

---

### Task 5: Adjudicate contradictory Llama advance questions without assuming promotion helps

**Files:**
- Generate locally, ignored: `data/calibration/llama32-advance-question-review.json`
- Modify only if Gate A passes: `app/guards.py`
- Modify only if Gate A passes: `app/runner.py`
- Test only if Gate A passes: `tests/test_guards.py`, `tests/test_runner.py`

**Interfaces:**
- Candidate knob: `Speech.promote_advance_question: bool = False`.
- Production default: `False` for Granite, Exaone, Yi, Hermes, and unknown models.
- Llama remains `False` unless both Gate A and the final live controls pass.

- [ ] **Step 1: Extract eligible contradictions from all fresh Llama captures**

Eligible rows have raw `act == "advance"`, raw `ok is False`, exactly one question in `say_raw`, no compound request, at most 20 words, and final guard `invented-question-dropped`.

- [ ] **Step 2: Apply Gate A**

Gate A passes only when at least five eligible questions exist, at least 60% are relevant and fresh, no more than 20% repeat an already-used focus, and none asks for unknowable information. Historical Llama evidence suggested it often emits no question on this contradiction; insufficient examples therefore fail the gate and preserve the current guard.

- [ ] **Step 3: Implement only after Gate A passes**

Follow the opt-in policy boundary from the Granite creative probing plan: only `advance + ok=False + exactly one valid question` may promote to `probe`; `end`, `skip`, `ok=True`, invalid output, stop confirmation, and candidate-question handling remain unchanged. Write and watch the guard and runner tests fail before adding the knob.

- [ ] **Step 4: Keep promotion experimental until the final controls pass**

Do not enable the knob in `LLAMA` during this task. Expose it only through a persisted experimental live profile, then compare it with the classifier-only candidate in Task 6.

---

### Task 6: Run matched Llama and Granite controls and select the product profile

**Files:**
- Generate locally, ignored: `data/calibration/llama32-granite42-fixed60.json`
- Generate locally, ignored: `data/calibration/llama32-granite42-live.json`
- Generate locally, ignored: final Llama and Granite session directories and transcripts
- Modify only when a candidate passes: `app/runner.py`, plus exact tests protecting the selected profile

**Interfaces:**
- Compares `llama-3.2-3b-instruct` with `granite-4.2-3b` under their own resolved `Speech` profiles.
- Produces: a selected Llama profile or an evidence-backed rejection, never a forced winner.

- [ ] **Step 1: Run the paired fixed screen**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  tools/tier1_model_screen.py llama-3.2-3b-instruct granite-4.2-3b `
  --arm final-product-profiles `
  --out data/calibration/llama32-granite42-fixed60.json
```

Require 49/49 PRODUCT, severity 0, zero family crossings, and zero invalid output for parity.

- [ ] **Step 2: Run the strong Llama control**

Use complete 70-120 word answers that include context, ownership, steps, and outcome. Require all 14 questions within 18 turns, at most three probes, zero reasks, zero repeated focus, and zero compound spoken requests.

- [ ] **Step 3: Repeat the junior-to-mid protocol with the selected Llama candidate**

Require all 14 questions within 23 turns, zero reasks/crossings/invalid output/repeated focus/compound spoken requests, and at least 80% relevant spoken probes.

- [ ] **Step 4: Run the matched Granite 4.2 junior control**

Load `granite-4.2-3b` with the same 8,192 context, parallelism 1, alias, temperature, seed, and plugged-in power. Use the same answer-quality protocol while answering the questions actually asked.

- [ ] **Step 5: Select without forcing a winner**

Reject any Llama candidate that misses a safety, accuracy, or completion gate. Among passing candidates prefer, in order: higher relevant raw-question retention, lower template rate, fewer repeated/generic questions, fewer live turns, then lower p90 latency. Call Llama better only when it clears every Granite parity gate and improves at least two of those product axes.

- [ ] **Step 6: Record exact evidence**

Write the selected profile, rejected variants, exact session IDs, fixture metrics, canary metrics, live metrics, and manual probe adjudications to `data/calibration/llama32-granite42-live.json`.

---

### Task 7: Complete verification and hand off for user-owned commit

**Files:**
- Verify all tracked changes
- Update locally, ignored if present: `RESEARCH_AND_EXPERIMENTS_LOG.md`

**Interfaces:**
- Produces: reviewable uncommitted code, tests, plan, transcripts, and an evidence-backed Granite comparison.

- [ ] **Step 1: Run static and focused checks**

```powershell
git diff --check
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m compileall -q app tools tests
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m pytest tests/test_guards.py tests/test_runner.py tests/test_probe_audit.py -q
```

- [ ] **Step 2: Run the full suite outside the Windows temp ACL restriction**

```powershell
& "C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird\.venv\Scripts\python.exe" `
  -m pytest -q -p no:cacheprovider
```

Require every collected test to pass. Sandbox-only `%TEMP%` permission errors are not application failures but must be rerun outside the sandbox.

- [ ] **Step 3: Verify repository scope**

```powershell
git status --short
git diff --stat
git diff -- app/runner.py app/focus.py app/guards.py tests
```

Confirm no session, transcript, calibration JSON, model file, or private harness is staged or tracked.

- [ ] **Step 4: Report rather than commit**

Provide the exact tests, session links, fixture comparison, latency comparison, selected/rejected profile settings, and remaining limitations. Leave the branch uncommitted until the user asks for a concise commit with no co-authoring.

## Completion Criteria

The wave is complete only when:

- Llama resolves to its own `trust_ok=True`, 20-word profile without affecting Hermes;
- the cap has paired before/after evidence and accepted retries never change action;
- raw and spoken questions remain independently auditable;
- broader creative retention or advance-question promotion is enabled only after its stated gate passes;
- all selected-profile fixtures, strong live, and junior live gates pass;
- Granite 4.2 is rerun as a matched control on the same plugged-in machine;
- the final verdict distinguishes speed, fixed accuracy, interview completion, and creative speech quality; and
- generated artefacts remain ignored and commits remain user-owned.

## Stage 2 Closure Addendum — 28/08/2026

This addendum records the final product decisions without rewriting the historical experiment
plan above. It supersedes only the completion gates that changed after the measured Llama
controls and the decision to support one LLM.

The accepted Stage 2 gates are:

- Llama speech may contain at most 25 words. The action-preserving shortening retry and raw
  speech provenance remain mandatory.
- The junior-to-mid control must complete all 14 questions within 25 turns, with no reask,
  family crossing, invalid action, repeated focus, or compound spoken request.
- The strong control must complete all 14 questions within 18 turns. Probe count is no longer
  a hard gate: additional probes are acceptable when they are relevant, single-focus, and
  distinct from every focus already used on that question.
- The design question has a hard two-follow-up cap and cannot borrow from the shared reserve.
- A reserve token is charged only when its probe or reask is actually dispatched. A proposal
  suppressed by observation pacing costs nothing.
- Granite is retained as historical comparison evidence, not as a release gate. Mockingbird
  now accepts only the exact `llama-3.2-3b-instruct` model identifier.

Final Stage 2 controls:

| Control | Session | Result | Probe behaviour |
|---|---|---|---|
| Junior-to-mid | `20260827-182435-73bff5` | 14/14 in 25 turns | 10 probes; nine retained model lines and one focus template |
| Strong | `20260827-183849-7ba120` | 14/14 in 18 turns | Four distinct probes: context, measurement, steps, and reasoning |

The Stage 2 implementation gate passed with `278 passed`, Python byte-compilation, and
`git diff --check`. Generated sessions and rendered transcripts remain ignored. Stage 2 is
closed when the commit containing this addendum and its runner/guard regressions is integrated
into `main` and pushed.

The following are non-blocking follow-up candidates rather than Stage 2 exit criteria:

- retain more useful Llama-authored questions that the bounded focus classifier currently
  substitutes;
- avoid past-experience wording when probing a hypothetical design answer.
