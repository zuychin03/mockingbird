# Exaone Semantic Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Exaone's interview probing by retaining useful model-invented questions, while preserving safety, provenance, deterministic defaults, and fair comparison with Granite 4.1 and 4.2.

**Architecture:** Keep the shared guard pipeline authoritative and introduce narrowly scoped model-profile capabilities around it. Record every raw model attempt and rejection before speech substitution, add an optional Exaone semantic classifier layer, persist the experiment profile with live sessions, and promote any riskier behaviour only after an evidence gate. Compare all surviving variants under matched Q4, Q5, strong-candidate, and junior-to-mid candidate conditions.

**Tech Stack:** Python 3.12, dataclasses, JSONL session persistence, pytest, LM Studio's OpenAI-compatible local endpoint, existing Mockingbird replay/screen/live harnesses.

**Spec:** `docs/superpowers/specs/2026-08-26-exaone-semantic-retention-design.md`

## Global Constraints

- Work only on `exaone-adaptation` in `C:\Users\kduy1\OneDrive\Desktop\Projects\mockingbird`.
- Use `.\.venv\Scripts\python.exe`; system Python 3.14 does not have this repository's test environment.
- Preserve the pre-existing edits to `app/runner.py` and `tests/test_runner.py`. Before each commit, stage only named files or exact hunks.
- Keep `docs/ARCHITECTURE.md`, `docs/architecture-explorer.html`, private Tier-1 harnesses, and generated `data/` artefacts out of commits.
- Preserve `trust_ok=False` and `max_say_words=15` for Exaone unless a later measured gate explicitly changes one of them.
- Default all new experimental switches off. A saved session must restore the exact model/profile combination or fail clearly.
- Treat raw output as evidence, not speech. Guarded/substituted `say` remains the only spoken value.
- Run model comparisons plugged in, thinking disabled, context length 8192, parallelism 1, temperature 0, and seed 11. Reject runs that do not meet those controls.
- Do not claim Exaone matches Granite unless it passes every product gate in Task 9.

## File Structure

- `app/guards.py`: shared deterministic candidate/action guards plus the public sentence-aware `question_count` helper and the optional advance-question gate.
- `app/focus.py`: base focus classifier and the opt-in bounded Exaone semantic layer.
- `app/runner.py`: model-specific `Speech` capabilities, retry orchestration, attempt disposition, and persisted turn records.
- `tools/probe_audit.py`: standard-library-only offline audit of `decisions.jsonl`; no model calls and no quality inference.
- `tools/experiment_profile.py`: serialisable model/speech/control profile and pure replay-summary construction shared by tracked and private harnesses.
- `tools/live_candidate.py`: tracked resumable live harness that enforces saved model/profile identity.
- `tools/stage1_replay.py` and `tools/tier1_model_screen.py`: ignored private measurement harnesses; local experiment changes are hashed into evidence and never staged.
- `tests/test_guards.py`, `tests/test_focus.py`, and `tests/test_runner.py`: behavioural and adversarial unit coverage.
- `tests/test_persistence.py`, `tests/test_probe_audit.py`, `tests/test_experiment_profile.py`, and `tests/test_live_candidate_profile.py`: schema, audit, profile, and resume-integrity coverage.
- `data/sessions/**` and `data/comparisons/**`: generated evidence only; never commit.

## Execution Preflight

Run before editing:

```powershell
git branch --show-current
git status --short
git diff -- app/runner.py tests/test_runner.py
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -q -p no:cacheprovider
```

Expected: branch `exaone-adaptation`, Python 3.12.x, the two pre-existing modified runner files, the approved-status edit to the spec, this untracked plan, the two unrelated untracked architecture documents, and the focused suite passing. If the dirty-file set differs, inspect before continuing. Keep the spec/plan documentation out of feature commits unless the user separately asks to commit them.

---

### Task 1: Bring the Shared Granite Candidate-Language Corrections Across

**Files:**

- Modify: `app/guards.py`
- Modify: `tests/test_guards.py`

**Interfaces:**

- Consumes: source commit `64027e36bb2ebf890e9f16c4f9cd796e6b7af19e` and existing `guards.apply(raw, utterance, said, trust_ok) -> Guarded`.
- Produces: model-independent candidate-language routing verified by `tests/test_guards.py`; no public signature change.

- [ ] **Step 1: Prove the source commit is narrowly scoped**

```powershell
git show --stat --oneline 64027e36bb2ebf890e9f16c4f9cd796e6b7af19e
git diff-tree --no-commit-id --name-only -r 64027e36bb2ebf890e9f16c4f9cd796e6b7af19e
```

Expected file list: only `app/guards.py` and `tests/test_guards.py`.

- [ ] **Step 2: Apply the shared correction as its own commit**

```powershell
git cherry-pick 64027e36bb2ebf890e9f16c4f9cd796e6b7af19e
```

If Git reports a conflict, abort the cherry-pick and port only the tested guard/test hunks manually; do not overwrite the user's runner experiment.

- [ ] **Step 3: Verify the shared behaviour and scope**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -q -p no:cacheprovider
git status --short
git diff -- app/runner.py tests/test_runner.py
```

Expected: the suite passes and the original dirty runner/test diff remains present and unstaged.

---

### Task 2: Make the Existing Off-Focus Retry an Explicit Experiment

**Files:**

- Modify: `app/runner.py:Speech`
- Modify: `app/runner.py:Runner._decide`
- Modify: `app/guards.py`
- Modify: `tests/test_guards.py`
- Modify: `tests/test_runner.py`

**Interfaces:**

- Consumes: `focus.classify(say: str) -> set[str]`, `Runner.submit(utterance: str) -> TurnOutcome`, and the dirty `missed_focus` retry experiment.
- Produces: `guards.question_count(text: str) -> int`, `Speech.retry_off_focus: bool = False`, and a two-call maximum for an explicitly enabled eligible focus retry.

- [ ] **Step 1: Add failing profile and call-count tests**

Extend the existing top-level runner import with `Speech`. Add tests using the existing `build`, `d`, `run`, and `ScriptedProvider.prompts` helpers. Pin `focus.next_focus` so the test does not depend on answer wording:

```python
from app.runner import CONFIRM_NARROW, Runner, Speech, live_view
```

```python
def test_exaone_profile_does_not_retry_off_focus_by_default():
    speech = Speech.for_model("exaone-deep-2.4b-q4_k_m")
    assert speech.retry_off_focus is False


def test_off_focus_retry_is_disabled_without_explicit_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "OUTCOME")
    r, state = build([
        d("probe", "Could you elaborate?"),
        d("probe", "What happened as a result?"),
    ], tmp_path)
    r.speech = Speech(max_say_words=15)
    run(r.ask())
    run(r.submit("I used Redis because it was fast."))
    assert len(r.provider.prompts) == 1
    assert last_decision(state)["model_calls"] == 1


def test_off_focus_retry_can_be_enabled_for_an_experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "OUTCOME")
    r, state = build([
        d("probe", "Could you elaborate?"),
        d("probe", "What happened as a result?"),
    ], tmp_path)
    r.speech = Speech(max_say_words=15, retry_off_focus=True)
    run(r.ask())
    run(r.submit("I used Redis because it was fast."))
    assert len(r.provider.prompts) == 2
    assert last_decision(state)["model_calls"] == 2
```

Add `last_decision(state)` next to the existing test helpers:

```python
def last_decision(state):
    lines = (state.dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])
