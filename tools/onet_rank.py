"""Rank each field's competencies by O*NET® importance (V1.2_PLAN D11).

Reads the O*NET® Database's work activities file from a path the developer downloaded, takes
the importance rating (scale IM, 1 to 5) of every work activity the bank maps a competency to,
and averages it over the field's occupations. The scores, the database version and the date go
into `config/fields.json`, and each new field's stock kinds get their ranked lists from them.
Nothing is fetched at run time (NFR-4); this tool is the record of how the shipped ranks were
derived, which the CC BY 4.0 notice in THIRD_PARTY_NOTICES.md points to.

31.0 publishes it as `db_31_0_csv/work_activities.csv`; earlier releases as tab-separated
`Work Activities.txt`. The columns are the same, so either is read.

    python tools/onet_rank.py "C:/onet/work_activities.csv" --version 31.0
    python tools/onet_rank.py <file> --version 31.0 --dry-run

Software's kinds are never rewritten: its stock plans stay as 1.1 shipped them (D5).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bank as bank_mod  # noqa: E402

FIELDS_JSON = ROOT / "config" / "fields.json"
SHARED_PHASES = ("behavioural_core", "collaboration")


def read_importance(path: str | Path) -> dict[str, dict[str, float]]:
    """{O*NET-SOC code: {element id: importance}} from the IM rows."""
    out: dict[str, dict[str, float]] = {}
    delimiter = "," if Path(path).suffix.lower() == ".csv" else "\t"
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=delimiter):
            if row["Scale ID"] == "IM":
                out.setdefault(row["O*NET-SOC Code"], {})[row["Element ID"]] = \
                    float(row["Data Value"])
    if not out:
        raise ValueError("%s has no importance (IM) rows; is it the work activities file?"
                         % path)
    return out


def scores(importance: dict[str, dict[str, float]], occupations: list[str],
           activities: dict[str, tuple[tuple[str, str], ...]]) -> dict[str, float]:
    """Each competency's mean importance over its activities, then over the occupations."""
    missing = [c for c in occupations if c not in importance]
    if missing:
        raise ValueError("no ratings for %s in this file" % ", ".join(missing))
    out = {}
    for comp, acts in activities.items():
        per_occupation = []
        for code in occupations:
            rated = importance[code]
            absent = [i for i, _ in acts if i not in rated]
            if absent:
                raise ValueError("%s has no rating for %s" % (code, ", ".join(absent)))
            per_occupation.append(mean(rated[i] for i, _ in acts))
        out[comp] = round(mean(per_occupation), 3)
    return out


def ranked(kind_shape: dict[str, int], view: bank_mod.Bank, score: dict[str, float]) -> list[str]:
    """The kind's competencies, most important first. Each phase gives only as many as it has
    slots: the rest could never be asked and would be reported as not covered. A kind with both
    shared and field phases alternates the two lists, as software's `mixed` does, so trimming
    for length takes from both halves."""
    def key(c: str) -> tuple[float, str]:
        return -score[c], c

    order = []
    for phase, slots in kind_shape.items():
        if slots > 0:
            order += sorted((c for c, p in view.phase_affinity.items() if p == phase),
                            key=key)[:slots]
    order.sort(key=key)
    shared = [c for c in order if view.phase_affinity[c] in SHARED_PHASES]
    own = [c for c in order if view.phase_affinity[c] not in SHARED_PHASES]
    if not shared or not own:
        return order
    out = []
    for i in range(max(len(shared), len(own))):
        out += shared[i:i + 1] + own[i:i + 1]
    return out


def rank(config: dict, b: bank_mod.Bank, importance: dict[str, dict[str, float]],
         version: str, today: str, file: str = "Work Activities.txt") -> dict:
    out = json.loads(json.dumps(config))
    per_field: dict[str, dict[str, float]] = {}
    for f in out["fields"]:
        codes = [o["code"] for o in f.get("onet_occupations", [])]
        if not codes:
            continue
        view = b.view(f["id"])
        unmapped = sorted(set(view.competencies) - set(view.onet))
        if unmapped:
            raise ValueError("%s: no O*NET activities for %s" % (f["id"], ", ".join(unmapped)))
        per_field[f["id"]] = scores(importance, codes, view.onet)
    for f in out["fields"]:
        if f["id"] in per_field:
            score = per_field[f["id"]]
        elif f.get("onet_mean_of"):
            # General has no occupation of its own: the mean of the fields it stands for.
            score = {c: round(mean(per_field[g][c] for g in f["onet_mean_of"]), 3)
                     for c in b.view(f["id"]).competencies}
        else:
            continue
        f["onet_importance"] = dict(sorted(score.items(), key=lambda kv: (-kv[1], kv[0])))
        if f["id"] == "software":
            continue
        view = b.view(f["id"])
        for kind in f.get("kinds", []):
            kind["ranked"] = ranked(kind["shape"], view, score)
    out["onet_database"] = {"version": version, "ranked": today, "scale": "IM", "file": file}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", type=Path,
                    help="O*NET work_activities.csv (31.0) or Work Activities.txt (earlier)")
    ap.add_argument("--version", required=True, help="O*NET database version, e.g. 31.0")
    ap.add_argument("--fields", type=Path, default=FIELDS_JSON)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    config = json.loads(a.fields.read_text(encoding="utf-8"))
    out = rank(config, bank_mod.load(bank_mod.SHIPPED), read_importance(a.file), a.version,
               date.today().isoformat(), a.file.name)
    for f in out["fields"]:
        if "onet_importance" not in f:
            continue
        print("\n%s" % f["id"])
        for c, v in f["onet_importance"].items():
            print("  %-24s %.2f" % (c, v))
        for kind in f.get("kinds", []) if f["id"] != "software" else []:
            print("  %s: %s" % (kind["id"], ", ".join(kind["ranked"])))
    if a.dry_run:
        return 0
    a.fields.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print("\nwrote %s" % a.fields)
    return 0


if __name__ == "__main__":
    sys.exit(main())
