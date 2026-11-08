"""One interview as a file you can keep. Plan section 12.9.

Everything here is local, so export *is* the sharing mechanism: there is no link to send and
no account to grant. That makes the format the whole feature, and it settles three things.

  self-contained    no stylesheet, no script, no font and no audio fetched from anywhere. A
                    report that needs a server to render is not a copy of anything, and this
                    one has to still open in five years on a machine that never had Mockingbird
                    installed. The cost is size, which is stated in the document rather than
                    discovered when it will not open.
  its own evidence  the quotes travel with it. A score whose evidence lives back in the app is
                    exactly the take-it-on-trust report 12.9 exists to avoid.
  says what made it the provenance block, verbatim (FR-42). A report that cannot say which
                    model and which prompt produced it cannot be checked against a later one,
                    and "the local model" is not an answer once the model has been swapped.

The JSON sidecar carries the same facts without the presentation, so the export is not a dead
end: it can be diffed, re-scored, or read by something that is not a browser. The Markdown copy
(FR-22) is for notes and documents: the words and the numbers, without the recordings.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from .corrections import scored_answers
from .score import met_by_question

# Past this much audio the document stops being openable, and a browser that hangs on it is a
# worse outcome than one that says what was left out. Roughly an hour of speech at 16 kHz mono.
AUDIO_CAP = 96 * 1024 * 1024

# The renderer underlines every heading with a rule of = or -. That is the one structural
# promise the plain text makes, so it is the only thing parsed.
_RULE = re.compile(r"^[=-]{10,}$")


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _dashes(text: str) -> str:
    return (text or "").replace(" -- ", " - ")


def _sections(text: str) -> list[dict]:
    lines = (text or "").split("\n")
    out: list[dict] = []
    current: dict = {"heading": None, "lines": []}
    i = 0
    while i < len(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if lines[i].strip() and _RULE.match(nxt.strip()):
            out.append(current)
            current = {"heading": lines[i].strip(), "lines": []}
            i += 2
            continue
        current["lines"].append(lines[i])
        i += 1
    out.append(current)
    return [s for s in out if s["heading"] or any(ln.strip() for ln in s["lines"])]


def _blocks(lines: list[str]) -> list[tuple[str, str]]:
    """Reflow the terminal's 60-column wrapping back into paragraphs.

    One line per element would make every wrap the terminal chose a hard break at whatever
    width the reader is on. A blank line separates blocks, a bullet starts one, and a line
    opening on a quotation mark is the candidate's own words rather than ours.
    """
    out: list[list[str]] = []
    kinds: list[str] = []
    fresh = True
    for raw in lines:
        line = raw.strip()
        if not line:
            fresh = True
            continue
        if line.startswith(("“", '"')) or line.startswith("You said:"):
            out.append([line])
            kinds.append("quote")
            fresh = True
            continue
        if line.startswith("- "):
            out.append([line[2:]])
            kinds.append("item")
            fresh = False
            continue
        if fresh or kinds[-1] in ("quote",):
            out.append([line])
            kinds.append("para")
            fresh = False
        else:
            out[-1].append(line)
    return list(zip(kinds, (" ".join(b) for b in out)))


def _is_rubric_section(section: dict, rubric: list[dict]) -> bool:
    """The text report prints the criteria aligned with spaces. The payload carries the same
    numbers as data, so the table replaces it rather than repeating it."""
    if len(rubric) < 2:
        return False
    body = "\n".join(section["lines"])
    return sum(1 for c in rubric if c.get("name") and c["name"] in body) >= 2


def _rubric_table(rubric: list[dict]) -> str:
    # Weakest first, as the report surface orders it: alphabetical buries the shortfalls
    # between full rows in a document whose whole claim is checkable arithmetic.
    def rank(c: dict) -> tuple:
        return (c.get("met", 0) / (c.get("of") or 1), c.get("name", ""))

    rows = []
    for c in sorted(rubric, key=rank):
        label = c.get("label") or (c.get("name") or "").replace("_", " ")
        ev = c.get("evidence") or []
        marks = "".join(
            '<span class="tick%s"></span>' % (" met" if e.get("met") else "") for e in ev
        ) or "".join('<span class="tick%s"></span>' % (" met" if i < c.get("met", 0) else "")
                     for i in range(c.get("of", 0)))
        detail = ""
        if ev:
            items = []
            for e in ev:
                quote = e.get("quote")
                if quote:
                    said = '<q>%s</q>' % _esc(_dashes(quote))
                else:
                    # Never inside quotation marks: the deterministic criteria are detections,
                    # and printing our own sentence as theirs is the one thing this must not do.
                    said = '<span class="none">%s</span>' % (
                        "Detected in this answer. No quote: this one is measured, not extracted."
                        if e.get("met") else "Not found in this answer.")
                items.append(
                    '<li class="%s"><span class="asked">%s</span>%s</li>'
                    % ("met" if e.get("met") else "missed", _esc(e.get("question") or ""), said))
            detail = (
                '<tr class="evidence"><td colspan="3"><details>'
                '<summary>What this rests on</summary>'
                '<ol>%s</ol></details></td></tr>' % "".join(items))
        rows.append(
            '<tr><th scope="row">%s</th><td class="ticks"><span class="marks">%s</span>'
            '<span class="count">%s<span class="of">/%s</span></span></td>'
            '<td class="desc">%s</td></tr>%s'
            % (_esc(label), marks, c.get("met", 0), c.get("of", 0),
               _esc(_dashes(c.get("description") or "")), detail))
    return '<table class="rubric"><tbody>%s</tbody></table>' % "".join(rows)


def _audio(session_dir: Path, turns: list[dict], embed: bool) -> tuple[dict[str, str], int, str]:
    """`audio` name -> data URI, the bytes spent, and what to say about what is missing."""
    if not embed:
        return {}, 0, "Recordings were left out of this copy."
    wanted = []
    for turn in turns:
        name = (turn.get("audio") or "").split("/")[-1]
        if name and name not in wanted:
            wanted.append(name)
    room = (session_dir / "audio")
    out: dict[str, str] = {}
    spent = 0
    dropped = 0
    for name in wanted:
        f = room / name
        try:
            blob = f.read_bytes()
        except OSError:
            dropped += 1
            continue
        if spent + len(blob) > AUDIO_CAP:
            dropped += 1
            continue
        out[name] = "data:audio/wav;base64," + base64.b64encode(blob).decode("ascii")
        spent += len(blob)
    if dropped:
        return out, spent, ("%d recording%s left out: this copy would not have opened with them."
                            % (dropped, "" if dropped == 1 else "s"))
    if not wanted:
        return out, spent, "This interview was typed, so there is nothing to play back."
    return out, spent, ""


def sidecar(report: dict, session: dict, turns: list[dict]) -> dict:
    """The same interview without the presentation. Diffable, re-scorable, and readable by
    something that is not a browser."""
    return {
        "session_id": report.get("session_id") or session.get("session_id"),
        "label": report.get("label"),
        "started_at": report.get("started_at") or session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "status": session.get("status"),
        "asked": report.get("asked"),
        "answered": report.get("answered"),
        "scored": report.get("scored"),
        "rubric": report.get("rubric") or [],
        "delivery": report.get("delivery") or {},
        "report_text": report.get("text") or "",
        # FR-31: what was corrected after the interview, each beside what was heard.
        "corrections": report.get("corrections") or [],
        # What produced it. Without this a report cannot be compared to a later one.
        "provenance": session.get("provenance") or {},
        "turns": [{
            "index": t.get("index"),
            "question_id": t.get("question_id"),
            "question": t.get("question"),
            "utterance": t.get("utterance"),
            "heard": t.get("heard"),
            "said": t.get("say"),
            "at": t.get("at"),
        } for t in turns],
    }


STYLE = """
:root {
  --ink: #14161a; --quiet: #5b6068; --faint: #8a8f98; --ground: #fbfaf8;
  --raised: #ffffff; --rule: #e2e0dc; --strong: #b9b6b0; --mark: #14161a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #e9e7e3; --quiet: #a6a9ae; --faint: #7d818a; --ground: #14161a;
    --raised: #1b1e23; --rule: #2c3037; --strong: #474c55; --mark: #e9e7e3;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2.5rem 1rem 4rem; background: var(--ground); color: var(--ink);
  font: 16px/1.6 ui-serif, Georgia, "Times New Roman", serif;
}
main { max-width: 46rem; margin: 0 auto; background: var(--raised); border: 1px solid var(--rule);
  padding: 2.5rem clamp(1rem, 4vw, 3rem) 3rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; letter-spacing: -0.01em; }
