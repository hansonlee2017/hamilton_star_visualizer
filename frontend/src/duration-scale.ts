// Playback speed for review -- a dropdown in the HUD (see dom.ts) sets
// this to 2 (0.5x) or 4 (0.25x) so the animation is easier to follow,
// especially on replay. Read by gantry.ts (every keyframe duration and
// flowPulse) and thermocycler.ts (lid slide + shimmer), written by dom.ts's
// speed-select handler -- pulled into its own tiny module so those three
// don't need to import each other just to share one number.
let durationScale = 1;

export function getDurationScale(): number {
  return durationScale;
}

export function setDurationScale(value: number): void {
  durationScale = value;
}
