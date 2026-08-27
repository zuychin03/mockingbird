# Model Experimenting Log

This log records how Mockingbird selected `llama-3.2-3b-instruct` as its sole LLM runtime.
It preserves the measurements that matter to the product decision after the multi-model
profiles and routing code were removed on 27/08/2026.

The conclusion is deliberately narrower than "Llama wins every benchmark". Granite sometimes
scored one fixture higher, and one Granite 4.2 result could not be reproduced later. Llama was
selected because it reached practical accuracy parity while producing substantially better
live interview speech, faster decisions and more reliable conversational behaviour under the
candidate profiles Mockingbird actually serves.

## 1. Decision standard

Model selection used five kinds of evidence:

1. A deterministic 60-case action fixture screen covering `advance`, `probe`, `reask`,
   `clarify`, `skip` and `end`.
2. A 49-case **product** score excluding eleven cases settled deterministically before the
   model can decide them: one candidate-question route and ten stop requests.
3. Fixed 22-turn replays for comparable action quality, family crossings, navigation and
   question coverage.
4. Full adaptive interviews with junior-to-mid and strong candidate answers.
5. Raw-versus-spoken probe audits measuring how often the harness retained, shortened,
   replaced or discarded the model's own wording.

Family crossings were weighted more heavily than mistakes within the same action family.
Ending or skipping incorrectly can lose an interview; an unnecessary probe usually costs one
turn. Live behaviour remained a required gate because two models can tie on isolated fixtures
while pacing a complete interview very differently.

All final comparisons used LM Studio on the target laptop, 8,192-token context, temperature
zero, a fixed seed, parallelism one and disabled model thinking. Power state was recorded
because battery throttling reduced decode from roughly 100+ tokens/s to single digits without
making time-to-first-token look unhealthy.

## 2. Why the original screen was not enough

The original screen scored all 60 cases as if the model controlled them. That misattributed
eleven deterministic harness decisions to the model. The first corrected comparison was:

| Model | Guarded 60-case result | Product result | Product severity |
|---|---:|---:|---:|
| Granite 4.1 3B | 48/60 | 39/49 | 14 |
| Llama 3.2 3B Q4 | 46/60 | 36/49 | 17 |

The apparent lower-severity Llama result on all 60 cases came partly from a stop request that
Python overrides correctly regardless of the model output. After procedural skip detection
was added, Granite reached 40/49 with severity 9 and zero family crossings; Llama reached
37/49 with severity 12.

This produced the first durable experiment rule: report raw, guarded and product scores
separately. A model cannot be credited or penalised for a decision it never controls in the
real runner.

## 3. Harness adaptation and symmetric testing

Reading Llama's errors found three harness gaps:

- An `advance` with `ok=false` was only corrected when the model also wrote an invented
  question. Llama often stayed silent, so the same contradiction escaped the guard.
- Segmented clarification questions such as "Quickly meaning what, a few days? A sprint?"
  were not recognised reliably.
- Several high-precision inability phrases were missing from deterministic `reask` routing.

After those model-independent corrections, Granite improved from 40 to 44 product cases and
Llama from 37 to 45. The larger Llama gain demonstrated that the previous gap was partly a
harness-shape effect.

The first adaptation was still asymmetric, so the advance/`ok` contradiction was then tested
both ways on both models:

| Model | Trust `ok` | Trust `act` | Selected historical profile |
|---|---:|---:|---|
| Granite 4.1 3B | 44/49, severity 5 | **46/49, severity 3** | trust `act` |
| Llama 3.2 3B | **45/49, severity 4** | 43/49, severity 6 | trust `ok` |

Llama marked all ten correct advances with `ok=true`; its incomplete advances were usefully
caught by `ok=false`. Granite's action label was more reliable than that field. This is why
profile-specific testing was necessary during research, and why the final Llama-only runner
now applies the Llama resolution directly instead of retaining a model switch.

On the paired 22-turn replay at this stage, both scored 17/22 with severity 5 and zero family
crossings. Llama completed 8/10 questions with 10 probes and 6 advances; Granite completed
5/10 with 14 probes and 3 advances. This was only one script, but it exposed the coverage and
depth trade-off that isolated fixtures cannot represent.

## 4. Challengers and rejected alternatives

### Yi and prompt copying

Yi copied the first prompt exemplar verbatim on 7/20 measured probes. Removing the exemplar
block raised its opener variety from 0.70 to 1.00 without changing its 48/60 guarded score.
Granite lost three fixtures without the same block. This showed that prompt affordances can
help one model and harm another, but maintaining a multi-model prompt switch was no longer
useful once Llama became the only runtime.

### Quantisation and larger models

One representative cost-and-quality screen produced:

| Model | Product score | Severity | Decode | Resident memory |
|---|---:|---:|---:|---:|
| Granite 4.1 3B Q4 | 40/49 | 9 | 106.3 tok/s | 2,860 MiB |
| OLMo 3 7B Q3 | 39/49 | 10 | 15.9 tok/s | 5,831 MiB |
| Llama 3.2 3B Q4 | 37/49 | 12 | 114.7 tok/s | 3,036 MiB |
| RNJ-1 Q3 | 35/49 | 14 | 22.9 tok/s | 4,884 MiB |
| Llama 3.2 3B Q6 | 34/49 | 15 | 90.9 tok/s | 3,613 MiB |

The 7B challenger was too slow and nearly filled the 6GB GPU. Llama Q6 used more memory,
decoded more slowly and scored below Q4, so higher quantisation precision was not assumed to
mean better product behaviour. Llama 3.2 1B F16 scored only 20/60 guarded with severity 84 and
eleven family crossings while providing no meaningful memory or speed advantage.

Other candidates were rejected for load failure, context ceiling, speed or weaker action
quality. These included IBM PowerMoE, Phi-4 Mini, Mistral 7B, Orca Mini, StableLM Zephyr,
Ling Tiny and related experimental builds. A model that could not load under the actual LM
Studio/llama.cpp runtime was treated as unavailable rather than credited from published data.

### Exaone 3.5 2.4B

Exaone initially looked much weaker because it was screened under the wrong contradiction
resolution. With its measured profile, Q5 reached 45/49 with severity 4, 131.5 tok/s and
2,458 MiB resident memory. Q4 was faster and lighter with similar decisions.

Its complete-interview behaviour was weaker. In matched 22-turn replays, both Q4 and Q5
scored 14/22 with severity 12, one family crossing and only 4/10 questions closed. Its raw
questions were frequently generic, long or unclassifiable, so 67% of probe speech was replaced
by templates in the first audit.

A 15-word cap plus one act-preserving shortening retry produced Exaone's best configuration:
15/22, severity 7, zero crossings, 5/10 questions closed, no over-length spoken probes and 53%
template substitution. The improvement was real, but it still remained behind Llama's live
navigation and required tighter model-specific repair. Later creative-probing work improved
its flexibility but did not close that live gap consistently.

### Hermes 3

Hermes and base Llama tied at 45/49 on the fixtures and behaved very differently in a full
replay:

| Model | Decisions | Severity | Probes : reasks | Questions closed |
|---|---:|---:|---:|---:|
| Llama 3.2 3B | 14/22 | 8 | 11 : 2 | 7/10 |
| Hermes 3 | 12/22 | 10 | 2 : 10 | 8/10 |

Hermes labelled ordinary follow-up questions as `reask`, which records an answered candidate
as having produced no usable answer. Its higher question count was therefore a symptom of
budget exhaustion, not better interviewing. The finetune was rejected despite the fixture tie.

## 5. Granite 4.2 comparison

Granite 4.2 was tested after disabling model thinking in LM Studio and raising its speech cap
to 20 words. A historical fixed screen reached 49/49 with severity zero, but the later matched
screen repeated at 47/49 with severity 2. The fixture hash was unchanged. This variability is
why the final decision does not claim that either model has a stable one-case accuracy lead.

Granite's creative-probing control also exposed a product mismatch with the desired interview
style. The historical classifier-only junior session completed in 23 turns with nine probes,
zero reasks and a 2,570.4 ms decision p90, but retained only 2/17 raw questions (11.8%) and
used templates on 23.5%. It also spoke one compound probe and repeated a focus dimension.

The final matched Granite junior control completed in 21 turns with five probes and one reask.
Its p90 was 2,422.9 ms. It retained 1/12 raw questions (8.3%), used templates on 33.3%, emitted
seven multi-question raw lines and produced four action/question conflicts that the harness
discarded. Granite was efficient in turns, but much of its useful interview speech came from
the deterministic harness rather than from its own generated wording.

## 6. Final Llama 3.2 adaptation

The selected implementation uses `llama-3.2-3b-instruct`, trusts its measured `ok` signal and
enforces a 20-word spoken-question cap with one act-preserving shortening attempt.

The cap was neutral on the paired fixed screen:

| Llama configuration | Raw | Guarded | Product | Severity |
|---|---:|---:|---:|---:|
| Uncapped baseline | 47/60 | 54/60 | 48/49 | 1 |
| 20-word cap | 47/60 | 54/60 | 48/49 | 1 |

The capped run decoded at approximately 114 tok/s while plugged in. In the junior live test,
one 22-word compound question exceeded the cap; shortening failed without preserving a safe
line, so the harness correctly used a focused template instead.

