// Gantry model + animation -- Phase 3. The 8(-ish)-channel arm: per-channel
// position queues (see Channel below), hardware-feasible motion planning
// across channels (planGantryPasses()/resolveChannelYs()), and the "op"
// event dispatcher (handleOpEvent()) that turns VisualizerBackend's
// pick_up_tips/drop_tips/aspirate/dispense/thermocycler_* events into that
// motion.

import * as THREE from "three";
import { mapPoint } from "./coordinates.js";
import { tipColorForVolume, EMPTY_COLOR, TIP_PRESENT_COLOR_FALLBACK } from "./categories.js";
import { TIP_PYRAMID_RADIUS, TIP_PYRAMID_HEIGHT, resourceIndex } from "./scene-builder.js";
import { applyEmbeddedResourceState } from "./resource-state.js";
import { queueLidAnimation, queueThermocyclerShimmer } from "./thermocycler.js";
import { getDurationScale } from "./duration-scale.js";
import { logEvent } from "./dom.js";
import { CHANNEL_PITCH_MM, resolveChannelYs, planGantryPasses as planGantryPassesPure } from "./gantry-planning.js";
import { MotionUnit } from "./motion-unit.js";

export { CHANNEL_PITCH_MM, resolveChannelYs };

export const NUM_CHANNELS_DEFAULT = 8;
const CHANNEL_Y_SPACING = 9; // mm, matches PLR's default minimum channel spacing
let restZ = 350;

// Called by main.js's loadScene() wrapper once the new deck's bounding box
// is known -- see that function for why this can't just live here (this
// module never touches sceneRoot/camera/logEvent itself, keeping it a
// clean leaf on that side of the graph).
export function setRestZ(value) {
  restZ = value;
}

export const gantryGroup = new THREE.Group();

// A small repeating-stripe gradient, scrolled via `map.offset.y` to read as
// liquid flowing up (aspirate) or down (dispense) through the tip. Built
// once on a canvas -- cheap, no external assets, no shader code.
function createFlowTexture(lightColor, darkColor) {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0.0, lightColor);
  gradient.addColorStop(0.25, darkColor);
  gradient.addColorStop(0.5, lightColor);
  gradient.addColorStop(0.75, darkColor);
  gradient.addColorStop(1.0, lightColor);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1, 3);
  return texture;
}
// Aspirate (liquid entering the tip) and dispense (leaving it) get their
// own colors -- red vs. blue -- so which direction a channel's mid-flow
// pulse is doing is readable from the color alone, not just the scroll
// direction (subtle at a glance, especially at a distance or mid-animation).
const FLOW_TEXTURE_ASPIRATE = createFlowTexture("#ffd6d6", "#c73a3a");
const FLOW_TEXTURE_DISPENSE = createFlowTexture("#bfeaff", "#2f8fc4");
const FLOW_PULSE_MS = 550;
const PULSE_COLOR = new THREE.Color(0xffffff);
// The channel's own carried-tip glyph is longer than the ones resting in
// the rack -- see animateChannelOp()'s CHANNEL_TIP_HEIGHT offset, which
// relies on this length to keep the channel *body* clear of whatever
// labware the tip is reaching into (a well, a rack, the trash). Radius
// stays under half the 9mm channel spacing so neighboring channels' tips
// never visually touch.
const CHANNEL_TIP_RADIUS = TIP_PYRAMID_RADIUS * 1.3;
const CHANNEL_TIP_HEIGHT = TIP_PYRAMID_HEIGHT * 2.2;

