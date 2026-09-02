<script>
  // The interview itself. Only the dialogue appears here: `ok`, the guard names and the
  // posterior are judgement, and section 12 treats showing an assessment mid-session as a
  // correctness bug. The API does not send them, and this page could not display them if it
  // wanted to.
  import Icon from '$lib/Icon.svelte';
  import Problem from '$lib/Problem.svelte';
  import { set as setLive } from '$lib/live.svelte.js';
  import { refused, unreachable } from '$lib/problem.js';

  let session = $state(null);
  let problem = $state(null);
  let busy = $state(false);
  let lastStatus = 0;
  let answer = $state('');
  let sending = $state(null);
  let planPath = $state('');
  let showPath = $state(false);
  let elapsed = $state(0);
  let box = $state();
  let composer = $state();

  const PLANS = [
    {
      path: 'data/interview_reviewed.json',
      name: 'The plan you reviewed',
      note: 'Whatever you last saved from the Plan page.'
    },
    {
      path: 'config/interview_swe_general.json',
      name: 'Software engineering, general',
      note: 'The standard mid-level plan. Fourteen questions, about an hour.'
    }
  ];

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

  const send = (path, body) => call(path, { method: 'POST', body: JSON.stringify(body) });

  function toBottom() {
    // An explicit behavior wins over the stylesheet, so reduced motion has to be asked here.
    const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    queueMicrotask(() => box?.scrollTo({ top: box.scrollHeight, behavior }));
  }

  function adopt(got) {
    if (!got) return false;
    session = got;
    setLive(got);
    toBottom();
    return true;
  }

  async function resume() {
    const got = await call('/api/session');
    if (got) adopt(got);
    else if (lastStatus === 404) problem = null;
  }

  async function start(path) {
    if (adopt(await send('/api/session/start', { plan_path: path }))) {
      queueMicrotask(() => composer?.focus());
    }
  }

  async function submit() {
    const text = answer.trim();
    if (!text || busy) return;
    // Show what they said for the whole wait. Clearing the box and appending nothing left a
    // model-length silence where their answer was nowhere on screen and the placeholder was
    // back in the empty composer, which reads as having lost it.
    sending = text;
    answer = '';
    toBottom();
    const got = await send('/api/session/answer', { text });
    if (got) {
      sending = null;
      adopt(got);
      queueMicrotask(() => composer?.focus());
    } else {
      answer = sending;
      sending = null;
      queueMicrotask(() => composer?.focus());
    }
  }

  function onKey(event) {
    // Enter sends, shift+enter is a newline. A spoken answer has no newlines in it, and this
    // page is standing in for speech.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  // What is being asked right now, separated from what has already been answered. The API
  // puts the pending line last; everything before it is the record.
  const pending = $derived.by(() => {
    if (!session || session.done) return null;
    const last = session.turns.at(-1);
    return last?.who === 'interviewer' ? last.text : null;
  });
  const record = $derived(
    !session ? [] : pending ? session.turns.slice(0, -1) : session.turns
  );
  const progress = $derived(
    session && session.question_total
      ? Math.min(1, (session.question_number - 1) / session.question_total)
      : 0
  );

  function clock(secs) {
    const m = Math.floor(secs / 60);
    return `${String(m).padStart(2, '0')}:${String(Math.floor(secs % 60)).padStart(2, '0')}`;
  }

  $effect(() => {
    resume();
  });

  $effect(() => {
    if (!session || session.done || !session.started_at) return;
    const began = Date.parse(session.started_at);
    if (Number.isNaN(began)) return;
    const tick = () => (elapsed = Math.max(0, (Date.now() - began) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  });
</script>

<main class:running={!!session}>
  {#if !session}
    <div class="door">
      <Problem {problem} onretry={resume} />
      <div class="door-title">
        <div>
          <h1>Sit an interview</h1>
          <p class="lede">
            Answer as you would out loud. Nothing here will tell you how you are doing; that is
            what the report is for, and keeping it out of this room is the point.
          </p>
        </div>
        <span class="seal">Assessment channel sealed</span>
      </div>

      <div class="plans">
        {#each PLANS as p}
          <button class="plan" disabled={busy} onclick={() => start(p.path)}>
            <span class="plan-name">{p.name}</span>
            <span class="plan-note">{p.note}</span>
          </button>
        {/each}
      </div>

      <button class="ghost" onclick={() => (showPath = !showPath)}>
        {showPath ? 'Hide' : 'Run a different plan'}
      </button>
      {#if showPath}
        <div class="other">
          <input bind:value={planPath} placeholder="path/to/plan.json" spellcheck="false"
            aria-label="Path to a plan file" />
          <button class="go" disabled={busy || !planPath.trim()} onclick={() => start(planPath.trim())}>
            Start
          </button>
        </div>
      {/if}
    </div>
  {:else}
    <div class="head">
      <div class="record-state">
        <div class="state" class:live={!session.done}>
          <span class="dot"></span>
          {session.done ? 'Interview closed' : 'Interview live'}
        </div>
        <span class="protocol">Candidate record / assessment isolated</span>
      </div>
      <div class="counts">
        <span class="num">{String(session.question_number).padStart(2, '0')}</span><span class="of"
          >/{String(session.question_total).padStart(2, '0')}</span
        >
        {#if !session.done && session.started_at}
          <span class="num time"><Icon name="clock" size={12} />{clock(elapsed)}</span>
        {/if}
      </div>
    </div>
    <div class="bar" style="--p: {progress}"></div>

    <div
      class="record"
      bind:this={box}
      role="log"
      aria-label="Interview transcript"
    >
      {#each record as turn, i (i)}
        <div class="turn {turn.who}">
          <span class="who">{turn.who === 'interviewer' ? 'Interviewer' : 'You'}</span>
          <p>{turn.text}</p>
        </div>
      {/each}

      {#if sending}
        <div class="turn candidate awaiting">
          <span class="who">You</span>
          <p>{sending}</p>
          <p class="thinking" aria-live="polite">
            <span class="sweep"><span></span></span>
            Considering your answer. This runs on your machine, so it takes a moment.
          </p>
        </div>
      {/if}

      {#if record.length === 0 && !sending}
        <p class="empty">The interview starts here.</p>
      {/if}
    </div>

    {#if session.done}
      <div class="closed">
        <h2>That is the end of the interview.</h2>
        <p>
          Nothing was judged while you were talking. The reading happens now, and it is under
          <a href="/history">History</a>.
        </p>
      </div>
    {:else}
      <div class="stage">
        <Problem {problem} />
        <div class="prompt">
          <span class="prompt-number num">Q{String(session.question_number).padStart(2, '0')}</span>
          <h1 class="asking" aria-live="polite">{pending ?? ''}</h1>
        </div>

        <div class="composer">
          <textarea
            bind:this={composer}
            bind:value={answer}
            onkeydown={onKey}
            rows="3"
            readonly={busy}
            aria-label="Your answer"
            placeholder={busy ? '' : 'Answer as you would say it out loud.'}
          ></textarea>
          <div class="send">
            <span class="keyhint">
              <b>Enter</b> sends · <b>Shift + Enter</b> for a new line
            </span>
            <button class="go" disabled={busy || !answer.trim()} onclick={submit}>
              {busy ? 'Sending' : 'Send'}
            </button>
          </div>
        </div>
      </div>
    {/if}
  {/if}
</main>

<style>
  main {
    max-width: 68rem;
    margin: 0 auto;
    padding: var(--s-6) var(--s-5) var(--s-8);
  }

  /* A live interview is one screen: the question and the composer are always reachable and
   * the transcript takes whatever is left. `dvh`, not `vh` -- on a phone `vh` counts the
   * space behind the browser chrome and pushed Send under the fold. */
  main.running {
    height: calc(100dvh - var(--strip-h, 52px));
    min-height: 24rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    padding: var(--s-4) var(--s-5) var(--s-5);
  }

  .door {
    margin-top: var(--s-4);
    padding: var(--s-7);
    background: color-mix(in srgb, var(--bg-raised) 96%, transparent);
    border: 1px solid var(--rule-strong);
    border-top: 4px solid var(--signal);
    box-shadow: var(--shadow);
  }
  .door-title {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--s-6);
    align-items: start;
    padding-bottom: var(--s-6);
    border-bottom: 1px solid var(--rule-strong);
  }
  .door h1 {
    font-size: var(--step-4);
  }
  .lede {
    color: var(--fg-quiet);
    font-size: var(--step-1);
    max-width: var(--measure);
    margin-top: var(--s-3);
  }
  .seal {
    font-family: var(--font-data);
    font-size: var(--step--2);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--signal);
    border: 1px solid currentColor;
    padding: 7px 9px;
  }

  .plans {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--s-3);
    margin: var(--s-6) 0 var(--s-4);
  }
  .plan {
    display: grid;
    gap: 3px;
    text-align: left;
    background: var(--bg-raised);
    border: 1px solid var(--rule);
    border-radius: 0;
    padding: var(--s-4);
    cursor: pointer;
    transition: border-color 160ms var(--ease), background 160ms var(--ease);
  }
  .plan:hover:not(:disabled) {
    border-color: var(--signal);
    background: color-mix(in srgb, var(--review-blue) 8%, var(--bg-raised));
  }
  .plan:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .plan-name {
    font-family: var(--font-structure);
    font-weight: 600;
    font-size: var(--step-1);
    color: var(--fg);
  }
  .plan-note {
    color: var(--fg-quiet);
    font-size: var(--step--1);
  }

  .other {
    display: flex;
    gap: var(--s-2);
    margin-top: var(--s-3);
    max-width: 32rem;
  }
  .other input {
    font-family: var(--font-data);
    font-size: var(--step--1);
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
    transition: border-color 140ms var(--ease), background 140ms var(--ease);
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
    white-space: nowrap;
  }
  .go:hover:not(:disabled) {
    background: var(--signal-fill-hover);
    border-color: var(--signal-fill-hover);
  }
  .ghost {
    border-color: transparent;
    color: var(--fg-quiet);
  }
  .ghost:hover {
    color: var(--fg);
    border-color: var(--rule-strong);
  }

  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-3) var(--s-4);
    background: color-mix(in srgb, var(--bg-sunk) 72%, transparent);
    border: 1px solid var(--rule);
    flex: none;
  }
  .record-state {
    display: grid;
    gap: 3px;
  }
  .state {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: var(--fg-faint);
  }
  .state.live {
    color: var(--signal);
  }
  .protocol {
    font-family: var(--font-data);
    font-size: 0.6rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--fg-faint);
  }
  .state .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
  }
  .state.live .dot {
    animation: pulse 2.6s var(--ease) infinite;
  }
  @keyframes pulse {
    0%,
    100% {
      box-shadow: 0 0 0 0 rgba(240, 83, 89, 0.55);
    }
    60% {
      box-shadow: 0 0 0 6px rgba(240, 83, 89, 0);
    }
  }

  .counts {
    display: flex;
    align-items: center;
    gap: var(--s-4);
    font-size: var(--step--1);
    color: var(--fg);
  }
  .of {
    color: var(--fg-faint);
  }
  .time {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--fg-quiet);
    font-size: var(--step--2);
  }

  .bar {
    height: 3px;
    background: var(--rule);
    position: relative;
    overflow: hidden;
    flex: none;
  }
  .bar::after {
    content: '';
    position: absolute;
    inset: 0;
    background: var(--signal);
    transform-origin: left;
    transform: scaleX(var(--p));
    transition: transform 520ms var(--ease);
  }

  .record {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    margin-top: var(--s-3);
    padding: var(--s-5) var(--s-5) var(--s-4);
    background: color-mix(in srgb, var(--bg-sunk) 64%, transparent);
    border: 1px solid var(--rule);
    display: flex;
    flex-direction: column;
    gap: var(--s-5);
    /* Both edges, not just the top: hard-clipping the bottom sliced a line of dialogue in
     * half straight into the composer's rule and read as a rendering fault. */
    mask-image: linear-gradient(
      to bottom,
      transparent,
      #000 var(--s-5),
      #000 calc(100% - var(--s-4)),
      transparent
    );
  }
  .empty {
    color: var(--fg-faint);
    font-size: var(--step--1);
  }

  .turn .who {
    display: block;
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: var(--fg-faint);
    margin-bottom: var(--s-1);
  }
  .turn p {
    white-space: pre-wrap;
    max-width: var(--measure);
  }
  .turn.interviewer p {
    color: var(--fg-quiet);
  }
  .turn.candidate {
    padding: var(--s-3) var(--s-4);
    border-left: 1px solid var(--rule-strong);
    background: color-mix(in srgb, var(--bg-raised) 56%, transparent);
  }
  .turn.candidate p {
    color: var(--fg);
  }
  .turn.awaiting {
    border-left-color: var(--signal);
  }
  .thinking {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-3);
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

  .stage {
    flex: none;
    margin-top: var(--s-3);
    border: 1px solid var(--rule-strong);
    border-top: 3px solid var(--signal);
    padding: var(--s-5);
    background: var(--bg-raised);
    box-shadow: var(--shadow);
  }

  .prompt {
    display: grid;
    grid-template-columns: 3.25rem minmax(0, 1fr);
    gap: var(--s-4);
    align-items: start;
  }
  .prompt-number {
    color: var(--signal);
    font-size: var(--step--1);
    padding-top: 0.4rem;
    border-top: 1px solid currentColor;
  }

  /* The question being answered is the brightest thing on the screen. Everything behind it
   * is deliberately dimmer. */
  .asking:empty {
    display: none;
  }
  .asking {
    font-family: var(--font-prose);
    letter-spacing: normal;
    font-size: var(--step-3);
    font-weight: 500;
    line-height: 1.3;
    color: var(--fg);
    max-width: 38ch;
    text-wrap: balance;
    margin-bottom: var(--s-5);
    animation: rise 420ms var(--ease) both;
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }

  .composer textarea {
    resize: none;
    min-height: 5.5rem;
    font-size: var(--step-1);
    line-height: 1.5;
  }
  .send {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-4);
    margin-top: var(--s-3);
  }
  .keyhint {
    color: var(--fg-faint);
    font-size: var(--step--1);
  }
  .keyhint b {
    font-weight: 500;
    color: var(--fg-quiet);
  }

  .closed {
    flex: none;
    border-top: 1px solid var(--rule);
    padding-top: var(--s-5);
    max-width: var(--measure);
  }
  .closed p {
    color: var(--fg-quiet);
    margin-top: var(--s-2);
  }
  .closed a {
    color: var(--signal);
  }

  @media (max-width: 40rem) {
    main {
      padding: var(--s-5) var(--s-4) var(--s-7);
    }
    main.running {
      padding: var(--s-3) var(--s-4) var(--s-4);
    }
    .door {
      margin: 0;
      padding: var(--s-5) var(--s-4);
      border-width: 0;
      border-top-width: 3px;
      box-shadow: none;
    }
    .door-title {
      grid-template-columns: 1fr;
      gap: var(--s-4);
    }
    .plans {
      grid-template-columns: 1fr;
    }
    .protocol {
      display: none;
    }
    .record {
      padding-inline: var(--s-3);
    }
    .stage {
      padding: var(--s-4);
    }
    .prompt {
      grid-template-columns: 2.25rem minmax(0, 1fr);
      gap: var(--s-3);
    }
    .asking {
      font-size: var(--step-2);
      margin-bottom: var(--s-4);
    }
    .send {
      flex-direction: column-reverse;
      align-items: stretch;
      gap: var(--s-2);
    }
    .send .go {
      width: 100%;
    }
    .keyhint {
      text-align: center;
    }
  }
</style>
