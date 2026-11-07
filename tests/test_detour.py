"""The candidate's own questions, answered from documents (rec 8, stage 5).

The thing under test is the refusal as much as the answer. A retrieval that always finds
something is indistinguishable from one that invents, and there is no employer behind a
practice interview to invent about.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import detour  # noqa: E402
from app.provider import Completion, ProviderError  # noqa: E402

POLICY = """# What this is

Mockingbird is a practice interview. There is no employer behind it and nobody else sees how
it went.

# What it cannot tell you [cannot answer]

Anything about a real job. Salary, team size, the office, who you would report to - there is no
company here to have an answer.

# Where the recordings are

In a folder on this machine, one directory per interview, holding the transcript and any audio.

# Deleting an interview

The history page has a delete button on every row. It removes that interview's directory,
recordings included, and it is not reversible.
"""

PLAN = {
    "label": "Mixed round",
    "notes": "We are hiring a backend engineer to work on payment reconciliation in Python.",
    "rubric": {"sets_context": {"label": "Sets the scene"}},
    "phases": [
        {"id": "warmup", "questions": ["Tell me about yourself?"], "rubric_criteria": []},
        {"id": "behavioural_core", "questions": ["A time you disagreed?", "A failure?"],
         "rubric_criteria": ["sets_context"]},
    ],
}


@pytest.fixture()
def policy(tmp_path):
    p = tmp_path / "about.md"
    p.write_text(POLICY, encoding="utf-8")
    return p


@pytest.fixture()
def passages(policy):
    return detour.corpus(PLAN, policy=policy)


@pytest.fixture()
def real_corpus():
    """The document that actually ships. It is product copy with behaviour attached -- what it
    says decides what the interview can answer -- so editing it should have to come past a
    test rather than change the answers quietly."""
    return detour.corpus(PLAN)


class Said:
    """A provider that answers with whatever it was told to, and records what it was asked."""

    def __init__(self, answer="", fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = []

    async def complete(self, system, user, schema=None, max_tokens=400, **kw):
        if self.fail:
            raise ProviderError("LM Studio is not answering")
        self.calls.append((system, user))
        return Completion(text=json.dumps({"quote": self.answer}))


def run(coro):
    return asyncio.run(coro)


# --- the corpus ------------------------------------------------------------------------------

def test_the_corpus_is_the_plan_and_the_policy_document(passages):
    docs = {p.doc for p in passages}
    assert docs == {"the plan for this interview", "how Mockingbird works"}


def test_every_plan_on_disk_builds_a_corpus():
    """This is the test the first version did not have, and it cost a 500 on `/api/session`
    the moment a real plan was loaded: `notes` is a LIST in the shipped config and a string in
    a generated one, and the fixture here was a guess at the shape. Run it against the files
    that actually exist."""
    root = Path(__file__).resolve().parent.parent
    plans = [root / "config" / "interview_swe_general.json"]
    plans += sorted((root / "data").glob("interview_*.json"))
    plans += sorted((root / "data").glob("plan_draft.json"))
    checked = 0
    for path in plans:
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        got = detour.corpus(raw.get("plan") or raw)
        assert got, "%s produced no passages" % path.name
        assert all(isinstance(p.text, str) and p.text for p in got)
        checked += 1
    assert checked, "no plan files were found to check"


def test_the_developers_own_notes_never_reach_a_candidate():
    """`notes` in the shipped plan is a revision log -- "v2, 2026-08-22: rubric pass after log
    7.36". Read as the job description it would answer "what does this role involve?" with an
    internal changelog, which is worse than the crash that first exposed it."""
    root = Path(__file__).resolve().parent.parent
    raw = json.loads((root / "config" / "interview_swe_general.json").read_text(encoding="utf-8"))
    blob = " ".join(p.text for p in detour.corpus(raw))
    assert "log 7.36" not in blob
    assert "rubric pass" not in blob


def test_the_plan_is_described_from_the_plan_not_from_prose(policy):
    """A checked-in paragraph about what will be asked is wrong the first time a question is
    moved, and wrong in the direction of a confident false answer."""
    moved = json.loads(json.dumps(PLAN))
    moved["phases"][1]["questions"] = ["A time you disagreed?"]
    text = " ".join(p.text for p in detour.corpus(moved, policy=policy))
    assert "behavioural core (1 question)" in text
    assert "behavioural core (2 questions)" not in text


def test_an_unscored_phase_is_named_as_unscored(passages):
    scoring = next(p for p in passages if p.title == "Scoring")
    assert "Sets the scene" in scoring.text
    assert "Nothing in warmup is scored" in scoring.text


def test_a_missing_policy_document_is_not_a_crash(tmp_path):
    got = detour.corpus(PLAN, policy=tmp_path / "nothing.md")
    assert got and all(p.doc != "how Mockingbird works" for p in got)


# --- retrieval -------------------------------------------------------------------------------

def test_it_finds_the_paragraph_that_answers_the_question(passages):
    hit = detour.find(passages, "How do I delete an interview afterwards?")
    assert hit and hit[1].title == "Deleting an interview"


def test_a_question_about_nothing_in_the_corpus_finds_nothing(passages):
    """Returning the least-bad paragraph is how a practice interview starts inventing a job.
    Below the floor it declines instead, and the runner says so."""
    for asked in ("What is the weather like in Hanoi?",
                  "Do you offer remote work and what are the hours?"):
        assert detour.find(passages, asked) is None, asked


def test_a_question_about_the_job_lands_on_the_paragraph_that_refuses_it(real_corpus):
    """Against the SHIPPED policy document, not a stub. There is no employer, so salary, team
    size, the office and who you would report to all have the same answer -- and the document
    has a paragraph that absorbs them. That paragraph being RETRIEVED is what keeps these off
    whatever else happens to share a word with them: without it, "who would I report to?" lands
    on the paragraph about reports.

    An earlier version of this test used a stub corpus with no such paragraph, so it asserted a
    decline and passed without ever exercising the case that matters."""
    for asked in ("What does the role pay?",
                  "How many people would be on my team?",
                  "Where is the office?",
                  "Who would I report to?",
                  "What is the tech stack for the role?"):
        hit = detour.find(real_corpus, asked)
        assert hit is not None, asked
        assert hit[1].title == "What it cannot tell you", "%s -> %s" % (asked, hit[1].title)
        assert hit[1].decline, "%s reached a paragraph that would be composed from" % asked


def test_a_phrase_decides_a_tie_that_corpus_order_would_get_wrong(real_corpus):
    """"Who would I report to?" has one content word, so every paragraph containing "report"
    scores 1.0 and the winner was whichever came first -- which was the paragraph about
    REPORTS. "report to" appears as a phrase in only one of them."""
    hit = detour.find(real_corpus, "Who would I report to?")
    assert hit and hit[0] == pytest.approx(1.0)
    assert hit[1].title == "What it cannot tell you"


@pytest.mark.parametrize("asked,want", [
    # "happens" put this on the paragraph about what Mockingbird is, where it was answered with
    # "Your recording is deleted immediately" -- false
    ("What happens to my recording after this?", "Where the recordings and transcripts are"),
    # "anything" put this on the refusal paragraph, so a question the documents answer declined
    ("Is anything sent to the cloud?", "Where the recordings and transcripts are"),
    # "else" is NOT a stop word: it is what joins these two
    ("Does anyone else see how I did?", "What this is"),
    # "any" answered this with where the recordings are stored
    ("Do you have any tips for me?", None),
])
def test_a_generic_word_does_not_steer_retrieval(real_corpus, asked, want):
    hit = detour.find(real_corpus, asked)
    assert (hit[1].title if hit else None) == want, (asked, hit and hit[1].title)


def test_different_forms_of_a_word_still_match(real_corpus):
    """The document says "exported"; nobody asks that way. Without folding, the only paragraph
    about exporting matched nothing the question said and lost a tie to SCORING."""
    hit = detour.find(real_corpus, "Can I export the report?")
    assert hit and hit[1].title == "Taking a report with you"


def test_a_common_word_decides_nothing(passages):
    """"interview" is in nearly every paragraph. If it carried weight, every question that
    contained it would match the longest paragraph rather than the right one."""
    hit = detour.find(passages, "What does this interview cover?")
    assert hit and hit[1].title == "Sections and length"


# --- only the document's own words are ever spoken --------------------------------------------
# The old check measured what share of a COMPOSED answer's words appeared in the passage. It let
# through "Your recording is deleted immediately after the interview" -- false -- because
# generic words carried it. These are the fabrications that reached, or could reach, a candidate.

FABRICATIONS = [
    # the one that was spoken, 21/09/2026, retrieved against the wrong paragraph
    ("What happens to my recording after this?",
     "Your recording is deleted immediately after the interview. Nothing else happens to it."),
    # rebuilt from the deletion paragraph's own words, false, and it scores well on any overlap
    ("What happens to my recording after this?",
     "Your recordings are removed from the history page when the interview ends."),
    # a true sentence with a false clause appended
    ("How do I delete an interview?",
     "The history page has a delete button on every row, and recordings are deleted after a "
     "week anyway."),
    # facts from nowhere
    ("How big is the team?", "The team is eight engineers in Manchester on 75000 pounds."),
]


@pytest.mark.parametrize("asked,said", FABRICATIONS)
def test_a_fabrication_is_never_spoken(real_corpus, asked, said):
    got = run(detour.answer(Said(said), asked, real_corpus))
    assert got is None or said not in got[0], got


def test_what_is_spoken_is_the_documents_text_not_the_models(passages):
    """The quote only LOCATES the answer. A model that tidies while copying -- a possessive
    dropped, a comma lost -- never puts its tidying into the room."""
    p = Said("It removes that interview directory, recordings included and it is not "
             "reversible.")
    said, _ = run(detour.answer(p, "How do I delete an interview?", passages))
    assert "that interview's directory, recordings included, and" in said


def test_a_paraphrase_is_not_a_quote(passages):
    """Reordering is composing. "including the recordings" for "recordings included" is a
    small change, and it is exactly the kind a model makes when it is writing its own sentence
    rather than copying -- so it declines, the same line `observe._grounded` draws for scores."""
    p = Said("It removes that interview's directory, including the recordings, and it is not "
             "reversible.")
    assert run(detour.answer(p, "How do I delete an interview?", passages)) is None


def test_a_fragment_is_spoken_as_its_whole_sentence(real_corpus):
    """Measured live: the model quoted a clause from the middle of a sentence -- "says how much
    space it is using, and states whether..." -- which is true and cannot be said aloud."""
    p = Said("says how much space it is using, and states whether anything is sent off the "
             "machine")
    said, _ = run(detour.answer(p, "What happens to my recording after this?", real_corpus))
    assert said.startswith("The history page names the exact path")
    assert said.endswith(".")


