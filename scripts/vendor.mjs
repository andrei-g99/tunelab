// Copies the pinned browser libraries (see package.json) into web/vendor.
// Run `npm install --ignore-scripts && npm run vendor` after changing a version.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const out = new URL("../web/vendor/", import.meta.url);
const from = (p) => new URL("../node_modules/" + p, import.meta.url);
const files = {
  "konva.min.js": "konva/konva.min.js",
  "Tone.js": "tone/build/Tone.js",
  "Midi.js": "@tonejs/midi/build/Midi.js",
  "tinykeys.mjs": "tinykeys/dist/tinykeys.mjs",
  "LICENSE.konva": "konva/LICENSE",
  "LICENSE.tone": "tone/LICENSE.md",
  "LICENSE.tonejs-midi": "@tonejs/midi/LICENSE.md",
  "LICENSE.tinykeys": "tinykeys/LICENSE",
};
mkdirSync(out, { recursive: true });
for (const [name, path] of Object.entries(files)) {
  if (name.startsWith("LICENSE")) copyFileSync(from(path), new URL(name, out));
  else writeFileSync(new URL(name, out), readFileSync(from(path), "utf8").replace(/\/\/# sourceMappingURL=.*\s*$/, ""));
}
console.log("vendored", Object.keys(files).length, "files");
