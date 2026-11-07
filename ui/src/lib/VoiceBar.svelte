<script>
  /* The voice control strip. One state indicator, one talk control, one captions toggle.
   *
   * 12.4: the indicator and the control are the same object, and the amplitude form is the
   * highest-value affordance here because it is what tells you the microphone is alive while
   * you are being quiet. It never appears alone -- every state carries a text label, which is
   * also the aria-live target, because colour and motion both fail for the people who most
   * need to know what the room is doing (12.8).
   *
   * "Type instead" is not in this component and that is deliberate: 12.6 makes it peer-level
   * and always visible, so it stays in the composer below rather than becoming a fallback this
   * bar can hide.
   */
  import Icon from '$lib/Icon.svelte';
  import {
    voice,
    LABELS,
    PAUSES,
    enable,
    toggleTalking,
    toggleCaptions,
    setLive,
    setPause
  } from '$lib/audio/voice.svelte.js';

  // Only the talk control waits on the API. Switching voice *on* during a routine fetch is
  // harmless, and gating it on `busy` made the button silently swallow the first click while
  // the session was still loading.
  let { busy = false } = $props();

  let still = $state(false);
  let elapsed = $state(0);
  let asking = $state(false);

  $effect(() => {
    const q = matchMedia('(prefers-reduced-motion: reduce)');
    const read = () => (still = q.matches);
    read();
    q.addEventListener('change', read);
    return () => q.removeEventListener('change', read);
  });

  // 12.5: the thinking state always carries an elapsed indicator. Silence with no indicator is
  // what makes people talk over the agent.
  $effect(() => {
    if (!voice.thinkingSince) return;
    const tick = () => (elapsed = (Date.now() - voice.thinkingSince) / 1000);
    tick();
    const id = setInterval(tick, 200);
    return () => clearInterval(id);
  });

  async function turnOn() {
    asking = true;
    await enable();
    asking = false;
  }

  const talking = $derived(voice.phase === 'listening' || voice.phase === 'tail');
  const label = $derived(LABELS[voice.phase] ?? '');
</script>

