"""The candidate's own questions, answered from documents. Rec 8, plan stage 5.

**Keyword over documents, not a vector store.** The whole corpus -- the plan for this
interview, the job description it was read from, and one policy document -- is a few thousand
tokens. An index, an embedding model and a similarity threshold to tune would all be machinery
for a linear scan over forty paragraphs, and every one of them is another thing that can be
subtly wrong in a way nobody notices.

Three properties this has to keep, and they are the reason it is not simply a second prompt.

  its own lineage   the detour never enters the turn prompt. A retrieved passage inserted
                    into the interview's history invalidates llama.cpp's prefix cache and the
                    next turn pays a full re-prefill -- which is the cost rec 8 names. Here it
                    is structural rather than remembered: this call has its own system prompt,
                    and what it produces is spoken, never appended to the history the turn
                    decision reads.
  quoted            the model is given one passage and asked which of its sentences answer the
                    question, word for word. What comes back is checked against that passage
                    by `observe._grounded`, the guard that has let no invented quote into a
                    score, and only a quote that passes is spoken. The model never composes,
                    so it has nothing to invent with.
  it declines       there is no employer behind a practice interview. A question the corpus
                    does not answer gets the honest line it already got, because inventing an
                    answer about a real workplace is the one thing this must never do -- and a
                    retrieval that always finds *something* is exactly how that happens.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .observe import _grounded
from .provider import Completion, Provider  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "about.md"

# Below this the best passage is not about the question. Set so that a question the corpus has
# nothing to say about declines rather than returning its least-bad paragraph: a retrieval
# that always answers is indistinguishable from one that invents.
MIN_SCORE = 0.22

# There is no grounding threshold of this module's own any more, and that is the fix. The model
# used to COMPOSE an answer that was checked by the share of its content words found in the
# passage. That told a candidate "Your recording is deleted immediately after the interview" --
# false; recordings stay until the user deletes them -- because generic words carried it:
# "interview", "else" and "happens" matched, "nothing" near-matched "not", and the claim itself
# ("record", "deleted", "immediately") appeared nowhere, for exactly 0.50 against a floor of
# 0.50. No share of words can separate that from a faithful paraphrase, and a false sentence
# built entirely from the passage's own words passes any of them. A verbatim quote cannot.

# A heading ending in this marks a section that exists to say the product cannot answer
# something. Written in the document rather than detected here: which questions have no answer
# is editorial, and a rule in code would have to be kept in step with prose it cannot see.
DECLINE = "[cannot answer]"

# 160 truncated a real answer mid-JSON, which arrives as unparseable and is indistinguishable
# from the model declining -- so "how am I scored?", which the corpus answers plainly, came back
# as "I can't answer for a real employer". The prompt still asks for two sentences; this is the
# headroom for when it writes three.
MAX_TOKENS = 320

SCHEMA = {
    "type": "object",
    "properties": {"quote": {"type": "string"}},
    "required": ["quote"],
    "additionalProperties": False,
}

SYSTEM = """A candidate has asked a question. You are given one note.

Copy the one or two sentences from the note that answer the question, exactly as they are written.
Do not change, shorten, combine or add any words.
If no sentence in the note answers the question, return an empty quote."""

# Generic words carry no subject, and several were steering retrieval: "happens" put "what
# happens to my recording?" on the paragraph about what this is, "anything" put "is anything
# sent to the cloud?" on the refusal paragraph, and "any" answered "do you have any tips?" with
# where the recordings are stored. Rare in this corpus is not the same as meaningful. "else" is
# deliberately NOT here: it is what joins "does anyone else see how I did?" to "nobody else
# sees how it went", and stopping it made that question decline.
STOP = frozenset("""a an and any anybody anyone anything are as at be been but by can could
did do does either every everybody everyone everything for from get gets got had happen happens
has have how i if in into is it its just like lot me my nobody nothing of on or our so some
somebody someone something than that the their them then there these they thing things this to
very was way we were what when where which who why will with would you your""".split())

_WORD = re.compile(r"[a-z0-9][a-z0-9'_-]*")

# Enough folding that a question and a document can use different forms of the same word, and
# no more. Measured on the real corpus: without it "Can I export the report?" retrieves the
# paragraph about SCORING, because the only paragraph that says "exported" matches nothing the
# question asked and loses on a tie. Longest suffix first, twice, so "scores" reaches the same
# stem as "scoring".
_SUFFIX = ("ings", "ies", "ing", "ed", "es", "s", "y", "e")


def _stem(word: str) -> str:
    for _ in range(2):
        if word.endswith("ss"):
            return word
        for suffix in _SUFFIX:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[:-len(suffix)]
                break
        else:
            break
    return word


@dataclass(frozen=True)
class Passage:
    doc: str
    title: str
    text: str
    # A paragraph that exists to say the product CANNOT answer something. It is retrieved like
    # any other -- absorbing the job questions, which otherwise land on whatever paragraph
    # shares a word with them -- and then declines without a model call. See `DECLINE`.
    decline: bool = False

    @property
    def cite(self) -> str:
        return "%s, %s" % (self.doc, self.title) if self.title else self.doc

    @property
    def shown(self) -> str:
        """Exactly what the model is given, which is what an answer has to be grounded in. The
        title travels in the citation line of the prompt, so leaving it out of the check marked
        the model's own words as invented."""
        return "%s %s" % (self.title, self.text) if self.title else self.text


