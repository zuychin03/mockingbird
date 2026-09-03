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
      <svg class="brand-mark" viewBox="15 28 485 365" aria-hidden="true" focusable="false">
        <path class="ink-stroke" stroke-width="15" stroke-linecap="butt" d="M232 303 290 378M291 305l74 73" />
        <path class="ink" d="M224 183 135 272l33-3L23 356c21 3 42 5 63 6l73-50-3-3c30-17 58-38 83-62-14-19-19-41-15-64Z" />
        <path class="accent" d="M354 133c-30 4-60 9-89 14-21 4-32 21-33 46-1 23 10 46 36 56-11 16-28 29-51 40 26-4 46-9 62-16 18-7 28-15 38-25 17-18 26-44 31-74l6-41Z" />
        <path class="ink" fill-rule="evenodd" d="M488 72 446 62c-17-19-40-27-67-24-24 3-38 20-51 39l-16 26-36 30 91-14c-3 29-7 56-14 82-8 25-23 49-45 68-12 10-24 17-35 19l-108 22c61 3 122 2 178-5 32-14 62-40 80-70 15-27 14-58 6-86l-6-20c-3-9-1-17 6-26l11-13 48-18Zm-88 0a10 10 0 1 0 20 0 10 10 0 0 0-20 0Z" />
        <rect class="ink" x="254" y="169" width="70" height="12" rx="1" />
        <rect class="ink" x="254" y="195" width="70" height="12" rx="1" />
        <rect class="ink" x="254" y="221" width="39" height="12" rx="1" />
        <rect class="ink" x="102" y="370" width="349" height="15" rx="7.5" />
      </svg>
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
    width: 42px;
    height: 36px;
    flex: none;
    overflow: visible;
  }
  .brand-mark .ink {
    fill: var(--fg);
  }
  .brand-mark .ink-stroke {
    fill: none;
    stroke: var(--fg);
  }
  .brand-mark .accent {
    fill: var(--signal);
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
    .brand-mark {
      width: 38px;
      height: 33px;
    }
  }
</style>
