# Granite 4.2 Creative Probing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain more relevant Granite 4.2-authored follow-up questions while keeping deterministic templates and action guards as measured safety fallbacks.

**Architecture:** Preserve every raw model-authored `say` before guards, classify a broader but bounded set of useful failure-mode questions, and audit raw-versus-spoken speech independently from navigation. Keep the current production policy until controlled replay and live-session gates show that a more permissive Granite 4.2 profile improves relevance without repeated probes, family crossings, or strong-candidate over-probing.

**Tech Stack:** Python 3.12 standard library, pytest 9.x, LM Studio OpenAI-compatible local API, existing `Runner`/`Speech`/`focus`/`guards` modules.

**Spec:** User-approved design from the Granite 4.2 live-session review. Local source evidence is in `data/sessions/20260826-200541-27e1fd/` and `data/sessions/20260826-203719-90e74f/`; those generated session artefacts remain ignored.

## Global Constraints

- Work only on `granite-4.2-adaptation` until the final matched Granite 4.1 comparison is complete.
- Preserve the raw model-authored line whenever any guard, focus substitution, shortening retry, or action handler changes what the candidate hears.
- Do not globally disable `substitute_focus`; templates remain the fallback for irrelevant, repeated, compound, or unclassifiable questions.
- Do not remove `invented-question-dropped`. A question emitted with `advance` or `end` is an action/speech contradiction and remains silent unless the explicit promotion gate in Task 4 is satisfied.
- Do not move focus instructions into the user prompt. Keep per-turn focus steering in the system prompt.
- Keep Granite 4.1 behaviour unchanged unless a matched comparison explicitly justifies a shared change.
- Add no runtime dependency; `app/` remains standard-library-only.
- Keep deterministic turns (`candidate-question->noted`, confirmation, skip offer, and closing) distinguishable from model-backed turns.
- Preserve the current local benchmark settings: thinking disabled, context length 8,192, parallelism 1, temperature 0, seed 11, and plugged-in power.
- Do not commit generated sessions, captures, rendered transcripts, calibration JSON, or private `tier1_*` harnesses.

## Evidence Baseline

The strong live session `20260826-200541-27e1fd` completed 14 questions in 17 turns with two probes. The junior-to-mid session `20260826-203719-90e74f` completed 14 questions in 23 turns with seven probes, no reasks, and no family crossings.

The junior-to-mid decision record contains four `off-focus` substitutions:

1. A repeated metrics/feedback-loop question became a useful `CONTEXT` scale template.
2. A forward-looking metrics question became a useful `CONTEXT` setup template.
3. A second repeated metrics question became a useful `STEPS` template.
4. A specific multi-region/Redis-unavailable question became the generic `ALTERNATIVE` template, even though Granite's line was better.

The same run contains nine `invented-question-dropped` events. Their original `say` values are not recorded, so their value cannot be judged from existing artefacts. This is why provenance precedes policy changes.

---

### Task 1: Record raw model speech before every transformation

**Files:**
- Modify: `app/runner.py:497-503`
- Modify: `app/runner.py:667-743`
- Test: `tests/test_runner.py:810-890`

**Interfaces:**
- Consumes: the parsed turn object returned by `Runner._decide()`.
- Produces: decision-record field `say_raw: str | None`; it is the exact `say` from the model decision that feeds the final guarded turn, captured before `guards.apply`, focus substitution, or action handling. Deterministic turns store `None`.
- Preserves: existing `say_model`, whose current meaning remains “the line replaced by a focus template”.

- [ ] **Step 1: Write a failing provenance test**

Add a test that drives an `advance` containing a question through the Granite-style `trust_ok=False` profile and proves the raw question survives in `decisions.jsonl` even though the candidate does not hear it:

