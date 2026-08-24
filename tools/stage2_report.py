"""Run the extractor and scorer over a recorded session.

Offline by design: it reads `transcript.json`, so a session can be re-scored after the
extractor changes without re-interviewing anyone.

Re-scoring is NOT repeatable, and a comparison of two extractor versions has to account for
that. `score.py` is pure arithmetic, but the observations it consumes come from a model call,
and the same transcript re-scored five times gave states_outcome 7,7,8,8,9 out of 10 --
temperature is already 0.0 with a fixed seed, so this is the runtime, not sampling. A change
worth believing has to move a criterion further than that band (log 9.7).

    python tools/stage2_report.py                     # the most recent session
    python tools/stage2_report.py --session <id>
    python tools/stage2_report.py --session <id> --quotes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools._console import utf8  # noqa: E402

utf8()

from app import observe, provider as prov, report as rep, score, session as sess  # noqa: E402


def latest() -> str:
    done = [d for d in (ROOT / "data" / "sessions").iterdir()
            if (d / "transcript.json").exists()]
    return sorted(done, key=lambda d: d.stat().st_mtime)[-1].name


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--quotes", action="store_true", help="show the evidence for every criterion")
    ap.add_argument("--feedback", action="store_true", help="print the candidate-facing report")
    ap.add_argument("--plan", default=str(ROOT / "config" / "interview_swe_general.json"))
    ap.add_argument("--re-extract", action="store_true",
                    help="ignore the cached extraction and call the model again")
    a = ap.parse_args()

    sid = a.session or latest()
    d = ROOT / "data" / "sessions" / sid
    turns = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["turns"]
    # Why each question ended. Older sessions predate the field and simply have none.
    closed = [SimpleNamespace(**q) for q in
              json.loads((d / "session.json").read_text(encoding="utf-8")).get("questions", [])]
    plan = sess.load_plan(a.plan)
    meta = {q["question_id"]: q for q in sess.iter_questions(plan)}

    by_q: dict[str, list[str]] = defaultdict(list)
    order: list[str] = []
    for t in turns:
        if t["question_id"] not in by_q:
            order.append(t["question_id"])
        by_q[t["question_id"]].append(t["utterance"])

    p = prov.LMStudio()
    print("session %s -- %d questions, %d answers\n" % (sid, len(order), len(turns)))

    items = [(qid, meta.get(qid, {}).get("question", qid), by_q[qid],
              meta.get(qid, {}).get("observation_shape", "star")) for qid in order]
    observations, cached = await observe.observe_all(
        p, items, cache=d / "observations.json", re_extract=a.re_extract)
    print("  extraction: %s\n" % (
        "cached (re-run gives the same report)" if cached
        else "fresh (re-running moves a criterion by a point or two)"))

    for obs in observations:
        parts = observe.DESIGN_PARTS if obs.shape == "design" else observe.STAR_PARTS
        got = [k[:4] for k in parts if getattr(obs, k)]
        print("  %-24s %-9s %-30s %s%s" % (
            obs.question_id, obs.addresses_question, ",".join(got) or "-",
            "".join(c for c, k in (("F", "first_person"), ("D", "specific_detail"),
                                   ("M", "measurement_stated")) if getattr(obs, k)) or "-",
            "   DROPPED %d" % len(obs.dropped_quotes) if obs.dropped_quotes else ""))

    report = score.build(sid, observations,
                         {qid: meta.get(qid, {}).get("rubric_criteria", []) for qid in order})

    print("\n  %-22s %s" % ("criterion", "met"))
    print("  " + "-" * 44)
    for name, (got, n) in sorted(report.totals.items()):
        bar = "#" * round(10 * got / n) + "." * (10 - round(10 * got / n))
        print("  %-22s %s %2d/%-2d" % (name, bar, got, n))

    if report.weakest:
        print("\n  Weakest, and what feedback would lead with:")
        for name in report.weakest:
            print("    %-22s %s" % (name, score.CRITERIA[name][1]))

    if a.quotes:
        print("\n  Evidence per question")
        for qs in report.scores:
            print("\n  %s" % qs.question[:76])
            for name, met in qs.met.items():
                print("    %-20s %-3s %s" % (name, "yes" if met else "no",
                                             qs.evidence[name][:64]))

    if a.feedback:
        print("\n" + "=" * 70)
        print(rep.render(report, questions_asked=len(order),
                         questions_answered=sum(1 for o in observations if o.text.strip()),
                         observations=observations, question_states=closed))
        print("=" * 70)

    dropped = sum(len(o.dropped_quotes) for o in observations)
    print("\n  VERDICT")
    print("    quotes dropped as ungrounded: %d of %d extracted" % (
        dropped, sum(1 for o in observations for k in ("situation", "action", "result")
                     if getattr(o, k)) + dropped))
    print("    unanswered questions: %d" % sum(1 for o in observations if not o.text.strip()))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except prov.ProviderError as e:
        print("provider error: %s" % e)
        sys.exit(1)
