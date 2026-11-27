import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeWav } from "../../web/daw/wav.js";

test("WAV header and 16-bit samples, clipped", () => {
  const b = encodeWav([Float32Array.from([0, 0.5, -1, 2, NaN])], 8000);
  const v = new DataView(b), text = (at) => String.fromCharCode(...new Uint8Array(b, at, 4));
  assert.equal(b.byteLength, 44 + 10);
  assert.deepEqual([text(0), text(8), text(12), text(36)], ["RIFF", "WAVE", "fmt ", "data"]);
  assert.equal(v.getUint32(4, true), 36 + 10);
  assert.deepEqual([v.getUint16(20, true), v.getUint16(22, true), v.getUint32(24, true), v.getUint16(34, true)], [1, 1, 8000, 16]);
  assert.deepEqual([0, 1, 2, 3, 4].map((i) => v.getInt16(44 + 2 * i, true)), [0, 16384, -32768, 32767, 0]);
});

test("WAV channels are interleaved", () => {
  const b = encodeWav([Float32Array.from([1, 1]), Float32Array.from([-1, -1])], 44100);
  const v = new DataView(b);
  assert.equal(v.getUint16(22, true), 2);
  assert.deepEqual([0, 1, 2, 3].map((i) => v.getInt16(44 + 2 * i, true)), [32767, -32768, 32767, -32768]);
});
