# Mockingbird

A mock-interview coach for software-engineering roles that runs entirely on your own machine.
It conducts a structured interview, decides for itself when to probe and when to move on, and
produces feedback in which every claim quotes something you actually said.

Built and validated against Qwen3-4B-Instruct-2507 on a 6GB laptop GPU, which is the
constraint that shaped the whole design. Mockingbird intentionally supports that model only:
accepting an unknown loaded model would bypass the controls measured for the product.

## The idea it is testing

An interview is latency-sensitive and consent-sensitive, so it is a bad fit for an
unconstrained agent loop. Mockingbird gives the model a narrow job and keeps everything else
in Python:

| | |
|---|---|
| **The model** | writes the next sentence, and extracts verbatim quotes from an answer |
| **Python** | decides when to probe, when to stop, what to score, and when to end |

The model never has authority over consent, pacing, budgets, durable state, or a score. Its
proposed action is recorded and usually overridden, which is deliberate: keeping it visible is
what makes the override measurable.

## Extract, then score

The model is never asked "was this a good answer". It is asked what an answer *contains* —
quote the situation, quote the action, quote the result — and deterministic Python computes
the rubric from those quotes.

Two properties follow. Every criterion names the observation behind it, so a score can be
argued with by pointing at the quote it rests on. And the arithmetic is reproducible: the same
observations always score the same way.

The boundary is real and the code is explicit about where it sits. A criterion that is a fact
about text works well. A criterion that smuggles in a judgement does not, and the design
questions are deliberately **observed and not scored** for that reason — the report describes
what a design answer covered rather than putting a number on it.

## Guards

Five guards run on every model decision before a handler sees it. Each exists because
something went wrong, not because it seemed prudent:

- an action that ends or skips a question needs the candidate's own words behind it
- a question the model invented for itself never reaches the candidate
- a repeated line is regenerated once, and a second repeat is treated as the model's position
- closing actions do not speak the model's line
- prompt fragments are stripped out of speech

Natural probing adds two bounded speech controls after those guards. Hypothetical design
questions are kept in future tense, and an empty or off-focus probe gets one speech-only repair
attempt. That second contract exposes only `say`, so it cannot change the chosen action, the
model's completeness judgement, candidate-question routing, pacing or budget. Python accepts the
repair when it is a direct question within the word cap, asks about a focus this question has not
already spent, and does not repeat the rejected line, the current question or earlier session
speech. Otherwise a reviewed focus template is used.

The repair asks for a focus but does not insist on it, because the decision path it serves does
not either: a question that arrives on a different unspent focus is a good turn, and demanding
the exact one discarded usable questions in favour of canned lines. The repair also runs under a
deadline; past it the turn stops waiting and speaks the template, which bounds what a candidate
can be left waiting for on a slow machine.

Two more controls compare meaning rather than spelling, and both are skipped when the optional
embedding model is absent:

- a probe that re-asks the previous one in different words is dropped and the question advances,
  because focus rotation compares LABELS and cannot see "how did you know X" and "what made you
  decide X" as one question
- a line the repetition guard flags is kept anyway when the embedding disagrees, because that
  guard compares characters and short interview questions are mostly shared scaffolding

Compound questions are kept rather than trimmed. A two-part question is ordinary interviewer
behaviour, one of the scripted questions is itself double-barrelled, and trimming to the first
clause discarded the better half often enough to notice while halving the text the focus
classifier had to read.

Control replies — stop, skip, carry on — are parsed by `app/intent.py`, which matches whole
tokens, scopes negation to its clause, and answers `UNCLEAR` when it genuinely cannot tell.
Ambiguity never ends a session.

## Live and report are separate channels

What the candidate sees comes only from `live_view()`. Judgement fields — the model's
completeness verdict, action posteriors, guard names, rubric results — go to storage and the
report and never cross the live channel. Someone who can watch the agent deciding their answer
is weak will change their answer, and the assessment stops measuring what it claims to.

## Installing it on Windows

`python installer/build.py` builds `dist/Mockingbird-Setup-<version>.exe`, a 33 MB installer
carrying its own Python, the app and the built interface. It needs Inno Setup 6 and the
interface built first (`npm --prefix ui run build`). The installer:

* installs for the current user only, with no admin rights, into
  `%LOCALAPPDATA%\Programs\Mockingbird`, and adds a Start-menu shortcut;
* on first start downloads about 5 GB once: the models from Hugging Face and the llama.cpp
  runtime from GitHub, each pinned to an exact revision and checked against SHA-256 before it
  is used, and Parselmouth from PyPI;
* then starts the model servers and the app and opens it. Closing its window stops everything.

It needs a 6 GB NVIDIA GPU. Uninstalling removes the program, the models and the runtime and
keeps the interviews in `data\`. The installer is not code-signed yet, so Windows SmartScreen
warns before running it.

## Running it from source

Needs Python 3.12. Every model runs in llama.cpp's `llama-server` on loopback, one process
each. Fetch the models and the runtime once, then start the servers before the app:

```bash
python -m app.download
python -m app.servers
```

`app.download` puts every file below in place, each checked against a pinned SHA-256, and skips
whatever is already there; `--from DIR` takes matching files from a folder that already holds
them. Point `MOCKINGBIRD_LLAMA_SERVER` at an existing `llama-server.exe` instead of fetching the
runtime into `runtime/`.

| Server | Model file | Where it goes | Port |
|---|---|---|---|
| Language model, required | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` from [`lmstudio-community/Qwen3-4B-Instruct-2507-GGUF`](https://huggingface.co/lmstudio-community/Qwen3-4B-Instruct-2507-GGUF) | `models/qwen3-4b-instruct-2507/` | 8091 |
| Voice | the LFM3-Audio files in the voice section below | `models/lfm3-audio/` | 8092 |
| Embedder, optional | `all-MiniLM-L6-v2-Q8_0.gguf` from [`second-state/All-MiniLM-L6-v2-Embedding-GGUF`](https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF) | `models/all-minilm-l6-v2/` | 8093 |

The language model is started under its exact alias and checked by alias and file before an
interview starts, so a different model cannot quietly take its place. All three fit a 6 GB
card together.

The embedder is optional and worth having. Two of the speech controls compare what a probe
MEANS rather than how it is spelled, and without it they fall back to comparing words, which is
quieter and weaker rather than an error. The model was chosen by measuring six candidates on
labelled probe pairs from real sessions rather than by leaderboard: all-MiniLM-L6-v2 at 22M
parameters beat nomic-embed-v1.5, mxbai-embed-large and embeddinggemma-300m, because those are
tuned for matching a short query to a long document while this compares two questions of the
same shape. It costs 25MB on disk and runs on the CPU, at about 11 ms a comparison.

Then plan an interview. There are three ways in.

From a job description, which is read for the competencies it actually asks for and turned
into a plan you review before anyone is interviewed with it:

```bash
python tools/plan_review.py --jd path/to/description.txt
```

Without one, from a stock plan at a length you choose:

```bash
python tools/plan_review.py --stock technical --minutes 40
```

Or skip planning and run the hand-written plan, which is the one every measurement in this
repo was taken against:

```bash
python -m app.cli
```

The runtime is standard library only. Tests need pytest:

```bash
pip install -e ".[test]"
python -m pytest
```

`tools/` holds a turn-at-a-time harness (`live_candidate.py`) for driving a session
programmatically, plus renderers for the report and the transcript.

To audit how model-written questions were retained or transformed in a recent session:

```powershell
python tools/probe_audit.py --session SESSION_ID `
  --out data/calibration/probe-audit.json
```

The audit measures speech transformation, not interview quality or model accuracy. It rejects
sessions captured before raw model speech provenance was added rather than mixing incompatible
records. It reports retained, repaired and template-substituted questions separately. Each repair
also persists its trigger, raw attempt, accepted line, detected focus and rejection reason in
`speech_attempt`.

## Planning, and what the agent is allowed to ask

A job description is read for the competencies it asks for, each one cited from the
description's own words. A competency whose citation is not actually in the text is dropped
and kept separately, because "the description did not ask for this" and "the planner missed
it" are different facts and only a person can tell them apart. The vocabulary is closed and
the extraction schema takes its list from the question bank, so the planner cannot name a
competency it has no question for.

Questions come from a curated bank. The model may also write one, and when it does the
question is marked `generated` and lands at `proposed`, which means it cannot be asked. There
are exactly three ways a question reaches a candidate:

- it was written by hand and reviewed, or
- it was generated and a person approved it, or
- a person typed it during review.

Approving changes a question's status and never its source, so a generated question stays
marked as one after it is approved. Assembly reads askable questions only, and review refuses
to add a proposal by hand, so the gate cannot be reached past from either side. That is what
makes asking every scripted question verbatim worth anything.

Assembly chooses questions and nothing else. Every other field of a phase -- the probe
budgets, the focus ladders, whether the phase is scored -- is a measured decision, so the
phase configuration is the reviewed template and a test asserts it comes through unchanged.

Two limits worth knowing. Extraction found four of six competencies on a hand-labelled
description and missed one the text names outright; asking per competency instead measured
worse, so review is the mitigation rather than a better prompt. And the near-duplicate check
on a generated question catches 12 of 28 real rephrasings at the threshold that produces no
false positives -- a cheap filter on the obvious cases, not a guarantee.

## Layout

```
app/
  runner.py        the loop: one decision per turn, dispatch over pure functions
  contract.py      the normal turn and speech-only repair schemas and prompts
  guards.py        the five guards
  intent.py        stop / skip / carry-on parsing
  direction.py     is this an answer, or a question aimed at the interviewer
  focus.py         picks what to ask ABOUT; the model only words it
  budget.py        per-question cap plus a shared session pool
  observe.py       quote extraction, with grounding
  provider.py      the language model over llama-server: turns, posteriors, the exact-model gate
  servers.py       starts the three llama-server processes, in order
  download.py      first-run downloads: pinned sources, SHA-256 checks
  launch.py        what the installed shortcut runs: download, servers, app, browser
  embed.py         OPTIONAL local sentence similarity; returns None when absent
  score.py         the rubric, as arithmetic
  report.py        the feedback, and the rules about how it is worded
  detour.py        the candidate's own questions, answered from documents or declined
  export.py        one interview as a single file, recordings inside it
  session.py       plan validation and persistence
  bank.py          the curated question bank and its closed competency vocabulary
  planner.py       description -> competencies -> plan; generation, and stock plans
  review.py        the operations a person performs on a plan before it is run
  resume.py        carrying a live session between processes
  audio.py         PCM framing, the wire protocol, where to cut a growing answer
  speech.py        the TTS port, onto LFM3-Audio
  listen.py        the ASR port, onto LFM3-Audio, a slice at a time
  lfm3.py          LFM3-Audio through llama-server: one process that hears and speaks
  endpoint.py      live mode's endpointer: when an answer has ended, from silence
  delivery.py      fluency from the waveform; observation, never a score
api/
  main.py          the HTTP surface, and the static host for the built interface
  voice.py         the WebSocket carrying microphone up and speech down
ui/
  src/lib/         design tokens, the shared on-air state, the icon set
  src/lib/audio/   the browser half of the transport, and the phase machine
  src/routes/      the three surfaces: plan, interview, history
  static/fonts/    the three faces, self-hosted so the app renders offline
config/            interview plans, the question bank, and what the interview may say
                   about itself (about.md)
installer/         the Windows installer: build script, Inno Setup script, locked wheels, and
                   the app icon with the script that renders it from the logo
LICENSES/          licence texts for third-party code the installer ships (GPL-3.0)
tests/             deterministic unit and integration coverage
tools/shots.sh     screenshots every surface at both widths, for design review
```

## Why Qwen3-4B-Instruct

Mockingbird was built measurement-first, and the runtime changed once the measurements said to.
Llama 3.2 3B was the sole model until September 2026, when a symmetric screen and a paired live
control replaced it.

On 60 fixtures scored through the real guards, Qwen reads 49/49 with severity 0 against Llama's
47/49 and severity 2, and it never contradicts itself on `advance`: it chooses that action ten
times for ten, where Llama chooses it twelve times for the same ten. On a live junior interview
answered turn by turn, Qwen closed all fourteen questions in 29 turns against Llama's 42, needed
no speech repair where Llama's failed three times and fell back to four canned lines, and drew
twice on the shared question pool where Llama drew five times.

Qwen decodes about 24% slower per token, which is the one axis it loses and the one that matters
least: it writes less per decision, so a single turn is faster in wall time (840 ms median against
897 ms, and 1438 ms at its worst against 1682 ms), and Llama is the one that breaches the 1500 ms
per-turn budget.

Two Arcee models were screened against it in September 2026 and both were rejected.
`afm-4.5b-i1` answered `reask` on 38 of 60 turns and reads 32/49: every one of its misses is an
answered question put a second time, which is a loop rather than an interview. The
`trinity-nano-preview` mixture-of-experts reads 43/49 and decodes about three times faster,
which is the only axis on which anything has beaten Qwen, but three quarters of its turns
arrive as several stacked questions and its raw score of 20/60 becomes 43 only because the
guards rewrite it -- the interview would be written by `guards.py` rather than by the model.

Giving Trinity its own tuned arm made it worse rather than better, and that is the useful
result. Stating the completeness test concretely fixed every behavioural axis it was aimed at
and simultaneously took Trinity's invalid replies from 1 to 6; handing back half the added
instruction recovered none of them. It cannot hold the structured-output contract while
following instructions detailed enough to correct its judgement, so there is no prompt that
buys one without spending the other.

The private development log `internal_docs/MODEL_EXPERIMENTING_LOG.md` records the screens,
controls, speech audits and rejected alternatives behind that change. It remains local and
intentionally ignored by Git.

## Status

The text interview, rubric scoring, report, the natural-probing wave and the planner are
implemented, with 657 automated tests passing. An interview can be planned from a job
description or from a stock plan, reviewed and edited, saved, and then conducted.

The paired acceptance control passes on a fresh run of each profile: a junior-to-mid interview
closed all 14 questions in 25 turns and a strong one in 16, with no reask, family crossing,
invalid output, repeated focus or unknowable question in either, and no pool draws. Creative
retention across the pair was 90.9% among the questions that reached the candidate, with
byte-for-byte retention reported separately at 61.5% because the two measure different things.

Two cautions on those numbers, both learned by getting them wrong first. A single session cannot
resolve a retention difference smaller than roughly fifteen points, because extraction is
non-deterministic on this GPU path — two runs of one build measured 50.0% and 65.2%. And timing
comparisons between sessions are worthless unless the arms are interleaved: the same build has
measured 20% apart depending on how warm the GPU was.

The browser interface is built. It is one page per stage of a run: a **plan** as a numbered
running order with per-phase durations, which you edit and approve before anything is asked; the
**interview** itself; and a **history** of past interviews with the report for any one of them.

Its design follows the product's own rule that no judgement reaches the candidate mid-interview.
The interview is a dark studio under a red on-air light; the plan and the report are that
studio's paperwork on a pale ground. Red carries exactly two meanings and no others: on air, or
this needs your decision. Nothing in the interview scores, ranks or congratulates.

Serving it needs the optional `web` extra and one build:

```bash
pip install -e ".[web]"
npm --prefix ui install && npm --prefix ui run build
python -m uvicorn api.main:app --port 8000
```

The install is editable on purpose: paths are resolved from the repo root, so the question bank,
the sessions and the built interface are found where they actually live. Add `voice` --
`pip install -e ".[web,voice]"` -- for speech and the delivery measurements, which need numpy,
sherpa-onnx, `websockets` and praat-parselmouth; the text interview needs none of them.

The API runs without the interface; the static host simply does not mount when `ui/build` is
absent.

Voice works end to end. The interviewer speaks its questions, you answer by tapping to talk, and
a barge-in cuts the line where you cut it and shows the rest struck through. A single WebSocket
at `/api/voice` carries microphone PCM up and synthesised speech down, an `AudioWorklet`
resamples capture to the 16 kHz the recogniser wants, and playback is scheduled on a monotonic
cursor so bursty delivery is not audible.

Your answer is recognised **while you are still giving it**: it is read in slices cut at pauses,
so the composer fills as you talk and only the tail is left when you stop -- **0.17 s** after
release, driving `/api/voice` with a recorded 24 s answer on mains with the language model
resident. The text lands in the composer rather than being sent, because correcting it before it
is scored is a fairness requirement, not a convenience: unedited recognition scores its own
accent bias rather than the person.

Recognition is verbatim, filled pauses included, because the report reads fluency as well as
content. Jargon such as `PostgreSQL`, `gRPC` and `p99` comes back whole, but it still makes
mistakes -- `cutover` came back as `queueover` -- which is the other reason the transcript is
yours to edit.

**Live mode** is the opt-in alternative to tapping, for an interview that runs like a
conversation. The microphone opens when the interviewer finishes, your answer ends once you have
been quiet for a pause you choose (2.5 s by default; 1.5, 4 and 6 are offered), and it is sent
as it was heard. Space still finishes early, and switching back to Tap mid-answer hands the end
back to you. It trades away correcting the transcript before it is scored, and says so where it
is switched on.

The end of an answer is decided by silence length alone, measured by Silero VAD. A semantic
turn detector (Smart Turn v3.2) was replayed over recorded answers first and could not tell a
pause between sentences from the end of an answer -- it called 7 of 10 mid-answer pauses
finished -- while no pause inside any answer reached 2 s. At a 1.5 s setting one answer was cut
at a pause between sentences; at 2.5 s none were. Any pause long enough to be the end is read
straight away, so by the time the pause has run out the answer is usually already transcribed.

Both directions run on [LFM3-Audio-2B](https://huggingface.co/LiquidAI/LFM3-Audio-2B) in one
resident `llama-server` process on `127.0.0.1:8092`, so nothing reloads between calls. It fits
beside the language model on a 6 GB card in either load order (5,965 of 6,144 MiB at peak), and
`python -m app.servers` starts it with the others.

Measured on mains with the language model resident: an 84 s answer recognised in 2.2 s, a
spoken line rendered in about a fifth of its own length, and the language model's turns no
slower. Inside one answer, a word on a slice boundary can come back twice.

Voice needs two things this repository does not ship, because neither is ours, besides the
llama.cpp build the language model already needs. `python -m app.download` fetches both:

| What | Where it goes |
|---|---|
| `LFM3-Audio-2B-Q8_0.gguf` and `mmproj-LFM3-Audio-2B-BF16.gguf` from [`LiquidAI/LFM3-Audio-2B-GGUF`](https://huggingface.co/LiquidAI/LFM3-Audio-2B-GGUF), at revision `b0d3187e`: the projector was replaced afterwards, and the voice was measured on this one | `models/lfm3-audio/` |
| Silero VAD, for live mode only: [`silero_vad.onnx`](https://github.com/snakers4/silero-vad/raw/v6.2.3/src/silero_vad/data/silero_vad.onnx) from v6.2.3 | `models/vad/` |

The server is checked at connect time and reported rather than assumed: without it the interview
runs on typed answers and says so on screen, and the interviewer does not speak. Its model is
under the LFM Open License v1.0, free below US$10M annual revenue. The model can also hold the
whole conversation by itself over `/v1/realtime`; that is not wired in and should not be, because
its speech would reach the candidate without passing the guards or the runner's policy.

## How you said it, and hearing it back

The report measures delivery from the waveform: syllable rate, articulation rate, pauses, mean
length of run, pitch and intensity, and words per minute when there is a transcript to count.

**None of it needs the recogniser, and that is the point.** Every figure but words per minute
comes off the intensity and pitch contours, so a candidate whose accent the recogniser mangles
still gets accurate fluency numbers. It is also why none of it is scored: delivery is the
measurement most contaminated by recognition error and most biased against non-native speakers,
so the report says so beside the numbers rather than leaving you to assume they counted.

A pause is 200 ms, not the 100 ms most tools default to, because that is the threshold L2
fluency research found predicted proficiency on monologic tasks. Syllables are intensity peaks
flanked by a 2 dB dip with unvoiced peaks discarded -- De Jong and Wempe's method, which agrees
with hand annotation about 85-90% of the time.

Where you paused matters more than how much, so each pause is classified by the pitch reset
across it: English marks a clause boundary with a reset, while a hesitation resumes at about the
pitch it left. That one is a prosodic heuristic and its agreement with human judgement is
**unmeasured**, so the measured reset is shown beside the label and can be argued with.

Then you can hear it. Each spoken answer in the report has a player, a track with every pause
drawn on it -- one colour for inside a clause, another for between -- and jumps into the longest
of them. It does not seek to a word: that needs an alignment nothing here produces, and guessing
one from word position lands about ten seconds out on a ninety-second answer and plays the wrong
sentence under a cursor that looks exact. Where you stopped is known exactly, so that is what it
offers.

## What a score rests on

Every criterion in the report opens onto the answers that decided it: the question, and the
candidate's own words where there are any. The three deterministic criteria have none, and say
so rather than putting our sentence in quotation marks -- `specific_detail` is a regex over the
answer, and dressing a detection as a quotation would attribute it to the person being scored.

The criteria are also shown **before** the interview, on the plan sheet, with the sections each
applies to. Being told how you will be judged is ordinary assessment practice, and it is what
makes the report afterwards something you can argue with rather than something to accept.

## Taking an interview with you

Any report exports as a single HTML file with the recordings embedded in it, or without them
for one that travels by email, plus a JSON sidecar carrying the same facts without the
presentation. Everything here is local, so export *is* the sharing mechanism -- there is no
link to send.

Self-contained is the requirement rather than a nicety: the file fetches no stylesheet, no
script, no font and no audio, so it opens on a machine that never had Mockingbird installed,
years after this repository is gone. It carries the quotes behind each score and the exact
model, quantisation, context length and prompt hash that produced it, because a report that
cannot say what made it cannot be compared to a later one.

## Questions the candidate asks

The closing phase answers them from documents: the plan for the interview, and one page saying
what Mockingbird is and is not. Keyword retrieval over a few paragraphs, then one model call
that is given a single passage and asked to answer from it -- and what comes back is checked
against that passage before it is said, so an answer that drifts is replaced by the document.

**It declines rather than inventing**, and declining is deterministic. A question nothing in the
corpus covers never reaches the model. A question about the job — salary, team size, who you
would report to — retrieves the paragraph that exists to say there is no company here to have an
answer, and a paragraph marked that way is never composed from: it is retrieved so those
questions cannot land on whatever else happens to share a word with them, and then the interview
says it cannot answer for a real employer.

That marker is written in the document, not detected in code. Which questions have no answer is
an editorial decision, and a rule in Python would have to be kept in step with prose it cannot
read.

## Whether you are getting better

The history page lays the same criteria across every interview that has been read, oldest
first, each cell showing what was met and out of how many.

**There is no trend line, no percentage and no arrow, and that is a decision.** The scores
come from model extraction, so two readings of one interview need not agree, and how far they
drift has never been measured here. Until that is known, "up 12%" would be a claim the
pipeline cannot support, in a report whose whole argument is that the arithmetic is checkable.
The numbers are laid out with their denominators and you draw your own line.

It reads reports that have already been built, and says how many interviews have not been.
Scoring one costs a full extraction pass, so sixty of them is hours of model time rather than
something a page can do while you look at it.

## Where your interviews are

The history page names the directory they are in, how many there are, how many recordings
they hold and how much disk that is -- and whether any of it leaves this computer.

**That last part is derived, not asserted.** It is computed from the model provider actually
in use, so a cloud provider would make the page say what it sends and where, rather than
leaving a reassuring sentence that nobody remembered to edit. A claim about privacy is worth
nothing if it cannot go false.

Any interview can be deleted from that page, and deleting one takes its recordings with it.
It takes two presses rather than a dialog, and the interview currently being conducted is
refused. A product that records your voice and offers no way to remove it has not earned the
sentence above.

## Licence

MIT, in [LICENSE](LICENSE).

That covers the code in this repository and nothing else. The typefaces are under the SIL Open
Font License (`ui/static/fonts/OFL.txt`), and the models, Python packages and runtimes are
downloaded separately, are not redistributed here, and carry their own licences.
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists each one. Three need care before
shipping anything built on this: Parselmouth is GPL-3.0-or-later; sherpa-onnx's binaries contain
espeak-ng, also GPL-3.0-or-later, so the Windows installer carries it with its licence text
([`LICENSES/`](LICENSES)) and the exact sources named in the notices; and LFM3-Audio's licence
does not cover commercial use by organisations with US$10M or more in annual revenue.