export class Channel {
  constructor(index) {
    this.index = index;
    // Negative: on a real Hamilton (and in PLR's own per-channel offsets --
    // e.g. an 8-channel drop_tips reports trash offsets +31.5, +22.5, ...,
    // -31.5 for channels 0-7, 9mm apart), channel 0 is the back-most
    // channel and increasing index moves toward the front (-y, PLR's "back"
    // axis -- see coordinates.js's mapPoint() docstring). A plain `+index *
    // CHANNEL_Y_SPACING` here put channel 0 at the front and channel 7 at
    // the back instead -- the whole rest row was mirrored front-to-back.
    // The leg-tweening/queue mechanics themselves live in a composed
    // MotionUnit (see motion-unit.js) -- shared with a future Core96Head,
    // per docs/PLAN.md's "Review round 37" design discussion -- not
    // reimplemented here.
    this.motion = new MotionUnit(
      { x: 0, y: -index * CHANNEL_Y_SPACING, z: restZ },
      () => this.applyPosition()
    );
    this.hasTip = false;

    this.group = new THREE.Group();

    // Sized a bit larger than a real Hamilton channel nose would be in mm --
    // a to-scale glyph is nearly invisible against a ~1m deck, and legibility
    // matters more here than strict scale accuracy for this one part.
    const bodyGeom = new THREE.CylinderGeometry(7, 7, 32, 12);
    this.body = new THREE.Mesh(bodyGeom, new THREE.MeshLambertMaterial({ color: 0x9aa0a8 }));
    this.body.position.y = 16;
    this.group.add(this.body);

    // Same inverted-pyramid shape as the tips resting in the rack (see
    // scene-builder.js's buildResourceObject) -- a bit longer than those
    // (see CHANNEL_TIP_HEIGHT) so the *body* clears the target labware's
    // top by a comfortable margin once animateChannelOp() accounts for it,
    // and a bit wider for readability, while staying under half the 9mm
    // channel spacing so adjacent channels' tips never touch.
    const tipGeom = new THREE.ConeGeometry(CHANNEL_TIP_RADIUS, CHANNEL_TIP_HEIGHT, 4);
    this.tipMesh = new THREE.Mesh(tipGeom, new THREE.MeshLambertMaterial({ color: EMPTY_COLOR }));
    this.tipMesh.position.y = -CHANNEL_TIP_HEIGHT / 2;
    // Flip apex-down (see the matching comment in scene-builder.js's
    // buildResourceObject).
    this.tipMesh.rotation.x = Math.PI;
    this.tipMesh.rotation.y = Math.PI / 4;
    this.tipMesh.visible = false;
    this.group.add(this.tipMesh);
    // Current effective tip length -- CHANNEL_TIP_HEIGHT until a real
    // pick-up reports the actual tip's length via setTip(); also what
    // animateChannelOp uses for body-clearance on every subsequent op this
    // channel does with that tip (aspirate/dispense/drop), not just the
    // pick-up itself.
    this.tipLength = CHANNEL_TIP_HEIGHT;

    // Own clones (one per direction) so this channel's scroll offset can't
    // fight another channel's concurrent flowPulse(), and so an aspirate
    // pulse and a dispense pulse never have to share one texture's offset
    // state even on the same channel.
    this.aspirateFlowTexture = FLOW_TEXTURE_ASPIRATE.clone();
    this.dispenseFlowTexture = FLOW_TEXTURE_DISPENSE.clone();

    gantryGroup.add(this.group);
    this.applyPosition();
  }

  // Delegates to the composed MotionUnit -- external readers (e.g.
  // gantry-planning.js's planGantryPasses(), reading `channels[ch].pos.y`)
  // keep working unchanged; nothing outside this class ever *writes*
  // `.pos` (the MotionUnit owns that), so a getter-only property is safe.
  get pos() {
    return this.motion.pos;
  }

  applyPosition() {
    const p = mapPoint(this.pos.x, this.pos.y, this.pos.z);
    this.group.position.copy(p);
  }

  // `lengthMm`/`maxVolumeUl`: the real length and nameplate capacity of
  // the tip just picked up (from the pick_up_tips op event's
  // tip_length_mm/tip_max_volume_ul -- see events.py), so the glyph
  // matches the actual tip instead of the CHANNEL_TIP_HEIGHT placeholder
  // and generic fallback color. Geometry is rebuilt (not just visually
  // toggled) since length also feeds animateChannelOp's body-clearance
  // math for every op this channel does until its next pick-up -- see
  // `tipLength` below.
  setTip(visible, lengthMm, maxVolumeUl) {
    this.hasTip = visible;
    this.tipMesh.visible = visible;
    this.tipMesh.material.color.setHex(visible ? tipColorForVolume(maxVolumeUl) : EMPTY_COLOR);
    if (visible) {
      const length = lengthMm ?? CHANNEL_TIP_HEIGHT;
      if (length !== this.tipLength) {
        this.tipMesh.geometry.dispose();
        this.tipMesh.geometry = new THREE.ConeGeometry(CHANNEL_TIP_RADIUS, length, 4);
        this.tipMesh.position.y = -length / 2;
        this.tipLength = length;
      }
    }
  }

  pulse() {
    this.body.material.color.copy(PULSE_COLOR);
    setTimeout(() => this.body.material.color.setHex(0x9aa0a8), 250 * getDurationScale());
  }

