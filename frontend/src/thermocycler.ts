// Thermocycler: lid slide + cycling shimmer. Both are tasks enqueued onto
// this resource's own animation-queue.ts AnimationQueue (`entry.animQueue`,
// created for every resource -- see scene-builder.ts), so a close/shimmer/
// open sequence fired back-to-back by the Python backend (no
// asyncio.sleep() needed on that side any more -- see
// examples/thermocycler_demo.py) plays out *in order* here instead of all
// starting -- and overlapping -- at once. That queue is what used to be
// missing (docs/PLAN.md's "Review round 37": these were previously plain
// fire-and-forget requestAnimationFrame loops with no way to wait for one
// another, which is exactly what let the lid open while the shimmer was
// still visibly running).
//
// Called from gantry.ts's handleOpEvent() on the thermocycler_open_lid/
// close_lid/run_protocol op events, with the resourceIndex entry passed in
// directly (this module never touches resourceIndex itself).

import * as THREE from "three";
import { getDurationScale } from "./duration-scale";
import { makeLogger } from "./log";
import type { ResourceEntry } from "./scene-builder";

const log = makeLogger("thermocycler");

export const THERMOCYCLER_LID_MS = 600;
// Deliberately not tied to the backend's own timing at all -- run_protocol()
// completes instantly against the chatterbox backend (see
// thermocycler_backend.py's module docstring for why this visualizer never
// simulates real cycling time), so this fixed window is *the entire reason*
// a "cycling" animation is visible at all.
export const THERMOCYCLER_SHIMMER_MS = 5000;

export function queueLidAnimation(entry: ResourceEntry, opening: boolean): void {
  if (!entry.lidMesh || !entry.lidOpenPos || !entry.lidClosedPos) return;
  const lidMesh = entry.lidMesh;
  let from: THREE.Vector3;
  const to = opening ? entry.lidOpenPos : entry.lidClosedPos;
  entry.animQueue.enqueue({
    // Read live, right when this task actually starts (not when it was
    // enqueued) -- both so `from` reflects wherever the lid genuinely is
    // once any earlier queued task has finished, and so a mid-queue speed
    // change picks up the new getDurationScale() for whichever task hasn't
    // started yet.
    duration: () => THERMOCYCLER_LID_MS * getDurationScale(),
    onStart: () => {
      from = lidMesh.position.clone();
      entry.lidOpen = opening;
      log.info(
        `${entry.node?.name ?? "?"}: lid ${opening ? "opening" : "closing"} animation started`
      );
    },
    onTick: (t) => {
      lidMesh.position.lerpVectors(from, to, t);
    },
  });
}

// A warm pulsing color on the block itself -- the same "something is
// actively happening here" language gantry.ts's flowPulse() uses for a
// channel's tip, scaled to a whole-block, multi-second effect instead of
// one leg's ~550ms.
const THERMOCYCLER_SHIMMER_COLOR = new THREE.Color(0xffa040);
export function queueThermocyclerShimmer(entry: ResourceEntry): void {
  if (!entry.mesh) return;
  const material = entry.mesh.material;
  let baseColor: THREE.Color;
  entry.animQueue.enqueue({
    duration: () => THERMOCYCLER_SHIMMER_MS * getDurationScale(),
    onStart: () => {
      baseColor = entry.baseColor!.clone();
      log.info(`${entry.node?.name ?? "?"}: cycling shimmer started`);
    },
    onTick: (t) => {
      // A handful of full oscillations over the whole window, not one slow
      // fade -- reads as "actively cycling," not just "briefly highlighted."
      // Raw `t` (AnimationQueue applies no easing of its own -- see that
      // file's docstring), not eased -- easing this would distort the
      // oscillation's pacing instead of just its overall speed.
      const pulse = (Math.sin(t * Math.PI * 2 * 6) + 1) / 2;
      material.color.copy(baseColor).lerp(THERMOCYCLER_SHIMMER_COLOR, pulse * 0.7);
    },
    onComplete: () => {
      material.color.copy(baseColor);
      log.info(`${entry.node?.name ?? "?"}: cycling shimmer finished`);
    },
  });
}
