import adapter from '@sveltejs/adapter-static';

// SPA mode: one index.html, no prerendering, no Node runtime in the artefact. FastAPI serves
// the folder and falls back to index.html, so there is one process and one port.
export default {
  kit: {
    adapter: adapter({ fallback: 'index.html', pages: 'build', assets: 'build' }),
    prerender: { entries: [] }
  }
};