h2 { font-family: ui-sans-serif, system-ui, sans-serif; font-size: .72rem; font-weight: 600;
  letter-spacing: .1em; text-transform: uppercase; color: var(--quiet);
  margin: 2.5rem 0 .75rem; }
h3 { font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; margin: 1.5rem 0 .4rem; }
p { margin: 0 0 .8rem; }
.slug { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: .72rem;
  letter-spacing: .08em; text-transform: uppercase; color: var(--faint); }
.lede { color: var(--quiet); font-size: .95rem; }
blockquote { margin: 0 0 .8rem; padding-left: .9rem; border-left: 2px solid var(--strong);
  color: var(--quiet); }
ul { margin: 0 0 .8rem; padding-left: 1.1rem; }
table { width: 100%; border-collapse: collapse; }
.rubric th { text-align: left; font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: .85rem; font-weight: 500; padding: .6rem 1rem .6rem 0; }
.rubric td { padding: .6rem 1rem .6rem 0; vertical-align: middle; font-size: .85rem; }
.rubric tr { border-bottom: 1px solid var(--rule); }
.ticks { white-space: nowrap; width: 1%; }
.marks { display: inline-flex; gap: 3px; margin-right: .75rem; vertical-align: -2px; }
.tick { width: 6px; height: 14px; border-radius: 1px; box-shadow: inset 0 0 0 1px var(--strong); }
.tick.met { background: var(--mark); box-shadow: none; }
.count { font-family: ui-monospace, Consolas, monospace; }
.of, .desc { color: var(--quiet); }
.evidence td { padding: 0 0 .8rem; }
.evidence summary { font-family: ui-sans-serif, system-ui, sans-serif; font-size: .75rem;
  letter-spacing: .04em; text-transform: uppercase; color: var(--faint); cursor: pointer; }
