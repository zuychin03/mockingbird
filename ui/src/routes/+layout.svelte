<script>
  import { page } from '$app/state';
  import { live, sync } from '$lib/live.svelte.js';
  import '$lib/theme.css';

  let { children } = $props();
  let strip;

  const tabs = [
    { href: '/', code: '01', label: 'Plan' },
    { href: '/session', code: '02', label: 'Interview' },
    { href: '/history', code: '03', label: 'History' }
  ];

  // The interview is the only room that judges nothing, and it is the only room that looks
  // different. Setting this on the document rather than a wrapper lets the ground itself
  // change, so entering the studio reads as walking into it.
  const room = $derived(page.url.pathname === '/session' ? 'studio' : 'document');

  $effect(() => {
    document.documentElement.setAttribute('data-room', room);
  });

  $effect(() => {
    sync();
  });

  // The interview is a fixed-height column measured against this bar, and the bar changes
  // height when the nav wraps. Publishing the real number beats hardcoding one per
  // breakpoint, which is how the composer ends up under the fold on a phone.
  $effect(() => {
    if (!strip) return;
    const publish = () =>
      document.documentElement.style.setProperty('--strip-h', strip.offsetHeight + 'px');
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(strip);
    return () => ro.disconnect();
  });
</script>

<header bind:this={strip}>
  <div class="strip">
    <a class="brand" href="/">
      <span class="brand-mark" class:on={live.on} aria-hidden="true">
        <span></span><span></span><span></span><span></span>
      </span>
      <span class="brand-copy">
        <strong>Mockingbird</strong>
        <small>Interview review system</small>
      </span>
    </a>

    <nav>
      {#each tabs as tab}
        <a href={tab.href} class:active={page.url.pathname === tab.href}>
          <span class="tab-code num">{tab.code}</span>
          <span>{tab.label}</span>
        </a>
      {/each}
    </nav>

    {#if live.on}
      <a class="tally on" href="/session" aria-label="Go to the interview in progress">
        <span class="dot"></span>
        <span class="state">Live session</span>
        <span class="num count">{live.question}/{live.total}</span>
      </a>
    {:else}
      <div class="tally">
        <span class="dot"></span>
        <span class="state">System ready</span>
      </div>
    {/if}
  </div>
</header>

{@render children()}

<style>
  header {
    position: sticky;
    top: 0;
    z-index: 20;
    background: color-mix(in srgb, var(--bg-raised) 96%, transparent);
    border-top: 3px solid var(--signal);
    border-bottom: 1px solid var(--rule-strong);
    transition: background 320ms var(--ease), border-color 320ms var(--ease);
  }

  .strip {
    max-width: var(--page);
    margin: 0 auto;
    padding: 0 var(--s-5);
    min-height: 68px;
    display: flex;
    align-items: center;
    gap: var(--s-6);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    font-family: var(--font-structure);
    color: var(--fg);
    text-decoration: none;
    white-space: nowrap;
  }

  .brand-mark {
    display: grid;
    grid-template-columns: repeat(2, 7px);
    grid-template-rows: repeat(2, 7px);
    gap: 2px;
    padding: 5px;
    border: 1px solid var(--rule-strong);
    background: var(--bg);
  }
  .brand-mark span {
    background: var(--fg-faint);
    transition: background 260ms var(--ease);
  }
  .brand-mark span:first-child,
  .brand-mark.on span {
    background: var(--signal);
  }
  .brand-copy {
    display: grid;
    gap: 1px;
  }
  .brand-copy strong {
    font-family: var(--font-structure);
    font-size: var(--step-0);
    letter-spacing: -0.025em;
  }
  .brand-copy small {
    font-family: var(--font-data);
    font-size: 0.58rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-faint);
  }

  nav {
    display: flex;
    gap: var(--s-5);
    margin-right: auto;
  }

  nav a {
    position: relative;
    font-family: var(--font-structure);
    font-size: var(--step--1);
    font-weight: 500;
    color: var(--fg-quiet);
    text-decoration: none;
    display: grid;
    grid-template-columns: auto auto;
    align-items: baseline;
    gap: 7px;
    padding: 6px 0;
    transition: color 160ms var(--ease);
  }
  .tab-code {
    font-size: 0.58rem;
    letter-spacing: 0;
    color: var(--fg-faint);
  }
  nav a:hover {
    color: var(--fg);
  }
  nav a.active {
    color: var(--fg);
  }
  nav a.active::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: -6px;
    height: 1px;
    background: var(--signal-bright);
  }

  .tally {
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: var(--s-2);
    font-family: var(--font-structure);
    font-size: var(--step--2);
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--fg-faint);
    padding: 4px 9px 4px 7px;
    border: 1px solid var(--rule);
    border-radius: 0;
    white-space: nowrap;
  }
  .tally.on {
    color: var(--signal);
    border-color: color-mix(in srgb, var(--signal) 45%, transparent);
    background: color-mix(in srgb, var(--signal) 10%, transparent);
  }
  a.tally.on:hover {
    border-color: var(--signal);
    background: color-mix(in srgb, var(--signal) 18%, transparent);
  }

  .tally .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.5;
  }
  .tally.on .dot {
    opacity: 1;
    animation: breathe 2.6s var(--ease) infinite;
  }

  .count {
    font-size: var(--step--2);
    font-weight: 500;
    letter-spacing: 0;
    opacity: 0.75;
    border-left: 1px solid currentColor;
    margin-left: 2px;
    padding-left: var(--s-2);
  }

  /* The one authored motion in the product: a tally lamp that behaves like a lamp. */
  @keyframes breathe {
    0%,
    100% {
      opacity: 1;
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--signal) 50%, transparent);
    }
    50% {
      opacity: 0.55;
      box-shadow: 0 0 0 4px transparent;
    }
  }

  @media (max-width: 40rem) {
    .strip {
      height: auto;
      padding: var(--s-3) var(--s-4) var(--s-2);
      gap: var(--s-3) var(--s-4);
      flex-wrap: wrap;
    }
    nav {
      order: 3;
      width: 100%;
      gap: var(--s-4);
      margin-right: 0;
      border-top: 1px solid var(--rule);
      padding-top: var(--s-2);
    }
    .tally {
      margin-left: auto;
    }
    .brand-copy small {
      display: none;
    }
  }
</style>