```

Add focused guard tests for `guards.question_count`: zero for declarative text, one for a single question, and two for two independent question sentences.

Use the repository's actual fixture and result conventions if names differ; keep the assertions about default/opt-in behaviour exact.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -k "question_count or off_focus_retry or exaone_profile_does_not_retry" -q -p no:cacheprovider
```

Expected: failure because `retry_off_focus` does not exist and the dirty experiment retries eagerly.

- [ ] **Step 3: Add the capability flag and gate the existing retry block**

In `Speech`:

```python
@dataclass
class Speech:
    # Existing fields remain unchanged.
    retry_off_focus: bool = False
```

Expose the existing sentence-aware question count rather than duplicating punctuation parsing in the runner:

```python
def question_count(text: str) -> int:
    return sum(_is_question(sentence) for sentence in _sentences(text))
```

In `Runner.submit`, keep the existing length retry unchanged, but require the new flag and exactly one guarded question before treating a classifier miss as retry-eligible:

```python
raw_say = (raw.get("say") or "").strip() if isinstance(raw, dict) else ""
off_focus = (
    self.speech.retry_off_focus
    and guards.question_count(raw_say) == 1
    and len(raw_say.split()) <= cap
    and want is not None
    and not (focus.classify(g.say) - self.focus_used)
)
```

Use the actual effective line, `g.say`, in `classify`, and retain the existing fresh-focus rule (`classify(g.say) - self.focus_used`), which deliberately accepts any unused dimension rather than only `want`. Extend the current acceptance expression with the raw retry contract so a guard cannot hide a compound or over-length model attempt:

```python
retry_say = (raw2.get("say") or "").strip() if isinstance(raw2, dict) else ""
kept = (
    g2.act == g.act
    and guards.question_count(retry_say) == 1
    and len(retry_say.split()) <= cap
    and bool(g2.say)
    and (not off_focus or bool(focus.classify(g2.say) - self.focus_used))
)
```

Do not change the length-retry prompt in this task.

- [ ] **Step 4: Run focused and regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -k "question_count or off_focus_retry or exaone_profile_does_not_retry" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -q -p no:cacheprovider
```

- [ ] **Step 5: Commit only the flag/gating hunks**

Because both files began dirty, use interactive staging and inspect the index:

```powershell
git add -- app/guards.py tests/test_guards.py
git add -p -- app/runner.py tests/test_runner.py
git diff --cached --check
git diff --cached
git commit -m "Gate Exaone focus retries"
```

Leave any unrelated pre-existing hunks unstaged.

---

### Task 3: Persist Raw Speech and Every Speech Attempt

**Files:**

- Modify: `app/runner.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_persistence.py`

**Interfaces:**

- Consumes: all model-call branches in `Runner.submit`, `guards.Guarded`, and `session.append_decision(state, record)`.
- Produces: every decision row contains `say_raw: str | None` and `speech_attempts: list[dict[str, object]]` using the closed kind/reason vocabularies in Step 3.

- [ ] **Step 1: Add failing provenance tests**

Cover all required paths:

```python
def test_decision_records_raw_say_and_attempts_for_focus_substitution(tmp_path):
    raw = "Could you elaborate?"
    r, state = build([d("probe", raw)], tmp_path)
    run(r.ask())
    run(r.submit("I used Redis because it was fast."))
    result = last_decision(state)
    assert result["say_raw"] == raw
    assert result["say"] != raw
    assert result["speech_attempts"][0] == {
        "kind": "initial",
        "act": "probe",
        "say": raw,
        "accepted": False,
        "reason": "off_focus",
    }


def test_accepted_retry_becomes_effective_raw_say(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "OUTCOME")
    original = "Could you elaborate?"
    retry = "What happened as a result?"
    r, state = build([d("probe", original), d("probe", retry)], tmp_path)
    r.speech = Speech(max_say_words=15, retry_off_focus=True)
    run(r.ask())
    run(r.submit("I used Redis because it was fast."))
    result = last_decision(state)
    assert result["say_raw"] == retry
    assert [attempt["accepted"] for attempt in result["speech_attempts"]] == [False, True]
    assert [attempt["kind"] for attempt in result["speech_attempts"]] == [
        "initial", "focus_retry"
    ]
    assert [attempt["reason"] for attempt in result["speech_attempts"]] == [
        "off_focus", "fresh_focus"
    ]


def test_rejected_retry_preserves_original_raw_say(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "OUTCOME")
    original = "Could you elaborate?"
    retry = "Could you please explain in considerable detail every part of what happened after that difficult technical decision?"
    r, state = build([d("probe", original), d("probe", retry)], tmp_path)
    r.speech = Speech(max_say_words=15, retry_off_focus=True)
    run(r.ask())
    run(r.submit("I used Redis because it was fast."))
    result = last_decision(state)
    assert result["say_raw"] == original
    assert result["speech_attempts"][-1]["accepted"] is False
    assert result["speech_attempts"][-1]["kind"] == "focus_retry"
    assert result["speech_attempts"][-1]["reason"] == "over_length"


def test_non_model_turn_has_deterministic_empty_provenance(tmp_path):
    r, state = build([], tmp_path)
    run(r.ask())
    run(r.submit("Actually, can I ask what the on-call rotation looks like?"))
    result = last_decision(state)
    assert result["say_raw"] is None
    assert result["speech_attempts"] == []
```

Also test with the same repository helpers:

- a guard-dropped question on `advance` records `accepted=False, reason="action_changed"`;
- a duplicate regeneration records ordered `initial` and `regeneration` attempts;
- an over-length retry uses `shortening_retry` rather than `focus_retry`; and
- an invalid structured response records an `invalid` attempt without inventing a raw question.

In `tests/test_persistence.py`, assert a `decisions.jsonl` row survives a save/read round trip with both keys unchanged.

- [ ] **Step 2: Run the new tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runner.py tests/test_persistence.py -k "raw_say or speech_attempt or provenance" -q -p no:cacheprovider
```

- [ ] **Step 3: Introduce one stable attempt schema**

Use a small serialisable helper rather than ad hoc dictionaries in several branches:

```python
def _speech_attempt(kind: str, raw: dict | None) -> dict[str, object]:
    return {
        "kind": kind,
        "act": raw.get("act") if isinstance(raw, dict) else None,
        "say": (raw.get("say") or "") if isinstance(raw, dict) else "",
        "accepted": False,
        "reason": "invalid",
    }


def _set_attempt(attempt: dict[str, object], accepted: bool, reason: str) -> None:
    attempt["accepted"] = accepted
    attempt["reason"] = reason
```

Allowed `kind` values are exactly `initial`, `regeneration`, `shortening_retry`, and `focus_retry`. Allowed `reason` values are exactly `selected`, `invalid`, `repeated`, `over_length`, `off_focus`, `compound`, `action_changed`, and `fresh_focus`. Assert these vocabularies in tests so later audit code can depend on them.

- [ ] **Step 4: Thread provenance through `_decide` and `_dispatch`**

- Append an `initial` attempt immediately after the first model response, including an invalid parse.
- Append every regeneration, shortening retry, and focus retry in call order before deciding its disposition.
- Mark a line retained as `accepted=True` with `selected` or `fresh_focus`. Mark a line that is substituted, repeated, over-length, compound, invalid, or removed by an action guard as `accepted=False` with the exact reason above.
- Set `say_raw` to the exact `say` from the effective model decision that enters the final guard pipeline. If a retry is accepted it becomes the effective line; if rejected, the original remains effective.
- Set `say_raw=None` and `speech_attempts=[]` for deterministic/non-model turns.
- Include both keys in the persisted decision record alongside `say_model` and `model_calls`.