.evidence ol { list-style: none; margin: .6rem 0 0; padding: 0; display: grid; gap: .7rem; }
.evidence li { border-left: 2px solid var(--strong); padding-left: .8rem; }
.evidence li.met { border-left-color: var(--mark); }
.asked { display: block; font-size: .75rem; color: var(--faint); }
.none { color: var(--quiet); }
q { quotes: "\\201C" "\\201D"; }
.answer { border-top: 1px solid var(--rule); padding-top: 1rem; margin-top: 1rem; }
audio { width: 100%; margin: .5rem 0; }
.figures { display: flex; flex-wrap: wrap; gap: 1.2rem; margin: 0; font-size: .8rem; }
.figures div { display: flex; gap: .4rem; align-items: baseline; }
.figures dt { color: var(--faint); text-transform: uppercase; font-size: .7rem;
  letter-spacing: .04em; font-family: ui-sans-serif, system-ui, sans-serif; }
.figures dd { margin: 0; font-family: ui-monospace, Consolas, monospace; }
.turn { margin: 0 0 1.1rem; }
.turn .who { display: block; font-size: .7rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--faint); font-family: ui-sans-serif, system-ui, sans-serif; }
.turn.them { color: var(--quiet); }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rule);
  font-size: .78rem; color: var(--quiet); }
