<script>
  // Every rule about what may be asked lives in the Python domain. This file renders what the
  // API reports and sends back what the reviewer did; it never decides whether something is
  // allowed. When the server refuses, its own sentence is shown, because those sentences were
  // written to explain the reason and a rewrite here would lose it.
  let plan = $state(null);
  let error = $state('');
  let busy = $state(false);
  let jd = $state('');
  let minutes = $state('');
  let editing = $state(null); // {phase, index, text}
  let adding = $state(null); // {phase, text}

  async function call(path, options = {}) {
    busy = true;
    error = '';
    try {
      const res = await fetch(path, {
        headers: { 'content-type': 'application/json' },
        ...options
      });
      const body = await res.json();
      if (!res.ok) {
        error = body.detail ?? 'something went wrong';
        return null;
      }
      return body;
    } catch (e) {
      error = String(e);
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
    else error = '';
  }

  async function apply(promise) {
    const got = await promise;
    if (got) plan = got;
  }

  const nMinutes = () => (minutes.trim() === '' ? null : Number(minutes));

  function startEdit(phase, index, text) {
    editing = { phase, index, text };
  }

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

  $effect(() => {
    load();
  });
</script>

<main>
  <h1>Mockingbird</h1>
  <p class="sub">Plan an interview, then read it before anyone is interviewed with it.</p>

  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}

  <section class="start">
    <div>
      <label for="jd">From a job description</label>
      <textarea id="jd" bind:value={jd} rows="4"
        placeholder="Paste the description here"></textarea>
      <button disabled={busy || jd.trim().length < 100}
        onclick={() => apply(send('/api/plan/from-description', { text: jd, minutes: nMinutes() }))}>
        Read it and plan
      </button>
    </div>
    <div>
      <label for="mins">Or a stock plan</label>
      <div class="row">
        {#each plan?.stock_kinds ?? ['behavioural', 'mixed', 'technical'] as kind}
          <button disabled={busy}
            onclick={() => apply(send('/api/plan/from-stock', { kind, minutes: nMinutes() }))}>
            {kind}
          </button>
        {/each}
      </div>
      <label for="mins" class="small">Target length, minutes (optional)</label>
      <input id="mins" bind:value={minutes} inputmode="numeric" placeholder="e.g. 40" />
    </div>
  </section>

  {#if plan}
    <h2>{plan.label}</h2>

    {#if plan.spec}
      <details open>
        <summary>What the description asked for</summary>
        <ul class="reqs">
          {#each plan.spec.requirements as r}
            <li><b>{r.name}</b> <span class="quote">{r.evidence}</span></li>
          {/each}
        </ul>
        {#if plan.spec.dropped.length}
          <p class="note">
            Named but not supported by the description's own words, so not used:
            {plan.spec.dropped.map((r) => r.name).join(', ')}
          </p>
        {/if}
      </details>
    {/if}

    {#if plan.gaps.length}
      <p class="gaps">
        Not covered by this plan: <b>{plan.gaps.join(', ')}</b>
        {#each plan.gaps as g}
          <button class="link" disabled={busy}
            onclick={() => apply(send('/api/proposals', { competency: g }))}>
            write one for {g}
          </button>
        {/each}
      </p>
    {/if}

    {#each plan.phases as phase}
      <section class="phase">
        <h3>
          {phase.id}
          {#if !phase.editable}<span class="tag">structural</span>{/if}
          {#if phase.scored}<span class="tag scored">scored</span>{/if}
        </h3>
        <ol>
          {#each phase.questions as q, i}
            <li>
              {#if editing && editing.phase === phase.id && editing.index === i}
                <textarea bind:value={editing.text} rows="2"></textarea>
                <button disabled={busy} onclick={commitEdit}>save</button>
                <button class="link" onclick={() => (editing = null)}>cancel</button>
              {:else}
                <span>{q.text}</span>
                {#if q.source === 'generated'}<span class="tag gen">generated</span>{/if}
                {#if q.edited_from}
                  <div class="was">edited, was: {q.edited_from}</div>
                {/if}
                {#if phase.editable}
                  <div class="ops">
                    <button class="link" onclick={() => startEdit(phase.id, i, q.text)}>edit</button>
                    <button class="link" disabled={busy || i === 0}
                      onclick={() => apply(send(`/api/plan/${phase.id}/questions/${i}/move`, { to: i - 1 }))}>up</button>
                    <button class="link" disabled={busy || i === phase.questions.length - 1}
                      onclick={() => apply(send(`/api/plan/${phase.id}/questions/${i}/move`, { to: i + 1 }))}>down</button>
                    <button class="link danger" disabled={busy}
                      onclick={() => apply(call(`/api/plan/${phase.id}/questions/${i}`, { method: 'DELETE' }))}>delete</button>
                  </div>
                {/if}
              {/if}
            </li>
          {/each}
        </ol>
        {#if phase.editable}
          {#if adding && adding.phase === phase.id}
            <textarea bind:value={adding.text} rows="2" placeholder="Your own question"></textarea>
            <button disabled={busy} onclick={commitAdd}>add</button>
            <button class="link" onclick={() => (adding = null)}>cancel</button>
          {:else}
            <button class="link" onclick={() => (adding = { phase: phase.id, text: '' })}>
              add a question
            </button>
          {/if}
        {/if}
      </section>
    {/each}

    {#if plan.proposals.length}
      <section class="proposals">
        <h3>Proposed</h3>
        <p class="note">
          Written by the model. None of these can be asked until you approve it.
        </p>
        {#each plan.proposals as p}
          <div class="proposal">
            <span>{p.text}</span>
            <button disabled={busy}
              onclick={() => apply(send(`/api/proposals/${p.id}/approve`, {}))}>approve</button>
          </div>
        {/each}
      </section>
    {/if}

    <section class="save">
      <button disabled={busy}
        onclick={() => apply(send('/api/plan/save', { path: 'data/interview_reviewed.json' }))}>
        Save to data/interview_reviewed.json
      </button>
    </section>
  {/if}
</main>

<style>
  :global(body) {
    margin: 0;
    background: #14161a;
    color: #e6e6e6;
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, sans-serif;
  }
  main { max-width: 60rem; margin: 0 auto; padding: 2rem 1.25rem 6rem; }
  h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.01em; }
  .sub { color: #9aa3ad; margin: 0.25rem 0 1.5rem; }
  h2 { font-size: 1.2rem; margin: 2rem 0 0.5rem; }
  h3 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em;
       color: #9aa3ad; margin: 1.5rem 0 0.4rem; }
  .start { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;
           border: 1px solid #262b33; border-radius: 8px; padding: 1rem; }
  @media (max-width: 40rem) { .start { grid-template-columns: 1fr; } }
  label { display: block; font-size: 0.85rem; color: #9aa3ad; margin-bottom: 0.35rem; }
  label.small { margin-top: 0.75rem; }
  textarea, input {
    width: 100%; box-sizing: border-box; background: #0f1115; color: #e6e6e6;
    border: 1px solid #2c323b; border-radius: 6px; padding: 0.5rem; font: inherit;
  }
  button {
    background: #232a33; color: #e6e6e6; border: 1px solid #333b46; border-radius: 6px;
    padding: 0.4rem 0.7rem; font: inherit; cursor: pointer; margin-top: 0.5rem;
  }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  button.link { background: none; border: none; color: #7aa2f7; padding: 0 0.4rem 0 0; }
  button.link.danger { color: #f07178; }
  .row { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .phase ol { margin: 0; padding-left: 1.3rem; }
  .phase li { margin-bottom: 0.6rem; }
  .ops { margin-top: 0.15rem; }
  .tag { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
         border: 1px solid #3a4250; border-radius: 999px; padding: 0 0.45rem;
         color: #9aa3ad; margin-left: 0.4rem; }
  .tag.scored { border-color: #2f5d4a; color: #7fd1a8; }
  .tag.gen { border-color: #5d4a2f; color: #d1a87f; }
  .was { font-size: 0.85rem; color: #7d8590; }
  .quote { color: #9aa3ad; }
  .reqs { margin: 0.4rem 0; padding-left: 1.1rem; }
  .note, .gaps { color: #9aa3ad; font-size: 0.9rem; }
  .gaps b { color: #e6c07b; }
  .error { background: #3a1f22; border: 1px solid #6b2b31; color: #ffb4b4;
           padding: 0.6rem 0.8rem; border-radius: 6px; }
  .proposal { display: flex; gap: 0.75rem; align-items: baseline;
              border: 1px dashed #4a4030; border-radius: 6px; padding: 0.5rem 0.7rem;
              margin-bottom: 0.5rem; }
  .save { margin-top: 2rem; }
</style>
