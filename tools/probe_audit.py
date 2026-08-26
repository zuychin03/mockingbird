"""Audit how model-written interview questions change before they are spoken."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import focus  # noqa: E402


def _disposition(row: dict, raw: str) -> str:
    guards = row.get("guards") or []
    spoken = row.get("say") or ""
    if not raw or "?" not in raw:
        return "no_raw_question"
    if any(guard in guards for guard in (
            "invented-question-dropped", "invented-question->probe")):
        return "action_conflict"
    if raw != spoken and any(str(guard).startswith("off-focus->") for guard in guards):
        return "substituted"
    if row.get("act") in ("probe", "reask") and raw == spoken:
        return "retained"
    return "other_changed"


def audit(rows: list[dict]) -> dict[str, object]:
    """Return disposition and shape metrics without judging interview quality."""
    counts = {
        "retained": 0,
        "substituted": 0,
        "action_conflicts": 0,
        "other_changed": 0,
        "no_raw_question": 0,
    }
    turns: list[dict] = []
    focus_mismatches: list[dict] = []
    raw_question_total = 0
    multi_question_raw = 0
    over_15_words_raw = 0

    count_key = {"action_conflict": "action_conflicts"}
    for row in rows:
        has_transport_metadata = any(key in row for key in (
            "posterior", "prompt_tokens", "decode_tokens"))
        if has_transport_metadata and not _model_backed(row):
            continue
        raw_value = row.get("say_raw")
        raw = raw_value if isinstance(raw_value, str) else ""
        disposition = _disposition(row, raw)
        counts[count_key.get(disposition, disposition)] += 1

        question_count = raw.count("?")
        word_count = len(raw.split())
        raw_focus = sorted(focus.classify(raw))
        if question_count:
            raw_question_total += 1
            multi_question_raw += int(question_count > 1)
            over_15_words_raw += int(word_count > 15)

        wanted = row.get("focus_asked")
        if question_count and wanted and wanted not in raw_focus:
            focus_mismatches.append({
                "turn": row.get("turn"),
                "focus_asked": wanted,
                "focus_raw": raw_focus,
                "say_raw": raw,
            })

        turns.append({
            "turn": row.get("turn"),
            "act": row.get("act"),
            "disposition": disposition,
            "say_raw": raw_value,
            "say": row.get("say") or "",
            "guards": row.get("guards") or [],
            "focus_asked": wanted,
            "focus_got": row.get("focus_got") or [],
            "focus_raw": raw_focus,
            "question_count": question_count,
            "word_count": word_count,
        })

    denominator = raw_question_total or 1
    return {
        "raw_question_total": raw_question_total,
        **counts,
        "retention_rate": round(counts["retained"] / denominator, 4),
        "template_rate": round(counts["substituted"] / denominator, 4),
        "multi_question_raw": multi_question_raw,
        "over_15_words_raw": over_15_words_raw,
        "focus_mismatches": focus_mismatches,
        "turns": turns,
    }


def _model_backed(row: dict) -> bool:
    """Recognise historical model turns without trusting the old model_calls field."""
    return bool(row.get("posterior") or row.get("prompt_tokens")
                or row.get("decode_tokens"))


def _load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    missing = [row.get("turn") for row in rows
               if _model_backed(row) and "say_raw" not in row]
    if missing:
        raise ValueError(
            "model-backed decisions lack say_raw provenance on turn(s): "
            + ", ".join(map(str, missing)))
    return rows


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session identifier")
    parser.add_argument("--out", required=True, type=Path, help="JSON output path")
    args = parser.parse_args(argv)

    source = Path("data") / "sessions" / args.session / "decisions.jsonl"
    result = audit(_load_rows(source))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "raw questions={raw_question_total} retained={retained} "
        "substituted={substituted} conflicts={action_conflicts} "
        "retention={retention_rate:.1%} templates={template_rate:.1%}".format(**result))
    return result


if __name__ == "__main__":
    main()