def _terms(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall((text or "").lower())
            if w not in STOP and len(w) > 2]


def _split(doc: str, text: str) -> list[Passage]:
    """Markdown headings start a passage; blank lines separate paragraphs inside one.

    The heading travels with the paragraph because it is usually where the question's own
    words are -- "how am I scored" matches a heading called Scoring far better than it matches
    the sentences under it.

    A section whose heading ends in `{decline}` marks itself a refusal. It is still retrieved,
    which is the point of it, and it is never composed from.
    """
    out: list[Passage] = []
    title = ""
    decline = False
    buf: list[str] = []

    def flush() -> None:
        body = " ".join(" ".join(buf).split())
        if body:
            out.append(Passage(doc=doc, title=title, text=body, decline=decline))
        buf.clear()

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            title = stripped.lstrip("#").strip()
            decline = title.endswith(DECLINE)
            if decline:
                title = title[:-len(DECLINE)].strip()
            continue
        if not stripped:
            flush()
            continue
        buf.append(stripped)
    flush()
    return out


def _plan_passages(plan: dict) -> list[Passage]:
    """The interview itself, described from the plan rather than from a document about it.

    Written here instead of kept as prose because the plan is edited before every session: a
    checked-in description of what will be asked would be wrong the first time a question is
    moved, and wrong in the direction of a confident false answer.

    **The job description is NOT here, and `notes` is not it.** Rec 8 names a three-document
    corpus and only two of them are reachable. The first version read `notes` as the
    description and broke live on the first request, because in the shipped plan `notes` is a
    LIST of the developer's own revision notes -- "v2, 2026-08-22: rubric pass after log 7.36"
    -- and in a generated plan it is provenance prose about how the plan was assembled. Neither
    describes a role, so the crash was the lesser half of the bug: fixing only the type would
    have left a candidate asking what the job involves and being read an internal changelog.

    The description itself never reaches here. `planner.read_jd` keeps a structured `spec`, the
    draft holds it, and the plan a session loads carries `id, label, notes, rubric, phases`.
    Wiring the spec's requirement evidence through the session snapshot would put real JD
    sentences in the corpus and is a schema change, not a line in this function.
    """
    out: list[Passage] = []
    label = plan.get("label") or "this interview"
    phases = plan.get("phases") or []
    scored = [ph for ph in phases if ph.get("rubric_criteria")]

    def _count(ph: dict) -> str:
        n = len(ph.get("questions") or [])
        return "%s (%d question%s)" % (ph["id"].replace("_", " "), n, "" if n == 1 else "s")

    counts = ", ".join(_count(ph) for ph in phases if ph.get("questions"))
    if counts:
        out.append(Passage("the plan for this interview", "Sections and length",
                           "%s covers %s. The questions were reviewed and approved before the "
                           "interview started; nothing is asked that was not on the sheet."
                           % (label, counts)))

    if scored:
        rubric = plan.get("rubric") or {}
        names = sorted({n for ph in scored for n in ph["rubric_criteria"]})
        labels = [(rubric.get(n) or {}).get("label") or n.replace("_", " ") for n in names]
        unscored = [ph["id"].replace("_", " ") for ph in phases if not ph.get("rubric_criteria")]
        out.append(Passage(
            "the plan for this interview", "Scoring",
            "Answers are scored on: %s. Each is a fact about what was said, checked against "
            "the answer itself, and the report names the answer behind every one of them. "
            "There is no single grade or mark out of ten.%s"
            % ("; ".join(labels),
               " Nothing in %s is scored." % ", ".join(unscored) if unscored else "")))

    return out


def corpus(plan: dict | None = None, policy: Path | None = None) -> list[Passage]:
    """The plan and the policy document. Rec 8's third source, the job description, is not
    reachable from the plan a session runs -- see `_plan_passages`. All of it fits in memory."""
    out: list[Passage] = []
    if plan:
        out.extend(_plan_passages(plan))
    path = POLICY if policy is None else policy
    try:
        out.extend(_split("how Mockingbird works", path.read_text(encoding="utf-8")))
    except OSError:
        pass
    return out


