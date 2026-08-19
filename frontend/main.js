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
const TIP_PRESENT_COLOR = 0xe0b23d;
const TIP_EMPTY_COLOR = 0x555a62;
// A tip's real length (~95mm for a 1000uL Hamilton tip) is much larger than
// the ~9mm spacing between rack positions -- drawn to true scale, adjacent
// tips would overlap. These are a visually-legible compromise, not to
// scale, same tradeoff as the gantry channel glyph size below.
const TIP_PYRAMID_RADIUS = 3.2;
const TIP_PYRAMID_HEIGHT = 16;
const VOLUME_EMPTY_COLOR = new THREE.Color(0x2c4f46);
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

replayBtn.addEventListener("click", () => {
  if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return;
  currentWs.send(JSON.stringify({ action: "replay" }));
  logEvent("replay", "requested from server");
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
  const isEnvelope = isDeck || isCarrier;
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
    // instead of being embedded inside it. Carriers themselves use the
    // normal above-origin placement, since their box now rises from their
    // own base up to their payload (see sizeZ above).
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
    tipPyramid = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ color: TIP_PRESENT_COLOR }));
    const localZ = node.location?.z ?? 0;
    const rackTopInSpotLocalFrame = (parentSizeZ ?? 0) - localZ;
    tipPyramid.position.set(
      sizeX / 2,
      rackTopInSpotLocalFrame - TIP_PYRAMID_HEIGHT / 2,
      -sizeY / 2
    );
    tipPyramid.rotation.y = Math.PI / 4; // diamond-facing orientation, purely cosmetic
    tipPyramid.visible = false; // shown by the first "state" event for this spot
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

  for (const child of node.children ?? []) {
    const childObj = buildResourceObject(child, false, sizeZ);
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
function applyState(resourceName, state) {
  const entry = resourceIndex.get(resourceName);
  if (!entry) return;

  if (Object.prototype.hasOwnProperty.call(state, "tip")) {
    const hasTip = state.tip !== null && state.tip !== undefined;
    if (entry.tipPyramid) entry.tipPyramid.visible = hasTip;
  } else if (!entry.mesh) {
    return;
  } else if (Object.prototype.hasOwnProperty.call(state, "volume")) {
    const maxVolume = state.max_volume || 1;
    const frac = THREE.MathUtils.clamp((state.volume ?? 0) / maxVolume, 0, 1);
    const c = VOLUME_EMPTY_COLOR.clone().lerp(VOLUME_FULL_COLOR, frac);
    entry.mesh.material.color.copy(c);
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
    // buildResourceObject), just a little larger for readability at this
    // camera distance.
    const tipGeom = new THREE.ConeGeometry(TIP_PYRAMID_RADIUS * 1.4, TIP_PYRAMID_HEIGHT * 1.4, 4);
    this.tipMesh = new THREE.Mesh(tipGeom, new THREE.MeshLambertMaterial({ color: TIP_EMPTY_COLOR }));
    this.tipMesh.position.y = -(TIP_PYRAMID_HEIGHT * 1.4) / 2;
    this.tipMesh.rotation.y = Math.PI / 4;
    this.tipMesh.visible = false;
    this.group.add(this.tipMesh);

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
    this.tipMesh.material.color.setHex(visible ? TIP_PRESENT_COLOR : TIP_EMPTY_COLOR);
  }

  pulse() {
    this.body.material.color.copy(PULSE_COLOR);
    setTimeout(() => this.body.material.color.setHex(0x9aa0a8), 250);
  }

  enqueue(target, duration) {
    this.queue.push({ target, duration });
  }

  update(dtMs) {
    if (!this.current) {
      this.current = this.queue.shift();
      if (this.current) {
        this.current.elapsed = 0;
        this.current.from = { ...this.pos };
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
      this.current = null;
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

function animateChannelOp(entry, { onArrive } = {}) {
  const ch = channels[entry.channel];
  if (!ch) return;
  ch.enqueue({ x: ch.pos.x, y: ch.pos.y, z: restZ }, RISE_MS);
  ch.enqueue({ x: entry.x, y: entry.y, z: restZ }, TRAVEL_MS);
  ch.enqueue({ x: entry.x, y: entry.y, z: entry.z }, DESCEND_MS);
  ch.enqueue({ x: entry.x, y: entry.y, z: entry.z }, HOLD_MS);
  if (onArrive) {
    // fire once the descend leg lands; approximate by delaying to match queue position
    const delay = RISE_MS + TRAVEL_MS + DESCEND_MS;
    setTimeout(onArrive, delay);
  }
  ch.enqueue({ x: entry.x, y: entry.y, z: restZ }, RETRACT_MS);
}

function flashResource(resourceName) {
  const entry = resourceIndex.get(resourceName);
  if (!entry || !entry.mesh) return;
  const base = entry.mesh.material.color.clone();
  entry.mesh.material.color.copy(PULSE_COLOR);
  setTimeout(() => entry.mesh.material.color.copy(base), 250);
}

function handleOpEvent(msg) {
  switch (msg.op) {
    case "pick_up_tips":
      for (const entry of msg.channels) {
        animateChannelOp(entry, { onArrive: () => channels[entry.channel]?.setTip(true) });
      }
      logEvent("pick_up_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "drop_tips":
      for (const entry of msg.channels) {
        animateChannelOp(entry, { onArrive: () => channels[entry.channel]?.setTip(false) });
      }
      logEvent("drop_tips", msg.channels.map((c) => `p${c.channel}:${c.resource}`).join(", "));
      break;
    case "aspirate":
    case "dispense":
      for (const entry of msg.channels) {
        animateChannelOp(entry, {
          onArrive: () => {
            channels[entry.channel]?.pulse();
            flashResource(entry.resource);
          },
        });
      }
      logEvent(
        msg.op,
        msg.channels.map((c) => `p${c.channel}:${c.resource} (${c.volume}µL)`).join(", ")
      );
      break;
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
