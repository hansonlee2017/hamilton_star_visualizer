// Hamilton Visualizer frontend.
//
// Renders the scene graph streamed from VisualizerServer as simple boxes in
// an isometric Three.js view, and animates the 8-channel gantry from the
// "op" events emitted by VisualizerBackend. See docs/DESIGN.md.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// ---------------------------------------------------------------------------
// Coordinate mapping: PyLabRobot is (x right, y "back", z up), in millimeters.
// Three.js is conventionally (x right, y up, z toward viewer). We map
// PLR z (height) -> Three y, and PLR y -> Three -z, keeping x as-is.
// ---------------------------------------------------------------------------
function mapPoint(x, y, z) {
  return new THREE.Vector3(x, z, -y);
}

// ---------------------------------------------------------------------------
// Category -> color palette (simple bounding boxes, no textures/materials
// beyond flat color, per the project's "keep it simple" scope).
// ---------------------------------------------------------------------------
const CATEGORY_COLORS = {
  deck: 0x3a3f47,
  tip_carrier: 0x5a6270,
  plate_carrier: 0x5a6270,
  plate_holder: 0x5a6270,
  mfx_carrier: 0x5a6270,
  tube_carrier: 0x5a6270,
  trough_carrier: 0x5a6270,
  tip_rack: 0x3d6fa8,
  // Same teal as "well" -- a trough/tube is a liquid container too, and
  // gets the same volumeVisual() fill-level color/opacity treatment
  // automatically (that logic isn't well-specific, just Container-shaped
  // "has a volume" state), so starting from the same base color keeps
  // that gradient reading the same way.
  trough: 0x59c9a5,
  tube: 0x59c9a5,
  // Deliberately *not* a shade of green: a plate's base needs to read as a
  // distinct supporting structure underneath its wells, the same way the
  // tip rack's blue base reads as distinct from its amber/black tips --
  // sharing the well-fill-gradient's hue (green, previously 0x3d9970) made
  // the base blend into its own contents instead of standing apart from it.
  plate: 0x6a5a94,
  well: 0x59c9a5,
  tip_spot: 0x8a8f98,
  trash: 0x8a3d3d,
  // Distinct from every carrier's neutral grey -- this is an active
  // instrument, not passive labware support, and the warm tone previews
  // the shimmer effect run_protocol() triggers (see animateThermocycler
  // Shimmer()).
  thermocycler: 0x8a5a3d,
};
const DEFAULT_COLOR = 0x6b7280;

// Deck and carrier resources declare a size_z that reflects their whole
// envelope (for a deck, ~900mm can be the instrument housing; for a
// carrier, ~130mm is the full rail height, not the height of the carrier's
// own structure) -- not a value you'd want to draw as a solid box directly.
// The deck is drawn as a thin platform; carriers are drawn as a shaft from
// their base up to their payload's holder -- see buildResourceObject().
const CARRIER_CATEGORIES = new Set([
  "tip_carrier",
  "plate_carrier",
  "mfx_carrier",
  "tube_carrier",
  // Confirmed the same envelope-vs-payload gap as every other carrier here
  // (e.g. Trough_CAR_5R60_A00: declared size_z=104mm, but its trough site
  // attaches at only z=63.5mm) -- without this, a reservoir carrier renders
  // as a full-height solid box that buries its own trough, the same bug
  // already fixed for the others in round 7.
  "trough_carrier",
  // Per user direction: render the thermocycler the same "solid block up
  // to the payload holder" way as any other carrier -- its own declared
  // size_z (124.3mm, the ODTC's real full housing height -- see
  // custom_labware.py) is likewise bigger than the visible payload
  // surface (child_location.z, ~74.6mm, where a PCR plate actually sits).
  // A separate lid mesh (see buildResourceObject()) sits above this block,
  // not part of it -- the lid is the one part of a real ODTC that visibly
  // moves (see thermocycler_backend.py's docstring: "opens and closes by
  // horizontal move").
  "thermocycler",
]);
const ENVELOPE_PLATFORM_THICKNESS = 10;
// tip_rack and plate have the same "declared size_z is bigger than the
// visible surface" problem as carriers -- their actual payload (a TipSpot's
// tip, a Well's liquid) sits recessed *inside* that declared height, so a
// solid box the full height buries it. Rendered the same way as carriers:
// a thin slab, not the full block.
const THIN_CATEGORIES = new Set(["tip_rack", "plate"]);
const THIN_CATEGORY_THICKNESS = 3;
// A present tip's color depends on its nameplate capacity (real Hamilton
// tips physically come in these -- see hamilton_96_tiprack_{50,300,1000}uL_
// filter in this project's demos), read from tip_max_volume_ul wherever a
// tip actually appears (a TipRack's own scene node for resting tips --
// scene.py's _inject_tip_info() -- or a pick_up_tips op entry for a
// channel's carried tip -- events.py's channel_ops_event()). Picking a tip
// size by transfer volume matters for realism (a 5uL transfer in a 1000uL
// tip is inaccurate on a real instrument) but isn't this file's job to
// enforce -- it just needs to render whichever tip a protocol actually used
// with the right color.
const TIP_COLOR_BY_VOLUME = [
  [50, 0xf48fb1], // pink
  [300, 0xffd54f], // yellow
  [Infinity, 0xffffff], // white
];
const TIP_PRESENT_COLOR_FALLBACK = 0xe0b23d; // unknown capacity -- the old flat amber
function tipColorForVolume(maxVolumeUl) {
  if (maxVolumeUl == null) return TIP_PRESENT_COLOR_FALLBACK;
  for (const [threshold, color] of TIP_COLOR_BY_VOLUME) {
    if (maxVolumeUl <= threshold) return color;
  }
  return TIP_PRESENT_COLOR_FALLBACK;
}
// Empty tip spots/wells are always rendered (not hidden) so a slot reads
// as "empty" rather than "missing" -- black distinguishes that at a glance
// from an occupied one, per user feedback.
const EMPTY_COLOR = 0x000000;
// A tip's real length (~95mm for a 1000uL Hamilton tip) is much larger than
// the ~9mm spacing between rack positions -- drawn to true scale, adjacent
// tips would overlap. These are a visually-legible compromise, not to
// scale, same tradeoff as the gantry channel glyph size below.
const TIP_PYRAMID_RADIUS = 3.2;
const TIP_PYRAMID_HEIGHT = 16;
// The channel's own carried-tip glyph is longer than the ones resting in
// the rack -- see animateChannelOp()'s CHANNEL_TIP_HEIGHT offset, which
// relies on this length to keep the channel *body* clear of whatever
// labware the tip is reaching into (a well, a rack, the trash). Radius
// stays under half the 9mm channel spacing so neighboring channels' tips
// never visually touch.
const CHANNEL_TIP_RADIUS = TIP_PYRAMID_RADIUS * 1.3;
const CHANNEL_TIP_HEIGHT = TIP_PYRAMID_HEIGHT * 2.2;
const VOLUME_EMPTY_COLOR = new THREE.Color(EMPTY_COLOR);
const VOLUME_FULL_COLOR = new THREE.Color(0x2ee6a8);
const PULSE_COLOR = new THREE.Color(0xffffff);