```python
def test_the_raw_model_line_survives_an_invented_question_drop(tmp_path):
    from app.runner import Runner, Speech
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    provider = ScriptedProvider([
        d("advance", "Thanks. What did you measure?", ok=False),
    ])
    runner = Runner(provider, PLAN, state, speech=Speech(trust_ok=False))

    run(runner.ask())
    run(runner.submit("I shipped the change."))

    row = json.loads((state.dir / "decisions.jsonl").read_text(
        encoding="utf-8").strip())
    assert row["say_raw"] == "Thanks. What did you measure?"
    assert "invented-question-dropped" in row["guards"]
    assert "?" not in row["say"]
```

- [ ] **Step 2: Run the focused test and verify the missing field**

Run:

```powershell
python -m pytest tests/test_runner.py::test_the_raw_model_line_survives_an_invented_question_drop -q
```

Expected: FAIL with `KeyError: 'say_raw'`.

- [ ] **Step 3: Capture `say_raw` at the correct boundary**

In `Runner.submit`, immediately after the final `_decide()` call and before `guards.apply`, capture:

```python
say_raw = ((raw or {}).get("say") or "").strip() if raw is not None else None
```

Pass `say_raw` through `_dispatch`. Add it to the decision record without changing the spoken `Turn`, action, or question state:

```python
"say_raw": say_raw,
"say_model": say_model,
```

When regeneration replaces the guarded decision, replace `say_raw` with the regenerated call's parsed `say`. When a shortening retry is accepted, replace it with the accepted retry's `say`; when that retry is rejected and the original guarded decision remains active, keep the original `say_raw`. Rejected attempts remain represented by `model_calls` and are outside this feature's raw-versus-spoken comparison.

- [ ] **Step 4: Pin deterministic-turn behaviour**

Add a closing-phase assertion to an existing deterministic-turn test:

```python
assert row["say_raw"] is None
assert row["model_calls"] == 1  # preserve the existing record shape
```

The `model_calls` value remains backward compatible even though the deterministic completion carries zero tokens and zero latency.

- [ ] **Step 5: Run provenance and persistence tests**

Run:

```powershell
python -m pytest tests/test_runner.py tests/test_persistence.py -q
```

Expected: all collected tests pass.

- [ ] **Step 6: Commit the provenance change**

```powershell
git add app/runner.py tests/test_runner.py
git commit -m "Record raw probe speech"
```

---

### Task 2: Recognise useful failure-mode questions as fresh focus

**Files:**
- Modify: `app/focus.py:76-95`
- Test: `tests/test_runner.py:810-890`

**Interfaces:**
- Consumes: `focus.classify(say: str) -> set[str]`.
- Produces: `CHALLENGE` for bounded failure-mode questions, allowing the existing `fresh = focus.classify(g.say) - self.focus_used` path to retain Granite's wording.
- Does not change: template selection, focus order, follow-up budget, action choice, or Granite 4.1 profile resolution.

- [ ] **Step 1: Write focused classification tests**

Add:

```python
def test_failure_mode_questions_are_a_fresh_challenge():
    for said in (
            "What happens if Redis is unavailable?",
            "How would you handle an outage in one region?",
            "What breaks first when this is under real load?",
            "How does the design behave when the shared store is down?"):
        assert "CHALLENGE" in focus.classify(said), said


def test_failure_words_in_an_answer_do_not_create_a_challenge_question():
    said = "Redis was unavailable during the incident. What did you do next?"
    assert "STEPS" in focus.classify(said)
    assert "CHALLENGE" not in focus.classify(said)
```

- [ ] **Step 2: Write the runner-level retention test**

```python
def test_a_specific_failure_mode_question_beats_the_alternative_template(tmp_path):
    plan = {
        "id": "failure-mode-probe",
        "phases": [{
            "id": "design",
            "answer_shape": "open",
            "probe_budget": 2,
            "scored": False,
            "observation_shape": "star",
            "focus_ladder": ["ALTERNATIVE", "CHALLENGE"],
            "questions": ["How would you design a rate limiter?"],
        }],
    }
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(plan)
    runner = Runner(ScriptedProvider([
        d("probe", "How would you handle multiple regions if Redis is unavailable?")
    ]), plan, state)

    run(runner.ask())
    outcome = run(runner.submit("I would use a Redis fixed-window counter."))

    assert outcome.spoken.text == (
        "How would you handle multiple regions if Redis is unavailable?")
    assert "CHALLENGE" in runner.focus_used
    assert not any("off-focus" in guard for guard in state.turns[-1].guards)
```