  // direction: +1 to scroll "up" (aspirate -- liquid entering the tip,
  // red), -1 to scroll "down" (dispense -- liquid leaving it, blue).
  flowPulse(direction) {
    const material = this.tipMesh.material;
    const restoreColor = material.color.clone();
    const texture = direction > 0 ? this.aspirateFlowTexture : this.dispenseFlowTexture;
    material.map = texture;
    material.color.setHex(0xffffff); // let the texture's own colors show through
    material.needsUpdate = true;

    const start = performance.now();
    const duration = FLOW_PULSE_MS * getDurationScale();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      texture.offset.y = direction * t * 2; // a couple of texture repeats' worth of scroll
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        material.map = null;
        material.color.copy(restoreColor);
        material.needsUpdate = true;
      }
    };
    requestAnimationFrame(step);
  }

  // `target.x`/`target.y`/`target.z` may each be `null`, meaning "stay at
  // whatever this leg actually starts from on that axis" -- used for the
  // rise-to-safe-height leg (x/y must not move horizontally) and for
  // nudge_channel ops that only change one of x/y (see handleOpEvent's
  // "nudge_channel" case). `target.z` may instead be a function -- either
  // `() => number` (the descend/hold legs' tip-length-aware depth -- see
  // animateChannelOp()) or `(from) => number` (a rise/retract leg's
  // traverse-height target, which needs to know where *this* leg is
  // actually starting from -- see traverseLegZ()'s docstring for why).
  // `duration` may also be a function (`(from, target) => number`), same
  // staleness reasoning -- see animateChannelOp()'s traverseHeightMm/
  // endHeightMm handling. All the actual lazy-resolution/queueing/easing
  // mechanics live in the composed MotionUnit now (motion-unit.js) -- this
  // is just a same-shaped pass-through, kept so every call site elsewhere
  // in this file doesn't need to know a Channel is secretly a MotionUnit.
  enqueue(target, duration, onComplete) {
    this.motion.enqueue(target, duration, onComplete);
  }

  update(dtMs) {
    this.motion.update(dtMs);
  }
}

export let channels = [];
export function ensureChannels(numChannels) {
  // Always rebuilt (not just when the count changes) so a fresh "scene"
  // message -- including the one that kicks off a replay -- also resets
  // the gantry back to its rest pose, not just the deck/plates/tips.
  for (const ch of channels) gantryGroup.remove(ch.group);
  channels = Array.from({ length: numChannels }, (_, i) => new Channel(i));
}

const RISE_MS = 350;
// Split into two legs, not one combined diagonal move -- a real Hamilton
// STAR's x motor is shared by the whole arm and its y motor is per-channel,
// so a move is physically x-then-y, never simultaneous (see
// hamilton_visualizer.gantry's module docstring and docs/PLAN.md's
// round-10 write-up). 200+200 keeps the total roughly the same as the old
// single 400ms diagonal leg.
const X_MOVE_MS = 200;
const Y_MOVE_MS = 200;
const DESCEND_MS = 350;
const HOLD_MS = 150;
const RETRACT_MS = 350;

const scaled = (ms) => ms * getDurationScale();