def find(passages: list[Passage], question: str) -> tuple[float, Passage] | None:
    """The best passage for this question, with a score in 0..1, or None when nothing is close.

    Terms are weighted by how rare they are in the corpus, so "interview", which is in every
    paragraph, decides nothing and "delete", which is in one, decides everything. Scored as the
    share of the question's own weight that the passage covers, which keeps a long paragraph
    from winning on length alone.
    """
    want = _terms(question)
    if not want or not passages:
        return None
    seen = [set(_terms(p.text + " " + p.title)) for p in passages]
    n = len(passages)
    weight = {
        t: math.log(1 + n / (1 + sum(1 for s in seen if t in s)))
        for t in set(want)
    }
    total = sum(weight[t] for t in set(want))
    if total <= 0:
        return None
    # Ties are common and they are not cosmetic: a one-word question scores every passage
    # containing that word at 1.0, and the winner was decided by corpus order. "Who would I
    # report to?" tied the paragraph about REPORTS with the one that says there is nobody to
    # report to, and order handed it the wrong one. Adjacency breaks it -- "report to" appears
    # as a phrase in only one of them -- and it decides nothing when there is no tie.
    ranked = []
    for passage, terms in zip(passages, seen):
        got = sum(weight[t] for t in set(want) if t in terms)
        ranked.append((got / total, _phrases(question, passage), passage))
    score, _, passage = max(ranked, key=lambda r: (r[0], r[1]))
    return None if score < MIN_SCORE else (score, passage)


def _phrases(question: str, passage: Passage) -> int:
    """How many of the question's adjacent word pairs appear in the passage, stopwords kept.

    The dropped words are what make a phrase a phrase: "report to" and "report names" share
    every content word this scorer can see and mean different things.
    """
    q = _WORD.findall(question.lower())
    body = " ".join(_WORD.findall((passage.text + " " + passage.title).lower()))
    return sum(1 for a, b in zip(q, q[1:]) if "%s %s" % (a, b) in body)


def quoted(quote: str, passage: Passage) -> bool:
    """Is this the passage's own words, and a real sentence rather than a fragment?

    `observe._grounded` measures how much of the quote the passage covers in long matching
    runs, which is what separates copying from composing: a sentence rebuilt from the passage's
    own words -- "recordings are removed when the interview ends" -- matches only in scraps, and
    a true sentence with a false clause appended carries the clause's length unmatched. It
    tolerates the tidying a model does while copying, and nothing more.
    """
    return _grounded(quote, passage.shown)


async def answer(provider: Provider, question: str,
                 passages: list[Passage]) -> tuple[str, str] | None:
    """One candidate question in, the passage's own sentence and its citation out, or None.

    Every way down ends at the honest line rather than at something assembled: no passage, a
    refusal paragraph, an empty quote and a quote that is not the passage's own words all
    decline. A declined answer the corpus could have given costs one "I can't answer"; a
    composed one that is wrong costs a candidate a false fact about their own recordings.
    """
    hit = find(passages, question)
    if hit is None:
        return None
    _, passage = hit

    # A refusal paragraph is retrieved and then declines, with no model call. Composing from it
    # produced the document's own third-person prose read aloud -- "Anything about a real job.
    # Salary, team size, the office ... there is no company here to have an answer" -- in reply
    # to someone who asked what the job pays. The runner's own line was written for this moment
    # and is better than anything assembled from a page about the product.
    if passage.decline:
        return None

    out = await provider.complete(
        SYSTEM,
        "Note (%s):\n%s\n\nThe candidate asked: %s" % (passage.cite, passage.text, question),
        schema=SCHEMA, max_tokens=MAX_TOKENS)
    try:
        said = " ".join((json.loads(out.text or "{}").get("quote") or "").split())
    except ValueError:
        said = ""
    if not said or not quoted(said, passage):
        return None
    spoken = _sentences_around(said, passage.text)
    return (spoken, passage.cite) if spoken else None


# Opens a sentence that leans on the one before it. Spoken alone, "It removes that interview's
# directory" answered "how do I delete an interview?" without ever saying what "it" was.
_LEANS_BACK = re.compile(r"^(?:it|its|this|that|these|those|they|their)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _sentences_around(quote: str, text: str) -> str:
    """The passage's own whole sentences that the quote was taken from.

    The quote only LOCATES the answer; what is spoken is the document's text, so a model that
    tidies while copying never puts its tidying into the room. Measured live: asked what happens
    to their recording, the model quoted a clause from the middle of a sentence -- "says how
    much space it is using, and states whether..." -- which is true and cannot be said aloud.
    """
    sentences = [s for s in _SENTENCE.split(text.strip()) if s]
    spans, at = [], 0
    for s in sentences:
        start = text.find(s, at)
        spans.append((start, start + len(s)))
        at = start + len(s)
    blocks = [b for b in difflib.SequenceMatcher(None, text.lower(), quote.lower(),
                                                 autojunk=False).get_matching_blocks()
              if b.size >= 12]
    # Nothing to locate means nothing to say. Falling back to the quote itself would speak the
    # model's words after all, which is the one thing this function exists to prevent.
    if not blocks:
        return ""
    lo, hi = blocks[0].a, blocks[-1].a + blocks[-1].size
    picked = [i for i, (a, b) in enumerate(spans) if a < hi and b > lo]
    if picked and picked[0] > 0 and _LEANS_BACK.match(sentences[picked[0]]):
        picked.insert(0, picked[0] - 1)
    return " ".join(sentences[i] for i in picked)