- [ ] **Step 5: Run focused and full persistence regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runner.py tests/test_persistence.py -k "raw_say or speech_attempt or provenance" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py tests/test_persistence.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit only this feature's hunks**

```powershell
git add -p -- app/runner.py tests/test_runner.py
git add -- tests/test_persistence.py
git diff --cached --check
git diff --cached
git commit -m "Record Exaone speech attempts"
```

---

### Task 4: Build a Raw-Versus-Spoken Probe Audit

**Files:**

- Create: `tools/probe_audit.py`
- Create: `tests/test_probe_audit.py`
- Modify: `tools/README.md`

**Interfaces:**

- Consumes: Task 3's `decisions.jsonl` fields plus `guards.question_count(text: str) -> int`.
- Produces: `load_rows(session_id: str, root: Path = Path("data/sessions")) -> list[dict[str, object]]`, `audit(rows: Iterable[Mapping[str, object]]) -> dict[str, object]`, and the `tools/probe_audit.py --session ID [--out PATH]` CLI.

- [ ] **Step 1: Write failing audit tests from synthetic decision rows**

```python
def attempt(kind, act, say, accepted, reason):
    return {
        "kind": kind,
        "act": act,
        "say": say,
        "accepted": accepted,
        "reason": reason,
    }


def decision(act, *, raw, spoken, attempts=None):
    substituted = raw != spoken
    return {
        "turn": 0,
        "question_id": "q1",
        "act": act,
        "say_raw": raw,
        "say": spoken,
        "say_model": raw if substituted else None,
        "speech_attempts": attempts or [
            attempt(
                "initial", act, raw, not substituted,
                "off_focus" if substituted else "selected",
            )
        ],
        "guards": ["off-focus->template"] if substituted else [],
        "focus_asked": "OUTCOME",
        "focus_got": ["OUTCOME"] if not substituted else [],
        "model_calls": len(attempts or [None]),
    }


def test_audit_separates_invented_retained_substituted_and_retry_attempts():
    rows = [
        decision("probe", raw="Why did you choose Redis?", spoken="Why did you choose Redis?"),
        decision("probe", raw="What was the scale?", spoken="What did you learn?"),
        decision(
            "probe",
            raw="What did you learn?",
            spoken="What did you learn?",
            attempts=[
                attempt("initial", "probe", "Could you elaborate?", False, "off_focus"),
                attempt("focus_retry", "probe", "What did you learn?", True, "fresh_focus"),
            ],
        ),
    ]
    report = audit(rows)
    assert report["decision_rows"] == 3
    assert report["raw_question_count"] == 3
    assert report["retained_model_question_count"] == 2
    assert report["template_substitution_count"] == 1
    assert report["attempts_total"] == 4
    assert report["rejections_by_reason"] == {"off_focus": 2}


def test_audit_rejects_mixed_or_missing_provenance():
    with pytest.raises(ValueError, match="provenance"):
        audit([{"action": "probe", "say": "What happened?"}])
```

Also cover zero-denominator rates and malformed attempt dictionaries.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_probe_audit.py -q -p no:cacheprovider
```

- [ ] **Step 3: Implement a pure audit core and a thin CLI**

```python
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import guards

ATTEMPT_KEYS = {"kind", "act", "say", "accepted", "reason"}
KINDS = {"initial", "regeneration", "shortening_retry", "focus_retry"}
REASONS = {
    "selected", "invalid", "repeated", "over_length", "off_focus",
    "compound", "action_changed", "fresh_focus",
}


def _norm(text: object) -> str:
    return " ".join(str(text or "").casefold().split())


def _over_words(text: object, cap: int = 15) -> bool:
    return len(str(text or "").split()) > cap


def load_rows(
    session_id: str,
    root: Path = Path("data/sessions"),
) -> list[dict[str, object]]:
    path = root / session_id / "decisions.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise ValueError(f"empty decisions file: {path}")
    return rows