// Hamilton deck rail geometry, from pylabrobot.resources.hamilton.
// hamilton_decks: rails_to_location(rail) = Coordinate(x=100.0 + (rail-1)
// * 22.5, ...). `num_rails` itself *is* already part of a deck node's own
// serialize() output (it's a real dataclass field, not scene.py-injected),
// but the 100.0/22.5 constants aren't resource attributes anywhere -- they
// only exist as that method's arithmetic -- so they're hardcoded here the
// same way CHANNEL_PITCH_MM is, rather than threading two numbers that
// never change per PyLabRobot's own source through scene.py for this.
const RAIL_X_OFFSET_MM = 100.0;
const RAIL_WIDTH_MM = 22.5;
const RAIL_LABEL_INTERVAL = 5;

const LEGEND_ENTRIES = [
  ["Carrier", 0x5a6270],
  ["Tip rack", 0x3d6fa8],
  ["Tip spot (empty)", 0x8a8f98],
  ["Tip (<=50uL)", 0xf48fb1],
  ["Tip (<=300uL)", 0xffd54f],
  ["Tip (<=1000uL)", 0xffffff],
  ["Plate", 0x6a5a94],
  ["Well (fill level)", 0x59c9a5],
  ["Trash", 0x8a3d3d],
  ["Gantry channel", 0xe0b23d],
  ["Thermocycler", 0x8a5a3d],
];

// ---------------------------------------------------------------------------
// DOM handles
// ---------------------------------------------------------------------------
const container = document.getElementById("canvas-container");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const tooltipEl = document.getElementById("tooltip");
const legendRowsEl = document.getElementById("legend-rows");
const logListEl = document.getElementById("log-list");
const replayBtn = document.getElementById("replay-btn");
const startBtn = document.getElementById("start-btn");
const resetBtn = document.getElementById("reset-btn");
const speedSelect = document.getElementById("speed-select");
const runParamsEl = document.getElementById("run-params");

// Populated by renderRunParams() from the server's "run_params" message --
// most demos never send any fields (see server.py's set_run_params()
// docstring), in which case this stays empty and #run-params stays hidden
// (its CSS default -- see index.html). `runParamFields` is the field-spec
// list itself (needed at Start-click time for id/min/max/default);
// `runParamInputs` maps field id -> its rendered <input>, for every
// editable ("number") field currently shown.
let runParamFields = [];
const runParamInputs = new Map();

// Tracked separately from the DOM so refreshStartButton() can OR them with
// text-field validity below without re-deriving "are we connected"/"has
// this run already started" from scratch each time.
let wsConnected = false;
let protocolStarted = false;

// A "text" field (see server.py's set_run_params() docstring) with a
// declared `length` blocks "Start Protocol" until its current value is
// exactly that long -- unlike a "number" field, which always clamps to
// something valid, a too-short word has no sensible default to silently
// fall back to mid-edit.
function runParamsValid() {
  for (const field of runParamFields) {
    if (field.type !== "text" || field.length == null) continue;
    const input = runParamInputs.get(field.id);
    if (!input || input.value.length !== field.length) return false;
  }
  return true;
}

function refreshStartButton() {
  startBtn.disabled = !wsConnected || protocolStarted || !runParamsValid();
}

// Builds the HUD's run-params row generically from the server-declared
// field list -- see server.py's set_run_params() docstring for the exact
// schema. Three field types: "number" (an editable input), "text" (an
// editable input restricted to uppercase A-Z0-9, sanitized as you type,
// gating the Start button via runParamsValid() above while too short),
// and "computed" (a read-only derived readout; currently only
// "picogreen_working_solution", what picogreen_demo.py's "PicoGreen 195uL"
// readout uses -- an unrecognized `basis` is simply not rendered, so this
// can grow new computed kinds without breaking older ones). A "computed"
// field's `of` must name a "number" field appearing *earlier* in the same
// list, since fields are rendered in a single top-to-bottom pass.
function renderRunParams(fields) {
  runParamsEl.innerHTML = "";
  runParamInputs.clear();
  runParamFields = fields || [];
  runParamsEl.classList.toggle("visible", runParamFields.length > 0);

  for (const field of runParamFields) {
    if (field.type === "number") {
      const label = document.createElement("label");
      if (field.title) label.title = field.title;
      label.appendChild(document.createTextNode(field.label ?? field.id));
      const input = document.createElement("input");
      input.type = "number";
      if (field.min != null) input.min = field.min;
      if (field.max != null) input.max = field.max;
      input.step = field.step ?? 1;
      input.value = field.default ?? field.min ?? 0;
      label.appendChild(input);
      if (field.suffix) label.appendChild(document.createTextNode(field.suffix));
      runParamsEl.appendChild(label);
      runParamInputs.set(field.id, input);
    } else if (field.type === "text") {
      const label = document.createElement("label");
      if (field.title) label.title = field.title;
      label.appendChild(document.createTextNode(field.label ?? field.id));
      const input = document.createElement("input");
      input.type = "text";
      if (field.length != null) {
        input.maxLength = field.length;
        // Native constraint-validation attributes -- purely for the
        // #run-params input[type="text"]:invalid CSS (index.html) to have
        // something real to key off; refreshStartButton()/runParamsValid()
        // above don't rely on the browser's own validity state at all.
        input.minLength = field.length;
        input.required = true;
      }
      input.value = String(field.default ?? "")
        .toUpperCase()
        .slice(0, field.length);
      input.addEventListener("input", () => {
        const clean = input.value
          .toUpperCase()
          .replace(/[^A-Z0-9]/g, "")
          .slice(0, field.length ?? input.value.length);
        if (clean !== input.value) input.value = clean;
        refreshStartButton();
      });
      label.appendChild(input);
      runParamsEl.appendChild(label);
      runParamInputs.set(field.id, input);
    } else if (field.type === "computed") {
      const span = document.createElement("span");
      span.className = "readout";
      if (field.title) span.title = field.title;
      runParamsEl.appendChild(span);
      const sourceInput = runParamInputs.get(field.of);
      const update = () => {
        if (field.basis === "picogreen_working_solution") {
          const sampleVol = sourceInput ? Number(sourceInput.value) || 0 : 0;
          span.textContent = `PicoGreen ${(field.total ?? 0) - sampleVol}µL`;
        }
      };
      if (sourceInput) sourceInput.addEventListener("input", update);
      update();
    }
  }
  refreshStartButton();
}

