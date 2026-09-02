<script>
  // Every rule about what may be asked lives in the Python domain. This file renders what the
  // API reports and sends back what the reviewer did; it never decides whether something is
  // allowed. When the server refuses, its own sentence is shown, because those sentences were
  // written to explain the reason and a rewrite here would lose it.
  import Icon from '$lib/Icon.svelte';
  import { goto } from '$app/navigation';

  import Problem from '$lib/Problem.svelte';
  import { refused, unreachable } from '$lib/problem.js';

  const STOCK = {
    behavioural: 'How you have worked, told as stories about real situations.',
    mixed: 'Behavioural and technical in one sitting. The usual first round.',
    technical: 'What you have built, changed and measured.'
  };

  let plan = $state(null);
  let problem = $state(null);
  let busy = $state(false);
  // Only "nothing here yet" is an expected refusal; everything else is worth showing.
  let lastStatus = 0;
  let jd = $state('');
  let minutes = $state('');
  let editing = $state(null);
  let adding = $state(null);
  let saved = $state(false);
  let sourceOpen = $state(false);

  async function call(path, options = {}) {
    busy = true;
    problem = null;
    try {
      const res = await fetch(path, {
        headers: { 'content-type': 'application/json' },
        ...options
      });
      const body = await res.json();
      lastStatus = res.status;
      if (!res.ok) {
        problem = refused(res.status, body.detail);
        return null;
      }
      return body;
    } catch (e) {
      lastStatus = 0;
      problem = unreachable(e);
      return null;
    } finally {
      busy = false;
    }
  }

  const send = (path, body, method = 'POST') =>
    call(path, { method, body: JSON.stringify(body) });

  async function load() {
    const got = await call('/api/plan');
    if (got) plan = got;
    else if (lastStatus === 404) problem = null;
  }

  async function apply(promise) {
    const got = await promise;
    if (got) {
      plan = got;
      saved = false;
      sourceOpen = false;
    }
  }

  const nMinutes = () => (minutes.trim() === '' ? null : Number(minutes));

  async function commitEdit() {
    const { phase, index, text } = editing;
    const got = await send(`/api/plan/${phase}/questions/${index}`, { text }, 'PUT');
    if (got) {
      plan = got;
      editing = null;
    }
  }

  async function commitAdd() {
    const { phase, text } = adding;
    const got = await send(`/api/plan/${phase}/questions`, { text });
    if (got) {
      plan = got;
      adding = null;
    }
  }

  async function save(thenRun) {
    // This endpoint answers with a receipt, not a plan. Assigning it to `plan` threw on the
    // next read of `plan.gaps` and froze the page mid-render.
    const got = await send('/api/plan/save', { path: 'data/interview_reviewed.json' });
    if (!got) return;
    saved = true;
    if (thenRun) goto('/session');
  }

  function clock(secs) {
    const m = Math.floor(secs / 60);
    const s = Math.round(secs % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  // The running order is numbered straight through, and each row carries the time the
  // interview is expected to reach when it starts. Both are the sheet's own arithmetic.
  const rows = $derived.by(() => {
    if (!plan) return [];
    const out = [];
    let n = 0;
    let at = 0;
    for (const phase of plan.phases) {
      for (let i = 0; i < phase.questions.length; i++) {
        out.push({ n: ++n, at, phase, index: i, q: phase.questions[i], first: i === 0 });
        at += phase.secs;
      }
    }
    return out;
  });

  const total = $derived(rows.reduce((t, r) => t + r.phase.secs, 0));
  const proposals = $derived(plan?.proposals ?? []);

  $effect(() => {
    load();
  });
</script>

<main>
  <span class="sheet-id num" aria-hidden="true">FORM MB-01 / REVIEW COPY</span>
  <Problem {problem} onretry={load} />

  {#if busy}
    <p class="working" role="status">
      <span class="sweep"><span></span></span>
      Working. Reading a description runs the model on your machine, so it takes a moment.
    </p>
  {/if}

  {#if !plan}
    <div class="lede">
      <div>
        <h1>Build an interview</h1>
        <p>
          Nothing is asked that you have not read first. Start from a job description or a
          standard plan, then edit the running order before anyone sits it.
        </p>
      </div>
      <dl class="assurance">
        <div><dt class="num">01</dt><dd>Draft from evidence</dd></div>
        <div><dt class="num">02</dt><dd>Review every question</dd></div>
        <div><dt class="num">03</dt><dd>Approve before use</dd></div>
      </dl>
    </div>
  {/if}

  {#if !plan || sourceOpen}
    <section class="source">
      <div class="col">
        <label for="jd">From a job description</label>
        <textarea
          id="jd"
          bind:value={jd}
          rows="6"
          placeholder="Paste the description. The competencies it actually evidences become the interview; the ones it only names are dropped."
        ></textarea>
        <button
          class="go"
          disabled={busy || jd.trim().length < 100}
          onclick={() =>
            apply(send('/api/plan/from-description', { text: jd, minutes: nMinutes() }))}
        >
          Read it and plan
        </button>
        {#if jd.trim().length > 0 && jd.trim().length < 100}
          <p class="hint">{100 - jd.trim().length} more characters before there is enough to read.</p>
        {/if}
      </div>

      <div class="col">
        <span class="label">From a standard plan</span>
        <div class="kinds">
          {#each plan?.stock_kinds ?? Object.keys(STOCK) as kind}
            <button
              class="kind"
              disabled={busy}
              onclick={() => apply(send('/api/plan/from-stock', { kind, minutes: nMinutes() }))}
            >
              <span class="kind-name">{kind[0].toUpperCase() + kind.slice(1)}</span>
              <span class="kind-note">{STOCK[kind] ?? ''}</span>
            </button>
          {/each}
        </div>

        <label for="mins" class="spaced">Target length</label>
        <div class="mins">
          <input id="mins" bind:value={minutes} inputmode="numeric" placeholder="e.g. 40" />
          <span class="unit">minutes</span>
        </div>
        <p class="hint">Optional. Left empty, each plan runs at its full length.</p>
      </div>
    </section>
  {/if}

  {#if plan}
    <header class="masthead">
      <div>
        <h1>{plan.label}</h1>
        <p class="meta">
          <span class="num">{rows.length}</span> questions
          <span class="sep">·</span>
          about <span class="num">{Math.round(total / 60)}</span> minutes
          {#if plan.spec}
            <span class="sep">·</span> from a job description
          {/if}
        </p>
      </div>
      <button class="ghost" onclick={() => (sourceOpen = !sourceOpen)}>
        {sourceOpen ? 'Close' : 'Start over'}
      </button>
    </header>

    {#if plan.spec}
      <section class="block">
        <h2>What the description asked for</h2>
        <ul class="reqs">
          {#each plan.spec.requirements as r}
            <li>
              <span class="req-name">{r.name}</span>
              <span class="evidence">{r.evidence}</span>
            </li>
          {/each}
        </ul>
        {#if plan.spec.dropped.length}
          <p class="note">
            Named but not evidenced by the description's own words, so not used:
            {plan.spec.dropped.map((r) => r.name).join(', ')}.
          </p>
        {/if}
      </section>
    {/if}

    {#if plan.gaps.length}
      <section class="block gaps">
        <h2>Not covered by this plan</h2>
        <div class="gap-row">
          {#each plan.gaps as g}
            <button class="gap" disabled={busy} onclick={() => apply(send('/api/proposals', { competency: g }))}>
              <Icon name="add" size={13} />
              {g}
            </button>
          {/each}
        </div>
        <p class="note">
          Ask the model to draft a question for any of these. Nothing it writes can be asked
          until you approve it.
        </p>
      </section>
    {/if}

    <section class="block">
      <div class="order-head">
        <h2>Running order</h2>
        <span class="slug legend">
          <span class="legend-item"><b class="mark scored"></b> scored</span>
          <span class="legend-item"><b class="mark gen"></b> written by the model</span>
        </span>
      </div>

      <ol class="order">
        {#each rows as row (row.phase.id + ':' + row.index)}
          {#if row.first}
            <li class="phase-head">
              <span class="slug">{row.phase.id.replace(/_/g, ' ')}</span>
              {#if row.phase.scored}
                <span class="mark scored" title="Answers here are scored in the report"></span>
              {/if}
              <span class="rule"></span>
              <span class="num phase-dur">{clock(row.phase.secs * row.phase.questions.length)}</span>
            </li>
          {/if}

          <li class="row" class:editing={editing?.phase === row.phase.id && editing?.index === row.index}>
            <span class="num n">{String(row.n).padStart(2, '0')}</span>
            <span class="num at">{clock(row.at)}</span>

            <div class="body">
              {#if editing && editing.phase === row.phase.id && editing.index === row.index}
                <textarea
                  bind:value={editing.text}
                  rows="3"
                  aria-label="Edit question {row.n}"
                ></textarea>
                <div class="ops">
                  <button class="go small" disabled={busy} onclick={commitEdit}>Save question</button>
                  <button class="ghost small" onclick={() => (editing = null)}>Cancel</button>
                </div>
              {:else}
                <p class="q">
                  {row.q.text}
                  {#if row.q.source === 'generated'}<span class="mark gen" title="Written by the model, approved by you"></span>{/if}
                </p>
                {#if row.q.edited_from}
                  <p class="was">Edited. Was: {row.q.edited_from}</p>
                {/if}
              {/if}
            </div>

            <!-- Its own column, not a block under the question: in flow beneath the text these
                 reserved their height whether shown or not, so every editable row stood taller
                 than every structural one and the sheet lost its rhythm. -->
            {#if row.phase.editable && editing?.phase !== row.phase.id}
              <div class="ops cue">
                <button class="op" aria-label="Edit question {row.n}" onclick={() => (editing = { phase: row.phase.id, index: row.index, text: row.q.text })}>
                  <Icon name="edit" size={13} />
                </button>
                <button
                  class="op"
                  aria-label="Move question {row.n} earlier"
                  disabled={busy || row.index === 0}
                  onclick={() => apply(send(`/api/plan/${row.phase.id}/questions/${row.index}/move`, { to: row.index - 1 }))}
                >
                  <Icon name="up" size={13} />
                </button>
                <button
                  class="op"
                  aria-label="Move question {row.n} later"
                  disabled={busy || row.index === row.phase.questions.length - 1}
                  onclick={() => apply(send(`/api/plan/${row.phase.id}/questions/${row.index}/move`, { to: row.index + 1 }))}
                >
                  <Icon name="down" size={13} />
                </button>
                <button
                  class="op danger"
                  aria-label="Remove question {row.n}"
                  disabled={busy}
                  onclick={() => apply(call(`/api/plan/${row.phase.id}/questions/${row.index}`, { method: 'DELETE' }))}
                >
                  <Icon name="remove" size={13} />
                </button>
              </div>
            {/if}
          </li>

          {#if row.index === row.phase.questions.length - 1 && row.phase.editable}
            <li class="add">
              {#if adding && adding.phase === row.phase.id}
                <textarea
                  bind:value={adding.text}
                  rows="3"
                  aria-label="Add a question to {row.phase.id.replace(/_/g, ' ')}"
                  placeholder="Your own question, in your own words."
                ></textarea>
                <div class="ops">
                  <button class="go small" disabled={busy || !adding.text.trim()} onclick={commitAdd}>Add to {row.phase.id.replace(/_/g, ' ')}</button>
                  <button class="ghost small" onclick={() => (adding = null)}>Cancel</button>
                </div>
              {:else}
                <button class="op" onclick={() => (adding = { phase: row.phase.id, text: '' })}>
                  <Icon name="add" size={13} /> Add a question here
                </button>
              {/if}
            </li>
          {/if}
        {/each}
      </ol>
    </section>

    {#if proposals.length}
      <section class="block proposals">
        <h2>Awaiting your approval</h2>
        <p class="note">
          Written by the model. None of these can be asked until you approve it, and approving
          adds it to your bank for later plans too.
        </p>
        {#each proposals as p}
          <div class="proposal">
            <p>{p.text}</p>
            <button class="go small" disabled={busy} onclick={() => apply(send(`/api/proposals/${p.id}/approve`, {}))}>
              <Icon name="check" size={13} /> Approve
            </button>
          </div>
        {/each}
      </section>
    {/if}

    <section class="block finish">
      <h2>Ready when you are</h2>
      <div class="finish-row">
        <button class="go" disabled={busy} onclick={() => save(true)}>
          Save and start the interview
        </button>
        <button disabled={busy} onclick={() => save(false)}>Save only</button>
      </div>
      <p class="note">
        {#if saved}
          Saved. This plan is the one the interview will run.
        {:else}
          Saving keeps this running order for the interview and for later.
        {/if}
      </p>
    </section>
  {/if}
</main>

<style>
  main {
    position: relative;
    max-width: calc(var(--page) - 4rem);
    margin: var(--s-7) auto var(--s-8);
    padding: var(--s-7) var(--s-5) var(--s-8);
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

  .lede {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(15rem, 0.7fr);
    gap: var(--s-7);
    align-items: end;
    margin-bottom: var(--s-7);
    padding: var(--s-5) 0 var(--s-6);
    border-bottom: 2px solid var(--fg);
  }
  .lede h1 {
    font-size: var(--step-4);
    max-width: 12ch;
  }
  .lede p {
    color: var(--fg-quiet);
    font-size: var(--step-1);
    margin-top: var(--s-3);
    max-width: 54ch;
  }
  .assurance {
    margin: 0;
    border-top: 1px solid var(--rule-strong);
  }
  .assurance div {
    display: grid;
    grid-template-columns: 2rem 1fr;
    gap: var(--s-3);
    padding: var(--s-2) 0;
    border-bottom: 1px solid var(--rule);
  }
  .assurance dt {
    color: var(--signal);
    font-size: var(--step--2);
  }
  .assurance dd {
    margin: 0;
    color: var(--fg-quiet);
    font-family: var(--font-structure);
    font-size: var(--step--1);
  }

  .source {
    display: grid;
    grid-template-columns: 1.35fr 1fr;
    gap: var(--s-6);
    padding: 0;
    border: 1px solid var(--rule-strong);
    margin-bottom: var(--s-7);
    background: var(--bg-raised);
  }
  .col {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    padding: var(--s-5);
  }
  .col:first-child {
    border-right: 1px solid var(--rule-strong);
  }
  label {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--fg-quiet);
    margin-bottom: var(--s-3);
  }
  label.spaced {
    margin-top: var(--s-5);
  }
  .kinds {
    display: grid;
    gap: var(--s-2);
    width: 100%;
  }
  .kind {
    display: grid;
    gap: 2px;
    text-align: left;
    padding: var(--s-3) 0;
    background: transparent;
    border-width: 0 0 1px;
    border-color: var(--rule);
  }
  .kind:hover:not(:disabled) {
    border-color: var(--signal);
  }
  .kind-name {
    font-family: var(--font-structure);
    font-weight: 600;
    color: var(--fg);
  }
  .kind-note {
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }
  .mins {
    display: flex;
    align-items: baseline;
    gap: var(--s-3);
  }
  .mins input {
    width: 5.5rem;
    font-family: var(--font-data);
  }
  .unit {
    color: var(--fg-quiet);
    font-size: var(--step--1);
  }
  .hint {
    color: var(--fg-faint);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }

  .working {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-bottom: var(--s-5);
  }
  .sweep {
    display: block;
    flex: none;
    width: 3rem;
    height: 2px;
    background: var(--rule);
    overflow: hidden;
  }
  .sweep span {
    display: block;
    height: 100%;
    width: 40%;
    background: var(--signal);
    animation: sweep 1.5s var(--ease) infinite;
  }
  @keyframes sweep {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(300%);
    }
  }

  button {
    font-family: var(--font-structure);
    font-size: var(--step--1);
    font-weight: 500;
    background: transparent;
    color: var(--fg);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: 10px 15px;
    min-height: 44px;
    cursor: pointer;
    transition: border-color 140ms var(--ease), background 140ms var(--ease), color 140ms var(--ease);
  }
  button:hover:not(:disabled) {
    border-color: var(--fg-quiet);
  }
  button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .go {
    background: var(--signal-fill);
    border-color: var(--signal-fill);
    color: var(--signal-fill-ink);
    font-weight: 600;
    letter-spacing: 0.02em;
    margin-top: var(--s-4);
  }
  .go:hover:not(:disabled) {
    background: var(--signal-fill-hover);
    border-color: var(--signal-fill-hover);
  }
  .go.small {
    margin-top: 0;
  }
  .ghost {
    border-color: transparent;
    color: var(--fg-quiet);
  }
  .ghost:hover:not(:disabled) {
    color: var(--fg);
    border-color: var(--rule-strong);
  }
  .ghost.small {
    font-size: var(--step--1);
  }

  .masthead {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-5) 0 var(--s-4);
    border-top: 4px solid var(--fg);
    border-bottom: 1px solid var(--rule-strong);
  }
  .masthead h1 {
    font-size: var(--step-4);
  }
  .meta {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }
  .meta .num {
    color: var(--fg);
    font-weight: 500;
  }
  .sep {
    padding: 0 var(--s-1);
    color: var(--fg-faint);
  }

  .block {
    margin-top: var(--s-7);
  }
  .block h2 {
    font-size: var(--step--2);
    font-family: var(--font-structure);
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--review-blue-deep);
    margin-bottom: var(--s-4);
  }
  .note {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    max-width: var(--measure);
    margin-top: var(--s-3);
  }

  .reqs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--s-3);
  }
  .reqs li {
    display: grid;
    grid-template-columns: 12rem 1fr;
    gap: var(--s-4);
    padding: var(--s-3) 0;
    border-bottom: 1px solid var(--rule);
  }
  .req-name {
    font-family: var(--font-structure);
    font-weight: 600;
    font-size: var(--step--1);
  }
  .evidence {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    font-style: italic;
  }
  .evidence::before {
    content: '“';
  }
  .evidence::after {
    content: '”';
  }

  .gap-row {
    display: flex;
    gap: var(--s-2);
    flex-wrap: wrap;
  }
  .gap {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    border-style: dashed;
    border-color: color-mix(in srgb, var(--cue-ink) 45%, transparent);
    color: var(--pending);
  }
  .gap:hover:not(:disabled) {
    border-color: var(--pending);
    border-style: solid;
  }

  .order-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s-4);
    flex-wrap: wrap;
  }
  .legend {
    display: flex;
    gap: var(--s-4);
    letter-spacing: 0.06em;
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
  }

  .mark {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
    flex: none;
  }
  .mark.scored {
    background: var(--signal);
  }
  .mark.gen {
    background: var(--pending);
    margin-left: var(--s-2);
    vertical-align: 0.12em;
  }

  .order {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 2px solid var(--fg);
    border-bottom: 1px solid var(--fg);
  }

  .phase-head {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    padding: var(--s-5) var(--s-3) var(--s-2);
    background: color-mix(in srgb, var(--review-blue) 5%, transparent);
  }
  .phase-head .rule {
    flex: 1;
    height: 1px;
    background: var(--rule);
  }
  .phase-dur {
    font-size: var(--step--2);
    color: var(--fg-faint);
  }

  .row {
    display: grid;
    grid-template-columns: 2.25rem 3.25rem minmax(0, 54ch) auto;
    justify-content: start;
    gap: var(--s-3);
    padding: var(--s-3);
    border-bottom: 1px solid var(--rule);
    align-items: baseline;
    transition: background 140ms var(--ease);
  }
  .row:hover,
  .row:focus-within {
    background: color-mix(in srgb, var(--review-blue) 6%, transparent);
  }
  .row .n {
    font-size: var(--step--1);
    font-weight: 500;
    color: var(--signal);
  }
  .row .at {
    font-size: var(--step--2);
    color: var(--fg-faint);
  }
  .q {
    font-size: var(--step-1);
    line-height: 1.45;
    max-width: 54ch;
  }
  .was {
    color: var(--fg-faint);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }

  .ops {
    display: flex;
    gap: var(--s-1);
    flex-wrap: wrap;
    margin-top: var(--s-2);
  }
  .ops.cue {
    margin-top: 0;
    align-self: center;
    flex-wrap: nowrap;
  }
  .op {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    border-color: transparent;
    color: var(--fg-faint);
    padding: 0;
    min-width: 44px;
    min-height: 44px;
    font-size: var(--step--2);
  }
  .op:hover:not(:disabled) {
    color: var(--fg);
    border-color: var(--rule-strong);
  }
  .op.danger:hover:not(:disabled) {
    color: var(--signal);
    border-color: color-mix(in srgb, var(--tally) 45%, transparent);
  }

  /* The controls are quiet until the row is in play, so a fourteen-row sheet reads as a
   * sheet rather than as ninety buttons. They stay reachable by keyboard throughout. */
  .row .ops.cue {
    opacity: 0;
    transition: opacity 140ms var(--ease);
  }
  .row:hover .ops.cue,
  .row:focus-within .ops.cue {
    opacity: 1;
  }
  @media (max-width: 40rem) {
    .row .ops.cue {
      opacity: 1;
    }
  }

  .add {
    padding: var(--s-2) var(--s-3) var(--s-2) calc(2.25rem + 3.25rem + var(--s-3) * 3);
    border-bottom: 1px solid var(--rule);
  }

  .proposal {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-4) 0;
    border-bottom: 1px solid var(--rule);
  }
  .proposal p {
    font-size: var(--step-1);
    max-width: 54ch;
  }
  .proposals {
    border-left: 1px solid var(--pending);
    padding-left: var(--s-4);
  }

  .finish-row {
    display: flex;
    gap: var(--s-3);
    flex-wrap: wrap;
    align-items: center;
  }
  .finish-row .go {
    margin-top: 0;
  }

  .finish {
    padding: var(--s-6);
    border: 1px solid var(--rule-strong);
    border-top: 4px solid var(--signal);
    background: var(--bg-raised);
  }

  @media (max-width: 52rem) {
    .lede {
      grid-template-columns: 1fr;
      gap: var(--s-5);
    }
    .source {
      grid-template-columns: 1fr;
      gap: var(--s-5);
    }
    .col:first-child {
      border-right: 0;
      border-bottom: 1px solid var(--rule-strong);
    }
    .reqs li {
      grid-template-columns: 1fr;
      gap: var(--s-1);
    }
  }

  @media (max-width: 40rem) {
    main {
      margin: 0;
      padding: var(--s-6) var(--s-4) var(--s-8);
      border-width: 0;
      box-shadow: none;
    }
    .row {
      grid-template-columns: 2rem 1fr;
      column-gap: var(--s-2);
    }
    .row .at {
      grid-row: 1;
      grid-column: 2;
      justify-self: end;
    }
    .row .body {
      grid-column: 1 / -1;
      margin-top: var(--s-1);
    }
    .row .ops.cue {
      grid-column: 1 / -1;
      justify-content: flex-start;
      margin-top: var(--s-1);
    }
    .add {
      padding-left: 0;
    }
    .row {
      grid-template-columns: 2rem minmax(0, 1fr);
    }
    .masthead {
      flex-direction: column;
      align-items: flex-start;
    }
    .finish {
      padding: var(--s-5) var(--s-4);
    }
  }
</style>
