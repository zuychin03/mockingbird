"""Correcting what the recogniser heard, before it is scored (FR-31; V1.1_PLAN P5).

Live mode sends an answer as it was heard, so a recognition error would be scored as if the
candidate had said it, and errors fall hardest on accented speech. After the interview, and only
then (FR-35 forbids editing during it), each answer can be corrected. Corrections live in their
own `corrections.json` beside the session; the transcript, the decisions and `session.json` are
never rewritten, so what the interviewer actually heard and acted on stays on record.

Writing the file makes the cached report older than the session folder, which is all
`_report_is_fresh` needs to rebuild it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

FILE = "corrections.json"
MAX_CHARS = 20000


class CorrectionError(ValueError):
    pass


def load(session_dir: Path) -> dict | None:
    try:
        return json.loads((session_dir / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _answers(raw: dict) -> dict[str, tuple[str, list[str]]]:
    """question_id -> (question, the answers as scored), from `session.json`."""
    return {q["question_id"]: (q.get("question", ""), list(q.get("answers") or []))
            for q in raw.get("questions") or []}


def save(session_dir: Path, raw: dict, edits: list[dict]) -> dict:
    """Keep the edits that change something. An empty list still records that the answers were
    reviewed, so the report does not ask again."""
    scored = _answers(raw)
    kept: dict[str, list[dict]] = {}
    for e in edits:
        qid, text = e.get("question_id"), (e.get("text") or "").strip()
        if qid not in scored:
            raise CorrectionError("no question %r in this interview" % qid)
        index = e.get("index")
        answers = scored[qid][1]
        if not isinstance(index, int) or not 0 <= index < len(answers):
            raise CorrectionError("question %r has no answer %r" % (qid, index))
        if not text:
            raise CorrectionError("an answer cannot be corrected to nothing")
        if len(text) > MAX_CHARS:
            raise CorrectionError("that correction is too long")
        if text != answers[index].strip():
            kept.setdefault(qid, []).append({"index": index, "original": answers[index],
                                             "text": text})
    record = {"version": 1, "saved_at": datetime.now().isoformat(timespec="seconds"),
              "answers": kept}
    tmp = session_dir / (FILE + ".tmp")
    tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8",
                   newline="\n")
    os.replace(tmp, session_dir / FILE)
    return record


def apply(states: list, record: dict | None) -> list[dict]:
    """Put corrected text into the answers the scorer reads. A correction whose original no
    longer matches is skipped rather than applied to a different answer."""
    if not record:
        return []
    changes = []
    by_id = {s.question_id: s for s in states}
    for qid, rows in (record.get("answers") or {}).items():
        s = by_id.get(qid)
        if s is None:
            continue
        # A copy: the list may be the one the loaded session holds, and the original stays put.
        s.answers = list(s.answers)
        for row in rows:
            i = row.get("index")
            if isinstance(i, int) and 0 <= i < len(s.answers) and s.answers[i] == row["original"]:
                s.answers[i] = row["text"]
                changes.append({"question_id": qid, "question": s.question, "index": i,
                                "original": row["original"], "corrected": row["text"]})
    return changes


def as_changes(record: dict | None) -> list[dict]:
    """The saved file in the shape `apply` returns, for readers that have no report to hand."""
    return [{"question_id": qid, "index": r.get("index"), "original": r.get("original"),
             "corrected": r.get("text")}
            for qid, rows in ((record or {}).get("answers") or {}).items() for r in rows]


def scored_answers(raw: dict, changes: list[dict] | None) -> dict[str, tuple[str, list[str]]]:
    """question_id -> (question, answers) as the report scored them: `session.json` with the
    report's own list of applied corrections laid over it."""
    out = _answers(raw)
    for c in changes or []:
        row = out.get(c.get("question_id"))
        i = c.get("index")
        if row and isinstance(i, int) and 0 <= i < len(row[1]) and row[1][i] == c.get("original"):
            row[1][i] = c.get("corrected") or row[1][i]
    return out


def review(session_dir: Path, raw: dict, turns: list[dict]) -> list[dict]:
    """Every scored answer with what can help correct it: the recording it came from and what
    the recogniser heard, matched through the turn that carried it."""
    record = load(session_dir) or {}
    corrected = {(qid, r["index"]): r["text"]
                 for qid, rows in (record.get("answers") or {}).items() for r in rows}
    rows = []
    for qid, (question, answers) in _answers(raw).items():
        for i, text in enumerate(answers):
            turn = next((t for t in turns if t.get("question_id") == qid
                         and (t.get("utterance") or "").strip() == text.strip()), {})
            audio = (turn.get("audio") or "").split("/")[-1] or None
            rows.append({"question_id": qid, "question": question, "index": i,
                         "original": text, "text": corrected.get((qid, i), text),
                         "corrected": (qid, i) in corrected, "heard": turn.get("heard"),
                         "audio": audio, "spoken": bool(audio or turn.get("heard"))})
    return rows
