// Live state updates (tip presence / liquid volume) -- Phase 2. Two ways a
// resource's color/opacity gets driven: the generic "state" broadcast (used
// for the initial sync burst and for anything not covered by a gantry op --
// see applyState()) and the timing-correct data a gantry op event embeds
// directly (used for live pick_up_tips/drop_tips/aspirate/dispense -- see
// applyEmbeddedResourceState(), called from gantry.ts's onArrive callbacks).

import * as THREE from "three";
import { resourceIndex } from "./scene-builder";
import { tipColorForVolume, EMPTY_COLOR, EMPTY_OPACITY, FULL_OPACITY } from "./categories";
import type { ResourceStateEntry, StateMessage } from "./types";

const VOLUME_EMPTY_COLOR = new THREE.Color(EMPTY_COLOR);
const VOLUME_FULL_COLOR = new THREE.Color(0x2ee6a8);

export interface VolumeVisual {
  color: THREE.Color;
  opacity: number;
}
export interface TipVisual {
  color: number;
  opacity: number;
}

export function volumeVisual(
  volume: number | null | undefined,
  maxVolume: number | null | undefined
): VolumeVisual {
  const rawFrac = THREE.MathUtils.clamp((volume ?? 0) / (maxVolume || 1), 0, 1);
  // sqrt rather than the raw fraction: a linear scale makes small-but-real
  // volumes (e.g. a 50uL dispense into a 360uL well, 14%) look almost
  // identical to genuinely empty (0%), which is what a well right after a
  // dispense typically looks like right next to a well that's never been
  // touched. sqrt boosts the low end while keeping 0 at 0, 1 at 1, and the
  // ordering monotonic, so "more liquid" still always reads as "brighter."
  const frac = Math.sqrt(rawFrac);
  return {
    color: VOLUME_EMPTY_COLOR.clone().lerp(VOLUME_FULL_COLOR, frac),
    opacity: THREE.MathUtils.lerp(EMPTY_OPACITY, FULL_OPACITY, frac),
  };
}

export function tipVisual(
  hasTip: boolean,
  maxVolumeUl: number | null | undefined
): TipVisual {
  return {
    color: hasTip ? tipColorForVolume(maxVolumeUl) : EMPTY_COLOR,
    opacity: hasTip ? FULL_OPACITY : EMPTY_OPACITY,
  };
}

export function applyState(resourceName: string, state: StateMessage["state"]): void {
  const entry = resourceIndex.get(resourceName);
  if (!entry) return;

  if (Object.prototype.hasOwnProperty.call(state, "tip")) {
    const hasTip = state.tip !== null && state.tip !== undefined;
    if (entry.tipPyramid) {
      const { color, opacity } = tipVisual(hasTip, entry.tipMaxVolumeUl);
      entry.tipPyramid.material.color.setHex(color);
      entry.tipPyramid.material.opacity = opacity;
    }
  } else if (Object.prototype.hasOwnProperty.call(state, "volume") && entry.mesh) {
    const { color, opacity } = volumeVisual(state.volume, state.max_volume);
    entry.mesh.material.color.copy(color);
    entry.mesh.material.opacity = opacity;
    entry.volume = state.volume ?? null;
    if (state.max_volume != null) entry.maxVolume = state.max_volume;
  } else if (Object.prototype.hasOwnProperty.call(state, "protocol_summary")) {
    entry.protocolSummary = state.protocol_summary ?? null;
  }
}

// Applies the resulting tip-presence/volume state that gantry.ts's
// channel_ops_event()-sourced op embeds directly in an "op" event's channel
// entry, timed by the caller (animateChannelOp's onArrive, i.e. exactly
// when the gantry visually arrives) rather than by whenever a separate
// "state" broadcast happens to show up -- see events.py's
// channel_ops_event() docstring for why the latter can't be relied on for
// timing. A no-op for resources without the relevant mesh (e.g. dropping a
// tip into a Trash, which has no tipPyramid).
export function applyEmbeddedResourceState(entry: ResourceStateEntry): void {
  const target = resourceIndex.get(entry.resource);
  if (!target) return;
  if (Object.prototype.hasOwnProperty.call(entry, "resource_has_tip")) {
    if (target.tipPyramid) {
      const { color, opacity } = tipVisual(!!entry.resource_has_tip, target.tipMaxVolumeUl);
      target.tipPyramid.material.color.setHex(color);
      target.tipPyramid.material.opacity = opacity;
    }
  } else if (Object.prototype.hasOwnProperty.call(entry, "resource_volume") && target.mesh) {
    const { color, opacity } = volumeVisual(entry.resource_volume, entry.resource_max_volume);
    target.mesh.material.color.copy(color);
    target.mesh.material.opacity = opacity;
    target.volume = entry.resource_volume ?? null;
    if (entry.resource_max_volume != null) target.maxVolume = entry.resource_max_volume;
  }
}