- [ ] **Step 3: Run the tests and verify both fail**

Run:

```powershell
python -m pytest tests/test_runner.py -k "failure_mode or specific_failure" -q
```

Expected: FAIL because current `CHALLENGE` patterns do not recognise the failure-mode wording.

- [ ] **Step 4: Add bounded question-shaped patterns**

Extend only `CHALLENGE` with question structures rather than bare words:

```python
r"what (?:happens|would happen) (?:if|when)|"
r"how (?:would|do) you handle .*(?:unavailable|down|outage)|"
r"what breaks first|"
r"how (?:does|would) .* behave (?:if|when)|"
r"failure mode"
```

Do not add bare `failure`, `unavailable`, `load`, `down`, or `outage`; those terms also occur in candidate answers and unrelated questions.

- [ ] **Step 5: Run the focused and full suites**

Run:

```powershell
python -m pytest tests/test_runner.py -q
python -m pytest -q -p no:cacheprovider
```

Expected: all 112 runner tests and all 267 current project tests pass, plus the newly added tests.

- [ ] **Step 6: Commit the classifier change**

```powershell
git add app/focus.py tests/test_runner.py
git commit -m "Keep useful failure probes"
```

---

### Task 3: Add a raw-versus-spoken probing audit

**Files:**
- Create: `tools/probe_audit.py`
- Create: `tests/test_probe_audit.py`
- Modify: `README.md:80-105`

**Interfaces:**
- Produces: `audit(rows: list[dict]) -> dict[str, object]`.
- CLI: `python tools/probe_audit.py --session SESSION_ID --out PATH`.
- Input: `data/sessions/<SESSION_ID>/decisions.jsonl` containing Task 1's `say_raw` field.
- Output: JSON under `data/calibration/`, which remains ignored.

- [ ] **Step 1: Write an audit unit test with all disposition classes**

```python
from tools.probe_audit import audit


def test_probe_audit_separates_retained_substituted_and_action_conflicts():
    rows = [
        {"turn": 0, "act": "probe", "say_raw": "What did you measure?",
         "say": "What did you measure?", "guards": [],
         "focus_asked": "MEASURE", "focus_got": ["MEASURE"]},
        {"turn": 1, "act": "probe", "say_raw": "Tell me about the weather?",
         "say": "What was the setup around it?",
         "guards": ["off-focus->context"],
         "focus_asked": "CONTEXT", "focus_got": ["CONTEXT"]},
        {"turn": 2, "act": "advance", "say_raw": "What happened next?",
         "say": "", "guards": ["invented-question-dropped"],
         "focus_asked": "STEPS", "focus_got": []},
    ]
    result = audit(rows)
    assert result["retained"] == 1
    assert result["substituted"] == 1
    assert result["action_conflicts"] == 1
    assert result["raw_question_total"] == 3
```

- [ ] **Step 2: Run the test and verify the missing module**

Run:

```powershell
python -m pytest tests/test_probe_audit.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.probe_audit'`.

- [ ] **Step 3: Implement the pure audit function**

Classify each model-backed row into exactly one disposition:

- `retained`: `act` is `probe` or `reask`, `say_raw` is non-empty, and `say_raw == say`.
- `substituted`: a guard starts with `off-focus->` and `say_raw != say`.
- `action_conflict`: `invented-question-dropped` or `invented-question->probe` appears.
- `other_changed`: raw and spoken differ for another named guard.
- `no_raw_question`: `say_raw` is empty or contains no question mark.

Also report:

```python
{
    "raw_question_total": int,
    "retained": int,
    "substituted": int,
    "action_conflicts": int,
    "other_changed": int,
    "no_raw_question": int,
    "retention_rate": float,
    "template_rate": float,
    "multi_question_raw": int,
    "over_15_words_raw": int,
    "focus_mismatches": list[dict],
    "turns": list[dict],
}
```

Use `focus.classify` and existing guard metadata; do not call a model or infer quality from answer length.

- [ ] **Step 4: Implement the CLI and validation**

Reject a session if any model-backed row lacks `say_raw`, because mixing old and new provenance would make the rates dishonest. Print a compact summary and write the complete JSON to the requested path.

- [ ] **Step 5: Document the audit command**

Add a short research/diagnostics entry to `README.md`:

```powershell
python tools/probe_audit.py --session 20260826-203719-90e74f `
  --out data/calibration/granite42-junior-probes.json
```

State that the output measures speech transformation, not interview quality or model accuracy.

- [ ] **Step 6: Run audit tests and static checks**

Run:

```powershell
python -m compileall -q app tools tests
python -m pytest tests/test_probe_audit.py tests/test_runner.py -q
```

Expected: compilation succeeds and all collected tests pass.

- [ ] **Step 7: Commit the audit tool**

```powershell
git add tools/probe_audit.py tests/test_probe_audit.py README.md
git commit -m "Audit raw probe speech"
```

---

### Task 4: Adjudicate whether contradictory `advance` questions deserve promotion

**Files:**
- Create locally: `data/calibration/granite42-advance-question-review.json`
- Modify only after Gate A passes: `app/guards.py:389-413`
- Modify only after Gate A passes: `app/runner.py:118-167`
- Test only after Gate A passes: `tests/test_guards.py:31-65`
- Test only after Gate A passes: `tests/test_runner.py:1290-1345`

**Interfaces:**
- Candidate policy knob: `Speech.promote_advance_question: bool = False`.
- Guard input: `promote_advance_question`, passed separately from `trust_ok`.
- Production default: `False` for Granite 4.1, Exaone, Yi, and unknown models.
- Granite 4.2 remains `False` until both Gate A and the live gates in Task 5 pass.

- [ ] **Step 1: Capture a fresh junior-to-mid Granite 4.2 session**

Use the same candidate protocol as session `20260826-203719-90e74f`: initial answers of roughly 25–60 words, incomplete metrics or ownership where natural, direct concise replies to probes, and no artificial refusals. Record the new session ID immediately.

- [ ] **Step 2: Generate the probing audit**

Run:

```powershell
python tools/probe_audit.py --session NEW_SESSION_ID `
  --out data/calibration/granite42-advance-question-review.json
```

Extract every row where:

- raw `act == "advance"`,
- raw `ok is False`,
- `say_raw` contains exactly one question, and
- the final guards include `invented-question-dropped`.

- [ ] **Step 3: Apply Gate A before changing policy**

Adjudicate each extracted question against the current candidate answer. Mark it usable only when it is relevant, asks one distinct question, does not repeat a focus already used on that question, and contains at most 20 words.

Gate A passes only when:

- at least five eligible questions were observed,
- at least 60% are usable,
- no more than 20% repeat a previously used focus,
- no usable question contains two independent requests, and
- none asks for facts the candidate could not know.

If Gate A fails, stop this task after saving the audit. Keep `invented-question-dropped` unchanged and proceed directly to Task 5 with the classifier-only candidate.

- [ ] **Step 4: Write promotion tests only when Gate A passes**

```python
def test_creative_profile_promotes_one_valid_advance_question():
    raw = g("advance", "What did you measure?", ok=False)
    result = guards.apply(raw, "We shipped it.", [], trust_ok=False,
                          promote_advance_question=True)
    assert result.act == "probe"
    assert result.say == "What did you measure?"
    assert "invented-question->probe" in result.applied


def test_creative_promotion_never_changes_end_or_ok_true_advance():
    ended = guards.apply(g("end", "Shall we rearrange?", ok=False),
                         "I need to stop.", [], trust_ok=False,
                         promote_advance_question=True)
    complete = guards.apply(g("advance", "Anything else?", ok=True),
                            "A complete answer.", [], trust_ok=False,
                            promote_advance_question=True)
    assert ended.act == "end" and "?" not in ended.say
    assert complete.act == "advance" and "?" not in complete.say
```

