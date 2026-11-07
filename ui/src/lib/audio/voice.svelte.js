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
 * backchannel and no keystroke that can trigger a false one.
 *
 * **Live mode** (FR-26's opt-in) keeps that true by staying half-duplex: the microphone opens
 * when the interviewer finishes, the server ends the answer after the chosen pause, and the
 * answer is sent without a press. The candidate's voice never interrupts the interviewer, so
 * 12.4's false-barge-in guards are still not needed; the talk button and Space still cut in.
 */

import { Voice } from './transport.js';

/* 12.6: users release on a thinking pause, so releasing keeps recording briefly and says so. */
const TAIL_MS = 700;
const BARS = 14;
const METER_MS = 50;
const CAPTIONS_KEY = 'mockingbird.captions';
const LIVE_KEY = 'mockingbird.live';
const PAUSE_KEY = 'mockingbird.pause';
/* Replayed over the recorded answers (22/09): 1.5 s cut one answer at a pause between
 * sentences, 2.5 s cut none. FR-26 makes it a setting because thinking pauses vary by person. */
export const PAUSES = [1.5, 2.5, 4, 6];
const PAUSE_DEFAULT = 2.5;

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
  live: false,
  pause: PAUSE_DEFAULT,
  liveReady: false,
  liveWhy: null,
  error: null,
  // Separate from `error`: a capped answer is a bounded, successful end, and colouring it as a
  // failure would tell the candidate their answer was lost when it was kept.
  notice: null,
  thinkingSince: 0
});

let link = null;
let tailTimer = null;
let lastMeter = 0;
// Plain rather than state: they route events and nothing renders them.
// A line was asked for and no answer has been started since, so live mode opens the mic
// once it has been heard.
let awaitingAnswer = false;
// The turn in progress was opened live, so its transcript is sent rather than adopted.
let liveTurn = false;

export function loadPreferences() {
  try {
    const saved = localStorage.getItem(CAPTIONS_KEY);
    if (saved !== null) voice.captionsOn = saved === '1';
    voice.live = localStorage.getItem(LIVE_KEY) === '1';
    const pause = Number(localStorage.getItem(PAUSE_KEY));
    if (PAUSES.includes(pause)) voice.pause = pause;
  } catch {
    // Private windows and blocked site data both throw. A caption preference is not worth
    // failing over; the default stands.
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* see loadPreferences */
  }
}

export function setLive(on) {
  voice.live = on;
  remember(LIVE_KEY, on ? '1' : '0');
  if (on && voice.liveReady && awaitingAnswer && voice.phase === 'idle') startTalking();
  if (!on && liveTurn && (voice.phase === 'listening' || voice.phase === 'tail')) {
    liveTurn = false;
    link?.manual();
  }
}

export function setPause(seconds) {
  if (!PAUSES.includes(seconds)) return;
  voice.pause = seconds;
  remember(PAUSE_KEY, String(seconds));
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
      if (voice.live && voice.liveReady && awaitingAnswer && voice.phase === 'idle') startTalking();
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
    voice.liveReady = !!m.live_ready;
    voice.liveWhy = m.live_why ?? null;
  } else if (m.t === 'partial') {
    // Append-only by construction: the server commits whole slices and never revises one, so
    // text that has been read does not reflow under the eye. 12.4.
    voice.partial = m.text;
  } else if (m.t === 'transcript') {
    voice.partial = m.text;
    const send = liveTurn && m.answer !== false;
    voice.transcript = { text: m.text, id: ++transcriptId, send, live: liveTurn };
    if (send) {
      // Straight to thinking: passing through idle would let the next turn open the mic
      // before the page has sent this one.
      setThinking(true);
    } else if (voice.phase === 'reading') {
      voice.phase = 'idle';
      if (liveTurn && voice.live) {
        voice.notice = m.text
          ? `Heard only "${m.text}", so nothing was sent. Still listening.`
          : 'Nothing was recognised, so nothing was sent. Still listening.';
        awaitingAnswer = true;
        startTalking({ keepNotice: true });
      }
    }
  } else if (m.t === 'speech') {
    voice.caption = m.text;
    voice.interrupted = null;
    voice.phase = 'speaking';
  } else if (m.t === 'interrupted') {
    // Not deleted. 12.4: the remainder is shown struck through, because dropping it destroys
    // both the record and the candidate's understanding of what just happened.
    voice.interrupted = { heard: m.heard, unheard: m.unheard };
    // The phase is deliberately not set here. Esc cuts the speech *without* opening the
    // microphone (12.8), so treating this message as "listening" lit REC over a closed mic,
    // dropped the answer, and then wedged in `tail` because stopTalking had nothing to close.
  } else if (m.t === 'utterance') {
    voice.recorded = { seconds: m.seconds, peak: m.peak, path: m.path };
    if (m.ended) link?.ended();
    if (m.capped) {
      // What happened, not a limit derived from it: rounding the cap to minutes read
      // "0-minute limit" at a short one, and the candidate cares how long was captured.
      const mins = Math.floor(m.seconds / 60);
      const length = mins >= 1
        ? `${mins} minute${mins === 1 ? '' : 's'}`
        : `${Math.round(m.seconds)} seconds`;
      voice.notice =
        `The microphone was open for ${length}, so the answer was closed automatically. ` +
        'Everything up to that point was kept.';
    }
    if (voice.thinkingSince) voice.phase = 'thinking';
    else voice.phase = voice.asrReady && m.seconds > 0 ? 'reading' : 'idle';
  } else if (m.t === 'error') {
    voice.error = m.why;
  }
}

/* Called once the answer carrying this recording has been accepted. Without it the path
 * outlives its answer, and the next question -- typed, with nothing said aloud -- would submit
 * the previous question's audio as its own. */
export function clearRecording() {
  voice.recorded = null;
}

export function say(text) {
  if (!link || !text) return;
  awaitingAnswer = true;
  link.say(text);
}

/* Pressing talk while the interviewer is speaking is the barge-in. */
export function startTalking({ keepNotice = false } = {}) {
  if (!link) return;
  // Cleared before the cut: cutting reports the line as spoken, and live mode would answer
  // that by opening the microphone from inside this call.
  awaitingAnswer = false;
  clearTimeout(tailTimer);
  tailTimer = null;
  if (voice.phase === 'speaking') link.cut();
  voice.bars = new Array(BARS).fill(0);
  voice.recorded = null;
  voice.partial = '';
  if (!keepNotice) voice.notice = null;
  liveTurn = voice.live && voice.liveReady;
  link.startTalking(liveTurn ? { live: true, pause: voice.pause } : {});
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
 * agent's speech that is not "start talking over it". In live mode the microphone does open
 * afterwards, as it would had the line finished: the floor is the candidate's either way. */
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
  awaitingAnswer = false;
  liveTurn = false;
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
