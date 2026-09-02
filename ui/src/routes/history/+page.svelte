<script>
  // Past sessions, and the report for one. Building a report runs extraction and scoring,
  // which are offline work by design -- the live and assessment channels are separate -- so
  // it is an explicit action and it is slow, rather than something a page polls for.
  import { page } from '$app/state';
  import { replaceState } from '$app/navigation';

  import Icon from '$lib/Icon.svelte';
  import Problem from '$lib/Problem.svelte';
  import { refused, unreachable } from '$lib/problem.js';

  let sessions = $state([]);
  let report = $state(null);
  let problem = $state(null);
  let busy = $state(false);
  let building = $state('');
  let opened = $state('');
  let showAbandoned = $state(false);

  const LIMIT = 50;

  async function call(path) {
    problem = null;
    try {
      const res = await fetch(path);
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
    const got = await call(`/api/sessions?limit=${LIMIT}`);
    if (got) sessions = got;
  }

  async function build(id) {
    busy = true;
    building = id;
    opened = id;
    report = null;
    // Unconditionally, before the request can fail: on success this is the shareable address
    // of the report, and on failure it is what stops the deep-link effect seeing a URL that
    // disagrees with `opened` and starting the whole build again.
    replaceState(`?s=${id}`, {});
    const got = await call(`/api/sessions/${id}/report`);
    if (got) report = got;
    busy = false;
    building = '';
  }

  function retry() {
    if (opened) build(opened);
    else load();
  }

  function close() {
    report = null;
    opened = '';
    replaceState('/history', {});
  }

  const when = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : 'unknown');
  const day = (iso) => (iso ? iso.slice(0, 10) : 'unknown');
  const at = (iso) => (iso ? iso.slice(11, 16) : '--:--');
  const finished = (s) => s.status === 'complete';

  // A stub with no answers looked identical to a full interview in a flat list of sixteen
  // near-identical labels. Finished interviews are the ones worth reading, so they lead and
  // the rest wait behind a count.
  const shownSessions = $derived(showAbandoned ? sessions : sessions.filter(finished));
  const abandoned = $derived(sessions.length - sessions.filter(finished).length);
  const days = $derived.by(() => {
    const out = [];
    for (const s of shownSessions) {
      const d = day(s.started_at);
      if (!out.length || out.at(-1).day !== d) out.push({ day: d, rows: [] });
      out.at(-1).rows.push(s);
    }
    return out;
  });

  /* The renderer underlines every heading with a rule of = or -. That is the one structural
   * promise the text makes, so it is the only thing parsed here; the words inside a section
   * are printed as written. `EVERY CRITERION` is the exception, replaced by the same numbers
   * as data so the rubric can be laid out instead of aligned with spaces. */
  const parsed = $derived.by(() => {
    if (!report?.text) return { sections: [], signoff: [] };
    const lines = report.text.split('\n');
    const out = [];
    let current = { heading: null, lines: [] };
    for (let i = 0; i < lines.length; i++) {
      const next = lines[i + 1] ?? '';
      if (lines[i].trim() && /^[=-]{10,}$/.test(next.trim())) {
        out.push(current);
        current = { heading: lines[i].trim(), lines: [] };
        i++;
        continue;
      }
      current.lines.push(lines[i]);
    }
    out.push(current);

    // The report signs off with unindented lines under no heading of their own, so they land
    // inside whatever section came last. Left there they drag that section's dedent to zero,
    // indenting every line that should sit flush, and the sign-off itself never renders.
    const last = out.at(-1);
    let signoff = [];
    if (last) {
      let end = last.lines.length;
      while (end > 0 && !last.lines[end - 1].trim()) end--;
      let from = end;
      while (from > 0 && last.lines[from - 1].trim() && !/^[ \t]/.test(last.lines[from - 1])) {
        from--;
      }
      if (from < end && (last.heading || from > 0)) {
        signoff = last.lines.slice(from, end).map((l) => l.trim());
        last.lines = last.lines.slice(0, from);
      }
    }

    const sections = out
      .map((s) => ({ ...s, body: s.lines }))
      .filter((s) => s.heading || s.body.some((l) => l.trim()));
    return { sections, signoff };
  });

  const shown = $derived(parsed.sections);
  const signoff = $derived(parsed.signoff);

  // Weakest first. Alphabetical buried the only two shortfalls in the document between four
  // full rows, in a report whose whole claim is checkable arithmetic.
  const rubric = $derived(
    [...(report?.rubric ?? [])].sort(
      (a, b) => a.met / (a.of || 1) - b.met / (b.of || 1) || a.name.localeCompare(b.name)
    )
  );

  const title = (s) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  const dashes = (s) => s.replace(/ -- /g, ' - ');

  /** Does this section just print the numbers the rubric already carries as data? */
  function isRubric(s) {
    if (!rubric.length) return false;
    const body = s.body.join('\n');
    return rubric.filter((c) => body.includes(c.name)).length >= 2;
  }

  /* The renderer wraps for a 60-column terminal, so one paragraph arrives as several lines.
   * Rendered one-line-per-element the report cannot reflow, and every wrap the terminal chose
   * becomes a hard break at whatever width the reader is on. Blank lines separate blocks; a
   * bullet or a number starts one; everything else joins the block it is inside. */
  function blocks(body) {
    const out = [];
    let cur = null;
    for (const raw of body) {
      const line = raw.trim();
      if (!line) {
        cur = null;
        continue;
      }
      if (/^(You said:\s*)?[“"]/.test(line)) {
        out.push({ kind: 'quote', text: line });
        cur = null;
        continue;
      }
      if (line.startsWith('- ')) {
        cur = { kind: 'item', text: line.slice(2) };
        out.push(cur);
        continue;
      }
      if (/^\d+\./.test(line)) {
        out.push({ kind: 'lead', text: line });
        cur = null;
        continue;
      }
      if (line.startsWith('[')) {
        out.push({ kind: 'item', text: line });
        cur = null;
        continue;
      }
      if (cur) {
        cur.text += ' ' + line;
        continue;
      }
      cur = { kind: 'p', text: line };
      out.push(cur);
    }
    return out;
  }

  $effect(() => {
    load();
  });

  $effect(() => {
    const want = page.url.searchParams.get('s');
    if (want && want !== opened && !busy) build(want);
  });
</script>

<main>
  <span class="sheet-id num" aria-hidden="true">ARCHIVE MB-03 / LOCAL RECORD</span>
  <div class="lede">
    <div>
      <h1>Interview history</h1>
      <p>
        Every interview recorded on this machine. Reading one runs the extraction and the
        scoring now, not during the interview, which is why it takes a minute.
      </p>
    </div>
    <div class="archive-note">
      <span class="num">LOCAL / PRIVATE</span>
      <p>Reports quote your answers and show which parts were model readings.</p>
    </div>
  </div>

  <Problem {problem} onretry={retry} />

  {#if report}
    <button class="back" onclick={close}>
      <Icon name="back" size={14} /> All interviews
    </button>
  {:else if sessions.length === 0}
    <p class="empty">
      Nothing recorded yet. An interview appears here the moment one starts.
      <a href="/session">Sit one now.</a>
    </p>
  {:else}
    {#each days as group (group.day)}
      <section class="day" aria-label="Interviews on {group.day}">
        <h2 class="slug">{group.day}</h2>
        {#each group.rows as s (s.session_id)}
          <button
            class="tape-row"
            class:working={building === s.session_id}
            disabled={busy}
            onclick={() => build(s.session_id)}
          >
            <span class="num at">{at(s.started_at)}</span>
            <span class="label">
              {s.label}
              {#if !finished(s)}<span class="tag">unfinished</span>{/if}
            </span>
            <span class="counts num">
              {s.questions} questions <span class="dot">·</span> {s.turns} turns
            </span>
            <span class="read">{building === s.session_id ? 'Reading…' : 'Read'}</span>
            {#if building === s.session_id}
              <span class="sweep"><span></span></span>
            {/if}
          </button>
        {/each}
      </section>
    {/each}

    {#if abandoned}
      <button class="toggle" onclick={() => (showAbandoned = !showAbandoned)}>
        {showAbandoned ? 'Hide' : 'Show'} {abandoned} unfinished
      </button>
    {/if}
    {#if sessions.length === LIMIT}
      <p class="note">The {LIMIT} most recent. Older interviews are still on disk.</p>
    {/if}
  {/if}

  {#if busy}
    <p class="waiting" aria-live="polite">
      Reading the answers. Extraction and scoring run on your machine, one question at a time.
    </p>
  {/if}

  {#if report}
    <article class="report">
      <header>
        <h2>{report.label}</h2>
        <p class="meta num">
          {when(report.started_at)}
          <span class="sep">·</span>{report.asked} asked
          <span class="sep">·</span>{report.answered} answered
          <span class="sep">·</span>{report.scored} scored
        </p>
      </header>

      {#each shown as s}
        <section>
          {#if s.heading}<h3>{s.heading.toLowerCase()}</h3>{/if}

          {#if isRubric(s)}
            <!-- One mark per answer judged, filled where it was met. A proportional bar hid
                 the denominator: 6/6 and 10/10 drew the same full bar, so a criterion judged
                 on four answers looked exactly as settled as one judged on ten. The marks are
                 ink, never red -- red here would be a third meaning, and a grade. -->
            <table class="rubric">
              <tbody>
                {#each rubric as c}
                  <tr>
                    <th scope="row">{title(c.name)}</th>
                    <td class="ticks">
                      <span class="marks" aria-hidden="true">
                        {#each { length: c.of } as _, i}
                          <span class="tick" class:met={i < c.met}></span>
                        {/each}
                      </span>
                      <span class="num count">{c.met}<span class="of">/{c.of}</span></span>
                    </td>
                    <td class="desc">{dashes(c.description)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <div class="prose">
              {#each blocks(s.body) as b}
                <p class={b.kind}>{dashes(b.text)}</p>
              {/each}
            </div>
          {/if}
        </section>
      {/each}

      {#if signoff.length}
        <footer>
          <span class="stamp">
            Evidence limits
          </span>
          <div>
            {#each signoff as line}
              {#if line.trim()}<p>{dashes(line.trim())}</p>{/if}
            {/each}
          </div>
        </footer>
      {/if}
    </article>
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
    border-top: 1px solid var(--signal);
  }
  .archive-note span {
    display: block;
    color: var(--signal);
    font-size: var(--step--2);
    letter-spacing: 0.08em;
    margin-bottom: var(--s-2);
  }
  .archive-note p {
    font-size: var(--step--1);
    color: var(--fg-quiet);
  }

  .empty {
    color: var(--fg-quiet);
  }
  .empty a {
    color: var(--signal);
  }
  .note {
    color: var(--fg-faint);
    font-size: var(--step--1);
    margin-top: var(--s-3);
  }

  .day + .day {
    margin-top: var(--s-5);
  }
  .day h2 {
    padding: var(--s-2) var(--s-3);
    border-top: 2px solid var(--fg);
    border-bottom: 1px solid var(--rule-strong);
    background: color-mix(in srgb, var(--review-blue) 5%, transparent);
  }

  /* The whole row is the control. Sixteen identical outline buttons down the right edge were
   * the loudest thing on a page whose job is choosing between near-identical labels. */
  .tape-row {
    position: relative;
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr) auto 4rem;
    gap: var(--s-4);
    align-items: baseline;
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule);
    border-radius: 0;
    padding: var(--s-3);
    font: inherit;
    color: inherit;
    cursor: pointer;
    min-height: 44px;
    transition: background 140ms var(--ease);
  }
  .tape-row:hover:not(:disabled) {
    background: color-mix(in srgb, var(--review-blue) 7%, transparent);
  }
  .tape-row:hover:not(:disabled) .read {
    color: var(--signal);
  }
  .tape-row:disabled {
    cursor: not-allowed;
  }
  .tape-row:disabled:not(.working) {
    opacity: 0.5;
  }
  .tape-row.working {
    background: color-mix(in srgb, var(--signal) 6%, transparent);
  }
  .at {
    font-size: var(--step--1);
    color: var(--signal);
  }
  .label {
    font-size: var(--step-0);
  }
  .counts {
    font-size: var(--step--1);
    color: var(--fg-faint);
    white-space: nowrap;
  }
  .counts .dot {
    padding: 0 2px;
  }
  .read {
    font-family: var(--font-structure);
    font-size: var(--step--1);
    color: var(--fg-faint);
    justify-self: end;
    white-space: nowrap;
  }
  .tag {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-faint);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: 1px 5px;
    margin-left: var(--s-2);
    white-space: nowrap;
  }

  .toggle {
    font-family: var(--font-structure);
    font-size: var(--step--1);
    background: transparent;
    color: var(--fg-quiet);
    border: 1px solid var(--rule-strong);
    border-radius: var(--r-1);
    padding: 9px 14px;
    min-height: 44px;
    margin-top: var(--s-4);
    cursor: pointer;
  }
  .toggle:hover {
    color: var(--fg);
    border-color: var(--fg-quiet);
  }

  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    font-family: var(--font-structure);
    font-size: var(--step--1);
    background: transparent;
    color: var(--fg-quiet);
    border: 1px solid transparent;
    border-radius: var(--r-1);
    padding: 9px 12px 9px 8px;
    margin-left: -8px;
    min-height: 44px;
    cursor: pointer;
    transition: color 140ms var(--ease), border-color 140ms var(--ease);
  }
  .back:hover {
    color: var(--signal);
    border-color: color-mix(in srgb, var(--signal) 40%, transparent);
  }

  /* Pinned to the row being read, not stranded below fifty of them. */
  .sweep {
    position: absolute;
    left: 0;
    right: 0;
    bottom: -1px;
    height: 2px;
    overflow: hidden;
    background: var(--rule);
  }
  .sweep span {
    display: block;
    height: 100%;
    width: 30%;
    background: var(--signal);
    animation: sweep 1.6s var(--ease) infinite;
  }
  @keyframes sweep {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(400%);
    }
  }
  .waiting {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-4);
    max-width: var(--measure);
  }

  .report {
    margin-top: var(--s-5);
    background: var(--bg-raised);
    border: 1px solid var(--rule-strong);
    border-top: 4px solid var(--signal);
    box-shadow: var(--shadow);
    padding: var(--s-6);
  }
  .report header {
    padding-bottom: var(--s-5);
    border-bottom: 2px solid var(--fg);
  }
  .report h2 {
    font-size: var(--step-3);
  }
  .report .meta {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    margin-top: var(--s-2);
  }
  .sep {
    padding: 0 var(--s-2);
    color: var(--fg-faint);
  }

  .report section {
    margin-top: var(--s-6);
  }
  .report h3 {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--review-blue-deep);
    margin-bottom: var(--s-4);
  }

  .prose {
    max-width: var(--measure);
  }
  .prose p {
    margin: 0;
  }
  .prose p + p {
    margin-top: var(--s-3);
  }
  .prose .lead {
    font-weight: 600;
    font-family: var(--font-structure);
    margin-top: var(--s-4);
  }
  .prose .item {
    padding-left: var(--s-4);
    position: relative;
  }
  .prose .item::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0.62em;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--fg-faint);
  }
  .prose .quote {
    font-family: var(--font-data);
    font-size: var(--step--1);
    line-height: 1.6;
    color: var(--fg-quiet);
    padding: var(--s-3) var(--s-4);
    margin: var(--s-3) 0 var(--s-3) var(--s-4);
    background: color-mix(in srgb, var(--review-blue) 6%, var(--bg-sunk));
    border-left: 1px solid var(--review-blue);
  }

  .rubric {
    width: 100%;
    border-collapse: collapse;
  }
  .rubric tr {
    border-bottom: 1px solid var(--rule);
  }
  .rubric th {
    text-align: left;
    font-family: var(--font-structure);
    font-weight: 500;
    font-size: var(--step--1);
    padding: var(--s-3) var(--s-4) var(--s-3) 0;
    white-space: nowrap;
  }
  .rubric td {
    padding: var(--s-3) var(--s-4) var(--s-3) 0;
    vertical-align: middle;
  }
  .ticks {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    width: 1%;
    white-space: nowrap;
  }
  .marks {
    display: inline-flex;
    gap: 3px;
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
  .desc {
    color: var(--fg-quiet);
    font-size: var(--step--1);
  }

  .report footer {
    display: flex;
    gap: var(--s-4);
    align-items: flex-start;
    margin-top: var(--s-6);
    padding-top: var(--s-4);
    border-top: 1px solid var(--rule);
  }
  .report footer p {
    color: var(--fg-quiet);
    font-size: var(--step--1);
    max-width: var(--measure);
  }
  .report footer p + p {
    margin-top: var(--s-2);
  }
  .stamp {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    flex: none;
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--signal);
    border: 1px solid color-mix(in srgb, var(--signal) 40%, transparent);
    border-radius: var(--r-1);
    padding: 4px 8px;
  }

  @media (max-width: 52rem) {
    .lede {
      grid-template-columns: 1fr;
      gap: var(--s-5);
    }
    .tape-row {
      grid-template-columns: 4rem minmax(0, 1fr) auto;
      row-gap: var(--s-1);
    }
    .tape-row .counts {
      grid-column: 2 / -1;
    }
  }

  @media (max-width: 40rem) {
    main {
      margin: 0;
      padding: var(--s-6) var(--s-4) var(--s-7);
      border-width: 0;
      box-shadow: none;
    }
    .report {
      padding: var(--s-5) var(--s-4);
    }
    .tape-row {
      grid-template-columns: 3.5rem minmax(0, 1fr);
      align-items: start;
    }
    .tape-row .counts {
      grid-column: 2;
    }
    .tape-row .read {
      grid-column: 2;
      justify-self: end;
      color: var(--signal);
    }
    /* The gloss is the only thing that makes the number checkable, so it moves rather than
     * disappearing: deleting it left six snake-case labels and six bare fractions. */
    .rubric tr {
      display: grid;
      grid-template-columns: 1fr auto;
      padding: var(--s-3) 0;
    }
    .rubric th,
    .rubric td {
      padding: 0;
      white-space: normal;
    }
    .rubric th {
      align-self: center;
    }
    .ticks {
      width: auto;
      justify-self: end;
      align-self: center;
    }
    .desc {
      grid-column: 1 / -1;
      margin-top: var(--s-1);
    }
    .report footer {
      flex-direction: column;
      gap: var(--s-3);
    }
  }
</style>