- [ ] **Step 5: Implement the opt-in policy only when Gate A passes**

Add `promote_advance_question=False` to `Speech`. Pass it to `guards.apply`. It may promote only `advance + ok=false + exactly one question`; it must not affect `end`, `skip`, `ok=true`, invalid output, stop confirmation, or candidate-question handling.

Do not enable the knob in `Speech.for_model` during this task. The implementation is an experimental capability until Task 5 passes.

- [ ] **Step 6: Verify the policy boundaries**

Run:

```powershell
python -m pytest tests/test_guards.py tests/test_runner.py -q
```

Expected: all guard and runner tests pass, including unchanged stop/skip and model-profile invariants.

- [ ] **Step 7: Commit only a Gate-A-approved implementation**

```powershell
git add app/guards.py app/runner.py tests/test_guards.py tests/test_runner.py
git commit -m "Trial creative Granite probes"
```

If Gate A failed, make no commit for this task.

---

### Task 5: Compare production, classifier-only, and creative probing

**Files:**
- Modify when the opt-in policy exists: `tools/live_candidate.py:1-120`
- Test when modified: `tests/test_runner.py:1290-1345`
- Generated locally: `data/calibration/granite42-creative-comparison.json`

**Interfaces:**
- CLI flag: `--creative-probes`, default off.
- Persisted live-session field: `creative_probes: bool`, restored on every `--answer` invocation.
- Production path without the flag remains byte-for-byte equivalent in its `Speech` values.

- [ ] **Step 1: Expose the experimental profile without changing the default**

When Task 4 produced the opt-in policy, add `--creative-probes` to `live_candidate.py`. Resolve the production `Speech.for_model(model_key)` first, then use `dataclasses.replace(speech, promote_advance_question=True)` only when the flag is present. Persist the flag in `data/live_session.json` so a multi-process live interview cannot silently change policy mid-session.

When Task 4 stopped at Gate A, skip this step and compare only baseline versus classifier-only behaviour.

- [ ] **Step 2: Pin CLI persistence**

Add a test around the live-state serialisation helpers proving that `creative_probes=True` survives save/restore and that a missing field restores as `False` for old sessions.

- [ ] **Step 3: Run the strong-candidate control**

Repeat the strong-candidate protocol from `20260826-200541-27e1fd` with the candidate variant. It passes only when:

- all 14 questions close,
- total turns are at most 18,
- probes are at most 3,
- reasks and family crossings are zero,
- no spoken line contains two independent questions, and
- no question repeats a focus.

- [ ] **Step 4: Run the junior-to-mid candidate**

Repeat the protocol from `20260826-203719-90e74f`. It passes only when:

- all 14 questions close in at most 25 turns,
- reasks and family crossings are zero,
- no spoken line contains two independent questions,
- no question repeats a focus,
- at least 60% of model-authored probe/reask questions are retained,
- template substitution is at most 40% of model-authored probe/reask questions, and
- manually adjudicated spoken-probe relevance is at least 80%.

- [ ] **Step 5: Check latency and guard dependence**

On plugged-in power, require:

- canary decode speed at least 50 tokens/second,
- decision latency p90 at most 3.5 seconds,
- zero invalid model outputs,
- zero unguarded `advance`/question contradictions, and
- raw-versus-spoken data present for every model-backed turn.

- [ ] **Step 6: Select the product candidate**

Selection order:

1. Reject any candidate that violates a safety or completion gate.
2. Prefer higher relevant model-authored-question retention.
3. Break a retention tie with fewer repeated or generic questions.
4. Break a quality tie with fewer total turns.
5. Do not select the creative promotion candidate merely because it uses fewer templates.

Write the exact session IDs, metrics, rejected gates, and selected variant to `data/calibration/granite42-creative-comparison.json`.

