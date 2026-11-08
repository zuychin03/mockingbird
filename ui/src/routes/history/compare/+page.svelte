<script>
  // Two interviews side by side (FR-25), from their reports as each was scored. Nothing here is
  // re-scored, so every number matches the report it came from.
  import { page } from '$app/state';

  import Icon from '$lib/Icon.svelte';
  import Problem from '$lib/Problem.svelte';
  import { refused, unreachable } from '$lib/problem.js';

  let data = $state(null);
  let problem = $state(null);
  let busy = $state(false);

  async function load() {
    const a = page.url.searchParams.get('a');
    const b = page.url.searchParams.get('b');
    problem = null;
    if (!a || !b) {
      problem = refused(400, 'Pick two interviews on the history page to compare them.');
      return;
    }
    busy = true;
    try {
      const res = await fetch(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
      const body = await res.json();
      if (res.ok) data = body;
      else problem = refused(res.status, body.detail);
    } catch (e) {
      problem = unreachable(e);
    }
    busy = false;
  }

  $effect(() => {
    load();
  });

  const SIDES = [
    ['a', 'Earlier'],
    ['b', 'Later']
  ];
  const when = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : 'unknown');
  const dashes = (s) => (s || '').replace(/ -- /g, ' - ');
  const labels = $derived(Object.fromEntries((data?.criteria ?? []).map((c) => [c.name, c.label])));
  const named = (met, want) =>
    Object.entries(met ?? {})
      .filter(([, ok]) => ok === want)
      .map(([k]) => (labels[k] ?? k).toLowerCase())
      .join(', ') || 'none';
  const spoke = $derived(data && (data.delivery.a.spoken || data.delivery.b.spoken));
  const FIGURES = [
    ['spoken', 'Answers measured', (v) => v ?? 0],
    ['articulation_rate', 'Syllables per second', (v) => v ?? '-'],
    ['wpm', 'Words per minute', (v) => (v ? Math.round(v) : '-')],
    ['pause_count', 'Pauses', (v) => v ?? '-'],
    ['mid_clause_share', 'Pauses mid-clause', (v) => (v == null ? '-' : `${Math.round(v * 100)}%`)],
    ['speaking_seconds', 'Seconds speaking', (v) => (v ? Math.round(v) : '-')]
  ];
</script>