footer dl { display: grid; grid-template-columns: auto 1fr; gap: .2rem 1rem; margin: .6rem 0 0; }
footer dt { color: var(--faint); }
footer dd { margin: 0; font-family: ui-monospace, Consolas, monospace; }
@media print {
  body { padding: 0; background: #fff; }
  main { border: 0; padding: 0; }
  audio, .evidence summary { display: none; }
  .evidence ol { margin-top: 0; }
}
"""


def _size(n: int) -> str:
    if n >= 1_000_000:
        return "%.1f MB" % (n / 1_000_000)
    return "%d kB" % max(1, round(n / 1000))


def html_document(report: dict, session: dict, turns: list[dict],
                  session_dir: Path, embed_audio: bool = True) -> str:
    """One interview, complete, in a single file."""
    rubric = report.get("rubric") or []
    delivery = report.get("delivery") or {}
    clips, spent, missing = _audio(session_dir, turns, embed_audio)

    label = report.get("label") or session.get("plan_id") or "Interview"
    started = (report.get("started_at") or session.get("started_at") or "")[:16].replace("T", " ")
    sid = report.get("session_id") or session.get("session_id") or ""

    body: list[str] = []
    for section in _sections(report.get("text") or ""):
        if section["heading"]:
            body.append("<h2>%s</h2>" % _esc(section["heading"].lower()))
        if _is_rubric_section(section, rubric):
            body.append(_rubric_table(rubric))
            continue
        items: list[str] = []
        for kind, text in _blocks(section["lines"]):
            if kind == "item":
                items.append("<li>%s</li>" % _esc(_dashes(text)))
                continue
            if items:
                body.append("<ul>%s</ul>" % "".join(items))
                items = []
            if kind == "quote":
                body.append("<blockquote>%s</blockquote>" % _esc(_dashes(text)))
            else:
                body.append("<p>%s</p>" % _esc(_dashes(text)))
        if items:
            body.append("<ul>%s</ul>" % "".join(items))

    spoken = [a for a in (delivery.get("answers") or []) if not a.get("why") and a.get("audio")]
    if spoken or missing:
        body.append("<h2>hear it back</h2>")
        if missing:
            body.append('<p class="lede">%s</p>' % _esc(missing))
        for a in spoken:
            name = (a.get("audio") or "").split("/")[-1]
            figures = [("Rate", "%s syl/s" % a.get("articulation_rate")),
                       ("Pauses", str(a.get("pause_count")))]
            if a.get("wpm"):
                figures.append(("Words", "%d/min" % round(a["wpm"])))
            if a.get("pause_count"):
                figures.append(("Mid-clause",
                                "%s of %s" % (a.get("mid_clause_pauses"), a.get("pause_count"))))
            player = ('<audio controls preload="none" src="%s"></audio>' % clips[name]
                      if name in clips else "")
            body.append(
                '<div class="answer"><h3>%s</h3>%s<dl class="figures">%s</dl></div>'
                % (_esc(a.get("question_id") or "answer"), player,
                   "".join("<div><dt>%s</dt><dd>%s</dd></div>" % (k, _esc(str(v)))
                           for k, v in figures)))

    fixes = report.get("corrections") or []
    if fixes:
        body.append("<h2>corrected before scoring</h2>")
        body.append('<p class="lede">The report reads these answers as the candidate corrected '
                    'them after the interview. What the recogniser heard is kept beside each, and '
                    'the transcript below is unchanged.</p>')
        for c in fixes:
            body.append('<div class="answer"><h3>%s</h3><p><span class="asked">Heard</span>%s</p>'
                        '<p><span class="asked">Corrected</span>%s</p></div>'
                        % (_esc(c.get("question") or c.get("question_id") or ""),
                           _esc(c.get("original") or ""), _esc(c.get("corrected") or "")))

    body.append("<h2>what was said</h2>")
    for turn in turns:
        if turn.get("utterance"):
            body.append('<p class="turn"><span class="who">You</span>%s</p>'
                        % _esc(turn["utterance"]))
        if turn.get("say"):
            body.append('<p class="turn them"><span class="who">Interviewer</span>%s</p>'
                        % _esc(turn["say"]))

    prov = session.get("provenance") or {}
    rows = "".join("<dt>%s</dt><dd>%s</dd>" % (_esc(k.replace("_", " ")), _esc(str(v)))
                   for k, v in prov.items() if v not in (None, ""))

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>%s - %s</title>\n<style>%s</style>\n</head>\n<body>\n<main>\n"
        "<span class=\"slug\">Mockingbird / %s</span>\n"
        "<h1>%s</h1>\n<p class=\"lede\">%s. Produced on the machine it was recorded on. "
        "Everything it claims is in this file, including the words each judgement rests on.</p>\n"
        "%s\n<footer><p>Scored by reading the answers back: which words counted as evidence was "
        "decided by a model, and the arithmetic over them was not. %s</p>"
        "<dl>%s</dl></footer>\n</main>\n</body>\n</html>\n"
        % (_esc(label), _esc(started or sid), STYLE, _esc(sid), _esc(label), _esc(started),
           "\n".join(body),
           _esc("Recordings embedded: %s." % _size(spent) if spent else (missing or "")),
           rows))


# CommonMark treats these as structure anywhere in a line, and an answer is the candidate's
# words: none of it may become a link, emphasis, a table cell boundary or raw HTML.
# An underscore inside a word is never emphasis, so Q4_K_M stays readable in the raw file.
_MD_INLINE = re.compile(r"([\\`*\[\]<>|~&]|(?<!\w)_|_(?!\w))")
_MD_LEAD = re.compile(r"^([#>+=-])|^(\d+)([.)])")


def _md(text: str) -> str:
    """One line of literal text."""
    t = _MD_INLINE.sub(r"\\\1", _dashes(" ".join((text or "").split())))
    return _MD_LEAD.sub(
        lambda m: "\\" + m.group(1) if m.group(1) else m.group(2) + "\\" + m.group(3), t)


def _md_heading(heading: str) -> str:
    h = heading.strip().lower()
    return h[:1].upper() + h[1:]


def _md_rubric(rubric: list[dict]) -> list[str]:
    def rank(c: dict) -> tuple:
        return (c.get("met", 0) / (c.get("of") or 1), c.get("name", ""))

    rows = ["| Criterion | Met | What it looks for |", "| --- | --- | --- |"]
    for c in sorted(rubric, key=rank):
        rows.append("| %s | %s/%s | %s |" % (
            _md(c.get("label") or (c.get("name") or "").replace("_", " ")),
            c.get("met", 0), c.get("of", 0), _md(c.get("description") or "")))
    return rows


def markdown_document(report: dict, session: dict) -> str:
    """The report, each question with its answers as scored, delivery and provenance."""
    rubric = report.get("rubric") or []
    delivery = report.get("delivery") or {}
    label = report.get("label") or session.get("plan_id") or "Interview"
    started = (report.get("started_at") or session.get("started_at") or "")[:16].replace("T", " ")
    sid = report.get("session_id") or session.get("session_id") or ""
    labels = {c.get("name"): c.get("label") or (c.get("name") or "").replace("_", " ")
              for c in rubric}

    out = ["# %s" % _md(label), "",
           "%s · %s asked, %s answered, %s scored · session %s" % (
               started or "unknown", report.get("asked", 0), report.get("answered", 0),
               report.get("scored", 0), _md(sid)), "",
           "Scored by reading the answers back: which words counted as evidence was decided by "
           "a model, and the arithmetic over them was not.", ""]

    tabled = False
    for section in _sections(report.get("text") or ""):
        if section["heading"]:
            out += ["## %s" % _md(_md_heading(section["heading"])), ""]
        if _is_rubric_section(section, rubric):
            out += _md_rubric(rubric) + [""]
            tabled = True
            continue
        last = None
        for kind, text in _blocks(section["lines"]):
            if last == "item" and kind != "item":
                out.append("")
            if kind == "item":
                out.append("- %s" % _md(text))
            else:
                out += ["%s%s" % ("> " if kind == "quote" else "", _md(text)), ""]
            last = kind
        if last == "item":
            out.append("")
    if rubric and not tabled:
        out += ["## Every criterion", ""] + _md_rubric(rubric) + [""]

    fixes = {(c.get("question_id"), c.get("index")): c.get("original")
             for c in report.get("corrections") or []}
    met = met_by_question(rubric)
    answered = [(qid, q, a) for qid, (q, a) in scored_answers(
        session, report.get("corrections")).items() if a]
    if answered:
        out += ["## Answers", ""]
        for n, (qid, question, answers) in enumerate(answered, 1):
            out += ["### %d. %s" % (n, _md(question or qid)), ""]
            for i, text in enumerate(answers):
                out += ["> %s" % _md(text), ""]
                if (qid, i) in fixes:
                    out += ["*Corrected after the interview. The recogniser heard:* %s"
                            % _md(fixes[(qid, i)]), ""]
            crit = met.get(qid) or {}
            if crit:
                hit = [labels.get(k, k) for k, ok in crit.items() if ok]
                miss = [labels.get(k, k) for k, ok in crit.items() if not ok]
                out += ["Met: %s. Missed: %s." % (_md(", ".join(hit) or "none"),
                                                  _md(", ".join(miss) or "none")), ""]

    spoken = [a for a in delivery.get("answers") or [] if not a.get("why")]
    if spoken:
        out += ["## Delivery, answer by answer", "",
                "| Answer | Syllables/s | Words/min | Pauses | Mid-clause pauses |",
                "| --- | --- | --- | --- | --- |"]
        for a in spoken:
            out.append("| %s | %s | %s | %s | %s |" % (
                _md(a.get("question_id") or "answer"), a.get("articulation_rate", ""),
                round(a["wpm"]) if a.get("wpm") else "", a.get("pause_count", ""),
                a.get("mid_clause_pauses", "")))
        out.append("")

    prov = dict(session.get("provenance") or {})
    if report.get("scored_by"):
        prov["scored_by"] = report["scored_by"]
    if prov:
        out += ["## What produced it", ""]
        for k, v in prov.items():
            if isinstance(v, dict):
                v = ", ".join("%s %s" % (kk, vv) for kk, vv in v.items() if vv not in (None, ""))
            if v not in (None, ""):
                out.append("- %s: %s" % (_md(k.replace("_", " ")), _md(str(v))))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"
