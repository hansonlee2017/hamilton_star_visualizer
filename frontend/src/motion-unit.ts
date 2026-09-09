// Shared "queue of x/y/z leg tweens" mechanics behind gantry.ts's Channel,
// and (per docs/PLAN.md's "Review round 37" design discussion) the
// Core96Head -- both are rigid bodies that move through the same
// rise/x/y/descend/hold/retract leg pattern, with the same lazy
// target/duration resolution and the same easing. A MotionUnit only knows
// about its own x/y/z; it doesn't know about tips, flow pulses, or
// anything else visual -- that stays in whatever owns it (see gantry.ts's
// Channel, which now composes one of these instead of implementing its
// own queue).
//
// No THREE.js/DOM dependency -- position is a plain {x, y, z} object, and
// "how to actually move the mesh" is injected as a callback, not imported.
// See test/motion-unit.test.ts.

import { AnimationQueue } from "./animation-queue";

export interface Pos {
  x: number;
  y: number;
  z: number;
}

// `x`/`y` may be `null` ("stay wherever this leg starts on that axis").
// `z` may additionally be a function resolved lazily when the leg starts.
export interface LegTarget {
  x: number | null;
  y: number | null;
  z: number | null | ((from: Pos) => number);
}
export type LegDuration = number | ((from: Pos, target: Pos) => number);

const easeInOutQuad = (t: number): number =>
  t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export class MotionUnit {
  pos: Pos;
  private _applyPosition: () => void;
  private _queue = new AnimationQueue();

  // applyPosition: () => void -- called every tick and on completion, after
  // `this.pos` has been updated, so the caller can copy it onto whatever
  // THREE.Object3D it owns (see gantry.ts's Channel.applyPosition()).
  constructor(initialPos: Pos, applyPosition: () => void) {
    this.pos = { ...initialPos };
    this._applyPosition = applyPosition;
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
  enqueue(target: LegTarget, duration: LegDuration, onComplete?: () => void): void {
    let from: Pos;
    let resolvedTarget: Pos;
    this._queue.enqueue({
      onStart: () => {
        from = { ...this.pos };
        const z = target.z === null ? from.z : target.z;
        resolvedTarget = {
          x: target.x === null ? from.x : target.x,
          y: target.y === null ? from.y : target.y,
          z: typeof z === "function" ? z(from) : z,
        };
      },
      // Only actually wrapped in a function when `duration` itself is one
      // (needs `from`/`resolvedTarget`, not available until onStart runs
      // above) -- a plain number passed straight through unwrapped, not
      // wrapped-and-later-resolved-back-into-the-same-number. Every call
      // site in this codebase only ever passes plain numbers (see this
      // file's own module docstring), so this is mostly about keeping
      // `AnimationQueue.remainingMs` able to see a *queued, not-yet-
      // started* task's own duration: that getter only sums plain-number
      // durations (a still-queued function-valued one can't be resolved
      // early without running its closure before its own onStart) --
      // unconditionally wrapping every duration in one, even an already-
      // known number, made *every* not-yet-started leg invisible to it,
      // undercounting a queue's own real remaining backlog (confirmed
      // live: gantry.ts's own gantryRemainingMs()-based fixes -- syncing
      // a CoRe-gripper pickup's hold and the thermocycler's own
      // animations to the rest of the gantry's real backlog -- silently
      // measured near-zero regardless of how much was actually still
      // queued, until this was fixed).
      duration:
        typeof duration === "function" ? () => duration(from, resolvedTarget) : duration,
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

  update(dtMs: number): void {
    this._queue.update(dtMs);
  }

  // Delegates to the composed AnimationQueue -- see its own remainingMs
  // docstring.
  get remainingMs(): number {
    return this._queue.remainingMs;
  }
}