def test_a_sentence_that_leans_back_brings_the_one_it_leans_on(passages):
    """Spoken alone, "It removes that interview's directory" answered "how do I delete an
    interview?" without ever saying what "it" was."""
    p = Said("It removes that interview's directory, recordings included, and it is not "
             "reversible.")
    said, _ = run(detour.answer(p, "How do I delete an interview?", passages))
    assert said.startswith("The history page has a delete button on every row.")


def test_a_quote_that_cannot_be_located_is_never_spoken_as_itself():
    """Unreachable while `quoted` holds, and kept for the day it does not: with nothing to
    locate, speaking the quote would put the model's own words into the room after all."""
    assert detour._sentences_around("totally unrelated words about something else",
                                    "The history page has a delete button on every row.") == ""


def test_a_quote_that_is_not_in_the_note_declines_rather_than_falling_back(passages):
    """There used to be a fallback that read out the passage's first sentences, which answered
    "do you have any tips?" with where the recordings are stored. A decline is honest; an
    unrelated true sentence only sounds like an answer."""
    p = Said("You should practise your answers out loud every day.")
    assert run(detour.answer(p, "How do I delete an interview?", passages)) is None


# --- answering -------------------------------------------------------------------------------

def test_a_quoted_answer_is_spoken_with_its_source(passages):
    p = Said("The history page has a delete button on every row.")
    got = run(detour.answer(p, "How do I delete an interview?", passages))
    assert got is not None
    said, cite = got
    assert "delete button" in said
    assert cite.startswith("how Mockingbird works")


