"""Extraction and scoring. Log section 8.23.

The design rule these pin is section 7.10's: ask the model for text the candidate said, never
for an opinion about it. Every test below is either "did it copy the right words" or "does
Python compute the criterion", and none is "did it judge correctly" -- because the whole point
is that nothing here asks it to judge.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import observe, score  # noqa: E402
from app.provider import Completion  # noqa: E402

ANSWER = ("We split a claims table in two while it was live, about 200 million rows. "
          "I dual-wrote for three weeks and backfilled in batches overnight. "
          "Row counts matched exactly, so the cutover was uneventful.")


class Quoter:
    """Returns whatever quotes the test wants, so grounding can be tested in isolation."""

    def __init__(self, **parts):
        self.parts = {"situation": "", "action": "", "result": "", **parts}
        self.calls = 0

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.calls += 1
        return Completion(text=json.dumps(self.parts))


def run(coro):
    return asyncio.run(coro)


def obs(**parts):
    return run(observe.observe(Quoter(**parts), "q.1", "Tell me about a schema change.",
                               [ANSWER]))


# ------------------------------------------------------------------ grounding
def test_a_verbatim_quote_is_kept():
    o = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    assert o.action.startswith("I dual-wrote")
    assert not o.dropped_quotes


def test_a_quote_tidied_as_it_was_copied_is_kept():
    """The model re-punctuates and respells; rejecting that discards real evidence."""
    o = obs(situation="We split a claims-table in two while it was live, about 200 million rows")
    assert o.situation
    assert not o.dropped_quotes


def test_a_quote_spanning_two_sentences_is_kept():
    """The first grounding check compared against single sentences and dropped 4 of 5."""
    o = obs(result="I dual-wrote for three weeks and backfilled in batches overnight. "
                   "Row counts matched exactly, so the cutover was uneventful.")
    assert o.result
    assert not o.dropped_quotes


def test_an_invented_quote_is_dropped():
    o = obs(result="I led a team of twelve through a cloud migration.")
    assert o.result == ""
    assert o.dropped_quotes


def test_a_paraphrase_is_dropped():
    """Paraphrase is judgement wearing a quote's clothes, and it breaks traceability."""
    o = obs(situation="The candidate migrated a large table without downtime.")
    assert o.situation == ""


def test_an_empty_field_is_a_valid_answer():
    o = obs(situation="We split a claims table in two while it was live, about 200 million rows.")
    assert o.situation and not o.action and not o.result
    assert not o.dropped_quotes


# ------------------------------------------- derived, never asked (section 7.10)
def test_addresses_question_is_derived_from_the_parts():
    assert obs(situation="x", action="y", result="z").addresses_question == "no"  # ungrounded
    full = obs(situation="We split a claims table in two while it was live, about 200 million rows.",
               action="I dual-wrote for three weeks and backfilled in batches overnight.",
               result="Row counts matched exactly, so the cutover was uneventful.")
    assert full.addresses_question == "yes"
    part = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    assert part.addresses_question == "partial"


# ------------------------------------------------- no model needed (section 8.23)
def test_three_criteria_are_computed_without_the_model():
    d = observe.deterministic(ANSWER)
    assert d["first_person"] and d["specific_detail"]
    assert observe.deterministic("We shipped it and it was fine.")["measurement_stated"] is False
    assert observe.deterministic("I measured it before and after.")["measurement_stated"] is True


def test_the_team_only_answer_fails_first_person():
    assert observe.deterministic("We rebuilt the pipeline.")["first_person"] is False


def test_an_unanswered_question_costs_no_model_call():
    q = Quoter(situation="anything")
    o = run(observe.observe(q, "q.1", "Tell me about it.", []))
    assert q.calls == 0
    assert o.addresses_question == "no"


# ----------------------------------------------------------------- scoring
def test_a_criterion_names_the_quote_behind_it():
    """NFR-5: a score must be disputable by pointing at the evidence, not at the model."""
    o = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    qs = score.score_question(o, ["describes_action", "sets_context"])
    assert qs.met["describes_action"] and not qs.met["sets_context"]
    assert "dual-wrote" in qs.evidence["describes_action"]
    assert qs.evidence["sets_context"] == "not found"


def test_scoring_is_pure_arithmetic_over_observations():
    o = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    a = score.score_question(o, ["describes_action", "first_person"])
    b = score.score_question(o, ["describes_action", "first_person"])
    assert a.met == b.met and a.evidence == b.evidence


