// DOM handles + HUD wiring: the event log, the run-params row, and the
// Start/Reset/Replay/speed controls. Owns `wsConnected`/`protocolStarted`
// (only this module needs them) and exposes a set of handleXxx() functions
// shaped to plug directly into websocket.js's connect({ onOpen, onClose,
// onStartStatus, onRunStatus, onReset, onRunParams }) -- main.js wires them
// in alongside its own onScene/onState/onOp handlers, which need
// scene-builder.js/gantry.js/resource-state.js instead.

import { send } from "./websocket.js";
import { setDurationScale } from "./duration-scale.js";
import { LEGEND_ENTRIES } from "./categories.js";

export const container = document.getElementById("canvas-container");
export const tooltipEl = document.getElementById("tooltip");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
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

export function logEvent(op, detail) {
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
export function renderRunParams(fields) {
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
  send({ action: "replay" });
  logEvent("replay", "requested from server");
});

// Locks the two run-parameter inputs and Replay -- called both
// optimistically (this tab clicked Start) and authoritatively (the
// server's "start_status" broadcast, which every connected tab receives --
// see handleStartStatus() below) so a *second* browser tab that never
// clicked Start still can't edit params, or replay over a live run, for a
// run already underway. Replay's lock lifts again once "run_status" says
// the run finished (see handleRunStatus() below) -- unlike the params,
// which stay locked until a Reset actually starts a new run.
function lockForRun() {
  for (const input of runParamInputs.values()) input.disabled = true;
  replayBtn.disabled = true;
}

startBtn.addEventListener("click", () => {
  if (!wsConnected) return;
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
  send({ action: "start_protocol", params });
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
  send({ action: "reset" });
  // Optimistically disable right away -- the server's "reset" broadcast
  // (once the protocol script actually rewinds) is what re-enables
  // everything for the next run; see handleReset() below.
  resetBtn.disabled = true;
  logEvent("reset", "requested");
});

speedSelect.addEventListener("change", () => {
  setDurationScale(Number(speedSelect.value) || 1);
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

// -- websocket.js connect() handlers -----------------------------------
// Shaped to plug directly into connect({ onOpen: handleOpen, ... }) --
// see this module's own header comment.

export function handleOpen() {
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
}

export function handleClose() {
  statusEl.className = "disconnected";
  statusTextEl.textContent = "disconnected -- retrying...";
  replayBtn.disabled = true;
  wsConnected = false;
  refreshStartButton();
  resetBtn.disabled = true;
}

export function handleStartStatus(started) {
  protocolStarted = started;
  refreshStartButton();
  startBtn.classList.toggle("started", started);
  if (started) {
    lockForRun();
    logEvent("start", "protocol started");
  }
}

export function handleRunStatus(finished) {
  resetBtn.disabled = !finished;
  resetBtn.classList.toggle("visible", finished);
  if (finished) {
    replayBtn.disabled = false;
    logEvent("run_status", "finished -- reset/replay available");
  }
}

export function handleReset() {
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
