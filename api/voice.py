"""The voice transport: microphone up, speech down, over one WebSocket.

**Why a WebSocket and not WebRTC.** 11.9 originally chose WebRTC because browser echo
cancellation was believed to require the agent's audio to arrive as a peer track. That was
measured on 2026-09-06 and it is not true: with `RTCPeerConnection` blocked outright, an
`<audio>` tag was still cancelled (0.7x with AEC on against 4.8x with it off). Cancellation
lives in the capture pipeline, applied by `getUserMedia({echoCancellation:true})`, so it
survives whatever the audio is shipped over. A socket carrying PCM is less machinery and
measured 362 ms of acoustic round trip against 487 ms through WebRTC.

**The protocol.** Control is JSON text, audio is raw int16 (see `app/audio.py`). Up:

    hello {rate, settings}     what the browser actually granted, not what we asked for
    mic_open / mic_close       one press-to-talk turn; binary frames arrive between them
    mic_open {live, pause}     live mode: the server ends the turn itself after `pause` s quiet
    manual                     live switched off mid-answer; this turn now ends on mic_close
    say {text}                 render and stream this line down
    cut {id, heard_ms}         barge-in: the candidate spoke over us
    played {id, heard_ms}      playback finished on its own

Down:

    ready {frame_ms, rate, voice, asr, asr_ready, live_ready}
    partial {text}             the answer so far, recognised while it is still being given
    transcript {text, answer}  the whole answer, once the tail has been read; `answer` is false
                               for silence or noise alone, which live mode must not send
    utterance {seconds, peak, path, ended}   ended: None (released), "cap" or "pause"
    speech {id, rate, seconds} then binary chunks, then speech_end {id}
    interrupted {id, heard, unheard}   after a cut, the line split where it was cut

**Audio is never sent while the receive loop is blocked.** Streaming happens in a task and the
loop keeps reading, because a barge-in that cannot be heard until the agent stops talking is
not a barge-in. 12.4 also requires that a cut truncates the transcript to what was actually
heard, so the client reports playback position and the server never guesses it from what it
sent.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import audio, endpoint, listen, speech

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live_session.json"
SESSIONS = ROOT / "data" / "sessions"
LOOSE = ROOT / "data" / "voice"

router = APIRouter()

# The answer is read in slices while it is still being given, so the composer fills as the
# candidate talks and only the tail is left when they stop. Measured on mains with the language
# model resident, a slice reads in well under a second (an 84 s answer whole in 2.2 s), so the
# backlog drains rather than growing.
SLICE_MIN = 6.0
SLICE_MAX = 14.0

# Tap-to-talk has no natural end (12.6): nothing bounds an open microphone, and the samples
# stay in memory for the whole of it. The client wedging with the microphone open is not
# hypothetical -- a phase bug did exactly that, showing REC over a socket that had never been
# opened. The cap sits far past any real answer (the longest measured here is 84 s) so it ends
# stuck turns and nothing else, and it ends them by closing the turn the normal way, so the
# audio and the transcript both survive.
UTTERANCE_MAX = 300.0

# Live mode reads the answer up to any pause this long straight away, instead of waiting for a
# 6 s slice. The pause may be the end, so starting the read here puts its cost inside the wait
# for the endpoint rather than after.
PAUSE_SLICE = 0.8
# Into the silence, so the slice does not clip the last word's release.
PAUSE_PAD = 0.2


def audio_dir() -> Path:
    """Where an answer's audio lands.

    Beside its session when there is one, so listening back to a run does not mean matching
    timestamps by hand; in a loose folder otherwise, because the audio check runs before any
    session exists and must not need one.
    """
    try:
        sid = json.loads(LIVE.read_text(encoding="utf-8")).get("session_id")
        if sid:
            return SESSIONS / sid / "audio"
    except (OSError, ValueError, AttributeError):
        pass
    return LOOSE


def write_answer(d: Path, data: bytes) -> Path:
    """Write one answer's wav under a name no other answer holds.

    Seconds are not fine enough: a one-second stray turn followed straight by a real one lands
    in the same second, and two answers in that directory already sit a second apart. The name
    carries milliseconds and is created **exclusively**, so the fallback covers the case a
    check-then-write cannot -- two browser tabs on one session writing at once, where the
    check passes for both and the second silently overwrites the first.
    """
    t = time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + "-%03d" % (t % 1 * 1000)
    f = d / ("answer-%s.wav" % stamp)
    try:
        with open(f, "xb") as out:
            out.write(data)
    except FileExistsError:
        f = d / ("answer-%s-%s.wav" % (stamp, uuid.uuid4().hex[:6]))
        f.write_bytes(data)
    return f


class Link:
    """One browser, one socket, for the length of a session."""

    def __init__(self, ws: WebSocket, engine: speech.TtsEngine,
                 asr: listen.AsrEngine | None = None, vad: endpoint.Silero | None = None) -> None:
        self.ws = ws
        self.engine = engine
        self.asr = asr
        self.vad_engine = vad
        self.vad: endpoint.Vad | None = None
        self.endpointer: endpoint.Endpointer | None = None
        self.utterance: audio.Utterance | None = None
        self.speech: audio.Speech | None = None
        self.task: asyncio.Task | None = None
        self.asr_task: asyncio.Task | None = None
        self.heard: list[str] = []
        self.committed = 0
        self.next_id = 1
        self.client: dict = {}

    async def send(self, **msg) -> None:
        await self.ws.send_text(audio.encode(msg))

    async def run(self) -> None:
        why = self.asr.available() if hasattr(self.asr, "available") else None
        live_why = (self.vad_engine.available() if self.vad_engine is not None
                    else "voice activity detection is not configured")
        # Live mode sends answers nobody reviewed first, so it needs the recogniser as well as
        # the endpointer: an answer that ends by itself with no text would have nothing to send.
        if live_why is None and (self.asr is None or why is not None):
            live_why = "speech recognition is not available"
        await self.send(t="ready", frame_ms=audio.FRAME_MS, rate=audio.MIC_RATE,
                        voice=speech.describe(), asr=listen.describe(),
                        asr_ready=self.asr is not None and why is None, asr_why=why,
                        live_ready=live_why is None, live_why=live_why)
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await self.on_audio(msg["bytes"])
            elif msg.get("text") is not None:
                if await self.on_control(audio.decode(msg["text"])):
                    return

    async def on_audio(self, pcm: bytes) -> None:
        # Audio arriving outside a press-to-talk turn is dropped rather than buffered: the tail
        # of a released button is worth nothing and silently recording between turns is exactly
        # what a local-only product must not do.
        if self.utterance is None:
            return
        # No level is echoed back: the worklet already has it, the pre-flight meter has to work
        # before this socket exists, and returning one per frame doubles the traffic to say
        # something the other end knows.
        self.utterance.add(pcm)
        if self.utterance.seconds >= UTTERANCE_MAX:
            await self.finish_utterance(ended="cap")
        elif self.endpointer is not None and self.endpointer.add(self.utterance.chunks[-1]):
            await self.finish_utterance(ended="pause")

    async def on_control(self, m: dict) -> bool:
        kind = m.get("t")
        if kind == "hello":
            self.client = {k: m.get(k) for k in ("rate", "settings", "device")}
        elif kind == "mic_open":
            self.utterance = audio.Utterance()
            self.heard, self.committed = [], 0
            self.endpointer = self.endpointer_for(m) if m.get("live") else None
            if self.asr is not None:
                self.asr_task = asyncio.create_task(self.read_along())
        elif kind == "mic_close":
            await self.finish_utterance()
        elif kind == "manual":
            self.endpointer = None
        elif kind == "say":
            await self.say(str(m.get("text") or ""))
        elif kind in ("cut", "played"):
            await self.finish_speech(m)
        elif kind == "bye":
            return True
        elif kind == "bad":
            await self.send(t="error", why=m.get("why", "bad control frame"))
        return False

    def endpointer_for(self, m: dict) -> endpoint.Endpointer | None:
        """None leaves the turn to the client, exactly as tap-to-talk: a live request the
        server cannot honour degrades to a turn that ends when the candidate says so."""
        if self.vad_engine is None or self.asr is None or self.vad_engine.available():
            return None
        if self.vad is None:
            self.vad = self.vad_engine.load()
        return endpoint.Endpointer(self.vad, endpoint.clamp_pause(m.get("pause")))

    def next_cut(self, u: audio.Utterance) -> int | None:
        """How many uncommitted samples to read next, or None to wait for more."""
        ep = self.endpointer
        if ep is not None:
            onset = ep.pause_onset(PAUSE_SLICE)
            if onset is not None and ep.speech_between(self.committed, onset):
                return min(onset + int(PAUSE_PAD * u.rate), u.length) - self.committed
        pending = u.seconds - self.committed / u.rate
        if pending < SLICE_MIN:
            return None
        region = u.samples[self.committed:]
        return audio.split_at_pause(region, u.rate, SLICE_MIN - 2.0, min(pending, SLICE_MAX))

    async def read_along(self) -> None:
        """Read the answer in slices while it is still being given.

        Each slice is recognised on its own, so a cut through a word would lose it from both
        sides -- `split_at_pause` puts the boundary in the quietest moment available rather
        than at a fixed offset. Work already done is kept even if the turn ends mid-pass: the
        slice belongs to that utterance either way, and throwing it away would mean reading the
        same seconds twice.
        """
        u = self.utterance
        while self.utterance is u and u is not None:
            cut = self.next_cut(u)
            if cut is None:
                await asyncio.sleep(0.2 if self.endpointer is not None else 0.4)
                continue
            region = u.samples[self.committed:self.committed + cut]
            text = await asyncio.to_thread(self.asr.transcribe, region, u.rate)
            self.committed += cut
            if text:
                self.heard.append(text)
            if self.utterance is not u:
                return
            if text:
                await self.send(t="partial", text=" ".join(self.heard))

    async def finish_utterance(self, ended: str | None = None) -> None:
        u, self.utterance = self.utterance, None
        if u is None:
            return
        ep, self.endpointer = self.endpointer, None
        path = ""
        if u.seconds > 0:
            d = audio_dir()
            d.mkdir(parents=True, exist_ok=True)
            f = write_answer(d, u.wav())
            path = str(f.relative_to(ROOT)).replace("\\", "/")
        # Announced before the slice in flight is awaited. When the server ended the turn, the
        # browser still shows "Listening" until it hears this, and a slice can take seconds:
        # long enough to keep talking into a microphone that is no longer recording.
        await self.send(t="utterance", seconds=round(u.seconds, 2), peak=round(u.peak, 4),
                        path=path, capped=ended == "cap", ended=ended)
        if self.asr_task is not None:
            # Let the slice in flight finish rather than racing it: it is reading seconds the
            # tail pass would otherwise have to read again.
            await self.asr_task
            self.asr_task = None
        if self.asr is None:
            return
        tail = u.samples[self.committed:]
        # After a live answer the tail is usually just the pause that ended it, its words
        # already read by the pause slice. Reading it again would only add a call to the wait
        # live mode exists to remove.
        silent = ep is not None and not ep.speech_between(self.committed, u.length)
        text = ""
        if len(tail) and not silent:
            text = await asyncio.to_thread(self.asr.transcribe, tail, u.rate)
        if text:
            self.heard.append(text)
        whole = " ".join(self.heard).strip()
        # Sent even when empty: silence has to read as "nothing was recognised" rather than as
        # a transcript that never arrived.
        await self.send(t="transcript", text=whole, seconds=round(u.seconds, 2),
                        answer=endpoint.is_answer(whole))

    async def say(self, text: str) -> None:
        if not text.strip():
            return
        await self.stop_speaking()
        # Synthesis blocks on a round trip to the voice server, and this event loop also carries
        # the microphone.
        # Off-thread or a two-second line stalls the uplink for two seconds.
        samples = await asyncio.to_thread(self.engine.say, text)
        sp = audio.Speech(id=self.next_id, text=text, rate=self.engine.rate, samples=samples)
        self.next_id += 1
        self.speech = sp
        self.task = asyncio.create_task(self.stream(sp))

    async def stream(self, sp: audio.Speech) -> None:
        try:
            await self.send(t="speech", id=sp.id, rate=sp.rate,
                            seconds=round(sp.seconds, 2), text=sp.text)
            for chunk in sp.chunks():
                await self.ws.send_bytes(chunk)
                sp.sent += 1
            await self.send(t="speech_end", id=sp.id)
        except (WebSocketDisconnect, RuntimeError):
            return

    async def finish_speech(self, m: dict) -> None:
        """Playback stopped, either on its own or because the candidate spoke over it.

        The position comes from the browser because only the browser knows it. The server sent
        the whole line in a burst, so what it sent says nothing about what was heard.

        On a cut the split is computed here and sent back rather than worked out again in the
        browser. 12.4 wants the unheard remainder struck through rather than deleted, and the
        report has to agree with what the candidate saw -- two implementations of the same
        apportioning would eventually disagree, and the transcript is the artefact.
        """
        sp = self.speech
        if sp is None or m.get("id") not in (None, sp.id):
            return
        heard = m.get("heard_ms")
        sp.heard_seconds = sp.seconds if heard is None else max(0.0, float(heard) / 1000.0)
        if m.get("t") == "cut":
            await self.stop_speaking()
            said, unsaid = sp.spoken_text()
            await self.send(t="interrupted", id=sp.id, heard=said, unheard=unsaid)

    async def stop_speaking(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self.task = None


@router.websocket("/api/voice")
async def voice(ws: WebSocket) -> None:
    await ws.accept()
    engine = speech.engine()
    asr = listen.engine()
    # A health check over loopback; off the loop in case the voice server is slow to answer.
    ready = await asyncio.to_thread(asr.available) is None
    link = Link(ws, engine, asr if ready else None, endpoint.engine())
    # Same reasoning as the prompt-cache warm in session_start: the first line on a connection took
    # 1.9 s to its first audio unwarmed and 0.8 s warmed, and the difference lands on the opener.
    warm = asyncio.create_task(asyncio.to_thread(engine.warm))
    try:
        await link.run()
    except WebSocketDisconnect:
        pass
    finally:
        warm.cancel()
        await link.stop_speaking()
