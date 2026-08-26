from __future__ import annotations

import json

import pytest

from tools.probe_audit import audit, main


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
        {"turn": 3, "act": "advance", "say_raw": None,
         "say": "Thanks -- that's everything from me.", "guards": ["closing->advance"],
         "posterior": {}, "prompt_tokens": 0, "decode_tokens": 0,
         "focus_asked": None, "focus_got": []},
    ]

    result = audit(rows)

    assert result["retained"] == 1
    assert result["substituted"] == 1
    assert result["action_conflicts"] == 1
    assert result["raw_question_total"] == 3
    assert [turn["disposition"] for turn in result["turns"]] == [
        "retained", "substituted", "action_conflict"]


def test_probe_audit_reports_all_dispositions_and_shape_metrics():
    rows = [
        {"turn": 0, "act": "probe", "say_raw": "No question here.",
         "say": "Could you say more?", "guards": ["invalid->probe"],
         "focus_asked": "STEPS", "focus_got": []},
        {"turn": 1, "act": "probe", "say_raw": "Why this? What failed?",
         "say": "Why this?", "guards": ["multi-question-trimmed"],
         "focus_asked": "REASON", "focus_got": ["REASON"]},
        {"turn": 2, "act": "probe",
         "say_raw": "What happened after the production release was completed by the team "
                    "during the planned overnight deployment window yesterday?",
         "say": "What happened next?", "guards": ["too-long->shortened"],
         "focus_asked": "OUTCOME", "focus_got": ["OUTCOME"]},
    ]

    result = audit(rows)

    assert result["no_raw_question"] == 1
    assert result["other_changed"] == 2
    assert result["multi_question_raw"] == 1
    assert result["over_15_words_raw"] == 1
    assert result["retention_rate"] == 0.0
    assert result["template_rate"] == 0.0


def test_cli_rejects_old_model_backed_rows_without_raw_provenance(tmp_path, monkeypatch):
    session_id = "old-session"
    session_dir = tmp_path / "data" / "sessions" / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "decisions.jsonl").write_text(json.dumps({
        "turn": 0, "act": "probe", "say": "What happened?", "guards": [],
        "posterior": {"probe": 0.9}, "prompt_tokens": 10, "decode_tokens": 4,
    }) + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="say_raw"):
        main(["--session", session_id, "--out", "audit.json"])
