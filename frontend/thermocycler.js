// Thermocycler: lid slide + cycling shimmer. Both are plain
// requestAnimationFrame tweens, like gantry.js's flowPulse()/Channel.pulse()
// -- not routed through a Channel's enqueue()'d position queue, since the
// thermocycler itself never moves; only its lid (a short, fixed slide) and
// its block's color (a fixed-duration pulse) do. Called from gantry.js's
// handleOpEvent() on the thermocycler_open_lid/close_lid/run_protocol op
// events, with the resourceIndex entry passed in directly (this module
// never touches resourceIndex itself).

import * as THREE from "three";
import { getDurationScale } from "./duration-scale.js";

export const THERMOCYCLER_LID_MS = 600;
// Deliberately not tied to the backend's own timing at all -- run_protocol()
// completes instantly against the chatterbox backend (see
// thermocycler_backend.py's module docstring for why this visualizer never
// simulates real cycling time), so this fixed window is *the entire reason*
// a "cycling" animation is visible at all.
export const THERMOCYCLER_SHIMMER_MS = 5000;

export function animateThermocyclerLid(entry, opening) {
  if (!entry.lidMesh || !entry.lidOpenPos || !entry.lidClosedPos) return;
  const from = entry.lidMesh.position.clone();
  const to = opening ? entry.lidOpenPos : entry.lidClosedPos;
  entry.lidOpen = opening;
  const start = performance.now();
  const duration = THERMOCYCLER_LID_MS * getDurationScale();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    entry.lidMesh.position.lerpVectors(from, to, t);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// A warm pulsing color on the block itself -- the same "something is
// actively happening here" language gantry.js's flowPulse() uses for a
// channel's tip, scaled to a whole-block, multi-second effect instead of
// one leg's ~550ms.
const THERMOCYCLER_SHIMMER_COLOR = new THREE.Color(0xffa040);
export function animateThermocyclerShimmer(entry) {
  if (!entry.mesh) return;
  const material = entry.mesh.material;
  const baseColor = entry.baseColor.clone();
  const start = performance.now();
  const duration = THERMOCYCLER_SHIMMER_MS * getDurationScale();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    // A handful of full oscillations over the whole window, not one slow
    // fade -- reads as "actively cycling," not just "briefly highlighted."
    const pulse = (Math.sin(t * Math.PI * 2 * 6) + 1) / 2;
    material.color.copy(baseColor).lerp(THERMOCYCLER_SHIMMER_COLOR, pulse * 0.7);
    if (t < 1) {
      requestAnimationFrame(step);
    } else {
      material.color.copy(baseColor);
    }
  };
  requestAnimationFrame(step);
}
