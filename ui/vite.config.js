import { sveltekit } from '@sveltejs/kit/vite';

export default {
  plugins: [sveltekit()],
  // In dev the UI runs on 5173 and the API on 8000; in the built artefact they are one origin.
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } }
};