<div class="voice" class:on={voice.phase !== 'off'} data-phase={voice.phase}>
  {#if voice.phase === 'off'}
    <div class="invite">
      <p>
        <b>Answer out loud.</b> The interviewer will speak its questions and your answer is
        recorded on this machine. Nothing is uploaded, and switching this on asks the browser for
        the microphone.
      </p>
      <button class="go" onclick={turnOn} disabled={asking}>
        <Icon name="mic" size={14} />
        {asking ? 'Asking the browser' : 'Turn on voice'}
      </button>
    </div>
    {#if voice.error}
      <!-- The likeliest failure of all -- a refused permission -- happens while the phase is
           still `off`, so an error rendered only in the other branch can never be seen. -->
      <p class="err" role="alert">{voice.error}</p>
    {/if}
  {:else}
    <div class="strip">
      <div class="meter" aria-hidden="true">
        {#if still || voice.phase !== 'listening'}
          <span class="chip" class:hot={voice.phase === 'listening'}></span>
        {:else}
          {#each voice.bars as b, i (i)}
            <span class="bar" style="--h: {Math.max(0.06, b)}"></span>
          {/each}
        {/if}
      </div>

      <p class="state" aria-live="polite">
        {label}{#if voice.phase === 'thinking'}<span class="num">{' '}{elapsed.toFixed(0)}s</span
          >{/if}
      </p>

      {#if talking}
        <span class="rec"><span class="lamp"></span>REC</span>
      {/if}

      <button
        class="cc"
        onclick={toggleCaptions}
        aria-pressed={voice.captionsOn}
        title="Captions for the interviewer's speech"
      >
        <Icon name="sound" size={14} />
        <span class="cc-text">Captions {voice.captionsOn ? 'on' : 'off'}</span>
      </button>
    </div>

    {#if voice.captionsOn && (voice.caption || voice.interrupted)}
      <p class="caption" aria-live="polite">
        {#if voice.interrupted}
          <!-- The separator is an explicit expression: leading whitespace inside an element is
               trimmed, which ran the heard words straight into the struck-through ones. -->
          {voice.interrupted.heard}{' '}<span class="unsaid">{voice.interrupted.unheard}</span>
          <span class="marker">(interrupted)</span>
        {:else}
          {voice.caption}
        {/if}
      </p>
    {/if}

    {#if voice.partial}
      <!-- Append-only: the server commits whole slices and never revises one, so read text
           never reflows under the eye (12.4). It stays editable below -- 12.6 makes correcting
           it a fairness requirement, not a convenience. -->
      <p class="heard" class:settling={voice.phase === 'reading'}>{voice.partial}</p>
    {/if}

    {#if voice.recorded && !voice.asrReady}
      <p class="recorded">
        Recorded {voice.recorded.seconds.toFixed(1)}s, but not transcribed{voice.asrWhy
          ? ' — ' + voice.asrWhy
          : ''}. Write the answer below and it will be scored from what you write.
      </p>
    {/if}

    {#if voice.notice}
      <p class="recorded" role="status">{voice.notice}</p>
    {/if}

    {#if voice.error}
      <p class="err" role="alert">{voice.error}</p>
    {/if}

    <div class="controls">
      <button class="talk" class:live={talking} onclick={toggleTalking} disabled={busy}>
        <Icon name="mic" size={14} />
        {talking ? (voice.live ? 'Finish answer' : 'Stop answering') : 'Tap to answer'}
      </button>

      <!-- FR-26: tap-to-talk is the default and live is the opt-in, with the pause a setting
           rather than a constant, because thinking pauses are personal (12.8). -->
      <div class="turns" role="group" aria-label="How an answer ends">
        <button class="mode" aria-pressed={!voice.live} onclick={() => setLive(false)}>Tap</button>
        <button
          class="mode"
          aria-pressed={voice.live}
          onclick={() => setLive(true)}
          disabled={!voice.liveReady}
          title={voice.liveReady ? 'Hands-free, like a conversation' : voice.liveWhy}
        >
          Live
        </button>
      </div>

      {#if voice.live}
        <label class="pause">
          Sent after
          <select value={voice.pause} onchange={(e) => setPause(Number(e.currentTarget.value))}>
            {#each PAUSES as p (p)}
              <option value={p}>{p} s quiet</option>
            {/each}
          </select>
        </label>
      {/if}

      <span class="keyhint">
        {#if voice.live}
          <b>Space</b> finishes early · <b>Esc</b> stops the interviewer · or type below
        {:else}
          <b>Space</b> talks · <b>Esc</b> stops the interviewer · or type below
        {/if}
      </span>
    </div>

    {#if voice.live}
      <!-- 12.6.2 makes correcting the transcript before scoring a fairness requirement; live
           mode trades it for flow, so the trade is stated where it is made. -->
      <p class="live-note">
        The microphone opens after each question, and your answer is sent as it was heard once
        you have been quiet for {voice.pause} s. Tap mode lets you correct it before it is sent.
      </p>
    {:else if !voice.liveReady && voice.liveWhy}
      <p class="live-note">Live mode is unavailable: {voice.liveWhy}.</p>
    {/if}
  {/if}
</div>

<style>
  .voice {
    border: 1px solid var(--rule);
    background: var(--bg-raised);
    padding: var(--s-3) var(--s-4);
    display: flex;
    flex-direction: column;
    gap: var(--s-3);
  }

  .invite {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-4);
    flex-wrap: wrap;
  }

  .invite p {
    margin: 0;
    max-width: 46ch;
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }

  .invite b {
    color: var(--fg);
  }

  .strip {
    display: flex;
    align-items: center;
    gap: var(--s-3);
  }

  /* The meter reads low on purpose: "listening, you are quiet" has to look different from a
   * dead microphone, so the floor is a visible sliver rather than nothing. */
  .meter {
    display: flex;
    align-items: center;
    gap: 2px;
    height: 22px;
    width: 8.5rem;
    flex: none;
  }

  .bar {
    flex: 1;
    height: calc(var(--h) * 100%);
    min-height: 2px;
    background: var(--signal);
    opacity: 0.85;
    transition: height 60ms linear;
  }

  .chip {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: var(--rule-strong);
  }

  .chip.hot {
    background: var(--signal);
  }

  .state {
    margin: 0;
    flex: 1;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    letter-spacing: 0.02em;
    color: var(--fg);
  }

  .num {
    font-family: var(--font-data);
    color: var(--fg-quiet);
  }

  .rec {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    font-family: var(--font-data);
    font-size: var(--step--2);
    letter-spacing: 0.09em;
    color: var(--signal);
  }

  .lamp {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--signal);
    animation: pulse 1.6s var(--ease) infinite;
  }

  @keyframes pulse {
    50% {
      opacity: 0.35;
    }
  }

  .cc,
  .talk,
  .go {
    font: inherit;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    border: 1px solid var(--rule-strong);
    background: transparent;
    color: var(--fg);
    padding: var(--s-2) var(--s-3);
    cursor: pointer;
  }

  .cc[aria-pressed='true'] {
    border-color: var(--signal);
    color: var(--signal);
  }

  .go,
  .talk.live {
    background: var(--signal-fill);
    border-color: var(--signal-fill);
    color: var(--signal-fill-ink);
  }

  .go:hover:not(:disabled),
  .talk.live:hover {
    background: var(--signal-fill-hover);
    border-color: var(--signal-fill-hover);
  }

  .cc:hover,
  .talk:hover:not(.live):not(:disabled) {
    border-color: var(--fg-quiet);
  }

  .go:disabled,
  .talk:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .controls {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    flex-wrap: wrap;
  }

  .turns {
    display: inline-flex;
  }

  .mode {
    font: inherit;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    border: 1px solid var(--rule-strong);
    background: transparent;
    color: var(--fg-quiet);
    padding: var(--s-2) var(--s-3);
    cursor: pointer;
  }

  .mode + .mode {
    border-left: none;
  }

  .mode[aria-pressed='true'] {
    border-color: var(--signal);
    color: var(--signal);
  }

  /* The pressed half draws its full border; the shared edge would otherwise stay grey. */
  .mode[aria-pressed='true'] + .mode,
  .mode + .mode[aria-pressed='true'] {
    border-left: 1px solid var(--signal);
  }

  .mode:hover:not(:disabled):not([aria-pressed='true']) {
    color: var(--fg);
  }

  .mode:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .pause {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }

  .pause select {
    font: inherit;
    font-family: var(--font-data);
    color: var(--fg);
    background: var(--bg-raised);
    border: 1px solid var(--rule-strong);
    padding: var(--s-1) var(--s-2);
  }

  .live-note {
    margin: 0;
    max-width: var(--measure);
    font-size: var(--step--2);
    color: var(--fg-quiet);
  }

  .keyhint {
    font-size: var(--step--2);
    color: var(--fg-faint);
  }

  .keyhint b {
    font-family: var(--font-data);
    font-weight: 500;
    color: var(--fg-quiet);
  }

  .caption {
    margin: 0;
    font-size: var(--step--1);
    line-height: 1.55;
    color: var(--fg-quiet);
    border-left: 2px solid var(--rule-strong);
    padding-left: var(--s-3);
  }

  /* Cut, not deleted (12.4). The remainder stays legible enough to read back. */
  .unsaid {
    text-decoration: line-through;
    opacity: 0.55;
  }

  .marker {
    font-family: var(--font-data);
    font-size: var(--step--2);
    color: var(--signal);
    margin-left: var(--s-2);
  }

  /* Subordinate to the transcript proper: this is what was heard, not yet what will be
   * scored, and it sits above an editable box that can still change it. */
  .heard {
    margin: 0;
    font-size: var(--step--1);
    line-height: 1.6;
    color: var(--fg-quiet);
    max-width: var(--measure);
  }

  .heard.settling::after {
    content: ' …';
    color: var(--signal);
  }

  .recorded,
  .err {
    margin: 0;
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }

  .err {
    color: var(--signal);
  }

  @media (prefers-reduced-motion: reduce) {
    .lamp {
      animation: none;
    }
    .bar {
      transition: none;
    }
  }

  @media (max-width: 34rem) {
    .meter {
      width: 5rem;
    }
    .cc-text {
      display: none;
    }
  }
</style>
