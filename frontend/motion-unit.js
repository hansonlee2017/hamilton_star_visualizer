// Shared "queue of x/y/z leg tweens" mechanics behind gantry.js's Channel,
// and (per docs/PLAN.md's "Review round 37" design discussion) a future
// Core96Head -- both are rigid bodies that move through the same
// rise/x/y/descend/hold/retract leg pattern, with the same lazy
// target/duration resolution and the same easing. A MotionUnit only knows
// about its own x/y/z; it doesn't know about tips, flow pulses, or
// anything else visual -- that stays in whatever owns it (see gantry.js's
// Channel, which now composes one of these instead of implementing its
// own queue).
//
// No THREE.js/DOM dependency -- position is a plain {x, y, z} object, and
// "how to actually move the mesh" is injected as a callback, not imported.
// See tests/frontend/motion-unit.test.js.

import { AnimationQueue } from "./animation-queue.js";

const easeInOutQuad = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
const lerp = (a, b, t) => a + (b - a) * t;

export class MotionUnit {
  // applyPosition: () => void -- called every tick and on completion, after
  // `this.pos` has been updated, so the caller can copy it onto whatever
  // THREE.Object3D it owns (see gantry.js's Channel.applyPosition()).
  constructor(initialPos, applyPosition) {
    this.pos = { ...initialPos };
    this._applyPosition = applyPosition;
    this._queue = new AnimationQueue();
  }

  // `onComplete`, if given, fires exactly when *this* leg's tween
  // finishes -- not a fixed wall-clock delay from when it was queued. That
  // distinction matters once the queue backs up (events arriving faster
  // than their animation takes to play out, which happens routinely): a
  // fixed-delay timer drifts out of sync with where this unit actually
  // visually is, while this fires exactly on arrival regardless of backup.
  //
  // `target.x`/`target.y`/`target.z` may each be `null`, meaning "stay at
  // whatever this leg actually starts from on that axis". `target.z` may
  // instead be a function `(from) => number`, resolved lazily when this
  // leg actually starts, not at enqueue time -- a value captured too early
  // can be stale by the time this leg's turn actually comes (e.g. still
  // this unit's *initial* position before it ever moved). `duration` may
  // also be a function `(from, target) => number`, resolved *after*
  // target.z above, so it can use the now-numeric target/from to compute
  // its own span.
  enqueue(target, duration, onComplete) {
    let from;
    let resolvedTarget;
    this._queue.enqueue({
      onStart: () => {
        from = { ...this.pos };
        resolvedTarget = {
          x: target.x === null ? from.x : target.x,
          y: target.y === null ? from.y : target.y,
          z: target.z === null ? from.z : target.z,
        };
        if (typeof resolvedTarget.z === "function") {
          resolvedTarget.z = resolvedTarget.z(from);
        }
      },
      duration: () => (typeof duration === "function" ? duration(from, resolvedTarget) : duration),
      onTick: (t) => {
        const eased = easeInOutQuad(t);
        this.pos = {
          x: lerp(from.x, resolvedTarget.x, eased),
          y: lerp(from.y, resolvedTarget.y, eased),
          z: lerp(from.z, resolvedTarget.z, eased),
        };
        this._applyPosition();
      },
      onComplete: () => {
        this.pos = { ...resolvedTarget };
        this._applyPosition();
        onComplete?.();
      },
    });
  }

  update(dtMs) {
    this._queue.update(dtMs);
  }
}
