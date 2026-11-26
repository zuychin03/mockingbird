# Changelog

Every release of Mockingbird. Dates are in Australian Eastern time.

## 1.1.0 - Unreleased

Mockingbird no longer needs an NVIDIA graphics card. The interviewer can run on a cloud provider
with your own API key, answers can be corrected before they are scored, and two interviews can be
compared side by side.

### Added

- Settings can hand the interviewer to a cloud provider: OpenAI, OpenRouter, Google Gemini or
  Groq, through their OpenAI-compatible APIs, with your own key. Settings names what is sent (the
  job description, every question and the text of every answer) and what is not (your
  recordings), and asks you to confirm before anything is sent.
- Cloud models that passed the same measurement as the local model are listed with their
  results: Qwen3.8 27B on Groq's free tier and Gemini 3.5 Flash-Lite on Google's free tier. Any
  other model runs labelled as unmeasured.
- Your API key is encrypted with your Windows login and is never shown again after you save it.
  Uninstalling removes it.
- An interview and its report stay with the provider that held the interview. Scoring it with a
  different provider asks first, twice, and names where its answers would go.
- Cloud interviews show their token use and estimated cost in the interview header and the
  report.
- A first-run setup page finds the graphics card and asks where the interviewer runs before
  anything is downloaded: on this computer (about 5.6 GB), or in the cloud with spoken answers
  (about 2.5 GB) or typed answers (52 MB). Without a suitable card, a short check decides whether
  the processor recognises speech fast enough for spoken answers.
- Four Piper voices join the two LFM3-Audio voices: kristin and norman, trained on public-domain
  recordings, and hfc_female and ryan, trained on recordings licensed for non-commercial use only.
  Settings labels them, previews each one and downloads it on first use. Without a suitable card,
  an LFM3 voice gives way to kristin.
- After a spoken interview, the first report opens with a review of what was heard: each answer
  with its recording, what the recogniser heard and what was sent. Corrected answers are scored,
  the originals are kept beside them, and "Correct a transcript" on the report reopens the review
  later. Exports carry both versions.
- Two interviews can be compared side by side from the history page: each criterion's count,
  each question's answers with what they met and missed, and the delivery measurements.
- Any report exports as Markdown, for notes and documents.
- In cloud mode, the report can show example answers for up to three of the weakest scored
  answers, written by the cloud model from the question, your answer and what it missed. Each is
  labelled as written by the model and is never scored. Facts only you know are left as bracketed
  placeholders rather than invented.
- An interview can be left partway through with Leave in its header. What you answered stays in
  the history page, where it can be scored or deleted, and Settings can change again.
- A Settings page for the interviewer, the voice and speech recognition.
- A release workflow that builds the installer from a version tag and attaches it to a draft
  release.

### Changed

- The interview header names the provider and model that are reading your answers.
- Requests that change anything are refused when they come from another website.
- The installer's file properties name the product, version and publisher.
- When your first answer to a story question says only "we", or says only that it worked with
  no number to show it, the interviewer now asks once about your own part or how it ended,
  where before it could move straight on. It counts as one of that question's follow-ups.

### Fixed

- A word repeated where live mode cut an answer into slices is now kept only once.
- The voice bar no longer says nothing is uploaded when a cloud provider is reading the answers.
- When the app was updated but the old version was still running, pages showed a JSON parse
  error. They now say to restart Mockingbird.
- Reports now include the note on the design question: what you would build, the alternatives,
  the costs and what could go wrong. It was written but never shown, because the design answer
  was read as a story answer.
- Asked at the end what happens to their recording, or how they will get feedback, the
  interviewer now answers. Before, a cloud interviewer said it could not answer, and the local
  one could answer a different question.
- Asked "How will I know how I did?" or "When do I see my results?", the interviewer now says
  the results come in the report. Before, it said it could not answer.
- A question about the job that names the job title, such as what support new nurses get on the
  ward, is now declined. Before, the interviewer could answer it with how many questions the
  interview has.
- When you have already said how a story ended, in words like "they kept the budget" or "no
  incidents since", the interviewer no longer asks what happened in the end.
- A short outcome said as a sentence of its own, such as "They signed anyway.", now counts as
  how the story ended, in the report and during the interview. Before, it was too short to
  count. "It went fine." still does not count.
- On Groq, the interviewer's rewritten follow-up questions were cut off at 128 characters and
  then thrown away, so a stock question was asked instead. Groq now gets room for the whole
  sentence. A rewrite that opens with a remark such as "You mentioned..." before its one
  question is now asked without the remark, rather than thrown away.
- Leaving an interview while an answer was still being read could be undone when that answer
  finished. Leave now waits for the answer, then ends the interview.
- Refreshing the interview page while an answer was being read could bring back the interview as
  it was before that answer. A refresh now only reads the interview.
- Each edit on the plan page wrote a temporary file into the Mockingbird folder to check the
  plan, so editing failed where that folder could not be written to. The plan is now checked
  without a file.
- Once you have said how a story ended, a later "it went well overall" on the same question no
  longer brings a question about what happened in the end.
- A follow-up such as "How did you know it worked?" or "How did you know it was safe to start?"
  is now kept as the interviewer wrote it. Before, it could be swapped for a stock question, or
  counted as asking how the story ended.
- A figure given alongside "we never measured it" now counts as unchecked, so the interviewer can
  ask how you know it.

## 1.0.1 - 2026-11-08

A licence-notice fix. The app works exactly as before.

### Fixed

- The installer ships sherpa-onnx, whose compiled files contain espeak-ng (GPL-3.0-or-later).
  1.0.1 adds the GPL text in the `LICENSES` folder and lists the exact espeak-ng and
  piper-phonemize sources in `THIRD_PARTY_NOTICES.md`. Mockingbird never calls that code, and its
  own code stays MIT.

## 1.0.0 - 2026-11-08

The first release: a Windows installer for a mock software-engineering interview that runs
entirely on your own computer.

### Added

- A structured interview run by Qwen3-4B-Instruct on a 6 GB NVIDIA GPU, through llama.cpp's
  `llama-server`. Python decides when to probe, when to move on and when to end; the model writes
  the next sentence.
- Spoken interviews through LFM3-Audio: the interviewer speaks, and you answer by tapping to talk
  or in live mode, which ends an answer after a pause you choose.
- Plans from a job description or a stock plan, reviewed and approved before anyone is
  interviewed with them.
- Reports in which every criterion quotes what you actually said, with delivery measurements
  from the recording and playback that marks every pause.
- History across interviews, export as one HTML file with the recordings inside or as JSON, and
  deletion of any interview with its recordings.
- A per-user installer that downloads the models on first start, each pinned to an exact
  revision and checked against its SHA-256.