replayBtn.addEventListener("click", () => {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  currentWs.send(JSON.stringify({ action: "replay" }));
  logEvent("replay", "requested from server");
});

// Locks the two run-parameter inputs and Replay -- called both
// optimistically (this tab clicked Start) and authoritatively (the
// server's "start_status" broadcast, which every connected tab receives --
// see the websocket handler below) so a *second* browser tab that never
// clicked Start still can't edit params, or replay over a live run, for a
// run already underway. Replay's lock lifts again once "run_status" says
// the run finished (see that handler below) -- unlike the params, which
// stay locked until a Reset actually starts a new run.
function lockForRun() {
  for (const input of runParamInputs.values()) input.disabled = true;
  replayBtn.disabled = true;
}

startBtn.addEventListener("click", () => {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  // Button is disabled (see refreshStartButton()) whenever a "text" field
  // is still short of its declared length, so by the time a click can
  // reach here every text field is already exactly the right length --
  // this loop only still needs to *clamp* "number" fields (a number field
  // is never invalid, just possibly out of range) and pass "text" fields
  // through as-is. The server also ignores a second "start_protocol" once
  // one's been accepted, so a stale/hand-crafted message here can't change
  // an already-running protocol's params either way.
  const params = {};
  for (const field of runParamFields) {
    const input = runParamInputs.get(field.id);
    if (!input) continue;
    if (field.type === "number") {
      const raw = Number(input.value);
      let value = Number.isFinite(raw) ? raw : field.default ?? field.min ?? 0;
      if (field.min != null) value = Math.max(field.min, value);
      if (field.max != null) value = Math.min(field.max, value);
      params[field.id] = Math.round(value);
    } else if (field.type === "text") {
      params[field.id] = input.value;
    }
  }
  currentWs.send(JSON.stringify({ action: "start_protocol", params }));
  // Optimistically reflect it immediately; the server's own
  // "start_status" broadcast (sent to every connected client, including
  // this one) will confirm it a moment later regardless.
  startBtn.disabled = true;
  startBtn.classList.add("started");
  lockForRun();
  const detail = Object.entries(params)
    .map(([id, value]) => `${id}=${value}`)
    .join(", ");
  logEvent("start", detail ? `protocol started (${detail})` : "protocol started");
});

resetBtn.addEventListener("click", () => {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  currentWs.send(JSON.stringify({ action: "reset" }));
  // Optimistically disable right away -- the server's "reset" broadcast
  // (once the protocol script actually rewinds) is what re-enables
  // everything for the next run; see that handler below.
  resetBtn.disabled = true;
  logEvent("reset", "requested");
});

// durationScale is declared with animateChannelOp() below (it's the thing
// that reads it); this just writes it whenever the dropdown changes.
speedSelect.addEventListener("change", () => {
  durationScale = Number(speedSelect.value) || 1;
});

for (const [label, color] of LEGEND_ENTRIES) {
  const row = document.createElement("div");
  row.className = "row";
  const swatch = document.createElement("div");
  swatch.className = "swatch";
  swatch.style.background = `#${color.toString(16).padStart(6, "0")}`;
  const text = document.createElement("span");
  text.textContent = label;
  row.appendChild(swatch);
  row.appendChild(text);
  legendRowsEl.appendChild(row);
}

function logEvent(op, detail) {
  const entry = document.createElement("div");
  entry.className = "entry";
  const time = new Date().toLocaleTimeString();
  entry.innerHTML =
    `<span class="time">${time}</span>` +
    `<span class="op">${op}</span> <span class="detail">${detail ?? ""}</span>`;
  logListEl.insertBefore(entry, logListEl.firstChild);
  while (logListEl.children.length > 200) {
    logListEl.removeChild(logListEl.lastChild);
  }
}

// ---------------------------------------------------------------------------
// Three.js scene setup
// ---------------------------------------------------------------------------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1e23);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);

const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10000);
camera.position.set(600, 600, 600);
camera.up.set(0, 1, 0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.1;

scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 0.9);
sun.position.set(1, 2, 1);
scene.add(sun);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
fillLight.position.set(-1, 0.5, -1);
scene.add(fillLight);

const sceneRoot = new THREE.Group();
scene.add(sceneRoot);

let frustumHalfHeight = 400; // updated once we know the deck size

// Frame the camera on the actual built geometry's bounding box, rather than
// trusting any single resource's declared size_x/y/z -- e.g. a deck
// resource's size_z can reflect the whole instrument housing, not just the
// populated work surface (see DECK_PLATFORM_THICKNESS above).
function fitCameraToContent(object3d) {
  const box = new THREE.Box3().setFromObject(object3d);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());

  const radius = Math.max(size.x, size.y, size.z, 100) * 0.65;
  frustumHalfHeight = radius;
  const dir = new THREE.Vector3(1, 1, 1).normalize();
  camera.position.copy(center.clone().add(dir.multiplyScalar(radius * 2.6)));
  controls.target.copy(center);
  camera.lookAt(controls.target);
  updateCameraFrustum();
}

