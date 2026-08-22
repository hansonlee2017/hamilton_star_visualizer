// Generic per-owner sequential animation queue: tasks run one at a time,
// each ticked every frame with a raw (unequal-eased) progress value in
// [0, 1]. This is the shared primitive behind gantry.js's Channel leg-
// tweening (via motion-unit.js) and thermocycler.js's lid-slide/shimmer
// sequencing -- both used to be independent, fire-and-forget
// requestAnimationFrame loops with no way to wait for one another, which
// is exactly what let a thermocycler's close/shimmer/open animations
// overlap instead of playing in order (see docs/PLAN.md's "Review round
// 37"). No THREE.js/DOM dependency at all -- see tests/frontend/
// animation-queue.test.js.
//
// Deliberately does *not* apply any easing itself -- a task's `onTick`
// receives the plain linear `t`, and decides for itself whether/how to
// ease it. Two existing call sites need genuinely different answers here:
// motion-unit.js's position tweens want easeInOutQuad (matching gantry.js's
// pre-refactor Channel.update()), while thermocycler.js's shimmer wants
// raw `t` fed straight into a sine wave (easing it would distort the
// oscillation instead of just changing its pacing) -- baking one policy
// into this generic queue would have been wrong for the other caller.

export class AnimationQueue {
  constructor() {
    this._queue = [];
    this._current = null;
  }

  // task: {
  //   duration: number | () => number,
  //   onStart?: () => void,
  //   onTick: (t: number) => void,   // t in [0, 1], linear
  //   onComplete?: () => void,
  // } | {
  //   waitUntil: () => boolean,
  //   onStart?: () => void,
  //   onComplete?: () => void,
  // }
  //
  // `duration` may be a function -- resolved once, right when this task
  // actually starts (after `onStart`, so it can read whatever onStart just
  // computed), not at enqueue time. This matters once the queue backs up
  // (a later task enqueued while an earlier one is still running): a value
  // captured at enqueue time can be stale by the time this task's turn
  // actually comes, e.g. a duration that depends on getDurationScale() and
  // the HUD's speed dropdown changed in between.
  //
  // `waitUntil` is a different kind of task entirely: no `duration`/
  // `onTick`, just a condition re-checked every real frame, completing the
  // instant it first returns true -- see update()'s own handling. Meant
  // for "don't start my *next* real task until some other queue/condition
  // elsewhere has caught up" (e.g. gantry.js's waitForGantry()), where a
  // *precomputed* duration is the wrong tool: it has to be recomputed
  // correctly at the exact right moment, can't react if more work gets
  // added to the thing being waited on after it was computed, and (see
  // docs/PLAN.md's "Review round 44"/"Review round 45") is exactly the
  // class of bug a fixed-duration hold kept reintroducing. A live
  // condition is self-correcting by construction: it simply doesn't
  // complete until it's actually true, however long that ends up taking.
  enqueue(task) {
    this._queue.push(task);
  }

  // True once every enqueued task has finished and nothing is running --
  // not currently read anywhere, but useful for a caller that wants to
  // know "is this resource done animating" without polling task state.
  get isIdle() {
    return !this._current && this._queue.length === 0;
  }

  // Total remaining real-world duration (ms) across the currently-running
  // task (if any) plus everything still queued behind it -- lets a
  // caller *outside* this queue's own owner find out how long it'll stay
  // busy without reaching into private state itself (see gantry.js's own
  // gantryRemainingMs(), used to make an unrelated animation -- the
  // thermocycler's lid-slide/shimmer, or a fresh CoRe-gripper pickup's
  // own hold -- wait for the rest of the scene to visually catch up
  // first, instead of starting the instant its own op event arrives).
  // Assumes every task's own `duration` is (or, for the currently-
  // running one, already resolved to -- see update()'s own function-
  // duration handling) a plain number; a still-queued task with a
  // function-valued duration (this queue supports those -- see
  // enqueue()'s own docstring -- thermocycler.js's lid-slide/shimmer
  // tasks use them) contributes 0 here rather than being called early,
  // which would run it before its own onStart. No caller in this
  // codebase currently reads remainingMs on a queue that also has
  // function-valued tasks queued (only ticked, never introspected this
  // way), so this is a documented limitation, not an active bug.
  //
  // A `waitUntil` task -- active or still queued -- also contributes 0,
  // for the same reason: its real duration isn't knowable in advance
  // (that's the whole point of it being a live condition, not a
  // precomputed number). Any *fixed*-duration task queued behind it still
  // counts normally, since its own duration is known regardless of how
  // long the wait ahead of it takes.
  get remainingMs() {
    let total = 0;
    if (this._current && !this._current.waitUntil) {
      total += Math.max(0, this._current.duration - this._current.elapsed);
    }
    for (const task of this._queue) {
      total += typeof task.duration === "number" ? task.duration : 0;
    }
    return total;
  }

  update(dtMs) {
    if (!this._current) {
      this._current = this._queue.shift();
      if (this._current) {
        this._current.onStart?.();
        if (!this._current.waitUntil) {
          this._current.elapsed = 0;
          if (typeof this._current.duration === "function") {
            this._current.duration = this._current.duration();
          }
        }
      }
    }
    if (!this._current) return;

    if (this._current.waitUntil) {
      // No `elapsed`/`duration`/`onTick` bookkeeping at all -- just poll
      // the condition every real frame and complete the instant it's
      // first true, however many frames that takes.
      if (this._current.waitUntil()) {
        const { onComplete } = this._current;
        this._current = null;
        onComplete?.();
      }
      return;
    }

    this._current.elapsed += dtMs;
    const t = Math.min(1, this._current.elapsed / this._current.duration);
    this._current.onTick(t);
    if (t >= 1) {
      const { onComplete } = this._current;
      this._current = null;
      onComplete?.();
    }
  }
}
