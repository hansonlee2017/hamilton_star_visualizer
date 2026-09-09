// Unit tests for frontend/resource-state.js's fill-level color/opacity math
// (volumeVisual()/tipVisual()) -- the logic behind a well's live color and
// a tip's presence/capacity color. Run with:
//
//     node --test tests/frontend/
//
// Imports "three" via frontend/node_modules/three/ -- see that directory's
// package.json for why that resolves without an actual npm dependency.

import { test } from "node:test";
import assert from "node:assert/strict";
import { volumeVisual, tipVisual } from "../../src/hamilton_visualizer/frontend/resource-state.js";
import { EMPTY_COLOR, EMPTY_OPACITY, FULL_OPACITY } from "../../src/hamilton_visualizer/frontend/categories.js";

test("volumeVisual at 0% is fully empty-colored and at empty opacity", () => {
  const { color, opacity } = volumeVisual(0, 100);
  assert.equal(color.getHex(), EMPTY_COLOR);
  assert.equal(opacity, EMPTY_OPACITY);
});

test("volumeVisual treats a null volume the same as 0", () => {
  const { color, opacity } = volumeVisual(null, 100);
  assert.equal(color.getHex(), EMPTY_COLOR);
  assert.equal(opacity, EMPTY_OPACITY);
});

test("volumeVisual at 100% is fully at the full-color/full-opacity end", () => {
  const { color, opacity } = volumeVisual(100, 100);
  assert.equal(color.getHex(), 0x2ee6a8);
  assert.equal(opacity, FULL_OPACITY);
});

test("volumeVisual's sqrt scaling makes a modest fill look brighter than a linear scale would", () => {
  // A 14%-full well (e.g. a 50uL dispense into a 360uL well) should read as
  // meaningfully more-than-empty, not nearly indistinguishable from 0 -- see
  // volumeVisual()'s own docstring for why a plain linear fraction was
  // rejected. sqrt(0.14) ~= 0.374, so this should land well above where a
  // linear scale would have put it (14% of the way from empty to full).
  const { opacity } = volumeVisual(14, 100);
  const linearOpacity = EMPTY_OPACITY + 0.14 * (FULL_OPACITY - EMPTY_OPACITY);
  assert.ok(
    opacity > linearOpacity,
    `sqrt-scaled opacity (${opacity}) should exceed what a linear scale would give (${linearOpacity})`
  );
});

test("volumeVisual is monotonic -- more liquid always reads as visually fuller", () => {
  const fractions = [0, 10, 25, 50, 75, 90, 100];
  const opacities = fractions.map((f) => volumeVisual(f, 100).opacity);
  for (let i = 0; i < opacities.length - 1; i++) {
    assert.ok(
      opacities[i] <= opacities[i + 1],
      `opacity should be non-decreasing with volume: ${fractions[i]}% -> ${opacities[i]}, ` +
        `${fractions[i + 1]}% -> ${opacities[i + 1]}`
    );
  }
});

test("tipVisual reports the empty color/opacity when no tip is present, regardless of capacity", () => {
  const { color, opacity } = tipVisual(false, 300);
  assert.equal(color, EMPTY_COLOR);
  assert.equal(opacity, EMPTY_OPACITY);
});

test("tipVisual reports the capacity-bucketed color at full opacity when a tip is present", () => {
  const { color, opacity } = tipVisual(true, 50);
  assert.equal(color, 0xf48fb1); // pink, <=50uL -- see categories.js's tipColorForVolume
  assert.equal(opacity, FULL_OPACITY);
});
