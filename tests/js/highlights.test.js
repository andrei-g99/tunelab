import assert from "node:assert/strict";
import { test } from "node:test";
import * as h from "../../web/transcriber/highlights.js";

test("painting covers the brush and does not modify the grid", () => {
  const a = h.emptyGrid(20, 12);
  const b = h.paint(a, [5, 6], [5, 6], 2, h.MELODY);
  assert.ok(h.isEmpty(a, h.MELODY));
  assert.deepEqual(h.toRuns(b, h.MELODY), [4, 5, 6, 7, 8].map((r) => [r, 4, 7]));
  assert.equal(h.paint(b, [5, 6], [5, 6], 1, h.MELODY), b);
});
test("a fast stroke leaves no holes, in any direction", () => {
  for (const [from, to] of [[[0, 5], [19, 5]], [[10, 0], [10, 11]], [[19, 11], [0, 0]]]) {
    const g = h.paint(h.emptyGrid(20, 12), from, to, 1, h.MELODY);
    for (let c = Math.min(from[0], to[0]); c <= Math.max(from[0], to[0]); c++) {
      const rows = [...Array(12).keys()].filter((r) => h.cellAt(g, c, r) === h.MELODY);
      assert.ok(rows.length && rows.every((r, i) => !i || r === rows[i - 1] + 1), `column ${c}`);
    }
  }
});
test("painting outside the grid is clipped", () => {
  const g = h.paint(h.emptyGrid(4, 4), [-9, -9], [20, 20], 3, h.NOT);
  assert.equal(g.cells.length, 16);
});
test("values replace each other, and erasing removes both", () => {
  let g = h.paint(h.emptyGrid(10, 10), [5, 5], [5, 5], 1, h.MELODY);
  g = h.paint(g, [5, 5], [5, 5], 0, h.NOT);
  assert.equal(h.cellAt(g, 5, 5), h.NOT);
  g = h.paint(g, [5, 5], [5, 5], 5, h.NONE);
  assert.ok(h.isEmpty(g, h.MELODY) && h.isEmpty(g, h.NOT));
});
test("runs survive a round trip", () => {
  let g = h.emptyGrid(30, 9);
  for (let i = 0; i < 40; i++) g = h.paint(g, [i * 7 % 30, i * 5 % 9], [i * 11 % 30, i * 4 % 9], i % 3, i % 3);
  const back = h.fromRuns(30, 9, h.toRuns(g, h.MELODY), h.toRuns(g, h.NOT));
  assert.deepEqual(back, g);
  assert.deepEqual(h.toRuns(h.fromRuns(3, 2, [[0, 1, 99], [7, 0, 2]], []), h.MELODY), [[0, 1, 3]]);
});
test("undo and redo", () => {
  const a = h.history(h.emptyGrid(5, 5));
  assert.equal(h.commit(a, a.grid), a);
  const b = h.commit(a, h.paint(a.grid, [2, 2], [2, 2], 0, h.MELODY));
  assert.equal(h.undo(b).grid, a.grid);
  assert.equal(h.redo(h.undo(b)).grid, b.grid);
  assert.equal(h.undo(a), a);
  assert.deepEqual(h.commit(h.undo(b), h.emptyGrid(5, 5)).future, []);
  let long = a;
  for (let i = 0; i < 150; i++) long = h.commit(long, h.emptyGrid(5, 5));
  assert.equal(long.past.length, 100);
});