The first junior interview retained 3/9 raw questions (33.3%) and substituted 4/9 (44.4%).
Three narrow question-shaped classifier additions were then derived from actual relevant
Llama output: impact, how-the-candidate-knew, and specific changes made or proposed. Adversarial
negatives ensured those phrases did not match as bare keywords in unrelated sentences.

The repeated junior interview produced:

- all 14 questions completed in 24 turns;
- nine probes, zero reasks and zero invalid decisions;
- six of eight raw questions retained (75.0%);
- one of eight questions templated (12.5%);
- zero multi-question raw probes and zero action conflicts;
- 1,304.1 ms decision p90 over 25 model calls.

Retained questions included:

- "What was the impact of this change on your users?"
- "How did you know that using a single free-text status field would lead to issues with
  automation?"
- "What specific changes would you make to address this inconsistency now?"

The strong-answer control completed all 14 questions in 15 turns with zero probes, zero
reasks and a 1,999.3 ms p90. It passed the no-over-probing gate. No eligible Llama
`advance`-with-invented-question cases appeared in the fresh captures, so the experimental
question-promotion switch was not enabled.

The final paired fixed run was 48/49 for Llama versus 47/49 for Granite 4.2, with decode at
114.4 versus 104.2 tok/s. Because Granite had an older 49/49 result, fixed accuracy is treated
as parity. Llama's decisive advantages were its 75% creative-question retention, lower
template dependence, cleaner single-question speech and lower live decision latency.

## 7. Final decision — 27/08/2026

Mockingbird now supports Llama 3.2 3B Instruct only.

The choice is based on the complete evidence, not a single leaderboard number:

- accuracy was at practical parity with the strongest Granite results;
- Llama produced zero family crossings in the decisive replays;
- its `ok` field was reliable enough to catch incomplete advances;
- its generated questions were shorter, more focused and much more likely to be retained;
- it completed both junior and strong live interviews without invalid decisions;
- it decoded faster on the target laptop;
- it required less model-specific repair than Exaone and did not mislabel answers like Hermes.

The product therefore rejects any loaded LM Studio instance whose exact identifier is not
`llama-3.2-3b-instruct`. Multi-model speech profiles, alias inference, prompt variants and
alternative-model tests were removed. Generic safety remains: consent gates, deterministic
focus selection, raw-versus-spoken provenance, one-question enforcement, directness rewrites,
repetition handling and the act-preserving shortening retry.

## 8. Reproducibility references

Important historical session IDs:

| Purpose | Session ID |
|---|---|
| Four-way Llama replay | `20260826-014148-1662fc` |
| Four-way Hermes replay | `20260826-014239-7853a1` |
| Four-way Exaone Q5 replay | `20260826-014015-759572` |
| Four-way Exaone Q4 replay | `20260826-014103-5bbfcf` |
| Final Llama junior interview | `20260827-031151-e476c5` |
| Final Llama strong-answer control | `20260827-031348-e02e04` |
| Final matched Granite junior control | `20260827-032619-baded5` |

Final local evidence files were generated under `data/calibration/` and `data/sessions/` and
remain intentionally ignored because they include large, machine-specific run artefacts. The
durable values and decision rationale are recorded here; the implementation-specific test and
experiment procedure remains in `LLAMA_ADAPTATION_PLAN.md`.

## 9. Stage 2 probing hardening — 28/08/2026

Two fresh Llama controls validated the 25-word speech profile and the final probing rules.
The junior-to-mid session `20260827-182435-73bff5` completed 14 questions in 25 turns with ten
probes, no reasks, and no invalid action. Nine probes retained model-authored wording and one
used a focus template. Its design question stopped after exactly two follow-ups without using
the shared reserve.

The strong session `20260827-183849-7ba120` completed 14 questions in 18 turns. It asked four
distinct follow-ups on one retrospective answer: scale, measurement, implementation steps,
and the reason for a two-week shadow run. The first three were focus templates and the fourth
retained Llama's wording. Although this exceeded the original three-probe limit, each turn
elicited new evidence. The accepted policy therefore judges extra probes by relevance and
focus distinctness rather than a session-wide numeric ceiling.

Three shared harness defects were closed:

- a design question can no longer extend its displayed two-follow-up cap with the pool;
- the deterministic design-gap question records `CHALLENGE`, preventing a repeated failure
  probe on the next turn;
- a punctuated sentence containing two coordinated interrogative clauses is reduced to its
  first request without changing action, model-call count, or raw provenance.

The live audit also found that an over-cap probe proposal could draw from the pool before the
observation pacer converted it to an unspoken `advance`. Pool charging now occurs after pacing,
so only a dispatched follow-up consumes the reserve. The resulting branch passed all 278
tests plus byte-compilation and whitespace checks before integration.

Two quality opportunities remain outside Stage 2: bounded retention for additional useful raw
questions, and tense-aware probing that does not describe a hypothetical design as something
the candidate already implemented.
