/* Microphone capture: device rate in, 16 kHz int16 frames out.
 *
 * An AudioWorkletProcessor rather than ScriptProcessorNode (deprecated, and it runs on the main
 * thread, so a re-render stutters the capture) or MediaRecorder (container-wrapped, on its own
 * cadence). 12.7.
 *
 * The resampling is here rather than on the AudioContext because constructing a context at
 * 16 kHz is not free: the browser inserts its own converter with its own latency, and on Windows
 * the device is almost always 48 kHz regardless of what you ask for. So the context is created
 * at the device default, `sampleRate` is read, and the conversion happens once, here.
 *
 * Downsampling without a low-pass folds everything above 8 kHz back into the speech band as
 * alias, which ASR hears as noise it cannot explain. Two cascaded biquads at 7.2 kHz cost
 * almost nothing and remove it. Linear interpolation after that is the approximation worth
 * revisiting first if ASR accuracy ever disappoints -- a polyphase kernel would be better and
 * is not worth it until something says otherwise.
 */

const TARGET_RATE = 16000;
const FRAME = 320; // 20 ms at 16 kHz

function biquadLowPass(fc, fs) {
  const w0 = (2 * Math.PI * fc) / fs;
  const cos = Math.cos(w0);
  const alpha = Math.sin(w0) / (2 * Math.SQRT1_2);
  const a0 = 1 + alpha;
  return {
    b0: ((1 - cos) / 2) / a0,
    b1: (1 - cos) / a0,
    b2: ((1 - cos) / 2) / a0,
    a1: (-2 * cos) / a0,
    a2: (1 - alpha) / a0,
    x1: 0, x2: 0, y1: 0, y2: 0
  };
}

function step(s, x) {
  const y = s.b0 * x + s.b1 * s.x1 + s.b2 * s.x2 - s.a1 * s.y1 - s.a2 * s.y2;
  s.x2 = s.x1; s.x1 = x;
  s.y2 = s.y1; s.y1 = y;
  return y;
}

class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.lp1 = biquadLowPass(TARGET_RATE * 0.45, sampleRate);
    this.lp2 = biquadLowPass(TARGET_RATE * 0.45, sampleRate);
    this.acc = new Float32Array(8192);
    this.accLen = 0;
    this.pos = 0;
    this.frame = new Float32Array(FRAME);
    this.frameLen = 0;
    this.running = false;
    this.port.onmessage = (e) => { this.running = !!e.data.running; };
  }

  emit() {
    let peak = 0;
    let sum = 0;
    const pcm = new Int16Array(FRAME);
    for (let i = 0; i < FRAME; i++) {
      const v = Math.max(-1, Math.min(1, this.frame[i]));
      pcm[i] = v * 32767;
      sum += v * v;
      if (Math.abs(v) > peak) peak = Math.abs(v);
    }
    // The level is computed here and not asked of the server: the pre-flight meter has to work
    // before any socket exists, and echoing a number back per frame would double the traffic
    // for something already known on this side. Samples only leave when the mic is open --
    // metering between turns is fine, streaming between turns is not.
    const rms = Math.sqrt(sum / FRAME);
    if (this.running) this.port.postMessage({ pcm: pcm.buffer, rms, peak }, [pcm.buffer]);
    else this.port.postMessage({ rms, peak });
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;

    for (let i = 0; i < input.length; i++) {
      this.acc[this.accLen++] = step(this.lp2, step(this.lp1, input[i]));
    }

    while (this.pos + 1 < this.accLen) {
      const i0 = this.pos | 0;
      const frac = this.pos - i0;
      this.frame[this.frameLen++] = this.acc[i0] * (1 - frac) + this.acc[i0 + 1] * frac;
      if (this.frameLen === FRAME) {
        this.emit();
        this.frameLen = 0;
      }
      this.pos += this.ratio;
    }

    const consumed = this.pos | 0;
    if (consumed > 0) {
      this.acc.copyWithin(0, consumed, this.accLen);
      this.accLen -= consumed;
      this.pos -= consumed;
    }
    return true;
  }
}

registerProcessor('mic-capture', MicCapture);
