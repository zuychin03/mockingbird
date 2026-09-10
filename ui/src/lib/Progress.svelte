<script>
  /* The same criteria across every interview that has been read (12.9, stage 8).
   *
   * **There is no trend line and no arrow, and that is a decision rather than an omission.**
   * The scores come from model extraction, so two readings of one interview need not agree,
   * and by how much has never been measured here. Until that noise floor is known, "up 12%"
   * would be a claim the pipeline cannot support -- and a false one is worse than none in a
   * report whose whole argument is that the arithmetic is checkable.
   *
   * So the numbers are laid out with their denominators and the reader draws their own line.
   * The rubric table already learned the other half of this: a rate without its denominator
   * makes a criterion judged on four answers look exactly as settled as one judged on ten, so
   * every cell shows both and the tint behind it never stands in for the figure.
   */
  let { progress } = $props();

  const when = (iso) => (iso ? iso.slice(5, 10).replace('-', '/') : '--');
  const title = (s) => (s ?? '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

  const shown = $derived(progress?.criteria ?? []);
  const sessions = $derived(progress?.sessions ?? []);
  const unread = $derived(Math.max(0, (progress?.readable ?? 0) - (progress?.read ?? 0)));

  function cell(c, i) {
    return c.points.find((p) => p.at === i) ?? null;
  }
</script>

{#if progress}
  <section class="progress">
    <h2 class="slug">Across your interviews</h2>

    {#if (progress.read ?? 0) < 2}
      <p class="note">
        {#if progress.read === 1}
          One interview has been read so far{#if unread}, and {unread}
            {unread === 1 ? 'other could be' : 'others could be'}{/if}. Reading a second is what
          gives this something to compare.
        {:else}
          No interview has been read yet{#if unread}, though {unread} could be{/if}. Open one from
          the list and this fills in.
        {/if}
        Reading an interview runs the scoring, which takes a minute, so it happens when you ask
        for it rather than on its own.
      </p>
    {:else}
      <p class="note">
        Every criterion, in each of the {progress.read} interviews that have been read{#if unread},
          out of {progress.read + unread} that could be{/if}. Both numbers are shown because a
        criterion judged on four answers is not as settled as one judged on ten &mdash; and there
        is deliberately no trend line: the scoring is a model reading, two readings of one
        interview need not agree, and how far they drift has not been measured.
      </p>

      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Criterion</th>
              {#each sessions as s (s.session_id)}
                <th scope="col" class="num">{when(s.started_at)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each shown as c (c.name)}
              <tr>
                <th scope="row">
                  {title(c.name)}
                  {#if c.description}<span class="desc">{c.description}</span>{/if}
                </th>
                {#each sessions as s, i (s.session_id)}
                  {@const p = cell(c, i)}
                  <td class="num">
                    {#if p && p.of}
                      <span class="tint" style="--r: {p.rate}"></span>
                      <span class="fig">{p.met}<span class="of">/{p.of}</span></span>
                    {:else}
                      <span class="absent" title="not judged in this interview">&mdash;</span>
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}

<style>
  .progress {
    display: flex;
    flex-direction: column;
    gap: var(--s-3);
    padding-bottom: var(--s-5);
  }

  .note {
    margin: 0;
    max-width: var(--measure);
    font-size: var(--step--1);
    line-height: 1.6;
    color: var(--fg-quiet);
  }

  /* Wide content scrolls inside its own box: one column per interview read, and the page body
   * must not start scrolling sideways because someone has sat twenty of them. */
  .scroll {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    font-size: var(--step--1);
  }

  th,
  td {
    text-align: left;
    padding: var(--s-2) var(--s-3);
    border-bottom: 1px solid var(--rule);
    white-space: nowrap;
  }

  thead th {
    font-family: var(--font-structure);
    font-size: var(--step--2);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--fg-faint);
    border-bottom-color: var(--rule-strong);
  }

  tbody th {
    font-weight: 500;
    color: var(--fg);
    padding-right: var(--s-5);
    white-space: normal;
  }

  .desc {
    display: block;
    font-size: var(--step--2);
    font-weight: 400;
    color: var(--fg-faint);
  }

  .num {
    font-family: var(--font-data);
    font-variant-numeric: tabular-nums;
  }

  td.num {
    position: relative;
    text-align: right;
  }

  /* Behind the figure, never instead of it. */
  .tint {
    position: absolute;
    left: 0;
    right: 0;
    top: 2px;
    bottom: 2px;
    background: var(--signal);
    opacity: calc(0.04 + var(--r) * 0.14);
  }

  .fig {
    position: relative;
  }

  .of {
    color: var(--fg-faint);
  }

  .absent {
    color: var(--fg-faint);
  }
</style>
