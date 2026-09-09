// Generic "just wait" incubation hold -- a resource-agnostic sibling of
// thermocycler.ts's queueThermocyclerShimmer(), for VisualizerBackend.
// incubate()'s "incubate" op event (see that method's own docstring for
// why it exists: a real protocol's incubation step -- 1 to 30 minutes in
// examples/spri_cleanup_demo.py -- must never literally block the demo
// with asyncio.sleep(), so lh.sleep() broadcasts this instead and the
// frontend renders one fixed-length cosmetic animation regardless of the
// real duration_s it was called with).
//
// Enqueued onto the target resource's own entry.animQueue (the same
// AnimationQueue every resource already carries -- see scene-builder.ts),
// which is what makes this compose for free with the rest of this
// project's animation machinery: gantry.ts's global op queue
// (advanceOpQueue()) already treats "every resource's own animQueue is
// idle" as part of isEverythingIdle(), so an "incubate" op genuinely
// blocks whatever op comes next until this finishes playing, exactly like
// every other op -- no bespoke bridging code needed for this to work.

import * as THREE from "three";
import { getDurationScale } from "./duration-scale";
import { makeLogger } from "./log";
import type { ResourceEntry } from "./scene-builder";

const log = makeLogger("incubate");

// Deliberately not tied to the real duration_s at all -- per user
// direction, one fixed length regardless of whether the step represents 1
// real minute or 30 -- mirrors thermocycler.ts's own THERMOCYCLER_SHIMMER_MS,
// just shorter (an incubation hold is one beat in a longer protocol, not
// the single centerpiece "cycling" moment run_protocol()'s own shimmer is).
export const INCUBATE_MS = 2500;

// A cool teal/blue pulse -- deliberately distinct from thermocycler.ts's
// warm-orange THERMOCYCLER_SHIMMER_COLOR, so the two "something is
// happening to this resource over time" cues read as different kinds of
// wait at a glance (active thermal cycling vs. a plain timed hold).
const INCUBATE_COLOR = new THREE.Color(0x40c0ff);

export function queueIncubateAnimation(entry: ResourceEntry): void {
  if (!entry.mesh) return;
  const material = entry.mesh.material;
  let baseColor: THREE.Color;
  entry.animQueue.enqueue({
    duration: () => INCUBATE_MS * getDurationScale(),
    onStart: () => {
      baseColor = entry.baseColor!.clone();
      log.info(`${entry.node?.name ?? "?"}: incubation hold started`);
    },
    onTick: (t) => {
      // A handful of full oscillations over the whole window, same
      // "reads as actively happening, not just briefly highlighted"
      // reasoning as queueThermocyclerShimmer()'s own pulse -- raw `t`
      // (AnimationQueue applies no easing of its own), not eased, for the
      // same "easing would distort the oscillation's pacing" reason.
      const pulse = (Math.sin(t * Math.PI * 2 * 4) + 1) / 2;
      material.color.copy(baseColor).lerp(INCUBATE_COLOR, pulse * 0.6);
    },
    onComplete: () => {
      material.color.copy(baseColor);
      log.info(`${entry.node?.name ?? "?"}: incubation hold finished`);
    },
  });
}
