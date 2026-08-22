// Scene-graph -> Three.js object construction: turns the deck scene graph
// streamed from VisualizerServer (see scene.py) into an isometric Three.js
// tree of boxes/cones, one call per "scene" websocket message (see
// websocket.js).

import * as THREE from "three";
import { mapPoint } from "./coordinates.js";
import {
  CATEGORY_COLORS,
  DEFAULT_COLOR,
  CARRIER_CATEGORIES,
  THIN_CATEGORIES,
  EMPTY_COLOR,
  EMPTY_OPACITY,
} from "./categories.js";
import { AnimationQueue } from "./animation-queue.js";

const ENVELOPE_PLATFORM_THICKNESS = 10;
const THIN_CATEGORY_THICKNESS = 3;
// A tip's real length (~95mm for a 1000uL Hamilton tip) is much larger than
// the ~9mm spacing between rack positions -- drawn to true scale, adjacent
// tips would overlap. These are a visually-legible compromise, not to
// scale, same tradeoff as the gantry channel glyph size in gantry.js.
export const TIP_PYRAMID_RADIUS = 3.2;
export const TIP_PYRAMID_HEIGHT = 16;

// Hamilton deck rail geometry, from pylabrobot.resources.hamilton.
// hamilton_decks: rails_to_location(rail) = Coordinate(x=100.0 + (rail-1)
// * 22.5, ...). `num_rails` itself *is* already part of a deck node's own
// serialize() output (it's a real dataclass field, not scene.py-injected),
// but the 100.0/22.5 constants aren't resource attributes anywhere -- they
// only exist as that method's arithmetic -- so they're hardcoded here the
// same way CHANNEL_PITCH_MM is in gantry.js, rather than threading two
// numbers that never change per PyLabRobot's own source through scene.py
// for this.
const RAIL_X_OFFSET_MM = 100.0;
const RAIL_WIDTH_MM = 22.5;
const RAIL_LABEL_INTERVAL = 5;

// resourceName -> { group, mesh, node, baseColor, ... } -- see the object
// built at the bottom of buildResourceObject() for the full shape. Read by
// resource-state.js (live tip/volume updates), gantry.js (flashResource(),
// thermocycler op handling), and tooltip.js (hover info).
export const resourceIndex = new Map();
// Every mesh a pointer can hover over -- fed to tooltip.js's raycaster.
export const hoverables = [];

function colorForNode(node) {
  return CATEGORY_COLORS[node.category] ?? DEFAULT_COLOR;
}

// A Well's real shape -- PyLabRobot already reports it (`bottom_type`:
// "flat"/"U"/"V"/"unknown", `cross_section_type`: "circle"/"rectangle",
// both present straight from Resource.serialize(), no scene.py changes
// needed) -- so its footprint shouldn't always render as the flat-topped
// box every other category uses. Built as a *unit* shape (radius/size 0.5,
// height 1) and non-uniformly scaled to the well's real size_x/size_z/
// size_y by the caller, so one geometry works for both circular and
// rectangular footprints without special-casing which.
//
//  - V-bottom (e.g. a PCR plate): an inverted cone -- liquid actually
//    collects at a point, and that's the plate's whole visual identity.
//  - Round (circular cross-section, any other bottom): a cylinder --
//    still reads as "round" even though a real U-bottom well's floor
//    curves rather than staying flat; approximating that curve isn't
//    worth a fourth geometry type for a shape difference this subtle at
//    well scale.
//  - Rectangular cross-section, non-V bottom: unchanged -- the existing
//    box (returns null; caller falls back to it).
function wellShapeFor(node) {
  if (node.category !== "well") return null;
  if (node.bottom_type === "V") {
    // Apex-down like the tip pyramid's cone -- THREE.ConeGeometry's apex
    // points +Y by default, so flip it in buildResourceObject the same
    // way (rotation.x = Math.PI).
    return { geometry: new THREE.ConeGeometry(0.5, 1, 24), invert: true };
  }
  if (node.cross_section_type === "circle") {
    return { geometry: new THREE.CylinderGeometry(0.5, 0.5, 1, 24), invert: false };
  }
  return null;
}

