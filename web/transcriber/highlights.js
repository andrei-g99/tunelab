// The grid of highlighted cells: pure operations. A grid is never modified; painting returns a new
// one, or the same one when nothing changed.
export const NONE = 0, MELODY = 1, NOT = 2;

export const emptyGrid = (columns, rows) => ({ columns, rows, cells: new Uint8Array(columns * rows) });
export const cellAt = (g, column, row) => g.cells[row * g.columns + column];
export const isEmpty = (g, value) => !g.cells.includes(value);

/** Sweep a brush (3 columns wide, 2 * half + 1 rows high) along a line between two [column, row]. */
export function paint(g, [c0, r0], [c1, r1], half, value) {
  const cells = g.cells.slice();
  const steps = Math.max(1, Math.ceil(Math.abs(c1 - c0)), Math.ceil(Math.abs(r1 - r0)));
  let changed = false;
  for (let i = 0; i <= steps; i++) {
    const c = Math.round(c0 + (c1 - c0) * i / steps), r = Math.round(r0 + (r1 - r0) * i / steps);
    for (let row = Math.max(0, r - half); row <= Math.min(g.rows - 1, r + half); row++) {
      for (let col = Math.max(0, c - 1); col <= Math.min(g.columns - 1, c + 1); col++) {
        const k = row * g.columns + col;
        if (cells[k] !== value) { cells[k] = value; changed = true; }
      }
    }
  }
  return changed ? { ...g, cells } : g;
}

/** Stretches of a value along the rows: [[row, first column, column after the last], ...] */
export function toRuns(g, value) {
  const runs = [];
  for (let row = 0; row < g.rows; row++) {
    let from = -1;
    for (let col = 0; col <= g.columns; col++) {
      const on = col < g.columns && cellAt(g, col, row) === value;
      if (on && from < 0) from = col;
      if (!on && from >= 0) { runs.push([row, from, col]); from = -1; }
    }
  }
  return runs;
}
export function fromRuns(columns, rows, melody, notMelody) {
  const g = emptyGrid(columns, rows);
  for (const [value, runs] of [[MELODY, melody], [NOT, notMelody]]) {
    for (const [row, from, to] of runs) {
      if (row < rows) g.cells.fill(value, row * columns + Math.min(from, columns), row * columns + Math.min(to, columns));
    }
  }
  return g;
}

// ---------- undo ----------
const LIMIT = 100;
export const history = (grid) => ({ grid, past: [], future: [] });
export function commit(h, grid) {
  return grid === h.grid ? h : { grid, past: [...h.past.slice(-(LIMIT - 1)), h.grid], future: [] };
}
export function undo(h) {
  return h.past.length ? { grid: h.past.at(-1), past: h.past.slice(0, -1), future: [h.grid, ...h.future] } : h;
}
export function redo(h) {
  return h.future.length ? { grid: h.future[0], past: [...h.past, h.grid], future: h.future.slice(1) } : h;
}
