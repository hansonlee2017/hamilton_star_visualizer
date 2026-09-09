// Unit tests for frontend/gantry-planning.js -- the pure motion-planning
// math behind the gantry's multi-channel op animation (see that file's own
// docstrings for the algorithm). Run with:
//
//     node --test tests/frontend/

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { CHANNEL_PITCH_MM, resolveChannelYs, planGantryPasses } from "../../src/hamilton_visualizer/frontend/gantry-planning.js";

// A plain `{ pos: { y } }` array -- planGantryPasses() only ever reads
// `.pos.y` and `.keys()` off this, nothing THREE.js-shaped.
function fakeChannels(ys) {
  return ys.map((y) => ({ pos: { y } }));
}

// The physical invariant planGantryPasses() exists to guarantee: within one
// gantry stop, channel 0's y must be the highest, and every next channel's
// y must be at least `pitchMm` lower -- reconstructed here from a pass's
// `active` entries plus its `idleMoves` (every channel this pass touches,
// one way or the other) and checked directly, rather than hand-deriving
// exact expected y's for every scenario (this is what the function is
// actually *for*, so it's the more robust thing to pin down).
function assertPitchInvariant(pass, pitchMm, message) {
  const yByChannel = new Map(pass.idleMoves);
  for (const entry of pass.active) yByChannel.set(entry.channel, entry.y);
  const ordered = [...yByChannel.entries()].sort((a, b) => a[0] - b[0]);
  for (let i = 0; i < ordered.length - 1; i++) {
    const [chA, yA] = ordered[i];
    const [chB, yB] = ordered[i + 1];
    assert.ok(
      yA - yB >= pitchMm - 1e-6,
      `${message}: channel ${chA} (y=${yA}) and channel ${chB} (y=${yB}) are only ` +
        `${(yA - yB).toFixed(3)}mm apart, need >= ${pitchMm}mm`
    );
  }
}

describe("resolveChannelYs", () => {
  test("leaves already-valid fixed positions unchanged", () => {
    const result = resolveChannelYs([0, 1], new Map([[0, 100], [1, 90]]), new Map(), 9);
    assert.deepEqual([...result], [[0, 100], [1, 90]]);
  });

  test("pulls a free channel to respect a fixed neighbor's pitch", () => {
    // Channel 1 prefers y=105 (above channel 0's fixed y=100), but must end
    // up at or below 100 - 9 = 91.
    const result = resolveChannelYs([0, 1], new Map([[0, 100]]), new Map([[1, 105]]), 9);
    assert.equal(result.get(0), 100); // fixed channel is never adjusted
    assert.ok(result.get(1) <= 91 + 1e-9, `channel 1 should be pulled down to <=91, got ${result.get(1)}`);
  });

  test("pulls a free channel sandwiched between two fixed ones into range", () => {
    // Channel 1 prefers y=70 (equal to channel 2's own fixed y), but must
    // land strictly between channel 0 (fixed 100) and channel 2 (fixed 70)
    // by at least one pitch on each side.
    const result = resolveChannelYs(
      [0, 1, 2],
      new Map([[0, 100], [2, 70]]),
      new Map([[1, 70]]),
      9
    );
    assert.equal(result.get(0), 100);
    assert.equal(result.get(2), 70);
    assert.ok(result.get(1) <= 91 + 1e-9 && result.get(1) >= 79 - 1e-9, `channel 1 should land in [79, 91], got ${result.get(1)}`);
  });

  test("throws when two fixed channels can't both be satisfied", () => {
    // Only 5mm apart, fixed pitch requires 9mm -- neither can move.
    assert.throws(
      () => resolveChannelYs([0, 1], new Map([[0, 100], [1, 95]]), new Map(), 9),
      /out of order or closer than/
    );
  });
});

describe("planGantryPasses", () => {
  test("a single shared x produces one pass covering every targeted channel", () => {
    const channels = fakeChannels([0, -9]);
    const entries = [
      { channel: 0, x: 100, y: 0 },
      { channel: 1, x: 100, y: -9 },
    ];
    const passes = planGantryPasses(entries, channels);
    assert.equal(passes.length, 1);
    assert.equal(passes[0].x, 100);
    assert.deepEqual(passes[0].active.map((e) => e.channel).sort(), [0, 1]);
    // Both channels were targeted at this one x -- nothing left to idle-move.
    assert.equal(passes[0].idleMoves.size, 0);
    assertPitchInvariant(passes[0], CHANNEL_PITCH_MM, "single pass");
  });

  test("scattered x's (e.g. the smiley-face demo) produce one pass per x, dragging idle channels along", () => {
    const channels = fakeChannels([0, -9]);
    const entries = [
      { channel: 0, x: 100, y: 0 },
      { channel: 1, x: 200, y: -9 },
    ];
    const passes = planGantryPasses(entries, channels);
    assert.equal(passes.length, 2);
    assert.deepEqual(passes.map((p) => p.x), [100, 200]);

    // Pass 1 (x=100) only targets channel 0 -- channel 1 must still be
    // dragged along (idle-moved), not left behind.
    assert.deepEqual(passes[0].active.map((e) => e.channel), [0]);
    assert.ok(passes[0].idleMoves.has(1), "channel 1 should be dragged along in pass 1");

    // Pass 2 (x=200) only targets channel 1 -- channel 0 gets dragged.
    assert.deepEqual(passes[1].active.map((e) => e.channel), [1]);
    assert.ok(passes[1].idleMoves.has(0), "channel 0 should be dragged along in pass 2");

    for (const pass of passes) assertPitchInvariant(pass, CHANNEL_PITCH_MM, `pass at x=${pass.x}`);
  });

  test("only a subset of channels targeted still drags every other loaded channel along", () => {
    // 3 channels total, only channel 1 (the middle one) is targeted --
    // channels 0 and 2 must still appear in idleMoves (a real Hamilton's
    // arm physically can't leave them behind -- see this file's own
    // docstring).
    const channels = fakeChannels([0, -9, -18]);
    const entries = [{ channel: 1, x: 150, y: -9 }];
    const passes = planGantryPasses(entries, channels);
    assert.equal(passes.length, 1);
    assert.deepEqual(passes[0].active.map((e) => e.channel), [1]);
    assert.deepEqual([...passes[0].idleMoves.keys()].sort(), [0, 2]);
    assertPitchInvariant(passes[0], CHANNEL_PITCH_MM, "partial-targeting pass");
  });

  test("two channels needing conflicting y's at the same x fall back to one stop per channel", () => {
    // Both target x=100, but only 1mm apart -- infeasible in a single
    // gantry stop (pitch is 9mm) -- must split into two single-channel
    // passes, smallest channel index first.
    const channels = fakeChannels([0, -9]);
    const entries = [
      { channel: 0, x: 100, y: 0 },
      { channel: 1, x: 100, y: -1 },
    ];
    const passes = planGantryPasses(entries, channels);
    assert.equal(passes.length, 2);
    assert.deepEqual(passes[0].active.map((e) => e.channel), [0]);
    assert.deepEqual(passes[1].active.map((e) => e.channel), [1]);
    // Each channel's own fixed target for *its* pass is honored exactly,
    // even though the two together were infeasible in one stop.
    assert.equal(passes[0].active[0].y, 0);
    assert.equal(passes[1].active[0].y, -1);
    for (const pass of passes) assertPitchInvariant(pass, CHANNEL_PITCH_MM, `fallback pass for channel`);
  });
});
