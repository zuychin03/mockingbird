<script>
  // What runs the interviewer (V1.1_PLAN P2). Plan 9.5's rules, in the order a person meets
  // them: what is sent and to whom is said before anything can be sent; the key is written
  // here and never shown again; nothing changes while an interview is running.
  import Problem from '$lib/Problem.svelte';
  import { refused, unreachable } from '$lib/problem.js';

  let view = $state(null);
  let problem = $state(null);
  let busy = $state(false);
  let saved = $state('');
  let tested = $state(null);

  let mode = $state('local');
  let vendor = $state('groq');
  let model = $state('');
  let useOther = $state(false);
  let other = $state('');
  let acknowledged = $state(false);
  let keyInput = $state('');

  async function call(path, init = {}) {
    problem = null;
    busy = true;
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
    } finally {
      busy = false;
    }
  }

  function adopt(v) {
    if (!v) return;
    view = v;
    const s = v.settings;
    mode = s.mode;
    vendor = s.vendor ?? v.measured[0]?.vendor ?? v.vendors[0].name;
    const listed = v.measured.filter((m) => m.vendor === vendor).map((m) => m.model);
    useOther = !!s.model && !listed.includes(s.model);
    other = useOther ? s.model : '';
    model = useOther ? '' : (s.model ?? listed[0] ?? '');
    acknowledged = v.ack.current;
  }

  async function load() {
    adopt(await call('/api/settings'));
  }

  const listed = $derived(view ? view.measured.filter((m) => m.vendor === vendor) : []);
  const chosenModel = $derived(useOther ? other.trim() : model);
  const host = $derived(view?.vendors.find((v) => v.name === vendor)?.host ?? '');
  const locked = $derived(!!view?.locked);
  const dirty = $derived.by(() => {
    if (!view) return false;
    const s = view.settings;
    if (mode !== s.mode) return true;
    if (mode === 'local') return false;
    return vendor !== s.vendor || chosenModel !== (s.model ?? '') || acknowledged !== view.ack.current;
  });

  function pickVendor(name) {
    vendor = name;
    const first = view.measured.find((m) => m.vendor === name);
    useOther = !first;
    model = first?.model ?? '';
  }

  async function save() {
    saved = '';
    tested = null;
    const body = { mode };
    if (mode === 'cloud') {
      body.vendor = vendor;
      body.model = chosenModel;
      body.ack_version = acknowledged ? view.ack.version : 0;
    }
    const got = await call('/api/settings', { method: 'PUT', body: JSON.stringify(body) });
    if (got) {
      adopt(got);
      saved = 'Saved. The next interview uses this.';
    }
  }

  async function saveKey() {
    const got = await call('/api/settings/key', {
      method: 'PUT',
      headers: { 'x-mockingbird': '1' },
      body: JSON.stringify({ key: keyInput.trim() })
    });
    if (got) {
      keyInput = '';
      adopt(got);
    }
  }

  async function removeKey() {
    adopt(await call('/api/settings/key', { method: 'DELETE', headers: { 'x-mockingbird': '1' } }));
  }

  async function test() {
    tested = null;
    tested = await call('/api/settings/test', { method: 'POST' });
  }

  // ---- voices (V1.1_PLAN P4)
  let voices = $state(null);
  let playing = $state('');
  let voiceTimer;
  let player;

  async function loadVoices() {
    const got = await call('/api/voices');
    if (!got) return;
    voices = got;
    clearTimeout(voiceTimer);
    if (got.download?.state === 'downloading') voiceTimer = setTimeout(loadVoices, 1000);
  }

  async function chooseVoice(id) {
    const got = await call('/api/settings', { method: 'PUT', body: JSON.stringify({ voice: id }) });
    if (got) {
      adopt(got);
      await loadVoices();
    }
  }

  async function downloadVoice(id) {
    const got = await call(`/api/voices/${encodeURIComponent(id)}/download`, { method: 'POST' });
    if (got) {
      voices = got;
      voiceTimer = setTimeout(loadVoices, 500);
    }
  }

  function preview(id) {
    player?.pause();
    playing = id;
    player = new Audio(`/api/voices/${encodeURIComponent(id)}/preview`);
    player.onended = player.onerror = () => (playing = '');
    player.play().catch(() => (playing = ''));
  }

  const chosenVoice = $derived(voices ? (voices.selected ?? voices.default) : null);
  const voiceName = (id) => voices?.voices.find((v) => v.id === id)?.label ?? id;

  function gateLine(g) {
    if (!g?.fixtures) return '';
    const bar = g.held_out_bar ? `, against a bar of ${g.held_out_bar}` : '';
    return `Measured ${g.date}: fixtures ${g.fixtures}, held-out answers ${g.held_out}${bar}, ` +
      `junior script ${g.junior}. A turn takes about ${g.turn_ms_p50} ms.`;
  }

  $effect(() => {
    load();
    loadVoices();
    return () => {
      clearTimeout(voiceTimer);
      player?.pause();
    };
  });
