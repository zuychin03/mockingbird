/* The browser half of the voice transport: microphone up, speech down, one WebSocket.
 *
 * Nothing here knows what an interview is. It moves audio and reports what happened, so the
 * voice UI (12.4) can be built and rebuilt against a seam that does not change.
 *
 * Two things in here are correctness rather than plumbing.
 *
 * **Playback runs on a monotonic cursor.** Scheduling each chunk with `start(0)` as it arrives
 * is where clicks come from -- chunks land whenever the socket delivers them and butt up against
 * each other with gaps and overlaps. Instead every chunk is scheduled at an accumulating time,
 * a jitter buffer ahead of now, so a bursty local GPU cannot be heard. 12.7.
 *
 * **A cut reports how much was actually heard.** 12.4 requires that a barge-in truncates the
 * context to what the candidate heard, and only this side knows where playback had got to.
 * The server sends the line in one burst, so what it sent says nothing about what was heard.
 *
 * Archival: 12.7 suggests running MediaRecorder in parallel to keep the answer audio. It is not
 * here, deliberately -- the full PCM already reaches the server, which writes a wav beside the
 * session. That is uncompressed and can be re-run through ASR later, which the compressed
 * container cannot. It costs disk (about 2 MB per minute) and that is the trade being made.
 */

const JITTER = 0.15; // 12.7 asks for 100-200 ms; a local GPU under load delivers in bursts

const CONSTRAINTS = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1
  }
};

export class Voice {
  constructor(handlers = {}) {
    this.on = handlers;
    this.ctx = null;
    this.ws = null;
    this.stream = null;
    this.node = null;
    this.settings = {};
    this.open = false;

    this.cursor = 0;
    this.playing = null;
    this.sources = [];
  }

  /* Must be called from a user gesture: an AudioContext created without one starts suspended
   * and stays that way, which looks exactly like a broken microphone. 12.7. */
  async connect() {
    this.stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
    const track = this.stream.getAudioTracks()[0];
    // What was asked for and what was granted are different things, and the difference is
    // silent. Chrome may decline to honour any of these.
    this.settings = track.getSettings();

    this.ctx = new AudioContext();
    await this.ctx.resume();
    await this.ctx.audioWorklet.addModule('/worklets/mic-capture.js');

    this.node = new AudioWorkletNode(this.ctx, 'mic-capture');
    this.node.port.onmessage = (e) => this.fromWorklet(e.data);

    // A worklet is only pulled while it reaches the destination, so it has to be connected --
    // but connecting it directly plays the microphone back out of the speakers. Through a
    // silent gain it runs and is heard by nobody.
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    this.ctx.createMediaStreamSource(this.stream).connect(this.node);
    this.node.connect(mute).connect(this.ctx.destination);

    await this.openSocket();
    navigator.mediaDevices.addEventListener('devicechange', this.deviceChange);
    track.addEventListener('ended', this.deviceChange);

    return {
      rate: this.ctx.sampleRate,
      device: track.label,
      settings: this.settings
    };
  }

  openSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.ws = new WebSocket(`${proto}://${location.host}/api/voice`);
    this.ws.binaryType = 'arraybuffer';
    this.ws.onmessage = (e) => this.fromServer(e);
    this.ws.onclose = () => this.on.closed?.();
    return new Promise((ok, fail) => {
      this.ws.addEventListener('open', () => {
        this.send({
          t: 'hello',
          rate: this.ctx.sampleRate,
          device: this.settings.deviceId ?? '',
          settings: this.settings
        });
        ok();
      });
      this.ws.addEventListener('error', fail, { once: true });
    });
  }

  send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  /* --- microphone ------------------------------------------------------------------ */

  fromWorklet(m) {
    this.on.level?.(m.rms, m.peak);
    if (m.pcm && this.ws?.readyState === WebSocket.OPEN) this.ws.send(m.pcm);
  }

  /* Tap-to-talk by default: 12.6 makes it so because interview answers are long and full of
   * thinking pauses, and a false cut truncates the answer being scored. `live` asks the server
   * to end the turn itself after `pause` seconds of quiet (FR-26's opt-in). */
  startTalking({ live = false, pause } = {}) {
    if (this.open) return;
    this.open = true;
    this.send(live ? { t: 'mic_open', live: true, pause } : { t: 'mic_open' });
    this.node?.port.postMessage({ running: true });
  }

  stopTalking() {
    if (!this.open) return;
    this.open = false;
    this.node?.port.postMessage({ running: false });
    this.send({ t: 'mic_close' });
  }

  /* The server ended the turn -- a live pause or the length cap -- so there is nothing to
   * close, only this side's flag to bring into line. Left set, the next press returns early
   * from startTalking and the microphone never reopens. */
  ended() {
    if (!this.open) return;
    this.open = false;
    this.node?.port.postMessage({ running: false });
  }

  /* Live switched off mid-answer: the answer now ends when the candidate says so. */
  manual() {
    if (this.open) this.send({ t: 'manual' });
  }

  /* --- speech ---------------------------------------------------------------------- */

  fromServer(e) {
    if (typeof e.data !== 'string') return this.enqueue(e.data);
    const m = JSON.parse(e.data);
    if (m.t === 'speech') {
      this.playing = { id: m.id, rate: m.rate, seconds: m.seconds, text: m.text, startedAt: 0 };
      this.cursor = 0;
      this.sources = [];
    } else if (m.t === 'speech_end') {
      this.armEnd();
    }
    this.on.message?.(m);
  }

  enqueue(buffer) {
    const p = this.playing;
    if (!p) return;
    const pcm = new Int16Array(buffer);
    const buf = this.ctx.createBuffer(1, pcm.length, p.rate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;

    // First chunk sets the clock; later chunks follow it. If the socket stalls long enough for
    // the cursor to fall behind the context, it is reset rather than scheduled in the past --
    // which would otherwise play everything at once.
    const now = this.ctx.currentTime;
    if (!this.cursor || this.cursor < now) {
      this.cursor = now + JITTER;
      if (!p.startedAt) p.startedAt = this.cursor;
    }
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    src.start(this.cursor);
    this.cursor += buf.duration;
    this.sources.push(src);
  }

  armEnd() {
    const p = this.playing;
    const last = this.sources[this.sources.length - 1];
    if (!p || !last) return;
    last.onended = () => {
      if (this.playing?.id !== p.id) return;
      this.send({ t: 'played', id: p.id, heard_ms: Math.round(p.seconds * 1000) });
      this.playing = null;
      this.sources = [];
      this.on.spoken?.(p);
    };
  }

  /* Barge-in. Cuts the audio and reports the position; 12.4 requires the remainder to be shown
   * struck through rather than deleted, so the server is told where we got to, not that it
   * should forget the line. */
  cut() {
    const p = this.playing;
    if (!p) return 0;
    const heard = Math.max(0, Math.min(this.ctx.currentTime - p.startedAt, p.seconds));
    for (const s of this.sources) {
      try { s.onended = null; s.stop(); } catch { /* already finished */ }
    }
    this.send({ t: 'cut', id: p.id, heard_ms: Math.round(heard * 1000) });
    this.playing = null;
    this.sources = [];
    this.on.spoken?.({ ...p, heard });
    return heard;
  }

  say(text) {
    this.send({ t: 'say', text });
  }

  /* --- lifecycle ------------------------------------------------------------------- */

  /* Plugging in a headset mid-session must not kill the run (12.7). The track ending is the
   * signal that matters; `devicechange` alone fires for unrelated devices too. */
  deviceChange = async () => {
    const track = this.stream?.getAudioTracks()[0];
    if (track && track.readyState === 'live') return this.on.devices?.();
    try {
      this.stream?.getTracks().forEach((t) => t.stop());
      this.stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
      const fresh = this.stream.getAudioTracks()[0];
      this.settings = fresh.getSettings();
      this.ctx.createMediaStreamSource(this.stream).connect(this.node);
      fresh.addEventListener('ended', this.deviceChange);
      this.on.devices?.(fresh.label);
    } catch (err) {
      this.on.lost?.(err);
    }
  };

  async close() {
    navigator.mediaDevices.removeEventListener('devicechange', this.deviceChange);
    this.stopTalking();
    this.send({ t: 'bye' });
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ws?.close();
    await this.ctx?.close();
    this.ctx = null;
  }
}