// Small text-on-a-canvas billboard, same "draw once on a 2D canvas, use as
// a texture" approach as gantry.js's createFlowTexture() -- no font-loading
// or text-geometry library needed for a handful of short numeric labels.
// Always faces the camera (THREE.Sprite), which is exactly what a ruler
// tick label wants regardless of orbit angle.
function createTextSprite(text, { fontSize = 64, color = "#c7ccd4" } = {}) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.font = `bold ${fontSize}px sans-serif`;
  const width = Math.ceil(ctx.measureText(text).width) + 16;
  const height = fontSize + 16;
  canvas.width = width;
  canvas.height = height;
  // Resizing the canvas resets its 2D context state, so the font has to be
  // set again before the actual fillText below.
  ctx.font = `bold ${fontSize}px sans-serif`;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, width / 2, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true })
  );
  // Fixed real-world height regardless of text length; width follows the
  // canvas's own aspect ratio so digits don't stretch.
  const worldHeight = 14;
  sprite.scale.set((width / height) * worldHeight, worldHeight, 1);
  return sprite;
}

// Every RAIL_LABEL_INTERVAL-th rail number along the deck's front edge --
// see the RAIL_X_OFFSET_MM/RAIL_WIDTH_MM comment above for where the
// coordinate formula comes from. Placed just in front of (smaller real-world
// y than) where carriers actually attach and at deck-surface height, so
// labels read like ruler markings instead of overlapping any carrier sitting
// on the rail.
function addRailLabels(parentGroup, node, deckSurfaceZ) {
  const numRails = node.num_rails;
  if (!numRails) return; // non-Hamilton or otherwise rail-less deck
  for (let rail = RAIL_LABEL_INTERVAL; rail <= numRails; rail += RAIL_LABEL_INTERVAL) {
    // RAIL_X_OFFSET_MM + (rail-1)*RAIL_WIDTH_MM is rail N's *left* border
    // (the same x addRailLines() draws that border at, and where a
    // resource assigned via rails=N actually attaches) -- labeling a rail
    // there reads as sitting on the boundary with the rail *before* it.
    // +RAIL_WIDTH_MM/2 centers the label within rail N's own slot instead.
    const x = RAIL_X_OFFSET_MM + (rail - 1) * RAIL_WIDTH_MM + RAIL_WIDTH_MM / 2;
    const sprite = createTextSprite(String(rail));
    sprite.position.copy(mapPoint(x, -15, deckSurfaceZ + 2));
    parentGroup.add(sprite);
  }
}

