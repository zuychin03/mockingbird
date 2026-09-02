<script>
  let { problem, onretry = null } = $props();
</script>

{#if problem}
  <div class="problem" role="alert">
    <div class="body">
      {#if problem.title}<p class="title">{problem.title}</p>{/if}
      <p class="detail">{problem.detail}</p>
      {#if problem.raw}
        <details>
          <summary>What the browser reported</summary>
          <code>{problem.raw}</code>
        </details>
      {/if}
    </div>
    {#if onretry}
      <button onclick={onretry}>Try again</button>
    {/if}
  </div>
{/if}

<style>
  .problem {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--s-4);
    background: color-mix(in srgb, var(--signal) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--signal) 38%, transparent);
    border-radius: var(--r-1);
    padding: var(--s-4);
    margin-bottom: var(--s-5);
  }
  .body {
    min-width: 0;
  }
  .title {
    font-family: var(--font-structure);
    font-weight: 600;
    color: var(--signal);
    margin-bottom: var(--s-1);
  }
  .detail {
    color: var(--fg);
    max-width: var(--measure);
  }
  details {
    margin-top: var(--s-3);
  }
  summary {
    font-size: var(--step--1);
    color: var(--fg-quiet);
    cursor: pointer;
  }
  code {
    display: block;
    font-family: var(--font-data);
    font-size: var(--step--1);
    color: var(--fg-quiet);
    margin-top: var(--s-2);
    overflow-wrap: anywhere;
  }
  button {
    flex: none;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    font-weight: 500;
    background: transparent;
    color: var(--signal);
    border: 1px solid color-mix(in srgb, var(--signal) 45%, transparent);
    border-radius: var(--r-1);
    padding: 9px 14px;
    min-height: 44px;
    cursor: pointer;
  }
  button:hover {
    border-color: var(--signal);
    background: color-mix(in srgb, var(--signal) 10%, transparent);
  }

  @media (max-width: 40rem) {
    .problem {
      flex-direction: column;
    }
    button {
      width: 100%;
    }
  }
</style>