// traverseHeightMm/endHeightMm (see events.py's channel_ops_event()
// docstring) are expressed in *tip-point* terms -- how high the tip's own
// point should clear a resource by -- not the *body-origin* Z every leg
// actually moves (a channel's body sits *above* the tip's point by the
// tip's own length). Converting needs `+ this op's own tip length` --
// getting this wrong doesn't just look slightly off: since a typical tip
// is ~50-95mm long, using a tip-point height directly as a body-origin Z
// can put the rise/retract leg *below* the descend leg's own body-origin Z
// (a real bug this once was -- see docs/PLAN.md's "Review round 23"), which
// both inverts the rise-then-descend order (the channel visibly moves *up*
// where it should move *down*) and, during the X/Y travel at that wrong
// height, puts the tip's own rendered point below the resource's rim it
// was supposed to be clearing -- exactly the "pierce through the well"/
// "clip through the reservoir" look. `tipLengthFn` is a function, not a
// value, for the same staleness reason `targetZ()` below is one:
// `ch.tipLength` can't safely be read before the leg actually starts (see
// enqueue()'s docstring).
//
// Deliberately *only* the Z target, not the duration: round 23 also scaled
// RISE_MS/RETRACT_MS down to match, and round 24 tried sharing that scaled
// duration across a whole gantry pass so active and idle channels landed
// on the same total -- but different passes (e.g. the diluent-distribution
// loop's 7 separate single-channel aspirate calls, each computing its own
// duration from its own entry.z, which drifts slightly as the tube drains)
// could still disagree slightly, and a real Hamilton's channels move at a
// fixed physical speed regardless of how far a given leg travels anyway --
// scaling duration was never realistic, just an animation embellishment
// that turned out to be the actual source of the desync. Every leg now
// always takes its fixed nominal duration (see docs/PLAN.md's "Review
// round 26") -- simpler, and there's no computation left that could ever
// disagree between channels.
// `(from) => number`, not `() => number`: a resource-specific traverse
// height only ever accounts for clearing *that* resource's own rim --
// it says nothing about whatever the channel might currently be sitting
// over (a different, possibly taller, resource or carrier from a *previous*
// op). The rise leg this feeds runs *before* X/Y move (see
// animateChannelOp()'s leg order), so if its target were allowed to sit
// below the channel's actual current height, the channel would drop in Z
// first, still at the *old* X/Y, then translate horizontally at that now-
// too-low height -- clipping straight through whatever's actually at the
// old position (a carrier wall, an adjacent tube) before ever reaching
// the new one. Clamping against `from.z` (the incoming leg's own starting
// height, resolved fresh every time -- see enqueue()'s docstring) means
// this leg only ever *rises or holds level* before translating, never
// dips first; all the real descending happens in the dedicated descend
// leg, once X/Y are already correct (confirmed live -- see docs/PLAN.md's
// "Review round 27" for the "clips the carrier after pick_up_tips" bug
// this fixes).
export function traverseLegZ(tipHeightMm, refZ, tipLengthFn) {
  if (tipHeightMm == null) return restZ;
  return (from) => {
    const tipLength = tipLengthFn();
    const currentZ = from ? from.z : 0;
    return Math.min(restZ, Math.max(refZ + tipLength, tipHeightMm + tipLength, currentZ));
  };
}

// `tipLength`: override for the pick_up_tips case, where the tip that
// matters for this op's clearance is the one about to be grabbed (from the
// op event's tip_length_mm), not whatever this channel was last carrying --
// see events.py's tip_length_mm comment. Every other op omits it and falls
// back to the channel's own remembered `tipLength` (set by its last
// pick-up), since it's still carrying that same tip throughout.
function animateChannelOp(entry, { onArrive, tipLength, traverseHeightMm, endHeightMm } = {}) {
  const ch = channels[entry.channel];
  if (!ch) return;
  // `entry.z` (from the server) is where the *tip's point* should end up --
  // see events.py's tip_grab_point()/liquid_surface_point(). The channel
  // group's own origin is where the tip *meets the body*, above the tip's
  // apex by the tip's own real length -- offsetting by that length keeps
  // the body clear of the target labware, so only the tip appears to enter
  // it (see docs/PLAN.md for the "pipette entering the well" bug this
  // fixes). A function, not a number: see enqueue()'s docstring for why
  // `ch.tipLength` must be read when the leg *starts*, not now.
  const targetZ = () => entry.z + (tipLength ?? ch.tipLength);
  const tipLengthFn = () => tipLength ?? ch.tipLength;

  const riseZ = traverseLegZ(traverseHeightMm, entry.z, tipLengthFn);
  const retractZ = traverseLegZ(endHeightMm, entry.z, tipLengthFn);

  // x/y: null means "stay wherever this leg actually starts" -- see
  // enqueue()'s docstring for why that can't just be ch.pos.x/y here.
  // Real Hamilton STAR motion order -- the shared-x arm moves first, then
  // this channel's own y motor, then z finally descends to do the actual
  // work -- never x/y together and never z before both are in place. See
  // planGantryPasses() below for the same "x is shared, y is per-channel"
  // fact applied *across* channels, not just within one channel's own
  // approach.
  ch.enqueue({ x: null, y: null, z: riseZ }, scaled(RISE_MS));
  ch.enqueue({ x: entry.x, y: null, z: riseZ }, scaled(X_MOVE_MS));
  ch.enqueue({ x: entry.x, y: entry.y, z: riseZ }, scaled(Y_MOVE_MS));
  // onArrive fires exactly when this leg's tween completes -- see enqueue()'s
  // docstring for why that's not the same as a fixed setTimeout delay.
  ch.enqueue({ x: entry.x, y: entry.y, z: targetZ }, scaled(DESCEND_MS), onArrive);
  ch.enqueue({ x: entry.x, y: entry.y, z: targetZ }, scaled(HOLD_MS));
  ch.enqueue({ x: entry.x, y: entry.y, z: retractZ }, scaled(RETRACT_MS));
}