function updateCameraFrustum() {
  const aspect = container.clientWidth / container.clientHeight;
  const h = frustumHalfHeight;
  camera.left = -h * aspect;
  camera.right = h * aspect;
  camera.top = h;
  camera.bottom = -h;
  camera.updateProjectionMatrix();
}

function onResize() {
  renderer.setSize(container.clientWidth, container.clientHeight);
  updateCameraFrustum();
}
window.addEventListener("resize", onResize);

// ---------------------------------------------------------------------------
// Scene-graph -> Three.js object construction
// ---------------------------------------------------------------------------

// resourceName -> { group, mesh, node, baseColor }
const resourceIndex = new Map();
const hoverables = [];

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
// a texture" approach as createFlowTexture() below -- no font-loading or
// text-geometry library needed for a handful of short numeric labels.
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

function buildResourceObject(node, isRoot, parentSizeZ, parentTipLengthMm, parentTipMaxVolumeUl) {
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
  // animateThermocyclerLid().
  let lidMesh = null;
  let lidClosedPos = null;
  let lidOpenPos = null;
  if (node.category === "thermocycler") {
    // sizeX (157.5mm, exactly 7 deck rails -- see inheco_odtc_thermocycler())
    // is rail-parallel and narrow; sizeY (248mm) is the long, front-to-back
    // axis a real ODTC actually has (per user direction). 0.85 covers the
    // ~127.76mm SBS plate width the lid needs to clear with a little margin
    // either side, out of the unit's own 157.5mm width.
    const lidSizeX = sizeX * 0.85;
    // Front region's depth along Y -- deliberately *not* half of sizeY: a
    // real ODTC's plate-holding front section can run longer than its rear
    // electronics section (per user direction: "the plate is in the front,
    // but may be more than half"). 0.55 * 248mm =~ 136mm, a bit past half.
    const lidSizeY = sizeY * 0.55;
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
    // A tip_spot's own capacity, in µL -- known at scene-build time (every
    // spot in a rack holds the same tip model) and constant for this
    // spot's whole lifetime, unlike a *channel*'s carried tip (which
    // switches models across a run and so needs its capacity threaded
    // through each pick_up_tips op event instead -- see the "pick_up_tips"
    // case in handleOpEvent()). Read by applyState()/
    // applyEmbeddedResourceState() to color a present tip correctly
    // without needing that data re-sent on every single state update.
    tipMaxVolumeUl: node.category === "tip_spot" ? parentTipMaxVolumeUl ?? null : null,
    // Live volume, kept in sync by applyState()/applyEmbeddedResourceState()
    // below -- purely for the hover tooltip (see "Hover tooltips" section);
    // the mesh's own color/opacity is the actual visual state. maxVolume
    // seeded from the node's own declared capacity so the tooltip has
    // something sensible to show even before any "state" message arrives.
    volume: null,
    maxVolume: node.max_volume ?? null,
    // Thermocycler-only fields -- lidMesh/lidOpenPos/lidClosedPos null for
    // every other category (see the "thermocycler" branch above).
    lidMesh,
    lidOpenPos,
    lidClosedPos,
    lidOpen: false,
    // Last-run protocol's human-readable summary (see
    // thermocycler_backend.py's summarize_protocol()) -- set by applyState()
    // below on a "protocol_summary" state message, shown in the hover
    // tooltip. null until a protocol has actually run.
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

function loadScene(deckNode) {
  sceneRoot.clear();
  resourceIndex.clear();
  hoverables.length = 0;
  const deckGroup = buildResourceObject(deckNode, true);
  sceneRoot.add(deckGroup);
  fitCameraToContent(deckGroup);
  restZ = new THREE.Box3().setFromObject(deckGroup).max.y + 150;
  logEvent("scene", `loaded deck "${deckNode.name}" (${deckNode.children?.length ?? 0} items)`);
}

// ---------------------------------------------------------------------------
// Live state updates (tip presence / liquid volume) -- Phase 2
// ---------------------------------------------------------------------------

// Shared with the op-event-embedded path below (applyEmbeddedResourceState)
// so both ways a color/opacity can be driven -- the generic "state"
// broadcast (used for the initial sync burst and for anything not covered
// by a gantry op) and the timing-correct embedded data (used for live
// pick_up_tips/drop_tips/aspirate/dispense) -- compute them identically.
const EMPTY_OPACITY = 0.5;
const FULL_OPACITY = 1.0;

function volumeVisual(volume, maxVolume) {
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

function tipVisual(hasTip, maxVolumeUl) {
  return {
    color: hasTip ? tipColorForVolume(maxVolumeUl) : EMPTY_COLOR,
    opacity: hasTip ? FULL_OPACITY : EMPTY_OPACITY,
  };
}

function applyState(resourceName, state) {
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
    entry.volume = state.volume;
    if (state.max_volume != null) entry.maxVolume = state.max_volume;
  } else if (Object.prototype.hasOwnProperty.call(state, "protocol_summary")) {
    entry.protocolSummary = state.protocol_summary;
  }
}

// Applies the resulting tip-presence/volume state that channel_ops_event()
// embeds directly in an "op" event's channel entry, timed by the caller
// (animateChannelOp's onArrive, i.e. exactly when the gantry visually
// arrives) rather than by whenever a separate "state" broadcast happens to
// show up -- see events.py's channel_ops_event() docstring for why the
// latter can't be relied on for timing. A no-op for resources without the
// relevant mesh (e.g. dropping a tip into a Trash, which has no tipPyramid).
function applyEmbeddedResourceState(entry) {
  const target = resourceIndex.get(entry.resource);
  if (!target) return;
  if (Object.prototype.hasOwnProperty.call(entry, "resource_has_tip")) {
    if (target.tipPyramid) {
      const { color, opacity } = tipVisual(entry.resource_has_tip, target.tipMaxVolumeUl);
      target.tipPyramid.material.color.setHex(color);
      target.tipPyramid.material.opacity = opacity;
    }
  } else if (Object.prototype.hasOwnProperty.call(entry, "resource_volume") && target.mesh) {
    const { color, opacity } = volumeVisual(entry.resource_volume, entry.resource_max_volume);
    target.mesh.material.color.copy(color);
    target.mesh.material.opacity = opacity;
    target.volume = entry.resource_volume;
    if (entry.resource_max_volume != null) target.maxVolume = entry.resource_max_volume;
  }
}

// ---------------------------------------------------------------------------
// Thermocycler: lid slide + cycling shimmer
// ---------------------------------------------------------------------------
const THERMOCYCLER_LID_MS = 600;
// Deliberately not tied to the backend's own timing at all -- run_protocol()
// completes instantly against the chatterbox backend (see
// thermocycler_backend.py's module docstring for why this visualizer never
// simulates real cycling time), so this fixed window is *the entire reason*
// a "cycling" animation is visible at all.
const THERMOCYCLER_SHIMMER_MS = 5000;

// Plain requestAnimationFrame tweens, like flowPulse()/Channel.pulse() --
// not routed through a Channel's enqueue()'d position queue, since the
// thermocycler itself never moves; only its lid (a short, fixed slide) and
// its block's color (a fixed-duration pulse) do.
function animateThermocyclerLid(entry, opening) {
  if (!entry.lidMesh || !entry.lidOpenPos || !entry.lidClosedPos) return;
  const from = entry.lidMesh.position.clone();
  const to = opening ? entry.lidOpenPos : entry.lidClosedPos;
  entry.lidOpen = opening;
  const start = performance.now();
  const duration = THERMOCYCLER_LID_MS * durationScale;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    entry.lidMesh.position.lerpVectors(from, to, t);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// A warm pulsing color on the block itself -- the same "something is
// actively happening here" language flowPulse() uses for a channel's tip,
// scaled to a whole-block, multi-second effect instead of one leg's ~550ms.
const THERMOCYCLER_SHIMMER_COLOR = new THREE.Color(0xffa040);
function animateThermocyclerShimmer(entry) {
  if (!entry.mesh) return;
  const material = entry.mesh.material;
  const baseColor = entry.baseColor.clone();
  const start = performance.now();
  const duration = THERMOCYCLER_SHIMMER_MS * durationScale;
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

// ---------------------------------------------------------------------------
// Gantry model + animation -- Phase 3
// ---------------------------------------------------------------------------
const NUM_CHANNELS_DEFAULT = 8;
const CHANNEL_Y_SPACING = 9; // mm, matches PLR's default minimum channel spacing
let restZ = 350;

const gantryGroup = new THREE.Group();
scene.add(gantryGroup);

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

class Channel {
  constructor(index) {
    this.index = index;
    // Negative: on a real Hamilton (and in PLR's own per-channel offsets --
    // e.g. an 8-channel drop_tips reports trash offsets +31.5, +22.5, ...,
    // -31.5 for channels 0-7, 9mm apart), channel 0 is the back-most
    // channel and increasing index moves toward the front (-y, PLR's "back"
    // axis -- see the coordinate-mapping comment up top). A plain `+index *
    // CHANNEL_Y_SPACING` here put channel 0 at the front and channel 7 at
    // the back instead -- the whole rest row was mirrored front-to-back.
    this.pos = { x: 0, y: -index * CHANNEL_Y_SPACING, z: restZ };
    this.hasTip = false;
    this.queue = [];
    this.current = null;

    this.group = new THREE.Group();

    // Sized a bit larger than a real Hamilton channel nose would be in mm --
    // a to-scale glyph is nearly invisible against a ~1m deck, and legibility
    // matters more here than strict scale accuracy for this one part.
    const bodyGeom = new THREE.CylinderGeometry(7, 7, 32, 12);
    this.body = new THREE.Mesh(bodyGeom, new THREE.MeshLambertMaterial({ color: 0x9aa0a8 }));
    this.body.position.y = 16;
    this.group.add(this.body);

    // Same inverted-pyramid shape as the tips resting in the rack (see
    // buildResourceObject) -- a bit longer than those (see
    // CHANNEL_TIP_HEIGHT) so the *body* clears the target labware's top by
    // a comfortable margin once animateChannelOp() accounts for it, and a
    // bit wider for readability, while staying under half the 9mm channel
    // spacing so adjacent channels' tips never touch.
    const tipGeom = new THREE.ConeGeometry(CHANNEL_TIP_RADIUS, CHANNEL_TIP_HEIGHT, 4);
    this.tipMesh = new THREE.Mesh(tipGeom, new THREE.MeshLambertMaterial({ color: EMPTY_COLOR }));
    this.tipMesh.position.y = -CHANNEL_TIP_HEIGHT / 2;
    // Flip apex-down (see the matching comment in buildResourceObject).
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
    setTimeout(() => this.body.material.color.setHex(0x9aa0a8), 250 * durationScale);
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
    const duration = FLOW_PULSE_MS * durationScale;
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

  // `onComplete`, if given, fires exactly when *this* waypoint's tween
  // finishes -- not a fixed wall-clock delay from when it was queued. That
  // distinction matters once the queue backs up (events arriving faster
  // than their ~1.6s animation takes to play out, which happens routinely):
  // a fixed-delay timer drifts out of sync with where the channel actually
  // visually is, while this fires exactly on arrival regardless of backup.
  // `target.x`/`target.y`/`target.z` may each be `null`, meaning "stay at
  // whatever this leg actually starts from on that axis" -- used for the
  // rise-to-safe-height leg (x/y must not move horizontally) and for
  // nudge_channel ops that only change one of x/y (see handleOpEvent's
  // "nudge_channel" case). `target.z` may instead be a function -- either
  // `() => number` (the descend/hold legs' tip-length-aware depth -- see
  // animateChannelOp()) or `(from) => number` (a rise/retract leg's
  // traverse-height target, which needs to know where *this* leg is
  // actually starting from -- see traverseLegZ()'s docstring for why).
  // None of these can just be resolved to a value
  // at enqueue time: since ops routinely arrive faster than their ~1.6s
  // animation plays out, the queue backs up, and a value captured now can
  // be stale by the time this leg actually starts -- e.g. still the
  // channel's *initial* position before it ever moved, or (for z) the
  // *previous* tip's length because the pick_up_tips op that updates
  // ch.tipLength for the *current* tip hasn't had its own animation reach
  // that point yet. Resolving both lazily, right when the leg starts in
  // update(), sidesteps that: by then, this channel's queue is strictly
  // FIFO, so anything enqueued earlier (including a preceding
  // pick_up_tips's onArrive) is guaranteed to have already run.
  // `duration` may also be a function (`(from, target) => number`), same
  // reasoning as `target.z` just above -- see animateChannelOp()'s
  // traverseHeightMm/endHeightMm handling for a leg whose duration depends
  // on values (this op's own tip length) that aren't safe to read until
  // the leg actually starts either.
  enqueue(target, duration, onComplete) {
    this.queue.push({ target, duration, onComplete });
  }

  update(dtMs) {
    if (!this.current) {
      this.current = this.queue.shift();
      if (this.current) {
        this.current.elapsed = 0;
        this.current.from = { ...this.pos };
        if (this.current.target.x === null) this.current.target.x = this.current.from.x;
        if (this.current.target.y === null) this.current.target.y = this.current.from.y;
        if (this.current.target.z === null) this.current.target.z = this.current.from.z;
        // Passed `this.current.from` -- see traverseLegZ()'s docstring for
        // why a rise leg's target needs to know where this leg is actually
        // starting from, not just resolve to a value at enqueue time.
        if (typeof this.current.target.z === "function") {
          this.current.target.z = this.current.target.z(this.current.from);
        }
        // Resolved after target.z above, not before -- a duration function
        // can use the now-numeric target/from to compute its own span.
        if (typeof this.current.duration === "function") {
          this.current.duration = this.current.duration(this.current.from, this.current.target);
        }
      }
    }
    if (!this.current) return;

    this.current.elapsed += dtMs;
    const t = Math.min(1, this.current.elapsed / this.current.duration);
    const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; // easeInOutQuad
    const { from, target } = this.current;
    this.pos = {
      x: THREE.MathUtils.lerp(from.x, target.x, ease),
      y: THREE.MathUtils.lerp(from.y, target.y, ease),
      z: THREE.MathUtils.lerp(from.z, target.z, ease),
    };
    this.applyPosition();

    if (t >= 1) {
      this.pos = { ...target };
      this.applyPosition();
      const { onComplete } = this.current;
      this.current = null;
      if (onComplete) onComplete();
    }
  }
}

let channels = [];
function ensureChannels(numChannels) {
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

// Playback speed for review -- a dropdown in the HUD sets this to 2 (0.5x)
// or 4 (0.25x) so the animation is easier to follow, especially on replay.
// Applied uniformly to every keyframe duration below and to flowPulse.
let durationScale = 1;
const scaled = (ms) => ms * durationScale;

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
function traverseLegZ(tipHeightMm, refZ, tipLengthFn) {
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

// Hamilton STAR's standard channel spacing -- also the minimum center-to-
// center distance two channels can be at without colliding.
const CHANNEL_PITCH_MM = 9.0;
const ROUND_MM = (v) => Math.round(v * 1000) / 1000;

// Assigns every channel in `channelIndices` (sorted ascending) a y for one
// gantry stop: y must decrease by at least `pitchMm` from each channel to
// the next (channel 0 is the highest-y channel -- see planGantryPasses()'s
// docstring). `fixedY` entries (Map) are non-negotiable -- this stop's real
// targets; every other channel is nudged off its preferred y (also a Map)
// no further than needed to keep the whole sequence in order.
//
// Solved with a change of variable, z[k] = y[channelIndices[k]] + k *
// pitchMm, turning "must decrease by >= pitchMm per step" into the simpler
// "must be non-increasing" -- then one forward pass (each value capped by
// the *actual resolved* value before it -- a fixed value is never capped,
// even if that means it's higher than what came before; that just means
// the earlier ones were resolved too low, corrected next) and one backward
// pass (each value raised to the actual resolved value after it, same
// exception for fixed values) converge on the unique tightest solution. A
// free channel sandwiched between two fixed ones always ends up consistent
// this way; the only way the *final* sequence can still be out of order is
// two fixed channels that are themselves mutually incompatible (out of
// order, or too close together), which is when this throws.
//
// (This is a direct port of hamilton_visualizer.gantry._resolve_ys --
// keep the two in sync if either changes. It lives here, not just
// server-side, because the whole point of moving this logic client-side
// is to sequence passes off each channel's own already-enqueued state --
// see planGantryPasses()'s docstring.)
function resolveChannelYs(channelIndices, fixedY, preferredY, pitchMm) {
  const eps = 1e-6;
  const n = channelIndices;
  const fixedZ = new Map();
  const preferredZ = new Map();
  n.forEach((ch, k) => {
    if (fixedY.has(ch)) fixedZ.set(k, fixedY.get(ch) + k * pitchMm);
    else preferredZ.set(k, preferredY.get(ch) + k * pitchMm);
  });

  const z = new Array(n.length).fill(0);
  let running = Infinity;
  for (let k = 0; k < n.length; k++) {
    const v = fixedZ.has(k) ? fixedZ.get(k) : Math.min(preferredZ.get(k), running);
    z[k] = v;
    running = v;
  }
  running = -Infinity;
  for (let k = n.length - 1; k >= 0; k--) {
    const v = fixedZ.has(k) ? fixedZ.get(k) : Math.max(z[k], running);
    z[k] = v;
    running = v;
  }
  for (let k = 0; k < n.length - 1; k++) {
    if (z[k] < z[k + 1] - eps) {
      throw new Error(
        `channels ${n[k]} and ${n[k + 1]} need y positions here that put them out of ` +
          `order or closer than ${pitchMm}mm apart -- this combination of targets isn't ` +
          "reachable in one gantry stop"
      );
    }
  }
  const result = new Map();
  n.forEach((ch, k) => result.set(ch, z[k] - k * pitchMm));
  return result;
}

// Groups a single multi-channel op's entries (msg.channels from one
// pick_up_tips/drop_tips/aspirate/dispense event) into a sequence of
// hardware-feasible gantry stops. A real Hamilton STAR's 8 channels are
// all bolted to one arm with a single x motor -- every loaded channel is
// always at the *same* x, whether or not it's doing anything there -- so a
// call whose targets don't share one x can't be reached in a single move,
// the way the naive "animate every entry's own (x, y) independently" code
// this replaced assumed.
//
// Channel-index-to-y direction: channel 0 is the highest-y (e.g. row "A")
// channel, increasing index means decreasing y -- matches how every demo
// in this repo assigns channels (`plate["A1:H1"]` assigns row A to channel
// 0 through row H to channel 7, and row A's y is larger than row H's).
//
// For each distinct x (ascending), every channel in this op with a target
// there is tried simultaneously first; if `resolveChannelYs` can't
// reconcile them (two channels needing y's whose gap, given how many
// channel-slots apart they are, exceeds their actual row gap), it falls
// back to one channel at a time, smallest index first -- exactly what a
// real instrument does when a single move can't reach both. Every *other*
// loaded channel -- whether idle for this whole op (this call doesn't
// target it at all, e.g. the other 7 channels while one alone does a
// single-channel serial dilution) or just this one stop -- gets nudged
// only as far as needed to stay clear, using each channel's own live
// `pos.y` (not a value threaded in from the protocol script) as its
// preferred position. "Loaded" here means "currently has a tip on"
// (`Channel.hasTip`), read directly off the renderer's own live state, not
// just "present in this call's entries" -- so this needs no cooperation
// from the Python side beyond issuing one normal multi-channel (or even
// single-channel) call; it also means a lopsided single-channel stage no
// longer leaves other channels' queues shorter than the busy one's (round
// 15 needed a calculated wait to paper over exactly that gap).
//
// Returns passes ordered so that simply enqueuing each one's legs in
// order -- onto every channel's own independent FIFO queue, see
// Channel.enqueue()'s docstring -- produces correct motion with no
// external timing/sleeping needed at all: each channel's queue naturally
// plays its own legs out in the order they were enqueued, and every pass
// here is only ever enqueued after the previous one.
function planGantryPasses(entries) {
  const targetedChannels = entries.map((e) => e.channel).sort((a, b) => a - b);
  const byChannel = new Map(entries.map((e) => [e.channel, e]));
  // Every *other* channel is dragged along too, tip or no tip -- a real
  // Hamilton's 8 channels share one arm, so a channel physically cannot
  // stay parked while a call that only targets *some* channels (a
  // single-channel serial dilution, or any multi-channel call with fewer
  // than 8 active entries) moves the arm somewhere else, regardless of
  // whether that channel happens to be carrying a tip right now.
  //
  // This used to be restricted to `loadedChannelsEager` (tip-carrying
  // channels only) -- deliberately widened to *every* channel (confirmed
  // live: a normalization-protocol run's un-targeted, tip-less channels
  // fell badly behind the targeted ones in queued animation time, since
  // they'd previously gotten nothing enqueued at all for calls that
  // didn't target them, eventually catching up to and animating a
  // *later* op -- picking up a tip from a different rack -- while the
  // targeted channels were still working through an earlier one; see
  // docs/PLAN.md's "Review round 34"). nudgeChannel()'s own total
  // duration already equals animateChannelOp()'s (same six leg-durations,
  // just the last three folded into one enqueue() call -- see that
  // function), so dragging every channel along for every op keeps all of
  // them accumulating identical total animation time regardless of which
  // ones a given call actually targets -- true lockstep by construction,
  // for any protocol, not just ones that happen to use every channel
  // evenly.
  const channelIndices = [...new Set([...targetedChannels, ...channels.keys()])].sort(
    (a, b) => a - b
  );
  // xs only ever comes from targeted channels -- a merely-dragged-along
  // channel has no target/x of its own to contribute a stop.
  const xs = [...new Set(targetedChannels.map((ch) => ROUND_MM(byChannel.get(ch).x)))].sort(
    (a, b) => a - b
  );

  // Seeded from each channel's own current position -- always accurate,
  // since it's the same state the renderer itself is driven by -- rather
  // than a snapshot the caller would otherwise have to compute by hand.
  const currentY = new Map(channelIndices.map((ch) => [ch, channels[ch].pos.y]));
  const passes = [];

  for (const x of xs) {
    const columnChannels = targetedChannels.filter((ch) => ROUND_MM(byChannel.get(ch).x) === x);

    let groups = [columnChannels];
    try {
      const fixedY = new Map(columnChannels.map((ch) => [ch, byChannel.get(ch).y]));
      const preferredY = new Map(
        channelIndices
          .filter((ch) => !columnChannels.includes(ch))
          .map((ch) => [ch, currentY.get(ch)])
      );
      resolveChannelYs(channelIndices, fixedY, preferredY, CHANNEL_PITCH_MM);
    } catch {
      groups = columnChannels.map((ch) => [ch]);
    }

    for (const group of groups) {
      const fixedY = new Map(group.map((ch) => [ch, byChannel.get(ch).y]));
      const preferredY = new Map(
        channelIndices.filter((ch) => !group.includes(ch)).map((ch) => [ch, currentY.get(ch)])
      );
      const resolved = resolveChannelYs(channelIndices, fixedY, preferredY, CHANNEL_PITCH_MM);
      for (const [ch, y] of resolved) currentY.set(ch, y);
      const idleMoves = new Map(
        channelIndices.filter((ch) => !group.includes(ch)).map((ch) => [ch, resolved.get(ch)])
      );
      passes.push({ x, active: group.map((ch) => byChannel.get(ch)), idleMoves });
    }
  }
  return passes;
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
  setTimeout(() => entry.mesh.material.color.copy(base), 250 * durationScale);
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

function handleOpEvent(msg) {
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
      if (entry) animateThermocyclerLid(entry, msg.op === "thermocycler_open_lid");
      logEvent(msg.op, msg.resource ?? "");
      break;
    }
    case "thermocycler_run_protocol": {
      const entry = resourceIndex.get(msg.resource);
      if (entry) {
        entry.protocolSummary = msg.protocol_summary;
        animateThermocyclerShimmer(entry);
      }
      logEvent(msg.op, `${msg.resource}: ${msg.protocol_summary ?? ""}`);
      break;
    }
    default:
      // 96-head / resource-move / manual-jog events: not animated in v1, but
      // still worth surfacing in the log so the panel reflects everything
      // the backend did.
      logEvent(msg.op, msg.resource ?? "");
  }
}

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------
let currentWs = null;

function connect() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
  currentWs = ws;

  ws.onopen = () => {
    if (ws !== currentWs) return; // stale socket superseded by a newer connect()
    statusEl.className = "connected";
    statusTextEl.textContent = "connected";
    replayBtn.disabled = false;
    // Whether to actually show this as clickable (vs. already-started) is
    // settled a moment later by the "start_status"/"run_status" the server
    // sends every new connection -- this just makes sure a *reconnect*
    // doesn't leave things stuck disabled from the previous connection's
    // onclose. refreshStartButton() also folds in current run-params
    // validity (see its docstring) rather than unconditionally enabling.
    wsConnected = true;
    refreshStartButton();
    resetBtn.disabled = true;
  };
  ws.onclose = () => {
    if (ws !== currentWs) return; // ditto -- don't let an old socket's close
    // clobber state a newer, already-open connection just set
    statusEl.className = "disconnected";
    statusTextEl.textContent = "disconnected -- retrying...";
    replayBtn.disabled = true;
    wsConnected = false;
    refreshStartButton();
    resetBtn.disabled = true;
    setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "scene") {
      loadScene(msg.deck);
      ensureChannels(msg.num_channels ?? NUM_CHANNELS_DEFAULT);
    } else if (msg.type === "run_params") {
      renderRunParams(msg.fields);
    } else if (msg.type === "state") {
      applyState(msg.resource, msg.state);
      window.__lastStateMessages = window.__lastStateMessages || [];
      window.__lastStateMessages.push(msg);
    } else if (msg.type === "op") {
      handleOpEvent(msg);
    } else if (msg.type === "start_status") {
      protocolStarted = msg.started;
      refreshStartButton();
      startBtn.classList.toggle("started", msg.started);
      if (msg.started) {
        lockForRun();
        logEvent("start", "protocol started");
      }
    } else if (msg.type === "run_status") {
      resetBtn.disabled = !msg.finished;
      resetBtn.classList.toggle("visible", msg.finished);
      if (msg.finished) {
        replayBtn.disabled = false;
        logEvent("run_status", "finished -- reset/replay available");
      }
    } else if (msg.type === "reset") {
      // The protocol script rewound to wait for a new "Start Protocol" --
      // put the whole HUD back to its pre-run state. The next "scene"
      // message (once the new run's lh.setup() fires) rebuilds the 3D
      // scene itself; this just resets the controls and log around it.
      for (const input of runParamInputs.values()) input.disabled = false;
      protocolStarted = false;
      refreshStartButton();
      startBtn.classList.remove("started");
      resetBtn.disabled = true;
      resetBtn.classList.remove("visible");
      replayBtn.disabled = false;
      logListEl.innerHTML = "";
      logEvent("reset", "ready for a new run");
    }
  };
}
connect();

// ---------------------------------------------------------------------------
// Hover tooltips
// ---------------------------------------------------------------------------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

renderer.domElement.addEventListener("pointermove", (event) => {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(hoverables, false);
  if (hits.length > 0) {
    const { resourceName, resourceType, category, model } = hits[0].object.userData;
    tooltipEl.style.display = "block";
    tooltipEl.style.left = `${event.clientX + 14}px`;
    tooltipEl.style.top = `${event.clientY + 14}px`;
    // Catalog identifier (e.g. "cor_96_wellplate_360uL_Fb",
    // "TIP_CAR_480_A00") -- `model` is a real PyLabRobot Resource field
    // (the name of the factory function/constant that built this specific
    // instance), already present in serialize() output with no scene.py
    // changes needed. `resourceType` above is the much coarser class name
    // ("Plate", "TipCarrier"); this is the specific catalog part number a
    // protocol author would actually recognize.
    const modelLine = model ? `<div class="model">${model}</div>` : "";
    // Volume line for any liquid container -- well, trough, or tube -- and
    // only once we actually know a value (entry.volume starts null until
    // the first "state" -- see resourceIndex.set()'s comment -- so an
    // unstarted protocol just omits the line rather than claiming 0uL).
    let volumeLine = "";
    if (category === "well" || category === "trough" || category === "tube") {
      const entry = resourceIndex.get(resourceName);
      if (entry && entry.volume != null) {
        // 1 decimal place on both sides -- a resource's real max_volume
        // (e.g. a tube carrier insert's declared capacity) can come out of
        // PyLabRobot as a long float (e.g. 203.52938905975373), not just
        // the live volume, so both need rounding here.
        const max = entry.maxVolume != null ? ` / ${entry.maxVolume.toFixed(1)}` : "";
        volumeLine = `<div class="volume">${entry.volume.toFixed(1)}${max} &micro;L</div>`;
      }
    }
    // Last-run PCR profile, e.g. "95.0C 0:30, 55.0C 0:30, 72.0C 1:00 (x30)"
    // -- see thermocycler_backend.py's summarize_protocol(). Omitted (not
    // "no protocol yet") until run_protocol() has actually broadcast one.
    let protocolLine = "";
    if (category === "thermocycler") {
      const entry = resourceIndex.get(resourceName);
      if (entry && entry.protocolSummary) {
        protocolLine = `<div class="volume">${entry.protocolSummary}</div>`;
      }
    }
    tooltipEl.innerHTML =
      `<div class="name">${resourceName}</div>` +
      `<div class="type">${resourceType}${category ? " &middot; " + category : ""}</div>` +
      modelLine +
      volumeLine +
      protocolLine;
  } else {
    tooltipEl.style.display = "none";
  }
});

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------
let lastTime = performance.now();
function animate(now) {
  const dt = now - lastTime;
  lastTime = now;
  for (const ch of channels) ch.update(dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

onResize();
requestAnimationFrame(animate);

// Debug hook -- inspect from the browser console with `window.__viz`.
// `channels` is a getter, not a plain reference, since ensureChannels()
// *reassigns* the module-level `channels` array (not just mutates it) --
// see docs/PLAN.md's "Review round 32" for the gantry-desync
// investigation this was added for.
window.__viz = {
  scene,
  camera,
  sceneRoot,
  gantryGroup,
  resourceIndex,
  controls,
  container,
  frustumHalfHeight: () => frustumHalfHeight,
  get channels() {
    return channels;
  },
};
