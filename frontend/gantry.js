// Gantry model + animation -- Phase 3. The 8(-ish)-channel arm: per-channel
// position queues (see Channel below), hardware-feasible motion planning
// across channels (planGantryPasses()/resolveChannelYs()), and the "op"
// event dispatcher (handleOpEvent()) that turns VisualizerBackend's
// pick_up_tips/drop_tips/aspirate/dispense/thermocycler_* events into that
// motion.

import * as THREE from "three";
import { mapPoint } from "./coordinates.js";
import { tipColorForVolume, EMPTY_COLOR, TIP_PRESENT_COLOR_FALLBACK, CORE_GRIPPER_PAD_COLOR } from "./categories.js";
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

// Set once by main.js right after it creates its own `sceneRoot` (unlike
// `gantryGroup`, which this module owns and exports the other way, main.js
// owns `sceneRoot` -- see that file's own header comment for the module
// boundary). Needed only for a CoRe-gripper drop's reparent-back-to-the-
// scene step (see handleOpEvent's "core_drop_resource" case) -- every
// other op in this file only ever touches `gantryGroup`/`channels`/
// `core96Head`, which is why nothing before this feature ever needed it.
let sceneRoot = null;
export function setSceneRoot(root) {
  sceneRoot = root;
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
// A CoRe gripper pad glyph's size -- a small rectangular block (per user
// direction: "you can render them as rectangle cubes"), not scaled to any
// real pad dimension (this project doesn't model the pad's own geometry,
// same "legible, not to scale" tradeoff as CHANNEL_TIP_RADIUS/HEIGHT above)
// -- just compact enough to read as a distinct fixture at the channel's
// nose rather than another tip.
const CORE_GRIPPER_PAD_SIZE_MM = 10;
const CORE_GRIPPER_PAD_HEIGHT_MM = 14;

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
    // Rest X derived from the 96-head's own rest position (parked just
    // above its own trash, see CORE96_REST_X_MM's own comment) plus the
    // same CORE96_X_OFFSET_MM every cross-mechanism drag already uses --
    // not an independent number -- so the two mechanisms start out
    // already consistent with the relationship they're dragged to
    // maintain, instead of only becoming so once the first op fires.
    // Forward reference to constants defined later in this file (with
    // Core96Head) -- safe: this constructor only ever runs from
    // ensureChannels(), itself only called once a "scene" message
    // arrives, long after the whole module (and every one of its
    // module-level consts) has finished evaluating.
    this.motion = new MotionUnit(
      { x: CORE96_REST_X_MM + CORE96_X_OFFSET_MM, y: -index * CHANNEL_Y_SPACING, z: restZ },
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

    // A CoRe gripper pad, attached "just like a tip" per user direction --
    // same hanging-below-the-body position as tipMesh (a channel only ever
    // carries one or the other in real use, never both at once, so sharing
    // the spot is fine), but a rectangular block instead of a cone -- see
    // CORE_GRIPPER_PAD_COLOR's own comment for why a distinct shape/color.
    // Hidden until a "core_pick_up_resource" op says this channel now holds
    // one -- see setPad()/gantry.js's own setGripperPadChannels().
    const padGeom = new THREE.BoxGeometry(
      CORE_GRIPPER_PAD_SIZE_MM,
      CORE_GRIPPER_PAD_HEIGHT_MM,
      CORE_GRIPPER_PAD_SIZE_MM
    );
    this.padMesh = new THREE.Mesh(padGeom, new THREE.MeshLambertMaterial({ color: CORE_GRIPPER_PAD_COLOR }));
    this.padMesh.position.y = -CORE_GRIPPER_PAD_HEIGHT_MM / 2;
    this.padMesh.visible = false;
    this.group.add(this.padMesh);

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

  // Toggles this channel's gripper-pad glyph -- see the constructor's own
  // comment on padMesh. No length/color parameters the way setTip() has:
  // every pad looks the same regardless of which resource it's about to
  // grip, unlike a tip's own per-model length/capacity.
  setPad(visible) {
    this.padMesh.visible = visible;
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

// Same idea as nudgeChannel() -- dragged along in X only, own Y/Z
// untouched -- for the CO-RE 96 head instead of one channel, since it
// rides the same shared X rail (see CORE96_X_OFFSET_MM's own comment).
// Same leg-duration shape as nudgeChannel()/animateCore96Op() so every
// mechanism's passes stay lockstep regardless of which one is "active"
// this particular op.
function nudgeCore96Head(x) {
  core96Head.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  core96Head.enqueue({ x, y: null, z: restZ }, scaled(X_MOVE_MS));
  core96Head.enqueue({ x, y: null, z: restZ }, scaled(Y_MOVE_MS));
  core96Head.enqueue({ x, y: null, z: restZ }, scaled(DESCEND_MS + HOLD_MS + RETRACT_MS));
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
    // The 96-head rides the same shared X rail as the 8 channels (see
    // CORE96_X_OFFSET_MM's own comment) -- every channel pass drags it
    // along too, converting this pass's channel-frame x into the head's
    // own frame the same way animateCore96Op()'s own passes convert back
    // (user-reported: "the eight channels seem to be stationary during
    // the core96 well operations" -- true in both directions before this,
    // just reported from the channels' side).
    nudgeCore96Head(pass.x - CORE96_X_OFFSET_MM);
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
// Parked position when nothing's queued -- directly above the head's own
// trash (`STARDeck().get_trash_area96()`, confirmed live:
// `Coordinate(-58.200, 106.000, 216.400)`) per user direction, rather
// than an arbitrary out-of-the-way spot -- not a real Hamilton
// home-position value (this project doesn't model the 96-head's own
// parking mechanism), but at least a real, meaningful deck landmark
// instead of a made-up one. `restZ` (the shared gantry rise/retract
// height, already comfortably above everything on deck -- see
// setRestZ()) covers "above," so only x/y need to match the trash here.
const CORE96_REST_X_MM = -58.2;
const CORE96_REST_Y_MM = 106.0;
// The 96-head and the 8 channels are two separate arm assemblies riding
// the *same* physical X rail on a real Hamilton STAR -- sharing one X
// drive, but not sitting at the same absolute X (mechanically offset
// along the rail -- user-flagged, see docs/PLAN.md's "Review round 37"
// design discussion). Real value: PyLabRobot's own STAR_backend.py
// documents this exact quantity -- `_head96_request_x_offset()` reads it
// live from the instrument's own EEPROM ("X-arm carriage center <-> CoRe
// 96 head channel A1") and its own comment gives a representative
// magnitude: "the head96 offset is ~10x the iSWAP's (~368 mm vs ~34
// mm)". It varies slightly per physical unit (that's the whole reason
// it's a live-read EEPROM value, not a constant, on real hardware) --
// 368mm here is representative, not universal. Direction (per user
// direction: the 8 channels sit at *higher* X than the head, i.e.
// `channelX = headX + CORE96_X_OFFSET_MM`) isn't stated in that source;
// taken from user direction, not derived from it.
const CORE96_X_OFFSET_MM = 368;

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

    // Own clones (like a single Channel's own aspirateFlowTexture/
    // dispenseFlowTexture -- see that class's own comment), not the
    // shared module-level FLOW_TEXTURE_ASPIRATE/DISPENSE directly: a
    // texture object's `.offset` is mutated in place while animating, and
    // this head's own flowPulse() would otherwise fight over that same
    // offset with whichever Channel happens to be flow-pulsing at the
    // same moment.
    this.aspirateFlowTexture = FLOW_TEXTURE_ASPIRATE.clone();
    this.dispenseFlowTexture = FLOW_TEXTURE_DISPENSE.clone();

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

  // A brief white flash on the block itself, exactly matching Channel.
  // pulse() -- the same "something is actively happening here" cue for an
  // aspirate96/dispense96 arriving.
  pulse() {
    this.body.material.color.copy(PULSE_COLOR);
    setTimeout(() => this.body.material.color.setHex(CORE96_EMPTY_COLOR), 250 * getDurationScale());
  }

  // direction: +1 to scroll "up" (aspirate), -1 to scroll "down"
  // (dispense) -- exactly Channel.flowPulse()'s own scheme, just applied
  // to the one shared `tipMaterial` all 96 tip cones already use (see the
  // constructor's own comment on why they share it), so animating it once
  // here visibly flows through all 96 at once instead of needing 96
  // independent flow animations. Not routed through the leg-motion
  // AnimationQueue -- like Channel's own version, this is a fire-and-
  // forget decorative overlay timed to *when this op visually arrives*,
  // not another leg to sequence.
  flowPulse(direction) {
    const material = this.tipMaterial;
    const restoreColor = material.color.clone();
    const texture = direction > 0 ? this.aspirateFlowTexture : this.dispenseFlowTexture;
    material.map = texture;
    material.color.setHex(0xffffff);
    material.needsUpdate = true;

    const start = performance.now();
    const duration = FLOW_PULSE_MS * getDurationScale();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      texture.offset.y = direction * t * 2;
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

  enqueue(target, duration, onComplete) {
    this.motion.enqueue(target, duration, onComplete);
  }

  update(dtMs) {
    this.motion.update(dtMs);
  }
}

export const core96Head = new Core96Head();

// Same six-leg rise/x/y/descend/hold/retract shape as animateChannelOp(),
// just for one rigid body instead of one channel among eight. No
// planGantryPasses()-style row-conflict resolution needed for the head
// itself (it's one rigid body engaging one x/y target, not 8 independent
// channels that might each want a different y) -- but it drags the 8
// channels along in X too, converting its own target into their shared-
// rail frame via CORE96_X_OFFSET_MM, the same physical constraint
// animateChannelGroupOp() drags the head along for in the other
// direction (user-reported: "the eight channels seem to be stationary
// during the core96 well operations").
//
// `msg.z` is the touched resource's own reported *top* (resource_point()'s
// top-center anchor -- see events.py), i.e. where the *tips' own points*
// should end up, not where the group origin (the block's bottom/the tips'
// own wide base -- see the constructor's own comment) should be -- those
// differ by the tips' full length, the exact same body-vs-tip-point
// distinction animateChannelOp()'s own targetZ comment explains for a
// single Channel. Omitting `+ tipLength` here previously put the group
// origin (not the tips' points) at the resource's own top, so the tips'
// points -- a real tip's ~60mm below that -- ended up buried tens of mm
// *through* the plate/rack instead of just reaching its surface
// (user-reported: "the tips seems to go through the well plates").
//
// `tipLength`: override for the pick_up_tips96 case, same reasoning as
// animateChannelOp()'s own `tipLength` param -- the tip that matters for
// *this* op's clearance is the one about to be grabbed
// (`msg.tip_length_mm`), not whatever core96Head was last carrying
// (`core96Head.tipLength`, still the *previous* pickup's value until
// `setTips()` runs in this op's own `onArrive`). Every other op omits it
// and falls back to `core96Head.tipLength`, since the head is still
// carrying that same tip throughout.
function animateCore96Op(msg, onArrive, tipLength) {
  const targetZ = () => msg.z + CORE96_ENGAGE_CLEARANCE_MM + (tipLength ?? core96Head.tipLength);
  const channelX = msg.x + CORE96_X_OFFSET_MM;
  for (let i = 0; i < channels.length; i++) {
    nudgeChannel(i, channelX, channels[i].pos.y);
  }
  core96Head.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  core96Head.enqueue({ x: msg.x, y: null, z: restZ }, scaled(X_MOVE_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: restZ }, scaled(Y_MOVE_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: targetZ }, scaled(DESCEND_MS), onArrive);
  core96Head.enqueue({ x: msg.x, y: msg.y, z: targetZ }, scaled(HOLD_MS));
  core96Head.enqueue({ x: msg.x, y: msg.y, z: restZ }, scaled(RETRACT_MS));
}

// ---------------------------------------------------------------------------
// CO-RE gripper (plate pick-up/move/drop via two of the 8 channels)
// ---------------------------------------------------------------------------
// Real CoRe-gripper mechanics (see STAR_backend.py's core_pick_up_resource/
// core_release_picked_up_resource): two of the 8 pipetting channels --
// `front_channel` and `back_channel = front_channel - 1` -- grab a pair of
// gripper pads normally parked at the deck's own `core_grippers` fixture,
// then straddle the target resource's front/back edges to clamp and carry
// it. `use_arm="core"` opt-in only (see visualizer_backend.py's own
// pick_up_resource/move_picked_up_resource/drop_resource) -- everything
// else keeps the old log-only resource-move behavior below.

// Half the distance apart the two gripper channels sit while straddling a
// resource's own center y -- an approximation (not sourced from any real
// per-resource grip-width calculation, which STARBackend derives from the
// resource's actual size_y -- see core_pick_up_resource's own
// `grip_width = resource.get_absolute_size_y()`), same "good enough for
// simple bounding-box animation, not a substitute for real motion
// planning" bar events.py's resource_point() already operates at.
const CORE_GRIP_HALF_SPAN_MM = 40;
// How far above a resource's own reported top-center (see events.py's
// resource_point()/resource_drop_point()/resource_move_point()) the two
// gripping channels' own origin (where body meets pad -- see Channel's
// padMesh) targets, so the pad glyph -- which hangs CORE_GRIPPER_PAD_
// HEIGHT_MM *below* that origin, same as a carried tip -- ends up
// straddling the resource's top edge instead of buried inside it (user-
// reported: "gripper pads are not visible" -- confirmed live: with no
// offset, the channel's own origin (and so the pad hanging below it)
// landed *at* the resource's top surface, putting the whole pad inside
// the resource's own mesh). Half the pad's height (so the pad visually
// straddles the edge, not floats entirely above it) plus a couple more mm
// of clearance so it doesn't z-fight with the resource's own top face --
// the same small-fixed-margin idea CORE96_ENGAGE_CLEARANCE_MM/
// scene-builder.js's thermocycler lid clearance already use.
const CORE_GRIP_CHANNEL_Z_OFFSET_MM = CORE_GRIPPER_PAD_HEIGHT_MM / 2 + 2;

// The resource currently gripped and being carried, or null -- at most one
// at a time (a real CoRe gripper only ever holds one resource). Its own
// THREE group has been reparented into `gantryGroup` (see
// "core_pick_up_resource" below) and is driven by this MotionUnit-backed
// wrapper the same rise/x/y/descend leg shape Channel/Core96Head use for
// their own motion, just converting each leg's target (a resource's
// top-center point, matching every other op's msg.x/y/z -- see events.py's
// resource_point()/resource_drop_point()/resource_move_point()) into the
// group's own left-front-bottom-anchored local frame on every tick (see
// applyPosition() below) rather than needing every call site here to do
// that conversion itself.
class CarriedPlate {
  constructor(resourceName, initialTopCenter) {
    this.resourceName = resourceName;
    this.motion = new MotionUnit({ ...initialTopCenter }, () => this.applyPosition());
  }

  applyPosition() {
    const entry = resourceIndex.get(this.resourceName);
    if (!entry) return;
    const node = entry.node;
    // Undo resource_point()'s own "top-center" anchor -- the group's own
    // local frame origin is the resource's left-front-bottom corner (same
    // convention scene-builder.js's buildResourceObject() positions every
    // group by by), not its top-center, so this has to subtract back out
    // exactly the half-extents/full-height resource_point() added -- the
    // mirror image of events.py's own _relocated_point() helper.
    const lfb = {
      x: this.motion.pos.x - (node.size_x ?? 0) / 2,
      y: this.motion.pos.y - (node.size_y ?? 0) / 2,
      z: this.motion.pos.z - (node.size_z ?? 0),
    };
    entry.group.position.copy(mapPoint(lfb.x, lfb.y, lfb.z));
  }

  enqueue(target, duration, onComplete) {
    this.motion.enqueue(target, duration, onComplete);
  }

  update(dtMs) {
    this.motion.update(dtMs);
  }
}

let carriedPlate = null;
// Ticked from main.js's render loop alongside every channel/core96Head --
// see that file's own animate() loop. A plain exported function (not a
// class main.js has to know about) since there's at most one at a time and
// main.js otherwise has no reason to reach into this module's gripper
// state.
export function updateCarriedPlate(dtMs) {
  carriedPlate?.update(dtMs);
}

// [backChannelIndex, frontChannelIndex] currently showing a pad glyph, or
// null -- mirrors visualizer_backend.py's own `_core_gripper_channels`
// persistent-attachment tracking (see that field's own comment), kept as
// separate frontend-side state rather than trusting a stale closure
// because a page reload / fresh "scene" message should visibly reset this
// too (ensureChannels() rebuilds every Channel from scratch, which starts
// every padMesh hidden again).
let gripperPadChannels = null;
function setGripperPadChannels(back, front) {
  if (gripperPadChannels) {
    const [prevBack, prevFront] = gripperPadChannels;
    channels[prevBack]?.setPad(false);
    channels[prevFront]?.setPad(false);
  }
  gripperPadChannels = back != null && front != null ? [back, front] : null;
  if (gripperPadChannels) {
    channels[back]?.setPad(true);
    channels[front]?.setPad(true);
  }
}

// One "stop" for the whole shared-X-rail gantry -- every one of the 8
// channels *and* the 96-head (see CORE96_X_OFFSET_MM's own comment: same
// physical X drive) -- used identically for every kind of stop a CoRe-
// gripper move makes: traveling to core_grippers to attach/return the
// pads, and traveling to grip/drop the actual resource. Rise/x/y/descend,
// the same leg shape animateChannelOp() uses for a single channel's
// approach; unlike that function there's no final retract leg -- whatever
// this stop leaves descended (the two gripping channels, holding onto
// whatever they're gripping) stays there until the *next* stop's own rise
// leg picks it back up, exactly like animateGripperStop()'s own callers
// chain multiple stops back to back (pad-attach -> resource-grip,
// resource-drop -> pad-return).
//
// `targetYFor`/`targetZFor` are `(channelIndex) => number`, letting each
// caller customize only the two participating channels' own Y/Z (every
// other channel keeps its own current Y and stays at restZ, exactly
// animateChannelGroupOp()'s own "idle channels get dragged along the
// shared rail, not left behind" reasoning -- user-reported: gripper
// channels "appear desync from the other pipettes... they don't move
// together in x-axis," true before this since the other 6 channels (and
// the 96-head) simply never got enqueued anything during a gripper move)
// without duplicating the leg-enqueueing/cross-mechanism-dragging plumbing
// once per kind of stop. `onArriveChannel`/`onArrive`: fired once, off
// that one channel's own descend completion (every channel's legs use the
// same fixed nominal durations -- see animateChannelOp()'s own "every leg
// always takes its fixed nominal duration" reasoning -- so they land
// within a frame of each other regardless of which channel's callback
// actually fires).
function animateGripperStop(x, targetYFor, targetZFor, onArriveChannel, onArrive) {
  for (let i = 0; i < channels.length; i++) {
    const ch = channels[i];
    const y = targetYFor(i);
    const z = targetZFor(i);
    ch.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
    ch.enqueue({ x, y: null, z: restZ }, scaled(X_MOVE_MS));
    ch.enqueue({ x, y, z: restZ }, scaled(Y_MOVE_MS));
    ch.enqueue({ x, y, z }, scaled(DESCEND_MS), i === onArriveChannel ? onArrive : undefined);
  }
  // The 96-head rides the same shared X rail -- converted into its own
  // frame exactly the way nudgeCore96Head()/animateCore96Op() already do
  // for ordinary channel ops (see CORE96_X_OFFSET_MM's own comment); no
  // separate onArrive hook needed here, it's a pure cosmetic drag-along
  // like every other idle passenger in this function.
  const headX = x - CORE96_X_OFFSET_MM;
  core96Head.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  core96Head.enqueue({ x: headX, y: null, z: restZ }, scaled(X_MOVE_MS));
  core96Head.enqueue({ x: headX, y: null, z: restZ }, scaled(Y_MOVE_MS));
  core96Head.enqueue({ x: headX, y: null, z: restZ }, scaled(DESCEND_MS));
}

// targetYFor/targetZFor for a stop where the two gripper channels
// straddle a *resource* (the plate/rack being picked up, moved, or
// dropped) -- back at +CORE_GRIP_HALF_SPAN_MM, front at
// -CORE_GRIP_HALF_SPAN_MM (mirrors Channel's own back/front convention --
// see that class's constructor comment: channel 0 is back-most, increasing
// index moves toward front/-y), descending to the resource's own z plus
// CORE_GRIP_CHANNEL_Z_OFFSET_MM. Every other channel keeps its own current
// y and stays at restZ (see animateGripperStop()'s own docstring).
function gripResourceTargets(backChannel, frontChannel, y, z) {
  return {
    targetYFor: (i) =>
      i === backChannel ? y + CORE_GRIP_HALF_SPAN_MM : i === frontChannel ? y - CORE_GRIP_HALF_SPAN_MM : channels[i].pos.y,
    targetZFor: (i) => (i === backChannel || i === frontChannel ? z + CORE_GRIP_CHANNEL_Z_OFFSET_MM : restZ),
  };
}

// targetYFor/targetZFor for a stop at core_grippers itself (attaching or
// returning the pads) -- both channels target the same (padY, padZ) point
// (no straddle span the way gripResourceTargets() has: `core_grippers` is
// a small compact fixture, not a full plate footprint to straddle across
// -- see CORE_GRIP_HALF_SPAN_MM's own "not sourced from any real per-
// resource grip-width calculation" comment for the same approximation
// bar). `padZ` may be omitted (a deck without a `core_grippers` resource
// -- see visualizer_backend.py's own `_core_grippers_point()`), in which
// case this stop just travels in x/y at restZ rather than descending.
function padTargets(backChannel, frontChannel, padY, padZ) {
  return {
    targetYFor: (i) => (i === backChannel || i === frontChannel ? padY : channels[i].pos.y),
    targetZFor: (i) =>
      i === backChannel || i === frontChannel
        ? (padZ != null ? padZ + CORE_GRIP_CHANNEL_Z_OFFSET_MM : restZ)
        : restZ,
  };
}

// Same rise/x/y/descend shape as animateGripperChannels(), for the
// currently-carried plate itself -- called alongside it (never alone) so
// the plate visibly travels with the two channels gripping it, not just
// teleporting to each new stop.
function animateCarriedPlateTo(x, y, z, onArrive) {
  if (!carriedPlate) return;
  carriedPlate.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  carriedPlate.enqueue({ x, y: null, z: restZ }, scaled(X_MOVE_MS));
  carriedPlate.enqueue({ x, y, z: restZ }, scaled(Y_MOVE_MS));
  carriedPlate.enqueue({ x, y, z }, scaled(DESCEND_MS), onArrive);
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
      }, msg.tip_length_mm);
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
      // Liquid flows "up" into the tips on aspirate, "down" out of them
      // on dispense -- see Core96Head.flowPulse(), exactly Channel's own
      // scheme.
      const flowDirection = msg.op === "aspirate96" ? 1 : -1;
      animateCore96Op(msg, () => {
        core96Head.pulse();
        core96Head.flowPulse(flowDirection);
        // Same reuse as the tip-spot case above, one call per well --
        // visualizer_backend.py's _well_volume_entries() builds these with
        // field names matching a single-channel aspirate/dispense's own
        // embedded resource_volume/resource_max_volume specifically so
        // this needs no separate per-well handling here. Flashing each
        // *well* individually (not `flashResource(msg.resource)`, the
        // whole plate at once) -- user-reported: "the plate lights up
        // instead of the wells" -- matches a single channel's own
        // per-well flash, just for all 96 at once instead of one.
        for (const well of msg.wells ?? []) {
          applyEmbeddedResourceState(well);
          flashResource(well.resource);
        }
      });
      logEvent(msg.op, `${msg.resource} (${msg.volume}µL)`);
      break;
    }
    case "core_pick_up_resource": {
      const { back_channel: back, front_channel: front, needs_attach, pad_x, pad_y, pad_z } = msg;
      // Reparented and wrapped in a CarriedPlate *synchronously* here, not
      // deferred to any channel's own onArrive -- a real websocket "op"
      // message for the very next leg of this same move (a
      // core_move_picked_up_resource, or -- the common case, since
      // move_resource() only calls move_picked_up_resource for explicit
      // intermediate_locations -- straight to core_drop_resource) routinely
      // arrives and gets handled well before this pickup's own approach
      // animation actually finishes (the backend has no reason to wait
      // between them -- see e.g. core_gripper_demo.py's own back-to-back
      // move_plate() calls), and that next event's own
      // animateCarriedPlateTo() call needs `carriedPlate` to already exist
      // to enqueue onto (confirmed live: deferring this to onArrive left
      // `carriedPlate` still null when the very next op's handler ran,
      // silently dropping its motion legs -- the resource visibly never
      // moved). Reparenting this early causes no visible jump either way:
      // `.attach()` preserves world position exactly, and nothing enqueues
      // any motion onto the new CarriedPlate until a *later* op actually
      // calls animateCarriedPlateTo(), so it just keeps rendering at this
      // same point throughout the channels' own approach, identical to how
      // it looked before being reparented.
      const entry = resourceIndex.get(msg.resource);
      if (entry) {
        gantryGroup.attach(entry.group);
        carriedPlate = new CarriedPlate(msg.resource, { x: msg.x, y: msg.y, z: msg.z });
      }
      // Pads aren't already on these channels -- a real prior leg (see
      // STAR_backend.py's own `if self.core_parked: await self.
      // pick_up_core_gripper_tools(...)`): travel to core_grippers first,
      // "grab" the pads once actually there (not instantly at event
      // receipt -- see setGripperPadChannels()'s own onArrive callback
      // below), *then* continue to the resource. `needs_attach` without
      // `pad_x` (a deck with no `core_grippers` resource -- see
      // visualizer_backend.py's own `_core_grippers_point()`) falls back
      // to the old instant toggle instead of skipping the pad glyph
      // entirely.
      if (needs_attach) {
        if (pad_x != null) {
          const pad = padTargets(back, front, pad_y, pad_z);
          animateGripperStop(pad_x, pad.targetYFor, pad.targetZFor, front, () => setGripperPadChannels(back, front));
        } else {
          setGripperPadChannels(back, front);
        }
      }
      const grip = gripResourceTargets(back, front, msg.y, msg.z);
      animateGripperStop(msg.x, grip.targetYFor, grip.targetZFor, front);
      logEvent("core_pick_up_resource", msg.resource ?? "");
      break;
    }
    case "core_move_picked_up_resource": {
      const { back_channel: back, front_channel: front } = msg;
      const grip = gripResourceTargets(back, front, msg.y, msg.z);
      animateGripperStop(msg.x, grip.targetYFor, grip.targetZFor, front);
      animateCarriedPlateTo(msg.x, msg.y, msg.z);
      logEvent("core_move_picked_up_resource", msg.resource ?? "");
      break;
    }
    case "core_drop_resource": {
      const { back_channel: back, front_channel: front, return_core_gripper, pad_x, pad_y, pad_z } = msg;
      const grip = gripResourceTargets(back, front, msg.y, msg.z);
      animateGripperStop(msg.x, grip.targetYFor, grip.targetZFor, front);
      // Enqueued while `carriedPlate` still refers to *this* resource --
      // must run before the reparent/null-out below.
      animateCarriedPlateTo(msg.x, msg.y, msg.z);
      // Reparented back under the plain scene root synchronously here, not
      // deferred to an onArrive -- same "the very next op can arrive and
      // run its own handler well before this one's ~1.1s descend animation
      // actually finishes" race core_pick_up_resource's own comment
      // describes (confirmed live: a deferred version here stomped on a
      // *second* pickup that had already started by the time this drop's
      // onArrive eventually fired, wiping out its carriedPlate mid-flight).
      // Reparenting early causes no visual jump: CarriedPlate.
      // applyPosition() always sets an absolute deck position regardless
      // of which (transform-less) parent the group currently sits under,
      // and the queued motion legs enqueued just above still play out
      // over their own real duration either way. Not into whatever THREE
      // group actually corresponds to the resource's new real PyLabRobot
      // parent (a carrier site's holder, a thermocycler's payload group,
      // etc.) -- this project's scene tree only ever gets rebuilt
      // wholesale from a fresh "scene" message (see scene-builder.js's
      // loadScene()), so there's no lighter-weight way to re-nest it
      // correctly short of that, and a flat sceneRoot child renders
      // identically either way (position is already absolute deck mm via
      // mapPoint()). Per user direction ("reparent the real plate mesh").
      const entry = resourceIndex.get(msg.resource);
      if (entry && sceneRoot) sceneRoot.attach(entry.group);
      // Deliberately *not* `carriedPlate = null` here: the legs just
      // enqueued above haven't played out yet (they take their own ~1.1s
      // of real ticking, via updateCarriedPlate() -- see that function's
      // own comment), and nulling the module-level reference synchronously
      // would orphan them, mid-queue, from the only thing that ever calls
      // `.update()` on them -- confirmed live: the resource visibly never
      // reached its drop destination, frozen at wherever it was when this
      // handler ran, exactly the "silently dropped legs" bug the pickup
      // side's own comment above describes, just for the opposite reason
      // (too eager to clear the reference, instead of too slow to create
      // it). Safe to just leave it referenced: once its queue drains, an
      // idle AnimationQueue.update() is a no-op (see that class's own
      // early-return), and the next core_pick_up_resource for this or any
      // other resource unconditionally overwrites `carriedPlate` with a
      // fresh instance anyway -- nothing ever reads a stale one as if it
      // were still actively gripped.
      if (return_core_gripper) {
        // Trailing, channels-only stop (the plate has already been
        // released above -- animateCarriedPlateTo() isn't called again):
        // travel back to core_grippers and "return" the pads once actually
        // there, mirroring the pickup side's own pad-attach travel. Same
        // "no pad_x, no coordinates to travel to" fallback as the pickup
        // side.
        if (pad_x != null) {
          const pad = padTargets(back, front, pad_y, pad_z);
          animateGripperStop(pad_x, pad.targetYFor, pad.targetZFor, front, () => setGripperPadChannels(null, null));
        } else {
          setGripperPadChannels(null, null);
        }
      }
      logEvent("core_drop_resource", msg.resource ?? "");
      break;
    }
    default:
      // resource-move / manual-jog events: not animated in v1, but still
      // worth surfacing in the log so the panel reflects everything the
      // backend did.
      logEvent(msg.op, msg.resource ?? "");
  }
}