// resolveChannelYs()/planGantryPasses() themselves are pure motion-planning
// math with no THREE.js/DOM dependency -- split out into gantry-planning.js
// so `node --test` can exercise them directly (see
// tests/frontend/gantry-planning.test.js). This is just a thin wrapper
// supplying this module's own live `channels` array, matching the plain
// `planGantryPasses(entries)` call shape the rest of this file already
// uses.
function planGantryPasses(entries) {
  return planGantryPassesPure(entries, channels);
}

// Cosmetic-only reposition for a channel that isn't doing anything at this
// gantry stop but still needs to be dragged along (or nudged clear) -- see
// planGantryPasses()'s docstring. No visible descend/hold since it's never
// touching labware, but the total *duration* still has to match an active
// channel's full RISE+X+Y+DESCEND+HOLD+RETRACT cycle exactly, padded out
// with a final no-op wait -- every channel's own queue is independent
// (Channel.enqueue()'s docstring), so if an idle channel's queue drained
// faster than an active one sharing this same stop, it would start the
// *next* stop's legs while the active channel here is still mid-descend,
// and the arm would visibly stop moving together pass-by-pass despite
// each channel's own motion still being correctly ordered on its own.
// (Confirmed live: recording all 8 channels' position and classifying
// which axis was moving showed exactly this -- one channel already
// descending while another, from the *next* pass, was already moving in
// y -- until this padding was added.) Every leg here uses the fixed
// nominal duration (RISE_MS/etc, never scaled down for a traverse-height
// override -- see animateChannelOp()'s docstring for why), so this always
// matches an active channel's own total exactly, with no computation that
// could ever disagree between channels.
//
// `traverseHeightMm`/`endHeightMm` (this channel's own, since it may be
// carrying a different tip than the pass's active channel -- unlikely in
// any protocol this demo runs today, but the Z math doesn't assume it)
// still adjust *where* it travels, same reasoning as animateChannelOp()'s
// riseZ/retractZ; unlike that function, there's no "this op's own working
// depth" floor to clamp against here (an idle channel isn't descending
// anywhere this pass), so it only ever clamps against the restZ ceiling
// and -- same reason as traverseLegZ()'s own `from` clamp -- against
// wherever this leg is actually starting from, so an idle channel dragged
// along at a reduced height never dips down before its own X/Y move either.
function nudgeChannel(channelIndex, x, y, { traverseHeightMm, endHeightMm } = {}) {
  const ch = channels[channelIndex];
  if (!ch) return;
  const riseZ =
    traverseHeightMm != null
      ? (from) => Math.min(restZ, Math.max(traverseHeightMm + ch.tipLength, from ? from.z : 0))
      : restZ;
  const retractZ =
    endHeightMm != null
      ? (from) => Math.min(restZ, Math.max(endHeightMm + ch.tipLength, from ? from.z : 0))
      : restZ;

  ch.enqueue({ x: null, y: null, z: riseZ }, scaled(RISE_MS));
  ch.enqueue({ x, y: null, z: riseZ }, scaled(X_MOVE_MS));
  ch.enqueue({ x, y, z: riseZ }, scaled(Y_MOVE_MS));
  ch.enqueue({ x, y, z: retractZ }, scaled(DESCEND_MS + HOLD_MS + RETRACT_MS));
}

function flashResource(resourceName) {
  const entry = resourceIndex.get(resourceName);
  if (!entry || !entry.mesh) return;
  const base = entry.mesh.material.color.clone();
  entry.mesh.material.color.copy(PULSE_COLOR);
  setTimeout(() => entry.mesh.material.color.copy(base), 250 * getDurationScale());
}

// Enqueues one multi-channel op's legs, pass by pass, using
// planGantryPasses() -- shared by pick_up_tips/drop_tips/aspirate/dispense
// below, which differ only in each active entry's onArrive effect.
// `makeOnArrive(entry)` builds that per-entry callback.
function animateChannelGroupOp(entries, makeOnArrive, { tipLengthFor, traverseHeightMm, endHeightMm } = {}) {
  for (const pass of planGantryPasses(entries)) {
    for (const [ch, y] of pass.idleMoves) {
      nudgeChannel(ch, pass.x, y, { traverseHeightMm, endHeightMm });
    }
    for (const entry of pass.active) {
      animateChannelOp(entry, {
        onArrive: makeOnArrive(entry),
        tipLength: tipLengthFor ? tipLengthFor(entry) : undefined,
        traverseHeightMm,
        endHeightMm,
      });
    }
  }
}