</script>

<main>
  <span class="sheet-id num" aria-hidden="true">SETTINGS MB-04</span>
  <div class="lede">
    <div>
      <h1>Settings</h1>
      <p>
        What reads your answers and asks the follow-ups. A change takes effect on the next
        interview; one in progress keeps what it started with.
      </p>
    </div>
    <div class="archive-note">
      {#if view}
        <span class="num">
          {view.configured.mode === 'cloud' ? `CLOUD / ${view.configured.label.toUpperCase()}` : 'LOCAL / PRIVATE'}
        </span>
        <p>
          {#if view.configured.mode === 'cloud'}
            The text of each interview goes to <b>{view.configured.host}</b> to be read.
            Recordings stay on this computer.
          {:else}
            Everything runs on this computer, and nothing you say leaves it.
          {/if}
        </p>
      {/if}
    </div>
  </div>

  <Problem {problem} onretry={load} />

  {#if view}
    {#if locked}
      <p class="locked">
        An interview is in progress. Settings can change once it has finished, or once you
        leave it from the <a href="/session">Interview</a> page.
      </p>
    {/if}

    <section aria-labelledby="interviewer">
      <h2 id="interviewer">Interviewer</h2>

      <fieldset class="choice" disabled={locked}>
        <legend class="sr">Where the interviewer runs</legend>
        <label class:on={mode === 'local'}>
          <input type="radio" name="mode" value="local" bind:group={mode} />
          <span>
            <strong>On this computer</strong>
            <small>Qwen3-4B on your NVIDIA GPU. Private, free, and the setup Mockingbird was
              measured on.</small>
          </span>
        </label>
        <label class:on={mode === 'cloud'}>
          <input type="radio" name="mode" value="cloud" bind:group={mode} />
          <span>
            <strong>In the cloud</strong>
            <small>For a computer without a capable GPU. Uses your own API key with a
              provider you choose.</small>
          </span>
        </label>
      </fieldset>

      {#if mode === 'cloud'}
        <div class="cloud">
          <div class="field">
            <label for="vendor">Provider</label>
            <select id="vendor" value={vendor} disabled={locked}
              onchange={(e) => pickVendor(e.currentTarget.value)}>
              {#each view.vendors as v (v.name)}
                <option value={v.name}>{v.label}</option>
              {/each}
            </select>
          </div>

          <fieldset class="models" disabled={locked}>
            <legend>Model</legend>
            {#each listed as m (m.model)}
              <label class:on={!useOther && model === m.model}>
                <input type="radio" name="model" checked={!useOther && model === m.model}
                  onchange={() => { useOther = false; model = m.model; }} />
                <span>
                  <strong>{m.label ?? m.model}</strong>
                  <small>{gateLine(m.gate)}</small>
                  {#if m.free_tier}
                    <small>Free tier: {m.free_tier.requests_per_day.toLocaleString()} requests a
                      day and {m.free_tier.tokens_per_minute.toLocaleString()} tokens a minute,
                      which a normal interview stays within.</small>
                  {/if}
                </span>
              </label>
            {/each}
            <label class:on={useOther}>
              <input type="radio" name="model" checked={useOther}
                onchange={() => (useOther = true)} />
              <span>
                <strong>Another model</strong>
                <small>Unmeasured. Mockingbird's interviewer rules were tested on the models above,
                  so another one may probe, move on and score differently.</small>
              </span>
            </label>
            {#if useOther}
              <input class="mono" bind:value={other} placeholder="model id, as the provider names it"
                spellcheck="false" aria-label="Model id" />
            {/if}
          </fieldset>

          <div class="field">
            <span class="label">API key for {view.vendors.find((v) => v.name === vendor)?.label}</span>
            <p class="key-state">
              {#if view.key.set}
                Set, ending in <span class="num">{view.key.last4 ?? '····'}</span>{#if view.key.source === 'environment'}, from the
                  MOCKINGBIRD_API_KEY environment variable{/if}. It is encrypted to your Windows
                login and never shown again.
              {:else}
                Not set.
              {/if}
            </p>
            <div class="row">
              <input type="password" bind:value={keyInput} autocomplete="off" spellcheck="false"
                placeholder={view.key.set ? 'Replace the key' : 'Paste the key'}
                aria-label="API key" disabled={locked} />
              <button disabled={locked || busy || !keyInput.trim()} onclick={saveKey}>Save key</button>
              {#if view.key.set && view.key.source === 'stored'}
                <button class="ghost" disabled={locked || busy} onclick={removeKey}>Remove</button>
              {/if}
            </div>
          </div>

          <div class="ack" class:current={acknowledged}>
            <p>{view.ack.text}</p>
            <p class="dest">Sent to: <code class="where">{host}</code></p>
            <label>
              <input type="checkbox" bind:checked={acknowledged} disabled={locked} />
              I understand what cloud mode sends.
            </label>
          </div>
        </div>
      {/if}

      <div class="actions">
        <button class="go" disabled={locked || busy || !dirty || (mode === 'cloud' && !chosenModel)}
          onclick={save}>Save</button>
        <button disabled={busy || dirty} onclick={test}>Test the connection</button>
        {#if saved}<span class="saved">{saved}</span>{/if}
        {#if tested}
          <span class="saved">
            {tested.provider.mode === 'cloud'
              ? `${tested.provider.label} answered in ${Math.round(tested.wall_ms)} ms.`
              : 'The model on this computer is running.'}
          </span>
        {/if}
      </div>
    </section>
  {/if}

  {#if voices}
    <section aria-labelledby="voice" class="voice-section">
      <h2 id="voice">Voice</h2>
      <p class="lead">
        The voice that asks the questions. Takes effect on the next interview.
        {#if voices.speaking}
          {voiceName(voices.speaking)} is speaking{voices.fallback ? `, because ${voices.fallback}` : ''}.
        {:else}
          No voice can speak here yet, so questions are shown rather than spoken{voices.fallback ? `: ${voices.fallback}` : ''}.
        {/if}
      </p>
      <fieldset class="models voices" disabled={locked}>
        <legend class="sr">The interviewer's voice</legend>
        {#each voices.voices as v (v.id)}
          {@const dl = voices.download?.id === v.id ? voices.download : null}
          <div class="voice-row" class:on={chosenVoice === v.id} class:off={!v.usable}>
            <label>
              <input type="radio" name="voice" checked={chosenVoice === v.id}
                disabled={locked || !v.usable || !v.installed} onchange={() => chooseVoice(v.id)} />
              <span>
                <strong>{v.label}</strong>
                <small>
                  {v.engine === 'lfm3' ? 'LFM3-Audio' : 'Piper'}, {v.gender}.
                  {#if v.noncommercial}<span class="nc">Non-commercial use only.</span>{/if}
                  {v.licence}.
                </small>
                {#if v.why_not}<small class="why">Unavailable: {v.why_not}.</small>{/if}
              </span>
            </label>
            <div class="voice-actions">
              {#if v.installed}
                <button class="ghost" disabled={!v.usable || playing === v.id} onclick={() => preview(v.id)}>
                  {playing === v.id ? 'Playing' : 'Preview'}
                </button>
              {:else if dl && dl.state === 'downloading'}
                <span class="num dl">{Math.round((100 * dl.got) / (dl.size || 1))}%</span>
              {:else if voices.managed}
                <button disabled={locked || !!(voices.download?.state === 'downloading')}
                  onclick={() => downloadVoice(v.id)}>Download {Math.round((v.size || 0) / 1e6)} MB</button>
              {:else}
                <code class="where">python -m app.download --voice {v.id.split(':')[1]}</code>
              {/if}
              {#if dl?.state === 'failed'}<small class="why">{dl.error}</small>{/if}
            </div>
          </div>
        {/each}
      </fieldset>
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
  .locked {
    color: var(--pending);
    margin-bottom: var(--s-4);
  }
  .locked a {
    color: inherit;
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
  .choice,
  .models {
    display: grid;
    gap: var(--s-2);
    max-width: 44rem;
  }
  .choice label,
  .models label {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--s-3);
    align-items: start;
    padding: var(--s-3) var(--s-4);
    border: 1px solid var(--rule);
    border-radius: var(--r-1);
    cursor: pointer;
  }
  .choice label.on,
  .models label.on {
    border-color: var(--fg-quiet);
    background: var(--bg-sunk);
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
  /* Drawn rather than native: with an ink accent the native unchecked radio rendered as a
     solid dot, darker than the checked one, which reads backwards. */
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
  input[type='radio']:disabled,
  input[type='checkbox']:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  input[type='checkbox'] {
    margin-top: 4px;
    accent-color: var(--fg);
  }

  .cloud {
    display: grid;
    gap: var(--s-5);
    margin-top: var(--s-5);
    padding-left: var(--s-4);
    border-left: 1px solid var(--rule-strong);
    max-width: 44rem;
  }
  .field label,
  .field .label,
  .models legend {
    display: block;
    font-family: var(--font-structure);
    font-weight: 600;
    font-size: var(--step--1);
    margin-bottom: var(--s-2);
  }
  select {
    background: var(--bg-raised);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: 10px 12px;
    min-height: 44px;
  }
  .mono {
    font-family: var(--font-data);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }
  .key-state {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-bottom: var(--s-2);
  }
  .row {
    display: flex;
    gap: var(--s-2);
    flex-wrap: wrap;
  }
  input[type='password'] {
    flex: 1 1 16rem;
    background: var(--bg-raised);
    color: var(--fg);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: var(--s-3);
    font-family: var(--font-data);
  }

  .ack {
    padding: var(--s-4);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    background: var(--bg-sunk);
  }
  .ack p {
    max-width: var(--measure);
  }
  .ack .dest {
    margin-top: var(--s-2);
    color: var(--fg-quiet);
    font-size: var(--step--1);
  }
  .ack label {
    display: flex;
    gap: var(--s-2);
    align-items: flex-start;
    margin-top: var(--s-3);
    font-family: var(--font-structure);
    font-weight: 600;
    cursor: pointer;
  }
  .where {
    font-family: var(--font-data);
    font-size: var(--step--2);
    overflow-wrap: anywhere;
  }

  .actions {
    display: flex;
    gap: var(--s-3);
    align-items: center;
    flex-wrap: wrap;
    margin-top: var(--s-6);
  }
  button {
    font-family: var(--font-structure);
    font-size: var(--step--1);
    font-weight: 500;
    background: transparent;
    color: var(--fg);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: 10px 14px;
    min-height: 44px;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .go {
    background: var(--signal-fill);
    border-color: var(--signal-fill);
    color: var(--signal-fill-ink);
    font-weight: 600;
  }
  .go:hover:not(:disabled) {
    background: var(--signal-fill-hover);
    border-color: var(--signal-fill-hover);
  }
  .ghost {
    border-color: transparent;
    color: var(--fg-quiet);
  }
  .saved {
    color: var(--fg-quiet);
    font-size: var(--step--1);
  }

  .voice-section {
    margin-top: var(--s-7);
    padding-top: var(--s-5);
    border-top: 1px solid var(--rule-strong);
  }
  .lead {
    color: var(--fg-quiet);
    max-width: var(--measure);
    margin-bottom: var(--s-4);
  }
  .voice-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--s-3);
    align-items: center;
    border: 1px solid var(--rule);
    border-radius: var(--r-1);
    padding-right: var(--s-3);
  }
  .voice-row.on {
    border-color: var(--fg-quiet);
    background: var(--bg-sunk);
  }
  .voice-row.off {
    opacity: 0.6;
  }
  .voice-row label {
    border: 0;
    background: transparent;
  }
  .voice-actions {
    display: flex;
    align-items: center;
    gap: var(--s-2);
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .nc {
    color: var(--pending);
    font-weight: 600;
  }
  .why {
    color: var(--pending);
  }
  .dl {
    color: var(--fg-quiet);
    font-size: var(--step--1);
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
    .cloud {
      padding-left: var(--s-3);
    }
  }
</style>
