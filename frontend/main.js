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
  tip_rack: 0x3d6fa8,
  plate: 0x3d9970,
  well: 0x59c9a5,
  tip_spot: 0x8a8f98,
  trash: 0x8a3d3d,
};
const DEFAULT_COLOR = 0x6b7280;

// Deck and carrier resources declare a size_z that reflects their whole
// envelope (for a deck, ~900mm can be the instrument housing; for a
// carrier, ~130mm is the full rail height, not the height of the carrier's
// own structure) -- not a value you'd want to draw as a solid box directly.
// The deck is drawn as a thin platform; carriers are drawn as a shaft from
// their base up to their payload's holder -- see buildResourceObject().
const CARRIER_CATEGORIES = new Set(["tip_carrier", "plate_carrier", "mfx_carrier", "tube_carrier"]);
const ENVELOPE_PLATFORM_THICKNESS = 10;
// tip_rack and plate have the same "declared size_z is bigger than the
// visible surface" problem as carriers -- their actual payload (a TipSpot's
// tip, a Well's liquid) sits recessed *inside* that declared height, so a
// solid box the full height buries it. Rendered the same way as carriers:
// a thin slab, not the full block.
const THIN_CATEGORIES = new Set(["tip_rack", "plate"]);
const THIN_CATEGORY_THICKNESS = 3;
const TIP_PRESENT_COLOR = 0xe0b23d;
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

const LEGEND_ENTRIES = [
  ["Carrier", 0x5a6270],
  ["Tip rack", 0x3d6fa8],
  ["Tip spot (empty / tip)", 0x8a8f98],
  ["Plate", 0x3d9970],
  ["Well (fill level)", 0x59c9a5],
  ["Trash", 0x8a3d3d],
  ["Gantry channel", 0xe0b23d],
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
const speedSelect = document.getElementById("speed-select");

replayBtn.addEventListener("click", () => {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  currentWs.send(JSON.stringify({ action: "replay" }));
  logEvent("replay", "requested from server");
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

function buildResourceObject(node, isRoot, parentSizeZ) {
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
    const geometry = new THREE.BoxGeometry(sizeX, sizeZ, sizeY);
    const color = colorForNode(node);
    const material = new THREE.MeshLambertMaterial({
      color,
      transparent: true,
      opacity: isEnvelope ? 0.85 : 1.0,
    });
    mesh = new THREE.Mesh(geometry, material);
    // The deck platform sits *below* its own origin (z=0) rather than above
    // it, so carriers resting at deck-level z=0 sit visibly on top of it
    // instead of being embedded inside it. Carriers and thin categories
    // both use the normal above-origin placement -- carriers because their
    // box now rises from their own base up to their payload (see sizeZ
    // above), thin categories because a shallow base at their own origin is
    // exactly where their payload's holder/location math expects it.
    const zOffset = isDeck ? -sizeZ / 2 : sizeZ / 2;
    mesh.position.set(sizeX / 2, zOffset, -sizeY / 2);
    mesh.userData = { resourceName: node.name, resourceType: node.type, category: node.category };
    group.add(mesh);
    hoverables.push(mesh);
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
    const geometry = new THREE.ConeGeometry(TIP_PYRAMID_RADIUS, TIP_PYRAMID_HEIGHT, 4);
    // Always visible (present -> amber, empty -> black) rather than shown/
    // hidden by tip presence -- an empty slot should still read as a slot,
    // not disappear. Starts black; the first "state" event recolors it.
    tipPyramid = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ color: EMPTY_COLOR }));
    const localZ = node.location?.z ?? 0;
    const rackTopInSpotLocalFrame = (parentSizeZ ?? 0) - localZ;
    tipPyramid.position.set(
      sizeX / 2,
      rackTopInSpotLocalFrame - TIP_PYRAMID_HEIGHT / 2,
      -sizeY / 2
    );
    // THREE.ConeGeometry's apex points toward +Y by default (an upright
    // cone) -- flip it so the apex points down and the wide end is up,
    // like an actual pipette tip's mounting collar facing the rack surface.
    tipPyramid.rotation.x = Math.PI;
    tipPyramid.rotation.y = Math.PI / 4; // diamond-facing orientation, purely cosmetic
    tipPyramid.userData = { resourceName: node.name, resourceType: node.type, category: node.category };
    group.add(tipPyramid);
    hoverables.push(tipPyramid);
  }

  resourceIndex.set(node.name, {
    group,
    mesh,
    node,
    baseColor: mesh ? mesh.material.color.clone() : null,
    tipPyramid,
  });

  // Children's own layout math (e.g. the tip-spot pyramid's "where's the
  // rack's real surface" calculation above) needs the parent's *declared*
  // size_z, not whatever we chose to actually render it as -- thin
  // categories deliberately render shorter than their declared height, and
  // that shrink must not shift where a child thinks its parent's surface is.
  const declaredSizeZ = node.size_z ?? 0;
  for (const child of node.children ?? []) {
    const childObj = buildResourceObject(child, false, declaredSizeZ);
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
// so both ways a color can be driven -- the generic "state" broadcast (used
// for the initial sync burst and for anything not covered by a gantry op)
// and the timing-correct embedded data (used for live pick_up_tips/
// drop_tips/aspirate/dispense) -- compute it identically.
function volumeColor(volume, maxVolume) {
  const rawFrac = THREE.MathUtils.clamp((volume ?? 0) / (maxVolume || 1), 0, 1);
  // sqrt rather than the raw fraction: a linear scale makes small-but-real
  // volumes (e.g. a 50uL dispense into a 360uL well, 14%) look almost
  // identical to genuinely empty (0%), which is what a well right after a
  // dispense typically looks like right next to a well that's never been
  // touched. sqrt boosts the low end while keeping 0 at 0, 1 at 1, and the
  // ordering monotonic, so "more liquid" still always reads as "brighter."
  return VOLUME_EMPTY_COLOR.clone().lerp(VOLUME_FULL_COLOR, Math.sqrt(rawFrac));
}

function applyState(resourceName, state) {
  const entry = resourceIndex.get(resourceName);
  if (!entry) return;

  if (Object.prototype.hasOwnProperty.call(state, "tip")) {
    const hasTip = state.tip !== null && state.tip !== undefined;
    if (entry.tipPyramid) entry.tipPyramid.material.color.setHex(hasTip ? TIP_PRESENT_COLOR : EMPTY_COLOR);
  } else if (Object.prototype.hasOwnProperty.call(state, "volume") && entry.mesh) {
    entry.mesh.material.color.copy(volumeColor(state.volume, state.max_volume));
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
      target.tipPyramid.material.color.setHex(entry.resource_has_tip ? TIP_PRESENT_COLOR : EMPTY_COLOR);
    }
  } else if (Object.prototype.hasOwnProperty.call(entry, "resource_volume") && target.mesh) {
    target.mesh.material.color.copy(volumeColor(entry.resource_volume, entry.resource_max_volume));
  }
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
function createFlowTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0.0, "#bfeaff");
  gradient.addColorStop(0.25, "#2f8fc4");
  gradient.addColorStop(0.5, "#bfeaff");
  gradient.addColorStop(0.75, "#2f8fc4");
  gradient.addColorStop(1.0, "#bfeaff");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1, 3);
  return texture;
}
const FLOW_TEXTURE = createFlowTexture();
const FLOW_PULSE_MS = 550;