// ---------------------------------------------------------------------------
// CO-RE 96 head
// ---------------------------------------------------------------------------
// A single rigid block that engages an entire 96-well plate/rack at once
// (pick_up_tips96/aspirate96/dispense96/drop_tips96), as opposed to the 8
// individual Channels above, which each act on one well/tip at a time.
// Reuses motion-unit.js's MotionUnit for its own rise/x/y/descend/hold/
// retract leg motion -- the same class, and the same leg pattern,
// Channel itself now composes (see docs/PLAN.md's "Review round 37"
// design discussion for why that split exists, and "Review round 39" for
// this actually using it).
//
// Deliberately *not* coordinated with the 8 channels' own shared-X gantry
// stops (planGantryPasses()) -- they're mechanically on the same physical
// X drive on a real Hamilton STAR but sit at different absolute X
// (offset along the rail), and the two are never actually used
// concurrently in any protocol this repo runs -- see docs/PLAN.md's
// "Review round 37" "Deferred: cross-mechanism X sharing" note for the
// sketch of how to add that once it's actually needed.

// Every labware the head ever engages -- tip racks, well plates, troughs
// -- shares the same SBS/ANSI microplate footprint, so a single fixed
// size (not resized per op) is both simpler and accurate enough; same
// reasoning as scene-builder.js's thermocycler lid being sized off the
// real plate footprint rather than the housing it happens to be on.
const CORE96_SIZE_X_MM = 127.76;
const CORE96_SIZE_Y_MM = 85.48;
const CORE96_HEIGHT_MM = 30; // visual thickness only -- not a real spec, just enough to read as a rigid block
// A few mm of clearance above the target resource's own reported top
// (resource_point()'s top-center anchor -- see events.py) so the block's
// bottom face doesn't z-fight with the labware mesh directly below it
// when "descended" -- the same kind of small fixed margin
// scene-builder.js's thermocycler lid uses around the real plate.
const CORE96_ENGAGE_CLEARANCE_MM = 3;
const CORE96_EMPTY_COLOR = 0x4fa8c9;
// The head's own 96 tip positions: an 8-row x 12-column grid at the same
// 9mm pitch a real 96-well plate (and CHANNEL_PITCH_MM, the 8 individual
// channels' own spacing) already uses -- not offset to any one specific
// plate's real A1 corner, just centered on the block's own footprint,
// which is close enough to read correctly without needing per-target
// well-position data. Each tip glyph is the exact same geometry/rotation/
// color Channel.tipMesh uses for a single carried tip (per user
// direction: "the same implementation as the multi-channel pipettes,
// where you can see the tips attached to them") -- toggled by
// setTips(present) via `.visible`, the same way, not a hue/opacity change.
const CORE96_TIP_ROWS = 8;
const CORE96_TIP_COLS = 12;
// Parked position when nothing's queued -- off to one side so it doesn't
// sit in the middle of a deck screenshot when unused. Not a real
// Hamilton home-position value (this project doesn't model the 96-head's
// own parking mechanism), just a reasonable out-of-the-way constant.
const CORE96_REST_X_MM = 60;
const CORE96_REST_Y_MM = 40;

