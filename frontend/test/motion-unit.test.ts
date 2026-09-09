// Unit tests for src/motion-unit.ts -- the shared "queue of x/y/z leg
// tweens" mechanics behind gantry.ts's Channel and Core96Head.
//
//     npm test

import { test, describe, assert } from "vitest";
import { MotionUnit, type Pos } from "../src/motion-unit";

function makeUnit(initialPos: Pos): { unit: MotionUnit; applied: Pos[] } {
  const applied: Pos[] = [];
  const unit = new MotionUnit(initialPos, () => applied.push({ ...unit.pos }));
  return { unit, applied };
}

describe("MotionUnit", () => {
  test("a plain numeric target is reached exactly at completion", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 0 });
    unit.enqueue({ x: 10, y: 20, z: 30 }, 100);
    unit.update(100);
    assert.deepEqual(unit.pos, { x: 10, y: 20, z: 30 });
  });

  test("null components stay at wherever this leg actually started, other axes still move", () => {
    const { unit } = makeUnit({ x: 1, y: 1, z: 1 });
    unit.enqueue({ x: null, y: 5, z: null }, 100);
    unit.update(100);
    assert.deepEqual(unit.pos, { x: 1, y: 5, z: 1 });
  });

  test("a function target.z is resolved lazily, using the leg's own starting position", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 10 });
    // First leg moves z up front -- a naive eager resolution of the second
    // leg's target.z (captured at enqueue time, before the first leg has
    // run) would see the stale starting z=10, not the real z=50 this leg
    // actually starts from.
    unit.enqueue({ x: null, y: null, z: 50 }, 10);
    unit.enqueue({ x: null, y: null, z: (from) => from.z + 100 }, 10);
    unit.update(10); // first leg completes: z=50
    assert.equal(unit.pos.z, 50);
    unit.update(10); // second leg completes: should be 50 + 100 = 150, not 10 + 100
    assert.equal(unit.pos.z, 150);
  });

  test("a function duration is resolved after target.z, and can read the resolved target", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 0 });
    const durationCalls: Array<{ from: Pos; target: Pos }> = [];
    unit.enqueue({ x: null, y: null, z: (from) => from.z + 40 }, (from, target) => {
      durationCalls.push({ from: { ...from }, target: { ...target } });
      return 40; // arbitrary
    });
    unit.update(40);
    assert.equal(durationCalls.length, 1);
    assert.equal(durationCalls[0].from.z, 0);
    assert.equal(
      durationCalls[0].target.z,
      40,
      "duration fn should see the already-resolved z, not the raw function"
    );
    assert.equal(unit.pos.z, 40);
  });

  test("onComplete fires exactly once, when this leg's own tween finishes", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 0 });
    let completions = 0;
    unit.enqueue({ x: 5, y: 0, z: 0 }, 100, () => completions++);
    unit.update(50);
    assert.equal(completions, 0);
    unit.update(50);
    assert.equal(completions, 1);
    unit.update(50); // nothing left queued -- harmless
    assert.equal(completions, 1);
  });

  test("motion is eased (easeInOutQuad), not linear", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 0 });
    unit.enqueue({ x: 100, y: 0, z: 0 }, 100);
    unit.update(25); // 25% of the way through the duration
    // easeInOutQuad(0.25) = 2 * 0.25^2 = 0.125 -- well below the linear 25
    // a plain lerp would give, confirming the ease-in is actually applied.
    assert.ok(unit.pos.x < 20, `expected an eased (slow-start) x well under 25, got ${unit.pos.x}`);
    assert.ok(unit.pos.x > 10, `expected some progress, got ${unit.pos.x}`);
  });

  test("applyPosition is invoked on every tick, and again (with the exact target) on completion", () => {
    const { unit, applied } = makeUnit({ x: 0, y: 0, z: 0 });
    unit.enqueue({ x: 10, y: 0, z: 0 }, 20);
    unit.update(10); // mid-tween: one applyPosition call
    assert.equal(applied.length, 1);
    unit.update(10); // finishes: one more from onTick's own t=1 call, plus
    // onComplete's own re-apply of the exact (not eased-then-rounded) target
    assert.equal(applied.length, 3);
    assert.deepEqual(applied.at(-1), { x: 10, y: 0, z: 0 });
  });

  test("legs enqueued back-to-back play out in order, each starting from where the last left off", () => {
    const { unit } = makeUnit({ x: 0, y: 0, z: 0 });
    unit.enqueue({ x: 10, y: 0, z: 0 }, 10);
    unit.enqueue({ x: 10, y: 20, z: 0 }, 10);
    unit.update(10);
    assert.deepEqual(unit.pos, { x: 10, y: 0, z: 0 });
    unit.update(10);
    assert.deepEqual(unit.pos, { x: 10, y: 20, z: 0 });
  });
});
