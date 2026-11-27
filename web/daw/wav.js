// WAV files: pure, no page or audio access.

/** 16-bit PCM WAV bytes from one or more channels of samples in -1..1 (all the same length). */
export function encodeWav(channels, sampleRate) {
  const n = channels[0].length, k = channels.length, data = n * k * 2;
  const view = new DataView(new ArrayBuffer(44 + data));
  const text = (at, s) => { for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + data, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, k, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * k * 2, true);
  view.setUint16(32, k * 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, data, true);
  let at = 44;
  for (let i = 0; i < n; i++) {
    for (const c of channels) {
      const x = Math.max(-1, Math.min(1, c[i] || 0)); // NaN becomes silence
      view.setInt16(at, Math.round(x < 0 ? x * 0x8000 : x * 0x7fff), true);
      at += 2;
    }
  }
  return view.buffer;
}