class Core96Head {
  constructor() {
    this.motion = new MotionUnit(
      { x: CORE96_REST_X_MM, y: CORE96_REST_Y_MM, z: restZ },
      () => this.applyPosition()
    );
    this.hasTips = false;

    this.group = new THREE.Group();
    const geometry = new THREE.BoxGeometry(CORE96_SIZE_X_MM, CORE96_HEIGHT_MM, CORE96_SIZE_Y_MM);
    this.body = new THREE.Mesh(
      geometry,
      new THREE.MeshLambertMaterial({ color: CORE96_EMPTY_COLOR, transparent: true, opacity: 0.85 })
    );
    // Group origin is the block's own *bottom* engaging face (matching
    // `pos.z`'s meaning as "where the head touches down"), so the body
    // extends upward from there, centered on the group's own x/z origin
    // (unlike scene-builder.js's corner-anchored resources) -- simplest
    // frame for the tip grid below to be centered in too.
    this.body.position.y = CORE96_HEIGHT_MM / 2;
    this.group.add(this.body);

    // 96 tip cones, hanging below the block the same way a single
    // Channel's own tipMesh hangs below its body -- see this class's own
    // CORE96_TIP_ROWS/COLS comment. All 96 share one geometry and one
    // material (not 96 independent ones) -- every tip in one rack is
    // normally the same model, so there's only ever one real length/color
    // to represent at a time, and setTips() below rebuilds/recolors this
    // one shared pair for all 96 at once, the same way Channel.setTip()
    // rebuilds its own single tipMesh's geometry when the real tip's
    // length differs from CHANNEL_TIP_HEIGHT's placeholder.
    this.tipLength = CHANNEL_TIP_HEIGHT;
    this.tipGeometry = new THREE.ConeGeometry(CHANNEL_TIP_RADIUS, CHANNEL_TIP_HEIGHT, 4);
    this.tipMaterial = new THREE.MeshLambertMaterial({ color: TIP_PRESENT_COLOR_FALLBACK });
    this.tipMeshes = [];
    for (let row = 0; row < CORE96_TIP_ROWS; row++) {
      for (let col = 0; col < CORE96_TIP_COLS; col++) {
        const tip = new THREE.Mesh(this.tipGeometry, this.tipMaterial);
        const localX = (col - (CORE96_TIP_COLS - 1) / 2) * CHANNEL_PITCH_MM;
        const localZ = (row - (CORE96_TIP_ROWS - 1) / 2) * CHANNEL_PITCH_MM;
        tip.position.set(localX, -CHANNEL_TIP_HEIGHT / 2, localZ);
        // Flip apex-down + diamond-facing, exactly matching Channel's own
        // tipMesh and scene-builder.js's resting-tip pyramids.
        tip.rotation.x = Math.PI;
        tip.rotation.y = Math.PI / 4;
        tip.visible = false;
        this.group.add(tip);
        this.tipMeshes.push(tip);
      }
    }

    gantryGroup.add(this.group);
    this.applyPosition();
  }

  get pos() {
    return this.motion.pos;
  }

  applyPosition() {
    const p = mapPoint(this.pos.x, this.pos.y, this.pos.z);
    this.group.position.copy(p);
  }

  // `lengthMm`/`maxVolumeUl`: the real length and nameplate capacity of
  // the representative tip visualizer_backend.py's pick_up_tips96 found
  // on the rack (see that function's own comment) -- mirrors Channel.
  // setTip() exactly: geometry only gets rebuilt (and every one of the 96
  // meshes repositioned to the new length) when the length actually
  // differs from what's currently built, and color follows
  // tipColorForVolume() the same capacity-bucket way a single channel's
  // carried tip does, not always the flat fallback amber.
  setTips(present, lengthMm, maxVolumeUl) {
    this.hasTips = present;
    for (const tip of this.tipMeshes) tip.visible = present;
    if (!present) return;
    this.tipMaterial.color.setHex(tipColorForVolume(maxVolumeUl));
    const length = lengthMm ?? CHANNEL_TIP_HEIGHT;
    if (length !== this.tipLength) {
      this.tipGeometry.dispose();
      this.tipGeometry = new THREE.ConeGeometry(CHANNEL_TIP_RADIUS, length, 4);
      for (const tip of this.tipMeshes) {
        tip.geometry = this.tipGeometry;
        tip.position.y = -length / 2;
      }
      this.tipLength = length;
    }
  }

  enqueue(target, duration, onComplete) {
    this.motion.enqueue(target, duration, onComplete);
  }

  update(dtMs) {
    this.motion.update(dtMs);
  }
}

export const core96Head = new Core96Head();

// Same six-leg rise/x/y/descend/hold/retract shape as animateChannelOp(),
// just for one rigid body instead of one channel among eight -- no
// planGantryPasses()/idle-channel dragging needed, since there's nothing
// else on this mechanism's own motion queue to coordinate with (see this
// section's own header comment for why the 8 channels aren't dragged
// along here either, at least not yet).
function animateCore96Op(msg, onArrive) {
  const targetZ = () => msg.z + CORE96_ENGAGE_CLEARANCE_MM;
  core96Head.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  core96Head.enqueue({ x: msg.x, y: null, z: restZ }, scaled(X_MOVE_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: restZ }, scaled(Y_MOVE_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: targetZ }, scaled(DESCEND_MS), onArrive);
  core96Head.enqueue({ x: msg.x, y: msg.y, z: targetZ }, scaled(HOLD_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: restZ }, scaled(RETRACT_MS));
}