def test_an_unscored_phase_produces_no_score():
    """warmup and closing declare no criteria; scoring them would grade small talk."""
    o = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    r = score.build("s", [o], {"q.1": []})
    assert r.scores == []


def test_the_report_ranks_the_weakest_criteria():
    o1 = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    o2 = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    o2.question_id = "q.2"
    r = score.build("s", [o1, o2], {"q.1": ["describes_action", "sets_context"],
                                    "q.2": ["describes_action", "sets_context"]})
    assert r.totals["describes_action"] == (2, 2)
    assert r.totals["sets_context"] == (0, 2)
    assert r.weakest == ["sets_context"]


def test_a_fragment_is_not_evidence():
    """Coverage stops discriminating on short strings -- every answer contains "x"."""
    o = obs(situation="rows", action="I", result="live")
    assert o.addresses_question == "no"
    assert len(o.dropped_quotes) == 3


# --------------------------------------------------- the candidate-facing report
from app import report as rep  # noqa: E402


def _report(rows):
    """rows: (question_id, question, answer, {criterion: met})."""
    scores = []
    for qid, q, ans, met in rows:
        qs = score.QuestionScore(question_id=qid, question=q, answer=ans,
                                 addresses_question="partial" if ans else "no")
        for k, v in met.items():
            qs.met[k] = v
            qs.evidence[k] = ans[:60] if v else "not found"
            if v:
                qs.quoted.add(k)
        scores.append(qs)
    return score.Report(session_id="s", scores=scores)


RICH = "I split the table while it was live and dual-wrote for three weeks before cutting over."
THIN = "I have not done that."


def test_the_report_never_puts_our_words_in_quotation_marks():
    """A deterministic criterion has no quote; rendering its placeholder as one is a lie."""
    qs = score.QuestionScore(question_id="q.1", question="Q?", answer=RICH)
    qs.met["first_person"] = True
    qs.evidence["first_person"] = "found in the answer"      # deliberately NOT in `quoted`
    text = rep.render(score.Report("s", [qs]), 1, 1)
    assert '"found in the answer"' not in text


def test_an_example_prefers_an_answer_they_actually_gave():
    """Citing "I have not done that" as an example of a habit reprimands inexperience."""
    r = _report([("q.1", "Thin one?", THIN, {"states_outcome": False}),
                 ("q.2", "Rich one?", RICH, {"states_outcome": False})])
    assert rep._missed(r, "states_outcome").question_id == "q.2"


def test_three_pieces_of_advice_do_not_all_cite_one_answer():
    r = _report([("q.1", "First?", RICH, {"states_outcome": False, "sets_context": False}),
                 ("q.2", "Second?", RICH + " And more besides.",
                  {"states_outcome": False, "sets_context": False})])
    text = rep.render(r, 2, 2)
    assert text.count("Where it showed") == 2
    assert "First?" in text and "Second?" in text


def test_the_report_carries_no_overall_grade():
    """A number out of ten says how they did and not what to change."""
    r = _report([("q.1", "Q?", RICH, {"states_outcome": False, "sets_context": True})])
    text = rep.render(r, 1, 1).lower()
    for word in ("score:", "grade", "out of 10", "overall rating", "/100"):
        assert word not in text


def test_a_session_with_nothing_scored_says_so():
    assert "No scored questions" in rep.render(score.Report("s", []), 3, 3)


def test_advice_and_praise_cover_every_criterion():
    """A criterion with no advice would render as its own name at a candidate."""
    for name in score.CRITERIA:
        assert name in rep.ADVICE and name in rep.PRAISE


# ------------------------------------------- design questions (log 9.6)
def _design(**parts):
    text = ("I'd count requests per API key in a window and reject with a 429. "
            "Not sure what the alternative would be. Maybe the counts drift if two "
            "servers write at once, I don't know how you'd stop that.")
    return run(observe.observe(Quoter(**parts), "design.1", "Design a rate limiter.",
                               [text], shape="design"))


def test_a_design_answer_is_extracted_on_its_own_parts():
    o = _design(approach="I'd count requests per API key in a window and reject with a 429.",
                failure_mode="Maybe the counts drift if two servers write at once")
    assert o.shape == "design"
    assert o.approach and o.failure_mode
    assert not o.situation and not o.action and not o.result