- [ ] **Step 7: Enable only the selected profile**

If classifier-only wins, leave `promote_advance_question=False` for Granite 4.2. If creative promotion wins, introduce a distinct `GRANITE42` profile and resolve it before the generic `"granite"` branch in `Speech.for_model`:

```python
if "granite-4.2" in m:
    return GRANITE42
if "granite" in m:
    return GRANITE
```

Pin Granite 4.1 as unchanged in `test_the_profile_follows_the_model_id`.

- [ ] **Step 8: Commit the selected product profile**

```powershell
git add app/runner.py tools/live_candidate.py tests/test_runner.py
git commit -m "Select Granite 4.2 probing"
```

Omit unchanged paths when classifier-only wins.

---

### Task 6: Run the matched Granite 4.1 comparison and final regression gate

**Files:**
- Generated locally: `data/calibration/granite41-granite42-probing.json`
- Modify only if commands changed: `README.md`

**Interfaces:**
- Compares the selected Granite 4.2 product profile with the existing Granite 4.1 product profile.
- Uses identical candidate protocols, context, seed, temperature, parallelism, and power conditions.
- Reports product behaviour and raw model behaviour separately.

- [ ] **Step 1: Run paired fixed-turn captures**

Run both models against the same 60 action fixtures and the same junior-session script. Resolve each model's own `Speech.for_model` profile; do not force both through the default profile.

Record raw action, guarded action, product action, severity, model-authored question, spoken question, focus, substitution, and latency for every turn.

- [ ] **Step 2: Run one Granite 4.1 junior-to-mid live interview**

Use the Task 5 junior-to-mid candidate protocol. Answer the interviewer that actually appears rather than replaying fixed lines after navigation diverges.

- [ ] **Step 3: Apply the final comparison gates**

Granite 4.2 is preferred only when it:

- has zero family crossings,
- closes all 14 live questions,
- retains a higher share of relevant model-authored probes than Granite 4.1,
- does not exceed Granite 4.1's repeated-probe rate,
- does not add more than three live turns without obtaining a new answer dimension, and
- keeps decision p90 within 1 second of Granite 4.1 on the same plugged-in run.

If neither model dominates, retain both model-specific profiles and report the trade-off rather than forcing a universal winner.

- [ ] **Step 4: Run complete verification**

Run:

```powershell
git diff --check
python -m compileall -q app tools tests
python -m pytest tests/test_guards.py -q
python -m pytest tests/test_runner.py -q
python -m pytest -q -p no:cacheprovider
```

Expected: no whitespace errors, successful compilation, and every collected test passes. On managed Windows, rerun pytest outside the sandbox when its only failures are `PermissionError` from pytest or `tempfile` directories.

- [ ] **Step 5: Verify repository scope**

Run:

```powershell
git status --short
git diff --stat HEAD~1
git log --format="%h %s" -6
```

Confirm that no generated session, calibration output, transcript, LM Studio wrapper, or private Tier-1 harness is staged.

- [ ] **Step 6: Commit final documentation only when changed**

```powershell
git add README.md
git commit -m "Document creative probe checks"
```

Skip this commit when `README.md` already contains the final commands and interpretation boundaries.

## Completion Criteria

The work is complete only when:

- raw model speech is recorded on every model-backed turn,
- useful failure-mode questions remain model-authored in the spoken interview,
- templates still replace repeated or irrelevant questions,
- contradictory action/question output remains guarded unless its promotion passed Gate A and both live controls,
- Granite 4.1 behaviour is unchanged except where a shared semantic classifier improvement is independently valid,
- strong and junior-to-mid live controls satisfy their separate turn/probe limits,
- no family crossing, focus repetition, multi-question spoken line, or invalid output appears,
- all project tests pass outside the known Windows temporary-directory ACL limitation, and
- the final recommendation cites exact session IDs and raw-versus-spoken evidence.

## Deferred Follow-up Defects

