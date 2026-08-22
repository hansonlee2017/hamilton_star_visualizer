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
  // }
  //
  // `duration` may be a function -- resolved once, right when this task
  // actually starts (after `onStart`, so it can read whatever onStart just
  // computed), not at enqueue time. This matters once the queue backs up
  // (a later task enqueued while an earlier one is still running): a value
  // captured at enqueue time can be stale by the time this task's turn
  // actually comes, e.g. a duration that depends on getDurationScale() and
  // the HUD's speed dropdown changed in between.
  enqueue(task) {
    this._queue.push(task);
  }

  // True once every enqueued task has finished and nothing is running --
  // not currently read anywhere, but useful for a caller that wants to
  // know "is this resource done animating" without polling task state.
  get isIdle() {
    return !this._current && this._queue.length === 0;
  }

  update(dtMs) {
    if (!this._current) {
      this._current = this._queue.shift();
      if (this._current) {
        this._current.elapsed = 0;
        this._current.onStart?.();
        if (typeof this._current.duration === "function") {
          this._current.duration = this._current.duration();
        }
      }
    }
    if (!this._current) return;

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
