/* Voice as the interview page sees it: one state, one level, one caption.
 *
 * The transport moves bytes; this decides what the room is doing. They are separate because
 * 12.4 makes the state indicator the single highest-value affordance in the voice UI -- it is
 * what distinguishes "dead mic" from "listening, you are quiet" -- and a state that is derived
 * from socket messages scattered through a component is a state that goes wrong quietly.
 *
 * `phase` is the whole model:
 *
 *   off        voice is not switched on
 *   idle       on, and waiting for you
 *   listening  the microphone is open and the meter is live
 *   tail       you released, and it is still recording for a moment (12.6)
 *   reading    the tail of your answer is being recognised
 *   thinking   your answer has gone to the model
 *   speaking   the interviewer is talking
 *
 * Barge-in needs no VAD guards here and that is 12.6's corollary, not an omission: with
 * tap-to-talk, pressing the talk button *is* the interrupt signal, so there is no cough, no
 * backchannel and no keystroke that can trigger a false one. The minimum-duration and
 * minimum-word-count guards 12.4 asks for belong with VAD, whenever VAD becomes opt-in.
 */

import { Voice } from './transport.js';

/* 12.6: users release on a thinking pause, so releasing keeps recording briefly and says so. */
const TAIL_MS = 700;
const BARS = 14;
const METER_MS = 50;
const CAPTIONS_KEY = 'mockingbird.captions';

export const voice = $state({
  phase: 'off',
  level: 0,
  bars: new Array(BARS).fill(0),
  caption: '',
  captionsOn: true,
  device: '',
  granted: null,
  recorded: null,
  interrupted: null,
  partial: '',
  transcript: null,
  asrReady: false,
  asrWhy: null,
  error: null,
  thinkingSince: 0
});

let link = null;
let tailTimer = null;
let lastMeter = 0;

export function loadPreferences() {
  try {
    const saved = localStorage.getItem(CAPTIONS_KEY);
    if (saved !== null) voice.captionsOn = saved === '1';
  } catch {
    // Private windows and blocked site data both throw. A caption preference is not worth
    // failing over; the default stands.
  }
}

export function toggleCaptions() {
  voice.captionsOn = !voice.captionsOn;
  try {
    localStorage.setItem(CAPTIONS_KEY, voice.captionsOn ? '1' : '0');
  } catch {
    /* see above */
  }
}

function meter(rms) {
  voice.level = rms;
  const now = performance.now();
  if (now - lastMeter < METER_MS) return;
  lastMeter = now;
  // A fixed scale, not an auto-ranging one: the meter has to be able to read *low*, because
  // "listening, you are quiet" is the state it exists to distinguish from a dead microphone.
  voice.bars = [...voice.bars.slice(1), Math.min(1, rms * 12)];
}

/* Must be called from a click: an AudioContext built without a user gesture starts suspended
 * and never recovers, which on screen is indistinguishable from a broken microphone. 12.7. */
export async function enable() {
  if (link) return true;
  voice.error = null;
  const v = new Voice({
    level: meter,
    message: onMessage,
    spoken: () => {
      if (voice.phase === 'speaking') voice.phase = 'idle';
    },
    devices: (label) => label && (voice.device = label),
    lost: (err) => {
      voice.error = describe(err);
      voice.phase = 'off';
    },
    closed: () => {
      if (voice.phase !== 'off') voice.phase = 'off';
      link = null;
    }
  });
  try {
    const info = await v.connect();
    link = v;
    voice.device = info.device || 'the default microphone';
    voice.granted = info.settings;
    voice.phase = 'idle';
    return true;
  } catch (err) {
    voice.error = describe(err);
    return false;
  }
}

function describe(err) {
  const name = err?.name || '';
  if (name === 'NotAllowedError')
    return 'The browser blocked the microphone. Allow it for this page and switch voice on again.';
  if (name === 'NotFoundError') return 'No microphone was found.';
  if (name === 'NotReadableError')
    return 'Another application is holding the microphone. Close it and try again.';
  return err?.message || 'The microphone could not be opened.';
}

let transcriptId = 0;

function onMessage(m) {
  if (m.t === 'ready') {
    voice.asrReady = !!m.asr_ready;
    voice.asrWhy = m.asr_why ?? null;
  } else if (m.t === 'partial') {
    // Append-only by construction: the server commits whole slices and never revises one, so
    // text that has been read does not reflow under the eye. 12.4.
    voice.partial = m.text;
  } else if (m.t === 'transcript') {
    voice.partial = m.text;
    voice.transcript = { text: m.text, id: ++transcriptId };
    if (voice.phase === 'reading') voice.phase = 'idle';
  } else if (m.t === 'speech') {
    voice.caption = m.text;
    voice.interrupted = null;
    voice.phase = 'speaking';
  } else if (m.t === 'interrupted') {
    // Not deleted. 12.4: the remainder is shown struck through, because dropping it destroys
    // both the record and the candidate's understanding of what just happened.
    voice.interrupted = { heard: m.heard, unheard: m.unheard };
    voice.phase = 'listening';
  } else if (m.t === 'utterance') {
    voice.recorded = { seconds: m.seconds, peak: m.peak, path: m.path };
    if (voice.thinkingSince) voice.phase = 'thinking';
    else voice.phase = voice.asrReady && m.seconds > 0 ? 'reading' : 'idle';
  } else if (m.t === 'error') {
    voice.error = m.why;
  }
}

export function say(text) {
  if (link && text) link.say(text);
}

/* Pressing talk while the interviewer is speaking is the barge-in. */
export function startTalking() {
  if (!link) return;
  clearTimeout(tailTimer);
  tailTimer = null;
  if (voice.phase === 'speaking') link.cut();
  voice.bars = new Array(BARS).fill(0);
  voice.recorded = null;
  voice.partial = '';
  link.startTalking();
  voice.phase = 'listening';
}

export function stopTalking() {
  if (!link || (voice.phase !== 'listening' && voice.phase !== 'tail')) return;
  voice.phase = 'tail';
  clearTimeout(tailTimer);
  tailTimer = setTimeout(() => {
    tailTimer = null;
    link?.stopTalking();
  }, TAIL_MS);
}

export function toggleTalking() {
  if (voice.phase === 'listening' || voice.phase === 'tail') stopTalking();
  else startTalking();
}

/* Esc. Stops the interviewer without opening the microphone -- 12.8 asks for a way out of the
 * agent's speech that is not "start talking over it". */
export function hush() {
  if (link && voice.phase === 'speaking') link.cut();
}

export function setThinking(on) {
  voice.thinkingSince = on ? Date.now() : 0;
  if (on) voice.phase = 'thinking';
  else if (voice.phase === 'thinking') voice.phase = 'idle';
}

export async function disable() {
  clearTimeout(tailTimer);
  tailTimer = null;
  const v = link;
  link = null;
  voice.phase = 'off';
  voice.bars = new Array(BARS).fill(0);
  voice.caption = '';
  await v?.close();
}

export const LABELS = {
  off: 'Voice off',
  idle: 'Ready when you are',
  listening: 'Listening',
  tail: 'Still capturing',
  reading: 'Reading your answer',
  thinking: 'Considering your answer',
  speaking: 'Interviewer speaking'
};
