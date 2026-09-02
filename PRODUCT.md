# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is a working software engineer preparing for job interviews, practising
alone, unobserved, on their own machine. Today that is the author; the interface is written
for a stranger because the product is intended to become publicly available later.

They arrive in one of two situations: an interview is scheduled and they want rehearsal
against that specific job description, or none is scheduled and they want to keep the skill
warm. Both are private, self-directed, and slightly uncomfortable -- nobody practises
interviewing because it is enjoyable.

## Product Purpose

Mockingbird conducts a mock interview and then tells the candidate how they answered.

A run has three stages, and they are deliberately separate: build a plan (from a job
description, a stock template, or a hand-written plan), sit the interview, then read a
report. Success is that the candidate finishes with specific, checkable knowledge of how
they answer questions -- not a score, and not encouragement.

## Positioning

Three commitments a neighbouring product could not truthfully copy:

**No assessment reaches the candidate during the interview.** The live channel and the
assessment channel are separate systems. Showing a judgement mid-session is treated as a
correctness bug, not a design preference, because a candidate who learns they are doing
badly stops performing naturally and the rest of the session measures nothing.

**Every question was approved by a human before it could be asked.** The model may propose
questions, but a proposal cannot be asked until it is approved. The interviewer draws only
from curated or approved questions.

**The report shows its work and marks its own limits.** Every strength is quoted in the
candidate's own words; the counting on top of those quotes is arithmetic they can check.
Which words counted as evidence was decided by a model, and the report says so in those
terms rather than presenting a reading as a measurement.

## Operating Context

Everything runs locally. The model is served by LM Studio on the user's own machine, and the
interview never leaves it. This is a privacy constraint the user set deliberately: any cloud
model is an opt-in alternative on a toggle, never a hybrid default.

The reference machine is a laptop with an RTX 3060 6GB. A single decision takes seconds, not
milliseconds, so waiting is a normal part of the interface rather than an error state.

The product is used across laptop, tablet, and phone, at a desk and away from one.

## Capabilities and Constraints

Three surfaces exist today:

- **Plan** -- build an interview from a pasted job description, from a stock template, or
  from a saved plan; review, reorder, edit, add, delete, and approve proposed questions
  before anything is asked.
- **Session** -- the interview itself. One question at a time, typed answers standing in for
  speech. The interviewer acknowledges, probes, clarifies, re-asks, skips, or advances.
- **History** -- past sessions, and the report built from any one of them.

Constraints that shape the interface:

- Extraction and scoring run when the report is built, not during the interview. Building a
  report over a full session takes minutes.
- A single turn takes several seconds. Latency is inherent, not incidental.
- Questions the candidate asks back are recorded and deliberately left unanswered: there is
  no employer behind the interview, and inventing facts about a real workplace is the one
  thing a practice interviewer must not do. They are returned in the report.
- The rubric criteria are fixed and named: sets_context, describes_action, states_outcome,
  first_person, specific_detail, measurement_stated.
- Vocabulary is closed and validated at load: phases, criteria, competencies, question
  shapes, sources, statuses.
- Stack: a Python package that stays standard-library-only, a FastAPI layer, and a SvelteKit
  static SPA. Styling was chosen for this rehaul as CSS custom-property design tokens
  consumed by Svelte's scoped styles.

## Brand Commitments

The name is Mockingbird. Red is the confirmed primary colour, chosen by the user.

The voice of the product is the voice of a competent, courteous interviewer: neutral, never
flattering, never harsh. The interviewer thanks a candidate for the act of explaining and
never for the quality of the answer. The report speaks plainly and refuses to congratulate.

## Evidence on Hand

Real, in the repository: a curated bank of 28 questions across 10 competencies; stock plans
for behavioural, technical, and mixed interviews; ~200 recorded sessions with full
transcripts; generated reports.

There are no customers, no testimonials, no benchmarks against competitors, and no pricing.
None of these may be invented.

## Product Principles

1. **Never assess in the live channel.** Anything that tells the candidate how they are
   doing belongs in the report, and nowhere else.
2. **Show the work, and name what is a reading.** Quote the candidate; make the counting
   checkable; say plainly which parts a model decided.
3. **A human approves every question.** Generation proposes; a person disposes.
4. **Waiting is part of the product.** Seconds per turn and minutes per report are inherent
   to running locally; the interface must make waiting legible rather than hide it.
5. **Local by default.** The interview stays on the machine that ran it.

## Accessibility & Inclusion

No formal standard was set. Confirmed requirement: the product is used on laptop, tablet,
and phone, so layouts, touch targets, and the answer composer must hold up across all three,
including with an on-screen keyboard.
