"""`tools/onet_rank.py`: O*NET importance into each field's ranks (V1.2_PLAN D11)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import onet_rank  # noqa: E402

from app import bank  # noqa: E402

HEADER = ("O*NET-SOC Code\tElement ID\tElement Name\tScale ID\tData Value\tN\tStandard Error\t"
          "Lower CI Bound\tUpper CI Bound\tRecommend Suppress\tNot Relevant\tDate\t"
          "Domain Source")
ACTS = {"4.A.2.a.4": "Analyzing Data or Information",
        "4.A.4.a.2": "Communicating with Supervisors, Peers, or Subordinates",
        "4.A.2.b.1": "Making Decisions and Solving Problems",
        "4.A.2.b.3": "Updating and Using Relevant Knowledge",
        "4.A.4.b.5": "Coaching and Developing Others"}


def _file(tmp_path, ratings: dict[str, dict[str, float]]):
    lines = [HEADER]
    for code, acts in ratings.items():
        for eid, im in acts.items():
            lines.append("\t".join([code, eid, ACTS[eid], "IM", str(im), "20", "0.1", "1", "5",
                                    "n/a", "n/a", "08/2026", "Incumbent"]))
            lines.append("\t".join([code, eid, ACTS[eid], "LV", "6.9", "20", "0.1", "1", "7",
                                    "N", "N", "08/2026", "Incumbent"]))
    p = tmp_path / "Work Activities.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _bank(tmp_path):
    raw = json.loads(bank.SHIPPED.read_text(encoding="utf-8"))
    raw["competencies"] = {"analysis": "finding something in data",
                           "collaboration": raw["competencies"]["collaboration"],
                           "ownership": raw["competencies"]["ownership"]}
    raw["competency_fields"] = {"analysis": "data_analytics", "collaboration": "shared",
                                "ownership": "shared"}
    raw["phase_affinity"] = {"analysis": "analytics_experience",
                             "collaboration": "collaboration", "ownership": "behavioural_core"}
    raw["onet"] = {"analysis": [{"id": "4.A.2.a.4", "title": ACTS["4.A.2.a.4"]}],
                   "collaboration": [{"id": "4.A.4.a.2", "title": ACTS["4.A.4.a.2"]}],
                   "ownership": [{"id": "4.A.2.b.1", "title": ACTS["4.A.2.b.1"]},
                                 {"id": "4.A.2.b.3", "title": ACTS["4.A.2.b.3"]}]}
    raw["questions"] = [
        {"id": "a", "text": "A?", "field": "data_analytics", "competencies": ["analysis"],
         "shape": "star", "source": "curated", "status": "approved"},
        {"id": "c", "text": "C?", "field": "shared", "competencies": ["collaboration"],
         "shape": "star", "source": "curated", "status": "approved"},
        {"id": "o", "text": "O?", "field": "shared", "competencies": ["ownership"],
         "shape": "star", "source": "curated", "status": "approved"},
    ]
    p = tmp_path / "bank.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return bank.load(p, templates={})


CONFIG = {"fields": [
    {"id": "data_analytics", "onet_occupations": [{"code": "15-2051.01"}, {"code": "15-2051.00"}],
     "kinds": [{"id": "behavioural", "shape": {"behavioural_core": 3, "collaboration": 2,
                                               "analytics_experience": 0}},
               {"id": "mixed", "shape": {"behavioural_core": 2, "collaboration": 1,
                                         "analytics_experience": 3}}]},
    {"id": "general", "onet_mean_of": ["data_analytics"],
     "kinds": [{"id": "behavioural", "shape": {"behavioural_core": 4, "collaboration": 2}}]},
]}
RATINGS = {"15-2051.01": {"4.A.2.a.4": 4.6, "4.A.4.a.2": 3.8, "4.A.2.b.1": 4.0, "4.A.2.b.3": 4.2},
           "15-2051.00": {"4.A.2.a.4": 4.8, "4.A.4.a.2": 3.6, "4.A.2.b.1": 3.8, "4.A.2.b.3": 4.4}}


def test_importance_is_read_from_the_im_rows_only(tmp_path):
    got = onet_rank.read_importance(_file(tmp_path, RATINGS))
    assert got["15-2051.01"]["4.A.2.a.4"] == 4.6


def test_a_competency_scores_its_activities_mean_over_the_occupations(tmp_path):
    b = _bank(tmp_path).view("data_analytics")
    s = onet_rank.scores(onet_rank.read_importance(_file(tmp_path, RATINGS)),
                         ["15-2051.01", "15-2051.00"], b.onet)
    assert s == {"analysis": 4.7, "collaboration": 3.7, "ownership": 4.1}


def test_the_ranks_land_in_the_config_and_mixed_alternates(tmp_path):
    out = onet_rank.rank(CONFIG, _bank(tmp_path),
                         onet_rank.read_importance(_file(tmp_path, RATINGS)), "31.0", "2026-11-11")
    da, general = out["fields"]
    assert list(da["onet_importance"]) == ["analysis", "ownership", "collaboration"]
    assert da["kinds"][0]["ranked"] == ["ownership", "collaboration"]
    assert da["kinds"][1]["ranked"] == ["ownership", "analysis", "collaboration"]
    assert general["onet_importance"] == {"ownership": 4.1, "collaboration": 3.7}
    assert out["onet_database"] == {"version": "31.0", "ranked": "2026-11-11", "scale": "IM",
                                    "file": "Work Activities.txt"}
    assert "onet_database" not in CONFIG


def test_a_missing_occupation_or_rating_is_refused(tmp_path):
    imp = onet_rank.read_importance(_file(tmp_path, {"15-2051.01": RATINGS["15-2051.01"]}))
    with pytest.raises(ValueError, match="no ratings for 15-2051.00"):
        onet_rank.rank(CONFIG, _bank(tmp_path), imp, "31.0", "2026-11-11")
    partial = {k: {e: v for e, v in r.items() if e != "4.A.2.b.3"} for k, r in RATINGS.items()}
    imp = onet_rank.read_importance(_file(tmp_path, partial))
    with pytest.raises(ValueError, match="no rating for 4.A.2.b.3"):
        onet_rank.rank(CONFIG, _bank(tmp_path), imp, "31.0", "2026-11-11")


def test_a_file_without_importance_rows_is_refused(tmp_path):
    p = tmp_path / "Work Activities.txt"
    p.write_text(HEADER + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no importance"):
        onet_rank.read_importance(p)


def test_31_0s_comma_separated_file_reads_the_same(tmp_path):
    """31.0 ships `work_activities.csv` with the text file's columns, comma-separated."""
    tab = _file(tmp_path, RATINGS)
    rows = [line.split("\t") for line in tab.read_text(encoding="utf-8").splitlines()]
    csv_path = tmp_path / "work_activities.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    assert onet_rank.read_importance(csv_path) == onet_rank.read_importance(tab)
    out = onet_rank.rank(CONFIG, _bank(tmp_path), onet_rank.read_importance(csv_path), "31.0",
                         "2026-11-13", csv_path.name)
    assert out["onet_database"]["file"] == "work_activities.csv"


def test_a_phase_gives_no_more_competencies_than_it_has_slots(tmp_path):
    view = _bank(tmp_path).view("data_analytics")
    score = {"analysis": 4.7, "collaboration": 3.7, "ownership": 4.1}
    assert onet_rank.ranked({"behavioural_core": 0, "collaboration": 1,
                             "analytics_experience": 1}, view, score) == \
        ["collaboration", "analysis"]
    assert onet_rank.ranked({"behavioural_core": 1, "collaboration": 0,
                             "analytics_experience": 0}, view, score) == ["ownership"]