// A thin line at every rail boundary (not just every RAIL_LABEL_INTERVAL-th
// one, unlike the labels above) -- numRails+1 of them, bracketing each
// 22.5mm-wide rail slot from the leftmost rail's left edge through the
// rightmost rail's right edge, spanning the deck's full y depth. Sits
// right on the platform's own top surface (normal depth-testing, unlike
// the always-on-top label sprites) so a carrier sitting on top of a line
// correctly occludes the part underneath it.
function addRailLines(parentGroup, node, deckSurfaceZ) {
  const numRails = node.num_rails;
  if (!numRails) return;
  const sizeY = node.size_y ?? 0;
  const points = [];
  for (let rail = 1; rail <= numRails + 1; rail++) {
    const x = RAIL_X_OFFSET_MM + (rail - 1) * RAIL_WIDTH_MM;
    points.push(mapPoint(x, 0, deckSurfaceZ + 0.3), mapPoint(x, sizeY, deckSurfaceZ + 0.3));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({ color: 0x50565f, transparent: true, opacity: 0.6 });
  parentGroup.add(new THREE.LineSegments(geometry, material));
}

export function buildResourceObject(node, isRoot, parentSizeZ, parentTipLengthMm, parentTipMaxVolumeUl) {
  const group = new THREE.Group();
  group.name = node.name;

  if (!isRoot) {
    const loc = node.location ?? { x: 0, y: 0, z: 0 };
    const p = mapPoint(loc.x, loc.y, loc.z);
    group.position.copy(p);
    const rotZ = node.rotation?.z ?? 0;
    // Only z-axis (yaw) rotation is applied -- see docs/DESIGN.md section 3
    // ("Gantry model") for why: PLR resources on a deck are almost always
    // rotated purely around z, and this keeps the transform simple.
    group.rotation.y = -THREE.MathUtils.degToRad(rotZ);
  }

  const isDeck = node.category === "deck";
  const isCarrier = CARRIER_CATEGORIES.has(node.category);
  const isThin = THIN_CATEGORIES.has(node.category);
  const isEnvelope = isDeck || isCarrier || isThin;
  // Shared by the platform's own zOffset below and by the rail labels --
  // both need "where do carriers actually attach," not the deck's own z=0
  // (see the zOffset comment further down for why those differ).
  const deckSurfaceZ = isDeck
    ? (() => {
        const childZs = (node.children ?? []).map((c) => c.location?.z ?? 0).filter((z) => z > 0);
        return childZs.length > 0 ? Math.min(...childZs) : 0;
      })()
    : null;
  const sizeX = Math.max(node.size_x ?? 0, 0.1);
  const sizeY = Math.max(node.size_y ?? 0, 0.1);
  let sizeZ;
  if (isDeck) {
    sizeZ = ENVELOPE_PLATFORM_THICKNESS;
  } else if (isCarrier) {
    // A carrier's own size_z is its whole rail envelope, not a thickness --
    // draw it as a solid shaft from its base up to where its payload
    // (plate/tip-rack, via a PlateHolder/ResourceHolder child) actually
    // sits, so the payload rests visibly on top instead of being buried
    // inside (or floating disconnected above) the carrier's box.
    const holderZs = (node.children ?? [])
      .map((c) => c.location?.z ?? 0)
      .filter((z) => z > 0);
    sizeZ = holderZs.length > 0 ? Math.min(...holderZs) : ENVELOPE_PLATFORM_THICKNESS;
  } else if (isThin) {
    // tip_rack/plate have the same problem as carriers: a TipSpot's tip and
    // a Well's liquid sit recessed *inside* the parent's declared size_z
    // (e.g. a well is 3-14mm up from a 14mm-tall plate's own base) -- a
    // solid box the full declared height buries them entirely. Render just
    // a thin base instead; the payload (rendered using the *declared*
    // height via parentSizeZ passed to children below, not this thinned
    // value) then sits visibly clear of it.
    sizeZ = THIN_CATEGORY_THICKNESS;
  } else {
    sizeZ = Math.max(node.size_z ?? 0.5, 0.1);
  }

  let mesh = null;
  if ((node.size_x ?? 0) > 0 && (node.size_y ?? 0) > 0) {
    const wellShape = wellShapeFor(node);
    const geometry = wellShape ? wellShape.geometry : new THREE.BoxGeometry(sizeX, sizeZ, sizeY);
    const color = colorForNode(node);
    const material = new THREE.MeshLambertMaterial({
      color,
      transparent: true,
      opacity: isEnvelope ? 0.85 : 1.0,
    });
    mesh = new THREE.Mesh(geometry, material);
    if (wellShape) {
      // Unit geometry -- see wellShapeFor()'s docstring -- scaled to this
      // well's real footprint/height. Scale (not baked-in geometry size)
      // so the same two geometries are reused across every well instead
      // of allocating one per well.
      mesh.scale.set(sizeX, sizeZ, sizeY);
      if (wellShape.invert) mesh.rotation.x = Math.PI;
    }
    // The deck platform sits *below* its own origin (z=0) rather than above
    // it -- but its own z=0 is *not* the carrier rail surface (on a real
    // STARLetDeck, carriers actually attach ~100mm up from there), so
    // anchoring the platform's top at z=0 left it floating in open space
    // ~100mm below every carrier instead of visibly supporting them.
    // Anchor its top at the lowest point any child actually attaches
    // instead -- same idea as the carrier shaft fix above, one level up.
    let zOffset;
    if (isDeck) {
      zOffset = deckSurfaceZ - sizeZ / 2;
    } else if (isThin) {
      // A thin category's own *placement* on its parent can itself be
      // recessed below the surface it visually sits on -- e.g. a Plate's
      // location.z on its carrier site is -3.03mm, a baked-in PLR datum
      // offset (the plate's local z=0 reference point, chosen so its own
      // wells -- at +3.03 -- land exactly flush with the rail), not "how
      // far above the rail its visible base sticks up." Naively drawing
      // the thin slab from local 0 upward buried the entire thing below
      // the rail (inside the carrier's own box, whose sizeZ reaches
      // exactly up to that same rail): a Plate's base was rendered but
      // never visible. Cancel a negative placement the same way round 7
      // canceled TipSpot's baked -83.5mm dz for its pyramid -- lift the
      // slab by however far its own origin sits below the surface, so its
      // *bottom* face is flush with the surface instead of buried under
      // it. A resource placed with location.z >= 0 (e.g. a TipRack, whose
      // site offset is exactly 0) is unaffected.
      const ownRecess = Math.max(0, -(node.location?.z ?? 0));
      zOffset = sizeZ / 2 + ownRecess;
    } else {
      // Carriers use the normal above-origin placement: their box now
      // rises from their own base up to their payload (see sizeZ above).
      zOffset = sizeZ / 2;
    }
    mesh.position.set(sizeX / 2, zOffset, -sizeY / 2);
    mesh.userData = {
      resourceName: node.name,
      resourceType: node.type,
      category: node.category,
      model: node.model,
    };
    group.add(mesh);
    hoverables.push(mesh);
  }

  // A real Inheco ODTC's lid isn't a PyLabRobot child resource (Thermocycler
  // models a plate landing directly on the block via child_location, not a
  // separate lid sub-resource -- see custom_labware.py), so there's no scene
  // node to build this from; it's purely a visualizer-side extra, sized and
  // positioned as an approximation of the plate-holder area it needs to
  // cover. Slides horizontally to "open" (see thermocycler_backend.py's
  // docstring for why that's the real mechanism, not a hinge) -- see
  // thermocycler.js's animateThermocyclerLid().
  let lidMesh = null;
  let lidClosedPos = null;
  let lidOpenPos = null;
  if (node.category === "thermocycler") {
    // Sized off the real PCR plate's own SBS footprint (127.76 x 85.48mm --
    // pylabrobot.resources.corning_costar.cor_96_wellplate_360uL_Fb, the
    // plate this visualizer's own verification script lands on the
    // thermocycler) plus a small clearance margin, *not* a fraction of the
    // unit's own size_x/size_y -- a fraction of the housing was tried first
    // and came out nearly square (~134 x ~136mm), which read as the lid
    // being rotated 90 degrees next to the visibly landscape-shaped plate
    // underneath it (a real plate, and its lid, are noticeably wider
    // (rail-parallel, X) than deep (front-to-back, Y)). Anchoring directly
    // to the plate's real proportions keeps the lid landscape-shaped no
    // matter how the housing's own size_x/size_y are tuned.
    const PLATE_FOOTPRINT_X_MM = 127.76;
    const PLATE_FOOTPRINT_Y_MM = 85.48;
    const lidClearanceMm = 6; // each side, so the lid visibly overlaps the plate's edges
    const lidSizeX = PLATE_FOOTPRINT_X_MM + lidClearanceMm * 2;
    const lidSizeY = PLATE_FOOTPRINT_Y_MM + lidClearanceMm * 2;
    const lidThickness = 8;
    const lidGeometry = new THREE.BoxGeometry(lidSizeX, lidThickness, lidSizeY);
    const lidMaterial = new THREE.MeshLambertMaterial({ color: 0x2c2f36 });
    lidMesh = new THREE.Mesh(lidGeometry, lidMaterial);
    // Resting height: near the top of the *declared* full housing height
    // (node.size_z, 124.3mm for a real ODTC), not the shorter carrier-style
    // sizeZ used for the block above (which only reaches the payload holder
    // height) -- leaves clearance for a PCR plate's own height between the
    // holder and the closed lid.
    const lidRestZ = (node.size_z ?? sizeZ) * 0.85;
    // Front margin matches child_location.y's own 5mm margin.
    const lidFrontMarginMm = 5;
    const lidCenterY = lidFrontMarginMm + lidSizeY / 2;
    lidClosedPos = new THREE.Vector3(sizeX / 2, lidRestZ, -lidCenterY);
    // "Open" slides the lid back along Y (per user direction: "the lid
    // should slide along the y-axis") just far enough to clear the plate,
    // capped so it lands flush with the unit's own rear edge (sizeY) rather
    // than overhanging past the real housing's footprint.
    const lidSlideDistanceMm = sizeY - (lidCenterY + lidSizeY / 2);
    lidOpenPos = new THREE.Vector3(sizeX / 2, lidRestZ, -lidCenterY - lidSlideDistanceMm);
    lidMesh.position.copy(lidClosedPos);
    lidMesh.userData = {
      resourceName: node.name,
      resourceType: node.type,
      category: node.category,
      model: node.model,
    };
    group.add(lidMesh);
    hoverables.push(lidMesh);
  }

  if (isDeck) {
    addRailLabels(group, node, deckSurfaceZ);
    addRailLines(group, node, deckSurfaceZ);
  }

  // A tip spot's own box is a near-zero-height placement marker (see
  // events.py's tip_grab_point() docstring for why), and -- easy to miss --
  // its *location.z* is likewise not a rendering-relevant surface: tip rack
  // factories place spots via a large negative dz (e.g. -83.5mm) that's
  // calibrated for firmware pick-up-depth math, not for "where the tip
  // visually pokes out." Anchoring the pyramid to the spot's own local
  // origin buries it far below the rack. Instead, cancel that baked-in
  // offset out (using the *parent* rack's own height, passed down as
  // parentSizeZ) so the pyramid hangs from just under the rack's visible
  // top surface, where a tip actually appears.
  let tipPyramid = null;
  if (node.category === "tip_spot") {
    // The rack (scene.py's `_rack_tip_length`) reports the real length of
    // whatever tip model this rack holds; fall back to the arbitrary
    // constant only if that lookup came back empty (e.g. a custom TipRack
    // subclass scene.py's heuristic doesn't handle).
    const tipHeight = parentTipLengthMm ?? TIP_PYRAMID_HEIGHT;
    const geometry = new THREE.ConeGeometry(TIP_PYRAMID_RADIUS, tipHeight, 4);
    // Always visible (present -> amber, empty -> black+translucent) rather
    // than shown/hidden by tip presence -- an empty slot should still read
    // as a slot, not disappear. Starts empty; the first "state" event (or
    // embedded op-event data) sets the real color/opacity.
    tipPyramid = new THREE.Mesh(
      geometry,
      new THREE.MeshLambertMaterial({ color: EMPTY_COLOR, transparent: true, opacity: EMPTY_OPACITY })
    );
    const localZ = node.location?.z ?? 0;
    const rackTopInSpotLocalFrame = (parentSizeZ ?? 0) - localZ;
    tipPyramid.position.set(
      sizeX / 2,
      rackTopInSpotLocalFrame - tipHeight / 2,
      -sizeY / 2
    );
    // THREE.ConeGeometry's apex points toward +Y by default (an upright
    // cone) -- flip it so the apex points down and the wide end is up,
    // like an actual pipette tip's mounting collar facing the rack surface.
    tipPyramid.rotation.x = Math.PI;
    tipPyramid.rotation.y = Math.PI / 4; // diamond-facing orientation, purely cosmetic
    tipPyramid.userData = {
      resourceName: node.name,
      resourceType: node.type,
      category: node.category,
      model: node.model,
    };
    group.add(tipPyramid);
    hoverables.push(tipPyramid);
  }

  resourceIndex.set(node.name, {
    group,
    mesh,
    node,
    baseColor: mesh ? mesh.material.color.clone() : null,
    tipPyramid,
    // Every resource gets one, uniformly -- cheap when nothing's ever
    // enqueued on it (main.js's render loop ticks every entry's animQueue
    // every frame regardless of category), and means a category that wants
    // sequenced animation (currently just "thermocycler" -- see
    // thermocycler.js) never needs scene-builder.js's own per-category
    // branching to know about it.
    animQueue: new AnimationQueue(),
    // A tip_spot's own capacity, in µL -- known at scene-build time (every
    // spot in a rack holds the same tip model) and constant for this
    // spot's whole lifetime, unlike a *channel*'s carried tip (which
    // switches models across a run and so needs its capacity threaded
    // through each pick_up_tips op event instead -- see the "pick_up_tips"
    // case in gantry.js's handleOpEvent()). Read by resource-state.js's
    // applyState()/applyEmbeddedResourceState() to color a present tip
    // correctly without needing that data re-sent on every single state
    // update.
    tipMaxVolumeUl: node.category === "tip_spot" ? parentTipMaxVolumeUl ?? null : null,
    // Live volume, kept in sync by resource-state.js's applyState()/
    // applyEmbeddedResourceState() below -- purely for the hover tooltip
    // (see tooltip.js); the mesh's own color/opacity is the actual visual
    // state. maxVolume seeded from the node's own declared capacity so the
    // tooltip has something sensible to show even before any "state"
    // message arrives.
    volume: null,
    maxVolume: node.max_volume ?? null,
    // Thermocycler-only fields -- lidMesh/lidOpenPos/lidClosedPos null for
    // every other category (see the "thermocycler" branch above).
    lidMesh,
    lidOpenPos,
    lidClosedPos,
    lidOpen: false,
    // Last-run protocol's human-readable summary (see
    // thermocycler_backend.py's summarize_protocol()) -- set by
    // resource-state.js's applyState() on a "protocol_summary" state
    // message, shown in the hover tooltip. null until a protocol has
    // actually run.
    protocolSummary: null,
  });

  // Children's own layout math (e.g. the tip-spot pyramid's "where's the
  // rack's real surface" calculation above) needs the parent's *declared*
  // size_z, not whatever we chose to actually render it as -- thin
  // categories deliberately render shorter than their declared height, and
  // that shrink must not shift where a child thinks its parent's surface is.
  const declaredSizeZ = node.size_z ?? 0;
  // A tip_rack node carries tip_length_mm/tip_max_volume_ul (see scene.py);
  // anything else just passes through whatever it received, in case of
  // unexpected nesting.
  const tipLengthMm = node.tip_length_mm ?? parentTipLengthMm;
  const tipMaxVolumeUl = node.tip_max_volume_ul ?? parentTipMaxVolumeUl;
  for (const child of node.children ?? []) {
    const childObj = buildResourceObject(child, false, declaredSizeZ, tipLengthMm, tipMaxVolumeUl);
    group.add(childObj);
  }

  return group;
}

// Rebuilds the whole Three.js tree for a fresh "scene" websocket message
// into `sceneRoot` (owned by main.js's viewport setup), clearing whatever
// was there (and every resource's own hover/state bookkeeping) first.
// Deliberately does *not* touch the camera, the gantry, or the event log --
// see main.js's own loadScene() wrapper, which calls this and then handles
// those (fitCameraToContent(), setRestZ(), logEvent()) itself, keeping this
// module a clean leaf with no upward imports.
export function loadScene(sceneRoot, deckNode) {
  sceneRoot.clear();
  resourceIndex.clear();
  hoverables.length = 0;
  const deckGroup = buildResourceObject(deckNode, true);
  sceneRoot.add(deckGroup);
  return deckGroup;
}
