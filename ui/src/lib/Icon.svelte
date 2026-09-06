<script>
  // One stroke weight, one grid, one join style. Drawn rather than borrowed so the marks sit
  // in the same world as the rules and slugs around them.
  let { name, size = 16 } = $props();

  const paths = {
    up: 'M8 12.5V3.5M8 3.5 4.5 7M8 3.5 11.5 7',
    down: 'M8 3.5v9M8 12.5 4.5 9M8 12.5 11.5 9',
    edit: 'M3 13h2.5l7-7a1.77 1.77 0 0 0-2.5-2.5l-7 7V13ZM9.75 4.25l2 2',
    remove: 'M3.5 5h9M6.5 5V3.5h3V5M5 5l.6 8h4.8L11 5M7 7.5v3M9 7.5v3',
    add: 'M8 3.5v9M3.5 8h9',
    check: 'M3.5 8.5 6.5 11.5 12.5 4.5',
    close: 'M4 4l8 8M12 4l-8 8',
    clock: 'M8 4.5V8l2.25 1.5',
    back: 'M12.5 8h-9M7 3.5 2.5 8 7 12.5',
    mic: 'M8 2.25a1.6 1.6 0 0 1 1.6 1.6v3.9a1.6 1.6 0 0 1-3.2 0v-3.9A1.6 1.6 0 0 1 8 2.25ZM4.6 7.4a3.4 3.4 0 0 0 6.8 0M8 10.8v2.95',
    sound: 'M3 6.25h1.9L7.4 4.1v7.8L4.9 9.75H3zM9.9 6.1a2.6 2.6 0 0 1 0 3.8M11.7 4.6a5 5 0 0 1 0 6.8'
  };
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  {#if name === 'clock'}
    <circle cx="8" cy="8" r="5.5" />
  {/if}
  {#if paths[name]}
    <path d={paths[name]} />
  {/if}
</svg>

<style>
  svg {
    display: block;
    flex: none;
  }
</style>
