# Roadmap

What is planned after 1.1, and what is deliberately out of scope. Shipped work is in
[CHANGELOG.md](CHANGELOG.md).

## Next: 1.2

- Interviews for other fields. Data analytics, product management, UX design and project
  management fit the same behavioural scoring. The plan is a shared competency vocabulary mapped
  to O*NET's work activities, a shared behavioural question bank, 10 to 15 curated questions for
  each field's own round, generated questions only to fill behavioural gaps, and criterion weights
  for each field (stating a measurement matters less in some roles). The software-engineering
  prompts stay unchanged, so their measured behaviour holds.

## Planned

- A plan library, after 1.2. Browse every question in the bank for your field and add any of them
  to the plan you are building. Save a plan as a named template (it suggests the job title and
  the date), then revise, rename or reuse your templates from their own page. A template can
  carry notes about the role, so when you ask the interviewer about the team or the job, it
  answers by quoting what you wrote, or says it does not know.
- A larger evaluation: 150 to 250 labelled fixtures with a held-out part and a confusion matrix,
  a decision rule on the model's action probabilities, a small classifier that runs on the
  processor, merging the clarify action into its neighbours, and closing the known gaps on the
  junior plan.
- A provider for each task (the interview, the scoring, the planning), and a native Anthropic
  client.
- Code signing through SignPath's free programme for open-source projects, once the project
  qualifies. Until then Windows SmartScreen warns before the installer runs.
- A Microsoft Store package, the one free way to install without the SmartScreen warning.
- Measuring battery use during an interview on a laptop.

## Considered, not planned

- Cloud speech recognition. It would cost under US$0.20 an interview, but your recordings would
  leave your computer. Recordings stay local in every mode today.
- An IELTS speaking module.
- Hosting for several users. Mockingbird is a single-user app on your own computer.
- Regulated fields and sales role-play. Nursing, finance, law and sales need answer keys or
  role-play rather than behavioural scoring.
