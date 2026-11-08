<script>
  // First run (V1.1_PLAN P3): where the interviewer runs, chosen before anything downloads,
  // then the download and start-up shown as they happen. An install that has already chosen
  // lands here only if someone opens the address, and sees its progress.
  import Problem from '$lib/Problem.svelte';
  import { refused, unreachable } from '$lib/problem.js';

  let view = $state(null);
  let problem = $state(null);
  let busy = $state(false);
  let mode = $state('');
  let hearing = $state(true);
  let timer;

  const ACTIVE = ['downloading', 'starting', 'checking'];

  async function call(path, init = {}) {
    problem = null;
    try {
      const res = await fetch(path, {
        ...init,
        headers: { 'content-type': 'application/json', ...(init.headers || {}) }
      });
      const body = await res.json();
      if (!res.ok) {
        problem = refused(res.status, body.detail);
        return null;
      }
      return body;
    } catch (e) {
      problem = unreachable(e);
      return null;
    }
  }

  async function load() {
    const got = await call('/api/setup');
    if (!got) return;
    view = got;
    if (!mode) mode = got.hardware.can_run_local ? 'local' : 'cloud';
    clearTimeout(timer);
    if (got.managed && ACTIVE.includes(got.status?.phase)) timer = setTimeout(load, 1000);
  }

  async function choose() {
    busy = true;
    const got = await call('/api/setup', {
      method: 'POST',
      body: JSON.stringify({ mode, hearing: mode === 'local' ? true : hearing })
    });
    busy = false;
    if (got) {
      view = got;
      timer = setTimeout(load, 500);
    }
  }

  const size = (n) =>
    n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : 'nothing';
  const status = $derived(view?.status ?? null);
  const phase = $derived(status?.phase ?? 'idle');
  const choosing = $derived(view?.managed && !view.set_up && phase === 'idle');
  const gpu = $derived(view?.hardware?.gpu ?? null);
  const PHASES = {
    downloading: 'Downloading. Each file is checked against a fixed checksum before it is used.',
    starting: 'Starting the model servers.',
    checking: 'Checking how fast this computer recognises speech.',
    ready: 'Ready.',
    failed: 'Setup stopped.'
  };

  $effect(() => {
    load();
    return () => clearTimeout(timer);
  });
</script>

