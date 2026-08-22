// Hamilton Visualizer frontend.
//
// Renders the scene graph streamed from VisualizerServer as simple boxes in
// an isometric Three.js view, and animates the 8-channel gantry from the
// "op" events emitted by VisualizerBackend. See docs/DESIGN.md.
//
// This file is the thin orchestrator: Three.js viewport/camera setup, the
// websocket wiring, and the render loop. Everything else lives in its own
// module (see each file's own header comment for what it owns):
//   coordinates.js    -- PyLabRobot <-> Three.js coordinate mapping
//   categories.js     -- category/tip color palette + legend data
//   duration-scale.js -- the HUD's playback-speed multiplier
//   log.js            -- optional leveled debug logging (off by default --
//                        see this file's own `?logLevel=` handling below)
//   scene-builder.js  -- scene graph -> Three.js object construction
//   resource-state.js -- live tip/volume/protocol-summary state updates
//   thermocycler.js   -- lid-slide + cycling-shimmer animation
//   gantry.js         -- the 8-channel arm model, the CO-RE 96 head, motion
//                        planning, and the "op" event dispatcher
//   dom.js            -- DOM handles, event log, HUD wiring
//   websocket.js       -- the websocket connection itself
//   tooltip.js        -- hover tooltips

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { container, tooltipEl, logEvent, renderRunParams, handleOpen, handleClose, handleStartStatus, handleRunStatus, handleReset } from "./dom.js";
import { loadScene as buildSceneInto, resourceIndex } from "./scene-builder.js";
import {
  gantryGroup,
  NUM_CHANNELS_DEFAULT,
  channels,
  core96Head,
  ensureChannels,
  handleOpEvent,
  setRestZ,
  setSceneRoot,
} from "./gantry.js";
import { applyState } from "./resource-state.js";
import { connect } from "./websocket.js";
import { initTooltip } from "./tooltip.js";
import { LEVELS as LOG_LEVELS, setLevel as setLogLevel, getLevel as getLogLevel } from "./log.js";

// `?logLevel=debug` (or info/warn/error/off, case-insensitive) turns on
// this project's own optional debug trace right from page load -- see
// log.js's own header comment for why this exists at all. Handy for a
// scripted/automated browser session that can't easily type into
// devtools; `window.__log.setLevel(...)` (below) covers the interactive
// case. Left OFF (log.js's own default) if the param is absent or
// unrecognized -- setLevel() itself already warns on a bad value.
const logLevelParam = new URLSearchParams(window.location.search).get("logLevel");
if (logLevelParam) setLogLevel(logLevelParam);

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
scene.add(gantryGroup);
// gantry.js needs this for a CoRe-gripper drop's reparent-back-to-the-scene
// step -- see that module's own setSceneRoot() comment for why it can't
// just own sceneRoot itself.
setSceneRoot(sceneRoot);

let frustumHalfHeight = 400; // updated once we know the deck size

// Frame the camera on the actual built geometry's bounding box, rather than
// trusting any single resource's declared size_x/y/z -- e.g. a deck
// resource's size_z can reflect the whole instrument housing, not just the
// populated work surface (see scene-builder.js's ENVELOPE_PLATFORM_THICKNESS).
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

// Rebuilds the 3D scene for a fresh "scene" websocket message -- the actual
// Three.js tree construction is scene-builder.js's loadScene(); this wrapper
// just handles the parts that module deliberately doesn't own (the camera,
// the gantry's rest height, and the event log), keeping scene-builder.js a
// clean leaf with no upward imports.
function loadScene(deckNode) {
  const deckGroup = buildSceneInto(sceneRoot, deckNode);
  fitCameraToContent(deckGroup);
  setRestZ(new THREE.Box3().setFromObject(deckGroup).max.y + 150);
  logEvent("scene", `loaded deck "${deckNode.name}" (${deckNode.children?.length ?? 0} items)`);
}

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------
connect({
  onOpen: handleOpen,
  onClose: handleClose,
  onScene: (msg) => {
    loadScene(msg.deck);
    ensureChannels(msg.num_channels ?? NUM_CHANNELS_DEFAULT);
  },
  onRunParams: renderRunParams,
  onState: (msg) => {
    applyState(msg.resource, msg.state);
    window.__lastStateMessages = window.__lastStateMessages || [];
    window.__lastStateMessages.push(msg);
  },
  onOp: handleOpEvent,
  onStartStatus: handleStartStatus,
  onRunStatus: handleRunStatus,
  onReset: handleReset,
});

