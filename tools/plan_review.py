"""FR-3 at the terminal: plan an interview from a job description, then review it.

The review LOGIC is `app/review.py`; this is only a surface for it, the way
`tools/live_candidate.py` is a surface for the runner. Stage 4 replaces this with the web UI
and should call the same functions.

State lives on disk between invocations for the reason the live-candidate harness does: each
command is its own process, and the small amount of state that matters is written out
explicitly rather than pickled, because pickling a live object across a code change is how a
harness starts lying.

    python tools/plan_review.py --jd jd.txt
    python tools/plan_review.py --show
    python tools/plan_review.py --propose performance
    python tools/plan_review.py --approve gen.performance.29
    python tools/plan_review.py --add-bank technical_experience gen.performance.29
    python tools/plan_review.py --edit collaboration 0 "Tell me about a disagreement you lost?"
    python tools/plan_review.py --move behavioural_core 3 0
    python tools/plan_review.py --delete design 0
    python tools/plan_review.py --save config/interview_generated.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools._console import utf8  # noqa: E402

utf8()

from app import bank as bank_mod  # noqa: E402
from app import embed, planner, provider as prov, review  # noqa: E402

STATE = ROOT / "data" / "plan_draft.json"
BANK = ROOT / "config" / "question_bank.json"


def save_state(d: review.Draft) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "plan": d.plan,
        "gaps": list(d.gaps),
        "edited_from": d.edited_from,
        "spec": None if d.spec is None else {
            "role": d.spec.role, "seniority": d.spec.seniority,
            "requirements": [[r.name, r.evidence] for r in d.spec.requirements],
            "dropped": [[r.name, r.evidence] for r in d.spec.dropped]},
        # Every question this draft added, whatever its status. Approving one takes it out
        # of `bank.proposed` and it is not in config/ either, so persisting only proposals
        # lost it the moment it was approved. They stay here rather than in the shipped bank
        # because that file is read by every future plan, and an approval belongs to this
        # review until someone saves it.
        "draft_questions": [{"id": q.id, "text": q.text,
                             "competencies": list(q.competencies), "shape": q.shape,
                             "source": q.source, "status": q.status}
                            for q in d.bank.questions if q.generated],
    }, indent=1), encoding="utf-8", newline="\n")


def load_state() -> review.Draft:
    if not STATE.exists():
        raise SystemExit("no draft in progress. Start one with --jd <file>")
    raw = json.loads(STATE.read_text(encoding="utf-8"))
    b = bank_mod.load(BANK)
    for item in raw.get("draft_questions", []):
        if any(q.id == item["id"] for q in b.questions):
            continue
        b = bank_mod.with_question(b, bank_mod.Question(
            id=item["id"], text=item["text"], competencies=tuple(item["competencies"]),
            shape=item["shape"], source=item["source"], status=item["status"]))
    spec = None
    if raw.get("spec"):
        s = raw["spec"]
        spec = planner.JobSpec(
            role=s["role"], seniority=s["seniority"],
            requirements=tuple(planner.Requirement(n, e) for n, e in s["requirements"]),
            dropped=tuple(planner.Requirement(n, e) for n, e in s["dropped"]))
    return review.Draft(plan=raw["plan"], bank=b, spec=spec,
                        gaps=tuple(raw.get("gaps", [])),
                        edited_from=raw.get("edited_from", {}))


def show(d: review.Draft) -> None:
    print("\n%s" % (d.plan.get("label") or d.plan.get("id")))
    print("=" * 74)
    if d.spec:
        print("  role %s   seniority %s" % (d.spec.role, d.spec.seniority))
        print("  the description asked for: %s"
              % ", ".join(r.name for r in d.spec.requirements))
        if d.spec.dropped:
            print("  named but not supported by its own words: %s"
                  % ", ".join(r.name for r in d.spec.dropped))
    if d.gaps:
        print("  NOT COVERED by this plan: %s" % ", ".join(d.gaps))
        print("    --propose <competency> writes one for review")
    print()
    for ph in d.plan["phases"]:
        mark = "" if ph["id"] in review.EDITABLE else "   (structural, not editable)"
        print("  [%s]%s" % (ph["id"], mark))
        for i, q in enumerate(ph.get("questions", [])):
            was = d.edited_from.get(q)
            print("    %d. %s" % (i, q))
            if was:
                print("       edited, was: %s" % was)
        print()
    if d.proposals:
        print("  PROPOSED, not askable until approved:")
        for q in d.proposals:
            print("    %-26s %s" % (q.id, q.text))
        print()
    approved_generated = [q for q in d.bank.questions if q.generated and q.askable]
    if approved_generated:
        print("  approved generated questions: %s"
              % ", ".join(q.id for q in approved_generated))


async def start(jd_path: Path) -> review.Draft:
    b = bank_mod.load(BANK)
    p = prov.LMStudio()
    spec = await planner.read_jd(p, b, jd_path.read_text(encoding="utf-8"))
    a = planner.assemble(spec, b)
    return review.from_assembled(a, b, spec)


async def propose(d: review.Draft, competency: str) -> review.Draft:
    p = prov.LMStudio()
    evidence = next((r.evidence for r in (d.spec.requirements if d.spec else ())
                     if r.name == competency), competency)
    q = await planner.propose_question(p, d.bank, competency, evidence,
                                       similarity=embed.similarity)
    print("  proposed %s: %s" % (q.id, q.text))
    print("  it is NOT askable. --approve %s to allow it, then --add-bank <phase> %s"
          % (q.id, q.id))
    return review.propose_into_bank(d, q)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", type=Path)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--propose", metavar="COMPETENCY")
    ap.add_argument("--approve", metavar="ID")
    ap.add_argument("--add-bank", nargs=2, metavar=("PHASE", "ID"))
    ap.add_argument("--add", nargs=2, metavar=("PHASE", "TEXT"))
    ap.add_argument("--edit", nargs=3, metavar=("PHASE", "INDEX", "TEXT"))
    ap.add_argument("--delete", nargs=2, metavar=("PHASE", "INDEX"))
    ap.add_argument("--move", nargs=3, metavar=("PHASE", "FROM", "TO"))
    ap.add_argument("--save", type=Path, metavar="PLAN")
    ap.add_argument("--save-bank", type=Path, default=BANK)
    a = ap.parse_args()

    if a.jd:
        d = await start(a.jd)
        save_state(d)
        show(d)
        return 0

    d = load_state()
    try:
        if a.propose:
            d = await propose(d, a.propose)
        elif a.approve:
            d = review.approve(d, a.approve)
            print("  approved %s -- it is now askable and may be added to a plan" % a.approve)
        elif a.add_bank:
            d = review.add_from_bank(d, a.add_bank[0], a.add_bank[1])
        elif a.add:
            d = review.add(d, a.add[0], a.add[1])
        elif a.edit:
            d = review.edit(d, a.edit[0], int(a.edit[1]), a.edit[2])
        elif a.delete:
            d = review.delete(d, a.delete[0], int(a.delete[1]))
        elif a.move:
            d = review.move(d, a.move[0], int(a.move[1]), int(a.move[2]))
        elif a.save:
            # The bank is written only when an approval happened, so a plain review never
            # rewrites the file every future plan reads from.
            wrote_bank = any(q.generated and q.askable for q in d.bank.questions)
            review.save(d, a.save, a.save_bank if wrote_bank else None)
            print("  wrote %s%s" % (a.save, " and %s" % a.save_bank if wrote_bank else ""))
            return 0
    except (ValueError, KeyError, IndexError) as e:
        print("  refused: %s" % e)
        return 1

    save_state(d)
    if not a.show:
        print()
    show(d)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
