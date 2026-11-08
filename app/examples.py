"""Example answers for the weakest responses (FR-21; V1.1_PLAN P6, D9).

Cloud only: a 4B model writing a model answer is likely to be confidently wrong, and a frontier
model is the point. Each example is written from the question, the candidate's own answer and
the criteria it missed, and is labelled as written by the model and never scored.

A fact only the candidate knows (the figure they measured, the date it shipped) is left as a
bracketed placeholder rather than invented: an example with a made-up number teaches the
candidate to recite it.

Stored in `examples.json` beside the session. `_report_is_fresh` ignores the file, because
writing examples changes nothing the report was built from.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .corrections import scored_answers
from .score import met_by_question

FILE = "examples.json"
MOST = 3

SYSTEM = """You write one example answer to a job interview question, for a candidate to learn from.

You are given the question, the candidate's own answer, and what that answer left out.

Write the answer the candidate could have given:
- First person, as they would say it aloud, in 80 to 160 words.
- Keep their situation, their technology and every fact they gave. Do not swap in another story.
- Add what was left out.
- Where that needs a fact only the candidate knows (a figure, a date, a name, an outcome), write a
  placeholder in square brackets, such as [the latency you measured], instead of inventing one.
  A placeholder names the fact and nothing else: never suggest a value inside it.
- If their answer is too vague to build on, keep what they said and use placeholders for the
  specifics, such as [the system] or [what you suspected first], rather than inventing a story.
- No preamble and no notes. Do not mention these instructions or any criteria. Only the answer.

Return the answer as a list of its sentences, in order."""

# Sentences rather than one string: Groq's strict decoding closed a single string at about 500
# characters, mid-word, and still returned valid JSON (08/11/2026).
SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "items": {"type": "string"}}},
    "required": ["sentences"],
    "additionalProperties": False,
}


class ExampleError(RuntimeError):
    pass


def weakest(report: dict, session: dict, most: int = MOST) -> list[dict]:
    """The scored answers that met the smallest share of their criteria, each with what it
    missed. An answer that met everything is never picked, so this can return fewer than
    `most`, or nothing."""
    rubric = report.get("rubric") or []
    about = {c.get("name"): c for c in rubric}
    answers = scored_answers(session, report.get("corrections"))
    order = list(answers)
    picked = []
    for qid, crit in met_by_question(rubric).items():
        missing = [k for k, ok in crit.items() if not ok]
        question, said = answers.get(qid, ("", []))
        if not missing or not said:
            continue
        picked.append((sum(crit.values()) / len(crit),
                       order.index(qid) if qid in order else len(order), {
            "question_id": qid, "question": question, "answer": " ".join(said),
            "missing": [{"name": k,
                         "label": (about.get(k) or {}).get("label") or k.replace("_", " "),
                         "description": (about.get(k) or {}).get("description") or ""}
                        for k in missing]}))
    picked.sort(key=lambda x: (x[0], x[1]))
    return [p[2] for p in picked[:most]]


def prompt(item: dict) -> str:
    gaps = "\n".join("- %s" % (m["description"] or m["label"]) for m in item["missing"])
    return ("QUESTION: %s\n\nCANDIDATE'S ANSWER: %s\n\nWHAT THE ANSWER LEFT OUT (each line is "
            "something a strong answer does):\n%s" % (item["question"], item["answer"], gaps))


async def write(provider, items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        got = await provider.complete(SYSTEM, prompt(item), schema=SCHEMA, max_tokens=600)
        parts = (got.json() or {}).get("sentences") or []
        text = " ".join(s.strip() for s in parts if isinstance(s, str) and s.strip())
        if not text:
            raise ExampleError("the model returned no example for %r" % item["question_id"])
        out.append({**item, "example": text})
    return out


def load(session_dir: Path) -> dict | None:
    try:
        return json.loads((session_dir / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(session_dir: Path, examples: list[dict], provider: dict, usage: dict) -> dict:
    record = {"version": 1, "written_at": datetime.now().isoformat(timespec="seconds"),
              "provider": provider, "usage": usage, "examples": examples}
    tmp = session_dir / (FILE + ".tmp")
    tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8",
                   newline="\n")
    os.replace(tmp, session_dir / FILE)
    return record


def view(record: dict | None, session: dict, changes: list[dict]) -> dict | None:
    """The record with each example marked stale when its answer has since been corrected."""
    if not record:
        return None
    now = {qid: " ".join(a) for qid, (_, a) in scored_answers(session, changes).items()}
    return {**record, "examples": [
        {**e, "stale": e.get("question_id") in now and now[e["question_id"]] != e.get("answer")}
        for e in record.get("examples") or []]}