def test_a_design_answer_is_never_scored():
    """Scoring these inverted the ranking of four measured candidates (log 9.6)."""
    import json as _json
    plan = _json.loads((Path(__file__).resolve().parent.parent / "config" /
                        "interview_swe_general.json").read_text(encoding="utf-8"))
    design = [p for p in plan["phases"] if p["id"] == "design"][0]
    assert design["rubric_criteria"] == []
    assert design["scored"] is False
    assert design["observed_not_scored"]


def test_the_design_note_describes_rather_than_grades():
    o = _design(approach="I'd count requests per API key in a window and reject with a 429.")
    block = rep.design_note([o])
    assert any("Not scored" in x for x in block)
    # Only the item lines matter: the preamble may legitimately say what a design answer
    # usually covers. A verdict on any single part is what must not appear.
    items = [x for x in block if x.strip().startswith(("You ", "Nothing in"))]
    assert items
    # Whole words: "met" is inside "something", and a substring check fails on that.
    import re as _re
    for verdict in ("covered", "met", "good", "weak", "poor", "strong"):
        pattern = _re.compile(r"\b%s\b" % verdict)
        assert not any(pattern.search(x.lower()) for x in items), verdict


def test_the_design_note_is_omitted_when_there_is_no_design_answer():
    o = obs(action="I dual-wrote for three weeks and backfilled in batches overnight.")
    assert rep.design_note([o]) == []


# ------------------------------------------- the extraction cache (log 9.7)
def test_a_second_run_reuses_the_extraction_instead_of_asking_again():
    """Scoring is deterministic; extraction is not. Re-scoring one transcript five times gave
    states_outcome 7,7,8,8,9 of 10, and the report claimed in writing that it would not."""
    import tempfile
    items = [("q.1", "Tell me about a schema change.", [ANSWER], "star")]
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        q = Quoter(action="I dual-wrote for three weeks and backfilled in batches overnight.")
        first, cached = run(observe.observe_all(q, items, cache=cache))
        assert q.calls == 1 and not cached

        again = Quoter(action="something completely different")
        second, cached = run(observe.observe_all(again, items, cache=cache))
        assert again.calls == 0 and cached
        assert second[0].action == first[0].action


def test_re_extract_ignores_the_cache():
    import tempfile
    items = [("q.1", "Tell me about a schema change.", [ANSWER], "star")]
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        run(observe.observe_all(Quoter(), items, cache=cache))
        q = Quoter()
        _, cached = run(observe.observe_all(q, items, cache=cache, re_extract=True))
        assert q.calls == 1 and not cached


def test_changing_the_extractor_invalidates_the_cache():
    """A stale cache turns a real improvement into a no-op and looks like it did not work."""
    import tempfile
    items = [("q.1", "Tell me about a schema change.", [ANSWER], "star")]
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        run(observe.observe_all(Quoter(), items, cache=cache))
        original = observe.SYSTEM
        try:
            observe.SYSTEM = original + "\n- One more rule."
            q = Quoter()
            _, cached = run(observe.observe_all(q, items, cache=cache))
            assert q.calls == 1 and not cached
        finally:
            observe.SYSTEM = original


def test_a_changed_answer_invalidates_the_cache():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        run(observe.observe_all(Quoter(), [("q.1", "Q?", [ANSWER], "star")], cache=cache))
        q = Quoter()
        _, cached = run(observe.observe_all(
            q, [("q.1", "Q?", [ANSWER + " And one more thing."], "star")], cache=cache))
        assert q.calls == 1 and not cached


def test_a_corrupt_cache_re_extracts_rather_than_failing():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        cache.write_text("{not json", encoding="utf-8")
        q = Quoter()
        _, cached = run(observe.observe_all(q, [("q.1", "Q?", [ANSWER], "star")], cache=cache))
        assert q.calls == 1 and not cached


def test_a_cached_observation_survives_the_round_trip_intact():
    """Every field the report reads has to come back, including the derived properties."""
    import tempfile
    items = [("design.1", "Design a rate limiter.",
              ["I'd count requests per API key in a window and reject with a 429."], "design")]
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "observations.json"
        q = Quoter(approach="I'd count requests per API key in a window and reject with a 429.")
        first, _ = run(observe.observe_all(q, items, cache=cache))
        second, cached = run(observe.observe_all(Quoter(), items, cache=cache))
        assert cached
        a, b = first[0], second[0]
        assert a.shape == b.shape == "design"
        assert a.approach == b.approach
        assert a.addresses_question == b.addresses_question
        assert a.text == b.text
        assert a.first_person == b.first_person