class Channel {
  constructor(index) {
    this.index = index;
    this.pos = { x: 0, y: index * CHANNEL_Y_SPACING, z: restZ };
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

    // Own clone so this channel's scroll offset can't fight another
    // channel's concurrent (and possibly opposite-direction) flowPulse().
    this.flowTexture = FLOW_TEXTURE.clone();

    gantryGroup.add(this.group);
    this.applyPosition();
  }

  applyPosition() {
    const p = mapPoint(this.pos.x, this.pos.y, this.pos.z);
    this.group.position.copy(p);
  }

  setTip(visible) {
    this.hasTip = visible;
    this.tipMesh.visible = visible;
    this.tipMesh.material.color.setHex(visible ? TIP_PRESENT_COLOR : EMPTY_COLOR);
  }

  pulse() {
    this.body.material.color.copy(PULSE_COLOR);
    setTimeout(() => this.body.material.color.setHex(0x9aa0a8), 250 * durationScale);
  }

  // direction: +1 to scroll "up" (aspirate -- liquid entering the tip),
  // -1 to scroll "down" (dispense -- liquid leaving it).
  flowPulse(direction) {
    const material = this.tipMesh.material;
    const restoreColor = material.color.clone();
    material.map = this.flowTexture;
    material.color.setHex(0xffffff); // let the texture's own colors show through
    material.needsUpdate = true;

    const start = performance.now();
    const duration = FLOW_PULSE_MS * durationScale;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      this.flowTexture.offset.y = direction * t * 2; // a couple of texture repeats' worth of scroll
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
  // `target.x`/`target.y` may be `null`, meaning "stay at whatever x/y this
  // leg actually starts from" -- used for the rise-to-safe-height leg,
  // which must not move horizontally. It can't just capture `this.pos.x/y`
  // at enqueue time: since ops routinely arrive faster than their ~1.6s
  // animation plays out, the queue backs up, and a snapshot taken now can
  // be stale by the time this leg actually starts (frequently still
  // showing the channel's *initial* position from before it ever moved).
  // Resolving null x/y lazily, right when the leg starts in update(),
  // sidesteps that entirely.
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
const TRAVEL_MS = 400;
const DESCEND_MS = 350;
const HOLD_MS = 150;
const RETRACT_MS = 350;

// Playback speed for review -- a dropdown in the HUD sets this to 2 (0.5x)
// or 4 (0.25x) so the animation is easier to follow, especially on replay.
// Applied uniformly to every keyframe duration below and to flowPulse.
let durationScale = 1;
const scaled = (ms) => ms * durationScale;

function animateChannelOp(entry, { onArrive } = {}) {
  const ch = channels[entry.channel];
  if (!ch) return;
  // `entry.z` (from the server) is where the *tip's point* should end up --
  // see events.py's tip_grab_point()/liquid_surface_point(). The channel
  // group's own origin is where the tip *meets the body*, above the tip's
  // apex by the tip's own rendered length -- offsetting by CHANNEL_TIP_HEIGHT
  // keeps the body clear of the target labware, so only the tip appears to
  // enter it (see docs/PLAN.md for the "pipette entering the well" bug this
  // fixes).
  const targetZ = entry.z + CHANNEL_TIP_HEIGHT;
  // x/y: null means "stay wherever this leg actually starts" -- see
  // enqueue()'s docstring for why that can't just be ch.pos.x/y here.
  ch.enqueue({ x: null, y: null, z: restZ }, scaled(RISE_MS));
  ch.enqueue({ x: entry.x, y: entry.y, z: restZ }, scaled(TRAVEL_MS));
  // onArrive fires exactly when this leg's tween completes -- see enqueue()'s
  // docstring for why that's not the same as a fixed setTimeout delay.
  ch.enqueue({ x: entry.x, y: entry.y, z: targetZ }, scaled(DESCEND_MS), onArrive);
  ch.enqueue({ x: entry.x, y: entry.y, z: targetZ }, scaled(HOLD_MS));
  ch.enqueue({ x: entry.x, y: entry.y, z: restZ }, scaled(RETRACT_MS));
}

function flashResource(resourceName) {
  const entry = resourceIndex.get(resourceName);
  if (!entry || !entry.mesh) return;
  const base = entry.mesh.material.color.clone();
  entry.mesh.material.color.copy(PULSE_COLOR);
  setTimeout(() => entry.mesh.material.color.copy(base), 250 * durationScale);
}

function handleOpEvent(msg) {
  switch (msg.op) {
    case "pick_up_tips":
      for (const entry of msg.channels) {
        animateChannelOp(entry, {
          onArrive: () => {
            channels[entry.channel]?.setTip(true);
            applyEmbeddedResourceState(entry);
          },
        });
      }
      logEvent("pick_up_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "drop_tips":
      for (const entry of msg.channels) {
        animateChannelOp(entry, {
          onArrive: () => {
            channels[entry.channel]?.setTip(false);
            applyEmbeddedResourceState(entry);
          },
        });
      }
      logEvent("drop_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "aspirate":
    case "dispense": {
      // Liquid flows "up" into the tip on aspirate, "down" out of it on
      // dispense -- see Channel.flowPulse().
      const flowDirection = msg.op === "aspirate" ? 1 : -1;
      for (const entry of msg.channels) {
        animateChannelOp(entry, {
          onArrive: () => {
            channels[entry.channel]?.pulse();
            channels[entry.channel]?.flowPulse(flowDirection);
            // Apply the real color *before* flashing -- flashResource()
            // captures whatever color is current as what to revert to, so
            // flashing first would revert back to the stale pre-dispense
            // shade instead of the one we just set.
            applyEmbeddedResourceState(entry);
            flashResource(entry.resource);
          },
        });
      }
      logEvent(
        msg.op,
        msg.channels.map((c) => `p${c.channel}:${c.resource} (${c.volume}µL)`).join(", ")
      );
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
  };
  ws.onclose = () => {
    if (ws !== currentWs) return; // ditto -- don't let an old socket's close
    // clobber state a newer, already-open connection just set
    statusEl.className = "disconnected";
    statusTextEl.textContent = "disconnected -- retrying...";
    replayBtn.disabled = true;
    setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "scene") {
      loadScene(msg.deck);
      ensureChannels(msg.num_channels ?? NUM_CHANNELS_DEFAULT);
    } else if (msg.type === "state") {
      applyState(msg.resource, msg.state);
      window.__lastStateMessages = window.__lastStateMessages || [];
      window.__lastStateMessages.push(msg);
    } else if (msg.type === "op") {
      handleOpEvent(msg);
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
    const { resourceName, resourceType, category } = hits[0].object.userData;
    tooltipEl.style.display = "block";
    tooltipEl.style.left = `${event.clientX + 14}px`;
    tooltipEl.style.top = `${event.clientY + 14}px`;
    tooltipEl.innerHTML =
      `<div class="name">${resourceName}</div>` +
      `<div class="type">${resourceType}${category ? " &middot; " + category : ""}</div>`;
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
window.__viz = { scene, camera, sceneRoot, gantryGroup, resourceIndex, controls, container, frustumHalfHeight: () => frustumHalfHeight };