<main>
  <span class="sheet-id num" aria-hidden="true">SETUP MB-00</span>
  <div class="lede">
    <div>
      <h1>Set up Mockingbird</h1>
      <p>
        Choose where the interviewer runs. Nothing is downloaded until you choose, and you can
        change it later in Settings.
      </p>
    </div>
    <div class="archive-note">
      {#if view}
        <span class="num">{gpu ? 'GPU FOUND' : 'NO NVIDIA GPU'}</span>
        <p>
          {#if gpu}
            {gpu.name}, {(gpu.memory_mib / 1024).toFixed(0)} GB.
            {view.hardware.can_run_local ? 'Enough to run the interviewer here.' : 'Not enough for the interviewer, which needs 6 GB.'}
          {:else}
            {view.hardware.forced_cpu ? 'Treated as having none, for testing.' : 'The interviewer will need a cloud provider.'}
          {/if}
        </p>
      {/if}
    </div>
  </div>

  <Problem {problem} onretry={load} />

  {#if view && !view.managed}
    <section>
      <h2>Running from source</h2>
      <p class="note">
        This copy was started by hand, so it fetches and starts nothing itself. Fetch the models
        with <code>python -m app.download</code> and start them with
        <code>python -m app.servers</code>; cloud mode is chosen in <a href="/settings">Settings</a>.
      </p>
    </section>
  {:else if choosing}
    <section aria-labelledby="where">
      <h2 id="where">Where the interviewer runs</h2>
      <fieldset class="choice">
        <legend class="sr">Where the interviewer runs</legend>
        <label class:on={mode === 'local'} class:off={!view.hardware.can_run_local}>
          <input type="radio" name="mode" value="local" bind:group={mode}
            disabled={!view.hardware.can_run_local} />
          <span>
            <strong>On this computer</strong>
            <small>Qwen3-4B and the voice on your NVIDIA GPU. Private and free; nothing you say
              leaves this computer. Downloads {size(view.sizes.local)} once.</small>
            {#if !view.hardware.can_run_local}
              <small class="why">Needs an NVIDIA GPU with 6 GB of memory.</small>
            {/if}
          </span>
        </label>
        <label class:on={mode === 'cloud'}>
          <input type="radio" name="mode" value="cloud" bind:group={mode} />
          <span>
            <strong>In the cloud</strong>
            <small>A provider you choose, with your own API key; Groq's free tier works. The text
              of each interview is sent to it to be read, and your recordings stay here.</small>
          </span>
        </label>
      </fieldset>

      {#if mode === 'cloud'}
        <fieldset class="choice sub">
          <legend>Your answers</legend>
          <label class:on={hearing}>
            <input type="radio" name="hearing" checked={hearing} onchange={() => (hearing = true)} />
            <span>
              <strong>Speak them</strong>
              <small>{gpu && gpu.memory_mib >= 3000
                ? `Recognised on your GPU, which also speaks the questions. Downloads ${size(view.sizes.cloud_spoken)}.`
                : `Recognised on this computer's processor. Downloads ${size(view.sizes.cloud_spoken)}, then a short check decides whether it is fast enough; if not, answers are typed.`}</small>
            </span>
          </label>
          <label class:on={!hearing}>
            <input type="radio" name="hearing" checked={!hearing} onchange={() => (hearing = false)} />
            <span>
              <strong>Type them</strong>
              <small>Downloads {size(view.sizes.cloud_typed)}.</small>
            </span>
          </label>
        </fieldset>
      {/if}

      <div class="actions">
        <button class="go" disabled={busy || !mode} onclick={choose}>Set up</button>
      </div>
    </section>
  {:else if view}
    <section aria-live="polite">
      <h2>{view.settings?.mode === 'cloud' ? 'Getting cloud mode ready' : 'Getting ready'}</h2>
      <p class="phase" class:failed={phase === 'failed'}>{PHASES[phase] ?? 'Waiting.'}</p>

      {#if status.items.length}
        <ul class="items">
          {#each status.items as item (item.name)}
            <li class={item.state}>
              <span class="name">{item.name}</span>
              <span class="num amount">{item.state === 'done' ? 'done' : item.state === 'failed' ? 'failed' : `${size(item.got)} of ${size(item.size)}`}</span>
              <span class="bar"><span style="--p: {item.size ? item.got / item.size : 0}"></span></span>
            </li>
          {/each}
        </ul>
      {/if}

      {#if status.error}<p class="error">{status.error}</p>{/if}
      {#each status.warnings as w}<p class="note">{w}</p>{/each}

      {#if phase === 'ready'}
        {#if status.hearing_speed !== null && status.hearing_speed !== undefined}
          <p class="note">
            This computer recognised speech at {status.hearing_speed.toFixed(1)}x real time:
            {status.hearing_speed >= 1.5 ? 'fast enough to speak your answers.' : 'too slow for spoken answers, so they are typed.'}
          </p>
        {/if}
        <div class="actions">
          {#if view.settings?.mode === 'cloud'}
            <a class="go" href="/settings">Next: your provider and API key</a>
          {:else}
            <a class="go" href="/">Plan an interview</a>
          {/if}
        </div>
      {/if}
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
    padding: var(--s-5) 0 var(--s-6);
    margin-bottom: var(--s-6);
    border-bottom: 2px solid var(--fg);
  }
  .lede h1 {
    font-size: var(--step-4);
  }
  .lede p {
    color: var(--fg-quiet);
    margin-top: var(--s-3);
    max-width: var(--measure);
  }
  .archive-note {
    padding-top: var(--s-3);
    border-top: 1px solid var(--rule-strong);
  }
  .archive-note span {
    display: block;
    color: var(--fg-quiet);
    font-size: var(--step--2);
    letter-spacing: 0.08em;
    margin-bottom: var(--s-2);
  }
  .archive-note p {
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }
  section h2 {
    font-size: var(--step-2);
    margin-bottom: var(--s-4);
  }
  .note {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-3);
    max-width: var(--measure);
  }
  .note a {
    color: var(--signal);
  }

  fieldset {
    border: 0;
    padding: 0;
    margin: 0;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .choice {
    display: grid;
    gap: var(--s-2);
    max-width: 44rem;
  }
  .choice.sub {
    margin-top: var(--s-5);
    padding-left: var(--s-4);
    border-left: 1px solid var(--rule-strong);
  }
  .choice.sub legend {
    font-family: var(--font-structure);
    font-weight: 600;
    font-size: var(--step--1);
    margin-bottom: var(--s-2);
  }
  .choice label {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--s-3);
    align-items: start;
    padding: var(--s-3) var(--s-4);
    border: 1px solid var(--rule);
    border-radius: var(--r-1);
    cursor: pointer;
  }
  .choice label.on {
    border-color: var(--fg-quiet);
    background: var(--bg-sunk);
  }
  .choice label.off {
    cursor: not-allowed;
    opacity: 0.6;
  }
  label strong {
    display: block;
    font-family: var(--font-structure);
    font-weight: 600;
  }
  label small {
    display: block;
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: 2px;
  }
  label small.why {
    color: var(--pending);
  }
  input[type='radio'] {
    appearance: none;
    width: 16px;
    height: 16px;
    margin: 3px 0 0;
    border: 1.5px solid var(--fg-faint);
    border-radius: 50%;
    background: var(--bg-raised);
    display: grid;
    place-content: center;
    cursor: pointer;
  }
  input[type='radio']::before {
    content: '';
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--fg);
    transform: scale(0);
    transition: transform 120ms var(--ease);
  }
  input[type='radio']:checked {
    border-color: var(--fg);
  }
  input[type='radio']:checked::before {
    transform: scale(1);
  }
  input[type='radio']:disabled {
    cursor: not-allowed;
  }

  .phase {
    color: var(--fg-quiet);
  }
  .phase.failed,
  .error {
    color: var(--signal);
  }
  .items {
    list-style: none;
    padding: 0;
    margin: var(--s-4) 0 0;
    display: grid;
    gap: var(--s-3);
    max-width: 44rem;
  }
  .items li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--s-1) var(--s-3);
    font-size: var(--step--1);
  }
  .items .amount {
    color: var(--fg-quiet);
  }
  .items .bar {
    grid-column: 1 / -1;
    height: 3px;
    background: var(--bg-sunk);
  }
  .items .bar span {
    display: block;
    height: 100%;
    width: calc(var(--p) * 100%);
    background: var(--fg-quiet);
    transition: width 400ms var(--ease);
  }
  .items li.done .bar span {
    background: var(--fg);
  }
  .items li.failed .amount {
    color: var(--signal);
  }

  .actions {
    display: flex;
    gap: var(--s-3);
    margin-top: var(--s-6);
  }
  .go {
    display: inline-flex;
    align-items: center;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    font-weight: 600;
    background: var(--signal-fill);
    border: 1px solid var(--signal-fill);
    color: var(--signal-fill-ink);
    border-radius: var(--r-1);
    padding: 10px 14px;
    min-height: 44px;
    cursor: pointer;
    text-decoration: none;
  }
  .go:hover:not(:disabled) {
    background: var(--signal-fill-hover);
    border-color: var(--signal-fill-hover);
  }
  .go:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  @media (max-width: 40rem) {
    main {
      margin: 0;
      padding: var(--s-6) var(--s-4) var(--s-7);
      border-width: 0;
      box-shadow: none;
    }
    .lede {
      grid-template-columns: 1fr;
      gap: var(--s-4);
    }
  }
</style>
