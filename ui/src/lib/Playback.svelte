<script>
  /* Answer playback for the report (12.9). Hearing yourself back is the highest-value thing a
   * speaking report can offer, and it costs nothing extra now that every turn names its own
   * recording.
   *
   * **What this deliberately does not do is seek to a word.** 12.9 asks for click-to-seek from
   * the transcript, and that needs an alignment nothing in this pipeline produces. Guessing one
   * from word position -- the approximation the barge-in split already uses -- would land ten
   * seconds out on a ninety-second answer and play the wrong sentence with a precise-looking
   * cursor over it. What the pipeline does know exactly is where the candidate stopped, so the
   * seek targets are the pauses, and they are honest.
   *
   * The markers double as 11.5's differentiator made visible: a pause inside a clause reads as
   * hunting for the word, one between clauses reads as ordinary. Hearing the difference is the
   * point of showing it here rather than only counting it.
   */
  import Icon from '$lib/Icon.svelte';

  let { sessionId, delivery } = $props();

  // One element for the whole list, so starting an answer stops the one before it. Separate
  // players let two answers talk over each other, which is the one thing playback must not do.
  let el = $state();
  let playing = $state('');
  let at = $state(0);

  const spoken = $derived((delivery?.answers ?? []).filter((a) => !a.why && a.audio));
  const src = (a) => `/api/sessions/${sessionId}/audio/${a.audio.split('/').pop()}`;

  function toggle(a) {
    if (!el) return;
    if (playing === a.audio) {
      if (el.paused) el.play();
      else el.pause();
      return;
    }
    playing = a.audio;
    at = 0;
    el.src = src(a);
    el.play();
  }

  function seek(a, seconds) {
    if (!el) return;
    if (playing !== a.audio) {
      playing = a.audio;
      el.src = src(a);
    }
    // A pause is worth hearing from just before it starts: landing inside the silence plays
    // nothing and reads as a broken control.
    el.currentTime = Math.max(0, seconds - 0.4);
    el.play();
  }

  const clock = (s) =>
    `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  const pct = (x, of) => `${Math.max(0, Math.min(100, (x / (of || 1)) * 100))}%`;
  const live = (a) => playing === a.audio;

  /* Every pause is drawn on the track, but not every pause is worth a button: one
   * 84-second answer has 56 of them, and 56 chips is a wall nobody reads. The longest
   * are the ones worth hearing, and the count says what was left out so the list does
   * not quietly pretend to be all of them. */
  const JUMPS = 6;

  function notable(pauses) {
    const top = [...pauses].sort((x, y) => y.seconds - x.seconds).slice(0, JUMPS);
    return top.sort((x, y) => x.at - y.at);
  }
</script>

{#if spoken.length}
  <section class="playback">
    <h3>Hear it back</h3>
    <p class="note">
      Your own answers, as recorded on this machine. The marks are where you stopped for longer
      than {0.2} seconds &mdash; <span class="key mid"></span> inside a clause, which reads as
      hunting for the word, and <span class="key edge"></span> between clauses, which reads as
      ordinary. Click one to hear it.
    </p>

    <!-- svelte-ignore a11y_media_has_caption -->
    <audio
      bind:this={el}
      ontimeupdate={() => (at = el?.currentTime ?? 0)}
      onended={() => (playing = '')}
      preload="none"
    ></audio>

    {#each spoken as a (a.audio)}
      <article class="answer" class:live={live(a)}>
        <div class="row">
          <button class="play" onclick={() => toggle(a)} aria-label="Play {a.question_id}">
            <Icon name={live(a) && !el?.paused ? 'sound' : 'mic'} size={14} />
          </button>
          <span class="qid">{a.question_id ?? 'answer'}</span>
          <span class="time">{clock(live(a) ? at : 0)} / {clock(a.seconds)}</span>
        </div>

        <div class="track">
          <div class="marks" aria-hidden="true">
            {#each a.pauses as p, i (i)}
              <span
                class="mark"
                class:mid={p.mid_clause}
                style="left: {pct(p.at, a.seconds)}; width: max(2px, {pct(p.seconds, a.seconds)})"
              ></span>
            {/each}
            {#if live(a)}
              <span class="head" style="left: {pct(at, a.seconds)}"></span>
            {/if}
          </div>
          <input
            class="scrub"
            type="range"
            min="0"
            max={a.seconds}
            step="0.05"
            value={live(a) ? at : 0}
            oninput={(e) => seek(a, Number(e.currentTarget.value) + 0.4)}
            aria-label="Seek within {a.question_id ?? 'this answer'}"
          />
        </div>

        {#if a.pauses.length}
          <div class="jumps">
            {#if a.pauses.length > JUMPS}
              <span class="of">{JUMPS} longest of {a.pauses.length}</span>
            {/if}
            {#each notable(a.pauses) as p, i (i)}
              <button
                class="jump"
                class:mid={p.mid_clause}
                onclick={() => seek(a, p.at)}
                title={p.reset_st === null
                  ? 'Pitch either side could not be measured'
                  : `Pitch moved ${p.reset_st.toFixed(1)} semitones across this pause`}
              >
                {clock(p.at)} · {p.seconds.toFixed(1)}s
              </button>
            {/each}
          </div>
        {/if}

        <dl class="figures">
          <div><dt>Rate</dt><dd>{a.articulation_rate} syl/s</dd></div>
          {#if a.wpm}<div><dt>Words</dt><dd>{a.wpm.toFixed(0)}/min</dd></div>{/if}
          <div><dt>Pauses</dt><dd>{a.pause_count}</dd></div>
          {#if a.pause_count}
            <div><dt>Mid-clause</dt><dd>{a.mid_clause_pauses} of {a.pause_count}</dd></div>
          {/if}
        </dl>
      </article>
    {/each}
  </section>
{/if}

<style>
  .playback {
    border: 1px solid var(--rule);
    padding: var(--s-4);
    display: flex;
    flex-direction: column;
    gap: var(--s-3);
  }

  h3 {
    margin: 0;
    font-family: var(--font-structure);
    font-size: var(--step-0);
    letter-spacing: 0.02em;
  }

  .note {
    margin: 0;
    max-width: var(--measure);
    font-size: var(--step--1);
    line-height: 1.6;
    color: var(--fg-quiet);
  }

  .key {
    display: inline-block;
    width: 1.6rem;
    height: 0.55rem;
    vertical-align: -1px;
    border-radius: 1px;
  }

  .key.mid {
    background: var(--signal);
  }

  .key.edge {
    background: var(--rule-strong);
  }

  .answer {
    border-top: 1px solid var(--rule);
    padding-top: var(--s-3);
    display: flex;
    flex-direction: column;
    gap: var(--s-2);
  }

  .row {
    display: flex;
    align-items: center;
    gap: var(--s-3);
  }

  .play {
    font: inherit;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    flex: none;
    border: 1px solid var(--rule-strong);
    background: transparent;
    color: var(--fg);
    cursor: pointer;
  }

  .answer.live .play {
    background: var(--signal-fill);
    border-color: var(--signal-fill);
    color: var(--signal-fill-ink);
  }

  .play:hover {
    border-color: var(--fg-quiet);
  }

  /* `min-width: 0` is what lets this shrink: a flex item defaults to its content's
   * minimum, so a long question id pushed the clock off the right edge instead of
   * truncating itself. */
  .qid {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-data);
    font-size: var(--step--2);
    letter-spacing: 0.06em;
    color: var(--fg-quiet);
  }

  .time {
    flex: none;
    font-family: var(--font-data);
    font-size: var(--step--2);
    font-variant-numeric: tabular-nums;
    color: var(--fg-quiet);
  }

  /* The marks sit above the scrubber rather than inside it: an input's own track cannot carry
   * children, and painting them into its background loses them to every browser's own styling. */
  .track {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .marks {
    position: relative;
    height: 0.6rem;
    background: var(--bg-sunk);
    border: 1px solid var(--rule);
  }

  .mark {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--rule-strong);
  }

  .mark.mid {
    background: var(--signal);
  }

  .head {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 2px;
    background: var(--fg);
  }

  .scrub {
    width: 100%;
    margin: 0;
    accent-color: var(--signal);
  }

  .jumps {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-2);
  }

  .jump {
    font-family: var(--font-data);
    font-size: var(--step--2);
    font-variant-numeric: tabular-nums;
    border: 1px solid var(--rule);
    border-left: 3px solid var(--rule-strong);
    background: transparent;
    color: var(--fg-quiet);
    padding: 2px var(--s-2);
    cursor: pointer;
  }

  .jump.mid {
    border-left-color: var(--signal);
  }

  .jump:hover {
    color: var(--fg);
    border-color: var(--fg-quiet);
  }

  .of {
    align-self: center;
    font-size: var(--step--2);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--fg-faint);
  }

  .figures {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-4);
    margin: 0;
  }

  .figures div {
    display: flex;
    align-items: baseline;
    gap: var(--s-2);
  }

  dt {
    font-size: var(--step--2);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--fg-faint);
  }

  dd {
    margin: 0;
    font-family: var(--font-data);
    font-size: var(--step--1);
    font-variant-numeric: tabular-nums;
    color: var(--fg);
  }

  @media (max-width: 34rem) {
    .figures {
      gap: var(--s-3);
    }
  }
</style>
