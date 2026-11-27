// Plays a recording, notes, or both. One thing at a time, with the button that started it as Stop.
import { voice } from "../shared/voice.js";

export function createPlayer({ volume, allowed }) {
  let ctx = null, playing = null;
  const buffers = new Map(); // decoded sounds, by url

  const context = async () => {
    ctx = ctx || new AudioContext();
    await ctx.resume();
    return ctx;
  };
  async function decoded(sound) {
    if (sound instanceof ArrayBuffer) return ctx.decodeAudioData(sound.slice(0));
    if (!buffers.has(sound)) {
      const r = await fetch(sound);
      if (!r.ok) throw new Error("The recording could not be loaded.");
      buffers.set(sound, await ctx.decodeAudioData(await r.arrayBuffer()));
    }
    return buffers.get(sound);
  }
  function stop() {
    if (!playing) return;
    cancelAnimationFrame(playing.raf);
    playing.master.gain.setTargetAtTime(0, ctx.currentTime, 0.01);
    const { master, sources } = playing;
    setTimeout(() => { sources.forEach((s) => s.stop()); master.disconnect(); }, 120);
    playing.button.textContent = playing.label;
    playing.onTime?.(null);
    playing = null;
  }
  /** notes: [start, end, pitch] in seconds. sound: url or WAV bytes. from: seconds to begin at.
   *  onTime: called with the position while playing, then with null. */
  async function play(button, { notes = [], sound = null, from = 0, onTime = null }) {
    const again = playing?.button === button;
    stop();
    if (again) return;
    await context();
    const buffer = sound ? await decoded(sound) : null;
    if (playing || !allowed()) return;
    const end = Math.max(buffer ? buffer.duration : 0, ...notes.map((n) => n[1]));
    if (from >= end) from = 0;
    const master = ctx.createGain();
    master.gain.value = volume();
    master.connect(ctx.destination);
    const t0 = ctx.currentTime + 0.08 - from, sources = [];
    if (buffer) {
      const s = ctx.createBufferSource(), g = ctx.createGain();
      g.gain.value = notes.length ? 0.45 : 1; // leave room for the guess on top
      s.buffer = buffer;
      s.connect(g).connect(master);
      s.start(t0 + from, from);
      sources.push(s);
    }
    for (const [a, b, p] of notes) {
      if (a >= from) voice(master, p, t0 + a, Math.max(0.03, (b - a) * 0.96), 0.4, "triangle");
    }
    playing = { button, label: button.textContent, master, sources, onTime, raf: 0 };
    const mine = playing;
    button.textContent = "Stop";
    const tick = () => {
      if (playing !== mine) return;
      const t = ctx.currentTime - t0;
      if (t > end) return stop();
      onTime?.(Math.max(from, t));
      mine.raf = requestAnimationFrame(tick);
    };
    tick();
  }
  async function note(pitch) {
    await context();
    const g = ctx.createGain();
    g.gain.value = volume();
    g.connect(ctx.destination);
    voice(g, pitch, ctx.currentTime, 0.5, 0.4, "triangle");
  }
  return {
    play, stop, note,
    isPlaying: (button) => playing?.button === button,
    setVolume: (v) => { if (playing) playing.master.gain.value = v; },
    forget: () => buffers.clear(),
  };
}
