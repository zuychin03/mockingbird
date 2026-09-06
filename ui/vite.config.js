import { sveltekit } from '@sveltejs/kit/vite';

export default {
  plugins: [sveltekit()],
  // In dev the UI runs on 5173 and the API on 8000; in the built artefact they are one origin.
  // `ws` matters: the voice transport is a WebSocket under /api, and without it the proxy
  // forwards the handshake as plain HTTP and the socket never opens in dev.
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true } } }
};