<main>
  <span class="sheet-id num" aria-hidden="true">ARCHIVE MB-03 / COMPARISON</span>
  <a class="back" href="/history"><Icon name="back" size={14} /> All interviews</a>

  <div class="lede">
    <h1>Two interviews</h1>
    <p>
      Side by side, as each report scored them. A criterion counts the answers it applied to,
      so the totals can differ when the interviews asked different questions.
    </p>
  </div>

  <Problem {problem} onretry={load} />

  {#if busy}
    <p class="waiting" aria-live="polite">
      Reading both interviews. A report that was never opened is built now, by the model that
      held that interview, which can take a minute.
    </p>
  {/if}

  {#if data}
    {#if data.note}<p class="plan-note">{data.note}</p>{/if}

    <div class="pair heads">
      {#each SIDES as [k, name]}
        <div class="head">
          <span class="slug">{name}</span>
          <h2>{data[k].label}</h2>
          <p class="meta num">
            {when(data[k].started_at)} · {data[k].asked} asked · {data[k].answered} answered ·
            {data[k].scored} scored
          </p>
          {#if data[k].scored_by?.mode === 'cloud'}
            <p class="meta">Scored by {data[k].scored_by.model} on {data[k].scored_by.label}</p>
          {/if}
          {#if data[k].corrected}
            <p class="meta">
              {data[k].corrected} {data[k].corrected === 1 ? 'answer' : 'answers'} corrected before scoring
            </p>
          {/if}
          <a class="open" href="/history?s={data[k].session_id}">Open the report</a>
        </div>
      {/each}
    </div>

    <section aria-labelledby="crit-head">
      <h3 id="crit-head">every criterion</h3>
      <table class="crit">
        <thead>
          <tr><th scope="col">Criterion</th><th scope="col">Earlier</th><th scope="col">Later</th></tr>
        </thead>
        <tbody>
          {#each data.criteria as c (c.name)}
            <tr>
              <th scope="row">{c.label}<span class="desc">{dashes(c.description)}</span></th>
              {#each SIDES as [k, name]}
                <td data-side={name}>
                  {#if c[k]}
                    <span class="marks" aria-hidden="true">
                      {#each { length: c[k].of } as _, i}<span class="tick" class:met={i < c[k].met}></span>{/each}
                    </span>
                    <span class="num count">{c[k].met}<span class="of">/{c[k].of}</span></span>
                  {:else}
                    <span class="none">not scored</span>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </section>

    <section aria-labelledby="q-head">
      <h3 id="q-head">question by question</h3>
      {#each data.questions as q, n (n)}
        <div class="question">
          <p class="asked">{q.question}</p>
          <div class="pair">
            {#each SIDES as [k, name]}
              <div class="side">
                <span class="slug">{name}</span>
                {#if !q[k]}
                  <p class="none">Not asked in this interview.</p>
                {:else if !q[k].answers.length}
                  <p class="none">Not answered.</p>
                {:else}
                  {#each q[k].answers as text}<p class="said">{text}</p>{/each}
                  {#if Object.keys(q[k].met).length}
                    <p class="judged">Met: {named(q[k].met, true)}</p>
                    <p class="judged">Missed: {named(q[k].met, false)}</p>
                  {/if}
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/each}
    </section>

    {#if spoke}
      <section aria-labelledby="d-head">
        <h3 id="d-head">delivery</h3>
        <p class="aside">How the answers were said. Never part of the score.</p>
        <table class="crit figures">
          <thead>
            <tr><th scope="col">Measure</th><th scope="col">Earlier</th><th scope="col">Later</th></tr>
          </thead>
          <tbody>
            {#each FIGURES as [key, label, show]}
              <tr>
                <th scope="row">{label}</th>
                <td class="num" data-side="Earlier">{show(data.delivery.a[key])}</td>
                <td class="num" data-side="Later">{show(data.delivery.b[key])}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}
  {/if}
</main>

<style>
  main {
    position: relative;
    max-width: calc(var(--page) - 4rem);
    margin: var(--s-7) auto var(--s-8);
    padding: var(--s-6) var(--s-5) var(--s-8);
    background: color-mix(in srgb, var(--bg-raised) 97%, transparent);
    border: 1px solid var(--rule-strong);
    box-shadow: var(--shadow);
  }
  .sheet-id {
    position: absolute;
    top: var(--s-3);
    right: var(--s-4);
    color: var(--fg-faint);
    font-size: 0.6rem;
    letter-spacing: 0.08em;
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    font-family: var(--font-structure);
    font-size: var(--step--1);
    color: var(--fg-quiet);
    text-decoration: none;
    padding: 9px 12px 9px 8px;
    margin-left: -8px;
    min-height: 44px;
  }
  .back:hover {
    color: var(--signal);
  }
  .lede {
    padding: var(--s-4) 0 var(--s-5);
    margin-bottom: var(--s-5);
    border-bottom: 2px solid var(--fg);
  }
  .lede h1 {
    font-size: var(--step-4);
  }
  .lede p,
  .waiting,
  .plan-note,
  .aside {
    color: var(--fg-quiet);
    max-width: var(--measure);
    margin-top: var(--s-3);
  }
  .plan-note {
    padding: var(--s-3) var(--s-4);
    border-left: 2px solid var(--review-blue);
    background: color-mix(in srgb, var(--review-blue) 6%, transparent);
    margin: 0 0 var(--s-5);
  }
  .aside {
    font-size: var(--step--1);
    margin: 0 0 var(--s-3);
  }

  .pair {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s-5);
  }
  .heads .head {
    padding-top: var(--s-3);
    border-top: 1px solid var(--rule-strong);
  }
  .slug {
    display: block;
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--review-blue-deep);
  }
  .head h2 {
    font-size: var(--step-2);
    margin-top: var(--s-1);
  }
  .meta {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-1);
  }
  .open {
    display: inline-block;
    margin-top: var(--s-2);
    font-size: var(--step--1);
    color: var(--fg-quiet);
    text-decoration: none;
    border-bottom: 1px solid var(--rule-strong);
  }
  .open:hover,
  .open:focus-visible {
    color: var(--signal);
    border-bottom-color: var(--signal);
  }

  section {
    margin-top: var(--s-7);
  }
  h3 {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--review-blue-deep);
    margin-bottom: var(--s-4);
  }

  .crit {
    width: 100%;
    border-collapse: collapse;
  }
  .crit tr {
    border-bottom: 1px solid var(--rule);
  }
  .crit thead th {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-faint);
    text-align: left;
    padding: 0 var(--s-4) var(--s-2) 0;
  }
  .crit tbody th {
    text-align: left;
    font-family: var(--font-structure);
    font-weight: 500;
    font-size: var(--step--1);
    padding: var(--s-3) var(--s-4) var(--s-3) 0;
  }
  .crit td {
    padding: var(--s-3) var(--s-4) var(--s-3) 0;
    white-space: nowrap;
    width: 22%;
  }
  .desc {
    display: block;
    font-family: var(--font-prose);
    font-weight: 400;
    color: var(--fg-quiet);
    margin-top: 2px;
  }
  .marks {
    display: inline-flex;
    gap: 3px;
    margin-right: var(--s-3);
    vertical-align: -2px;
  }
  .tick {
    width: 6px;
    height: 14px;
    border-radius: 1px;
    background: var(--bg-sunk);
    box-shadow: inset 0 0 0 1px var(--rule-strong);
  }
  .tick.met {
    background: var(--fg);
    box-shadow: none;
  }
  .count {
    font-size: var(--step--1);
  }
  .count .of {
    color: var(--fg-faint);
  }
  .none {
    color: var(--fg-faint);
    font-size: var(--step--1);
  }

  .question {
    padding: var(--s-4) 0;
    border-top: 1px solid var(--rule);
  }
  .question .asked {
    font-family: var(--font-structure);
    font-weight: 600;
    margin-bottom: var(--s-3);
    max-width: var(--measure);
  }
  .side .slug {
    margin-bottom: var(--s-1);
  }
  .said {
    line-height: 1.6;
  }
  .said + .said {
    margin-top: var(--s-2);
  }
  .judged {
    color: var(--fg-faint);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }
  .judged + .judged {
    margin-top: 0;
  }

  @media (max-width: 40rem) {
    main {
      margin: 0;
      padding: var(--s-6) var(--s-4) var(--s-7);
      border-width: 0;
      box-shadow: none;
    }
    .pair {
      grid-template-columns: 1fr;
      gap: var(--s-4);
    }
    .crit thead {
      display: none;
    }
    .crit tr {
      display: grid;
      grid-template-columns: 1fr 1fr;
      padding: var(--s-3) 0;
    }
    .crit tbody th {
      grid-column: 1 / -1;
      padding: 0 0 var(--s-2);
    }
    .crit td {
      width: auto;
      padding: 0;
    }
    .crit td::before {
      content: attr(data-side);
      display: block;
      font-family: var(--font-structure);
      font-size: var(--step--2);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-faint);
    }
  }
</style>
