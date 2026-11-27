"""An interview as it was spoken, line by line, from its `transcript.json` (V1.2_PLAN P4).

One reader for History's Transcript view and the HTML export's "what was said", so the two
cannot disagree. Nothing new is captured: a turn already holds its question, the answer, what
the interviewer said back, the phase, the time and the recording. Only the dialogue is read.
`act`, `ok`, the guards and `ask` (the candidate's own question as the model copied it) are the
decision record and stay out, as they do in the live view.
"""

from __future__ import annotations

from pathlib import Path

from . import report as report_mod


def _answer_index(answers: list[str], n: int, said: str) -> int | None:
    """Which scored answer a turn carried: its place among the question's turns, checked by
    text, else the answer with its words (one replay session has more answers than turns)."""
    if n < len(answers) and answers[n].strip() == said.strip():
        return n
    return next((i for i, a in enumerate(answers) if a.strip() == said.strip()), None)


def _recording(turn: dict, session_dir: Path | None) -> str | None:
    name = (turn.get("audio") or "").split("/")[-1]
    if not name or session_dir is None or not (session_dir / "audio" / name).is_file():
        return None
    return name


def lines(session: dict, turns: list[dict], record: dict | None = None,
          session_dir: Path | None = None) -> list[dict]:
    """Every line in order. A question opens each run of turns that answer it; then each
    answer and what the interviewer said back. An answer corrected after the interview
    (`record` is `corrections.json`) carries the correction, its `text` staying as heard."""
    written = {g["question_id"]: g["duty"] for g in report_mod.about(session)["generated"]}
    answers = {q["question_id"]: list(q.get("answers") or [])
               for q in session.get("questions") or []}
    fixed = {(qid, r.get("index")): r
             for qid, rows in ((record or {}).get("answers") or {}).items() for r in rows}
    out: list[dict] = []
    seen: dict[str, int] = {}
    previous = None
    for t in turns:
        qid = t.get("question_id")
        if qid != previous:
            out.append({"who": "interviewer", "kind": "question", "question_id": qid,
                        "phase": t.get("phase"), "text": t.get("question") or "",
                        "duty": written.get(qid)})
            previous = qid
        n = seen.get(qid, 0)
        seen[qid] = n + 1
        said = t.get("utterance") or ""
        if said.strip():
            scored = answers.get(qid, [])
            i = _answer_index(scored, n, said)
            fix = fixed.get((qid, i))
            out.append({"who": "candidate", "kind": "answer", "question_id": qid,
                        "phase": t.get("phase"), "turn": t.get("index"), "at": t.get("at"),
                        "text": said,
                        # Applied as the report applies it: only while the original still matches.
                        "corrected": (fix["text"] if fix and i is not None
                                      and fix.get("original") == scored[i] else None),
                        "audio": _recording(t, session_dir)})
        if (t.get("say") or "").strip():
            out.append({"who": "interviewer", "kind": "reply", "question_id": qid,
                        "text": t["say"]})
    return out
