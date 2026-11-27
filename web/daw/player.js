// Playback with Tone.js. One synth per track; the Tone transport counts in our ticks.
/* global Tone */
import { PPQ, audibleTracks, noteEnd, projectEnd } from "./model.js";

const SYNTHS = {
  soft: () => new Tone.PolySynth(Tone.Synth, { oscillator: { type: "triangle" }, envelope: { attack: 0.01, decay: 0.2, sustain: 0.5, release: 0.15 } }),
  sine: () => new Tone.PolySynth(Tone.Synth, { oscillator: { type: "sine" }, envelope: { attack: 0.02, decay: 0.1, sustain: 0.7, release: 0.2 } }),
  square: () => new Tone.PolySynth(Tone.Synth, { oscillator: { type: "square" }, envelope: { attack: 0.005, decay: 0.15, sustain: 0.4, release: 0.1 }, volume: -10 }),
  saw: () => new Tone.PolySynth(Tone.Synth, { oscillator: { type: "sawtooth" }, envelope: { attack: 0.01, decay: 0.2, sustain: 0.4, release: 0.12 }, volume: -10 }),
  epiano: () => new Tone.PolySynth(Tone.FMSynth, { harmonicity: 2, modulationIndex: 4, envelope: { attack: 0.005, decay: 0.6, sustain: 0.2, release: 0.3 } }),
  bell: () => new Tone.PolySynth(Tone.FMSynth, { harmonicity: 3.5, modulationIndex: 8, envelope: { attack: 0.002, decay: 1.2, sustain: 0, release: 0.6 } }),
};
const freq = (p) => 440 * 2 ** ((p - 69) / 12);
const TAIL = 2; // seconds of sound after the last note ends: releases and bell decay
function makeSynth(sound, destination) {
  const synth = SYNTHS[sound]().connect(destination);
  synth.maxPolyphony = 64;
  return synth;
}

/** Mono samples of some tracks of p, sounding as playback does (sound, volume, velocity, tempo).
 * Starts at the project's start and ends TAIL seconds after the tracks' last note. */
export async function render(p, tracks, sampleRate = 44100) {
  const perTick = 60 / p.bpm / PPQ;
  const end = Math.max(0, ...tracks.flatMap((t) => t.notes.map(noteEnd)));
  const buffer = await Tone.Offline(() => {
    const limiter = new Tone.Limiter(-1).toDestination();
    for (const t of tracks) {
      const synth = makeSynth(t.sound, new Tone.Volume(t.volume).connect(limiter));
      for (const n of t.notes) synth.triggerAttackRelease(freq(n.pitch), Math.max(0.02, n.dur * perTick), n.start * perTick, n.vel / 127);
    }
  }, end * perTick + TAIL, 1, sampleRate);
  return buffer.getChannelData(0);
}

export function createPlayer({ store, onFrame, onState }) {
  const transport = Tone.getTransport();
  transport.PPQ = PPQ;
  const limiter = new Tone.Limiter(-1).toDestination();
  const voices = new Map(); // track id -> {sound, synth}
  let project = null, raf = 0, position = 0, generation = 0;
  // our own flag: the transport starts slightly in the future, so its state lags behind
  let active = false;
  const playing = () => active;

  function syncVoices(p) {
    const audible = new Set(audibleTracks(p));
    const alive = new Set();
    for (const t of p.tracks) {
      alive.add(t.id);
      let v = voices.get(t.id);
      if (v && v.sound !== t.sound) { drop(t.id); v = null; }
      if (!v) {
        const gain = new Tone.Volume(0).connect(limiter);
        const synth = makeSynth(t.sound, gain);
        voices.set(t.id, (v = { sound: t.sound, synth, gain }));
      }
      v.gain.volume.value = t.volume;
      v.gain.mute = !audible.has(t);
    }
    for (const id of [...voices.keys()]) if (!alive.has(id)) drop(id);
  }
  function drop(id) {
    const { synth, gain } = voices.get(id);
    voices.delete(id);
    synth.releaseAll();
    setTimeout(() => { synth.dispose(); gain.dispose(); }, 1500);
  }
  function schedule(p) {
    transport.cancel(0);
    const perTick = 60 / p.bpm / PPQ;
    for (const t of p.tracks) for (const n of t.notes) {
      transport.schedule((time) => {
        voices.get(t.id)?.synth.triggerAttackRelease(freq(n.pitch), Math.max(0.02, n.dur * perTick), time, n.vel / 127);
      }, `${n.start}i`);
    }
  }
  /** Call whenever the project changes; safe while playing. */
  function update(p) {
    if (p === project) return;
    const notesChanged = !project || p.bpm !== project.bpm || p.tracks.length !== project.tracks.length
      || p.tracks.some((t, i) => t.notes !== project.tracks[i].notes || t.id !== project.tracks[i].id);
    project = p;
    syncVoices(p); // also when stopped, so that the first note does not wait for a synth to be built
    if (!playing()) return;
    transport.bpm.value = p.bpm;
    if (notesChanged) schedule(p);
  }
  function hush() { for (const { synth } of voices.values()) synth.releaseAll(); }

  function frame() {
    if (!playing()) return;
    if (transport.state === "started") position = transport.ticks; // else: not begun yet
    if (position >= Math.max(1, projectEnd(project))) { halt(0); return; }
    onFrame(position);
    raf = requestAnimationFrame(frame);
  }
  function halt(at) {
    generation++;
    active = false;
    cancelAnimationFrame(raf);
    transport.stop();
    transport.cancel(0);
    hush();
    position = at;
    onFrame(at);
    onState(false);
  }
  async function play() {
    const mine = ++generation;
    await Tone.start();
    if (mine !== generation || playing()) return; // stopped or restarted meanwhile
    project = store.state.project;
    const end = projectEnd(project);
    if (!end) return;
    if (position >= end) position = 0;
    transport.bpm.value = project.bpm;
    schedule(project);
    transport.start("+0.01", `${position}i`);
    active = true;
    onState(true);
    raf = requestAnimationFrame(frame);
  }
  const held = new Map(); // what is sounding by hand: any id -> {trackId, pitch}
  function release(id) {
    const h = held.get(id);
    held.delete(id);
    if (h) voices.get(h.trackId)?.synth.triggerRelease(freq(h.pitch), Tone.immediate());
  }
  return {
    playing, update, release,
    /** Sound a note until release(id). */
    async press(id, trackId, pitch, vel) {
      release(id);
      const note = { trackId, pitch };
      held.set(id, note);
      if (Tone.getContext().state !== "running") await Tone.start();
      if (held.get(id) !== note) return; // released while the audio was starting
      voices.get(trackId)?.synth.triggerAttack(freq(pitch), Tone.immediate(), vel / 127);
    },
    toggle: () => (playing() ? halt(Math.round(transport.ticks)) : play()),
    stop: () => halt(0),
    position: () => Math.round(position),
    seek(tick) {
      position = tick;
      if (playing()) { hush(); transport.ticks = tick; }
      onFrame(tick);
    },
    /** Sound one note as soon as possible. Waits only if the browser has not started audio yet. */
    async preview(trackId, pitch, vel, secs) {
      if (Tone.getContext().state !== "running") await Tone.start();
      // immediate(), because now() adds the look-ahead as latency
      voices.get(trackId)?.synth.triggerAttackRelease(freq(pitch), secs, Tone.immediate(), vel / 127);
    },
  };
}
