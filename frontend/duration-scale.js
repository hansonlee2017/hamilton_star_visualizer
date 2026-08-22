// Playback speed for review -- a dropdown in the HUD (see dom.js) sets
// this to 2 (0.5x) or 4 (0.25x) so the animation is easier to follow,
// especially on replay. Read by gantry.js (every keyframe duration and
// flowPulse) and thermocycler.js (lid slide + shimmer), written by dom.js's
// speed-select handler -- pulled into its own tiny module so those three
// don't need to import each other just to share one number.
let durationScale = 1;

export function getDurationScale() {
  return durationScale;
}

export function setDurationScale(value) {
  durationScale = value;
}