def test_the_note_is_what_the_model_is_given_and_nothing_else(passages):
    p = Said("")
    run(detour.answer(p, "How do I delete an interview?", passages))
    system, user = p.calls[0]
    assert "delete button" in user
    # One passage, not the corpus: the other documents must not be in the prompt at all.
    assert "payment reconciliation" not in user
    assert "exactly as they are written" in system


def test_an_empty_answer_declines(passages):
    p = Said("")
    assert run(detour.answer(p, "How do I delete an interview?", passages)) is None


def test_a_question_with_no_passage_never_reaches_the_model(passages):
    p = Said("I would happily make something up.")
    assert run(detour.answer(p, "What is the weather like in Hanoi?", passages)) is None
    assert p.calls == [], "the model was asked about something the corpus cannot answer"


def test_a_refusal_paragraph_declines_without_a_model_call(passages):
    """Measured against qwen: composing from it read the document's own third-person prose
    aloud -- "Anything about a real job. Salary, team size, the office ... there is no company
    here to have an answer" -- in reply to someone who asked what the job pays. The runner's
    `QUESTION_NOTED` was written for this moment and is better than anything assembled from a
    page about the product."""
    p = Said("The team is eight engineers in Manchester.")
    for asked in ("What does the role pay?", "Who would I report to?"):
        assert run(detour.answer(p, asked, passages)) is None, asked
    assert p.calls == [], "a refusal paragraph was composed from"


def test_the_marker_is_stripped_from_the_title_it_marks(passages):
    """It is machine-readable, not something to read out or retrieve on."""
    refusal = next(x for x in passages if x.decline)
    assert refusal.title == "What it cannot tell you"
    assert "cannot answer]" not in refusal.cite
