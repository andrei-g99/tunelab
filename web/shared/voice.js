// One plain note, used by the Tune Generator and the Melody Transcriber.
/** Schedule a note on the AudioNode `out`: MIDI pitch, start time in its context, length, gain. */
export function voice(out, midi, at, secs, gain, type) {
  const ctx = out.context;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type;
  o.frequency.value = 440 * 2 ** ((midi - 69) / 12);
  const end = at + secs;
  const atk = Math.min(0.012, secs / 4), rel = Math.min(0.06, secs / 3);
  g.gain.setValueAtTime(0, at);
  g.gain.linearRampToValueAtTime(gain, at + atk);
  g.gain.linearRampToValueAtTime(gain * 0.55, end - rel);
  g.gain.linearRampToValueAtTime(0, end);
  o.connect(g).connect(out);
  o.start(at);
  o.stop(end + 0.01);
}