export function handleOpEvent(msg) {
  switch (msg.op) {
    case "pick_up_tips":
      animateChannelGroupOp(
        msg.channels,
        (entry) => () => {
          channels[entry.channel]?.setTip(true, entry.tip_length_mm, entry.tip_max_volume_ul);
          applyEmbeddedResourceState(entry);
        },
        { tipLengthFor: (entry) => entry.tip_length_mm }
      );
      logEvent("pick_up_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "drop_tips":
      animateChannelGroupOp(msg.channels, (entry) => () => {
        channels[entry.channel]?.setTip(false);
        applyEmbeddedResourceState(entry);
      });
      logEvent("drop_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "aspirate":
    case "dispense": {
      // Liquid flows "up" into the tip on aspirate, "down" out of it on
      // dispense -- see Channel.flowPulse().
      const flowDirection = msg.op === "aspirate" ? 1 : -1;
      animateChannelGroupOp(
        msg.channels,
        (entry) => () => {
          channels[entry.channel]?.pulse();
          channels[entry.channel]?.flowPulse(flowDirection);
          // Apply the real color *before* flashing -- flashResource()
          // captures whatever color is current as what to revert to, so
          // flashing first would revert back to the stale pre-dispense
          // shade instead of the one we just set.
          applyEmbeddedResourceState(entry);
          flashResource(entry.resource);
        },
        // Only present when the protocol script actually set the
        // underlying STARBackend kwargs (see events.py's
        // channel_ops_event() docstring) -- undefined otherwise, which
        // animateChannelOp() already treats as "use restZ, unchanged."
        { traverseHeightMm: msg.traverse_height_mm, endHeightMm: msg.end_height_mm }
      );
      logEvent(
        msg.op,
        msg.channels.map((c) => `p${c.channel}:${c.resource} (${c.volume}µL)`).join(", ")
      );
      break;
    }
    case "thermocycler_open_lid":
    case "thermocycler_close_lid": {
      const entry = resourceIndex.get(msg.resource);
      if (entry) queueLidAnimation(entry, msg.op === "thermocycler_open_lid");
      logEvent(msg.op, msg.resource ?? "");
      break;
    }
    case "thermocycler_run_protocol": {
      const entry = resourceIndex.get(msg.resource);
      if (entry) {
        entry.protocolSummary = msg.protocol_summary;
        queueThermocyclerShimmer(entry);
      }
      logEvent(msg.op, `${msg.resource}: ${msg.protocol_summary ?? ""}`);
      break;
    }
    case "pick_up_tips96":
      animateCore96Op(msg, () => {
        core96Head.setTips(true, msg.tip_length_mm, msg.tip_max_volume_ul);
        // Every one of the rack's 96 spots empties at once -- see
        // visualizer_backend.py's pick_up_tips96 for why this needs no
        // tracker read, same reasoning channel_ops_event() uses for a
        // single-channel pickup. Reuses applyEmbeddedResourceState()
        // (resource-state.js) verbatim, one call per spot -- the per-item
        // shape (`resource`/`resource_has_tip`) deliberately matches what
        // that function already expects from a single-channel op.
        for (const spot of msg.tip_spots ?? []) applyEmbeddedResourceState(spot);
      });
      logEvent("pick_up_tips96", msg.resource ?? "");
      break;
    case "drop_tips96":
      animateCore96Op(msg, () => {
        core96Head.setTips(false);
        for (const spot of msg.tip_spots ?? []) applyEmbeddedResourceState(spot);
      });
      logEvent("drop_tips96", msg.resource ?? "");
      break;
    case "aspirate96":
    case "dispense96": {
      animateCore96Op(msg, () => {
        // Same reuse as the tip-spot case above, one call per well --
        // visualizer_backend.py's _well_volume_entries() builds these with
        // field names matching a single-channel aspirate/dispense's own
        // embedded resource_volume/resource_max_volume specifically so
        // this needs no separate per-well handling here.
        for (const well of msg.wells ?? []) applyEmbeddedResourceState(well);
        flashResource(msg.resource);
      });
      logEvent(msg.op, `${msg.resource} (${msg.volume}µL)`);
      break;
    }
    default:
      // resource-move / manual-jog events: not animated in v1, but still
      // worth surfacing in the log so the panel reflects everything the
      // backend did.
      logEvent(msg.op, msg.resource ?? "");
  }
}