These defects were observed while executing this plan. They are documented for a later,
separately approved fix and are not part of the completed creative-probing implementation.
Do not weaken the existing stop, skip, action, budget, or provenance guards while addressing
them.

### Defect A: One punctuated question can contain two independent requests

**Status:** Deferred.

**Evidence:** Granite 4.2 junior session `20260827-015615-e48e64`, turn 2,
question `behavioural_core.1` retained and spoke:

> How did your team respond to your suggestion, and what was the outcome?

The line contains one question mark but asks for two independently answerable dimensions:
the team's response and the eventual outcome. It therefore passed the existing sentence and
question-count guards even though the turn contract requires one short question. The matched
Granite 4.1 junior run `20260827-021700-4e835d` also produced compound probes, so this is a
shared guard boundary rather than a Granite 4.2-only profile issue.

**Likely cause:** The current multi-question protection recognises multiple question sentences
or question marks. It does not recognise coordinated interrogative clauses joined inside one
punctuated sentence. A bare check for `and` or `or` would be too broad because one coherent
request may legitimately coordinate examples or equivalent signals.

**Likely files:**

- `app/guards.py` for bounded compound-request detection and repair.
- `app/focus.py` only if focus classification is needed to distinguish two independent
  dimensions from one coordinated dimension.
- `tests/test_guards.py` and `tests/test_runner.py` for guard and spoken-turn regressions.

**Required regression cases:**

- Reject or reduce `How did your team respond, and what was the outcome?` to one request.
- Reject or reduce `What failed, and how did you recover?` to one request.
- Preserve a single coherent request such as `What metrics or feedback informed that choice?`.
- Preserve an either/or clarification when it offers two interpretations of the same question.
- Never change the action family, consume an extra follow-up, or discard raw provenance while
  repairing speech.

**Acceptance gate:** Across a fresh strong and junior Granite 4.2 live pair, no model-backed
spoken probe or reask contains two independently answerable requests. The guard must still
retain relevant single-focus model wording, and the full action, stop, skip, direction, and
runner suites must remain green.

### Defect B: The deterministic design-gap probe is not registered as `CHALLENGE`

**Status:** Deferred.

**Evidence:** Granite 4.2 junior session `20260827-015615-e48e64` spoke the deterministic
design-gap line on turn 15:

> What breaks first when this is under real load?

The decision carried `design-gap->probe`, but `focus_got` was empty and `CHALLENGE` was not
added to `focus_used`. Turn 17 therefore selected `CHALLENGE` again and substituted:

> What was the hardest part?

Both turns ask for the design's failure or challenge dimension. The repeated focus consumed a
follow-up and caused the junior control to fail the zero-focus-repetition gate.

**Likely cause:** The focus-validation block deliberately exempts `design-gap->probe` because
the line is deterministic, but the exemption also skips recording the focus already asked.
The fixed wording should remain exempt from model-line validation while still participating in
per-question focus accounting.

**Likely files:**

- `app/runner.py` to record `CHALLENGE` when the deterministic design-gap probe is actually
  dispatched.
- `app/focus.py` only if the existing `FAILURE` design gap needs an explicit mapping to the
  closed `CHALLENGE` focus.
- `tests/test_runner.py` to pin state and persisted decision metadata across the next turn.

**Required regression cases:**

- After `design-gap->probe`, `focus_used` contains `CHALLENGE`.
- The decision record reports `focus_got: ["CHALLENGE"]` while retaining the original
  model-requested `focus_asked` for diagnosis.
- The next follow-up on the same design question cannot select or substitute another
  `CHALLENGE` question.
- Closing the question resets the recorded focus normally for the next question.
- The deterministic probe remains model-call neutral and does not change budgets, action
  choice, `say_raw`, or the shared 20-word Granite speech profile.

**Acceptance gate:** A fresh junior Granite 4.2 live session contains no repeated design
failure/challenge focus, closes all 14 questions within 25 turns, and introduces no family
crossing, reask, compound spoken question, invalid output, or provenance gap.