// ---------------------------------------------------------------------------
// Hover tooltips
// ---------------------------------------------------------------------------
initTooltip(camera, renderer, tooltipEl);

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------
let lastTime = performance.now();
// Caps how much simulated time a single frame can ever advance queued
// animations by. Without this, any real gap between two consecutive
// requestAnimationFrame callbacks -- a backgrounded/minimized tab (browsers
// throttle or fully pause rAF for hidden tabs), a slow synchronous script
// elsewhere on the page, even just this browser's dev-tools paused on a
// breakpoint -- feeds straight into `dt` as one giant number on the next
// callback, and a single Channel.update(dt)/AnimationQueue.update(dt) call
// with a multi-second dt finishes whatever's currently animating instantly.
// With the thermocycler's ops now firing back-to-back with no
// asyncio.sleep() between them (see docs/PLAN.md's "Review round 37"), the
// *entire* close/shimmer/open story depends on the frontend actually
// spending real frames animating it -- a single stray large-dt frame right
// after Start is clicked was enough to blow through the whole queue at
// once (user-reported: "the lid opens before the thermal cycling
// animation finished... I did not see the close lid animation" -- round
// 38). Clamping means a resumed/throttled tab just takes longer in real
// time to finish whatever was still queued, rather than skipping to the
// end -- the standard fix for this whole class of rAF pitfall.
const MAX_FRAME_DT_MS = 50;
function animate(now) {
  const dt = Math.min(now - lastTime, MAX_FRAME_DT_MS);
  lastTime = now;
  for (const ch of channels) ch.update(dt);
  core96Head.update(dt);
  // A gripped or seated resource needs no per-frame update call of its
  // own any more -- it's a real THREE.js child of whatever's carrying it
  // (a channel's group while gripped, another resource's group while
  // seated on it -- see gantry.js's attachResourceTo()), so its world
  // position falls straight out of the normal renderer.render() below,
  // the same way every other nested scene-graph child already does.
  // Every resource's own AnimationQueue (currently only ever populated for
  // "thermocycler" -- see thermocycler.js) -- one uniform loop rather than
  // per-category wiring here, so a future category that wants sequenced
  // animation just starts enqueuing onto its own entry.animQueue with no
  // main.js change needed.
  for (const entry of resourceIndex.values()) entry.animQueue.update(dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

onResize();
requestAnimationFrame(animate);

// Debug hook -- inspect from the browser console with `window.__viz`.
// `channels` is a getter, not a plain reference, since ensureChannels()
// *reassigns* the module-level `channels` array (not just mutates it) --
// see docs/PLAN.md's "Review round 32" for the gantry-desync investigation
// this was added for. Importing `channels` here is already a *live*
// binding (ES modules, unlike CommonJS, re-read the exporting module's
// current value on every access) -- the getter isn't working around a
// stale import, it's just kept for continuity with every past debugging
// session that's used `window.__viz.channels`.
window.__viz = {
  scene,
  camera,
  sceneRoot,
  gantryGroup,
  resourceIndex,
  controls,
  container,
  core96Head,
  frustumHalfHeight: () => frustumHalfHeight,
  get channels() {
    return channels;
  },
};

// `window.__log.setLevel("debug")` turns on this project's own optional
// trace live, from devtools, without a page reload (see log.js's own
// header comment, and the `?logLevel=` handling above for the
// reload-at-page-load equivalent). `LEVELS` exposed too, so
// `window.__log.setLevel(window.__log.LEVELS.INFO)` works without typing
// a string.
window.__log = { setLevel: setLogLevel, getLevel: getLogLevel, LEVELS: LOG_LEVELS };