def audit(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Summarise model attempts, selected raw speech, and spoken substitutions."""
    records = [dict(row) for row in rows]
    if not records:
        raise ValueError("empty provenance input")
    if any("say_raw" not in row or "speech_attempts" not in row for row in records):
        raise ValueError("incomplete or mixed speech provenance")

    attempts: list[dict[str, object]] = []
    traces: list[dict[str, object]] = []
    focus_by_question: dict[str, list[str]] = defaultdict(list)
    spoken_seen: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    accepted_retry_reasons: Counter[str] = Counter()
    rejected_retry_reasons: Counter[str] = Counter()

    for row in records:
        row_attempts = row["speech_attempts"]
        if not isinstance(row_attempts, list):
            raise ValueError("speech_attempts must be a list")
        for attempt in row_attempts:
            if not isinstance(attempt, dict) or set(attempt) != ATTEMPT_KEYS:
                raise ValueError("invalid speech attempt schema")
            if attempt["kind"] not in KINDS or attempt["reason"] not in REASONS:
                raise ValueError("unknown speech attempt disposition")
            attempts.append(attempt)
            counts[f"attempt_kind:{attempt['kind']}"] += 1
            if not attempt["accepted"]:
                rejection_reasons[str(attempt["reason"])] += 1
            if attempt["kind"] != "initial":
                bucket = accepted_retry_reasons if attempt["accepted"] else rejected_retry_reasons
                bucket[str(attempt["reason"])] += 1

        raw = row["say_raw"]
        spoken = row.get("say") or ""
        guards_applied = [str(item) for item in (row.get("guards") or [])]
        raw_questions = guards.question_count(str(raw or ""))
        spoken_questions = guards.question_count(str(spoken))
        counts["raw_questions"] += raw_questions
        counts["raw_multi_question"] += raw_questions > 1
        counts["spoken_multi_question"] += spoken_questions > 1
        counts["raw_over_15"] += _over_words(raw)
        counts["spoken_over_15"] += _over_words(spoken)
        counts["template_substitutions"] += row.get("say_model") is not None
        counts["action_conflict_removals"] += "invented-question-dropped" in guards_applied
        counts["action_conflict_promotions"] += any(
            name in guards_applied
            for name in ("invented-question->probe", "advance-question->probe")
        )
        counts["focus_classifier_misses"] += any(
            attempt["reason"] == "off_focus" for attempt in row_attempts
        )

        effective_retained = any(
            attempt["accepted"]
            and _norm(attempt["say"]) == _norm(raw)
            and attempt["reason"] in {"selected", "fresh_focus"}
            for attempt in row_attempts
        )
        counts["retained_model_questions"] += bool(raw_questions and effective_retained
                                                   and row.get("say_model") is None)

        question_id = str(row.get("question_id") or "")
        focus_by_question[question_id].extend(str(x) for x in row.get("focus_got") or [])
        if spoken_questions:
            spoken_seen[_norm(spoken)] += 1
        traces.append({
            "turn": row.get("turn"),
            "question_id": question_id,
            "act": row.get("act"),
            "focus_asked": row.get("focus_asked"),
            "focus_got": row.get("focus_got") or [],
            "say_raw": raw,
            "speech_attempts": row_attempts,
            "say": spoken,
            "guards": guards_applied,
        })

    repeated_focus = sum(
        len(values) - len(set(values)) for values in focus_by_question.values()
    )
    repeated_wording = sum(total - 1 for total in spoken_seen.values() if total > 1)
    raw_questions = counts["raw_questions"]
    substitutions = counts["template_substitutions"]
    retained = counts["retained_model_questions"]
    return {
        "decision_rows": len(records),
        "model_calls": sum(int(row.get("model_calls") or 0) for row in records),
        "attempts_total": len(attempts),
        "attempts_by_kind": {
            kind: counts[f"attempt_kind:{kind}"] for kind in sorted(KINDS)
        },
        "rejections_by_reason": dict(sorted(rejection_reasons.items())),
        "accepted_retries_by_reason": dict(sorted(accepted_retry_reasons.items())),
        "rejected_retries_by_reason": dict(sorted(rejected_retry_reasons.items())),
        "raw_question_count": raw_questions,
        "retained_model_question_count": retained,
        "retained_model_question_rate": retained / raw_questions if raw_questions else 0.0,
        "template_substitution_count": substitutions,
        "template_substitution_rate": substitutions / raw_questions if raw_questions else 0.0,
        "action_conflict_removals": counts["action_conflict_removals"],
        "action_conflict_promotions": counts["action_conflict_promotions"],
        "raw_multi_question_count": counts["raw_multi_question"],
        "spoken_multi_question_count": counts["spoken_multi_question"],
        "raw_over_15_count": counts["raw_over_15"],
        "spoken_over_15_count": counts["spoken_over_15"],
        "repeated_focus_count": repeated_focus,
        "repeated_wording_count": repeated_wording,
        "focus_classifier_miss_count": counts["focus_classifier_misses"],
        "trace": traces,
    }
```

The report must include:

- raw question count;
- retained model-authored question count and rate;
- template substitution count and rate;
- action-conflict removals and promotions;
- accepted and rejected retries by exact reason;
- raw and spoken multi-question counts;
- raw and spoken over-15-word counts;
- repeated focus and repeated wording counts;
- focus-classifier misses;
- total model calls and attempts by kind; and
- a per-turn raw/attempted/spoken trace containing turn, action, focus, guards, and dispositions.

Read only `decisions.jsonl`; transcript turns alone do not contain the diagnostic fields. Fail on a partially migrated session rather than silently combining old and new schemas. Validate the closed `kind` and `reason` vocabularies from Task 3. Emit JSON to stdout and optionally to `--out`. The audit measures transformation; do not label relevance automatically.

- [ ] **Step 4: Document the exact command**

Add to `tools/README.md`:

```powershell
.\.venv\Scripts\python.exe tools\probe_audit.py --session 20260826-203719-90e74f
```

Explain that old sessions without `say_raw`/`speech_attempts` are valid transcripts but are not provenance-auditable.

- [ ] **Step 5: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_probe_audit.py tests/test_persistence.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe tools\probe_audit.py --help
git add -- tools/probe_audit.py tests/test_probe_audit.py tools/README.md
git diff --cached --check
git commit -m "Audit Exaone probe speech"
```

---

### Task 5: Add Bounded Exaone Semantic Retention

**Files:**

- Modify: `app/focus.py`
- Modify: `app/runner.py`
- Modify: `tests/test_focus.py`
- Modify: `tests/test_runner.py`

**Interfaces:**

- Consumes: base `_COMPILED` focus patterns, Task 3 provenance, and Task 4 audit dispositions.
- Produces: `focus.classify(say: str, *, exaone_semantics: bool = False) -> set[str]` and `Speech.semantic_retention: bool = False`; every runner focus check passes the profile flag.

- [ ] **Step 1: Add classifier tests before implementation**

Use phrases observed in Exaone's real output, plus adversarial declarative and postposed-negation cases:

```python
@pytest.mark.parametrize(
        ("say", "expected"),
    [
        ("What influenced that technical choice?", {"REASON"}),
        ("What concerns led to that disagreement?", {"REASON"}),
        ("Could you explain how you communicated your concerns?", {"STEPS"}),
        ("How did you ensure the rollout was safe?", {"STEPS"}),
        ("What issues arose during the outage?", {"CHALLENGE"}),
        ("Which part did you own?", {"ROLE"}),
    ],
)
def test_exaone_semantic_retention_recognises_natural_probes(say, expected):
    assert expected <= classify(say, exaone_semantics=True)


@pytest.mark.parametrize(
    "say",
    [
        "I explained how the team diagnosed it.",
        "The hard part was not the database.",
        "Redis was unavailable, not because of memory pressure.",
        "I influenced that technical choice.",
    ],
)
def test_exaone_semantic_retention_does_not_read_answers_as_questions(say):
    assert classify(say, exaone_semantics=True) == classify(say)


GRANITE_REFERENCE_CASES = [
    ("How did you present your concerns, and what concrete evidence or experiments helped convince the team?", set()),
    ("What specific technical trade-offs did you consider during the discussion?", {"REASON"}),
    ("What metrics or data did you use to decide it wasn't working?", {"MEASURE"}),
    ("What specific metrics or feedback loops were in place during development?", {"MEASURE"}),
    ("What did you measure or observe that didn't go as expected after those three weeks?", {"DURATION", "MEASURE"}),
    ("What specific metrics (latency, throughput, error rate) did you measure before and after?", {"MEASURE"}),
    ("What specific metrics (p95 latency, DB queries) would you like to improve?", {"MEASURE"}),
    ("What specific metrics did you measure (e.g., latency, throughput, memory usage) before and after the change?", {"MEASURE"}),
    ("How would you handle rate limiting across multiple geographic regions, especially when Redis might be temporarily unavailable?", set()),
]


@pytest.mark.parametrize(("say", "expected"), GRANITE_REFERENCE_CASES)
def test_default_classifier_is_compatible_with_recorded_granite_lines(say, expected):
    assert classify(say) == expected
    assert classify(say, exaone_semantics=False) == expected
```

The immutable cases above are copied from model-authored probe lines in sessions `20260826-200541-27e1fd` and `20260826-203719-90e74f`; the test must not read another worktree at runtime. Add runner tests proving that the same natural Exaone probe is retained with the profile switch on and substituted with it off, while a generic, repeated, compound, or over-15-word line still falls back.

- [ ] **Step 2: Run the new tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_focus.py tests/test_runner.py -k "semantic_retention or byte_for_byte_compatible" -q -p no:cacheprovider
```

- [ ] **Step 3: Extend the classifier behind an explicit keyword-only flag**

```python
_EXAONE_PATTERNS = {
    "REASON": (
        r"\bwhat (?:concerns? )?led\b|"
        r"\bwhat influenced\b"
    ),
    "STEPS": r"\bhow (?:did )?you (?:communicat\w*|handl\w*|identif\w*|ensur\w*)\b",
    "CHALLENGE": (
        r"\bwhat (?:issues? arose|challenges? did you face|breaks?)\b|"
        r"\bwhat\b.{0,40}\b(?:outage|unavailab\w*)\b"
    ),
    "ROLE": r"\bwhich part did you own\b|\bwhat was your contribution\b",
}
_EXAONE_COMPILED = {
    kind: re.compile(pattern, re.I) for kind, pattern in _EXAONE_PATTERNS.items()
}
_EXAONE_IMPERATIVE = re.compile(r"^\s*(?:walk me through|tell me|describe)\b", re.I)


def _is_question_shaped(say: str) -> bool:
    text = (say or "").strip()
    return text.endswith("?") or bool(_EXAONE_IMPERATIVE.search(text))


def classify(say: str, *, exaone_semantics: bool = False) -> set[str]:
    found = {kind for kind, rx in _COMPILED.items() if rx.search(say or "")}
    if exaone_semantics and _is_question_shaped(say):
        found.update(kind for kind, rx in _EXAONE_COMPILED.items() if rx.search(say))
    return found
```

`_is_question_shaped` must require a trailing `?` or an imperative probe stem such as `walk me through`, `tell me`, or `describe`. Add only the bounded approved pattern families: `REASON` (`what led`, `what concerns led`, `what influenced`), `STEPS` (`how you communicated`, `how you handled`, `how you identified`, `how you ensured`), `CHALLENGE` (`what issues arose`, `what challenges did you face`, `what breaks`, bounded outage/unavailability forms), and `ROLE` (`which part did you own`, `what was your contribution`). Bare `issue`, `down`, `handled`, `team`, and `specific` must never be sufficient. Do not infer `OUTCOME` or `MEASURE` from broad nouns like “result” or “impact”. Preserve the existing contextual-negation behaviour.

- [ ] **Step 4: Add and route the profile flag**

```python
@dataclass(frozen=True)
class Speech:
    semantic_retention: bool = False


# Wherever focus is checked:
covered = classify(raw_say, exaone_semantics=self.speech.semantic_retention)
```

Route the flag through every classification site in `Runner.submit`: off-focus detection, retry acceptance, final `focus_got`, and focus-history updates. Under `semantic_retention=True`, require exactly one fresh classified focus; when two dimensions survive, substitute and record the effective attempt as `accepted=False, reason="compound"`. When the only recognised focus is already used, record `reason="repeated"`. Keep `Speech.for_model(model_id)` conservative for now: the Exaone default remains `False` until Task 9 selects a winning profile.

- [ ] **Step 5: Run focused, adversarial, and regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_focus.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit**

```powershell
git add -- app/focus.py tests/test_focus.py
git add -p -- app/runner.py tests/test_runner.py
git diff --cached --check
git diff --cached
git commit -m "Recognise Exaone probe semantics"
```

---

### Task 6: Persist and Enforce the Live Experiment Profile

**Files:**

- Create: `tools/experiment_profile.py`
- Modify: `tools/live_candidate.py`
- Modify locally, never stage: `tools/stage1_replay.py` (ignored private harness)
- Modify: `tests/test_persistence.py`
- Create: `tests/test_live_candidate_profile.py`
- Create: `tests/test_experiment_profile.py`

**Interfaces:**

- Consumes: `Speech.for_model(model_id: str) -> Speech`, `dataclasses.asdict`, loaded model metadata from `app.provider`, and Task 3 decision records.
- Produces: `LiveProfile`, `profile_to_dict(profile: LiveProfile) -> dict[str, object]`, `profile_from_dict(data: Mapping[str, object]) -> LiveProfile`, `speech_from_profile(profile: LiveProfile) -> Speech`, and `build_replay_summary -> dict[str, object]` in `tools/experiment_profile.py`.

- [ ] **Step 1: Add failing profile round-trip and mismatch tests**

```python
def test_live_session_persists_exact_model_and_speech_profile():
    profile = LiveProfile(
        model_id="exaone-deep-2.4b-q4_k_m",
        speech={
            "exemplars": True,
            "substitute_focus": True,
            "repeat_closes": True,
            "trust_ok": False,
            "max_say_words": 15,
            "retry_off_focus": False,
            "semantic_retention": True,
        },
        seed=11,
    )
    assert profile_from_dict(profile_to_dict(profile)) == profile


def test_restore_aborts_when_loaded_model_differs(tmp_path):
    profile = LiveProfile(
        model_id="exaone-deep-2.4b-q4_k_m",
        speech=asdict(Speech.for_model("exaone-deep-2.4b-q4_k_m")),
        seed=11,
    )
    with pytest.raises(RuntimeError, match="model mismatch"):
        profile.require_model("granite-4.2-3b-a800m-instruct")


def test_replay_summary_records_controls_and_profile():
    summary = build_replay_summary(
        session_id="unit-session",
        model_id="exaone-deep-2.4b-q4_k_m",
        speech=asdict(Speech(
            trust_ok=False,
            max_say_words=15,
            semantic_retention=True,
        )),
        seed=11,
        action_counts={"advance": 1},
        severity=0,
        family_crossings=0,
        navigation_drift=0,
        model_calls=1,
        wall_ms=[250.0],
    )
    assert summary["profile"]["speech"]["semantic_retention"] is True
    assert summary["profile"]["speech"]["trust_ok"] is False
    assert summary["controls"]["temperature"] == 0
    assert summary["controls"]["seed"] == 11


def test_profile_payload_contains_no_runtime_secret_or_home_path():
    profile = LiveProfile(
        model_id="exaone-3.5-2.4b-q4_k_m",
        speech=asdict(Speech.for_model("exaone-3.5-2.4b-q4_k_m")),
        seed=11,
    )
    text = json.dumps(profile_to_dict(profile)).casefold()
    assert "api_key" not in text
    assert "authorization" not in text
    assert "response_body" not in text
    assert "c:\\users\\" not in text
```

The payload is deliberately a closed schema, so a future API token, LM Studio response body, or absolute user-home path cannot enter through arbitrary metadata.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_candidate_profile.py tests/test_experiment_profile.py tests/test_persistence.py -q -p no:cacheprovider
```

- [ ] **Step 3: Introduce one tracked, serialisable experiment profile helper**

```python
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Mapping

from app.runner import Speech


@dataclass(frozen=True)
class LiveProfile:
    model_id: str
    speech: dict[str, bool | int | None]
    seed: int

    def require_model(self, loaded_model: str) -> None:
        if loaded_model != self.model_id:
            raise RuntimeError(
                f"model mismatch: session requires {self.model_id!r}, loaded {loaded_model!r}"
            )


def profile_to_dict(profile: LiveProfile) -> dict[str, object]:
    return {
        "model_id": profile.model_id,
        "speech": dict(profile.speech),
        "seed": profile.seed,
    }


def profile_from_dict(data: Mapping[str, object]) -> LiveProfile:
    if set(data) != {"model_id", "speech", "seed"}:
        raise ValueError("invalid live profile fields")
    speech = data["speech"]
    if not isinstance(data["model_id"], str) or not isinstance(speech, dict):
        raise ValueError("invalid live profile types")
    profile = LiveProfile(str(data["model_id"]), dict(speech), int(data["seed"]))
    speech_from_profile(profile)
    return profile


def speech_from_profile(profile: LiveProfile) -> Speech:
    expected = {field.name for field in fields(Speech)}
    if set(profile.speech) != expected:
        raise ValueError("saved speech profile does not match Speech fields")
    return Speech(**profile.speech)


def build_replay_summary(
    *,
    session_id: str,
    model_id: str,
    speech: dict[str, bool | int | None],
    seed: int,
    action_counts: dict[str, int],
    severity: int,
    family_crossings: int,
    navigation_drift: int,
    model_calls: int,
    wall_ms: list[float],
) -> dict[str, object]:
    ordered = sorted(wall_ms)
    p90 = ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)] if ordered else 0.0
    return {
        "session_id": session_id,
        "profile": profile_to_dict(LiveProfile(model_id, speech, seed)),
        "controls": {"temperature": 0, "seed": seed},
        "action_counts": dict(action_counts),
        "severity": severity,
        "family_crossings": family_crossings,
        "navigation_drift": navigation_drift,
        "model_calls": model_calls,
        "decision_p90_ms": p90,
    }
```

Place `LiveProfile`, strict dictionary validation, and the pure `build_replay_summary` helper in `tools/experiment_profile.py`. Build the dictionary with `dataclasses.asdict(resolved_speech)`, validate it against the `Speech` dataclass fields on restore, and reconstruct with `Speech(**profile.speech)`. This captures the complete resolved profile (`trust_ok`, word cap, existing speech rules, and experiment flags), not just the switches currently under study. Store it inside the existing `data/live_session.json`, not in a second competing state file. At `--start`, resolve the loaded model once and save it. At `--answer`, compare the current loaded model with the saved value before calling `Runner.submit`; never silently re-resolve to another model/profile.

- [ ] **Step 4: Add explicit CLI experiment switches**

For tracked `tools/live_candidate.py` and the local ignored `tools/stage1_replay.py`, wire the parser and profile override without mutating the shared constants:

```python
ap.add_argument("--expected-model")
ap.add_argument("--seed", type=int, default=11)
ap.add_argument("--semantic-retention", action="store_true")
ap.add_argument("--retry-off-focus", action="store_true")

base = Speech.for_model(model_id)
speech = replace(
    base,
    semantic_retention=args.semantic_retention,
    retry_off_focus=args.retry_off_focus,
)
profile = LiveProfile(model_id=model_id, speech=asdict(speech), seed=args.seed)
profile.require_model(args.expected_model or model_id)
provider = prov.LMStudio(seed=args.seed)
```

The experimental switches default to false and seed defaults to 11 for these comparison harnesses. `--expected-model` is required for admissible experiment runs and aborts before inference if the resolved loaded model ID differs. Pass the seed into `prov.LMStudio(seed=args.seed)`. The private replay harness imports the tracked pure summary/profile helper and writes `replay_summary.json` containing model ID, complete resolved speech profile, seed, temperature 0, action counts, severity, family crossings, navigation drift, model-call count, latency, and session ID. Add the promotion switch only in Task 7 if its evidence gate passes. Do not stage the private harness or write model outputs to tracked paths.

- [ ] **Step 5: Verify restoration and replay output**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_candidate_profile.py tests/test_experiment_profile.py tests/test_persistence.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe tools\live_candidate.py --help
.\.venv\Scripts\python.exe tools\stage1_replay.py --help
```

- [ ] **Step 6: Commit**

```powershell
git add -- tools/experiment_profile.py tools/live_candidate.py tests/test_live_candidate_profile.py tests/test_experiment_profile.py tests/test_persistence.py
git diff --cached --check
git diff --cached --name-only
git commit -m "Persist Exaone experiment profiles"
```

The cached file list must not contain `tools/stage1_replay.py` or any `tools/tier1_*.py` file.

---

### Task 7: Run the Action-Question Evidence Gate Before Implementing Promotion

**Files:**

- Read after Step 1: the new junior session's `decisions.jsonl`
- Read after Step 1: the new junior session's `transcript.html`
- Modify only if the gate passes: `app/guards.py`
- Modify only if the gate passes: `app/runner.py`
- Modify only if the gate passes: `tests/test_guards.py`
- Modify only if the gate passes: `tests/test_runner.py`
- Modify only if the gate passes: `tools/experiment_profile.py`
- Modify only if the gate passes: `tools/live_candidate.py`
- Modify locally and never stage if the gate passes: `tools/stage1_replay.py`
- Modify only if the gate passes: `tests/test_experiment_profile.py`

**Interfaces:**

- Consumes: Task 4's audit report, Task 5's fresh-focus classification, Task 6's complete profile serialisation, and the existing `invented-question-dropped` guard marker.
- Produces only if the evidence gate passes: `Speech.promote_advance_question: bool = False`, an explicit guard parameter of the same name, persisted CLI support, and guard marker `advance-question->probe`.

- [ ] **Step 1: Produce a provenance-enabled junior-to-mid evidence session**

With Exaone Q4 loaded and the matched environment confirmed, resolve its exact loaded key and require it explicitly:

```powershell
$exaoneQ4 = .\.venv\Scripts\python.exe -c "from app import provider as p; xs=p.loaded_models(); print(p.model_key(xs[0]) if len(xs)==1 else '')"
if (-not $exaoneQ4) { throw 'Exactly one Exaone Q4 model must be loaded' }
.\.venv\Scripts\python.exe tools\live_candidate.py --start --expected-model $exaoneQ4 --seed 11 --semantic-retention
```

Answer each displayed interviewer turn with a plausible 25–60 word junior-to-mid response, deliberately leaving some metrics, ownership, and failure-analysis details incomplete. Continue with `--answer` until the interview ends, and record the emitted session ID immediately.

Render and audit the session:

```powershell
.\.venv\Scripts\python.exe tools\render_transcript.py --live --session $sessionId --out "data\sessions\$sessionId\transcript.html"
.\.venv\Scripts\python.exe tools\probe_audit.py --session $sessionId --out "data\sessions\$sessionId\probe_audit.json"
```

- [ ] **Step 2: Adjudicate every eligible action conflict**

Filter to `advance + ok=false + exactly one raw question` whose final guard recorded `invented-question-dropped`. For each row, record whether the question is:

- relevant to the current interview question;
- fresh relative to used focus/history;
- at most 15 words;
- a single independent question;
- answerable from the candidate's experience; and
- within the current question family.

Persist the adjudication beside the generated session, not in a tracked source directory.

- [ ] **Step 3: Apply the mandatory implementation gate**

Do not write promotion code unless all are true:

- at least five eligible examples exist;
- at least 60% are usable on every criterion above;
- no more than 20% repeat an existing focus; and
- none crosses question families.

If any condition fails, record `promotion_candidate: rejected` and the measured reason in the comparison summary. Skip Steps 4–7 and leave the capability absent.

- [ ] **Step 4: If and only if the gate passes, add failing opt-in tests**

```python
@pytest.mark.parametrize("model_id", [
    "exaone-3.5-2.4b-q4_k_m",
    "exaone-3.5-2.4b-q5_k_m",
    "granite-4.1-3b",
    "granite-4.2-3b-a800m-instruct",
    "yi-1.5-6b-chat",
    "unknown",
])
def test_advance_question_promotion_is_off_for_every_profile_by_default(model_id):
    assert Speech.for_model(model_id).promote_advance_question is False


def test_opt_in_promotes_one_safe_fresh_advance_question(tmp_path):
    r, state = build([d("advance", "Which part did you own?", ok=False)], tmp_path)
    r.speech = Speech(trust_ok=False, promote_advance_question=True)
    run(r.ask())
    result = run(r.submit("I worked with the wider platform team."))
    record = last_decision(state)
    assert result.act == "probe"
    assert record["say_raw"] == "Which part did you own?"
    assert record["speech_attempts"][0]["reason"] == "fresh_focus"


@pytest.mark.parametrize(
    "say",
    [
        "What did you do, and what happened next?",
        "What was the exact private revenue figure?",
        "Which part did you own? Which part did your manager own?",
    ],
)
def test_promotion_rejects_compound_or_unknowable_questions(tmp_path, say):
    r, state = build([d("advance", say, ok=False)], tmp_path)
    r.speech = Speech(trust_ok=False, promote_advance_question=True)
    run(r.ask())
    result = run(r.submit("I worked with the wider platform team."))
    assert result.act == "advance"
    assert result.spoken.text != say
    assert last_decision(state)["speech_attempts"][0]["reason"] == "action_changed"
```

- [ ] **Step 5: Run and confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -k "promotion or promotes_one_safe" -q -p no:cacheprovider
```

- [ ] **Step 6: Implement the smallest disabled capability**

Add the disabled capability and an explicit eligible-only guard parameter. Replace the current `advance` question condition inside Guard 1 with this combined condition; do not add a second action-resolution branch elsewhere:

```python
@dataclass
class Speech:
    # Existing fields remain unchanged.
    promote_advance_question: bool = False


def apply(
    raw: dict | None,
    utterance: str,
    said_this_question: list[str],
    trust_ok: bool = True,
    promote_advance_question: bool = False,
) -> Guarded:
    # Existing parsing remains above this branch.
    if not ok and act == "advance" and (trust_ok or promote_advance_question):
        act = "probe"
        applied.append(
            "advance-question->probe"
            if promote_advance_question and not trust_ok
            else "invented-question->probe"
        )
```

Compute eligibility in `Runner.submit` before every applicable `guards.apply` call, because only the runner owns focus history:

```python
raw_say = (raw.get("say") or "").strip() if isinstance(raw, dict) else ""
fresh = focus.classify(
    raw_say,
    exaone_semantics=self.speech.semantic_retention,
) - self.focus_used
promotion_eligible = (
    self.speech.promote_advance_question
    and isinstance(raw, dict)
    and raw.get("act") == "advance"
    and not bool(raw.get("ok"))
    and guards.question_count(raw_say) == 1
    and len(raw_say.split()) <= 15
    and len(fresh) == 1
    and not guards.is_unanswerable_probe(raw_say)
)
g = guards.apply(
    raw,
    utterance,
    self.said_this_question,
    self.speech.trust_ok,
    promote_advance_question=promotion_eligible,
)
```

Implement `guards.is_unanswerable_probe(text: str) -> bool` with only the evidence-grounded private/confidential/unpublished/exact-company-figure forms found in Step 2. Do not pretend to solve answerability with a broad heuristic. Promotion changes `advance` to `probe`; it must not allow an unguarded question to remain attached to `advance` or `end`. Extend the tracked profile serialisation tests and both harness CLIs with `--promote-advance-question`, but keep the flag false for Exaone and all other production profiles until Task 9.

- [ ] **Step 7: Verify and commit the optional arm**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_guards.py tests/test_runner.py -q -p no:cacheprovider
git add -- app/guards.py tests/test_guards.py tools/experiment_profile.py tools/live_candidate.py tests/test_experiment_profile.py
git add -p -- app/runner.py tests/test_runner.py
git diff --cached --check
git diff --cached --name-only
git commit -m "Trial Exaone advance probes"
```

The private `tools/stage1_replay.py` change stays untracked/ignored.

---

### Task 8: Run Symmetric Fixed-Fixture and Replay Comparisons

**Files:**

- Modify locally, never stage: `tools/tier1_model_screen.py` (ignored private harness)
- Modify locally, never stage: `tools/stage1_replay.py` (ignored private harness)
- Generate only: `data/sessions/**`
- Generate only: `data/comparisons/exaone-semantic-retention.json`

**Interfaces:**

- Consumes: `LiveProfile`, `build_replay_summary`, `audit`, the private 60-fixture screen, and private pinned/unpinned replay harness.
- Produces: ignored comparison JSON keyed by arm, model ID, complete profile, harness SHA-256, session IDs, controls, fixed metrics, replay metrics, speech audit, and arm disposition.

- [ ] **Step 1: Define the admissible arms before running them**

Run these one-variable-at-a-time arms:

1. committed Exaone baseline at `5e21330`;
2. shared-guard control;
3. instrumented control with all speech experiments off;
4. classifier-only candidate;
5. classifier plus off-focus retry;
6. promotion candidate only if Task 7 passed.

Run a fresh baseline from an isolated worktree at `5e21330`; use `superpowers:using-git-worktrees` during execution and do not reset the current dirty branch. Before copying an output session back to this branch's ignored `data/sessions`, verify the source contains the expected `session.json`, `transcript.json`, and `decisions.jsonl`, and verify the destination session ID does not exist. Preserve outputs by session ID, then remove only that exact temporary worktree after resolving and checking its path. Eliminate an arm immediately if it violates a non-negotiable safety gate.

- [ ] **Step 2: Run the 60 fixed action fixtures for Q4 and Q5**

Extend the ignored private screen locally with the tracked `LiveProfile`/summary helper and switches for the current arm. Add `"--parallel", "1"` to its existing `lms load` command; it already sets context 8192, temperature 0, and seed 11. Persist the harness file SHA-256 in every result so later local edits cannot be confused. Never stage this private harness change.

Load only one model at a time in LM Studio and confirm thinking is off before each model. Run the 60-case screen with the resolved `Speech.for_model(model_id)` profile, and capture model ID, full speech profile, canary speed, raw/guarded/product action, severity loss, family crossings, focus drift, speech disposition, latency, and model-call count. Use the exact model key reported by `prov.model_key`, for example:

```powershell
.\.venv\Scripts\python.exe tools\tier1_model_screen.py $exaoneQ4
```

Run Q4 first for every surviving arm, then Q5. Run Granite 4.2 and Granite 4.1 on the same harness revision as controls. Any harness path that falls back to default `Speech()` instead of `Speech.for_model(model_id)` is invalid and must be fixed/tested before collecting results.

- [ ] **Step 3: Run both recorded 22-turn replays pinned and unpinned**

For Q4, run the instrumented control, classifier-only candidate, and classifier-plus-retry candidate on both replay scripts. Run two independent sessions for each pinned/unpinned condition because speech enters later model history. Repeat surviving candidates on Q5.

Use the explicit switches from Task 6, for example:

```powershell
.\.venv\Scripts\python.exe tools\stage1_replay.py --expected-model $modelId --seed 11 --semantic-retention
.\.venv\Scripts\python.exe tools\stage1_replay.py --expected-model $modelId --seed 11 --semantic-retention --retry-off-focus
```

Use the harness's existing pin option for pinned arms; do not emulate pinning by editing prompts.

- [ ] **Step 4: Audit each generated session from persisted decisions**

```powershell
.\.venv\Scripts\python.exe tools\probe_audit.py --session $sessionId --out "data\sessions\$sessionId\probe_audit.json"
```

Reject a run if its saved model/profile differs from the requested arm, if provenance is incomplete, or if canary speed/power drift makes it incomparable.

- [ ] **Step 5: Build the ignored comparison record**

Write `data/comparisons/exaone-semantic-retention.json` from saved screen summaries, replay summaries, and audit JSON. Include every session ID and exact profile switch; do not transcribe terminal numbers by hand. For each arm, calculate:

- action accuracy and severity-weighted loss;
- family crossing and invalid-output counts;
- close count and total turns;
- probes and reasks;
- relevant raw-question retention and template substitution;
- retry acceptance and rejection reasons;
- repeated/compound/over-length spoken questions;
- decision p90 and model calls.

- [ ] **Step 6: Select live candidates without committing generated evidence**

Apply the specification's ordering: safety first, then lowest fixed severity, then live potential/retention, then repetition/genericity, turns/model calls/latency. Prefer Q4 when it is within one severity point of Q5. Carry no more than the best safe Q4 arm and best safe Q5 arm into Task 9.

---

### Task 9: Run Matched Live Controls and Select the Product Profile

**Files:**

- Modify after evidence: `app/runner.py`
- Modify after evidence: `tests/test_runner.py`
- Generate only: `data/sessions/**`
- Generate only: `data/comparisons/exaone-semantic-retention.json`

**Interfaces:**

- Consumes: Task 8's surviving Q4/Q5 arms and Task 6's model/profile-enforcing live CLI.
- Produces: matched strong and junior live sessions, manual relevance adjudication, Granite 4.1/4.2 controls, final behind/close/match classification, and the evidence-selected `Speech.for_model` defaults.

Every live arm has the same non-negotiable safety gates: zero family crossings; zero invalid outputs escaping deterministic fallback; zero unguarded `advance` or `end` questions; zero spoken lines with two independent questions; zero repeated focus within one interview question; and unchanged stop, skip, clarify, and cannot-answer controls.

- [ ] **Step 1: Record a canary before every live run**

For each model, record model ID, decode speed, time-to-first-token if available, plugged-in status, thinking disabled, context 8192, parallelism 1, temperature 0, and seed 11. Repeat any run with material thermal or power drift.

- [ ] **Step 2: Run the strong-candidate control for each surviving Exaone arm**

Use the same 14-question plan as Granite. Answer the interviewer that actually appears with complete, concise evidence. A passing arm must:

- close all 14 questions;
- finish in at most 18 candidate turns;
- use at most three probes;
- use zero reasks;
- request no answer dimension already supplied; and
- pass every non-negotiable safety gate.

Start each session with its exact saved profile, for example:

```powershell
.\.venv\Scripts\python.exe tools\live_candidate.py --start --expected-model $modelId --seed 11 --semantic-retention
```

Add `--retry-off-focus` or `--promote-advance-question` only for that named arm.

Eliminate any arm that fails; do not carry it to final selection.

- [ ] **Step 3: Run the junior-to-mid control for each remaining Exaone arm**

Use natural 25–60 word answers with some incomplete metrics, ownership, and failure analysis. Answer the displayed interviewer rather than replaying fixed text after navigation diverges. Render and manually adjudicate every spoken probe for relevance.

Classify an arm as **close to Granite 4.2** only if it:

- closes all 14 questions in at most 25 turns;
- uses at most nine probes and one reask;
- retains at least 50% of relevant model-authored probe/reask questions;
- uses templates for at most 50% of model-authored probe/reask questions;
- achieves at least 80% manually adjudicated spoken-probe relevance; and
- passes every safety gate.

Classify it as **matching Granite 4.2** only if it:

- closes all 14 questions in at most 23 turns;
- uses at most seven probes and zero reasks;
- retains at least 60% of relevant model-authored questions;
- substitutes templates for at most 40%; and
- passes every safety gate.

- [ ] **Step 4: Rerun Granite controls on the same harness revision**

Run Granite 4.2 strong and junior-to-mid controls, then at least the Granite 4.1 junior-to-mid control. Do not use the earlier transcripts as matched measurements. Exaone's decision p90 must be no more than one second slower than the new Granite 4.2 control.

- [ ] **Step 5: Adjudicate the off-focus retry arm separately**

It is production-eligible only if, relative to classifier-only, it:

- reduces substitutions by at least 20 percentage points on model-authored probe/reask turns;
- retains at least 60% of retry attempts;
- adds no family crossing; and
- keeps decision p90 within one second of classifier-only.

If it fails, leave `retry_off_focus=False`. Retain the disabled, tested capability and private-harness switch because they are required to reproduce the documented rejected arm; do not enable it in any production profile.

- [ ] **Step 6: Add a failing test for the evidence-selected profile**

For example, if classifier-only Q4 wins:

```python
def test_exaone_product_profile_uses_selected_semantic_policy():
    q4 = Speech.for_model("exaone-3.5-2.4b-q4_k_m")
    q5 = Speech.for_model("exaone-3.5-2.4b-q5_k_m")
    assert q4.semantic_retention is True
    assert q4.retry_off_focus is False
    assert q4.trust_ok is False
    assert q4.max_say_words == 15
    assert q5.semantic_retention is False
```

Write the assertions from measured selection, not from this example. If Task 7 produced the optional field, add a separate assertion for its selected value; if the gate rejected implementation, do not reference a nonexistent field. Add explicit Granite 4.1, Granite 4.2, Yi, and unknown-model non-regression assertions.

- [ ] **Step 7: Make only the selected profile defaults production behaviour**

Change `Speech.for_model` and remove rejected experimental branches when they are no longer required for reproducibility. Keep Q5 distinct unless it independently passes. Do not alter Granite defaults as a side effect.

- [ ] **Step 8: Verify and commit the evidence-backed selection**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_focus.py tests/test_guards.py tests/test_runner.py tests/test_persistence.py tests/test_probe_audit.py tests/test_live_candidate_profile.py tests/test_experiment_profile.py -q -p no:cacheprovider
git add -p -- app/runner.py tests/test_runner.py
git diff --cached --check
git diff --cached
git commit -m "Select Exaone probing profile"
```

Skip this commit if no production default changes.

---

### Task 10: Final Regression, Evidence Audit, and Handoff

**Files:**

- Modify if necessary: `tools/README.md`
- Generate only: `data/comparisons/exaone-semantic-retention.json`
- Read: all changed source/test files and generated comparison artefacts

**Interfaces:**

- Consumes: all source changes, automated tests, exact generated session IDs, audit reports, manual adjudications, and the ignored comparison JSON.
- Produces: a clean verified branch handoff with calibrated claims, exact test evidence, commit hashes, and a list of preserved user-owned files.

- [ ] **Step 1: Inspect branch scope before claiming completion**

```powershell
git status --short
git log --oneline --decorate -12
git diff 5e21330 --stat
git diff --check 5e21330
git diff --name-only 5e21330
```

Confirm the original unrelated architecture documents remain untracked and generated sessions/comparison JSON are neither staged nor committed.

- [ ] **Step 2: Run syntax and focused verification**

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tools tests
.\.venv\Scripts\python.exe -m pytest tests/test_focus.py tests/test_guards.py tests/test_runner.py tests/test_persistence.py tests/test_probe_audit.py tests/test_live_candidate_profile.py tests/test_experiment_profile.py -q -p no:cacheprovider
```

If Windows temp-directory ACL errors occur, verify the traceback is confined to pytest/`tempfile`, then rerun the identical command outside the managed sandbox. Do not relabel an application failure as an environment failure.

- [ ] **Step 3: Run the full automated suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Record exact passed/failed/skipped counts and elapsed time. Live evidence supplements but does not replace this suite.

- [ ] **Step 4: Verify every acceptance criterion from persisted evidence**

Check that:

- every model-backed row has `say_raw` and complete ordered `speech_attempts`;
- retained lines are short, single-focus, relevant, and fresh;
- templates still catch unsafe, generic, repeated, compound, and over-length questions;
- candidate stop, skip, clarify, and cannot-answer controls remain unchanged;
- every enabled policy passed fixed, replay, strong-live, and junior-live gates;
- Q4, Q5, Granite 4.1, and Granite 4.2 results identify exact session IDs and profiles; and
- the comparison labels Exaone as behind, close, or matching strictly from Task 9's gates.

- [ ] **Step 5: Commit only a necessary documentation clarification**

If `tools/README.md` changed after Task 6:

```powershell
git add -- tools/README.md
git diff --cached --check
git commit -m "Document Exaone probe audit"
```

Otherwise, do not manufacture a final commit.

- [ ] **Step 6: Deliver a calibrated report**

Report:

- selected Q4/Q5 profile and rejected arms;
- fixed, replay, strong-live, and junior-live metrics;
- exact Exaone and Granite session IDs;
- raw retention, template substitution, relevance, safety, latency, and model-call results;
- whether Exaone is behind, close to, or matching Granite 4.2;
- remaining limitations and the next highest-value experiment;
- commit hashes and uncommitted user-owned files preserved.

Do not commit `data/`, transcripts, the comparison JSON, architecture documents, or private Tier-1 harnesses.

## Plan Completion Conditions

This plan is complete only when all ten tasks have either passed or produced an explicit evidence-backed rejection, the full Python 3.12 suite passes, generated evidence remains uncommitted, and the final comparison uses matched live controls rather than historical Granite sessions.
