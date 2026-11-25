from __future__ import annotations

import json

import pytest

from app import session as sess
from tools import live_candidate as lc

PLAN = sess.load_plan(lc.ROOT / "config" / "interview_swe_general.json")


def _entry(q, act, asked=(), said="an answer", reply="A line?"):
    return {"q": q, "phase": "p", "kind": "script", "said": said, "act": act,
            "guards": [], "reply": reply, "asked": list(asked)}


@pytest.mark.parametrize("gap, act, asked, expected", [
    ("no outcome", "advance", [], "missed"),
    ("no outcome", "probe", ["OUTCOME"], "targeted"),
    ("no outcome", "probe", ["ROLE"], "other"),
    ("we throughout", "probe", ["ROLE", "STEPS"], "targeted"),
    ("we throughout", "reask", [], "other"),
    ("it went well", "probe", ["MEASURE"], "targeted"),
    ("no figure", "probe", ["OUTCOME"], "other"),
])
def test_a_gap_counts_only_when_the_line_asks_for_what_it_leaves_out(gap, act, asked, expected):
    assert lc.verdict(gap, _entry(3, act, asked)) == expected


def test_an_unreached_gap_is_missed_and_an_unknown_label_is_refused():
    assert lc.verdict("no outcome", None) == "missed"
    with pytest.raises(KeyError):
        lc.verdict("no story", _entry(3, "probe", ["OUTCOME"]))


def test_report_keeps_the_old_follow_up_count_beside_the_targeted_one(capsys):
    script = {3: {"gap": "no outcome"}, 4: {"gap": "we throughout"}, 5: {"gap": "no figure"}}
    log = [_entry(3, "probe", ["ROLE"], reply="Which parts were yours?"),
           _entry(3, "advance"),
           _entry(4, "probe", ["ROLE"]),
           _entry(5, "advance")]
    got = lc.report(PLAN, script, log)
    assert (got["gaps_targeted"], got["gaps_followed"], got["gaps"]) == (1, 2, 3)
    rows = {r["q"]: r for r in got["rows"]}
    assert [rows[n]["verdict"] for n in (3, 4, 5)] == ["other", "targeted", "missed"]
    assert rows[3]["reply"] == "Which parts were yours?"
    assert "followed, asked ROLE" in capsys.readouterr().out


def test_saved_logs_take_the_asked_focus_from_their_own_turn_in_order():
    log = [{"said": "That's all."}, {"said": "Real answer."}, {"said": "That's all."}]
    records = [{"utterance": "That's all.", "focus_got": ["ROLE"]},
               {"utterance": "Real answer.", "focus_got": ["OUTCOME"]},
               {"utterance": "That's all.", "focus_got": []}]
    lc.fill_asked(log, records)
    assert [e["asked"] for e in log] == [["ROLE"], ["OUTCOME"], []]


def test_rescore_reads_a_saved_run_and_its_session(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions" / "s1"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(json.dumps({"plan_snapshot": PLAN}),
                                              encoding="utf-8")
    (session_dir / "decisions.jsonl").write_text(
        json.dumps({"turn": 0, "utterance": "We did it.", "focus_got": ["ROLE"]}) + "\n",
        encoding="utf-8")
    entry = _entry(3, "probe", said="We did it.")
    del entry["asked"]
    (tmp_path / "field_script_x.json").write_text(json.dumps(
        {"field": "x", "session": "s1", "status": "complete", "log": [entry]}), encoding="utf-8")
    monkeypatch.setattr(lc, "read_script", lambda field: {3: {"gap": "we throughout"}})
    assert lc.rescore(tmp_path) == (1, 1, 1)
