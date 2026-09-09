// Unit tests for frontend/animation-queue.js -- the generic sequential
// task queue behind gantry.js's Channel (via motion-unit.js) and
// thermocycler.js's lid-slide/shimmer sequencing. Run with:
//
//     node --test ./tests/frontend/*.test.js

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { AnimationQueue } from "../../src/hamilton_visualizer/frontend/animation-queue.js";

describe("AnimationQueue", () => {
  test("a single task runs its onStart once, ticks with linear t, and completes at t=1", () => {
    const q = new AnimationQueue();
    const ticks = [];
    let started = 0;
    let completed = 0;
    q.enqueue({
      duration: 100,
      onStart: () => started++,
      onTick: (t) => ticks.push(t),
      onComplete: () => completed++,
    });

    assert.equal(started, 0, "onStart shouldn't fire until the first update()");
    q.update(40);
    assert.equal(started, 1);
    assert.deepEqual(ticks, [0.4]);
    assert.equal(completed, 0);

    q.update(40);
    assert.deepEqual(ticks, [0.4, 0.8]);

    q.update(40); // overshoots past the 100ms duration
    assert.deepEqual(ticks, [0.4, 0.8, 1]); // clamped to 1, not 1.2
    assert.equal(completed, 1);
    assert.equal(started, 1, "onStart never fires again for a task that's already finished");
  });

  test("tasks run strictly one at a time, in enqueue order", () => {
    const q = new AnimationQueue();
    const events = [];
    q.enqueue({
      duration: 50,
      onStart: () => events.push("A start"),
      onTick: () => {},
      onComplete: () => events.push("A complete"),
    });
    q.enqueue({
      duration: 50,
      onStart: () => events.push("B start"),
      onTick: () => {},
      onComplete: () => events.push("B complete"),
    });

    q.update(30); // A still running
    assert.deepEqual(events, ["A start"]);
    q.update(30); // A finishes (60 >= 50); B hasn't started yet this same update()
    assert.deepEqual(events, ["A start", "A complete"]);
    q.update(10); // B starts and ticks within this same call
    assert.deepEqual(events, ["A start", "A complete", "B start"]);
    q.update(50);
    assert.deepEqual(events, ["A start", "A complete", "B start", "B complete"]);
  });

  test("duration as a function is resolved once, after onStart, not at enqueue time", () => {
    const q = new AnimationQueue();
    let readAt = null;
    let externalValue = 999; // deliberately wrong at enqueue time
    q.enqueue({
      duration: () => externalValue,
      onStart: () => {
        externalValue = 100; // mutated between enqueue() and the task actually starting
        readAt = "onStart ran first";
      },
      onTick: () => {},
    });
    assert.equal(readAt, null, "onStart shouldn't run until update() is called");
    q.update(100); // if duration were resolved at enqueue time (999), this wouldn't finish
    // Task should have completed (used duration=100, resolved after onStart's mutation).
    q.update(0);
    assert.equal(q.isIdle, true);
  });

  test("update() with nothing queued is a harmless no-op", () => {
    const q = new AnimationQueue();
    assert.doesNotThrow(() => q.update(16));
    assert.equal(q.isIdle, true);
  });

  test("isIdle is false while a task is queued or running, true once drained", () => {
    const q = new AnimationQueue();
    assert.equal(q.isIdle, true);
    q.enqueue({ duration: 10, onTick: () => {} });
    assert.equal(q.isIdle, false, "enqueued but not yet started still counts as not idle");
    q.update(5);
    assert.equal(q.isIdle, false);
    q.update(5);
    assert.equal(q.isIdle, true);
  });
});
